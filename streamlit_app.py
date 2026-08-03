from __future__ import annotations

import streamlit as st

from ui.notebooks import notebook_actions_dialog
from ui.session import initialize_session
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
render_theme_css()
model_id, reasoning_effort = render_topbar()
render_workspace(model_id, reasoning_effort)

if st.session_state.pending_notebook_actions:
    notebook_actions_dialog()
