"""Optional AgentCore runtimeSessionId affinity. Deterministic mocks only."""

from __future__ import annotations

import json
from typing import Any

import pytest

from backend.agentcore_provider import (
    AgentCoreCoachProvider,
    _affinity_session_id,
    _runtime_session_id,
)
from backend.application import CoachApplicationService
from backend.domain import CoachRequest, StageDecision
from backend.learning_service import LearningProgressService
from backend.repositories import (
    SQLiteNotebookRepository,
    SQLitePhaseTransitionRepository,
)
from backend.retrieval import (
    RetrievedChunk,
    RetrievalQuery,
    RetrievalResult,
    retrieval_sources_from_notebook,
)
from backend.settings import settings
from backend.source_library import add_text_source, list_visible_sources
from backend.student_store import StudentStore
from backend.workflow import CoachWorkflow
from agentcore_runtime.prompts.loader import load_stage_prompt
from agentcore_runtime.structured_coach import specialist_system_prompt
from fake_agentcore_runtime import FakeAgentCoreRuntime

_RUNTIME_ARN = (
    "arn:aws:bedrock-agentcore:us-west-2:123456789012:runtime/test-harness"
)
_OWNER = "cognito:critical-path-student"
_NOTEBOOK = "thread-notebook-id"
_OTHER_OWNER = "cognito:other-owner-id"
_OTHER_NOTEBOOK = "thread-other-notebook"
_STUDENT_MESSAGE = "I compared privacy and fairness before choosing the design."
_PROJECT_MESSAGE = "I think option B is stronger."


def _output(*, needs_source_retrieval: bool = False, **overrides: Any) -> dict[str, Any]:
    """Return one lightweight fast-chat coaching payload."""
    payload: dict[str, Any] = {
        "mode": "coaching",
        "response_text": "What trade-off still needs evidence?",
        "recommendation": "stay",
        "recommendation_rationale": "More evidence is still needed.",
        "citations": [],
        "hmw_scaffold_ready": False,
        "needs_source_retrieval": needs_source_retrieval,
        "out_of_scope": False,
    }
    payload.update(overrides)
    return payload


def _provider(client: FakeAgentCoreRuntime) -> AgentCoreCoachProvider:
    """Build the adapter against an injected fake AgentCore client."""
    return AgentCoreCoachProvider(
        _RUNTIME_ARN,
        region="us-west-2",
        qualifier="DEFAULT",
        timeout_seconds=110.0,
        max_retries=0,
        client=client,
    )


def _request(**overrides: Any) -> CoachRequest:
    """Return one coaching request with server-owned identity fields."""
    payload: dict[str, Any] = {
        "thread_id": _NOTEBOOK,
        "student_message": _STUDENT_MESSAGE,
        "current_stage": "problem_identification",
        "response_detail": "short",
        "student_id": _OWNER,
    }
    payload.update(overrides)
    return CoachRequest(**payload)


def _enable_affinity(
    monkeypatch: pytest.MonkeyPatch, *, generation: str = "1"
) -> None:
    """Turn on FastAPI-owned session affinity for one test."""
    monkeypatch.setattr(settings, "agentcore_session_affinity_enabled", True)
    monkeypatch.setattr(settings, "agentcore_session_generation", generation)


def _decoded_payload(call: dict[str, Any]) -> dict[str, Any]:
    """Return the JSON object sent as the InvokeAgentRuntime payload."""
    raw = call["payload"]
    if isinstance(raw, (bytes, bytearray)):
        return json.loads(bytes(raw).decode("utf-8"))
    return json.loads(str(raw))


def test_same_owner_notebook_role_generation_yields_identical_id() -> None:
    first = _affinity_session_id(_OWNER, _NOTEBOOK, "fast_chat", "1")
    second = _affinity_session_id(_OWNER, _NOTEBOOK, "fast_chat", "1")
    assert first == second
    assert first.startswith("codesign-")
    assert len(first) == 73


def test_different_notebook_yields_different_id() -> None:
    first = _affinity_session_id(_OWNER, _NOTEBOOK, "fast_chat", "1")
    second = _affinity_session_id(_OWNER, _OTHER_NOTEBOOK, "fast_chat", "1")
    assert first != second


def test_different_owner_yields_different_id() -> None:
    first = _affinity_session_id(_OWNER, _NOTEBOOK, "fast_chat", "1")
    second = _affinity_session_id(_OTHER_OWNER, _NOTEBOOK, "fast_chat", "1")
    assert first != second


def test_review_deep_is_isolated_from_fast_chat() -> None:
    fast = _affinity_session_id(_OWNER, _NOTEBOOK, "fast_chat", "1")
    review = _affinity_session_id(_OWNER, _NOTEBOOK, "review_deep", "1")
    assert fast != review


