"""Backward-compatible coaching application façade."""

from backend.coaching.execution import (
    CoachApplicationService,
    _coach_request_fingerprint,
    _research_observation_from_coding,
)

__all__ = [
    "CoachApplicationService",
    "_coach_request_fingerprint",
    "_research_observation_from_coding",
]
