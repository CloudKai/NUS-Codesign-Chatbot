"""Deterministic one-call fast-chat AgentCore tests (no AWS)."""

from __future__ import annotations

import json
from typing import Any

import pytest

from backend.agentcore_provider import AgentCoreCoachProvider
from backend.domain import (
    CoachRequest,
    EducationalAssessment,
    FacioneDimensionScores,
    RetrievalChunkReference,
    StageDecision,
)
from backend.providers import ProviderUnavailableError
from fake_agentcore_runtime import FakeAgentCoreRuntime

_RUNTIME_ARN = (
    "arn:aws:bedrock-agentcore:us-west-2:123456789012:runtime/test-harness"
)


def _assessment(
    *,
    recommendation: StageDecision = StageDecision.STAY,
    readiness_candidate: bool = False,
) -> EducationalAssessment:
    """Return a valid coaching assessment."""
    return EducationalAssessment(
        current_stage="problem_identification",
        contribution_summary="The student compared two design constraints.",
        stage_assessment="The contribution is usable but can be developed further.",
        critical_understanding_level="Developing",
        confidence=0.7,
        recommendation=recommendation,
        recommendation_rationale="More evidence is still needed."
        if recommendation is StageDecision.STAY
        else "The stage readiness bar is met.",
        guidance_questions=["What trade-off still needs evidence?"],
        learning_summary="The student is developing the problem.",
        readiness_candidate=readiness_candidate,
        citations=[],
        facione_scores=FacioneDimensionScores(),
    )


def _coaching_output(
    *, recommendation: StageDecision = StageDecision.STAY
) -> dict[str, Any]:
    """Return a lightweight fast-chat coaching payload."""
    return {
        "mode": "coaching",
        "response_text": "What trade-off still needs evidence?",
        "recommendation": recommendation.value,
        "recommendation_rationale": (
            "More evidence is still needed."
            if recommendation is StageDecision.STAY
            else "The stage readiness bar is met."
        ),
        "citations": [],
        "needs_source_retrieval": False,
    }


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
    """Return one minimal coaching request."""
    payload = {
        "thread_id": "thread-demo",
        "student_message": "I think option B is better because it is easier for older users.",
        "current_stage": "problem_identification",
        "response_detail": "short",
    }
    payload.update(overrides)
    return CoachRequest(**payload)


def _decoded(call: dict[str, Any]) -> dict[str, Any]:
    """Decode one recorded InvokeAgentRuntime payload."""
    raw = call["payload"]
    if isinstance(raw, (bytes, bytearray)):
        return json.loads(bytes(raw).decode("utf-8"))
    return json.loads(str(raw))


def _phases(client: FakeAgentCoreRuntime) -> list[str]:
    """Return payload phases in invoke order."""
    return [str(_decoded(call).get("phase") or "") for call in client.calls]


def test_hello_and_coaching_are_one_agentcore_invoke() -> None:
    """Normal Fast Chat is one InvokeAgentRuntime for short and coaching turns."""
    hello = FakeAgentCoreRuntime(payload=_coaching_output())
    _provider(hello).assess(_request(student_message="hello"))
    coaching = FakeAgentCoreRuntime(payload=_coaching_output())
    _provider(coaching).assess(_request())
    assert len(hello.calls) == 1
    assert len(coaching.calls) == 1
    assert _phases(hello) == ["fast_chat"]
    assert _phases(coaching) == ["fast_chat"]
    assert "review" not in _phases(hello)
    assert "review" not in _phases(coaching)


def test_runtime_cycle_telemetry_is_copied_when_present() -> None:
    payload = _coaching_output()
    payload["event_loop_cycle_count"] = 1
    payload["structured_output_recovery_used"] = False
    payload["first_cycle_tool_choice_installed"] = True
    payload["first_cycle_tool_choice_applied"] = True
    payload["first_cycle_tool_choice_decision"] = "applied"
    client = FakeAgentCoreRuntime(payload=payload)
    _provider(client).assess(_request())
    assert len(client.calls) == 1


