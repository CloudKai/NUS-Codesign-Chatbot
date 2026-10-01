"""Course library is view-only; Chat routing stays local/prod-parity.

Lecture Notes / Readings never enter selected Chat context. Course Q&A uses
the catalog for Bedrock KB Retrieve. Personal My Sources and attachments keep
their existing selection / turn-scoped semantics.
"""

from __future__ import annotations

from typing import Any

import pytest

from backend.application import CoachApplicationService
from backend.coaching.mode_policy import (
    QA_EVIDENCE_GAP_RESPONSE,
    is_private_attachment_question,
    resolve_mode_policy,
)
from backend.coaching.workflow_navigation import (
    classify_workflow_intent,
    manual_stage_selection_target,
)
from backend.domain import CoachRequest
from backend.learning_service import LearningProgressService
from backend.agentcore_provider import AgentCoreCoachProvider
from backend.repositories import (
    SQLiteNotebookRepository,
    SQLitePhaseTransitionRepository,
)
from backend.retrieval import RetrievalQuery, RetrievalResult
from backend.source_library import (
    CHAT_ATTACHMENT_ORIGIN,
    SharedCourseItem,
    add_file_sources,
    is_locked_course_source,
    list_course_library_sources,
    list_visible_sources,
    project_shared_course_item,
    sync_lecture_notes_folder,
)
from backend.student_store import StudentStore
from backend.workflow import CoachWorkflow
from fake_agentcore_runtime import FakeAgentCoreRuntime

_RUNTIME_ARN = (
    "arn:aws:bedrock-agentcore:us-west-2:123456789012:runtime/test-harness"
)


def _coaching_payload(*, recommendation: str = "stay") -> dict[str, Any]:
    return {
        "response_text": "What assumption is carrying this preference?",
        "mode": "coaching",
        "recommendation": recommendation,
        "current_stage": "problem_identification",
        "contribution_summary": "Stage work",
        "stage_assessment": "Still framing",
        "evidence_identified": [],
        "gaps_identified": [],
        "recommendation_rationale": "Keep refining",
        "citations": [],
    }


def _qa_payload(*, text: str = "Week 2 covers JTBD [S1].") -> dict[str, Any]:
    return {
        "response_text": text,
        "mode": "qa",
        "recommendation": None,
        "current_stage": "problem_identification",
        "contribution_summary": "",
        "stage_assessment": "",
        "evidence_identified": [],
        "gaps_identified": [],
        "recommendation_rationale": "",
        "citations": [{"source_id": "ignored", "label": "S1", "title": "Week 2"}],
    }


def _provider(client: FakeAgentCoreRuntime) -> AgentCoreCoachProvider:
    return AgentCoreCoachProvider(
        runtime_arn=_RUNTIME_ARN,
        region="us-west-2",
        qualifier="DEFAULT",
        client=client,
    )


class _RecordingRetriever:
    """Record Retrieve queries and return optional empty course gap."""

    def __init__(self, *, empty_course: bool = False) -> None:
        self.queries: list[RetrievalQuery] = []
        self.empty_course = empty_course

    def retrieve(self, query: RetrievalQuery) -> RetrievalResult:
        self.queries.append(query)
        if self.empty_course:
            from backend.retrieval import with_course_evidence_gap

            return with_course_evidence_gap(
                RetrievalResult(context="", chunks=()),
                status="empty",
            )
        return RetrievalResult(context="", chunks=())


class _NoRetrieve:
    def retrieve(self, query: Any) -> Any:
        message = getattr(query, "current_message", "")
        raise AssertionError(f"unexpected retrieval for {message!r}")


def _service(
    store: StudentStore,
    client: FakeAgentCoreRuntime,
    *,
    retriever: Any | None = None,
) -> CoachApplicationService:
    notebooks = SQLiteNotebookRepository(store)
    transitions = SQLitePhaseTransitionRepository(store)
    return CoachApplicationService(
        store,
        notebooks,
        CoachWorkflow(_provider(client), transitions),
        LearningProgressService(store, notebooks, transitions),
        auto_advance_stages=False,
        retriever=retriever,
    )


def _make_notebook(tmp_path) -> tuple[StudentStore, str]:
    store = StudentStore(tmp_path / "course-library.sqlite3")
    thread_id = store.create_thread(model_id="mock", support_mode="critical-thinking")
    return store, thread_id


