"""Hybrid Haiku router + Sonnet Deep Review adapter tests (no AWS)."""

from __future__ import annotations

import json
import logging
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
from backend.learning_service import LearningProgressService
from backend.repositories import (
    SQLiteNotebookRepository,
    SQLitePhaseTransitionRepository,
)
from backend.specialists.routing import (
    SPECIALIST_COACHING,
    SPECIALIST_QA,
    SPECIALIST_REVIEW,
    apply_semantic_route,
    select_specialist,
)
from backend.student_store import StudentStore
from backend.workflow import CoachWorkflow
from fake_agentcore_runtime import FakeAgentCoreRuntime

_RUNTIME_ARN = (
    "arn:aws:bedrock-agentcore:us-west-2:123456789012:runtime/test-harness"
)
_STREET = "A quiet residential street"


def _assessment(
    *,
    stage: str = "problem_identification",
    recommendation: StageDecision = StageDecision.STAY,
) -> EducationalAssessment:
    """Return a valid coaching assessment for hybrid adapter tests."""
    return EducationalAssessment(
        current_stage=stage,
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
    )


def _output(*, recommendation: StageDecision = StageDecision.STAY) -> dict[str, Any]:
    """Return a lightweight fast-chat coaching payload."""
    return {
        "mode": "coaching",
        "response_text": "What trade-off still needs evidence?",
        "recommendation": recommendation.value,
        "recommendation_rationale": (
            "More evidence is still needed."
            if recommendation is StageDecision.STAY
            else "The stage readiness bar is met."
        ),
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
    }
    payload.update(overrides)
    return CoachRequest(**payload)


def _decoded(call: dict[str, Any]) -> dict[str, Any]:
    """Decode one recorded InvokeAgentRuntime payload."""
    raw = call["payload"]
    if isinstance(raw, (bytes, bytearray)):
        return json.loads(bytes(raw).decode("utf-8"))
    return json.loads(str(raw))


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


def _phases(client: FakeAgentCoreRuntime) -> list[str]:
    """Return payload phases in invoke order."""
    return [str(_decoded(call).get("phase") or "") for call in client.calls]


def test_fast_chat_qa_mode_is_one_call() -> None:
    client = FakeAgentCoreRuntime(
        payload={
            "mode": "qa",
            "response_text": "Week 2 covers stakeholder mapping [S1].",
            "citations": [],
        }
    )
    result = _provider(client).assess(_request(student_message="What is Week 2 about?"))
    assert _phases(client) == ["fast_chat"]
    assert result.specialist == SPECIALIST_QA
    assert result.assessment.recommendation is None
    assert result.assessment.response_mode == "qa"


def test_project_discussion_is_one_fast_chat_call() -> None:
    client = FakeAgentCoreRuntime(payload=_output())
    result = _provider(client).assess(_request())
    assert _phases(client) == ["fast_chat"]
    assert result.assessment.recommendation is StageDecision.STAY
    assert "deep" not in [
        str(_decoded(call).get("review_mode") or "") for call in client.calls
    ]


def test_free_text_review_request_does_not_invoke_deep_review() -> None:
    client = FakeAgentCoreRuntime(payload=_output())
    result = _provider(client).assess(
        _request(student_message="Do you think my reasoning has improved enough?")
    )
    assert _phases(client) == ["fast_chat"]
    assert result.specialist == SPECIALIST_COACHING
    assert result.assessment.recommendation is StageDecision.STAY


def test_legacy_semantic_route_helper_still_falls_back() -> None:
    assert apply_semantic_route("qa", 0.2) == SPECIALIST_COACHING
    assert apply_semantic_route("admin", 0.99) == SPECIALIST_COACHING


def test_fast_chat_safety_blocked_fails_closed() -> None:
    client = FakeAgentCoreRuntime(
        payload={"ok": False, "error": True, "category": "safety_blocked"}
    )
    with pytest.raises(Exception, match="blocked") as raised:
        _provider(client).assess(_request())
    assert getattr(raised.value, "category", "") == "safety_blocked"
    assert _phases(client) == ["fast_chat"]


def test_server_owned_review_skips_router() -> None:
    client = FakeAgentCoreRuntime(
        payload={
            "response_text": "Formative review of progress.",
            "strengths": ["Concrete setting"],
            "areas_to_develop": ["Name who is affected"],
            "synthesis": "Not a grade.",
        }
    )
    result = _provider(client).assess(
        _request(student_message="Keep going.", specialist="review")
    )
    assert "router" not in _phases(client)
    assert "fast_chat" not in _phases(client)
    assert _phases(client) == ["review"]
    assert result.assessment.recommendation is StageDecision.STAY


def test_application_service_drops_browser_specialist_hint(tmp_path) -> None:
    store = StudentStore(tmp_path / "hybrid-browser.sqlite3")
    thread_id = store.create_thread(model_id="mock", support_mode="critical-thinking")
    client = FakeAgentCoreRuntime(payload=_output())
    service = _service(store, client)
    service.submit(
        _request(
            thread_id=thread_id,
            specialist="qa",
            student_message="I want to solve the lack of elderly caregivers in Singapore.",
            idempotency_key="browser-cannot-force-qa",
        )
    )
    assert _phases(client) == ["fast_chat"]
    assert "qa" not in _phases(client)
    assert "review" not in _phases(client)


