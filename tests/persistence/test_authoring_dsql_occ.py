"""Authoring writes through the DSQL adapter seam: OCC retry and idempotency.

No live Aurora DSQL: the adapter's ``_connection_factory`` seam is backed by
recording SQLite proxies, following the established fake-DSQL harness from
``tests/persistence/test_deep_review_dsql.py``. Serialization failures are
raised at the proxy so the real ``run_dsql_transaction`` wrapper (never a test
double) must classify and retry them as whole units, and every assertion is
externally observable through committed rows, returned ids, or the proxy's
execution log.
"""

from __future__ import annotations

import sqlite3
import threading
from pathlib import Path
from typing import Any

import pytest

from backend.persistence.dsql_student_store import DsqlStudentStore, _OCC_WRITE_METHODS
from backend.persistence.store.operations.artifacts import (
    ArtifactConflictError,
    ArtifactValidationError,
)
from backend.persistence.store.operations.canvases import CanvasConflictError
from backend.student_store import StudentStore


class SerializationFailure(Exception):
    """Aurora DSQL serialization conflict declared at the database boundary."""

    sqlstate = "40001"


class TransactionAborted(Exception):
    """PostgreSQL session state after a failed statement in the same transaction."""

    sqlstate = "25P02"


class _RecordingDsqlProxy:
    """SQLite transaction facade that records write units and can fail once.

    After a serialization failure the same session behaves like an aborted
    PostgreSQL transaction (SQLSTATE 25P02), so a create-race recovery that
    swallowed the 40001 and re-read inside the failed session could not mask
    the retryable error from the OCC wrapper.
    """

    def __init__(
        self,
        database: Path,
        *,
        fail_on: str | None = None,
        once: list[bool] | None = None,
        log: list[str] | None = None,
    ) -> None:
        self.connection = sqlite3.connect(database, timeout=30)
        self.connection.row_factory = sqlite3.Row
        self.connection.execute("PRAGMA foreign_keys = ON")
        self._fail_on = fail_on
        self._once = once
        self._log = log
        self._failed = False
        self._wrote = False

    def execute(self, sql: str, params=None):
        """Record the statement, fail once on the configured one, then delegate."""
        compact = " ".join(sql.split())
        if self._failed:
            raise TransactionAborted("current transaction is aborted")
        if self._log is not None:
            self._log.append(compact)
        if self._once is not None and self._once[0] and self._fail_on in compact:
            self._once[0] = False
            self._failed = True
            raise SerializationFailure("could not serialize access")
        if compact[:6].upper() in ("INSERT", "UPDATE", "DELETE"):
            self._wrote = True
        return self.connection.execute(sql, params or ())

    def commit(self) -> None:
        """Commit the underlying test transaction."""
        self.connection.commit()

    def rollback(self) -> None:
        """Roll back the underlying test transaction."""
        self.connection.rollback()

    def __enter__(self):
        return self

    def __exit__(self, exc_type, _exc, _tb) -> None:
        if exc_type is None:
            if self._wrote and self._log is not None:
                self._log.append("COMMIT")
            self.connection.commit()
        else:
            self.connection.rollback()
        self.connection.close()


def _dsql_store(
    database: Path,
    owner: StudentStore,
    *,
    fail_on: str | None = None,
    once: list[bool] | None = None,
    log: list[str] | None = None,
) -> DsqlStudentStore:
    """Build one independent DSQL adapter instance over a shared test database."""
    dsql_store = object.__new__(DsqlStudentStore)
    dsql_store.identifier = owner.identifier
    dsql_store.owner_id = owner.owner_id
    dsql_store.path = None
    dsql_store._lock = threading.RLock()
    dsql_store._endpoint = ""
    dsql_store._region = ""
    dsql_store._database = "postgres"
    dsql_store._user = "co_design_app"
    dsql_store._connection_factory = lambda: _RecordingDsqlProxy(
        database, fail_on=fail_on, once=once, log=log,
    )
    dsql_store._install_occ_wrappers()
    return dsql_store


