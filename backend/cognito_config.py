"""Cognito OIDC client configuration for FastAPI-owned login.

Credentials may come from environment variables or the private
``.streamlit/secrets.toml`` ``[auth]`` table. Secrets are never committed.

Redirect URI precedence (highest first):

1. Explicit ``COGNITO_REDIRECT_URI`` environment variable
2. Private ``secrets.toml`` ``[auth].redirect_uri``
3. Derived ``CO_DESIGN_PUBLIC_API_URL`` + ``/api/v1/auth/callback``
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


def _resolve_redirect_uri(auth: Mapping[str, Any]) -> str:
    """Resolve Cognito callback URL without a hard-coded local override."""
    explicit = os.getenv("COGNITO_REDIRECT_URI", "").strip()
    if explicit:
        return explicit
    secrets_redirect = str(auth.get("redirect_uri") or "").strip()
    # Ignore legacy Streamlit OIDC callback so production secrets cannot stick
    # on /oauth2callback after the FastAPI-owned login migration.
    if secrets_redirect.endswith("/oauth2callback"):
        secrets_redirect = ""
    if secrets_redirect:
        return secrets_redirect
    return f"{str(settings.public_api_base_url).rstrip('/')}/api/v1/auth/callback"


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
        redirect_uri=_resolve_redirect_uri(auth),
        scopes=scopes,
        prompt=prompt,
    )
