from __future__ import annotations

from backend.domain import CoachRequest, StageDecision, TransitionStatus
from backend.mock_provider import DeterministicCoachProvider
from backend.repositories import SQLitePhaseTransitionRepository
from backend.student_store import StudentStore
from backend.workflow import CoachWorkflow


def _request(thread_id: str) -> CoachRequest:
    return CoachRequest(
        thread_id=thread_id,
        student_message="I want to assess whether the evidence supports this claim.",
        current_stage="focus",
        response_detail="short",
    )


def test_workflow_keeps_stage_without_creating_a_pending_transition(tmp_path):
    store = StudentStore(tmp_path / "coach.sqlite3")
    thread_id = store.create_thread(model_id="gpt-5", support_mode="critical-thinking")
    workflow = CoachWorkflow(
        DeterministicCoachProvider(StageDecision.STAY),
        SQLitePhaseTransitionRepository(store),
    )

    turn = workflow.run(_request(thread_id))

    assert turn.assessment.recommendation is StageDecision.STAY
    assert turn.pending_transition is None
    assert store.get_pending_phase_transition(thread_id) is None


def test_workflow_requires_student_confirmation_before_stage_change(tmp_path):
    store = StudentStore(tmp_path / "coach.sqlite3")
    thread_id = store.create_thread(model_id="gpt-5", support_mode="critical-thinking")
    repository = SQLitePhaseTransitionRepository(store)
    workflow = CoachWorkflow(DeterministicCoachProvider(StageDecision.ADVANCE), repository)

    turn = workflow.run(_request(thread_id))

    assert turn.pending_transition is not None
    assert turn.pending_transition.from_stage == "focus"
    assert turn.pending_transition.to_stage == "evidence"
    metadata = (store.get_thread(thread_id) or {})["metadata"]
    # resolve() alone must not advance the notebook stage.
    assert metadata.get("thinking_stage") == "focus"
    assert (metadata.get("learning_journey") or {}).get("completed_stages") == []

    resolved = repository.resolve(thread_id, turn.pending_transition.id, accepted=True)
    assert resolved.status is TransitionStatus.CONFIRMED
    metadata = (store.get_thread(thread_id) or {})["metadata"]
    assert metadata.get("thinking_stage") == "focus"
    assert (metadata.get("learning_journey") or {}).get("completed_stages") == []


def test_guided_mock_changes_its_question_then_recommends_progress(tmp_path):
    store = StudentStore(tmp_path / "guided.sqlite3")
    thread_id = store.create_thread(model_id="mock", support_mode="critical-thinking")
    workflow = CoachWorkflow(
        DeterministicCoachProvider(),
        SQLitePhaseTransitionRepository(store),
    )

    first = workflow.run(_request(thread_id))
    follow_up_request = _request(thread_id).model_copy(
        update={
            "student_message": "I need a precise safety outcome for older pedestrians.",
            "history": [
                {
                    "role": "user",
                    "content": "I want to evaluate a crossing design.",
                    "metadata": {"thinking_stage": "focus"},
                }
            ],
        }
    )
    follow_up = workflow.run(follow_up_request)

    assert first.assessment.recommendation is StageDecision.STAY
    assert "That's an interesting direction" in first.response_text
    assert "?" in first.response_text
    assert first.response_text != follow_up.response_text
    assert follow_up.assessment.recommendation is StageDecision.ADVANCE
    assert follow_up.pending_transition is not None
    assert follow_up.pending_transition.to_stage == "evidence"
    summary = workflow.inspect_thread(thread_id)
    assert summary is not None
    assert summary["steps"] == ["load_context", "assess", "recommend", "format"]
    assert summary["mode"] in {"langgraph", "sequential"}
