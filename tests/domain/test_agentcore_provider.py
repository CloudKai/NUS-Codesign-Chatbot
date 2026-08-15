"""Deterministic AgentCore coach-adapter contract tests (no AWS or paid calls)."""

from __future__ import annotations

import json
from typing import Any

import pytest
from fastapi.testclient import TestClient

from backend.agentcore_provider import AgentCoreCoachProvider, agentcore_topic_for_stage
from backend.api import create_app
from backend.application import CoachApplicationService
from backend.domain import (
    CitationReference,
    ClearCode,
    CoachImageInput,
    CoachRequest,
    EducationalAssessment,
    FacioneBehavior,
    FacioneDimensionScores,
    ProviderCoachOutput,
    ProvisionalResearchCoding,
    ResearchCodingStatus,
    ResearchEvidence,
    StageDecision,
)
from backend.learning_service import LearningProgressService
from backend.prompts import compose_coach_prompt
from backend.providers import ProviderUnavailableError, configured_coach_provider
from backend.repositories import (
    SQLiteNotebookRepository,
    SQLitePhaseTransitionRepository,
)
from backend.settings import settings
from backend.student_store import StudentStore
from backend.workflow import CoachWorkflow

_TINY_PNG = (
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQ"
    "AAAABJRU5ErkJggg=="
)
_STUDENT_MESSAGE = "I compared privacy and fairness before choosing the design."
_RUNTIME_ARN = (
    "arn:aws:bedrock-agentcore:us-west-2:123456789012:runtime/test-harness"
)
_STAGE_MARKERS = {
    "problem_identification": "STAGE: PROBLEM IDENTIFICATION",
    "concept_generation": "STAGE: CONCEPT GENERATION",
    "design_specification": "STAGE: DESIGN SPECIFICATION",
    "deep_analysis": "STAGE: ETHICS & CRITICAL THINKING",
    "reflection": "STAGE: REFLECTION",
}


class FakeClientError(Exception):
    """Stand-in for botocore ClientError that never imports AWS SDKs."""

    def __init__(self, code: str, message: str = "aws-error") -> None:
        super().__init__(message)
        self.response = {"Error": {"Code": code, "Message": message}}


class FakeBody:
    """Minimal streaming-body stand-in used by the fake runtime client."""

    def __init__(self, payload: bytes) -> None:
        self._payload = payload

    def read(self) -> bytes:
        """Return the whole fake response body."""
        return self._payload


class FakeAgentCoreRuntime:
    """Injected bedrock-agentcore client that records InvokeAgentRuntime calls."""

    def __init__(
        self,
        *,
        payload: dict[str, Any] | None = None,
        raw: bytes | None = None,
        content_type: str = "application/json",
        error: BaseException | None = None,
    ) -> None:
        self.calls: list[dict[str, Any]] = []
        self._payload = payload
        self._raw = raw
        self._content_type = content_type
        self._error = error

    def invoke_agent_runtime(self, **kwargs: Any) -> dict[str, Any]:
        """Record one runtime invocation and return a fake structured response."""
        self.calls.append(kwargs)
        if self._error is not None:
            raise self._error
        if self._raw is not None:
            body = self._raw
        else:
            body = json.dumps(self._payload or {}).encode("utf-8")
        return {"contentType": self._content_type, "response": FakeBody(body)}


def _assessment(
    *,
    stage: str = "problem_identification",
    citations: list[CitationReference] | None = None,
) -> EducationalAssessment:
    """Return a valid coaching assessment for adapter tests."""
    return EducationalAssessment(
        current_stage=stage,
        contribution_summary="The student compared two design constraints.",
        stage_assessment="The contribution is usable but can be developed further.",
        critical_understanding_level="Developing",
        confidence=0.7,
        recommendation=StageDecision.STAY,
        recommendation_rationale="One important element remains to be examined.",
        guidance_questions=["What should you examine next?"],
        learning_summary="The student is developing the design reasoning.",
        citations=citations or [],
        facione_scores=FacioneDimensionScores(analysis=2, evaluation=2),
    )


