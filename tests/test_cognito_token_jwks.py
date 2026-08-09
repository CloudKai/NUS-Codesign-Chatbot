"""Deterministic Cognito ID-token claim and JWKS cache tests (no network)."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

import pytest
from joserfc import jwt
from joserfc.jwk import OctKey

from backend.auth_oidc import CognitoOIDCClient, CognitoOIDCError
from backend.cognito_config import CognitoAuthConfig
from backend.student_store import StudentStore


# Far-future clock so joserfc wall-clock ``exp`` checks remain valid in CI.
FIXED_NOW = datetime(2030, 1, 15, 12, 0, tzinfo=timezone.utc)
_KEY_V1 = OctKey.generate_key(256, parameters={"alg": "HS256", "kid": "kid-v1"})
_KEY_V2 = OctKey.generate_key(256, parameters={"alg": "HS256", "kid": "kid-v2"})


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


def _mint(
    *,
    sub: str,
    key: OctKey,
    token_use: str = "id",
    kid: str | None = None,
    email: str = "student@example.edu",
) -> str:
    issued = datetime.now(timezone.utc)
    header = {"alg": "HS256", "kid": kid or key.kid}
    claims = {
        "sub": sub,
        "email": email,
        "iss": _metadata()["issuer"],
        "aud": "test-client",
        "token_use": token_use,
        "exp": int((issued + timedelta(hours=1)).timestamp()),
        "iat": int(issued.timestamp()),
    }
    return jwt.encode(header, claims, key)


def test_token_use_id_succeeds_and_access_is_rejected(tmp_path):
    store = StudentStore(tmp_path / "token-use.sqlite3")
    fetches: list[str] = []

    def jwks_loader(_uri: str) -> dict[str, Any]:
        fetches.append(_uri)
        return {"keys": [_KEY_V1.as_dict()]}

    oidc = CognitoOIDCClient(
        _config(),
        store=store,
        metadata_loader=lambda _url: _metadata(),
        jwks_loader=jwks_loader,
        clock=lambda: FIXED_NOW,
    )
    good = _mint(sub="sub-id", key=_KEY_V1, token_use="id")
    identity = oidc.verify_id_token(good)
    assert identity.sub == "sub-id"

    access = _mint(sub="sub-access", key=_KEY_V1, token_use="access")
    with pytest.raises(CognitoOIDCError):
        oidc.verify_id_token(access)


def test_jwks_is_cached_and_unknown_kid_refreshes_once(tmp_path):
    store = StudentStore(tmp_path / "jwks-cache.sqlite3")
    payloads = [
        {"keys": [_KEY_V1.as_dict()]},
        {"keys": [_KEY_V1.as_dict(), _KEY_V2.as_dict()]},
    ]
    fetches: list[int] = []

    def jwks_loader(_uri: str) -> dict[str, Any]:
        index = len(fetches)
        fetches.append(index)
        return payloads[min(index, len(payloads) - 1)]

    oidc = CognitoOIDCClient(
        _config(),
        store=store,
        metadata_loader=lambda _url: _metadata(),
        jwks_loader=jwks_loader,
        clock=lambda: FIXED_NOW,
    )
    first = _mint(sub="sub-a", key=_KEY_V1, kid="kid-v1")
    oidc.verify_id_token(first)
    oidc.verify_id_token(first)
    assert len(fetches) == 1

    rotated = _mint(sub="sub-b", key=_KEY_V2, kid="kid-v2")
    identity = oidc.verify_id_token(rotated)
    assert identity.sub == "sub-b"
    assert len(fetches) == 2

    with pytest.raises(CognitoOIDCError):
        oidc.verify_id_token("not-a-jwt")
    # Invalid tokens must not keep refetching JWKS forever.
    assert len(fetches) == 2
