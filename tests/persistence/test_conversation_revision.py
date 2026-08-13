"""Persistence tests for append-only conversation revisions (mock only).

Required behavior under test (production may implement concurrently):

- Message rows carry ``conversation_revision`` (default 0), nullable
  ``previous_message_id``, and nullable ``superseded_at_revision``. No separate
  message-identity columns.
- Normal sends stamp the notebook's current revision and do not bump it.
- Revise bumps ``R -> R+1``, supersedes the edited user and all currently active
  later messages (rows/content retained), inserts a replacement user at the new
  revision whose ``previous_message_id`` is the immediate old user, then an
  assistant at the new revision. Surviving active prefix remains visible.
- ``get_messages`` uses active predicate
  ``conversation_revision <= R AND (superseded IS NULL OR superseded > R)``.
  ``get_messages_at_revision`` reconstructs earlier revisions with ownership
  checks.
- Sequential edits establish immediate lineage and retain all historical rows;
  editing a replacement supersedes the current branch only.
- CAS ``rowcount == 0`` on revise/persist notebook updates raises
  ``ConversationRevisionConflictError`` and rolls back.
- Completed-idempotency replay and persist-before-complete retry recover without
  a second bump, re-supersede, duplicate provider call, or duplicate history.
- ``assessment_text`` is set only on assessed coach responses; welcome/user rows
  keep expected columns NULL. Sources ownership/refs are unchanged by revise.
"""

from __future__ import annotations

import sqlite3
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from typing import Any

import pytest
from fastapi.testclient import TestClient

from backend.api import create_app
from backend.application import CoachApplicationService
from backend.domain import CoachRequest, StageDecision
from backend.learning_service import LearningProgressService
from backend.mock_provider import DeterministicCoachProvider
from backend.repositories import SQLiteNotebookRepository, SQLitePhaseTransitionRepository
from backend.settings import settings
from backend.student_store import (
    CoachIdempotencyConflictError,
    ConversationRevisionConflictError,
    StudentStore,
)
from backend.workflow import CoachWorkflow

_FORBIDDEN_IDENTITY_COLUMNS = frozenset(
    {
        "message_identity",
        "identity_id",
        "logical_id",
        "canonical_id",
        "edit_of",
        "original_message_id",
    }
)


def _coach(store: StudentStore, *, auto_advance: bool = False) -> CoachApplicationService:
    notebooks = SQLiteNotebookRepository(store)
    transitions = SQLitePhaseTransitionRepository(store)
    workflow = CoachWorkflow(
        DeterministicCoachProvider(StageDecision.ADVANCE),
        transitions,
    )
    learning = LearningProgressService(store, notebooks, transitions)
    return CoachApplicationService(
        store,
        notebooks,
        workflow,
        learning,
        auto_advance_stages=auto_advance,
    )


def _coach_with_provider(
    store: StudentStore,
    provider,
    *,
    auto_advance: bool = False,
) -> CoachApplicationService:
    notebooks = SQLiteNotebookRepository(store)
    transitions = SQLitePhaseTransitionRepository(store)
    workflow = CoachWorkflow(provider, transitions)
    learning = LearningProgressService(store, notebooks, transitions)
    return CoachApplicationService(
        store,
        notebooks,
        workflow,
        learning,
        auto_advance_stages=auto_advance,
    )


class _RecordingProvider:
    """Mock provider that records each CoachRequest it assesses."""

    def __init__(self, decision: StageDecision = StageDecision.STAY) -> None:
        self.decision = decision
        self.requests: list[CoachRequest] = []

    def assess(self, request: CoachRequest):
        self.requests.append(request)
        return DeterministicCoachProvider(self.decision).assess(request)


class _FailingProvider:
    """Mock provider that always raises after the revise transaction commits."""

    def assess(self, request: CoachRequest):
        raise RuntimeError("simulated provider failure")


def _message_columns(store: StudentStore) -> set[str]:
    with store._connect() as connection:
        return {
            str(row["name"])
            for row in connection.execute("PRAGMA table_info(messages)")
        }


def _raw_messages(store: StudentStore, thread_id: str) -> list[dict[str, Any]]:
    """Return all durable message rows (including superseded), chronologically."""
    with store._connect() as connection:
        rows = connection.execute(
            """
            SELECT id, role, content, assessment_text, cited_source_ids_text,
                   conversation_revision, previous_message_id, superseded_at_revision,
                   metadata_text, created_at
            FROM messages
            WHERE notebook_id=?
            ORDER BY created_at ASC, id ASC
            """,
            (thread_id,),
        ).fetchall()
    return [
        {
            "id": str(row["id"]),
            "role": str(row["role"]),
            "content": str(row["content"] or ""),
            "assessment_text": row["assessment_text"],
            "cited_source_ids_text": row["cited_source_ids_text"],
            "conversation_revision": int(row["conversation_revision"] or 0),
            "previous_message_id": (
                str(row["previous_message_id"])
                if row["previous_message_id"] is not None
                else None
            ),
            "superseded_at_revision": (
                int(row["superseded_at_revision"])
                if row["superseded_at_revision"] is not None
                else None
            ),
            "metadata_text": row["metadata_text"],
            "created_at": row["created_at"],
        }
        for row in rows
    ]


def _visible_contents(messages: list[dict[str, Any]]) -> list[str]:
    return [str(message.get("content") or "") for message in messages]


def _user_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [row for row in rows if row["role"] == "user"]


def test_message_schema_has_revision_lineage_columns_not_identity(tmp_path):
    store = StudentStore(tmp_path / "schema-cols.sqlite3")
    columns = _message_columns(store)
    assert "conversation_revision" in columns
    assert "previous_message_id" in columns
    assert "superseded_at_revision" in columns
    assert not (_FORBIDDEN_IDENTITY_COLUMNS & columns)


