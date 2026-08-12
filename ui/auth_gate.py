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
import math
import time
from typing import Any
from urllib.parse import ParseResult, urlparse

import streamlit as st

from backend.settings import settings
from ui.constants import PRODUCT_SUBTITLE, PRODUCT_TITLE
from ui.runtime import rerun_app


_SIGNIN_COOLDOWN_SECONDS = 5.0
_SIGNIN_COOLDOWN_QUERY_PARAM = "signin_cooldown_until"
_SIGNIN_COOLDOWN_RESTORE_GRACE_SECONDS = 30.0


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
    _clear_signin_pending_state()
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
    """Return whether a signed-out render should try the browser refresh bridge.

    Full-page navigation clears Streamlit ``session_state``, so loop prevention
    relies on query markers returned by FastAPI (``auth_required``,
    ``auth_refreshed``, ``auth_error``, ``signed_out``) as well as the in-tab
    ``_auth_refresh_attempted`` flag.

    The refresh cookie is path-scoped to ``/api/v1/auth`` and invisible here.
    The non-sensitive Path=/ session hint identifies browsers that may have a
    refresh session after the short-lived ID cookie expires. Cold visitors go
    directly to the login gate instead of making a pointless refresh round trip.
    """
    if any(
        bool(st.session_state.get(key))
        for key in (
            "_auth_refresh_attempted",
            "_auth_launch_cognito",
            "_auth_signin_redirecting",
        )
    ):
        return False
    try:
        if any(
            st.query_params.get(key) == "1"
            for key in (
                "auth_required",
                "auth_refreshed",
                "auth_error",
                "signed_out",
            )
        ):
            return False
    except Exception:
        return False
    session_hint = _cookie_value(
        str(
            getattr(
                settings,
                "cognito_session_hint_cookie_name",
                "co_design_session",
            )
        )
    )
    if session_hint == "1":
        return True
    # Retain compatibility with sessions created before the hint cookie was
    # introduced. A rejected ID cookie may still accompany a valid refresh
    # cookie, and the bridge remains loop-safe through the markers above.
    return bool(
        _cookie_value(
            str(getattr(settings, "cognito_id_token_cookie_name", "co_design_id"))
        )
    )


def redirect_to_session_refresh() -> bool:
    """Navigate to FastAPI refresh without exposing the refresh token to JS.

    The signed-out app skeleton is already present when this renders. A centered
    progress indicator covers that shell while a trusted same-document link and
    direct-location fallback navigate to the refresh endpoint.

    Returns:
        ``True`` when the bridge UI was armed and the caller should ``st.stop()``.
    """
    url = auth_refresh_url()
    if not url:
        return False
    st.session_state["_auth_refresh_attempted"] = True
    st.markdown(
        '<div class="cd-auth-session-loading" role="status" aria-live="polite" '
        'aria-label="Checking your session">'
        '<span class="cd-auth-session-spinner" aria-hidden="true"></span>'
        '<span class="cd-auth-visually-hidden">Checking your session</span>'
        "</div>",
        unsafe_allow_html=True,
    )
    st.markdown(
        f'<a class="cd-auth-refresh-link" data-cd-auth-refresh="1" '
        f'href="{_escape_attr(url)}" target="_self" rel="noopener" '
        'aria-hidden="true" tabindex="-1">Continue</a>',
        unsafe_allow_html=True,
    )
    _click_refresh_link(url)
    return True


