"""Shared AgentCore system-prompt text for FastAPI token estimation.

Reuses the canonical specialist prompt assembler so backend estimates cannot
drift from runtime pedagogy. This module does not call Bedrock or CountTokens.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

try:
    from .structured_coach import specialist_system_prompt
except ImportError:  # pragma: no cover - flat runtime copy
    from structured_coach import specialist_system_prompt  # type: ignore


def fast_chat_system_prompt_for_estimate(
    *,
    topic: str,
    trusted_runtime_rules: str = "",
    runtime_context: Mapping[str, Any] | None = None,
) -> str:
    """Return the exact Fast Chat system prompt text the runtime would send.

    Args:
        topic: AgentCore stage topic key.
        trusted_runtime_rules: FastAPI trusted runtime instructions.
        runtime_context: Application-owned runtime constraints JSON, matching
            the payload field AgentCore appends to the trusted suffix.

    Returns:
        Canonical ``fast_chat`` system prompt including JSON contract.
    """
    payload: dict[str, Any] = {
        "phase": "fast_chat",
        "topic": str(topic or "").strip() or "problem_identification",
        "output_contract": "fast_chat_turn",
        "trusted_instructions": str(trusted_runtime_rules or "").strip(),
    }
    if isinstance(runtime_context, Mapping) and runtime_context:
        payload["runtime_context"] = dict(runtime_context)
    return specialist_system_prompt(payload)
