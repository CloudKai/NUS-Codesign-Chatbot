"""FastAPI authentication handlers: Cognito login + opaque app sessions."""

from __future__ import annotations

import hmac
import logging
from typing import Any
from urllib.parse import urlparse

from fastapi import HTTPException, Request, Response
from fastapi.responses import JSONResponse, RedirectResponse

from backend.app_sessions import (
    AppSessionService,
    cookie_settings,
    oauth_state_cookie_settings,
)
from backend.auth_oidc import CognitoOIDCClient, CognitoOIDCError, OAUTH_STATE_TTL_SECONDS
from backend.auth_profiles import sync_authenticated_user
from backend.settings import settings
from backend.student_store import StudentStore

logger = logging.getLogger(__name__)


def _safe_ui_redirect(path_query: str = "/") -> str:
    """Build a redirect target under the configured UI origin only."""
    target = str(settings.ui_base_url or "").rstrip("/")
    parsed = urlparse(target)
    local_http = parsed.scheme == "http" and parsed.hostname in {
        "127.0.0.1",
        "localhost",
    }
    if (
        not parsed.netloc
        or parsed.username
        or parsed.password
        or parsed.query
        or parsed.fragment
        or (parsed.scheme != "https" and not local_http)
    ):
        raise HTTPException(status_code=500, detail="Invalid configured UI URL")
    suffix = path_query if path_query.startswith("/") else f"/{path_query}"
    return f"{target}{suffix}"


def _public_user_payload(user: dict[str, Any]) -> dict[str, Any]:
    """Return the safe /auth/me user object (no secrets or tokens)."""
    return {
        "id": str(user.get("id") or ""),
        "cognito_sub": str(user.get("cognito_sub") or ""),
        "email": user.get("email"),
        "display_name": str(user.get("display_name") or "Student"),
        "role": str(user.get("role") or "student"),
    }


def _read_session_cookie(request: Request) -> str | None:
    """Return the opaque application-session cookie value, if any."""
    name = settings.app_session_cookie_name
    value = request.cookies.get(name)
    cleaned = str(value or "").strip()
    return cleaned or None


def _set_session_cookie(response: Response, raw_token: str) -> None:
    """Attach the HttpOnly application-session cookie to *response*."""
    params = cookie_settings()
    response.set_cookie(value=raw_token, **params)


def _clear_session_cookie(response: Response) -> None:
    """Expire the application-session cookie."""
    params = cookie_settings()
    response.delete_cookie(
        key=params["key"],
        path=params["path"],
        httponly=params["httponly"],
        samesite=params["samesite"],
        secure=params["secure"],
    )


def _set_oauth_state_cookie(response: Response, state: str) -> None:
    """Bind OAuth ``state`` to the initiating browser via a short-lived cookie."""
    params = oauth_state_cookie_settings(max_age=OAUTH_STATE_TTL_SECONDS)
    response.set_cookie(value=state, **params)


def _clear_oauth_state_cookie(response: Response) -> None:
    """Expire the temporary OAuth-state binder cookie."""
    params = oauth_state_cookie_settings(max_age=0)
    response.delete_cookie(
        key=params["key"],
        path=params["path"],
        httponly=params["httponly"],
        samesite=params["samesite"],
        secure=params["secure"],
    )


def _oauth_state_matches(request: Request, query_state: str) -> bool:
    """Return whether the OAuth-state cookie matches the callback query state."""
    expected = str(query_state or "").strip()
    cookie_value = str(
        request.cookies.get(settings.oauth_state_cookie_name) or ""
    ).strip()
    if not expected or not cookie_value:
        return False
    return hmac.compare_digest(cookie_value, expected)


def register_auth_routes(
    app,
    *,
    store: StudentStore,
    sessions: AppSessionService | None = None,
    oidc: CognitoOIDCClient | None = None,
) -> None:
    """Attach FastAPI-owned Cognito login and application-session routes."""
    session_service = sessions or AppSessionService(store)
    oidc_client = oidc or CognitoOIDCClient(store=store)

    @app.get("/api/v1/auth/login")
    def auth_login() -> RedirectResponse:
        """Redirect the browser to Cognito Managed Login (authorization code + PKCE)."""
        try:
            authorize_url, state = oidc_client.begin_login()
        except CognitoOIDCError as error:
            raise HTTPException(status_code=503, detail=str(error)) from error
        response = RedirectResponse(authorize_url, status_code=302)
        _set_oauth_state_cookie(response, state)
        response.headers["Cache-Control"] = "no-store"
        return response

    @app.get("/api/v1/auth/callback")
    def auth_callback(
        request: Request,
        code: str | None = None,
        state: str | None = None,
        error: str | None = None,
    ) -> RedirectResponse:
        """Complete Cognito login, create an app session, and redirect to the UI."""

        def _auth_error_redirect() -> RedirectResponse:
            response = RedirectResponse(
                _safe_ui_redirect("/?auth_error=1"), status_code=302
            )
            _clear_oauth_state_cookie(response)
            response.headers["Cache-Control"] = "no-store"
            return response

        if error:
            logger.info("Cognito callback returned error=%s", error)
            return _auth_error_redirect()

        query_state = str(state or "").strip()
        if not _oauth_state_matches(request, query_state):
            logger.info("OAuth state cookie missing or mismatched")
            return _auth_error_redirect()

        try:
            identity = oidc_client.complete_login(code=code or "", state=query_state)
            profile = sync_authenticated_user(identity.claims, store=store)
            created = session_service.create_session(profile.user_id)
        except CognitoOIDCError as exc:
            logger.info("Cognito callback rejected: %s", exc)
            return _auth_error_redirect()
        except Exception:
            logger.exception("Cognito callback failed unexpectedly")
            return _auth_error_redirect()

        response = RedirectResponse(_safe_ui_redirect("/"), status_code=302)
        _set_session_cookie(response, created.raw_token)
        _clear_oauth_state_cookie(response)
        response.headers["Cache-Control"] = "no-store"
        return response

    @app.get("/api/v1/auth/me")
    def auth_me(request: Request) -> JSONResponse:
        """Return the authenticated application user for a valid session cookie."""
        raw = _read_session_cookie(request)
        user = session_service.get_session_user(raw)
        if not user or not str(user.get("cognito_sub") or "").strip():
            raise HTTPException(status_code=401, detail="Not authenticated")
        return JSONResponse(
            {
                "authenticated": True,
                "user": _public_user_payload(user),
            }
        )

    @app.get("/api/v1/auth/logout")
    @app.post("/api/v1/auth/logout")
    def auth_logout(request: Request) -> RedirectResponse:
        """Revoke the application session, clear the cookie, and return to the UI."""
        raw = _read_session_cookie(request)
        session_service.revoke_session(raw)
        response = RedirectResponse(
            _safe_ui_redirect("/?signed_out=1"), status_code=302
        )
        _clear_session_cookie(response)
        response.headers["Cache-Control"] = "no-store"
        return response
