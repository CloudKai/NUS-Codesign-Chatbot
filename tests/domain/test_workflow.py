"""LangGraph coaching-workflow routing tests."""

from __future__ import annotations

from backend.domain import CoachRequest, StageDecision
from backend.mock_provider import DeterministicCoachProvider
from backend.providers import ProviderUnavailableError
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


def test_workflow_returns_unpersisted_recommendation_without_stage_change(tmp_path):
    store = StudentStore(tmp_path / "coach.sqlite3")
    thread_id = store.create_thread(model_id="gpt-5", support_mode="critical-thinking")
    repository = SQLitePhaseTransitionRepository(store)
    workflow = CoachWorkflow(DeterministicCoachProvider(StageDecision.ADVANCE), repository)

    turn = workflow.run(_request(thread_id))

    assert turn.pending_transition is not None
    assert turn.pending_transition.from_stage == "focus"
    assert turn.pending_transition.to_stage == "evidence"
    assert store.get_pending_phase_transition(thread_id) is None
    metadata = (store.get_thread(thread_id) or {})["metadata"]
    assert metadata.get("thinking_stage") == "focus"
    assert (metadata.get("learning_journey") or {}).get("completed_stages") == []


def test_quick_mock_changes_its_question_then_recommends_progress(tmp_path):
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
                },
                {
                    "role": "assistant",
                    "content": first.response_text,
                    "metadata": {
                        "coaching_profile": "quick",
                        "assessment": first.assessment.model_dump(mode="json"),
                    },
                },
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


def test_provider_failure_is_not_replayed_by_sequential_fallback(tmp_path):
    """A graph/provider runtime error must never trigger a second paid call."""

    class FailingProvider:
        def __init__(self) -> None:
            self.calls = 0

        def assess(self, request: CoachRequest):
            self.calls += 1
            raise ProviderUnavailableError("provider unavailable")

    store = StudentStore(tmp_path / "provider-failure.sqlite3")
    thread_id = store.create_thread(model_id="mock", support_mode="critical-thinking")
    provider = FailingProvider()
    workflow = CoachWorkflow(provider, SQLitePhaseTransitionRepository(store))

    try:
        workflow.run(_request(thread_id))
    except ProviderUnavailableError:
        pass
    else:  # pragma: no cover - explicit failure message is clearer than pytest.raises.
        raise AssertionError("provider failure should propagate")

    assert provider.calls == 1


def test_conclusion_normalizes_advance_to_stay_without_transition(tmp_path):
    """Conclusion is terminal even when a provider returns ADVANCE."""
    store = StudentStore(tmp_path / "terminal.sqlite3")
    thread_id = store.create_thread(model_id="mock", support_mode="critical-thinking")
    workflow = CoachWorkflow(
        DeterministicCoachProvider(StageDecision.ADVANCE),
        SQLitePhaseTransitionRepository(store),
    )
    request = _request(thread_id).model_copy(update={"current_stage": "conclusion"})

    turn = workflow.run(request)

    assert turn.assessment.recommendation is StageDecision.STAY
    assert turn.pending_transition is None
    assert store.get_pending_phase_transition(thread_id) is None
