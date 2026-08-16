"""Hybrid Luna router + Sonnet Stage Judge adapter tests (no AWS)."""

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
    ProviderCoachOutput,
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
    """Return a coach_turn payload."""
    return ProviderCoachOutput(
        response_text="What trade-off still needs evidence?",
        assessment=_assessment(recommendation=recommendation),
        research_coding=None,
    ).model_dump(mode="json")


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


def test_clear_qa_router_result_selects_qa() -> None:
    client = FakeAgentCoreRuntime(
        payload={
            "response_text": "Week 2 covers stakeholder mapping [S1].",
            "citations": [],
        },
        router_payload={
            "specialist": "qa",
            "confidence": 0.91,
            "rationale_category": "course_information",
        },
    )
    result = _provider(client).assess(_request(student_message="What is Week 2 about?"))
    assert _phases(client) == ["router", "qa"]
    assert result.assessment.recommendation is StageDecision.STAY
    assert "does not recommend" in result.assessment.recommendation_rationale


def test_implicit_qa_router_result_selects_qa() -> None:
    client = FakeAgentCoreRuntime(
        payload={"response_text": "The brief asks for a JTBD statement.", "citations": []},
        router_payload={
            "specialist": "qa",
            "confidence": 0.84,
            "rationale_category": "course_information",
        },
    )
    result = _provider(client).assess(
        _request(student_message="Can you explain the assignment brief?")
    )
    assert _phases(client) == ["router", "qa"]
    assert result.assessment.recommendation is StageDecision.STAY


def test_project_discussion_routes_to_coaching() -> None:
    client = FakeAgentCoreRuntime(payload=_output())
    result = _provider(client).assess(_request())
    assert _phases(client)[:2] == ["router", "coaching"]
    assert result.assessment.recommendation is StageDecision.STAY
    assert "deep" not in [
        str(_decoded(call).get("review_mode") or "") for call in client.calls
    ]


def test_semantic_review_routes_to_review_and_cannot_advance() -> None:
    client = FakeAgentCoreRuntime(
        payload={
            "response_text": "Your reasoning is more specific than last week.",
            "strengths": ["Named a real constraint"],
            "areas_to_develop": ["Name who is affected"],
            "synthesis": "Formative progress, not a grade.",
            "current_stage": "problem_identification",
            "recommendation": "stay",
            "rationale_summary": "Stay.",
        },
        router_payload={
            "specialist": "review",
            "confidence": 0.88,
            "rationale_category": "formative_review",
        },
    )
    result = _provider(client).assess(
        _request(student_message="Do you think my reasoning has improved enough?")
    )
    assert _phases(client) == ["router", "review"]
    assert result.assessment.recommendation is StageDecision.STAY
    assert "coaching" not in _phases(client)


def test_malformed_router_output_falls_back_to_coaching() -> None:
    client = FakeAgentCoreRuntime(
        payload=_output(),
        router_payload={"specialist": "admin", "confidence": 0.99},
    )
    result = _provider(client).assess(_request())
    assert "coaching" in _phases(client)
    assert result.assessment.recommendation is StageDecision.STAY


def test_router_timeout_falls_back_to_coaching() -> None:
    client = FakeAgentCoreRuntime(payload=_output(), router_error=TimeoutError("timed out"))
    result = _provider(client).assess(_request())
    assert _phases(client)[:2] == ["router", "coaching"]
    assert result.response_text


def test_low_confidence_router_falls_back_to_coaching() -> None:
    client = FakeAgentCoreRuntime(
        payload=_output(),
        router_payload={
            "specialist": "qa",
            "confidence": 0.2,
            "rationale_category": "course_information",
        },
    )
    result = _provider(client).assess(_request(student_message="What is Week 2 about?"))
    assert apply_semantic_route("qa", 0.2) == SPECIALIST_COACHING
    assert _phases(client)[0] == "router"
    assert "coaching" in _phases(client)
    assert result.assessment.recommendation is StageDecision.STAY


