"""Streamlit entrypoint for the Co-design learning notebook.

Startup order matters: inject static CSS, initialize session (including
appearance from the store), sync appearance, apply theme tokens, then render
the top bar and three-column workspace. Prefer ``sh scripts/start.sh`` so the
local coaching API is running with ``USE_LOCAL_API=true``.
"""

from __future__ import annotations

import streamlit as st

from ui.toasts import show_corner_toasts
from ui.notebooks import notebook_actions_dialog
from ui.session import initialize_session
from ui.settings import sync_appearance_from_widget
from ui.theme import inject_template_css, render_theme_css
from ui.topbar import render_topbar
from ui.workspace import render_workspace

st.set_page_config(
    page_title="Co-design · Learning Notebook",
    page_icon="◈",
    layout="wide",
    initial_sidebar_state="collapsed",
)

inject_template_css()
initialize_session()
sync_appearance_from_widget()
render_theme_css()
if st.session_state.pop("toast_course_materials_loading", False):
    show_corner_toasts("Course materials are loading.")
model_id, reasoning_effort = render_topbar()
render_workspace(model_id, reasoning_effort)

if st.session_state.pending_notebook_actions:
    notebook_actions_dialog()
