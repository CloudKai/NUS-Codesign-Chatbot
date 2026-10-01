"""DSQL StudentStore Deep Review OCC regressions. No live Aurora DSQL."""

from __future__ import annotations

import sqlite3
import threading
from typing import Any

from backend.persistence.dsql_student_store import DsqlStudentStore, _OCC_WRITE_METHODS
from backend.domain import StageDecision
from backend.specialists.review_orchestration import (
    COUNTER_SETTINGS_KEY,
    DEEP_REVIEW_JOB_COMPLETED,
    DEEP_REVIEW_JOB_KEY,
    DEEP_REVIEW_SNAPSHOT_KEY,
    DEEP_REVIEW_TURN_MESSAGE,
    deep_review_snapshot_payload,
    parse_deep_review_job,
)
from backend.student_store import StudentStore


class _SqliteDsqlProxy:
    """SQLite transaction facade used to exercise the pathless DSQL adapter."""

    def __init__(self, database) -> None:
        self.connection = sqlite3.connect(database, timeout=30)
        self.connection.row_factory = sqlite3.Row
        self.connection.execute("PRAGMA foreign_keys = ON")

    def execute(self, sql: str, params=None):
        """Execute shared StudentStore SQL inside this test transaction."""
        return self.connection.execute(sql, params or ())

    def __enter__(self):
        return self

    def __exit__(self, exc_type, _exc, _tb) -> None:
        if exc_type is None:
            self.connection.commit()
        else:
            self.connection.rollback()
        self.connection.close()


def _dsql_store_over_sqlite(database, owner: StudentStore) -> DsqlStudentStore:
    """Build one independent DSQL adapter instance over a shared test database."""
    dsql_store = object.__new__(DsqlStudentStore)
    dsql_store.identifier = owner.identifier
    dsql_store.owner_id = owner.owner_id
    dsql_store.path = None
    dsql_store._lock = threading.RLock()
    dsql_store._connection_factory = lambda: _SqliteDsqlProxy(database)
    dsql_store._endpoint = ""
    dsql_store._region = ""
    dsql_store._database = "postgres"
    dsql_store._user = "co_design_app"
    dsql_store._install_occ_wrappers()
    return dsql_store


def _snapshot_payload(*, reviewed_stage_id: str) -> dict[str, Any]:
    """Return one durable Deep Review snapshot for store-level completion."""
    return deep_review_snapshot_payload(
        conversation_revision=0,
        created_at="2026-08-19T00:00:00+00:00",
        synthesis="Frozen problem-identification Deep Review.",
        summary="Frozen problem-identification Deep Review.",
        strengths=["Frozen PI strength"],
        areas_to_develop=["Frozen PI area"],
        facione_scores={"analysis": 2},
        working_conclusion="Working concept.",
        readiness_candidate=False,
        readiness_evidence=[],
        missing_requirements=[],
        model_id="global.anthropic.claude-sonnet-4-6",
        reviewed_stage_id=reviewed_stage_id,
    )


def _queue_frozen_problem_review(
    dsql_store: DsqlStudentStore,
    thread_id: str,
    *,
    review_id: str,
) -> None:
    """Queue a Deep Review frozen at problem identification, then advance live stage."""
    job, created = dsql_store.start_or_get_deep_review_job(
        thread_id,
        review_id=review_id,
        reviewed_revision=0,
        stage_at_start="problem_identification",
        source_ids=[],
        message_ids=[],
    )
    assert created is True
    assert job["review_id"] == review_id
    assert job["stage_at_start"] == "problem_identification"
    assert dsql_store.mark_deep_review_job_running(thread_id, review_id) is True
    metadata = dict((dsql_store.get_thread(thread_id) or {}).get("metadata") or {})
    journey = dict(metadata.get("learning_journey") or {})
    journey["completed_stages"] = ["problem_identification"]
    metadata["learning_journey"] = journey
    dsql_store.update_thread(thread_id, metadata=metadata)
    dsql_store.select_learning_stage(thread_id, "concept_generation")


def _assert_frozen_stage_after_complete(
    owner: StudentStore,
    thread_id: str,
    *,
    review_id: str,
    revision_before: int,
    message_count_before: int,
) -> None:
    """Require live stage and frozen reviewed-stage provenance after completion."""
    thread = owner.get_thread(thread_id) or {}
    metadata = dict(thread.get("metadata") or {})
    journey = dict(metadata.get("learning_journey") or {})
    job = parse_deep_review_job(metadata.get(DEEP_REVIEW_JOB_KEY))
    snapshot = metadata.get(DEEP_REVIEW_SNAPSHOT_KEY)
    assert journey.get("current_stage") == "concept_generation"
    assert int(thread.get("conversation_revision") or 0) == revision_before
    assert job is not None
    assert job.get("review_id") == review_id
    assert job.get("status") == DEEP_REVIEW_JOB_COMPLETED
    assert isinstance(snapshot, dict)
    assert snapshot.get("reviewed_stage_id") == "problem_identification"
    assert snapshot.get("strengths") == ["Frozen PI strength"]
    assert int(metadata.get(COUNTER_SETTINGS_KEY, -1)) == 0
    messages = owner.get_messages(thread_id)
    assert len(messages) == message_count_before
    assert all(
        DEEP_REVIEW_TURN_MESSAGE not in str(item.get("content") or "")
        for item in messages
    )


