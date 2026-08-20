from __future__ import annotations

from backend.domain import CoachRequest, StageDecision
from backend.mock_provider import DeterministicCoachProvider
from backend.providers import ProviderUnavailableError
from backend.repositories import SQLitePhaseTransitionRepository
from backend.student_store import StudentStore
from backend.workflow import CoachWorkflow


_PI_HMW = (
    "How might we improve road crossings for older pedestrians so that they "
    "can cross safely without rushing?"
)


def _request(thread_id: str, message: str | None = None) -> CoachRequest:
    return CoachRequest(
        thread_id=thread_id,
        student_message=message or _PI_HMW,
        current_stage="problem_identification",
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
    assert turn.pending_transition.from_stage == "problem_identification"
    assert turn.pending_transition.to_stage == "concept_generation"
    assert store.get_pending_phase_transition(thread_id) is None
    metadata = (store.get_thread(thread_id) or {})["metadata"]
    assert metadata.get("thinking_stage") == "problem_identification"
    assert (metadata.get("learning_journey") or {}).get("completed_stages") == []


def test_guided_mock_changes_its_question_then_recommends_progress(tmp_path):
    store = StudentStore(tmp_path / "guided.sqlite3")
    thread_id = store.create_thread(model_id="mock", support_mode="critical-thinking")
    workflow = CoachWorkflow(
        DeterministicCoachProvider(),
        SQLitePhaseTransitionRepository(store),
    )

    first = workflow.run(
        _request(thread_id, "I want to assess whether the evidence supports this claim.")
    )
    follow_up_request = _request(thread_id).model_copy(
        update={
            "student_message": _PI_HMW,
            "history": [
                {
                    "role": "assistant",
                    "content": "Clarify the safety outcome.",
                    "metadata": {
                        "thinking_stage": "problem_identification",
                        "coaching_profile": "quick",
                        "assessment": {"current_stage": "problem_identification"},
                    },
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
    assert follow_up.pending_transition.to_stage == "concept_generation"
    summary = workflow.inspect_thread(thread_id)
    assert summary is not None
    assert summary["steps"] == ["load_context", "assess", "recommend", "format"]
    assert summary["mode"] in {"langgraph", "sequential"}


def test_guided_mock_separates_quick_and_strict_assessment_history(tmp_path):
    store = StudentStore(tmp_path / "guided-profiles.sqlite3")
    provider = DeterministicCoachProvider()
    common = {
        "thread_id": store.create_thread(
            model_id="mock", support_mode="critical-thinking"
        ),
        "student_message": "I specified the design problem.",
        "current_stage": "problem_identification",
    }
    quick_assessment = {
        "role": "assistant",
        "content": "Quick feedback",
        "metadata": {
            "thinking_stage": "problem_identification",
            "coaching_profile": "quick",
            "assessment": {"current_stage": "problem_identification"},
        },
    }
    strict_assessment = {
        "role": "assistant",
        "content": "Strict feedback",
        "metadata": {
            "thinking_stage": "problem_identification",
            "coaching_profile": "strict",
            "assessment": {"current_stage": "problem_identification"},
        },
    }
    legacy_assessment = {
        "role": "assistant",
        "content": "Legacy feedback",
        "metadata": {
            "thinking_stage": "problem_identification",
            "assessment": {"current_stage": "problem_identification"},
        },
    }

    quick = provider.assess(
        CoachRequest(**common, response_detail="short", history=[quick_assessment])
    )
    strict_with_quick_history = provider.assess(
        CoachRequest(
            **common,
            response_detail="long",
            history=[quick_assessment, quick_assessment],
        )
    )
    strict_with_eligible_history = provider.assess(
        CoachRequest(
            **common,
            response_detail="long",
            history=[strict_assessment, legacy_assessment],
        )
    )

    assert quick.assessment.recommendation is StageDecision.ADVANCE
    assert strict_with_quick_history.assessment.recommendation is StageDecision.STAY
    assert strict_with_eligible_history.assessment.recommendation is StageDecision.ADVANCE


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


def test_reflection_normalizes_advance_to_stay_without_transition(tmp_path):
    """Reflection is terminal even when a provider returns ADVANCE."""
    store = StudentStore(tmp_path / "terminal.sqlite3")
    thread_id = store.create_thread(model_id="mock", support_mode="critical-thinking")
    workflow = CoachWorkflow(
        DeterministicCoachProvider(StageDecision.ADVANCE),
        SQLitePhaseTransitionRepository(store),
    )
    request = _request(thread_id).model_copy(update={"current_stage": "reflection"})

    turn = workflow.run(request)

    assert turn.assessment.recommendation is StageDecision.STAY
    assert turn.pending_transition is None
    assert store.get_pending_phase_transition(thread_id) is None
