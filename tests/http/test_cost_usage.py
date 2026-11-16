"""Public HTTP generation telemetry contracts with deterministic providers."""

from __future__ import annotations

import json
import logging
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from backend.api import create_app
from backend.student_store import StudentStore


def _events(caplog: pytest.LogCaptureFixture) -> list[dict]:
    """Read only the documented JSON usage events from captured operator logs."""
    result = []
    for record in caplog.records:
        if record.name == "co_design.usage":
            result.append(json.loads(record.getMessage()))
    return result


def test_saved_answer_and_replay_do_not_double_count_generation(
    tmp_path: Path, caplog: pytest.LogCaptureFixture,
) -> None:
    """A retry recovers the answer while the cost ledger counts one generation."""
    caplog.set_level(logging.INFO, logger="co_design.usage")
    store = StudentStore(tmp_path / "usage.sqlite3")
    thread_id = store.create_thread(model_id="mock", support_mode="critical-thinking")
    with TestClient(create_app(store)) as client:
        body = {
            "thread_id": thread_id,
            "student_message": "PRIVATE STUDENT TEXT improve accessibility",
            "current_stage": "problem_identification",
            "response_detail": "short",
            "idempotency_key": "PRIVATE-RETRY-KEY",
        }
        first = client.post("/api/v1/coach/turn", json=body)
        replay = client.post("/api/v1/coach/turn", json=body)
    assert first.status_code == replay.status_code == 200
    events = _events(caplog)
    attempts = [event for event in events if event["event"] == "generation_usage"]
    outcomes = [event for event in events if event["event"] == "operation_usage"]
    assert len(attempts) == 1
    assert attempts[0]["provider"] == "mock"
    assert attempts[0]["input_tokens"] == 0
    assert len(outcomes) == 2
    assert [event["answer_delivered"] for event in outcomes] == [True, False]
    assert [event["replayed"] for event in outcomes] == [False, True]
    assert len({event["session_key"] for event in outcomes}) == 1
    logged = json.dumps(events)
    assert thread_id not in logged
    assert "PRIVATE" not in logged
    assert "student_message" not in logged


@pytest.mark.parametrize("fails", [False, True])
def test_explicit_deep_review_has_its_own_usage_outcome(
    tmp_path: Path, caplog: pytest.LogCaptureFixture,
    monkeypatch: pytest.MonkeyPatch, fails: bool,
) -> None:
    """A completed review is counted without inflating delivered chat answers."""
    import time

    from backend.student_journey import THINKING_STAGES, normalize_journey
    from backend.mock_provider import DeterministicCoachProvider
    from backend.providers import ProviderUnavailableError
    from backend.domain import CoachRequest, ProviderAssessmentResult
    import backend.owner_context as owner_context

    class ReviewProvider(DeterministicCoachProvider):
        """Deterministic provider boundary with an optional review failure."""

        def assess(self, request: CoachRequest) -> ProviderAssessmentResult:
            """Fail only for the requested synthetic failure case."""
            if fails:
                raise ProviderUnavailableError("PRIVATE failed review")
            return super().assess(request)

    monkeypatch.setattr(owner_context, "configured_coach_provider", ReviewProvider)
    caplog.set_level(logging.INFO, logger="co_design.usage")
    store = StudentStore(tmp_path / "review-usage.sqlite3")
    thread_id = store.create_thread(model_id="mock", support_mode="critical-thinking")
    journey = normalize_journey(None)
    journey["completed_stages"] = [stage.id for stage in THINKING_STAGES]
    store.update_thread(thread_id, metadata={"learning_journey": journey})
    with TestClient(create_app(store)) as client:
        result = client.post(f"/api/v1/threads/{thread_id}/deep-review", json={})
        assert result.status_code == 200
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            result = client.get(f"/api/v1/threads/{thread_id}/deep-review")
            if result.json()["status"] in {"completed", "failed"}:
                break
            time.sleep(0.01)
        assert result.json()["status"] == ("failed" if fails else "completed")
    events = _events(caplog)
    reviews = [event for event in events if event["event"] == "operation_usage" and event["kind"] == "deep_review"]
    assert len(reviews) == 1
    assert reviews[0]["success"] is not fails
    assert reviews[0]["answer_delivered"] is False
    assert reviews[0]["generation_attempts"] == 1
    attempts = [event for event in events if event["event"] == "generation_usage"]
    assert attempts[0]["kind"] == "deep_review"
    assert attempts[0]["operation_id"] == reviews[0]["operation_id"]
    assert "PRIVATE" not in json.dumps(events)


