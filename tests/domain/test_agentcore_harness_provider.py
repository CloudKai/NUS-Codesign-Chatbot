"""Deterministic Luna InvokeHarness configuration and adapter tests (no AWS)."""

from __future__ import annotations

import json
from typing import Any

import pytest

from pathlib import Path

from backend.agentcore_harness_provider import (
    HARNESS_STRUCTURED_COACH_PROMPT,
    AgentCoreHarnessCoachProvider,
)
from backend.domain import CoachRequest, ProviderCoachOutput
from backend.live_eval_config import (
    LIVE_EVAL_API_FORMAT,
    LIVE_EVAL_MODEL_ID,
    LiveEvalConfigurationError,
    LiveEvalModelConfig,
    assert_live_eval_invoke_kwargs,
    live_eval_banner,
)
from backend.prompts import compose_coach_prompt
from backend.providers import ProviderUnavailableError, configured_coach_provider
from backend.settings import settings


class FakeHarness:
    """Injected InvokeHarness client that records kwargs and returns JSON."""

    def __init__(self, payload: dict[str, Any] | None = None) -> None:
        self.calls: list[dict[str, Any]] = []
        self._payload = payload or {}

    def invoke_harness(self, **kwargs: Any) -> dict[str, Any]:
        """Record one harness invocation and return a fake JSON body."""
        self.calls.append(kwargs)
        body = json.dumps(self._payload).encode("utf-8")
        return {"contentType": "application/json", "response": _FakeBody(body)}


class _FakeBody:
    def __init__(self, payload: bytes) -> None:
        self._payload = payload

    def read(self) -> bytes:
        return self._payload


def _output() -> dict[str, Any]:
    return ProviderCoachOutput.model_validate(
        {
            "response_text": "What evidence still needs checking?",
            "assessment": {
                "current_stage": "problem_identification",
                "contribution_summary": "The student framed a crossing problem.",
                "stage_assessment": "The contribution is a starting point.",
                "critical_understanding_level": "Developing",
                "confidence": 0.6,
                "recommendation": "stay",
                "recommendation_rationale": "The user group is still vague.",
                "guidance_questions": ["Who is most affected at night?"],
                "learning_summary": "The student is defining the problem.",
                "citations": [],
                "facione_scores": {"analysis": 2, "evaluation": 1},
            },
            "research_coding": None,
        }
    ).model_dump(mode="json")


def _request(**overrides: Any) -> CoachRequest:
    payload = {
        "thread_id": "thread-demo",
        "student_message": "Older pedestrians wait too long at the crossing.",
        "current_stage": "problem_identification",
        "response_detail": "short",
        "model_id": "browser-supplied-claude-sonnet",
    }
    payload.update(overrides)
    return CoachRequest(**payload)


def test_live_eval_config_rejects_non_luna_and_claude_fallback():
    with pytest.raises(Exception):
        LiveEvalModelConfig(model_id="global.anthropic.claude-sonnet-4-6")
    with pytest.raises(Exception):
        LiveEvalModelConfig(api_format="converse_stream")
    with pytest.raises(Exception):
        LiveEvalModelConfig(claude_fallback=True)
    config = LiveEvalModelConfig()
    assert config.model_id == LIVE_EVAL_MODEL_ID
    assert config.api_format == LIVE_EVAL_API_FORMAT


def test_assert_invoke_kwargs_requires_luna_override_and_no_tools():
    config = LiveEvalModelConfig()
    kwargs = {
        "harnessArn": "arn:aws:bedrock-agentcore:us-west-2:123:harness/eval",
        "runtimeSessionId": "stateless-" + ("a" * 32),
        "model": config.invoke_model_override(),
        "systemPrompt": [{"text": HARNESS_STRUCTURED_COACH_PROMPT}],
        "tools": [],
        "allowedTools": [],
        "messages": [{"role": "user", "content": [{"text": "hi"}]}],
    }
    assert_live_eval_invoke_kwargs(kwargs)
    with pytest.raises(LiveEvalConfigurationError, match="Claude"):
        assert_live_eval_invoke_kwargs(
            {
                **kwargs,
                "model": {
                    "bedrockModelConfig": {
                        "modelId": "global.anthropic.claude-sonnet-4-6",
                        "apiFormat": "responses",
                    }
                },
            }
        )
    with pytest.raises(LiveEvalConfigurationError, match="tools"):
        assert_live_eval_invoke_kwargs({**kwargs, "tools": [{"type": "shell"}]})