def test_dsql_schema_includes_message_revision_columns():
    from backend.persistence.dsql_schema import DSQL_SCHEMA

    assert "conversation_revision INTEGER NOT NULL DEFAULT 0" in DSQL_SCHEMA
    messages_block = DSQL_SCHEMA.split("CREATE TABLE IF NOT EXISTS messages")[1].split(
        "CREATE TABLE IF NOT EXISTS sources"
    )[0]
    assert "conversation_revision INTEGER NOT NULL DEFAULT 0" in messages_block
    assert "previous_message_id TEXT" in messages_block
    assert "superseded_at_revision INTEGER" in messages_block
    for name in _FORBIDDEN_IDENTITY_COLUMNS:
        assert name not in messages_block
    # Ownership stays messages -> notebooks -> users (no denormalized user cols).
    for forbidden in ("user_id", "cognito_sub", "email"):
        assert forbidden not in messages_block


def test_normal_submit_does_not_bump_revision_and_stamps_messages(
    tmp_path, monkeypatch
):
    monkeypatch.setattr(settings, "student_stage_selection", False)
    store = StudentStore(tmp_path / "no-bump.sqlite3")
    coach = _coach(store)
    thread_id = store.create_thread(model_id="mock", support_mode="critical-thinking")
    assert int((store.get_thread(thread_id) or {}).get("conversation_revision") or 0) == 0
    coach.submit(
        CoachRequest(
            thread_id=thread_id,
            student_message="First turn.",
            current_stage="focus",
            response_detail="short",
            idempotency_key="send-only",
        )
    )
    thread = store.get_thread(thread_id) or {}
    assert int(thread.get("conversation_revision") or 0) == 0
    rows = _raw_messages(store, thread_id)
    visible = [row for row in rows if row["role"] in {"user", "assistant"}]
    assert visible
    assert all(row["conversation_revision"] == 0 for row in visible)
    assert all(row["superseded_at_revision"] is None for row in visible)
    assert all(row["previous_message_id"] is None for row in visible)


def test_assessment_text_populated_on_assistant_null_on_user(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "student_stage_selection", False)
    store = StudentStore(tmp_path / "assessment-cols.sqlite3")
    coach = _coach(store)
    thread_id = store.create_thread(model_id="mock", support_mode="critical-thinking")
    store.add_message(
        thread_id,
        "assistant",
        "Welcome to your critical-thinking coach.",
        metadata={"kind": "coach_welcome", "workflow": "welcome"},
    )
    coach.submit(
        CoachRequest(
            thread_id=thread_id,
            student_message="Assess me.",
            current_stage="focus",
            response_detail="short",
            idempotency_key="assess-1",
        )
    )
    rows = [
        row
        for row in _raw_messages(store, thread_id)
        if '"_internal_type": "coach_idempotency"' not in (row["metadata_text"] or "")
    ]
    welcome = next(row for row in rows if "Welcome" in row["content"])
    users = [row for row in rows if row["role"] == "user"]
    # Pending-transition skeletons may be empty; assessed coach replies have body.
    assessed_assistants = [
        row
        for row in rows
        if row["role"] == "assistant"
        and str(row["content"] or "").strip()
        and "Welcome" not in row["content"]
    ]
    assert welcome["assessment_text"] is None
    assert users
    assert assessed_assistants
    assert all(row["assessment_text"] is None for row in users)
    assert all(
        row["assessment_text"] is not None and str(row["assessment_text"]).strip()
        for row in assessed_assistants
    )


def test_revise_latest_supersedes_retains_and_links_previous_message_id(
    tmp_path, monkeypatch
):
    monkeypatch.setattr(settings, "student_stage_selection", False)
    store = StudentStore(tmp_path / "revise-latest.sqlite3")
    coach = _coach(store)
    thread_id = store.create_thread(model_id="mock", support_mode="critical-thinking")
    coach.submit(
        CoachRequest(
            thread_id=thread_id,
            student_message="Original focus claim.",
            current_stage="focus",
            response_detail="short",
            idempotency_key="send-1",
        )
    )
    before = _raw_messages(store, thread_id)
    original_user = next(row for row in before if row["role"] == "user")
    # Skip empty pending-transition skeletons inserted before the user turn.
    original_assistant = next(
        row
        for row in before
        if row["role"] == "assistant"
        and row["content"].strip()
        and (
            row["created_at"] > original_user["created_at"]
            or (
                row["created_at"] == original_user["created_at"]
                and row["id"] > original_user["id"]
            )
        )
    )
    original_user_content = original_user["content"]
    original_assistant_content = original_assistant["content"]

    turn = coach.revise_and_resubmit(
        thread_id,
        original_user["id"],
        "Edited focus claim.",
        idempotency_key="revise-1",
    )
    assert turn.response_text

    thread = store.get_thread(thread_id) or {}
    assert int(thread.get("conversation_revision") or 0) == 1

    after = _raw_messages(store, thread_id)
    by_id = {row["id"]: row for row in after}
    assert original_user["id"] in by_id
    assert original_assistant["id"] in by_id
    assert by_id[original_user["id"]]["content"] == original_user_content
    assert by_id[original_assistant["id"]]["content"] == original_assistant_content
    assert by_id[original_user["id"]]["superseded_at_revision"] == 1
    assert by_id[original_assistant["id"]]["superseded_at_revision"] == 1

    active = store.get_messages(thread_id)
    assert [message["role"] for message in active] == ["user", "assistant"]
    assert active[0]["content"] == "Edited focus claim."
    assert active[0]["id"] != original_user["id"]
    replacement = by_id[active[0]["id"]]
    assert replacement["conversation_revision"] == 1
    assert replacement["previous_message_id"] == original_user["id"]
    assert replacement["superseded_at_revision"] is None
    new_assistant = by_id[active[1]["id"]]
    assert new_assistant["conversation_revision"] == 1
    assert new_assistant["superseded_at_revision"] is None


