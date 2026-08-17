"""Application-owned rare RAG fallback for fast chat. No AWS."""

from __future__ import annotations

from typing import Any

import pytest

from backend.agentcore_provider import AgentCoreCoachProvider
from backend.application import CoachApplicationService
from backend.domain import (
    CoachRequest,
    EducationalAssessment,
    FacioneDimensionScores,
    StageDecision,
)
from backend.learning_service import LearningProgressService
from backend.repositories import (
    SQLiteNotebookRepository,
    SQLitePhaseTransitionRepository,
)
from backend.retrieval import (
    LocalChunkRetriever,
    RetrievedChunk,
    RetrievalQuery,
    RetrievalResult,
    retrieval_sources_from_notebook,
)
from backend.source_library import add_text_source, list_visible_sources
from backend.sources.chunk_cache import reset_student_source_chunk_cache
from backend.specialists.review_orchestration import COUNTER_SETTINGS_KEY
from backend.student_store import StudentStore
from backend.workflow import CoachWorkflow
from counting_file_storage import CountingFileStorage, install_counting_storage
from fake_agentcore_runtime import FakeAgentCoreRuntime

_RUNTIME_ARN = (
    "arn:aws:bedrock-agentcore:us-west-2:123456789012:runtime/test-harness"
)
_PROJECT_MESSAGE = "I think option B is stronger."
_SOURCE_QUESTION = "What does lecture 3 say about accessibility?"


def _assessment(
    *,
    recommendation: StageDecision = StageDecision.STAY,
    contribution: str = "The student compared two design constraints.",
) -> EducationalAssessment:
    """Return a valid coaching assessment."""
    return EducationalAssessment(
        current_stage="problem_identification",
        contribution_summary=contribution,
        stage_assessment="The contribution is usable but can be developed further.",
        critical_understanding_level="Developing",
        confidence=0.7,
        recommendation=recommendation,
        recommendation_rationale="More evidence is still needed."
        if recommendation is StageDecision.STAY
        else "The stage readiness bar is met.",
        guidance_questions=["What trade-off still needs evidence?"],
        learning_summary="The student is developing the problem.",
        citations=[],
        facione_scores=FacioneDimensionScores(),
    )


def _coaching_payload(
    *,
    response_text: str = "What assumption is carrying this preference?",
    needs_source_retrieval: bool = False,
    recommendation: StageDecision = StageDecision.STAY,
    research_quote: str | None = None,
) -> dict[str, Any]:
    """Return one lightweight fast-chat coaching body."""
    payload = {
        "mode": "coaching",
        "response_text": response_text,
        "recommendation": recommendation.value,
        "recommendation_rationale": (
            "More evidence is still needed."
            if recommendation is StageDecision.STAY
            else "The stage readiness bar is met."
        ),
        "citations": [],
        "needs_source_retrieval": needs_source_retrieval,
    }
    if research_quote:
        payload["research_coding"] = {
            "coding_status": "coded",
            "dominant_clear": "logical",
            "facione_behaviors": ["analysis"],
            "evidence": [
                {
                    "quote": research_quote,
                    "rationale": "The student named a concrete preference.",
                    "confidence": 0.8,
                }
            ],
        }
    return payload


class RecordingRetriever:
    """Test retriever that records queries and returns a prepared result."""

    def __init__(
        self,
        result: RetrievalResult | None = None,
        error: BaseException | None = None,
    ) -> None:
        self.calls: list[RetrievalQuery] = []
        self._result = result
        self._error = error

    def retrieve(self, query: RetrievalQuery) -> RetrievalResult:
        """Record one retrieve and return the fixture or raise."""
        self.calls.append(query)
        if self._error is not None:
            raise self._error
        if self._result is None:
            return RetrievalResult(context="", chunks=())
        return self._result


def _result_for_source(store: StudentStore, thread_id: str) -> RetrievalResult:
    """Build a scoped retrieval result from the notebook's selected source."""
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
    return RetrievalResult(
        context=f"--- [{src.label}] {src.title} --- {chunk.text}",
        chunks=(chunk,),
    )


def _service(
    store: StudentStore,
    client: FakeAgentCoreRuntime,
    retriever: RecordingRetriever,
) -> CoachApplicationService:
    """Build the application path with injected AgentCore and retriever."""
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


def _submit(
    service: CoachApplicationService,
    thread_id: str,
    message: str,
    *,
    key: str,
) -> Any:
    """Submit one coaching turn."""
    return service.submit(
        CoachRequest(
            thread_id=thread_id,
            student_message=message,
            current_stage="problem_identification",
            response_detail="short",
            idempotency_key=key,
        )
    )


