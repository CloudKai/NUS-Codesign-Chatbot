"""Deterministic retrieval quality, isolation, and adapter-boundary tests."""

from __future__ import annotations

import pytest

from backend.application import CoachApplicationService
from backend.chat_service import ChatOptions, StudentChatEngine
from backend.domain import (
    CitationReference,
    CoachRequest,
    ProviderAssessmentResult,
    StageDecision,
)
from backend.learning_service import LearningProgressService
from backend.mock_provider import DeterministicCoachProvider
from backend.repositories import SQLiteNotebookRepository, SQLitePhaseTransitionRepository
from backend.retrieval import (
    LocalChunkRetriever,
    RetrievalQuery,
    RetrievalResult,
    RetrievalSource,
    RetrievedChunk,
    bounded_retrieval_result,
    course_material_id_collisions,
    course_material_id_from_object_key,
    retrieval_sources_from_notebook,
)
from backend.source_library import add_file_sources, add_text_source, image_inputs_for_source_ids
from backend.student_store import StudentStore
from backend.workflow import CoachWorkflow


def _source(
    source_id: str,
    label: str,
    title: str,
    text: str,
    *,
    kind: str = "file",
) -> RetrievalSource:
    return RetrievalSource(
        source_id=source_id,
        label=label,
        title=title,
        text=text,
        kind=kind,
    )


def test_local_retriever_finds_relevant_late_document_chunk():
    padding = "General introductory material without the target topic. " * 45
    target = (
        "Thermal battery degradation accelerates above 45 degrees Celsius. "
        "The reported capacity loss was 18 percent after 500 cycles."
    )
    sources = (
        _source("battery", "S1", "Battery study", padding + target),
        _source(
            "crossing",
            "S2",
            "Road design note",
            "Pedestrian crossings need visible signals and sufficient timing. " * 20,
        ),
    )
    result = LocalChunkRetriever(
        chunk_chars=500,
        overlap_chars=80,
        max_chunks=3,
    ).retrieve(
        RetrievalQuery(
            current_message="What evidence quantifies thermal battery degradation?",
            current_stage="concept_generation",
            sources=sources,
        )
    )

    assert result.chunks
    assert result.chunks[0].source_id == "battery"
    assert "18 percent after 500 cycles" in result.context
    assert "Road design note" not in result.context
    assert len(result.context) < len(padding + target)


def test_local_retriever_preserves_stable_labels_and_source_diversity():
    sources = (
        _source(
            "survey",
            "S1",
            "Survey",
            "Older adults reported insufficient crossing time in the survey.",
        ),
        _source(
            "audit",
            "S2",
            "Street audit",
            "The crossing audit measured insufficient signal timing for older adults.",
        ),
    )
    result = LocalChunkRetriever(max_chunks=4).retrieve(
        RetrievalQuery(
            current_message="What evidence concerns crossing time for older adults?",
            current_stage="concept_generation",
            sources=sources,
        )
    )

    assert {chunk.source_id for chunk in result.chunks} == {"survey", "audit"}
    assert {chunk.label for chunk in result.chunks} == {"S1", "S2"}
    assert "[S1] Survey" in result.context
    assert "[S2] Street audit" in result.context


def test_local_retriever_generic_query_uses_bounded_representative_fallback():
    sources = tuple(
        _source(
            f"source-{index}",
            f"S{index}",
            f"Document {index}",
            (f"Distinct document {index} content. " * 100),
        )
        for index in range(1, 5)
    )
    result = LocalChunkRetriever(
        chunk_chars=500,
        overlap_chars=50,
        max_chunks=2,
        max_chunks_per_source=1,
        max_context_chars=1_500,
    ).retrieve(
        RetrievalQuery(
            current_message="What do these say?",
            current_stage="problem_identification",
            sources=sources,
        )
    )

    assert len(result.chunks) == 2
    assert len({chunk.source_id for chunk in result.chunks}) == 2
    assert len(result.context) <= 1_500