def test_revise_earlier_keeps_downstream_physically_excludes_from_active(
    tmp_path, monkeypatch
):
    monkeypatch.setattr(settings, "auto_advance_stages", False)
    monkeypatch.setattr(settings, "student_stage_selection", False)
    store = StudentStore(tmp_path / "revise-earlier.sqlite3")
    coach = _coach(store, auto_advance=False)
    thread_id = store.create_thread(model_id="mock", support_mode="critical-thinking")
    first = coach.submit(
        CoachRequest(
            thread_id=thread_id,
            student_message="Focus message one.",
            current_stage="focus",
            response_detail="short",
            idempotency_key="a1",
        )
    )
    assert first.pending_transition is not None
    coach._progress.resolve(thread_id, first.pending_transition.id, accepted=True)
    thread = store.get_thread(thread_id) or {}
    stage = (thread.get("metadata") or {}).get("thinking_stage") or "evidence"
    assert stage == "evidence"
    coach.submit(
        CoachRequest(
            thread_id=thread_id,
            student_message="Evidence message two.",
            current_stage=stage,
            response_detail="short",
            idempotency_key="a2",
        )
    )
    before_active = store.get_messages(thread_id)
    assert len(before_active) >= 4
    conversation_01 = list(before_active)
    first_user = before_active[0]
    second_user = next(
        message
        for message in before_active
        if message["role"] == "user" and message["content"] == "Evidence message two."
    )
    second_assistant = next(
        message
        for message in before_active
        if message["role"] == "assistant"
        and before_active.index(message) > before_active.index(second_user)
    )

    coach.revise_and_resubmit(
        thread_id,
        first_user["id"],
        "Reworked focus opener.",
        idempotency_key="revise-earlier-root",
    )

    # Downstream rows remain on disk with original content.
    rows = _raw_messages(store, thread_id)
    by_id = {row["id"]: row for row in rows}
    assert by_id[second_user["id"]]["content"] == "Evidence message two."
    assert by_id[second_assistant["id"]]["content"] == second_assistant["content"]
    assert by_id[second_user["id"]]["superseded_at_revision"] == 1
    assert by_id[second_assistant["id"]]["superseded_at_revision"] == 1
    assert by_id[first_user["id"]]["superseded_at_revision"] == 1
    assert len(rows) > 2

    active = store.get_messages(thread_id)
    assert [message["role"] for message in active] == ["user", "assistant"]
    assert active[0]["content"] == "Reworked focus opener."
    assert active[0]["id"] != first_user["id"]
    assert all(message["id"] != second_user["id"] for message in active)
    assert all(message["id"] != second_assistant["id"] for message in active)

    # Conversation 01 (revision 0) reconstructs the pre-edit active branch.
    at_zero = store.get_messages_at_revision(thread_id, 0)
    assert [message["id"] for message in at_zero] == [
        message["id"] for message in conversation_01
    ]
    assert _visible_contents(at_zero) == _visible_contents(conversation_01)

    thread = store.get_thread(thread_id) or {}
    assert int(thread.get("conversation_revision") or 0) == 1
    assert (thread.get("metadata") or {}).get("thinking_stage") == "focus"
    assert "evidence" not in (
        (thread.get("metadata") or {}).get("learning_journey") or {}
    ).get("completed_stages", [])


def test_get_messages_active_only_and_at_revision_ownership(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "student_stage_selection", False)
    store = StudentStore(tmp_path / "active-pred.sqlite3")
    other = StudentStore(tmp_path / "active-pred-other.sqlite3", identifier="other")
    coach = _coach(store)
    thread_id = store.create_thread(model_id="mock", support_mode="critical-thinking")
    coach.submit(
        CoachRequest(
            thread_id=thread_id,
            student_message="Original",
            current_stage="focus",
            response_detail="short",
            idempotency_key="ap-1",
        )
    )
    original_user_id = store.get_messages(thread_id)[0]["id"]
    coach.revise_and_resubmit(
        thread_id,
        original_user_id,
        "Edited",
        idempotency_key="ap-revise",
    )
    assert int((store.get_thread(thread_id) or {}).get("conversation_revision") or 0) == 1

    active = store.get_messages(thread_id)
    assert active[0]["content"] == "Edited"
    assert all(message["id"] != original_user_id for message in active)

    at_zero = store.get_messages_at_revision(thread_id, 0)
    zero_by_id = {message["id"]: message for message in at_zero}
    assert original_user_id in zero_by_id
    assert zero_by_id[original_user_id]["content"] == "Original"
    assert all(message["content"] != "Edited" for message in at_zero)

    at_one = store.get_messages_at_revision(thread_id, 1)
    assert _visible_contents(at_one) == _visible_contents(active)

    assert other.get_messages(thread_id) == []
    # Owner isolation: foreign notebooks are invisible (empty) or rejected.
    try:
        foreign_history = other.get_messages_at_revision(thread_id, 0)
    except ValueError as error:
        assert "not found" in str(error).lower()
    else:
        assert foreign_history == []


def test_double_edit_previous_message_id_lineage(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "auto_advance_stages", False)
    monkeypatch.setattr(settings, "student_stage_selection", False)
    store = StudentStore(tmp_path / "seq-edits.sqlite3")
    coach = _coach(store, auto_advance=False)
    thread_id = store.create_thread(model_id="mock", support_mode="critical-thinking")
    first = coach.submit(
        CoachRequest(
            thread_id=thread_id,
            student_message="Focus A.",
            current_stage="focus",
            response_detail="short",
            idempotency_key="seq-1",
        )
    )
    coach._progress.resolve(thread_id, first.pending_transition.id, accepted=True)
    coach.submit(
        CoachRequest(
            thread_id=thread_id,
            student_message="Evidence B.",
            current_stage="evidence",
            response_detail="short",
            idempotency_key="seq-2",
        )
    )
    messages = store.get_messages(thread_id)
    u1 = messages[0]
    u2 = next(
        message
        for message in messages
        if message["role"] == "user" and message["content"] == "Evidence B."
    )

    coach.revise_and_resubmit(
        thread_id,
        u2["id"],
        "Evidence B edited once.",
        idempotency_key="seq-rev-1",
    )
    active_after_first = store.get_messages(thread_id)
    replacement_u2 = active_after_first[2]
    assert replacement_u2["content"] == "Evidence B edited once."

    coach.revise_and_resubmit(
        thread_id,
        replacement_u2["id"],
        "Evidence B edited twice.",
        idempotency_key="seq-rev-2",
    )
    active = store.get_messages(thread_id)
    assert active[0]["id"] == u1["id"]
    assert active[2]["content"] == "Evidence B edited twice."
    final_replacement = active[2]

    rows = _raw_messages(store, thread_id)
    by_id = {row["id"]: row for row in rows}
    assert by_id[u2["id"]]["superseded_at_revision"] == 1
    assert by_id[replacement_u2["id"]]["superseded_at_revision"] == 2
    assert by_id[replacement_u2["id"]]["previous_message_id"] == u2["id"]
    assert by_id[final_replacement["id"]]["previous_message_id"] == replacement_u2["id"]
    assert by_id[final_replacement["id"]]["conversation_revision"] == 2
    assert by_id[u1["id"]]["superseded_at_revision"] is None
    assert int((store.get_thread(thread_id) or {}).get("conversation_revision") or 0) == 2
    assert len(_user_rows(rows)) >= 3