def test_coaching_stay_does_not_call_deep_review() -> None:
    client = FakeAgentCoreRuntime(payload=_output(recommendation=StageDecision.STAY))
    result = _provider(client).assess(_request())
    modes = [
        str(_decoded(call).get("review_mode") or "") for call in client.calls
    ]
    assert "deep" not in modes
    assert result.assessment.recommendation is StageDecision.STAY


def test_coaching_advance_is_advisory_without_sonnet() -> None:
    client = FakeAgentCoreRuntime(payload=_output(recommendation=StageDecision.ADVANCE))
    result = _provider(client).assess(_request())
    modes = [
        str(_decoded(call).get("review_mode") or "") for call in client.calls
    ]
    assert modes.count("deep") == 0
    assert _phases(client) == ["fast_chat"]
    assert result.assessment.recommendation is StageDecision.ADVANCE
    assert result.assessment.readiness_candidate is True


def test_explicit_deep_review_stay_does_not_advance() -> None:
    client = FakeAgentCoreRuntime(
        payload={
            "response_text": "Stay for now.",
            "strengths": [],
            "areas_to_develop": ["Name who is affected at night"],
            "synthesis": "The affected people are still unnamed.",
            "current_stage": "problem_identification",
            "recommendation": "stay",
            "confidence": 0.8,
            "readiness_evidence": [],
            "missing_requirements": ["Name who is affected at night"],
            "rationale_summary": "The affected people are still unnamed.",
        }
    )
    result = _provider(client).assess(_request(specialist="review"))
    assert result.assessment.recommendation is StageDecision.STAY
    assert "Name who is affected at night" in result.assessment.missing_reasoning_elements
    assert "unnamed" in result.assessment.recommendation_rationale


def test_explicit_deep_review_malformed_fails_closed() -> None:
    client = FakeAgentCoreRuntime(deep_payload={"recommendation": "maybe"})
    with pytest.raises(Exception):
        _provider(client).assess(_request(specialist="review"))


def test_explicit_deep_review_timeout_fails_closed() -> None:
    client = FakeAgentCoreRuntime(deep_error=TimeoutError("judge-timeout"))
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
            "confidence": 0.99,
            "readiness_evidence": ["Looks ready"],
            "missing_requirements": [],
            "rationale_summary": "Ready.",
        }
    )
    result = _provider(client).assess(_request(specialist="review"))
    assert result.assessment.recommendation is StageDecision.STAY


def test_deep_review_payload_omits_research_coding() -> None:
    client = FakeAgentCoreRuntime(
        payload={
            "response_text": "Formative deep review of progress.",
            "strengths": ["The contribution named a concrete constraint."],
            "areas_to_develop": ["Name who is affected at night."],
            "synthesis": "Stay.",
            "current_stage": "problem_identification",
            "recommendation": "stay",
            "rationale_summary": "Stay.",
        }
    )
    _provider(client).assess(_request(specialist="review"))
    deep_payload = _decoded(client.calls[0])
    assert deep_payload["phase"] == "review"
    assert "dominant_clear" not in json.dumps(deep_payload)
    assert deep_payload["runtime_context"]["current_stage"] == "problem_identification"


def test_explicit_review_does_not_run_coaching() -> None:
    client = FakeAgentCoreRuntime(
        payload={
            "response_text": "Formative review",
            "strengths": ["Clear constraint"],
            "areas_to_develop": ["Name who is affected"],
            "synthesis": "Not a grade.",
            "current_stage": "problem_identification",
            "recommendation": "stay",
            "rationale_summary": "Stay.",
        }
    )
    result = _provider(client).assess(
        _request(student_message="How strong is what I've done so far?", specialist="review")
    )
    assert result.assessment.recommendation is StageDecision.STAY
    assert "fast_chat" not in _phases(client)
    assert "coaching" not in _phases(client)


def test_fast_chat_logs_omit_student_text(caplog: pytest.LogCaptureFixture) -> None:
    client = FakeAgentCoreRuntime(payload=_output())
    with caplog.at_level(logging.INFO):
        _provider(client).assess(_request())
    joined = " ".join(record.getMessage() for record in caplog.records)
    assert "elderly caregivers" not in joined
    assert "role=fast_chat" in joined
    assert "role=router" not in joined


def test_select_specialist_surface_still_bypasses_semantic() -> None:
    assert (
        select_specialist("Keep going.", surface="review", use_semantic=True)
        == SPECIALIST_REVIEW
    )
    assert (
        select_specialist("Keep going.", requested="qa", use_semantic=True)
        == SPECIALIST_QA
    )
    assert (
        select_specialist(
            "Keep going.",
            use_semantic=True,
            semantic_specialist="review",
            semantic_confidence=0.9,
        )
        == SPECIALIST_REVIEW
    )


def test_idempotent_retry_does_not_duplicate_provider_after_persist(tmp_path) -> None:
    store = StudentStore(tmp_path / "hybrid-idempotent.sqlite3")
    thread_id = store.create_thread(model_id="mock", support_mode="critical-thinking")
    client = FakeAgentCoreRuntime(payload=_output())
    service = _service(store, client)
    request = _request(
        thread_id=thread_id,
        idempotency_key="hybrid-retry-once",
    )
    first = service.submit(request)
    second = service.submit(request)
    assert first.response_text == second.response_text
    assert _phases(client).count("fast_chat") == 1
    assert _phases(client).count("router") == 0
