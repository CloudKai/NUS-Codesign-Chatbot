"""Deterministic tests for the in-process coach rate limiter."""

from __future__ import annotations

import threading
from concurrent.futures import ThreadPoolExecutor

import pytest
from fastapi.testclient import TestClient

from backend.api import create_app
from backend.application import CoachApplicationService
from backend.rate_limit import (
    CoachRateLimiter,
    LoginStartLimiter,
    RateLimitExceeded,
    reset_coach_rate_limiter_for_tests,
    reset_login_start_limiter_for_tests,
)
from backend.student_store import StudentStore


@pytest.fixture(autouse=True)
def _reset_limiter():
    reset_coach_rate_limiter_for_tests()
    reset_login_start_limiter_for_tests()
    yield
    reset_coach_rate_limiter_for_tests()
    reset_login_start_limiter_for_tests()


def test_limiter_releases_after_success_and_exception():
    limiter = CoachRateLimiter(
        max_active_per_user=1,
        requests_per_minute=8,
        max_concurrent_model_calls=20,
    )
    with limiter.limit("user-a"):
        pass
    with limiter.limit("user-a"):
        pass
    with pytest.raises(RuntimeError):
        with limiter.limit("user-a"):
            raise RuntimeError("boom")
    with limiter.limit("user-a"):
        pass


def test_limiter_isolates_users_and_returns_retry_after():
    limiter = CoachRateLimiter(
        max_active_per_user=1,
        requests_per_minute=1,
        max_concurrent_model_calls=20,
    )
    limiter.acquire("user-a")
    with pytest.raises(RateLimitExceeded) as active:
        limiter.acquire("user-a")
    assert active.value.retry_after_seconds >= 1
    limiter.acquire("user-b")
    limiter.release("user-a")
    limiter.release("user-b")
    with pytest.raises(RateLimitExceeded) as burst:
        limiter.acquire("user-a")
    assert burst.value.retry_after_seconds >= 1


def test_api_returns_429_with_retry_after_for_active_limit(tmp_path, monkeypatch):
    """Distinct in-flight coach executions for one user are limited to one."""
    from backend import rate_limit as rate_limit_module

    limiter = CoachRateLimiter(
        max_active_per_user=1,
        requests_per_minute=20,
        max_concurrent_model_calls=20,
    )
    monkeypatch.setattr(rate_limit_module, "_LIMITER", limiter)

    store = StudentStore(tmp_path / "rate-limit.sqlite3")
    thread_id = store.create_thread(model_id="mock", support_mode="critical-thinking")
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
            json={
                "thread_id": thread_id,
                "student_message": "first",
                "current_stage": "focus",
                "response_detail": "short",
                "idempotency_key": "rate-1",
            },
        )

    with ThreadPoolExecutor(max_workers=1) as executor:
        future = executor.submit(first_call)
        assert started.wait(timeout=2)
        second = client.post(
            "/api/v1/coach/turn",
            json={
                "thread_id": thread_id,
                "student_message": "second",
                "current_stage": "focus",
                "response_detail": "short",
                "idempotency_key": "rate-2",
            },
        )
        release.set()
        first = future.result(timeout=5)

    assert first.status_code == 200
    assert second.status_code == 429
    assert second.headers.get("retry-after")
    assert "one active" in second.json()["detail"].lower()


