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
    "citations": [],
    "hmw_scaffold_ready": False,
    "needs_source_retrieval": False,
    "out_of_scope": False,
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
                "tool_names": [
                    spec.get("name") if isinstance(spec, dict) else None
                    for spec in list(tool_specs or [])
                ],
                "tool_schema_types": [
                    ((spec.get("inputSchema") or {}).get("json") or {}).get("type")
                    if isinstance(spec, dict)
                    else None
                    for spec in list(tool_specs or [])
                ],
                "tool_schema_has_top_one_of": [
                    "oneOf" in ((spec.get("inputSchema") or {}).get("json") or {})
                    if isinstance(spec, dict)
                    else False
                    for spec in list(tool_specs or [])
                ],
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


def _flatten_schema_allows(schema: dict[str, Any], instance: dict[str, Any]) -> bool:
    """Return whether a flattened Bedrock object schema accepts ``instance``."""
    required = schema.get("required") or []
    if any(key not in instance for key in required):
        return False
    properties = schema.get("properties") or {}
    for key, subschema in properties.items():
        if key not in instance:
            continue
        value = instance[key]
        expected = subschema.get("type")
        if expected is not None:
            names = expected if isinstance(expected, list) else [expected]
            if value is None:
                actual = "null"
            elif isinstance(value, str):
                actual = "string"
            elif isinstance(value, bool):
                actual = "boolean"
            elif isinstance(value, list):
                actual = "array"
            elif isinstance(value, dict):
                actual = "object"
            else:
                actual = type(value).__name__
            if actual not in names:
                return False
        if "enum" in subschema and value not in subschema["enum"]:
            return False
        if "anyOf" in subschema:
            options = subschema["anyOf"]
            if not any(
                (opt.get("type") == "null" and value is None)
                or (
                    value in (opt.get("enum") or [])
                    if "enum" in opt
                    else opt.get("type") == "string" and isinstance(value, str)
                )
                for opt in options
            ):
                return False
    if_schema = schema.get("if")
    then_schema = schema.get("then")
    if if_schema and then_schema:
        mode_ok = instance.get("mode") == (if_schema.get("properties") or {}).get(
            "mode", {}
        ).get("const")
        if mode_ok:
            then_required = then_schema.get("required") or []
            if any(key not in instance for key in then_required):
                return False
            then_props = then_schema.get("properties") or {}
            rec_schema = then_props.get("recommendation") or {}
            rec = instance.get("recommendation")
            if "enum" in rec_schema and rec not in rec_schema["enum"]:
                return False
            if rec_schema.get("type") == "string" and not isinstance(rec, str):
                return False
    return True


def test_fast_chat_turn_output_is_one_strands_object_tool() -> None:
    """Strands 1.52.0 must emit one FastChatTurnOutput object schema, not a union."""
    from strands.tools.structured_output.structured_output_utils import (
        convert_pydantic_to_tool_spec,
    )

    from agentcore_runtime.models import FastChatTurnOutput

    spec = convert_pydantic_to_tool_spec(FastChatTurnOutput)
    assert spec["name"] == "FastChatTurnOutput"
    schema = spec["inputSchema"]["json"]
    assert schema.get("type") == "object"
    assert "oneOf" not in schema
    assert "anyOf" not in schema
    citations = (schema.get("properties") or {}).get("citations") or {}
    assert citations.get("type") == "array"
    assert "null" not in str(citations.get("type"))
    assert "citations" in (schema.get("required") or [])
    hmw_ready = (schema.get("properties") or {}).get("hmw_scaffold_ready") or {}
    assert hmw_ready.get("type") == "boolean"
    assert "null" not in str(hmw_ready.get("type"))
    assert "hmw_scaffold_ready" in (schema.get("required") or [])
    coaching_null = {
        "mode": "coaching",
        "response_text": "Which constraint is actually binding?",
        "recommendation": None,
        "citations": [],
        "hmw_scaffold_ready": False,
    }
    coaching_stay = {
        "mode": "coaching",
        "response_text": "Which constraint is actually binding?",
        "recommendation": "stay",
        "citations": [],
        "hmw_scaffold_ready": False,
    }
    coaching_citations_null = {
        "mode": "coaching",
        "response_text": "Which constraint is actually binding?",
        "recommendation": "stay",
        "citations": None,
        "hmw_scaffold_ready": False,
    }
    qa_null = {
        "mode": "qa",
        "response_text": "Week 1 covers innovation.",
        "recommendation": None,
        "citations": [],
        "hmw_scaffold_ready": False,
    }
    assert _flatten_schema_allows(schema, coaching_stay)
    assert not _flatten_schema_allows(schema, coaching_null)
    assert not _flatten_schema_allows(schema, coaching_citations_null)
    if "if" in schema:
        assert _flatten_schema_allows(schema, qa_null)
    else:
        # Flatten may drop if/then. Enum without null still blocks coaching
        # null. Q&A null remains valid on the Pydantic model.
        rec = (schema.get("properties") or {}).get("recommendation") or {}
        assert "stay" in (rec.get("enum") or [])
        FastChatTurnOutput.model_validate(qa_null)


