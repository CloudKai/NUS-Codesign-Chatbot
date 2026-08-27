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


def _install_inprocess_api(
    monkeypatch,
    *,
    auto_advance: bool,
    stage_selection: bool = False,
) -> LocalApiClient:
    """Point Streamlit UI modules at an in-process FastAPI app on the test DB."""
    monkeypatch.setattr(settings, "use_local_api", True)
    monkeypatch.setattr(settings, "auto_advance_stages", auto_advance)
    monkeypatch.setattr(settings, "student_stage_selection", stage_selection)
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
        "How might we improve road crossings for older pedestrians so that "
        "they can cross safely without rushing?"
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
            "How might we improve road crossings for older pedestrians so that "
            "they can cross safely without rushing?"
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
            "How might we improve road crossings for older pedestrians so that "
            "they can cross safely without rushing?"
        ).run()
        assert not app.exception

        assert client.pending_transition(thread_id) is None
        state = client.learning_state(thread_id)
        assert (state.get("learning_journey") or {}).get("current_stage") == "concept_generation"
        assert app.session_state["learning_journey"]["current_stage"] == "concept_generation"
    finally:
        client.close()


def test_streamlit_stage_selection_refreshes_authoritative_stage_and_status(monkeypatch):
    """The local-only selector remounts from the API's persisted Journey state."""
    client = _install_inprocess_api(
        monkeypatch,
        auto_advance=False,
        stage_selection=True,
    )
    try:
        app = AppTest.from_file("streamlit_app.py", default_timeout=30).run()
        assert not app.exception
        thread_id = app.session_state["thread_id"]
        store = StudentStore()
        thread = store.get_thread(thread_id) or {}
        metadata = dict(thread.get("metadata") or {})
        journey = dict(metadata.get("learning_journey") or {})
        journey["completed_stages"] = ["problem_identification"]
        metadata["learning_journey"] = journey
        store.update_thread(thread_id, metadata=metadata)
        app.session_state["learning_journey"]["completed_stages"] = [
            "problem_identification"
        ]
        app.run()

        select = next(
            button
            for button in app.button
            if button.key == "journey-select-concept_generation"
        )
        select.click().run()

        persisted = client.learning_state(thread_id)
        assert persisted["thinking_stage"] == "concept_generation"
        assert persisted["learning_journey"]["current_stage"] == "concept_generation"
        assert app.session_state["learning_journey"]["current_stage"] == "concept_generation"
        assert app.session_state["mobile_panel"] == "Chat"
        assert "chat_follow_bottom" not in app.session_state
        assert app.session_state["stage_move_notice"] == "Moved to stage: Concept generation"
        messages = client.get_messages(thread_id)
        assert not any(
            "Moved to Stage:" in str(message.get("content") or "")
            for message in messages
        )

        app.chat_input[0].set_value(
            "I need to examine the trade-off between crossing safety and traffic delay."
        ).run()
        assert not app.exception
        assert app.session_state["stage_move_notice"] is None
        messages = client.get_messages(thread_id)
        normal_assistant = [
            message for message in messages if message["role"] == "assistant"
        ][-1]
        normal_assessment = (
            (normal_assistant.get("metadata") or {}).get("assessment") or {}
        )
        assert normal_assessment["current_stage"] == "concept_generation"

        app.chat_input[0].set_value("What stage am I in?").run()
        assert not app.exception
        messages = client.get_messages(thread_id)
        assistant = [message for message in messages if message["role"] == "assistant"][-1]
        assert "Concept generation" in assistant["content"]
        assessment = (assistant.get("metadata") or {}).get("assessment") or {}
        assert assessment["current_stage"] == "concept_generation"
        assert assessment["response_mode"] == "qa"
        assert assessment.get("citations") == []
        assert app.session_state["learning_journey"]["current_stage"] == "concept_generation"
    finally:
        client.close()


def test_streamlit_manual_stage_chat_command_refreshes_authoritative_journey(
    monkeypatch,
):
    """Exact move-me-to updates journey without chat bubbles, then clears notice."""
    client = _install_inprocess_api(
        monkeypatch,
        auto_advance=False,
        stage_selection=True,
    )
    try:
        app = AppTest.from_file("streamlit_app.py", default_timeout=30).run()
        assert not app.exception
        thread_id = app.session_state["thread_id"]
        store = StudentStore()
        thread = store.get_thread(thread_id) or {}
        metadata = dict(thread.get("metadata") or {})
        journey = dict(metadata.get("learning_journey") or {})
        journey["completed_stages"] = ["problem_identification"]
        metadata["learning_journey"] = journey
        store.update_thread(thread_id, metadata=metadata)
        app.session_state["learning_journey"]["completed_stages"] = [
            "problem_identification"
        ]
        app.run()

        app.chat_input[0].set_value("move me to Concept generation").run()

        assert not app.exception
        state = client.learning_state(thread_id)
        assert state["thinking_stage"] == "concept_generation"
        assert state["learning_journey"]["current_stage"] == "concept_generation"
        assert app.session_state["learning_journey"]["current_stage"] == "concept_generation"
        assert app.session_state["stage_move_notice"] == "Moved to stage: Concept generation"
        messages = client.get_messages(thread_id)
        assert not any(
            "Moved to Stage:" in str(message.get("content") or "")
            for message in messages
        )
        assert not any(
            str(message.get("content") or "").lower().startswith("move me to")
            for message in messages
            if message.get("role") == "user"
        )

        app.chat_input[0].set_value("Hi, can I move to Concept Generation?").run()
        assert not app.exception
        assert (
            app.session_state["stage_move_notice"]
            == "You are already in Concept generation"
        )
        assert client.get_messages(thread_id) == messages

        app.chat_input[0].set_value("move me to Reflection").run()
        assert not app.exception
        assert (
            app.session_state["stage_move_notice"]
            == "Must complete Ethics & Critical Thinking to reach Reflection"
        )
        assert client.learning_state(thread_id)["thinking_stage"] == "concept_generation"
        assert client.get_messages(thread_id) == messages

        app.chat_input[0].set_value(
            "I am reflecting on how evidence changed my design decision."
        ).run()
        assert not app.exception
        assert app.session_state["stage_move_notice"] is None
        messages = client.get_messages(thread_id)
        assistant = [message for message in messages if message["role"] == "assistant"][-1]
        assert assistant["metadata"]["assessment"]["current_stage"] == "concept_generation"
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
