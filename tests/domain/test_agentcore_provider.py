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

from fake_agentcore_runtime import FakeAgentCoreRuntime

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


def _assessment(
    *,
    stage: str = "problem_identification",
    citations: list[CitationReference] | None = None,
    recommendation: StageDecision = StageDecision.STAY,
) -> EducationalAssessment:
    """Return a valid coaching assessment for adapter tests."""
    return EducationalAssessment(
        current_stage=stage,
        contribution_summary="The student compared two design constraints.",
        stage_assessment="The contribution is usable but can be developed further.",
        critical_understanding_level="Developing",
        confidence=0.7,
        recommendation=recommendation,
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
    recommendation: StageDecision = StageDecision.STAY,
) -> dict[str, Any]:
    """Return a JSON-ready provider envelope, including optional research."""
    envelope = ProviderCoachOutput(
        response_text=response_text,
        assessment=_assessment(
            stage=stage, citations=citations, recommendation=recommendation
        ),
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


def _service(
    store: StudentStore,
    provider: AgentCoreCoachProvider,
    *,
    auto_advance_stages: bool = False,
) -> CoachApplicationService:
    """Build the normal application path with the AgentCore adapter injected."""
    notebooks = SQLiteNotebookRepository(store)
    transitions = SQLitePhaseTransitionRepository(store)
    return CoachApplicationService(
        store,
        notebooks,
        CoachWorkflow(provider, transitions),
        LearningProgressService(store, notebooks, transitions),
        auto_advance_stages=auto_advance_stages,
    )


def _decoded_payload(call: dict[str, Any]) -> dict[str, Any]:
    """Return the JSON object sent as the InvokeAgentRuntime payload."""
    raw = call["payload"]
    if isinstance(raw, (bytes, bytearray)):
        return json.loads(bytes(raw).decode("utf-8"))
    return json.loads(str(raw))


def _call_phase(call: dict[str, Any]) -> str:
    """Return the payload phase for one recorded runtime call."""
    return str(_decoded_payload(call).get("phase") or "")


def _specialist_call(client: FakeAgentCoreRuntime) -> dict[str, Any]:
    """Return the first non-router, non-judge InvokeAgentRuntime call."""
    calls = [
        call
        for call in client.calls
        if _call_phase(call) not in {"router"}
        and not (
            _call_phase(call) == "review"
            and str(_decoded_payload(call).get("review_mode") or "") == "incremental"
        )
    ]
    assert calls
    return calls[0]


def _router_calls(client: FakeAgentCoreRuntime) -> list[dict[str, Any]]:
    """Return recorded Luna router invokes."""
    return [call for call in client.calls if _call_phase(call) == "router"]


def _deep_review_calls(client: FakeAgentCoreRuntime) -> list[dict[str, Any]]:
    """Return recorded Deep Review invokes."""
    calls = []
    for call in client.calls:
        payload = _decoded_payload(call)
        if payload.get("phase") != "review":
            continue
        mode = str(payload.get("review_mode") or "")
        context = payload.get("runtime_context")
        if isinstance(context, dict) and not mode:
            mode = str(context.get("review_mode") or "")
        if mode == "deep":
            calls.append(call)
    return calls


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
    assert len(_router_calls(client)) == 1
    assert len(_deep_review_calls(client)) == 0
    call = _specialist_call(client)
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
    assert payload["trusted_instructions"] == prepared.runtime_instructions
    assert _current_turn_text(payload) == prepared.untrusted_turn_text
    assert _STAGE_MARKERS["problem_identification"] not in payload["trusted_instructions"]
    assert _STAGE_MARKERS["problem_identification"] not in _current_turn_text(payload)
    assert payload["runtime_context"]["current_stage"] == "problem_identification"
    assert payload["runtime_context"]["specialist"] == "coaching"
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
    payload = _decoded_payload(_specialist_call(client))
    assert payload["topic"] == "ethics_critical"
    assert _STAGE_MARKERS["deep_analysis"] not in payload["trusted_instructions"]
    assert _STAGE_MARKERS["deep_analysis"] not in _current_turn_text(payload)
    assert payload["runtime_context"]["current_stage"] == "deep_analysis"
    assert payload["runtime_context"]["agentcore_topic"] == "ethics_critical"


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
    payload = _decoded_payload(_specialist_call(client))
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
    payload = _decoded_payload(_specialist_call(client))
    assert payload["student_id"] == "cognito:critical-path-student"
    assert payload["student_id"] != "thread-notebook-id"
    messages = payload["messages"]
    assert all(item["role"] in {"user", "assistant"} for item in messages)
    assert messages[-1]["role"] == "user"
    assert _STAGE_MARKERS["problem_identification"] not in payload["trusted_instructions"]
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
    payload = _decoded_payload(_specialist_call(client))
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
    payload = _decoded_payload(_specialist_call(client))
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
    with pytest.raises(ProviderUnavailableError, match="could not be completed") as raised:
        _service(store, _provider(client)).submit(
            _request(thread_id=thread_id)
        )
    assert raised.value.category == "structured_output_failure"
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
    payload = _decoded_payload(_specialist_call(client))
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
    with pytest.raises(ProviderUnavailableError, match="could not be completed") as raised:
        _provider(client).assess(_request())
    assert raised.value.category == "structured_output_failure"


def test_plain_prose_agentcore_output_is_rejected_without_persistence(tmp_path):
    store = StudentStore(tmp_path / "agentcore-prose.sqlite3")
    thread_id = store.create_thread(model_id="mock", support_mode="critical-thinking")
    client = FakeAgentCoreRuntime(raw=b"Here is coaching without a JSON object.")
    with pytest.raises(ProviderUnavailableError, match="could not be completed") as raised:
        _service(store, _provider(client)).submit(_request(thread_id=thread_id))
    assert raised.value.category == "structured_output_failure"
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


def test_malformed_sse_prose_is_rejected_as_structured_output_failure():
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
    with pytest.raises(ProviderUnavailableError, match="could not be completed") as raised:
        _provider(client).assess(_request())
    assert raised.value.category == "structured_output_failure"


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
    from agentcore_runtime.structured_coach import coaching_invoke_prompts

    prepared = compose_coach_prompt(_request(), include_recent_messages=False)
    payload = {
        "output_contract": "coach_turn",
        "trusted_instructions": prepared.trusted_instructions,
        "messages": [
            {"role": "user", "content": [{"text": prepared.untrusted_turn_text}]}
        ],
    }
    system_prompt, user_prompt = coaching_invoke_prompts(payload)
    assert prepared.trusted_instructions in system_prompt
    assert user_prompt == prepared.untrusted_turn_text
    assert _STAGE_MARKERS["problem_identification"] in system_prompt
    assert _STUDENT_MESSAGE in user_prompt
    assert _STUDENT_MESSAGE not in system_prompt
    legacy_system, legacy_user = coaching_invoke_prompts(
        {"messages": [{"role": "user", "content": [{"text": prepared.composed_text}]}]}
    )
    assert prepared.trusted_instructions not in legacy_system
    assert legacy_user == prepared.composed_text


_STREET = "A quiet residential street"


def _thread_stage(store: StudentStore, thread_id: str) -> str:
    """Return the persisted Thinking Path stage for one notebook."""
    thread = store.get_thread(thread_id) or {}
    metadata = thread.get("metadata") or {}
    journey = metadata.get("learning_journey") or {}
    return str(
        journey.get("current_stage")
        or metadata.get("thinking_stage")
        or ""
    )


def test_empty_runtime_body_is_structured_output_failure():
    client = FakeAgentCoreRuntime(raw=b"")
    with pytest.raises(ProviderUnavailableError, match="could not be completed") as raised:
        _provider(client).assess(_request())
    assert raised.value.category == "structured_output_failure"
    assert "JSONDecodeError" not in str(raised.value)


def test_harness_error_envelope_maps_to_structured_output_failure():
    client = FakeAgentCoreRuntime(
        payload={"ok": False, "error": True, "category": "structured_output_failure"}
    )
    with pytest.raises(ProviderUnavailableError, match="could not be completed") as raised:
        _provider(client).assess(_request())
    assert raised.value.category == "structured_output_failure"


def test_harness_safety_envelope_stays_safety_blocked():
    client = FakeAgentCoreRuntime(
        payload={"ok": False, "error": True, "category": "safety_blocked"}
    )
    with pytest.raises(ProviderUnavailableError, match="blocked this turn") as raised:
        _provider(client).assess(_request())
    assert raised.value.category == "safety_blocked"


def test_short_street_contribution_is_invoked_and_not_treated_as_empty():
    client = FakeAgentCoreRuntime(payload=_output(research=None))
    result = _provider(client).assess(_request(student_message=_STREET))
    assert result.response_text
    assert result.assessment.recommendation is StageDecision.STAY
    payload = _decoded_payload(_specialist_call(client))
    current = _current_turn_text(payload)
    assert current.count(_STREET) == 1
    assert json.dumps(payload).count(_STREET) == 1
    assert _STREET in current
    assert payload["messages"][-1]["content"][0]["text"].strip()


def test_large_history_and_evidence_keep_current_street_contribution_once():
    history = []
    for index in range(24):
        role = "user" if index % 2 == 0 else "assistant"
        history.append(
            {
                "role": role,
                "content": f"history-turn-{index} " + ("design-context " * 80),
            }
        )
    evidence = "retrieved-excerpt " * 1200
    request = _request(
        student_message=_STREET,
        history=history,
        source_context=evidence,
        student_project_context="project-context " * 400,
    )
    client = FakeAgentCoreRuntime(payload=_output(research=None))
    result = _provider(client).assess(request)
    assert result.response_text
    encoded = _specialist_call(client)["payload"]
    size = len(encoded if isinstance(encoded, (bytes, bytearray)) else str(encoded))
    assert 30_000 <= size <= 150_000
    payload = _decoded_payload(_specialist_call(client))
    current = _current_turn_text(payload)
    assert current.count(_STREET) == 1
    assert json.dumps(payload).count(_STREET) == 1
    assert _STREET not in payload["trusted_instructions"]
    assert payload["messages"][-1]["role"] == "user"


def test_structured_output_failure_retry_persists_exactly_one_turn(tmp_path):
    store = StudentStore(tmp_path / "agentcore-street-retry.sqlite3")
    thread_id = store.create_thread(model_id="mock", support_mode="critical-thinking")
    client = FakeAgentCoreRuntime(payloads=[b"", _output(research=None)])
    service = _service(store, _provider(client))
    request = _request(
        thread_id=thread_id,
        student_message=_STREET,
        idempotency_key="street-structured-retry",
    )
    with pytest.raises(ProviderUnavailableError, match="could not be completed") as raised:
        service.submit(request)
    assert raised.value.category == "structured_output_failure"
    first_messages = store.get_messages(thread_id)
    assert all(item["role"] != "assistant" for item in first_messages)
    assert all(str(item.get("content") or "").strip() for item in first_messages)
    assert store.get_pending_phase_transition(thread_id) is None
    completed = service.submit(request)
    assert completed.response_text
    messages = store.get_messages(thread_id)
    roles = [item["role"] for item in messages]
    assert roles.count("user") == 1
    assert roles.count("assistant") == 1
    user = next(item for item in messages if item["role"] == "user")
    assistant = next(item for item in messages if item["role"] == "assistant")
    assert user["content"] == _STREET
    assert assistant["content"].strip()
    assert store.get_pending_phase_transition(thread_id) is None
    assert _thread_stage(store, thread_id) == "problem_identification"


def test_street_stay_does_not_advance_stage(tmp_path):
    store = StudentStore(tmp_path / "agentcore-street-stay.sqlite3")
    thread_id = store.create_thread(model_id="mock", support_mode="critical-thinking")
    client = FakeAgentCoreRuntime(payload=_output(research=None))
    turn = _service(store, _provider(client)).submit(
        _request(thread_id=thread_id, student_message=_STREET)
    )
    assert turn.assessment.recommendation is StageDecision.STAY
    assert turn.pending_transition is None
    assert _thread_stage(store, thread_id) == "problem_identification"


def test_street_advance_follows_validated_recommendation_not_the_sentence(tmp_path):
    store = StudentStore(tmp_path / "agentcore-street-advance.sqlite3")
    thread_id = store.create_thread(model_id="mock", support_mode="critical-thinking")
    client = FakeAgentCoreRuntime(
        payload=_output(research=None, recommendation=StageDecision.ADVANCE)
    )
    turn = _service(store, _provider(client)).submit(
        _request(thread_id=thread_id, student_message=_STREET)
    )
    assert turn.assessment.recommendation is StageDecision.ADVANCE
    assert turn.pending_transition is not None
    assert _thread_stage(store, thread_id) == "problem_identification"


def test_street_advance_auto_applies_when_configured(tmp_path):
    store = StudentStore(tmp_path / "agentcore-street-auto.sqlite3")
    thread_id = store.create_thread(model_id="mock", support_mode="critical-thinking")
    client = FakeAgentCoreRuntime(
        payload=_output(research=None, recommendation=StageDecision.ADVANCE)
    )
    turn = _service(
        store, _provider(client), auto_advance_stages=True
    ).submit(_request(thread_id=thread_id, student_message=_STREET))
    assert turn.assessment.recommendation is StageDecision.ADVANCE
    assert turn.pending_transition is None
    assert turn.auto_advanced_to == "concept_generation"
    assert _thread_stage(store, thread_id) == "concept_generation"
    messages = store.get_messages(thread_id)
    assert [item["role"] for item in messages].count("assistant") == 1
    assert all(str(item.get("content") or "").strip() for item in messages)
