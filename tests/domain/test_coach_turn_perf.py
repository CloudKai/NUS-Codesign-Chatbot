"""Privacy-safe coach_turn_perf emission tests."""

from __future__ import annotations

import json
import logging

import pytest

from backend.agentcore_provider import AgentCoreCoachProvider
from backend.domain import (
    CoachRequest,
)
from backend.providers import ProviderUnavailableError
from backend.turn_perf import (
    SAFE_PERF_FIELDS,
    assert_payload_is_safe,
    begin_coach_turn_perf,
    emit_coach_turn_perf,
    reset_coach_turn_perf,
)
from fake_agentcore_runtime import FakeAgentCoreRuntime

_RUNTIME_ARN = (
    "arn:aws:bedrock-agentcore:us-west-2:123456789012:runtime/test-harness"
)


def _timing_values(caplog) -> dict[str, float]:
    """Parse ``TIMING <span> <seconds>s`` lines from captured logs."""
    values: dict[str, float] = {}
    for record in caplog.records:
        parts = str(record.message).split()
        if len(parts) < 3 or parts[0] != "TIMING":
            continue
        if parts[1].startswith("request_id="):
            continue
        values[parts[1]] = float(parts[2].rstrip("s"))
    return values


def _output() -> dict:
    """Return a lightweight coaching fast-chat payload."""
    return {
        "mode": "coaching",
        "response_text": "What trade-off still needs evidence?",
        "recommendation": "stay",
        "recommendation_rationale": "More evidence is still needed.",
        "citations": [],
        "needs_source_retrieval": False,
    }


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
    timings = _timing_values(caplog)
    assert timings.keys() >= {
        "auth",
        "student_state",
        "memory",
        "retrieval",
        "kb_sdk",
        "kb_validate",
        "context_build",
        "agent",
        "persistence",
        "TOTAL",
    }
    assert "request_id=-" in " ".join(record.message for record in caplog.records)
    assert timings["agent"] >= 0
    assert timings["TOTAL"] >= 0
    assert all("I think option B" not in record.message for record in caplog.records)


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


def test_configure_operational_loggers_enables_info_without_root_debug():
    from backend.operational_metrics import configure_operational_loggers

    root = logging.getLogger()
    previous_root = root.level
    retrieve_logger = logging.getLogger("backend.bedrock_retrieve")
    agentcore_logger = logging.getLogger("backend.agentcore_provider")
    perf_logger = logging.getLogger("co_design.turn_perf")
    previous_retrieve = retrieve_logger.level
    previous_agentcore = agentcore_logger.level
    previous_perf = perf_logger.level
    try:
        root.setLevel(logging.WARNING)
        retrieve_logger.setLevel(logging.NOTSET)
        agentcore_logger.setLevel(logging.NOTSET)
        perf_logger.setLevel(logging.NOTSET)
        configure_operational_loggers()
        assert retrieve_logger.level == logging.INFO
        assert agentcore_logger.level == logging.INFO
        assert perf_logger.level == logging.INFO
        assert retrieve_logger.isEnabledFor(logging.INFO)
        assert agentcore_logger.isEnabledFor(logging.INFO)
        assert perf_logger.isEnabledFor(logging.INFO)
        assert root.level == logging.WARNING
    finally:
        root.setLevel(previous_root)
        retrieve_logger.setLevel(previous_retrieve)
        agentcore_logger.setLevel(previous_agentcore)
        perf_logger.setLevel(previous_perf)


def test_snapshot_computes_service_latency_fields() -> None:
    perf = begin_coach_turn_perf()
    try:
        perf.set("notebook_load_ms", 10)
        perf.set("history_load_ms", 20)
        perf.set("source_load_ms", 5)
        perf.set("memory_load_ms", 3)
        perf.set("prompt_compose_ms", 8)
        perf.set("context_planner_ms", 2)
        perf.set("agentcore_invoke_ms", 100)
        perf.set("persist_turn_ms", 7)
        perf.set("idempotency_complete_ms", 1)
        snapshot = perf.snapshot()
        assert snapshot["student_state_ms"] == 35.0
        assert snapshot["memory_load_ms"] == 3
        assert snapshot["context_build_ms"] == 10.0
        assert snapshot["agent_ms"] == 100
        assert snapshot["persistence_ms"] == 8.0
    finally:
        reset_coach_turn_perf()