def test_gate_false_without_needs_retrieval_is_one_haiku_call(tmp_path) -> None:
    store = StudentStore(tmp_path / "fallback-one.sqlite3")
    thread_id = store.create_thread(model_id="mock", support_mode="critical-thinking")
    add_text_source(store, thread_id, "Lecture 3", "Accessibility notes")
    retriever = RecordingRetriever(result=_result_for_source(store, thread_id))
    client = FakeAgentCoreRuntime(
        payload=_coaching_payload(needs_source_retrieval=False)
    )
    service = _service(store, client, retriever)
    turn = _submit(service, thread_id, _PROJECT_MESSAGE, key="one-call")
    assert len(client.calls) == 1
    assert retriever.calls == []
    assert turn.response_text.startswith("What assumption")
    assistants = [item for item in store.get_messages(thread_id) if item["role"] == "assistant"]
    assert len(assistants) == 1


def test_gate_false_needs_retrieval_retries_once_and_persists_second(tmp_path) -> None:
    store = StudentStore(tmp_path / "fallback-two.sqlite3")
    thread_id = store.create_thread(model_id="mock", support_mode="critical-thinking")
    add_text_source(store, thread_id, "Lecture 3", "Accessibility notes")
    retriever = RecordingRetriever(result=_result_for_source(store, thread_id))
    client = FakeAgentCoreRuntime(
        payloads=[
            _coaching_payload(
                response_text="I would need the lecture excerpt first.",
                needs_source_retrieval=True,
                recommendation=StageDecision.ADVANCE,
            ),
            _coaching_payload(
                response_text="What does that 12 percent figure change about option B?",
                needs_source_retrieval=True,
            ),
        ]
    )
    service = _service(store, client, retriever)
    turn = _submit(service, thread_id, _PROJECT_MESSAGE, key="retry-once")
    assert len(client.calls) == 2
    assert len(retriever.calls) == 1
    assert turn.response_text.startswith("What does that 12 percent")
    assert turn.pending_transition is None
    assistants = [item for item in store.get_messages(thread_id) if item["role"] == "assistant"]
    assert len(assistants) == 1
    assert "12 percent" in assistants[0]["content"]
    assert "lecture excerpt first" not in assistants[0]["content"]
    users = [item for item in store.get_messages(thread_id) if item["role"] == "user"]
    assert len(users) == 1


def test_gate_true_does_not_duplicate_retrieval_or_haiku(tmp_path) -> None:
    store = StudentStore(tmp_path / "fallback-gated.sqlite3")
    thread_id = store.create_thread(model_id="mock", support_mode="critical-thinking")
    add_text_source(store, thread_id, "Lecture 3", "Accessibility notes")
    retriever = RecordingRetriever(result=_result_for_source(store, thread_id))
    client = FakeAgentCoreRuntime(
        payload=_coaching_payload(needs_source_retrieval=True)
    )
    service = _service(store, client, retriever)
    _submit(service, thread_id, _SOURCE_QUESTION, key="already-gated")
    assert len(retriever.calls) == 1
    assert len(client.calls) == 1


def test_needs_retrieval_without_selected_source_does_not_retry(tmp_path) -> None:
    store = StudentStore(tmp_path / "fallback-none.sqlite3")
    thread_id = store.create_thread(model_id="mock", support_mode="critical-thinking")
    retriever = RecordingRetriever()
    client = FakeAgentCoreRuntime(
        payload=_coaching_payload(needs_source_retrieval=True)
    )
    service = _service(store, client, retriever)
    _submit(service, thread_id, _PROJECT_MESSAGE, key="no-source")
    assert retriever.calls == []
    assert len(client.calls) == 1


def test_fallback_retrieval_failure_does_not_persist_assistant(tmp_path) -> None:
    store = StudentStore(tmp_path / "fallback-fail.sqlite3")
    thread_id = store.create_thread(model_id="mock", support_mode="critical-thinking")
    add_text_source(store, thread_id, "Lecture 3", "Accessibility notes")
    error = RuntimeError("kb-down")
    error.category = "unavailable"
    retriever = RecordingRetriever(error=error)
    client = FakeAgentCoreRuntime(
        payload=_coaching_payload(needs_source_retrieval=True)
    )
    service = _service(store, client, retriever)
    with pytest.raises(RuntimeError):
        _submit(service, thread_id, _PROJECT_MESSAGE, key="retrieve-fail")
    assert len(client.calls) == 1
    assert store.get_messages(thread_id) == []


def test_second_needs_retrieval_does_not_make_a_third_call(tmp_path) -> None:
    store = StudentStore(tmp_path / "fallback-cap.sqlite3")
    thread_id = store.create_thread(model_id="mock", support_mode="critical-thinking")
    add_text_source(store, thread_id, "Lecture 3", "Accessibility notes")
    retriever = RecordingRetriever(result=_result_for_source(store, thread_id))
    client = FakeAgentCoreRuntime(
        payloads=[
            _coaching_payload(needs_source_retrieval=True, response_text="Need sources."),
            _coaching_payload(
                needs_source_retrieval=True,
                response_text="Need sources again after retrieval.",
            ),
        ]
    )
    service = _service(store, client, retriever)
    turn = _submit(service, thread_id, _PROJECT_MESSAGE, key="cap-two")
    assert len(client.calls) == 2
    assert len(retriever.calls) == 1
    assert turn.response_text.startswith("Need sources again")


