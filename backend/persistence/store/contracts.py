"""Stable contracts shared by SQLite, DSQL, services, and compatibility façades."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, ContextManager, Protocol


COACH_IDEMPOTENCY_MARKER = "coach_idempotency"

# Progress blob keys never include current_stage; that is a notebook column.
PROGRESS_KEYS = frozenset(
    {
        "completed_stages",
        "stage_notes",
        "working_conclusion",
        "critical_reflection",
        "response_detail",
        "learning_summary",
        "understanding_change",
        "critical_understanding",
    }
)

SETTINGS_KEYS = frozenset(
    {
        "selected_model",
        "reasoning_effort",
        "support_mode",
        "assignment",
        "response_language",
        "allow_model_knowledge",
        "display_name",
        "last_workflow_user_message_id",
        "tags",
        "revoked_coach_idempotency_keys",
    }
)


class StoreContext(Protocol):
    """Narrow persistence context consumed by cohesive operation objects.

    SQLite and DSQL stores both provide this structural contract. Operations
    open connections only through the façade so DSQL's whole-method OCC retry
    boundary remains unchanged.
    """

    owner_id: str
    identifier: str
    _lock: Any

    def _connect(self) -> ContextManager[Any]:
        """Open one provider-specific database connection."""
        ...

    def get_thread(self, thread_id: str) -> dict[str, Any] | None:
        """Return one owned notebook when it exists."""
        ...


class CoachIdempotencyConflictError(ValueError):
    """Raised when one idempotency key is reused for a different request."""


class CoachRequestLeaseLostError(RuntimeError):
    """Raised when an expired reservation was claimed by another worker."""


class CoachRequestInProgressError(RuntimeError):
    """Raised when another worker still owns an active request lease."""


class ConversationRevisionConflictError(ValueError):
    """Raised when a coach result targets a stale conversation revision."""


class CoachingStyleConflictError(ConversationRevisionConflictError):
    """Raised when coaching style changes while a coach turn is in flight."""


@dataclass(frozen=True)
class AtomicAutoAdvance:
    """Confirmed stage transition applied with its completed coach turn."""

    transition_id: str
    from_stage: str
    to_stage: str
    contribution_summary: str


@dataclass(frozen=True)
class ConversationRevisionResult:
    """Authoritative notebook state after an append-only revision.

    ``edited_message_id`` is the replacement user-message id and
    ``surviving_history`` is the active branch at ``conversation_revision``.
    """

    thread_id: str
    edited_message_id: str
    conversation_revision: int
    current_stage: str
    surviving_history: list[dict[str, Any]]


@dataclass(frozen=True)
class CoachRequestReservation:
    """Durable state returned while reserving one coach request key."""

    state: str
    marker_id: str
    lease_token: str | None = None
    turn_payload: dict[str, Any] | None = None


def utc_now() -> str:
    """Return an ISO-8601 UTC timestamp string."""
    return datetime.now(timezone.utc).isoformat()


def dump_json(value: Any) -> str:
    """Serialize *value* as JSON text for database TEXT columns."""
    return json.dumps(value, ensure_ascii=False)


def load_json(value: str | None, default: Any) -> Any:
    """Deserialize JSON text, returning *default* when empty or invalid."""
    if not value:
        return default
    try:
        return json.loads(value)
    except (TypeError, json.JSONDecodeError):
        return default
