"""Application-session service over StudentStore persistence.

Designed so the SQLite adapter can later be replaced with PostgreSQL without
changing Streamlit cookie/auth-gate call sites.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Callable

from backend.session_tokens import generate_session_token, hash_session_token
from backend.settings import settings
from backend.student_store import StudentStore


@dataclass(frozen=True)
class CreatedAppSession:
    """Result of creating a new opaque application session."""

    session_id: str
    raw_token: str
    expires_at: str


class AppSessionService:
    """Create, resolve, and revoke opaque application sessions."""

    def __init__(
        self,
        store: StudentStore | None = None,
        *,
        ttl_seconds: int | None = None,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._store = store or StudentStore()
        self._ttl_seconds = int(
            settings.app_session_ttl_seconds if ttl_seconds is None else ttl_seconds
        )
        self._clock = clock or (lambda: datetime.now(timezone.utc))

    @property
    def ttl_seconds(self) -> int:
        """Configured application-session lifetime in seconds."""
        return self._ttl_seconds

    def create_session(self, user_id: str) -> CreatedAppSession:
        """Issue a fresh session for *user_id* and return the raw cookie token."""
        now = self._clock()
        expires = now + timedelta(seconds=self._ttl_seconds)
        raw_token = generate_session_token()
        token_hash = hash_session_token(raw_token)
        session_id = self._store.create_app_session(
            user_id=user_id,
            token_hash=token_hash,
            created_at=now.isoformat(),
            expires_at=expires.isoformat(),
        )
        return CreatedAppSession(
            session_id=session_id,
            raw_token=raw_token,
            expires_at=expires.isoformat(),
        )

    def get_session_user(self, raw_token: str | None) -> dict[str, Any] | None:
        """Return the bound user for a valid raw token, else ``None``."""
        token = str(raw_token or "").strip()
        if not token:
            return None
        try:
            token_hash = hash_session_token(token)
        except ValueError:
            return None
        now = self._clock()
        user = self._store.get_user_for_session_hash(
            token_hash, now_iso=now.isoformat()
        )
        return user

    def revoke_session(self, raw_token: str | None) -> bool:
        """Revoke the session for *raw_token* when present. Return whether revoked."""
        token = str(raw_token or "").strip()
        if not token:
            return False
        try:
            token_hash = hash_session_token(token)
        except ValueError:
            return False
        return self._store.revoke_app_session(
            token_hash, revoked_at=self._clock().isoformat()
        )

    def cleanup_expired_sessions(self) -> int:
        """Delete expired or long-revoked session rows. Return deleted count."""
        return self._store.cleanup_expired_app_sessions(
            now_iso=self._clock().isoformat()
        )


def cookie_settings() -> dict[str, Any]:
    """Return FastAPI ``set_cookie`` / ``delete_cookie`` keyword defaults."""
    return {
        "key": settings.app_session_cookie_name,
        "httponly": True,
        "samesite": "lax",
        "path": "/",
        "secure": bool(settings.app_session_cookie_secure),
        "max_age": int(settings.app_session_ttl_seconds),
    }


def oauth_state_cookie_settings(*, max_age: int) -> dict[str, Any]:
    """Return cookie kwargs for the short-lived OAuth state binder.

    Path is scoped to ``/api/v1/auth`` so the binder is sent only on login and
    callback. Host-only (no Domain). Secure follows ``APP_SESSION_COOKIE_SECURE``.
    """
    return {
        "key": settings.oauth_state_cookie_name,
        "httponly": True,
        "samesite": "lax",
        "path": "/api/v1/auth",
        "secure": bool(settings.app_session_cookie_secure),
        "max_age": int(max_age),
    }
