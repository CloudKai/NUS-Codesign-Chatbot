"""Incremental Haiku Review and periodic/event Deep Review tests (no AWS)."""

from __future__ import annotations

import json
import logging
import threading
from pathlib import Path
from typing import Any

import pytest

from backend.agentcore_provider import AgentCoreCoachProvider
from backend.application import CoachApplicationService
from backend.domain import (
    CoachRequest,
    EducationalAssessment,
    FacioneDimensionScores,
    StageDecision,
)
from backend.student_journey import learning_review
from backend.learning_service import LearningProgressService
from backend.persistence.store.contracts import (
    SETTINGS_KEYS,
    ConversationRevisionConflictError,
)
from backend.repositories import (
    SQLiteNotebookRepository,
    SQLitePhaseTransitionRepository,
)
from backend.providers import ProviderUnavailableError
from backend.specialists.review_orchestration import (
    COUNTER_SETTINGS_KEY,
    bound_deep_review_interval,
    next_persisted_counter,
    resolve_deep_review_trigger,
    should_run_deep_review,
)
from backend.student_store import StudentStore
from backend.workflow import CoachWorkflow
from fake_agentcore_runtime import FakeAgentCoreRuntime

_RUNTIME_ARN = (
    "arn:aws:bedrock-agentcore:us-west-2:123456789012:runtime/test-harness"
)


def _assessment(
    *,
    recommendation: StageDecision = StageDecision.STAY,
    readiness_candidate: bool = False,
) -> EducationalAssessment:
    """Return a valid coaching assessment."""
    return EducationalAssessment(
        current_stage="problem_identification",
        contribution_summary="The student compared two design constraints.",
        stage_assessment="The contribution is usable but can be developed further.",
        critical_understanding_level="Developing",
        confidence=0.7,
        recommendation=recommendation,
        recommendation_rationale="More evidence is still needed."
        if recommendation is StageDecision.STAY
        else "The stage readiness bar is met.",
        guidance_questions=["What trade-off still needs evidence?"],
        learning_summary="The student is developing the problem.",
        working_conclusion="Elderly caregivers are scarce in Singapore.",
        evidence_identified=["Manpower shortage"],
        assumptions_identified=["Families cannot fill the gap"],
        missing_reasoning_elements=["Named stakeholders"],
        citations=[],
        facione_scores=FacioneDimensionScores(),
        readiness_candidate=readiness_candidate,
    )


def _output(
    *,
    recommendation: StageDecision = StageDecision.STAY,
    readiness_candidate: bool = False,
) -> dict[str, Any]:
    """Return a lightweight fast-chat coaching payload."""
    del readiness_candidate
    return {
        "mode": "coaching",
        "response_text": "What trade-off still needs evidence?",
        "recommendation": recommendation.value,
        "recommendation_rationale": "More evidence is still needed.",
        "citations": [],
        "needs_source_retrieval": False,
    }


def _provider(client: FakeAgentCoreRuntime) -> AgentCoreCoachProvider:
    """Build the adapter against an injected fake AgentCore client."""
    return AgentCoreCoachProvider(
        _RUNTIME_ARN,
        region="us-west-2",
        qualifier="DEFAULT",
        timeout_seconds=110.0,
        max_retries=0,
        client=client,
    )


def _request(**overrides: Any) -> CoachRequest:
    """Return one minimal coaching request."""
    payload = {
        "thread_id": "thread-demo",
        "student_message": "I want to solve the lack of elderly caregivers in Singapore.",
        "current_stage": "problem_identification",
        "response_detail": "short",
        "deep_review_interval_turns": 3,
    }
    payload.update(overrides)
    return CoachRequest(**payload)


def _decoded(call: dict[str, Any]) -> dict[str, Any]:
    """Decode one recorded InvokeAgentRuntime payload."""
    raw = call["payload"]
    if isinstance(raw, (bytes, bytearray)):
        return json.loads(bytes(raw).decode("utf-8"))
    return json.loads(str(raw))


