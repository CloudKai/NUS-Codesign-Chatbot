"""Deterministic retrieval quality, isolation, and adapter-boundary tests."""

from __future__ import annotations

import pytest

from backend.application import CoachApplicationService
from backend.chat_service import ChatOptions, StudentChatEngine
from backend.domain import CoachRequest, StageDecision
from backend.learning_service import LearningProgressService
from backend.mock_provider import DeterministicCoachProvider
from backend.repositories import SQLiteNotebookRepository, SQLitePhaseTransitionRepository
from backend.retrieval import (
    LocalChunkRetriever,
    RetrievalQuery,
    RetrievalResult,
    RetrievalSource,
    RetrievedChunk,
    retrieval_sources_from_notebook,
)
from backend.source_library import add_text_source
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
            current_stage="evidence",
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
            current_stage="evidence",
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
            current_stage="focus",
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
            current_stage="focus",
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
            current_stage="focus",
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
                current_stage="focus",
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
            current_stage="focus",
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
