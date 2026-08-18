"""Network-free Strands 1.52.0 first-cycle tool_choice integration.

Companion pytest skips this file when ``strands`` is absent. The
``agentcore-runtime-compatibility`` job installs the pinned runtime extras
and runs it. No AWS, Bedrock, or student content.
"""

from __future__ import annotations

import asyncio
import json
from typing import Any, AsyncIterator

import pytest

pytest.importorskip("strands")

from pydantic import BaseModel
from strands import Agent
from strands.models.model import Model

from agentcore_runtime.main import _install_first_cycle_structured_output
from agentcore_runtime.structured_coach import (
    FAST_CHAT_INVOKE_LIMITS,
    STRUCTURED_OUTPUT_REPAIR_PROMPT,
    event_loop_cycle_count_from_agent_result,
    first_cycle_tool_choice_decision,
)


class TinyFastChatOut(BaseModel):
    """Minimal structured Fast Chat shape for the fake model."""

    mode: str
    response_text: str
    recommendation: str | None = None
    needs_source_retrieval: bool = False


_VALID_OUTPUT = {
    "mode": "coaching",
    "response_text": "Which constraint is actually binding?",
    "recommendation": "stay",
    "needs_source_retrieval": False,
}


def _usage() -> dict[str, Any]:
    """Return a Strands metadata usage block."""
    return {
        "usage": {
            "inputTokens": 8,
            "outputTokens": 12,
            "totalTokens": 20,
        },
        "metrics": {"latencyMs": 1},
    }


def _tool_use_events(tool_specs: list[Any] | None) -> list[dict[str, Any]]:
    """Return Bedrock-shaped stream events that invoke the structured tool."""
    name = "TinyFastChatOut"
    if tool_specs:
        first = tool_specs[0]
        if isinstance(first, dict) and first.get("name"):
            name = str(first["name"])
    payload = json.dumps(_VALID_OUTPUT)
    return [
        {"messageStart": {"role": "assistant"}},
        {
            "contentBlockStart": {
                "start": {"toolUse": {"toolUseId": "tu-1", "name": name}}
            }
        },
        {"contentBlockDelta": {"delta": {"toolUse": {"input": payload}}}},
        {"contentBlockStop": {}},
        {"messageStop": {"stopReason": "tool_use"}},
        {"metadata": _usage()},
    ]


def _prose_events() -> list[dict[str, Any]]:
    """Return cycle-1 prose that omits the structured-output tool."""
    return [
        {"messageStart": {"role": "assistant"}},
        {
            "contentBlockDelta": {
                "delta": {"text": "Which constraint is actually binding?"}
            }
        },
        {"contentBlockStop": {}},
        {"messageStop": {"stopReason": "end_turn"}},
        {"metadata": _usage()},
    ]


class RecordingModel(Model):
    """Record ``tool_choice`` and emit scripted Converse stream events."""

    def __init__(self, *, recover_after_prose: bool = False) -> None:
        self.calls: list[dict[str, Any]] = []
        self.config: dict[str, Any] = {"model_id": "fake-haiku"}
        self._recover_after_prose = recover_after_prose

    def update_config(self, **model_config: Any) -> None:
        self.config.update(model_config)

    def get_config(self) -> dict[str, Any]:
        return dict(self.config)

    async def structured_output(
        self,
        output_model: type[BaseModel],
        prompt: Any,
        system_prompt: str | None = None,
        **kwargs: Any,
    ) -> AsyncIterator[dict[str, Any]]:
        del output_model, prompt, system_prompt, kwargs
        raise NotImplementedError("tests use invoke_async structured_output_model")
        yield {}  # pragma: no cover

    async def stream(
        self,
        messages: Any,
        tool_specs: list[Any] | None = None,
        system_prompt: str | None = None,
        *,
        tool_choice: Any = None,
        **kwargs: Any,
    ) -> AsyncIterator[dict[str, Any]]:
        del messages, system_prompt, kwargs
        self.calls.append(
            {
                "tool_choice": tool_choice,
                "tool_count": len(list(tool_specs or [])),
            }
        )
        if self._recover_after_prose and len(self.calls) == 1:
            events = _prose_events()
        else:
            events = _tool_use_events(tool_specs)
        for event in events:
            yield event


def _invoke(
    model: RecordingModel,
    *,
    install: bool,
    cycle_state: dict[str, Any] | None = None,
) -> Any:
    """Run one Fast Chat structured invoke against the fake model."""
    agent = Agent(
        model=model,
        tools=[],
        system_prompt="Return the structured Fast Chat result.",
        callback_handler=None,
        load_tools_from_directory=False,
    )
    if install:
        assert (
            _install_first_cycle_structured_output(
                agent, role="fast_chat", cycle_state=cycle_state
            )
            is True
        )
    return asyncio.run(
        agent.invoke_async(
            "Older pedestrians may not have enough time to cross.",
            structured_output_model=TinyFastChatOut,
            structured_output_prompt=STRUCTURED_OUTPUT_REPAIR_PROMPT,
            limits=FAST_CHAT_INVOKE_LIMITS,
        )
    )