def test_emit_logs_timing_seconds_without_student_text(caplog) -> None:
    caplog.set_level(logging.INFO)
    perf = begin_coach_turn_perf()
    perf.set("notebook_load_ms", 12)
    perf.set("history_load_ms", 4)
    perf.set("source_load_ms", 2)
    perf.set("memory_load_ms", 1)
    perf.set("retrieval_total_ms", 30)
    perf.set("prompt_compose_ms", 9)
    perf.set("agentcore_invoke_ms", 250)
    perf.set("persist_turn_ms", 8)
    perf.success = True
    payload = emit_coach_turn_perf(perf)
    assert payload["student_state_ms"] == 18.0
    timings = _timing_values(caplog)
    assert timings["student_state"] == pytest.approx(0.018, abs=0.0005)
    assert timings["memory"] == pytest.approx(0.001, abs=0.0005)
    assert timings["retrieval"] == pytest.approx(0.030, abs=0.0005)
    assert timings["context_build"] == pytest.approx(0.009, abs=0.0005)
    assert timings["agent"] == pytest.approx(0.250, abs=0.0005)
    assert timings["persistence"] == pytest.approx(0.008, abs=0.0005)
    assert timings["TOTAL"] >= 0
    blob = " ".join(record.message for record in caplog.records)
    assert "student_message" not in blob
    assert "Bearer" not in blob
    assert "TIMING_MS request_id=" in blob
    assert "retrieval_gate_ms=" in blob
    assert "total_server_ms=" in blob


def test_submit_records_service_latency_breakdown(caplog, tmp_path) -> None:
    from backend.application import CoachApplicationService
    from backend.learning_service import LearningProgressService
    from backend.mock_provider import DeterministicCoachProvider
    from backend.repositories import (
        SQLiteNotebookRepository,
        SQLitePhaseTransitionRepository,
    )
    from backend.student_store import StudentStore
    from backend.workflow import CoachWorkflow

    caplog.set_level(logging.INFO)
    store = StudentStore(tmp_path / "perf-submit.sqlite3")
    thread_id = store.create_thread(model_id="mock", support_mode="critical-thinking")
    service = CoachApplicationService(
        store,
        SQLiteNotebookRepository(store),
        CoachWorkflow(
            DeterministicCoachProvider(),
            SQLitePhaseTransitionRepository(store),
        ),
        LearningProgressService(
            store,
            SQLiteNotebookRepository(store),
            SQLitePhaseTransitionRepository(store),
        ),
    )
    service.submit(
        CoachRequest(
            thread_id=thread_id,
            student_message="I think option B is better because of privacy.",
            current_stage="problem_identification",
            response_detail="short",
            idempotency_key="service-timing",
        )
    )
    events = [
        json.loads(record.message)
        for record in caplog.records
        if record.message.startswith("{") and "coach_turn_perf" in record.message
    ]
    assert events
    payload = events[-1]
    assert_payload_is_safe(
        {key: value for key, value in payload.items() if key != "event"}
    )
    assert payload["memory_load_ms"] >= 0
    assert payload["student_state_ms"] >= 0
    assert payload["retrieval_total_ms"] >= 0
    assert payload["context_build_ms"] >= 0
    assert payload["agent_ms"] >= 0
    assert payload["persistence_ms"] >= 0
    assert payload["request_total_ms"] >= payload["agent_ms"]
    timings = _timing_values(caplog)
    assert timings["TOTAL"] >= 0
    assert "I think option B" not in json.dumps(payload)
    assert all("I think option B" not in record.message for record in caplog.records)