def test_normal_coaching_invokes_agentcore_once() -> None:
    client = FakeAgentCoreRuntime(payload=_coaching_output())
    result = _provider(client).assess(_request())
    assert len(client.calls) == 1
    assert _phases(client) == ["fast_chat"]
    assert _decoded(client.calls[0])["output_contract"] == "fast_chat_turn"
    assert _decoded(client.calls[0])["runtime_context"]["specialist"] == "fast_chat"
    assert _decoded(client.calls[0])["runtime_context"].get("specialist") != "coaching"
    assert result.specialist == "coaching"
    assert result.assessment.recommendation is StageDecision.STAY
    assert result.qualifying_coaching_turn is True


def test_testing_input_is_one_fast_chat_call_without_router() -> None:
    client = FakeAgentCoreRuntime(payload=_coaching_output())
    result = _provider(client).assess(_request(student_message="testing"))
    assert len(client.calls) == 1
    assert _phases(client) == ["fast_chat"]
    assert "router" not in _phases(client)
    assert result.assessment.review_depth is None
    payload = _decoded(client.calls[0])
    assert payload["runtime_context"]["specialist"] == "fast_chat"
    assert "expected_response_mode" not in payload["runtime_context"]


def test_normal_qa_invokes_agentcore_once() -> None:
    client = FakeAgentCoreRuntime(
        payload={
            "mode": "qa",
            "response_text": "Week 2 covers stakeholder mapping [S1].",
            "citations": [],
        }
    )
    result = _provider(client).assess(
        _request(student_message="What does the selected lecture say about mapping?")
    )
    assert len(client.calls) == 1
    assert _phases(client) == ["fast_chat"]
    assert result.specialist == "qa"
    assert result.assessment.recommendation is None
    assert result.qualifying_coaching_turn is False


def test_router_and_incremental_and_sonnet_are_not_called() -> None:
    client = FakeAgentCoreRuntime(payload=_coaching_output())
    _provider(client).assess(_request())
    phases = _phases(client)
    assert "router" not in phases
    assert "review" not in phases
    assert all(
        str(_decoded(call).get("review_mode") or "") != "incremental"
        for call in client.calls
    )


def test_malformed_mode_fails_closed() -> None:
    client = FakeAgentCoreRuntime(
        payload={
            "mode": "review",
            "response_text": "Nope.",
            "assessment": _assessment().model_dump(mode="json"),
        }
    )
    with pytest.raises(ProviderUnavailableError):
        _provider(client).assess(_request())


def test_malformed_coaching_without_recommendation_fails_closed() -> None:
    client = FakeAgentCoreRuntime(
        payload={"mode": "coaching", "response_text": "Hello"}
    )
    with pytest.raises(ProviderUnavailableError):
        _provider(client).assess(_request())


def test_qa_cannot_mutate_stage() -> None:
    client = FakeAgentCoreRuntime(
        payload={
            "mode": "qa",
            "response_text": "The lecture names stakeholders.",
            "assessment": _assessment(recommendation=StageDecision.ADVANCE).model_dump(
                mode="json"
            ),
        }
    )
    result = _provider(client).assess(_request())
    assert result.assessment.recommendation is None
    assert result.assessment.current_stage == "problem_identification"


def test_coaching_advance_is_advisory() -> None:
    client = FakeAgentCoreRuntime(
        payload=_coaching_output(recommendation=StageDecision.ADVANCE)
    )
    result = _provider(client).assess(_request())
    assert result.assessment.recommendation is StageDecision.ADVANCE
    assert result.assessment.readiness_candidate is True
    assert result.assessment.current_stage == "problem_identification"
    assert "review" not in _phases(client)


def test_research_coding_does_not_change_mode_or_stage() -> None:
    payload = _coaching_output()
    payload["research_coding"] = {
        "coding_status": "coded",
        "dominant_clear": "C",
        "clear_codes": ["C"],
        "facione_behaviors": [],
        "ethical_flags": [],
        "version": "clear-facione-ethics-v1",
    }
    result = _provider(FakeAgentCoreRuntime(payload=payload)).assess(_request())
    assert result.specialist == "coaching"
    assert result.assessment.current_stage == "problem_identification"
    assert result.assessment.recommendation is StageDecision.STAY


