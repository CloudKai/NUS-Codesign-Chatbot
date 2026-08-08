"""Deterministic Cognito cookie-session and FastAPI auth tests (no network)."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

import httpx
import pytest
from fastapi.testclient import TestClient
from joserfc import jwt
from joserfc.jwk import OctKey

from backend.api import create_app
from backend.auth_oidc import (
    CognitoAuthSession,
    CognitoIdentity,
    CognitoOIDCClient,
    CognitoOIDCError,
    OAUTH_STATE_TTL_SECONDS,
)
from backend.cognito_config import CognitoAuthConfig, load_cognito_auth_config
from backend.cognito_cookies import (
    AUTH_COOKIE_PATH,
    ID_TOKEN_COOKIE_PATH,
    id_token_cookie_settings,
    oauth_state_cookie_settings,
    refresh_cookie_settings,
)
from backend.settings import settings
from backend.student_store import StudentStore


FIXED_NOW = datetime(2026, 1, 15, 12, 0, tzinfo=timezone.utc)
_SIGNING_KEY = OctKey.generate_key(256, parameters={"alg": "HS256", "kid": "test"})


def _set_cookie_header(response) -> str:
    return ";".join(response.headers.get_list("set-cookie"))


def _oauth_cookie_name() -> str:
    return settings.oauth_state_cookie_name


def _id_cookie_name() -> str:
    return settings.cognito_id_token_cookie_name


def _refresh_cookie_name() -> str:
    return settings.cognito_refresh_cookie_name


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
        "revocation_endpoint": "https://login.example.test/oauth2/revoke",
    }


def _mint_id_token(
    *,
    sub: str,
    email: str | None = None,
    exp_delta: timedelta = timedelta(hours=1),
    now: datetime | None = None,
) -> str:
    issued = now or datetime.now(timezone.utc)
    claims = {
        "sub": sub,
        "email": email or f"{sub}@example.edu",
        "given_name": sub.replace("sub-", "").title(),
        "iss": _metadata()["issuer"],
        "aud": "test-client",
        "exp": int((issued + exp_delta).timestamp()),
        "iat": int(issued.timestamp()),
    }
    return jwt.encode({"alg": "HS256", "kid": "test"}, claims, _SIGNING_KEY)


class _RecordingOIDC(CognitoOIDCClient):
    """Deterministic OIDC client with in-memory verify/refresh/revoke."""

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.refresh_calls: list[str] = []
        self.revoke_calls: list[str] = []
        self._refresh_should_fail = False
        self._sessions: dict[str, CognitoAuthSession] = {}

    def seed_session(
        self,
        *,
        sub: str,
        refresh_token: str,
        id_token: str | None = None,
        email: str | None = None,
    ) -> CognitoAuthSession:
        token = id_token or _mint_id_token(sub=sub, email=email)
        session = CognitoAuthSession(
            identity=CognitoIdentity(
                sub=sub,
                email=email or f"{sub}@example.edu",
                claims={
                    "sub": sub,
                    "email": email or f"{sub}@example.edu",
                    "given_name": sub.replace("sub-", "").title(),
                },
            ),
            refresh_token=refresh_token,
            id_token=token,
        )
        self._sessions[refresh_token] = session
        return session

    def verify_id_token(self, id_token: str) -> CognitoIdentity:
        token = str(id_token or "").strip()
        if not token:
            raise CognitoOIDCError("Missing ID token")
        try:
            claims = dict(jwt.decode(token, _SIGNING_KEY).claims)
            jwt.JWTClaimsRegistry(
                iss={"essential": True, "value": _metadata()["issuer"]},
                aud={"essential": True, "value": "test-client"},
                exp={"essential": True},
                sub={"essential": True},
            ).validate(claims)
        except Exception as error:
            raise CognitoOIDCError("Cognito ID token verification failed") from error
        sub = str(claims.get("sub") or "").strip()
        if not sub:
            raise CognitoOIDCError("Cognito ID token missing sub")
        email = str(claims.get("email") or "").strip() or None
        return CognitoIdentity(sub=sub, email=email, claims=dict(claims))

    def refresh(self, refresh_token: str) -> CognitoAuthSession:
        raw = str(refresh_token or "").strip()
        self.refresh_calls.append(raw)
        if self._refresh_should_fail or raw not in self._sessions:
            raise CognitoOIDCError("Cognito refresh failed")
        prior = self._sessions[raw]
        new_id = _mint_id_token(sub=prior.identity.sub, email=prior.identity.email)
        session = CognitoAuthSession(
            identity=prior.identity,
            refresh_token=raw,
            id_token=new_id,
        )
        self._sessions[raw] = session
        return session

    def revoke(self, refresh_token: str) -> bool:
        raw = str(refresh_token or "").strip()
        if not raw:
            return False
        self.revoke_calls.append(raw)
        self._sessions.pop(raw, None)
        return True


def test_auth_me_requires_valid_id_cookie(tmp_path, monkeypatch):
    store = StudentStore(tmp_path / "auth-me.sqlite3")
    monkeypatch.setattr(settings, "ui_base_url", "http://127.0.0.1:8501")
    monkeypatch.setattr(settings, "auth_cookie_secure", False)
    oidc = _RecordingOIDC(
        _config(),
        store=store,
        metadata_loader=lambda _url: _metadata(),
        clock=lambda: FIXED_NOW,
    )
    client = TestClient(create_app(store, oidc_client=oidc))
    assert client.get("/api/v1/auth/me").status_code == 401
    assert (
        client.get(
            "/api/v1/auth/me",
            cookies={_id_cookie_name(): "bad"},
        ).status_code
        == 401
    )

    store.upsert_cognito_user(
        cognito_sub="sub-me",
        identifier="cognito:sub-me",
        email="me@example.edu",
        display_name="Me",
    )
    session = oidc.seed_session(
        sub="sub-me",
        refresh_token="refresh-me",
        email="me@example.edu",
    )
    response = client.get(
        "/api/v1/auth/me",
        cookies={_id_cookie_name(): session.id_token},
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
    assert session.id_token not in response.text
    assert session.refresh_token not in response.text
    assert oidc.refresh_calls == []


def test_auth_me_refreshes_expired_id_cookie(tmp_path, monkeypatch):
    store = StudentStore(tmp_path / "auth-refresh.sqlite3")
    monkeypatch.setattr(settings, "ui_base_url", "http://127.0.0.1:8501")
    monkeypatch.setattr(settings, "auth_cookie_secure", False)
    oidc = _RecordingOIDC(
        _config(),
        store=store,
        metadata_loader=lambda _url: _metadata(),
        clock=lambda: FIXED_NOW,
    )
    store.upsert_cognito_user(
        cognito_sub="sub-ref",
        identifier="cognito:sub-ref",
        email="ref@example.edu",
        display_name="Ref",
    )
    session = oidc.seed_session(
        sub="sub-ref",
        refresh_token="refresh-ref",
        email="ref@example.edu",
    )
    expired = _mint_id_token(
        sub="sub-ref", email="ref@example.edu", exp_delta=timedelta(hours=-1)
    )
    client = TestClient(create_app(store, oidc_client=oidc))
    response = client.get(
        "/api/v1/auth/me",
        cookies={
            _id_cookie_name(): expired,
            _refresh_cookie_name(): session.refresh_token,
        },
    )
    assert response.status_code == 200
    assert response.json()["user"]["cognito_sub"] == "sub-ref"
    assert oidc.refresh_calls == ["refresh-ref"]
    set_cookie = _set_cookie_header(response).lower()
    assert _id_cookie_name().lower() in set_cookie
    assert "httponly" in set_cookie
    assert f"path={ID_TOKEN_COOKIE_PATH}" in set_cookie
    new_id = _cookie_value_from_response(response, _id_cookie_name())
    assert new_id
    assert new_id != expired
    assert "refresh-ref" not in response.text


def test_auth_me_refresh_failure_clears_cookies(tmp_path, monkeypatch):
    store = StudentStore(tmp_path / "auth-fail.sqlite3")
    monkeypatch.setattr(settings, "auth_cookie_secure", False)
    oidc = _RecordingOIDC(
        _config(),
        store=store,
        metadata_loader=lambda _url: _metadata(),
        clock=lambda: FIXED_NOW,
    )
    oidc._refresh_should_fail = True
    expired = _mint_id_token(sub="sub-x", exp_delta=timedelta(hours=-1))
    client = TestClient(create_app(store, oidc_client=oidc))
    response = client.get(
        "/api/v1/auth/me",
        cookies={
            _id_cookie_name(): expired,
            _refresh_cookie_name(): "stale-refresh",
        },
    )
    assert response.status_code == 401
    headers = [h.lower() for h in response.headers.get_list("set-cookie")]
    assert any(_id_cookie_name().lower() in h and "max-age=0" in h for h in headers)
    assert any(
        _refresh_cookie_name().lower() in h and "max-age=0" in h for h in headers
    )


def test_browser_refresh_bridge_keeps_refresh_token_out_of_streamlit(
    tmp_path, monkeypatch
):
    store = StudentStore(tmp_path / "auth-bridge.sqlite3")
    monkeypatch.setattr(settings, "ui_base_url", "http://127.0.0.1:8501")
    monkeypatch.setattr(settings, "auth_cookie_secure", False)
    oidc = _RecordingOIDC(
        _config(),
        store=store,
        metadata_loader=lambda _url: _metadata(),
        clock=lambda: FIXED_NOW,
    )
    session = oidc.seed_session(
        sub="sub-bridge",
        refresh_token="refresh-bridge",
        email="bridge@example.edu",
    )
    client = TestClient(create_app(store, oidc_client=oidc))

    response = client.get(
        "/api/v1/auth/refresh",
        cookies={_refresh_cookie_name(): session.refresh_token},
        follow_redirects=False,
    )

    assert response.status_code == 302
    assert response.headers["location"] == "http://127.0.0.1:8501/"
    assert oidc.refresh_calls == ["refresh-bridge"]
    assert response.text.find(session.refresh_token) == -1
    id_header = next(
        header
        for header in response.headers.get_list("set-cookie")
        if header.lower().startswith(f"{_id_cookie_name().lower()}=")
    ).lower()
    refresh_header = next(
        header
        for header in response.headers.get_list("set-cookie")
        if header.lower().startswith(f"{_refresh_cookie_name().lower()}=")
    ).lower()
    assert f"path={ID_TOKEN_COOKIE_PATH}" in id_header
    assert f"path={AUTH_COOKIE_PATH}" in refresh_header
    assert store.get_user_by_cognito_sub("sub-bridge") is not None


def test_browser_refresh_bridge_failure_clears_cookies(tmp_path, monkeypatch):
    store = StudentStore(tmp_path / "auth-bridge-fail.sqlite3")
    monkeypatch.setattr(settings, "ui_base_url", "http://127.0.0.1:8501")
    monkeypatch.setattr(settings, "auth_cookie_secure", False)
    oidc = _RecordingOIDC(
        _config(),
        store=store,
        metadata_loader=lambda _url: _metadata(),
        clock=lambda: FIXED_NOW,
    )
    oidc._refresh_should_fail = True
    client = TestClient(create_app(store, oidc_client=oidc))

    response = client.get(
        "/api/v1/auth/refresh",
        cookies={_refresh_cookie_name(): "expired-refresh"},
        follow_redirects=False,
    )

    assert response.status_code == 302
    assert response.headers["location"].endswith("/?auth_required=1")
    headers = [header.lower() for header in response.headers.get_list("set-cookie")]
    assert any(_id_cookie_name().lower() in header for header in headers)
    assert any(_refresh_cookie_name().lower() in header for header in headers)
    assert all("max-age=0" in header for header in headers)


def test_oidc_refresh_grant_and_revocation_are_mocked_without_token_logs(
    tmp_path, monkeypatch, caplog
):
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        form = parse_qs(request.content.decode("utf-8"))
        if request.url.path.endswith("/token"):
            assert form["grant_type"] == ["refresh_token"]
            assert form["refresh_token"] == ["RAW-REFRESH-SECRET"]
            return httpx.Response(
                200,
                json={"id_token": "new-id-token", "access_token": "unused"},
            )
        if request.url.path.endswith("/revoke"):
            assert form["token"] == ["RAW-REFRESH-SECRET"]
            return httpx.Response(200)
        return httpx.Response(404)

    store = StudentStore(tmp_path / "oidc-http.sqlite3")
    oidc = CognitoOIDCClient(
        _config(),
        store=store,
        transport=httpx.MockTransport(handler),
        metadata_loader=lambda _url: _metadata(),
    )
    monkeypatch.setattr(
        oidc,
        "_verify_id_token",
        lambda _token, **_kwargs: {
            "sub": "sub-http",
            "email": "http@example.edu",
        },
    )

    session = oidc.refresh("RAW-REFRESH-SECRET")
    assert session.identity.sub == "sub-http"
    assert session.refresh_token == "RAW-REFRESH-SECRET"
    assert "RAW-REFRESH-SECRET" not in repr(session)
    assert "new-id-token" not in repr(session)
    assert oidc.revoke("RAW-REFRESH-SECRET") is True
    assert [request.url.path for request in requests] == [
        "/oauth2/token",
        "/oauth2/revoke",
    ]
    failing = CognitoOIDCClient(
        _config(),
        store=store,
        transport=httpx.MockTransport(lambda _request: httpx.Response(400)),
        metadata_loader=lambda _url: _metadata(),
    )
    with pytest.raises(CognitoOIDCError):
        failing.refresh("ANOTHER-RAW-REFRESH")
    assert "RAW-REFRESH-SECRET" not in caplog.text
    assert "ANOTHER-RAW-REFRESH" not in caplog.text


def test_users_isolated_by_cognito_sub(tmp_path, monkeypatch):
    store = StudentStore(tmp_path / "isolate.sqlite3")
    monkeypatch.setattr(settings, "auth_cookie_secure", False)
    oidc = _RecordingOIDC(
        _config(),
        store=store,
        metadata_loader=lambda _url: _metadata(),
        clock=lambda: FIXED_NOW,
    )
    store.upsert_cognito_user(
        cognito_sub="sub-a",
        identifier="cognito:sub-a",
        email="a@example.edu",
        display_name="Ada",
    )
    store.upsert_cognito_user(
        cognito_sub="sub-b",
        identifier="cognito:sub-b",
        email="b@example.edu",
        display_name="Bea",
    )
    session_a = oidc.seed_session(sub="sub-a", refresh_token="ra", email="a@example.edu")
    session_b = oidc.seed_session(sub="sub-b", refresh_token="rb", email="b@example.edu")
    client = TestClient(create_app(store, oidc_client=oidc))
    a = client.get("/api/v1/auth/me", cookies={_id_cookie_name(): session_a.id_token})
    b = client.get("/api/v1/auth/me", cookies={_id_cookie_name(): session_b.id_token})
    assert a.json()["user"]["cognito_sub"] == "sub-a"
    assert b.json()["user"]["cognito_sub"] == "sub-b"
    assert a.json()["user"]["id"] != b.json()["user"]["id"]


def test_logout_revokes_refresh_and_clears_cookies(tmp_path, monkeypatch):
    store = StudentStore(tmp_path / "logout.sqlite3")
    monkeypatch.setattr(settings, "ui_base_url", "http://127.0.0.1:8501")
    monkeypatch.setattr(settings, "auth_cookie_secure", False)
    oidc = _RecordingOIDC(
        _config(),
        store=store,
        metadata_loader=lambda _url: _metadata(),
        clock=lambda: FIXED_NOW,
    )
    store.upsert_cognito_user(
        cognito_sub="sub-out",
        identifier="cognito:sub-out",
        email="out@example.edu",
        display_name="Out",
    )
    session = oidc.seed_session(
        sub="sub-out", refresh_token="refresh-out", email="out@example.edu"
    )
    client = TestClient(create_app(store, oidc_client=oidc))
    response = client.get(
        "/api/v1/auth/logout",
        cookies={
            _id_cookie_name(): session.id_token,
            _refresh_cookie_name(): session.refresh_token,
        },
        follow_redirects=False,
    )
    assert response.status_code == 302
    assert response.headers["location"] == "http://127.0.0.1:8501/?signed_out=1"
    assert oidc.revoke_calls == ["refresh-out"]
    set_cookie = ";".join(response.headers.get_list("set-cookie")).lower()
    assert _id_cookie_name().lower() in set_cookie
    assert _refresh_cookie_name().lower() in set_cookie
    assert "max-age=0" in set_cookie
    # Refresh grant is revoked; ID JWT may still verify until short Max-Age/exp.
    assert (
        client.get(
            "/api/v1/auth/me",
            cookies={
                _id_cookie_name(): _mint_id_token(
                    sub="sub-out", exp_delta=timedelta(hours=-1)
                ),
                _refresh_cookie_name(): session.refresh_token,
            },
        ).status_code
        == 401
    )


def test_logout_idempotent_without_cookies(tmp_path, monkeypatch):
    store = StudentStore(tmp_path / "logout-empty.sqlite3")
    monkeypatch.setattr(settings, "ui_base_url", "http://127.0.0.1:8501")
    client = TestClient(create_app(store))
    response = client.post("/api/v1/auth/logout", follow_redirects=False)
    assert response.status_code == 302
    assert "signed_out=1" in response.headers["location"]
    headers = [h.lower() for h in response.headers.get_list("set-cookie")]
    assert any(_id_cookie_name().lower() in h and "max-age=0" in h for h in headers)
    assert any(
        _refresh_cookie_name().lower() in h and "max-age=0" in h for h in headers
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
    client = TestClient(create_app(store, oidc_client=oidc))
    bad = client.get(
        "/api/v1/auth/callback",
        params={"code": "abc", "state": "nope"},
        follow_redirects=False,
    )
    assert bad.status_code == 302
    assert "auth_error=1" in bad.headers["location"]

    class _MissingSub(CognitoOIDCClient):
        def complete_login(self, *, code: str, state: str):
            return CognitoAuthSession(
                identity=CognitoIdentity(
                    sub="", email=None, claims={"email": "x@example.edu"}
                ),
                refresh_token="r",
                id_token="i",
            )

    missing = TestClient(
        create_app(
            store,
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


def test_callback_sets_auth_cookies_without_persisting_tokens(tmp_path, monkeypatch):
    store = StudentStore(tmp_path / "callback-ok.sqlite3")
    monkeypatch.setattr(settings, "ui_base_url", "http://127.0.0.1:8501")
    monkeypatch.setattr(settings, "auth_cookie_secure", False)
    id_token = _mint_id_token(sub="sub-callback", email="cb@example.edu")

    class _FakeOIDC(CognitoOIDCClient):
        def begin_login(self):
            return "https://login.example.test/oauth2/authorize?x=1", "good-state"

        def complete_login(self, *, code: str, state: str):
            if code != "good" or state != "good-state":
                raise CognitoOIDCError("bad")
            return CognitoAuthSession(
                identity=CognitoIdentity(
                    sub="sub-callback",
                    email="cb@example.edu",
                    claims={
                        "sub": "sub-callback",
                        "email": "cb@example.edu",
                        "given_name": "Callback",
                    },
                ),
                refresh_token="REFRESH-MUST-NOT-PERSIST",
                id_token=id_token,
            )

    oidc = _FakeOIDC(_config(), store=store, clock=lambda: FIXED_NOW)
    client = TestClient(create_app(store, oidc_client=oidc))
    response = client.get(
        "/api/v1/auth/callback",
        params={"code": "good", "state": "good-state"},
        cookies={_oauth_cookie_name(): "good-state"},
        follow_redirects=False,
    )
    assert response.status_code == 302
    assert response.headers["location"] == "http://127.0.0.1:8501/"
    set_cookie = _set_cookie_header(response)
    assert f"{_id_cookie_name()}=" in set_cookie
    assert f"{_refresh_cookie_name()}=" in set_cookie
    assert "HttpOnly" in set_cookie
    assert "samesite=lax" in set_cookie.lower()
    assert f"path={AUTH_COOKIE_PATH}" in set_cookie.lower()
    oauth_clear = next(
        h
        for h in response.headers.get_list("set-cookie")
        if h.lower().startswith(f"{_oauth_cookie_name().lower()}=")
    )
    assert "max-age=0" in oauth_clear.lower()
    id_header = next(
        h
        for h in response.headers.get_list("set-cookie")
        if h.lower().startswith(f"{_id_cookie_name().lower()}=")
    )
    refresh_header = next(
        h
        for h in response.headers.get_list("set-cookie")
        if h.lower().startswith(f"{_refresh_cookie_name().lower()}=")
    )
    assert "secure" not in id_header.lower()
    assert "secure" not in refresh_header.lower()
    db_text = (tmp_path / "callback-ok.sqlite3").read_bytes().decode(
        "latin-1", errors="ignore"
    )
    assert "REFRESH-MUST-NOT-PERSIST" not in db_text
    assert id_token not in db_text
    profile = store.get_user_by_cognito_sub("sub-callback")
    assert profile is not None
    assert profile["display_name"] == "Callback"
    with store._connect() as connection:
        names = {
            str(row["name"])
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
        }
    assert "app_sessions" not in names


def test_login_sets_oauth_state_cookie(tmp_path, monkeypatch):
    store = StudentStore(tmp_path / "login.sqlite3")
    monkeypatch.setattr(settings, "auth_cookie_secure", False)
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
    assert f"path={AUTH_COOKIE_PATH}" in header
    assert f"max-age={OAUTH_STATE_TTL_SECONDS}" in header
    assert "secure" not in header


def test_callback_requires_matching_oauth_state_cookie(tmp_path, monkeypatch):
    store = StudentStore(tmp_path / "state-bind.sqlite3")
    monkeypatch.setattr(settings, "ui_base_url", "http://127.0.0.1:8501")
    monkeypatch.setattr(settings, "auth_cookie_secure", False)

    class _FakeOIDC(CognitoOIDCClient):
        def begin_login(self):
            return "https://login.example.test/oauth2/authorize?x=1", "bound-state"

        def complete_login(self, *, code: str, state: str):
            return CognitoAuthSession(
                identity=CognitoIdentity(
                    sub="sub-bound",
                    email="bound@example.edu",
                    claims={
                        "sub": "sub-bound",
                        "email": "bound@example.edu",
                        "given_name": "B",
                    },
                ),
                refresh_token="refresh-bound",
                id_token=_mint_id_token(sub="sub-bound", email="bound@example.edu"),
            )

    oidc = _FakeOIDC(_config(), store=store, clock=lambda: FIXED_NOW)
    client = TestClient(create_app(store, oidc_client=oidc))

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

    ok = client.get(
        "/api/v1/auth/callback",
        params={"code": "good", "state": "bound-state"},
        cookies={_oauth_cookie_name(): "bound-state"},
        follow_redirects=False,
    )
    assert ok.status_code == 302
    assert ok.headers["location"] == "http://127.0.0.1:8501/"
    assert any(
        h.lower().startswith(f"{_id_cookie_name().lower()}=")
        for h in ok.headers.get_list("set-cookie")
    )
    assert any(
        h.lower().startswith(f"{_refresh_cookie_name().lower()}=")
        for h in ok.headers.get_list("set-cookie")
    )
    oauth_clear = next(
        h
        for h in ok.headers.get_list("set-cookie")
        if h.lower().startswith(f"{_oauth_cookie_name().lower()}=")
    )
    assert "max-age=0" in oauth_clear.lower()

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


def test_cookie_settings_local_insecure(monkeypatch):
    monkeypatch.setattr(settings, "auth_cookie_secure", False)
    monkeypatch.setattr(settings, "cognito_refresh_cookie_max_age", 2592000)
    monkeypatch.setattr(settings, "cognito_id_token_cookie_max_age", 3600)
    refresh = refresh_cookie_settings()
    id_cookie = id_token_cookie_settings()
    assert refresh["httponly"] is True
    assert refresh["samesite"] == "lax"
    assert refresh["path"] == AUTH_COOKIE_PATH
    assert refresh["secure"] is False
    assert refresh["max_age"] == 2592000
    assert refresh["key"] == settings.cognito_refresh_cookie_name
    assert id_cookie["path"] == ID_TOKEN_COOKIE_PATH
    assert id_cookie["max_age"] == 3600
    assert id_cookie["httponly"] is True
    oauth = oauth_state_cookie_settings(max_age=OAUTH_STATE_TTL_SECONDS)
    assert oauth["path"] == AUTH_COOKIE_PATH
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


def test_callback_cognito_error_clears_oauth_state_cookie(tmp_path, monkeypatch):
    store = StudentStore(tmp_path / "callback-error.sqlite3")
    monkeypatch.setattr(settings, "ui_base_url", "http://127.0.0.1:8501")
    client = TestClient(
        create_app(
            store,
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
