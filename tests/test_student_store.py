"""Deterministic tests for the six-table StudentStore model."""

from __future__ import annotations

import sqlite3

from backend.student_store import StudentStore


def test_chat_history_and_notebook_state(tmp_path):
    store = StudentStore(tmp_path / "store.sqlite3", identifier="student-a")
    thread_id = store.create_thread(
        name="Central question",
        model_id="mock",
        support_mode="critical-thinking",
    )
    user_id = store.add_message(
        thread_id, "user", "What evidence supports longer crossing times?"
    )
    assistant_id = store.add_message(
        thread_id,
        "assistant",
        "Consider signal timing studies.",
        metadata={
            "assessment": {
                "current_stage": "focus",
                "contribution_summary": "Crossing times",
                "stage_assessment": "Clear focus",
                "critical_understanding_level": "Emerging",
                "confidence": 0.4,
                "recommendation": "stay",
                "recommendation_rationale": "Need more evidence",
                "learning_summary": "Exploring crossing design.",
            }
        },
    )
    store.update_thread(
        thread_id,
        metadata={
            "learning_journey": {
                "current_stage": "focus",
                "completed_stages": [],
                "response_detail": "short",
            },
            "selected_model": "mock",
        },
    )

    thread = store.get_thread(thread_id)
    assert thread is not None
    assert thread["name"] == "Central question"
    assert thread["metadata"]["thinking_stage"] == "focus"
    assert thread["metadata"]["selected_model"] == "mock"
    assert store.list_threads("central")[0]["id"] == thread_id

    messages = store.get_messages(thread_id)
    assert [message["role"] for message in messages] == ["user", "assistant"]
    assert messages[0]["id"] == user_id
    assert messages[1]["id"] == assistant_id
    assert messages[1]["metadata"]["assessment"]["learning_summary"].startswith(
        "Exploring"
    )
    # Canonical history comes directly from messages; no legacy provider state API.
    assert not hasattr(store, "get_state")
    assert not hasattr(store, "save_state")
    assert not hasattr(store, "record_turn")


def test_notebook_update_reads_and_writes_on_one_connection(tmp_path, monkeypatch):
    """The merge must be one OCC-visible unit for Aurora DSQL."""
    store = StudentStore(tmp_path / "atomic-update.sqlite3")
    thread_id = store.create_thread(model_id="mock", support_mode="guided")
    real_connect = store._connect
    connection_count = 0

    def counting_connect():
        nonlocal connection_count
        connection_count += 1
        return real_connect()

    monkeypatch.setattr(store, "_connect", counting_connect)

    store.update_thread(thread_id, metadata={"response_detail": "long"})

    assert connection_count == 1
    thread = store.get_thread(thread_id) or {}
    assert thread["metadata"]["thinking_stage"] == "focus"
    assert thread["metadata"]["response_detail"] == "long"


def test_delete_notebook_removes_messages_and_sources(tmp_path):
    store = StudentStore(tmp_path / "delete.sqlite3")
    thread_id = store.create_thread(
        name="Draft",
        model_id="mock",
        support_mode="critical-thinking",
    )
    message_id = store.add_message(thread_id, "user", "Original")
    store.update_message(message_id, "Revised")
    store.update_thread(thread_id, name="Draft feedback")
    assert store.get_messages(thread_id)[0]["content"] == "Revised"
    assert store.get_thread(thread_id)["name"] == "Draft feedback"
    store.delete_thread(thread_id)
    assert store.get_thread(thread_id) is None


def test_revise_user_message_discards_later_turns(tmp_path):
    store = StudentStore(tmp_path / "revise.sqlite3")
    thread_id = store.create_thread(
        name="Revise",
        model_id="mock",
        support_mode="critical-thinking",
    )
    first_user = store.add_message(thread_id, "user", "Old first prompt")
    store.add_message(thread_id, "assistant", "Old answer")
    store.add_message(thread_id, "user", "Later prompt")
    store.add_message(thread_id, "assistant", "Later answer")

    history = store.revise_user_message(
        thread_id,
        first_user,
        "Revised first prompt",
        model_id="mock",
        metadata={},
    )
    assert history == []
    messages = store.get_messages(thread_id)
    assert len(messages) == 1
    assert messages[0]["content"] == "Revised first prompt"