def test_fast_chat_first_model_call_receives_forced_tool_choice() -> None:
    """Valid first-cycle structured output uses tool_choice any and one cycle."""
    model = RecordingModel()
    cycle_state: dict[str, Any] = {}
    result = _invoke(model, install=True, cycle_state=cycle_state)
    assert model.calls, "the fake model was never invoked"
    assert model.calls[0]["tool_choice"] == {"any": {}}
    assert model.calls[0]["tool_count"] == 1
    assert len(model.calls) == 1
    cycles = event_loop_cycle_count_from_agent_result(result)
    assert cycles == 1
    assert cycle_state["applied"] is True
    assert cycle_state["decision"] == "applied"
    output = getattr(result, "structured_output", None)
    assert output is not None
    assert output.mode == "coaching"


def test_invalid_first_cycle_uses_bounded_recovery() -> None:
    """Prose on cycle 1 still recovers once; Fast Chat stays at turns=2."""
    model = RecordingModel(recover_after_prose=True)
    cycle_state: dict[str, Any] = {}
    result = _invoke(model, install=True, cycle_state=cycle_state)
    assert len(model.calls) == 2
    assert model.calls[0]["tool_choice"] == {"any": {}}
    assert model.calls[1]["tool_choice"] == {"any": {}}
    cycles = event_loop_cycle_count_from_agent_result(result)
    assert cycles == 2
    assert cycle_state["applied"] is True
    assert cycle_state["decision"] == "applied"
    output = getattr(result, "structured_output", None)
    assert output is not None
    assert FAST_CHAT_INVOKE_LIMITS == {"turns": 2}


def test_middleware_unavailable_keeps_voluntary_tool_choice() -> None:
    """Missing Strands middleware must not crash; cycle 1 stays voluntary."""
    from types import SimpleNamespace

    cycle_state: dict[str, Any] = {}
    assert (
        _install_first_cycle_structured_output(
            SimpleNamespace(), role="fast_chat", cycle_state=cycle_state
        )
        is False
    )
    assert cycle_state["applied"] is False
    assert cycle_state["decision"] == "middleware_unavailable"
    model = RecordingModel()
    _invoke(model, install=False)
    assert model.calls[0]["tool_choice"] is None


def test_unexpected_multiple_tools_are_not_forced() -> None:
    """Do not blindly apply any when extra application tools appear."""
    specs = [{"name": "TinyFastChatOut"}, {"name": "web_search"}]
    choice, category = first_cycle_tool_choice_decision(
        None, specs, role="fast_chat"
    )
    assert choice is None
    assert category == "unexpected_tool_count"


def test_deep_review_does_not_install_fast_chat_force() -> None:
    """Sonnet Deep Review must not receive the Fast Chat cycle-1 force."""
    from types import SimpleNamespace

    from agentcore_runtime.structured_coach import stamp_structured_output_telemetry

    added: list[object] = []
    agent = SimpleNamespace(
        _middleware_registry=SimpleNamespace(
            add_middleware=lambda *args, **kwargs: added.append((args, kwargs))
        )
    )
    cycle_state: dict[str, Any] = {}
    assert (
        _install_first_cycle_structured_output(
            agent, role="review_deep", cycle_state=cycle_state
        )
        is False
    )
    assert added == []
    assert cycle_state == {}
    model = RecordingModel()
    review_agent = Agent(
        model=model,
        tools=[],
        system_prompt="Return a formative review.",
        callback_handler=None,
        load_tools_from_directory=False,
    )
    assert _install_first_cycle_structured_output(review_agent, role="review_deep") is False
    asyncio.run(
        review_agent.invoke_async(
            "Summarise progress.",
            structured_output_model=TinyFastChatOut,
            structured_output_prompt=STRUCTURED_OUTPUT_REPAIR_PROMPT,
            limits={"turns": 3},
        )
    )
    assert model.calls[0]["tool_choice"] is None
    payload: dict[str, Any] = {}
    stamp_structured_output_telemetry(
        payload,
        cycle_count=1,
        first_cycle_tool_choice_installed=None,
        first_cycle_tool_choice_applied=None,
        first_cycle_tool_choice_decision=None,
    )
    assert "first_cycle_tool_choice_applied" not in payload
    assert "first_cycle_tool_choice_installed" not in payload
