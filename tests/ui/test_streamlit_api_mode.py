"""Streamlit AppTest coverage for preferred API coaching and legacy fallback."""

from __future__ import annotations

import threading

from fastapi.testclient import TestClient
from streamlit.testing.v1 import AppTest

from backend.api import create_app
from backend.api_client import LocalApiClient
from backend.settings import settings
from backend.source_library import CourseMaterialSyncCoordinator
from backend.student_store import StudentStore


def _install_inprocess_api(monkeypatch, *, auto_advance: bool) -> LocalApiClient:
    """Point Streamlit UI modules at an in-process FastAPI app on the test DB."""
    monkeypatch.setattr(settings, "use_local_api", True)
    monkeypatch.setattr(settings, "auto_advance_stages", auto_advance)
    store = StudentStore()
    client = LocalApiClient(
        "http://testserver",
        session=TestClient(create_app(store, auto_advance_stages=auto_advance)),
    )
    monkeypatch.setattr("ui.runtime.local_api_enabled", lambda: True)
    monkeypatch.setattr("ui.runtime.local_api_client", lambda bound=client: bound)
    return client


def test_inprocess_streamlit_chat_path_still_smoke_tests():
    """Retain one AppTest on the in-process coach path (USE_LOCAL_API=false)."""
    assert settings.use_local_api is False
    app = AppTest.from_file("streamlit_app.py", default_timeout=30).run()
    assert not app.exception
    assert len(app.chat_input) == 1
    app.chat_input[0].set_value(
        "I want to evaluate a crossing design for older pedestrians."
    ).run()
    assert not app.exception
    assert len(app.chat_message) >= 2


def test_authenticated_inprocess_path_confirms_pending_transition():
    """Cognito-scoped sessions retain full Thinking Path confirmation behavior."""
    assert settings.use_local_api is False
    app = AppTest.from_file("streamlit_app.py", default_timeout=30).run()

    app.chat_input[0].set_value(
        "I want to evaluate a crossing design for older pedestrians."
    ).run()
    app.chat_input[0].set_value(
        "Which design gives older pedestrians enough time and visibility?"
    ).run()
    app.chat_input[0].set_value(
        "Older adults near schools need a longer crossing interval than the current signal."
    ).run()

    next_button = next(
        button for button in app.button if button.key == "thinking-path-next"
    )
    assert next_button.disabled is False
    next_button.click().run()
    confirm = next(
        button for button in app.button if button.key == "confirm-next-stage"
    )
    confirm.click().run()

    assert not app.exception
    assert app.session_state["learning_journey"]["current_stage"] == "concept_generation"


def test_streamlit_api_mode_confirmation_creates_pending_transition(monkeypatch):
    client = _install_inprocess_api(monkeypatch, auto_advance=False)
    try:
        app = AppTest.from_file("streamlit_app.py", default_timeout=30).run()
        assert not app.exception
        thread_id = app.session_state["thread_id"]

        app.chat_input[0].set_value(
            "I want to evaluate a crossing design for older pedestrians."
        ).run()
        assert not app.exception

        app.chat_input[0].set_value(
            "Which design gives older pedestrians enough time and visibility?"
        ).run()
        assert not app.exception

        app.chat_input[0].set_value(
            "Older adults near schools need a longer crossing interval than the current signal."
        ).run()
        assert not app.exception

        pending = client.pending_transition(thread_id)
        assert pending is not None
        assert pending.to_stage == "concept_generation"
        state = client.learning_state(thread_id)
        assert (state.get("learning_journey") or {}).get("current_stage", "problem_identification") == (
            "problem_identification"
        )
        rendered = "\n".join(markdown.value or "" for markdown in app.markdown)
        assert "recommended a next step" in rendered.lower() or pending is not None
    finally:
        client.close()


def test_streamlit_api_mode_auto_advance_moves_thinking_path(monkeypatch):
    client = _install_inprocess_api(monkeypatch, auto_advance=True)
    try:
        app = AppTest.from_file("streamlit_app.py", default_timeout=30).run()
        assert not app.exception
        thread_id = app.session_state["thread_id"]

        app.chat_input[0].set_value(
            "I want to evaluate a crossing design for older pedestrians."
        ).run()
        assert not app.exception

        app.chat_input[0].set_value(
            "Which design gives older pedestrians enough time and visibility?"
        ).run()
        assert not app.exception

        app.chat_input[0].set_value(
            "Older adults near schools need a longer crossing interval than the current signal."
        ).run()
        assert not app.exception

        assert client.pending_transition(thread_id) is None
        state = client.learning_state(thread_id)
        assert (state.get("learning_journey") or {}).get("current_stage") == "concept_generation"
        assert app.session_state["learning_journey"]["current_stage"] == "concept_generation"
    finally:
        client.close()


def test_course_sync_snapshots_streamlit_auth_before_background_worker(monkeypatch):
    """The sync executor must not resolve browser cookies from its own thread."""
    from ui import runtime

    main_thread = threading.get_ident()
    snapshot_threads: list[int] = []
    worker_threads: list[int] = []

    class _Client:
        def auth_cookie_snapshot(self) -> dict[str, str]:
            snapshot_threads.append(threading.get_ident())
            return {"co_design_id": "captured-on-render-thread"}

        def sync_course_materials(
            self,
            thread_id: str,
            *,
            auth_cookies: dict[str, str],
        ) -> dict:
            worker_threads.append(threading.get_ident())
            assert thread_id == "owned-notebook"
            assert auth_cookies == {
                "co_design_id": "captured-on-render-thread"
            }
            return {
                "added": 0,
                "updated": 0,
                "removed": 0,
                "unchanged": 0,
                "skipped": 0,
                "errors": [],
            }

    coordinator = CourseMaterialSyncCoordinator()
    monkeypatch.setattr(runtime, "local_api_enabled", lambda: True)
    monkeypatch.setattr(runtime, "local_api_client", lambda: _Client())
    monkeypatch.setattr(runtime, "course_material_sync", lambda: coordinator)

    result = runtime.WorkspaceFacade().request_course_material_sync(
        "owned-notebook"
    ).result(timeout=5)

    assert not result.errors
    assert snapshot_threads == [main_thread]
    assert worker_threads and worker_threads[0] != main_thread
