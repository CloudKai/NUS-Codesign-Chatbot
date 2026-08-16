"""Deterministic tests for the in-process coach rate limiter."""

from __future__ import annotations

import threading
from concurrent.futures import ThreadPoolExecutor

import pytest
from fastapi.testclient import TestClient

from backend.api import create_app
from backend.application import CoachApplicationService
from backend.rate_limit import (
    GLOBAL_CAPACITY,
    NOTEBOOK_CONCURRENCY,
    USER_CONCURRENCY,
    USER_RPM,
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


def _production_limiter(**overrides: int) -> CoachRateLimiter:
    """Return a limiter with the intended production ceilings."""
    values = {
        "max_active_per_notebook": 1,
        "max_active_per_user": 2,
        "requests_per_minute": 8,
        "max_concurrent_model_calls": 120,
    }
    values.update(overrides)
    return CoachRateLimiter(**values)


def test_same_user_same_notebook_second_acquire_fails():
    limiter = _production_limiter()
    limiter.acquire("user-a", "notebook-1")
    with pytest.raises(RateLimitExceeded) as raised:
        limiter.acquire("user-a", "notebook-1")
    assert raised.value.category == NOTEBOOK_CONCURRENCY
    assert "per notebook" in raised.value.detail.lower()
    limiter.release("user-a", "notebook-1")


def test_same_user_two_notebooks_succeed_concurrently():
    limiter = _production_limiter()
    barrier = threading.Barrier(2)
    held: list[str] = []

    def hold(thread_id: str) -> None:
        with limiter.limit("user-a", thread_id):
            barrier.wait(timeout=2)
            held.append(thread_id)

    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = [
            executor.submit(hold, "notebook-1"),
            executor.submit(hold, "notebook-2"),
        ]
        for future in futures:
            future.result(timeout=5)
    assert sorted(held) == ["notebook-1", "notebook-2"]


def test_same_user_third_notebook_rejected_at_user_limit():
    limiter = _production_limiter()
    limiter.acquire("user-a", "notebook-1")
    limiter.acquire("user-a", "notebook-2")
    with pytest.raises(RateLimitExceeded) as raised:
        limiter.acquire("user-a", "notebook-3")
    assert raised.value.category == USER_CONCURRENCY
    limiter.release("user-a", "notebook-1")
    limiter.release("user-a", "notebook-2")


def test_different_users_do_not_block_each_other():
    limiter = _production_limiter()
    barrier = threading.Barrier(3)
    held: list[str] = []

    def hold(user_id: str, thread_id: str) -> None:
        with limiter.limit(user_id, thread_id):
            barrier.wait(timeout=2)
            held.append(user_id)

    with ThreadPoolExecutor(max_workers=3) as executor:
        futures = [
            executor.submit(hold, "user-a", "notebook-a"),
            executor.submit(hold, "user-b", "notebook-b"),
            executor.submit(hold, "user-c", "notebook-c"),
        ]
        for future in futures:
            future.result(timeout=5)
    assert sorted(held) == ["user-a", "user-b", "user-c"]


def test_one_hundred_distinct_students_acquire_under_global_120():
    limiter = _production_limiter()
    for index in range(100):
        limiter.acquire(f"user-{index}", f"notebook-{index}")
    assert limiter._global_active == 100  # noqa: SLF001
    for index in range(100):
        limiter.release(f"user-{index}", f"notebook-{index}")
    assert limiter._global_active == 0  # noqa: SLF001
    assert limiter._active_per_user == {}  # noqa: SLF001
    assert limiter._active_per_notebook == {}  # noqa: SLF001


def test_one_hundred_twenty_workflows_fill_global_capacity():
    limiter = _production_limiter()
    for index in range(120):
        limiter.acquire(f"user-{index}", f"notebook-{index}")
    assert limiter._global_active == 120  # noqa: SLF001


def test_one_hundred_twenty_first_workflow_is_rejected():
    limiter = _production_limiter()
    for index in range(120):
        limiter.acquire(f"user-{index}", f"notebook-{index}")
    with pytest.raises(RateLimitExceeded) as raised:
        limiter.acquire("user-overflow", "notebook-overflow")
    assert raised.value.category == GLOBAL_CAPACITY
    limiter.release("user-0", "notebook-0")
    limiter.acquire("user-overflow", "notebook-overflow")


def test_release_frees_notebook_slot_for_same_notebook():
    limiter = _production_limiter()
    limiter.acquire("user-a", "notebook-1")
    limiter.release("user-a", "notebook-1")
    limiter.acquire("user-a", "notebook-1")
    limiter.release("user-a", "notebook-1")


def test_exception_inside_limit_resets_all_counters():
    limiter = _production_limiter()
    with pytest.raises(RuntimeError):
        with limiter.limit("user-a", "notebook-1"):
            raise RuntimeError("boom")
    assert limiter._global_active == 0  # noqa: SLF001
    assert limiter._active_per_user == {}  # noqa: SLF001
    assert limiter._active_per_notebook == {}  # noqa: SLF001
    with limiter.limit("user-a", "notebook-1"):
        pass


def test_per_user_rpm_window_still_rejects_ninth_acquire():
    limiter = _production_limiter(requests_per_minute=8, max_concurrent_model_calls=20)
    for index in range(8):
        limiter.acquire("user-a", f"notebook-{index % 2}")
        limiter.release("user-a", f"notebook-{index % 2}")
    with pytest.raises(RateLimitExceeded) as raised:
        limiter.acquire("user-a", "notebook-1")
    assert raised.value.category == USER_RPM
    assert raised.value.retry_after_seconds >= 1


def test_double_release_does_not_underflow():
    limiter = _production_limiter()
    limiter.acquire("user-a", "notebook-1")
    limiter.release("user-a", "notebook-1")
    limiter.release("user-a", "notebook-1")
    assert limiter._global_active == 0  # noqa: SLF001
    limiter.acquire("user-a", "notebook-1")
    limiter.release("user-a", "notebook-1")


def test_missing_identity_is_rejected_without_consuming_capacity():
    limiter = _production_limiter()
    with pytest.raises(RateLimitExceeded) as raised:
        limiter.acquire("", "notebook-1")
    assert raised.value.category == "missing_identity"
    with pytest.raises(RateLimitExceeded):
        limiter.acquire("user-a", "")
    assert limiter._global_active == 0  # noqa: SLF001


def test_api_returns_429_with_retry_after_for_active_limit(tmp_path, monkeypatch):
    """Overlapping executions for the same notebook are limited to one."""
    from backend import rate_limit as rate_limit_module

    limiter = _production_limiter(requests_per_minute=20, max_concurrent_model_calls=20)
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
                "current_stage": "problem_identification",
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
                "current_stage": "problem_identification",
                "response_detail": "short",
                "idempotency_key": "rate-2",
            },
        )
        release.set()
        first = future.result(timeout=5)

    assert first.status_code == 200
    assert second.status_code == 429
    assert second.headers.get("retry-after")
    assert "per notebook" in second.json()["detail"].lower()