def test_failed_generation_is_counted_and_retry_keeps_both_attempts(
    tmp_path: Path, caplog: pytest.LogCaptureFixture, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A provider failure is not free, even when only a later response has meters."""
    from backend.agentcore_provider import AgentCoreCoachProvider
    from fake_agentcore_runtime import FakeBody
    import backend.owner_context as owner_context

    class Runtime:
        """External SDK boundary with one timeout then one metered response."""

        calls = 0

        def invoke_agent_runtime(self, **kwargs: object) -> dict:
            """Return deterministic usage without contacting a provider."""
            self.calls += 1
            if self.calls == 1:
                raise TimeoutError("PRIVATE SDK ERROR")
            return {"contentType": "application/json", "response": FakeBody(json.dumps({
                "mode": "coaching", "response_text": "Which constraint matters?",
                "recommendation": "stay", "recommendation_rationale": "Explain a constraint.",
                "citations": [], "hmw_scaffold_ready": False,
                "needs_source_retrieval": False, "out_of_scope": False,
                "model_input_tokens": 120, "model_output_tokens": 30,
                "cache_read_input_tokens": 10, "cache_write_input_tokens": 5,
            }).encode())}

    runtime = Runtime()
    provider = AgentCoreCoachProvider(
        "arn:aws:bedrock-agentcore:us-west-2:123456789012:runtime/test",
        region="us-west-2", client=runtime, max_retries=0,
    )
    monkeypatch.setattr(owner_context, "configured_coach_provider", lambda: provider)
    caplog.set_level(logging.INFO, logger="co_design.usage")
    store = StudentStore(tmp_path / "failure-usage.sqlite3")
    thread_id = store.create_thread(model_id="mock", support_mode="critical-thinking")
    body = {"thread_id": thread_id, "student_message": "Improve access for older users",
            "current_stage": "problem_identification", "response_detail": "short"}
    with TestClient(create_app(store)) as client:
        assert client.post("/api/v1/coach/turn", json={**body, "idempotency_key": "failed"}).status_code == 503
        assert client.post("/api/v1/coach/turn", json={**body, "idempotency_key": "retry"}).status_code == 200
    events = _events(caplog)
    attempts = [event for event in events if event["event"] == "generation_usage"]
    assert len(attempts) == 2
    assert [event["provider"] for event in attempts] == ["agentcore", "agentcore"]
    assert [event["success"] for event in attempts] == [False, True]
    assert [event["input_tokens"] for event in attempts] == [None, 120]
    assert [event["output_tokens"] for event in attempts] == [None, 30]
    assert [event["model_calls"] for event in attempts] == [None, None]
    assert "PRIVATE" not in json.dumps(events)


@pytest.mark.parametrize("envelope", [None, "coach_turn", "result", "output"])
def test_harness_recovery_keeps_failed_call_tokens_and_one_delivered_answer(
    tmp_path: Path, caplog: pytest.LogCaptureFixture, monkeypatch: pytest.MonkeyPatch,
    envelope: str | None,
) -> None:
    """Structured-output recovery adds usage instead of replacing earlier meters."""
    import backend.owner_context as owner_context
    from backend.agentcore_provider import AgentCoreCoachProvider
    from fake_agentcore_runtime import FakeAgentCoreRuntime

    payloads = [
        {"ok": False, "error": True, "category": "structured_output_failure",
         "model_input_tokens": 100, "model_output_tokens": 40},
        {"mode": "coaching", "response_text": "Which constraint matters?",
         "recommendation": "stay", "recommendation_rationale": "Explain the constraint.",
         "citations": [], "hmw_scaffold_ready": False,
         "needs_source_retrieval": False, "out_of_scope": False,
         "model_input_tokens": 150, "model_output_tokens": 50},
    ]
    runtime = FakeAgentCoreRuntime(payloads=[{envelope: payload} if envelope else payload for payload in payloads])
    provider = AgentCoreCoachProvider(
        "arn:aws:bedrock-agentcore:us-west-2:123456789012:runtime/test",
        region="us-west-2", client=runtime, max_retries=0,
    )
    monkeypatch.setattr(owner_context, "configured_coach_provider", lambda: provider)
    caplog.set_level(logging.INFO, logger="co_design.usage")
    store = StudentStore(tmp_path / "recovery-usage.sqlite3")
    thread_id = store.create_thread(model_id="mock", support_mode="critical-thinking")
    with TestClient(create_app(store)) as client:
        response = client.post("/api/v1/coach/turn", json={
            "thread_id": thread_id, "student_message": "Older people need accessible routes",
            "current_stage": "problem_identification", "response_detail": "short",
            "idempotency_key": "recovery",
        })
        assert response.status_code == 200
    events = _events(caplog)
    attempts = [event for event in events if event["event"] == "generation_usage"]
    assert [event["input_tokens"] for event in attempts] == [100, 150]
    assert [event["output_tokens"] for event in attempts] == [40, 50]
    assert [event["success"] for event in attempts] == [False, True]
    outcomes = [event for event in events if event["event"] == "operation_usage"]
    assert len(outcomes) == 1
    assert outcomes[0]["generation_attempts"] == 2
    assert outcomes[0]["answer_delivered"] is True
