"""Coach-turn message ordering must not depend on random message ids.

Message reads order by ``created_at`` and then by the message id, which is a
random UUID. When the user and assistant rows of one turn were stamped inside
the same microsecond the tiebreaker became a coin flip, so an assistant reply
could sort before the student message that produced it.
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from backend.persistence.store.contracts import utc_now_after
from backend.student_store import StudentStore


FROZEN = "2026-08-17T10:00:00.000000+00:00"


def _freeze_clock(monkeypatch, stamp: str = FROZEN) -> None:
    """Make every timestamp source return *stamp* so both rows collide.

    ``student_store`` imports ``utc_now`` by value, and ``utc_now_after``
    resolves it through the contracts module, so both references are pinned.
    """
    monkeypatch.setattr("backend.student_store.utc_now", lambda: stamp)
    monkeypatch.setattr("backend.persistence.store.contracts.utc_now", lambda: stamp)


def _persist_turn(store: StudentStore, thread_id: str) -> None:
    """Persist one minimal coaching turn."""
    store.persist_coach_turn(
        thread_id,
        expected_stage="problem_identification",
        expected_conversation_revision=0,
        user_content="What should I evaluate in this crossing design?",
        user_metadata={"thinking_stage": "problem_identification"},
        assistant_content="Which pedestrian group are you designing for?",
        assistant_metadata={"source_refs": [{"id": "s1", "label": "S1"}]},
        summary_metadata={},
    )


def test_utc_now_after_returns_a_strictly_later_stamp():
    later = utc_now_after(FROZEN)
    assert later > FROZEN

    future = "2999-01-01T00:00:00.000000+00:00"
    assert utc_now_after(future) > future

    # An unparsable anchor must not raise; it degrades to the current time.
    assert utc_now_after("not-a-timestamp")


def test_utc_now_after_compares_instants_not_raw_strings():
    """Alternate ISO spellings must not read as an earlier instant.

    A row written with a trailing ``Z``, with no timezone, or with a non-UTC
    offset still names a real instant. Comparing raw strings could rank a
    far-future stamp as earlier and skip the nudge.
    """
    for spelling in (
        "2999-01-01T00:00:00.000000Z",
        "2999-01-01T00:00:00.000000",
        "2999-01-01T08:00:00.000000+08:00",
        "2999-01-01T00:00:00Z",
    ):
        result = utc_now_after(spelling)
        assert datetime.fromisoformat(result.replace("Z", "+00:00")) > datetime(
            2998, 12, 31, 23, 59, 59, tzinfo=timezone.utc
        ), f"{spelling} was treated as an earlier instant"


def test_coach_turn_rows_stay_ordered_when_the_clock_does_not_advance(
    tmp_path: Path, monkeypatch
):
    store = StudentStore(tmp_path / "ordering.sqlite3")
    thread_id = store.create_thread(model_id="mock", support_mode="critical-thinking")
    _freeze_clock(monkeypatch)

    _persist_turn(store, thread_id)

    messages = store.get_messages(thread_id)
    roles = [message["role"] for message in messages]
    assert roles[-2:] == ["user", "assistant"]

    user_row, assistant_row = messages[-2], messages[-1]
    assert assistant_row["created_at"] > user_row["created_at"], (
        "the assistant row must sort after its user row even when the wall "
        "clock does not advance between the two inserts"
    )
    assert assistant_row["metadata"]["source_refs"][0]["label"] == "S1"


def test_filled_skeleton_sorts_after_the_user_turn_on_a_frozen_clock(
    tmp_path: Path, monkeypatch
):
    """Materializing an empty assistant skeleton must not tie with the user row.

    ``add_message`` restamps a blank assistant message when it is filled. A bare
    ``utc_now()`` could tie with the user row and hand ordering back to the
    random-UUID tiebreaker.
    """
    store = StudentStore(tmp_path / "skeleton.sqlite3")
    thread_id = store.create_thread(model_id="mock", support_mode="critical-thinking")
    _freeze_clock(monkeypatch)

    store.add_message(thread_id, role="user", content="Why this crossing design?")
    skeleton_id = store.add_message(thread_id, role="assistant", content="")
    store.add_message(
        thread_id,
        role="assistant",
        content="Which pedestrian group are you designing for?",
        message_id=skeleton_id,
    )

    messages = [m for m in store.get_messages(thread_id) if m["role"] in {"user", "assistant"}]
    assert [m["role"] for m in messages] == ["user", "assistant"]
    assert messages[-1]["created_at"] > messages[0]["created_at"]


def test_repeated_frozen_turns_keep_transcript_order(tmp_path: Path, monkeypatch):
    """Ordering must hold across turns, not just within one pair."""
    store = StudentStore(tmp_path / "ordering-multi.sqlite3")
    thread_id = store.create_thread(model_id="mock", support_mode="critical-thinking")

    for index, stamp in enumerate(
        (
            "2026-08-17T10:00:00.000000+00:00",
            "2026-08-17T10:00:01.000000+00:00",
            "2026-08-17T10:00:02.000000+00:00",
        )
    ):
        _freeze_clock(monkeypatch, stamp)
        store.persist_coach_turn(
            thread_id,
            expected_stage="problem_identification",
            expected_conversation_revision=0,
            user_content=f"Question {index}",
            user_metadata={"thinking_stage": "problem_identification"},
            assistant_content=f"Reply {index}",
            assistant_metadata={},
            summary_metadata={},
        )

    messages = [m for m in store.get_messages(thread_id) if m["role"] in {"user", "assistant"}]
    assert [m["role"] for m in messages] == ["user", "assistant"] * 3
    contents = [m["content"] for m in messages]
    assert contents == [
        "Question 0",
        "Reply 0",
        "Question 1",
        "Reply 1",
        "Question 2",
        "Reply 2",
    ]
