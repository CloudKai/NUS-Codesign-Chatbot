"""Coach-turn structured-output contract."""

from __future__ import annotations

try:
    from models import AssessmentOutput, CoachTurnOutput, parse_coach_turn_output
except ImportError:  # pragma: no cover
    from agentcore_runtime.models import (
        AssessmentOutput,
        CoachTurnOutput,
        parse_coach_turn_output,
    )

__all__ = ["AssessmentOutput", "CoachTurnOutput", "parse_coach_turn_output"]
