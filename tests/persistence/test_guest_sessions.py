"""Deterministic persistence tests for Phase 2 guest credentials."""

from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from backend.persistence.dsql_student_store import DsqlStudentStore, _OCC_WRITE_METHODS
from backend.persistence.guest_sessions import guest_secret_digest
from backend.student_store import StudentStore


NOW = datetime(2026, 9, 24, 12, 0, tzinfo=timezone.utc)


def test_sqlite_guest_sessions_are_distinct_digest_only_and_restart_safe(
    tmp_path: Path,
) -> None:
    """Two server-created credentials resolve to distinct owners after restart."""
    path = tmp_path / "guest.sqlite3"
    store = StudentStore(path, identifier="existing-cognito")
    cognito_owner = store.owner_id
    owner_a, secret_a = store.create_guest_session(now=NOW)
    owner_b, secret_b = store.create_guest_session(now=NOW)

    assert owner_a != owner_b
    assert secret_a != secret_b
    assert len(secret_a) >= 43
    assert store.validate_guest_session(secret_a, now=NOW) == owner_a
    assert store.validate_guest_session(secret_b, now=NOW) == owner_b

    with sqlite3.connect(path) as connection:
        rows = connection.execute(
            "SELECT token_digest, owner_user_id FROM guest_sessions ORDER BY owner_user_id"
        ).fetchall()
        identifiers = connection.execute(
            "SELECT id, identifier FROM users WHERE id IN (?, ?)", (owner_a, owner_b)
        ).fetchall()
    assert {row[0] for row in rows} == {
        guest_secret_digest(secret_a),
        guest_secret_digest(secret_b),
    }
    assert secret_a not in repr(rows) and secret_b not in repr(rows)
    guest_identifiers = {str(row[1]) for row in identifiers}
    assert all(identifier.startswith("guest:") for identifier in guest_identifiers)
    guest_identifier_a = next(
        str(row[1]) for row in identifiers if str(row[0]) == owner_a
    )

    restarted = StudentStore(path, identifier="existing-cognito", ensure_owner=False)
    assert restarted.owner_id == ""
    assert restarted.validate_guest_session(secret_a, now=NOW) == owner_a
    assert restarted.validate_guest_session(secret_b, now=NOW) == owner_b
    assert restarted.get_user_by_id(cognito_owner) is not None
    guest_store = StudentStore(path, identifier=guest_identifier_a)
    assert guest_store.owner_id == owner_a


def test_guest_session_rejects_invalid_expired_and_revoked_secret(
    tmp_path: Path,
) -> None:
    store = StudentStore(tmp_path / "guest-invalid.sqlite3")
    owner_id, secret = store.create_guest_session(now=NOW)

    assert store.validate_guest_session("invalid", now=NOW) is None
    assert store.validate_guest_session(secret, now=NOW + timedelta(days=400)) is None
    assert store.revoke_guest_session(secret, now=NOW + timedelta(days=2)) is True
    assert store.revoke_guest_session(secret, now=NOW + timedelta(days=3)) is False
    assert store.validate_guest_session(secret, now=NOW + timedelta(days=3)) is None
    assert store.get_user_by_id(owner_id) is not None


def test_guest_session_renewal_slides_expiry_by_400_days(tmp_path: Path) -> None:
    path = tmp_path / "guest-renew.sqlite3"
    store = StudentStore(path)
    owner_id, secret = store.create_guest_session(now=NOW)
    renewal_time = NOW + timedelta(days=100)

    assert store.renew_guest_session(secret, now=renewal_time) is True
    assert store.renew_guest_session("unknown", now=renewal_time) is False
    assert store.validate_guest_session(secret, now=NOW + timedelta(days=399)) == owner_id
    assert store.validate_guest_session(secret, now=renewal_time + timedelta(days=400)) is None

    with sqlite3.connect(path) as connection:
        expires_at = connection.execute(
            "SELECT expires_at FROM guest_sessions WHERE token_digest=?",
            (guest_secret_digest(secret),),
        ).fetchone()[0]
    assert expires_at == (renewal_time + timedelta(days=400)).isoformat(
        timespec="microseconds"
    )


