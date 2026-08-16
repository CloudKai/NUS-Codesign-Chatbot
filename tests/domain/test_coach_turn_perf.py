"""Privacy-safe coach_turn_perf emission tests."""

from __future__ import annotations

import json
import logging

import pytest

from backend.agentcore_provider import AgentCoreCoachProvider
from backend.domain import (
    CoachRequest,
    EducationalAssessment,
    FacioneDimensionScores,
    ProviderCoachOutput,
    StageDecision,
)
from backend.providers import ProviderUnavailableError
from backend.turn_perf import SAFE_PERF_FIELDS, assert_payload_is_safe, begin_coach_turn_perf
from fake_agentcore_runtime import FakeAgentCoreRuntime

_RUNTIME_ARN = (
    "arn:aws:bedrock-agentcore:us-west-2:123456789012:runtime/test-harness"
)


def _output() -> dict:
    """Return a coaching fast-chat payload."""
    payload = ProviderCoachOutput(
        response_text="What trade-off still needs evidence?",
        assessment=EducationalAssessment(
            current_stage="problem_identification",
            contribution_summary="The student compared two design constraints.",
            stage_assessment="The contribution is usable.",
            critical_understanding_level="Developing",
            confidence=0.7,
            recommendation=StageDecision.STAY,
            recommendation_rationale="More evidence is still needed.",
            guidance_questions=["What trade-off still needs evidence?"],
            learning_summary="The student is developing the problem.",
            citations=[],
            facione_scores=FacioneDimensionScores(),
        ),
        research_coding=None,
    ).model_dump(mode="json")
    payload["mode"] = "coaching"
    return payload


def test_success_perf_log_has_no_student_text_or_secrets(caplog) -> None:
    caplog.set_level(logging.INFO)
    client = FakeAgentCoreRuntime(payload=_output())
    provider = AgentCoreCoachProvider(
        _RUNTIME_ARN,
        region="us-west-2",
        qualifier="DEFAULT",
        timeout_seconds=110.0,
        max_retries=0,
        client=client,
    )
    provider.assess(
        CoachRequest(
            thread_id="notebook-secret-id",
            student_message="I think option B is better because of privacy.",
            current_stage="problem_identification",
            response_detail="short",
        )
    )
    events = [
        json.loads(record.message)
        for record in caplog.records
        if record.message.startswith("{") and "coach_turn_perf" in record.message
    ]
    assert events
    payload = events[-1]
    assert payload["event"] == "coach_turn_perf"
    assert_payload_is_safe(
        {key: value for key, value in payload.items() if key != "event"}
    )
    blob = json.dumps(payload)
    assert "I think option B" not in blob
    assert "notebook-secret-id" not in blob
    assert "Bearer" not in blob
    assert payload["agentcore_invoke_ms"] >= 0
    assert payload["agentcore_call_count"] == 1
    assert payload["success"] is True


def test_timeout_still_emits_agentcore_and_total(caplog) -> None:
    caplog.set_level(logging.INFO)
    client = FakeAgentCoreRuntime(error=TimeoutError("coach-timeout"))
    provider = AgentCoreCoachProvider(
        _RUNTIME_ARN,
        region="us-west-2",
        qualifier="DEFAULT",
        timeout_seconds=110.0,
        max_retries=0,
        client=client,
    )
    with pytest.raises(ProviderUnavailableError) as raised:
        provider.assess(
            CoachRequest(
                thread_id="thread-demo",
                student_message="I think option B is better.",
                current_stage="problem_identification",
                response_detail="short",
            )
        )
    assert raised.value.category == "timeout"
    events = [
        json.loads(record.message)
        for record in caplog.records
        if record.message.startswith("{") and "coach_turn_perf" in record.message
    ]
    assert events
    payload = events[-1]
    assert payload["failure_category"] == "timeout"
    assert payload["agentcore_invoke_ms"] >= 0
    assert payload["request_total_ms"] >= 0
    assert payload["success"] is False


def test_begin_perf_rejects_unsafe_keys() -> None:
    perf = begin_coach_turn_perf()
    perf.set("student_message", "secret")
    perf.set("prompt", "system prompt")
    assert "student_message" not in perf.fields
    assert set(perf.fields).issubset(SAFE_PERF_FIELDS)


def test_retrieval_failure_still_emits_timing(caplog, tmp_path) -> None:
    from backend.application import CoachApplicationService
    from backend.learning_service import LearningProgressService
    from backend.repositories import (
        SQLiteNotebookRepository,
        SQLitePhaseTransitionRepository,
    )
    from backend.retrieval import RetrievalQuery, RetrievalResult
    from backend.source_library import add_text_source
    from backend.student_store import StudentStore
    from backend.workflow import CoachWorkflow

    class _FailingRetriever:
        def retrieve(self, query: RetrievalQuery) -> RetrievalResult:
            del query
            error = RuntimeError("kb-down")
            error.category = "unavailable"
            raise error

    caplog.set_level(logging.INFO)
    store = StudentStore(tmp_path / "perf-retrieval.sqlite3")
    thread_id = store.create_thread(model_id="mock", support_mode="critical-thinking")
    add_text_source(store, thread_id, "Lecture", "Accessibility notes")
    client = FakeAgentCoreRuntime(payload=_output())
    service = CoachApplicationService(
        store,
        SQLiteNotebookRepository(store),
        CoachWorkflow(
            AgentCoreCoachProvider(
                _RUNTIME_ARN,
                region="us-west-2",
                qualifier="DEFAULT",
                timeout_seconds=110.0,
                max_retries=0,
                client=client,
            ),
            SQLitePhaseTransitionRepository(store),
        ),
        LearningProgressService(
            store,
            SQLiteNotebookRepository(store),
            SQLitePhaseTransitionRepository(store),
        ),
        retriever=_FailingRetriever(),
    )
    with pytest.raises(Exception):
        service.submit(
            CoachRequest(
                thread_id=thread_id,
                student_message="What does the lecture say about accessibility?",
                current_stage="problem_identification",
                response_detail="short",
                idempotency_key="retrieval-fail",
            )
        )
    events = [
        json.loads(record.message)
        for record in caplog.records
        if record.message.startswith("{") and "coach_turn_perf" in record.message
    ]
    assert events
    payload = events[-1]
    assert payload["success"] is False
    assert payload["retrieval_total_ms"] >= 0
    assert payload["failure_category"]
