"""Deterministic tests for the six-table StudentStore model."""

from __future__ import annotations

import sqlite3

from backend.retrieval import (
    LocalChunkRetriever,
    RetrievalQuery,
    retrieval_sources_from_notebook,
)
from backend.settings import settings
from backend.student_store import StudentStore
from backend.workspace_service import WorkspaceService


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


def test_legacy_workspace_is_preserved_and_copied_into_five_tables(tmp_path):
    """Local schema upgrade keeps old rows and makes them usable by new APIs/RAG."""
    db_path = tmp_path / "workspace-legacy.sqlite3"
    legacy_file = (
        settings.files_dir
        / "threads"
        / "legacy-thread"
        / "uploads"
        / "evidence.txt"
    )
    legacy_file.parent.mkdir(parents=True, exist_ok=True)
    legacy_file.write_bytes(b"original local source bytes")
    with sqlite3.connect(db_path) as connection:
        connection.executescript(
            """
            PRAGMA foreign_keys = ON;
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
            );
            CREATE TABLE threads (
                id TEXT PRIMARY KEY,
                createdAt TEXT NOT NULL,
                name TEXT,
                userId TEXT,
                userIdentifier TEXT,
                tags TEXT NOT NULL DEFAULT '[]',
                metadata TEXT NOT NULL DEFAULT '{}',
                FOREIGN KEY (userId) REFERENCES users(id) ON DELETE CASCADE
            );
            CREATE TABLE steps (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                type TEXT NOT NULL,
                threadId TEXT NOT NULL,
                isError INTEGER,
                metadata TEXT NOT NULL DEFAULT '{}',
                output TEXT,
                createdAt TEXT,
                FOREIGN KEY (threadId) REFERENCES threads(id) ON DELETE CASCADE
            );
            CREATE TABLE notebook_sources (
                id TEXT PRIMARY KEY,
                threadId TEXT NOT NULL,
                ownerId TEXT NOT NULL,
                kind TEXT NOT NULL,
                title TEXT NOT NULL,
                mime TEXT,
                path TEXT,
                sourceUrl TEXT,
                extractedText TEXT,
                size INTEGER,
                selected INTEGER,
                metadata TEXT,
                createdAt TEXT,
                updatedAt TEXT,
                FOREIGN KEY (threadId) REFERENCES threads(id) ON DELETE CASCADE,
                FOREIGN KEY (ownerId) REFERENCES users(id) ON DELETE CASCADE
            );
            CREATE TABLE phase_transitions (
                id TEXT PRIMARY KEY,
                threadId TEXT NOT NULL,
                fromStage TEXT NOT NULL,
                toStage TEXT NOT NULL,
                assessment TEXT NOT NULL,
                status TEXT NOT NULL,
                createdAt TEXT NOT NULL,
                resolvedAt TEXT
            );
            """
        )
        connection.execute(
            "INSERT INTO users VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                "legacy-user",
                "legacy-login-key",
                '{"appearance":"Dark"}',
                "2026-01-01T00:00:00+00:00",
                "legacy-sub",
                "legacy@example.edu",
                "Legacy Student",
                "student",
                None,
                None,
            ),
        )
        connection.execute(
            "INSERT INTO threads VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                "legacy-thread",
                "2026-01-02T00:00:00+00:00",
                "Preserved notebook",
                "legacy-user",
                "legacy-login-key",
                '["research"]',
                '{"thinking_stage":"evidence","response_detail":"long"}',
            ),
        )
        connection.execute(
            "INSERT INTO steps VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (
                "legacy-message",
                "You",
                "user_message",
                "legacy-thread",
                0,
                '{}',
                "What does the evidence show?",
                "2026-01-03T00:00:00+00:00",
            ),
        )
        connection.execute(
            "INSERT INTO notebook_sources VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                "legacy-source",
                "legacy-thread",
                "legacy-user",
                "file",
                "evidence.txt",
                "text/plain",
                str(legacy_file),
                None,
                "Crossing times were too short for older pedestrians.",
                52,
                1,
                '{}',
                "2026-01-02T00:00:00+00:00",
                "2026-01-02T00:00:00+00:00",
            ),
        )

    store = StudentStore(db_path, identifier="cognito:legacy-sub")

    assert store.owner_id == "legacy-user"
    assert store.get_thread("legacy-thread")["metadata"]["thinking_stage"] == (
        "evidence"
    )
    assert store.get_messages("legacy-thread")[0]["content"] == (
        "What does the evidence show?"
    )
    source = store.get_source("legacy-thread", "legacy-source")
    assert source is not None
    assert "older pedestrians" in source["extractedText"]
    assert "_legacy_extracted_text" not in source["metadata"]
    assert WorkspaceService(store).read_source_content(
        "legacy-thread", "legacy-source"
    ).data == b"original local source bytes"
    retrieval = LocalChunkRetriever().retrieve(
        RetrievalQuery(
            current_message="What evidence concerns older pedestrians?",
            current_stage="evidence",
            sources=retrieval_sources_from_notebook([source]),
        )
    )
    assert "older pedestrians" in retrieval.context

    # The compatibility source remains intact for rollback and a retry does not
    # duplicate any production-table row.
    StudentStore(db_path, identifier="cognito:legacy-sub")
    with store._connect() as connection:
        assert connection.execute("SELECT COUNT(*) FROM threads").fetchone()[0] == 1
        assert connection.execute("SELECT COUNT(*) FROM notebooks").fetchone()[0] == 1
        assert connection.execute("SELECT COUNT(*) FROM messages").fetchone()[0] == 1
        assert connection.execute("SELECT COUNT(*) FROM sources").fetchone()[0] == 1