def _coding(*, quote: str = _STUDENT_MESSAGE) -> ProvisionalResearchCoding:
    """Return valid research coding whose quote matches the test contribution."""
    return ProvisionalResearchCoding(
        coding_status=ResearchCodingStatus.CODED,
        dominant_clear=ClearCode.LOGICAL,
        facione_behaviors=[FacioneBehavior.ANALYSIS, FacioneBehavior.EVALUATION],
        evidence=[
            ResearchEvidence(
                quote=quote,
                rationale="The student explicitly relates constraints to a choice.",
                confidence=0.8,
            )
        ],
    )


def _output(
    *,
    stage: str = "problem_identification",
    research: ProvisionalResearchCoding | None | dict[str, Any] = _coding(),
    citations: list[CitationReference] | None = None,
    response_text: str = "What trade-off still needs evidence [S1]?",
) -> dict[str, Any]:
    """Return a JSON-ready provider envelope, including optional research."""
    envelope = ProviderCoachOutput(
        response_text=response_text,
        assessment=_assessment(stage=stage, citations=citations),
        research_coding=research if not isinstance(research, dict) else None,
    )
    dumped = envelope.model_dump(mode="json")
    if isinstance(research, dict):
        dumped["research_coding"] = research
    return dumped


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
    """Return one minimal coaching request for direct adapter tests."""
    payload = {
        "thread_id": "thread-demo",
        "student_message": _STUDENT_MESSAGE,
        "current_stage": "problem_identification",
        "response_detail": "short",
    }
    payload.update(overrides)
    return CoachRequest(**payload)


def _service(store: StudentStore, provider: AgentCoreCoachProvider) -> CoachApplicationService:
    """Build the normal application path with the AgentCore adapter injected."""
    notebooks = SQLiteNotebookRepository(store)
    transitions = SQLitePhaseTransitionRepository(store)
    return CoachApplicationService(
        store,
        notebooks,
        CoachWorkflow(provider, transitions),
        LearningProgressService(store, notebooks, transitions),
    )


def _decoded_payload(call: dict[str, Any]) -> dict[str, Any]:
    """Return the JSON object sent as the InvokeAgentRuntime payload."""
    raw = call["payload"]
    if isinstance(raw, (bytes, bytearray)):
        return json.loads(bytes(raw).decode("utf-8"))
    return json.loads(str(raw))


def _current_turn_text(payload: dict[str, Any]) -> str:
    """Return the composed current-turn text from Converse messages."""
    messages = payload["messages"]
    assert messages[-1]["role"] == "user"
    return str(messages[-1]["content"][0]["text"])


def _sse_bytes(*events: dict[str, Any]) -> bytes:
    """Encode runtime events as an SSE body for adapter tests."""
    return "".join(f"data: {json.dumps(event)}\n\n" for event in events).encode("utf-8")


def test_agentcore_provider_rejects_missing_runtime_arn():
    with pytest.raises(ProviderUnavailableError, match="AGENTCORE_RUNTIME_ARN"):
        AgentCoreCoachProvider("  ", client=FakeAgentCoreRuntime(payload=_output()))


def test_valid_structured_coaching_and_research_coding():
    client = FakeAgentCoreRuntime(payload=_output())
    result = _provider(client).assess(_request())
    assert result.response_text.startswith("What trade-off")
    assert result.assessment.current_stage == "problem_identification"
    assert result.research_coding is not None
    assert result.research_coding.coding_status is ResearchCodingStatus.CODED
    assert len(client.calls) == 1
    call = client.calls[0]
    assert call["agentRuntimeArn"] == _RUNTIME_ARN
    assert call["qualifier"] == "DEFAULT"
    assert str(call["runtimeSessionId"]).startswith("stateless-")
    assert len(str(call["runtimeSessionId"])) >= 33
    payload = _decoded_payload(call)
    assert payload["phase"] == "coaching"
    assert payload["topic"] == "problem_identification"
    assert payload["output_contract"] == "coach_turn"
    assert "prompt" not in payload
    prepared = compose_coach_prompt(_request(), include_recent_messages=False)
    assert payload["trusted_instructions"] == prepared.trusted_instructions
    assert _current_turn_text(payload) == prepared.untrusted_turn_text
    assert _STAGE_MARKERS["problem_identification"] in payload["trusted_instructions"]
    assert _STAGE_MARKERS["problem_identification"] not in _current_turn_text(payload)
    assert _STUDENT_MESSAGE in _current_turn_text(payload)
    assert _STUDENT_MESSAGE not in payload["trusted_instructions"]
    assert "RetrieveAndGenerate" not in json.dumps(payload)