def test_router_safety_blocked_does_not_fallback_to_coaching() -> None:
    client = FakeAgentCoreRuntime(
        payload=_output(),
        router_payload={"ok": False, "error": True, "category": "safety_blocked"},
    )
    with pytest.raises(Exception, match="blocked") as raised:
        _provider(client).assess(_request())
    assert getattr(raised.value, "category", "") == "safety_blocked"
    assert _phases(client) == ["router"]


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
    assert _phases(client)[0] == "router"
    assert "qa" not in _phases(client)
    assert "coaching" in _phases(client)


def test_coaching_stay_does_not_call_deep_review() -> None:
    client = FakeAgentCoreRuntime(payload=_output(recommendation=StageDecision.STAY))
    result = _provider(client).assess(_request())
    modes = [
        str(_decoded(call).get("review_mode") or "") for call in client.calls
    ]
    assert "deep" not in modes
    assert result.assessment.recommendation is StageDecision.STAY


def test_coaching_advance_calls_deep_review_once() -> None:
    client = FakeAgentCoreRuntime(payload=_output(recommendation=StageDecision.ADVANCE))
    result = _provider(client).assess(_request())
    modes = [
        str(_decoded(call).get("review_mode") or "") for call in client.calls
    ]
    assert modes.count("deep") == 1
    assert _phases(client).count("coaching") == 1
    assert result.assessment.recommendation is StageDecision.ADVANCE


def test_deep_review_stay_blocks_transition() -> None:
    client = FakeAgentCoreRuntime(
        payload=_output(recommendation=StageDecision.ADVANCE),
        judge_payload={
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
        },
    )
    result = _provider(client).assess(_request())
    assert result.assessment.recommendation is StageDecision.STAY
    assert "Name who is affected at night" in result.assessment.missing_reasoning_elements
    assert "unnamed" in result.assessment.recommendation_rationale


def test_deep_review_malformed_fails_closed_to_stay() -> None:
    client = FakeAgentCoreRuntime(
        payload=_output(recommendation=StageDecision.ADVANCE),
        judge_payload={"recommendation": "maybe"},
    )
    result = _provider(client).assess(_request())
    assert result.assessment.recommendation is StageDecision.STAY
    assert result.response_text.startswith("What trade-off")


def test_deep_review_timeout_fails_closed_to_stay() -> None:
    client = FakeAgentCoreRuntime(
        payload=_output(recommendation=StageDecision.ADVANCE),
        judge_error=TimeoutError("judge-timeout"),
    )
    result = _provider(client).assess(_request())
    assert result.assessment.recommendation is StageDecision.STAY


def test_deep_review_wrong_stage_fails_closed_to_stay() -> None:
    client = FakeAgentCoreRuntime(
        payload=_output(recommendation=StageDecision.ADVANCE),
        judge_payload={
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
        },
    )
    result = _provider(client).assess(_request())
    assert result.assessment.recommendation is StageDecision.STAY


def test_deep_review_payload_omits_research_coding() -> None:
    envelope = ProviderCoachOutput(
        response_text="What trade-off still needs evidence?",
        assessment=_assessment(recommendation=StageDecision.ADVANCE),
        research_coding=None,
    ).model_dump(mode="json")
    client = FakeAgentCoreRuntime(payload=envelope)
    _provider(client).assess(_request())
    deep_payload = _decoded(
        next(
            call
            for call in client.calls
            if _decoded(call).get("phase") == "review"
            and _decoded(call).get("review_mode") == "deep"
        )
    )
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
        },
        router_payload={
            "specialist": "review",
            "confidence": 0.9,
            "rationale_category": "formative_review",
        },
    )
    result = _provider(client).assess(
        _request(student_message="How strong is what I've done so far?")
    )
    assert result.assessment.recommendation is StageDecision.STAY
    assert "coaching" not in _phases(client)


def test_router_logs_omit_student_text(caplog: pytest.LogCaptureFixture) -> None:
    client = FakeAgentCoreRuntime(payload=_output())
    with caplog.at_level(logging.INFO):
        _provider(client).assess(_request())
    joined = " ".join(record.getMessage() for record in caplog.records)
    assert "elderly caregivers" not in joined
    assert "role=router" in joined
    assert "role=coaching" in joined


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
    assert _phases(client).count("coaching") == 1
    assert _phases(client).count("router") == 1
