"""API-level upload size, count, and filename hardening tests."""

from __future__ import annotations

import asyncio

from fastapi.testclient import TestClient

from backend.api import create_app
from backend.settings import settings
from backend.student_store import StudentStore
from backend.workspace_service import WorkspaceService


def test_upload_processing_runs_off_the_event_loop(tmp_path, monkeypatch):
    """Blocking upload writes must not stall the event loop (ticket 39).

    The measured harness (``scripts/benchmark_concurrency.py``) shows the
    same blocking work placed on the asyncio loop stalls every concurrent
    request, while bounded threadpool offloading does not. The two ``async``
    upload routes must therefore run their workspace writes via the bounded
    threadpool like every sync route.
    """
    store = StudentStore(tmp_path / "upload-offloop.sqlite3")
    client = TestClient(create_app(store))
    thread_id = store.create_thread(model_id="mock", support_mode="critical-thinking")
    observations: list[str] = []
    real = WorkspaceService.upload_sources

    def spy(self, spy_thread_id, uploads):
        try:
            asyncio.get_running_loop()
            observations.append("event-loop")
        except RuntimeError:
            observations.append("worker-thread")
        return real(self, spy_thread_id, uploads)

    monkeypatch.setattr(WorkspaceService, "upload_sources", spy)
    response = client.post(
        f"/api/v1/threads/{thread_id}/sources",
        files=[("files", ("a.txt", b"one", "text/plain"))],
    )
    assert response.status_code == 200, response.text
    assert observations == ["worker-thread"]


def test_upload_rejects_too_many_files(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "max_files", 2)
    store = StudentStore(tmp_path / "upload-count.sqlite3")
    client = TestClient(create_app(store))
    thread_id = store.create_thread(model_id="mock", support_mode="critical-thinking")

    response = client.post(
        f"/api/v1/threads/{thread_id}/sources",
        files=[
            ("files", ("a.txt", b"one", "text/plain")),
            ("files", ("b.txt", b"two", "text/plain")),
            ("files", ("c.txt", b"three", "text/plain")),
        ],
    )
    assert response.status_code == 400
    assert "at most 2" in response.json()["detail"].lower()


def test_upload_rejects_oversized_file_without_buffering_all_bytes(
    tmp_path, monkeypatch
):
    monkeypatch.setattr(settings, "max_file_size_mb", 1)
    store = StudentStore(tmp_path / "upload-size.sqlite3")
    client = TestClient(create_app(store))
    thread_id = store.create_thread(model_id="mock", support_mode="critical-thinking")
    oversized = b"x" * (1 * 1024 * 1024 + 1)

    response = client.post(
        f"/api/v1/threads/{thread_id}/sources",
        files=[("files", ("big.txt", oversized, "text/plain"))],
    )
    assert response.status_code == 400
    assert "exceeds the 1 mb limit" in response.json()["detail"].lower()


def test_upload_accepts_exact_byte_limit(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "max_file_size_mb", 1)
    store = StudentStore(tmp_path / "upload-exact.sqlite3")
    client = TestClient(create_app(store))
    thread_id = store.create_thread(model_id="mock", support_mode="critical-thinking")
    exact = b"y" * (1 * 1024 * 1024)

    response = client.post(
        f"/api/v1/threads/{thread_id}/sources",
        files=[("files", ("exact.txt", exact, "text/plain"))],
    )
    assert response.status_code == 200, response.text
    payload = response.json()[0]
    assert "path" not in payload
    assert "object_key" not in payload
    assert payload["has_file"] is True


def test_upload_sanitizes_path_traversal_filename(tmp_path):
    store = StudentStore(tmp_path / "upload-name.sqlite3")
    client = TestClient(create_app(store))
    thread_id = store.create_thread(model_id="mock", support_mode="critical-thinking")

    response = client.post(
        f"/api/v1/threads/{thread_id}/sources",
        files=[
            (
                "files",
                ("../../etc/passwd.txt", b"safe body", "text/plain"),
            )
        ],
    )
    assert response.status_code == 200, response.text
    title = response.json()[0]["title"]
    assert ".." not in title
    assert "/" not in title
    assert "passwd" in title.lower()
