"""HTTP and provider-parity contracts for bounded notebook history pages."""

from __future__ import annotations

import sqlite3
import threading
from pathlib import Path

from fastapi.testclient import TestClient

from backend.api import create_app
from backend.persistence.dsql_student_store import DsqlStudentStore
from backend.student_store import StudentStore


def _seed_messages(store: StudentStore, thread_id: str, count: int) -> None:
    """Write a deterministic alternating transcript for page assertions."""
    for index in range(count):
        store.add_message(
            thread_id,
            "user" if index % 2 == 0 else "assistant",
            f"message-{index}",
        )


def test_message_page_route_is_typed_and_preserves_full_history_endpoint(tmp_path):
    """The additive page route is bounded while the legacy route stays complete."""
    store = StudentStore(tmp_path / "messages-api.sqlite3")
    thread_id = store.create_thread(model_id="mock", support_mode="critical-thinking")
    _seed_messages(store, thread_id, 7)
    client = TestClient(create_app(store))

    first = client.get(f"/api/v1/threads/{thread_id}/messages/page")
    assert first.status_code == 200
    payload = first.json()
    assert len(payload["messages"]) == 6
    assert payload["messages"][0]["content"] == "message-1"
    assert payload["messages"][-1]["content"] == "message-6"
    assert payload["total_count"] == 7
    assert payload["conversation_revision"] == 0
    assert payload["next_cursor"]

    older = client.get(
        f"/api/v1/threads/{thread_id}/messages/page",
        params={"cursor": payload["next_cursor"]},
    )
    assert older.status_code == 200
    assert [item["content"] for item in older.json()["messages"]] == ["message-0"]
    assert len(client.get(f"/api/v1/threads/{thread_id}/messages").json()) == 7


def test_message_page_route_rejects_bad_stale_and_foreign_requests(tmp_path):
    """Cursor errors and owner boundaries are explicit at the HTTP boundary."""
    database = tmp_path / "messages-api-errors.sqlite3"
    owner_store = StudentStore(database, identifier="owner")
    thread_id = owner_store.create_thread(
        model_id="mock", support_mode="critical-thinking"
    )
    _seed_messages(owner_store, thread_id, 7)
    owner_client = TestClient(create_app(owner_store))
    page = owner_client.get(f"/api/v1/threads/{thread_id}/messages/page").json()

    malformed = owner_client.get(
        f"/api/v1/threads/{thread_id}/messages/page",
        params={"cursor": "not-a-cursor"},
    )
    assert malformed.status_code == 400

    with owner_store._connect() as connection:
        connection.execute(
            "UPDATE notebooks SET conversation_revision=1 WHERE id=?", (thread_id,)
        )
    stale = owner_client.get(
        f"/api/v1/threads/{thread_id}/messages/page",
        params={"cursor": page["next_cursor"]},
    )
    assert stale.status_code == 409

    foreign_store = StudentStore(database, identifier="foreign")
    foreign_client = TestClient(create_app(foreign_store))
    foreign = foreign_client.get(f"/api/v1/threads/{thread_id}/messages/page")
    assert foreign.status_code == 404


def test_title_context_is_bounded(tmp_path):
    """The title migration route returns only the requested oldest user rows."""
    store = StudentStore(tmp_path / "title-context.sqlite3")
    thread_id = store.create_thread(model_id="mock", support_mode="critical-thinking")
    _seed_messages(store, thread_id, 7)
    client = TestClient(create_app(store))

    response = client.get(
        f"/api/v1/threads/{thread_id}/messages/title-context",
        params={"limit": 1},
    )
    assert response.status_code == 200
    assert response.json() == ["message-0"]


class _SqliteDsqlProxy:
    """Small SQLite-backed proxy exercising the DSQL StudentStore adapter."""

    def __init__(self, database: str | Path) -> None:
        self.connection = sqlite3.connect(database, timeout=30)
        self.connection.row_factory = sqlite3.Row

    def execute(self, sql: str, params=()):
        return self.connection.execute(sql, params or ())

    def __enter__(self):
        return self

    def __exit__(self, exc_type, _value, _traceback) -> None:
        if exc_type is None:
            self.connection.commit()
        else:
            self.connection.rollback()
        self.connection.close()


def _dsql_read_adapter(database, owner: StudentStore) -> DsqlStudentStore:
    """Construct a pathless DSQL adapter over the initialized SQLite schema."""
    adapter = object.__new__(DsqlStudentStore)
    adapter.identifier = owner.identifier
    adapter.owner_id = owner.owner_id
    adapter.path = None
    adapter._lock = threading.RLock()
    adapter._connection_factory = lambda: _SqliteDsqlProxy(database)
    adapter._endpoint = ""
    adapter._region = ""
    adapter._database = "postgres"
    adapter._user = "co_design_app"
    return adapter


def test_message_page_sqlite_and_dsql_adapters_have_same_projection(tmp_path):
    """The shared keyset/read projection remains provider-parity compatible."""
    database = tmp_path / "messages-parity.sqlite3"
    sqlite_store = StudentStore(database, identifier="parity-owner")
    thread_id = sqlite_store.create_thread(
        model_id="mock", support_mode="critical-thinking"
    )
    _seed_messages(sqlite_store, thread_id, 13)
    dsql_store = _dsql_read_adapter(database, sqlite_store)

    sqlite_page = sqlite_store.get_message_page(thread_id)
    dsql_page = dsql_store.get_message_page(thread_id)
    assert [item["id"] for item in dsql_page["messages"]] == [
        item["id"] for item in sqlite_page["messages"]
    ]
    assert dsql_page["total_count"] == sqlite_page["total_count"] == 13

    sqlite_next = sqlite_store.get_message_page(
        thread_id, cursor=sqlite_page["next_cursor"]
    )
    dsql_next = dsql_store.get_message_page(
        thread_id, cursor=dsql_page["next_cursor"]
    )
    assert [item["content"] for item in dsql_next["messages"]] == [
        item["content"] for item in sqlite_next["messages"]
    ]
