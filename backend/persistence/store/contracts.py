"""Stable contracts shared by SQLite, DSQL, services, and compatibility façades."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
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
        "conversation_memory",
        "coaching_turns_since_deep_review",
        "deep_review_snapshot",
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


def _parse_utc(value: str) -> datetime | None:
    """Parse an ISO-8601 stamp as an aware UTC datetime, or return ``None``.

    Accepts the ``+00:00`` form this module writes, a trailing ``Z``, and naive
    stamps (read as UTC) so comparisons stay correct for rows written by other
    writers or restored from a backup.

    Args:
        value: Candidate ISO-8601 timestamp.

    Returns:
        An aware UTC ``datetime``, or ``None`` when *value* is unparsable.
    """
    try:
        parsed = datetime.fromisoformat(str(value).strip().replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def utc_now_after(previous: str) -> str:
    """Return a UTC timestamp strictly greater than *previous*.

    Message reads order by ``created_at`` and then by the message id, which is
    a random UUID. Two rows of one turn written inside the same microsecond
    would therefore sort unpredictably, so the later row of an ordered pair is
    nudged forward instead of adding a sequence column.

    Comparison is on parsed instants rather than raw strings so a differently
    formatted *previous* (trailing ``Z``, naive, or a non-UTC offset) cannot be
    mistaken for an earlier instant and defeat the nudge.

    Args:
        previous: ISO-8601 timestamp the result must sort after.

    Returns:
        An ISO-8601 UTC timestamp strictly greater than *previous*, or the
        current time when *previous* cannot be parsed.
    """
    current = utc_now()
    anchor = _parse_utc(previous)
    if anchor is None:
        return current
    now = _parse_utc(current)
    if now is not None and now > anchor:
        return current
    return (anchor + timedelta(microseconds=1)).isoformat()


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
