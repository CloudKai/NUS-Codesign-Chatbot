"""SQLite compatibility migrations applied during local store startup.

Production DSQL never imports or runs these functions; its schema lifecycle is
owned by ``scripts/init_dsql.py``. The functions preserve the historical
automatic local-database repair order and transaction behavior.
"""

from __future__ import annotations

import sqlite3


def migrate_student_artifact_versions(connection: sqlite3.Connection) -> None:
    """Add the bounded version-history table additively; legacy artifacts gain history on their next save."""
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS student_artifact_versions (
            id TEXT PRIMARY KEY,
            artifact_id TEXT NOT NULL,
            notebook_id TEXT NOT NULL,
            user_id TEXT NOT NULL,
            revision INTEGER NOT NULL,
            title TEXT NOT NULL,
            kind TEXT NOT NULL,
            document_text TEXT NOT NULL,
            origin TEXT NOT NULL,
            restored_from INTEGER,
            created_at TEXT NOT NULL,
            UNIQUE (artifact_id, revision)
        )
        """
    )
    connection.execute(
        "CREATE INDEX IF NOT EXISTS idx_student_artifact_versions_artifact "
        "ON student_artifact_versions(artifact_id, revision)"
    )


def migrate_student_artifact_kind(connection: sqlite3.Connection) -> None:
    """Add the artifact category column additively; legacy artifacts are general notes."""
    columns = {str(row[1]) for row in connection.execute("PRAGMA table_info(student_artifacts)")}
    if 'kind' not in columns:
        connection.execute("ALTER TABLE student_artifacts ADD COLUMN kind TEXT NOT NULL DEFAULT 'notes'")


def migrate_student_artifacts(connection: sqlite3.Connection) -> None:
    """Add the persistent artifact table and index additively to legacy stores.

    Existing rows in every other table are untouched. The statement matches the
    canonical schema, so pre-artifact databases upgrade in place and the
    rollback path is a source-only revert of this migration plus the schema.
    """
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS student_artifacts (
            id TEXT PRIMARY KEY,
            notebook_id TEXT NOT NULL,
            user_id TEXT NOT NULL,
            title TEXT NOT NULL,
            document_text TEXT NOT NULL,
            schema_version INTEGER NOT NULL DEFAULT 1,
            revision INTEGER NOT NULL DEFAULT 1,
            origin TEXT NOT NULL DEFAULT 'editor',
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            FOREIGN KEY (notebook_id) REFERENCES notebooks(id) ON DELETE CASCADE,
            FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
        )
        """
    )
    connection.execute(
        "CREATE INDEX IF NOT EXISTS idx_student_artifacts_notebook_updated "
        "ON student_artifacts(notebook_id, updated_at)"
    )


def migrate_artifact_reference_columns(connection: sqlite3.Connection) -> None:
    """Add the evidence-reference columns additively; legacy artifacts start with none."""
    for table in ('student_artifacts', 'student_artifact_versions'):
        columns = {str(row[1]) for row in connection.execute(f'PRAGMA table_info({table})')}
        if 'references_text' not in columns:
            connection.execute(
                f"ALTER TABLE {table} ADD COLUMN references_text TEXT NOT NULL DEFAULT '[]'")


def migrate_student_artifact_request_id(connection: sqlite3.Connection) -> None:
    """Add the idempotent create key and retry fingerprint additively; legacy rows keep NULLs."""
    columns = {str(row[1]) for row in connection.execute("PRAGMA table_info(student_artifacts)")}
    if 'request_id' not in columns:
        connection.execute("ALTER TABLE student_artifacts ADD COLUMN request_id TEXT")
    if 'request_fingerprint' not in columns:
        connection.execute("ALTER TABLE student_artifacts ADD COLUMN request_fingerprint TEXT")
    connection.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS idx_student_artifacts_request "
        "ON student_artifacts(notebook_id, request_id) WHERE request_id IS NOT NULL"
    )