def _phases(client: FakeAgentCoreRuntime) -> list[str]:
    """Return payload phases in invoke order."""
    return [str(_decoded(call).get("phase") or "") for call in client.calls]


def _review_modes(client: FakeAgentCoreRuntime) -> list[str]:
    """Return Review modes in invoke order."""
    modes: list[str] = []
    for call in client.calls:
        payload = _decoded(call)
        if payload.get("phase") != "review":
            continue
        mode = str(payload.get("review_mode") or "")
        context = payload.get("runtime_context")
        if isinstance(context, dict) and not mode:
            mode = str(context.get("review_mode") or "")
        modes.append(mode or "deep")
    return modes


def _service(store: StudentStore, client: FakeAgentCoreRuntime) -> CoachApplicationService:
    """Build the application path with the AgentCore adapter injected."""
    notebooks = SQLiteNotebookRepository(store)
    transitions = SQLitePhaseTransitionRepository(store)
    return CoachApplicationService(
        store,
        notebooks,
        CoachWorkflow(_provider(client), transitions),
        LearningProgressService(store, notebooks, transitions),
    )


def _counter(store: StudentStore, thread_id: str) -> int:
    """Return the persisted periodic Deep Review counter."""
    thread = store.get_thread(thread_id) or {}
    metadata = dict(thread.get("metadata") or {})
    try:
        return int(metadata.get(COUNTER_SETTINGS_KEY) or 0)
    except (TypeError, ValueError):
        return 0


def _persist_review_turn(
    store: StudentStore,
    thread_id: str,
    *,
    user_content: str,
    qualifying: bool,
    deep_succeeded: bool,
    stale_counter: int | None = None,
) -> None:
    """Persist one coach turn with Review-counter flags and optional stale metadata."""
    thread = store.get_thread(thread_id) or {}
    summary: dict[str, Any] = {}
    if stale_counter is not None:
        summary[COUNTER_SETTINGS_KEY] = stale_counter
    store.persist_coach_turn(
        thread_id,
        expected_stage="problem_identification",
        expected_conversation_revision=int(thread.get("conversation_revision") or 0),
        user_content=user_content,
        user_metadata={},
        assistant_content="What trade-off still needs evidence?",
        assistant_metadata={
            "assessment": {
                "recommendation": "stay",
                "contribution_summary": "The student named a constraint.",
                "learning_summary": "Learning",
                "working_conclusion": "Conclusion",
                "understanding_change": "Change",
                "critical_understanding_level": "developing",
                "guidance_questions": ["What next?"],
                "citations": [],
            }
        },
        summary_metadata=summary,
        review_counter_qualifying=qualifying,
        review_counter_deep_succeeded=deep_succeeded,
    )


def test_periodic_definition_is_turn_based() -> None:
    """Periodic Deep Review is N coaching turns, not elapsed time."""
    assert bound_deep_review_interval(3) == 3
    assert resolve_deep_review_trigger(
        specialist="coaching",
        current_stage="problem_identification",
        readiness_candidate=False,
        coaching_turns_since_deep_review=0,
        interval=3,
        qualifying_coaching_turn=True,
    ) is None
    assert resolve_deep_review_trigger(
        specialist="coaching",
        current_stage="problem_identification",
        readiness_candidate=False,
        coaching_turns_since_deep_review=2,
        interval=3,
        qualifying_coaching_turn=True,
    ) == "periodic"
    assert not should_run_deep_review(
        resolve_deep_review_trigger(
            specialist="qa",
            current_stage="problem_identification",
            readiness_candidate=False,
            coaching_turns_since_deep_review=2,
            interval=3,
            qualifying_coaching_turn=False,
        )
    )


