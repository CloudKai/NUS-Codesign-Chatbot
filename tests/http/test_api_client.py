"""Contract tests for the typed local API client."""

from __future__ import annotations

import httpx
import pytest
from fastapi.testclient import TestClient

from backend.api import create_app
from backend.api_client import LocalApiClient
from backend.domain import CoachRequest
from backend.student_store import StudentStore


def _set_first_phase(store: StudentStore, thread_id: str) -> None:
    """Set the five-phase domain default until persisted defaults are migrated."""
    store.update_thread(
        thread_id,
        metadata={
            "thinking_stage": "problem_identification",
            "learning_journey": {
                "current_stage": "problem_identification",
                "completed_stages": [],
                "stage_notes": {},
                "response_detail": "short",
            },
        },
    )


def _client_for_store(store: StudentStore, *, auto_advance: bool) -> LocalApiClient:
    """Build an in-process client bound to one isolated StudentStore."""
    app = create_app(store, auto_advance_stages=auto_advance)
    return LocalApiClient("http://testserver", session=TestClient(app))


def test_api_client_health_and_confirmation_round_trip(tmp_path):
    store = StudentStore(tmp_path / "client.sqlite3")
    thread_id = store.create_thread(model_id="mock", support_mode="critical-thinking")
    _set_first_phase(store, thread_id)
    client = _client_for_store(store, auto_advance=False)
    try:
        assert client.health() == {"status": "ok", "mode": "local"}

        first = client.coach_turn(
            CoachRequest(
                thread_id=thread_id,
                student_message="I want to evaluate a crossing design.",
                current_stage="problem_identification",
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
                current_stage="problem_identification",
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
        assert (state.get("learning_journey") or {}).get("current_stage") == "concept_generation"
        assert client.pending_transition(thread_id) is None
    finally:
        client.close()


def test_api_client_auto_advance_mode(tmp_path):
    store = StudentStore(tmp_path / "client-auto.sqlite3")
    thread_id = store.create_thread(model_id="mock", support_mode="critical-thinking")
    _set_first_phase(store, thread_id)
    client = _client_for_store(store, auto_advance=True)
    try:
        client.coach_turn(
            CoachRequest(
                thread_id=thread_id,
                student_message="I want to evaluate a crossing design.",
                current_stage="problem_identification",
                response_detail="short",
            )
        )
        follow_up = client.coach_turn(
            CoachRequest(
                thread_id=thread_id,
                student_message=(
                    "Which crossing design gives older pedestrians enough time?"
                ),
                current_stage="problem_identification",
                response_detail="short",
            )
        )
        assert follow_up.auto_advanced_to == "concept_generation"
        assert follow_up.pending_transition is None
        state = client.learning_state(thread_id)
        assert (state.get("learning_journey") or {}).get("current_stage") == "concept_generation"
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
                    current_stage="problem_identification",
                    response_detail="short",
                )
            )
    finally:
        client.close()


def test_api_client_ready_stream_and_graph(tmp_path):
    store = StudentStore(tmp_path / "client-stream.sqlite3")
    thread_id = store.create_thread(model_id="mock", support_mode="critical-thinking")
    _set_first_phase(store, thread_id)
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
                    current_stage="problem_identification",
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


