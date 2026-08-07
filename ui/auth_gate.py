"""Signed-out shell and FastAPI application-session login gate for Streamlit.

Unauthenticated visitors see a static layout preview plus a non-dismissible
login dialog. Protected notebook/source data must never be loaded on this path.

Authentication authority is FastAPI ``/api/v1/auth/me`` validated against the
opaque ``co_design_session`` cookie. Cognito tokens are not used after login.
Streamlit native OIDC helpers are not the session authority.
"""

from __future__ import annotations

import json
from typing import Any
from urllib.parse import ParseResult, urlparse

import streamlit as st
import streamlit.components.v1 as components

from backend.settings import settings


def _is_allowed_http_origin(parsed: ParseResult) -> bool:
    """Return whether *parsed* is https or loopback http with a host."""
    if not parsed.netloc:
        return False
    if parsed.scheme == "https":
        return True
    return parsed.scheme == "http" and parsed.hostname in {
        "127.0.0.1",
        "localhost",
    }


def _session_cookie_value() -> str | None:
    """Read the opaque application-session cookie from Streamlit context."""
    name = str(getattr(settings, "app_session_cookie_name", "co_design_session"))
    try:
        cookies = getattr(st, "context", None)
        cookie_map = getattr(cookies, "cookies", None) if cookies is not None else None
        if cookie_map is None:
            return None
        value = cookie_map.get(name)
        cleaned = str(value or "").strip()
        return cleaned or None
    except Exception:
        return None


def authenticated_user() -> dict[str, Any] | None:
    """Return the FastAPI ``/auth/me`` user for the current cookie, if valid.

    Results are cached in ``st.session_state`` for the current run identity so
    Streamlit reruns do not hammer the API, but the cache key includes the raw
    cookie so a different session cannot reuse another user's profile.
    """
    token = _session_cookie_value()
    if not token:
        st.session_state.pop("_auth_me_user", None)
        st.session_state.pop("_auth_me_token", None)
        return None
    cached_token = str(st.session_state.get("_auth_me_token") or "")
    cached_user = st.session_state.get("_auth_me_user")
    if cached_token == token and isinstance(cached_user, dict):
        return cached_user
    try:
        from ui.runtime import local_api_client

        user = local_api_client().auth_me(token)
    except Exception:
        st.session_state.pop("_auth_me_user", None)
        st.session_state.pop("_auth_me_token", None)
        return None
    if not user or not str(user.get("cognito_sub") or "").strip():
        st.session_state.pop("_auth_me_user", None)
        st.session_state.pop("_auth_me_token", None)
        return None
    st.session_state["_auth_me_token"] = token
    st.session_state["_auth_me_user"] = user
    return user


def is_logged_in() -> bool:
    """Return whether FastAPI validates the opaque application-session cookie."""
    return authenticated_user() is not None


def current_user_claims() -> dict[str, Any]:
    """Return identity claims derived from the FastAPI session user (no tokens)."""
    user = authenticated_user()
    if not user:
        return {}
    claims: dict[str, Any] = {"sub": str(user.get("cognito_sub") or "").strip()}
    email = str(user.get("email") or "").strip()
    if email:
        claims["email"] = email
    display_name = str(user.get("display_name") or "").strip()
    if display_name:
        claims["name"] = display_name
        claims["given_name"] = display_name
    return claims


def display_name_from_claims(claims: dict[str, Any]) -> str:
    """Build a safe profile display name from session-backed claims."""
    for key in ("given_name", "name", "preferred_username", "cognito:username"):
        value = str(claims.get(key) or "").strip()
        if value:
            return value[:80]
    email = str(claims.get("email") or "").strip()
    if email and "@" in email:
        return email.split("@", 1)[0][:80]
    if email:
        return email[:80]
    return "Student"


def auth_login_url() -> str | None:
    """Return the public FastAPI Cognito login URL."""
    base = str(
        getattr(settings, "public_api_base_url", "")
        or getattr(settings, "api_base_url", "")
        or ""
    ).rstrip("/")
    parsed = urlparse(base)
    if (
        not _is_allowed_http_origin(parsed)
        or parsed.username
        or parsed.password
        or parsed.query
        or parsed.fragment
    ):
        return None
    return f"{base}/api/v1/auth/login"


