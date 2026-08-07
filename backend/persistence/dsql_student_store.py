"""Aurora DSQL-backed StudentStore for production structured state.

Reuses the SQLite ``StudentStore`` public API so FastAPI, auth, and workspace
services stay provider-agnostic. Runtime connections use the ``co_design_app``
DbConnect role and never issue CREATE/ALTER/INDEX DDL — schema bootstrap is
``scripts/init_dsql.py`` only.
"""

from __future__ import annotations

import logging
import threading
from typing import Any, Callable

from backend.student_store import StudentStore

from .dsql_connection import (
    DsqlConnectionProxy,
    connect_dsql,
    run_dsql_transaction,
)
from .dsql_schema import RUNTIME_ROLE_NAME, THREAD_CHILD_TABLES

logger = logging.getLogger(__name__)

# StudentStore write methods re-executed as a whole on SQLSTATE 40001.
_OCC_WRITE_METHODS = (
    "upsert_cognito_user",
    "create_app_session",
    "get_user_for_session_hash",
    "revoke_app_session",
    "cleanup_expired_app_sessions",
    "save_oauth_login_state",
    "consume_oauth_login_state",
    "update_user_preferences",
    "create_thread",
    "update_thread",
    # delete_thread is overridden below with DSQL cascade + post-commit S3 cleanup.
    "add_message",    "update_message",
    "revise_user_message",
    "set_feedback",
    "create_folder",
    "rename_folder",
    "delete_folder",
    "move_thread",
    "create_phase_transition",
    "resolve_phase_transition",
    "apply_phase_transition_decision",
    "save_state",
    "add_source",
    "set_source_selected",
    "set_all_sources_selected",
    "rename_source",
    "delete_source",
    "record_turn",
)


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

        Does not create or alter schema. Run ``scripts/init_dsql.py`` as admin
        before starting the application.

        Args:
            identifier: Logical owner key (for example ``cognito:<sub>``).
            connection_factory: Optional injectable factory for tests.
            endpoint: DSQL cluster endpoint hostname.
            region: AWS region (default from settings).
            database: Database name (DSQL currently exposes one).
            user: Runtime DB role (default ``co_design_app``; never ``admin``).
        """
        from backend.settings import settings

        self.identifier = identifier
        self.path = None  # type: ignore[assignment]
        self._lock = threading.RLock()
        self._endpoint = (endpoint or settings.dsql_endpoint).strip()
        self._region = (region or settings.aws_region).strip()
        self._database = (database or settings.dsql_database).strip() or "postgres"
        configured_user = (user if user is not None else settings.dsql_user).strip()
        self._user = configured_user or RUNTIME_ROLE_NAME
        self._connection_factory = connection_factory
        if self._connection_factory is None and not self._endpoint:
            raise ValueError(
                "DSQL_ENDPOINT is required when DATABASE_PROVIDER=dsql"
            )
        if self._user.lower() == "admin":
            raise ValueError(
                "DsqlStudentStore must not connect as admin; "
                f"use {RUNTIME_ROLE_NAME}"
            )
        self._install_occ_wrappers()
        self.owner_id = run_dsql_transaction(self._ensure_user)

    def _install_occ_wrappers(self) -> None:
        """Wrap inherited write methods so OCC conflicts retry the whole unit."""
        for name in _OCC_WRITE_METHODS:
            unbound = getattr(StudentStore, name)

            def _make(method: Callable[..., Any], method_name: str) -> Callable[..., Any]:
                def wrapped(*args: Any, **kwargs: Any) -> Any:
                    return run_dsql_transaction(
                        lambda: method(self, *args, **kwargs)
                    )

                wrapped.__name__ = method_name
                wrapped.__doc__ = unbound.__doc__
                return wrapped

            setattr(self, name, _make(unbound, name))

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
        """No-op: runtime must not ALTER TABLE (admin bootstrap owns DDL)."""
        return

    def _ensure_cognito_user_columns(self, connection: Any) -> None:
        """No-op: Cognito columns are created by ``scripts/init_dsql.py``."""
        return

    def _ensure_app_session_tables(self, connection: Any) -> None:
        """No-op: app session tables are created by ``scripts/init_dsql.py``."""
        return

    def delete_thread(self, thread_id: str) -> None:
        """Delete a notebook and all child rows, then purge stored files."""
        if not self.get_thread(thread_id):
            return

        def _delete() -> None:
            with self._lock, self._connect() as connection:
                for table in THREAD_CHILD_TABLES:
                    if table == "thread_folders":
                        connection.execute(
                            "DELETE FROM thread_folders WHERE threadId = ? AND ownerId = ?",
                            (thread_id, self.owner_id),
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

        # OCC wrapper already wraps delete_thread; when called via wrapper this
        # body runs inside one attempt. Call _delete directly from the unbound
        # path below — the installed wrapper targets StudentStore.delete_thread,
        # so override fully here with its own retry.
        run_dsql_transaction(_delete)
        self._cleanup_thread_files(thread_id)

    def _cleanup_thread_files(self, thread_id: str) -> None:
        """Remove persisted upload objects for a deleted notebook.

        Runs after the DB transaction commits so S3 deletes are not retried as
        part of OCC (avoid non-idempotent coupling inside the DB retry loop).
        """
        from backend.persistence.factory import get_file_storage
        from backend.persistence.object_keys import thread_prefix

        storage = get_file_storage()
        storage.delete_prefix(
            thread_prefix(user_id=self.owner_id, thread_id=thread_id)
        )
