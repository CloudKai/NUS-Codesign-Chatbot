"""Signed-out shell and Cognito OIDC login gate for Streamlit.

Unauthenticated visitors see a static layout preview plus a non-dismissible
login dialog. Protected notebook/source data must never be loaded on this path.
Authentication is determined solely by ``st.user.is_logged_in``.
"""

from __future__ import annotations

import json
from typing import Any
from urllib.parse import ParseResult, urlencode, urlparse

import streamlit as st
import streamlit.components.v1 as components

from backend.settings import settings


def _is_allowed_http_origin(parsed: ParseResult) -> bool:
    """Return whether *parsed* is https or loopback http with a host.

    Shared by Cognito and local-API logout URL builders so both accept the same
    origins: ``https`` anywhere with a netloc, or ``http`` on ``127.0.0.1`` /
    ``localhost`` only.
    """
    if not parsed.netloc:
        return False
    if parsed.scheme == "https":
        return True
    return parsed.scheme == "http" and parsed.hostname in {
        "127.0.0.1",
        "localhost",
    }


def is_logged_in() -> bool:
    """Return whether Streamlit's OIDC identity cookie marks the user logged in."""
    user = getattr(st, "user", None)
    if user is None:
        return False
    return bool(getattr(user, "is_logged_in", False))


def current_user_claims() -> dict[str, Any]:
    """Return a plain dict of available ``st.user`` identity claims (no tokens)."""
    user = getattr(st, "user", None)
    if user is None or not getattr(user, "is_logged_in", False):
        return {}
    claims: dict[str, Any] = {}
    for key in (
        "sub",
        "email",
        "given_name",
        "name",
        "preferred_username",
        "cognito:username",
    ):
        value = _claim(user, key)
        if value is not None and str(value).strip():
            claims[key] = value
    return claims


def _claim(user: Any, key: str) -> Any:
    """Read one claim from dict-like or attribute-style ``st.user``."""
    try:
        if hasattr(user, "get"):
            value = user.get(key)
            if value is not None:
                return value
    except Exception:
        pass
    try:
        return getattr(user, key, None)
    except Exception:
        return None


def display_name_from_claims(claims: dict[str, Any]) -> str:
    """Build a safe profile display name from Cognito claims."""
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


def auth_credentials_configured() -> tuple[bool, str | None]:
    """Return whether Streamlit OIDC secrets look usable for Cognito login."""
    try:
        from streamlit.auth_util import validate_auth_credentials

        # st.login(None) normalizes to provider "default" before validation.
        # Passing None here raises TypeError: argument of type 'NoneType' is
        # not iterable inside Streamlit's auth_util.
        validate_auth_credentials("default")
        return True, None
    except Exception as exc:
        message = str(exc).strip() or "Authentication is not configured."
        return False, message


def start_login() -> None:
    """Validate Cognito secrets then start Streamlit's OIDC login redirect.

    Shows a friendly error in session state when ``secrets.toml`` is missing
    or incomplete, instead of raising an uncaught StreamlitAuthError.
    """
    ok, error = auth_credentials_configured()
    if not ok:
        st.session_state["_auth_config_error"] = error
        st.session_state.pop("_auth_redirecting", None)
        return
    st.session_state.pop("_auth_config_error", None)
    st.session_state["_auth_redirecting"] = True
    try:
        st.login()
    except Exception:
        st.session_state.pop("_auth_redirecting", None)
        st.session_state["_auth_config_error"] = (
            "Could not start sign-in. Check your network connection and try again."
        )


@st.dialog(
    "Welcome to your critical-thinking coach",
    width="small",
    dismissible=False,
)
def render_login_gate() -> None:
    """Non-dismissible Cognito sign-in dialog over the signed-out shell.

    Layout (top → bottom), styled by ``ui/assets/styles/55-auth.css``:

    1. Brand + body + course notice (``.cd-auth-card``)
    2. Optional config error, or redirecting status, or signed-out success
    3. Primary Sign in CTA (``.st-key-auth-sign-in``)
    4. Cognito Managed Login caption
    """
    # One-shot after the Sign in click: show redirecting UI for this rerun,
    # then clear so a later return to the gate can retry.
    redirecting = bool(st.session_state.pop("_auth_redirecting", None))
    just_signed_out = False
    try:
        if st.query_params.get("signed_out") == "1":
            just_signed_out = True
            del st.query_params["signed_out"]
    except Exception:
        just_signed_out = bool(st.session_state.pop("_just_signed_out", None))
    with st.container(key="auth_login_card"):
        # --- Login card: brand, pitch, and "Never graded" course notice ---
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
        if config_error:
            # --- Auth misconfiguration (secrets / Cognito client) ---
            st.error(
                "Sign-in is temporarily unavailable. Check your network, then try "
                "again. If it keeps failing, ask the course team to check the "
                "authentication configuration."
            )
        elif redirecting:
            # --- Redirecting status (between course notice and Sign in CTA) ---
            # ``.cd-auth-gap-after-course-notice`` = 10px gap under Never graded.
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
            # --- Post-logout success (between course notice and Sign in CTA) ---
            with st.container(key="auth-signed-out-notice"):
                st.markdown(
                    '<div class="cd-auth-gap-after-course-notice '
                    'cd-auth-gap-after-course-notice--spacer" '
                    'aria-hidden="true"></div>',
                    unsafe_allow_html=True,
                )
                st.success("You are signed out. Sign in again when you are ready.")
        # --- Primary CTA: start Cognito OIDC via start_login / st.login() ---
        st.button(
            "Redirecting securely…" if redirecting else "Sign in or create an account",
            type="primary",
            use_container_width=True,
            key="auth-sign-in",
            on_click=start_login,
            disabled=redirecting,
        )
        # --- Footer: Cognito owns signup / password / confirmation UX ---
        st.caption(
            "Account creation, confirmation, and passwords are handled securely "
            "by Amazon Cognito Managed Login."
        )