def test_live_uppercase_recommendation_and_object_stage_assessment_are_accepted():
    payload = _output()
    payload["assessment"]["recommendation"] = "STAY"
    payload["assessment"]["stage_assessment"] = {
        "strengths": [],
        "improvements": ["Trade-offs can be identified."],
    }
    result = _provider(FakeAgentCoreRuntime(payload=payload)).assess(_request())
    assert result.assessment.recommendation is StageDecision.STAY
    assert "Trade-offs can be identified." in result.assessment.stage_assessment


def test_deep_analysis_maps_only_to_agentcore_ethics_critical_topic():
    assert agentcore_topic_for_stage("deep_analysis") == "ethics_critical"
    client = FakeAgentCoreRuntime(payload=_output(stage="deep_analysis"))
    result = _provider(client).assess(_request(current_stage="deep_analysis"))
    assert result.assessment.current_stage == "deep_analysis"
    payload = _decoded_payload(client.calls[0])
    assert payload["topic"] == "ethics_critical"
    assert _STAGE_MARKERS["deep_analysis"] in payload["trusted_instructions"]
    assert _STAGE_MARKERS["deep_analysis"] not in _current_turn_text(payload)


def test_stateless_session_ids_are_unique_per_invoke():
    client = FakeAgentCoreRuntime(payload=_output())
    provider = _provider(client)
    provider.assess(_request())
    provider.assess(_request())
    first = str(client.calls[0]["runtimeSessionId"])
    second = str(client.calls[1]["runtimeSessionId"])
    assert first != second
    assert first.startswith("stateless-")
    assert second.startswith("stateless-")


def test_runtime_session_is_never_notebook_memory_or_history():
    """AgentCore must not become a second transcript beside DSQL/SQLite."""
    client = FakeAgentCoreRuntime(payload=_output())
    provider = _provider(client)
    long_thread = "thread-" + ("a" * 40)
    provider.assess(_request(thread_id=long_thread))
    session_id = str(client.calls[0]["runtimeSessionId"])
    assert session_id != long_thread
    assert "thread-" not in session_id
    assert not hasattr(provider, "_history")
    assert not hasattr(provider, "_sessions")
    payload = _decoded_payload(client.calls[0])
    for forbidden in (
        "memoryId",
        "memory_id",
        "sessionId",
        "history",
        "runtimeSessionId",
    ):
        assert forbidden not in payload
    assert "student_id" not in payload


def test_agentcore_payload_sends_full_history_and_owner_student_id():
    """DSQL history is Converse messages; student_id is the store owner, not the notebook."""
    client = FakeAgentCoreRuntime(payload=_output())
    history = [
        {"role": "user", "content": f"Earlier student turn {index}."}
        for index in range(8)
    ]
    history.append({"role": "assistant", "content": "Earlier coach reply."})
    _provider(client).assess(
        _request(
            thread_id="thread-notebook-id",
            student_id="cognito:critical-path-student",
            history=history,
        )
    )
    payload = _decoded_payload(client.calls[0])
    assert payload["student_id"] == "cognito:critical-path-student"
    assert payload["student_id"] != "thread-notebook-id"
    messages = payload["messages"]
    assert all(item["role"] in {"user", "assistant"} for item in messages)
    assert messages[-1]["role"] == "user"
    assert _STAGE_MARKERS["problem_identification"] in payload["trusted_instructions"]
    assert _STAGE_MARKERS["problem_identification"] not in messages[-1]["content"][0]["text"]
    prior = messages[:-1]
    assert len(prior) == 9
    assert prior[0]["content"][0]["text"] == "Earlier student turn 0."
    assert prior[-1]["role"] == "assistant"
    current_text = messages[-1]["content"][0]["text"]
    assert "Earlier student turn 0." not in current_text
    assert "Earlier coach reply." not in current_text
    assert "<recent_messages>" in current_text
    assert "supplied separately as message history" in current_text


