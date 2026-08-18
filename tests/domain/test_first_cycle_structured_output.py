"""Deterministic first-cycle structured-output helpers. No Strands or AWS."""

from __future__ import annotations

import ast
from pathlib import Path
from types import SimpleNamespace

from agentcore_runtime.structured_coach import (
    FAST_CHAT_INVOKE_LIMITS,
    FIRST_CYCLE_FORCE_ROLES,
    FIRST_CYCLE_STRUCTURED_OUTPUT_TOOL_CHOICE,
    apply_first_cycle_tool_choice,
    classify_structured_output_recovery,
    first_cycle_tool_choice_decision,
    recovery_used_from_cycle_count,
    sanitize_stop_reason,
    stamp_structured_output_telemetry,
)


def test_first_cycle_tool_choice_matches_strands_forced_mode_default() -> None:
    """Cycle 1 uses the same ``any`` constraint Strands recovery would set."""
    assert FIRST_CYCLE_FORCE_ROLES == frozenset({"fast_chat"})
    assert FIRST_CYCLE_STRUCTURED_OUTPUT_TOOL_CHOICE == {"any": {}}
    assert apply_first_cycle_tool_choice(None, [{"name": "FastChatTurnOutput"}]) == {
        "any": {}
    }
    choice, category = first_cycle_tool_choice_decision(
        None, [{"name": "FastChatTurnOutput"}], role="fast_chat"
    )
    assert choice == {"any": {}}
    assert category == "applied"


def test_first_cycle_tool_choice_does_not_override_forced_mode() -> None:
    existing = {"tool": {"name": "FastChatTurnOutput"}}
    assert apply_first_cycle_tool_choice(existing, [{"name": "FastChatTurnOutput"}]) is existing


def test_first_cycle_tool_choice_skips_when_no_tools() -> None:
    assert apply_first_cycle_tool_choice(None, []) is None
    assert apply_first_cycle_tool_choice(None, None) is None


def test_first_cycle_tool_choice_skips_unexpected_multiple_tools() -> None:
    specs = [{"name": "FastChatTurnOutput"}, {"name": "web_search"}]
    assert apply_first_cycle_tool_choice(None, specs) is None
    _choice, category = first_cycle_tool_choice_decision(None, specs, role="fast_chat")
    assert category == "unexpected_tool_count"


def test_first_cycle_tool_choice_skips_non_fast_chat_roles() -> None:
    specs = [{"name": "ReviewTurnOutput"}]
    assert apply_first_cycle_tool_choice(None, specs, role="review_deep") is None
    _choice, category = first_cycle_tool_choice_decision(
        None, specs, role="review_deep"
    )
    assert category == "role_not_fast_chat"


def test_recovery_classification_is_category_only() -> None:
    assert recovery_used_from_cycle_count(None) is None
    assert recovery_used_from_cycle_count(1) is False
    assert recovery_used_from_cycle_count(2) is True
    assert classify_structured_output_recovery(cycle_count=1) == ""
    assert (
        classify_structured_output_recovery(
            first_cycle_stop_reason="end_turn",
            cycle_count=2,
        )
        == "end_turn_without_output_tool"
    )
    assert (
        classify_structured_output_recovery(
            first_cycle_stop_reason="max_tokens",
            cycle_count=2,
        )
        == "max_tokens"
    )
    assert (
        classify_structured_output_recovery(
            first_cycle_stop_reason="tool_use",
            cycle_count=2,
        )
        == "invalid_or_incomplete_tool"
    )
    assert sanitize_stop_reason("Please use the output tool now.") == ""
    assert sanitize_stop_reason("end_turn") == "end_turn"


def test_stamp_omits_recovery_when_metrics_absent() -> None:
    payload: dict[str, object] = {}
    stamp_structured_output_telemetry(
        payload, cycle_count=None, first_cycle_stop_reason="end_turn"
    )
    assert "structured_output_recovery_used" not in payload
    assert payload["first_cycle_stop_reason"] == "end_turn"
    stamp_structured_output_telemetry(payload, cycle_count=1)
    assert payload["event_loop_cycle_count"] == 1
    assert payload["structured_output_recovery_used"] is False
    assert "structured_output_failure_category" not in payload
    stamp_structured_output_telemetry(
        payload, cycle_count=1, first_cycle_tool_choice_installed=True
    )
    assert payload["first_cycle_tool_choice_installed"] is True


def test_stamp_records_recovery_without_student_text() -> None:
    payload: dict[str, object] = {}
    stamp_structured_output_telemetry(
        payload,
        cycle_count=2,
        first_cycle_stop_reason="end_turn",
    )
    assert payload["structured_output_recovery_used"] is True
    assert payload["structured_output_failure_category"] == (
        "end_turn_without_output_tool"
    )
    assert "student" not in str(payload).lower()


def test_turns_two_recovery_cap_is_unchanged() -> None:
    assert FAST_CHAT_INVOKE_LIMITS == {"turns": 2}


def test_structured_role_invoke_installs_first_cycle_middleware() -> None:
    source = Path("agentcore_runtime/main.py").read_text(encoding="utf-8")
    invoke = source.split("async def _structured_role_invoke", 1)[1].split(
        "async def specialist_invoke", 1
    )[0]
    assert invoke.index("agent = Agent(") < invoke.index(
        "_install_first_cycle_structured_output("
    )
    assert invoke.index("_install_first_cycle_structured_output(") < invoke.index(
        "invoke_async"
    )
    assert "role=role" in invoke
    assert "turns=1" not in invoke
    assert "structured_output_limits_for_role(role)" in invoke


def test_install_helper_is_a_noop_without_strands_middleware() -> None:
    from agentcore_runtime.main import _install_first_cycle_structured_output

    assert _install_first_cycle_structured_output(
        SimpleNamespace(), role="fast_chat"
    ) is False


def test_install_helper_survives_registry_exceptions(monkeypatch) -> None:
    """A broken middleware registry must not crash the student request."""
    import sys
    from types import ModuleType

    from agentcore_runtime.main import _install_first_cycle_structured_output

    strands = ModuleType("strands")
    middleware = ModuleType("strands._middleware")
    stages = ModuleType("strands._middleware.stages")
    stages.InvokeModelStage = SimpleNamespace(Input="input")
    monkeypatch.setitem(sys.modules, "strands", strands)
    monkeypatch.setitem(sys.modules, "strands._middleware", middleware)
    monkeypatch.setitem(sys.modules, "strands._middleware.stages", stages)

    def _boom(*_args: object, **_kwargs: object) -> None:
        raise RuntimeError("middleware registry exploded")

    agent = SimpleNamespace(
        _middleware_registry=SimpleNamespace(add_middleware=_boom)
    )
    assert _install_first_cycle_structured_output(agent, role="fast_chat") is False


def test_install_helper_skips_deep_review_even_with_a_registry() -> None:
    from agentcore_runtime.main import _install_first_cycle_structured_output

    added: list[object] = []
    agent = SimpleNamespace(
        _middleware_registry=SimpleNamespace(
            add_middleware=lambda *args, **kwargs: added.append((args, kwargs))
        )
    )
    assert _install_first_cycle_structured_output(agent, role="review_deep") is False
    assert added == []


def test_main_still_has_one_invoke_async_call() -> None:
    tree = ast.parse(
        Path("agentcore_runtime/main.py").read_text(encoding="utf-8"),
        filename="agentcore_runtime/main.py",
    )
    calls = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "invoke_async"
    ]
    assert len(calls) == 1
