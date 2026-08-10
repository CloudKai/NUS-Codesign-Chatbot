"""Privacy-safe coach logging regressions."""

from __future__ import annotations

import logging

from fastapi.testclient import TestClient

from backend.api import create_app
from backend.student_store import StudentStore


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
                "current_stage": "focus",
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