def test_api_same_key_waiters_converge_under_active_limit(tmp_path, monkeypatch):
    """Same-key concurrent callers must wait/replay, not receive HTTP 429."""
    from backend import rate_limit as rate_limit_module

    limiter = CoachRateLimiter(
        max_active_per_user=1,
        requests_per_minute=20,
        max_concurrent_model_calls=20,
    )
    monkeypatch.setattr(rate_limit_module, "_LIMITER", limiter)

    store = StudentStore(tmp_path / "rate-limit-same-key.sqlite3")
    thread_id = store.create_thread(model_id="mock", support_mode="critical-thinking")
    client = TestClient(create_app(store))
    started = threading.Event()
    release = threading.Event()
    original = CoachApplicationService._submit_once
    provider_calls = {"count": 0}
    lock = threading.Lock()

    def slow_submit_once(self, request, **kwargs):
        with lock:
            provider_calls["count"] += 1
        started.set()
        assert release.wait(timeout=3)
        return original(self, request, **kwargs)

    monkeypatch.setattr(CoachApplicationService, "_submit_once", slow_submit_once)
    payload = {
        "thread_id": thread_id,
        "student_message": "Assess this shared claim.",
        "current_stage": "focus",
        "response_detail": "short",
        "idempotency_key": "same-key-under-limit",
    }

    def first_call():
        return client.post("/api/v1/coach/turn", json=payload)

    def second_call():
        assert started.wait(timeout=3)
        return client.post("/api/v1/coach/turn", json=payload)

    with ThreadPoolExecutor(max_workers=2) as executor:
        first_future = executor.submit(first_call)
        second_future = executor.submit(second_call)
        assert started.wait(timeout=3)
        release.set()
        first = first_future.result(timeout=8)
        second = second_future.result(timeout=8)

    assert first.status_code == 200, first.text
    assert second.status_code == 200, second.text
    assert first.json() == second.json()
    assert provider_calls["count"] == 1
    assert len(store.get_messages(thread_id)) == 2


def test_limiter_allows_concurrent_distinct_users():
    """Two different authenticated owners may hold active slots simultaneously."""
    limiter = CoachRateLimiter(
        max_active_per_user=1,
        requests_per_minute=8,
        max_concurrent_model_calls=20,
    )
    barrier = threading.Barrier(2)
    results: list[str] = []

    def hold(user_id: str) -> None:
        with limiter.limit(user_id):
            barrier.wait(timeout=2)
            results.append(user_id)

    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = [
            executor.submit(hold, "user-a"),
            executor.submit(hold, "user-b"),
        ]
        for future in futures:
            future.result(timeout=5)

    assert sorted(results) == ["user-a", "user-b"]


def test_login_start_limiter_enforces_per_client_and_global_ceilings():
    limiter = LoginStartLimiter(per_client_per_minute=1, global_per_minute=2)
    limiter.acquire("1.1.1.1")
    with pytest.raises(RateLimitExceeded) as per_client:
        limiter.acquire("1.1.1.1")
    assert per_client.value.retry_after_seconds >= 1
    limiter.acquire("2.2.2.2")
    with pytest.raises(RateLimitExceeded) as global_limit:
        limiter.acquire("3.3.3.3")
    assert global_limit.value.retry_after_seconds >= 1


def test_auth_login_rate_limit_short_circuits_before_oauth_write(tmp_path, monkeypatch):
    """Rate-limited login starts redirect without writing OAuth state."""
    from backend import auth_routes

    class _BlockingLimiter:
        def acquire(self, client_key: str) -> None:
            raise RateLimitExceeded(3, "Login start rate limit exceeded; retry shortly")

    monkeypatch.setattr(auth_routes, "get_login_start_limiter", lambda: _BlockingLimiter())
    store = StudentStore(tmp_path / "login-limit.sqlite3")
    client = TestClient(create_app(store))
    response = client.get("/api/v1/auth/login", follow_redirects=False)
    assert response.status_code == 302
    assert "auth_error=1" in response.headers["location"]
    assert response.headers.get("Retry-After") == "3"
    # No durable OAuth state rows should exist when begin_login never runs.
    assert store.consume_oauth_login_state("any") is None


def test_cognito_callback_error_log_is_allow_listed(tmp_path, caplog):
    """Callback error query values must not be logged verbatim."""
    from backend.auth_routes import _cognito_callback_error_category

    assert _cognito_callback_error_category("access_denied") == "access_denied"
    assert (
        _cognito_callback_error_category('<script>alert(1)</script>')
        == "unlisted"
    )

    store = StudentStore(tmp_path / "callback-log.sqlite3")
    client = TestClient(create_app(store))
    with caplog.at_level("INFO"):
        response = client.get(
            "/api/v1/auth/callback",
            params={"error": "attacker-controlled payload"},
            follow_redirects=False,
        )
    assert response.status_code == 302
    assert "auth_error=1" in response.headers["location"]
    joined = "\n".join(record.getMessage() for record in caplog.records)
    assert "attacker-controlled payload" not in joined
    assert "category=unlisted" in joined