def _doc(text: str = "") -> dict[str, Any]:
    """Return one minimal valid Tiptap document."""
    return {"type": "doc", "content": []} if not text else {
        "type": "doc",
        "content": [{"type": "paragraph", "content": [{"type": "text", "text": text}]}],
    }


def _graph(title: str) -> dict[str, Any]:
    """Return one minimal valid canvas graph."""
    return {"nodes": [{"id": "n0", "kind": "note", "title": title, "x": 0, "y": 0}],
            "edges": []}


def test_dsql_occ_wrappers_include_authoring_writes() -> None:
    """Production DSQL adapter must retry every artifact/canvas write as one unit."""
    assert issubclass(DsqlStudentStore, StudentStore)
    assert {
        "create_artifact", "update_artifact", "restore_artifact", "delete_artifact",
        "create_canvas", "update_canvas", "restore_canvas", "delete_canvas",
    } <= set(_OCC_WRITE_METHODS)


def test_dsql_create_artifact_request_id_replays_same_artifact_without_second_row(
    tmp_path: Path,
) -> None:
    """A retried create through the adapter replays the committed row, not a new one."""
    database = tmp_path / "dsql-authoring-replay.sqlite3"
    owner = StudentStore(database)
    thread = owner.create_thread(model_id="mock", support_mode="critical-thinking")
    log: list[str] = []
    store = _dsql_store(database, owner, log=log)
    document = _doc()

    first = store.create_artifact(thread, "Synthesized notes", document,
                                  origin="coach_draft", request_id="draft:draft-1")
    replay = store.create_artifact(thread, "Synthesized notes", document,
                                   origin="coach_draft", request_id="draft:draft-1")

    assert replay["id"] == first["id"]
    assert replay["revision"] == 1
    assert replay["origin"] == "coach_draft"
    assert len(store.list_artifacts(thread)) == 1
    assert [entry["revision"] for entry in store.list_artifact_versions(first["id"])] == [1]
    # Only the first create's single write transaction ever committed.
    assert log.count("COMMIT") == 1


def test_dsql_create_artifact_changed_payload_under_same_request_id_refuses(
    tmp_path: Path,
) -> None:
    """A changed retry under one request id refuses through the adapter without retrying."""
    database = tmp_path / "dsql-authoring-refuse.sqlite3"
    owner = StudentStore(database)
    thread = owner.create_thread(model_id="mock", support_mode="critical-thinking")
    log: list[str] = []
    store = _dsql_store(database, owner, log=log)
    document = _doc()
    first = store.create_artifact(thread, "Notes", document, request_id="draft:draft-1")

    before = len(log)
    with pytest.raises(ArtifactValidationError, match="operation"):
        store.create_artifact(thread, "Changed retry", document,
                              request_id="draft:draft-1")

    # The refusal is a validation failure, never an OCC retry: exactly one
    # request-key lookup ran and no write transaction committed.
    refusing_calls = log[before:]
    assert sum("FROM student_artifacts" in entry for entry in refusing_calls) == 1
    assert "COMMIT" not in refusing_calls
    assert [entry["id"] for entry in store.list_artifacts(thread)] == [first["id"]]
    assert store.get_artifact(first["id"])["title"] == "Notes"


