"""Focused transaction and race tests for completed coaching turns."""

from __future__ import annotations

import sqlite3
import threading
from collections.abc import Callable

import pytest

from backend.application import CoachApplicationService
from backend.domain import CoachRequest, StageDecision
from backend.learning_service import LearningProgressService
from backend.mock_provider import DeterministicCoachProvider
from backend.persistence.dsql_student_store import DsqlStudentStore, _OCC_WRITE_METHODS
from backend.repositories import (
    SQLiteNotebookRepository,
    SQLitePhaseTransitionRepository,
)
from backend.settings import settings
from backend.student_store import (
    RESEARCH_WORKFLOW_CONTRACT_KEY,
    CoachingStyleConflictError,
    StudentStore,
)
from backend.workflow import CoachWorkflow


class _CallbackProvider:
    """Deterministic provider that mutates test state during an in-flight turn."""

    provider_id = "mock"

    def __init__(self, callback: Callable[[], None]) -> None:
        self._callback = callback
        self.calls = 0

    def assess(self, request: CoachRequest):
        self.calls += 1
        self._callback()
        return DeterministicCoachProvider(StageDecision.ADVANCE).assess(request)


class _SqliteDsqlProxy:
    """SQLite transaction facade for shared StudentStore SQL in DSQL tests."""

    def __init__(self, database) -> None:
        self.connection = sqlite3.connect(database, timeout=30)
        self.connection.row_factory = sqlite3.Row
        self.connection.execute("PRAGMA foreign_keys = ON")

    def execute(self, sql: str, params=None):
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
    """Build a pathless DSQL adapter over the additive SQLite test schema."""
    store = object.__new__(DsqlStudentStore)
    store.identifier = owner.identifier
    store.owner_id = owner.owner_id
    store.path = None
    store._lock = threading.RLock()
    store._connection_factory = lambda: _SqliteDsqlProxy(database)
    store._endpoint = ""
    store._region = ""
    store._database = "postgres"
    store._user = "co_design_app"
    store._install_occ_wrappers()
    return store


def _service(
    store: StudentStore,
    *,
    provider=None,
    auto_advance: bool = True,
) -> tuple[CoachApplicationService, LearningProgressService]:
    notebooks = SQLiteNotebookRepository(store)
    transitions = SQLitePhaseTransitionRepository(store)
    progress = LearningProgressService(store, notebooks, transitions)
    workflow = CoachWorkflow(
        provider or DeterministicCoachProvider(StageDecision.ADVANCE),
        transitions,
    )
    return (
        CoachApplicationService(
            store,
            notebooks,
            workflow,
            progress,
            auto_advance_stages=auto_advance,
        ),
        progress,
    )


def _request(thread_id: str, *, key: str | None = None) -> CoachRequest:
    return CoachRequest(
        thread_id=thread_id,
        student_message=(
            "I defined the crossing problem, affected older pedestrians, and "
            "the safety context."
        ),
        current_stage="problem_identification",
        response_detail="short",
        idempotency_key=key,
    )


def test_style_switch_during_provider_rolls_back_stale_profile_and_research(tmp_path):
    store = StudentStore(tmp_path / "style-race.sqlite3")
    thread_id = store.create_thread(model_id="mock", support_mode="guided")
    provider = _CallbackProvider(
        lambda: store.update_thread(thread_id, metadata={"response_detail": "long"})
    )
    service, _progress = _service(store, provider=provider)

    with pytest.raises(CoachingStyleConflictError, match="style changed"):
        service.submit(_request(thread_id))

    assert provider.calls == 1
    assert store.get_messages(thread_id) == []
    assert store.list_research_observations(notebook_id=thread_id) == []
    thread = store.get_thread(thread_id) or {}
    assert thread["metadata"]["response_detail"] == "long"
    assert thread["metadata"]["thinking_stage"] == "problem_identification"


def test_direct_coach_path_rejects_unmarked_legacy_data_before_provider(tmp_path):
    store = StudentStore(tmp_path / "legacy-contract.sqlite3")
    thread_id = store.create_thread(model_id="mock", support_mode="guided")
    with store._connect() as connection:
        connection.execute(
            "DELETE FROM system_metadata WHERE key=?",
            (RESEARCH_WORKFLOW_CONTRACT_KEY,),
        )
    provider = _CallbackProvider(lambda: None)
    service, _progress = _service(store, provider=provider)

    with pytest.raises(ValueError, match="explicit reset/bootstrap"):
        service.submit(_request(thread_id))

    assert provider.calls == 0
    assert store.get_messages(thread_id) == []


def test_auto_advance_is_one_persistence_unit_and_keeps_research(tmp_path, monkeypatch):
    store = StudentStore(tmp_path / "atomic-auto.sqlite3")
    thread_id = store.create_thread(model_id="mock", support_mode="guided")
    service, progress = _service(store)

    def forbidden(*_args, **_kwargs):
        raise AssertionError("legacy post-persist transition path was called")

    monkeypatch.setattr(progress, "resolve", forbidden)
    monkeypatch.setattr(store, "apply_phase_transition_decision", forbidden)
    monkeypatch.setattr(store, "add_message", forbidden)

    turn = service.submit(_request(thread_id))

    assert turn.auto_advanced_to == "concept_generation"
    assert turn.pending_transition is None
    thread = store.get_thread(thread_id) or {}
    assert thread["metadata"]["thinking_stage"] == "concept_generation"
    assert thread["metadata"]["learning_summary"] == turn.assessment.learning_summary
    messages = store.get_messages(thread_id)
    assert [message["role"] for message in messages] == ["user", "assistant"]
    assistant = messages[1]
    assert assistant["metadata"]["decision_status"] == "confirmed"
    assert assistant["metadata"]["proposed_stage"] == "concept_generation"
    assert assistant["metadata"]["auto_advanced_to"] == "concept_generation"
    assert assistant["metadata"]["research_coding"]["phase_id"] == (
        "problem_identification"
    )
    observations = store.list_research_observations(notebook_id=thread_id)
    assert len(observations) == 1
    assert observations[0]["assistant_message_id"] == assistant["id"]


