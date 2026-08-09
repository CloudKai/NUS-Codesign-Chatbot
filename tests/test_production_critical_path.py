"""Authenticated, no-network critical-path regression coverage.

This module intentionally exercises the same public FastAPI boundary that an
EC2 deployment uses.  Cognito and object storage are replaced by deterministic
in-memory adapters; no production authentication bypass, AWS call, or model
provider call is involved.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from fastapi.testclient import TestClient

from backend.api import create_app
from backend.auth_oidc import CognitoIdentity, CognitoOIDCClient, CognitoOIDCError
from backend.cognito_config import CognitoAuthConfig
from backend.persistence.factory import get_file_storage, reset_file_storage_cache
from backend.settings import settings
from backend.student_store import StudentStore


_FIXED_NOW = datetime(2026, 1, 15, 12, tzinfo=timezone.utc)


class _DeterministicOIDC(CognitoOIDCClient):
    """In-memory Cognito verifier used only by this API integration test."""

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self._identities: dict[str, CognitoIdentity] = {}
        self.revoked_refresh_tokens: list[str] = []

    def seed(self, *, sub: str, email: str) -> tuple[str, str]:
        """Register a deterministic ID/refresh token pair for one student."""
        id_token = f"id-token-{sub}"
        refresh_token = f"refresh-token-{sub}"
        self._identities[id_token] = CognitoIdentity(
            sub=sub,
            email=email,
            claims={"sub": sub, "email": email, "given_name": "E2E Student"},
        )
        return id_token, refresh_token

    def verify_id_token(self, id_token: str) -> CognitoIdentity:
        """Return a seeded identity or reject an untrusted test token."""
        try:
            return self._identities[str(id_token)]
        except KeyError as error:
            raise CognitoOIDCError("Unknown test ID token") from error

    def revoke(self, refresh_token: str) -> bool:
        """Record revocation without contacting Cognito."""
        self.revoked_refresh_tokens.append(str(refresh_token))
        return True


def _oidc_config() -> CognitoAuthConfig:
    """Return an explicit non-network test-only Cognito configuration."""
    return CognitoAuthConfig(
        client_id="critical-path-client",
        client_secret="critical-path-secret",
        server_metadata_url="https://example.test/.well-known/openid-configuration",
        redirect_uri="http://127.0.0.1:8000/api/v1/auth/callback",
    )


def _authenticated_cookies(oidc: _DeterministicOIDC) -> dict[str, str]:
    """Seed the verified Cognito cookies used on every authenticated request."""
    id_token, refresh_token = oidc.seed(
        sub="critical-path-student", email="student@example.edu"
    )
    return {
        settings.cognito_id_token_cookie_name: id_token,
        settings.cognito_refresh_cookie_name: refresh_token,
    }


def _turn(thread_id: str, message: str, source_id: str) -> dict[str, Any]:
    """Build one public coach-turn request with server-authoritative sources."""
    return {
        "thread_id": thread_id,
        "student_message": message,
        "current_stage": "focus",
        "response_detail": "short",
        "source_ids": [source_id],
    }


def test_authenticated_production_critical_path_survives_restart_and_cleanup(
    tmp_path, monkeypatch
):
    """Exercise Cognito-bound workspace, RAG, confirmation, restart, and logout.

    The flow deliberately runs through HTTP rather than calling services
    directly.  Memory object storage gives upload/content/delete coverage with
    the same generated object-key path used by S3, while the deterministic OIDC
    verifier ensures every stateful request is tied to a verified ``sub``.
    """
    monkeypatch.setattr(settings, "auth_cookie_secure", False)
    monkeypatch.setattr(settings, "file_storage_provider", "memory")
    reset_file_storage_cache()
    database = tmp_path / "critical-path.sqlite3"
    bootstrap = StudentStore(database, identifier="local-student")
    oidc = _DeterministicOIDC(
        _oidc_config(),
        store=bootstrap,
        metadata_loader=lambda _url: {},
        clock=lambda: _FIXED_NOW,
    )
    cookies = _authenticated_cookies(oidc)
    client = TestClient(create_app(bootstrap, auto_advance_stages=False, oidc_client=oidc))

    # Authentication stays a hard boundary: neither a missing nor forged token
    # becomes an authenticated profile.
    assert client.get("/api/v1/auth/me").status_code == 401
    assert client.get(
        "/api/v1/auth/me",
        cookies={settings.cognito_id_token_cookie_name: "forged"},
    ).status_code == 401
    profile = client.get("/api/v1/auth/me", cookies=cookies)
    assert profile.status_code == 200
    assert profile.json()["user"]["cognito_sub"] == "critical-path-student"
    assert cookies[settings.cognito_id_token_cookie_name] not in profile.text

    ready = client.get("/api/v1/ready", headers={"X-Request-ID": "critical-e2e"})
    assert ready.status_code == 200
    assert ready.json()["status"] == "ready"
    assert ready.headers["X-Request-ID"] == "critical-e2e"

    created = client.post(
        "/api/v1/threads",
        json={
            "name": "Crossing safety evidence",
            "model_id": "mock",
            "support_mode": "critical-thinking",
        },
        cookies=cookies,
    )
    assert created.status_code == 200
    thread_id = created.json()["id"]

    evidence = b"Older pedestrians need longer crossing intervals at low-light junctions."
    uploaded = client.post(
        f"/api/v1/threads/{thread_id}/sources",
        files=[("files", ("crossing-notes.txt", evidence, "text/plain"))],
        cookies=cookies,
    )
    assert uploaded.status_code == 200
    source = uploaded.json()[0]
    source_id = source["id"]
    assert source["selected"] is True
    assert source["has_file"] is True
    assert "path" not in source and "object_key" not in source

    # Source selection is authoritative and the preview reads through the
    # object-storage adapter, not a local path leaked to the client.
    deselected = client.patch(
        f"/api/v1/threads/{thread_id}/sources/{source_id}",
        json={"selected": False},
        cookies=cookies,
    )
    assert deselected.status_code == 200
    assert client.get(
        f"/api/v1/threads/{thread_id}/sources", params={"selected_only": True}, cookies=cookies
    ).json() == []
    selected = client.post(
        f"/api/v1/threads/{thread_id}/sources/select-all",
        json={"selected": True},
        cookies=cookies,
    )
    assert selected.status_code == 200
    assert [item["id"] for item in selected.json() if item["selected"]] == [source_id]
    preview = client.get(
        f"/api/v1/threads/{thread_id}/sources/{source_id}/content", cookies=cookies
    )
    assert preview.status_code == 200
    assert preview.content == evidence

    first_request = {
        **_turn(
            thread_id,
            "I want to evaluate whether a crossing design is safe for older pedestrians.",
            source_id,
        ),
        "idempotency_key": "critical-first-turn",
    }
    first = client.post(
        "/api/v1/coach/turn",
        json=first_request,
        headers={"Idempotency-Key": "critical-first-turn"},
        cookies=cookies,
    )
    assert first.status_code == 200, first.text
    # Retrying a completed HTTP request must replay the persisted result, not
    # duplicate messages, a model call, or a transition recommendation.
    replay = client.post(
        "/api/v1/coach/turn",
        json=first_request,
        headers={"Idempotency-Key": "critical-first-turn"},
        cookies=cookies,
    )
    assert replay.status_code == 200, replay.text
    assert replay.json() == first.json()
    assert len(
        client.get(f"/api/v1/threads/{thread_id}/messages", cookies=cookies).json()
    ) == 2
    conflict = client.post(
        "/api/v1/coach/turn",
        json={
            **first_request,
            "student_message": "This changed turn must not reuse the completed request.",
        },
        headers={"Idempotency-Key": "critical-first-turn"},
        cookies=cookies,
    )
    assert conflict.status_code == 409
    second = client.post(
        "/api/v1/coach/turn",
        json=_turn(
            thread_id,
            "I will compare signal timing and lighting at junctions so older pedestrians can cross safely.",
            source_id,
        ),
        cookies=cookies,
    )
    assert second.status_code == 200, second.text
    turn = second.json()
    assert "[S1]" in turn["response_text"]
    assert turn["assessment"]["citations"] == [
        {
            "source_id": source_id,
            "label": "S1",
            "title": "crossing-notes.txt",
            "excerpt": evidence.decode(),
        }
    ]
    pending = turn["pending_transition"]
    assert pending is not None
    assert pending["from_stage"] == "focus"
    assert pending["to_stage"] == "evidence"
    messages_before_restart = client.get(
        f"/api/v1/threads/{thread_id}/messages", cookies=cookies
    ).json()
    assert len(messages_before_restart) == 4

    # A fresh app / store instance represents the process restart that happens
    # during an EC2 replacement or application restart.
    restarted_store = StudentStore(database, identifier="local-student")
    restarted = TestClient(
        create_app(restarted_store, auto_advance_stages=False, oidc_client=oidc)
    )
    restored_pending = restarted.get(
        f"/api/v1/threads/{thread_id}/phase-transitions/pending", cookies=cookies
    )
    assert restored_pending.status_code == 200
    assert restored_pending.json()["id"] == pending["id"]
    assert restarted.get(
        f"/api/v1/threads/{thread_id}/messages", cookies=cookies
    ).json() == messages_before_restart

    confirmed = restarted.post(
        f"/api/v1/threads/{thread_id}/phase-transitions/{pending['id']}/resolve",
        json={"accepted": True},
        cookies=cookies,
    )
    assert confirmed.status_code == 200
    state = restarted.get(
        f"/api/v1/threads/{thread_id}/learning-state", cookies=cookies
    )
    assert state.json()["learning_journey"]["current_stage"] == "evidence"

    storage = get_file_storage()
    assert len(storage._objects) == 2  # raw upload plus extracted text
    deleted = restarted.delete(f"/api/v1/threads/{thread_id}", cookies=cookies)
    assert deleted.status_code == 200
    assert storage._objects == {}
    assert restarted.get(f"/api/v1/threads/{thread_id}", cookies=cookies).status_code == 404

    logout = restarted.post("/api/v1/auth/logout", cookies=cookies, follow_redirects=False)
    assert logout.status_code == 302
    assert logout.headers["location"].endswith("/?signed_out=1")
    assert oidc.revoked_refresh_tokens == [cookies[settings.cognito_refresh_cookie_name]]
    assert restarted.get("/api/v1/auth/me").status_code == 401