def test_stale_persist_rejected_after_revision(tmp_path):
    store = StudentStore(tmp_path / "stale-persist.sqlite3")
    thread_id = store.create_thread(model_id="mock", support_mode="critical-thinking")
    user_id = store.add_message(
        thread_id,
        "user",
        "Hello",
        metadata={"thinking_stage": "focus"},
    )
    store.add_message(thread_id, "assistant", "Reply")
    result = store.revise_conversation_from_user_message(
        thread_id,
        user_id,
        "Hello edited",
        model_id="mock",
        metadata={"thinking_stage": "focus"},
    )
    assert result.conversation_revision == 1
    replacement_id = result.edited_message_id
    assert replacement_id != user_id
    rows_before = _raw_messages(store, thread_id)
    with pytest.raises(ConversationRevisionConflictError):
        store.persist_coach_turn(
            thread_id,
            expected_stage="focus",
            expected_conversation_revision=0,
            user_content="Hello edited",
            user_metadata={"thinking_stage": "focus"},
            assistant_content="Stale reply",
            assistant_metadata={
                "assessment": {
                    "current_stage": "focus",
                    "contribution_summary": "x",
                    "stage_assessment": "x",
                    "critical_understanding_level": "Emerging",
                    "confidence": 0.5,
                    "recommendation": "stay",
                    "recommendation_rationale": "x",
                    "learning_summary": "x",
                }
            },
            summary_metadata={},
            existing_user_message_id=replacement_id,
        )
    rows_after = _raw_messages(store, thread_id)
    assert rows_after == rows_before


def test_revise_cas_conflict_rolls_back(tmp_path):
    store = StudentStore(tmp_path / "revise-cas.sqlite3")
    thread_id = store.create_thread(model_id="mock", support_mode="critical-thinking")
    user_id = store.add_message(
        thread_id,
        "user",
        "Hello",
        metadata={"thinking_stage": "focus"},
    )
    store.add_message(thread_id, "assistant", "Reply")
    barrier = __import__("threading").Barrier(2)
    outcomes: list[str] = []
    contents = ["Concurrent edit A", "Concurrent edit B"]

    def _attempt(content: str) -> None:
        try:
            barrier.wait(timeout=5)
            store.revise_conversation_from_user_message(
                thread_id,
                user_id,
                content,
                model_id="mock",
                metadata={"thinking_stage": "focus"},
            )
            outcomes.append("ok")
        except ConversationRevisionConflictError:
            outcomes.append("conflict")
        except ValueError as error:
            # Serialized loser: target is no longer active after the winner.
            if "not found" in str(error).lower():
                outcomes.append("conflict")
            else:
                outcomes.append(f"other:{type(error).__name__}")
        except Exception as error:  # noqa: BLE001 - collect race outcomes
            outcomes.append(f"other:{type(error).__name__}")

    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(_attempt, content) for content in contents]
        for future in futures:
            future.result(timeout=10)

    assert outcomes.count("ok") == 1
    assert outcomes.count("conflict") == 1
    assert all(item in {"ok", "conflict"} for item in outcomes)
    thread = store.get_thread(thread_id) or {}
    assert int(thread.get("conversation_revision") or 0) == 1
    rows = _raw_messages(store, thread_id)
    active_users = [
        row
        for row in rows
        if row["role"] == "user" and row["superseded_at_revision"] is None
    ]
    assert len(active_users) == 1
    assert active_users[0]["content"] in contents
    original = next(row for row in rows if row["id"] == user_id)
    assert original["content"] == "Hello"
    assert original["superseded_at_revision"] == 1


def test_persist_cas_rowcount_zero_raises_conflict(tmp_path):
    store = StudentStore(tmp_path / "persist-cas.sqlite3")
    thread_id = store.create_thread(model_id="mock", support_mode="critical-thinking")
    store.add_message(
        thread_id,
        "user",
        "Hello",
        metadata={"thinking_stage": "focus"},
    )
    store.add_message(thread_id, "assistant", "Reply")

    real_connect = store._connect

    class _ZeroRowcountCursor:
        def __init__(self, cursor):
            self._cursor = cursor
            self.rowcount = 0

        def __getattr__(self, name: str):
            return getattr(self._cursor, name)

    class _CasConnection:
        def __init__(self, connection):
            self._connection = connection

        def execute(self, sql, parameters=()):
            result = self._connection.execute(sql, parameters)
            normalized = " ".join(str(sql).lower().split())
            if (
                "update notebooks" in normalized
                and "where" in normalized
                and "conversation_revision" in normalized
                and "set" in normalized
            ):
                return _ZeroRowcountCursor(result)
            return result

        def __getattr__(self, name: str):
            return getattr(self._connection, name)

        def __enter__(self):
            entered = self._connection.__enter__()
            if entered is self._connection:
                return self
            return entered

        def __exit__(self, *args):
            return self._connection.__exit__(*args)

    @contextmanager
    def _wrapped_connect(*args, **kwargs):
        with real_connect(*args, **kwargs) as connection:
            yield _CasConnection(connection)

    store._connect = _wrapped_connect  # type: ignore[method-assign]
    rows_before = _raw_messages(store, thread_id)
    with pytest.raises(ConversationRevisionConflictError):
        store.persist_coach_turn(
            thread_id,
            expected_stage="focus",
            expected_conversation_revision=0,
            user_content="Hello again",
            user_metadata={"thinking_stage": "focus"},
            assistant_content="CAS miss reply",
            assistant_metadata={
                "assessment": {
                    "current_stage": "focus",
                    "contribution_summary": "x",
                    "stage_assessment": "x",
                    "critical_understanding_level": "Emerging",
                    "confidence": 0.5,
                    "recommendation": "stay",
                    "recommendation_rationale": "x",
                    "learning_summary": "x",
                }
            },
            summary_metadata={},
        )
    assert _raw_messages(store, thread_id) == rows_before