def test_counter_resets_only_after_successful_deep_review() -> None:
    assert next_persisted_counter(
        current=3, qualifying_coaching_turn=True, deep_review_succeeded=True
    ) == 0
    assert next_persisted_counter(
        current=2, qualifying_coaching_turn=True, deep_review_succeeded=False
    ) == 3
    assert next_persisted_counter(
        current=2, qualifying_coaching_turn=False, deep_review_succeeded=False
    ) == 2


def test_settings_key_survives_notebook_split() -> None:
    assert COUNTER_SETTINGS_KEY in SETTINGS_KEYS
    from backend.specialists.review_orchestration import (
        DEEP_REVIEW_JOB_KEY,
        DEEP_REVIEW_SNAPSHOT_KEY,
    )

    assert DEEP_REVIEW_SNAPSHOT_KEY in SETTINGS_KEYS
    assert DEEP_REVIEW_JOB_KEY in SETTINGS_KEYS


def test_successful_coaching_is_one_fast_chat_call() -> None:
    client = FakeAgentCoreRuntime(payload=_output())
    result = _provider(client).assess(_request())
    assert _phases(client) == ["fast_chat"]
    assert _review_modes(client) == []
    assert result.assessment.recommendation is StageDecision.STAY
    assert result.assessment.review_depth != "incremental"
    assert result.qualifying_coaching_turn is True


def test_qa_does_not_call_incremental_or_deep_review() -> None:
    client = FakeAgentCoreRuntime(
        payload={
            "mode": "qa",
            "response_text": "Week 2 covers stakeholder mapping [S1].",
            "citations": [],
        }
    )
    result = _provider(client).assess(_request(student_message="What is Week 2 about?"))
    assert _phases(client) == ["fast_chat"]
    assert _review_modes(client) == []
    assert result.assessment.recommendation is None
    assert result.qualifying_coaching_turn is False


def test_explicit_review_goes_to_deep_review_without_coaching() -> None:
    client = FakeAgentCoreRuntime(
        payload={
            "response_text": "Your reasoning is more specific than last week.",
            "strengths": ["Named a real constraint"],
            "areas_to_develop": ["Name who is affected"],
            "synthesis": "Formative progress, not a grade.",
            "current_stage": "problem_identification",
            "recommendation": "stay",
            "rationale_summary": "Stay and name who is affected.",
        }
    )
    result = _provider(client).assess(
        _request(student_message="Can you assess how I am doing?", specialist="review")
    )
    assert _phases(client) == ["review"]
    assert _review_modes(client) == ["deep"]
    assert "fast_chat" not in _phases(client)
    assert "coaching" not in _phases(client)
    assert result.assessment.recommendation is StageDecision.STAY
    assert result.deep_review_succeeded is True
    assert result.qualifying_coaching_turn is False


def test_failed_coaching_does_not_call_incremental_review() -> None:
    client = FakeAgentCoreRuntime(error=TimeoutError("coach-timeout"))
    with pytest.raises(Exception):
        _provider(client).assess(_request())
    assert "review" not in _phases(client)


def test_fast_chat_timeout_does_not_persist(tmp_path) -> None:
    """A failed fast-chat invoke must fail the turn before DSQL writes."""
    store = StudentStore(tmp_path / "fast-chat-timeout.sqlite3")
    thread_id = store.create_thread(model_id="mock", support_mode="critical-thinking")
    client = FakeAgentCoreRuntime(error=TimeoutError("fast-chat-timeout"))
    with pytest.raises(ProviderUnavailableError) as raised:
        _service(store, client).submit(
            _request(thread_id=thread_id, idempotency_key="fast-chat-fail")
        )
    assert raised.value.category == "timeout"
    assert _review_modes(client) == []
    assert _counter(store, thread_id) == 0
    assert all(item["role"] != "assistant" for item in store.get_messages(thread_id))