def test_dsql_create_artifact_serialization_failure_is_retried_not_swallowed(
    tmp_path: Path,
) -> None:
    """A 40001 on the artifact INSERT reaches the OCC wrapper and commits exactly once.

    The create-race recovery catches broad exceptions; it must re-raise the
    declared-sqlstate serialization failure before any rollback/re-read so the
    whole-transaction retry in ``run_dsql_transaction`` sees it. The proxy
    turns the failed session into an aborted transaction (25P02), so a
    recovery that swallowed the 40001 and re-read would surface a
    non-retryable error instead.
    """
    database = tmp_path / "dsql-authoring-occ.sqlite3"
    owner = StudentStore(database)
    thread = owner.create_thread(model_id="mock", support_mode="critical-thinking")
    once, log = [True], []
    store = _dsql_store(
        database, owner,
        fail_on="INSERT INTO student_artifacts (", once=once, log=log,
    )
    document = _doc()

    created = store.create_artifact(thread, "Notes", document,
                                    request_id="draft:retry-1")

    assert once == [False]
    artifact_insert = "INSERT INTO student_artifacts ("
    assert sum(entry.startswith(artifact_insert) for entry in log) == 2
    assert log.count("COMMIT") == 1
    assert created["revision"] == 1
    assert len(store.list_artifacts(thread)) == 1
    assert [entry["revision"] for entry in store.list_artifact_versions(created["id"])] == [1]
    # The committed request row stays replayable after the retried create.
    replay = store.create_artifact(thread, "Notes", document, request_id="draft:retry-1")
    assert replay["id"] == created["id"]


def test_dsql_update_canvas_retries_whole_unit_and_keeps_revision_guard(
    tmp_path: Path,
) -> None:
    """A 40001 across the canvas checkpoint retries as one unit; stale saves still refuse."""
    database = tmp_path / "dsql-authoring-canvas-occ.sqlite3"
    owner = StudentStore(database)
    thread = owner.create_thread(model_id="mock", support_mode="critical-thinking")
    log: list[str] = []
    store = _dsql_store(database, owner, log=log)
    canvas = store.create_canvas(thread, "Concept map", _graph("First"))

    once = [True]
    before = len(log)
    store._connection_factory = lambda: _RecordingDsqlProxy(
        database, fail_on="INSERT INTO student_canvas_versions", once=once, log=log,
    )
    saved = store.update_canvas(canvas["id"], _graph("Retried"), canvas["revision"])

    assert once == [False]
    assert saved["revision"] == 2
    assert saved["graph"]["nodes"][0]["title"] == "Retried"
    assert [entry["revision"] for entry in store.list_canvas_versions(canvas["id"])] == [2, 1]
    assert log[before:].count("COMMIT") == 1

    before = len(log)
    with pytest.raises(CanvasConflictError):
        store.update_canvas(canvas["id"], _graph("Stale"), 1)
    stale_calls = log[before:]
    # The revision guard refuses without any OCC retry.
    assert sum(entry.startswith("UPDATE student_canvases") for entry in stale_calls) == 1
    assert "COMMIT" not in stale_calls
    assert store.get_canvas(canvas["id"])["revision"] == 2


def test_dsql_restore_artifact_replays_requested_version_and_refuses_stale(
    tmp_path: Path,
) -> None:
    """Restore through the adapter re-creates the chosen version behind the revision guard."""
    database = tmp_path / "dsql-authoring-restore-artifact.sqlite3"
    owner = StudentStore(database)
    thread = owner.create_thread(model_id="mock", support_mode="critical-thinking")
    store = _dsql_store(database, owner)
    created = store.create_artifact(thread, "Notes", _doc("first"),
                                    request_id="draft:v1")
    store.update_artifact(created["id"], _doc("second"), 1, "Edited")

    restored = store.restore_artifact(created["id"], 1, 2)

    assert restored["revision"] == 3
    assert restored["origin"] == "restore"
    assert restored["title"] == "Notes"
    assert restored["document"] == _doc("first")
    with pytest.raises(ArtifactConflictError):
        store.restore_artifact(created["id"], 2, 1)
    with pytest.raises(LookupError):
        store.restore_artifact(created["id"], 9, 3)
    assert store.get_artifact(created["id"])["revision"] == 3