def test_old_idempotency_key_revoked_after_edit(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "student_stage_selection", False)
    store = StudentStore(tmp_path / "revoke-key.sqlite3")
    coach = _coach(store)
    thread_id = store.create_thread(model_id="mock", support_mode="critical-thinking")
    coach.submit(
        CoachRequest(
            thread_id=thread_id,
            student_message="Original",
            current_stage="focus",
            response_detail="short",
            idempotency_key="old-key",
        )
    )
    user_id = store.get_messages(thread_id)[0]["id"]
    coach.revise_and_resubmit(
        thread_id,
        user_id,
        "Edited",
        idempotency_key="new-key",
    )
    with pytest.raises(CoachIdempotencyConflictError):
        store.claim_coach_request(
            thread_id,
            idempotency_key="old-key",
            request_fingerprint="abc",
        )


def test_old_pending_transition_cannot_resolve_after_supersede(
    tmp_path, monkeypatch
):
    monkeypatch.setattr(settings, "auto_advance_stages", False)
    monkeypatch.setattr(settings, "student_stage_selection", False)
    store = StudentStore(tmp_path / "pending-clear.sqlite3")
    coach = _coach(store, auto_advance=False)
    thread_id = store.create_thread(model_id="mock", support_mode="critical-thinking")
    turn = coach.submit(
        CoachRequest(
            thread_id=thread_id,
            student_message="Ready to move on with a clear focus.",
            current_stage="focus",
            response_detail="short",
            idempotency_key="pending-1",
        )
    )
    assert turn.pending_transition is not None
    transition_id = turn.pending_transition.id
    user_id = store.get_messages(thread_id)[0]["id"]
    replacement = coach.revise_and_resubmit(
        thread_id,
        user_id,
        "Revised before advancing.",
        idempotency_key="pending-revise",
    )
    with pytest.raises(ValueError):
        store.resolve_phase_transition(thread_id, transition_id, "confirmed")
    pending = store.get_pending_phase_transition(thread_id)
    if pending is not None:
        assert pending["id"] != transition_id
        assert replacement.pending_transition is not None
        assert pending["id"] == replacement.pending_transition.id


def test_revise_api_ownership_empty_and_foreign(tmp_path):
    store = StudentStore(tmp_path / "revise-api.sqlite3")
    other = StudentStore(tmp_path / "revise-api-other.sqlite3", identifier="other")
    thread_id = store.create_thread(model_id="mock", support_mode="critical-thinking")
    user_id = store.add_message(thread_id, "user", "Mine")
    client = TestClient(create_app(store, auto_advance_stages=False))

    empty = client.post(
        f"/api/v1/threads/{thread_id}/messages/{user_id}/revise",
        json={"content": "   ", "idempotency_key": "k1"},
    )
    assert empty.status_code == 400

    missing = client.post(
        f"/api/v1/threads/{thread_id}/messages/missing/revise",
        json={"content": "Edited", "idempotency_key": "k2"},
    )
    assert missing.status_code == 404

    other_client = TestClient(create_app(other, auto_advance_stages=False))
    foreign = other_client.post(
        f"/api/v1/threads/{thread_id}/messages/{user_id}/revise",
        json={"content": "Edited", "idempotency_key": "k3"},
    )
    assert foreign.status_code == 404

    ok = client.post(
        f"/api/v1/threads/{thread_id}/messages/{user_id}/revise",
        json={"content": "Edited safely", "idempotency_key": "k4"},
    )
    assert ok.status_code == 200
    assert ok.json()["response_text"]

    listed = client.get(f"/api/v1/threads/{thread_id}/messages")
    assert listed.status_code == 200
    body = listed.json()
    assert [message["role"] for message in body] == ["user", "assistant"]
    assert body[0]["content"] == "Edited safely"
    assert body[0]["id"] != user_id
    assert all(message["id"] != user_id for message in body)