def _perf_event(caplog) -> dict:
    """Return the last coach_turn_perf JSON object from captured logs."""
    events = [
        json.loads(record.message)
        for record in caplog.records
        if record.message.startswith("{") and "coach_turn_perf" in record.message
    ]
    assert events
    return events[-1]


def test_runtime_model_provenance_is_recorded_distinct_from_configured(
    caplog,
) -> None:
    caplog.set_level(logging.INFO)
    payload = _output()
    payload["runtime_model_role"] = "fast_chat"
    payload["runtime_model_provider"] = "bedrock"
    payload["runtime_model_id"] = "global.anthropic.claude-haiku-4-5-20251001-v1:0"
    payload["runtime_model_region"] = "us-west-2"
    payload["runtime_strands_agents"] = "1.52.0"
    client = FakeAgentCoreRuntime(payload=payload)
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
    recorded = _perf_event(caplog)
    assert recorded["runtime_model_role"] == "fast_chat"
    assert recorded["runtime_model_provider"] == "bedrock"
    assert (
        recorded["runtime_model_id"]
        == "global.anthropic.claude-haiku-4-5-20251001-v1:0"
    )
    assert recorded["runtime_model_region"] == "us-west-2"
    assert recorded["runtime_strands_agents"] == "1.52.0"
    assert "model_id" in recorded
    assert "runtime_model_id" in recorded
    blob = json.dumps(recorded)
    assert "I think option B" not in blob
    assert "notebook-secret-id" not in blob


def test_absent_runtime_provenance_is_tolerated(caplog) -> None:
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
            thread_id="thread-demo",
            student_message="I think option B is better.",
            current_stage="problem_identification",
            response_detail="short",
        )
    )
    recorded = _perf_event(caplog)
    assert "runtime_model_id" not in recorded
    assert "runtime_model_provider" not in recorded
    assert "runtime_model_role" not in recorded
    assert "runtime_model_region" not in recorded
    assert "runtime_strands_agents" not in recorded
    assert recorded["success"] is True
    assert recorded["agentcore_call_count"] == 1


def test_malformed_runtime_provenance_is_ignored(caplog) -> None:
    caplog.set_level(logging.INFO)
    payload = _output()
    payload["runtime_model_id"] = "I think option B is better because of privacy."
    payload["runtime_model_role"] = {"nested": "fast_chat"}
    payload["runtime_model_provider"] = 12345
    payload["runtime_model_region"] = "x" * 200
    payload["runtime_strands_agents"] = "1.52.0; student said secrets"
    client = FakeAgentCoreRuntime(payload=payload)
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
            thread_id="thread-demo",
            student_message="I think option B is better because of privacy.",
            current_stage="problem_identification",
            response_detail="short",
        )
    )
    recorded = _perf_event(caplog)
    assert "runtime_model_id" not in recorded
    assert "runtime_model_role" not in recorded
    assert "runtime_model_provider" not in recorded
    assert "runtime_model_region" not in recorded
    assert "runtime_strands_agents" not in recorded
    assert "I think option B" not in json.dumps(recorded)


def test_event_loop_cycle_count_is_recorded_when_runtime_sends_it(caplog) -> None:
    """FastAPI copies cycle count when present. LIVE TRACE REQUIRED for rate."""
    caplog.set_level(logging.INFO)
    payload = _output()
    payload["event_loop_cycle_count"] = 2
    client = FakeAgentCoreRuntime(payload=payload)
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
            thread_id="thread-demo",
            student_message="I think option B is better.",
            current_stage="problem_identification",
            response_detail="short",
        )
    )
    recorded = _perf_event(caplog)
    assert recorded["event_loop_cycle_count"] == 2
    assert recorded["agentcore_call_count"] == 1