def _click_refresh_link(refresh_url: str) -> None:
    """Navigate to refresh after a short paint delay.

    Streamlit can mount the script before the preceding Markdown link. Direct
    navigation is therefore required when the link is not visible to the first
    DOM query; omitting that fallback caused the production session-check page
    to remain indefinitely.
    """
    safe_url = json.dumps(refresh_url)
    st.html(
        f"""
<script>
(() => {{
  const url = {safe_url};
  const go = () => {{
    try {{
      const link = document.querySelector(
        'a.cd-auth-refresh-link[data-cd-auth-refresh="1"]'
      );
      if (link) {{
        link.click();
        return;
      }}
    }} catch (error) {{
    }}
    if (!url) {{
      return;
    }}
    try {{
      window.location.replace(url);
    }} catch (error) {{
    }}
  }};
  setTimeout(go, 120);
}})();
</script>
""",
        unsafe_allow_javascript=True,
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
    """Start Cognito sign-in and arm the 5s button cooldown.

    The next dialog render keeps the original Sign in button in place,
    disables it for ``_SIGNIN_COOLDOWN_SECONDS``, and auto-clicks a hidden
    same-document link for reliable same-tab Cognito navigation.
    """
    url = auth_login_url()
    if not url:
        st.session_state["_auth_config_error"] = (
            "Sign-in is temporarily unavailable. Ask the course team to check "
            "the authentication configuration."
        )
        _clear_signin_pending_state()
        return
    st.session_state.pop("_auth_config_error", None)
    deadline = time.time() + _SIGNIN_COOLDOWN_SECONDS
    st.session_state["_auth_launch_cognito"] = True
    st.session_state["_auth_signin_redirecting"] = True
    st.session_state["_auth_signin_cooldown_until"] = deadline
    _set_signin_cooldown_query_marker(deadline)


def _clear_signin_pending_state() -> None:
    """Remove one-shot redirect and cooldown state from this browser session."""
    for key in (
        "_auth_launch_cognito",
        "_auth_signin_cooldown_until",
        "_auth_signin_redirecting",
    ):
        st.session_state.pop(key, None)
    _clear_signin_cooldown_query_marker()


def _set_signin_cooldown_query_marker(deadline: float) -> None:
    """Keep a non-sensitive deadline in this tab's URL for one Back recovery."""
    try:
        st.query_params[_SIGNIN_COOLDOWN_QUERY_PARAM] = f"{deadline:.6f}"
    except Exception:
        # A missing query-parameter context only loses the optional Back
        # recovery; the in-session, server-rendered cooldown remains intact.
        return


def _clear_signin_cooldown_query_marker() -> None:
    """Remove the one-tab cooldown marker without touching other query state."""
    try:
        if _SIGNIN_COOLDOWN_QUERY_PARAM in st.query_params:
            del st.query_params[_SIGNIN_COOLDOWN_QUERY_PARAM]
    except Exception:
        return


def _restore_signin_pending_state_from_query_marker() -> None:
    """Restore a signed-out cooldown after Cognito navigation starts a new session.

    The marker is UI-only and holds a server-created epoch deadline. Invalid,
    stale, or implausibly future values are ignored. It never authorizes a user
    or affects the Cognito/OAuth flow, and is consumed after one fresh render.
    """
    if any(
        key in st.session_state
        for key in (
            "_auth_launch_cognito",
            "_auth_signin_cooldown_until",
            "_auth_signin_redirecting",
        )
    ):
        return
    try:
        raw_deadline = st.query_params.get(_SIGNIN_COOLDOWN_QUERY_PARAM)
    except Exception:
        return
    _clear_signin_cooldown_query_marker()
    try:
        deadline = float(raw_deadline)
    except (TypeError, ValueError):
        return
    now = time.time()
    if (
        not math.isfinite(deadline)
        or deadline < now - _SIGNIN_COOLDOWN_RESTORE_GRACE_SECONDS
        or deadline > now + _SIGNIN_COOLDOWN_SECONDS + 1
    ):
        return
    st.session_state["_auth_signin_redirecting"] = True
    if deadline > now:
        st.session_state["_auth_signin_cooldown_until"] = deadline


def _signin_cooldown_active() -> bool:
    """Return whether the sign-in button should stay disabled."""
    try:
        until = float(st.session_state.get("_auth_signin_cooldown_until") or 0.0)
    except (TypeError, ValueError):
        st.session_state.pop("_auth_signin_cooldown_until", None)
        return False
    return time.time() < until


def _render_signin_button(*, disabled: bool) -> bool:
    """Render the original sign-in button and return whether it was clicked."""
    with st.container(key="auth-sign-in"):
        return bool(
            st.button(
                "Sign in or create an account",
                type="primary",
                use_container_width=True,
                key="auth-sign-in-button",
                disabled=disabled,
            )
        )


@st.fragment(run_every=0.5)
def _render_signin_cooldown_fragment() -> None:
    """Rerender only the disabled sign-in button until its server deadline.

    The fragment exists only while a cooldown is active.  On expiry it requests
    one app-scoped rerun, which replaces this fragment with the normal enabled
    button. The absolute deadline in session state makes remounts and
    intervening reruns unable to extend the five-second window.
    """
    if _signin_cooldown_active():
        _render_signin_button(disabled=True)
        return
    st.session_state.pop("_auth_signin_cooldown_until", None)
    rerun_app()


def _render_redirecting_status() -> None:
    """Render the stable redirect status directly above the original button."""
    with st.container(key="auth-redirecting"):
        st.markdown(
            '<div class="cd-auth-gap-after-course-notice">'
            '<div class="cd-auth-redirecting" role="status" aria-live="polite">'
            '<span class="cd-auth-spinner" aria-hidden="true"></span>'
            '<span class="cd-auth-redirecting-copy">'
            "<strong>Redirecting...</strong>"
            '<span class="cd-auth-redirecting-hint">'
            "(If Cognito does not open, this button will be available again in 5 seconds)"
            "</span>"
            "</span>"
            "</div>"
            "</div>",
            unsafe_allow_html=True,
        )


def _launch_cognito_redirect(login_url: str) -> None:
    """Launch the hidden same-document Cognito redirect link exactly once."""
    # Keep this fallback link out of the visual UI while preserving a reliable
    # same-tab navigation target for the trusted delayed script.
    st.markdown(
        f'<a data-cd-auth-redirect="1" href="{_escape_attr(login_url)}" '
        'target="_self" rel="noopener" aria-hidden="true" tabindex="-1" '
        'style="display:none !important">Sign in</a>',
        unsafe_allow_html=True,
    )
    _click_login_link(login_url)


def _click_login_link(login_url: str) -> None:
    """Navigate this tab to Cognito after a short paint delay.

    Prefer clicking the hidden same-document ``<a>``. Fall back to
    ``location.replace`` when the link is no longer available.
    """
    safe_url = json.dumps(login_url)
    st.html(
        f"""
<script>
(() => {{
  const url = {safe_url};
  const go = () => {{
    try {{
      const link = document.querySelector(
        'a[data-cd-auth-redirect="1"]'
      );
      if (link) {{
        link.click();
        return;
      }}
    }} catch (error) {{
    }}
    if (!url) {{
      return;
    }}
    try {{
      window.location.replace(url);
    }} catch (error) {{
    }}
  }};
  setTimeout(go, 280);
}})();
</script>
""",
        unsafe_allow_javascript=True,
    )


@st.dialog(
    "Welcome to CDE2300 Design Thinking Companion",
    width="small",
    dismissible=False,
)
def render_login_gate() -> None:
    """Non-dismissible Cognito sign-in dialog over the signed-out shell."""
    # Consume the launch flag once. Leaving it set would auto-redirect again
    # on every later rerun (including browser Back from Cognito).
    launch_cognito = bool(st.session_state.pop("_auth_launch_cognito", False))
    just_signed_out = False
    try:
        if st.query_params.get("signed_out") == "1":
            just_signed_out = True
            del st.query_params["signed_out"]
            _clear_signin_pending_state()
    except Exception:
        just_signed_out = bool(st.session_state.pop("_just_signed_out", None))
        if just_signed_out:
            _clear_signin_pending_state()
    try:
        if st.query_params.get("auth_required") == "1":
            st.session_state["_auth_refresh_attempted"] = True
            del st.query_params["auth_required"]
    except Exception:
        pass
    try:
        if st.query_params.get("auth_refreshed") == "1":
            # Refresh bridge already ran for this browser navigation. Keep the
            # one-shot flag so a still-signed-out paint cannot loop forever.
            st.session_state["_auth_refresh_attempted"] = True
            del st.query_params["auth_refreshed"]
    except Exception:
        pass
    try:
        if st.query_params.get("auth_error") == "1":
            st.session_state["_auth_config_error"] = (
                "Sign-in did not complete. Try again. If it keeps failing, ask "
                "the course team to check the authentication configuration."
            )
            _clear_signin_pending_state()
            del st.query_params["auth_error"]
    except Exception:
        pass
    if not just_signed_out and not st.session_state.get("_auth_config_error"):
        _restore_signin_pending_state_from_query_marker()
    with st.container(key="auth_login_card"):
        st.markdown(
            '<div class="cd-auth-card">'
            '<div class="cd-auth-brand">'
            '<span class="cd-auth-brand-mark" aria-hidden="true">C</span>'
            '<span class="cd-auth-brand-copy">'
            f'<span class="cd-auth-brand-name">{PRODUCT_TITLE}</span>'
            f'<span class="cd-auth-brand-subtitle">{PRODUCT_SUBTITLE}</span>'
            "</span>"
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
            _clear_signin_pending_state()
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
        else:
            if just_signed_out and not launch_cognito:
                with st.container(key="auth-signed-out-notice"):
                    st.markdown(
                        '<div class="cd-auth-gap-after-course-notice '
                        'cd-auth-gap-after-course-notice--spacer" '
                        'aria-hidden="true"></div>',
                        unsafe_allow_html=True,
                    )
                    st.success(
                        "You are signed out. Sign in again when you are ready."
                    )
            if launch_cognito or st.session_state.get("_auth_signin_redirecting"):
                _render_redirecting_status()
            if launch_cognito:
                _launch_cognito_redirect(login_url)
            if _signin_cooldown_active():
                _render_signin_cooldown_fragment()
            elif _render_signin_button(disabled=False):
                # A fragment-local button interaction otherwise reruns only the
                # fragment.  Always request one app rerun so the launch flag is
                # consumed by this gate and the redirect starts once.
                start_login()
                rerun_app()
        st.caption(
            "Account creation, confirmation, and passwords are handled securely "
            "by Amazon Cognito Managed Login."
        )


def render_signed_out_shell() -> None:
    """Render a static, dimmed layout preview with no protected student data."""
    with st.container(key="auth_shell"):
        st.markdown(
            f"""
<!-- Signed-out decorative shell (behind the login dialog) -->
<div class="cd-auth-shell" aria-hidden="true">
  <div class="cd-auth-shell-topbar">
    <div class="cd-auth-shell-brand"><span class="cd-auth-shell-mark">C</span>
      <span class="cd-auth-shell-brand-copy">
        <span class="cd-auth-shell-brand-title">{PRODUCT_TITLE}</span>
        <span class="cd-auth-shell-brand-subtitle">{PRODUCT_SUBTITLE}</span>
      </span>
    </div>
    <div class="cd-auth-shell-title">Untitled notebook</div>
    <div class="cd-auth-shell-actions">
      <span class="cd-auth-shell-chip">Notebooks</span>
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
        <h2>Welcome back. What are you working through today?</h2>
        <p>Sign in to continue your project thinking, evidence, and reflections.</p>
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
    _clear_signin_pending_state()
    url = app_logout_url()
    if not url:
        st.session_state["_auth_config_error"] = (
            "Sign-out requires the application API "
            "(CO_DESIGN_PUBLIC_API_URL or CO_DESIGN_API_URL). "
            "Start the app with scripts/start.sh."
        )
        return
    safe_url = json.dumps(url)
    st.html(
        f"""
<script>
(() => {{
  const url = {safe_url};
  try {{
    window.location.replace(url);
  }} catch (error) {{
  }}
}})();
</script>
""",
        unsafe_allow_javascript=True,
    )
    st.link_button("Continue sign-out", url, type="primary")
    st.stop()