def auth_credentials_configured() -> tuple[bool, str | None]:
    """Return whether a login URL can be built for Cognito via FastAPI."""
    if auth_login_url():
        return True, None
    return False, "Authentication is not configured."


def start_login() -> None:
    """Navigate the browser to FastAPI Cognito login (same tab)."""
    url = auth_login_url()
    if not url:
        st.session_state["_auth_config_error"] = (
            "Sign-in is temporarily unavailable. Ask the course team to check "
            "the authentication configuration."
        )
        st.session_state.pop("_auth_redirecting", None)
        return
    st.session_state.pop("_auth_config_error", None)
    st.session_state["_auth_redirecting"] = True
    safe_url = json.dumps(url)
    components.html(
        f"""
<script>
(() => {{
  const url = {safe_url};
  try {{
    window.parent.location.replace(url);
  }} catch (error) {{
    window.location.replace(url);
  }}
}})();
</script>
""",
        height=0,
    )


@st.dialog(
    "Welcome to your critical-thinking coach",
    width="small",
    dismissible=False,
)
def render_login_gate() -> None:
    """Non-dismissible Cognito sign-in dialog over the signed-out shell."""
    redirecting = bool(st.session_state.pop("_auth_redirecting", None))
    just_signed_out = False
    try:
        if st.query_params.get("signed_out") == "1":
            just_signed_out = True
            del st.query_params["signed_out"]
    except Exception:
        just_signed_out = bool(st.session_state.pop("_just_signed_out", None))
    try:
        if st.query_params.get("auth_error") == "1":
            st.session_state["_auth_config_error"] = (
                "Sign-in did not complete. Try again. If it keeps failing, ask "
                "the course team to check the authentication configuration."
            )
            del st.query_params["auth_error"]
    except Exception:
        pass
    with st.container(key="auth_login_card"):
        st.markdown(
            '<div class="cd-auth-card">'
            '<div class="cd-auth-brand">'
            '<span class="cd-auth-brand-mark" aria-hidden="true">C</span>'
            '<span class="cd-auth-brand-name">Critical Thinking Companion</span>'
            "</div>"
            '<p class="cd-auth-body">Sign in to save your notebooks, conversations, '
            "journey progress, sources, reviews, and personalised feedback.</p>"
            '<div class="cd-auth-course-notice">'
            '<p><strong>Never graded.</strong> Work in this chatbot has no association '
            "with your course grades.</p>"
            "<p>This companion is used for the course. We would like to understand "
            "how students use it and whether it benefits their learning.</p>"
            "</div>"
            "</div>",
            unsafe_allow_html=True,
        )
        config_error = st.session_state.get("_auth_config_error")
        login_url = auth_login_url()
        if config_error or not login_url:
            st.error(
                "Sign-in is temporarily unavailable. Check your network, then try "
                "again. If it keeps failing, ask the course team to check the "
                "authentication configuration."
            )
        elif redirecting:
            with st.container(key="auth-redirecting"):
                st.markdown(
                    '<div class="cd-auth-gap-after-course-notice">'
                    '<div class="cd-auth-redirecting" role="status" aria-live="polite">'
                    '<span class="cd-auth-spinner" aria-hidden="true"></span>'
                    '<span class="cd-auth-redirecting-copy">'
                    "<strong>Redirecting...</strong>"
                    '<span class="cd-auth-redirecting-hint">'
                    "(If Cognito did not open, you may have timed out)"
                    "</span>"
                    "</span>"
                    "</div>"
                    "</div>",
                    unsafe_allow_html=True,
                )
        if just_signed_out and not redirecting:
            with st.container(key="auth-signed-out-notice"):
                st.markdown(
                    '<div class="cd-auth-gap-after-course-notice '
                    'cd-auth-gap-after-course-notice--spacer" '
                    'aria-hidden="true"></div>',
                    unsafe_allow_html=True,
                )
                st.success("You are signed out. Sign in again when you are ready.")
        if login_url and not config_error:
            st.button(
                "Redirecting securely…" if redirecting else "Sign in or create an account",
                type="primary",
                use_container_width=True,
                key="auth-sign-in",
                on_click=start_login,
                disabled=redirecting,
            )
        st.caption(
            "Account creation, confirmation, and passwords are handled securely "
            "by Amazon Cognito Managed Login. After sign-in, this app keeps you "
            "signed in with its own 30-day session cookie — not Cognito tokens."
        )


