"""HTTP Deep Review route: server-owned, ownership-isolated, concurrent-safe."""

from __future__ import annotations

import threading
from concurrent.futures import ThreadPoolExecutor

from fastapi.testclient import TestClient

from backend.api import create_app
from backend.application import CoachApplicationService
from backend.rate_limit import CoachRateLimiter, reset_coach_rate_limiter_for_tests
from backend.specialists.review_orchestration import (
    COUNTER_SETTINGS_KEY,
    DEEP_REVIEW_TURN_MESSAGE,
)
from backend.student_store import StudentStore


def _coach_payload(thread_id: str, message: str, key: str) -> dict[str, str]:
    """Return one mock coaching JSON body."""
    return {
        "thread_id": thread_id,
        "student_message": message,
        "current_stage": "problem_identification",
        "response_detail": "short",
        "idempotency_key": key,
    }


def test_coach_turn_cannot_choose_specialist_review(tmp_path) -> None:
    store = StudentStore(tmp_path / "http-dr-hint.sqlite3")
    thread_id = store.create_thread(model_id="mock", support_mode="critical-thinking")
    client = TestClient(create_app(store))
    response = client.post(
        "/api/v1/coach/turn",
        json={
            **_coach_payload(thread_id, "I compared two constraints.", "hint-1"),
            "specialist": "review",
        },
    )
    assert response.status_code == 200
    body = response.json()
    assert body["assessment"]["guidance_questions"]
    assert body["assessment"].get("review_depth") != "deep"
    metadata = dict((store.get_thread(thread_id) or {}).get("metadata") or {})
    assert metadata.get("deep_review_snapshot") is None


def test_deep_review_body_rejects_privileged_fields(tmp_path) -> None:
    store = StudentStore(tmp_path / "http-dr-extra.sqlite3")
    thread_id = store.create_thread(model_id="mock", support_mode="critical-thinking")
    client = TestClient(create_app(store))
    response = client.post(
        f"/api/v1/threads/{thread_id}/deep-review",
        json={"specialist": "review", "current_stage": "reflection"},
    )
    assert response.status_code == 422


def test_ineligible_deep_review_returns_400(tmp_path) -> None:
    store = StudentStore(tmp_path / "http-dr-400.sqlite3")
    thread_id = store.create_thread(model_id="mock", support_mode="critical-thinking")
    client = TestClient(create_app(store))
    response = client.post(
        f"/api/v1/threads/{thread_id}/deep-review",
        json={"idempotency_key": "too-soon"},
    )
    assert response.status_code == 400
    assert "not available" in response.json()["detail"].lower()