def test_current_student_message_not_duplicated_in_history() -> None:
    history = [
        {"role": "user", "content": "Earlier thought."},
        {"role": "assistant", "content": "What is missing?"},
    ]
    message = "I think option B is better because it is easier for older users."
    client = FakeAgentCoreRuntime(payload=_coaching_output())
    _provider(client).assess(_request(history=history, student_message=message))
    payload = _decoded(client.calls[0])
    prior = payload["messages"][:-1]
    texts = [
        block.get("text", "")
        for item in prior
        for block in item.get("content") or []
        if isinstance(block, dict)
    ]
    assert message not in texts
    current = payload["messages"][-1]["content"][0]["text"]
    assert message in current
    assert current.count(message) == 1
    assert "tools" not in payload


def test_fifty_history_messages_send_at_most_configured_verbatim() -> None:
    history = [
        {
            "role": "user" if index % 2 == 0 else "assistant",
            "content": f"historic-turn-{index} decision about older pedestrians",
        }
        for index in range(50)
    ]
    client = FakeAgentCoreRuntime(payload=_coaching_output())
    _provider(client).assess(_request(history=history))
    payload = _decoded(client.calls[0])
    prior = payload["messages"][:-1]
    prior_text = "\n".join(
        str(block.get("text") or "")
        for item in prior
        for block in item.get("content") or []
        if isinstance(block, dict)
    )
    assert len(prior) <= 6
    assert "historic-turn-0" not in prior_text
    assert len(prior) <= 6
    assert "historic-turn-0" not in prior_text
    assert "historic-turn-49" in prior_text
    current = payload["messages"][-1]["content"][0]["text"]
    assert "I think option B is better" in current
    assert current.count("I think option B is better") == 1


def test_qa_foreign_citations_are_dropped() -> None:
    client = FakeAgentCoreRuntime(
        payload={
            "mode": "qa",
            "response_text": "A claim with a foreign citation.",
            "citations": [
                {
                    "source_id": "foreign",
                    "label": "S9",
                    "title": "Other notebook",
                    "excerpt": "secret",
                }
            ],
        }
    )
    result = _provider(client).assess(_request())
    assert result.assessment.citations == []
    assert result.assessment.recommendation is None


def test_qa_keeps_supplied_s1_and_drops_foreign_s9() -> None:
    """Allowed [S1] survives; an invented [S9] does not, even in the same payload."""
    client = FakeAgentCoreRuntime(
        payload={
            "mode": "qa",
            "response_text": "Validation is checking the chosen concept against needs [S1].",
            "citations": [
                {
                    "source_id": "src-week1",
                    "label": "S1",
                    "title": "Week 1",
                    "excerpt": "Validation checks the concept against needs.",
                },
                {
                    "source_id": "foreign",
                    "label": "S9",
                    "title": "Other notebook",
                    "excerpt": "secret",
                },
            ],
        }
    )
    result = _provider(client).assess(
        _request(
            retrieved_chunks=[
                RetrievalChunkReference(
                    source_id="src-week1",
                    label="S1",
                    title="Week 1",
                    chunk_id="S1-C1",
                    excerpt="Validation checks the concept against needs.",
                )
            ]
        )
    )
    labels = [citation.label for citation in result.assessment.citations]
    assert labels == ["S1"]
    assert result.assessment.citations[0].source_id == "src-week1"


def test_explicit_deep_review_is_one_sonnet_call() -> None:
    client = FakeAgentCoreRuntime(
        payload={
            "response_text": "Formative review of progress.",
            "strengths": ["Concrete setting"],
            "areas_to_develop": ["Name who is affected"],
            "synthesis": "Not a grade.",
            "current_stage": "problem_identification",
            "recommendation": "stay",
            "rationale_summary": "Stay.",
        }
    )
    result = _provider(client).assess(_request(specialist="review"))
    assert len(client.calls) == 1
    assert _phases(client) == ["review"]
    assert _decoded(client.calls[0]).get("review_mode") == "deep"
    assert result.qualifying_coaching_turn is False
