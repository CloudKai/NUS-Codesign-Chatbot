"""Streamlit entrypoint for the Co-design learning notebook.

Startup order matters: inject static CSS, drop the one-shot
``auth_refreshed`` query marker, gate on the FastAPI application session
(``/api/v1/auth/me``), then initialize session (including appearance from
the store), sync appearance, apply theme tokens, run nonvisual workspace
preparation, and render the three-region workspace. Guest-enabled visitors
enter through a browser-issued guest cookie before notebook data is loaded;
the login gate remains the fallback when guest access is disabled. Prefer
``sh scripts/start.sh`` so the local API is running.

Chat transcript scrolling is owned by ``.st-key-chat_panel`` and
``ui.layout.chat_scroll``; do not restore per-log overflow scrolling.
"""

from __future__ import annotations

import streamlit as st

from ui.auth_gate import (
    AuthServiceUnavailable,
    authenticated_user,
    authenticated_guest,
    clear_identity_session_state,
    consume_auth_refresh_marker,
    current_user_claims,
    display_name_from_claims,
    logout_user,
    redirect_to_session_refresh,
    render_guest_entry,
    render_login_gate,
    render_signed_out_shell,
    should_attempt_session_refresh,
    guest_access_available,
)
from ui.constants import DEFAULT_APPEARANCE
from ui.toasts import show_corner_toasts
from ui.notebooks import notebooks_dialog
from ui.runtime import bind_owner_identifier, configure_ui_perf_logger
from ui.session import initialize_session, new_notebook, select_thread
from ui.settings import sync_appearance_from_widget
from ui.theme import inject_template_css, render_theme_css
from ui.profile import inject_profile_leave_helper
from ui.topbar import prepare_workspace_context
from ui.professor import prepare_professor_appearance, render_professor_dashboard
from ui.workspace import render_workspace

from backend.auth_profiles import store_identifier_for_sub

st.set_page_config(
    page_title="Co-design · Learning Notebook",
    page_icon="◈",
    layout="wide",
    initial_sidebar_state="collapsed",
)

configure_ui_perf_logger()
inject_template_css()
consume_auth_refresh_marker()

try:
    user = authenticated_user()
except AuthServiceUnavailable:
    # Verification failed without a 401: keep the current owner and refresh
    # hints untouched, and do not try a guest or protected workspace request.
    st.error("We couldn't check your session right now. Please retry.")
    if st.button("Retry", key="auth-service-retry"):
        st.rerun()
    st.stop()
signed_out_shell_rendered = False
if not user:
    # Auth gate has no preference store; always use the app default (System).
    # Overwrite leftovers from a prior logged-in session in this browser tab.
    st.session_state.appearance = DEFAULT_APPEARANCE
    render_theme_css()
    if should_attempt_session_refresh():
        # Cognito refresh still takes priority over an existing guest cookie.
        # The old decorative shell is only needed for the login-gated mode.
        if not guest_access_available():
            render_signed_out_shell()
            signed_out_shell_rendered = True
        if redirect_to_session_refresh():
            st.stop()

# A Cognito refresh hint takes precedence over a coincident guest cookie. The
# browser refresh bridge runs before FastAPI is asked to bind a guest owner.
guest = authenticated_guest() if not user else None
if not user and not guest:
    if guest_access_available():
        render_guest_entry()
    else:
        if not signed_out_shell_rendered:
            render_signed_out_shell()
        render_login_gate()
    st.stop()

# Reuse the verified /auth/me result. Calling the helper without it performs a
# second network request on every Streamlit rerun and can strand a valid local
# session when that duplicate request fails transiently.
if guest:
    owner_key = str(guest["guest_id"])
    if str(st.session_state.get("_auth_bound_owner") or "") != owner_key:
        clear_identity_session_state()
    bind_owner_identifier(owner_key)
    st.session_state["_auth_bound_owner"] = owner_key
    st.session_state["_auth_bound_kind"] = "guest"
    st.session_state["display_name"] = "Guest"
else:
    claims = current_user_claims(user)
    cognito_sub = str(user.get("cognito_sub") or claims.get("sub") or "").strip()
    if not cognito_sub:
        logout_user()
        st.stop()

    store_identifier = store_identifier_for_sub(cognito_sub)
    if str(st.session_state.get("_auth_bound_owner") or "") != store_identifier:
        clear_identity_session_state()
    bind_owner_identifier(store_identifier)
    st.session_state["_auth_bound_owner"] = store_identifier
    st.session_state["_auth_bound_kind"] = "cognito"
    st.session_state["_auth_bound_sub"] = cognito_sub
    display_name = str(user.get("display_name") or "").strip() or display_name_from_claims(
        claims
    )
    if not str(st.session_state.get("display_name") or "").strip():
        st.session_state.display_name = display_name

if "display_name" not in st.session_state:
    st.session_state.display_name = display_name

if user and st.query_params.get("guest_transfer_error") == "1":
    st.warning(
        "We couldn't confirm whether your guest notebooks were added. Check "
        "your notebook list. If they are missing, sign out and sign in again "
        "to retry; keep this browser's cookies."
    )

# Professor navigation is only a convenience; the FastAPI professor routes
# independently verify Cognito and the persisted lecturer/admin role.  Branch
# before student notebook/session initialisation so staff never create or alter
# a student workspace while reviewing analytics.
if user and str(user.get("role") or "").strip().lower() in {"lecturer", "admin"}:
    # Staff bypasses student session initialization, but still restores the
    # persisted appearance and synchronizes the settings widget before theme
    # CSS is injected. This branch must not create or select a notebook.
    professor_client = prepare_professor_appearance()
    render_professor_dashboard(professor_client)
    st.stop()

# Debug counter for full-script runs (fragment-only interactions skip this path).
st.session_state["_app_runs"] = int(st.session_state.get("_app_runs") or 0) + 1

initialize_session()
# Recents delete may request a notebook switch after the dialog closed; apply
# before top-bar widgets are instantiated.
_pending_select = st.session_state.pop("_pending_select_thread", None)
if _pending_select:
    select_thread(str(_pending_select), should_rerun=False)
elif st.session_state.pop("_pending_new_notebook", False):
    new_notebook(should_rerun=False)
sync_appearance_from_widget()
render_theme_css()
if st.session_state.pop("toast_course_materials_loading", False):
    show_corner_toasts("Course materials are loading.")
model_id, reasoning_effort = prepare_workspace_context()
render_workspace(model_id, reasoning_effort)
if guest:
    st.html(
        """
<script>
fetch('/api/v1/auth/guest/renew', {
  method: 'POST',
  credentials: 'same-origin'
}).catch(() => {});
</script>
""",
        unsafe_allow_javascript=True,
    )
inject_profile_leave_helper()

# Single Your Notebooks dialog: remount while an inline actions panel is pending
# or after delete asks for the list view. No nested Notebook Actions dialog.
_pending_notebook = st.session_state.get("pending_notebook_actions")
_reopen_notebooks = st.session_state.pop("reopen_notebooks_dialog", False)
if _pending_notebook or _reopen_notebooks:
    notebooks_dialog()
