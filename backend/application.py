"""Backward-compatible coaching application façade."""

from backend.coaching.execution import (
    CoachApplicationService,
    _coach_request_fingerprint,
)

__all__ = ["CoachApplicationService", "_coach_request_fingerprint"]
