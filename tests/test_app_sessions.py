"""Deterministic application-session and FastAPI auth tests (no Cognito network)."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

import pytest
from fastapi.testclient import TestClient
from joserfc import jwt
from joserfc.jwk import OctKey

from backend.api import create_app
from backend.app_sessions import (
    AppSessionService,
    cookie_settings,
    oauth_state_cookie_settings,
)
from backend.auth_oidc import CognitoOIDCClient, CognitoOIDCError, OAUTH_STATE_TTL_SECONDS
from backend.cognito_config import CognitoAuthConfig, load_cognito_auth_config
from backend.session_tokens import generate_session_token, hash_session_token
from backend.settings import settings
from backend.student_store import StudentStore


FIXED_NOW = datetime(2026, 1, 15, 12, 0, tzinfo=timezone.utc)


def _set_cookie_header(response) -> str:
    return ";".join(response.headers.get_list("set-cookie"))


def _oauth_cookie_name() -> str:
    return settings.oauth_state_cookie_name


def _cookie_value_from_response(response, name: str) -> str | None:
    for header in response.headers.get_list("set-cookie"):
        first = header.split(";", 1)[0]
        if first.lower().startswith(f"{name.lower()}="):
            return first.split("=", 1)[1]
    return None


def _state_from_authorize_location(location: str) -> str:
    query = parse_qs(urlparse(location).query)
    return str(query.get("state", [""])[0])


def _config() -> CognitoAuthConfig:
    return CognitoAuthConfig(
        client_id="test-client",
        client_secret="test-secret",
        server_metadata_url="https://example.test/.well-known/openid-configuration",
        redirect_uri="http://127.0.0.1:8000/api/v1/auth/callback",
    )


def _metadata() -> dict[str, Any]:
    return {
        "issuer": "https://cognito-idp.example.test/pool",
        "authorization_endpoint": "https://login.example.test/oauth2/authorize",
        "token_endpoint": "https://login.example.test/oauth2/token",
        "jwks_uri": "https://login.example.test/oauth2/jwks",
    }


def test_session_token_is_hashed_not_stored_raw(tmp_path):
    store = StudentStore(tmp_path / "sessions.sqlite3")
    service = AppSessionService(store, clock=lambda: FIXED_NOW)
    profile = store.upsert_cognito_user(
        cognito_sub="sub-a",
        identifier="cognito:sub-a",
        email="a@example.edu",
        display_name="Ada",
    )
    created = service.create_session(profile["id"])
    assert len(created.raw_token) >= 40
    assert created.raw_token not in (tmp_path / "sessions.sqlite3").read_bytes().decode(
        "latin-1", errors="ignore"
    )
    digest = hash_session_token(created.raw_token)
    with store._connect() as connection:
        row = connection.execute(
            "SELECT tokenHash FROM app_sessions WHERE id = ?",
            (created.session_id,),
        ).fetchone()
    assert row is not None
    assert row["tokenHash"] == digest
    assert row["tokenHash"] != created.raw_token


def test_valid_session_authenticates_and_isolates_users(tmp_path):
    store = StudentStore(tmp_path / "sessions.sqlite3")
    service = AppSessionService(store, clock=lambda: FIXED_NOW)
    user_a = store.upsert_cognito_user(
        cognito_sub="sub-a",
        identifier="cognito:sub-a",
        email="a@example.edu",
        display_name="Ada",
    )
    user_b = store.upsert_cognito_user(
        cognito_sub="sub-b",
        identifier="cognito:sub-b",
        email="b@example.edu",
        display_name="Bea",
    )
    session_a = service.create_session(user_a["id"])
    session_b = service.create_session(user_b["id"])
    resolved_a = service.get_session_user(session_a.raw_token)
    resolved_b = service.get_session_user(session_b.raw_token)
    assert resolved_a is not None
    assert resolved_b is not None
    assert resolved_a["cognito_sub"] == "sub-a"
    assert resolved_b["cognito_sub"] == "sub-b"
    assert resolved_a["id"] != resolved_b["id"]


def test_invalid_expired_revoked_sessions_do_not_authenticate(tmp_path):
    store = StudentStore(tmp_path / "sessions.sqlite3")
    now = FIXED_NOW

    def clock() -> datetime:
        return now

    service = AppSessionService(store, ttl_seconds=60, clock=clock)
    user = store.upsert_cognito_user(
        cognito_sub="sub-x",
        identifier="cognito:sub-x",
        email="x@example.edu",
        display_name="X",
    )
    created = service.create_session(user["id"])
    assert service.get_session_user("not-a-token") is None
    assert service.get_session_user(generate_session_token()) is None

    now = FIXED_NOW + timedelta(seconds=120)
    assert service.get_session_user(created.raw_token) is None

    now = FIXED_NOW
    fresh = service.create_session(user["id"])
    assert service.revoke_session(fresh.raw_token) is True
    assert service.get_session_user(fresh.raw_token) is None


def test_default_ttl_is_thirty_days(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "app_session_ttl_seconds", 2592000)
    store = StudentStore(tmp_path / "sessions.sqlite3")
    service = AppSessionService(store, clock=lambda: FIXED_NOW)
    assert service.ttl_seconds == 2592000
    user = store.upsert_cognito_user(
        cognito_sub="sub-ttl",
        identifier="cognito:sub-ttl",
        email=None,
        display_name="TTL",
    )
    created = service.create_session(user["id"])
    expected = (FIXED_NOW + timedelta(seconds=2592000)).isoformat()
    assert created.expires_at == expected


def test_auth_me_requires_valid_cookie(tmp_path, monkeypatch):
    store = StudentStore(tmp_path / "auth-me.sqlite3")
    monkeypatch.setattr(settings, "ui_base_url", "http://127.0.0.1:8501")
    monkeypatch.setattr(settings, "app_session_cookie_secure", False)
    sessions = AppSessionService(store, clock=lambda: FIXED_NOW)
    client = TestClient(create_app(store, session_service=sessions))
    assert client.get("/api/v1/auth/me").status_code == 401
    assert (
        client.get(
            "/api/v1/auth/me",
            cookies={settings.app_session_cookie_name: "bad"},
        ).status_code
        == 401
    )

    user = store.upsert_cognito_user(
        cognito_sub="sub-me",
        identifier="cognito:sub-me",
        email="me@example.edu",
        display_name="Me",
    )
    created = sessions.create_session(user["id"])
    response = client.get(
        "/api/v1/auth/me",
        cookies={settings.app_session_cookie_name: created.raw_token},
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["authenticated"] is True
    assert payload["user"]["cognito_sub"] == "sub-me"
    assert payload["user"]["email"] == "me@example.edu"
    blob = response.text.lower()
    assert "access_token" not in blob
    assert "refresh_token" not in blob
    assert "id_token" not in blob
    assert "token_hash" not in blob
    assert created.raw_token not in response.text


def test_logout_revokes_session_and_clears_cookie(tmp_path, monkeypatch):
    store = StudentStore(tmp_path / "logout.sqlite3")
    monkeypatch.setattr(settings, "ui_base_url", "http://127.0.0.1:8501")
    sessions = AppSessionService(store, clock=lambda: FIXED_NOW)
    client = TestClient(create_app(store, session_service=sessions))
    user = store.upsert_cognito_user(
        cognito_sub="sub-out",
        identifier="cognito:sub-out",
        email="out@example.edu",
        display_name="Out",
    )
    created = sessions.create_session(user["id"])
    response = client.get(
        "/api/v1/auth/logout",
        cookies={settings.app_session_cookie_name: created.raw_token},
        follow_redirects=False,
    )
    assert response.status_code == 302
    assert response.headers["location"] == "http://127.0.0.1:8501/?signed_out=1"
    set_cookie = ";".join(response.headers.get_list("set-cookie")).lower()
    assert settings.app_session_cookie_name in set_cookie
    assert "max-age=0" in set_cookie
    assert sessions.get_session_user(created.raw_token) is None
    assert (
        client.get(
            "/api/v1/auth/me",
            cookies={settings.app_session_cookie_name: created.raw_token},
        ).status_code
        == 401
    )


def test_callback_rejects_invalid_state_and_missing_sub(tmp_path, monkeypatch):
    store = StudentStore(tmp_path / "callback.sqlite3")
    monkeypatch.setattr(settings, "ui_base_url", "http://127.0.0.1:8501")
    oidc = CognitoOIDCClient(
        _config(),
        store=store,
        metadata_loader=lambda _url: _metadata(),
        clock=lambda: FIXED_NOW,
    )
    client = TestClient(
        create_app(
            store,
            session_service=AppSessionService(store, clock=lambda: FIXED_NOW),
            oidc_client=oidc,
        )
    )
    bad = client.get(
        "/api/v1/auth/callback",
        params={"code": "abc", "state": "nope"},
        follow_redirects=False,
    )
    assert bad.status_code == 302
    assert "auth_error=1" in bad.headers["location"]
    with store._connect() as connection:
        sessions = connection.execute("SELECT COUNT(*) AS n FROM app_sessions").fetchone()
    assert int(sessions["n"]) == 0

    class _MissingSub(CognitoOIDCClient):
        def complete_login(self, *, code: str, state: str):
            from backend.auth_oidc import CognitoIdentity

            return CognitoIdentity(sub="", email=None, claims={"email": "x@example.edu"})

    missing = TestClient(
        create_app(
            store,
            session_service=AppSessionService(store, clock=lambda: FIXED_NOW),
            oidc_client=_MissingSub(_config(), store=store, clock=lambda: FIXED_NOW),
        )
    )
    response = missing.get(
        "/api/v1/auth/callback",
        params={"code": "x", "state": "y"},
        cookies={_oauth_cookie_name(): "y"},
        follow_redirects=False,
    )
    assert response.status_code == 302
    assert "auth_error=1" in response.headers["location"]
    with store._connect() as connection:
        sessions = connection.execute("SELECT COUNT(*) AS n FROM app_sessions").fetchone()
    assert int(sessions["n"]) == 0


def test_callback_creates_session_cookie_without_persisting_tokens(
    tmp_path, monkeypatch
):
    store = StudentStore(tmp_path / "callback-ok.sqlite3")
    monkeypatch.setattr(settings, "ui_base_url", "http://127.0.0.1:8501")
    monkeypatch.setattr(settings, "app_session_cookie_secure", False)
    key = OctKey.generate_key(256, parameters={"alg": "HS256", "kid": "test"})
    claims = {
        "sub": "sub-callback",
        "email": "cb@example.edu",
        "given_name": "Callback",
        "iss": _metadata()["issuer"],
        "aud": "test-client",
        "exp": int((FIXED_NOW + timedelta(hours=1)).timestamp()),
        "iat": int(FIXED_NOW.timestamp()),
    }
    id_token = jwt.encode({"alg": "HS256", "kid": "test"}, claims, key)

    class _FakeOIDC(CognitoOIDCClient):
        def begin_login(self):
            return "https://login.example.test/oauth2/authorize?x=1", "good-state"

        def complete_login(self, *, code: str, state: str):
            if code != "good" or state != "good-state":
                raise CognitoOIDCError("bad")
            from backend.auth_oidc import CognitoIdentity

            return CognitoIdentity(
                sub="sub-callback",
                email="cb@example.edu",
                claims={
                    "sub": "sub-callback",
                    "email": "cb@example.edu",
                    "given_name": "Callback",
                    "access_token": "MUST-NOT-PERSIST",
                    "refresh_token": "MUST-NOT-PERSIST",
                    "id_token": id_token,
                },
            )

    oidc = _FakeOIDC(_config(), store=store, clock=lambda: FIXED_NOW)
    client = TestClient(
        create_app(
            store,
            session_service=AppSessionService(store, clock=lambda: FIXED_NOW),
            oidc_client=oidc,
        )
    )
    response = client.get(
        "/api/v1/auth/callback",
        params={"code": "good", "state": "good-state"},
        cookies={_oauth_cookie_name(): "good-state"},
        follow_redirects=False,
    )
    assert response.status_code == 302
    assert response.headers["location"] == "http://127.0.0.1:8501/"
    set_cookie = _set_cookie_header(response)
    assert f"{settings.app_session_cookie_name}=" in set_cookie
    assert "HttpOnly" in set_cookie
    assert "samesite=lax" in set_cookie.lower()
    assert f"{_oauth_cookie_name()}=" in set_cookie.lower() or any(
        _oauth_cookie_name() in h for h in response.headers.get_list("set-cookie")
    )
    # OAuth binder cleared (Max-Age=0) and session cookie set without Secure locally.
    oauth_clear = next(
        h
        for h in response.headers.get_list("set-cookie")
        if h.lower().startswith(f"{_oauth_cookie_name().lower()}=")
    )
    assert "max-age=0" in oauth_clear.lower()
    session_header = next(
        h
        for h in response.headers.get_list("set-cookie")
        if h.lower().startswith(f"{settings.app_session_cookie_name.lower()}=")
    )
    assert "secure" not in session_header.lower()
    db_text = (tmp_path / "callback-ok.sqlite3").read_bytes().decode(
        "latin-1", errors="ignore"
    )
    assert "MUST-NOT-PERSIST" not in db_text
    assert id_token not in db_text
    profile = store.get_user_by_cognito_sub("sub-callback")
    assert profile is not None
    assert profile["display_name"] == "Callback"


def test_login_sets_oauth_state_cookie(tmp_path, monkeypatch):
    store = StudentStore(tmp_path / "login.sqlite3")
    monkeypatch.setattr(settings, "app_session_cookie_secure", False)
    oidc = CognitoOIDCClient(
        _config(),
        store=store,
        metadata_loader=lambda _url: _metadata(),
        clock=lambda: FIXED_NOW,
    )
    client = TestClient(create_app(store, oidc_client=oidc))
    response = client.get("/api/v1/auth/login", follow_redirects=False)
    assert response.status_code == 302
    location = response.headers["location"]
    assert location.startswith("https://login.example.test/oauth2/authorize?")
    assert "code_challenge=" in location
    state = _state_from_authorize_location(location)
    assert state
    cookie_value = _cookie_value_from_response(response, _oauth_cookie_name())
    assert cookie_value == state
    header = next(
        h
        for h in response.headers.get_list("set-cookie")
        if h.lower().startswith(f"{_oauth_cookie_name().lower()}=")
    ).lower()
    assert "httponly" in header
    assert "samesite=lax" in header
    assert "path=/api/v1/auth" in header
    assert f"max-age={OAUTH_STATE_TTL_SECONDS}" in header
    assert "secure" not in header


def test_callback_requires_matching_oauth_state_cookie(tmp_path, monkeypatch):
    store = StudentStore(tmp_path / "state-bind.sqlite3")
    monkeypatch.setattr(settings, "ui_base_url", "http://127.0.0.1:8501")
    monkeypatch.setattr(settings, "app_session_cookie_secure", False)

    class _FakeOIDC(CognitoOIDCClient):
        def begin_login(self):
            return "https://login.example.test/oauth2/authorize?x=1", "bound-state"

        def complete_login(self, *, code: str, state: str):
            from backend.auth_oidc import CognitoIdentity

            return CognitoIdentity(
                sub="sub-bound",
                email="bound@example.edu",
                claims={"sub": "sub-bound", "email": "bound@example.edu", "given_name": "B"},
            )

    oidc = _FakeOIDC(_config(), store=store, clock=lambda: FIXED_NOW)
    client = TestClient(
        create_app(
            store,
            session_service=AppSessionService(store, clock=lambda: FIXED_NOW),
            oidc_client=oidc,
        )
    )

    no_cookie = client.get(
        "/api/v1/auth/callback",
        params={"code": "good", "state": "bound-state"},
        follow_redirects=False,
    )
    assert no_cookie.status_code == 302
    assert "auth_error=1" in no_cookie.headers["location"]

    mismatch = client.get(
        "/api/v1/auth/callback",
        params={"code": "good", "state": "bound-state"},
        cookies={_oauth_cookie_name(): "other-state"},
        follow_redirects=False,
    )
    assert mismatch.status_code == 302
    assert "auth_error=1" in mismatch.headers["location"]
    with store._connect() as connection:
        assert (
            int(
                connection.execute("SELECT COUNT(*) AS n FROM app_sessions").fetchone()[
                    "n"
                ]
            )
            == 0
        )

    ok = client.get(
        "/api/v1/auth/callback",
        params={"code": "good", "state": "bound-state"},
        cookies={_oauth_cookie_name(): "bound-state"},
        follow_redirects=False,
    )
    assert ok.status_code == 302
    assert ok.headers["location"] == "http://127.0.0.1:8501/"
    assert any(
        h.lower().startswith(f"{settings.app_session_cookie_name.lower()}=")
        for h in ok.headers.get_list("set-cookie")
    )
    oauth_clear = next(
        h
        for h in ok.headers.get_list("set-cookie")
        if h.lower().startswith(f"{_oauth_cookie_name().lower()}=")
    )
    assert "max-age=0" in oauth_clear.lower()

    # Replay with the same binder/state must not create another session once DB
    # state is gone; FakeOIDC would succeed, so use a real OIDC client for replay.
    real = CognitoOIDCClient(
        _config(),
        store=store,
        metadata_loader=lambda _url: _metadata(),
        clock=lambda: FIXED_NOW,
    )
    login = TestClient(create_app(store, oidc_client=real)).get(
        "/api/v1/auth/login", follow_redirects=False
    )
    state = _state_from_authorize_location(login.headers["location"])
    cookie = _cookie_value_from_response(login, _oauth_cookie_name())
    assert cookie == state
    # First consume via complete_login path with matching cookie but invalid code
    # clears DB state; second matching attempt must fail.
    first = TestClient(create_app(store, oidc_client=real)).get(
        "/api/v1/auth/callback",
        params={"code": "not-exchanged", "state": state},
        cookies={_oauth_cookie_name(): state},
        follow_redirects=False,
    )
    assert "auth_error=1" in first.headers["location"]
    replay = TestClient(create_app(store, oidc_client=real)).get(
        "/api/v1/auth/callback",
        params={"code": "not-exchanged", "state": state},
        cookies={_oauth_cookie_name(): state},
        follow_redirects=False,
    )
    assert "auth_error=1" in replay.headers["location"]
    with store._connect() as connection:
        remaining = connection.execute(
            "SELECT COUNT(*) AS n FROM oauth_login_states WHERE state = ?",
            (state,),
        ).fetchone()
    assert int(remaining["n"]) == 0


def test_login_redirects_to_cognito_authorize(tmp_path, monkeypatch):
    store = StudentStore(tmp_path / "login-redirect.sqlite3")
    oidc = CognitoOIDCClient(
        _config(),
        store=store,
        metadata_loader=lambda _url: _metadata(),
        clock=lambda: FIXED_NOW,
    )
    client = TestClient(create_app(store, oidc_client=oidc))
    response = client.get("/api/v1/auth/login", follow_redirects=False)
    assert response.status_code == 302
    location = response.headers["location"]
    assert location.startswith("https://login.example.test/oauth2/authorize?")
    assert "code_challenge=" in location
    assert "state=" in location


def test_cookie_settings_local_insecure():
    params = cookie_settings()
    assert params["httponly"] is True
    assert params["samesite"] == "lax"
    assert params["path"] == "/"
    assert params["key"] == settings.app_session_cookie_name
    oauth = oauth_state_cookie_settings(max_age=OAUTH_STATE_TTL_SECONDS)
    assert oauth["path"] == "/api/v1/auth"
    assert oauth["httponly"] is True
    assert oauth["samesite"] == "lax"
    assert oauth["max_age"] == OAUTH_STATE_TTL_SECONDS


def test_cognito_redirect_uri_precedence(monkeypatch, tmp_path):
    monkeypatch.delenv("COGNITO_REDIRECT_URI", raising=False)
    monkeypatch.setattr(
        settings, "public_api_base_url", "https://cde2300chatbot.duckdns.org"
    )
    monkeypatch.setattr(
        "backend.cognito_config._secrets_auth_table",
        lambda: {"redirect_uri": "https://from-secrets.example/api/v1/auth/callback"},
    )
    assert (
        load_cognito_auth_config().redirect_uri
        == "https://from-secrets.example/api/v1/auth/callback"
    )

    monkeypatch.setenv(
        "COGNITO_REDIRECT_URI",
        "https://cde2300chatbot.duckdns.org/api/v1/auth/callback",
    )
    assert (
        load_cognito_auth_config().redirect_uri
        == "https://cde2300chatbot.duckdns.org/api/v1/auth/callback"
    )



    monkeypatch.delenv("COGNITO_REDIRECT_URI", raising=False)
    monkeypatch.setattr(
        "backend.cognito_config._secrets_auth_table",
        lambda: {"redirect_uri": "http://127.0.0.1:8501/oauth2callback"},
    )
    assert (
        load_cognito_auth_config().redirect_uri
        == "https://cde2300chatbot.duckdns.org/api/v1/auth/callback"
    )


def test_callback_cognito_error_clears_oauth_state_cookie_without_session(
    tmp_path, monkeypatch
):
    store = StudentStore(tmp_path / "callback-error.sqlite3")
    monkeypatch.setattr(settings, "ui_base_url", "http://127.0.0.1:8501")
    client = TestClient(
        create_app(
            store,
            session_service=AppSessionService(store, clock=lambda: FIXED_NOW),
            oidc_client=CognitoOIDCClient(
                _config(),
                store=store,
                metadata_loader=lambda _url: _metadata(),
                clock=lambda: FIXED_NOW,
            ),
        )
    )
    response = client.get(
        "/api/v1/auth/callback",
        params={"error": "access_denied", "state": "any"},
        cookies={_oauth_cookie_name(): "any"},
        follow_redirects=False,
    )
    assert response.status_code == 302
    assert "auth_error=1" in response.headers["location"]
    oauth_clear = next(
        h
        for h in response.headers.get_list("set-cookie")
        if h.lower().startswith(f"{_oauth_cookie_name().lower()}=")
    )
    assert "max-age=0" in oauth_clear.lower()
    with store._connect() as connection:
        count = connection.execute("SELECT COUNT(*) AS n FROM app_sessions").fetchone()
    assert int(count["n"]) == 0


def test_logout_accepts_post_and_cleanup_expired_sessions(tmp_path, monkeypatch):
    store = StudentStore(tmp_path / "logout-post.sqlite3")
    monkeypatch.setattr(settings, "ui_base_url", "http://127.0.0.1:8501")
    sessions = AppSessionService(store, ttl_seconds=60, clock=lambda: FIXED_NOW)
    client = TestClient(create_app(store, session_service=sessions))
    user = store.upsert_cognito_user(
        cognito_sub="sub-post",
        identifier="cognito:sub-post",
        email="post@example.edu",
        display_name="Post",
    )
    created = sessions.create_session(user["id"])
    response = client.post(
        "/api/v1/auth/logout",
        cookies={settings.app_session_cookie_name: created.raw_token},
        follow_redirects=False,
    )
    assert response.status_code == 302
    assert "signed_out=1" in response.headers["location"]
    assert sessions.get_session_user(created.raw_token) is None

    expired = sessions.create_session(user["id"])
    later = AppSessionService(
        store,
        ttl_seconds=60,
        clock=lambda: FIXED_NOW + timedelta(seconds=120),
    )
    deleted = later.cleanup_expired_sessions()
    assert deleted >= 1
    assert later.get_session_user(expired.raw_token) is None
