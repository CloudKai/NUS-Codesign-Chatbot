"""Authoring writes retry SQLSTATE 40001 as whole OCC units.

A transient serialization conflict landing after a mid-transaction insert must
retry the entire authoring unit and leave exactly one committed row set.
"""

from __future__ import annotations

import sqlite3
import threading
from pathlib import Path

from backend.persistence.dsql_student_store import DsqlStudentStore
from backend.student_store import StudentStore


class SerializationFailure(Exception):
    """Deterministic Aurora serialization conflict at the database boundary."""

    sqlstate = "40001"


class _RecordingProxy:
    """SQLite transaction facade that records committed write units."""

    def __init__(
        self,
        database: Path,
        *,
        fail_on: str,
        once: list[bool],
        committed: list[str],
    ) -> None:
        self.connection = sqlite3.connect(database, timeout=30)
        self.connection.row_factory = sqlite3.Row
        self.connection.execute("PRAGMA foreign_keys = ON")
        self._fail_on = fail_on
        self._once = once
        self._committed = committed
        self._wrote = False

    def execute(self, sql: str, params=None):
        """Fail once on the configured statement, then behave normally."""
        if self._once[0] and self._fail_on in sql:
            self._once[0] = False
            raise SerializationFailure("could not serialize access")
        if sql.lstrip().upper().startswith(("INSERT", "UPDATE", "DELETE")):
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
            if self._wrote:
                self._committed.append("commit")
            self.commit()
        else:
            self.rollback()
        self.connection.close()


def _dsql_store(
    database: Path,
    owner: StudentStore,
    *,
    fail_on: str,
    once: list[bool],
    committed: list[str],
) -> DsqlStudentStore:
    """Build one DSQL adapter over SQLite with a single injected conflict."""
    store = object.__new__(DsqlStudentStore)
    store.identifier = owner.identifier
    store.owner_id = owner.owner_id
    store.path = None
    store._lock = threading.RLock()
    store._endpoint = ""
    store._region = ""
    store._database = "postgres"
    store._user = "co_design_app"
    store._connection_factory = lambda: _RecordingProxy(
        database, fail_on=fail_on, once=once, committed=committed,
    )
    store._install_occ_wrappers()
    return store


def test_artifact_create_retries_sqlstate_40001_as_one_unit(tmp_path: Path) -> None:
    """A conflict after the artifact insert still creates one artifact and checkpoint."""
    database = tmp_path / "authoring-artifact.sqlite3"
    local = StudentStore(database)
    notebook = local.create_thread(model_id="mock", support_mode="critical-thinking")
    once, committed = [True], []
    store = _dsql_store(
        database, local, fail_on="INSERT INTO student_artifact_versions",
        once=once, committed=committed,
    )

    created = store.create_artifact(
        notebook, "Field notes", {"type": "doc", "content": []},
    )

    assert once == [False]
    assert created["title"] == "Field notes"
    assert [entry["id"] for entry in store.list_artifacts(notebook)] == [created["id"]]
    assert [
        version["revision"] for version in store.list_artifact_versions(created["id"])
    ] == [1]
    assert committed == ["commit"]


def test_canvas_update_retries_sqlstate_40001_as_one_unit(tmp_path: Path) -> None:
    """A conflict after the version checkpoint still saves one new checked revision."""
    database = tmp_path / "authoring-canvas.sqlite3"
    local = StudentStore(database)
    notebook = local.create_thread(model_id="mock", support_mode="critical-thinking")
    graph = {"nodes": [
        {"id": "n0", "kind": "note", "title": "First", "x": 0, "y": 0},
    ], "edges": []}
    canvas = local.create_canvas(notebook, "Concept map", graph)
    once, committed = [True], []
    store = _dsql_store(
        database, local, fail_on="UPDATE student_canvases",
        once=once, committed=committed,
    )
    updated_graph = {"nodes": [
        {"id": "n0", "kind": "note", "title": "Retried", "x": 0, "y": 0},
    ], "edges": []}

    saved = store.update_canvas(canvas["id"], updated_graph, canvas["revision"])

    assert once == [False]
    assert saved["revision"] == 2
    assert saved["graph"]["nodes"][0]["title"] == "Retried"
    assert [
        version["revision"] for version in store.list_canvas_versions(canvas["id"])
    ] == [2, 1]
    assert committed == ["commit"]
