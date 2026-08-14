"""Deterministic retention tests for Streamlit coach retry-key session state."""

from __future__ import annotations

import hashlib
from uuid import uuid4

from ui.retry_keys import (
    MAX_RETRY_KEYS_GLOBAL,
    MAX_RETRY_KEYS_PER_NOTEBOOK,
    RETRY_KEYS_SESSION_KEY,
    RETRY_KEY_TTL_SECONDS,
    get_retry_key,
    purge_notebook_retry_keys,
    remove_retry_key,
)


NOW = 1_700_000_000.0


def _scope(thread_id: str, stage: str, prompt: str) -> str:
    """Return the expected non-sensitive key used by the retry helper."""
    return hashlib.sha256(f"{thread_id}\x00{stage}\x00{prompt}".encode()).hexdigest()


def _key() -> str:
    """Build a valid deterministic-format idempotency UUID."""
    return str(uuid4())


def test_reuses_active_retry_without_storing_prompt_text():
    """The same unresolved prompt retains one UUID while session state is private."""
    state: dict[str, object] = {}
    first = get_retry_key(
        state, thread_id="notebook-a", stage="problem_identification", prompt="Private claim", now=NOW
    )
    replay = get_retry_key(
        state, thread_id="notebook-a", stage="problem_identification", prompt="Private claim", now=NOW + 2
    )

    assert replay == first
    assert list(state[RETRY_KEYS_SESSION_KEY]) == [
        _scope("notebook-a", "problem_identification", "Private claim")
    ]
    assert "Private claim" not in repr(state[RETRY_KEYS_SESSION_KEY])


def test_success_removal_and_expiry_produce_fresh_keys():
    """Completed and hour-old submissions cannot retain a retry key."""
    state: dict[str, object] = {}
    first = get_retry_key(
        state, thread_id="notebook-a", stage="problem_identification", prompt="Claim", now=NOW
    )
    remove_retry_key(
        state, thread_id="notebook-a", stage="problem_identification", prompt="Claim", now=NOW + 1
    )
    after_success = get_retry_key(
        state, thread_id="notebook-a", stage="problem_identification", prompt="Claim", now=NOW + 2
    )
    after_expiry = get_retry_key(
        state,
        thread_id="notebook-a",
        stage="problem_identification",
        prompt="Claim",
        now=NOW + RETRY_KEY_TTL_SECONDS + 3,
    )

    assert after_success != first
    assert after_expiry != after_success


def test_prunes_oldest_per_notebook_and_globally():
    """Retention keeps the newest eight per notebook and newest 24 overall."""
    state: dict[str, object] = {}
    for index in range(MAX_RETRY_KEYS_PER_NOTEBOOK + 2):
        get_retry_key(
            state,
            thread_id="notebook-a",
            stage="problem_identification",
            prompt=f"A {index}",
            now=NOW + index,
        )
    records = state[RETRY_KEYS_SESSION_KEY]
    assert len(records) == MAX_RETRY_KEYS_PER_NOTEBOOK
    assert _scope("notebook-a", "problem_identification", "A 0") not in records
    assert _scope("notebook-a", "problem_identification", "A 1") not in records

    state = {}
    for index in range(MAX_RETRY_KEYS_GLOBAL + 4):
        get_retry_key(
            state,
            thread_id=f"notebook-{index}",
            stage="problem_identification",
            prompt="Claim",
            now=NOW + index,
        )
    records = state[RETRY_KEYS_SESSION_KEY]
    assert len(records) == MAX_RETRY_KEYS_GLOBAL
    assert _scope("notebook-0", "problem_identification", "Claim") not in records
    assert _scope("notebook-3", "problem_identification", "Claim") not in records


def test_notebook_switch_preserves_valid_entries_and_delete_purges_them():
    """Keys survive navigation but cannot outlive their deleted notebook."""
    state: dict[str, object] = {}
    first = get_retry_key(
        state, thread_id="notebook-a", stage="problem_identification", prompt="Claim A", now=NOW
    )
    get_retry_key(
        state, thread_id="notebook-b", stage="problem_identification", prompt="Claim B", now=NOW + 1
    )

    assert get_retry_key(
        state, thread_id="notebook-a", stage="problem_identification", prompt="Claim A", now=NOW + 2
    ) == first
    purge_notebook_retry_keys(state, "notebook-a", now=NOW + 2)
    records = state[RETRY_KEYS_SESSION_KEY]
    assert _scope("notebook-a", "problem_identification", "Claim A") not in records
    assert _scope("notebook-b", "problem_identification", "Claim B") in records


def test_migrates_exact_active_legacy_string_and_discards_other_legacy_state():
    """Only the currently submitted old raw scope survives as a dated hash record."""
    active_key = _key()
    state: dict[str, object] = {
        RETRY_KEYS_SESSION_KEY: {
            "notebook-a:problem_identification:Claim A": active_key,
            "notebook-b:problem_identification:Claim B": _key(),
            "malformed": "not-a-uuid",
            "already-hashed-but-undated": _key(),
        }
    }

    actual = get_retry_key(
        state, thread_id="notebook-a", stage="problem_identification", prompt="Claim A", now=NOW
    )

    assert actual == active_key
    assert state[RETRY_KEYS_SESSION_KEY] == {
        _scope("notebook-a", "problem_identification", "Claim A"): {
            "key": active_key,
            "notebook_id": "notebook-a",
            "scope_sha256": _scope("notebook-a", "problem_identification", "Claim A"),
            "created_at": NOW,
        }
    }


def test_discards_malformed_expired_and_undated_records():
    """Malformed session values cannot create unbounded or invalid retry state."""
    state: dict[str, object] = {
        RETRY_KEYS_SESSION_KEY: {
            _scope("old", "problem_identification", "Claim"): {
                "key": _key(),
                "notebook_id": "old",
                "scope_sha256": _scope("old", "problem_identification", "Claim"),
                "created_at": NOW - RETRY_KEY_TTL_SECONDS - 1,
            },
            "valid-looking": _key(),
        }
    }

    get_retry_key(state, thread_id="new", stage="problem_identification", prompt="Claim", now=NOW)

    assert len(state[RETRY_KEYS_SESSION_KEY]) == 1
    assert _scope("new", "problem_identification", "Claim") in state[RETRY_KEYS_SESSION_KEY]
