"""Contract tests for the typed local API client."""

from __future__ import annotations

import httpx
import pytest
from fastapi.testclient import TestClient

from backend.api import create_app
from backend.api_client import LocalApiClient
from backend.domain import CoachRequest
from backend.student_store import StudentStore


def _client_for_store(store: StudentStore, *, auto_advance: bool) -> LocalApiClient:
    """Build an in-process client bound to one isolated StudentStore."""
    app = create_app(store, auto_advance_stages=auto_advance)
    return LocalApiClient("http://testserver", session=TestClient(app))


def test_api_client_health_and_confirmation_round_trip(tmp_path):
    store = StudentStore(tmp_path / "client.sqlite3")
    thread_id = store.create_thread(model_id="mock", support_mode="critical-thinking")
    client = _client_for_store(store, auto_advance=False)
    try:
        assert client.health() == {"status": "ok", "mode": "local"}

        first = client.coach_turn(
            CoachRequest(
                thread_id=thread_id,
                student_message="I want to evaluate a crossing design.",
                current_stage="focus",
                response_detail="short",
            )
        )
        assert first.pending_transition is None

        follow_up = client.coach_turn(
            CoachRequest(
                thread_id=thread_id,
                student_message=(
                    "Which crossing design gives older pedestrians enough time?"
                ),
                current_stage="focus",
                response_detail="short",
            )
        )
        assert follow_up.pending_transition is not None
        pending = client.pending_transition(thread_id)
        assert pending is not None
        assert pending.id == follow_up.pending_transition.id

        resolved = client.resolve_transition(thread_id, pending.id, accepted=True)
        assert resolved.status.value == "confirmed"
        state = client.learning_state(thread_id)
        assert (state.get("learning_journey") or {}).get("current_stage") == "evidence"
        assert client.pending_transition(thread_id) is None
    finally:
        client.close()


def test_api_client_auto_advance_mode(tmp_path):
    store = StudentStore(tmp_path / "client-auto.sqlite3")
    thread_id = store.create_thread(model_id="mock", support_mode="critical-thinking")
    client = _client_for_store(store, auto_advance=True)
    try:
        client.coach_turn(
            CoachRequest(
                thread_id=thread_id,
                student_message="I want to evaluate a crossing design.",
                current_stage="focus",
                response_detail="short",
            )
        )
        follow_up = client.coach_turn(
            CoachRequest(
                thread_id=thread_id,
                student_message=(
                    "Which crossing design gives older pedestrians enough time?"
                ),
                current_stage="focus",
                response_detail="short",
            )
        )
        assert follow_up.auto_advanced_to == "evidence"
        assert follow_up.pending_transition is None
        state = client.learning_state(thread_id)
        assert (state.get("learning_journey") or {}).get("current_stage") == "evidence"
    finally:
        client.close()


def test_api_client_raises_for_missing_notebook(tmp_path):
    store = StudentStore(tmp_path / "client-missing.sqlite3")
    client = _client_for_store(store, auto_advance=False)
    try:
        with pytest.raises(httpx.HTTPStatusError):
            client.coach_turn(
                CoachRequest(
                    thread_id="missing-thread",
                    student_message="No notebook here.",
                    current_stage="focus",
                    response_detail="short",
                )
            )
    finally:
        client.close()


def test_api_client_ready_stream_and_graph(tmp_path):
    store = StudentStore(tmp_path / "client-stream.sqlite3")
    thread_id = store.create_thread(model_id="mock", support_mode="critical-thinking")
    client = _client_for_store(store, auto_advance=False)
    try:
        ready = client.ready()
        assert ready["status"] == "ready"
        assert ready["provider"] == "mock"

        events = list(
            client.stream_coach_turn(
                CoachRequest(
                    thread_id=thread_id,
                    student_message="I want to evaluate a crossing design.",
                    current_stage="focus",
                    response_detail="short",
                )
            )
        )
        kinds = [event.get("event") for event in events]
        assert "started" in kinds
        assert "token" in kinds
        assert "done" in kinds
        done = next(event for event in events if event.get("event") == "done")
        assert done["turn"]["response_text"]

        graph = client.graph_state(thread_id)
        assert graph["thread_id"] == thread_id
        assert graph["steps"] == ["load_context", "assess", "recommend", "format"]
    finally:
        client.close()


def test_api_client_auth_me_returns_user_or_none(tmp_path):
    """LocalApiClient.auth_me maps /auth/me success and 401 without raising."""
    from datetime import datetime, timezone

    from backend.app_sessions import AppSessionService

    store = StudentStore(tmp_path / "client-auth-me.sqlite3")
    fixed = datetime(2026, 1, 15, 12, 0, tzinfo=timezone.utc)
    sessions = AppSessionService(store, clock=lambda: fixed)
    app = create_app(store, session_service=sessions)
    client = LocalApiClient("http://testserver", session=TestClient(app))
    try:
        assert client.auth_me("") is None
        assert client.auth_me("not-a-session") is None

        user = store.upsert_cognito_user(
            cognito_sub="sub-client",
            identifier="cognito:sub-client",
            email="client@example.edu",
            display_name="Client",
        )
        created = sessions.create_session(user["id"])
        profile = client.auth_me(created.raw_token)
        assert profile is not None
        assert profile["cognito_sub"] == "sub-client"
        assert profile["email"] == "client@example.edu"
        assert "access_token" not in profile
        assert created.raw_token not in str(profile)
    finally:
        client.close()
