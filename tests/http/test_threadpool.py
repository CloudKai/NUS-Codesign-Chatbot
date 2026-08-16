"""Deterministic tests for AnyIO sync-threadpool startup configuration."""

from __future__ import annotations

import asyncio

import anyio.to_thread
from fastapi.testclient import TestClient

from backend.http.app import configure_sync_threadpool, create_app
from backend.settings import _bounded_int, settings
from backend.student_store import StudentStore


def test_sync_threadpool_tokens_parses_valid_value(monkeypatch):
    monkeypatch.setenv("SYNC_THREADPOOL_TOKENS", "120")
    assert _bounded_int("SYNC_THREADPOOL_TOKENS", 40, 8, 500) == 120


def test_sync_threadpool_tokens_invalid_values_fall_back(monkeypatch):
    monkeypatch.setenv("SYNC_THREADPOOL_TOKENS", "0")
    assert _bounded_int("SYNC_THREADPOOL_TOKENS", 40, 8, 500) == 40
    monkeypatch.setenv("SYNC_THREADPOOL_TOKENS", "-3")
    assert _bounded_int("SYNC_THREADPOOL_TOKENS", 40, 8, 500) == 40
    monkeypatch.setenv("SYNC_THREADPOOL_TOKENS", "99999")
    assert _bounded_int("SYNC_THREADPOOL_TOKENS", 40, 8, 500) == 40
    monkeypatch.setenv("SYNC_THREADPOOL_TOKENS", "not-a-number")
    assert _bounded_int("SYNC_THREADPOOL_TOKENS", 40, 8, 500) == 40


def test_sync_threadpool_tokens_default_is_40(monkeypatch):
    monkeypatch.delenv("SYNC_THREADPOOL_TOKENS", raising=False)
    assert _bounded_int("SYNC_THREADPOOL_TOKENS", 40, 8, 500) == 40


def test_coach_concurrency_settings_clamp(monkeypatch):
    monkeypatch.setenv("MAX_ACTIVE_COACH_REQUESTS_PER_NOTEBOOK", "1")
    assert _bounded_int("MAX_ACTIVE_COACH_REQUESTS_PER_NOTEBOOK", 1, 1, 8) == 1
    monkeypatch.setenv("MAX_ACTIVE_COACH_REQUESTS_PER_USER", "2")
    assert _bounded_int("MAX_ACTIVE_COACH_REQUESTS_PER_USER", 2, 1, 20) == 2
    monkeypatch.setenv("MAX_CONCURRENT_MODEL_CALLS", "120")
    assert _bounded_int("MAX_CONCURRENT_MODEL_CALLS", 20, 1, 500) == 120
    monkeypatch.setenv("MAX_CONCURRENT_MODEL_CALLS", "0")
    assert _bounded_int("MAX_CONCURRENT_MODEL_CALLS", 20, 1, 500) == 20


def test_configure_sync_threadpool_sets_anyio_limiter():
    """The limiter is a per-event-loop RunVar and must be set from async code."""

    async def _configure() -> tuple[int, int]:
        applied = configure_sync_threadpool(48)
        limiter = anyio.to_thread.current_default_thread_limiter()
        return applied, int(limiter.total_tokens)

    applied, tokens = asyncio.run(_configure())
    assert applied == 48
    assert tokens == 48


def test_application_startup_configures_threadpool_once(tmp_path, monkeypatch, caplog):
    monkeypatch.setattr(settings, "sync_threadpool_tokens", 96)
    store = StudentStore(tmp_path / "threadpool.sqlite3")
    app = create_app(store)
    with caplog.at_level("INFO"):
        with TestClient(app) as client:
            assert client.app.state.sync_threadpool_tokens == 96
            health = client.get("/api/v1/health")
            assert health.status_code == 200
    messages = [record.getMessage() for record in caplog.records]
    configured = [
        item for item in messages if "sync_threadpool_configured tokens=96" in item
    ]
    assert len(configured) == 1