def test_out_of_order_guest_renewal_never_shortens_expiry(tmp_path: Path) -> None:
    """An older renewal request cannot replace a later 400-day expiry."""
    path = tmp_path / "guest-monotonic.sqlite3"
    store = StudentStore(path)
    _, secret = store.create_guest_session(now=NOW)
    later_request = NOW + timedelta(days=300)
    earlier_request = NOW + timedelta(days=100)

    assert store.renew_guest_session(secret, now=later_request) is True
    assert store.renew_guest_session(secret, now=earlier_request) is True

    with sqlite3.connect(path) as connection:
        expires_at = connection.execute(
            "SELECT expires_at FROM guest_sessions WHERE token_digest=?",
            (guest_secret_digest(secret),),
        ).fetchone()[0]
    assert expires_at == (later_request + timedelta(days=400)).isoformat(
        timespec="microseconds"
    )


class _SQLiteDsqlAdapter:
    """Isolated SQLite-backed adapter for the DSQL store's SQL contract."""

    def __init__(self, path: Path):
        self.connection = sqlite3.connect(path, timeout=30)
        self.connection.row_factory = sqlite3.Row

    def execute(self, sql: str, params: Any = None) -> Any:
        return self.connection.execute(sql, tuple(params or ()))

    def __enter__(self) -> _SQLiteDsqlAdapter:
        return self

    def __exit__(self, exc_type, _exc, _tb) -> None:
        if exc_type is None:
            self.connection.commit()
        else:
            self.connection.rollback()
        self.connection.close()


def test_dsql_guest_session_operations_use_persistent_dsql_adapter(
    tmp_path: Path,
) -> None:
    """Independent DSQL store instances see durable guest records and OCC writes."""
    path = tmp_path / "dsql-adapter.sqlite3"
    StudentStore(path, identifier="schema-owner")
    factory = lambda: _SQLiteDsqlAdapter(path)  # noqa: E731
    first = DsqlStudentStore(
        identifier="dsql-runtime", ensure_owner=False, connection_factory=factory
    )
    owner_id, secret = first.create_guest_session(now=NOW)

    second = DsqlStudentStore(
        identifier="dsql-runtime", ensure_owner=False, connection_factory=factory
    )
    assert second.validate_guest_session(secret, now=NOW) == owner_id
    later_renewal = NOW + timedelta(days=2)
    earlier_renewal = NOW + timedelta(days=1)
    assert second.renew_guest_session(secret, now=later_renewal) is True
    assert second.renew_guest_session(secret, now=earlier_renewal) is True
    assert first.validate_guest_session(secret, now=NOW + timedelta(days=400)) == owner_id
    with sqlite3.connect(path) as connection:
        expires_at = connection.execute(
            "SELECT expires_at FROM guest_sessions WHERE token_digest=?",
            (guest_secret_digest(secret),),
        ).fetchone()[0]
    assert expires_at == (later_renewal + timedelta(days=400)).isoformat(
        timespec="microseconds"
    )
    assert second.revoke_guest_session(secret, now=NOW + timedelta(days=2)) is True
    assert first.validate_guest_session(secret, now=NOW + timedelta(days=3)) is None
    assert {"create_guest_session", "renew_guest_session", "revoke_guest_session"}.issubset(
        set(_OCC_WRITE_METHODS)
    )


def test_guest_schema_adds_without_rewriting_existing_user_and_notebook(
    tmp_path: Path,
) -> None:
    """Legacy user/notebook rows survive the additive guest-table initialization."""
    path = tmp_path / "existing.sqlite3"
    original = StudentStore(path, identifier="student-preserved")
    notebook_id = original.create_thread(model_id="mock", support_mode="guided")
    original_owner = original.owner_id

    # Model the pre-Phase-2 schema while retaining representative user data.
    with sqlite3.connect(path) as connection:
        connection.execute("DROP TABLE guest_sessions")
        assert connection.execute(
            "SELECT COUNT(*) FROM sqlite_master WHERE type='table' "
            "AND name='guest_sessions'"
        ).fetchone()[0] == 0

    reopened = StudentStore(path, identifier="student-preserved")
    assert reopened.owner_id == original_owner
    assert reopened.get_thread(notebook_id) is not None
    with reopened._connect() as connection:
        columns = {
            str(row["name"])
            for row in connection.execute("PRAGMA table_info(guest_sessions)")
        }
        indexes = {
            str(row["name"])
            for row in connection.execute("PRAGMA index_list(guest_sessions)")
        }
    assert columns == {
        "token_digest",
        "owner_user_id",
        "created_at",
        "expires_at",
        "revoked_at",
        "claim_user_id",
        "claim_operation_id",
        "claim_result_text",
        "claim_expires_at",
        "preview_user_id",
        "preview_operation_id",
        "preview_fingerprint",
        "preview_expires_at",
    }
    assert "idx_guest_sessions_owner_expires" in indexes
    assert "idx_guest_sessions_expires" in indexes