def test_provider_failure_after_revise_keeps_historical_rows(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "auto_advance_stages", False)
    monkeypatch.setattr(settings, "student_stage_selection", False)
    store = StudentStore(tmp_path / "provider-fail.sqlite3")
    ok_coach = _coach(store, auto_advance=False)
    thread_id = store.create_thread(model_id="mock", support_mode="critical-thinking")
    first = ok_coach.submit(
        CoachRequest(
            thread_id=thread_id,
            student_message="Focus A.",
            current_stage="focus",
            response_detail="short",
            idempotency_key="pf-1",
        )
    )
    ok_coach._progress.resolve(thread_id, first.pending_transition.id, accepted=True)
    ok_coach.submit(
        CoachRequest(
            thread_id=thread_id,
            student_message="Evidence B.",
            current_stage="evidence",
            response_detail="short",
            idempotency_key="pf-2",
        )
    )
    before = _raw_messages(store, thread_id)
    assert len(before) >= 4
    first_user = next(row for row in before if row["role"] == "user")
    first_user_content = first_user["content"]
    evidence_row = next(
        row for row in before if row["content"] == "Evidence B."
    )

    failing = _coach_with_provider(store, _FailingProvider(), auto_advance=False)
    with pytest.raises(RuntimeError, match="simulated provider failure"):
        failing.revise_and_resubmit(
            thread_id,
            first_user["id"],
            "Edited after supersede.",
            idempotency_key="pf-revise-fail",
        )

    rows = _raw_messages(store, thread_id)
    by_id = {row["id"]: row for row in rows}
    # Old content remains; nothing deleted.
    assert by_id[first_user["id"]]["content"] == first_user_content
    assert by_id[evidence_row["id"]]["content"] == "Evidence B."
    assert by_id[first_user["id"]]["superseded_at_revision"] == 1
    assert by_id[evidence_row["id"]]["superseded_at_revision"] == 1
    new_users = [
        row
        for row in rows
        if row["role"] == "user"
        and row["content"] == "Edited after supersede."
        and row["superseded_at_revision"] is None
    ]
    assert len(new_users) == 1
    assert new_users[0]["previous_message_id"] == first_user["id"]
    assert new_users[0]["conversation_revision"] == 1

    active = store.get_messages(thread_id)
    assert len(active) == 1
    assert active[0]["id"] == new_users[0]["id"]
    assert active[0]["content"] == "Edited after supersede."
    thread = store.get_thread(thread_id) or {}
    assert int(thread.get("conversation_revision") or 0) == 1
    assert (thread.get("metadata") or {}).get("thinking_stage") == "focus"


def test_revise_excludes_edited_and_replacement_from_provider_history(
    tmp_path, monkeypatch
):
    monkeypatch.setattr(settings, "student_stage_selection", False)
    store = StudentStore(tmp_path / "history-exclude.sqlite3")
    recorder = _RecordingProvider(StageDecision.STAY)
    coach = _coach_with_provider(store, recorder)
    thread_id = store.create_thread(model_id="mock", support_mode="critical-thinking")
    coach.submit(
        CoachRequest(
            thread_id=thread_id,
            student_message="Original text.",
            current_stage="focus",
            response_detail="short",
            idempotency_key="hist-1",
        )
    )
    user_id = store.get_messages(thread_id)[0]["id"]
    coach.revise_and_resubmit(
        thread_id,
        user_id,
        "Edited text for provider.",
        idempotency_key="hist-revise",
    )
    assert recorder.requests, "provider should have been called on revise"
    last = recorder.requests[-1]
    assert last.student_message == "Edited text for provider."
    # Append-only: request targets the replacement user id, not the superseded one.
    assert last.revise_user_message_id != user_id
    assert last.revise_user_message_id == store.get_messages(thread_id)[0]["id"]
    assert all(str(message.get("id") or "") != user_id for message in last.history)
    assert all(
        str(message.get("id") or "") != last.revise_user_message_id
        for message in last.history
    )
    assert not any(
        message.get("role") == "user"
        and message.get("content") == "Edited text for provider."
        for message in last.history
    )


def test_fingerprint_includes_conversation_revision():
    base = {
        "thread_id": "t1",
        "student_message": "same",
        "current_stage": "focus",
        "response_detail": "short",
        "idempotency_key": "k",
    }
    from backend.application import _coach_request_fingerprint

    a = _coach_request_fingerprint(
        CoachRequest(**base, conversation_revision=0)
    )
    b = _coach_request_fingerprint(
        CoachRequest(**base, conversation_revision=1)
    )
    assert a != b


def test_reject_revise_assistant_message(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "student_stage_selection", False)
    store = StudentStore(tmp_path / "assistant-revise.sqlite3")
    coach = _coach(store)
    thread_id = store.create_thread(model_id="mock", support_mode="critical-thinking")
    coach.submit(
        CoachRequest(
            thread_id=thread_id,
            student_message="Hello",
            current_stage="focus",
            response_detail="short",
            idempotency_key="as-1",
        )
    )
    assistant_id = store.get_messages(thread_id)[1]["id"]
    with pytest.raises(ValueError, match="User message not found"):
        coach.revise_and_resubmit(
            thread_id,
            assistant_id,
            "Should fail",
            idempotency_key="as-revise",
        )


def test_revise_idempotent_replay_same_new_key(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "student_stage_selection", False)
    store = StudentStore(tmp_path / "idempotent-revise.sqlite3")
    coach = _coach(store)
    thread_id = store.create_thread(model_id="mock", support_mode="critical-thinking")
    coach.submit(
        CoachRequest(
            thread_id=thread_id,
            student_message="Original",
            current_stage="focus",
            response_detail="short",
            idempotency_key="ir-1",
        )
    )
    user_id = store.get_messages(thread_id)[0]["id"]
    first = coach.revise_and_resubmit(
        thread_id,
        user_id,
        "Edited once",
        idempotency_key="ir-revise",
    )
    second = coach.revise_and_resubmit(
        thread_id,
        user_id,
        "Edited once",
        idempotency_key="ir-revise",
    )
    assert first.response_text == second.response_text
    messages = store.get_messages(thread_id)
    assert len(messages) == 2
    assert messages[0]["content"] == "Edited once"
    assert int((store.get_thread(thread_id) or {}).get("conversation_revision") or 0) == 1
    # Historical superseded row remains; no second supersede from replay.
    rows = _raw_messages(store, thread_id)
    superseded_users = [
        row
        for row in rows
        if row["role"] == "user" and row["superseded_at_revision"] is not None
    ]
    assert len(superseded_users) == 1


class _FailOnceThenRecordProvider:
    """Fail the first assess, then record subsequent requests."""

    def __init__(self) -> None:
        self.calls = 0
        self.requests: list[CoachRequest] = []

    def assess(self, request: CoachRequest):
        self.calls += 1
        if self.calls == 1:
            raise RuntimeError("simulated provider failure")
        self.requests.append(request)
        return DeterministicCoachProvider(StageDecision.STAY).assess(request)


