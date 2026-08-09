"""Bounded, privacy-preserving UI retry keys for coach submissions.

The durable idempotency decision belongs to the application service.  This
module merely keeps a short-lived client key after a disconnected Streamlit
submission, so a student can retry the same unresolved prompt safely.
"""

from __future__ import annotations

import hashlib
import math
import time
from collections.abc import Callable, MutableMapping
from typing import Any
from uuid import UUID, uuid4


RETRY_KEYS_SESSION_KEY = "coach_idempotency_keys"
RETRY_KEY_TTL_SECONDS = 60 * 60
MAX_RETRY_KEYS_PER_NOTEBOOK = 8
MAX_RETRY_KEYS_GLOBAL = 24


def _new_retry_key() -> str:
    """Create one UUID-formatted idempotency key for a new unresolved turn."""
    return str(uuid4())


def _scope_sha256(thread_id: str, stage: str, prompt: str) -> str:
    """Return the stable, non-reversible session scope for one coach turn."""
    scope = "\x00".join((thread_id, stage, prompt))
    return hashlib.sha256(scope.encode("utf-8")).hexdigest()


def _valid_key(value: Any) -> str | None:
    """Return a canonical UUID key, or ``None`` when state is malformed."""
    if not isinstance(value, str):
        return None
    try:
        return str(UUID(value))
    except (TypeError, ValueError, AttributeError):
        return None


def _valid_timestamp(value: Any, now: float) -> float | None:
    """Return an unexpired timestamp, rejecting invalid and future state."""
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        return None
    timestamp = float(value)
    if (
        not math.isfinite(timestamp)
        or timestamp > now
        or now - timestamp > RETRY_KEY_TTL_SECONDS
    ):
        return None
    return timestamp


def _record_from_value(
    scope_sha256: str,
    value: Any,
    now: float,
) -> dict[str, Any] | None:
    """Validate one persisted retry-key record without retaining prompt text."""
    if not isinstance(value, dict):
        return None
    key = _valid_key(value.get("key"))
    notebook_id = value.get("notebook_id")
    stored_scope = value.get("scope_sha256")
    created_at = _valid_timestamp(value.get("created_at"), now)
    if (
        key is None
        or not isinstance(notebook_id, str)
        or not notebook_id
        or stored_scope != scope_sha256
        or created_at is None
    ):
        return None
    return {
        "key": key,
        "notebook_id": notebook_id,
        "scope_sha256": scope_sha256,
        "created_at": created_at,
    }


def _validated_records(
    session_state: MutableMapping[str, Any],
    now: float,
) -> dict[str, dict[str, Any]]:
    """Normalize modern records and discard malformed or expired state."""
    raw = session_state.get(RETRY_KEYS_SESSION_KEY)
    if not isinstance(raw, dict):
        records: dict[str, dict[str, Any]] = {}
    else:
        records = {}
        for scope_sha256, value in raw.items():
            if not isinstance(scope_sha256, str):
                continue
            record = _record_from_value(scope_sha256, value, now)
            if record is not None:
                records[scope_sha256] = record
    session_state[RETRY_KEYS_SESSION_KEY] = records
    return records


def _apply_limits(records: dict[str, dict[str, Any]]) -> None:
    """Keep only the newest configured records per notebook and globally."""
    newest_first = sorted(
        records.items(),
        key=lambda item: (-float(item[1]["created_at"]), item[0]),
    )
    retained: dict[str, dict[str, Any]] = {}
    notebook_counts: dict[str, int] = {}
    for scope_sha256, record in newest_first:
        notebook_id = str(record["notebook_id"])
        if notebook_counts.get(notebook_id, 0) >= MAX_RETRY_KEYS_PER_NOTEBOOK:
            continue
        if len(retained) >= MAX_RETRY_KEYS_GLOBAL:
            break
        retained[scope_sha256] = record
        notebook_counts[notebook_id] = notebook_counts.get(notebook_id, 0) + 1
    records.clear()
    records.update(retained)


def prune_retry_keys(session_state: MutableMapping[str, Any], *, now: float | None = None) -> None:
    """Discard expired, malformed, and excess coach retry-key state in place.

    Args:
        session_state: Streamlit-compatible session mapping to normalize.
        now: Optional wall-clock timestamp for deterministic tests.
    """
    records = _validated_records(session_state, time.time() if now is None else now)
    _apply_limits(records)


def get_retry_key(
    session_state: MutableMapping[str, Any],
    *,
    thread_id: str,
    stage: str,
    prompt: str,
    now: float | None = None,
    new_key: Callable[[], str] | None = None,
) -> str:
    """Return the retry key for an unresolved prompt, creating one if needed.

    The exact active legacy raw-prompt entry is migrated once, before all other
    undated legacy entries are discarded.  Modern state stores only the SHA-256
    scope, notebook id, UUID key, and creation timestamp.
    """
    current_time = time.time() if now is None else now
    scope_sha256 = _scope_sha256(thread_id, stage, prompt)
    raw = session_state.get(RETRY_KEYS_SESSION_KEY)
    legacy_scope = f"{thread_id}:{stage}:{prompt}"
    legacy_key = _valid_key(raw.get(legacy_scope)) if isinstance(raw, dict) else None
    records = _validated_records(session_state, current_time)
    _apply_limits(records)
    existing = records.get(scope_sha256)
    if existing is not None:
        return str(existing["key"])
    if legacy_key is not None:
        key = legacy_key
    else:
        key = _valid_key((new_key or _new_retry_key)())
        if key is None:
            raise ValueError("new retry keys must be UUIDs")
    records[scope_sha256] = {
        "key": key,
        "notebook_id": thread_id,
        "scope_sha256": scope_sha256,
        "created_at": current_time,
    }
    _apply_limits(records)
    return key


def remove_retry_key(
    session_state: MutableMapping[str, Any],
    *,
    thread_id: str,
    stage: str,
    prompt: str,
    now: float | None = None,
) -> None:
    """Remove the retry key after its coaching turn completes successfully."""
    prune_retry_keys(session_state, now=now)
    records = session_state[RETRY_KEYS_SESSION_KEY]
    records.pop(_scope_sha256(thread_id, stage, prompt), None)


def purge_notebook_retry_keys(
    session_state: MutableMapping[str, Any],
    thread_id: str,
    *,
    now: float | None = None,
) -> None:
    """Remove all retry keys associated with a notebook that is being deleted."""
    prune_retry_keys(session_state, now=now)
    records = session_state[RETRY_KEYS_SESSION_KEY]
    for scope_sha256, record in list(records.items()):
        if record["notebook_id"] == thread_id:
            records.pop(scope_sha256, None)