def test_pre_phase5_guest_sessions_migrate_after_online_backup_and_restore(
    tmp_path: Path,
) -> None:
    """A legacy live DB and its online backup retain valid guest workspace rows."""
    path = tmp_path / "legacy-live.sqlite3"
    backup_path = tmp_path / "legacy-backup.sqlite3"
    restore_path = tmp_path / "restored.sqlite3"
    initial = StudentStore(path, identifier="legacy-owner")
    owner_id, _ = initial.create_guest_session(now=NOW)
    owner = initial.get_user_by_id(owner_id)
    assert owner is not None
    guest = StudentStore(path, identifier=str(owner["identifier"]))
    notebook_id = guest.create_thread(model_id="mock", support_mode="guided")
    guest.add_message(notebook_id, "user", "Legacy guest work")
    secret = "legacy-valid-session-token"
    with sqlite3.connect(path) as connection:
        connection.execute("DROP TABLE guest_sessions")
        connection.execute(
            "CREATE TABLE guest_sessions (token_digest TEXT PRIMARY KEY, "
            "owner_user_id TEXT NOT NULL, created_at TEXT NOT NULL, "
            "expires_at TEXT NOT NULL, revoked_at TEXT, "
            "FOREIGN KEY (owner_user_id) REFERENCES users(id) ON DELETE CASCADE)"
        )
        connection.execute(
            "INSERT INTO guest_sessions VALUES (?, ?, ?, ?, NULL)",
            (
                guest_secret_digest(secret),
                owner_id,
                NOW.isoformat(),
                (NOW + timedelta(days=200)).isoformat(),
            ),
        )
    with sqlite3.connect(path) as source, sqlite3.connect(backup_path) as backup:
        source.backup(backup)

    migrated = StudentStore(path, identifier="legacy-owner")
    assert migrated.validate_guest_session(secret, now=NOW) == owner_id
    assert migrated.get_user_by_id(owner_id) == owner
    migrated_guest = StudentStore(path, identifier=str(owner["identifier"]))
    assert migrated_guest.get_thread(notebook_id) is not None
    assert migrated_guest.get_messages(notebook_id)[0]["content"] == "Legacy guest work"
    with migrated._connect() as connection:
        migrated_columns = {
            str(row["name"])
            for row in connection.execute("PRAGMA table_info(guest_sessions)")
        }
    assert "claim_operation_id" in migrated_columns
    assert "preview_fingerprint" in migrated_columns

    with sqlite3.connect(backup_path) as backup, sqlite3.connect(restore_path) as restored:
        backup.backup(restored)
    restored_store = StudentStore(restore_path, identifier="legacy-owner")
    assert restored_store.validate_guest_session(secret, now=NOW) == owner_id
    restored_guest = StudentStore(restore_path, identifier=str(owner["identifier"]))
    assert restored_guest.get_thread(notebook_id) is not None
    assert restored_guest.get_messages(notebook_id)[0]["content"] == "Legacy guest work"


