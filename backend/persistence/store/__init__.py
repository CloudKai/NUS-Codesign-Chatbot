"""Provider-neutral persistence contracts and SQLite implementation helpers."""

from backend.persistence.store.contracts import (
    AutoAdvancePersistence,
    CoachIdempotencyConflictError,
    CoachingStyleConflictError,
    CoachRequestInProgressError,
    CoachRequestLeaseLostError,
    CoachRequestReservation,
    ConversationRevisionConflictError,
    ConversationRevisionResult,
)

__all__ = [
    "AutoAdvancePersistence",
    "CoachIdempotencyConflictError",
    "CoachingStyleConflictError",
    "CoachRequestInProgressError",
    "CoachRequestLeaseLostError",
    "CoachRequestReservation",
    "ConversationRevisionConflictError",
    "ConversationRevisionResult",
]
