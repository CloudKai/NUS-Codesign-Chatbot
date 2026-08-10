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
        assert kinds[0] == "started"
        assert kinds[1] == "status"
        assert events[1].get("phase") == "thinking"
        assert "token" in kinds
        assert "done" in kinds
        done = next(event for event in events if event.get("event") == "done")
        assert done["turn"]["response_text"]

        graph = client.graph_state(thread_id)
        assert graph["thread_id"] == thread_id
        assert graph["steps"] == ["load_context", "assess", "recommend", "format"]
    finally:
        client.close()


def test_api_client_auth_me_returns_user_or_none(tmp_path, monkeypatch):
    """LocalApiClient.auth_me maps /auth/me success and 401 without raising."""
    from datetime import datetime, timezone

    from joserfc import jwt
    from joserfc.jwk import OctKey

    from backend.auth_oidc import CognitoIdentity, CognitoOIDCClient, CognitoOIDCError
    from backend.cognito_config import CognitoAuthConfig

    store = StudentStore(tmp_path / "client-auth-me.sqlite3")
    fixed = datetime(2026, 1, 15, 12, 0, tzinfo=timezone.utc)
    key = OctKey.generate_key(256, parameters={"alg": "HS256", "kid": "client"})
    claims = {
        "sub": "sub-client",
        "email": "client@example.edu",
        "iss": "https://cognito-idp.example.test/pool",
        "aud": "test-client",
        "exp": int((fixed.timestamp()) + 3600),
        "iat": int(fixed.timestamp()),
    }
    id_token = jwt.encode({"alg": "HS256", "kid": "client"}, claims, key)

    class _OIDC(CognitoOIDCClient):
        def verify_id_token(self, token: str):
            if token != id_token:
                raise CognitoOIDCError("bad")
            return CognitoIdentity(
                sub="sub-client",
                email="client@example.edu",
                claims=dict(claims),
            )

        def refresh(self, refresh_token: str):
            raise CognitoOIDCError("no refresh in this test")

    store.upsert_cognito_user(
        cognito_sub="sub-client",
        identifier="cognito:sub-client",
        email="client@example.edu",
        display_name="Client",
    )
    oidc = _OIDC(
        CognitoAuthConfig(
            client_id="test-client",
            client_secret="test-secret",
            server_metadata_url="https://example.test/.well-known/openid-configuration",
            redirect_uri="http://127.0.0.1:8000/api/v1/auth/callback",
        ),
        store=store,
        clock=lambda: fixed,
    )
    app = create_app(store, oidc_client=oidc)
    client = LocalApiClient("http://testserver", session=TestClient(app))
    try:
        assert client.auth_me("") is None
        assert client.auth_me("not-a-token") is None

        profile = client.auth_me(id_token)
        assert profile is not None
        assert profile["cognito_sub"] == "sub-client"
        assert profile["email"] == "client@example.edu"
        assert "access_token" not in profile
        assert id_token not in str(profile)
    finally:
        client.close()


def test_course_sync_uses_explicit_cookie_snapshot_without_worker_provider_call():
    """A background sync can reuse main-thread auth without rereading context."""
    provider_calls = 0

    def cookie_provider():
        nonlocal provider_calls
        provider_calls += 1
        return {"co_design_id": "short-lived-id-token"}

    class _Session:
        received_cookies: dict[str, str] | None = None

        def post(self, url, **kwargs):
            self.received_cookies = kwargs.get("cookies")
            return httpx.Response(
                200,
                json={
                    "added": 0,
                    "updated": 0,
                    "removed": 0,
                    "unchanged": 0,
                    "skipped": 0,
                    "errors": [],
                },
                request=httpx.Request("POST", url),
            )

    session = _Session()
    client = LocalApiClient(
        "http://testserver",
        session=session,
        cookie_provider=cookie_provider,
    )
    snapshot = client.auth_cookie_snapshot()

    client.sync_course_materials("notebook-1", auth_cookies=snapshot)

    assert provider_calls == 1
    assert session.received_cookies == {
        "co_design_id": "short-lived-id-token"
    }
