from __future__ import annotations

from backend.domain import CoachRequest, StageDecision, TransitionStatus
from backend.learning_service import LearningProgressService
from backend.mock_provider import DeterministicCoachProvider
from backend.repositories import SQLiteNotebookRepository, SQLitePhaseTransitionRepository
from backend.student_store import StudentStore
from backend.workflow import CoachWorkflow


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

    service = LearningProgressService(store, notebooks, transitions)
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

    resolved = LearningProgressService(store, notebooks, transitions).resolve(
        thread_id, pending.id, accepted=False
    )

    assert resolved.status is TransitionStatus.REJECTED
    assert "thinking_stage" not in (store.get_thread(thread_id) or {})["metadata"]
