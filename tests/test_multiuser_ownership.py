"""Deterministic multi-user ownership tests for Cognito → FastAPI → store/S3."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from fastapi.testclient import TestClient
from joserfc import jwt
from joserfc.jwk import OctKey

from backend.api import create_app
from backend.auth_oidc import (
    CognitoAuthSession,
    CognitoIdentity,
    CognitoOIDCClient,
    CognitoOIDCError,
)
from backend.cognito_config import CognitoAuthConfig
from backend.domain import SourceUpdateRequest
from backend.owner_context import OwnerResolver
from backend.persistence.factory import reset_file_storage_cache
from backend.persistence.memory_files import MemoryFileStorage
from backend.persistence.object_keys import (
    build_upload_object_key,
    notebook_prefix,
    sanitize_filename,
)
from backend.settings import settings
from backend.source_library import CourseMaterialSyncCoordinator, add_file_sources
from backend.student_store import StudentStore


FIXED_NOW = datetime(2026, 1, 15, 12, 0, tzinfo=timezone.utc)
_SIGNING_KEY = OctKey.generate_key(256, parameters={"alg": "HS256", "kid": "mu"})


def _id_cookie_name() -> str:
    return settings.cognito_id_token_cookie_name


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


def _mint_id_token(*, sub: str, email: str | None = None) -> str:
    issued = FIXED_NOW
    claims = {
        "sub": sub,
        "email": email or f"{sub}@example.edu",
        "given_name": sub,
        "iss": _metadata()["issuer"],
        "aud": "test-client",
        "token_use": "id",
        "exp": int((issued + timedelta(hours=1)).timestamp()),
        "iat": int(issued.timestamp()),
    }
    return jwt.encode({"alg": "HS256", "kid": "mu"}, claims, _SIGNING_KEY)


class _FakeOIDC(CognitoOIDCClient):
    """In-memory ID-token verifier for multi-user API tests."""

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self._sessions: dict[str, CognitoAuthSession] = {}

    def seed(self, *, sub: str, email: str | None = None) -> CognitoAuthSession:
        token = _mint_id_token(sub=sub, email=email)
        session = CognitoAuthSession(
            identity=CognitoIdentity(
                sub=sub,
                email=email or f"{sub}@example.edu",
                claims={
                    "sub": sub,
                    "email": email or f"{sub}@example.edu",
                    "given_name": sub,
                },
            ),
            refresh_token=f"refresh-{sub}",
            id_token=token,
        )
        self._sessions[token] = session
        return session

    def verify_id_token(self, id_token: str) -> CognitoIdentity:
        token = str(id_token or "").strip()
        session = self._sessions.get(token)
        if session is None:
            raise CognitoOIDCError("Unknown ID token")
        return session.identity


def _seed_user(store: StudentStore, *, sub: str, email: str) -> dict[str, Any]:
    return store.upsert_cognito_user(
        cognito_sub=sub,
        identifier=f"cognito:{sub}",
        email=email,
        display_name=sub,
    )


def _client_for(tmp_path, monkeypatch):
    db = tmp_path / "multiuser.sqlite3"
    bootstrap = StudentStore(db, identifier="local-student")
    oidc = _FakeOIDC(
        _config(),
        store=bootstrap,
        metadata_loader=lambda _url: _metadata(),
        clock=lambda: FIXED_NOW,
    )
    monkeypatch.setattr(settings, "auth_cookie_secure", False)
    client = TestClient(create_app(bootstrap, oidc_client=oidc))
    return client, bootstrap, oidc, db


def test_user_a_cannot_access_user_b_notebook_or_sources(tmp_path, monkeypatch):
    client, bootstrap, oidc, db = _client_for(tmp_path, monkeypatch)
    user_a = _seed_user(bootstrap, sub="sub-a", email="a@example.edu")
    user_b = _seed_user(bootstrap, sub="sub-b", email="b@example.edu")
    assert user_a["id"] != user_b["id"]

    store_b = StudentStore(db, identifier="cognito:sub-b")
    notebook_b = store_b.create_thread(
        name="B notebook", model_id="mock", support_mode="critical-thinking"
    )
    source_b = store_b.add_source(
        notebook_b,
        kind="file",
        title="b.txt",
        mime="text/plain",
        path="users/b/notebooks/n/sources/s/b.txt",
        selected=True,
        metadata={"object_key": "users/b/notebooks/n/sources/s/b.txt"},
    )

    session_a = oidc.seed(sub="sub-a", email="a@example.edu")
    cookies_a = {_id_cookie_name(): session_a.id_token}

    assert (
        client.get(f"/api/v1/threads/{notebook_b}", cookies=cookies_a).status_code
        == 404
    )
    assert (
        client.get(
            f"/api/v1/threads/{notebook_b}/sources/{source_b}",
            cookies=cookies_a,
        ).status_code
        == 404
    )
    assert (
        client.patch(
            f"/api/v1/threads/{notebook_b}/sources/{source_b}",
            json=SourceUpdateRequest(selected=False).model_dump(exclude_none=True),
            cookies=cookies_a,
        ).status_code
        == 404
    )
    assert (
        client.delete(
            f"/api/v1/threads/{notebook_b}/sources/{source_b}",
            cookies=cookies_a,
        ).status_code
        == 404
    )
    upload = client.post(
        f"/api/v1/threads/{notebook_b}/sources",
        files=[("files", ("evil.txt", b"nope", "text/plain"))],
        cookies=cookies_a,
    )
    assert upload.status_code == 404
    # Ownership intact for B.
    assert store_b.get_source(notebook_b, source_b) is not None


def test_client_supplied_user_identity_is_ignored(tmp_path, monkeypatch):
    client, bootstrap, oidc, db = _client_for(tmp_path, monkeypatch)
    _seed_user(bootstrap, sub="sub-a", email="a@example.edu")
    _seed_user(bootstrap, sub="sub-b", email="b@example.edu")
    store_b = StudentStore(db, identifier="cognito:sub-b")
    notebook_b = store_b.create_thread(
        name="B", model_id="mock", support_mode="critical-thinking"
    )
    session_a = oidc.seed(sub="sub-a")
    cookies_a = {_id_cookie_name(): session_a.id_token}

    response = client.get(
        f"/api/v1/threads/{notebook_b}",
        cookies=cookies_a,
        headers={"X-User-Id": store_b.owner_id, "X-Owner-Id": "cognito:sub-b"},
        params={"user_id": store_b.owner_id, "identifier": "cognito:sub-b"},
    )
    assert response.status_code == 404


def test_authenticated_owner_can_manage_own_notebook(tmp_path, monkeypatch):
    client, bootstrap, oidc, _db = _client_for(tmp_path, monkeypatch)
    _seed_user(bootstrap, sub="sub-a", email="a@example.edu")
    session_a = oidc.seed(sub="sub-a")
    cookies = {_id_cookie_name(): session_a.id_token}

    created = client.post(
        "/api/v1/threads",
        json={
            "name": "A notebook",
            "model_id": "mock",
            "support_mode": "critical-thinking",
        },
        cookies=cookies,
    )
    assert created.status_code == 200
    notebook_id = created.json()["id"]
    listed = client.get("/api/v1/threads", cookies=cookies)
    assert listed.status_code == 200
    assert any(item["id"] == notebook_id for item in listed.json())


def test_production_providers_require_auth_cookie(tmp_path, monkeypatch):
    store = StudentStore(tmp_path / "prod-auth.sqlite3")
    oidc = _FakeOIDC(
        _config(),
        store=store,
        metadata_loader=lambda _url: _metadata(),
        clock=lambda: FIXED_NOW,
    )
    resolver = OwnerResolver(
        store,
        oidc=oidc,
        course_sync=CourseMaterialSyncCoordinator(),
        auto_advance_stages=False,
    )
    monkeypatch.setattr(settings, "database_provider", "dsql")
    assert resolver.requires_authenticated_owner() is True
    monkeypatch.setattr(settings, "database_provider", "sqlite")
    monkeypatch.setattr(settings, "file_storage_provider", "s3")
    assert resolver.requires_authenticated_owner() is True
    monkeypatch.setattr(settings, "file_storage_provider", "local")
    assert resolver.requires_authenticated_owner() is False


def test_same_filename_produces_isolated_object_keys(tmp_path, monkeypatch):
    memory = MemoryFileStorage()
    monkeypatch.setattr(settings, "file_storage_provider", "memory")
    reset_file_storage_cache()
    monkeypatch.setattr(
        "backend.persistence.factory.get_file_storage",
        lambda: memory,
    )

    store_a = StudentStore(tmp_path / "a.sqlite3", identifier="cognito:a")
    store_b = StudentStore(tmp_path / "b.sqlite3", identifier="cognito:b")
    notebook_a = store_a.create_thread(model_id="mock", support_mode="guided")
    notebook_b = store_b.create_thread(model_id="mock", support_mode="guided")
    notebook_a2 = store_a.create_thread(model_id="mock", support_mode="guided")

    created_a = add_file_sources(
        store_a, notebook_a, [("report.pdf", b"%PDF-1", "application/pdf")]
    )
    created_b = add_file_sources(
        store_b, notebook_b, [("report.pdf", b"%PDF-2", "application/pdf")]
    )
    created_a2 = add_file_sources(
        store_a, notebook_a2, [("report.pdf", b"%PDF-3", "application/pdf")]
    )

    key_a = created_a[0]["object_key"]
    key_b = created_b[0]["object_key"]
    key_a2 = created_a2[0]["object_key"]
    assert key_a != key_b
    assert key_a != key_a2
    assert created_a[0]["id"] in key_a
    assert "/notebooks/" in key_a and "/sources/" in key_a
    assert key_a.startswith(f"users/{sanitize_filename(store_a.owner_id)}/")
    assert key_b.startswith(f"users/{sanitize_filename(store_b.owner_id)}/")
    assert memory.get_bytes(key_a) == b"%PDF-1"
    assert memory.get_bytes(key_b) == b"%PDF-2"

    # Source deletion must not remove another user's object.
    store_a.delete_source(notebook_a, created_a[0]["id"])
    assert not memory.exists(key_a)
    assert memory.exists(key_b)

    # Notebook deletion removes only that notebook prefix.
    prefix_b = notebook_prefix(user_id=store_b.owner_id, notebook_id=notebook_b)
    store_b.delete_thread(notebook_b)
    assert not any(key.startswith(prefix_b) for key in memory._objects)
    assert memory.exists(key_a2)


def test_unsafe_filenames_are_sanitized_in_object_keys():
    key = build_upload_object_key(
        user_id="user/../x",
        notebook_id="nb/../y",
        source_id="src/../z",
        filename="../../evil name.pdf",
    )
    # Path.name strips directory segments before sanitizing.
    assert key == "users/x/notebooks/y/sources/z/evil_name.pdf"
    assert ".." not in key
    assert sanitize_filename("evil name.pdf") == "evil_name.pdf"
