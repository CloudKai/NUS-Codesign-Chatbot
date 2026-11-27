"""Disposable registered-identity boundary for the Playwright CI slice (ticket 05).

Mirrors the deterministic verifier in
``tests/http/test_production_critical_path.py``: an in-memory Cognito OIDC client
is injected into ``create_app`` so the browser slice can exercise a synthetic
*registered* student without live Cognito, AWS or a paid provider. Seeding a
token pair is a test-only action; forged or unknown tokens are still rejected so
authentication stays a hard boundary.

Run with uvicorn on a disposable port; all workspace paths must be explicit and
temporary (validated before the application imports).
"""
from __future__ import annotations

import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from backend.auth_oidc import CognitoIdentity, CognitoOIDCClient, CognitoOIDCError
from backend.cognito_config import CognitoAuthConfig
from backend.student_store import StudentStore

_FIXED_NOW = datetime(2026, 1, 15, 12, tzinfo=timezone.utc)

# Kept in sync with frontend/tests/browser/registered_journey.spec.ts.
REGISTERED_SUB = "browser-ci-student"
REGISTERED_EMAIL = "browser-ci-student@example.edu"
REGISTERED_ID_TOKEN = f"id-token-{REGISTERED_SUB}"
REGISTERED_REFRESH_TOKEN = f"refresh-token-{REGISTERED_SUB}"


def _require_disposable_mock() -> None:
    """Refuse to run unless mock provider and disposable temp paths are selected."""
    root = Path(os.environ.get("APP_DATA_DIR", "/invalid")).resolve()
    temporary = (Path("/tmp").resolve(), Path(tempfile.gettempdir()).resolve())
    if os.environ.get("MODEL_PROVIDER") != "mock" or not any(root.is_relative_to(p) for p in temporary):
        raise RuntimeError("Registered fixture requires an explicit temporary mock workspace")
    for key in ("APP_DATABASE_PATH", "APP_FILES_DIR", "APP_WORKSPACES_DIR", "LECTURE_NOTES_DIR"):
        if not os.environ.get(key) or not Path(os.environ[key]).resolve().is_relative_to(root):
            raise RuntimeError("All fixture workspace paths must be explicit and temporary")


class DeterministicOIDC(CognitoOIDCClient):
    """In-memory Cognito verifier used only by this browser fixture."""

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self._identities: dict[str, CognitoIdentity] = {}

    def seed(self, *, sub: str, email: str) -> tuple[str, str]:
        """Register one deterministic ID/refresh token pair for the synthetic student."""
        id_token = f"id-token-{sub}"
        refresh_token = f"refresh-token-{sub}"
        self._identities[id_token] = CognitoIdentity(
            sub=sub,
            email=email,
            claims={"sub": sub, "email": email, "given_name": "Browser CI Student"},
        )
        return id_token, refresh_token

    def verify_id_token(self, id_token: str) -> CognitoIdentity:
        """Return the seeded identity or reject an untrusted token."""
        try:
            return self._identities[str(id_token)]
        except KeyError as error:
            raise CognitoOIDCError("Unknown test ID token") from error

    def revoke(self, refresh_token: str) -> bool:
        """Record revocation without contacting Cognito."""
        return True


def _config() -> CognitoAuthConfig:
    """Return an explicit non-network test-only Cognito configuration."""
    return CognitoAuthConfig(
        client_id="browser-ci-client",
        client_secret="browser-ci-secret",
        server_metadata_url="https://example.test/.well-known/openid-configuration",
        redirect_uri="http://127.0.0.1:8000/api/v1/auth/callback",
    )


def _create_registered_app() -> tuple[Any, DeterministicOIDC]:
    """Validate disposable paths, then build the app with the injected verifier."""
    _require_disposable_mock()

    from backend.http.app import create_app
    from backend.settings import settings

    store = StudentStore(Path(settings.database_path), identifier="local-student")
    oidc = DeterministicOIDC(
        _config(),
        store=store,
        metadata_loader=lambda _url: {},
        clock=lambda: _FIXED_NOW,
    )
    oidc.seed(sub=REGISTERED_SUB, email=REGISTERED_EMAIL)
    return create_app(store, auto_advance_stages=False, oidc_client=oidc), oidc


app, registered_oidc = _create_registered_app()
