"""Streamlit entrypoint for the Co-design learning notebook.

Startup order matters: inject static CSS, gate on Cognito OIDC identity, then
initialize session (including appearance from the store), sync appearance,
apply theme tokens, and render the top bar and three-column workspace.
Unauthenticated visitors see only a static shell plus the login dialog.
Prefer ``sh scripts/start.sh`` so the local coaching API is running with
``USE_LOCAL_API=true``.
"""

from __future__ import annotations

import streamlit as st

from ui.auth_gate import (
    current_user_claims,
    display_name_from_claims,
    is_logged_in,
    logout_user,
    render_login_gate,
    render_signed_out_shell,
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

from backend.auth_profiles import store_identifier_for_sub, sync_authenticated_user

st.set_page_config(
    page_title="Co-design · Learning Notebook",
    page_icon="◈",
    layout="wide",
    initial_sidebar_state="collapsed",
)

inject_template_css()

if not is_logged_in():
    # Auth gate has no preference store; always use the app default (System).
    # Overwrite leftovers from a prior logged-in session in this browser tab.
    st.session_state.appearance = DEFAULT_APPEARANCE
    render_theme_css()
    render_signed_out_shell()
    render_login_gate()
    st.stop()

claims = current_user_claims()
cognito_sub = str(claims.get("sub") or "").strip()
if not cognito_sub:
    # A signed identity cookie without the stable Cognito subject cannot be
    # mapped safely to application data. Clear it locally — never st.logout(),
    # which sends Cognito OIDC end-session params Cognito rejects as Invalid
    # request.
    logout_user()
    st.stop()

bound_sub = str(st.session_state.get("_auth_bound_sub") or "")
if bound_sub != cognito_sub:
    profile = sync_authenticated_user(claims)
    bind_owner_identifier(profile.store_identifier)
    if bound_sub:
        # Defensive account-switch handling: never carry one student's local
        # profile label into another authenticated identity.
        st.session_state.display_name = profile.display_name
        st.session_state.pop("profile_display_name", None)
    elif not str(st.session_state.get("display_name") or "").strip():
        st.session_state.display_name = profile.display_name
    st.session_state["_auth_bound_sub"] = cognito_sub
else:
    # Resource caches are keyed by owner, so rebinding is cheap and avoids a
    # database upsert on every Streamlit widget rerun.
    bind_owner_identifier(store_identifier_for_sub(cognito_sub))

if "display_name" not in st.session_state:
    st.session_state.display_name = display_name_from_claims(claims)

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
