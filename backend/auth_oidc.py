"""Server-side Cognito authorization-code + PKCE helpers for FastAPI login.

Uses Authlib for the OAuth2 token exchange and joserfc to verify the ID token
against Cognito JWKS. Cognito tokens are used only to establish identity and
are discarded afterward — never persisted.
"""

from __future__ import annotations

import hashlib
import logging
from base64 import urlsafe_b64encode
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Callable, Mapping
from urllib.parse import urlencode

import httpx
from authlib.integrations.httpx_client import OAuth2Client
from joserfc import jwt
from joserfc.jwk import KeySet

from backend.cognito_config import CognitoAuthConfig, load_cognito_auth_config
from backend.persistence.factory import create_student_store
from backend.session_tokens import generate_oauth_state, generate_pkce_verifier
from backend.student_store import StudentStore, utc_now

logger = logging.getLogger(__name__)

# Short-lived OAuth login CSRF binder (DB row + browser cookie Max-Age).
OAUTH_STATE_TTL_SECONDS = 600


@dataclass(frozen=True)
class CognitoIdentity:
    """Verified Cognito identity claims used to upsert an application user."""

    sub: str
    email: str | None
    claims: dict[str, Any]


class CognitoOIDCError(ValueError):
    """Raised when Cognito login/callback validation fails."""


def _pkce_challenge(verifier: str) -> str:
    """Return the S256 code_challenge for *verifier*."""
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    return urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")


class CognitoOIDCClient:
    """Build authorize URLs and exchange authorization codes for identity."""

    def __init__(
        self,
        config: CognitoAuthConfig | None = None,
        *,
        store: StudentStore | None = None,
        transport: httpx.BaseTransport | None = None,
        clock: Callable[[], datetime] | None = None,
        metadata_loader: Callable[[str], Mapping[str, Any]] | None = None,
        jwks_loader: Callable[[str], Mapping[str, Any]] | None = None,
    ) -> None:
        self._config = config or load_cognito_auth_config()
        self._store = store or create_student_store()
        self._transport = transport
        self._clock = clock or (lambda: datetime.now(timezone.utc))
        self._metadata_loader = metadata_loader
        self._jwks_loader = jwks_loader
        self._metadata_cache: dict[str, Any] | None = None

    @property
    def config(self) -> CognitoAuthConfig:
        """Return the resolved Cognito configuration."""
        return self._config

    def require_configured(self) -> CognitoAuthConfig:
        """Return config or raise when Cognito credentials are incomplete."""
        if not self._config.is_configured:
            raise CognitoOIDCError("Cognito authentication is not configured")
        return self._config

    def _http(self) -> httpx.Client:
        return httpx.Client(timeout=30.0, transport=self._transport)

    def discovery(self) -> dict[str, Any]:
        """Return OpenID provider metadata (cached per process)."""
        if self._metadata_cache is not None:
            return self._metadata_cache
        config = self.require_configured()
        if self._metadata_loader is not None:
            payload = dict(self._metadata_loader(config.server_metadata_url))
        else:
            with self._http() as client:
                response = client.get(config.server_metadata_url)
                response.raise_for_status()
                payload = response.json()
        self._metadata_cache = payload
        return payload

    def begin_login(self) -> tuple[str, str]:
        """Persist OAuth state/PKCE and return ``(authorization_url, state)``."""
        config = self.require_configured()
        metadata = self.discovery()
        authorize_endpoint = str(metadata.get("authorization_endpoint") or "").strip()
        if not authorize_endpoint:
            raise CognitoOIDCError("Cognito authorization_endpoint is missing")
        state = generate_oauth_state()
        verifier = generate_pkce_verifier()
        now = self._clock()
        self._store.save_oauth_login_state(
            state=state,
            code_verifier=verifier,
            created_at=now.isoformat(),
            expires_at=(now + timedelta(seconds=OAUTH_STATE_TTL_SECONDS)).isoformat(),
        )
        query = urlencode(
            {
                "client_id": config.client_id,
                "response_type": "code",
                "scope": config.scopes,
                "redirect_uri": config.redirect_uri,
                "state": state,
                "code_challenge": _pkce_challenge(verifier),
                "code_challenge_method": "S256",
                "prompt": config.prompt,
            }
        )
        return f"{authorize_endpoint}?{query}", state

    def complete_login(self, *, code: str, state: str) -> CognitoIdentity:
        """Exchange *code* after validating *state*; return verified identity."""
        config = self.require_configured()
        auth_code = str(code or "").strip()
        auth_state = str(state or "").strip()
        if not auth_code or not auth_state:
            raise CognitoOIDCError("Missing authorization code or state")
        verifier = self._store.consume_oauth_login_state(
            auth_state, now_iso=self._clock().isoformat()
        )
        if not verifier:
            raise CognitoOIDCError("Invalid or expired OAuth state")
        metadata = self.discovery()
        token_endpoint = str(metadata.get("token_endpoint") or "").strip()
        jwks_uri = str(metadata.get("jwks_uri") or "").strip()
        issuer = str(metadata.get("issuer") or "").strip()
        if not token_endpoint or not jwks_uri or not issuer:
            raise CognitoOIDCError("Cognito discovery metadata is incomplete")

        client = OAuth2Client(
            client_id=config.client_id,
            client_secret=config.client_secret,
            redirect_uri=config.redirect_uri,
            scope=config.scopes,
            transport=self._transport,
            timeout=30.0,
        )
        try:
            token = client.fetch_token(
                token_endpoint,
                code=auth_code,
                code_verifier=verifier,
            )
        except Exception as error:  # pragma: no cover - network/provider failures
            logger.warning("Cognito token exchange failed")
            raise CognitoOIDCError("Cognito token exchange failed") from error
        finally:
            client.close()

        id_token = str(token.get("id_token") or "").strip()
        if not id_token:
            raise CognitoOIDCError("Cognito response did not include an ID token")
        claims = self._verify_id_token(
            id_token,
            jwks_uri=jwks_uri,
            issuer=issuer,
            audience=config.client_id,
        )
        # Explicitly drop token material; only verified claims continue.
        del token
        del id_token
        sub = str(claims.get("sub") or "").strip()
        if not sub:
            raise CognitoOIDCError("Cognito ID token missing sub")
        email = str(claims.get("email") or "").strip() or None
        return CognitoIdentity(sub=sub, email=email, claims=dict(claims))

    def _verify_id_token(
        self,
        id_token: str,
        *,
        jwks_uri: str,
        issuer: str,
        audience: str,
    ) -> dict[str, Any]:
        """Verify the Cognito ID token signature and standard claims."""
        if self._jwks_loader is not None:
            jwks_payload = dict(self._jwks_loader(jwks_uri))
        else:
            with self._http() as client:
                response = client.get(jwks_uri)
                response.raise_for_status()
                jwks_payload = response.json()
        try:
            key_set = KeySet.import_key_set(jwks_payload)
            token = jwt.decode(id_token, key_set)
            claims = dict(token.claims)
            jwt.JWTClaimsRegistry(
                iss={"essential": True, "value": issuer},
                aud={"essential": True, "value": audience},
                exp={"essential": True},
                sub={"essential": True},
            ).validate(claims)
        except Exception as error:
            raise CognitoOIDCError("Cognito ID token verification failed") from error
        return claims
