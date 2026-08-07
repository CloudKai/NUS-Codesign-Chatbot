"""Opaque application-session token helpers.

Cognito proves identity at login. Ongoing authentication uses a random
application session token that exists only in an HttpOnly cookie. The database
stores a SHA-256 digest of that token, never the raw value.
"""

from __future__ import annotations

import hashlib
import secrets


def generate_session_token() -> str:
    """Return a URL-safe session token with at least 256 bits of entropy."""
    return secrets.token_urlsafe(32)


def hash_session_token(raw_token: str) -> str:
    """Return the SHA-256 hex digest used for exact session lookup."""
    token = str(raw_token or "").strip()
    if not token:
        raise ValueError("session token is required")
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def generate_oauth_state() -> str:
    """Return a high-entropy OAuth state value."""
    return secrets.token_urlsafe(32)


def generate_pkce_verifier() -> str:
    """Return a PKCE code_verifier (43–128 chars per RFC 7636)."""
    return secrets.token_urlsafe(64)