def test_agentcore_compression_keeps_early_decision_out_of_recent_messages():
    from backend.context_planner import ContextBudget, HistoryContextPlanner

    client = FakeAgentCoreRuntime(payload=_output())
    planner = HistoryContextPlanner(
        ContextBudget(
            model_context_limit_tokens=7_000,
            max_input_tokens=6_000,
            output_reserve_tokens=500,
            safety_margin_tokens=500,
            recent_verbatim_messages=4,
        )
    )
    history = [
        {
            "role": "user",
            "content": "EARLY_DECISION I chose a raised crossing for older pedestrians.",
        },
        {"role": "assistant", "content": "What evidence supports that choice?"},
    ]
    history.extend(
        {
            "role": "user" if index % 2 == 0 else "assistant",
            "content": f"later-{index} " + ("padding " * 40),
        }
        for index in range(20)
    )
    provider = AgentCoreCoachProvider(
        _RUNTIME_ARN,
        client=client,
        planner=planner,
    )
    provider.assess(_request(history=history, conversation_revision=1))
    payload = _decoded_payload(client.calls[0])
    prior = payload["messages"][:-1]
    assert 1 <= len(prior) <= 4
    current_text = _current_turn_text(payload)
    assert "EARLY_DECISION" in current_text
    assert "<conversation_memory>" in current_text
    assert "supplied separately as message history" in current_text
    for item in prior:
        assert "EARLY_DECISION" not in item["content"][0]["text"]
    assert current_text.count(_STUDENT_MESSAGE) == 1


def test_application_path_stamps_store_identifier_as_student_id(tmp_path):
    store = StudentStore(
        tmp_path / "agentcore-owner.sqlite3", identifier="cognito:owner-sub"
    )
    thread_id = store.create_thread(model_id="mock", support_mode="critical-thinking")
    store.add_message(thread_id, "user", "I framed the crossing problem.")
    store.add_message(thread_id, "assistant", "Who is affected at night?")
    client = FakeAgentCoreRuntime(payload=_output())
    _service(store, _provider(client)).submit(_request(thread_id=thread_id))
    payload = _decoded_payload(client.calls[0])
    assert payload["student_id"] == "cognito:owner-sub"
    assert payload["student_id"] != thread_id
    prior = payload["messages"][:-1]
    assert prior[0]["content"][0]["text"] == "I framed the crossing problem."
    assert prior[1]["content"][0]["text"] == "Who is affected at night?"
    current_text = payload["messages"][-1]["content"][0]["text"]
    assert "I framed the crossing problem." not in current_text
    assert "Who is affected at night?" not in current_text


def test_valid_agentcore_turn_persists_only_in_student_store(tmp_path):
    store_path = tmp_path / "agentcore-persist.sqlite3"
    store = StudentStore(store_path)
    thread_id = store.create_thread(model_id="mock", support_mode="critical-thinking")
    client = FakeAgentCoreRuntime(payload=_output())
    turn = _service(store, _provider(client)).submit(_request(thread_id=thread_id))
    messages = store.get_messages(thread_id)
    assert any(item["role"] == "user" for item in messages)
    assert any(item["content"] == turn.response_text for item in messages)
    assert store_path.is_file()
    assert not (tmp_path / "poc_store.json").exists()
    assert list(tmp_path.glob("*.json")) == []


def test_result_envelope_is_unwrapped():
    client = FakeAgentCoreRuntime(payload={"result": _output()})
    result = _provider(client).assess(_request())
    assert result.response_text.startswith("What trade-off")