def test_cognito_store_reuses_legacy_subject_row_instead_of_splitting_owner(tmp_path):
    db_path = tmp_path / "legacy-owner.sqlite3"
    bootstrap = StudentStore(db_path, identifier="local-student")
    created = bootstrap.upsert_cognito_user(
        cognito_sub="legacy-sub",
        identifier="legacy-login-key",
        email="legacy@example.edu",
        display_name="Legacy Student",
    )

    owner_store = StudentStore(db_path, identifier="cognito:legacy-sub")

    assert owner_store.owner_id == created["id"]
    with owner_store._connect() as connection:
        rows = connection.execute(
            "SELECT id, identifier, cognito_sub FROM users WHERE cognito_sub=? "
            "OR identifier=?",
            ("legacy-sub", "cognito:legacy-sub"),
        ).fetchall()
    assert len(rows) == 1
    assert str(rows[0]["identifier"]) == "cognito:legacy-sub"


def test_cognito_store_repairs_preexisting_split_owner_without_losing_notebooks(
    tmp_path,
):
    db_path = tmp_path / "split-owner.sqlite3"
    bootstrap = StudentStore(db_path, identifier="local-student")
    profile = bootstrap.upsert_cognito_user(
        cognito_sub="split-sub",
        identifier="legacy-login-key",
        email="legacy@example.edu",
        display_name="Legacy Student",
    )
    with bootstrap._connect() as connection:
        connection.execute(
            "INSERT INTO users "
            "(id, identifier, preferences_text, created_at, role) "
            "VALUES (?, ?, ?, ?, 'student')",
            (
                "split-duplicate",
                "cognito:split-sub",
                '{"active_thread_id":"split-notebook"}',
                "2026-01-01T00:00:00+00:00",
            ),
        )
        connection.execute(
            "INSERT INTO notebooks "
            "(id, user_id, title, current_stage, progress_text, settings_text, "
            "created_at, updated_at) VALUES (?, ?, ?, 'focus', '{}', '{}', ?, ?)",
            (
                "split-notebook",
                "split-duplicate",
                "Do not lose me",
                "2026-01-02T00:00:00+00:00",
                "2026-01-02T00:00:00+00:00",
            ),
        )

    repaired = StudentStore(db_path, identifier="cognito:split-sub")

    assert repaired.owner_id == profile["id"]
    assert repaired.get_thread("split-notebook") is not None
    assert repaired.get_user_preferences()["active_thread_id"] == "split-notebook"
    with repaired._connect() as connection:
        duplicate = connection.execute(
            "SELECT identifier FROM users WHERE id='split-duplicate'"
        ).fetchone()
        canonical = connection.execute(
            "SELECT identifier FROM users WHERE id=?", (profile["id"],)
        ).fetchone()
    assert str(duplicate["identifier"]).startswith("legacy-orphan:")
    assert str(canonical["identifier"]) == "cognito:split-sub"


def test_startup_repairs_users_legacy_notebook_foreign_key_without_data_loss(
    tmp_path,
):
    """The retired user-table rebuild must not strand local notebook writes."""
    db_path = tmp_path / "misbound-foreign-key.sqlite3"
    original = StudentStore(db_path, identifier="cognito:repair-sub")
    notebook_id = original.create_thread(
        name="Existing notebook",
        model_id="mock",
        support_mode="critical-thinking",
    )
    message_id = original.add_message(notebook_id, "user", "Keep this message")
    source_id = original.add_source(
        notebook_id,
        kind="text",
        title="Keep this source",
        source_id="existing-source",
    )

    # Reproduce the on-disk state left by the old destructive users migration:
    # users_legacy is absent but notebooks.user_id still targets that name.
    with sqlite3.connect(db_path) as connection:
        connection.execute("PRAGMA foreign_keys = OFF")
        connection.execute("BEGIN IMMEDIATE")
        connection.execute(
            """
            CREATE TABLE notebooks_broken (
                id TEXT PRIMARY KEY,
                user_id TEXT NOT NULL,
                title TEXT,
                current_stage TEXT NOT NULL DEFAULT 'focus',
                progress_text TEXT NOT NULL DEFAULT '{}',
                settings_text TEXT NOT NULL DEFAULT '{}',
                conversation_revision INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                FOREIGN KEY (user_id) REFERENCES users_legacy(id)
                    ON DELETE CASCADE
            )
            """
        )
        connection.execute(
            "INSERT INTO notebooks_broken SELECT * FROM notebooks"
        )
        connection.execute("DROP TABLE notebooks")
        connection.execute("ALTER TABLE notebooks_broken RENAME TO notebooks")
        connection.execute(
            "CREATE INDEX idx_notebooks_user_updated "
            "ON notebooks(user_id, updated_at)"
        )
        connection.commit()

    repaired = StudentStore(db_path, identifier="cognito:repair-sub")

    with repaired._connect() as connection:
        notebook_parent = next(
            row
            for row in connection.execute("PRAGMA foreign_key_list(notebooks)")
            if str(row["from"]) == "user_id"
        )
        assert str(notebook_parent["table"]) == "users"
        assert connection.execute(
            "PRAGMA foreign_key_check(notebooks)"
        ).fetchall() == []
        assert connection.execute(
            "SELECT COUNT(*) FROM messages WHERE id=?", (message_id,)
        ).fetchone()[0] == 1
        assert connection.execute(
            "SELECT COUNT(*) FROM sources WHERE id=?", (source_id,)
        ).fetchone()[0] == 1

    assert repaired.get_thread(notebook_id)["name"] == "Existing notebook"
    assert repaired.create_thread(
        name="Notebook after repair",
        model_id="mock",
        support_mode="critical-thinking",
    )

    # A second startup is a no-op and proves the migration is idempotent.
    StudentStore(db_path, identifier="cognito:repair-sub")


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