def test_fast_chat_turn_output_agent_keeps_first_cycle_force() -> None:
    """Production FastChatTurnOutput still gets cycle-1 tool_choice any."""
    from agentcore_runtime.models import FastChatTurnOutput

    class FastChatRecordingModel(RecordingModel):
        """Emit a valid FastChatTurnOutput tool payload."""

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
            specs = list(tool_specs or [])
            self.calls.append(
                {
                    "tool_choice": tool_choice,
                    "tool_count": len(specs),
                    "tool_names": [
                        spec.get("name") if isinstance(spec, dict) else None
                        for spec in specs
                    ],
                }
            )
            name = "FastChatTurnOutput"
            if specs and isinstance(specs[0], dict) and specs[0].get("name"):
                name = str(specs[0]["name"])
            payload = json.dumps(
                {
                    "mode": "coaching",
                    "response_text": "Which constraint is actually binding?",
                    "recommendation": "stay",
                    "citations": [],
                }
            )
            events = [
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
            for event in events:
                yield event

    model = FastChatRecordingModel()
    cycle_state: dict[str, Any] = {}
    agent = Agent(
        model=model,
        tools=[],
        system_prompt="Return the structured Fast Chat result.",
        callback_handler=None,
        load_tools_from_directory=False,
    )
    assert (
        _install_first_cycle_structured_output(
            agent, role="fast_chat", cycle_state=cycle_state
        )
        is True
    )
    result = asyncio.run(
        agent.invoke_async(
            "Older pedestrians may not have enough time to cross.",
            structured_output_model=FastChatTurnOutput,
            structured_output_prompt=STRUCTURED_OUTPUT_REPAIR_PROMPT,
            limits=FAST_CHAT_INVOKE_LIMITS,
        )
    )
    assert model.calls[0]["tool_choice"] == {"any": {}}
    assert model.calls[0]["tool_count"] == 1
    assert model.calls[0]["tool_names"] == ["FastChatTurnOutput"]
    assert cycle_state["applied"] is True
    assert cycle_state["decision"] == "applied"
    output = getattr(result, "structured_output", None)
    assert isinstance(output, FastChatTurnOutput)
    assert output.recommendation == "stay"
    cycles = event_loop_cycle_count_from_agent_result(result)
    assert cycles == 1


def test_coaching_null_recovers_within_turns_two() -> None:
    """Bounded recovery still runs when cycle 1 coaching recommendation is null."""
    from agentcore_runtime.models import FastChatTurnOutput

    class RecoveringFastChatModel(RecordingModel):
        """Cycle 1 emits coaching+null; cycle 2 emits stay."""

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
            specs = list(tool_specs or [])
            self.calls.append(
                {
                    "tool_choice": tool_choice,
                    "tool_count": len(specs),
                }
            )
            name = "FastChatTurnOutput"
            if specs and isinstance(specs[0], dict) and specs[0].get("name"):
                name = str(specs[0]["name"])
            if len(self.calls) == 1:
                payload = json.dumps(
                    {
                        "mode": "coaching",
                        "response_text": "Which constraint is actually binding?",
                        "recommendation": None,
                    }
                )
            else:
                payload = json.dumps(
                    {
                        "mode": "coaching",
                        "response_text": "Which constraint is actually binding?",
                        "recommendation": "stay",
                    }
                )
            events = [
                {"messageStart": {"role": "assistant"}},
                {
                    "contentBlockStart": {
                        "start": {"toolUse": {"toolUseId": f"tu-{len(self.calls)}", "name": name}}
                    }
                },
                {"contentBlockDelta": {"delta": {"toolUse": {"input": payload}}}},
                {"contentBlockStop": {}},
                {"messageStop": {"stopReason": "tool_use"}},
                {"metadata": _usage()},
            ]
            for event in events:
                yield event

    model = RecoveringFastChatModel()
    agent = Agent(
        model=model,
        tools=[],
        system_prompt="Return the structured Fast Chat result.",
        callback_handler=None,
        load_tools_from_directory=False,
    )
    assert _install_first_cycle_structured_output(agent, role="fast_chat") is True
    result = asyncio.run(
        agent.invoke_async(
            "Older pedestrians may not have enough time to cross.",
            structured_output_model=FastChatTurnOutput,
            structured_output_prompt=STRUCTURED_OUTPUT_REPAIR_PROMPT,
            limits=FAST_CHAT_INVOKE_LIMITS,
        )
    )
    assert len(model.calls) == 2
    assert FAST_CHAT_INVOKE_LIMITS == {"turns": 2}
    output = getattr(result, "structured_output", None)
    assert isinstance(output, FastChatTurnOutput)
    assert output.recommendation == "stay"


def _scripted_fast_chat_model(payloads: list[dict[str, Any]]) -> RecordingModel:
    """Return a fake Converse model that emits successive Fast Chat tool payloads."""

    class ScriptedFastChatModel(RecordingModel):
        """Emit one scripted FastChatTurnOutput tool payload per cycle."""

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
            specs = list(tool_specs or [])
            self.calls.append(
                {
                    "tool_choice": tool_choice,
                    "tool_count": len(specs),
                }
            )
            name = "FastChatTurnOutput"
            if specs and isinstance(specs[0], dict) and specs[0].get("name"):
                name = str(specs[0]["name"])
            index = min(len(self.calls) - 1, len(payloads) - 1)
            events = [
                {"messageStart": {"role": "assistant"}},
                {
                    "contentBlockStart": {
                        "start": {
                            "toolUse": {
                                "toolUseId": f"tu-{len(self.calls)}",
                                "name": name,
                            }
                        }
                    }
                },
                {
                    "contentBlockDelta": {
                        "delta": {"toolUse": {"input": json.dumps(payloads[index])}}
                    }
                },
                {"contentBlockStop": {}},
                {"messageStop": {"stopReason": "tool_use"}},
                {"metadata": _usage()},
            ]
            for event in events:
                yield event

    return ScriptedFastChatModel()


def _invoke_scripted_fast_chat(payloads: list[dict[str, Any]]) -> Any:
    """Invoke Fast Chat with a scripted fake model. No AWS."""
    from agentcore_runtime.models import FastChatTurnOutput

    model = _scripted_fast_chat_model(payloads)
    agent = Agent(
        model=model,
        tools=[],
        system_prompt="Return the structured Fast Chat result.",
        callback_handler=None,
        load_tools_from_directory=False,
    )
    assert _install_first_cycle_structured_output(agent, role="fast_chat") is True
    result = asyncio.run(
        agent.invoke_async(
            "Older pedestrians may not have enough time to cross.",
            structured_output_model=FastChatTurnOutput,
            structured_output_prompt=STRUCTURED_OUTPUT_REPAIR_PROMPT,
            limits=FAST_CHAT_INVOKE_LIMITS,
        )
    )
    return model, result


_STAY_EMPTY_CITATIONS = {
    "mode": "coaching",
    "response_text": "What evidence would help you verify that assumption?",
    "recommendation": "stay",
    "citations": [],
}


def test_empty_citations_complete_in_one_cycle() -> None:
    """Structurally valid empty citations must not trigger recovery."""
    from agentcore_runtime.models import FastChatTurnOutput

    model, result = _invoke_scripted_fast_chat([_STAY_EMPTY_CITATIONS])
    assert len(model.calls) == 1
    output = getattr(result, "structured_output", None)
    assert isinstance(output, FastChatTurnOutput)
    assert output.citations == []
    assert output.recommendation == "stay"
    assert output.response_text == _STAY_EMPTY_CITATIONS["response_text"]
    assert event_loop_cycle_count_from_agent_result(result) == 1


def test_valid_citation_list_completes_in_one_cycle() -> None:
    """A valid CitationOutput list is accepted on cycle 1."""
    from agentcore_runtime.models import FastChatTurnOutput

    payload = {
        "mode": "qa",
        "response_text": "Week 1 covers innovation [S1].",
        "citations": [{"label": "S1", "title": "Week 1"}],
    }
    model, result = _invoke_scripted_fast_chat([payload])
    assert len(model.calls) == 1
    output = getattr(result, "structured_output", None)
    assert isinstance(output, FastChatTurnOutput)
    assert output.mode == "qa"
    assert output.citations[0].label == "S1"
    assert event_loop_cycle_count_from_agent_result(result) == 1


def test_null_citations_remain_invalid_and_recover_within_turns_two() -> None:
    """citations=null must not be normalized; bounded recovery still works."""
    from agentcore_runtime.models import FastChatTurnOutput

    model, result = _invoke_scripted_fast_chat(
        [
            {
                "mode": "coaching",
                "response_text": "What evidence would help you verify that assumption?",
                "recommendation": "stay",
                "citations": None,
            },
            _STAY_EMPTY_CITATIONS,
        ]
    )
    assert len(model.calls) == 2
    assert FAST_CHAT_INVOKE_LIMITS == {"turns": 2}
    output = getattr(result, "structured_output", None)
    assert isinstance(output, FastChatTurnOutput)
    assert output.citations == []
    assert output.recommendation == "stay"


def test_string_citations_remain_invalid_and_recover_within_turns_two() -> None:
    """A primitive citations value stays invalid; recovery still succeeds."""
    from agentcore_runtime.models import FastChatTurnOutput

    model, result = _invoke_scripted_fast_chat(
        [
            {
                "mode": "coaching",
                "response_text": "What evidence would help you verify that assumption?",
                "recommendation": "stay",
                "citations": "S1",
            },
            _STAY_EMPTY_CITATIONS,
        ]
    )
    assert len(model.calls) == 2
    output = getattr(result, "structured_output", None)
    assert isinstance(output, FastChatTurnOutput)
    assert output.citations == []


def test_object_citations_remain_invalid_and_recover_within_turns_two() -> None:
    """An object citations value stays invalid; recovery still succeeds."""
    from agentcore_runtime.models import FastChatTurnOutput

    model, result = _invoke_scripted_fast_chat(
        [
            {
                "mode": "coaching",
                "response_text": "What evidence would help you verify that assumption?",
                "recommendation": "stay",
                "citations": {},
            },
            _STAY_EMPTY_CITATIONS,
        ]
    )
    assert len(model.calls) == 2
    output = getattr(result, "structured_output", None)
    assert isinstance(output, FastChatTurnOutput)
    assert output.citations == []


def test_malformed_citation_item_remains_invalid_and_recovers() -> None:
    """A list item missing CitationOutput.label stays invalid."""
    from agentcore_runtime.models import FastChatTurnOutput

    model, result = _invoke_scripted_fast_chat(
        [
            {
                "mode": "coaching",
                "response_text": "What evidence would help you verify that assumption?",
                "recommendation": "stay",
                "citations": [{"wrong": "shape"}],
            },
            _STAY_EMPTY_CITATIONS,
        ]
    )
    assert len(model.calls) == 2
    output = getattr(result, "structured_output", None)
    assert isinstance(output, FastChatTurnOutput)
    assert output.citations == []
