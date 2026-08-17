"""Deterministic checks that Strands 1.52.0 ``limits`` are actually passed.

NEEDS LIVE TRACE: these tests cannot prove Haiku performs one generation plus
at most one recovery. Strands is not installed in the companion venv. They
assert the invoke argument is constructed with ``turns=2`` for Fast Chat and
``turns=3`` for Deep Review, and that model-retry policy is a separate cap.
"""

from __future__ import annotations

import ast
from pathlib import Path

from agentcore_runtime.structured_coach import (
    DEEP_REVIEW_INVOKE_LIMITS,
    FAST_CHAT_INVOKE_LIMITS,
    FAST_CHAT_MODEL_RETRY,
    DEEP_REVIEW_MODEL_RETRY,
    model_retry_policy_for_role,
    structured_output_limits_for_role,
)


def test_fast_chat_limits_are_initial_plus_one_recovery() -> None:
    """``turns=2`` is the verified 1.52.0 value for initial + one recovery."""
    assert FAST_CHAT_INVOKE_LIMITS == {"turns": 2}
    assert structured_output_limits_for_role("fast_chat") == {"turns": 2}
    assert structured_output_limits_for_role("router") == {"turns": 2}
    assert structured_output_limits_for_role("qa") == {"turns": 2}
    assert structured_output_limits_for_role("coaching") == {"turns": 2}


def test_review_roles_are_capped_at_three_event_loop_turns() -> None:
    """Deep Review may repair twice; it must not inherit an unlimited loop."""
    assert DEEP_REVIEW_INVOKE_LIMITS == {"turns": 3}
    assert structured_output_limits_for_role("review_deep") == {"turns": 3}
    assert structured_output_limits_for_role("review_incremental") == {"turns": 3}
    assert structured_output_limits_for_role("review") == {"turns": 3}


def test_model_retry_policy_is_role_specific_and_finite() -> None:
    """Event-loop turns and model retries are separate finite caps."""
    haiku = model_retry_policy_for_role("fast_chat")
    assert haiku == FAST_CHAT_MODEL_RETRY
    assert haiku.max_attempts == 2
    assert haiku.initial_delay == 1
    assert haiku.max_delay == 4
    assert model_retry_policy_for_role("qa") == FAST_CHAT_MODEL_RETRY
    assert model_retry_policy_for_role("coaching") == FAST_CHAT_MODEL_RETRY
    assert model_retry_policy_for_role("review_incremental") == FAST_CHAT_MODEL_RETRY
    deep = model_retry_policy_for_role("review_deep")
    assert deep == DEEP_REVIEW_MODEL_RETRY
    assert deep.max_attempts == 3
    assert deep.initial_delay == 2
    assert deep.max_delay == 16
    assert model_retry_policy_for_role("review") == DEEP_REVIEW_MODEL_RETRY


def test_invoke_async_passes_role_limits_argument() -> None:
    """The shared structured invoke is the only Agent.invoke_async call site."""
    tree = ast.parse(
        Path("agentcore_runtime/main.py").read_text(encoding="utf-8"),
        filename="agentcore_runtime/main.py",
    )
    calls: list[ast.Call] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Attribute):
            continue
        if node.func.attr == "invoke_async":
            calls.append(node)
    assert len(calls) == 1
    keywords = {keyword.arg: keyword.value for keyword in calls[0].keywords}
    limits_node = keywords.get("limits")
    assert isinstance(limits_node, ast.Call)
    assert isinstance(limits_node.func, ast.Name)
    assert limits_node.func.id == "structured_output_limits_for_role"
    assert isinstance(limits_node.args[0], ast.Name)
    assert limits_node.args[0].id == "role"
