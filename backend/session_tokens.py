"""OAuth state and PKCE verifier helpers for Cognito authorization-code login.

Ongoing authentication uses Cognito refresh/ID tokens in HttpOnly cookies.
This module only generates high-entropy OAuth binder values — never app
session tokens.
"""

from __future__ import annotations

import secrets


def generate_oauth_state() -> str:
    """Return a high-entropy OAuth state value."""
    return secrets.token_urlsafe(32)


def generate_pkce_verifier() -> str:
    """Return a PKCE code_verifier (43–128 chars per RFC 7636)."""
    return secrets.token_urlsafe(64)
