"""Server-owned explicit Deep Review application path. No AWS."""

from __future__ import annotations

import json
from typing import Any

import pytest

from backend.agentcore_provider import AgentCoreCoachProvider
from backend.application import CoachApplicationService, _coach_request_fingerprint
from backend.domain import (
    CoachRequest,
    EducationalAssessment,
    FacioneDimensionScores,
    ProviderCoachOutput,
    StageDecision,
)
from backend.learning_service import LearningProgressService
from backend.providers import ProviderUnavailableError
from backend.repositories import (
    SQLiteNotebookRepository,
    SQLitePhaseTransitionRepository,
)
from backend.specialists.review_orchestration import (
    COUNTER_SETTINGS_KEY,
    DEEP_REVIEW_SNAPSHOT_KEY,
    DEEP_REVIEW_TURN_MESSAGE,
    explicit_deep_review_available,
)
from backend.student_journey import learning_review
from backend.student_store import CoachIdempotencyConflictError, StudentStore
from backend.workflow import CoachWorkflow
from fake_agentcore_runtime import FakeAgentCoreRuntime

_RUNTIME_ARN = (
    "arn:aws:bedrock-agentcore:us-west-2:123456789012:runtime/test-harness"
)


def _assessment() -> EducationalAssessment:
    """Return one valid coaching assessment."""
    return EducationalAssessment(
        current_stage="problem_identification",
        contribution_summary="The student compared two design constraints.",
        stage_assessment="The contribution is usable but can be developed further.",
        critical_understanding_level="Developing",
        confidence=0.7,
        recommendation=StageDecision.STAY,
        recommendation_rationale="More evidence is still needed.",
        guidance_questions=["What trade-off still needs evidence?"],
        learning_summary="The student is developing the problem.",
        citations=[],
        facione_scores=FacioneDimensionScores(),
    )


def _coaching_payload() -> dict[str, Any]:
    """Return one fast-chat coaching body."""
    payload = ProviderCoachOutput(
        response_text="What assumption is carrying this preference?",
        assessment=_assessment(),
        research_coding=None,
    ).model_dump(mode="json")
    payload["mode"] = "coaching"
    return payload


def _deep_payload(*, synthesis: str = "Formative Deep Review A.") -> dict[str, Any]:
    """Return one explicit Deep Review body that stays on the current stage."""
    return {
        "response_text": synthesis,
        "strengths": ["Named a real constraint"],
        "areas_to_develop": ["Name who is affected"],
        "synthesis": synthesis,
        "current_stage": "problem_identification",
        "recommendation": "advance",
        "rationale_summary": "Readiness information only.",
        "working_conclusion": "Option B is the working concept.",
        "facione_profile": {
            "interpretation": 2,
            "analysis": 2,
            "inference": 2,
            "evaluation": 2,
            "explanation": 2,
            "self_regulation": 2,
        },
    }


def _provider(client: FakeAgentCoreRuntime) -> AgentCoreCoachProvider:
    """Build the AgentCore adapter around a fake runtime."""
    return AgentCoreCoachProvider(
        _RUNTIME_ARN,
        region="us-west-2",
        qualifier="DEFAULT",
        timeout_seconds=110.0,
        max_retries=0,
        client=client,
    )


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


def _decoded(call: dict[str, Any]) -> dict[str, Any]:
    """Decode one recorded InvokeAgentRuntime payload."""
    raw = call["payload"]
    if isinstance(raw, (bytes, bytearray)):
        return json.loads(bytes(raw).decode("utf-8"))
    return json.loads(str(raw))


def _phases(client: FakeAgentCoreRuntime) -> list[str]:
    """Return payload phases in invoke order."""
    return [str(_decoded(call).get("phase") or "") for call in client.calls]


def _counter(store: StudentStore, thread_id: str) -> int:
    """Return the persisted Deep Review counter."""
    metadata = dict((store.get_thread(thread_id) or {}).get("metadata") or {})
    try:
        return int(metadata.get(COUNTER_SETTINGS_KEY) or 0)
    except (TypeError, ValueError):
        return 0


def _snapshot(store: StudentStore, thread_id: str) -> dict[str, Any] | None:
    """Return the durable Deep Review snapshot when present."""
    metadata = dict((store.get_thread(thread_id) or {}).get("metadata") or {})
    raw = metadata.get(DEEP_REVIEW_SNAPSHOT_KEY)
    return raw if isinstance(raw, dict) else None


