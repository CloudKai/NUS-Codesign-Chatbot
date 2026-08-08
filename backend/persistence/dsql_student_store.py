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

from backend.student_store import NOTEBOOK_CHILD_TABLES, StudentStore

from .dsql_connection import (
    DsqlConnectionProxy,
    connect_dsql,
    run_dsql_transaction,
)
from .dsql_schema import RUNTIME_ROLE_NAME

logger = logging.getLogger(__name__)

# StudentStore write methods re-executed as a whole on SQLSTATE 40001.
_OCC_WRITE_METHODS = (
    "upsert_cognito_user",
    "save_oauth_login_state",
    "consume_oauth_login_state",
    "update_user_preferences",
    "create_thread",
    "update_thread",
    "add_message",
    "update_message",
    "revise_user_message",
    "create_phase_transition",
    "resolve_phase_transition",
    "apply_phase_transition_decision",
    "add_source",
    "set_source_selected",
    "set_all_sources_selected",
    "rename_source",
    "delete_source",
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

    def delete_thread(self, thread_id: str) -> None:
        """Delete a notebook and all child rows, then purge stored files."""
        if not self.get_thread(thread_id):
            return

        def _delete() -> None:
            with self._lock, self._connect() as connection:
                for table in NOTEBOOK_CHILD_TABLES:
                    connection.execute(
                        f"DELETE FROM {table} WHERE notebook_id = ?",
                        (thread_id,),
                    )
                connection.execute(
                    "DELETE FROM notebooks WHERE id = ? AND user_id = ?",
                    (thread_id, self.owner_id),
                )

        run_dsql_transaction(_delete)
        self._cleanup_notebook_files(thread_id)

    def _cleanup_notebook_files(self, notebook_id: str) -> None:
        """Remove persisted upload objects for a deleted notebook.

        Runs after the DB transaction commits so S3 deletes are not retried as
        part of OCC (avoid non-idempotent coupling inside the DB retry loop).
        """
        from backend.persistence.factory import get_file_storage
        from backend.persistence.object_keys import notebook_prefix

        storage = get_file_storage()
        storage.delete_prefix(
            notebook_prefix(user_id=self.owner_id, notebook_id=notebook_id)
        )