def test_incremental_review_is_not_on_the_active_path() -> None:
    client = FakeAgentCoreRuntime(
        payload=_output(),
        incremental_payload={
            "response_text": "Incremental review.",
            "strengths": ["Concrete setting"],
            "areas_to_develop": ["Name who is affected"],
            "synthesis": "Not a grade.",
            "readiness_candidate": False,
            "recommendation": "advance",
            "current_stage": "problem_identification",
        },
    )
    result = _provider(client).assess(_request())
    assert result.assessment.recommendation is StageDecision.STAY
    assert "deep" not in _review_modes(client)
    assert "incremental" not in _review_modes(client)


def test_readiness_candidate_does_not_auto_invoke_sonnet() -> None:
    client = FakeAgentCoreRuntime(
        payload=_output(readiness_candidate=True),
        deep_payload={
            "response_text": "Deep review stay.",
            "strengths": ["Named stakeholders"],
            "areas_to_develop": ["Night-time evidence"],
            "synthesis": "Stay for now.",
            "current_stage": "problem_identification",
            "recommendation": "stay",
            "rationale_summary": "Night-time evidence is still missing.",
            "missing_requirements": ["Name who is affected at night"],
        },
    )
    result = _provider(client).assess(
        _request(coaching_turns_since_deep_review=1)
    )
    assert _review_modes(client) == []
    assert result.assessment.recommendation is StageDecision.STAY
    assert result.deep_review_succeeded is False


def test_coaching_advance_is_advisory_without_deep_review() -> None:
    client = FakeAgentCoreRuntime(
        payload=_output(recommendation=StageDecision.ADVANCE),
        deep_payload={
            "response_text": "Deep review stay.",
            "strengths": ["Clear constraint"],
            "areas_to_develop": ["Name who is affected"],
            "synthesis": "Stay.",
            "current_stage": "problem_identification",
            "recommendation": "stay",
            "rationale_summary": "The affected people are still unnamed.",
            "missing_requirements": ["Name who is affected at night"],
        },
    )
    result = _provider(client).assess(_request())
    assert _review_modes(client) == []
    assert result.assessment.recommendation is StageDecision.ADVANCE
    assert result.assessment.readiness_candidate is True


def test_fast_chat_advance_uses_existing_transition_path() -> None:
    client = FakeAgentCoreRuntime(payload=_output(recommendation=StageDecision.ADVANCE))
    result = _provider(client).assess(_request())
    assert result.assessment.recommendation is StageDecision.ADVANCE
    assert result.deep_review_succeeded is False


def test_explicit_deep_review_malformed_fails_closed() -> None:
    client = FakeAgentCoreRuntime(deep_payload={"recommendation": "maybe"})
    with pytest.raises(Exception):
        _provider(client).assess(_request(specialist="review"))


def test_explicit_deep_review_timeout_fails_closed() -> None:
    client = FakeAgentCoreRuntime(deep_error=TimeoutError("deep-timeout"))
    with pytest.raises(Exception):
        _provider(client).assess(_request(specialist="review"))


def test_explicit_deep_review_wrong_stage_fails_closed_to_stay() -> None:
    client = FakeAgentCoreRuntime(
        payload={
            "response_text": "Ready.",
            "strengths": ["Looks ready"],
            "areas_to_develop": [],
            "synthesis": "Ready.",
            "current_stage": "reflection",
            "recommendation": "advance",
            "rationale_summary": "Ready.",
        }
    )
    result = _provider(client).assess(_request(specialist="review"))
    assert result.assessment.recommendation is StageDecision.STAY
    assert result.deep_review_succeeded is False


def test_reflection_checkpoint_does_not_auto_invoke_sonnet() -> None:
    client = FakeAgentCoreRuntime(payload=_output())
    result = _provider(client).assess(
        _request(current_stage="reflection", coaching_turns_since_deep_review=0)
    )
    assert "deep" not in _review_modes(client)
    assert result.review_trigger is None
    assert _phases(client) == ["fast_chat"]


