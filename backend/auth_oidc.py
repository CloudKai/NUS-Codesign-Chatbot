"""Server-side Cognito authorization-code + PKCE helpers for FastAPI login.

Uses Authlib for the OAuth2 token exchange and joserfc to verify the ID token
against Cognito JWKS. Refresh and ID tokens are returned only for HttpOnly
cookie attachment — never logged or persisted to the database.
"""

from __future__ import annotations

import hashlib
import json
import logging
import threading
from base64 import urlsafe_b64decode, urlsafe_b64encode
from dataclasses import dataclass, field
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
from backend.settings import settings
from backend.student_store import StudentStore

logger = logging.getLogger(__name__)

# Short-lived OAuth login CSRF binder (DB row + browser cookie Max-Age).
OAUTH_STATE_TTL_SECONDS = 600
# Successful JWKS responses are reused in-process; never cache tokens.
DEFAULT_JWKS_CACHE_TTL_SECONDS = 6 * 60 * 60


@dataclass(frozen=True)
class CognitoIdentity:
    """Verified Cognito identity claims used to upsert an application user."""

    sub: str
    email: str | None
    claims: dict[str, Any]


@dataclass(frozen=True)
class CognitoAuthSession:
    """Verified identity plus tokens destined only for HttpOnly cookies.

    Never log, serialize to JSON API bodies, or store these token fields in DB.
    """

    identity: CognitoIdentity
    refresh_token: str = field(repr=False)
    id_token: str = field(repr=False)


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
        # Prevent concurrent refresh grants from racing within one API process.
        # Cognito remains authoritative; no token is cached or persisted here.
        self._refresh_lock = threading.Lock()
        self._jwks_lock = threading.Lock()
        # jwks_uri -> (expires_at_epoch, KeySet)
        self._jwks_cache: dict[str, tuple[float, KeySet]] = {}
        self._jwks_cache_ttl_seconds = float(
            getattr(
                settings,
                "cognito_jwks_cache_ttl_seconds",
                DEFAULT_JWKS_CACHE_TTL_SECONDS,
            )
        )
        self._jwks_fetch_count = 0

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

    def complete_login(self, *, code: str, state: str) -> CognitoAuthSession:
        """Exchange *code* after validating *state*; return identity + tokens."""
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

        return self._session_from_token_response(
            token,
            jwks_uri=jwks_uri,
            issuer=issuer,
            audience=config.client_id,
        )

    def verify_id_token(self, id_token: str) -> CognitoIdentity:
        """Verify *id_token* with discovery JWKS/issuer/audience and return identity."""
        config = self.require_configured()
        token = str(id_token or "").strip()
        if not token:
            raise CognitoOIDCError("Missing ID token")
        metadata = self.discovery()
        jwks_uri = str(metadata.get("jwks_uri") or "").strip()
        issuer = str(metadata.get("issuer") or "").strip()
        if not jwks_uri or not issuer:
            raise CognitoOIDCError("Cognito discovery metadata is incomplete")
        claims = self._verify_id_token(
            token,
            jwks_uri=jwks_uri,
            issuer=issuer,
            audience=config.client_id,
        )
        sub = str(claims.get("sub") or "").strip()
        if not sub:
            raise CognitoOIDCError("Cognito ID token missing sub")
        email = str(claims.get("email") or "").strip() or None
        return CognitoIdentity(sub=sub, email=email, claims=dict(claims))

    def refresh(self, refresh_token: str) -> CognitoAuthSession:
        """Refresh Cognito tokens and return a verified ID token session.

        Uses ``grant_type=refresh_token`` against the discovery token endpoint.
        Validates the new ID token with the same JWKS/issuer/audience rules.
        """
        config = self.require_configured()
        raw_refresh = str(refresh_token or "").strip()
        if not raw_refresh:
            raise CognitoOIDCError("Missing refresh token")
        metadata = self.discovery()
        token_endpoint = str(metadata.get("token_endpoint") or "").strip()
        jwks_uri = str(metadata.get("jwks_uri") or "").strip()
        issuer = str(metadata.get("issuer") or "").strip()
        if not token_endpoint or not jwks_uri or not issuer:
            raise CognitoOIDCError("Cognito discovery metadata is incomplete")

        try:
            with self._refresh_lock:
                with self._http() as client:
                    response = client.post(
                        token_endpoint,
                        data={
                            "grant_type": "refresh_token",
                            "client_id": config.client_id,
                            "client_secret": config.client_secret,
                            "refresh_token": raw_refresh,
                        },
                        headers={"Content-Type": "application/x-www-form-urlencoded"},
                    )
                    response.raise_for_status()
                    token = response.json()
        except Exception as error:  # pragma: no cover - network/provider failures
            logger.warning("Cognito refresh token grant failed")
            raise CognitoOIDCError("Cognito refresh failed") from error

        if not str(token.get("refresh_token") or "").strip():
            token = dict(token)
            token["refresh_token"] = raw_refresh
        return self._session_from_token_response(
            token,
            jwks_uri=jwks_uri,
            issuer=issuer,
            audience=config.client_id,
        )

    def revoke(self, refresh_token: str) -> bool:
        """Best-effort revoke *refresh_token* via discovery ``revocation_endpoint``.

        Returns ``True`` when a revocation request was accepted, ``False`` when
        the endpoint is missing or the call fails. Never raises for revoke
        failures; never logs the token value.
        """
        raw_refresh = str(refresh_token or "").strip()
        if not raw_refresh:
            return False
        try:
            config = self.require_configured()
            metadata = self.discovery()
        except CognitoOIDCError:
            return False
        revoke_endpoint = str(metadata.get("revocation_endpoint") or "").strip()
        if not revoke_endpoint:
            return False
        try:
            with self._http() as client:
                response = client.post(
                    revoke_endpoint,
                    data={
                        "token": raw_refresh,
                        "client_id": config.client_id,
                    },
                    headers={"Content-Type": "application/x-www-form-urlencoded"},
                    auth=(config.client_id, config.client_secret),
                )
                if response.status_code >= 400:
                    logger.warning("Cognito token revocation returned an error status")
                    return False
                return True
        except Exception:
            logger.warning("Cognito token revocation failed")
            return False

    def _session_from_token_response(
        self,
        token: Mapping[str, Any],
        *,
        jwks_uri: str,
        issuer: str,
        audience: str,
    ) -> CognitoAuthSession:
        """Build a verified session from a Cognito token-endpoint JSON body."""
        id_token = str(token.get("id_token") or "").strip()
        refresh_token = str(token.get("refresh_token") or "").strip()
        if not id_token:
            raise CognitoOIDCError("Cognito response did not include an ID token")
        if not refresh_token:
            raise CognitoOIDCError("Cognito response did not include a refresh token")
        claims = self._verify_id_token(
            id_token,
            jwks_uri=jwks_uri,
            issuer=issuer,
            audience=audience,
        )
        sub = str(claims.get("sub") or "").strip()
        if not sub:
            raise CognitoOIDCError("Cognito ID token missing sub")
        email = str(claims.get("email") or "").strip() or None
        identity = CognitoIdentity(sub=sub, email=email, claims=dict(claims))
        return CognitoAuthSession(
            identity=identity,
            refresh_token=refresh_token,
            id_token=id_token,
        )

    def _token_header_kid(self, id_token: str) -> str | None:
        """Return the unverified JWT header ``kid`` when present."""
        try:
            header_segment = str(id_token).split(".", 1)[0]
            padded = header_segment + "=" * (-len(header_segment) % 4)
            header = json.loads(urlsafe_b64decode(padded.encode("ascii")))
        except Exception:
            return None
        if not isinstance(header, dict):
            return None
        kid = str(header.get("kid") or "").strip()
        return kid or None

    def _fetch_jwks_payload(self, jwks_uri: str) -> Mapping[str, Any]:
        """Load JWKS JSON via the injectable loader or HTTP (never caches tokens)."""
        self._jwks_fetch_count += 1
        if self._jwks_loader is not None:
            return dict(self._jwks_loader(jwks_uri))
        with self._http() as client:
            response = client.get(jwks_uri)
            response.raise_for_status()
            payload = response.json()
        if not isinstance(payload, Mapping):
            raise CognitoOIDCError("Cognito JWKS payload is invalid")
        return payload

    def _get_key_set(self, jwks_uri: str, *, force_refresh: bool = False) -> KeySet:
        """Return a cached Cognito JWKS KeySet, refreshing when stale or forced."""
        now = self._clock().timestamp()
        with self._jwks_lock:
            cached = self._jwks_cache.get(jwks_uri)
            if (
                not force_refresh
                and cached is not None
                and cached[0] > now
            ):
                return cached[1]
            payload = self._fetch_jwks_payload(jwks_uri)
            key_set = KeySet.import_key_set(dict(payload))
            self._jwks_cache[jwks_uri] = (
                now + max(60.0, self._jwks_cache_ttl_seconds),
                key_set,
            )
            return key_set

    def _verify_id_token(
        self,
        id_token: str,
        *,
        jwks_uri: str,
        issuer: str,
        audience: str,
    ) -> dict[str, Any]:
        """Verify Cognito ID token signature and required claims including token_use.

        Successful JWKS responses are cached in-process. When the token ``kid`` is
        absent from the cache, JWKS is refreshed once so signing-key rotation
        still works. Tokens themselves are never cached or logged.
        """
        kid = self._token_header_kid(id_token)
        key_set = self._get_key_set(jwks_uri)
        if kid:
            try:
                key_set.get_by_kid(kid)
            except Exception:
                key_set = self._get_key_set(jwks_uri, force_refresh=True)
        try:
            token = jwt.decode(id_token, key_set)
            claims = dict(token.claims)
            jwt.JWTClaimsRegistry(
                iss={"essential": True, "value": issuer},
                aud={"essential": True, "value": audience},
                exp={"essential": True},
                sub={"essential": True},
                token_use={"essential": True, "value": "id"},
            ).validate(claims)
        except CognitoOIDCError:
            raise
        except Exception as error:
            raise CognitoOIDCError("Cognito ID token verification failed") from error
        if str(claims.get("token_use") or "").strip() != "id":
            raise CognitoOIDCError("Cognito ID token verification failed")
        return claims