def migrate_student_canvases(connection: sqlite3.Connection) -> None:
    """Add the persistent canvas table and index additively to legacy stores.

    Existing rows in every other table are untouched. The statement matches the
    canonical schema, so pre-canvas databases upgrade in place and the
    rollback path is a source-only revert of this migration plus the schema.
    """
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS student_canvases (
            id TEXT PRIMARY KEY,
            notebook_id TEXT NOT NULL,
            user_id TEXT NOT NULL,
            title TEXT NOT NULL,
            graph_text TEXT NOT NULL,
            schema_version INTEGER NOT NULL DEFAULT 1,
            revision INTEGER NOT NULL DEFAULT 1,
            origin TEXT NOT NULL DEFAULT 'editor',
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            FOREIGN KEY (notebook_id) REFERENCES notebooks(id) ON DELETE CASCADE,
            FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
        )
        """
    )
    connection.execute(
        "CREATE INDEX IF NOT EXISTS idx_student_canvases_notebook_updated "
        "ON student_canvases(notebook_id, updated_at)"
    )


def migrate_student_canvas_versions(connection: sqlite3.Connection) -> None:
    """Add the bounded canvas version-history table additively; legacy canvases gain history on their next save."""
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS student_canvas_versions (
            id TEXT PRIMARY KEY,
            canvas_id TEXT NOT NULL,
            notebook_id TEXT NOT NULL,
            user_id TEXT NOT NULL,
            revision INTEGER NOT NULL,
            title TEXT NOT NULL,
            graph_text TEXT NOT NULL,
            origin TEXT NOT NULL,
            restored_from INTEGER,
            created_at TEXT NOT NULL,
            UNIQUE (canvas_id, revision)
        )
        """
    )
    connection.execute(
        "CREATE INDEX IF NOT EXISTS idx_student_canvas_versions_canvas "
        "ON student_canvas_versions(canvas_id, revision)"
    )


def migrate_guest_claim_columns(connection: sqlite3.Connection) -> None:
    """Add the small retry tombstone fields to existing guest sessions."""
    columns = {str(row[1]) for row in connection.execute("PRAGMA table_info(guest_sessions)")}
    for name in (
        "claim_user_id", "claim_operation_id", "claim_result_text", "claim_expires_at",
        "preview_user_id", "preview_operation_id", "preview_fingerprint", "preview_expires_at",
    ):
        if name not in columns:
            connection.execute(f"ALTER TABLE guest_sessions ADD COLUMN {name} TEXT")


def migrate_oauth_login_states(connection: sqlite3.Connection) -> None:
    """Rebuild legacy camelCase OAuth state columns to snake_case."""
    rows = connection.execute(
        "SELECT name FROM sqlite_master WHERE type = 'table' AND name = ?",
        ("oauth_login_states",),
    ).fetchall()
    if not rows:
        return
    columns = {
        str(row[1])
        for row in connection.execute("PRAGMA table_info(oauth_login_states)")
    }
    if {"state", "code_verifier", "created_at", "expires_at"}.issubset(columns):
        return
    connection.execute(
        "ALTER TABLE oauth_login_states RENAME TO oauth_login_states_legacy"
    )
    connection.execute(
        """
        CREATE TABLE oauth_login_states (
            state TEXT PRIMARY KEY,
            code_verifier TEXT NOT NULL,
            created_at TEXT NOT NULL,
            expires_at TEXT NOT NULL
        )
        """
    )
    legacy = {
        str(row[1])
        for row in connection.execute("PRAGMA table_info(oauth_login_states_legacy)")
    }
    if {"state", "codeVerifier", "createdAt", "expiresAt"}.issubset(legacy):
        connection.execute(
            """
            INSERT INTO oauth_login_states
              (state, code_verifier, created_at, expires_at)
            SELECT state, codeVerifier, createdAt, expiresAt
            FROM oauth_login_states_legacy
            """
        )
    connection.execute("DROP TABLE oauth_login_states_legacy")


def migrate_users_table(connection: sqlite3.Connection) -> None:
    """Add five-table user fields without replacing the legacy table."""
    rows = connection.execute(
        "SELECT name FROM sqlite_master WHERE type = 'table' AND name = ?",
        ("users",),
    ).fetchall()
    if not rows:
        return
    columns = {str(row[1]) for row in connection.execute("PRAGMA table_info(users)")}
    expected = {
        "id",
        "identifier",
        "cognito_sub",
        "email",
        "display_name",
        "role",
        "preferences_text",
        "created_at",
        "updated_at",
        "last_login_at",
    }
    if expected.issubset(columns):
        return
    additions = {
        "cognito_sub": "TEXT",
        "email": "TEXT",
        "display_name": "TEXT",
        "role": "TEXT NOT NULL DEFAULT 'student'",
        "preferences_text": "TEXT NOT NULL DEFAULT '{}'",
        "created_at": "TEXT NOT NULL DEFAULT ''",
        "updated_at": "TEXT",
        "last_login_at": "TEXT",
    }
    for name, declaration in additions.items():
        if name not in columns:
            connection.execute(f"ALTER TABLE users ADD COLUMN {name} {declaration}")
    copies = {
        "cognito_sub": "cognitoSub",
        "display_name": "displayName",
        "preferences_text": "metadata",
        "created_at": "createdAt",
        "updated_at": "updatedAt",
        "last_login_at": "lastLoginAt",
    }
    for target, source in copies.items():
        if source not in columns:
            continue
        connection.execute(
            f"UPDATE users SET {target}={source} "
            f"WHERE {source} IS NOT NULL AND TRIM(CAST({source} AS TEXT)) != ''"
        )
    connection.execute(
        "UPDATE users SET display_name='Student' "
        "WHERE display_name IS NULL OR TRIM(display_name)=''"
    )
    connection.execute(
        "UPDATE users SET role='student' WHERE role IS NULL OR TRIM(role)=''"
    )
    connection.execute(
        "UPDATE users SET preferences_text='{}' "
        "WHERE preferences_text IS NULL OR TRIM(preferences_text)=''"
    )