def test_retrieval_source_normalization_keeps_course_group_and_image_label():
    sources = retrieval_sources_from_notebook(
        [
            {
                "id": "lecture",
                "title": "Week 2",
                "kind": "file",
                "extractedText": "Evaluation methods",
                "object_key": "course/lectureNotes/week2.pdf",
                "metadata": {"course_material_group": "Lecture Notes"},
            },
            {
                "id": "diagram",
                "title": "Model.png",
                "kind": "image",
                "extractedText": "",
                "metadata": {},
            },
        ]
    )

    assert sources[0].label == "S1"
    assert sources[0].group == "Lecture Notes"
    assert sources[0].object_key == "course/lectureNotes/week2.pdf"
    assert sources[1].label == "S2"
    assert "Image source" in sources[1].text


def test_application_retrieval_is_selected_notebook_scoped_and_audited(tmp_path):
    store = StudentStore(tmp_path / "retrieval-scope.sqlite3")
    notebook = store.create_thread(model_id="mock", support_mode="critical-thinking")
    other_notebook = store.create_thread(
        model_id="mock", support_mode="critical-thinking"
    )
    selected = add_text_source(
        store,
        notebook,
        "Selected battery study",
        "Thermal battery evidence reports 18 percent capacity loss.",
    )
    hidden = add_text_source(
        store,
        notebook,
        "Deselected secret",
        "SECRET_DESELECTED_CONTENT about thermal batteries.",
    )
    store.set_source_selected(notebook, hidden["id"], False)
    add_text_source(
        store,
        other_notebook,
        "Other notebook secret",
        "SECRET_OTHER_NOTEBOOK_CONTENT about thermal batteries.",
    )
    notebooks = SQLiteNotebookRepository(store)
    transitions = SQLitePhaseTransitionRepository(store)
    provider = DeterministicCoachProvider(StageDecision.STAY)
    service = CoachApplicationService(
        store,
        notebooks,
        CoachWorkflow(provider, transitions),
        LearningProgressService(store, notebooks, transitions),
    )

    turn = service.submit(
        CoachRequest(
            thread_id=notebook,
            student_message="What thermal battery evidence is available?",
            current_stage="problem_identification",
            response_detail="short",
        )
    )

    assert provider.last_prepared_prompt is not None
    prompt = provider.last_prepared_prompt.composed_text
    assert "18 percent capacity loss" in prompt
    assert "SECRET_DESELECTED_CONTENT" not in prompt
    assert "SECRET_OTHER_NOTEBOOK_CONTENT" not in prompt
    assistant = store.get_messages(notebook)[-1]
    retrieval_refs = assistant["metadata"]["retrieval_refs"]
    assert retrieval_refs[0]["source_id"] == selected["id"]
    assert retrieval_refs[0]["label"] == "S1"
    assert retrieval_refs[0]["chunk_id"].startswith("S1-C")
    assert (
        "Thermal battery evidence reports 18 percent capacity loss."
        in turn.response_text
    )
    assert "[S1]" in turn.response_text
    assert turn.assessment.citations[0].source_id == selected["id"]
    assert assistant["metadata"]["source_refs"] == [
        {
            "id": selected["id"],
            "label": "S1",
            "title": "Selected battery study",
        }
    ]


def test_citation_preview_uses_retrieved_excerpt_not_document_beginning(
    tmp_path,
):
    store = StudentStore(tmp_path / "retrieved-citation.sqlite3")
    notebook = store.create_thread(model_id="mock", support_mode="critical-thinking")
    add_text_source(
        store,
        notebook,
        "Battery report",
        ("Unrelated background material. " * 160)
        + "Thermal degradation caused exactly 18 percent capacity loss after 500 cycles.",
    )
    notebooks = SQLiteNotebookRepository(store)
    transitions = SQLitePhaseTransitionRepository(store)
    service = CoachApplicationService(
        store,
        notebooks,
        CoachWorkflow(DeterministicCoachProvider(), transitions),
        LearningProgressService(store, notebooks, transitions),
    )

    turn = service.submit(
        CoachRequest(
            thread_id=notebook,
            student_message="What quantified thermal degradation was reported?",
            current_stage="problem_identification",
            response_detail="short",
        )
    )

    assert len(turn.assessment.citations) == 1
    assert "18 percent capacity loss" in turn.assessment.citations[0].excerpt
    assert "18 percent capacity loss" in turn.response_text
    assert "[S1]" in turn.response_text