def test_periodic_three_coaching_turns_unlock_without_sonnet(tmp_path) -> None:
    store = StudentStore(tmp_path / "periodic.sqlite3")
    thread_id = store.create_thread(model_id="mock", support_mode="critical-thinking")
    client = FakeAgentCoreRuntime(payload=_output())
    service = _service(store, client)
    for index in range(3):
        service.submit(
            _request(
                thread_id=thread_id,
                idempotency_key=f"periodic-{index}",
                student_message=(
                    "I want to solve the lack of elderly caregivers in Singapore. "
                    f"Turn {index + 1}."
                ),
            )
        )
    assert _review_modes(client).count("incremental") == 0
    assert _review_modes(client).count("deep") == 0
    assert _phases(client).count("fast_chat") == 3
    assert _counter(store, thread_id) == 3
    service.submit(
        _request(
            thread_id=thread_id,
            idempotency_key="periodic-next",
            student_message="I still want to solve caregiver shortages in Singapore.",
        )
    )
    assert _counter(store, thread_id) == 4
    assert _review_modes(client).count("deep") == 0
    _persist_review_turn(
        store,
        thread_id,
        user_content="Successful explicit Deep Review.",
        qualifying=False,
        deep_succeeded=True,
    )
    assert _counter(store, thread_id) == 0


def test_qa_does_not_increment_counter_and_free_text_review_is_not_deep(
    tmp_path,
) -> None:
    store = StudentStore(tmp_path / "counter-qa.sqlite3")
    thread_id = store.create_thread(model_id="mock", support_mode="critical-thinking")
    client = FakeAgentCoreRuntime(payload=_output())
    service = _service(store, client)
    service.submit(
        _request(thread_id=thread_id, idempotency_key="coach-one")
    )
    assert _counter(store, thread_id) == 1
    qa_client = FakeAgentCoreRuntime(
        payload={
            "mode": "qa",
            "response_text": "Week 2 covers mapping [S1].",
            "citations": [],
        }
    )
    _service(store, qa_client).submit(
        _request(
            thread_id=thread_id,
            student_message="What is Week 2 about?",
            idempotency_key="qa-one",
        )
    )
    assert _counter(store, thread_id) == 1
    assert "review" not in _phases(qa_client)
    review_client = FakeAgentCoreRuntime(payload=_output())
    _service(store, review_client).submit(
        _request(
            thread_id=thread_id,
            student_message="Can you review my progress?",
            idempotency_key="review-one",
        )
    )
    assert _phases(review_client) == ["fast_chat"]
    assert _review_modes(review_client) == []
    assert _counter(store, thread_id) == 2


def test_failed_deep_review_keeps_due_counter(tmp_path) -> None:
    store = StudentStore(tmp_path / "deep-fail.sqlite3")
    thread_id = store.create_thread(model_id="mock", support_mode="critical-thinking")
    client = FakeAgentCoreRuntime(payload=_output())
    service = _service(store, client)
    service.submit(_request(thread_id=thread_id, idempotency_key="due-1"))
    service.submit(
        _request(
            thread_id=thread_id,
            idempotency_key="due-2",
            student_message="I want to solve caregiver shortages. Turn 2.",
        )
    )
    service.submit(
        _request(
            thread_id=thread_id,
            idempotency_key="due-3",
            student_message="I want to solve caregiver shortages. Turn 3.",
        )
    )
    assert _counter(store, thread_id) == 3
    assert _review_modes(client).count("deep") == 0
    _persist_review_turn(
        store,
        thread_id,
        user_content="Failed explicit Deep Review.",
        qualifying=False,
        deep_succeeded=False,
    )
    assert _counter(store, thread_id) == 3
    _persist_review_turn(
        store,
        thread_id,
        user_content="Successful explicit Deep Review.",
        qualifying=False,
        deep_succeeded=True,
    )
    assert _counter(store, thread_id) == 0


