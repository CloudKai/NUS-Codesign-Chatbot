"""Cognito OIDC client configuration for FastAPI-owned login.

Credentials may come from environment variables or the private
``.streamlit/secrets.toml`` ``[auth]`` table. Secrets are never committed.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any, Mapping

from backend.settings import PROJECT_ROOT, settings


@dataclass(frozen=True)
class CognitoAuthConfig:
    """Resolved Cognito app-client settings for authorization-code login."""

    client_id: str
    client_secret: str
    server_metadata_url: str
    redirect_uri: str
    scopes: str = "openid email profile"
    prompt: str = "login"

    @property
    def is_configured(self) -> bool:
        """Return whether required Cognito fields are present."""
        return bool(
            self.client_id
            and self.client_secret
            and self.server_metadata_url
            and self.redirect_uri
            and "<" not in self.client_id
            and "<" not in self.client_secret
            and "<" not in self.server_metadata_url
        )


def _secrets_auth_table() -> Mapping[str, Any]:
    """Load the private ``[auth]`` table when present; never raise on absence."""
    path = PROJECT_ROOT / ".streamlit" / "secrets.toml"
    if not path.is_file():
        return {}
    try:
        import tomllib

        with path.open("rb") as handle:
            payload = tomllib.load(handle)
    except Exception:
        return {}
    auth = payload.get("auth") or {}
    return auth if isinstance(auth, dict) else {}


def load_cognito_auth_config() -> CognitoAuthConfig:
    """Resolve Cognito settings from environment, falling back to secrets.toml."""
    auth = _secrets_auth_table()
    client_kwargs = auth.get("client_kwargs") or {}
    if not isinstance(client_kwargs, dict):
        client_kwargs = {}
    scopes = str(
        os.getenv("COGNITO_SCOPES")
        or client_kwargs.get("scope")
        or "openid email profile"
    ).strip()
    prompt = str(
        os.getenv("COGNITO_PROMPT") or client_kwargs.get("prompt") or "login"
    ).strip() or "login"
    redirect_uri = str(
        os.getenv("COGNITO_REDIRECT_URI")
        or getattr(settings, "cognito_redirect_uri", "")
        or auth.get("redirect_uri")
        or ""
    ).strip()
    # Prefer the FastAPI callback when secrets still list Streamlit's old URI.
    if redirect_uri.endswith("/oauth2callback"):
        redirect_uri = str(
            os.getenv("COGNITO_REDIRECT_URI")
            or getattr(settings, "cognito_redirect_uri", "")
            or ""
        ).strip()
    if not redirect_uri:
        redirect_uri = (
            f"{str(settings.public_api_base_url).rstrip('/')}/api/v1/auth/callback"
        )
    return CognitoAuthConfig(
        client_id=str(
            os.getenv("COGNITO_CLIENT_ID") or auth.get("client_id") or ""
        ).strip(),
        client_secret=str(
            os.getenv("COGNITO_CLIENT_SECRET") or auth.get("client_secret") or ""
        ).strip(),
        server_metadata_url=str(
            os.getenv("COGNITO_SERVER_METADATA_URL")
            or auth.get("server_metadata_url")
            or ""
        ).strip(),
        redirect_uri=redirect_uri,
        scopes=scopes,
        prompt=prompt,
    )
