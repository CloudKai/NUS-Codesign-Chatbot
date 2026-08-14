"""Provider-neutral persistence contracts and SQLite implementation helpers."""

from backend.persistence.store.contracts import (
    AtomicAutoAdvance,
    CoachIdempotencyConflictError,
    CoachingStyleConflictError,
    CoachRequestInProgressError,
    CoachRequestLeaseLostError,
    CoachRequestReservation,
    ConversationRevisionConflictError,
    ConversationRevisionResult,
)

__all__ = [
    "AtomicAutoAdvance",
    "CoachIdempotencyConflictError",
    "CoachingStyleConflictError",
    "CoachRequestInProgressError",
    "CoachRequestLeaseLostError",
    "CoachRequestReservation",
    "ConversationRevisionConflictError",
    "ConversationRevisionResult",
]
