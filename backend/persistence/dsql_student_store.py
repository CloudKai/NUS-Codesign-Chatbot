"""Aurora DSQL-backed StudentStore for production structured state.

Reuses the SQLite ``StudentStore`` public API so FastAPI, auth, and workspace
services stay provider-agnostic. SQL is adapted for DSQL (no foreign keys;
application-level cascade deletes; IAM token auth via ``dsql_connection``).
"""

from __future__ import annotations

import logging
import threading
from typing import Any, Callable

from backend.student_store import StudentStore, _dump, utc_now

from .dsql_connection import DsqlConnectionProxy, connect_dsql
from .dsql_schema import DSQL_SCHEMA, THREAD_CHILD_TABLES

logger = logging.getLogger(__name__)


class DsqlStudentStore(StudentStore):
    """StudentStore implementation that persists to Aurora DSQL."""

    def __init__(
        self,
        identifier: str = "local-student",
        *,
        connection_factory: Callable[[], DsqlConnectionProxy] | None = None,
        endpoint: str | None = None,
        region: str | None = None,
        database: str | None = None,
        user: str | None = None,
    ):
        """Create a DSQL-backed store for *identifier*.

        Args:
            identifier: Logical owner key (for example ``cognito:<sub>``).
            connection_factory: Optional injectable factory for tests.
            endpoint: DSQL cluster endpoint hostname.
            region: AWS region (default from settings).
            database: Database name (DSQL currently exposes one).
            user: Database user (IAM-authenticated ``admin`` by default).
        """
        from backend.settings import settings

        self.identifier = identifier
        self.path = None  # type: ignore[assignment]
        self._lock = threading.RLock()
        self._endpoint = (endpoint or settings.dsql_endpoint).strip()
        self._region = (region or settings.aws_region).strip()
        self._database = (database or settings.dsql_database).strip() or "postgres"
        self._user = (user or settings.dsql_user).strip() or "admin"
        self._connection_factory = connection_factory
        if self._connection_factory is None and not self._endpoint:
            raise ValueError(
                "DSQL_ENDPOINT is required when DATABASE_PROVIDER=dsql"
            )
        with self._connect() as connection:
            connection.executescript(DSQL_SCHEMA)
            self._ensure_dsql_source_columns(connection)
            try:
                connection.execute(
                    "CREATE UNIQUE INDEX IF NOT EXISTS idx_users_cognito_sub "
                    "ON users(cognitoSub) WHERE cognitoSub IS NOT NULL"
                )
            except Exception:
                # Partial indexes may vary by DSQL revision; uniqueness is still
                # enforced in upsert_cognito_user application logic.
                logger.debug("Optional cognitoSub unique index not created", exc_info=True)
        self.owner_id = self._ensure_user()

    def _connect(self) -> DsqlConnectionProxy:
        """Open one DSQL connection (or the injected test factory)."""
        if self._connection_factory is not None:
            return self._connection_factory()
        return connect_dsql(
            endpoint=self._endpoint,
            region=self._region,
            database=self._database,
            user=self._user,
        )

    def _ensure_column(
        self,
        connection: Any,
        table: str,
        column: str,
        definition: str,
    ) -> None:
        """Add a missing column using information_schema (no PRAGMA)."""
        row = connection.execute(
            """
            SELECT 1 AS present
            FROM information_schema.columns
            WHERE lower(table_name) = ? AND lower(column_name) = ?
            """,
            (table.lower(), column.lower()),
        ).fetchone()
        if row is not None:
            return
        try:
            connection.execute(f"SELECT {column} FROM {table} LIMIT 0")
            return
        except Exception:
            pass
        connection.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")

    def _ensure_cognito_user_columns(self, connection: Any) -> None:
        """Ensure Cognito profile columns exist on DSQL users table."""
        for column, definition in (
            ("cognitoSub", "TEXT"),
            ("email", "TEXT"),
            ("displayName", "TEXT"),
            ("role", "TEXT NOT NULL DEFAULT 'student'"),
            ("updatedAt", "TEXT"),
            ("lastLoginAt", "TEXT"),
        ):
            self._ensure_column(connection, "users", column, definition)

    def _ensure_app_session_tables(self, connection: Any) -> None:
        """No-op: app session tables are part of ``DSQL_SCHEMA``."""
        return

    def _ensure_dsql_source_columns(self, connection: Any) -> None:
        """Ensure upload metadata columns exist on notebook_sources."""
        for column, definition in (
            ("objectKey", "TEXT"),
            ("contentType", "TEXT"),
            ("fileSize", "INTEGER"),
            ("uploadedAt", "TEXT"),
        ):
            self._ensure_column(connection, "notebook_sources", column, definition)

    def delete_thread(self, thread_id: str) -> None:
        """Delete a notebook and all child rows, then purge stored files."""
        if not self.get_thread(thread_id):
            return
        with self._lock, self._connect() as connection:
            for table in THREAD_CHILD_TABLES:
                if table == "thread_folders":
                    connection.execute(
                        "DELETE FROM thread_folders WHERE threadId = ? AND ownerId = ?",
                        (thread_id, self.owner_id),
                    )
                elif table in {"openai_thread_state"}:
                    connection.execute(
                        f"DELETE FROM {table} WHERE threadId = ?",
                        (thread_id,),
                    )
                else:
                    connection.execute(
                        f"DELETE FROM {table} WHERE threadId = ?",
                        (thread_id,),
                    )
            connection.execute(
                "DELETE FROM threads WHERE id = ? AND userId = ?",
                (thread_id, self.owner_id),
            )
        self._cleanup_thread_files(thread_id)

    def _cleanup_thread_files(self, thread_id: str) -> None:
        """Remove persisted upload objects for a deleted notebook."""
        from backend.persistence.factory import get_file_storage
        from backend.persistence.object_keys import thread_prefix

        storage = get_file_storage()
        storage.delete_prefix(
            thread_prefix(user_id=self.owner_id, thread_id=thread_id)
        )