def test_absent_or_invalid_research_coding_is_retained_as_uncoded():
    missing = _provider(FakeAgentCoreRuntime(payload=_output(research=None))).assess(
        _request()
    )
    assert missing.research_coding is None

    invalid = _provider(
        FakeAgentCoreRuntime(payload=_output(research={"not": "a-coding"}))
    ).assess(_request())
    assert invalid.research_coding is None
    assert invalid.response_text.startswith("What trade-off")


def test_invalid_coaching_is_rejected_without_persistence(tmp_path):
    store = StudentStore(tmp_path / "agentcore-invalid.sqlite3")
    thread_id = store.create_thread(model_id="mock", support_mode="critical-thinking")
    client = FakeAgentCoreRuntime(payload={"response_text": ""})
    with pytest.raises(ProviderUnavailableError, match="malformed"):
        _service(store, _provider(client)).submit(
            _request(thread_id=thread_id)
        )
    assert all(item["role"] != "assistant" for item in store.get_messages(thread_id))
    assert store.list_research_observations(notebook_id=thread_id) == []


def test_persisted_stage_overrides_model_supplied_phase():
    client = FakeAgentCoreRuntime(payload=_output(stage="reflection"))
    result = _provider(client).assess(_request(current_stage="concept_generation"))
    assert result.assessment.current_stage == "concept_generation"


def test_selected_source_citations_pass_through_the_adapter():
    citations = [
        CitationReference(
            source_id="src-1",
            label="S1",
            title="Lecture",
            excerpt="Crossing evidence.",
        )
    ]
    client = FakeAgentCoreRuntime(payload=_output(citations=citations))
    result = _provider(client).assess(_request())
    assert result.assessment.citations[0].label == "S1"
    assert result.assessment.citations[0].source_id == "src-1"


def test_images_are_mapped_into_runtime_messages():
    image = CoachImageInput(
        source_id="img-1",
        mime="image/png",
        data_url=f"data:image/png;base64,{_TINY_PNG}",
    )
    client = FakeAgentCoreRuntime(payload=_output())
    _provider(client).assess(_request(image_inputs=[image]))
    payload = _decoded_payload(client.calls[0])
    assert "prompt" not in payload
    content = payload["messages"][-1]["content"]
    assert content[0]["text"] == compose_coach_prompt(
        _request(image_inputs=[image]),
        include_recent_messages=False,
    ).untrusted_turn_text
    assert content[1]["image"]["format"] == "png"
    assert content[1]["image"]["source"]["bytes"] == _TINY_PNG


def test_unsupported_image_fails_closed_before_invoke():
    image = CoachImageInput(
        source_id="img-1",
        mime="image/tiff",
        data_url="data:image/tiff;base64,QQ==",
    )
    client = FakeAgentCoreRuntime(payload=_output())
    with pytest.raises(ProviderUnavailableError, match="image type"):
        _provider(client).assess(_request(image_inputs=[image]))
    assert client.calls == []


@pytest.mark.parametrize(
    "error,match",
    [
        (FakeClientError("ThrottlingException", _STUDENT_MESSAGE), "throttled"),
        (TimeoutError(_STUDENT_MESSAGE), "timed out"),
        (FakeClientError("AccessDeniedException", _STUDENT_MESSAGE), "access was denied"),
        (
            FakeClientError("ResourceNotFoundException", _STUDENT_MESSAGE),
            "runtime is unavailable",
        ),
    ],
)
def test_agentcore_error_translation_hides_aws_and_student_content(
    error: BaseException, match: str
):
    client = FakeAgentCoreRuntime(error=error)
    with pytest.raises(ProviderUnavailableError, match=match) as raised:
        _provider(client).assess(_request())
    message = str(raised.value)
    assert _STUDENT_MESSAGE not in message
    assert "aws-error" not in message
    assert "AccessDeniedException" not in message
    if "throttl" in match:
        assert raised.value.category == "throttled"
    elif "timed out" in match:
        assert raised.value.category == "timeout"
    elif "denied" in match:
        assert raised.value.category == "access_denied"
    else:
        assert raised.value.category == "unavailable"