def test_guest_claim_fences_owner_transfer_and_same_account_retry(tmp_path: Path) -> None:
    """Claim keeps IDs and rows, revokes only after commit, and replays safely."""
    path = tmp_path / "claim.sqlite3"
    root = StudentStore(path)
    guest_user_id, secret = root.create_guest_session()
    guest_profile = root.get_user_by_id(guest_user_id)
    assert guest_profile
    guest = StudentStore(path, identifier=str(guest_profile["identifier"]))
    notebook_id = guest.create_thread(model_id="mock", support_mode="guided")
    message_id = guest.add_message(notebook_id, "user", "Keep this transcript")
    with guest._connect() as connection:
        connection.execute(
            "INSERT INTO sources (id, notebook_id, kind, title, content_type, "
            "byte_size, object_key, extracted_text_key, metadata_text, created_at, updated_at) "
            "VALUES ('source-a', ?, 'file', 'brief.pdf', 'application/pdf', 4, "
            "'users/guest/notebooks/source-a/raw/brief.pdf', "
            "'users/guest/notebooks/source-a/derived/extracted.txt', '{}', 'now', 'now')",
            (notebook_id,),
        )
    account = StudentStore(path, identifier="cognito:claimant")
    prior_account_profile = account.get_user_by_id(account.owner_id)
    preview = root.create_guest_claim_preview(secret=secret, target_user_id=account.owner_id)
    assert preview is not None
    operation_id = preview["operation_id"]
    snapshot = root.begin_guest_claim(
        secret=secret, target_user_id=account.owner_id, operation_id=operation_id
    )
    assert snapshot is not None
    assert root.validate_guest_session(secret) is None
    assert root.list_threads() == []
    reopened = StudentStore(path)
    recovered_preview = reopened.create_guest_claim_preview(
        secret=secret, target_user_id=account.owner_id
    )
    assert recovered_preview["operation_id"] == operation_id
    mapping = {
        "users/guest/notebooks/source-a/raw/brief.pdf":
            "users/account/notebooks/source-a/raw/brief.pdf",
        "users/guest/notebooks/source-a/derived/extracted.txt":
            "users/account/notebooks/source-a/derived/extracted.txt",
    }
    result = root.guest_claim_transfer(
        secret=secret, target_user_id=account.owner_id, operation_id=operation_id,
        expected_sources=snapshot["sources"], expected_notebooks=snapshot["notebooks"],
        expected_fingerprint=snapshot["fingerprint"], key_map=mapping,
    )
    assert result == {"notebook_ids": [notebook_id], "notebook_count": 1}
    assert account.get_thread(notebook_id) is not None
    assert account.get_messages(notebook_id)[0]["id"] == message_id
    source = account.get_source(notebook_id, "source-a", include_extracted_text=False)
    assert source["object_key"] == mapping["users/guest/notebooks/source-a/raw/brief.pdf"]
    assert source["extracted_text_key"] == mapping[
        "users/guest/notebooks/source-a/derived/extracted.txt"
    ]
    assert account.get_user_by_id(account.owner_id) == prior_account_profile
    assert root.guest_claim_transfer(
        secret=secret, target_user_id=account.owner_id, operation_id=operation_id,
        expected_sources=[], expected_notebooks=[], expected_fingerprint="", key_map={},
    ) == result
    recovered_result = root.create_guest_claim_preview(
        secret=secret, target_user_id=account.owner_id
    )
    assert recovered_result["already_claimed"] is True
    assert recovered_result["notebook_ids"] == [notebook_id]
    assert recovered_result["operation_id"] == operation_id
    other = StudentStore(path, identifier="cognito:other-claimant")
    assert root.guest_claim_transfer(
        secret=secret, target_user_id=other.owner_id, operation_id=operation_id,
        expected_sources=[], expected_notebooks=[], expected_fingerprint="", key_map={},
    ) is None


def test_guest_claim_pending_fence_can_be_cancelled_after_store_restart(tmp_path: Path) -> None:
    """Only the preview's Cognito owner can release its persisted claim fence."""
    path = tmp_path / "claim-cancel.sqlite3"
    store = StudentStore(path)
    _guest_user_id, secret = store.create_guest_session()
    account = StudentStore(path, identifier="cognito:cancel-owner")
    other = StudentStore(path, identifier="cognito:other-owner")
    preview = store.create_guest_claim_preview(
        secret=secret, target_user_id=account.owner_id
    )
    assert preview
    operation_id = str(preview["operation_id"])
    assert store.begin_guest_claim(
        secret=secret, target_user_id=account.owner_id, operation_id=operation_id
    )
    assert store.validate_guest_session(secret) is None

    restarted = StudentStore(path)
    assert not restarted.release_guest_claim(
        secret=secret, target_user_id=other.owner_id, operation_id=operation_id
    )
    assert not restarted.release_guest_claim(
        secret=secret, target_user_id=account.owner_id, operation_id="wrong-operation"
    )
    assert restarted.validate_guest_session(secret) is None
    assert restarted.release_guest_claim(
        secret=secret, target_user_id=account.owner_id, operation_id=operation_id
    )
    assert restarted.validate_guest_session(secret) == _guest_user_id
