"""SQLite compatibility migrations applied during local store startup.

Production DSQL never imports or runs these functions; its schema lifecycle is
owned by ``scripts/init_dsql.py``. The functions preserve the historical
automatic local-database repair order and transaction behavior.
"""

from __future__ import annotations

import sqlite3


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
        "id", "identifier", "cognito_sub", "email", "display_name", "role",
        "preferences_text", "created_at", "updated_at", "last_login_at",
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
        "id", "user_id", "title", "current_stage", "progress_text",
        "settings_text", "conversation_revision", "created_at", "updated_at",
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
                current_stage TEXT NOT NULL DEFAULT 'focus',
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