def render_signed_out_shell() -> None:
    """Render a static, dimmed layout preview with no protected student data."""
    with st.container(key="auth_shell"):
        st.markdown(
            """
<!-- Signed-out decorative shell (behind the login dialog) -->
<div class="cd-auth-shell" aria-hidden="true">
  <div class="cd-auth-shell-topbar">
    <div class="cd-auth-shell-brand"><span class="cd-auth-shell-mark">C</span>
      Critical Thinking Companion</div>
    <div class="cd-auth-shell-title">Untitled notebook</div>
    <div class="cd-auth-shell-actions">
      <span class="cd-auth-shell-chip">Notebooks</span>
      <span class="cd-auth-shell-chip">Guidance Level: Quick</span>
      <span class="cd-auth-shell-avatar">S</span>
    </div>
  </div>
  <div class="cd-auth-shell-workspace">
    <aside class="cd-auth-shell-panel cd-auth-shell-studio">
      <div class="cd-auth-shell-pane-title">Thinking Path</div>
      <div class="cd-auth-shell-tabs"><span class="is-active">Journey</span><span>Review</span></div>
      <div class="cd-auth-shell-muted">Your critical-thinking journey</div>
      <div class="cd-auth-shell-stage is-active">Focus</div>
      <div class="cd-auth-shell-stage">Evidence</div>
      <div class="cd-auth-shell-stage">Assumptions</div>
      <div class="cd-auth-shell-stage">Perspectives</div>
      <div class="cd-auth-shell-stage">Synthesis</div>
      <div class="cd-auth-shell-stage">Conclusion</div>
    </aside>
    <section class="cd-auth-shell-panel cd-auth-shell-coach">
      <div class="cd-auth-shell-pane-title">Coach</div>
      <div class="cd-auth-shell-coach-copy">
        <h2>Welcome to your critical-thinking coach</h2>
        <p>Sign in to continue your notebooks and coaching conversations.</p>
      </div>
    </section>
    <aside class="cd-auth-shell-panel cd-auth-shell-sources">
      <div class="cd-auth-shell-pane-title">Sources</div>
      <div class="cd-auth-shell-muted">No sources until you sign in</div>
      <div class="cd-auth-shell-source-row">Lecture notes</div>
      <div class="cd-auth-shell-source-row">Readings</div>
    </aside>
  </div>
</div>
            """,
            unsafe_allow_html=True,
        )


def app_logout_url() -> str | None:
    """Return the FastAPI application-session logout URL used by profile Logout."""
    base = str(
        getattr(settings, "public_api_base_url", "")
        or getattr(settings, "api_base_url", "")
        or ""
    ).rstrip("/")
    parsed = urlparse(base)
    if (
        not _is_allowed_http_origin(parsed)
        or parsed.username
        or parsed.password
        or parsed.query
        or parsed.fragment
    ):
        return None
    return f"{base}/api/v1/auth/logout"


def logout_user() -> None:
    """Send the browser to FastAPI logout; never use Streamlit native logout."""
    url = app_logout_url()
    if not url:
        st.session_state["_auth_config_error"] = (
            "Sign-out requires the application API "
            "(CO_DESIGN_PUBLIC_API_URL or CO_DESIGN_API_URL). "
            "Start the app with scripts/start.sh."
        )
        return
    st.session_state.pop("_auth_me_user", None)
    st.session_state.pop("_auth_me_token", None)
    safe_url = json.dumps(url)
    components.html(
        f"""
<script>
(() => {{
  const url = {safe_url};
  try {{
    window.parent.location.replace(url);
    return;
  }} catch (error) {{
  }}
  window.location.replace(url);
}})();
</script>
""",
        height=0,
    )
    st.link_button("Continue sign-out", url, type="primary")
    st.stop()
