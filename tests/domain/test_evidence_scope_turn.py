"""First-pass evidence scope through ``_prepare_authoritative_turn``. No AWS.

Each scenario drives the real authoritative preparation step with a stub
retriever and a stub course-intent classifier, then records what the turn
decided: the ordered ``record_field`` names (timing values masked), the request
stamps the provider reads, and which sources were searched. The expected values
were captured from the code before the scope decision moved to
``backend/coaching/evidence_scope.py``, so a refactor that changes a decision,
a stamp or the telemetry order fails here. Scenarios cover lecture help,
Thinking Path commands, attachment-only questions, missing image Q&A,
``force_retrieval``, the course catalog, the upload retrieval policy and the
Laya hook, none of which has a direct turn-level test elsewhere.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from backend.application import CoachApplicationService
from backend.coaching import execution
from backend.domain import CoachRequest
from backend.learning_service import LearningProgressService
from backend.mock_provider import DeterministicCoachProvider
from backend.repositories import (
    SQLiteNotebookRepository,
    SQLitePhaseTransitionRepository,
)
from backend.retrieval import RetrievalQuery, RetrievalResult, RetrievedChunk
from backend.settings import settings
from backend.source_library import (
    CHAT_ATTACHMENT_ORIGIN,
    add_file_sources,
    add_text_source,
    sync_lecture_notes_folder,
)
from backend.student_store import StudentStore
from backend.turn_perf import begin_coach_turn_perf, reset_coach_turn_perf
from backend.workflow import CoachWorkflow

_NO_CUE_COURSE_QUESTION = "what questions do we ask in the JTBD interview"
_UPLOAD_QUESTION = "what does the survey say about peak hours"
_COURSE_CUE_QUESTION = "explain week 2 JTBD from the lecture notes"
_STATUS_THEN_GUIDANCE = "what stage am I on and what should I do next?"


class _Retriever:
    """Return one chunk for the first source of each query; record titles."""

    def __init__(self) -> None:
        self.searched: list[list[str]] = []

    def retrieve(self, query: RetrievalQuery) -> RetrievalResult:
        self.searched.append(sorted(source.title for source in query.sources))
        source = query.sources[0]
        chunk = RetrievedChunk(
            source_id=source.source_id,
            label=source.label,
            title=source.title,
            chunk_id="c1",
            text="An excerpt.",
            score=0.9,
            source_index=0,
            chunk_index=0,
        )
        return RetrievalResult(context=f"[{source.label}] An excerpt.", chunks=(chunk,))


class _Classifier:
    """Fixed Laya-style score; record whether it was asked."""

    def __init__(self, score: float | None) -> None:
        self.score_value = score
        self.calls = 0

    def score(self, message: str, history: Any, titles: Any) -> float | None:
        self.calls += 1
        return self.score_value


# History and source loads run on two threads, so their relative order varies.
_THREAD_RACED = frozenset({"history_load_ms", "source_load_ms"})


def _scenario(message: str, **options: Any) -> dict[str, Any]:
    return {"message": message, **options}


_GOLDEN = json.loads(
    Path(__file__).with_name("evidence_scope_turn_golden.json").read_text(encoding="utf-8")
)

SCENARIOS: dict[str, dict[str, Any]] = {
    "plain_course_question": _scenario("what is dot voting"),
    "no_cue_no_classifier": _scenario(_NO_CUE_COURSE_QUESTION),
    "upload_question_policy_off": _scenario(_UPLOAD_QUESTION, upload=True),
    "upload_question_policy_on": _scenario(_UPLOAD_QUESTION, upload=True, policy=True),
    "chit_chat_policy_on": _scenario("thanks", upload=True, policy=True),
    "stage_status": _scenario("what stage am I on?", upload=True, policy=True),
    "stage_progression": _scenario("let's go to concept generation", upload=True),
    "workflow_meta_guidance": _scenario("what should I do next", upload=True),
    "status_then_guidance": _scenario(_STATUS_THEN_GUIDANCE, upload=True),
    "course_cue_question": _scenario(_COURSE_CUE_QUESTION),
    "course_cue_question_with_upload": _scenario(_COURSE_CUE_QUESTION, upload=True, policy=True),
    "course_cue_question_with_laya": _scenario(_COURSE_CUE_QUESTION, classifier=0.95),
    "attachment_only_question": _scenario(
        "summarise the uploaded file", upload=True, attachment=True
    ),
    "attachment_course_comparison": _scenario(
        "compare this attachment with Lecture 4", upload=True, attachment=True
    ),
    "attachment_with_stage_status": _scenario(
        "what stage am I on?", upload=True, attachment=True
    ),
    "attachment_with_progression": _scenario(
        "let's go to concept generation", attachment=True
    ),
    "lecture_help": _scenario("hello", interaction="lecture_help", upload=True),
    "lecture_help_with_status_words": _scenario(
        "what stage am I on?", interaction="lecture_help", upload=True
    ),
    "project_coaching_course_question": _scenario(
        _COURSE_CUE_QUESTION, interaction="project_coaching", upload=True
    ),
    "lecture_help_course_question": _scenario(
        _COURSE_CUE_QUESTION, interaction="lecture_help"
    ),
    "project_coaching_status": _scenario(
        "what stage am I on?", interaction="project_coaching"
    ),
    "force_retrieval_with_upload": _scenario("thanks", upload=True, force=True),
    "force_retrieval_no_sources": _scenario("thanks", force=True),
    "force_retrieval_status": _scenario("what stage am I on?", upload=True, force=True),
    "force_retrieval_course_cue": _scenario(_COURSE_CUE_QUESTION, upload=True, force=True),
    "force_retrieval_attachment": _scenario(
        "summarise the uploaded file", attachment=True, upload=True, force=True
    ),
    "missing_image_question": _scenario(
        "What is this image about?", image="missing"
    ),
    "missing_image_not_a_request": _scenario("nice", image="missing"),
    "missing_image_with_upload": _scenario(
        "What is this image about?", image="missing", upload=True
    ),
    "missing_image_attachment_only": _scenario(
        "What is this image about?", image="missing", attachment=True
    ),
    "resolved_image_question": _scenario("What is this image about?", image="resolved"),
    "laya_promotes": _scenario(_NO_CUE_COURSE_QUESTION, classifier=0.95),
    "laya_below_cutoff": _scenario(_NO_CUE_COURSE_QUESTION, classifier=0.2),
    "laya_no_score": _scenario(_NO_CUE_COURSE_QUESTION, classifier=None),
    "laya_skipped_for_chit_chat": _scenario("thanks", classifier=0.95),
    "laya_skipped_with_selected_source": _scenario(
        _NO_CUE_COURSE_QUESTION, classifier=0.95, upload=True
    ),
    "laya_skipped_with_interaction_intent": _scenario(
        _NO_CUE_COURSE_QUESTION, classifier=0.95, interaction="project_coaching"
    ),
    "laya_promotes_then_upload_policy": _scenario(
        _NO_CUE_COURSE_QUESTION, classifier=0.95, upload=True, policy=True
    ),
}


def _service(store: StudentStore, retriever: Any, classifier: Any) -> CoachApplicationService:
    notebooks = SQLiteNotebookRepository(store)
    transitions = SQLitePhaseTransitionRepository(store)
    return CoachApplicationService(
        store,
        notebooks,
        CoachWorkflow(DeterministicCoachProvider(), transitions),
        LearningProgressService(store, notebooks, transitions),
        auto_advance_stages=False,
        retriever=retriever,
        course_intent_classifier=classifier,
    )


def _prepare(tmp_path: Any, monkeypatch: pytest.MonkeyPatch, spec: dict[str, Any]) -> dict[str, Any]:
    from backend import source_library

    store = StudentStore(tmp_path / "scope-turn.sqlite3")
    thread_id = store.create_thread(model_id="mock", support_mode="critical-thinking")
    notes = tmp_path / "lecture_notes" / "lectureNotes"
    notes.mkdir(parents=True)
    (notes / "Week 2 JTBD.pdf").write_text("Week 2 JTBD body", encoding="utf-8")
    monkeypatch.setattr(source_library.settings, "lecture_notes_dir", tmp_path / "lecture_notes")
    monkeypatch.setattr(source_library.settings, "course_material_sync_enabled", True)
    monkeypatch.setattr(source_library.settings, "course_materials_bucket", "")
    monkeypatch.setattr(source_library.settings, "max_lecture_notes", 50)
    monkeypatch.setattr(source_library.settings, "max_course_material_size_mb", 1)
    sync_lecture_notes_folder(store, thread_id)
    monkeypatch.setattr(settings, "fast_chat_upload_retrieval_enabled", bool(spec.get("policy")))
    monkeypatch.setattr(settings, "fast_chat_needs_sources_enabled", True)
    monkeypatch.setattr(settings, "local_course_intent_threshold", 0.8)
    monkeypatch.setattr(settings, "local_course_intent_first_turn_threshold", 0.8)

    if spec.get("upload"):
        add_text_source(store, thread_id, "Survey results", "Peak hours are 12pm to 1pm.")
    if spec.get("image"):
        add_file_sources(store, thread_id, [("Sketch.png", b"not-a-real-image", "image/png")])
    attachment_ids: list[str] = []
    if spec.get("attachment"):
        attached = add_file_sources(
            store,
            thread_id,
            [("Persona.txt", b"The persona is a commuter.", "text/plain")],
            origin=CHAT_ATTACHMENT_ORIGIN,
            selected=False,
        )
        attachment_ids = [attached[0]["id"]]
    if spec.get("image") == "missing":
        monkeypatch.setattr(execution, "image_inputs_for_sources", lambda sources: [])

    # ``record_field`` drops names outside the perf allowlist (the status,
    # progression, workflow and attachment cues), so spy on the calls too: the
    # call order is what a refactor must keep.
    calls: list[list[Any]] = []
    real_record_field = execution.record_field

    def spy(name: str, value: Any) -> None:
        if name not in _THREAD_RACED:
                calls.append([name, "<ms>" if name.endswith("_ms") else value])
        real_record_field(name, value)

    monkeypatch.setattr(execution, "record_field", spy)
    retriever = _Retriever()
    classifier = _Classifier(spec["classifier"]) if "classifier" in spec else None
    service = _service(store, retriever, classifier)
    request = CoachRequest(
        thread_id=thread_id,
        student_message=spec["message"],
        current_stage="problem_identification",
        response_detail="short",
        attachment_source_ids=attachment_ids,
        interaction_intent=spec.get("interaction"),
        idempotency_key="scope-turn",
    )
    perf = begin_coach_turn_perf()
    try:
        prepared, _snapshot = service._prepare_authoritative_turn(
            request, force_retrieval=bool(spec.get("force"))
        )
        fields = [
            [name, "<ms>" if name.endswith("_ms") else value]
            for name, value in perf.fields.items()
            if name not in _THREAD_RACED
        ]
    finally:
        reset_coach_turn_perf()
    titles = {
        source["id"]: source["title"] for source in store.list_sources(thread_id)
    }
    titles.update({attachment_id: "Persona.txt" for attachment_id in attachment_ids})
    return {
        "record_field_calls": calls,
        "fields": fields,
        "retrieval_required": prepared.retrieval_required,
        "source_need_check": prepared.source_need_check,
        "expected_response_mode": prepared.expected_response_mode,
        "mode_policy_intent": prepared.mode_policy_intent,
        "allow_model_knowledge": prepared.allow_model_knowledge,
        "source_ids": sorted(titles.get(source_id, source_id) for source_id in prepared.source_ids),
        "attachment_titles": list(prepared.attachment_titles),
        "image_inputs": len(prepared.image_inputs),
        "retrieved_chunks": len(prepared.retrieved_chunks),
        "searched": retriever.searched,
        "classifier_calls": classifier.calls if classifier else None,
    }


@pytest.mark.parametrize("name", sorted(SCENARIOS))
def test_turn_scope_matches_the_recorded_decision(
    name: str, tmp_path: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    actual = _prepare(tmp_path, monkeypatch, SCENARIOS[name])
    if name == "lecture_help":
        # The bare greeting still follows Q&A policy but has no evidence request.
        assert actual["expected_response_mode"] == "qa"
        assert not actual["retrieval_required"]
        assert not actual["searched"]
        return
    assert actual == _GOLDEN[name]
