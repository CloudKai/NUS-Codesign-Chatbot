"""Bounded notebook-history pagination contracts."""

from __future__ import annotations

import json

import pytest

from backend.student_store import (
    MessagePageCursorError,
    MessagePageRevisionConflictError,
    StudentStore,
)


def _messages(store: StudentStore, thread_id: str, count: int) -> None:
    for index in range(count):
        store.add_message(
            thread_id,
            "user" if index % 2 == 0 else "assistant",
            f"message-{index}",
        )


@pytest.mark.parametrize("count", [0, 1, 6, 7, 13])
def test_newest_pages_are_chronological_and_accumulate(tmp_path, count: int) -> None:
    store = StudentStore(tmp_path / f"messages-{count}.sqlite3")
    thread_id = store.create_thread(model_id="mock", support_mode="critical-thinking")
    _messages(store, thread_id, count)

    page = store.get_message_page(thread_id)
    seen = [item["content"] for item in page["messages"]]
    while page["next_cursor"]:
        page = store.get_message_page(thread_id, cursor=page["next_cursor"])
        seen = [item["content"] for item in page["messages"]] + seen

    assert seen == [f"message-{index}" for index in range(count)]
    assert page["total_count"] == count


def test_page_filters_internal_markers_and_empty_assistants(tmp_path) -> None:
    store = StudentStore(tmp_path / "filtered.sqlite3")
    thread_id = store.create_thread(model_id="mock", support_mode="critical-thinking")
    store.add_message(thread_id, "user", "visible")
    store.add_message(thread_id, "assistant", "")
    with store._connect() as connection:
        connection.execute(
            """
            INSERT INTO messages
              (id, notebook_id, role, content, metadata_text, created_at)
            VALUES (?, ?, 'assistant', ?, ?, ?)
            """,
            (
                "marker",
                thread_id,
                "reserved",
                json.dumps({"_internal_type": "coach_idempotency"}),
                "9999-01-01T00:00:00+00:00",
            ),
        )
    page = store.get_message_page(thread_id)
    assert [item["content"] for item in page["messages"]] == ["visible"]
    assert page["total_count"] == 1
    # The compatibility endpoint keeps its historical empty-assistant row.
    assert len(store.get_messages(thread_id)) == 2


def test_keyset_pages_are_deterministic_when_timestamps_are_equal(tmp_path) -> None:
    """The message id tie-breaker keeps equal-timestamp rows gap-free."""
    store = StudentStore(tmp_path / "equal-timestamps.sqlite3")
    thread_id = store.create_thread(model_id="mock", support_mode="critical-thinking")
    _messages(store, thread_id, 7)
    timestamp = "2026-01-01T00:00:00+00:00"
    with store._connect() as connection:
        connection.execute(
            "UPDATE messages SET created_at=? WHERE notebook_id=?",
            (timestamp, thread_id),
        )

    first = store.get_message_page(thread_id)
    second = store.get_message_page(thread_id, cursor=first["next_cursor"])
    expected = sorted(
        store.get_messages(thread_id),
        key=lambda item: (str(item.get("created_at") or ""), str(item["id"])),
    )
    assert [item["id"] for item in [*second["messages"], *first["messages"]]] == [
        item["id"] for item in expected
    ]


def test_cursor_is_bound_to_notebook_and_revision(tmp_path) -> None:
    store = StudentStore(tmp_path / "cursor.sqlite3")
    first = store.create_thread(model_id="mock", support_mode="critical-thinking")
    second = store.create_thread(model_id="mock", support_mode="critical-thinking")
    _messages(store, first, 7)
    _messages(store, second, 7)
    cursor = store.get_message_page(first)["next_cursor"]
    assert cursor
    with pytest.raises(MessagePageCursorError):
        store.get_message_page(second, cursor=cursor)

    with store._connect() as connection:
        connection.execute(
            "UPDATE notebooks SET conversation_revision=1 WHERE id=?", (first,)
        )
    with pytest.raises(MessagePageRevisionConflictError):
        store.get_message_page(first, cursor=cursor)


def test_tampered_cursor_anchor_is_rejected(tmp_path) -> None:
    store = StudentStore(tmp_path / "tampered.sqlite3")
    thread_id = store.create_thread(model_id="mock", support_mode="critical-thinking")
    _messages(store, thread_id, 7)
    page = store.get_message_page(thread_id)
    assert page["next_cursor"]
    # A valid base64 cursor with a nonexistent anchor must not silently skip.
    import base64

    raw = base64.urlsafe_b64decode(page["next_cursor"] + "==")
    payload = json.loads(raw)
    payload["message_id"] = "not-a-real-message"
    tampered = base64.urlsafe_b64encode(json.dumps(payload).encode()).decode().rstrip("=")
    with pytest.raises(MessagePageCursorError):
        store.get_message_page(thread_id, cursor=tampered)