def test_banner_states_luna_and_unchanged_production_default():
    text = live_eval_banner()
    assert "openai.gpt-5.6-luna" in text
    assert "responses" in text
    assert "AgentCore InvokeHarness" in text
    assert "DISABLED" in text
    assert "UNCHANGED" in text


def test_harness_provider_sends_luna_override_and_ignores_request_model_id():
    client = FakeHarness(payload=_output())
    provider = AgentCoreHarnessCoachProvider(
        "arn:aws:bedrock-agentcore:us-west-2:123:harness/NUSCodesignEvalLuna",
        client=client,
    )
    result = provider.assess(_request())
    assert result.response_text.startswith("What evidence")
    assert provider.model_id_for(_request()) == LIVE_EVAL_MODEL_ID
    assert len(client.calls) == 1
    kwargs = client.calls[0]
    assert kwargs["model"]["bedrockModelConfig"]["modelId"] == LIVE_EVAL_MODEL_ID
    assert kwargs["model"]["bedrockModelConfig"]["apiFormat"] == "responses"
    assert kwargs["tools"] == []
    assert kwargs["allowedTools"] == []
    assert kwargs["maxIterations"] == 1
    assert "claude" not in json.dumps(kwargs).casefold()
    current = kwargs["messages"][-1]["content"][0]["text"]
    prepared = compose_coach_prompt(_request(), include_recent_messages=False)
    assert current == prepared.untrusted_turn_text
    assert "supplied separately as message history" in current
    system = kwargs["systemPrompt"][0]["text"]
    assert prepared.trusted_instructions in system
    assert "STAGE: PROBLEM IDENTIFICATION" in system
    assert "STAGE: PROBLEM IDENTIFICATION" not in current


def test_harness_system_prompt_stays_thin_and_matches_runtime_patch_intent():
    assert "structured Socratic reasoning" in HARNESS_STRUCTURED_COACH_PROMPT
    assert "Do not call tools" in HARNESS_STRUCTURED_COACH_PROMPT
    assert "STAGE: PROBLEM IDENTIFICATION" not in HARNESS_STRUCTURED_COACH_PROMPT
    assert "Interpret" in HARNESS_STRUCTURED_COACH_PROMPT
    patch = Path("scripts/agentcore/harness_patch/structured_coach.py").read_text(
        encoding="utf-8"
    )
    assert "Do not call tools" in patch
    assert "output_contract=coach_turn" in patch or "coach_turn" in patch
    assert "trusted_instructions" in patch


def test_configured_production_provider_is_not_the_eval_harness(
    monkeypatch: pytest.MonkeyPatch,
):
    monkeypatch.setattr(settings, "model_provider", "agentcore")
    monkeypatch.setattr(
        settings,
        "agentcore_runtime_arn",
        "arn:aws:bedrock-agentcore:us-west-2:123:runtime/prod",
    )
    provider = configured_coach_provider()
    assert provider.provider_id == "agentcore"
    assert not isinstance(provider, AgentCoreHarnessCoachProvider)


def test_harness_malformed_output_fails_closed():
    client = FakeHarness(payload={"response_text": ""})
    provider = AgentCoreHarnessCoachProvider(
        "arn:aws:bedrock-agentcore:us-west-2:123:harness/NUSCodesignEvalLuna",
        client=client,
    )
    with pytest.raises(ProviderUnavailableError, match="malformed"):
        provider.assess(_request())
