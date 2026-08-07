from __future__ import annotations

import json
import shutil
import sqlite3
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .settings import settings


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _dump(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False)


def _load(value: str | None, default: Any) -> Any:
    if not value:
        return default
    try:
        return json.loads(value)
    except (TypeError, json.JSONDecodeError):
        return default


SCHEMA = """
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS users (
    id TEXT PRIMARY KEY,
    identifier TEXT NOT NULL UNIQUE,
    metadata TEXT NOT NULL DEFAULT '{}',
    createdAt TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS threads (
    id TEXT PRIMARY KEY,
    createdAt TEXT NOT NULL,
    name TEXT,
    userId TEXT,
    userIdentifier TEXT,
    tags TEXT NOT NULL DEFAULT '[]',
    metadata TEXT NOT NULL DEFAULT '{}',
    FOREIGN KEY (userId) REFERENCES users(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS steps (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    type TEXT NOT NULL,
    threadId TEXT NOT NULL,
    parentId TEXT,
    streaming INTEGER NOT NULL DEFAULT 0,
    waitForAnswer INTEGER,
    isError INTEGER,
    metadata TEXT NOT NULL DEFAULT '{}',
    tags TEXT NOT NULL DEFAULT '[]',
    input TEXT,
    output TEXT,
    createdAt TEXT,
    command TEXT,
    start TEXT,
    end TEXT,
    generation TEXT NOT NULL DEFAULT '{}',
    showInput TEXT,
    language TEXT,
    indent INTEGER,
    defaultOpen INTEGER,
    modes TEXT NOT NULL DEFAULT '{}',
    FOREIGN KEY (threadId) REFERENCES threads(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_steps_thread_created ON steps(threadId, createdAt);

CREATE TABLE IF NOT EXISTS folders (
    id TEXT PRIMARY KEY,
    ownerId TEXT NOT NULL,
    name TEXT NOT NULL,
    color TEXT NOT NULL DEFAULT '#6d5dfc',
    position INTEGER NOT NULL DEFAULT 0,
    createdAt TEXT NOT NULL,
    updatedAt TEXT NOT NULL,
    UNIQUE(ownerId, name),
    FOREIGN KEY (ownerId) REFERENCES users(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS thread_folders (
    threadId TEXT PRIMARY KEY,
    folderId TEXT NOT NULL,
    ownerId TEXT NOT NULL,
    createdAt TEXT NOT NULL,
    FOREIGN KEY (threadId) REFERENCES threads(id) ON DELETE CASCADE,
    FOREIGN KEY (folderId) REFERENCES folders(id) ON DELETE CASCADE,
    FOREIGN KEY (ownerId) REFERENCES users(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS feedbacks (
    id TEXT PRIMARY KEY,
    forId TEXT NOT NULL UNIQUE,
    threadId TEXT NOT NULL,
    value INTEGER NOT NULL,
    comment TEXT,
    FOREIGN KEY (threadId) REFERENCES threads(id) ON DELETE CASCADE,
    FOREIGN KEY (forId) REFERENCES steps(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS model_turns (
    id TEXT PRIMARY KEY,
    threadId TEXT NOT NULL,
    userMessageId TEXT,
    assistantMessageId TEXT,
    modelId TEXT NOT NULL,
    reasoningEffort TEXT,
    usage TEXT NOT NULL DEFAULT '{}',
    createdAt TEXT NOT NULL,
    FOREIGN KEY (threadId) REFERENCES threads(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS openai_thread_state (
    threadId TEXT PRIMARY KEY,
    previousResponseId TEXT,
    modelId TEXT,
    history TEXT NOT NULL DEFAULT '[]',
    vectorStoreId TEXT,
    sourceSnapshot TEXT NOT NULL DEFAULT '[]',
    groundingMode TEXT NOT NULL DEFAULT 'source_first',
    updatedAt TEXT NOT NULL,
    FOREIGN KEY (threadId) REFERENCES threads(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS notebook_sources (
    id TEXT PRIMARY KEY,
    threadId TEXT NOT NULL,
    ownerId TEXT NOT NULL,
    kind TEXT NOT NULL,
    title TEXT NOT NULL,
    mime TEXT NOT NULL DEFAULT 'text/plain',
    path TEXT,
    sourceUrl TEXT,
    extractedText TEXT NOT NULL DEFAULT '',
    size INTEGER NOT NULL DEFAULT 0,
    selected INTEGER NOT NULL DEFAULT 1,
    metadata TEXT NOT NULL DEFAULT '{}',
    createdAt TEXT NOT NULL,
    updatedAt TEXT NOT NULL,
    FOREIGN KEY (threadId) REFERENCES threads(id) ON DELETE CASCADE,
    FOREIGN KEY (ownerId) REFERENCES users(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_notebook_sources_thread
ON notebook_sources(threadId, createdAt);

CREATE TABLE IF NOT EXISTS phase_transitions (
    id TEXT PRIMARY KEY,
    threadId TEXT NOT NULL,
    fromStage TEXT NOT NULL,
    toStage TEXT NOT NULL,
    assessment TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending',
    createdAt TEXT NOT NULL,
    resolvedAt TEXT,
    FOREIGN KEY (threadId) REFERENCES threads(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_phase_transitions_thread_status
ON phase_transitions(threadId, status, createdAt);

CREATE TABLE IF NOT EXISTS app_sessions (
    id TEXT PRIMARY KEY,
    tokenHash TEXT NOT NULL UNIQUE,
    userId TEXT NOT NULL,
    createdAt TEXT NOT NULL,
    expiresAt TEXT NOT NULL,
    lastSeenAt TEXT,
    revokedAt TEXT,
    FOREIGN KEY (userId) REFERENCES users(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_app_sessions_token_hash
ON app_sessions(tokenHash);

CREATE INDEX IF NOT EXISTS idx_app_sessions_user
ON app_sessions(userId);

CREATE TABLE IF NOT EXISTS oauth_login_states (
    state TEXT PRIMARY KEY,
    codeVerifier TEXT NOT NULL,
    createdAt TEXT NOT NULL,
    expiresAt TEXT NOT NULL
);
"""