def test_persist_before_complete_retry_recovers_without_second_bump(
    tmp_path, monkeypatch
):
    monkeypatch.setattr(settings, "student_stage_selection", False)
    store = StudentStore(tmp_path / "recover-revise.sqlite3")
    provider = _FailOnceThenRecordProvider()
    coach = _coach_with_provider(store, provider)
    thread_id = store.create_thread(model_id="mock", support_mode="critical-thinking")
    seed = _coach(store)
    seed.submit(
        CoachRequest(
            thread_id=thread_id,
            student_message="Original",
            current_stage="focus",
            response_detail="short",
            idempotency_key="recover-seed",
        )
    )
    user_id = store.get_messages(thread_id)[0]["id"]
    with pytest.raises(RuntimeError, match="simulated provider failure"):
        coach.revise_and_resubmit(
            thread_id,
            user_id,
            "Edited after fail.",
            idempotency_key="recover-revise",
        )
    assert int((store.get_thread(thread_id) or {}).get("conversation_revision") or 0) == 1
    mid_rows = _raw_messages(store, thread_id)
    assert any(
        row["id"] == user_id and row["superseded_at_revision"] == 1 for row in mid_rows
    )
    active_mid = store.get_messages(thread_id)
    assert len(active_mid) == 1
    assert active_mid[0]["content"] == "Edited after fail."
    replacement_id = active_mid[0]["id"]

    recovered = coach.revise_and_resubmit(
        thread_id,
        user_id,
        "Edited after fail.",
        idempotency_key="recover-revise",
    )
    assert recovered.response_text
    assert provider.calls == 2
    assert int((store.get_thread(thread_id) or {}).get("conversation_revision") or 0) == 1
    active = store.get_messages(thread_id)
    assert len(active) == 2
    assert active[0]["id"] == replacement_id
    assert active[0]["content"] == "Edited after fail."
    rows = _raw_messages(store, thread_id)
    by_id = {row["id"]: row for row in rows}
    assert by_id[replacement_id]["superseded_at_revision"] is None
    assert by_id[user_id]["superseded_at_revision"] == 1
    assert len([row for row in rows if row["previous_message_id"] == user_id]) == 1


def test_revise_cas_rowcount_zero_raises_conflict_and_rolls_back(tmp_path):
    store = StudentStore(tmp_path / "revise-rowcount.sqlite3")
    thread_id = store.create_thread(model_id="mock", support_mode="critical-thinking")
    user_id = store.add_message(
        thread_id,
        "user",
        "Hello",
        metadata={"thinking_stage": "focus"},
    )
    store.add_message(thread_id, "assistant", "Reply")
    rows_before = _raw_messages(store, thread_id)

    real_connect = store._connect

    class _ZeroRowcountCursor:
        def __init__(self, cursor):
            self._cursor = cursor
            self.rowcount = 0

        def __getattr__(self, name: str):
            return getattr(self._cursor, name)

    class _CasConnection:
        def __init__(self, connection):
            self._connection = connection

        def execute(self, sql, parameters=()):
            result = self._connection.execute(sql, parameters)
            normalized = " ".join(str(sql).lower().split())
            if (
                "update notebooks" in normalized
                and "where" in normalized
                and "conversation_revision" in normalized
                and "set" in normalized
            ):
                return _ZeroRowcountCursor(result)
            return result

        def __getattr__(self, name: str):
            return getattr(self._connection, name)

        def __enter__(self):
            entered = self._connection.__enter__()
            if entered is self._connection:
                return self
            return entered

        def __exit__(self, *args):
            return self._connection.__exit__(*args)

    @contextmanager
    def _wrapped_connect(*args, **kwargs):
        with real_connect(*args, **kwargs) as connection:
            yield _CasConnection(connection)

    store._connect = _wrapped_connect  # type: ignore[method-assign]
    with pytest.raises(ConversationRevisionConflictError):
        store.revise_conversation_from_user_message(
            thread_id,
            user_id,
            "Hello edited",
            model_id="mock",
            metadata={"thinking_stage": "focus"},
        )
    assert _raw_messages(store, thread_id) == rows_before
    assert int((store.get_thread(thread_id) or {}).get("conversation_revision") or 0) == 0


def test_revise_preserves_sources_ownership_and_refs(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "student_stage_selection", False)
    store = StudentStore(tmp_path / "sources-revise.sqlite3")
    coach = _coach(store)
    thread_id = store.create_thread(model_id="mock", support_mode="critical-thinking")
    source_id = store.add_source(
        thread_id,
        kind="text",
        title="Note",
        mime="text/plain",
        metadata={"inline_text": "Evidence excerpt for citations."},
    )
    coach.submit(
        CoachRequest(
            thread_id=thread_id,
            student_message="Original with sources.",
            current_stage="focus",
            response_detail="short",
            idempotency_key="src-1",
        )
    )
    sources_before = store.list_sources(thread_id)
    assert any(item["id"] == source_id for item in sources_before)
    user_id = store.get_messages(thread_id)[0]["id"]
    coach.revise_and_resubmit(
        thread_id,
        user_id,
        "Edited with sources.",
        idempotency_key="src-revise",
    )
    sources_after = store.list_sources(thread_id)
    assert [item["id"] for item in sources_after] == [
        item["id"] for item in sources_before
    ]
    assert store.get_source(thread_id, source_id) is not None
    other = StudentStore(tmp_path / "sources-revise-other.sqlite3", identifier="other")
    assert other.get_source(thread_id, source_id) is None


