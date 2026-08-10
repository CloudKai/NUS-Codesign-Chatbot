"""Production-safe edit/revise conversation tests (mock provider only)."""

from __future__ import annotations

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


def test_revise_latest_user_message(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "student_stage_selection", False)
    store = StudentStore(tmp_path / "revise-latest.sqlite3")
    coach = _coach(store)
    thread_id = store.create_thread(model_id="mock", support_mode="critical-thinking")
    first = coach.submit(
        CoachRequest(
            thread_id=thread_id,
            student_message="Original focus claim.",
            current_stage="focus",
            response_detail="short",
            idempotency_key="send-1",
        )
    )
    assert first.response_text
    user_id = store.get_messages(thread_id)[0]["id"]
    turn = coach.revise_and_resubmit(
        thread_id,
        user_id,
        "Edited focus claim.",
        idempotency_key="revise-1",
    )
    assert turn.response_text
    messages = store.get_messages(thread_id)
    assert len(messages) == 2
    assert messages[0]["role"] == "user"
    assert messages[0]["content"] == "Edited focus claim."
    assert messages[1]["role"] == "assistant"
    thread = store.get_thread(thread_id) or {}
    assert int(thread.get("conversation_revision") or 0) == 1


def test_revise_earlier_user_message_truncates_later_turns(tmp_path, monkeypatch):
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
    second = coach.submit(
        CoachRequest(
            thread_id=thread_id,
            student_message="Evidence message two.",
            current_stage=stage,
            response_detail="short",
            idempotency_key="a2",
        )
    )
    assert second.pending_transition is not None
    coach._progress.resolve(thread_id, second.pending_transition.id, accepted=True)
    messages_before = store.get_messages(thread_id)
    assert len(messages_before) >= 4
    second_user = next(
        message
        for message in messages_before
        if message["role"] == "user" and message["content"] == "Evidence message two."
    )
    coach.revise_and_resubmit(
        thread_id,
        second_user["id"],
        "Edited evidence message.",
        idempotency_key="revise-earlier",
    )
    messages = store.get_messages(thread_id)
    assert [message["role"] for message in messages] == [
        "user",
        "assistant",
        "user",
        "assistant",
    ]
    assert messages[2]["content"] == "Edited evidence message."
    thread = store.get_thread(thread_id) or {}
    assert (thread.get("metadata") or {}).get("thinking_stage") == "evidence"
    assert "assumptions" not in (
        (thread.get("metadata") or {}).get("learning_journey") or {}
    ).get("completed_stages", [])


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
            existing_user_message_id=user_id,
        )


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


def test_revise_clears_pending_transition(tmp_path, monkeypatch):
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


def test_revise_api_ownership_and_empty(tmp_path):
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


def test_dsql_schema_includes_conversation_revision():
    from backend.persistence.dsql_schema import DSQL_SCHEMA

    assert "conversation_revision INTEGER NOT NULL DEFAULT 0" in DSQL_SCHEMA


class _RecordingProvider:
    """Mock provider that records the last CoachRequest it assessed."""

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


def test_normal_submit_does_not_bump_conversation_revision(tmp_path, monkeypatch):
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
    assert int((store.get_thread(thread_id) or {}).get("conversation_revision") or 0) == 0


def test_revise_first_message_rewinds_stage_and_truncates_all_later(
    tmp_path, monkeypatch
):
    monkeypatch.setattr(settings, "auto_advance_stages", False)
    monkeypatch.setattr(settings, "student_stage_selection", False)
    store = StudentStore(tmp_path / "rewind-first.sqlite3")
    coach = _coach(store, auto_advance=False)
    thread_id = store.create_thread(model_id="mock", support_mode="critical-thinking")
    first = coach.submit(
        CoachRequest(
            thread_id=thread_id,
            student_message="Focus opener.",
            current_stage="focus",
            response_detail="short",
            idempotency_key="r1",
        )
    )
    assert first.pending_transition is not None
    coach._progress.resolve(thread_id, first.pending_transition.id, accepted=True)
    coach.submit(
        CoachRequest(
            thread_id=thread_id,
            student_message="Evidence follow-up.",
            current_stage="evidence",
            response_detail="short",
            idempotency_key="r2",
        )
    )
    first_user = store.get_messages(thread_id)[0]
    assert first_user["role"] == "user"
    coach.revise_and_resubmit(
        thread_id,
        first_user["id"],
        "Reworked focus opener.",
        idempotency_key="revise-root",
    )
    messages = store.get_messages(thread_id)
    assert len(messages) == 2
    assert messages[0]["content"] == "Reworked focus opener."
    thread = store.get_thread(thread_id) or {}
    assert (thread.get("metadata") or {}).get("thinking_stage") == "focus"
    journey = (thread.get("metadata") or {}).get("learning_journey") or {}
    assert journey.get("completed_stages") in ([], None)
    assert int(thread.get("conversation_revision") or 0) == 1


def test_revise_excludes_edited_user_from_provider_history(tmp_path, monkeypatch):
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
    assert last.revise_user_message_id == user_id
    assert all(
        str(message.get("id") or "") != user_id for message in last.history
    )
    assert not any(
        message.get("role") == "user"
        and message.get("content") == "Edited text for provider."
        for message in last.history
    )


def test_provider_failure_after_revise_keeps_truncated_history(tmp_path, monkeypatch):
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
    messages_before = store.get_messages(thread_id)
    assert len(messages_before) >= 4
    first_user = messages_before[0]
    failing = _coach_with_provider(store, _FailingProvider(), auto_advance=False)
    with pytest.raises(RuntimeError, match="simulated provider failure"):
        failing.revise_and_resubmit(
            thread_id,
            first_user["id"],
            "Edited after truncate.",
            idempotency_key="pf-revise-fail",
        )
    messages = store.get_messages(thread_id)
    assert len(messages) == 1
    assert messages[0]["id"] == first_user["id"]
    assert messages[0]["content"] == "Edited after truncate."
    thread = store.get_thread(thread_id) or {}
    assert int(thread.get("conversation_revision") or 0) == 1
    assert (thread.get("metadata") or {}).get("thinking_stage") == "focus"


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
    assert int((store.get_thread(thread_id) or {}).get("conversation_revision") or 0) == 1


def test_sqlite_migration_adds_conversation_revision(tmp_path):
    import sqlite3

    db_path = tmp_path / "legacy-rev.sqlite3"
    original = StudentStore(db_path)
    thread_id = original.create_thread(
        name="Legacy notebook",
        model_id="mock",
        support_mode="critical-thinking",
    )
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
        connection.commit()

    migrated = StudentStore(db_path)
    thread = migrated.get_thread(thread_id)
    assert thread is not None
    assert int(thread.get("conversation_revision") or 0) == 0
    with migrated._connect() as connection:
        columns = {
            str(row["name"])
            for row in connection.execute("PRAGMA table_info(notebooks)")
        }
    assert "conversation_revision" in columns
