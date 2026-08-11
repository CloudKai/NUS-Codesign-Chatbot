"""HttpOnly Cognito refresh / ID-token cookie helpers for FastAPI auth routes.

Cognito owns the session. Refresh and ID tokens live only in HttpOnly cookies
(never DB, JSON responses, logs, or browser JS). The refresh token is scoped
to ``/api/v1/auth``; the short-lived ID token is available to the server-rendered
root for FastAPI verification. A non-sensitive Path=/ session-hint cookie tells
Streamlit to attempt the browser refresh bridge after the ID cookie expires.
"""

from __future__ import annotations

from typing import Any

from backend.settings import settings

AUTH_COOKIE_PATH = "/api/v1/auth"
ID_TOKEN_COOKIE_PATH = "/"
SESSION_HINT_COOKIE_VALUE = "1"


def auth_cookies_secure() -> bool:
    """Return whether auth cookies should set the Secure attribute."""
    return bool(settings.auth_cookie_secure)


def refresh_cookie_settings() -> dict[str, Any]:
    """Return FastAPI ``set_cookie`` kwargs for the Cognito refresh token."""
    return {
        "key": settings.cognito_refresh_cookie_name,
        "httponly": True,
        "samesite": "lax",
        "path": AUTH_COOKIE_PATH,
        "secure": auth_cookies_secure(),
        "max_age": int(settings.cognito_refresh_cookie_max_age),
    }


def id_token_cookie_settings() -> dict[str, Any]:
    """Return cookie kwargs for the short-lived Cognito ID token.

    The ID token is sent to the server-rendered Streamlit root so Streamlit can
    ask FastAPI to verify it. It remains HttpOnly and is never available to
    browser JavaScript. The refresh token stays scoped to ``AUTH_COOKIE_PATH``
    and is never sent to Streamlit.
    """
    return {
        "key": settings.cognito_id_token_cookie_name,
        "httponly": True,
        "samesite": "lax",
        "path": ID_TOKEN_COOKIE_PATH,
        "secure": auth_cookies_secure(),
        "max_age": int(settings.cognito_id_token_cookie_max_age),
    }


def session_hint_cookie_settings() -> dict[str, Any]:
    """Return cookie kwargs for the Path=/ Cognito session presence marker.

    Value is always ``SESSION_HINT_COOKIE_VALUE`` (``\"1\"``). It carries no
    token material. Max-Age matches the refresh cookie so Streamlit can still
    attempt ``/api/v1/auth/refresh`` after the 1-hour ID cookie expires.
    """
    return {
        "key": settings.cognito_session_hint_cookie_name,
        "httponly": True,
        "samesite": "lax",
        "path": ID_TOKEN_COOKIE_PATH,
        "secure": auth_cookies_secure(),
        "max_age": int(settings.cognito_refresh_cookie_max_age),
    }


def oauth_state_cookie_settings(*, max_age: int) -> dict[str, Any]:
    """Return cookie kwargs for the short-lived OAuth state binder.

    Path is scoped to ``/api/v1/auth`` so the binder is sent only on login and
    callback. Host-only (no Domain). Secure follows ``AUTH_COOKIE_SECURE``.
    """
    return {
        "key": settings.oauth_state_cookie_name,
        "httponly": True,
        "samesite": "lax",
        "path": AUTH_COOKIE_PATH,
        "secure": auth_cookies_secure(),
        "max_age": int(max_age),
    }