class StudentStore:
    """Framework-neutral SQLite store shared by the Streamlit frontend and OpenAI engine."""

    def __init__(self, path: Path | None = None, identifier: str = "local-student"):
        self.path = (path or settings.database_path).resolve()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.identifier = identifier
        self._lock = threading.RLock()
        with self._connect() as connection:
            connection.executescript(SCHEMA)
            self._ensure_column(
                connection,
                "openai_thread_state",
                "sourceSnapshot",
                "TEXT NOT NULL DEFAULT '[]'",
            )
            self._ensure_column(
                connection,
                "openai_thread_state",
                "groundingMode",
                "TEXT NOT NULL DEFAULT 'source_first'",
            )
            self._ensure_cognito_user_columns(connection)
            self._ensure_app_session_tables(connection)
        self.owner_id = self._ensure_user()

    @staticmethod
    def _ensure_column(
        connection: sqlite3.Connection,
        table: str,
        column: str,
        definition: str,
    ) -> None:
        columns = {
            str(row["name"])
            for row in connection.execute(f"PRAGMA table_info({table})").fetchall()
        }
        if column not in columns:
            connection.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")

    def _ensure_cognito_user_columns(self, connection: sqlite3.Connection) -> None:
        """Add Cognito profile columns without destroying existing rows."""
        self._ensure_column(connection, "users", "cognitoSub", "TEXT")
        self._ensure_column(connection, "users", "email", "TEXT")
        self._ensure_column(connection, "users", "displayName", "TEXT")
        self._ensure_column(connection, "users", "role", "TEXT NOT NULL DEFAULT 'student'")
        self._ensure_column(connection, "users", "updatedAt", "TEXT")
        self._ensure_column(connection, "users", "lastLoginAt", "TEXT")
        connection.execute(
            "CREATE UNIQUE INDEX IF NOT EXISTS idx_users_cognito_sub "
            "ON users(cognitoSub) WHERE cognitoSub IS NOT NULL"
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
            self._ensure_cognito_user_columns(connection)
            row = connection.execute(
                "SELECT id, role, displayName, email, metadata, cognitoSub FROM users "
                "WHERE cognitoSub = ?",
                (sub,),
            ).fetchone()
            created = False
            if row is None:
                row = connection.execute(
                    "SELECT id, role, displayName, email, metadata, cognitoSub FROM users "
                    "WHERE identifier = ?",
                    (identifier,),
                ).fetchone()
                if row is not None:
                    created = not bool(row["cognitoSub"])
            if row:
                existing_role = str(row["role"] or STUDENT_ROLE)
                role = resolve_role(existing_role)
                connection.execute(
                    "UPDATE users SET identifier = ?, cognitoSub = ?, email = ?, "
                    "displayName = ?, role = ?, updatedAt = ?, lastLoginAt = ? WHERE id = ?",
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
            inserted = connection.execute(
                "INSERT OR IGNORE INTO users ("
                "id, identifier, metadata, createdAt, cognitoSub, email, "
                "displayName, role, updatedAt, lastLoginAt"
                ") VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    owner_id,
                    identifier,
                    _dump({"role": role, "auth": "cognito"}),
                    now,
                    sub,
                    safe_email,
                    safe_name,
                    role,
                    now,
                    now,
                ),
            )
            # Another app worker can win the first-login insert between our
            # SELECT and INSERT. Resolve the unique Cognito subject back to the
            # one canonical row instead of surfacing an intermittent 500.
            canonical = connection.execute(
                "SELECT id, role FROM users WHERE cognitoSub = ?",
                (sub,),
            ).fetchone()
            if canonical is None:
                raise ValueError("Cognito identity could not be linked safely")
            role = resolve_role(str(canonical["role"] or STUDENT_ROLE))
            connection.execute(
                "UPDATE users SET identifier = ?, email = ?, displayName = ?, "
                "role = ?, updatedAt = ?, lastLoginAt = ? WHERE id = ?",
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
        with self._lock, self._connect() as connection:
            self._ensure_cognito_user_columns(connection)
            row = connection.execute(
                "SELECT id, identifier, cognitoSub, email, displayName, role, "
                "createdAt, updatedAt, lastLoginAt FROM users WHERE cognitoSub = ?",
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
        with self._lock, self._connect() as connection:
            self._ensure_cognito_user_columns(connection)
            row = connection.execute(
                "SELECT id, identifier, cognitoSub, email, displayName, role, "
                "createdAt, updatedAt, lastLoginAt FROM users WHERE id = ?",
                (owner_id,),
            ).fetchone()
        if not row:
            return None
        return self._user_profile_dict(row)

    @staticmethod
    def _user_profile_dict(row: sqlite3.Row) -> dict[str, Any]:
        """Normalize a users row into the public profile shape."""
        return {
            "id": str(row["id"]),
            "identifier": str(row["identifier"]),
            "cognito_sub": row["cognitoSub"],
            "email": row["email"],
            "display_name": row["displayName"],
            "role": row["role"] or "student",
            "created_at": row["createdAt"],
            "updated_at": row["updatedAt"],
            "last_login_at": row["lastLoginAt"],
        }

    def _ensure_app_session_tables(self, connection: sqlite3.Connection) -> None:
        """Create application-session tables on existing databases."""
        connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS app_sessions (
                id TEXT PRIMARY KEY,
                tokenHash TEXT NOT NULL UNIQUE,
                userId TEXT NOT NULL,
                createdAt TEXT NOT NULL,
                expiresAt TEXT NOT NULL,
                lastSeenAt TEXT,
                revokedAt TEXT,
                FOREIGN KEY (userId) REFERENCES users(id) ON DELETE CASCADE
            );
            CREATE INDEX IF NOT EXISTS idx_app_sessions_token_hash
            ON app_sessions(tokenHash);
            CREATE INDEX IF NOT EXISTS idx_app_sessions_user
            ON app_sessions(userId);
            CREATE TABLE IF NOT EXISTS oauth_login_states (
                state TEXT PRIMARY KEY,
                codeVerifier TEXT NOT NULL,
                createdAt TEXT NOT NULL,
                expiresAt TEXT NOT NULL
            );
            """
        )

    def create_app_session(
        self,
        *,
        user_id: str,
        token_hash: str,
        created_at: str,
        expires_at: str,
    ) -> str:
        """Persist a hashed application session and return its id."""
        owner_id = str(user_id or "").strip()
        digest = str(token_hash or "").strip()
        if not owner_id or not digest:
            raise ValueError("user_id and token_hash are required")
        session_id = str(uuid.uuid4())
        with self._lock, self._connect() as connection:
            self._ensure_app_session_tables(connection)
            connection.execute(
                "INSERT INTO app_sessions ("
                "id, tokenHash, userId, createdAt, expiresAt, lastSeenAt, revokedAt"
                ") VALUES (?, ?, ?, ?, ?, ?, NULL)",
                (session_id, digest, owner_id, created_at, expires_at, created_at),
            )
        return session_id

    def get_user_for_session_hash(
        self, token_hash: str, *, now_iso: str | None = None
    ) -> dict[str, Any] | None:
        """Return the user for a valid session hash, else ``None``.

        Expired or revoked sessions never authenticate. ``lastSeenAt`` is
        updated for valid sessions using UTC *now_iso*.
        """
        digest = str(token_hash or "").strip()
        if not digest:
            return None
        now_value = now_iso or utc_now()
        with self._lock, self._connect() as connection:
            self._ensure_app_session_tables(connection)
            self._ensure_cognito_user_columns(connection)
            row = connection.execute(
                "SELECT s.id AS session_id, s.expiresAt, s.revokedAt, "
                "u.id, u.identifier, u.cognitoSub, u.email, u.displayName, u.role, "
                "u.createdAt, u.updatedAt, u.lastLoginAt "
                "FROM app_sessions s "
                "JOIN users u ON u.id = s.userId "
                "WHERE s.tokenHash = ?",
                (digest,),
            ).fetchone()
            if row is None:
                return None
            if row["revokedAt"]:
                return None
            expires_at = str(row["expiresAt"] or "")
            if expires_at and expires_at <= now_value:
                return None
            connection.execute(
                "UPDATE app_sessions SET lastSeenAt = ? WHERE id = ?",
                (now_value, str(row["session_id"])),
            )
            return self._user_profile_dict(row)

    def revoke_app_session(
        self, token_hash: str, *, revoked_at: str | None = None
    ) -> bool:
        """Mark a session revoked by token hash. Return whether a row changed."""
        digest = str(token_hash or "").strip()
        if not digest:
            return False
        when = revoked_at or utc_now()
        with self._lock, self._connect() as connection:
            self._ensure_app_session_tables(connection)
            result = connection.execute(
                "UPDATE app_sessions SET revokedAt = ? "
                "WHERE tokenHash = ? AND revokedAt IS NULL",
                (when, digest),
            )
            return int(result.rowcount or 0) > 0

    def cleanup_expired_app_sessions(self, *, now_iso: str | None = None) -> int:
        """Delete expired sessions and return the number removed."""
        now_value = now_iso or utc_now()
        with self._lock, self._connect() as connection:
            self._ensure_app_session_tables(connection)
            result = connection.execute(
                "DELETE FROM app_sessions WHERE expiresAt <= ? OR "
                "(revokedAt IS NOT NULL AND revokedAt <= ?)",
                (now_value, now_value),
            )
            return int(result.rowcount or 0)

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
            self._ensure_app_session_tables(connection)
            connection.execute(
                "INSERT OR REPLACE INTO oauth_login_states "
                "(state, codeVerifier, createdAt, expiresAt) VALUES (?, ?, ?, ?)",
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
            self._ensure_app_session_tables(connection)
            row = connection.execute(
                "SELECT codeVerifier, expiresAt FROM oauth_login_states WHERE state = ?",
                (state_value,),
            ).fetchone()
            connection.execute(
                "DELETE FROM oauth_login_states WHERE state = ?",
                (state_value,),
            )
            if row is None:
                return None
            if str(row["expiresAt"] or "") <= now_value:
                return None
            return str(row["codeVerifier"])

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path, timeout=30)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA journal_mode = WAL")
        return connection

    def _ensure_user(self) -> str:
        with self._lock, self._connect() as connection:
            row = connection.execute(
                "SELECT id FROM users WHERE identifier = ?", (self.identifier,)
            ).fetchone()
            if row:
                return str(row["id"])
            owner_id = str(uuid.uuid4())
            connection.execute(
                "INSERT INTO users (id, identifier, metadata, createdAt) VALUES (?, ?, ?, ?)",
                (owner_id, self.identifier, _dump({"role": "student", "auth": "none"}), utc_now()),
            )
            return owner_id

    def get_user_preferences(self) -> dict[str, Any]:
        """Return the local user's preference metadata blob."""
        with self._lock, self._connect() as connection:
            row = connection.execute(
                "SELECT metadata FROM users WHERE id = ?",
                (self.owner_id,),
            ).fetchone()
        if not row:
            return {}
        metadata = _load(row["metadata"], {})
        return metadata if isinstance(metadata, dict) else {}

    def update_user_preferences(self, patch: dict[str, Any]) -> None:
        """Merge preference keys into the local user's metadata."""
        if not patch:
            return
        with self._lock, self._connect() as connection:
            row = connection.execute(
                "SELECT metadata FROM users WHERE id = ?",
                (self.owner_id,),
            ).fetchone()
            current = _load(row["metadata"] if row else None, {})
            if not isinstance(current, dict):
                current = {}
            next_metadata = {**current, **patch}
            connection.execute(
                "UPDATE users SET metadata = ? WHERE id = ?",
                (_dump(next_metadata), self.owner_id),
            )

    def create_thread(
        self,
        *,
        name: str = "New assignment chat",
        model_id: str,
        support_mode: str,
        assignment: dict[str, str] | None = None,
    ) -> str:
        thread_id = str(uuid.uuid4())
        metadata = {
            "selected_model": model_id,
            "support_mode": support_mode,
            "assignment": assignment or {},
        }
        with self._lock, self._connect() as connection:
            connection.execute(
                """
                INSERT INTO threads
                  (id, createdAt, name, userId, userIdentifier, tags, metadata)
                VALUES (?, ?, ?, ?, ?, '[]', ?)
                """,
                (
                    thread_id,
                    utc_now(),
                    name,
                    self.owner_id,
                    self.identifier,
                    _dump(metadata),
                ),
            )
        return thread_id

    def get_thread(self, thread_id: str) -> dict[str, Any] | None:
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT t.*, tf.folderId, folder.name AS folderName,
                       folder.color AS folderColor
                FROM threads t
                LEFT JOIN thread_folders tf ON tf.threadId = t.id
                LEFT JOIN folders folder ON folder.id=tf.folderId
                WHERE t.id = ? AND t.userId = ?
                """,
                (thread_id, self.owner_id),
            ).fetchone()
        return self._thread_dict(row) if row else None

    def list_threads(
        self, search: str = "", folder_id: str | None = None
    ) -> list[dict[str, Any]]:
        clauses = ["t.userId = ?"]
        parameters: list[Any] = [self.owner_id]
        if search.strip():
            clauses.append(
                "(LOWER(COALESCE(t.name, '')) LIKE ? OR EXISTS "
                "(SELECT 1 FROM steps s WHERE s.threadId=t.id AND LOWER(COALESCE(s.output,'')) LIKE ?))"
            )
            needle = f"%{search.strip().lower()}%"
            parameters.extend([needle, needle])
        if folder_id == "__unfiled__":
            clauses.append("tf.folderId IS NULL")
        elif folder_id:
            clauses.append("tf.folderId = ?")
            parameters.append(folder_id)
        with self._connect() as connection:
            rows = connection.execute(
                f"""
                SELECT t.*, tf.folderId, folder.name AS folderName,
                       folder.color AS folderColor,
                       COUNT(s.id) AS messageCount,
                       SUM(CASE WHEN s.type='user_message' THEN 1 ELSE 0 END)
                         AS studentTurnCount,
                       SUM(CASE WHEN feedback.value=1 THEN 1 ELSE 0 END)
                         AS helpfulCount,
                       SUM(CASE WHEN feedback.value=-1 THEN 1 ELSE 0 END)
                         AS needsReviewCount,
                       (
                         SELECT recent.output
                         FROM steps recent
                         WHERE recent.threadId=t.id
                           AND recent.type='user_message'
                         ORDER BY recent.createdAt DESC, recent.rowid DESC
                         LIMIT 1
                       ) AS latestUserMessage,
                       MAX(COALESCE(s.createdAt, t.createdAt)) AS lastActivity
                FROM threads t
                LEFT JOIN thread_folders tf ON tf.threadId=t.id
                LEFT JOIN folders folder ON folder.id=tf.folderId
                LEFT JOIN steps s ON s.threadId=t.id
                LEFT JOIN feedbacks feedback ON feedback.forId=s.id
                WHERE {' AND '.join(clauses)}
                GROUP BY t.id
                ORDER BY lastActivity DESC
                """,
                parameters,
            ).fetchall()
        return [self._thread_dict(row) for row in rows]

    def _thread_dict(self, row: sqlite3.Row) -> dict[str, Any]:
        value = dict(row)
        value["metadata"] = _load(value.get("metadata"), {})
        value["tags"] = _load(value.get("tags"), [])
        return value

    def update_thread(
        self,
        thread_id: str,
        *,
        name: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        thread = self.get_thread(thread_id)
        if not thread:
            raise ValueError("Chat not found")
        next_metadata = thread["metadata"]
        if metadata:
            next_metadata = {**next_metadata, **metadata}
        with self._lock, self._connect() as connection:
            connection.execute(
                "UPDATE threads SET name=?, metadata=? WHERE id=? AND userId=?",
                (
                    name.strip()[:120] if name is not None else thread.get("name"),
                    _dump(next_metadata),
                    thread_id,
                    self.owner_id,
                ),
            )

    def delete_thread(self, thread_id: str) -> None:
        if not self.get_thread(thread_id):
            return
        with self._lock, self._connect() as connection:
            connection.execute(
                "DELETE FROM threads WHERE id=? AND userId=?", (thread_id, self.owner_id)
            )
        for root, allowed in (
            (settings.files_dir / "threads" / thread_id, settings.files_dir),
            (settings.workspaces_dir / thread_id, settings.workspaces_dir),
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
        if not self.get_thread(thread_id):
            raise ValueError("Chat not found")
        message_id = message_id or str(uuid.uuid4())
        step_type = "user_message" if role == "user" else "assistant_message"
        step_metadata = {**(metadata or {})}
        if model_id:
            step_metadata["model"] = model_id
        with self._lock, self._connect() as connection:
            connection.execute(
                """
                INSERT INTO steps
                  (id, name, type, threadId, streaming, isError, metadata, tags,
                   input, output, createdAt, generation, modes)
                VALUES (?, ?, ?, ?, 0, ?, ?, '[]', '', ?, ?, '{}', '{}')
                """,
                (
                    message_id,
                    "You" if role == "user" else "Co-design",
                    step_type,
                    thread_id,
                    int(is_error),
                    _dump(step_metadata),
                    content,
                    utc_now(),
                ),
            )
            if role == "user":
                count = connection.execute(
                    "SELECT COUNT(*) AS total FROM steps WHERE threadId=? AND type='user_message'",
                    (thread_id,),
                ).fetchone()["total"]
                if count == 1:
                    from .title_service import NotebookTitleService

                    title = NotebookTitleService.generate(content)
                    connection.execute(
                        """
                        UPDATE threads SET name=?
                        WHERE id=? AND (name IS NULL OR name IN (?, ?))
                        """,
                        (title, thread_id, "Untitled notebook", "New assignment chat"),
                    )
        return message_id

    def update_message(self, message_id: str, content: str) -> None:
        with self._lock, self._connect() as connection:
            owned = connection.execute(
                """
                SELECT s.id FROM steps s JOIN threads t ON t.id=s.threadId
                WHERE s.id=? AND t.userId=?
                """,
                (message_id, self.owner_id),
            ).fetchone()
            if not owned:
                raise ValueError("Message not found")
            connection.execute("UPDATE steps SET output=? WHERE id=?", (content, message_id))

    def revise_user_message(
        self,
        thread_id: str,
        message_id: str,
        content: str,
        *,
        model_id: str,
        metadata: dict[str, Any],
    ) -> list[dict[str, Any]]:
        """Replace a user turn and discard every later turn and stale response state."""
        cleaned = content.strip()
        if not cleaned:
            raise ValueError("Message cannot be empty")
        with self._lock, self._connect() as connection:
            target = connection.execute(
                """
                SELECT s.rowid, s.type
                FROM steps s
                JOIN threads t ON t.id=s.threadId
                WHERE s.id=? AND s.threadId=? AND t.userId=?
                """,
                (message_id, thread_id, self.owner_id),
            ).fetchone()
            if not target or target["type"] != "user_message":
                raise ValueError("User message not found")

            later_rows = connection.execute(
                """
                SELECT id FROM steps
                WHERE threadId=? AND rowid>?
                  AND type IN ('user_message','assistant_message')
                """,
                (thread_id, target["rowid"]),
            ).fetchall()
            discarded_ids = [str(row["id"]) for row in later_rows]
            turn_message_ids = [message_id, *discarded_ids]
            placeholders = ",".join("?" for _ in turn_message_ids)
            connection.execute(
                f"""
                DELETE FROM model_turns
                WHERE threadId=?
                  AND (
                    userMessageId IN ({placeholders})
                    OR assistantMessageId IN ({placeholders})
                  )
                """,
                (thread_id, *turn_message_ids, *turn_message_ids),
            )
            connection.execute(
                "DELETE FROM steps WHERE threadId=? AND rowid>?",
                (thread_id, target["rowid"]),
            )
            next_metadata = {**metadata, "model": model_id}
            connection.execute(
                """
                UPDATE steps
                SET output=?, metadata=?, isError=0
                WHERE id=? AND threadId=?
                """,
                (cleaned, _dump(next_metadata), message_id, thread_id),
            )

            prior_rows = connection.execute(
                """
                SELECT type, output FROM steps
                WHERE threadId=? AND rowid<?
                  AND type IN ('user_message','assistant_message')
                ORDER BY createdAt ASC, rowid ASC
                """,
                (thread_id, target["rowid"]),
            ).fetchall()
            history = [
                {
                    "role": (
                        "user" if row["type"] == "user_message" else "assistant"
                    ),
                    "content": str(row["output"] or ""),
                }
                for row in prior_rows
            ]
            current_state = connection.execute(
                "SELECT vectorStoreId FROM openai_thread_state WHERE threadId=?",
                (thread_id,),
            ).fetchone()
            vector_store_id = (
                current_state["vectorStoreId"] if current_state else None
            )
            connection.execute(
                """
                INSERT INTO openai_thread_state
                  (threadId, previousResponseId, modelId, history, vectorStoreId,
                   sourceSnapshot, groundingMode, updatedAt)
                VALUES (?, NULL, NULL, ?, ?, '[]', 'source_first', ?)
                ON CONFLICT(threadId) DO UPDATE SET
                  previousResponseId=NULL,
                  modelId=NULL,
                  history=excluded.history,
                  vectorStoreId=excluded.vectorStoreId,
                  sourceSnapshot='[]',
                  groundingMode='source_first',
                  updatedAt=excluded.updatedAt
                """,
                (
                    thread_id,
                    _dump(history),
                    vector_store_id,
                    utc_now(),
                ),
            )
        return history

    def get_messages(self, thread_id: str) -> list[dict[str, Any]]:
        if not self.get_thread(thread_id):
            return []
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT s.*, f.value AS feedbackValue
                FROM steps s
                LEFT JOIN feedbacks f ON f.forId=s.id
                WHERE s.threadId=? AND s.type IN ('user_message','assistant_message')
                ORDER BY s.createdAt ASC, s.rowid ASC
                """,
                (thread_id,),
            ).fetchall()
        messages = []
        for row in rows:
            value = dict(row)
            messages.append(
                {
                    "id": value["id"],
                    "role": "user" if value["type"] == "user_message" else "assistant",
                    "content": value.get("output") or "",
                    "metadata": _load(value.get("metadata"), {}),
                    "created_at": value.get("createdAt"),
                    "is_error": bool(value.get("isError")),
                    "feedback": value.get("feedbackValue"),
                }
            )
        return messages

    def set_feedback(self, thread_id: str, message_id: str, value: int) -> None:
        if value not in (-1, 0, 1):
            raise ValueError("Feedback must be -1, 0, or 1")
        with self._lock, self._connect() as connection:
            owned = connection.execute(
                """
                SELECT s.id FROM steps s JOIN threads t ON t.id=s.threadId
                WHERE s.id=? AND s.threadId=? AND t.userId=?
                """,
                (message_id, thread_id, self.owner_id),
            ).fetchone()
            if not owned:
                raise ValueError("Message not found")
            connection.execute(
                """
                INSERT INTO feedbacks (id, forId, threadId, value, comment)
                VALUES (?, ?, ?, ?, NULL)
                ON CONFLICT(forId) DO UPDATE SET value=excluded.value
                """,
                (str(uuid.uuid4()), message_id, thread_id, value),
            )

    def list_folders(self) -> list[dict[str, Any]]:
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT f.*, COUNT(tf.threadId) AS threadCount
                FROM folders f
                LEFT JOIN thread_folders tf ON tf.folderId=f.id
                WHERE f.ownerId=?
                GROUP BY f.id
                ORDER BY f.position ASC, f.createdAt ASC
                """,
                (self.owner_id,),
            ).fetchall()
        return [dict(row) for row in rows]

    def create_folder(self, name: str, color: str = "#6d5dfc") -> str:
        folder_id = str(uuid.uuid4())
        with self._lock, self._connect() as connection:
            next_position = connection.execute(
                "SELECT COALESCE(MAX(position), -1)+1 AS value FROM folders WHERE ownerId=?",
                (self.owner_id,),
            ).fetchone()["value"]
            now = utc_now()
            connection.execute(
                """
                INSERT INTO folders
                  (id, ownerId, name, color, position, createdAt, updatedAt)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    folder_id,
                    self.owner_id,
                    name.strip()[:80],
                    color,
                    next_position,
                    now,
                    now,
                ),
            )
        return folder_id

    def rename_folder(self, folder_id: str, name: str) -> None:
        with self._lock, self._connect() as connection:
            changed = connection.execute(
                "UPDATE folders SET name=?, updatedAt=? WHERE id=? AND ownerId=?",
                (name.strip()[:80], utc_now(), folder_id, self.owner_id),
            ).rowcount
        if not changed:
            raise ValueError("Folder not found")

    def delete_folder(self, folder_id: str) -> None:
        with self._lock, self._connect() as connection:
            connection.execute(
                "DELETE FROM folders WHERE id=? AND ownerId=?",
                (folder_id, self.owner_id),
            )

    def move_thread(self, thread_id: str, folder_id: str | None) -> None:
        if not self.get_thread(thread_id):
            raise ValueError("Chat not found")
        with self._lock, self._connect() as connection:
            if folder_id is None:
                connection.execute(
                    "DELETE FROM thread_folders WHERE threadId=? AND ownerId=?",
                    (thread_id, self.owner_id),
                )
                return
            folder = connection.execute(
                "SELECT id FROM folders WHERE id=? AND ownerId=?",
                (folder_id, self.owner_id),
            ).fetchone()
            if not folder:
                raise ValueError("Folder not found")
            connection.execute(
                """
                INSERT INTO thread_folders (threadId, folderId, ownerId, createdAt)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(threadId) DO UPDATE SET
                  folderId=excluded.folderId, ownerId=excluded.ownerId
                """,
                (thread_id, folder_id, self.owner_id, utc_now()),
            )

    def create_phase_transition(self, transition: dict[str, Any]) -> dict[str, Any]:
        """Persist one model recommendation that awaits a student decision.

        This method deliberately does not alter the notebook journey. A separate
        confirmation service applies an accepted transition after validation.
        """
        thread_id = str(transition.get("thread_id") or "")
        if not self.get_thread(thread_id):
            raise ValueError("Chat not found")
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
        with self._lock, self._connect() as connection:
            connection.execute(
                """
                UPDATE phase_transitions
                SET status='rejected', resolvedAt=?
                WHERE threadId=? AND status='pending'
                """,
                (utc_now(), thread_id),
            )
            connection.execute(
                """
                INSERT INTO phase_transitions
                  (id, threadId, fromStage, toStage, assessment, status, createdAt, resolvedAt)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    record["id"],
                    record["thread_id"],
                    record["from_stage"],
                    record["to_stage"],
                    _dump(record["assessment"]),
                    record["status"],
                    record["created_at"],
                    record["resolved_at"],
                ),
            )
        return record

    def get_pending_phase_transition(self, thread_id: str) -> dict[str, Any] | None:
        """Return the newest unresolved transition for an owned notebook."""
        if not self.get_thread(thread_id):
            return None
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT * FROM phase_transitions
                WHERE threadId=? AND status='pending'
                ORDER BY createdAt DESC
                LIMIT 1
                """,
                (thread_id,),
            ).fetchone()
        return self._phase_transition_dict(row) if row else None

    def resolve_phase_transition(
        self,
        thread_id: str,
        transition_id: str,
        status: str,
    ) -> dict[str, Any]:
        """Record a student's confirmation or rejection without advancing the journey."""
        if status not in {"confirmed", "rejected"}:
            raise ValueError("Transition status must be confirmed or rejected")
        with self._lock, self._connect() as connection:
            row = connection.execute(
                """
                SELECT pt.* FROM phase_transitions pt
                JOIN threads t ON t.id=pt.threadId
                WHERE pt.id=? AND pt.threadId=? AND t.userId=? AND pt.status='pending'
                """,
                (transition_id, thread_id, self.owner_id),
            ).fetchone()
            if not row:
                raise ValueError("Pending transition not found")
            resolved_at = utc_now()
            connection.execute(
                "UPDATE phase_transitions SET status=?, resolvedAt=? WHERE id=?",
                (status, resolved_at, transition_id),
            )
            value = dict(row)
            value["status"] = status
            value["resolvedAt"] = resolved_at
        return self._phase_transition_dict_from_value(value)

    def apply_phase_transition_decision(
        self,
        thread_id: str,
        transition_id: str,
        *,
        accepted: bool,
        metadata_patch: dict[str, Any] | None = None,
        expected_from_stage: str | None = None,
    ) -> dict[str, Any]:
        """Confirm or reject a transition and optionally advance journey atomically.

        Transition status and notebook metadata update in one SQLite connection so
        a failure cannot leave a confirmed transition without matching journey
        state (or a journey advance without a resolved transition).
        """
        status = "confirmed" if accepted else "rejected"
        if accepted and not metadata_patch:
            raise ValueError("Accepted transitions require a journey metadata patch")
        with self._lock, self._connect() as connection:
            row = connection.execute(
                """
                SELECT pt.* FROM phase_transitions pt
                JOIN threads t ON t.id=pt.threadId
                WHERE pt.id=? AND pt.threadId=? AND t.userId=? AND pt.status='pending'
                """,
                (transition_id, thread_id, self.owner_id),
            ).fetchone()
            if not row:
                raise ValueError("Pending transition not found")
            thread_row = connection.execute(
                "SELECT metadata FROM threads WHERE id=? AND userId=?",
                (thread_id, self.owner_id),
            ).fetchone()
            if not thread_row:
                raise ValueError("Notebook not found")
            current_metadata = _load(thread_row["metadata"], {})
            if not isinstance(current_metadata, dict):
                current_metadata = {}
            if accepted and expected_from_stage is not None:
                journey = current_metadata.get("learning_journey")
                journey_stage = (
                    journey.get("current_stage")
                    if isinstance(journey, dict)
                    else None
                )
                thinking_stage = current_metadata.get("thinking_stage")
                active_stage = journey_stage or thinking_stage or "focus"
                if active_stage != expected_from_stage:
                    raise ValueError(
                        "The notebook stage changed; request a new recommendation"
                    )
            resolved_at = utc_now()
            connection.execute(
                "UPDATE phase_transitions SET status=?, resolvedAt=? WHERE id=?",
                (status, resolved_at, transition_id),
            )
            if accepted and metadata_patch:
                next_metadata = {**current_metadata, **metadata_patch}
                connection.execute(
                    "UPDATE threads SET metadata=? WHERE id=? AND userId=?",
                    (_dump(next_metadata), thread_id, self.owner_id),
                )
            value = dict(row)
            value["status"] = status
            value["resolvedAt"] = resolved_at
        return self._phase_transition_dict_from_value(value)

    @staticmethod
    def _phase_transition_dict(row: sqlite3.Row) -> dict[str, Any]:
        """Convert a SQLite transition row into the domain-facing snake-case form."""
        return StudentStore._phase_transition_dict_from_value(dict(row))

    @staticmethod
    def _phase_transition_dict_from_value(value: dict[str, Any]) -> dict[str, Any]:
        """Normalize persisted JSON and camel-case storage columns for consumers."""
        return {
            "id": str(value["id"]),
            "thread_id": str(value["threadId"]),
            "from_stage": str(value["fromStage"]),
            "to_stage": str(value["toStage"]),
            "assessment": _load(value.get("assessment"), {}),
            "status": str(value["status"]),
            "created_at": str(value["createdAt"]),
            "resolved_at": value.get("resolvedAt"),
        }

    def get_state(self, thread_id: str) -> dict[str, Any]:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM openai_thread_state WHERE threadId=?", (thread_id,)
            ).fetchone()
        if not row:
            return {
                "history": [],
                "sourceSnapshot": [],
                "groundingMode": "source_first",
            }
        value = dict(row)
        value["history"] = _load(value.get("history"), [])
        value["sourceSnapshot"] = _load(value.get("sourceSnapshot"), [])
        return value

    def save_state(
        self,
        thread_id: str,
        *,
        previous_response_id: str | None,
        model_id: str,
        history: list[dict[str, Any]],
        vector_store_id: str | None = None,
        source_snapshot: list[str] | None = None,
        grounding_mode: str = "source_first",
    ) -> None:
        with self._lock, self._connect() as connection:
            connection.execute(
                """
                INSERT INTO openai_thread_state
                  (threadId, previousResponseId, modelId, history, vectorStoreId,
                   sourceSnapshot, groundingMode, updatedAt)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(threadId) DO UPDATE SET
                  previousResponseId=excluded.previousResponseId,
                  modelId=excluded.modelId,
                  history=excluded.history,
                  vectorStoreId=excluded.vectorStoreId,
                  sourceSnapshot=excluded.sourceSnapshot,
                  groundingMode=excluded.groundingMode,
                  updatedAt=excluded.updatedAt
                """,
                (
                    thread_id,
                    previous_response_id,
                    model_id,
                    _dump(history),
                    vector_store_id,
                    _dump(source_snapshot or []),
                    grounding_mode,
                    utc_now(),
                ),
            )

    def add_source(
        self,
        thread_id: str,
        *,
        kind: str,
        title: str,
        mime: str = "text/plain",
        path: str | None = None,
        source_url: str | None = None,
        extracted_text: str = "",
        size: int = 0,
        selected: bool = True,
        metadata: dict[str, Any] | None = None,
        source_id: str | None = None,
    ) -> str:
        if not self.get_thread(thread_id):
            raise ValueError("Notebook not found")
        if kind not in {"file", "image", "text", "url"}:
            raise ValueError("Unsupported source type")
        normalized_title = " ".join(title.strip().split())[:180]
        if not normalized_title:
            raise ValueError("Source title is required")
        if path:
            resolved_path = Path(path).resolve()
            allowed_root = (settings.files_dir / "threads" / thread_id).resolve()
            if allowed_root not in resolved_path.parents:
                raise ValueError("Unsafe source path")
            path = str(resolved_path)
        source_id = source_id or str(uuid.uuid4())
        now = utc_now()
        with self._lock, self._connect() as connection:
            connection.execute(
                """
                INSERT INTO notebook_sources
                  (id, threadId, ownerId, kind, title, mime, path, sourceUrl,
                   extractedText, size, selected, metadata, createdAt, updatedAt)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    source_id,
                    thread_id,
                    self.owner_id,
                    kind,
                    normalized_title,
                    mime or "application/octet-stream",
                    path,
                    source_url,
                    extracted_text[:120_000],
                    max(0, int(size)),
                    int(selected),
                    _dump(metadata or {}),
                    now,
                    now,
                ),
            )
        return source_id

    def list_sources(
        self,
        thread_id: str,
        *,
        selected_only: bool = False,
    ) -> list[dict[str, Any]]:
        if not self.get_thread(thread_id):
            return []
        selected_clause = " AND selected=1" if selected_only else ""
        with self._connect() as connection:
            rows = connection.execute(
                f"""
                SELECT * FROM notebook_sources
                WHERE threadId=? AND ownerId=?{selected_clause}
                ORDER BY createdAt ASC, rowid ASC
                """,
                (thread_id, self.owner_id),
            ).fetchall()
        return [self._source_dict(row) for row in rows]

    def get_source(self, thread_id: str, source_id: str) -> dict[str, Any] | None:
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT * FROM notebook_sources
                WHERE id=? AND threadId=? AND ownerId=?
                """,
                (source_id, thread_id, self.owner_id),
            ).fetchone()
        return self._source_dict(row) if row else None

    def find_source_by_path(
        self,
        thread_id: str,
        path: str,
    ) -> dict[str, Any] | None:
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT * FROM notebook_sources
                WHERE threadId=? AND ownerId=? AND path=?
                """,
                (thread_id, self.owner_id, path),
            ).fetchone()
        return self._source_dict(row) if row else None

    @staticmethod
    def _source_dict(row: sqlite3.Row) -> dict[str, Any]:
        value = dict(row)
        value["selected"] = bool(value.get("selected"))
        value["metadata"] = _load(value.get("metadata"), {})
        return value

    def set_source_selected(
        self,
        thread_id: str,
        source_id: str,
        selected: bool,
    ) -> None:
        with self._lock, self._connect() as connection:
            changed = connection.execute(
                """
                UPDATE notebook_sources SET selected=?, updatedAt=?
                WHERE id=? AND threadId=? AND ownerId=?
                """,
                (int(selected), utc_now(), source_id, thread_id, self.owner_id),
            ).rowcount
        if not changed:
            raise ValueError("Source not found")

    def set_all_sources_selected(self, thread_id: str, selected: bool) -> None:
        if not self.get_thread(thread_id):
            raise ValueError("Notebook not found")
        with self._lock, self._connect() as connection:
            connection.execute(
                """
                UPDATE notebook_sources SET selected=?, updatedAt=?
                WHERE threadId=? AND ownerId=?
                """,
                (int(selected), utc_now(), thread_id, self.owner_id),
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
                UPDATE notebook_sources
                SET title=?, updatedAt=?
                WHERE id=? AND threadId=? AND ownerId=?
                """,
                (normalized_title, utc_now(), source_id, thread_id, self.owner_id),
            )

    def delete_source(
        self,
        thread_id: str,
        source_id: str,
        *,
        force: bool = False,
    ) -> None:
        """Delete a notebook source unless it is managed course material.

        The synchronizer may use ``force`` to refresh a managed copy after its
        read-only source file changes. Interactive callers cannot remove course
        materials from a notebook.
        """
        source = self.get_source(thread_id, source_id)
        if not source:
            return
        metadata = source.get("metadata") or {}
        if metadata.get("locked_source") and not force:
            raise ValueError("Course materials cannot be removed from the app.")
        with self._lock, self._connect() as connection:
            connection.execute(
                """
                DELETE FROM notebook_sources
                WHERE id=? AND threadId=? AND ownerId=?
                """,
                (source_id, thread_id, self.owner_id),
            )
        path_value = source.get("path")
        if not path_value or not metadata.get("managed_file"):
            return
        path = Path(path_value).resolve()
        allowed_root = (settings.files_dir / "threads" / thread_id).resolve()
        if path.is_file() and allowed_root in path.parents:
            path.unlink(missing_ok=True)

    def record_turn(
        self,
        thread_id: str,
        user_message_id: str,
        assistant_message_id: str,
        model_id: str,
        reasoning_effort: str | None,
        usage: dict[str, Any],
    ) -> None:
        with self._lock, self._connect() as connection:
            connection.execute(
                """
                INSERT INTO model_turns
                  (id, threadId, userMessageId, assistantMessageId, modelId,
                   reasoningEffort, usage, createdAt)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    str(uuid.uuid4()),
                    thread_id,
                    user_message_id,
                    assistant_message_id,
                    model_id,
                    reasoning_effort,
                    _dump(usage),
                    utc_now(),
                ),
            )