def test_dsql_validated_phase2_completion_keeps_focus_and_pending_transition(
    tmp_path,
) -> None:
    """The DSQL OCC façade atomically records completion beside the pending turn."""
    database = tmp_path / "dsql-phase2-completion.sqlite3"
    owner = StudentStore(database)
    thread_id = owner.create_thread(model_id="mock", support_mode="critical-thinking")
    dsql_store = _dsql_store_over_sqlite(database, owner)
    assessment = {
        "current_stage": "problem_identification",
        "response_mode": "coaching",
        "recommendation": StageDecision.ADVANCE.value,
    }
    thread = dsql_store.get_thread(thread_id) or {}
    revision = int(thread.get("conversation_revision") or 0)

    dsql_store.persist_coach_turn(
        thread_id,
        expected_stage="problem_identification",
        expected_conversation_revision=revision,
        expected_response_detail="short",
        user_content=(
            "How might we improve road crossings for older pedestrians so that "
            "they can cross safely without rushing?"
        ),
        user_metadata={"thinking_stage": "problem_identification"},
        assistant_content="The problem is ready for the next stage.",
        assistant_message_id="phase2-advance-assistant",
        assistant_metadata={
            "thinking_stage": "problem_identification",
            "assessment": assessment,
            "proposed_stage": "concept_generation",
            "decision_status": "pending",
            "from_stage": "problem_identification",
        },
        summary_metadata={},
        validated_completion_stage="problem_identification",
    )

    persisted = owner.get_thread(thread_id) or {}
    journey = (persisted.get("metadata") or {}).get("learning_journey") or {}
    assert journey["current_stage"] == "problem_identification"
    assert journey["completed_stages"] == ["problem_identification"]
    pending = owner.get_pending_phase_transition(thread_id)
    assert pending is not None
    assert pending["from_stage"] == "problem_identification"
    assert pending["to_stage"] == "concept_generation"


def test_dsql_occ_wrappers_include_deep_review_writes() -> None:
    """Production DSQL adapter must retry Deep Review writes as whole OCC units."""
    assert issubclass(DsqlStudentStore, StudentStore)
    wrapped = set(_OCC_WRITE_METHODS)
    assert {
        "start_or_get_deep_review_job",
        "mark_deep_review_job_running",
        "complete_deep_review_job",
        "fail_deep_review_job",
    } <= wrapped


def test_dsql_complete_preserves_frozen_reviewed_stage_when_live_stage_advanced(
    tmp_path,
) -> None:
    """Completion must not restore the enqueue-time Thinking Path stage."""
    database = tmp_path / "dsql-deep-review-stage.sqlite3"
    owner = StudentStore(database)
    thread_id = owner.create_thread(model_id="mock", support_mode="critical-thinking")
    owner.add_message(thread_id, "user", "Prior design note.")
    owner.update_thread(thread_id, metadata={COUNTER_SETTINGS_KEY: 3})
    dsql_store = _dsql_store_over_sqlite(database, owner)
    review_id = "frozen-pi-review"
    _queue_frozen_problem_review(dsql_store, thread_id, review_id=review_id)

    thread_before = owner.get_thread(thread_id) or {}
    revision_before = int(thread_before.get("conversation_revision") or 0)
    message_count_before = len(owner.get_messages(thread_id))
    assert (
        dict(thread_before.get("metadata") or {})
        .get("learning_journey", {})
        .get("current_stage")
        == "concept_generation"
    )
    assert _snapshot_payload(reviewed_stage_id="problem_identification")[
        "reviewed_stage_id"
    ] == "problem_identification"

    dsql_store.complete_deep_review_job(
        thread_id,
        review_id=review_id,
        snapshot=_snapshot_payload(reviewed_stage_id="problem_identification"),
    )
    _assert_frozen_stage_after_complete(
        owner,
        thread_id,
        review_id=review_id,
        revision_before=revision_before,
        message_count_before=message_count_before,
    )


def test_dsql_complete_retries_sqlstate_40001_without_restoring_old_stage(
    tmp_path, monkeypatch
) -> None:
    """A serialization conflict retries completion once and keeps frozen provenance."""
    database = tmp_path / "dsql-deep-review-occ.sqlite3"
    owner = StudentStore(database)
    thread_id = owner.create_thread(model_id="mock", support_mode="critical-thinking")
    owner.add_message(thread_id, "user", "Prior design note.")
    owner.update_thread(thread_id, metadata={COUNTER_SETTINGS_KEY: 3})
    dsql_store = _dsql_store_over_sqlite(database, owner)
    review_id = "frozen-pi-occ-review"
    _queue_frozen_problem_review(dsql_store, thread_id, review_id=review_id)

    thread_before = owner.get_thread(thread_id) or {}
    revision_before = int(thread_before.get("conversation_revision") or 0)
    message_count_before = len(owner.get_messages(thread_id))

    class SerializationFailure(RuntimeError):
        sqlstate = "40001"

    import backend.persistence.dsql_student_store as dsql_module

    original_transaction = dsql_module.run_dsql_transaction
    attempts = 0

    def retry_with_injected_conflict(work, **_kwargs):
        def flaky_work():
            nonlocal attempts
            attempts += 1
            if attempts == 1:
                raise SerializationFailure("could not serialize access")
            return work()

        return original_transaction(flaky_work, sleep=lambda _seconds: None)

    monkeypatch.setattr(
        dsql_module, "run_dsql_transaction", retry_with_injected_conflict
    )
    dsql_store.complete_deep_review_job(
        thread_id,
        review_id=review_id,
        snapshot=_snapshot_payload(reviewed_stage_id="problem_identification"),
    )

    assert attempts == 2
    _assert_frozen_stage_after_complete(
        owner,
        thread_id,
        review_id=review_id,
        revision_before=revision_before,
        message_count_before=message_count_before,
    )
    with sqlite3.connect(database) as connection:
        row_count = connection.execute(
            "SELECT COUNT(*) FROM notebooks WHERE id=?", (thread_id,)
        ).fetchone()[0]
    assert row_count == 1
