"""Citation resolution must not N+1 store gets or S3 catalog listings."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

from backend.agentcore_provider import AgentCoreCoachProvider
from backend.application import CoachApplicationService
from backend.domain import CoachImageInput, CoachRequest, CoachTurn, EducationalAssessment
from backend.learning_service import LearningProgressService
from backend.persistence.factory import reset_file_storage_cache
from backend.persistence.memory_files import MemoryFileStorage
from backend.persistence.ports import ListedObject
from backend.prompts.composer import PromptComposer, prompt_context_from_request
from backend.repositories import (
    SQLiteNotebookRepository,
    SQLitePhaseTransitionRepository,
)
from backend.retrieval import RetrievedChunk, RetrievalQuery, RetrievalResult
from backend.settings import settings
from backend.source_library import virtual_course_source_id
from backend.student_store import StudentStore
from backend.workflow import CoachWorkflow
from fake_agentcore_runtime import FakeAgentCoreRuntime

_RUNTIME_ARN = (
    "arn:aws:bedrock-agentcore:us-west-2:123456789012:runtime/test-harness"
)


class CountingStudentStore:
    """Delegating store that counts ``get_source`` / ``get_thread`` reads."""

    def __init__(self, inner: StudentStore) -> None:
        self._inner = inner
        self.get_source_calls = 0
        self.get_thread_calls = 0
        self.list_sources_calls = 0

    def get_source(
        self,
        thread_id: str,
        source_id: str,
        *,
        include_extracted_text: bool = True,
    ) -> dict[str, Any] | None:
        """Count one owned-source lookup."""
        self.get_source_calls += 1
        return self._inner.get_source(
            thread_id,
            source_id,
            include_extracted_text=include_extracted_text,
        )

    def get_thread(self, thread_id: str) -> dict[str, Any] | None:
        """Count one notebook-row lookup."""
        self.get_thread_calls += 1
        return self._inner.get_thread(thread_id)

    def list_sources(
        self,
        thread_id: str,
        *,
        selected_only: bool = False,
        include_extracted_text: bool = True,
    ) -> list[dict[str, Any]]:
        """Count one notebook source listing."""
        self.list_sources_calls += 1
        return self._inner.list_sources(
            thread_id,
            selected_only=selected_only,
            include_extracted_text=include_extracted_text,
        )

    def __getattr__(self, name: str) -> Any:
        return getattr(self._inner, name)


class CountingFileStorage(MemoryFileStorage):
    """Memory file storage that counts ``list_prefix`` calls."""

    def __init__(self) -> None:
        super().__init__()
        self.list_prefix_calls = 0

    def list_prefix(self, prefix: str) -> list[ListedObject]:
        """Count one prefix listing, then delegate."""
        self.list_prefix_calls += 1
        return super().list_prefix(prefix)


class IndexedChunkRetriever:
    """Return retrieved chunks for two selected-source indexes."""

    def __init__(self, indexes: tuple[int, int] = (4, 16)) -> None:
        self.indexes = indexes
        self.calls: list[RetrievalQuery] = []

    def retrieve(self, query: RetrievalQuery) -> RetrievalResult:
        """Return chunks for the configured selected-source indexes."""
        self.calls.append(query)
        sources = list(query.sources)
        chosen = tuple(sources[index] for index in self.indexes)
        chunks = tuple(
            RetrievedChunk(
                source_id=source.source_id,
                label=source.label,
                title=source.title,
                chunk_id=f"c-{source.label}",
                text=f"{source.title} reports a quantified 12 percent finding.",
                score=0.91,
                source_index=int(source.label[1:]) - 1,
                chunk_index=0,
            )
            for source in chosen
        )
        context = " ".join(
            f"--- [{chunk.label}] {chunk.title} --- {chunk.text}" for chunk in chunks
        )
        return RetrievalResult(context=context, chunks=chunks)


def _enable_shared_catalog(monkeypatch: Any, storage: CountingFileStorage) -> None:
    """Point course-material listing at *storage* for this test."""
    monkeypatch.setattr(settings, "file_storage_provider", "memory")
    monkeypatch.setattr(settings, "course_materials_prefix", "course/")
    monkeypatch.setattr(settings, "course_materials_bucket", "course-test")
    monkeypatch.setattr(settings, "course_material_sync_enabled", True)
    monkeypatch.setattr(settings, "max_lecture_notes", 50)
    monkeypatch.setattr(settings, "max_course_material_size_mb", 1)
    reset_file_storage_cache()
    monkeypatch.setattr(
        "backend.persistence.factory.get_file_storage", lambda: storage
    )
    monkeypatch.setattr(
        "backend.persistence.factory.get_course_file_storage", lambda: storage
    )


def _seed_catalog(storage: CountingFileStorage, count: int = 20) -> list[str]:
    """Write *count* lecture-note objects and return their object keys."""
    keys: list[str] = []
    for index in range(1, count + 1):
        key = f"course/lectureNotes/week-{index:02d}.txt"
        storage.put_bytes(
            key=key,
            data=f"Lecture {index} accessibility notes.".encode("utf-8"),
            content_type="text/plain",
        )
        keys.append(key)
    return keys


def test_citation_resolution_is_bounded_and_keeps_selected_list_labels(
    tmp_path, monkeypatch
) -> None:
    """20 selected sources with 2 retrieved chunks must not list the catalog 40 times.

    ``S#`` labels stay aligned with the full selected list, not the retrieved
    subset. Before this fix, citation resolution called ``get_visible_source``
    for every selected id (20 DSQL gets + 40 S3 listings on catalog misses).
    """
    storage = CountingFileStorage()
    _enable_shared_catalog(monkeypatch, storage)
    keys = _seed_catalog(storage, 20)
    inner = StudentStore(tmp_path / "cite.sqlite3")
    store = CountingStudentStore(inner)
    thread_id = store.create_thread(model_id="mock", support_mode="critical-thinking")
    expected_ids = [virtual_course_source_id(key) for key in keys]
    expected_titles = [f"week-{index:02d}.txt" for index in range(1, 21)]
    retriever = IndexedChunkRetriever((4, 16))
    client = FakeAgentCoreRuntime(
        payload={
            "mode": "coaching",
            "response_text": (
                "Lecture notes support the wait-time claim [S5] and the "
                "crossing-time measurement [S17]."
            ),
            "recommendation": "stay",
            "recommendation_rationale": "More evidence is still needed.",
            "citations": [],
            "hmw_scaffold_ready": False,
            "needs_source_retrieval": False,
            "out_of_scope": False,
        }
    )
    notebooks = SQLiteNotebookRepository(store)  # type: ignore[arg-type]
    transitions = SQLitePhaseTransitionRepository(store)  # type: ignore[arg-type]
    service = CoachApplicationService(
        store,  # type: ignore[arg-type]
        notebooks,
        CoachWorkflow(
            AgentCoreCoachProvider(
                _RUNTIME_ARN,
                region="us-west-2",
                qualifier="DEFAULT",
                timeout_seconds=110.0,
                max_retries=0,
                client=client,
            ),
            transitions,
        ),
        LearningProgressService(store, notebooks, transitions),  # type: ignore[arg-type]
        retriever=retriever,
    )
    storage.list_prefix_calls = 0
    store.get_source_calls = 0

    turn = service.submit(
        CoachRequest(
            thread_id=thread_id,
            student_message="What does the lecture say about accessibility?",
            current_stage="problem_identification",
            response_detail="short",
            idempotency_key="cite-20",
        )
    )

    assert retriever.calls
    query_sources = list(retriever.calls[0].sources)
    assert [source.source_id for source in query_sources] == expected_ids
    assert [source.label for source in query_sources] == [
        f"S{index}" for index in range(1, 21)
    ]
    assert store.get_source_calls == 0
    assert storage.list_prefix_calls == 2
    cited = {item.label: item for item in turn.assessment.citations}
    assert set(cited) == {"S5", "S17"}
    assert cited["S5"].source_id == expected_ids[4]
    assert cited["S17"].source_id == expected_ids[16]
    assert cited["S5"].title == expected_titles[4]
    assert cited["S17"].title == expected_titles[16]
    assert cited["S5"].label == "S5"
    assert cited["S17"].label == "S17"


def test_direct_image_citation_uses_authoritative_selected_label() -> None:
    """A resolved image can be cited without becoming a fake RAG chunk."""
    service = object.__new__(CoachApplicationService)
    request = CoachRequest(
        thread_id="thread-1",
        student_message="What is this image about?",
        current_stage="problem_identification",
        response_detail="short",
        source_ids=["image-1", "text-1"],
        image_inputs=[
            CoachImageInput(
                source_id="image-1",
                mime="image/png",
                data_url="data:image/png;base64,AA==",
            )
        ],
    )
    sources = {
        "image-1": {"id": "image-1", "title": "ChatGPT Image.png", "kind": "image"},
        "text-1": {"id": "text-1", "title": "Lecture.pdf", "kind": "file"},
    }
    turn = CoachTurn(
        response_text="The image shows a crossing layout [S1].",
        assessment=EducationalAssessment(current_stage="problem_identification"),
    )

    citations = service._relevant_citations(
        request,
        turn,
        SimpleNamespace(sources_by_id=sources),
    )

    assert [(item.source_id, item.label, item.title) for item in citations] == [
        ("image-1", "S1", "ChatGPT Image.png")
    ]


def test_selected_image_without_resolved_input_is_not_citable() -> None:
    """Selection alone must not create an image Sources-used entry."""
    service = object.__new__(CoachApplicationService)
    request = CoachRequest(
        thread_id="thread-1",
        student_message="Discuss pedestrian safety.",
        current_stage="problem_identification",
        response_detail="short",
        source_ids=["image-1"],
    )
    turn = CoachTurn(
        response_text="Pedestrian safety needs attention [S1].",
        assessment=EducationalAssessment(current_stage="problem_identification"),
    )

    citations = service._relevant_citations(
        request,
        turn,
        SimpleNamespace(
            sources_by_id={
                "image-1": {
                    "id": "image-1",
                    "title": "ChatGPT Image.png",
                    "kind": "image",
                }
            }
        ),
    )

    assert citations == []


def test_image_prompt_uses_full_selected_source_labels() -> None:
    """Image metadata uses the same S# order as mixed text retrieval."""
    request = CoachRequest(
        thread_id="thread-1",
        student_message="Compare the image with the lecture.",
        current_stage="problem_identification",
        response_detail="short",
        source_ids=["image-1", "text-1"],
        image_inputs=[
            CoachImageInput(
                source_id="image-1",
                mime="image/png",
                data_url="data:image/png;base64,AA==",
            )
        ],
    )

    context = prompt_context_from_request(request)

    assert "Attached notebook images (1): S1" in context.image_note


def test_attachment_prompt_note_names_current_turn_files() -> None:
    """Current-turn uploads are named in the prompt so the model cannot deny them."""
    request = CoachRequest(
        thread_id="thread-1",
        student_message="so like this article that states my point further",
        current_stage="concept_generation",
        response_detail="short",
        attachment_source_ids=["att-1"],
        attachment_titles=["muarc157.pdf"],
    )

    context = prompt_context_from_request(request)

    assert "Current-turn private attachments (1): muarc157.pdf" in context.attachment_note
    assert "Do not claim they are missing" in context.attachment_note
    prepared = PromptComposer().compose(context)
    assert "muarc157.pdf" in prepared.runtime_instructions
    assert "muarc157.pdf" in prepared.trusted_instructions