def test_professor_research_client_uses_versioned_routes_and_server_identity() -> None:
    """Research client methods preserve paths and never add reviewer identity."""
    calls: list[tuple[str, str, dict]] = []

    class _Session:
        def get(self, url, **kwargs):
            calls.append(("GET", url, kwargs))
            if url.endswith("export.csv"):
                return httpx.Response(
                    200,
                    content=b"observation_id\nobservation-1\n",
                    request=httpx.Request("GET", url),
                )
            payload = {"items": [], "total": 0, "limit": 25, "offset": 0}
            if url.endswith("summary"):
                payload = {"active_observations": 0}
            elif "/notebooks/" in url:
                payload = {"notebook_id": "notebook/one"}
            return httpx.Response(
                200, json=payload, request=httpx.Request("GET", url)
            )

        def post(self, url, **kwargs):
            calls.append(("POST", url, kwargs))
            return httpx.Response(
                201,
                json={"id": "record-1", **kwargs.get("json", {})},
                request=httpx.Request("POST", url),
            )

    client = LocalApiClient("http://testserver", session=_Session())
    assert client.professor_research_summary()["active_observations"] == 0
    client.professor_research_queue(coding_status="coded", limit=25)
    assert client.professor_research_notebook("notebook/one")["notebook_id"] == "notebook/one"
    review = client.professor_submit_research_review(
        {"observation_id": "observation-1", "status": "confirmed"}
    )
    assert "reviewer_user_id" not in review
    assert client.professor_research_export(phase="reflection").startswith(
        b"observation_id"
    )

    assert any(url.endswith("/api/v1/professor/research/summary") for _, url, _ in calls)
    assert any("notebook%2Fone" in url for _, url, _ in calls)
    assert all(
        "reviewer_user_id" not in (kwargs.get("json") or {})
        for method, _url, kwargs in calls
        if method == "POST"
    )


def test_api_client_surfaces_safety_blocked_category(tmp_path, monkeypatch):
    """Stream error events expose the structured category to the UI client."""
    from backend.providers import ProviderUnavailableError
    from backend.workflow import CoachWorkflow

    store = StudentStore(tmp_path / "client-blocked.sqlite3")
    thread_id = store.create_thread(model_id="mock", support_mode="critical-thinking")
    _set_first_phase(store, thread_id)

    def fail_run(self, request):
        raise ProviderUnavailableError(
            "AgentCore blocked this turn", category="safety_blocked"
        )

    monkeypatch.setattr(CoachWorkflow, "run", fail_run)
    client = _client_for_store(store, auto_advance=False)
    try:
        events = list(
            client.stream_coach_turn(
                CoachRequest(
                    thread_id=thread_id,
                    student_message="I compared two crossing designs.",
                    current_stage="problem_identification",
                    response_detail="short",
                )
            )
        )
        error = next(event for event in events if event.get("event") == "error")
        assert error["status"] == 503
        assert error["category"] == "safety_blocked"
        assert error["detail"] == "AgentCore blocked this turn"
        assert LocalApiClient.coaching_error_category(error) == "safety_blocked"
        assert (
            LocalApiClient.coaching_error_category(
                {"detail": {"message": "AgentCore blocked this turn", "category": "safety_blocked"}}
            )
            == "safety_blocked"
        )
    finally:
        client.close()


def test_api_client_surfaces_structured_output_failure_category(tmp_path, monkeypatch):
    """Stream error events expose structured_output_failure to the UI client."""
    from backend.providers import ProviderUnavailableError
    from backend.workflow import CoachWorkflow

    store = StudentStore(tmp_path / "client-structured.sqlite3")
    thread_id = store.create_thread(model_id="mock", support_mode="critical-thinking")
    _set_first_phase(store, thread_id)

    def fail_run(self, request):
        raise ProviderUnavailableError(
            "The coach reply could not be completed",
            category="structured_output_failure",
        )

    monkeypatch.setattr(CoachWorkflow, "run", fail_run)
    client = _client_for_store(store, auto_advance=False)
    try:
        events = list(
            client.stream_coach_turn(
                CoachRequest(
                    thread_id=thread_id,
                    student_message="A quiet residential street",
                    current_stage="problem_identification",
                    response_detail="short",
                )
            )
        )
        error = next(event for event in events if event.get("event") == "error")
        assert error["status"] == 503
        assert error["category"] == "structured_output_failure"
        assert "JSONDecodeError" not in str(error)
        assert LocalApiClient.coaching_error_category(error) == "structured_output_failure"
    finally:
        client.close()
