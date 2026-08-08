"""Signed-out shell and Cognito cookie-session login gate for Streamlit.

Unauthenticated visitors see a static layout preview plus a non-dismissible
login dialog. Protected notebook/source data must never be loaded on this path.

Authentication authority is FastAPI ``/api/v1/auth/me``. Streamlit receives
only the short-lived HttpOnly Cognito ID-token cookie; the refresh cookie is
scoped to FastAPI's auth path and never reaches Streamlit or browser
JavaScript. Tokens are never stored in ``st.session_state`` or localStorage.
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


def _cookie_value(name: str) -> str | None:
    """Read one cookie from Streamlit context when the browser sent it."""
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
    """Return the FastAPI ``/auth/me`` user for the current Cognito cookies.

    Always revalidates against FastAPI on each Streamlit rerun. Cookie values
    are read from the browser context and never stored in ``st.session_state``.
    FastAPI remains the authentication authority for expiry and refresh.
    """
    id_token = _cookie_value(
        str(getattr(settings, "cognito_id_token_cookie_name", "co_design_id"))
    )
    if not id_token:
        return None
    try:
        from ui.runtime import local_api_client

        user = local_api_client().auth_me(id_token)
    except Exception:
        return None
    if not user or not str(user.get("cognito_sub") or "").strip():
        return None
    st.session_state.pop("_auth_refresh_attempted", None)
    return user


def is_logged_in() -> bool:
    """Return whether FastAPI validates the Cognito auth cookies."""
    return authenticated_user() is not None


def current_user_claims(user: dict[str, Any] | None = None) -> dict[str, Any]:
    """Return identity claims derived from the FastAPI session user (no tokens)."""
    user = user or authenticated_user()
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


def auth_refresh_url() -> str | None:
    """Return the browser-only Cognito refresh bridge URL."""
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
    return f"{base}/api/v1/auth/refresh"


def should_attempt_session_refresh() -> bool:
    """Return whether a signed-out render should try the browser refresh bridge."""
    if bool(st.session_state.get("_auth_refresh_attempted")):
        return False
    try:
        return not any(
            st.query_params.get(key) == "1"
            for key in ("auth_required", "auth_error", "signed_out")
        )
    except Exception:
        return False


def redirect_to_session_refresh() -> None:
    """Navigate to FastAPI refresh without exposing the refresh token to JS."""
    url = auth_refresh_url()
    if not url:
        return
    st.session_state["_auth_refresh_attempted"] = True
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


def auth_credentials_configured() -> tuple[bool, str | None]:
    """Return whether a login URL can be built for Cognito via FastAPI."""
    if auth_login_url():
        return True, None
    return False, "Authentication is not configured."


def _escape_attr(value: str) -> str:
    """Escape a value for safe use inside an HTML attribute."""
    return (
        str(value)
        .replace("&", "&amp;")
        .replace('"', "&quot;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
    )


def start_login() -> None:
    """Arm the Redirecting UI on the next dialog render.

    Navigation itself uses a real same-tab ``<a>`` rendered after this flag is
    set. Sandboxed ``components.html`` ``location.replace`` is unreliable in
    Streamlit dialogs.
    """
    url = auth_login_url()
    if not url:
        st.session_state["_auth_config_error"] = (
            "Sign-in is temporarily unavailable. Ask the course team to check "
            "the authentication configuration."
        )
        st.session_state.pop("_auth_redirecting", None)
        return
    st.session_state.pop("_auth_config_error", None)
    st.session_state.pop("_auth_refresh_attempted", None)
    st.session_state["_auth_redirecting"] = True


def _click_parent_login_link() -> None:
    """Click the same-tab login ``<a>`` in the parent document after a short pause.

    The pause lets the Redirecting status paint before Cognito navigation.
    """
    components.html(
        """
<script>
(() => {
  const clickContinue = () => {
    try {
      const link = window.parent.document.querySelector(
        'a.cd-auth-sign-in-link[data-cd-auth-continue="1"]'
      );
      if (link) {
        link.click();
      }
    } catch (error) {
    }
  };
  setTimeout(clickContinue, 280);
})();
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
    redirecting = bool(st.session_state.get("_auth_redirecting"))
    just_signed_out = False
    try:
        if st.query_params.get("signed_out") == "1":
            just_signed_out = True
            del st.query_params["signed_out"]
    except Exception:
        just_signed_out = bool(st.session_state.pop("_just_signed_out", None))
    try:
        if st.query_params.get("auth_required") == "1":
            st.session_state["_auth_refresh_attempted"] = True
            del st.query_params["auth_required"]
    except Exception:
        pass
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
            with st.container(key="auth-config-error"):
                st.markdown(
                    '<div class="cd-auth-gap-after-course-notice--spacer" '
                    'aria-hidden="true"></div>',
                    unsafe_allow_html=True,
                )
                st.error(
                    "Sign-in is temporarily unavailable. Check your network, then try "
                    "again. If it keeps failing, ask the course team to check the "
                    "authentication configuration."
                )
        elif redirecting and login_url:
            with st.container(key="auth-redirecting"):
                st.markdown(
                    '<div class="cd-auth-gap-after-course-notice">'
                    '<div class="cd-auth-redirecting" role="status" aria-live="polite">'
                    '<span class="cd-auth-spinner" aria-hidden="true"></span>'
                    '<span class="cd-auth-redirecting-copy">'
                    "<strong>Redirecting...</strong>"
                    '<span class="cd-auth-redirecting-hint">'
                    "(If Cognito did not open, use Continue to sign-in below)"
                    "</span>"
                    "</span>"
                    "</div>"
                    "</div>",
                    unsafe_allow_html=True,
                )
            with st.container(key="auth-sign-in"):
                st.markdown(
                    f'<a class="cd-auth-sign-in-link" data-cd-auth-continue="1" '
                    f'href="{_escape_attr(login_url)}" target="_self" rel="noopener">'
                    "Continue to sign-in"
                    "</a>",
                    unsafe_allow_html=True,
                )
            _click_parent_login_link()
            # Keep flag until navigation leaves the page; clear on a later
            # interaction so refresh can show the Sign in button again.
            st.session_state.pop("_auth_redirecting", None)
        if just_signed_out and not redirecting and login_url and not config_error:
            with st.container(key="auth-signed-out-notice"):
                st.markdown(
                    '<div class="cd-auth-gap-after-course-notice '
                    'cd-auth-gap-after-course-notice--spacer" '
                    'aria-hidden="true"></div>',
                    unsafe_allow_html=True,
                )
                st.success("You are signed out. Sign in again when you are ready.")
        if login_url and not config_error and not redirecting:
            with st.container(key="auth-sign-in"):
                st.button(
                    "Sign in or create an account",
                    type="primary",
                    use_container_width=True,
                    key="auth-sign-in-button",
                    on_click=start_login,
                )
        st.caption(
            "Account creation, confirmation, and passwords are handled securely "
            "by Amazon Cognito Managed Login."
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