def test_application_rejects_out_of_scope_retriever_result(tmp_path):
    class _BadRetriever:
        def retrieve(self, query: RetrievalQuery) -> RetrievalResult:
            del query
            return RetrievalResult(
                context="--- [S9] forged ---\nforged",
                chunks=(
                    RetrievedChunk(
                        source_id="another-notebook-source",
                        label="S9",
                        title="Forged",
                        chunk_id="S9-C1",
                        text="forged",
                        score=1.0,
                        source_index=9,
                        chunk_index=1,
                    ),
                ),
        )

    store = StudentStore(tmp_path / "bad-retriever.sqlite3")
    notebook = store.create_thread(model_id="mock", support_mode="critical-thinking")
    add_text_source(store, notebook, "Owned", "Owned selected source content")
    notebooks = SQLiteNotebookRepository(store)
    transitions = SQLitePhaseTransitionRepository(store)
    service = CoachApplicationService(
        store,
        notebooks,
        CoachWorkflow(DeterministicCoachProvider(), transitions),
        LearningProgressService(store, notebooks, transitions),
        retriever=_BadRetriever(),
    )

    with pytest.raises(ValueError, match="outside the selected notebook scope"):
        service.submit(
            CoachRequest(
                thread_id=notebook,
                student_message="Use the source.",
                current_stage="problem_identification",
                response_detail="short",
            )
        )


def test_application_rebuilds_context_from_adapter_chunks(tmp_path):
    class _OpaqueContextRetriever:
        def __init__(self) -> None:
            self.source_id = ""

        def retrieve(self, query: RetrievalQuery) -> RetrievalResult:
            label = query.sources[0].label
            return RetrievalResult(
                context="SECRET_OPAQUE_ADAPTER_TEXT",
                chunks=(
                    RetrievedChunk(
                        source_id=self.source_id,
                        label=label,
                        title="Owned source",
                        chunk_id=f"{label}-C1",
                        text="Canonical selected chunk text.",
                        score=2.0,
                        source_index=1,
                        chunk_index=1,
                    ),
                ),
            )

    store = StudentStore(tmp_path / "opaque-context.sqlite3")
    notebook = store.create_thread(model_id="mock", support_mode="critical-thinking")
    source = add_text_source(store, notebook, "Owned source", "Stored source text")
    retriever = _OpaqueContextRetriever()
    retriever.source_id = source["id"]
    notebooks = SQLiteNotebookRepository(store)
    transitions = SQLitePhaseTransitionRepository(store)
    provider = DeterministicCoachProvider()
    service = CoachApplicationService(
        store,
        notebooks,
        CoachWorkflow(provider, transitions),
        LearningProgressService(store, notebooks, transitions),
        retriever=retriever,
    )

    service.submit(
        CoachRequest(
            thread_id=notebook,
            student_message="Use the selected evidence.",
            current_stage="problem_identification",
            response_detail="short",
        )
    )

    assert provider.last_prepared_prompt is not None
    prompt = provider.last_prepared_prompt.composed_text
    assert "Canonical selected chunk text" in prompt
    assert "SECRET_OPAQUE_ADAPTER_TEXT" not in prompt


def test_legacy_development_fallback_uses_same_local_retriever(tmp_path):
    store = StudentStore(tmp_path / "legacy-retrieval.sqlite3")
    notebook = store.create_thread(model_id="mock", support_mode="critical-thinking")
    add_text_source(
        store,
        notebook,
        "Battery evidence",
        ("Background. " * 220) + "Thermal capacity loss reached 18 percent.",
    )
    add_text_source(
        store,
        notebook,
        "Unrelated crossing note",
        "Signal timing for pedestrians. " * 30,
    )

    stream = StudentChatEngine(store).submit(
        notebook,
        "What thermal capacity loss was reported?",
        ChatOptions(model_id="gpt-5.4-mini"),
    )

    assert "18 percent" in stream.retrieval_context
    assert "Unrelated crossing note" not in stream.retrieval_context
    user = store.get_messages(notebook)[-1]
    assert user["metadata"]["retrieval_refs"][0]["label"] == "S1"


