"""Compatibility wrapper. Deep Review replaced the Stage Judge authority."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

try:
    from models import ReviewTurnOutput, parse_review_turn_output
    from prompts.loader import load_review_deep_prompt
    from structured_coach import last_user_text, structured_from_agent_result
except ImportError:  # pragma: no cover
    from agentcore_runtime.models import ReviewTurnOutput, parse_review_turn_output
    from agentcore_runtime.prompts.loader import load_review_deep_prompt
    from agentcore_runtime.structured_coach import last_user_text, structured_from_agent_result


def stage_judge_system_prompt() -> str:
    """Return the Deep Review prompt used for leftover judge-shaped invokes."""
    return load_review_deep_prompt()


def stage_judge_user_prompt(payload: Mapping[str, Any] | None) -> str:
    """Return the current-turn text for a leftover judge-shaped invoke."""
    return last_user_text(payload)


def stage_judge_output_from_agent_result(result: Any) -> ReviewTurnOutput:
    """Parse leftover judge-shaped output as Deep Review."""
    return structured_from_agent_result(result, parse_review_turn_output)


def stage_judge_output_text(output: ReviewTurnOutput) -> str:
    """Return student-visible Deep Review text for output guardrails."""
    return str(output.response_text or "").strip()