def test_markdown_fences_are_not_parsed_as_structured_output():
    fenced = "```json\n" + json.dumps(_output()) + "\n```"
    client = FakeAgentCoreRuntime(raw=fenced.encode("utf-8"))
    with pytest.raises(ProviderUnavailableError, match="malformed"):
        _provider(client).assess(_request())


def test_plain_prose_agentcore_output_is_rejected_without_persistence(tmp_path):
    store = StudentStore(tmp_path / "agentcore-prose.sqlite3")
    thread_id = store.create_thread(model_id="mock", support_mode="critical-thinking")
    client = FakeAgentCoreRuntime(raw=b"Here is coaching without a JSON object.")
    with pytest.raises(ProviderUnavailableError, match="malformed"):
        _service(store, _provider(client)).submit(_request(thread_id=thread_id))
    assert all(item["role"] != "assistant" for item in store.get_messages(thread_id))
    assert store.list_research_observations(notebook_id=thread_id) == []


def test_configured_coach_provider_selects_agentcore(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(settings, "model_provider", "agentcore")
    monkeypatch.setattr(settings, "agentcore_runtime_arn", _RUNTIME_ARN)
    monkeypatch.setattr(settings, "aws_region", "us-west-2")
    provider = configured_coach_provider()
    assert isinstance(provider, AgentCoreCoachProvider)
    assert provider.provider_id == "agentcore"
    assert provider.model_id_for(_request()) == _RUNTIME_ARN


def test_readiness_requires_agentcore_runtime_arn(
    tmp_path, monkeypatch: pytest.MonkeyPatch
):
    client = TestClient(create_app(StudentStore(tmp_path / "agentcore-ready.sqlite3")))
    monkeypatch.setattr(settings, "model_provider", "agentcore")
    monkeypatch.setattr(settings, "agentcore_runtime_arn", "")
    monkeypatch.setattr(settings, "agentcore_runtime_id", "")
    response = client.get("/api/v1/ready")
    assert response.status_code == 503
    assert "AGENTCORE_RUNTIME_ARN" in response.json()["detail"]


def test_successful_sse_structured_output_is_parsed():
    client = FakeAgentCoreRuntime(
        raw=_sse_bytes(
            {"event": {"messageStart": {"role": "assistant"}}},
            {
                "event": {
                    "contentBlockDelta": {"delta": {"text": json.dumps(_output())}}
                }
            },
            {"event": {"messageStop": {"stopReason": "end_turn"}}},
        ),
        content_type="text/event-stream",
    )
    result = _provider(client).assess(_request())
    assert result.response_text.startswith("What trade-off")


def test_guardrail_intervened_is_blocked_without_parsing_refusal(caplog):
    refusal = "I can't respond to that request."
    client = FakeAgentCoreRuntime(
        raw=_sse_bytes(
            {"event": {"messageStart": {"role": "assistant"}}},
            {"event": {"contentBlockDelta": {"delta": {"text": refusal}}}},
            {"event": {"messageStop": {"stopReason": "guardrail_intervened"}}},
            {
                "event": {
                    "metadata": {
                        "trace": {
                            "guardrail": {
                                "inputAssessment": {
                                    "o8aipba8m129": {
                                        "contentPolicy": {
                                            "filters": [
                                                {
                                                    "type": "PROMPT_ATTACK",
                                                    "action": "BLOCKED",
                                                    "confidence": "HIGH",
                                                }
                                            ]
                                        }
                                    }
                                }
                            }
                        }
                    }
                }
            },
        ),
        content_type="text/event-stream",
    )
    with pytest.raises(ProviderUnavailableError, match="blocked this turn") as raised:
        _provider(client).assess(_request())
    assert raised.value.category == "safety_blocked"
    assert refusal not in str(raised.value)
    assert "PROMPT_ATTACK" not in str(raised.value)
    assert _STUDENT_MESSAGE not in str(raised.value)
    joined = "\n".join(record.getMessage() for record in caplog.records)
    assert "PROMPT_ATTACK" not in joined
    assert refusal not in joined


def test_trace_only_blocked_assessment_is_safety_blocked():
    client = FakeAgentCoreRuntime(
        raw=_sse_bytes(
            {
                "event": {
                    "metadata": {
                        "trace": {
                            "guardrail": {
                                "inputAssessment": {
                                    "gid": {
                                        "contentPolicy": {
                                            "filters": [
                                                {
                                                    "type": "PROMPT_ATTACK",
                                                    "action": "BLOCKED",
                                                }
                                            ]
                                        }
                                    }
                                }
                            }
                        }
                    }
                }
            }
        ),
        content_type="text/event-stream",
    )
    with pytest.raises(ProviderUnavailableError, match="blocked this turn") as raised:
        _provider(client).assess(_request())
    assert raised.value.category == "safety_blocked"
    assert "PROMPT_ATTACK" not in str(raised.value)


def test_content_filtered_stop_reason_is_safety_blocked():
    client = FakeAgentCoreRuntime(
        raw=_sse_bytes(
            {"event": {"contentBlockDelta": {"delta": {"text": "filtered"}}}},
            {"event": {"messageStop": {"stopReason": "content_filtered"}}},
        ),
        content_type="text/event-stream",
    )
    with pytest.raises(ProviderUnavailableError, match="blocked this turn") as raised:
        _provider(client).assess(_request())
    assert raised.value.category == "safety_blocked"
    assert "filtered" not in str(raised.value)


def test_malformed_sse_prose_is_rejected_as_malformed():
    client = FakeAgentCoreRuntime(
        raw=_sse_bytes(
            {
                "event": {
                    "contentBlockDelta": {
                        "delta": {"text": "Here is coaching without a JSON object."}
                    }
                }
            },
            {"event": {"messageStop": {"stopReason": "end_turn"}}},
        ),
        content_type="text/event-stream",
    )
    with pytest.raises(ProviderUnavailableError, match="malformed") as raised:
        _provider(client).assess(_request())
    assert raised.value.category == "malformed"


def test_blocked_turn_is_rejected_without_persistence(tmp_path):
    store = StudentStore(tmp_path / "agentcore-blocked.sqlite3")
    thread_id = store.create_thread(model_id="mock", support_mode="critical-thinking")
    client = FakeAgentCoreRuntime(
        raw=_sse_bytes(
            {"event": {"messageStop": {"stopReason": "guardrail_intervened"}}}
        ),
        content_type="text/event-stream",
    )
    with pytest.raises(ProviderUnavailableError, match="blocked this turn"):
        _service(store, _provider(client)).submit(_request(thread_id=thread_id))
    assert all(item["role"] != "assistant" for item in store.get_messages(thread_id))
    assert store.list_research_observations(notebook_id=thread_id) == []


def test_harness_patch_appends_trusted_instructions_and_uses_untrusted_user():
    import importlib.util
    from pathlib import Path

    path = Path("scripts/agentcore/harness_patch/structured_coach.py")
    spec = importlib.util.spec_from_file_location("harness_structured_coach", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    prepared = compose_coach_prompt(_request(), include_recent_messages=False)
    payload = {
        "output_contract": "coach_turn",
        "trusted_instructions": prepared.trusted_instructions,
        "messages": [
            {"role": "user", "content": [{"text": prepared.untrusted_turn_text}]}
        ],
    }
    system_prompt, user_prompt = module.coaching_invoke_prompts(payload)
    assert prepared.trusted_instructions in system_prompt
    assert user_prompt == prepared.untrusted_turn_text
    assert _STAGE_MARKERS["problem_identification"] in system_prompt
    assert _STUDENT_MESSAGE in user_prompt
    assert _STUDENT_MESSAGE not in system_prompt
    legacy_system, legacy_user = module.coaching_invoke_prompts(
        {"messages": [{"role": "user", "content": [{"text": prepared.composed_text}]}]}
    )
    assert prepared.trusted_instructions not in legacy_system
    assert legacy_user == prepared.composed_text
