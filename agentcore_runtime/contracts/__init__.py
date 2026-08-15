"""Runtime structured-output contracts. Canonical models live in ``models.py``."""

from __future__ import annotations

try:
    from models import (
        AssessmentOutput,
        CitationOutput,
        CoachTurnOutput,
        FacioneScoresOutput,
        QATurnOutput,
        ReviewTurnOutput,
        parse_coach_turn_output,
    )
except ImportError:  # pragma: no cover - imported as agentcore_runtime.*
    from agentcore_runtime.models import (
        AssessmentOutput,
        CitationOutput,
        CoachTurnOutput,
        FacioneScoresOutput,
        QATurnOutput,
        ReviewTurnOutput,
        parse_coach_turn_output,
    )

__all__ = [
    "AssessmentOutput",
    "CitationOutput",
    "CoachTurnOutput",
    "FacioneScoresOutput",
    "QATurnOutput",
    "ReviewTurnOutput",
    "parse_coach_turn_output",
]