def test_different_generation_yields_different_id() -> None:
    first = _affinity_session_id(_OWNER, _NOTEBOOK, "fast_chat", "1")
    second = _affinity_session_id(_OWNER, _NOTEBOOK, "fast_chat", "2")
    assert first != second


def test_session_id_does_not_contain_owner_notebook_or_cognito_sub() -> None:
    session_id = _affinity_session_id(_OWNER, _NOTEBOOK, "fast_chat", "1")
    assert _OWNER not in session_id
    assert _NOTEBOOK not in session_id
    assert "cognito:" not in session_id
    assert "critical-path-student" not in session_id
    assert "thread-notebook-id" not in session_id
    assert "@" not in session_id


def test_flag_disabled_uses_fresh_stateless_ids(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "agentcore_session_affinity_enabled", False)
    client = FakeAgentCoreRuntime(payload=_output())
    provider = _provider(client)
    provider.assess(_request())
    provider.assess(_request())
    first = str(client.calls[0]["runtimeSessionId"])
    second = str(client.calls[1]["runtimeSessionId"])
    assert first != second
    assert first.startswith("stateless-")
    assert second.startswith("stateless-")
    assert len(first) >= 33
    assert len(second) >= 33


def test_missing_owner_fails_open_to_stateless(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _enable_affinity(monkeypatch)
    client = FakeAgentCoreRuntime(payload=_output())
    _provider(client).assess(_request(student_id=None))
    session_id = str(client.calls[0]["runtimeSessionId"])
    assert session_id.startswith("stateless-")
    assert not session_id.startswith("codesign-")


def test_assess_reuses_fast_chat_session_across_invokes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _enable_affinity(monkeypatch)
    client = FakeAgentCoreRuntime(payload=_output())
    provider = _provider(client)
    provider.assess(_request())
    provider.assess(_request())
    first = str(client.calls[0]["runtimeSessionId"])
    second = str(client.calls[1]["runtimeSessionId"])
    assert first == second
    assert first == _affinity_session_id(_OWNER, _NOTEBOOK, "fast_chat", "1")


def test_authoritative_stage_change_keeps_affinity_but_changes_prompt(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    """A chat-selected stage reuses affinity while replacing stage pedagogy."""
    _enable_affinity(monkeypatch)
    monkeypatch.setattr(settings, "student_stage_selection", True)
    store = StudentStore(tmp_path / "affinity-stage.sqlite3", identifier=_OWNER)
    thread_id = store.create_thread(model_id="mock", support_mode="critical-thinking")
    client = FakeAgentCoreRuntime(payloads=[_output(), _output()])
    notebooks = SQLiteNotebookRepository(store)
    transitions = SQLitePhaseTransitionRepository(store)
    service = CoachApplicationService(
        store,
        notebooks,
        CoachWorkflow(_provider(client), transitions),
        LearningProgressService(store, notebooks, transitions),
    )

    service.submit(
        _request(
            thread_id=thread_id,
            current_stage="problem_identification",
            idempotency_key="stage-pi",
        )
    )
    selected = service.submit(
        _request(
            thread_id=thread_id,
            student_message="move me to concept generation",
            current_stage="problem_identification",
            idempotency_key="stage-select-concept",
        )
    )
    assert selected.response_text == "Moved to Stage: Concept generation."
    assert len(client.calls) == 1
    service.submit(
        _request(
            thread_id=thread_id,
            current_stage="concept_generation",
            idempotency_key="stage-concept",
        )
    )

    assert len(client.calls) == 2
    first_call, second_call = client.calls
    assert first_call["runtimeSessionId"] == second_call["runtimeSessionId"]
    assert first_call["runtimeSessionId"] == _affinity_session_id(
        _OWNER, thread_id, "fast_chat", "1"
    )
    first_payload = _decoded_payload(first_call)
    second_payload = _decoded_payload(second_call)
    assert first_payload["topic"] == "problem_identification"
    assert first_payload["runtime_context"]["current_stage"] == (
        "problem_identification"
    )
    assert second_payload["topic"] == "concept_generation"
    assert second_payload["runtime_context"]["current_stage"] == "concept_generation"

    first_prompt = specialist_system_prompt(first_payload)
    second_prompt = specialist_system_prompt(second_payload)
    assert load_stage_prompt("problem_identification") in first_prompt
    assert load_stage_prompt("concept_generation") in second_prompt
    assert load_stage_prompt("concept_generation") not in first_prompt
    assert load_stage_prompt("problem_identification") not in second_prompt


def test_assess_isolates_review_deep_from_fast_chat(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _enable_affinity(monkeypatch)
    client = FakeAgentCoreRuntime(payload=_output())
    provider = _provider(client)
    provider.assess(_request())
    provider.assess(_request(specialist="review"))
    fast = str(client.calls[0]["runtimeSessionId"])
    review = str(client.calls[1]["runtimeSessionId"])
    assert fast != review
    assert fast == _affinity_session_id(_OWNER, _NOTEBOOK, "fast_chat", "1")
    assert review == _affinity_session_id(_OWNER, _NOTEBOOK, "review_deep", "1")


class _RecordingRetriever:
    """Test retriever that records queries and returns a prepared result."""

    def __init__(self, result: RetrievalResult) -> None:
        self.calls: list[RetrievalQuery] = []
        self._result = result

    def retrieve(self, query: RetrievalQuery) -> RetrievalResult:
        """Record one retrieve and return the fixture."""
        self.calls.append(query)
        return self._result


def test_rag_fallback_second_invoke_reuses_fast_chat_session(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    _enable_affinity(monkeypatch)
    store = StudentStore(
        tmp_path / "affinity-rag.sqlite3", identifier=_OWNER
    )
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
    retriever = _RecordingRetriever(
        RetrievalResult(
            context=f"--- [{src.label}] {src.title} --- {chunk.text}",
            chunks=(chunk,),
        )
    )
    client = FakeAgentCoreRuntime(
        payloads=[
            _output(
                response_text="I would need the lecture excerpt first.",
                needs_source_retrieval=True,
                recommendation=StageDecision.ADVANCE.value,
            ),
            _output(
                response_text="What does that 12 percent figure change about option B?",
                needs_source_retrieval=True,
            ),
        ]
    )
    notebooks = SQLiteNotebookRepository(store)
    transitions = SQLitePhaseTransitionRepository(store)
    service = CoachApplicationService(
        store,
        notebooks,
        CoachWorkflow(_provider(client), transitions),
        LearningProgressService(store, notebooks, transitions),
        retriever=retriever,
    )
    service.submit(
        CoachRequest(
            thread_id=thread_id,
            student_message=_PROJECT_MESSAGE,
            current_stage="problem_identification",
            response_detail="short",
            idempotency_key="affinity-rag",
        )
    )
    assert len(client.calls) == 2
    first = str(client.calls[0]["runtimeSessionId"])
    second = str(client.calls[1]["runtimeSessionId"])
    assert first == second
    expected = _affinity_session_id(_OWNER, thread_id, "fast_chat", "1")
    assert first == expected
    runtime_id = _runtime_session_id(
        CoachRequest(
            thread_id=thread_id,
            student_message=_PROJECT_MESSAGE,
            current_stage="problem_identification",
            response_detail="short",
            student_id=_OWNER,
        ),
        "fast_chat",
    )
    assert runtime_id == first


def test_affinity_still_sends_bounded_history_every_invoke(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _enable_affinity(monkeypatch)
    client = FakeAgentCoreRuntime(payload=_output())
    history = [
        {"role": "user", "content": "Earlier student turn about privacy."},
        {"role": "assistant", "content": "Earlier coach reply."},
        {"role": "user", "content": "A second historical student turn."},
        {"role": "assistant", "content": "A second historical coach reply."},
    ]
    _provider(client).assess(_request(history=history))
    _provider(client).assess(_request(history=history))
    assert len(client.calls) == 2
    assert client.calls[0]["runtimeSessionId"] == client.calls[1]["runtimeSessionId"]
    for call in client.calls:
        payload = _decoded_payload(call)
        messages = payload["messages"]
        assert messages[-1]["role"] == "user"
        prior = messages[:-1]
        assert prior
        blob = json.dumps(payload)
        assert "Earlier student turn about privacy." in blob
        assert "memoryId" not in payload
        assert "memory_id" not in payload
        assert "AgentCoreMemory" not in payload
        assert "session_manager" not in payload
        assert "runtimeSessionId" not in payload


def test_affinity_does_not_make_runtime_transcript_authoritative(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _enable_affinity(monkeypatch)
    client = FakeAgentCoreRuntime(payload=_output())
    provider = _provider(client)
    provider.assess(_request())
    session_id = str(client.calls[0]["runtimeSessionId"])
    assert session_id.startswith("codesign-")
    assert _OWNER not in session_id
    assert _NOTEBOOK not in session_id
    assert not hasattr(provider, "_history")
    assert not hasattr(provider, "_sessions")
    payload = _decoded_payload(client.calls[0])
    assert "messages" in payload
    assert payload["messages"][-1]["role"] == "user"
    for forbidden in ("memoryId", "memory_id", "AgentCoreMemory", "session_manager"):
        assert forbidden not in payload