def test_idempotent_replay_does_not_repeat_model_calls(tmp_path) -> None:
    store = StudentStore(tmp_path / "review-idempotent.sqlite3")
    thread_id = store.create_thread(model_id="mock", support_mode="critical-thinking")
    client = FakeAgentCoreRuntime(payload=_output())
    service = _service(store, client)
    request = _request(thread_id=thread_id, idempotency_key="replay-once")
    first = service.submit(request)
    second = service.submit(request)
    assert first.response_text == second.response_text
    assert _phases(client).count("fast_chat") == 1
    assert _review_modes(client).count("incremental") == 0
    assert _review_modes(client).count("deep") == 0
    assert _counter(store, thread_id) == 1


def test_persist_recomputes_counter_from_stored_settings(tmp_path) -> None:
    """Stale pre-provider counter values must not overwrite the stored count."""
    store = StudentStore(tmp_path / "counter-cas.sqlite3")
    thread_id = store.create_thread(model_id="mock", support_mode="critical-thinking")
    _persist_review_turn(
        store,
        thread_id,
        user_content="Qualifying coaching turn one.",
        qualifying=True,
        deep_succeeded=False,
        stale_counter=0,
    )
    assert _counter(store, thread_id) == 1
    _persist_review_turn(
        store,
        thread_id,
        user_content="Qualifying coaching turn two.",
        qualifying=True,
        deep_succeeded=False,
        stale_counter=1,
    )
    assert _counter(store, thread_id) == 2


def test_concurrent_persist_does_not_lose_counter_increment(tmp_path) -> None:
    """Two overlapping persists must not both write the same counter value."""
    database = tmp_path / "counter-race.sqlite3"
    owner = StudentStore(database)
    thread_id = owner.create_thread(model_id="mock", support_mode="critical-thinking")
    barrier = threading.Barrier(2)
    errors: list[BaseException] = []

    def _worker(label: str) -> None:
        store = StudentStore(database)
        barrier.wait()
        try:
            _persist_review_turn(
                store,
                thread_id,
                user_content=f"Concurrent qualifying turn {label}.",
                qualifying=True,
                deep_succeeded=False,
            )
        except Exception as error:
            errors.append(error)

    first = threading.Thread(target=_worker, args=("a",))
    second = threading.Thread(target=_worker, args=("b",))
    first.start()
    second.start()
    first.join()
    second.join()
    successes = 2 - len(errors)
    assert successes in {1, 2}
    if successes == 2:
        assert _counter(owner, thread_id) == 2
        assert len(owner.get_messages(thread_id)) == 4
        return
    assert _counter(owner, thread_id) == 1
    assert len(owner.get_messages(thread_id)) == 2
    assert len(errors) == 1
    assert isinstance(errors[0], ConversationRevisionConflictError)


def test_review_tab_projection_does_not_invoke_models() -> None:
    review = learning_review([], {"current_stage": "problem_identification"})
    assert "summary" in review
    studio = Path("ui/panels/studio.py").read_text(encoding="utf-8")
    journey = Path("backend/learning/journey.py").read_text(encoding="utf-8")
    assert "def render_learning_review" in studio
    assert "AgentCore" not in studio
    assert "assess(" not in studio.split("def render_learning_review", 1)[1].split(
        "def ", 1
    )[0]
    review_fn = studio.split("def render_learning_review", 1)[1].split("def ", 1)[0]
    assert "deep_review_snapshot=" in review_fn
    review_call = review_fn.split("review = learning_review", 1)[1].split(")", 1)[0]
    assert "session_state" not in review_call
    assert "_merge_deep_review_feedback" in journey
    assert "reviewed_stage_id" in journey


def test_fast_chat_logs_omit_student_text(caplog: pytest.LogCaptureFixture) -> None:
    client = FakeAgentCoreRuntime(payload=_output())
    with caplog.at_level(logging.INFO):
        _provider(client).assess(_request())
    joined = " ".join(record.getMessage() for record in caplog.records)
    assert "elderly caregivers" not in joined
    assert "role=fast_chat" in joined
    assert "review_depth=incremental" not in joined
    assert "role=router" not in joined
