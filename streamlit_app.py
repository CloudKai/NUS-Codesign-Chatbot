"""Streamlit entrypoint for the Co-design learning notebook.

Startup order matters: inject static CSS, gate on the FastAPI application
session (``/api/v1/auth/me``), then initialize session (including appearance
from the store), sync appearance, apply theme tokens, and render the top bar
and three-column workspace. Unauthenticated visitors see only a static shell
plus the login dialog. Prefer ``sh scripts/start.sh`` so the local API is
running.
"""

from __future__ import annotations

import streamlit as st

from ui.auth_gate import (
    authenticated_user,
    clear_authenticated_refresh_marker,
    current_user_claims,
    display_name_from_claims,
    logout_user,
    redirect_to_session_refresh,
    render_login_gate,
    render_signed_out_shell,
    should_attempt_session_refresh,
)
from ui.constants import DEFAULT_APPEARANCE
from ui.toasts import show_corner_toasts
from ui.notebooks import notebook_actions_dialog, notebooks_dialog
from ui.runtime import bind_owner_identifier
from ui.session import initialize_session
from ui.settings import sync_appearance_from_widget
from ui.theme import inject_template_css, render_theme_css
from ui.topbar import render_topbar
from ui.workspace import render_workspace

from backend.auth_profiles import store_identifier_for_sub

st.set_page_config(
    page_title="Co-design · Learning Notebook",
    page_icon="◈",
    layout="wide",
    initial_sidebar_state="collapsed",
)

inject_template_css()

user = authenticated_user()
if not user:
    # Auth gate has no preference store; always use the app default (System).
    # Overwrite leftovers from a prior logged-in session in this browser tab.
    st.session_state.appearance = DEFAULT_APPEARANCE
    render_theme_css()
    signed_out_shell_rendered = False
    if should_attempt_session_refresh():
        # Keep the static app skeleton visible while the browser checks an
        # existing Cognito refresh session. No protected data is loaded here.
        render_signed_out_shell()
        signed_out_shell_rendered = True
        if redirect_to_session_refresh():
            st.stop()
    if not signed_out_shell_rendered:
        render_signed_out_shell()
    render_login_gate()
    st.stop()

# The refresh bridge uses this one-shot marker to avoid signed-out redirect
# loops. Once the session is verified, keep the student-facing URL clean.
clear_authenticated_refresh_marker()

# Reuse the verified /auth/me result. Calling the helper without it performs a
# second network request on every Streamlit rerun and can strand a valid local
# session when that duplicate request fails transiently.
claims = current_user_claims(user)
cognito_sub = str(user.get("cognito_sub") or claims.get("sub") or "").strip()
if not cognito_sub:
    logout_user()
    st.stop()

bound_sub = str(st.session_state.get("_auth_bound_sub") or "")
store_identifier = store_identifier_for_sub(cognito_sub)
display_name = str(user.get("display_name") or "").strip() or display_name_from_claims(
    claims
)
if bound_sub != cognito_sub:
    bind_owner_identifier(store_identifier)
    if bound_sub:
        # Defensive account-switch handling: never carry one student's local
        # profile label into another authenticated identity.
        st.session_state.display_name = display_name
        st.session_state.pop("profile_display_name", None)
    elif not str(st.session_state.get("display_name") or "").strip():
        st.session_state.display_name = display_name
    st.session_state["_auth_bound_sub"] = cognito_sub
else:
    # Resource caches are keyed by owner, so rebinding is cheap.
    bind_owner_identifier(store_identifier)

if "display_name" not in st.session_state:
    st.session_state.display_name = display_name

# Debug counter for full-script runs (fragment-only interactions skip this path).
st.session_state["_app_runs"] = int(st.session_state.get("_app_runs") or 0) + 1

initialize_session()
sync_appearance_from_widget()
render_theme_css()
if st.session_state.pop("toast_course_materials_loading", False):
    show_corner_toasts("Course materials are loading.")
model_id, reasoning_effort = render_topbar()
render_workspace(model_id, reasoning_effort)

# Streamlit allows only one dialog at a time. Closing Notebook Actions reopens
# Your Notebooks via reopen_notebooks_dialog.
if st.session_state.pending_notebook_actions:
    notebook_actions_dialog()
elif st.session_state.pop("reopen_notebooks_dialog", False):
    notebooks_dialog()
