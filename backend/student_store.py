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
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .settings import settings


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

CREATE UNIQUE INDEX IF NOT EXISTS idx_users_cognito_sub
ON users(cognito_sub);

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
        self.owner_id = self._ensure_user() if ensure_owner else ""

    def ping(self) -> None:
        """Verify the database connection without creating or reading a user row."""
        with self._connect() as connection:
            connection.execute("SELECT 1").fetchone()

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
            row = connection.execute(
                "SELECT id FROM users WHERE identifier = ?", (self.identifier,)
            ).fetchone()
            if row:
                return str(row["id"])
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
                   created_at, updated_at)
                VALUES (?, ?, ?, ?, '{}', ?, ?, ?)
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
            clauses.append(
                "(LOWER(COALESCE(n.title, '')) LIKE ? OR EXISTS "
                "(SELECT 1 FROM messages m WHERE m.notebook_id=n.id AND "
                "LOWER(COALESCE(m.content,'')) LIKE ?))"
            )
            needle = f"%{search.strip().lower()}%"
            parameters.extend([needle, needle])
        with self._connect() as connection:
            rows = connection.execute(
                f"""
                SELECT n.*,
                       COUNT(m.id) AS messageCount,
                       SUM(CASE WHEN m.role='user' THEN 1 ELSE 0 END)
                         AS studentTurnCount,
                       (
                         SELECT recent.content
                         FROM messages recent
                         WHERE recent.notebook_id=n.id
                           AND recent.role='user'
                         ORDER BY recent.created_at DESC, recent.id DESC
                         LIMIT 1
                       ) AS latestUserMessage,
                       MAX(COALESCE(m.created_at, n.updated_at, n.created_at))
                         AS lastActivity
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
                "SELECT id FROM notebooks WHERE id=? AND user_id=?",
                (thread_id, self.owner_id),
            ).fetchone()
            if not owned:
                raise ValueError("Chat not found")
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
                # so the assistant reply sorts after the user turn.
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
                       decision_at, metadata_text, created_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
                    ),
                )
            if role == "user":
                count = connection.execute(
                    "SELECT COUNT(*) AS total FROM messages "
                    "WHERE notebook_id=? AND role='user'",
                    (thread_id,),
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

    def persist_coach_turn(
        self,
        thread_id: str,
        *,
        expected_stage: str,
        user_content: str,
        user_metadata: dict[str, Any],
        assistant_content: str,
        assistant_metadata: dict[str, Any],
        summary_metadata: dict[str, Any],
        assistant_message_id: str | None = None,
        generated_title: str | None = None,
    ) -> tuple[str, str]:
        """Persist one completed coaching turn in a single DB transaction.

        Provider, retrieval, and object-storage work must finish before this
        method is called. The user row, assistant assessment/citations/pending
        decision, and notebook summary either commit together or roll back.
        """
        cleaned_user = user_content.strip()
        cleaned_assistant = assistant_content.strip()
        if not cleaned_user or not cleaned_assistant:
            raise ValueError("Completed coach turns require both messages")
        user_id = str(uuid.uuid4())
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

            user_created_at = utc_now()
            assistant_created_at = utc_now()
            connection.execute(
                """
                INSERT INTO messages
                  (id, notebook_id, role, content, is_error, assessment_text,
                   cited_source_ids_text, proposed_stage, decision_status,
                   decision_at, metadata_text, created_at)
                VALUES (?, ?, 'user', ?, 0, NULL, NULL, NULL, NULL, NULL, ?, ?)
                """,
                (user_id, thread_id, cleaned_user, _dump(user_metadata), user_created_at),
            )
            if decision_status == "pending":
                connection.execute(
                    """
                    UPDATE messages
                    SET decision_status='rejected', decision_at=?
                    WHERE notebook_id=? AND decision_status='pending'
                    """,
                    (assistant_created_at, thread_id),
                )
            connection.execute(
                """
                INSERT INTO messages
                  (id, notebook_id, role, content, is_error, assessment_text,
                   cited_source_ids_text, proposed_stage, decision_status,
                   decision_at, metadata_text, created_at)
                VALUES (?, ?, 'assistant', ?, 0, ?, ?, ?, ?, NULL, ?, ?)
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
                ),
            )

            thread = self._thread_dict(notebook)
            current_meta = {
                **dict(thread.get("metadata") or {}),
                **summary_metadata,
                "last_workflow_user_message_id": user_id,
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
            connection.execute(
                """
                UPDATE notebooks
                SET title=?, current_stage=?, progress_text=?, settings_text=?,
                    updated_at=?
                WHERE id=? AND user_id=?
                """,
                (
                    title,
                    stage,
                    progress_text,
                    settings_text,
                    assistant_created_at,
                    thread_id,
                    self.owner_id,
                ),
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

    def revise_user_message(
        self,
        thread_id: str,
        message_id: str,
        content: str,
        *,
        model_id: str,
        metadata: dict[str, Any],
    ) -> list[dict[str, Any]]:
        """Replace a user turn and discard every later turn."""
        cleaned = content.strip()
        if not cleaned:
            raise ValueError("Message cannot be empty")
        with self._lock, self._connect() as connection:
            target = connection.execute(
                """
                SELECT m.id, m.role, m.created_at
                FROM messages m
                JOIN notebooks n ON n.id=m.notebook_id
                WHERE m.id=? AND m.notebook_id=? AND n.user_id=?
                """,
                (message_id, thread_id, self.owner_id),
            ).fetchone()
            if not target or target["role"] != "user":
                raise ValueError("User message not found")

            target_created = str(target["created_at"] or "")
            connection.execute(
                """
                DELETE FROM messages
                WHERE notebook_id=?
                  AND (
                    created_at > ?
                    OR (created_at = ? AND id > ?)
                  )
                """,
                (thread_id, target_created, target_created, message_id),
            )
            next_metadata = {**metadata, "model": model_id}
            connection.execute(
                """
                UPDATE messages
                SET content=?, metadata_text=?, is_error=0,
                    assessment_text=NULL, cited_source_ids_text=NULL,
                    proposed_stage=NULL, decision_status=NULL, decision_at=NULL
                WHERE id=? AND notebook_id=?
                """,
                (cleaned, _dump(next_metadata), message_id, thread_id),
            )
            prior_rows = connection.execute(
                """
                SELECT role, content FROM messages
                WHERE notebook_id=?
                  AND (
                    created_at < ?
                    OR (created_at = ? AND id < ?)
                  )
                ORDER BY created_at ASC, id ASC
                """,
                (thread_id, target_created, target_created, message_id),
            ).fetchall()
            history = [
                {
                    "role": str(row["role"]),
                    "content": str(row["content"] or ""),
                }
                for row in prior_rows
            ]
            connection.execute(
                "UPDATE notebooks SET updated_at=? WHERE id=? AND user_id=?",
                (utc_now(), thread_id, self.owner_id),
            )
        return history

    def get_messages(self, thread_id: str) -> list[dict[str, Any]]:
        """Return canonical chronological messages for an owned notebook."""
        if not self.get_thread(thread_id):
            return []
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT * FROM messages
                WHERE notebook_id=?
                ORDER BY created_at ASC, id ASC
                """,
                (thread_id,),
            ).fetchall()
        messages = []
        for row in rows:
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
            messages.append(
                {
                    "id": str(row["id"]),
                    "role": str(row["role"]),
                    "content": row["content"] or "",
                    "metadata": meta,
                    "created_at": row["created_at"],
                    "is_error": bool(row["is_error"]),
                    "feedback": None,
                }
            )
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
                "SELECT id FROM notebooks WHERE id=? AND user_id=?",
                (thread_id, self.owner_id),
            ).fetchone()
            if not owned:
                raise ValueError("Chat not found")
            connection.execute(
                """
                UPDATE messages
                SET decision_status='rejected', decision_at=?
                WHERE notebook_id=? AND decision_status='pending'
                """,
                (utc_now(), thread_id),
            )
            connection.execute(
                """
                INSERT INTO messages
                  (id, notebook_id, role, content, is_error, assessment_text,
                   cited_source_ids_text, proposed_stage, decision_status,
                   decision_at, metadata_text, created_at)
                VALUES (?, ?, 'assistant', '', 0, ?, NULL, ?, 'pending', NULL, ?, ?)
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
                ),
            )
        return record

    def get_pending_phase_transition(self, thread_id: str) -> dict[str, Any] | None:
        """Return the newest unresolved stage recommendation for a notebook."""
        if not self.get_thread(thread_id):
            return None
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT * FROM messages
                WHERE notebook_id=? AND decision_status='pending'
                  AND proposed_stage IS NOT NULL
                ORDER BY created_at DESC, id DESC
                LIMIT 1
                """,
                (thread_id,),
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
            row = connection.execute(
                """
                SELECT m.* FROM messages m
                JOIN notebooks n ON n.id=m.notebook_id
                WHERE m.id=? AND m.notebook_id=? AND n.user_id=?
                  AND m.decision_status='pending'
                """,
                (transition_id, thread_id, self.owner_id),
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
            row = connection.execute(
                """
                SELECT m.* FROM messages m
                JOIN notebooks n ON n.id=m.notebook_id
                WHERE m.id=? AND m.notebook_id=? AND n.user_id=?
                  AND m.decision_status='pending'
                """,
                (transition_id, thread_id, self.owner_id),
            ).fetchone()
            if not row:
                raise ValueError("Pending transition not found")
            notebook = connection.execute(
                "SELECT current_stage, progress_text, settings_text FROM notebooks "
                "WHERE id=? AND user_id=?",
                (thread_id, self.owner_id),
            ).fetchone()
            if not notebook:
                raise ValueError("Notebook not found")
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
        object_key = row["object_key"]
        local_path = metadata.get("local_path")
        extracted = self._load_extracted_text(row["extracted_text_key"])
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
        """Toggle one source selection flag."""
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
        """Select or deselect every source in an owned notebook."""
        if not self.get_thread(thread_id):
            raise ValueError("Notebook not found")
        with self._lock, self._connect() as connection:
            connection.execute(
                """
                UPDATE sources SET selected=?, updated_at=?
                WHERE notebook_id=?
                """,
                (int(selected), utc_now(), thread_id),
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