def test_user_preferences_round_trip(tmp_path):
    store = StudentStore(tmp_path / "prefs.sqlite3")
    assert store.get_user_preferences().get("role") == "student"

    store.update_user_preferences({"appearance": "Dark"})
    prefs = store.get_user_preferences()
    assert prefs["appearance"] == "Dark"
    assert prefs["role"] == "student"

    store.update_user_preferences({"appearance": "System", "extra": True})
    prefs = store.get_user_preferences()
    assert prefs["appearance"] == "System"
    assert prefs["extra"] is True

    reloaded = StudentStore(tmp_path / "prefs.sqlite3")
    assert reloaded.get_user_preferences()["appearance"] == "System"


def test_stage_decision_lives_on_assistant_message(tmp_path):
    store = StudentStore(tmp_path / "decision.sqlite3")
    thread_id = store.create_thread(model_id="mock", support_mode="critical-thinking")
    created = store.create_phase_transition(
        {
            "thread_id": thread_id,
            "from_stage": "focus",
            "to_stage": "evidence",
            "assessment": {
                "current_stage": "focus",
                "contribution_summary": "Ready",
                "stage_assessment": "Clear",
                "critical_understanding_level": "Emerging",
                "confidence": 0.5,
                "recommendation": "advance",
                "recommendation_rationale": "Enough focus",
                "learning_summary": "Summary",
            },
        }
    )
    pending = store.get_pending_phase_transition(thread_id)
    assert pending is not None
    assert pending["id"] == created["id"]
    assert pending["to_stage"] == "evidence"

    store.add_message(
        thread_id,
        "user",
        "I clarified the focus.",
    )
    store.add_message(
        thread_id,
        "assistant",
        "Ready for evidence.",
        message_id=created["id"],
    )
    messages = store.get_messages(thread_id)
    assert [message["role"] for message in messages] == ["user", "assistant"]
    assert messages[1]["id"] == created["id"]

    resolved = store.apply_phase_transition_decision(
        thread_id,
        created["id"],
        accepted=True,
        metadata_patch={
            "learning_journey": {
                "current_stage": "evidence",
                "completed_stages": ["focus"],
                "stage_notes": {"focus": "Done"},
                "response_detail": "short",
            },
            "thinking_stage": "evidence",
        },
        expected_from_stage="focus",
    )
    assert resolved["status"] == "confirmed"
    thread = store.get_thread(thread_id) or {}
    assert thread["metadata"]["thinking_stage"] == "evidence"
    assert store.get_pending_phase_transition(thread_id) is None


def test_owner_isolation_for_notebooks(tmp_path):
    first = StudentStore(tmp_path / "iso.sqlite3", identifier="student-a")
    second = StudentStore(tmp_path / "iso.sqlite3", identifier="student-b")
    thread_id = first.create_thread(model_id="mock", support_mode="critical-thinking")
    assert first.get_thread(thread_id) is not None
    assert second.get_thread(thread_id) is None


def test_saving_oauth_state_prunes_expired_rows(tmp_path):
    store = StudentStore(tmp_path / "oauth-cleanup.sqlite3")
    store.save_oauth_login_state(
        state="expired",
        code_verifier="old-verifier",
        created_at="2026-08-01T00:00:00+00:00",
        expires_at="2026-08-01T00:05:00+00:00",
    )

    store.save_oauth_login_state(
        state="current",
        code_verifier="new-verifier",
        created_at="2026-08-01T00:06:00+00:00",
        expires_at="2026-08-01T00:11:00+00:00",
    )

    with store._connect() as connection:
        states = {
            str(row["state"])
            for row in connection.execute(
                "SELECT state FROM oauth_login_states ORDER BY state"
            ).fetchall()
        }
        assert states == {"current"}


