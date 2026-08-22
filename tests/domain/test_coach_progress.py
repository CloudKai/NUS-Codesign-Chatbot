"""Coach progress events correspond to real execution boundaries. No AWS."""

from __future__ import annotations

from typing import Any

from backend.agentcore_provider import AgentCoreCoachProvider
from backend.application import CoachApplicationService
from backend.domain import CoachRequest, StageDecision
from backend.learning_service import LearningProgressService
from backend.repositories import (
    SQLiteNotebookRepository,
    SQLitePhaseTransitionRepository,
)
from backend.retrieval import RetrievalQuery, RetrievalResult
from backend.source_library import add_text_source, list_visible_sources
from backend.retrieval import retrieval_sources_from_notebook, RetrievedChunk
from backend.student_store import StudentStore
from backend.workflow import CoachWorkflow
from fake_agentcore_runtime import FakeAgentCoreRuntime

_RUNTIME_ARN = (
    "arn:aws:bedrock-agentcore:us-west-2:123456789012:runtime/test-harness"
)


class RecordingRetriever:
    """Test retriever that records queries and returns a prepared result."""

    def __init__(self, result: RetrievalResult | None = None) -> None:
        self.calls: list[RetrievalQuery] = []
        self._result = result

    def retrieve(self, query: RetrievalQuery) -> RetrievalResult:
        self.calls.append(query)
        return self._result or RetrievalResult(context="", chunks=())


def _coaching_payload() -> dict[str, Any]:
    return {
        "mode": "coaching",
        "response_text": "What assumption is carrying this preference?",
        "recommendation": "stay",
        "recommendation_rationale": "More evidence is still needed.",
        "citations": [],
        "hmw_scaffold_ready": False,
        "needs_source_retrieval": False,
        "out_of_scope": False,
    }


def _service(
    store: StudentStore,
    client: FakeAgentCoreRuntime,
    retriever: RecordingRetriever,
) -> CoachApplicationService:
    notebooks = SQLiteNotebookRepository(store)
    transitions = SQLitePhaseTransitionRepository(store)
    return CoachApplicationService(
        store,
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
        LearningProgressService(store, notebooks, transitions),
        retriever=retriever,
    )


def test_non_rag_turn_emits_thinking_then_saving(tmp_path) -> None:
    store = StudentStore(tmp_path / "progress-non-rag.sqlite3")
    thread_id = store.create_thread(model_id="mock", support_mode="critical-thinking")
    client = FakeAgentCoreRuntime(payload=_coaching_payload())
    service = _service(store, client, RecordingRetriever())
    phases: list[str] = []
    service.submit(
        CoachRequest(
            thread_id=thread_id,
            student_message="I think option B is stronger because older users wait less.",
            current_stage="problem_identification",
            response_detail="short",
            idempotency_key="progress-non-rag",
        ),
        progress=phases.append,
    )
    assert phases == ["thinking", "saving"]
    assert len(client.calls) == 1


def test_rag_turn_emits_retrieving_before_thinking(tmp_path) -> None:
    store = StudentStore(tmp_path / "progress-rag.sqlite3")
    thread_id = store.create_thread(model_id="mock", support_mode="critical-thinking")
    add_text_source(store, thread_id, "Lecture 3", "Accessibility notes")
    selected = list_visible_sources(store, thread_id, selected_only=True)
    sources = retrieval_sources_from_notebook(selected)
    src = sources[0]
    chunk = RetrievedChunk(
        source_id=src.source_id,
        label=src.label,
        title=src.title,
        chunk_id="c1",
        text="Lecture 3 reports quantified thermal degradation of 12 percent.",
        score=0.91,
        source_index=0,
        chunk_index=0,
    )
    retriever = RecordingRetriever(
        RetrievalResult(
            context=f"--- [{src.label}] {src.title} --- {chunk.text}",
            chunks=(chunk,),
        )
    )
    client = FakeAgentCoreRuntime(payload=_coaching_payload())
    service = _service(store, client, retriever)
    phases: list[str] = []
    service.submit(
        CoachRequest(
            thread_id=thread_id,
            student_message="What does lecture 3 say about accessibility?",
            current_stage="problem_identification",
            response_detail="short",
            idempotency_key="progress-rag",
        ),
        progress=phases.append,
    )
    assert phases[0] == "retrieving"
    assert "thinking" in phases
    assert phases[-1] == "saving"
    assert retriever.calls


def test_fast_chat_persists_slim_assessment(tmp_path) -> None:
    store = StudentStore(tmp_path / "slim-assessment.sqlite3")
    thread_id = store.create_thread(model_id="mock", support_mode="critical-thinking")
    client = FakeAgentCoreRuntime(payload=_coaching_payload())
    service = _service(store, client, RecordingRetriever())
    service.submit(
        CoachRequest(
            thread_id=thread_id,
            student_message="I compared two constraints.",
            current_stage="problem_identification",
            response_detail="short",
            idempotency_key="slim-assessment",
        )
    )
    assistant = [
        message
        for message in store.get_messages(thread_id)
        if message.get("role") == "assistant"
    ][-1]
    assessment = (assistant.get("metadata") or {}).get("assessment") or {}
    assert assessment.get("response_mode") == "coaching"
    assert assessment.get("recommendation") == StageDecision.STAY.value
    assert "facione_scores" not in assessment
    assert "review_strengths" not in assessment
    assert "working_conclusion" not in assessment


def test_fast_chat_does_not_blank_existing_learning_summary(tmp_path) -> None:
    store = StudentStore(tmp_path / "keep-summary.sqlite3")
    thread_id = store.create_thread(model_id="mock", support_mode="critical-thinking")
    store.update_thread(
        thread_id,
        metadata={"learning_summary": "Prior notebook summary stays."},
    )
    client = FakeAgentCoreRuntime(payload=_coaching_payload())
    service = _service(store, client, RecordingRetriever())
    service.submit(
        CoachRequest(
            thread_id=thread_id,
            student_message="I compared two constraints.",
            current_stage="problem_identification",
            response_detail="short",
            idempotency_key="keep-summary",
        )
    )
    thread = store.get_thread(thread_id) or {}
    assert (thread.get("metadata") or {}).get("learning_summary") == (
        "Prior notebook summary stays."
    )