def test_course_material_id_is_stable_from_object_key():
    assert (
        course_material_id_from_object_key("course/lectureNotes/week_02_jtbd.pdf")
        == "lecture_week_02_jtbd"
    )
    assert (
        course_material_id_from_object_key("course/readings/pixar.pdf")
        == "reading_pixar"
    )
    assert (
        course_material_id_from_object_key("course/readings/week1.pdf")
        == "reading_week1"
    )
    assert (
        course_material_id_from_object_key("course/readings/archive/week1.pdf")
        == "reading_archive_week1"
    )
    assert (
        course_material_id_from_object_key("course/readings/myweek1.pdf")
        == "reading_myweek1"
    )
    collisions = course_material_id_collisions(
        [
            "course/readings/week 01.pdf",
            "course/readings/week_01.pdf",
            "course/Readings/WEEK_01.PDF",
            "course/lectureNotes/week1.pdf",
        ]
    )
    assert "reading_week_01" in collisions
    assert "lecture_week1" not in collisions


def test_bounded_retrieval_skips_near_duplicate_chunks_from_the_same_source():
    duplicate = "Older pedestrians need a longer crossing interval at night."
    result = bounded_retrieval_result(
        [
            RetrievedChunk(
                source_id="src-1",
                label="S1",
                title="Lecture",
                chunk_id="S1-KB1",
                text=duplicate,
                score=0.9,
                source_index=1,
                chunk_index=1,
            ),
            RetrievedChunk(
                source_id="src-1",
                label="S1",
                title="Lecture",
                chunk_id="S1-KB2",
                text=duplicate,
                score=0.8,
                source_index=1,
                chunk_index=2,
            ),
            RetrievedChunk(
                source_id="src-1",
                label="S1",
                title="Lecture",
                chunk_id="S1-KB3",
                text="A different excerpt about signal timing and kerb height.",
                score=0.7,
                source_index=1,
                chunk_index=3,
            ),
        ]
    )
    assert [chunk.chunk_id for chunk in result.chunks] == ["S1-KB1", "S1-KB3"]
    assert result.context.count(duplicate) == 1


def test_forged_citation_is_not_persisted(tmp_path):
    store = StudentStore(tmp_path / "forged-citation.sqlite3")
    notebook = store.create_thread(model_id="mock", support_mode="critical-thinking")
    selected = add_text_source(
        store,
        notebook,
        "Selected battery study",
        "Thermal battery evidence reports 18 percent capacity loss.",
    )

    class ForgedCitationProvider:
        provider_id = "mock"

        def model_id_for(self, request: CoachRequest) -> str:
            del request
            return "deterministic-v1"

        def assess(self, request: CoachRequest) -> ProviderAssessmentResult:
            inner = DeterministicCoachProvider(StageDecision.STAY)
            result = inner.assess(request)
            forged = CitationReference(
                source_id="forged-source",
                label="S99",
                title="Invented source",
                excerpt="This citation was not retrieved.",
            )
            assessment = result.assessment.model_copy(
                update={"citations": [*result.assessment.citations, forged]}
            )
            return ProviderAssessmentResult(
                response_text=f"{result.response_text} See [S99].",
                assessment=assessment,
                research_coding=result.research_coding,
            )

    notebooks = SQLiteNotebookRepository(store)
    transitions = SQLitePhaseTransitionRepository(store)
    service = CoachApplicationService(
        store,
        notebooks,
        CoachWorkflow(ForgedCitationProvider(), transitions),
        LearningProgressService(store, notebooks, transitions),
    )
    turn = service.submit(
        CoachRequest(
            thread_id=notebook,
            student_message="What thermal battery evidence is available?",
            current_stage="problem_identification",
            response_detail="short",
        )
    )
    assistant = store.get_messages(notebook)[-1]
    source_ids = {item["id"] for item in assistant["metadata"]["source_refs"]}
    labels = {item["label"] for item in assistant["metadata"]["source_refs"]}
    assert selected["id"] in source_ids or "[S1]" in turn.response_text
    assert "S99" not in labels
    assert "forged-source" not in source_ids
    assert all(citation.label != "S99" for citation in turn.assessment.citations)


