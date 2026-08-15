"""Compatibility re-export. Canonical source: ``agentcore_runtime/``.

Live runtime copies must use ``agentcore_runtime/structured_coach.py``.
This file exists so older tests and docs that import the patch path still
resolve the same helpers.
"""

from __future__ import annotations

from agentcore_runtime.structured_coach import (
    STRUCTURED_COACH_TURN_PROMPT,
    CoachTurnExtractionError,
    coach_turn_from_agent_result,
    coaching_invoke_prompts,
    harness_error_payload,
    last_user_text,
    structured_coaching_system_prompt,
)

__all__ = [
    "STRUCTURED_COACH_TURN_PROMPT",
    "CoachTurnExtractionError",
    "coach_turn_from_agent_result",
    "coaching_invoke_prompts",
    "harness_error_payload",
    "last_user_text",
    "structured_coaching_system_prompt",
]
