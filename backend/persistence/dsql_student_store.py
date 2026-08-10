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
# delete_source / delete_thread are overridden so object-storage cleanup runs
# only after a successful DB commit (never inside the OCC retry callback).
_OCC_WRITE_METHODS = (
    "upsert_cognito_user",
    "save_oauth_login_state",
    "consume_oauth_login_state",
    "update_user_preferences",
    "create_thread",
    "update_thread",
    "add_message",
    "claim_coach_request",
    "complete_coach_request",
    "fail_coach_request",
    "persist_coach_turn",
    "update_message",
    "revise_user_message",
    "revise_conversation_from_user_message",
    "select_learning_stage",
    "create_phase_transition",
    "resolve_phase_transition",
    "apply_phase_transition_decision",
    "add_source",
    "set_source_selected",
    "set_all_sources_selected",
    "rename_source",
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
        ensure_owner: bool = True,
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
            ensure_owner: When False, skip creating a user row (auth bootstrap).
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
        self.owner_id = (
            run_dsql_transaction(self._ensure_user) if ensure_owner else ""
        )

    def ping(self) -> None:
        """Verify connectivity plus all required runtime table privileges."""

        def _ping() -> None:
            with self._connect() as connection:
                for table in (
                    "users",
                    "oauth_login_states",
                    "notebooks",
                    "messages",
                    "sources",
                ):
                    connection.execute(f"SELECT * FROM {table} LIMIT 0").fetchall()

        run_dsql_transaction(_ping)

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
        """Delete a notebook and all child rows, then purge stored files.

        Object-prefix cleanup always runs after the DB unit (or when the
        notebook row is already absent on retry). It is never inside the OCC
        callback.
        """
        if self.get_thread(thread_id):

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

    def delete_source(
        self,
        thread_id: str,
        source_id: str,
        *,
        force: bool = False,
    ) -> None:
        """Delete owned source metadata, then purge the source object prefix.

        While metadata exists, ownership and locked-course checks apply and the
        DB delete stays inside ``run_dsql_transaction``. After commit — or when
        the row is already absent on retry — delete the deterministic
        authenticated-owner source prefix outside the OCC callback. Never uses
        metadata-supplied keys for that cleanup.
        """
        source = self.get_source(thread_id, source_id)
        if source:
            metadata = source.get("metadata") or {}
            if metadata.get("locked_source") and not force:
                raise ValueError("Course materials cannot be removed from the app.")

            def _delete() -> None:
                with self._lock, self._connect() as connection:
                    connection.execute(
                        """
                        DELETE FROM sources
                        WHERE id = ? AND notebook_id = ?
                          AND notebook_id IN (
                            SELECT id FROM notebooks WHERE id = ? AND user_id = ?
                          )
                        """,
                        (source_id, thread_id, thread_id, self.owner_id),
                    )

            run_dsql_transaction(_delete)
            self._cleanup_source_local_file(source, thread_id=thread_id)
        self._cleanup_source_object_prefix(thread_id, source_id)

    def _cleanup_notebook_files(self, notebook_id: str) -> None:
        """Remove persisted upload objects for a deleted notebook.

        Runs after the DB transaction commits (or on absent-row retry) so S3
        deletes are not retried as part of OCC.
        """
        from backend.persistence.factory import get_file_storage
        from backend.persistence.object_keys import notebook_prefix

        storage = get_file_storage()
        storage.delete_prefix(
            notebook_prefix(user_id=self.owner_id, notebook_id=notebook_id)
        )
