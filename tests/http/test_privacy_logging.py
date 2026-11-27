"""Privacy-safe coach logging regressions."""

from __future__ import annotations

import json
import logging

from fastapi.testclient import TestClient

from backend.api import create_app
from backend.student_store import StudentStore


def test_http_request_log_correlates_the_client_request_id(tmp_path, caplog):
    """The access log carries the same opaque request id the browser sent.

    Browser TIMING lines, the coach-turn log and ``coach_turn_perf`` already
    use this id; the per-request access log must correlate with them too.
    """
    store = StudentStore(tmp_path / "privacy-rid.sqlite3")
    client = TestClient(create_app(store))
    request_id = "0f0e1d2c-3b4a-5968-7788-990011223344"

    with caplog.at_level(logging.INFO, logger="co_design.operational"):
        response = client.get("/api/v1/health", headers={"X-Request-ID": request_id})

    assert response.status_code == 200
    events = [
        json.loads(record.message)
        for record in caplog.records
        if record.message.startswith("{") and "http_request" in record.message
    ]
    assert events
    assert events[-1]["request_id"] == request_id
    assert "thread_id" not in events[-1]
    assert "student_message" not in events[-1]


def test_coach_turn_logs_omit_thread_id_and_message_text(tmp_path, caplog):
    store = StudentStore(tmp_path / "privacy-logs.sqlite3")
    thread_id = store.create_thread(model_id="mock", support_mode="critical-thinking")
    client = TestClient(create_app(store))
    secret_message = "PRIVACY_MARKER_student_claim_should_not_appear"

    with caplog.at_level(logging.INFO, logger="backend.api"):
        response = client.post(
            "/api/v1/coach/turn",
            json={
                "thread_id": thread_id,
                "student_message": secret_message,
                "current_stage": "problem_identification",
                "response_detail": "short",
                "idempotency_key": "privacy-log-1",
            },
        )

    assert response.status_code == 200, response.text
    joined = "\n".join(record.getMessage() for record in caplog.records)
    assert "coach_turn request" in joined
    assert "coach_turn ok" in joined
    assert thread_id not in joined
    assert secret_message not in joined
    assert "PRIVACY_MARKER" not in joined
