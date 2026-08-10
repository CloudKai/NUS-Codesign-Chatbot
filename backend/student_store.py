"""Student persistence shared by FastAPI, Streamlit, and DSQL.

Logical production schema (Cognito owns the browser session; no app_sessions):

    users
     └── notebooks
          ├── messages
          └── sources → S3 object keys

    oauth_login_states  (pre-auth, transient)

Public method names such as ``create_thread`` / ``thread_id`` remain as
compatibility wrappers over ``notebooks`` so API and UI churn stays limited.
"""

from __future__ import annotations

import json
import shutil
import sqlite3
import threading
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from .settings import settings


_COACH_IDEMPOTENCY_MARKER = "coach_idempotency"


class CoachIdempotencyConflictError(ValueError):
    """Raised when one idempotency key is reused for a different coach request."""


class CoachRequestLeaseLostError(RuntimeError):
    """Raised when an expired reservation was claimed by another worker."""


class CoachRequestInProgressError(RuntimeError):
    """Raised when another worker still owns an active coach request lease."""


class ConversationRevisionConflictError(ValueError):
    """Raised when a coach result targets a stale conversation_revision."""


@dataclass(frozen=True)
class ConversationRevisionResult:
    """Authoritative notebook state after an append-only conversation revision.

    ``edited_message_id`` is the new replacement user-message id (not the
    superseded original). ``surviving_history`` is the active branch at the
    new notebook revision.
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


def _dump(value: Any) -> str:
    """Serialize *value* as JSON text for TEXT columns."""
    return json.dumps(value, ensure_ascii=False)


def _load(value: str | None, default: Any) -> Any:
    """Deserialize a JSON TEXT column, returning *default* on empty/invalid."""
    if not value:
        return default
    try:
        return json.loads(value)
    except (TypeError, json.JSONDecodeError):
        return default


# Progress blob keys (never include current_stage — that is notebooks.current_stage).
_PROGRESS_KEYS = frozenset(
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

# Notebook settings blob keys.
_SETTINGS_KEYS = frozenset(
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


SCHEMA = """
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS users (
    id TEXT PRIMARY KEY,
    identifier TEXT NOT NULL UNIQUE,
    cognito_sub TEXT,
    email TEXT,
    display_name TEXT,
    role TEXT NOT NULL DEFAULT 'student',
    preferences_text TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL,
    updated_at TEXT,
    last_login_at TEXT
);