def test_dsql_restore_canvas_replays_requested_version_and_refuses_stale(
    tmp_path: Path,
) -> None:
    """Canvas restore through the adapter keeps the checkpoint trail behind the guard."""
    database = tmp_path / "dsql-authoring-restore-canvas.sqlite3"
    owner = StudentStore(database)
    thread = owner.create_thread(model_id="mock", support_mode="critical-thinking")
    store = _dsql_store(database, owner)
    created = store.create_canvas(thread, "Map", _graph("First"))
    store.update_canvas(created["id"], _graph("Second"), created["revision"])

    restored = store.restore_canvas(created["id"], 1, 2)

    assert restored["revision"] == 3
    assert restored["origin"] == "restore"
    assert restored["graph"]["nodes"][0]["title"] == "First"
    assert [entry["restored_from"] for entry in store.list_canvas_versions(created["id"])] == [
        1, None, None,
    ]
    with pytest.raises(CanvasConflictError):
        store.restore_canvas(created["id"], 2, 1)
    with pytest.raises(LookupError):
        store.restore_canvas(created["id"], 9, 3)
    assert store.get_canvas(created["id"])["revision"] == 3


def test_dsql_delete_authoring_units_through_adapter(tmp_path: Path) -> None:
    """Deletes through the adapter honor confirmation and revision-bound guards."""
    database = tmp_path / "dsql-authoring-delete.sqlite3"
    owner = StudentStore(database)
    thread = owner.create_thread(model_id="mock", support_mode="critical-thinking")
    store = _dsql_store(database, owner)
    artifact = store.create_artifact(thread, "Notes", _doc(), request_id="draft:del")
    canvas = store.create_canvas(thread, "Map", _graph("First"))

    with pytest.raises(ArtifactValidationError):
        store.delete_artifact(artifact["id"], confirmed=False)
    store.delete_artifact(artifact["id"], confirmed=True)
    assert store.get_artifact(artifact["id"]) is None
    with sqlite3.connect(database) as connection:
        versions_left = connection.execute(
            "SELECT COUNT(*) FROM student_artifact_versions WHERE artifact_id=?",
            (artifact["id"],),
        ).fetchone()[0]
    assert versions_left == 0

    with pytest.raises(CanvasConflictError):
        store.delete_canvas(canvas["id"], canvas["revision"] + 5, confirmed=True)
    store.delete_canvas(canvas["id"], canvas["revision"], confirmed=True)
    assert store.get_canvas(canvas["id"]) is None


def test_dsql_canvas_accepted_suggestion_ids_survive_the_adapter(tmp_path: Path) -> None:
    """Acceptance provenance persists canonically through adapter creates and retried saves."""
    database = tmp_path / "dsql-authoring-suggestions.sqlite3"
    owner = StudentStore(database)
    thread = owner.create_thread(model_id="mock", support_mode="critical-thinking")
    log: list[str] = []
    store = _dsql_store(database, owner, log=log)
    graph = _graph("First")
    graph["accepted_suggestion_ids"] = ["sg-2", "sg-1", "sg-1"]
    created = store.create_canvas(thread, "Map", graph)
    # Duplicates collapse; first-occurrence order is preserved.
    assert created["graph"]["accepted_suggestion_ids"] == ["sg-2", "sg-1"]

    once = [True]
    before = len(log)
    store._connection_factory = lambda: _RecordingDsqlProxy(
        database, fail_on="UPDATE student_canvases", once=once, log=log,
    )
    updated = dict(created["graph"])
    updated["nodes"] = [{"id": "n0", "kind": "note", "title": "Retried", "x": 0, "y": 0}]
    updated["accepted_suggestion_ids"] = ["sg-3"]
    saved = store.update_canvas(created["id"], updated, created["revision"])

    assert once == [False]
    assert log[before:].count("COMMIT") == 1
    assert saved["graph"]["accepted_suggestion_ids"] == ["sg-3"]
    assert [entry["revision"] for entry in store.list_canvas_versions(created["id"])] == [2, 1]