def _unlock(store: StudentStore, thread_id: str) -> None:
    """Grant one explicit Deep Review entitlement without stacking credits."""
    store.update_thread(thread_id, metadata={COUNTER_SETTINGS_KEY: 3})


def _coach(service: CoachApplicationService, thread_id: str, key: str, message: str) -> None:
    """Submit one normal coaching turn."""
    service.submit(
        CoachRequest(
            thread_id=thread_id,
            student_message=message,
            current_stage="problem_identification",
            response_detail="short",
            idempotency_key=key,
        )
    )


def test_eligibility_requires_persisted_interval() -> None:
    assert explicit_deep_review_available(
        coaching_turns_since_deep_review=2, interval=3
    ) is False
    assert explicit_deep_review_available(
        coaching_turns_since_deep_review=3, interval=3
    ) is True
    assert explicit_deep_review_available(
        coaching_turns_since_deep_review=6, interval=3
    ) is True


def test_locked_deep_review_is_rejected_without_sonnet(tmp_path) -> None:
    store = StudentStore(tmp_path / "dr-locked.sqlite3")
    thread_id = store.create_thread(model_id="mock", support_mode="critical-thinking")
    client = FakeAgentCoreRuntime(payload=_coaching_payload(), deep_payload=_deep_payload())
    service = _service(store, client)
    with pytest.raises(ValueError, match="not available"):
        service.run_deep_review(thread_id, idempotency_key="locked")
    assert client.calls == []
    assert _counter(store, thread_id) == 0


def test_eligible_deep_review_is_one_sonnet_call_and_resets_counter(tmp_path) -> None:
    store = StudentStore(tmp_path / "dr-ok.sqlite3")
    thread_id = store.create_thread(model_id="mock", support_mode="critical-thinking")
    _unlock(store, thread_id)
    client = FakeAgentCoreRuntime(payload=_coaching_payload(), deep_payload=_deep_payload())
    service = _service(store, client)
    turn = service.run_deep_review(thread_id, idempotency_key="deep-1")
    assert _phases(client) == ["review"]
    assert turn.assessment.recommendation is StageDecision.STAY
    assert turn.pending_transition is None
    assert turn.auto_advanced_to is None
    assert _counter(store, thread_id) == 0
    snapshot = _snapshot(store, thread_id)
    assert snapshot is not None
    assert snapshot["review_depth"] == "deep"
    assert snapshot["review_trigger"] == "explicit"
    assert snapshot["model_id"] == "global.anthropic.claude-sonnet-4-6"
    assert "Formative Deep Review A" in snapshot["synthesis"]
    thread = store.get_thread(thread_id) or {}
    journey = dict((thread.get("metadata") or {}).get("learning_journey") or {})
    assert journey.get("current_stage") == "problem_identification"


def test_failed_deep_review_leaves_counter_and_snapshot_unchanged(tmp_path) -> None:
    store = StudentStore(tmp_path / "dr-fail.sqlite3")
    thread_id = store.create_thread(model_id="mock", support_mode="critical-thinking")
    _unlock(store, thread_id)
    client = FakeAgentCoreRuntime(deep_error=TimeoutError("deep-timeout"))
    service = _service(store, client)
    with pytest.raises(ProviderUnavailableError):
        service.run_deep_review(thread_id, idempotency_key="deep-fail")
    assert _counter(store, thread_id) == 3
    assert _snapshot(store, thread_id) is None
    assert all(item["role"] != "assistant" for item in store.get_messages(thread_id))


def test_idempotent_replay_does_not_rerun_sonnet(tmp_path) -> None:
    store = StudentStore(tmp_path / "dr-idem.sqlite3")
    thread_id = store.create_thread(model_id="mock", support_mode="critical-thinking")
    _unlock(store, thread_id)
    client = FakeAgentCoreRuntime(deep_payload=_deep_payload())
    service = _service(store, client)
    first = service.run_deep_review(thread_id, idempotency_key="same-deep")
    replay_client = FakeAgentCoreRuntime(deep_payload=_deep_payload(synthesis="Must not run."))
    replay = _service(store, replay_client).run_deep_review(
        thread_id, idempotency_key="same-deep"
    )
    assert replay_client.calls == []
    assert replay.response_text == first.response_text
    assert _counter(store, thread_id) == 0