def test_cross_user_source_id_is_rejected_before_retrieval(tmp_path):
    owner = StudentStore(tmp_path / "owner.sqlite3", identifier="student-a")
    owner_notebook = owner.create_thread(
        model_id="mock", support_mode="critical-thinking"
    )
    owner_source = add_text_source(
        owner, owner_notebook, "Owner notes", "Owner-only crossing evidence."
    )
    stranger = StudentStore(tmp_path / "stranger.sqlite3", identifier="student-b")
    stranger_notebook = stranger.create_thread(
        model_id="mock", support_mode="critical-thinking"
    )
    add_text_source(
        stranger, stranger_notebook, "Stranger notes", "SECRET_STRANGER_SOURCE"
    )
    assert stranger.get_source(owner_notebook, owner_source["id"]) is None
    notebooks = SQLiteNotebookRepository(stranger)
    transitions = SQLitePhaseTransitionRepository(stranger)
    service = CoachApplicationService(
        stranger,
        notebooks,
        CoachWorkflow(DeterministicCoachProvider(StageDecision.STAY), transitions),
        LearningProgressService(stranger, notebooks, transitions),
    )
    with pytest.raises(ValueError, match="unknown"):
        service.submit(
            CoachRequest(
                thread_id=stranger_notebook,
                student_message="Use the other student's source.",
                current_stage="problem_identification",
                response_detail="short",
                source_ids=[owner_source["id"]],
            )
        )
    with pytest.raises(ValueError, match="Notebook not found"):
        service.submit(
            CoachRequest(
                thread_id=owner_notebook,
                student_message="Open someone else's notebook.",
                current_stage="problem_identification",
                response_detail="short",
            )
        )


def test_foreign_image_is_not_supplied_as_coach_input(tmp_path, monkeypatch):
    from backend import source_library

    monkeypatch.setattr(source_library.settings, "files_dir", tmp_path / "files")
    png = (
        b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01"
        b"\x08\x02\x00\x00\x00\x90wS\xde\x00\x00\x00\x0cIDATx\x9cc\xf8\x0f"
        b"\x00\x00\x01\x01\x00\x05\x18\xd8N\x00\x00\x00\x00IEND\xaeB`\x82"
    )
    owner = StudentStore(tmp_path / "img-owner.sqlite3", identifier="student-a")
    owner_notebook = owner.create_thread(
        model_id="mock", support_mode="critical-thinking"
    )
    created = add_file_sources(
        owner,
        owner_notebook,
        [("diagram.png", png, "image/png")],
    )
    stranger = StudentStore(tmp_path / "img-stranger.sqlite3", identifier="student-b")
    stranger_notebook = stranger.create_thread(
        model_id="mock", support_mode="critical-thinking"
    )
    images = image_inputs_for_source_ids(
        stranger,
        stranger_notebook,
        [created[0]["id"]],
    )
    assert images == []
    owned = image_inputs_for_source_ids(
        owner,
        owner_notebook,
        [created[0]["id"]],
    )
    assert len(owned) == 1
    assert owned[0]["source_id"] == created[0]["id"]


def test_research_coding_does_not_advance_stage(tmp_path):
    store = StudentStore(tmp_path / "research-independence.sqlite3")
    notebook = store.create_thread(model_id="mock", support_mode="critical-thinking")
    notebooks = SQLiteNotebookRepository(store)
    transitions = SQLitePhaseTransitionRepository(store)
    service = CoachApplicationService(
        store,
        notebooks,
        CoachWorkflow(DeterministicCoachProvider(StageDecision.STAY), transitions),
        LearningProgressService(store, notebooks, transitions),
        auto_advance_stages=True,
    )
    turn = service.submit(
        CoachRequest(
            thread_id=notebook,
            student_message="I compared privacy and fairness before choosing the design.",
            current_stage="problem_identification",
            response_detail="short",
        )
    )
    assert turn.pending_transition is None
    progress = store.get_thread(notebook)["metadata"]["learning_journey"]
    assert progress["current_stage"] == "problem_identification"
    assert turn.assessment.recommendation is StageDecision.STAY
