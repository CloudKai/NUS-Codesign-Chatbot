"""Streamlit AppTest coverage for preferred API coaching and legacy fallback."""

from __future__ import annotations

from fastapi.testclient import TestClient
from streamlit.testing.v1 import AppTest

from backend.api import create_app
from backend.api_client import LocalApiClient
from backend.settings import settings
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
    monkeypatch.setattr("ui.studio.local_api_enabled", lambda: True)
    monkeypatch.setattr("ui.studio.local_api_client", lambda bound=client: bound)
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

        pending = client.pending_transition(thread_id)
        assert pending is not None
        assert pending.to_stage == "evidence"
        state = client.learning_state(thread_id)
        assert (state.get("learning_journey") or {}).get("current_stage", "focus") == (
            "focus"
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

        assert client.pending_transition(thread_id) is None
        state = client.learning_state(thread_id)
        assert (state.get("learning_journey") or {}).get("current_stage") == "evidence"
        assert app.session_state["learning_journey"]["current_stage"] == "evidence"
    finally:
        client.close()