def test_sqlite_migration_adds_notebook_and_message_revision_columns(tmp_path):
    db_path = tmp_path / "legacy-rev.sqlite3"
    original = StudentStore(db_path)
    thread_id = original.create_thread(
        name="Legacy notebook",
        model_id="mock",
        support_mode="critical-thinking",
    )
    original.add_message(thread_id, "user", "Keep me")
    with sqlite3.connect(db_path) as connection:
        connection.execute("PRAGMA foreign_keys = OFF")
        connection.execute("BEGIN IMMEDIATE")
        connection.execute(
            """
            CREATE TABLE notebooks_legacy (
                id TEXT PRIMARY KEY,
                user_id TEXT NOT NULL,
                title TEXT,
                current_stage TEXT NOT NULL DEFAULT 'focus',
                progress_text TEXT NOT NULL DEFAULT '{}',
                settings_text TEXT NOT NULL DEFAULT '{}',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
            )
            """
        )
        connection.execute(
            """
            INSERT INTO notebooks_legacy
              (id, user_id, title, current_stage, progress_text, settings_text,
               created_at, updated_at)
            SELECT id, user_id, title, current_stage, progress_text, settings_text,
                   created_at, updated_at
            FROM notebooks
            """
        )
        connection.execute("DROP TABLE notebooks")
        connection.execute("ALTER TABLE notebooks_legacy RENAME TO notebooks")
        connection.execute(
            """
            CREATE TABLE messages_legacy (
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
            )
            """
        )
        connection.execute(
            """
            INSERT INTO messages_legacy
              (id, notebook_id, role, content, is_error, assessment_text,
               cited_source_ids_text, proposed_stage, decision_status, decision_at,
               metadata_text, created_at)
            SELECT id, notebook_id, role, content, is_error, assessment_text,
                   cited_source_ids_text, proposed_stage, decision_status, decision_at,
                   metadata_text, created_at
            FROM messages
            """
        )
        connection.execute("DROP TABLE messages")
        connection.execute("ALTER TABLE messages_legacy RENAME TO messages")
        connection.commit()

    migrated = StudentStore(db_path)
    thread = migrated.get_thread(thread_id)
    assert thread is not None
    assert int(thread.get("conversation_revision") or 0) == 0
    with migrated._connect() as connection:
        notebook_cols = {
            str(row["name"])
            for row in connection.execute("PRAGMA table_info(notebooks)")
        }
        message_cols = {
            str(row["name"])
            for row in connection.execute("PRAGMA table_info(messages)")
        }
    assert "conversation_revision" in notebook_cols
    assert "conversation_revision" in message_cols
    assert "previous_message_id" in message_cols
    assert "superseded_at_revision" in message_cols
    assert migrated.get_messages(thread_id)[0]["content"] == "Keep me"


def test_select_learning_stage_rejects_only_active_pending(tmp_path, monkeypatch):
    """Historical superseded pendings stay pending for revision reconstruction."""
    monkeypatch.setattr(settings, "auto_advance_stages", False)
    monkeypatch.setattr(settings, "student_stage_selection", True)
    store = StudentStore(tmp_path / "stage-pending.sqlite3")
    coach = _coach(store, auto_advance=False)
    thread_id = store.create_thread(model_id="mock", support_mode="critical-thinking")
    turn = coach.submit(
        CoachRequest(
            thread_id=thread_id,
            student_message="Ready to move on with a clear focus.",
            current_stage="focus",
            response_detail="short",
            idempotency_key="stage-pending-1",
        )
    )
    assert turn.pending_transition is not None
    superseded_pending_id = turn.pending_transition.id
    user_id = store.get_messages(thread_id)[0]["id"]
    coach.revise_and_resubmit(
        thread_id,
        user_id,
        "Stay in focus for now.",
        idempotency_key="stage-pending-revise",
    )
    # Simulate a historical pending left on a superseded tip (revision snapshot).
    with store._lock, store._connect() as connection:
        connection.execute(
            """
            UPDATE messages
            SET decision_status='pending', decision_at=NULL
            WHERE id=? AND notebook_id=?
            """,
            (superseded_pending_id, thread_id),
        )
        connection.commit()
    store.update_thread(
        thread_id,
        metadata={
            "thinking_stage": "evidence",
            "learning_journey": {
                "current_stage": "evidence",
                "completed_stages": ["focus"],
            },
        },
    )
    store.select_learning_stage(thread_id, "focus")
    revision = int(store.get_thread(thread_id)["conversation_revision"] or 0)
    with store._connect() as connection:
        after = connection.execute(
            """
            SELECT decision_status, superseded_at_revision
            FROM messages WHERE id=?
            """,
            (superseded_pending_id,),
        ).fetchone()
        active_pending = connection.execute(
            f"""
            SELECT id FROM messages
            WHERE notebook_id=? AND decision_status='pending'
              AND {store._active_at_revision_sql()}
            """,
            (thread_id, revision, revision),
        ).fetchall()
    assert after is not None
    assert after["superseded_at_revision"] is not None
    assert after["decision_status"] == "pending"
    assert active_pending == []
    rev0 = store.get_messages_at_revision(thread_id, 0)
    assert any(message["id"] == superseded_pending_id for message in rev0)


def test_provider_failure_retry_same_key_does_not_double_bump(tmp_path, monkeypatch):
    """Stable revise key resumes replacement without a second CAS bump."""
    monkeypatch.setattr(settings, "student_stage_selection", False)
    store = StudentStore(tmp_path / "retry-same-key.sqlite3")
    provider = _FailOnceThenRecordProvider()
    coach = _coach_with_provider(store, provider)
    thread_id = store.create_thread(model_id="mock", support_mode="critical-thinking")
    seed = _coach(store)
    seed.submit(
        CoachRequest(
            thread_id=thread_id,
            student_message="First prompt",
            current_stage="focus",
            response_detail="short",
            idempotency_key="retry-seed",
        )
    )
    user_id = store.get_messages(thread_id)[0]["id"]
    with pytest.raises(RuntimeError, match="simulated provider failure"):
        coach.revise_and_resubmit(
            thread_id,
            user_id,
            "Edited once",
            idempotency_key="stable-revise-key",
        )
    assert int(store.get_thread(thread_id)["conversation_revision"] or 0) == 1
    recovered = coach.revise_and_resubmit(
        thread_id,
        user_id,
        "Edited once",
        idempotency_key="stable-revise-key",
    )
    assert int(store.get_thread(thread_id)["conversation_revision"] or 0) == 1
    assert recovered.response_text
    active_users = [
        message
        for message in store.get_messages(thread_id)
        if message.get("role") == "user"
    ]
    assert len(active_users) == 1
    assert active_users[0]["content"] == "Edited once"
