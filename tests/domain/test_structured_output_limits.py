"""Deterministic checks that Strands 1.52.0 ``limits`` are actually passed.

NEEDS LIVE TRACE: these tests cannot prove Haiku performs one generation plus
at most one recovery. Strands is not installed in the companion venv. They
assert the invoke argument is constructed with ``turns=2`` for Fast Chat and
omitted for Deep Review.
"""

from __future__ import annotations

import ast
from pathlib import Path

from agentcore_runtime.structured_coach import (
    FAST_CHAT_INVOKE_LIMITS,
    structured_output_limits_for_role,
)


def test_fast_chat_limits_are_initial_plus_one_recovery() -> None:
    """``turns=2`` is the verified 1.52.0 value for initial + one recovery."""
    assert FAST_CHAT_INVOKE_LIMITS == {"turns": 2}
    assert structured_output_limits_for_role("fast_chat") == {"turns": 2}
    assert structured_output_limits_for_role("router") == {"turns": 2}
    assert structured_output_limits_for_role("qa") == {"turns": 2}
    assert structured_output_limits_for_role("coaching") == {"turns": 2}


def test_review_roles_are_not_capped_by_the_fast_chat_limit() -> None:
    """Deep Review must not inherit the Fast Chat turns cap."""
    assert structured_output_limits_for_role("review_deep") is None
    assert structured_output_limits_for_role("review_incremental") is None
    assert structured_output_limits_for_role("review") is None


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