def test_legacy_camelcase_oauth_login_states_are_migrated(tmp_path):
    """Older local DBs used camelCase OAuth columns; login needs snake_case."""
    db_path = tmp_path / "oauth-legacy.sqlite3"
    with sqlite3.connect(db_path) as connection:
        connection.execute(
            """
            CREATE TABLE oauth_login_states (
                state TEXT PRIMARY KEY,
                codeVerifier TEXT NOT NULL,
                createdAt TEXT NOT NULL,
                expiresAt TEXT NOT NULL
            )
            """
        )
        connection.execute(
            """
            INSERT INTO oauth_login_states
              (state, codeVerifier, createdAt, expiresAt)
            VALUES (?, ?, ?, ?)
            """,
            (
                "legacy-state",
                "legacy-verifier",
                "2026-08-01T00:00:00+00:00",
                "2026-08-01T00:05:00+00:00",
            ),
        )
        connection.commit()

    store = StudentStore(db_path)
    with store._connect() as connection:
        columns = {
            str(row[1])
            for row in connection.execute("PRAGMA table_info(oauth_login_states)")
        }
        assert columns == {
            "state",
            "code_verifier",
            "created_at",
            "expires_at",
        }
        row = connection.execute(
            "SELECT code_verifier, expires_at FROM oauth_login_states WHERE state = ?",
            ("legacy-state",),
        ).fetchone()
        assert row is not None
        assert str(row["code_verifier"]) == "legacy-verifier"
        assert str(row["expires_at"]) == "2026-08-01T00:05:00+00:00"

    store.save_oauth_login_state(
        state="fresh",
        code_verifier="fresh-verifier",
        created_at="2030-01-01T00:00:00+00:00",
        expires_at="2030-01-01T00:05:00+00:00",
    )
    assert store.consume_oauth_login_state("fresh") == "fresh-verifier"


def test_legacy_camelcase_users_table_is_migrated(tmp_path):
    """Older local DBs used camelCase users columns; Cognito upsert needs snake_case."""
    db_path = tmp_path / "users-legacy.sqlite3"
    with sqlite3.connect(db_path) as connection:
        connection.execute(
            """
            CREATE TABLE users (
                id TEXT PRIMARY KEY,
                identifier TEXT NOT NULL UNIQUE,
                metadata TEXT NOT NULL DEFAULT '{}',
                createdAt TEXT NOT NULL,
                cognitoSub TEXT,
                email TEXT,
                displayName TEXT,
                role TEXT NOT NULL DEFAULT 'student',
                updatedAt TEXT,
                lastLoginAt TEXT
            )
            """
        )
        connection.execute(
            """
            INSERT INTO users (
                id, identifier, metadata, createdAt, cognitoSub, email,
                displayName, role, updatedAt, lastLoginAt
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "user-1",
                "cognito:sub-1",
                '{"appearance":"System"}',
                "2026-08-01T00:00:00+00:00",
                "sub-1",
                "a@example.edu",
                "Alex",
                "student",
                "2026-08-01T00:01:00+00:00",
                "2026-08-01T00:02:00+00:00",
            ),
        )
        connection.commit()

    store = StudentStore(db_path, identifier="cognito:sub-1")
    with store._connect() as connection:
        columns = {
            str(row[1]) for row in connection.execute("PRAGMA table_info(users)")
        }
        assert {
            "cognito_sub",
            "display_name",
            "preferences_text",
            "created_at",
            "updated_at",
            "last_login_at",
        }.issubset(columns)
        row = connection.execute(
            "SELECT cognito_sub, display_name, preferences_text, created_at "
            "FROM users WHERE id = ?",
            ("user-1",),
        ).fetchone()
        assert row is not None
        assert str(row["cognito_sub"]) == "sub-1"
        assert str(row["display_name"]) == "Alex"
        assert "appearance" in str(row["preferences_text"])

    updated = store.upsert_cognito_user(
        cognito_sub="sub-1",
        identifier="cognito:sub-1",
        email="a@example.edu",
        display_name="Alex",
    )
    assert updated["id"] == "user-1"
    assert updated["display_name"] == "Alex"


def test_six_table_schema_has_no_legacy_tables(tmp_path):
    store = StudentStore(tmp_path / "schema.sqlite3")
    with store._connect() as connection:
        names = {
            str(row["name"])
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
        }
    expected = {
        "users",
        "oauth_login_states",
        "notebooks",
        "messages",
        "sources",
    }
    assert expected <= names
    assert "app_sessions" not in names
    legacy = {
        "threads",
        "steps",
        "folders",
        "thread_folders",
        "feedbacks",
        "model_turns",
        "openai_thread_state",
        "notebook_sources",
        "phase_transitions",
        "app_sessions",
    }
    assert names.isdisjoint(legacy)