def test_api_same_key_waiters_converge_under_active_limit(tmp_path, monkeypatch):
    """Same-key concurrent callers must wait/replay, not receive HTTP 429."""
    from backend import rate_limit as rate_limit_module

    limiter = _production_limiter(requests_per_minute=20, max_concurrent_model_calls=20)
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
        "current_stage": "problem_identification",
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


def test_login_limiter_does_not_track_globally_rejected_client_keys():
    """A rotated-IP flood at global capacity must not grow process memory."""
    limiter = LoginStartLimiter(per_client_per_minute=10, global_per_minute=1)
    limiter.acquire("accepted-client")

    for index in range(100):
        with pytest.raises(RateLimitExceeded):
            limiter.acquire(f"rejected-client-{index}")

    assert set(limiter._recent_by_client) == {"accepted-client"}  # noqa: SLF001


def test_login_limiter_evicts_stale_client_keys(monkeypatch):
    """Accepted client identities expire with their rolling-window entries."""
    from backend import rate_limit as rate_limit_module

    clock = {"now": 0.0}
    monkeypatch.setattr(
        rate_limit_module.time,
        "monotonic",
        lambda: clock["now"],
    )
    limiter = LoginStartLimiter(per_client_per_minute=10, global_per_minute=10)
    limiter.acquire("old-client")
    clock["now"] = 61.0
    limiter.acquire("current-client")

    assert set(limiter._recent_by_client) == {"current-client"}  # noqa: SLF001


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