def test_normal_coaching_does_not_overwrite_snapshot(tmp_path) -> None:
    store = StudentStore(tmp_path / "dr-snap.sqlite3")
    thread_id = store.create_thread(model_id="mock", support_mode="critical-thinking")
    _unlock(store, thread_id)
    deep_client = FakeAgentCoreRuntime(deep_payload=_deep_payload())
    _service(store, deep_client).run_deep_review(thread_id, idempotency_key="deep-a")
    first = _snapshot(store, thread_id)
    assert first is not None
    coach_client = FakeAgentCoreRuntime(payload=_coaching_payload())
    _coach(
        _service(store, coach_client),
        thread_id,
        "coach-after",
        "I still prefer option B because maintenance is manageable.",
    )
    assert _phases(coach_client) == ["fast_chat"]
    after = _snapshot(store, thread_id)
    assert after == first
    review = learning_review(
        store.get_messages(thread_id),
        (store.get_thread(thread_id) or {}).get("metadata") or {},
        deep_review_snapshot=after,
    )
    assert "Formative Deep Review A" in str(review.get("summary") or "")


def test_next_successful_deep_review_replaces_snapshot(tmp_path) -> None:
    store = StudentStore(tmp_path / "dr-replace.sqlite3")
    thread_id = store.create_thread(model_id="mock", support_mode="critical-thinking")
    _unlock(store, thread_id)
    _service(store, FakeAgentCoreRuntime(deep_payload=_deep_payload())).run_deep_review(
        thread_id, idempotency_key="deep-a"
    )
    _unlock(store, thread_id)
    _service(
        store,
        FakeAgentCoreRuntime(deep_payload=_deep_payload(synthesis="Formative Deep Review C.")),
    ).run_deep_review(thread_id, idempotency_key="deep-c")
    snapshot = _snapshot(store, thread_id)
    assert snapshot is not None
    assert "Deep Review C" in snapshot["synthesis"]
    assert "Deep Review A" not in snapshot["synthesis"]


def test_submit_cannot_select_review_specialist(tmp_path) -> None:
    store = StudentStore(tmp_path / "dr-hint.sqlite3")
    thread_id = store.create_thread(model_id="mock", support_mode="critical-thinking")
    client = FakeAgentCoreRuntime(payload=_coaching_payload(), deep_payload=_deep_payload())
    _service(store, client).submit(
        CoachRequest(
            thread_id=thread_id,
            student_message="I compared two constraints for Holland Road.",
            current_stage="problem_identification",
            response_detail="short",
            specialist="review",
            idempotency_key="hint-review",
        )
    )
    assert _phases(client) == ["fast_chat"]
    assert _snapshot(store, thread_id) is None
    assert _counter(store, thread_id) == 1


def test_deep_review_fingerprint_differs_from_coach_turn() -> None:
    request = CoachRequest(
        thread_id="thread-demo",
        student_message=DEEP_REVIEW_TURN_MESSAGE,
        current_stage="problem_identification",
        response_detail="short",
        idempotency_key="shared",
    )
    coach = _coach_request_fingerprint(request)
    same_surface = _coach_request_fingerprint(request, surface="coach_turn")
    deep = _coach_request_fingerprint(request, surface="deep_review")
    assert coach == same_surface
    assert deep != coach


def test_coach_turn_cannot_poison_deep_review_idempotency_key(tmp_path) -> None:
    store = StudentStore(tmp_path / "dr-poison.sqlite3")
    thread_id = store.create_thread(model_id="mock", support_mode="critical-thinking")
    client = FakeAgentCoreRuntime(payload=_coaching_payload(), deep_payload=_deep_payload())
    service = _service(store, client)
    _coach(service, thread_id, "shared-key", DEEP_REVIEW_TURN_MESSAGE)
    assert _phases(client) == ["fast_chat"]
    _unlock(store, thread_id)
    with pytest.raises(CoachIdempotencyConflictError):
        service.run_deep_review(thread_id, idempotency_key="shared-key")
    assert "review" not in _phases(client)
    assert _snapshot(store, thread_id) is None
    assert _counter(store, thread_id) == 3