def test_eligible_deep_review_endpoint_invokes_server_owned_review(tmp_path) -> None:
    store = StudentStore(tmp_path / "http-dr-ok.sqlite3")
    thread_id = store.create_thread(model_id="mock", support_mode="critical-thinking")
    store.update_thread(thread_id, metadata={COUNTER_SETTINGS_KEY: 3})
    client = TestClient(create_app(store))
    response = client.post(
        f"/api/v1/threads/{thread_id}/deep-review",
        json={"idempotency_key": "deep-ok"},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["assessment"]["recommendation"] == "stay"
    assert body["pending_transition"] is None
    assert body["auto_advanced_to"] is None
    assert body["assessment"]["review_depth"] == "deep"
    metadata = dict((store.get_thread(thread_id) or {}).get("metadata") or {})
    assert int(metadata.get(COUNTER_SETTINGS_KEY, -1)) == 0
    snapshot = metadata.get("deep_review_snapshot")
    assert isinstance(snapshot, dict)
    assert snapshot["review_trigger"] == "explicit"
    journey = dict(metadata.get("learning_journey") or {})
    assert journey.get("current_stage") == "problem_identification"


def test_missing_notebook_deep_review_is_404(tmp_path) -> None:
    store = StudentStore(tmp_path / "http-dr-404.sqlite3")
    client = TestClient(create_app(store))
    response = client.post(
        "/api/v1/threads/does-not-exist/deep-review",
        json={},
    )
    assert response.status_code == 404


def test_deep_review_same_notebook_concurrency_is_rejected(tmp_path, monkeypatch) -> None:
    from backend import rate_limit as rate_limit_module

    reset_coach_rate_limiter_for_tests()
    limiter = CoachRateLimiter(
        max_active_per_notebook=1,
        max_active_per_user=2,
        requests_per_minute=20,
        max_concurrent_model_calls=20,
    )
    monkeypatch.setattr(rate_limit_module, "_LIMITER", limiter)
    store = StudentStore(tmp_path / "http-dr-busy.sqlite3")
    thread_id = store.create_thread(model_id="mock", support_mode="critical-thinking")
    store.update_thread(thread_id, metadata={COUNTER_SETTINGS_KEY: 3})
    client = TestClient(create_app(store))
    started = threading.Event()
    release = threading.Event()
    original = CoachApplicationService._submit_once

    def slow_submit_once(self, request, **kwargs):
        started.set()
        assert release.wait(timeout=2)
        return original(self, request, **kwargs)

    monkeypatch.setattr(CoachApplicationService, "_submit_once", slow_submit_once)

    def first_call():
        return client.post(
            "/api/v1/coach/turn",
            json=_coach_payload(thread_id, "first overlapping send", "busy-1"),
        )

    with ThreadPoolExecutor(max_workers=1) as executor:
        future = executor.submit(first_call)
        assert started.wait(timeout=2)
        second = client.post(
            f"/api/v1/threads/{thread_id}/deep-review",
            json={"idempotency_key": "busy-deep"},
        )
        release.set()
        first = future.result(timeout=5)

    assert first.status_code == 200
    assert second.status_code == 429
    assert "per notebook" in second.json()["detail"].lower()
    reset_coach_rate_limiter_for_tests()


def test_another_user_cannot_invoke_deep_review(tmp_path) -> None:
    db = tmp_path / "http-dr-owner.sqlite3"
    owner_a = StudentStore(db, identifier="cognito:a")
    thread_id = owner_a.create_thread(model_id="mock", support_mode="critical-thinking")
    owner_a.update_thread(thread_id, metadata={COUNTER_SETTINGS_KEY: 3})
    owner_b = StudentStore(db, identifier="cognito:b")
    client = TestClient(create_app(owner_b))
    response = client.post(
        f"/api/v1/threads/{thread_id}/deep-review",
        json={"idempotency_key": "foreign"},
    )
    assert response.status_code == 404


def test_coach_turn_cannot_complete_deep_review_idempotency_key(tmp_path) -> None:
    store = StudentStore(tmp_path / "http-dr-poison.sqlite3")
    thread_id = store.create_thread(model_id="mock", support_mode="critical-thinking")
    client = TestClient(create_app(store))
    poisoned = client.post(
        "/api/v1/coach/turn",
        json=_coach_payload(thread_id, DEEP_REVIEW_TURN_MESSAGE, "shared-deep"),
    )
    assert poisoned.status_code == 200
    store.update_thread(thread_id, metadata={COUNTER_SETTINGS_KEY: 3})
    response = client.post(
        f"/api/v1/threads/{thread_id}/deep-review",
        json={"idempotency_key": "shared-deep"},
    )
    assert response.status_code == 409
    metadata = dict((store.get_thread(thread_id) or {}).get("metadata") or {})
    assert metadata.get("deep_review_snapshot") is None
    assert int(metadata.get(COUNTER_SETTINGS_KEY) or 0) == 3


def test_mock_review_phrasing_does_not_reset_deep_review_counter(tmp_path) -> None:
    store = StudentStore(tmp_path / "http-dr-mock-review.sqlite3")
    thread_id = store.create_thread(model_id="mock", support_mode="critical-thinking")
    store.update_thread(thread_id, metadata={COUNTER_SETTINGS_KEY: 3})
    client = TestClient(create_app(store))
    response = client.post(
        "/api/v1/coach/turn",
        json=_coach_payload(thread_id, "Can you review my progress?", "review-phrase"),
    )
    assert response.status_code == 200
    body = response.json()
    assert body["assessment"].get("review_depth") != "deep"
    metadata = dict((store.get_thread(thread_id) or {}).get("metadata") or {})
    assert metadata.get("deep_review_snapshot") is None
    assert int(metadata.get(COUNTER_SETTINGS_KEY) or 0) == 3
