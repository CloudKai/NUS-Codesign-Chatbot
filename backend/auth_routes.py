"""FastAPI authentication handlers: Cognito login + HttpOnly token cookies."""

from __future__ import annotations

import hmac
import logging
from typing import Any
from urllib.parse import urlparse

from fastapi import HTTPException, Request, Response
from fastapi.responses import JSONResponse, RedirectResponse

from backend.auth_oidc import (
    CognitoAuthSession,
    CognitoOIDCClient,
    CognitoOIDCError,
    OAUTH_STATE_TTL_SECONDS,
)
from backend.auth_profiles import sync_authenticated_user
from backend.cognito_cookies import (
    id_token_cookie_settings,
    oauth_state_cookie_settings,
    refresh_cookie_settings,
)
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


def _read_cookie(request: Request, name: str) -> str | None:
    """Return a trimmed cookie value, or ``None`` when missing."""
    cleaned = str(request.cookies.get(name) or "").strip()
    return cleaned or None


def _set_auth_cookies(response: Response, session: CognitoAuthSession) -> None:
    """Attach HttpOnly refresh + ID-token cookies from a verified session."""
    refresh_params = refresh_cookie_settings()
    id_params = id_token_cookie_settings()
    response.set_cookie(value=session.refresh_token, **refresh_params)
    response.set_cookie(value=session.id_token, **id_params)


def _clear_auth_cookies(response: Response) -> None:
    """Expire both Cognito auth cookies (idempotent)."""
    for params in (refresh_cookie_settings(), id_token_cookie_settings()):
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
    oidc: CognitoOIDCClient | None = None,
) -> None:
    """Attach FastAPI-owned Cognito login and cookie-session routes."""
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
        """Complete Cognito login, set auth cookies, and redirect to the UI."""

        def _auth_error_redirect() -> RedirectResponse:
            response = RedirectResponse(
                _safe_ui_redirect("/?auth_error=1"), status_code=302
            )
            _clear_oauth_state_cookie(response)
            _clear_auth_cookies(response)
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
            session = oidc_client.complete_login(code=code or "", state=query_state)
            sync_authenticated_user(session.identity.claims, store=store)
        except CognitoOIDCError as exc:
            logger.info("Cognito callback rejected: %s", exc)
            return _auth_error_redirect()
        except Exception:
            logger.exception("Cognito callback failed unexpectedly")
            return _auth_error_redirect()

        response = RedirectResponse(_safe_ui_redirect("/"), status_code=302)
        _set_auth_cookies(response, session)
        _clear_oauth_state_cookie(response)
        response.headers["Cache-Control"] = "no-store"
        return response

    @app.get("/api/v1/auth/refresh")
    def auth_refresh(request: Request) -> RedirectResponse:
        """Refresh Cognito in the browser context, then return to Streamlit.

        The refresh cookie is scoped to ``/api/v1/auth`` and therefore never
        reaches Streamlit. When Streamlit's short-lived ID cookie expires, it
        redirects the browser here; the browser attaches the refresh cookie
        without exposing it to JavaScript.
        """
        refresh_token = _read_cookie(
            request, settings.cognito_refresh_cookie_name
        )
        if not refresh_token:
            response = RedirectResponse(
                _safe_ui_redirect("/?auth_required=1"), status_code=302
            )
            _clear_auth_cookies(response)
            response.headers["Cache-Control"] = "no-store"
            return response
        try:
            session = oidc_client.refresh(refresh_token)
            sync_authenticated_user(session.identity.claims, store=store)
        except (CognitoOIDCError, ValueError):
            response = RedirectResponse(
                _safe_ui_redirect("/?auth_required=1"), status_code=302
            )
            _clear_auth_cookies(response)
            response.headers["Cache-Control"] = "no-store"
            return response

        response = RedirectResponse(_safe_ui_redirect("/"), status_code=302)
        _set_auth_cookies(response, session)
        response.headers["Cache-Control"] = "no-store"
        return response

    @app.get("/api/v1/auth/me")
    def auth_me(request: Request) -> JSONResponse:
        """Return the authenticated user for valid Cognito cookies (no tokens)."""
        id_token = _read_cookie(request, settings.cognito_id_token_cookie_name)
        refresh_token = _read_cookie(request, settings.cognito_refresh_cookie_name)

        identity = None
        refreshed: CognitoAuthSession | None = None
        if id_token:
            try:
                identity = oidc_client.verify_id_token(id_token)
            except CognitoOIDCError:
                identity = None

        if identity is None:
            if not refresh_token:
                response = JSONResponse(
                    {"authenticated": False, "detail": "Not authenticated"},
                    status_code=401,
                )
                _clear_auth_cookies(response)
                response.headers["Cache-Control"] = "no-store"
                return response
            try:
                refreshed = oidc_client.refresh(refresh_token)
                identity = refreshed.identity
            except CognitoOIDCError:
                response = JSONResponse(
                    {"authenticated": False, "detail": "Not authenticated"},
                    status_code=401,
                )
                _clear_auth_cookies(response)
                response.headers["Cache-Control"] = "no-store"
                return response

        # Prefer exact sub lookup; sync when missing so first-refresh after
        # callback still binds the row without requiring a second login.
        user = store.get_user_by_cognito_sub(identity.sub)
        if user is None:
            profile = sync_authenticated_user(identity.claims, store=store)
            user = store.get_user_by_id(profile.user_id)
        if not user or not str(user.get("cognito_sub") or "").strip():
            response = JSONResponse(
                {"authenticated": False, "detail": "Not authenticated"},
                status_code=401,
            )
            _clear_auth_cookies(response)
            response.headers["Cache-Control"] = "no-store"
            return response

        payload = {
            "authenticated": True,
            "user": _public_user_payload(user),
        }
        response = JSONResponse(payload)
        if refreshed is not None:
            # Rotate ID cookie (and refresh when Cognito returned a new one).
            response.set_cookie(
                value=refreshed.id_token, **id_token_cookie_settings()
            )
            if refreshed.refresh_token != refresh_token:
                response.set_cookie(
                    value=refreshed.refresh_token, **refresh_cookie_settings()
                )
        response.headers["Cache-Control"] = "no-store"
        return response

    @app.get("/api/v1/auth/logout")
    @app.post("/api/v1/auth/logout")
    def auth_logout(request: Request) -> RedirectResponse:
        """Best-effort revoke refresh token, always clear cookies, return to UI."""
        refresh_token = _read_cookie(request, settings.cognito_refresh_cookie_name)
        if refresh_token:
            oidc_client.revoke(refresh_token)
        response = RedirectResponse(
            _safe_ui_redirect("/?signed_out=1"), status_code=302
        )
        _clear_auth_cookies(response)
        response.headers["Cache-Control"] = "no-store"
        return response