def migrate_notebook_revision(connection: sqlite3.Connection) -> None:
    """Add or repair the notebook conversation revision column."""
    columns = {
        str(row["name"])
        for row in connection.execute("PRAGMA table_info(notebooks)")
    }
    if "conversation_revision" not in columns:
        connection.execute(
            "ALTER TABLE notebooks ADD COLUMN conversation_revision "
            "INTEGER NOT NULL DEFAULT 0"
        )
        return
    connection.execute(
        "UPDATE notebooks SET conversation_revision = 0 "
        "WHERE conversation_revision IS NULL"
    )


def migrate_message_revisions(connection: sqlite3.Connection) -> None:
    """Add or repair append-only message revision columns."""
    columns = {
        str(row["name"])
        for row in connection.execute("PRAGMA table_info(messages)")
    }
    if "conversation_revision" not in columns:
        connection.execute(
            "ALTER TABLE messages ADD COLUMN conversation_revision "
            "INTEGER NOT NULL DEFAULT 0"
        )
    else:
        connection.execute(
            "UPDATE messages SET conversation_revision = 0 "
            "WHERE conversation_revision IS NULL"
        )
    if "previous_message_id" not in columns:
        connection.execute("ALTER TABLE messages ADD COLUMN previous_message_id TEXT")
    if "superseded_at_revision" not in columns:
        connection.execute(
            "ALTER TABLE messages ADD COLUMN superseded_at_revision INTEGER"
        )


def repair_misbound_notebook_foreign_key(connection: sqlite3.Connection) -> None:
    """Repair notebooks whose legacy FK points at removed ``users_legacy``."""
    foreign_keys = connection.execute("PRAGMA foreign_key_list(notebooks)").fetchall()
    user_key = next(
        (row for row in foreign_keys if str(row["from"]) == "user_id"),
        None,
    )
    if user_key is None or str(user_key["table"]) == "users":
        return
    expected_columns = (
        "id",
        "user_id",
        "title",
        "current_stage",
        "progress_text",
        "settings_text",
        "conversation_revision",
        "created_at",
        "updated_at",
    )
    actual_columns = tuple(
        str(row["name"])
        for row in connection.execute("PRAGMA table_info(notebooks)")
    )
    if actual_columns != expected_columns:
        raise RuntimeError(
            "Cannot safely repair the local notebooks foreign key because "
            f"its columns differ from the expected schema: {actual_columns!r}"
        )
    connection.commit()
    connection.execute("PRAGMA foreign_keys = OFF")
    try:
        connection.execute("BEGIN IMMEDIATE")
        connection.execute(
            """
            CREATE TABLE notebooks_fk_repair (
                id TEXT PRIMARY KEY,
                user_id TEXT NOT NULL,
                title TEXT,
                current_stage TEXT NOT NULL DEFAULT 'problem_identification',
                progress_text TEXT NOT NULL DEFAULT '{}',
                settings_text TEXT NOT NULL DEFAULT '{}',
                conversation_revision INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
            )
            """
        )
        connection.execute(
            """
            INSERT INTO notebooks_fk_repair
              (id, user_id, title, current_stage, progress_text,
               settings_text, conversation_revision, created_at, updated_at)
            SELECT id, user_id, title, current_stage, progress_text,
                   settings_text, COALESCE(conversation_revision, 0),
                   created_at, updated_at
            FROM notebooks
            """
        )
        connection.execute("DROP TABLE notebooks")
        connection.execute("ALTER TABLE notebooks_fk_repair RENAME TO notebooks")
        connection.execute(
            "CREATE INDEX idx_notebooks_user_updated ON notebooks(user_id, updated_at)"
        )
        violations = connection.execute("PRAGMA foreign_key_check(notebooks)").fetchall()
        if violations:
            raise RuntimeError(
                "Cannot repair the local notebooks foreign key because "
                "one or more notebooks have no matching user"
            )
        connection.commit()
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.execute("PRAGMA foreign_keys = ON")