def test_idempotency_replay_does_not_rerun_fallback(tmp_path) -> None:
    store = StudentStore(tmp_path / "fallback-idem.sqlite3")
    thread_id = store.create_thread(model_id="mock", support_mode="critical-thinking")
    add_text_source(store, thread_id, "Lecture 3", "Accessibility notes")
    retriever = RecordingRetriever(result=_result_for_source(store, thread_id))
    client = FakeAgentCoreRuntime(
        payloads=[
            _coaching_payload(needs_source_retrieval=True, response_text="Need sources."),
            _coaching_payload(response_text="Grounded follow-up question?"),
        ]
    )
    service = _service(store, client, retriever)
    first = _submit(service, thread_id, _PROJECT_MESSAGE, key="same-key")
    second = _submit(service, thread_id, _PROJECT_MESSAGE, key="same-key")
    assert first.response_text == second.response_text
    assert len(client.calls) == 2
    assert len(retriever.calls) == 1


def test_research_and_counter_and_stage_use_final_result_only(tmp_path) -> None:
    store = StudentStore(tmp_path / "fallback-final.sqlite3")
    thread_id = store.create_thread(model_id="mock", support_mode="critical-thinking")
    add_text_source(store, thread_id, "Lecture 3", "Accessibility notes")
    retriever = RecordingRetriever(result=_result_for_source(store, thread_id))
    client = FakeAgentCoreRuntime(
        payloads=[
            _coaching_payload(
                needs_source_retrieval=True,
                recommendation=StageDecision.ADVANCE,
                research_quote=_PROJECT_MESSAGE,
                response_text="Provisional advance without evidence.",
            ),
            _coaching_payload(
                needs_source_retrieval=False,
                research_quote=_PROJECT_MESSAGE,
                response_text="What evidence still challenges option B?",
            ),
        ]
    )
    service = _service(store, client, retriever)
    turn = _submit(service, thread_id, _PROJECT_MESSAGE, key="final-only")
    assert turn.pending_transition is None
    assert turn.assessment.current_stage == "problem_identification"
    observations = store.list_research_observations(notebook_id=thread_id)
    assert observations == []
    metadata = store.get_thread(thread_id)["metadata"]
    assert int(metadata.get(COUNTER_SETTINGS_KEY) or 0) == 1
    assistants = [item for item in store.get_messages(thread_id) if item["role"] == "assistant"]
    assert len(assistants) == 1
    proposed = assistants[0]["metadata"].get("proposed_stage")
    assert proposed in {None, ""}


def test_gate_false_needs_retrieval_uses_one_artifact_get(
    tmp_path, monkeypatch
) -> None:
    """Hydrate once from chunks.v1.json; fallback retrieve does not re-GET extracted."""
    reset_student_source_chunk_cache()
    storage = CountingFileStorage()
    install_counting_storage(monkeypatch, storage)
    store = StudentStore(tmp_path / "fallback-ops.sqlite3")
    thread_id = store.create_thread(model_id="mock", support_mode="critical-thinking")
    add_text_source(
        store,
        thread_id,
        "Lecture 3",
        "Lecture notes on accessibility explain longer crossing times.",
    )
    inner = LocalChunkRetriever()
    retriever = RecordingRetriever()

    def _retrieve(query: RetrievalQuery) -> RetrievalResult:
        retriever.calls.append(query)
        return inner.retrieve(query)

    retriever.retrieve = _retrieve  # type: ignore[method-assign]
    client = FakeAgentCoreRuntime(
        payloads=[
            _coaching_payload(
                response_text="I would need the lecture excerpt first.",
                needs_source_retrieval=True,
                recommendation=StageDecision.ADVANCE,
                research_quote=_PROJECT_MESSAGE,
            ),
            _coaching_payload(
                response_text="What does that crossing-time figure change about option B?",
                needs_source_retrieval=True,
            ),
        ]
    )
    service = _service(store, client, retriever)
    storage.reset_counts()
    turn = _submit(service, thread_id, _PROJECT_MESSAGE, key="ops-retry")
    assert len(client.calls) == 2
    assert len(retriever.calls) == 1
    assert retriever.calls[0].sources
    assert retriever.calls[0].sources[0].chunks
    counts = storage.counts()
    assert counts.chunks_gets <= 1
    assert counts.extracted_gets == 0
    assert turn.pending_transition is None
    observations = store.list_research_observations(notebook_id=thread_id)
    assert observations == []
    assistants = [
        item for item in store.get_messages(thread_id) if item["role"] == "assistant"
    ]
    assert len(assistants) == 1
    assert "lecture excerpt first" not in assistants[0]["content"]
    reset_student_source_chunk_cache()