def render_signed_out_shell() -> None:
    """Render a static, dimmed layout preview with no protected student data.

    Mirrors the real app chrome (top bar + three columns) so the login dialog
    sits over a familiar frame. Markup classes map 1:1 to ``55-auth.css``
    ``.cd-auth-shell-*`` rules. ``pointer-events: none`` keeps it non-interactive.
    """
    with st.container(key="auth_shell"):
        st.markdown(
            """
<!-- Signed-out decorative shell (behind the login dialog) -->
<div class="cd-auth-shell" aria-hidden="true">
  <!-- Fake top bar: brand | notebook title | chips + avatar -->
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
    <!-- Left: Thinking Path / Journey stages -->
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
    <!-- Center: Coach welcome copy -->
    <section class="cd-auth-shell-panel cd-auth-shell-coach">
      <div class="cd-auth-shell-pane-title">Coach</div>
      <div class="cd-auth-shell-coach-copy">
        <h2>Welcome to your critical-thinking coach</h2>
        <p>Sign in to continue your notebooks and coaching conversations.</p>
      </div>
    </section>
    <!-- Right: placeholder Sources list -->
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


def cognito_logout_url() -> str | None:
    """Build an ordered Cognito-to-Streamlit logout URL (optional / unused by UI).

    Profile Logout uses ``app_logout_url()`` only (same-tab local callback).
    Keep this helper for a future Cognito hosted ``/logout`` path once the
    exact ``logout_uri`` is allow-listed. Until then, do not wire it into the
    profile menu — Cognito rejects Streamlit OIDC end-session params.

    When enabled, ``logout_uri`` must share ``redirect_uri``'s hostname and
    target ``/api/v1/auth/logout/callback``.
    """
    try:
        auth = st.secrets.get("auth", {})
    except Exception:
        return None
    if not isinstance(auth, dict) and hasattr(auth, "to_dict"):
        try:
            auth = dict(auth)
        except Exception:
            return None
    try:
        domain = str(auth.get("cognito_domain") or "").rstrip("/")
        client_id = str(auth.get("client_id") or "").strip()
        logout_uri = str(auth.get("logout_uri") or "").strip()
        redirect_uri = str(auth.get("redirect_uri") or "").strip()
    except Exception:
        return None
    if not domain or not client_id or not logout_uri or not redirect_uri:
        return None
    if any("<" in value for value in (domain, client_id, logout_uri, redirect_uri)):
        return None

    domain_parts = urlparse(domain)
    logout_parts = urlparse(logout_uri)
    redirect_parts = urlparse(redirect_uri)
    if (
        domain_parts.scheme != "https"
        or not domain_parts.netloc
        or domain_parts.path not in {"", "/"}
        or domain_parts.query
        or domain_parts.fragment
    ):
        return None
    if not _is_allowed_http_origin(logout_parts):
        return None
    if logout_parts.hostname != redirect_parts.hostname:
        return None
    if (
        logout_parts.username
        or logout_parts.password
        or logout_parts.query
        or logout_parts.fragment
    ):
        return None
    if logout_parts.path.rstrip("/") != "/api/v1/auth/logout/callback":
        return None
    query = urlencode({"client_id": client_id, "logout_uri": logout_uri})
    return f"{domain}/logout?{query}"


def app_logout_url() -> str | None:
    """Return the local API logout callback used by profile Logout.

    Clears Streamlit auth cookies on ``CO_DESIGN_PUBLIC_API_URL`` (falling back
    to ``CO_DESIGN_API_URL`` for local compatibility), then redirects to the UI
    login gate with ``?signed_out=1``. See ``backend/api.py``
    ``auth_logout_callback``.
    """
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
    return f"{base}/api/v1/auth/logout/callback"


def logout_user() -> None:
    """Send the browser to the local logout callback; never use ``st.logout()``.

    Cognito advertises ``/logout`` as ``end_session_endpoint``, but Streamlit
    calls it with OIDC ``post_logout_redirect_uri`` / ``id_token_hint``. Cognito
    expects ``logout_uri`` instead and responds with "Invalid request". The
    local API callback expires Streamlit cookies and returns to the login gate.

    Prefer a user-clicked ``target="_self"`` anchor (profile menu). This helper
    is for automatic clears (for example missing ``sub``): it navigates the
    parent Streamlit frame the same way other UI injectors do.
    """
    url = app_logout_url()
    if not url:
        st.session_state["_auth_config_error"] = (
            "Sign-out requires the local API callback "
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
    // Fall through to a visible same-tab link if parent navigation is blocked.
  }}
  const doc = window.parent.document;
  const existing = doc.getElementById("cd-forced-logout");
  if (existing) existing.remove();
  const anchor = doc.createElement("a");
  anchor.id = "cd-forced-logout";
  anchor.href = url;
  anchor.target = "_self";
  anchor.rel = "noopener";
  anchor.textContent = "Continue sign-out";
  anchor.style.cssText = [
    "position:fixed",
    "inset:auto 1rem 1rem auto",
    "z-index:100001",
    "padding:0.75rem 1rem",
    "border-radius:0.65rem",
    "background:#1b2337",
    "color:#fff",
    "font:600 0.9rem/1.2 system-ui,sans-serif",
    "text-decoration:none",
  ].join(";");
  doc.body.appendChild(anchor);
}})();
</script>
""",
        height=0,
    )
    st.link_button("Continue sign-out", url, type="primary")
    st.stop()