def _local_course_sync(tmp_path, monkeypatch, store: StudentStore, thread_id: str) -> None:
    from backend import source_library

    lecture_notes = tmp_path / "lecture_notes"
    notes = lecture_notes / "lectureNotes"
    notes.mkdir(parents=True)
    (notes / "Concept Generation.pdf").write_text(
        "Concept generation lecture body",
        encoding="utf-8",
    )
    (notes / "Week 2 JTBD.pdf").write_text("Week 2 JTBD body", encoding="utf-8")
    monkeypatch.setattr(source_library.settings, "lecture_notes_dir", lecture_notes)
    monkeypatch.setattr(source_library.settings, "course_material_sync_enabled", True)
    monkeypatch.setattr(source_library.settings, "course_materials_bucket", "")
    monkeypatch.setattr(source_library.settings, "max_lecture_notes", 50)
    monkeypatch.setattr(source_library.settings, "max_course_material_size_mb", 1)
    sync_lecture_notes_folder(store, thread_id)


def _virtual_course_item(name: str, *, group: str = "lectureNotes") -> dict[str, Any]:
    relative = f"{group}/{name}"
    return project_shared_course_item(
        SharedCourseItem(
            relative_path=relative,
            object_key=f"course/{relative}",
            filename=name,
            size=12,
            fingerprint_token=1,
            signature=f"sig-{name}",
            material_group="Lecture Notes" if group == "lectureNotes" else "Readings",
        )
    )


def test_local_course_library_visible_but_not_selected(tmp_path, monkeypatch) -> None:
    store, thread_id = _make_notebook(tmp_path)
    _local_course_sync(tmp_path, monkeypatch, store, thread_id)
    personal = add_file_sources(
        store, thread_id, [("interview.pdf", b"notes", "application/pdf")]
    )[0]

    visible = list_visible_sources(store, thread_id)
    selected = list_visible_sources(store, thread_id, selected_only=True)
    course = list_course_library_sources(store, thread_id)

    assert len(course) == 2
    assert all(is_locked_course_source(item) for item in course)
    assert all(item["selected"] is False for item in course)
    assert selected == [personal] or [item["id"] for item in selected] == [personal["id"]]
    assert not any(is_locked_course_source(item) for item in selected)
    assert {item["id"] for item in course} <= {item["id"] for item in visible}


def test_virtual_course_library_visible_but_not_selected() -> None:
    item = _virtual_course_item("Week 1 Introduction.pdf")
    assert item["selected"] is False
    assert is_locked_course_source(item) is True


@pytest.mark.parametrize(
    "message",
    (
        "i would like to work on the concept generation.",
        "I want to work on Concept Generation.",
        "Let's work on Concept Generation.",
        "I'd like to focus on Concept Generation.",
    ),
)
def test_concept_generation_work_phrases_do_not_force_course_qa(
    message: str,
) -> None:
    # Course library is never Chat-selected, so titles are not passed in.
    clean = resolve_mode_policy(message, has_selected_sources=False)
    assert clean.retrieve is False
    assert clean.expected_mode == "coaching"
    assert manual_stage_selection_target(message) is None
    assert classify_workflow_intent(message).kind == "none"


def test_what_is_concept_generation_is_not_stage_move() -> None:
    assert manual_stage_selection_target("What is Concept Generation?") is None
    assert classify_workflow_intent("What is Concept Generation?").kind == "none"


def test_move_to_concept_generation_is_workflow() -> None:
    assert manual_stage_selection_target("Can I move to Concept Generation?") == (
        "concept_generation"
    )


def test_work_on_concept_generation_with_course_catalog_skips_retrieve(
    tmp_path, monkeypatch
) -> None:
    store, thread_id = _make_notebook(tmp_path)
    _local_course_sync(tmp_path, monkeypatch, store, thread_id)
    client = FakeAgentCoreRuntime(payload=_coaching_payload())
    service = _service(store, client, retriever=_NoRetrieve())
    turn = service.submit(
        CoachRequest(
            thread_id=thread_id,
            student_message="i would like to work on the concept generation.",
            current_stage="problem_identification",
            response_detail="short",
            idempotency_key="work-concept-no-rag",
        )
    )
    assert len(client.calls) == 1
    assert turn.response_text != QA_EVIDENCE_GAP_RESPONSE
    assert turn.assessment.response_mode == "coaching"