CREATE TABLE IF NOT EXISTS oauth_login_states (
    state TEXT PRIMARY KEY,
    code_verifier TEXT NOT NULL,
    created_at TEXT NOT NULL,
    expires_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS notebooks (
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
);

CREATE INDEX IF NOT EXISTS idx_notebooks_user_updated
ON notebooks(user_id, updated_at);

CREATE TABLE IF NOT EXISTS messages (
    id TEXT PRIMARY KEY,
    notebook_id TEXT NOT NULL,
    role TEXT NOT NULL,
    content TEXT NOT NULL,
    is_error INTEGER NOT NULL DEFAULT 0,
    assessment_text TEXT,
    cited_source_ids_text TEXT,
    proposed_stage TEXT,
    decision_status TEXT,
    decision_at TEXT,
    metadata_text TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL,
    conversation_revision INTEGER NOT NULL DEFAULT 0,
    previous_message_id TEXT,
    superseded_at_revision INTEGER,
    FOREIGN KEY (notebook_id) REFERENCES notebooks(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_messages_notebook_created
ON messages(notebook_id, created_at, id);

CREATE INDEX IF NOT EXISTS idx_messages_notebook_decision
ON messages(notebook_id, decision_status, created_at);

CREATE TABLE IF NOT EXISTS sources (
    id TEXT PRIMARY KEY,
    notebook_id TEXT NOT NULL,
    kind TEXT NOT NULL,
    title TEXT NOT NULL,
    content_type TEXT,
    byte_size INTEGER NOT NULL DEFAULT 0,
    object_key TEXT,
    extracted_text_key TEXT,
    source_url TEXT,
    selected INTEGER NOT NULL DEFAULT 1,
    metadata_text TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    FOREIGN KEY (notebook_id) REFERENCES notebooks(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_sources_notebook_created
ON sources(notebook_id, created_at, id);
"""


# Child tables deleted explicitly when a notebook is removed (DSQL has no FK cascade).
NOTEBOOK_CHILD_TABLES = ("messages", "sources")


class StudentStore:
    """Framework-neutral store for notebooks, messages, sources, and auth users."""

    def __init__(self, path: Path | None = None, identifier: str = "local-student", *, ensure_owner: bool = True):
        """Open (or create) the local SQLite database for *identifier*.

        When ``ensure_owner`` is False the store can run auth/OAuth helpers
        without inserting a user row (used for production DSQL bootstrap).
        """
        self.path = (path or settings.database_path).resolve()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.identifier = identifier
        self._lock = threading.RLock()
        with self._connect() as connection:
            connection.executescript(SCHEMA)
            self._migrate_oauth_login_states(connection)
            self._migrate_users_table(connection)
            self._migrate_notebooks_conversation_revision(connection)
            self._migrate_messages_revision_columns(connection)
            self._repair_misbound_local_foreign_keys(connection)
            self._migrate_legacy_workspace(connection)
            # Index after users migration so legacy camelCase DBs can rebuild first.
            connection.execute(
                "CREATE UNIQUE INDEX IF NOT EXISTS idx_users_cognito_sub "
                "ON users(cognito_sub)"
            )
        self.owner_id = self._ensure_user() if ensure_owner else ""

    def ping(self) -> None:
        """Verify the database connection without creating or reading a user row."""
        with self._connect() as connection:
            connection.execute("SELECT 1").fetchone()

    @staticmethod
    def _migrate_oauth_login_states(connection: sqlite3.Connection) -> None:
        """Rebuild legacy camelCase ``oauth_login_states`` to snake_case columns.

        Older local DBs still have Streamlit-era ``codeVerifier`` / ``expiresAt``
        columns. ``CREATE TABLE IF NOT EXISTS`` does not rename them, so login
        then fails with ``no such column: expires_at`` and the browser sees a
        blank/white page. Rows are one-time PKCE state and safe to remap or drop.
        """
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
            for row in connection.execute(
                "PRAGMA table_info(oauth_login_states_legacy)"
            )
        }
        if {
            "state",
            "codeVerifier",
            "createdAt",
            "expiresAt",
        }.issubset(legacy):
            connection.execute(
                """
                INSERT INTO oauth_login_states
                  (state, code_verifier, created_at, expires_at)
                SELECT state, codeVerifier, createdAt, expiresAt
                FROM oauth_login_states_legacy
                """
            )
        connection.execute("DROP TABLE oauth_login_states_legacy")

    @staticmethod
    def _migrate_users_table(connection: sqlite3.Connection) -> None:
        """Extend legacy camelCase ``users`` rows for the five-table schema.

        Local demo DBs often still have ``displayName`` / ``cognitoSub`` /
        ``createdAt`` / ``metadata`` from the pre-Cognito store. Cognito
        callback upserts require snake_case columns; without this migration
        sign-in completes at Cognito then fails with ``auth_error=1``.

        This migration is deliberately additive. Renaming and dropping the old
        ``users`` table makes SQLite rewrite legacy foreign keys to
        ``users_legacy`` and then cascade-delete old threads, sources, and
        messages. Keeping the original table identity preserves those rows
        while the compatibility migration copies them into the five-table
        layout.
        """
        rows = connection.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table' AND name = ?",
            ("users",),
        ).fetchall()
        if not rows:
            return
        columns = {
            str(row[1]) for row in connection.execute("PRAGMA table_info(users)")
        }
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
                connection.execute(
                    f"ALTER TABLE users ADD COLUMN {name} {declaration}"
                )

        # Copy old values only when their camelCase source columns exist.
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

    @staticmethod
    def _migrate_notebooks_conversation_revision(
        connection: sqlite3.Connection,
    ) -> None:
        """Add ``conversation_revision`` for edit/revise CAS on existing DBs."""
        columns = {
            str(row["name"])
            for row in connection.execute("PRAGMA table_info(notebooks)")
        }
        if "conversation_revision" in columns:
            return
        connection.execute(
            "ALTER TABLE notebooks ADD COLUMN conversation_revision "
            "INTEGER NOT NULL DEFAULT 0"
        )

    @staticmethod
    def _migrate_messages_revision_columns(
        connection: sqlite3.Connection,
    ) -> None:
        """Add append-only message revision columns on existing local DBs."""
        columns = {
            str(row["name"])
            for row in connection.execute("PRAGMA table_info(messages)")
        }
        if "conversation_revision" not in columns:
            connection.execute(
                "ALTER TABLE messages ADD COLUMN conversation_revision "
                "INTEGER NOT NULL DEFAULT 0"
            )
        if "previous_message_id" not in columns:
            connection.execute(
                "ALTER TABLE messages ADD COLUMN previous_message_id TEXT"
            )
        if "superseded_at_revision" not in columns:
            connection.execute(
                "ALTER TABLE messages ADD COLUMN superseded_at_revision INTEGER"
            )

    @staticmethod
    def _notebook_revision_value(row: Any) -> int:
        """Return a notebook ``conversation_revision``, treating NULL as 0."""
        try:
            return int(row["conversation_revision"] or 0)
        except (KeyError, IndexError, TypeError, ValueError):
            return 0

    @staticmethod
    def _message_revision_value(row: Any) -> int:
        """Return a message ``conversation_revision``, treating NULL as 0."""
        try:
            return int(row["conversation_revision"] or 0)
        except (KeyError, IndexError, TypeError, ValueError):
            return 0

    @staticmethod
    def _message_superseded_at(row: Any) -> int | None:
        """Return ``superseded_at_revision`` or ``None`` when unset/invalid."""
        try:
            value = row["superseded_at_revision"]
        except (KeyError, IndexError, TypeError):
            return None
        if value is None:
            return None
        try:
            return int(value)
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _message_previous_id(row: Any) -> str | None:
        """Return ``previous_message_id`` when present."""
        try:
            value = row["previous_message_id"]
        except (KeyError, IndexError, TypeError):
            return None
        if value is None:
            return None
        text = str(value).strip()
        return text or None

    @classmethod
    def _is_active_at_revision(cls, row: Any, revision: int) -> bool:
        """Return whether *row* is visible in conversation snapshot *revision*."""
        if cls._message_revision_value(row) > revision:
            return False
        superseded = cls._message_superseded_at(row)
        if superseded is not None and superseded <= revision:
            return False
        return True

    @staticmethod
    def _active_at_revision_sql(alias: str = "") -> str:
        """SQL predicate for messages active at a bound revision parameter.

        The predicate expects two identical revision bind values.
        """
        prefix = f"{alias}." if alias else ""
        return (
            f"COALESCE({prefix}conversation_revision, 0) <= ? "
            f"AND ({prefix}superseded_at_revision IS NULL "
            f"OR {prefix}superseded_at_revision > ?)"
        )

    @classmethod
    def _public_message_dict(cls, row: Any) -> dict[str, Any]:
        """Map a messages row to the public chat-message dict shape."""
        meta = _load(row["metadata_text"], {})
        if not isinstance(meta, dict):
            meta = {}
        assessment = _load(row["assessment_text"], None)
        if isinstance(assessment, dict):
            meta["assessment"] = assessment
        cited = _load(row["cited_source_ids_text"], None)
        if cited is not None:
            meta["source_refs"] = cited
        if row["proposed_stage"]:
            meta["proposed_stage"] = row["proposed_stage"]
            meta["pending_transition_id"] = str(row["id"])
        if row["decision_status"]:
            meta["decision_status"] = row["decision_status"]
        return {
            "id": str(row["id"]),
            "role": str(row["role"]),
            "content": row["content"] or "",
            "metadata": meta,
            "created_at": row["created_at"],
            "is_error": bool(row["is_error"]),
            "feedback": None,
            "conversation_revision": cls._message_revision_value(row),
            "previous_message_id": cls._message_previous_id(row),
            "superseded_at_revision": cls._message_superseded_at(row),
        }

    @staticmethod
    def _is_coach_idempotency_marker_meta(meta: Any) -> bool:
        """Return whether *meta* is an internal coach idempotency marker."""
        return (
            isinstance(meta, dict)
            and meta.get("_internal_type") == _COACH_IDEMPOTENCY_MARKER
        )

    @staticmethod
    def _collect_idempotency_keys_from_meta(meta: Any) -> list[str]:
        """Extract non-empty coach/request idempotency keys from message metadata."""
        if not isinstance(meta, dict):
            return []
        keys: list[str] = []
        for field in ("idempotency_key", "coach_idempotency_key"):
            key = str(meta.get(field) or "").strip()
            if key:
                keys.append(key)
        return keys

    @staticmethod
    def _repair_misbound_local_foreign_keys(
        connection: sqlite3.Connection,
    ) -> None:
        """Repair notebooks created by the retired destructive user migration.

        A previous local compatibility migration renamed ``users`` to
        ``users_legacy`` before rebuilding it. SQLite consequently rewrote the
        existing ``notebooks.user_id`` foreign key to reference that temporary
        name. Dropping the temporary table left Cognito-authenticated notebook
        creation failing with ``no such table: main.users_legacy``.

        Rebuilding ``notebooks`` is SQLite-only, transactional, and preserves
        its primary keys, so existing ``messages`` and ``sources`` continue to
        reference the same notebooks. Production DSQL never invokes this
        initializer and its schema is intentionally unchanged.
        """
        foreign_keys = connection.execute(
            "PRAGMA foreign_key_list(notebooks)"
        ).fetchall()
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

        # PRAGMA foreign_keys is ignored inside an active transaction. Commit
        # preceding additive migrations before entering this isolated rebuild.
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
            connection.execute(
                "ALTER TABLE notebooks_fk_repair RENAME TO notebooks"
            )
            connection.execute(
                "CREATE INDEX idx_notebooks_user_updated "
                "ON notebooks(user_id, updated_at)"
            )
            violations = connection.execute(
                "PRAGMA foreign_key_check(notebooks)"
            ).fetchall()
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

    @staticmethod
    def _migrate_legacy_workspace(connection: sqlite3.Connection) -> None:
        """Copy legacy local workspace rows into the five production tables.

        The old tables remain untouched as a rollback source. Inserts are
        idempotent, so interrupted startup can safely retry. This compatibility
        path is SQLite-only; production DSQL is bootstrapped directly with the
        five-table schema.
        """

        def _table(name: str) -> bool:
            return connection.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
                (name,),
            ).fetchone() is not None

        if not _table("threads"):
            return

        user_ids = {
            str(row[0])
            for row in connection.execute("SELECT id FROM users").fetchall()
        }
        identifiers = {
            str(row[1]): str(row[0])
            for row in connection.execute("SELECT id, identifier FROM users").fetchall()
        }
        for row in connection.execute("SELECT * FROM threads").fetchall():
            value = dict(row)
            owner_id = str(value.get("userId") or "")
            if owner_id not in user_ids:
                owner_id = identifiers.get(str(value.get("userIdentifier") or ""), "")
            if not owner_id:
                continue
            metadata = _load(value.get("metadata"), {})
            if not isinstance(metadata, dict):
                metadata = {}
            tags = _load(value.get("tags"), [])
            if isinstance(tags, list):
                metadata["tags"] = tags
            stage, progress_text, settings_text = StudentStore._split_notebook_metadata(
                metadata
            )
            created_at = str(value.get("createdAt") or utc_now())
            connection.execute(
                """
                INSERT OR IGNORE INTO notebooks
                  (id, user_id, title, current_stage, progress_text,
                   settings_text, conversation_revision, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, 0, ?, ?)
                """,
                (
                    str(value["id"]),
                    owner_id,
                    value.get("name"),
                    stage,
                    progress_text,
                    settings_text,
                    created_at,
                    created_at,
                ),
            )

        transition_by_id: dict[str, dict[str, Any]] = {}
        if _table("phase_transitions"):
            transition_by_id = {
                str(value["id"]): value
                for value in (
                    dict(row)
                    for row in connection.execute(
                        "SELECT * FROM phase_transitions"
                    ).fetchall()
                )
            }

        if _table("steps"):
            for row in connection.execute(
                "SELECT * FROM steps WHERE type IN ('user_message','assistant_message')"
            ).fetchall():
                value = dict(row)
                notebook_id = str(value.get("threadId") or "")
                if connection.execute(
                    "SELECT 1 FROM notebooks WHERE id=?", (notebook_id,)
                ).fetchone() is None:
                    continue
                metadata = _load(value.get("metadata"), {})
                if not isinstance(metadata, dict):
                    metadata = {}
                assessment = metadata.pop("assessment", None)
                cited = metadata.pop("source_refs", None)
                transition_id = str(metadata.get("pending_transition_id") or "")
                transition = transition_by_id.get(transition_id)
                proposed_stage = transition.get("toStage") if transition else None
                decision_status = transition.get("status") if transition else None
                decision_at = transition.get("resolvedAt") if transition else None
                if transition:
                    metadata.setdefault("from_stage", transition.get("fromStage"))
                    assessment = assessment or _load(transition.get("assessment"), {})
                connection.execute(
                    """
                    INSERT OR IGNORE INTO messages
                      (id, notebook_id, role, content, is_error, assessment_text,
                       cited_source_ids_text, proposed_stage, decision_status,
                       decision_at, metadata_text, created_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        str(value["id"]),
                        notebook_id,
                        "user" if value.get("type") == "user_message" else "assistant",
                        str(value.get("output") or ""),
                        int(bool(value.get("isError"))),
                        _dump(assessment) if isinstance(assessment, dict) else None,
                        _dump(cited) if cited is not None else None,
                        proposed_stage,
                        decision_status,
                        decision_at,
                        _dump(metadata),
                        str(value.get("createdAt") or utc_now()),
                    ),
                )

        if _table("notebook_sources"):
            for row in connection.execute("SELECT * FROM notebook_sources").fetchall():
                value = dict(row)
                notebook_id = str(value.get("threadId") or "")
                if connection.execute(
                    "SELECT 1 FROM notebooks WHERE id=?", (notebook_id,)
                ).fetchone() is None:
                    continue
                metadata = _load(value.get("metadata"), {})
                if not isinstance(metadata, dict):
                    metadata = {}
                path = str(value.get("path") or "").strip()
                storage_provider = str(metadata.get("storage_provider") or "local")
                object_key = metadata.get("object_key")
                if not object_key and (
                    path.startswith("users/") or storage_provider in {"s3", "memory"}
                ):
                    object_key = path or None
                elif path:
                    metadata.setdefault("local_path", path)
                extracted = str(value.get("extractedText") or "")
                if extracted:
                    # Kept inside the local compatibility row; _source_dict removes
                    # this private key before returning metadata to API callers.
                    metadata["_legacy_extracted_text"] = extracted
                created_at = str(value.get("createdAt") or utc_now())
                connection.execute(
                    """
                    INSERT OR IGNORE INTO sources
                      (id, notebook_id, kind, title, content_type, byte_size,
                       object_key, extracted_text_key, source_url, selected,
                       metadata_text, created_at, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, NULL, ?, ?, ?, ?, ?)
                    """,
                    (
                        str(value["id"]),
                        notebook_id,
                        str(value.get("kind") or "file"),
                        str(value.get("title") or "Untitled source"),
                        str(value.get("mime") or "application/octet-stream"),
                        max(0, int(value.get("size") or 0)),
                        object_key,
                        value.get("sourceUrl"),
                        int(bool(value.get("selected", 1))),
                        _dump(metadata),
                        created_at,
                        str(value.get("updatedAt") or created_at),
                    ),
                )

    def upsert_cognito_user(
        self,
        *,
        cognito_sub: str,
        identifier: str,
        email: str | None,
        display_name: str,
    ) -> dict[str, Any]:
        """Create or update a user row keyed by Cognito ``sub``.

        Never elevates role from client input. Preserves lecturer/admin roles.
        Does not store Cognito tokens.
        """
        from backend.auth_profiles import STUDENT_ROLE, resolve_role

        sub = str(cognito_sub or "").strip()
        if not sub:
            raise ValueError("cognito_sub is required")
        now = utc_now()
        safe_name = (display_name or "Student").strip()[:80] or "Student"
        safe_email = (email or "").strip() or None
        with self._lock, self._connect() as connection:
            row = connection.execute(
                "SELECT id, role, display_name, email, preferences_text, cognito_sub "
                "FROM users WHERE cognito_sub = ?",
                (sub,),
            ).fetchone()
            created = False
            if row is None:
                row = connection.execute(
                    "SELECT id, role, display_name, email, preferences_text, cognito_sub "
                    "FROM users WHERE identifier = ?",
                    (identifier,),
                ).fetchone()
                if row is not None:
                    created = not bool(row["cognito_sub"])
            if row:
                existing_role = str(row["role"] or STUDENT_ROLE)
                role = resolve_role(existing_role)
                connection.execute(
                    "UPDATE users SET identifier = ?, cognito_sub = ?, email = ?, "
                    "display_name = ?, role = ?, updated_at = ?, last_login_at = ? "
                    "WHERE id = ?",
                    (
                        identifier,
                        sub,
                        safe_email,
                        safe_name,
                        role,
                        now,
                        now,
                        str(row["id"]),
                    ),
                )
                return {
                    "id": str(row["id"]),
                    "display_name": safe_name,
                    "role": role,
                    "created": created,
                }
            owner_id = str(uuid.uuid4())
            role = STUDENT_ROLE
            prefs = _dump({"role": role, "auth": "cognito"})
            inserted = connection.execute(
                "INSERT OR IGNORE INTO users ("
                "id, identifier, cognito_sub, email, display_name, role, "
                "preferences_text, created_at, updated_at, last_login_at"
                ") VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    owner_id,
                    identifier,
                    sub,
                    safe_email,
                    safe_name,
                    role,
                    prefs,
                    now,
                    now,
                    now,
                ),
            )
            canonical = connection.execute(
                "SELECT id, role FROM users WHERE cognito_sub = ?",
                (sub,),
            ).fetchone()
            if canonical is None:
                raise ValueError("Cognito identity could not be linked safely")
            role = resolve_role(str(canonical["role"] or STUDENT_ROLE))
            connection.execute(
                "UPDATE users SET identifier = ?, email = ?, display_name = ?, "
                "role = ?, updated_at = ?, last_login_at = ? WHERE id = ?",
                (
                    identifier,
                    safe_email,
                    safe_name,
                    role,
                    now,
                    now,
                    str(canonical["id"]),
                ),
            )
            return {
                "id": str(canonical["id"]),
                "display_name": safe_name,
                "role": role,
                "created": inserted.rowcount == 1,
            }

    def get_user_by_cognito_sub(self, cognito_sub: str) -> dict[str, Any] | None:
        """Return a user profile dict for the Cognito subject, if present."""
        sub = str(cognito_sub or "").strip()
        if not sub:
            return None
        with self._connect() as connection:
            row = connection.execute(
                "SELECT id, identifier, cognito_sub, email, display_name, role, "
                "created_at, updated_at, last_login_at FROM users WHERE cognito_sub = ?",
                (sub,),
            ).fetchone()
        if not row:
            return None
        return self._user_profile_dict(row)

    def get_user_by_id(self, user_id: str) -> dict[str, Any] | None:
        """Return a user profile dict for the internal user id, if present."""
        owner_id = str(user_id or "").strip()
        if not owner_id:
            return None
        with self._connect() as connection:
            row = connection.execute(
                "SELECT id, identifier, cognito_sub, email, display_name, role, "
                "created_at, updated_at, last_login_at FROM users WHERE id = ?",
                (owner_id,),
            ).fetchone()
        if not row:
            return None
        return self._user_profile_dict(row)

    @staticmethod
    def _user_profile_dict(row: Any) -> dict[str, Any]:
        """Normalize a users row into the public profile shape."""
        return {
            "id": str(row["id"]),
            "identifier": str(row["identifier"]),
            "cognito_sub": row["cognito_sub"],
            "email": row["email"],
            "display_name": row["display_name"],
            "role": row["role"] or "student",
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
            "last_login_at": row["last_login_at"],
        }

    def save_oauth_login_state(
        self,
        *,
        state: str,
        code_verifier: str,
        created_at: str,
        expires_at: str,
    ) -> None:
        """Persist one-time OAuth state + PKCE verifier until callback."""
        state_value = str(state or "").strip()
        verifier = str(code_verifier or "").strip()
        if not state_value or not verifier:
            raise ValueError("state and code_verifier are required")
        with self._lock, self._connect() as connection:
            # Login is the natural bounded cleanup point; no scheduler is needed
            # for transient states abandoned before the callback.
            connection.execute(
                "DELETE FROM oauth_login_states WHERE expires_at <= ?",
                (created_at,),
            )
            connection.execute(
                """
                INSERT INTO oauth_login_states
                  (state, code_verifier, created_at, expires_at)
                VALUES (?, ?, ?, ?)
                ON CONFLICT (state) DO UPDATE SET
                  code_verifier=excluded.code_verifier,
                  created_at=excluded.created_at,
                  expires_at=excluded.expires_at
                """,
                (state_value, verifier, created_at, expires_at),
            )

    def consume_oauth_login_state(
        self, state: str, *, now_iso: str | None = None
    ) -> str | None:
        """Return and delete the PKCE verifier for *state*, or ``None`` if invalid."""
        state_value = str(state or "").strip()
        if not state_value:
            return None
        now_value = now_iso or utc_now()
        with self._lock, self._connect() as connection:
            row = connection.execute(
                "SELECT code_verifier, expires_at FROM oauth_login_states WHERE state = ?",
                (state_value,),
            ).fetchone()
            connection.execute(
                "DELETE FROM oauth_login_states WHERE state = ?",
                (state_value,),
            )
            if row is None:
                return None
            if str(row["expires_at"] or "") <= now_value:
                return None
            return str(row["code_verifier"])

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path, timeout=30)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA journal_mode = WAL")
        return connection

    def _ensure_user(self) -> str:
        with self._lock, self._connect() as connection:
            identifier_row = connection.execute(
                "SELECT id, cognito_sub, preferences_text FROM users "
                "WHERE identifier = ?",
                (self.identifier,),
            ).fetchone()
            if self.identifier.startswith("cognito:"):
                cognito_sub = self.identifier.removeprefix("cognito:").strip()
                if cognito_sub:
                    subject_row = connection.execute(
                        "SELECT id, cognito_sub, preferences_text FROM users "
                        "WHERE cognito_sub = ?",
                        (cognito_sub,),
                    ).fetchone()
                    if subject_row:
                        subject_id = str(subject_row["id"])
                        if (
                            identifier_row
                            and str(identifier_row["id"]) != subject_id
                        ):
                            # Repair the split-owner layout created by the first
                            # five-table local build: the canonical identifier
                            # row had no Cognito subject, while the authenticated
                            # profile remained under its legacy identifier.
                            duplicate_id = str(identifier_row["id"])
                            duplicate_preferences = _load(
                                identifier_row["preferences_text"], {}
                            )
                            subject_preferences = _load(
                                subject_row["preferences_text"], {}
                            )
                            if not isinstance(duplicate_preferences, dict):
                                duplicate_preferences = {}
                            if not isinstance(subject_preferences, dict):
                                subject_preferences = {}
                            connection.execute(
                                "UPDATE notebooks SET user_id=? WHERE user_id=?",
                                (subject_id, duplicate_id),
                            )
                            connection.execute(
                                "UPDATE users SET identifier=? WHERE id=?",
                                (f"legacy-orphan:{duplicate_id}", duplicate_id),
                            )
                            connection.execute(
                                "UPDATE users SET identifier=?, preferences_text=?, "
                                "updated_at=? WHERE id=?",
                                (
                                    self.identifier,
                                    _dump(
                                        {
                                            **duplicate_preferences,
                                            **subject_preferences,
                                        }
                                    ),
                                    utc_now(),
                                    subject_id,
                                ),
                            )
                            return subject_id
                        connection.execute(
                            "UPDATE users SET identifier=?, updated_at=? WHERE id=?",
                            (self.identifier, utc_now(), subject_id),
                        )
                        return subject_id
                    if identifier_row:
                        existing_sub = str(identifier_row["cognito_sub"] or "").strip()
                        if existing_sub and existing_sub != cognito_sub:
                            raise ValueError(
                                "Cognito store identifier is linked to another subject"
                            )
                        connection.execute(
                            "UPDATE users SET cognito_sub=?, updated_at=? WHERE id=?",
                            (cognito_sub, utc_now(), str(identifier_row["id"])),
                        )
                        return str(identifier_row["id"])
            if identifier_row:
                return str(identifier_row["id"])
            owner_id = str(uuid.uuid4())
            connection.execute(
                "INSERT INTO users (id, identifier, preferences_text, created_at, role) "
                "VALUES (?, ?, ?, ?, 'student')",
                (
                    owner_id,
                    self.identifier,
                    _dump({"role": "student", "auth": "none"}),
                    utc_now(),
                ),
            )
            return owner_id

    def get_user_preferences(self) -> dict[str, Any]:
        """Return the local user's preference metadata blob."""
        with self._connect() as connection:
            row = connection.execute(
                "SELECT preferences_text FROM users WHERE id = ?",
                (self.owner_id,),
            ).fetchone()
        if not row:
            return {}
        metadata = _load(row["preferences_text"], {})
        return metadata if isinstance(metadata, dict) else {}

    def update_user_preferences(self, patch: dict[str, Any]) -> None:
        """Merge preference keys into the local user's preferences_text."""
        if not patch:
            return
        with self._lock, self._connect() as connection:
            row = connection.execute(
                "SELECT preferences_text FROM users WHERE id = ?",
                (self.owner_id,),
            ).fetchone()
            current = _load(row["preferences_text"] if row else None, {})
            if not isinstance(current, dict):
                current = {}
            next_metadata = {**current, **patch}
            connection.execute(
                "UPDATE users SET preferences_text = ?, updated_at = ? WHERE id = ?",
                (_dump(next_metadata), utc_now(), self.owner_id),
            )

    def create_thread(
        self,
        *,
        name: str = "New assignment chat",
        model_id: str,
        support_mode: str,
        assignment: dict[str, str] | None = None,
    ) -> str:
        """Create a notebook and return its id (``thread_id`` compatibility)."""
        from backend.student_journey import DEFAULT_STAGE

        notebook_id = str(uuid.uuid4())
        now = utc_now()
        settings_blob = {
            "selected_model": model_id,
            "support_mode": support_mode,
            "assignment": assignment or {},
        }
        with self._lock, self._connect() as connection:
            connection.execute(
                """
                INSERT INTO notebooks
                  (id, user_id, title, current_stage, progress_text, settings_text,
                   conversation_revision, created_at, updated_at)
                VALUES (?, ?, ?, ?, '{}', ?, 0, ?, ?)
                """,
                (
                    notebook_id,
                    self.owner_id,
                    name,
                    DEFAULT_STAGE,
                    _dump(settings_blob),
                    now,
                    now,
                ),
            )
        return notebook_id

    def get_thread(self, thread_id: str) -> dict[str, Any] | None:
        """Return one owned notebook in the legacy thread-shaped dict."""
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT * FROM notebooks
                WHERE id = ? AND user_id = ?
                """,
                (thread_id, self.owner_id),
            ).fetchone()
        return self._thread_dict(row) if row else None

    def list_threads(
        self, search: str = "", folder_id: str | None = None
    ) -> list[dict[str, Any]]:
        """List owned notebooks ordered by recent activity.

        *folder_id* is ignored (folder organization was removed).
        """
        del folder_id
        clauses = ["n.user_id = ?"]
        parameters: list[Any] = [self.owner_id]
        if search.strip():
            needle = f"%{search.strip().lower()}%"
            clauses.append(
                "(LOWER(COALESCE(n.title, '')) LIKE ? OR EXISTS "
                "(SELECT 1 FROM messages m WHERE m.notebook_id=n.id AND "
                "COALESCE(m.conversation_revision, 0) <= "
                "COALESCE(n.conversation_revision, 0) AND "
                "(m.superseded_at_revision IS NULL OR "
                "m.superseded_at_revision > COALESCE(n.conversation_revision, 0)) "
                "AND LOWER(COALESCE(m.content,'')) LIKE ?))"
            )
            parameters.extend([needle, needle])
        with self._connect() as connection:
            rows = connection.execute(
                f"""
                SELECT n.*,
                       COUNT(CASE
                           WHEN m.metadata_text NOT LIKE '%"_internal_type": "coach_idempotency"%'
                            AND COALESCE(m.conversation_revision, 0) <=
                                COALESCE(n.conversation_revision, 0)
                            AND (
                                m.superseded_at_revision IS NULL
                                OR m.superseded_at_revision >
                                   COALESCE(n.conversation_revision, 0)
                            )
                           THEN m.id
                       END) AS messageCount,
                       SUM(CASE
                           WHEN m.role='user'
                            AND COALESCE(m.conversation_revision, 0) <=
                                COALESCE(n.conversation_revision, 0)
                            AND (
                                m.superseded_at_revision IS NULL
                                OR m.superseded_at_revision >
                                   COALESCE(n.conversation_revision, 0)
                            )
                           THEN 1 ELSE 0
                       END) AS studentTurnCount,
                       (
                         SELECT recent.content
                         FROM messages recent
                         WHERE recent.notebook_id=n.id
                           AND recent.role='user'
                           AND COALESCE(recent.conversation_revision, 0) <=
                               COALESCE(n.conversation_revision, 0)
                           AND (
                               recent.superseded_at_revision IS NULL
                               OR recent.superseded_at_revision >
                                  COALESCE(n.conversation_revision, 0)
                           )
                         ORDER BY recent.created_at DESC, recent.id DESC
                         LIMIT 1
                       ) AS latestUserMessage,
                       MAX(COALESCE(
                           CASE
                               WHEN m.metadata_text NOT LIKE '%"_internal_type": "coach_idempotency"%'
                                AND COALESCE(m.conversation_revision, 0) <=
                                    COALESCE(n.conversation_revision, 0)
                                AND (
                                    m.superseded_at_revision IS NULL
                                    OR m.superseded_at_revision >
                                       COALESCE(n.conversation_revision, 0)
                                )
                               THEN m.created_at
                           END,
                           n.updated_at,
                           n.created_at
                       )) AS lastActivity
                FROM notebooks n
                LEFT JOIN messages m ON m.notebook_id=n.id
                WHERE {' AND '.join(clauses)}
                GROUP BY n.id
                ORDER BY lastActivity DESC
                """,
                parameters,
            ).fetchall()
        return [self._thread_dict(row) for row in rows]

    def _thread_dict(self, row: Any) -> dict[str, Any]:
        """Map a notebooks row to the thread-shaped dict expected by callers."""
        progress = _load(row["progress_text"], {})
        if not isinstance(progress, dict):
            progress = {}
        settings_blob = _load(row["settings_text"], {})
        if not isinstance(settings_blob, dict):
            settings_blob = {}
        current_stage = str(row["current_stage"] or "focus")
        try:
            conversation_revision = int(row["conversation_revision"] or 0)
        except (KeyError, TypeError, ValueError):
            conversation_revision = 0
        journey = {
            **{key: progress[key] for key in _PROGRESS_KEYS if key in progress},
            "current_stage": current_stage,
            "completed_stages": progress.get("completed_stages") or [],
            "stage_notes": progress.get("stage_notes") or {},
            "working_conclusion": progress.get("working_conclusion") or "",
            "critical_reflection": progress.get("critical_reflection") or "",
            "response_detail": progress.get("response_detail") or "short",
        }
        metadata: dict[str, Any] = {
            **settings_blob,
            "learning_journey": journey,
            "thinking_stage": current_stage,
            "response_detail": journey["response_detail"],
            "conversation_revision": conversation_revision,
        }
        for key in (
            "learning_summary",
            "working_conclusion",
            "understanding_change",
            "critical_understanding",
        ):
            if key in progress and progress[key] not in (None, ""):
                metadata[key] = progress[key]
        value = {
            "id": str(row["id"]),
            "name": row["title"],
            "createdAt": row["created_at"],
            "userId": row["user_id"],
            "userIdentifier": self.identifier,
            "tags": settings_blob.get("tags") or [],
            "conversation_revision": conversation_revision,
            "metadata": metadata,
        }
        for key in (
            "messageCount",
            "studentTurnCount",
            "latestUserMessage",
            "lastActivity",
        ):
            if key in row.keys():
                value[key] = row[key]
        return value

    def update_thread(
        self,
        thread_id: str,
        *,
        name: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        """Rename and/or merge metadata in one retryable database transaction.

        The owned-row SELECT, Python merge, and UPDATE deliberately share one
        connection. Aurora DSQL can therefore detect an OCC conflict instead of
        allowing a stale settings write to overwrite a newly confirmed stage.
        """
        with self._lock, self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM notebooks WHERE id=? AND user_id=?",
                (thread_id, self.owner_id),
            ).fetchone()
            if not row:
                raise ValueError("Chat not found")
            thread = self._thread_dict(row)
            current_meta = dict(thread.get("metadata") or {})
            if metadata:
                current_meta = {**current_meta, **metadata}
                if "learning_journey" in metadata and isinstance(
                    metadata.get("learning_journey"), dict
                ):
                    # Trusted internal journey updates replace the normalized
                    # journey snapshot. Public API models exclude this field.
                    current_meta["learning_journey"] = metadata["learning_journey"]
                journey_meta = dict(current_meta.get("learning_journey") or {})
                for key in _PROGRESS_KEYS:
                    if key in metadata:
                        journey_meta[key] = metadata[key]
                current_meta["learning_journey"] = journey_meta
            current_stage, progress_text, settings_text = self._split_notebook_metadata(
                current_meta
            )
            title = (
                name.strip()[:120]
                if name is not None
                else thread.get("name")
            )
            connection.execute(
                """
                UPDATE notebooks
                SET title=?, current_stage=?, progress_text=?, settings_text=?,
                    updated_at=?
                WHERE id=? AND user_id=?
                """,
                (
                    title,
                    current_stage,
                    progress_text,
                    settings_text,
                    utc_now(),
                    thread_id,
                    self.owner_id,
                ),
            )

    def select_learning_stage(self, thread_id: str, stage_id: str) -> dict[str, Any]:
        """Set the notebook's current stage and reject any pending transitions.

        Updates journey metadata and clears pending ADVANCE recommendations in
        one connection so a mid-flight failure cannot leave a pending transition
        pointing at a stage the student already left.

        Returns:
            The updated notebook metadata dict (includes ``learning_journey``).

        Raises:
            ValueError: When the notebook is missing or ``stage_id`` is unknown.
        """
        from backend.student_journey import STAGE_BY_ID, normalize_journey, set_current_stage

        cleaned_stage = str(stage_id or "").strip()
        if cleaned_stage not in STAGE_BY_ID:
            raise ValueError(f"Unknown thinking stage: {cleaned_stage}")

        with self._lock, self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM notebooks WHERE id=? AND user_id=?",
                (thread_id, self.owner_id),
            ).fetchone()
            if not row:
                raise ValueError("Notebook not found")
            thread = self._thread_dict(row)
            current_meta = dict(thread.get("metadata") or {})
            journey = normalize_journey(current_meta.get("learning_journey"))
            next_journey = set_current_stage(journey, cleaned_stage)
            current_meta["learning_journey"] = next_journey
            current_meta["thinking_stage"] = cleaned_stage
            now = utc_now()
            connection.execute(
                """
                UPDATE messages
                SET decision_status='rejected', decision_at=?
                WHERE notebook_id=? AND decision_status='pending'
                """,
                (now, thread_id),
            )
            current_stage, progress_text, settings_text = self._split_notebook_metadata(
                current_meta
            )
            connection.execute(
                """
                UPDATE notebooks
                SET current_stage=?, progress_text=?, settings_text=?, updated_at=?
                WHERE id=? AND user_id=?
                """,
                (
                    current_stage,
                    progress_text,
                    settings_text,
                    now,
                    thread_id,
                    self.owner_id,
                ),
            )
            return current_meta

    @staticmethod
    def _split_notebook_metadata(
        metadata: dict[str, Any],
    ) -> tuple[str, str, str]:
        """Split a legacy metadata blob into stage + progress + settings TEXT."""
        from backend.student_journey import DEFAULT_STAGE, STAGE_BY_ID

        journey_raw = metadata.get("learning_journey")
        journey = journey_raw if isinstance(journey_raw, dict) else {}
        stage = (
            journey.get("current_stage")
            or metadata.get("thinking_stage")
            or DEFAULT_STAGE
        )
        stage = str(stage) if str(stage) in STAGE_BY_ID else DEFAULT_STAGE

        progress: dict[str, Any] = {}
        for key in _PROGRESS_KEYS:
            if key in journey:
                progress[key] = journey[key]
            elif key in metadata:
                progress[key] = metadata[key]
        if "response_detail" not in progress:
            progress["response_detail"] = (
                journey.get("response_detail")
                or metadata.get("response_detail")
                or "short"
            )
        if "completed_stages" not in progress:
            progress["completed_stages"] = journey.get("completed_stages") or []
        if "stage_notes" not in progress:
            progress["stage_notes"] = journey.get("stage_notes") or {}

        settings_blob: dict[str, Any] = {}
        for key in _SETTINGS_KEYS:
            if key in metadata and key != "tags":
                settings_blob[key] = metadata[key]
        if "tags" in metadata:
            settings_blob["tags"] = metadata["tags"]
        if "assignment" not in settings_blob and isinstance(
            metadata.get("assignment"), dict
        ):
            settings_blob["assignment"] = metadata["assignment"]
        return stage, _dump(progress), _dump(settings_blob)

    def delete_thread(self, thread_id: str) -> None:
        """Delete a notebook and its child rows, then purge stored files.

        When the notebook row is already gone (retry after a committed delete),
        still run authenticated-owner prefix cleanup so object storage stays
        consistent. Repeated cleanup is harmless.
        """
        if self.get_thread(thread_id):
            with self._lock, self._connect() as connection:
                for table in NOTEBOOK_CHILD_TABLES:
                    connection.execute(
                        f"DELETE FROM {table} WHERE notebook_id = ?",
                        (thread_id,),
                    )
                connection.execute(
                    "DELETE FROM notebooks WHERE id=? AND user_id=?",
                    (thread_id, self.owner_id),
                )
        self._cleanup_notebook_files(thread_id)

    def _cleanup_notebook_files(self, notebook_id: str) -> None:
        """Remove local and object-storage files owned by a deleted notebook."""
        from backend.persistence.factory import get_file_storage
        from backend.persistence.object_keys import notebook_prefix

        if settings.file_storage_provider != "local":
            get_file_storage().delete_prefix(
                notebook_prefix(user_id=self.owner_id, notebook_id=notebook_id)
            )
            return
        # Local provider: remove both object-key tree (if used) and legacy dirs.
        try:
            get_file_storage().delete_prefix(
                notebook_prefix(user_id=self.owner_id, notebook_id=notebook_id)
            )
        except Exception:  # noqa: BLE001 - best-effort local cleanup
            pass
        for root, allowed in (
            (settings.files_dir / "threads" / notebook_id, settings.files_dir),
            (settings.workspaces_dir / notebook_id, settings.workspaces_dir),
        ):
            resolved = root.resolve()
            if resolved.exists() and allowed in resolved.parents:
                shutil.rmtree(resolved, ignore_errors=True)

    def add_message(
        self,
        thread_id: str,
        role: str,
        content: str,
        *,
        model_id: str | None = None,
        metadata: dict[str, Any] | None = None,
        message_id: str | None = None,
        is_error: bool = False,
    ) -> str:
        """Persist one chat message; upsert when *message_id* already exists."""
        if role not in {"user", "assistant"}:
            raise ValueError("role must be user or assistant")
        message_id = message_id or str(uuid.uuid4())
        meta = {**(metadata or {})}
        if model_id:
            meta["model"] = model_id
        assessment = meta.pop("assessment", None)
        assessment_text = (
            _dump(assessment) if isinstance(assessment, dict) else None
        )
        cited = meta.pop("source_refs", None)
        if cited is None:
            cited = meta.pop("cited_source_ids", None)
        cited_text = _dump(cited) if cited is not None else None
        proposed_stage = meta.pop("proposed_stage", None)
        decision_status = meta.pop("decision_status", None)
        decision_at = meta.pop("decision_at", None)
        pending_id = meta.pop("pending_transition_id", None)
        if pending_id and not proposed_stage:
            # Compatibility: pending transition id names the assistant message.
            message_id = str(pending_id)
        now = utc_now()
        with self._lock, self._connect() as connection:
            owned = connection.execute(
                "SELECT id, conversation_revision FROM notebooks "
                "WHERE id=? AND user_id=?",
                (thread_id, self.owner_id),
            ).fetchone()
            if not owned:
                raise ValueError("Chat not found")
            stamp_revision = self._notebook_revision_value(owned)
            existing = connection.execute(
                """
                SELECT m.id FROM messages m
                JOIN notebooks n ON n.id = m.notebook_id
                WHERE m.id=? AND m.notebook_id=? AND n.user_id=?
                """,
                (message_id, thread_id, self.owner_id),
            ).fetchone()
            if existing:
                # Bump created_at when materializing a pending-transition skeleton
                # so the assistant reply sorts after the user turn. Preserve any
                # existing revision stamp / predecessor / superseded markers.
                connection.execute(
                    """
                    UPDATE messages
                    SET content=?, is_error=?,
                        assessment_text=COALESCE(?, assessment_text),
                        cited_source_ids_text=COALESCE(?, cited_source_ids_text),
                        proposed_stage=COALESCE(?, proposed_stage),
                        decision_status=COALESCE(?, decision_status),
                        decision_at=COALESCE(?, decision_at),
                        metadata_text=?,
                        created_at=CASE
                            WHEN content = '' AND ? != '' THEN ?
                            ELSE created_at
                        END
                    WHERE id=? AND notebook_id=?
                    """,
                    (
                        content,
                        int(is_error),
                        assessment_text,
                        cited_text,
                        proposed_stage,
                        decision_status,
                        decision_at,
                        _dump(meta),
                        content,
                        now,
                        message_id,
                        thread_id,
                    ),
                )
            else:
                connection.execute(
                    """
                    INSERT INTO messages
                      (id, notebook_id, role, content, is_error, assessment_text,
                       cited_source_ids_text, proposed_stage, decision_status,
                       decision_at, metadata_text, created_at,
                       conversation_revision, previous_message_id,
                       superseded_at_revision)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, NULL, NULL)
                    """,
                    (
                        message_id,
                        thread_id,
                        role,
                        content,
                        int(is_error),
                        assessment_text,
                        cited_text,
                        proposed_stage,
                        decision_status,
                        decision_at,
                        _dump(meta),
                        now,
                        stamp_revision,
                    ),
                )
            if role == "user":
                count = connection.execute(
                    """
                    SELECT COUNT(*) AS total FROM messages
                    WHERE notebook_id=? AND role='user'
                      AND COALESCE(conversation_revision, 0) <= ?
                      AND (
                        superseded_at_revision IS NULL
                        OR superseded_at_revision > ?
                      )
                    """,
                    (thread_id, stamp_revision, stamp_revision),
                ).fetchone()["total"]
                if count == 1:
                    from .title_service import NotebookTitleService

                    title = NotebookTitleService.generate(content)
                    connection.execute(
                        """
                        UPDATE notebooks SET title=?, updated_at=?
                        WHERE id=? AND (title IS NULL OR title IN (?, ?))
                        """,
                        (
                            title,
                            now,
                            thread_id,
                            "Untitled notebook",
                            "New assignment chat",
                        ),
                    )
                else:
                    connection.execute(
                        "UPDATE notebooks SET updated_at=? WHERE id=? AND user_id=?",
                        (now, thread_id, self.owner_id),
                    )
            else:
                connection.execute(
                    "UPDATE notebooks SET updated_at=? WHERE id=? AND user_id=?",
                    (now, thread_id, self.owner_id),
                )
        return message_id

    def _coach_marker_id(self, thread_id: str, idempotency_key: str) -> str:
        """Return a deterministic internal message id for one owned request key."""
        return str(
            uuid.uuid5(
                uuid.NAMESPACE_URL,
                f"co-design-coach-request:{self.owner_id}:{thread_id}:{idempotency_key}",
            )
        )

    @staticmethod
    def _coach_request_has_expired(metadata: dict[str, Any]) -> bool:
        """Return whether an internal request lease is absent, invalid, or expired."""
        raw_expiry = str(metadata.get("lease_expires_at") or "")
        try:
            expiry = datetime.fromisoformat(raw_expiry)
        except ValueError:
            return True
        if expiry.tzinfo is None:
            return True
        return expiry <= datetime.now(timezone.utc)

    def _recorded_coach_turn(
        self,
        connection: Any,
        thread_id: str,
        idempotency_key: str,
        *,
        active_revision: int | None = None,
    ) -> dict[str, Any] | None:
        """Recover a committed turn if a process stopped before marking it complete.

        The user and assistant rows are committed atomically by
        :meth:`persist_coach_turn`.  Keeping the request key on both rows lets a
        restarted process promote that durable result without invoking the
        provider again. Superseded historical assistants are ignored when
        *active_revision* is provided.
        """
        rows = connection.execute(
            """
            SELECT * FROM messages
            WHERE notebook_id=? AND role='assistant'
            ORDER BY created_at ASC, id ASC
            """,
            (thread_id,),
        ).fetchall()
        for row in rows:
            if active_revision is not None and not self._is_active_at_revision(
                row, active_revision
            ):
                continue
            metadata = _load(row["metadata_text"], {})
            if not isinstance(metadata, dict) or metadata.get(
                "coach_idempotency_key"
            ) != idempotency_key:
                continue
            assessment = _load(row["assessment_text"], None)
            if not isinstance(assessment, dict):
                continue
            pending_transition: dict[str, Any] | None = None
            if (
                row["proposed_stage"]
                and row["decision_status"] == "pending"
                and metadata.get("from_stage")
            ):
                pending_transition = {
                    "id": str(row["id"]),
                    "thread_id": thread_id,
                    "from_stage": str(metadata["from_stage"]),
                    "to_stage": str(row["proposed_stage"]),
                    "assessment": assessment,
                    "status": "pending",
                    "created_at": str(row["created_at"]),
                    "resolved_at": None,
                }
            return {
                "response_text": str(row["content"] or ""),
                "assessment": assessment,
                "pending_transition": pending_transition,
                "auto_advanced_to": metadata.get("auto_advanced_to"),
            }
        return None

    def lookup_completed_coach_request(
        self,
        thread_id: str,
        *,
        idempotency_key: str,
    ) -> dict[str, Any] | None:
        """Return a completed or persist-recovered coach turn for *idempotency_key*.

        Used by revise-and-resubmit so safe retries replay without rewriting
        history or bumping ``conversation_revision`` again. When the user and
        assistant rows already committed but the marker was not yet marked
        complete, promote the recorded active-branch turn onto the marker.
        Revoked keys are treated as absent so a later edit cannot resurrect a
        superseded turn.
        """
        key = str(idempotency_key or "").strip()
        if not key:
            return None
        marker_id = self._coach_marker_id(thread_id, key)
        with self._lock, self._connect() as connection:
            owned = connection.execute(
                "SELECT id, settings_text, conversation_revision FROM notebooks "
                "WHERE id=? AND user_id=?",
                (thread_id, self.owner_id),
            ).fetchone()
            if not owned:
                return None
            settings_blob = _load(owned["settings_text"], {})
            if not isinstance(settings_blob, dict):
                settings_blob = {}
            revoked = settings_blob.get("revoked_coach_idempotency_keys") or []
            if isinstance(revoked, list) and key in {
                str(item).strip() for item in revoked if str(item).strip()
            }:
                return None
            active_revision = self._notebook_revision_value(owned)
            row = connection.execute(
                "SELECT metadata_text FROM messages WHERE id=? AND notebook_id=?",
                (marker_id, thread_id),
            ).fetchone()
            metadata = _load(row["metadata_text"] if row else None, {})
            if (
                isinstance(metadata, dict)
                and metadata.get("_internal_type") == _COACH_IDEMPOTENCY_MARKER
                and metadata.get("status") == "completed"
            ):
                turn = metadata.get("turn")
                if isinstance(turn, dict):
                    return turn
            recorded = self._recorded_coach_turn(
                connection,
                thread_id,
                key,
                active_revision=active_revision,
            )
            if recorded is None:
                return None
            if row is not None and isinstance(metadata, dict):
                metadata.update({"status": "completed", "turn": recorded})
                metadata.pop("lease_token", None)
                metadata.pop("lease_expires_at", None)
                connection.execute(
                    "UPDATE messages SET metadata_text=? WHERE id=? AND notebook_id=?",
                    (_dump(metadata), marker_id, thread_id),
                )
            return recorded

    def lookup_completed_or_recorded_coach_request(
        self,
        thread_id: str,
        *,
        idempotency_key: str,
    ) -> dict[str, Any] | None:
        """Compatibility alias for durable revise/submit recovery."""
        return self.lookup_completed_coach_request(
            thread_id, idempotency_key=idempotency_key
        )

    def claim_coach_request(
        self,
        thread_id: str,
        *,
        idempotency_key: str,
        request_fingerprint: str,
        lease_seconds: int = 180,
    ) -> CoachRequestReservation:
        """Reserve or replay an owned coach request without running a provider.

        An internal marker uses the existing ``messages`` primary key rather
        than adding a sixth production table.  The deterministic id makes the
        reservation unique for the owner, notebook, and caller-provided key on
        both SQLite and Aurora DSQL.  Leases make a request recoverable after a
        worker or container restart; they never represent a completed turn.
        """
        key = str(idempotency_key or "").strip()
        fingerprint = str(request_fingerprint or "").strip()
        if not key or not fingerprint:
            raise ValueError("Coach idempotency key and fingerprint are required")
        if lease_seconds < 1:
            raise ValueError("Coach idempotency lease must be positive")
        marker_id = self._coach_marker_id(thread_id, key)
        with self._lock, self._connect() as connection:
            owned = connection.execute(
                "SELECT id, settings_text, conversation_revision FROM notebooks "
                "WHERE id=? AND user_id=?",
                (thread_id, self.owner_id),
            ).fetchone()
            if not owned:
                raise ValueError("Chat not found")
            stamp_revision = self._notebook_revision_value(owned)
            settings_blob = _load(owned["settings_text"], {})
            if not isinstance(settings_blob, dict):
                settings_blob = {}
            revoked = settings_blob.get("revoked_coach_idempotency_keys") or []
            if isinstance(revoked, list) and key in {
                str(item).strip() for item in revoked if str(item).strip()
            }:
                raise CoachIdempotencyConflictError(
                    "This coach request key was invalidated by a conversation revision"
                )
            row = connection.execute(
                "SELECT * FROM messages WHERE id=? AND notebook_id=?",
                (marker_id, thread_id),
            ).fetchone()
            if row is None:
                lease_token = str(uuid.uuid4())
                metadata = {
                    "_internal_type": _COACH_IDEMPOTENCY_MARKER,
                    "idempotency_key": key,
                    "request_fingerprint": fingerprint,
                    "status": "pending",
                    "lease_token": lease_token,
                    "lease_expires_at": (
                        datetime.now(timezone.utc) + timedelta(seconds=lease_seconds)
                    ).isoformat(),
                }
                connection.execute(
                    """
                    INSERT INTO messages
                      (id, notebook_id, role, content, is_error, assessment_text,
                       cited_source_ids_text, proposed_stage, decision_status,
                       decision_at, metadata_text, created_at,
                       conversation_revision, previous_message_id,
                       superseded_at_revision)
                    VALUES (?, ?, 'assistant', '', 0, NULL, NULL, NULL, NULL,
                            NULL, ?, ?, ?, NULL, NULL)
                    ON CONFLICT (id) DO NOTHING
                    """,
                    (
                        marker_id,
                        thread_id,
                        _dump(metadata),
                        utc_now(),
                        stamp_revision,
                    ),
                )
                # A concurrent DSQL claimant may have committed the same
                # deterministic primary key first. Read back the winner in the
                # same retryable DB unit instead of relying on process-local
                # locks or a non-portable JSON unique index.
                row = connection.execute(
                    "SELECT * FROM messages WHERE id=? AND notebook_id=?",
                    (marker_id, thread_id),
                ).fetchone()
                inserted_metadata = _load(
                    row["metadata_text"] if row else None, {}
                )
                if (
                    isinstance(inserted_metadata, dict)
                    and inserted_metadata.get("lease_token") == lease_token
                    and inserted_metadata.get("request_fingerprint") == fingerprint
                ):
                    return CoachRequestReservation("claimed", marker_id, lease_token)

            metadata = _load(row["metadata_text"], {})
            if (
                not isinstance(metadata, dict)
                or metadata.get("_internal_type") != _COACH_IDEMPOTENCY_MARKER
            ):
                raise ValueError("Coach idempotency marker is invalid")
            if metadata.get("request_fingerprint") != fingerprint:
                raise CoachIdempotencyConflictError(
                    "Idempotency key was already used for a different coach request"
                )
            recorded = self._recorded_coach_turn(
                connection,
                thread_id,
                key,
                active_revision=stamp_revision,
            )
            if recorded is not None:
                metadata.update({"status": "completed", "turn": recorded})
                metadata.pop("lease_token", None)
                metadata.pop("lease_expires_at", None)
                connection.execute(
                    "UPDATE messages SET metadata_text=? WHERE id=? AND notebook_id=?",
                    (_dump(metadata), marker_id, thread_id),
                )
                return CoachRequestReservation(
                    "completed", marker_id, turn_payload=recorded
                )
            completed = metadata.get("turn")
            if metadata.get("status") == "completed" and isinstance(completed, dict):
                return CoachRequestReservation(
                    "completed", marker_id, turn_payload=completed
                )
            if (
                metadata.get("status") == "pending"
                and not self._coach_request_has_expired(metadata)
            ):
                return CoachRequestReservation("in_progress", marker_id)

            lease_token = str(uuid.uuid4())
            metadata.update(
                {
                    "status": "pending",
                    "lease_token": lease_token,
                    "lease_expires_at": (
                        datetime.now(timezone.utc) + timedelta(seconds=lease_seconds)
                    ).isoformat(),
                }
            )
            metadata.pop("turn", None)
            connection.execute(
                "UPDATE messages SET metadata_text=? WHERE id=? AND notebook_id=?",
                (_dump(metadata), marker_id, thread_id),
            )
            return CoachRequestReservation("claimed", marker_id, lease_token)

    def complete_coach_request(
        self,
        thread_id: str,
        *,
        marker_id: str,
        idempotency_key: str,
        request_fingerprint: str,
        lease_token: str,
        turn_payload: dict[str, Any],
    ) -> None:
        """Durably store the exact completed turn for a reserved request key.

        A waiter or restarted process may promote the marker to ``completed``
        from already-persisted message rows after this worker's
        :meth:`persist_coach_turn` commits but before this method runs. That
        promotion clears the lease on purpose for restart recovery; treat the
        matching completed marker as an idempotent success so the lease owner
        does not raise a false :class:`CoachRequestLeaseLostError`.
        """
        with self._lock, self._connect() as connection:
            row = connection.execute(
                "SELECT metadata_text FROM messages WHERE id=? AND notebook_id=?",
                (marker_id, thread_id),
            ).fetchone()
            if not row:
                raise ValueError("Coach idempotency marker was not found")
            metadata = _load(row["metadata_text"], {})
            if (
                not isinstance(metadata, dict)
                or metadata.get("_internal_type") != _COACH_IDEMPOTENCY_MARKER
                or metadata.get("idempotency_key") != idempotency_key
                or metadata.get("request_fingerprint") != request_fingerprint
            ):
                raise CoachRequestLeaseLostError(
                    "Coach request lease was claimed by another worker"
                )
            # Waiter/restart promotion already recorded the durable turn.
            if metadata.get("status") == "completed" and isinstance(
                metadata.get("turn"), dict
            ):
                return
            if (
                metadata.get("status") != "pending"
                or metadata.get("lease_token") != lease_token
            ):
                raise CoachRequestLeaseLostError(
                    "Coach request lease was claimed by another worker"
                )
            metadata.update({"status": "completed", "turn": turn_payload})
            metadata.pop("lease_token", None)
            metadata.pop("lease_expires_at", None)
            metadata.pop("failure", None)
            connection.execute(
                "UPDATE messages SET metadata_text=? WHERE id=? AND notebook_id=?",
                (_dump(metadata), marker_id, thread_id),
            )

    def fail_coach_request(
        self,
        thread_id: str,
        *,
        marker_id: str,
        request_fingerprint: str,
        lease_token: str,
    ) -> None:
        """Release a failed request so its key can retry instead of replaying failure."""
        with self._lock, self._connect() as connection:
            row = connection.execute(
                "SELECT metadata_text FROM messages WHERE id=? AND notebook_id=?",
                (marker_id, thread_id),
            ).fetchone()
            if not row:
                return
            metadata = _load(row["metadata_text"], {})
            if (
                not isinstance(metadata, dict)
                or metadata.get("_internal_type") != _COACH_IDEMPOTENCY_MARKER
                or metadata.get("request_fingerprint") != request_fingerprint
                or metadata.get("status") == "completed"
                or metadata.get("lease_token") != lease_token
            ):
                return
            metadata.update({"status": "failed", "failure": "unavailable"})
            metadata.pop("lease_token", None)
            metadata.pop("lease_expires_at", None)
            connection.execute(
                "UPDATE messages SET metadata_text=? WHERE id=? AND notebook_id=?",
                (_dump(metadata), marker_id, thread_id),
            )

    def persist_coach_turn(
        self,
        thread_id: str,
        *,
        expected_stage: str,
        expected_conversation_revision: int,
        user_content: str,
        user_metadata: dict[str, Any],
        assistant_content: str,
        assistant_metadata: dict[str, Any],
        summary_metadata: dict[str, Any],
        assistant_message_id: str | None = None,
        generated_title: str | None = None,
        existing_user_message_id: str | None = None,
        idempotency_marker_id: str | None = None,
        idempotency_key: str | None = None,
        idempotency_lease_token: str | None = None,
        idempotency_fingerprint: str | None = None,
    ) -> tuple[str, str]:
        """Persist one completed coaching turn in a single DB transaction.

        Provider, retrieval, and object-storage work must finish before this
        method is called. The user row, assistant assessment/citations/pending
        decision, and notebook summary either commit together or roll back.

        When ``existing_user_message_id`` is set (edit/revise path), the user
        message is already durable from the revision transaction. Content is not
        rewritten destructively; metadata may be refreshed without clearing
        lineage columns. An assistant row stamped with the expected revision is
        inserted.
        """
        cleaned_user = user_content.strip()
        cleaned_assistant = assistant_content.strip()
        if not cleaned_user or not cleaned_assistant:
            raise ValueError("Completed coach turns require both messages")
        user_id = str(existing_user_message_id or uuid.uuid4())
        assistant_id = assistant_message_id or str(uuid.uuid4())
        assistant_meta = dict(assistant_metadata)
        assessment = assistant_meta.pop("assessment", None)
        cited = assistant_meta.pop("source_refs", None)
        proposed_stage = assistant_meta.pop("proposed_stage", None)
        decision_status = assistant_meta.pop("decision_status", None)
        assistant_meta.pop("pending_transition_id", None)
        if decision_status and decision_status != "pending":
            raise ValueError("New coach transition status must be pending")
        if bool(proposed_stage) != bool(decision_status):
            raise ValueError("Pending coach transitions require a proposed stage")

        with self._lock, self._connect() as connection:
            notebook = connection.execute(
                "SELECT * FROM notebooks WHERE id=? AND user_id=?",
                (thread_id, self.owner_id),
            ).fetchone()
            if not notebook:
                raise ValueError("Chat not found")
            active_stage = str(notebook["current_stage"] or "focus")
            if active_stage != expected_stage:
                raise ValueError(
                    "The notebook stage changed before the coaching turn was saved"
                )
            active_revision = self._notebook_revision_value(notebook)
            if active_revision != int(expected_conversation_revision):
                raise ConversationRevisionConflictError(
                    "The conversation was revised before the coaching turn was saved"
                )
            if idempotency_marker_id is not None:
                marker = connection.execute(
                    "SELECT metadata_text FROM messages WHERE id=? AND notebook_id=?",
                    (idempotency_marker_id, thread_id),
                ).fetchone()
                marker_metadata = _load(
                    marker["metadata_text"] if marker else None, {}
                )
                if (
                    not isinstance(marker_metadata, dict)
                    or marker_metadata.get("_internal_type")
                    != _COACH_IDEMPOTENCY_MARKER
                    or marker_metadata.get("status") != "pending"
                    or marker_metadata.get("idempotency_key") != idempotency_key
                    or marker_metadata.get("request_fingerprint")
                    != idempotency_fingerprint
                    or marker_metadata.get("lease_token") != idempotency_lease_token
                ):
                    raise CoachRequestLeaseLostError(
                        "Coach request lease was claimed by another worker"
                    )

            user_created_at = utc_now()
            assistant_created_at = utc_now()
            if existing_user_message_id:
                owned_user = connection.execute(
                    """
                    SELECT * FROM messages
                    WHERE id=? AND notebook_id=?
                    """,
                    (existing_user_message_id, thread_id),
                ).fetchone()
                if (
                    not owned_user
                    or owned_user["role"] != "user"
                    or not self._is_active_at_revision(owned_user, active_revision)
                ):
                    raise ValueError("User message not found")
                if self._message_revision_value(owned_user) != active_revision:
                    raise ConversationRevisionConflictError(
                        "The conversation was revised before the coaching turn was saved"
                    )
                # Preserve content and lineage; refresh metadata only.
                user_id = existing_user_message_id
                connection.execute(
                    """
                    UPDATE messages
                    SET metadata_text=?
                    WHERE id=? AND notebook_id=?
                    """,
                    (_dump(user_metadata), existing_user_message_id, thread_id),
                )
            else:
                connection.execute(
                    """
                    INSERT INTO messages
                      (id, notebook_id, role, content, is_error, assessment_text,
                       cited_source_ids_text, proposed_stage, decision_status,
                       decision_at, metadata_text, created_at,
                       conversation_revision, previous_message_id,
                       superseded_at_revision)
                    VALUES (?, ?, 'user', ?, 0, NULL, NULL, NULL, NULL, NULL, ?, ?,
                            ?, NULL, NULL)
                    """,
                    (
                        user_id,
                        thread_id,
                        cleaned_user,
                        _dump(user_metadata),
                        user_created_at,
                        active_revision,
                    ),
                )
            if decision_status == "pending":
                connection.execute(
                    f"""
                    UPDATE messages
                    SET decision_status='rejected', decision_at=?
                    WHERE notebook_id=? AND decision_status='pending'
                      AND {self._active_at_revision_sql()}
                    """,
                    (
                        assistant_created_at,
                        thread_id,
                        active_revision,
                        active_revision,
                    ),
                )
            connection.execute(
                """
                INSERT INTO messages
                  (id, notebook_id, role, content, is_error, assessment_text,
                   cited_source_ids_text, proposed_stage, decision_status,
                   decision_at, metadata_text, created_at,
                   conversation_revision, previous_message_id,
                   superseded_at_revision)
                VALUES (?, ?, 'assistant', ?, 0, ?, ?, ?, ?, NULL, ?, ?,
                        ?, NULL, NULL)
                """,
                (
                    assistant_id,
                    thread_id,
                    cleaned_assistant,
                    _dump(assessment) if isinstance(assessment, dict) else None,
                    _dump(cited) if cited is not None else None,
                    proposed_stage,
                    decision_status,
                    _dump(assistant_meta),
                    assistant_created_at,
                    active_revision,
                ),
            )

            thread = self._thread_dict(notebook)
            current_meta = {
                **dict(thread.get("metadata") or {}),
                **summary_metadata,
                "last_workflow_user_message_id": user_id,
                "conversation_revision": active_revision,
            }
            journey_meta = dict(current_meta.get("learning_journey") or {})
            for key in _PROGRESS_KEYS:
                if key in summary_metadata:
                    journey_meta[key] = summary_metadata[key]
            current_meta["learning_journey"] = journey_meta
            stage, progress_text, settings_text = self._split_notebook_metadata(
                current_meta
            )
            if stage != expected_stage:
                raise ValueError("Coach summary cannot change the notebook stage")
            title = generated_title or notebook["title"]
            updated = connection.execute(
                """
                UPDATE notebooks
                SET title=?, current_stage=?, progress_text=?, settings_text=?,
                    updated_at=?
                WHERE id=? AND user_id=? AND conversation_revision=?
                """,
                (
                    title,
                    stage,
                    progress_text,
                    settings_text,
                    assistant_created_at,
                    thread_id,
                    self.owner_id,
                    active_revision,
                ),
            )
            if int(getattr(updated, "rowcount", 0) or 0) == 0:
                raise ConversationRevisionConflictError(
                    "The conversation was revised before the coaching turn was saved"
                )
        return user_id, assistant_id

    def update_message(self, message_id: str, content: str) -> None:
        """Replace the content of an owned message."""
        with self._lock, self._connect() as connection:
            owned = connection.execute(
                """
                SELECT m.id FROM messages m
                JOIN notebooks n ON n.id=m.notebook_id
                WHERE m.id=? AND n.user_id=?
                """,
                (message_id, self.owner_id),
            ).fetchone()
            if not owned:
                raise ValueError("Message not found")
            connection.execute(
                "UPDATE messages SET content=? WHERE id=?",
                (content, message_id),
            )

    def _find_active_replacement_user(
        self,
        connection: Any,
        thread_id: str,
        original_message_id: str,
        content: str,
        revision: int,
    ) -> Any | None:
        """Return an active replacement user descended from *original_message_id*.

        Walks ``previous_message_id`` edges so a provider-failure retry can resume
        the already-inserted replacement without re-superseding or bumping again.
        """
        cleaned = content.strip()
        frontier = [str(original_message_id)]
        seen: set[str] = set()
        while frontier:
            current = frontier.pop()
            if current in seen:
                continue
            seen.add(current)
            children = connection.execute(
                """
                SELECT * FROM messages
                WHERE notebook_id=? AND previous_message_id=?
                ORDER BY created_at ASC, id ASC
                """,
                (thread_id, current),
            ).fetchall()
            for child in children:
                child_id = str(child["id"])
                if self._is_active_at_revision(child, revision):
                    if (
                        child["role"] == "user"
                        and str(child["content"] or "").strip() == cleaned
                    ):
                        return child
                frontier.append(child_id)
        return None

    def _history_dicts_at_revision(
        self,
        connection: Any,
        thread_id: str,
        revision: int,
    ) -> list[dict[str, Any]]:
        """Return active non-marker messages at *revision* (connection-bound)."""
        rows = connection.execute(
            f"""
            SELECT * FROM messages
            WHERE notebook_id=?
              AND {self._active_at_revision_sql()}
            ORDER BY created_at ASC, id ASC
            """,
            (thread_id, revision, revision),
        ).fetchall()
        history: list[dict[str, Any]] = []
        for row in rows:
            meta = _load(row["metadata_text"], {})
            if self._is_coach_idempotency_marker_meta(meta):
                continue
            if not isinstance(meta, dict):
                meta = {}
            history.append(
                {
                    "id": str(row["id"]),
                    "role": str(row["role"]),
                    "content": str(row["content"] or ""),
                    "metadata": meta,
                }
            )
        return history

    def try_resume_revision_result(
        self,
        thread_id: str,
        message_id: str,
        content: str,
    ) -> ConversationRevisionResult | None:
        """Return an already-applied append-only edit tip, if one matches.

        Used by revise-and-resubmit after a provider failure so retries can reuse
        the replacement user without CAS-bumping again. Concurrent first-time
        edits must still go through :meth:`revise_conversation_from_user_message`
        so the loser observes a conflict / inactive target.
        """
        cleaned = content.strip()
        if not cleaned:
            return None
        with self._lock, self._connect() as connection:
            notebook = connection.execute(
                "SELECT * FROM notebooks WHERE id=? AND user_id=?",
                (thread_id, self.owner_id),
            ).fetchone()
            if not notebook:
                return None
            revision = self._notebook_revision_value(notebook)
            target = connection.execute(
                "SELECT * FROM messages WHERE id=? AND notebook_id=?",
                (message_id, thread_id),
            ).fetchone()
            if not target or target["role"] != "user":
                return None
            if self._is_active_at_revision(target, revision):
                return None
            replacement = self._find_active_replacement_user(
                connection, thread_id, message_id, cleaned, revision
            )
            if replacement is None:
                return None
            from backend.student_journey import STAGE_BY_ID

            restored_stage = str(notebook["current_stage"] or "focus")
            if restored_stage not in STAGE_BY_ID:
                restored_stage = "focus"
            return ConversationRevisionResult(
                thread_id=thread_id,
                edited_message_id=str(replacement["id"]),
                conversation_revision=revision,
                current_stage=restored_stage,
                surviving_history=self._history_dicts_at_revision(
                    connection, thread_id, revision
                ),
            )

    def revise_conversation_from_user_message(
        self,
        thread_id: str,
        message_id: str,
        content: str,
        *,
        model_id: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> ConversationRevisionResult:
        """Append-only revise a user turn and bump ``conversation_revision``.

        Supersedes the target user message and every currently-active later
        message (rows retained; content unchanged). Inserts a replacement user
        row at ``N+1``. Deletes coach idempotency marker rows only. Pending
        decisions on superseded assistants are rejected in place. Raises
        ``ConversationRevisionConflictError`` on CAS miss so SQLite rolls back.
        """
        from backend.student_journey import STAGE_BY_ID, THINKING_STAGES, normalize_journey

        cleaned = content.strip()
        if not cleaned:
            raise ValueError("Message cannot be empty")
        with self._lock, self._connect() as connection:
            notebook = connection.execute(
                "SELECT * FROM notebooks WHERE id=? AND user_id=?",
                (thread_id, self.owner_id),
            ).fetchone()
            if not notebook:
                raise ValueError("Notebook not found")
            previous_revision = self._notebook_revision_value(notebook)
            next_revision = previous_revision + 1
            target = connection.execute(
                """
                SELECT * FROM messages
                WHERE id=? AND notebook_id=?
                """,
                (message_id, thread_id),
            ).fetchone()
            if not target or target["role"] != "user":
                raise ValueError("User message not found")
            if not self._is_active_at_revision(target, previous_revision):
                raise ConversationRevisionConflictError(
                    "The conversation was revised before this edit could be saved"
                )

            target_created = str(target["created_at"] or "")
            target_meta = _load(target["metadata_text"], {})
            if not isinstance(target_meta, dict):
                target_meta = {}
            restored_stage = str(
                target_meta.get("thinking_stage")
                or notebook["current_stage"]
                or "focus"
            ).strip()
            if restored_stage not in STAGE_BY_ID:
                restored_stage = "focus"

            # Latest active surviving assistant assessment before the target.
            prior_assistants = connection.execute(
                f"""
                SELECT assessment_text, metadata_text FROM messages
                WHERE notebook_id=? AND role='assistant'
                  AND {self._active_at_revision_sql()}
                  AND (
                    created_at < ?
                    OR (created_at = ? AND id < ?)
                  )
                ORDER BY created_at DESC, id DESC
                """,
                (
                    thread_id,
                    previous_revision,
                    previous_revision,
                    target_created,
                    target_created,
                    message_id,
                ),
            ).fetchall()
            surviving_assessment: dict[str, Any] | None = None
            for row in prior_assistants:
                meta = _load(row["metadata_text"], {})
                if self._is_coach_idempotency_marker_meta(meta):
                    continue
                assessment = _load(row["assessment_text"], None)
                if isinstance(assessment, dict):
                    surviving_assessment = assessment
                    break

            # Collect keys from the branch being superseded, then delete markers.
            superseded_candidates = connection.execute(
                f"""
                SELECT id, metadata_text FROM messages
                WHERE notebook_id=?
                  AND {self._active_at_revision_sql()}
                  AND (
                    id = ?
                    OR created_at > ?
                    OR (created_at = ? AND id > ?)
                  )
                """,
                (
                    thread_id,
                    previous_revision,
                    previous_revision,
                    message_id,
                    target_created,
                    target_created,
                    message_id,
                ),
            ).fetchall()
            revoked_keys: list[str] = []
            for row in superseded_candidates:
                revoked_keys.extend(
                    self._collect_idempotency_keys_from_meta(
                        _load(row["metadata_text"], {})
                    )
                )

            marker_rows = connection.execute(
                """
                SELECT id, metadata_text FROM messages
                WHERE notebook_id=?
                """,
                (thread_id,),
            ).fetchall()
            for row in marker_rows:
                meta = _load(row["metadata_text"], {})
                if not self._is_coach_idempotency_marker_meta(meta):
                    continue
                revoked_keys.extend(self._collect_idempotency_keys_from_meta(meta))
                connection.execute(
                    "DELETE FROM messages WHERE id=? AND notebook_id=?",
                    (row["id"], thread_id),
                )

            now = utc_now()
            # Reject pending decisions on the superseded branch, then mark it.
            connection.execute(
                f"""
                UPDATE messages
                SET decision_status='rejected', decision_at=?
                WHERE notebook_id=?
                  AND decision_status='pending'
                  AND {self._active_at_revision_sql()}
                  AND (
                    id = ?
                    OR created_at > ?
                    OR (created_at = ? AND id > ?)
                  )
                """,
                (
                    now,
                    thread_id,
                    previous_revision,
                    previous_revision,
                    message_id,
                    target_created,
                    target_created,
                    message_id,
                ),
            )
            connection.execute(
                f"""
                UPDATE messages
                SET superseded_at_revision=?
                WHERE notebook_id=?
                  AND {self._active_at_revision_sql()}
                  AND (
                    id = ?
                    OR created_at > ?
                    OR (created_at = ? AND id > ?)
                  )
                """,
                (
                    next_revision,
                    thread_id,
                    previous_revision,
                    previous_revision,
                    message_id,
                    target_created,
                    target_created,
                    message_id,
                ),
            )

            replacement_id = str(uuid.uuid4())
            next_metadata = {
                **target_meta,
                **(metadata or {}),
                "thinking_stage": restored_stage,
            }
            if model_id:
                next_metadata["model"] = model_id
            connection.execute(
                """
                INSERT INTO messages
                  (id, notebook_id, role, content, is_error, assessment_text,
                   cited_source_ids_text, proposed_stage, decision_status,
                   decision_at, metadata_text, created_at,
                   conversation_revision, previous_message_id,
                   superseded_at_revision)
                VALUES (?, ?, 'user', ?, 0, NULL, NULL, NULL, NULL, NULL, ?, ?,
                        ?, ?, NULL)
                """,
                (
                    replacement_id,
                    thread_id,
                    cleaned,
                    _dump(next_metadata),
                    now,
                    next_revision,
                    message_id,
                ),
            )

            thread = self._thread_dict(notebook)
            current_meta = dict(thread.get("metadata") or {})
            journey = normalize_journey(current_meta.get("learning_journey"))
            stage_order = [stage.id for stage in THINKING_STAGES]
            restored_index = stage_order.index(restored_stage)
            journey["current_stage"] = restored_stage
            journey["completed_stages"] = [
                stage_id
                for stage_id in journey.get("completed_stages") or []
                if stage_id in STAGE_BY_ID
                and stage_order.index(stage_id) < restored_index
            ]
            journey["stage_notes"] = {
                stage_id: note
                for stage_id, note in (journey.get("stage_notes") or {}).items()
                if stage_id in STAGE_BY_ID
                and (
                    stage_id in journey["completed_stages"]
                    or stage_order.index(stage_id) < restored_index
                )
            }
            if surviving_assessment:
                current_meta["learning_summary"] = surviving_assessment.get(
                    "learning_summary"
                ) or current_meta.get("learning_summary")
                current_meta["working_conclusion"] = surviving_assessment.get(
                    "working_conclusion"
                ) or ""
                current_meta["understanding_change"] = surviving_assessment.get(
                    "understanding_change"
                ) or ""
                current_meta["critical_understanding"] = surviving_assessment.get(
                    "critical_understanding_level"
                ) or current_meta.get("critical_understanding")
                journey["working_conclusion"] = current_meta.get(
                    "working_conclusion"
                ) or journey.get("working_conclusion") or ""
                journey["critical_reflection"] = surviving_assessment.get(
                    "understanding_change"
                ) or journey.get("critical_reflection") or ""
                journey["learning_summary"] = current_meta.get("learning_summary") or ""
            else:
                for key in (
                    "learning_summary",
                    "working_conclusion",
                    "understanding_change",
                    "critical_understanding",
                ):
                    current_meta.pop(key, None)
                journey["working_conclusion"] = ""
                journey["critical_reflection"] = ""
                journey.pop("learning_summary", None)

            current_meta["learning_journey"] = journey
            current_meta["thinking_stage"] = restored_stage
            current_meta["last_workflow_user_message_id"] = replacement_id
            prior_revoked = current_meta.get("revoked_coach_idempotency_keys") or []
            if not isinstance(prior_revoked, list):
                prior_revoked = []
            merged_revoked = []
            seen_keys: set[str] = set()
            for key in [*prior_revoked, *revoked_keys]:
                cleaned_key = str(key or "").strip()
                if not cleaned_key or cleaned_key in seen_keys:
                    continue
                seen_keys.add(cleaned_key)
                merged_revoked.append(cleaned_key)
            current_meta["revoked_coach_idempotency_keys"] = merged_revoked[-64:]
            stage, progress_text, settings_text = self._split_notebook_metadata(
                current_meta
            )
            updated = connection.execute(
                """
                UPDATE notebooks
                SET current_stage=?, progress_text=?, settings_text=?,
                    conversation_revision=?, updated_at=?
                WHERE id=? AND user_id=? AND conversation_revision=?
                """,
                (
                    stage,
                    progress_text,
                    settings_text,
                    next_revision,
                    now,
                    thread_id,
                    self.owner_id,
                    previous_revision,
                ),
            )
            if int(getattr(updated, "rowcount", 0) or 0) == 0:
                raise ConversationRevisionConflictError(
                    "The conversation was revised before this edit could be saved"
                )

            surviving_rows = connection.execute(
                f"""
                SELECT * FROM messages
                WHERE notebook_id=?
                  AND {self._active_at_revision_sql()}
                ORDER BY created_at ASC, id ASC
                """,
                (thread_id, next_revision, next_revision),
            ).fetchall()
            surviving_history: list[dict[str, Any]] = []
            for row in surviving_rows:
                meta = _load(row["metadata_text"], {})
                if self._is_coach_idempotency_marker_meta(meta):
                    continue
                surviving_history.append(self._public_message_dict(row))

            return ConversationRevisionResult(
                thread_id=thread_id,
                edited_message_id=replacement_id,
                conversation_revision=next_revision,
                current_stage=restored_stage,
                surviving_history=surviving_history,
            )

    def revise_user_message(
        self,
        thread_id: str,
        message_id: str,
        content: str,
        *,
        model_id: str,
        metadata: dict[str, Any],
    ) -> list[dict[str, Any]]:
        """Compatibility wrapper: revise and return prior history only.

        Prefer :meth:`revise_conversation_from_user_message` for coach edits.
        """
        result = self.revise_conversation_from_user_message(
            thread_id,
            message_id,
            content,
            model_id=model_id,
            metadata=metadata,
        )
        prior: list[dict[str, Any]] = []
        for message in result.surviving_history:
            if message.get("id") == result.edited_message_id:
                break
            prior.append(
                {
                    "role": str(message.get("role") or ""),
                    "content": str(message.get("content") or ""),
                }
            )
        return prior

    def get_messages(self, thread_id: str) -> list[dict[str, Any]]:
        """Return messages active at the notebook's current conversation revision."""
        thread = self.get_thread(thread_id)
        if not thread:
            return []
        revision = int(thread.get("conversation_revision") or 0)
        return self.get_messages_at_revision(thread_id, revision)

    def get_messages_at_revision(
        self,
        thread_id: str,
        revision: int,
    ) -> list[dict[str, Any]]:
        """Reconstruct messages active at a specific owned notebook revision.

        Active rows satisfy ``COALESCE(conversation_revision,0) <= revision`` and
        ``superseded_at_revision IS NULL OR superseded_at_revision > revision``.
        Internal coach-idempotency markers are hidden.
        """
        with self._connect() as connection:
            notebook = connection.execute(
                "SELECT conversation_revision FROM notebooks "
                "WHERE id=? AND user_id=?",
                (thread_id, self.owner_id),
            ).fetchone()
            if not notebook:
                raise ValueError("Notebook not found")
            current_revision = self._notebook_revision_value(notebook)
            try:
                requested = int(revision)
            except (TypeError, ValueError) as error:
                raise ValueError("Invalid conversation revision") from error
            if requested < 0 or requested > current_revision:
                raise ValueError("Invalid conversation revision")
            rows = connection.execute(
                f"""
                SELECT * FROM messages
                WHERE notebook_id=?
                  AND {self._active_at_revision_sql()}
                ORDER BY created_at ASC, id ASC
                """,
                (thread_id, requested, requested),
            ).fetchall()
        messages: list[dict[str, Any]] = []
        for row in rows:
            meta = _load(row["metadata_text"], {})
            if self._is_coach_idempotency_marker_meta(meta):
                continue
            messages.append(self._public_message_dict(row))
        return messages

    def create_phase_transition(self, transition: dict[str, Any]) -> dict[str, Any]:
        """Persist a pending stage recommendation on a new assistant message row.

        The transition id becomes the assistant message id. Content is filled in
        later when the coach reply is stored via ``add_message``.
        """
        thread_id = str(transition.get("thread_id") or "")
        record = {
            "id": str(transition.get("id") or uuid.uuid4()),
            "thread_id": thread_id,
            "from_stage": str(transition.get("from_stage") or ""),
            "to_stage": str(transition.get("to_stage") or ""),
            "assessment": transition.get("assessment") or {},
            "status": str(transition.get("status") or "pending"),
            "created_at": str(transition.get("created_at") or utc_now()),
            "resolved_at": transition.get("resolved_at"),
        }
        if not record["from_stage"] or not record["to_stage"]:
            raise ValueError("Transition stages are required")
        assessment = record["assessment"]
        if hasattr(assessment, "model_dump"):
            assessment = assessment.model_dump(mode="json")
        with self._lock, self._connect() as connection:
            owned = connection.execute(
                "SELECT id, conversation_revision FROM notebooks "
                "WHERE id=? AND user_id=?",
                (thread_id, self.owner_id),
            ).fetchone()
            if not owned:
                raise ValueError("Chat not found")
            stamp_revision = self._notebook_revision_value(owned)
            connection.execute(
                f"""
                UPDATE messages
                SET decision_status='rejected', decision_at=?
                WHERE notebook_id=? AND decision_status='pending'
                  AND {self._active_at_revision_sql()}
                """,
                (utc_now(), thread_id, stamp_revision, stamp_revision),
            )
            connection.execute(
                """
                INSERT INTO messages
                  (id, notebook_id, role, content, is_error, assessment_text,
                   cited_source_ids_text, proposed_stage, decision_status,
                   decision_at, metadata_text, created_at,
                   conversation_revision, previous_message_id,
                   superseded_at_revision)
                VALUES (?, ?, 'assistant', '', 0, ?, NULL, ?, 'pending', NULL, ?, ?,
                        ?, NULL, NULL)
                """,
                (
                    record["id"],
                    record["thread_id"],
                    _dump(assessment if isinstance(assessment, dict) else {}),
                    record["to_stage"],
                    _dump(
                        {
                            "from_stage": record["from_stage"],
                            "workflow": "langgraph",
                            "pending_transition_id": record["id"],
                        }
                    ),
                    record["created_at"],
                    stamp_revision,
                ),
            )
        return record

    def get_pending_phase_transition(self, thread_id: str) -> dict[str, Any] | None:
        """Return the newest unresolved stage recommendation for a notebook."""
        thread = self.get_thread(thread_id)
        if not thread:
            return None
        revision = int(thread.get("conversation_revision") or 0)
        with self._connect() as connection:
            row = connection.execute(
                f"""
                SELECT * FROM messages
                WHERE notebook_id=? AND decision_status='pending'
                  AND proposed_stage IS NOT NULL
                  AND {self._active_at_revision_sql()}
                ORDER BY created_at DESC, id DESC
                LIMIT 1
                """,
                (thread_id, revision, revision),
            ).fetchone()
        return self._phase_transition_from_message(row) if row else None

    def resolve_phase_transition(
        self,
        thread_id: str,
        transition_id: str,
        status: str,
    ) -> dict[str, Any]:
        """Record a student's confirmation or rejection without advancing journey."""
        if status not in {"confirmed", "rejected"}:
            raise ValueError("Transition status must be confirmed or rejected")
        with self._lock, self._connect() as connection:
            notebook = connection.execute(
                "SELECT conversation_revision FROM notebooks "
                "WHERE id=? AND user_id=?",
                (thread_id, self.owner_id),
            ).fetchone()
            if not notebook:
                raise ValueError("Pending transition not found")
            revision = self._notebook_revision_value(notebook)
            row = connection.execute(
                f"""
                SELECT m.* FROM messages m
                JOIN notebooks n ON n.id=m.notebook_id
                WHERE m.id=? AND m.notebook_id=? AND n.user_id=?
                  AND m.decision_status='pending'
                  AND {self._active_at_revision_sql('m')}
                """,
                (
                    transition_id,
                    thread_id,
                    self.owner_id,
                    revision,
                    revision,
                ),
            ).fetchone()
            if not row:
                raise ValueError("Pending transition not found")
            resolved_at = utc_now()
            connection.execute(
                "UPDATE messages SET decision_status=?, decision_at=? WHERE id=?",
                (status, resolved_at, transition_id),
            )
            value = dict(row)
            value["decision_status"] = status
            value["decision_at"] = resolved_at
        return self._phase_transition_from_message(value)

    def apply_phase_transition_decision(
        self,
        thread_id: str,
        transition_id: str,
        *,
        accepted: bool,
        metadata_patch: dict[str, Any] | None = None,
        expected_from_stage: str | None = None,
    ) -> dict[str, Any]:
        """Confirm or reject a transition and optionally advance journey atomically."""
        status = "confirmed" if accepted else "rejected"
        if accepted and not metadata_patch:
            raise ValueError("Accepted transitions require a journey metadata patch")
        with self._lock, self._connect() as connection:
            notebook = connection.execute(
                "SELECT current_stage, progress_text, settings_text, "
                "conversation_revision FROM notebooks "
                "WHERE id=? AND user_id=?",
                (thread_id, self.owner_id),
            ).fetchone()
            if not notebook:
                raise ValueError("Notebook not found")
            revision = self._notebook_revision_value(notebook)
            row = connection.execute(
                f"""
                SELECT m.* FROM messages m
                JOIN notebooks n ON n.id=m.notebook_id
                WHERE m.id=? AND m.notebook_id=? AND n.user_id=?
                  AND m.decision_status='pending'
                  AND {self._active_at_revision_sql('m')}
                """,
                (
                    transition_id,
                    thread_id,
                    self.owner_id,
                    revision,
                    revision,
                ),
            ).fetchone()
            if not row:
                raise ValueError("Pending transition not found")
            if accepted and expected_from_stage is not None:
                active_stage = str(notebook["current_stage"] or "focus")
                if active_stage != expected_from_stage:
                    raise ValueError(
                        "The notebook stage changed; request a new recommendation"
                    )
            resolved_at = utc_now()
            connection.execute(
                "UPDATE messages SET decision_status=?, decision_at=? WHERE id=?",
                (status, resolved_at, transition_id),
            )
            if accepted and metadata_patch:
                progress = _load(notebook["progress_text"], {})
                if not isinstance(progress, dict):
                    progress = {}
                settings_blob = _load(notebook["settings_text"], {})
                if not isinstance(settings_blob, dict):
                    settings_blob = {}
                current_meta = {
                    **settings_blob,
                    "learning_journey": {
                        **progress,
                        "current_stage": notebook["current_stage"],
                    },
                    "thinking_stage": notebook["current_stage"],
                }
                next_meta = {**current_meta, **metadata_patch}
                if isinstance(metadata_patch.get("learning_journey"), dict):
                    next_meta["learning_journey"] = metadata_patch["learning_journey"]
                stage, progress_text, settings_text = self._split_notebook_metadata(
                    next_meta
                )
                connection.execute(
                    """
                    UPDATE notebooks
                    SET current_stage=?, progress_text=?, settings_text=?, updated_at=?
                    WHERE id=? AND user_id=?
                    """,
                    (
                        stage,
                        progress_text,
                        settings_text,
                        resolved_at,
                        thread_id,
                        self.owner_id,
                    ),
                )
            value = dict(row)
            value["decision_status"] = status
            value["decision_at"] = resolved_at
        return self._phase_transition_from_message(value)

    def _phase_transition_from_message(self, row: Any) -> dict[str, Any]:
        """Convert a messages row carrying a decision into PendingPhaseTransition shape."""
        meta = _load(row["metadata_text"], {})
        if not isinstance(meta, dict):
            meta = {}
        assessment = _load(row["assessment_text"], {})
        if not isinstance(assessment, dict):
            assessment = {}
        from_stage = str(
            meta.get("from_stage")
            or assessment.get("current_stage")
            or ""
        )
        return {
            "id": str(row["id"]),
            "thread_id": str(row["notebook_id"]),
            "from_stage": from_stage,
            "to_stage": str(row["proposed_stage"] or ""),
            "assessment": assessment,
            "status": str(row["decision_status"] or "pending"),
            "created_at": str(row["created_at"]),
            "resolved_at": row["decision_at"],
        }

    def _load_extracted_text(self, extracted_text_key: str | None) -> str:
        """Load extracted text bytes from object storage."""
        if not extracted_text_key:
            return ""
        from backend.persistence.factory import get_file_storage

        try:
            data = get_file_storage().get_bytes(str(extracted_text_key))
        except FileNotFoundError:
            return ""
        try:
            return data.decode("utf-8")
        except UnicodeDecodeError:
            return data.decode("utf-8", errors="replace")

    def add_source(
        self,
        thread_id: str,
        *,
        kind: str,
        title: str,
        mime: str = "text/plain",
        path: str | None = None,
        source_url: str | None = None,
        extracted_text_key: str | None = None,
        size: int = 0,
        selected: bool = True,
        metadata: dict[str, Any] | None = None,
        source_id: str | None = None,
    ) -> str:
        """Add source metadata whose extracted text is already in file storage.

        This method performs database work only so DSQL may safely retry the
        whole write transaction. Source services must store extracted text
        first and pass its deterministic object key.
        """
        if kind not in {"file", "image", "text", "url"}:
            raise ValueError("Unsupported source type")
        normalized_title = " ".join(title.strip().split())[:180]
        if not normalized_title:
            raise ValueError("Source title is required")
        metadata_dict = dict(metadata or {})
        object_key = metadata_dict.get("object_key") or None
        storage_provider = str(metadata_dict.get("storage_provider") or "local")
        if path:
            if storage_provider in {"s3", "memory"} or object_key:
                object_key = str(object_key or path)
                path = None
            else:
                resolved_path = Path(path).resolve()
                allowed_root = (settings.files_dir / "threads" / thread_id).resolve()
                if allowed_root not in resolved_path.parents:
                    raise ValueError("Unsafe source path")
                # Local filesystem path kept in metadata for compatibility.
                metadata_dict["local_path"] = str(resolved_path)
                path = None
        source_id = source_id or str(uuid.uuid4())
        stored_text_key = str(extracted_text_key or "").strip() or None
        now = utc_now()
        with self._lock, self._connect() as connection:
            owned = connection.execute(
                "SELECT id FROM notebooks WHERE id=? AND user_id=?",
                (thread_id, self.owner_id),
            ).fetchone()
            if not owned:
                raise ValueError("Notebook not found")
            connection.execute(
                """
                INSERT INTO sources
                  (id, notebook_id, kind, title, content_type, byte_size,
                   object_key, extracted_text_key, source_url, selected,
                   metadata_text, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    source_id,
                    thread_id,
                    kind,
                    normalized_title,
                    mime or "application/octet-stream",
                    max(0, int(size)),
                    object_key,
                    stored_text_key,
                    source_url,
                    int(selected),
                    _dump(metadata_dict),
                    now,
                    now,
                ),
            )
            connection.execute(
                "UPDATE notebooks SET updated_at=? WHERE id=? AND user_id=?",
                (now, thread_id, self.owner_id),
            )
        return source_id

    def list_sources(
        self,
        thread_id: str,
        *,
        selected_only: bool = False,
    ) -> list[dict[str, Any]]:
        """List owned sources for a notebook."""
        if not self.get_thread(thread_id):
            return []
        selected_clause = " AND selected=1" if selected_only else ""
        with self._connect() as connection:
            rows = connection.execute(
                f"""
                SELECT s.* FROM sources s
                JOIN notebooks n ON n.id=s.notebook_id
                WHERE s.notebook_id=? AND n.user_id=?{selected_clause}
                ORDER BY s.created_at ASC, s.id ASC
                """,
                (thread_id, self.owner_id),
            ).fetchall()
        return [self._source_dict(row) for row in rows]

    def get_source(self, thread_id: str, source_id: str) -> dict[str, Any] | None:
        """Return one owned source or ``None``."""
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT s.* FROM sources s
                JOIN notebooks n ON n.id=s.notebook_id
                WHERE s.id=? AND s.notebook_id=? AND n.user_id=?
                """,
                (source_id, thread_id, self.owner_id),
            ).fetchone()
        return self._source_dict(row) if row else None

    def find_source_by_path(
        self,
        thread_id: str,
        path: str,
    ) -> dict[str, Any] | None:
        """Find a source by object key or legacy local path."""
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT s.* FROM sources s
                JOIN notebooks n ON n.id=s.notebook_id
                WHERE s.notebook_id=? AND n.user_id=?
                  AND (s.object_key=? OR s.metadata_text LIKE ?)
                """,
                (thread_id, self.owner_id, path, f'%{path}%'),
            ).fetchone()
        if not row:
            return None
        source = self._source_dict(row)
        if source.get("path") == path or source.get("object_key") == path:
            return source
        # Fallback: check local_path in metadata.
        if (source.get("metadata") or {}).get("local_path") == path:
            return source
        return None

    def _source_dict(self, row: Any) -> dict[str, Any]:
        """Normalize a sources row for callers (legacy keys preserved)."""
        metadata = _load(row["metadata_text"], {})
        if not isinstance(metadata, dict):
            metadata = {}
        legacy_extracted = str(metadata.pop("_legacy_extracted_text", "") or "")
        object_key = row["object_key"]
        local_path = metadata.get("local_path")
        extracted = self._load_extracted_text(row["extracted_text_key"])
        if not extracted:
            extracted = legacy_extracted
        path_value = object_key or local_path
        if object_key and metadata.get("storage_provider") not in {"s3", "memory"}:
            # Object key present implies object storage for readers.
            if settings.file_storage_provider != "local":
                metadata.setdefault(
                    "storage_provider", settings.file_storage_provider
                )
                metadata.setdefault("object_key", object_key)
        return {
            "id": str(row["id"]),
            "threadId": str(row["notebook_id"]),
            "notebook_id": str(row["notebook_id"]),
            "ownerId": self.owner_id,
            "kind": row["kind"],
            "title": row["title"],
            "mime": row["content_type"] or "application/octet-stream",
            "content_type": row["content_type"],
            "path": path_value,
            "object_key": object_key,
            "extracted_text_key": row["extracted_text_key"],
            "sourceUrl": row["source_url"],
            "extractedText": extracted,
            "size": int(row["byte_size"] or 0),
            "byte_size": int(row["byte_size"] or 0),
            "selected": bool(row["selected"]),
            "metadata": metadata,
            "createdAt": row["created_at"],
            "updatedAt": row["updated_at"],
        }

    def set_source_selected(
        self,
        thread_id: str,
        source_id: str,
        selected: bool,
    ) -> None:
        """Toggle one personal source selection flag.

        Locked course materials (Lecture Notes / Readings) stay selected and
        cannot be cleared through this API.
        """
        from backend.source_library import is_locked_course_source

        source = self.get_source(thread_id, source_id)
        if not source:
            raise ValueError("Source not found")
        if is_locked_course_source(source):
            if not selected:
                raise ValueError(
                    "Course materials stay selected and cannot be unselected."
                )
            if source.get("selected"):
                return
        with self._lock, self._connect() as connection:
            changed = connection.execute(
                """
                UPDATE sources SET selected=?, updated_at=?
                WHERE id=? AND notebook_id=? AND notebook_id IN (
                  SELECT id FROM notebooks WHERE id=? AND user_id=?
                )
                """,
                (
                    int(selected),
                    utc_now(),
                    source_id,
                    thread_id,
                    thread_id,
                    self.owner_id,
                ),
            ).rowcount
        if not changed:
            raise ValueError("Source not found")

    def set_all_sources_selected(self, thread_id: str, selected: bool) -> None:
        """Select or deselect personal sources in an owned notebook.

        Locked course materials are never cleared. When selecting all, any
        locked row that somehow became unselected is forced back on.
        """
        from backend.source_library import is_locked_course_source

        if not self.get_thread(thread_id):
            raise ValueError("Notebook not found")
        now = utc_now()
        with self._lock, self._connect() as connection:
            rows = connection.execute(
                """
                SELECT id, selected, metadata_text FROM sources
                WHERE notebook_id=?
                """,
                (thread_id,),
            ).fetchall()
            for row in rows:
                metadata = _load(row["metadata_text"], {})
                if not isinstance(metadata, dict):
                    metadata = {}
                locked = is_locked_course_source(
                    {"metadata": metadata, "selected": bool(row["selected"])}
                )
                if locked:
                    if not bool(row["selected"]):
                        connection.execute(
                            """
                            UPDATE sources SET selected=1, updated_at=?
                            WHERE id=? AND notebook_id=?
                            """,
                            (now, row["id"], thread_id),
                        )
                    continue
                connection.execute(
                    """
                    UPDATE sources SET selected=?, updated_at=?
                    WHERE id=? AND notebook_id=?
                    """,
                    (int(selected), now, row["id"], thread_id),
                )

    def rename_source(self, thread_id: str, source_id: str, title: str) -> None:
        """Rename a personal notebook source. Locked course materials stay fixed."""
        source = self.get_source(thread_id, source_id)
        if not source:
            raise ValueError("Source not found")
        metadata = source.get("metadata") or {}
        if metadata.get("locked_source"):
            raise ValueError("Course materials cannot be renamed.")
        normalized_title = " ".join(title.strip().split())[:180]
        if not normalized_title:
            raise ValueError("Source title is required")
        with self._lock, self._connect() as connection:
            connection.execute(
                """
                UPDATE sources SET title=?, updated_at=?
                WHERE id=? AND notebook_id=?
                """,
                (normalized_title, utc_now(), source_id, thread_id),
            )

    def delete_source(
        self,
        thread_id: str,
        source_id: str,
        *,
        force: bool = False,
    ) -> None:
        """Delete a notebook source unless it is managed course material.

        While metadata exists, ownership and locked-course checks apply and the
        DB delete runs first. After a successful DB unit (or when the row is
        already absent on retry), always purge the deterministic
        authenticated-owner source object prefix. Never uses metadata-supplied
        keys for that cleanup. Repeated successful deletes are harmless.
        """
        source = self.get_source(thread_id, source_id)
        if source:
            metadata = source.get("metadata") or {}
            if metadata.get("locked_source") and not force:
                raise ValueError("Course materials cannot be removed from the app.")
            with self._lock, self._connect() as connection:
                connection.execute(
                    """
                    DELETE FROM sources
                    WHERE id=? AND notebook_id=?
                      AND notebook_id IN (
                        SELECT id FROM notebooks WHERE id=? AND user_id=?
                      )
                    """,
                    (source_id, thread_id, thread_id, self.owner_id),
                )
            self._cleanup_source_local_file(source, thread_id=thread_id)
        self._cleanup_source_object_prefix(thread_id, source_id)

    def _cleanup_source_object_prefix(self, thread_id: str, source_id: str) -> None:
        """Delete object-storage keys under the authenticated owner's source prefix.

        Always derived from ``self.owner_id`` plus the requested notebook/source
        ids — never from metadata ``object_key`` values — so retries cannot
        target another user's prefix.
        """
        from backend.persistence.factory import get_file_storage
        from backend.persistence.object_keys import source_prefix

        get_file_storage().delete_prefix(
            source_prefix(
                user_id=self.owner_id,
                notebook_id=thread_id,
                source_id=source_id,
            )
        )

    def _cleanup_source_local_file(
        self,
        source: dict[str, Any],
        *,
        thread_id: str,
    ) -> None:
        """Remove a managed legacy local file when metadata still named one.

        Only runs when the source row was present (so a trusted ``local_path``
        is known). Absent-row retries rely solely on object-prefix cleanup and
        do not guess unrelated local paths.
        """
        metadata = source.get("metadata") or {}
        local_path = metadata.get("local_path")
        if not (local_path and metadata.get("managed_file")):
            return
        path = Path(str(local_path)).resolve()
        allowed_root = (settings.files_dir / "threads" / thread_id).resolve()
        if path.is_file() and allowed_root in path.parents:
            path.unlink(missing_ok=True)