def test_auto_advance_failure_rolls_back_messages_research_and_stage(tmp_path, monkeypatch):
    store = StudentStore(tmp_path / "atomic-failure.sqlite3")
    thread_id = store.create_thread(model_id="mock", support_mode="guided")
    service, _progress = _service(store)

    def injected_failure(_metadata):
        raise RuntimeError("injected notebook summary failure")

    monkeypatch.setattr(store, "_split_notebook_metadata", injected_failure)
    with pytest.raises(RuntimeError, match="injected notebook summary"):
        service.submit(_request(thread_id))

    assert store.get_messages(thread_id) == []
    assert store.list_research_observations(notebook_id=thread_id) == []
    assert (store.get_thread(thread_id) or {})["metadata"]["thinking_stage"] == (
        "problem_identification"
    )


def test_auto_advance_uses_fresh_same_stage_journey_and_current_summary(tmp_path):
    store = StudentStore(tmp_path / "fresh-journey.sqlite3")
    thread_id = store.create_thread(model_id="mock", support_mode="guided")

    def update_fresh_metadata() -> None:
        thread = store.get_thread(thread_id) or {}
        journey = dict(thread["metadata"]["learning_journey"])
        journey["stage_notes"] = {
            "problem_identification": "Fresh concurrent notebook note",
            "reflection": "Fresh unrelated note",
        }
        store.update_thread(
            thread_id,
            metadata={"learning_journey": journey},
        )

    provider = _CallbackProvider(update_fresh_metadata)
    service, _progress = _service(store, provider=provider)
    turn = service.submit(_request(thread_id))

    journey = (store.get_thread(thread_id) or {})["metadata"]["learning_journey"]
    assert journey["current_stage"] == "concept_generation"
    # Auto-advance refreshes the completed-stage note with the assessment's
    # current contribution summary, while retaining other fresh journey state.
    assert journey["stage_notes"]["problem_identification"] == (
        turn.assessment.contribution_summary
    )
    assert journey["stage_notes"]["reflection"] == "Fresh unrelated note"
    assert journey["learning_summary"] == turn.assessment.learning_summary


def test_atomic_auto_advance_recovers_after_persist_before_complete(tmp_path, monkeypatch):
    store = StudentStore(tmp_path / "auto-recovery.sqlite3")
    thread_id = store.create_thread(model_id="mock", support_mode="guided")
    provider = _CallbackProvider(lambda: None)
    service, _progress = _service(store, provider=provider)
    request = _request(thread_id, key="atomic-auto-recovery")
    real_complete = store.complete_coach_request

    def crash_after_persist(*_args, **_kwargs):
        raise RuntimeError("simulated process stop")

    monkeypatch.setattr(store, "complete_coach_request", crash_after_persist)
    with pytest.raises(RuntimeError, match="simulated process stop"):
        service.submit(request)

    monkeypatch.setattr(store, "complete_coach_request", real_complete)
    replay = service.submit(request)

    assert replay.auto_advanced_to == "concept_generation"
    assert replay.pending_transition is None
    assert provider.calls == 1
    assert len(store.get_messages(thread_id)) == 2
    assert len(store.list_research_observations(notebook_id=thread_id)) == 1
    assert (store.get_thread(thread_id) or {})["metadata"]["thinking_stage"] == (
        "concept_generation"
    )


def test_selection_mode_and_manual_confirmation_remain_confirmation_gated(
    tmp_path, monkeypatch
):
    store = StudentStore(tmp_path / "confirmation.sqlite3")
    thread_id = store.create_thread(model_id="mock", support_mode="guided")
    service, progress = _service(store, auto_advance=True)
    monkeypatch.setattr(settings, "student_stage_selection", True)

    turn = service.submit(_request(thread_id))

    assert turn.auto_advanced_to is None
    assert turn.pending_transition is not None
    assert (store.get_thread(thread_id) or {})["metadata"]["thinking_stage"] == (
        "problem_identification"
    )
    progress.resolve(thread_id, turn.pending_transition.id, accepted=True)
    assert (store.get_thread(thread_id) or {})["metadata"]["thinking_stage"] == (
        "concept_generation"
    )


def test_atomic_coach_write_remains_in_dsql_occ_inventory():
    assert "persist_coach_turn" in _OCC_WRITE_METHODS


def test_atomic_auto_advance_runs_through_dsql_occ_adapter(tmp_path):
    database = tmp_path / "dsql-atomic-auto.sqlite3"
    owner = StudentStore(database)
    thread_id = owner.create_thread(model_id="mock", support_mode="guided")
    dsql_store = _dsql_store_over_sqlite(database, owner)
    service, _progress = _service(dsql_store)

    turn = service.submit(_request(thread_id))

    assert turn.auto_advanced_to == "concept_generation"
    assert (owner.get_thread(thread_id) or {})["metadata"]["thinking_stage"] == (
        "concept_generation"
    )
    assert len(owner.get_messages(thread_id)) == 2
    assert len(owner.list_research_observations(notebook_id=thread_id)) == 1
