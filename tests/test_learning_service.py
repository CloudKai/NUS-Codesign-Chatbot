from __future__ import annotations

import pytest

from backend.domain import CoachRequest, StageDecision, TransitionStatus
from backend.learning_service import LearningProgressService
from backend.mock_provider import DeterministicCoachProvider
from backend.repositories import SQLiteNotebookRepository, SQLitePhaseTransitionRepository
from backend.settings import settings
from backend.student_store import StudentStore
from backend.workflow import CoachWorkflow


def _learning_service(store: StudentStore) -> LearningProgressService:
    return LearningProgressService(
        store,
        SQLiteNotebookRepository(store),
        SQLitePhaseTransitionRepository(store),
    )


def test_confirmed_recommendation_is_the_only_way_to_advance(tmp_path):
    store = StudentStore(tmp_path / "coach.sqlite3")
    thread_id = store.create_thread(model_id="mock", support_mode="critical-thinking")
    notebooks = SQLiteNotebookRepository(store)
    transitions = SQLitePhaseTransitionRepository(store)
    workflow = CoachWorkflow(DeterministicCoachProvider(StageDecision.ADVANCE), transitions)
    request = CoachRequest(
        thread_id=thread_id,
        student_message="My central claim is that the evidence needs evaluation.",
        current_stage="focus",
        response_detail="short",
    )
    pending = workflow.run(request).pending_transition
    assert pending is not None
    pending = transitions.create(pending)

    service = LearningProgressService(store, notebooks, transitions)
    assert service.get_pending(thread_id) == pending
    resolved = service.resolve(thread_id, pending.id, accepted=True)

    assert resolved.status is TransitionStatus.CONFIRMED
    thread = store.get_thread(thread_id) or {}
    assert thread["metadata"]["thinking_stage"] == "evidence"
    assert thread["metadata"]["learning_journey"]["completed_stages"] == ["focus"]


def test_rejected_recommendation_keeps_current_stage(tmp_path):
    store = StudentStore(tmp_path / "coach.sqlite3")
    thread_id = store.create_thread(model_id="mock", support_mode="critical-thinking")
    notebooks = SQLiteNotebookRepository(store)
    transitions = SQLitePhaseTransitionRepository(store)
    pending = CoachWorkflow(
        DeterministicCoachProvider(StageDecision.ADVANCE), transitions
    ).run(
        CoachRequest(
            thread_id=thread_id,
            student_message="I have defined a focused question.",
            current_stage="focus",
            response_detail="short",
        )
    ).pending_transition
    assert pending is not None
    pending = transitions.create(pending)

    resolved = LearningProgressService(store, notebooks, transitions).resolve(
        thread_id, pending.id, accepted=False
    )

    assert resolved.status is TransitionStatus.REJECTED
    thread = store.get_thread(thread_id) or {}
    assert (thread.get("metadata") or {}).get("thinking_stage", "focus") == "focus"
    journey = (thread.get("metadata") or {}).get("learning_journey") or {}
    assert journey.get("current_stage", "focus") == "focus"
    assert journey.get("completed_stages") in (None, [])


def test_accepted_transition_rolls_back_when_journey_write_fails(tmp_path, monkeypatch):
    import backend.student_store as student_store_module

    store = StudentStore(tmp_path / "atomic.sqlite3")
    thread_id = store.create_thread(model_id="mock", support_mode="critical-thinking")
    notebooks = SQLiteNotebookRepository(store)
    transitions = SQLitePhaseTransitionRepository(store)
    pending = CoachWorkflow(
        DeterministicCoachProvider(StageDecision.ADVANCE), transitions
    ).run(
        CoachRequest(
            thread_id=thread_id,
            student_message="I have defined a focused question.",
            current_stage="focus",
            response_detail="short",
        )
    ).pending_transition
    assert pending is not None
    pending = transitions.create(pending)

    real_dump = student_store_module._dump

    def flaky_dump(value):
        # Progress blob written on accepted transition contains completed_stages.
        if isinstance(value, dict) and "completed_stages" in value:
            raise RuntimeError("simulated journey write failure")
        return real_dump(value)

    monkeypatch.setattr(student_store_module, "_dump", flaky_dump)

    service = LearningProgressService(store, notebooks, transitions)
    try:
        service.resolve(thread_id, pending.id, accepted=True)
        raised = False
    except RuntimeError:
        raised = True

    assert raised
    assert transitions.get_pending(thread_id) is not None
    thread = store.get_thread(thread_id) or {}
    journey = (thread.get("metadata") or {}).get("learning_journey") or {}
    assert journey.get("current_stage", "focus") == "focus"


def test_select_stage_requires_flag(tmp_path, monkeypatch):
    store = StudentStore(tmp_path / "select-off.sqlite3")
    thread_id = store.create_thread(model_id="mock", support_mode="critical-thinking")
    monkeypatch.setattr(settings, "student_stage_selection", False)
    service = _learning_service(store)

    with pytest.raises(ValueError, match="not enabled"):
        service.select_stage(thread_id, "evidence")


def test_select_stage_rejects_unknown_stage(tmp_path, monkeypatch):
    store = StudentStore(tmp_path / "select-bad.sqlite3")
    thread_id = store.create_thread(model_id="mock", support_mode="critical-thinking")
    monkeypatch.setattr(settings, "student_stage_selection", True)
    service = _learning_service(store)

    with pytest.raises(ValueError, match="Unknown thinking stage"):
        service.select_stage(thread_id, "not-a-stage")


def test_select_stage_updates_journey_without_completing_skipped(tmp_path, monkeypatch):
    store = StudentStore(tmp_path / "select-ok.sqlite3")
    thread_id = store.create_thread(model_id="mock", support_mode="critical-thinking")
    monkeypatch.setattr(settings, "student_stage_selection", True)
    service = _learning_service(store)

    metadata = service.select_stage(thread_id, "synthesis")

    journey = metadata["learning_journey"]
    assert journey["current_stage"] == "synthesis"
    assert journey.get("completed_stages") == []
    assert metadata["thinking_stage"] == "synthesis"
    thread = store.get_thread(thread_id) or {}
    assert thread["metadata"]["thinking_stage"] == "synthesis"


def test_select_stage_rejects_pending_transition(tmp_path, monkeypatch):
    store = StudentStore(tmp_path / "select-pending.sqlite3")
    thread_id = store.create_thread(model_id="mock", support_mode="critical-thinking")
    notebooks = SQLiteNotebookRepository(store)
    transitions = SQLitePhaseTransitionRepository(store)
    pending = CoachWorkflow(
        DeterministicCoachProvider(StageDecision.ADVANCE), transitions
    ).run(
        CoachRequest(
            thread_id=thread_id,
            student_message="I have defined a focused question.",
            current_stage="focus",
            response_detail="short",
        )
    ).pending_transition
    assert pending is not None
    transitions.create(pending)
    assert transitions.get_pending(thread_id) is not None

    monkeypatch.setattr(settings, "student_stage_selection", True)
    service = LearningProgressService(store, notebooks, transitions)
    service.select_stage(thread_id, "perspectives")

    assert transitions.get_pending(thread_id) is None
    thread = store.get_thread(thread_id) or {}
    assert thread["metadata"]["thinking_stage"] == "perspectives"
    assert thread["metadata"]["learning_journey"]["completed_stages"] == []