def test_structured_output_recovery_flags_are_recorded(caplog) -> None:
    """Recovery telemetry is copied when the runtime stamps it. No student text."""
    caplog.set_level(logging.INFO)
    payload = _output()
    payload["event_loop_cycle_count"] = 2
    payload["structured_output_recovery_used"] = True
    payload["structured_output_failure_category"] = "end_turn_without_output_tool"
    payload["first_cycle_stop_reason"] = "end_turn"
    payload["first_cycle_tool_choice_installed"] = True
    client = FakeAgentCoreRuntime(payload=payload)
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
            thread_id="thread-demo",
            student_message="I think option B is better.",
            current_stage="problem_identification",
            response_detail="short",
        )
    )
    recorded = _perf_event(caplog)
    assert recorded["structured_output_recovery_used"] is True
    assert recorded["structured_output_failure_category"] == (
        "end_turn_without_output_tool"
    )
    assert recorded["first_cycle_stop_reason"] == "end_turn"
    assert recorded["first_cycle_tool_choice_installed"] is True
    assert recorded["agentcore_call_count"] == 1
    assert "I think option B" not in json.dumps(recorded)


def test_deep_review_runtime_provenance_is_recorded(caplog) -> None:
    caplog.set_level(logging.INFO)
    review_payload = {
        "response_text": "Formative deep review of progress.",
        "strengths": ["The contribution named a concrete constraint."],
        "areas_to_develop": ["Name who is affected at night."],
        "synthesis": "The work is ready to advance.",
        "readiness_candidate": True,
        "review_depth": "deep",
        "current_stage": "problem_identification",
        "recommendation": "advance",
        "confidence": 0.9,
        "readiness_evidence": ["The candidate met the current-stage bar."],
        "missing_requirements": [],
        "rationale_summary": "The contribution is ready to advance.",
        "working_conclusion": "Elderly caregivers are scarce in Singapore.",
        "runtime_model_role": "review_deep",
        "runtime_model_provider": "bedrock",
        "runtime_model_id": "global.anthropic.claude-sonnet-4-6",
        "runtime_model_region": "us-west-2",
    }
    client = FakeAgentCoreRuntime(deep_payload=review_payload)
    provider = AgentCoreCoachProvider(
        _RUNTIME_ARN,
        region="us-west-2",
        qualifier="DEFAULT",
        timeout_seconds=110.0,
        max_retries=0,
        client=client,
    )
    begin_coach_turn_perf()
    try:
        provider.assess(
            CoachRequest(
                thread_id="thread-demo",
                student_message="I think option B is better.",
                current_stage="problem_identification",
                response_detail="short",
                specialist="review",
            )
        )
    finally:
        recorded = emit_coach_turn_perf()
        reset_coach_turn_perf()
    assert recorded is not None
    assert recorded["runtime_model_role"] == "review_deep"
    assert recorded["runtime_model_id"] == "global.anthropic.claude-sonnet-4-6"
    assert recorded["runtime_model_provider"] == "bedrock"
    blob = json.dumps(recorded)
    assert "I think option B" not in blob


def test_runtime_model_fields_are_on_the_privacy_allow_list() -> None:
    assert "runtime_model_role" in SAFE_PERF_FIELDS
    assert "runtime_model_provider" in SAFE_PERF_FIELDS
    assert "runtime_model_id" in SAFE_PERF_FIELDS
    assert "runtime_model_region" in SAFE_PERF_FIELDS
    assert "runtime_strands_agents" in SAFE_PERF_FIELDS
    assert "event_loop_cycle_count" in SAFE_PERF_FIELDS
    assert "structured_output_recovery_used" in SAFE_PERF_FIELDS
    assert "structured_output_failure_category" in SAFE_PERF_FIELDS
    assert "first_cycle_stop_reason" in SAFE_PERF_FIELDS
    assert "first_cycle_tool_choice_installed" in SAFE_PERF_FIELDS
    assert "request_id" in SAFE_PERF_FIELDS
    assert "submit_notebook_lookup_ms" in SAFE_PERF_FIELDS
    assert "history_source_join_ms" in SAFE_PERF_FIELDS