def test_attachment_source_material_phrase_scopes_to_attachment(tmp_path) -> None:
    assert is_private_attachment_question(
        "Help me understand the source material I just added.",
        attachment_count=1,
    )
    store, thread_id = _make_notebook(tmp_path)
    # Simulate always-visible course titles without selecting them for Chat.
    course = add_file_sources(
        store,
        thread_id,
        [("Concept Generation.pdf", b"course", "application/pdf")],
        origin="lecture_notes_folder",
        selected=False,
        extra_metadata={
            "locked_source": True,
            "lecture_note_relative_path": "lectureNotes/Concept Generation.pdf",
            "course_material_group": "Lecture Notes",
        },
    )[0]
    image = add_file_sources(
        store,
        thread_id,
        [("image.png", b"fake-image", "image/png")],
        origin=CHAT_ATTACHMENT_ORIGIN,
        selected=False,
    )[0]
    client = FakeAgentCoreRuntime(payload=_qa_payload(text="The diagram shows a flow."))
    retriever = _RecordingRetriever()
    service = _service(store, client, retriever=retriever)
    request = CoachRequest(
        thread_id=thread_id,
        student_message="Help me understand the source material I just added.",
        current_stage="problem_identification",
        response_detail="short",
        attachment_source_ids=[image["id"]],
        idempotency_key="attachment-source-material",
    )
    prepared, _ = service._prepare_authoritative_turn(request)
    assert prepared.source_ids == [image["id"]]
    assert course["id"] not in prepared.source_ids
    assert prepared.allow_model_knowledge is False or prepared.image_inputs
    assert all(
        source.source_id == image["id"] for source in (prepared.retrieved_chunks or [])
    ) or prepared.retrieval_required
    # Attachment-only must not pull the course library into Retrieve.
    if retriever.queries:
        for query in retriever.queries:
            assert all(item.source_id == image["id"] for item in query.sources)
    turn = service.submit(request)
    assert turn.response_text != QA_EVIDENCE_GAP_RESPONSE
    assert "validated course excerpt" not in turn.response_text.lower()


def test_week_two_question_uses_course_catalog_retrieve(tmp_path, monkeypatch) -> None:
    store, thread_id = _make_notebook(tmp_path)
    _local_course_sync(tmp_path, monkeypatch, store, thread_id)
    client = FakeAgentCoreRuntime(payload=_qa_payload())
    retriever = _RecordingRetriever()
    service = _service(store, client, retriever=retriever)
    prepared, _ = service._prepare_authoritative_turn(
        CoachRequest(
            thread_id=thread_id,
            student_message="What does Week 2 say about JTBD?",
            current_stage="problem_identification",
            response_detail="short",
            idempotency_key="week2-jtbd-prepare",
        )
    )
    assert prepared.retrieval_required is True
    assert prepared.allow_model_knowledge is False
    assert prepared.source_ids == []
    assert prepared.expected_response_mode == "qa"
    assert len(retriever.queries) == 1
    course_ids = {
        item["id"] for item in list_course_library_sources(store, thread_id)
    }
    retrieved_ids = {item.source_id for item in retriever.queries[0].sources}
    assert course_ids & retrieved_ids


def test_local_and_virtual_routing_parity_for_work_phrase() -> None:
    message = "I would like to work on Concept Generation."
    local_policy = resolve_mode_policy(message, has_selected_sources=False)
    virtual_policy = resolve_mode_policy(
        message,
        selected_source_titles=[],
        has_selected_sources=False,
    )
    assert local_policy.retrieve is False
    assert virtual_policy.retrieve is False
    assert local_policy.expected_mode == "coaching"
    assert virtual_policy.expected_mode == "coaching"
    assert classify_workflow_intent(message).kind == "none"


def test_personal_source_selection_unchanged(tmp_path, monkeypatch) -> None:
    store, thread_id = _make_notebook(tmp_path)
    _local_course_sync(tmp_path, monkeypatch, store, thread_id)
    personal = add_file_sources(
        store, thread_id, [("mine.txt", b"personal", "text/plain")]
    )[0]
    store.set_source_selected(thread_id, personal["id"], False)
    assert list_visible_sources(store, thread_id, selected_only=True) == []
    store.set_all_sources_selected(thread_id, True)
    selected = list_visible_sources(store, thread_id, selected_only=True)
    assert [item["id"] for item in selected] == [personal["id"]]
    assert not any(is_locked_course_source(item) for item in selected)
