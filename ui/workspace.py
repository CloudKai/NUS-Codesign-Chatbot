"""Three-column notebook workspace layout.

Composes Thinking Path (studio), Chat, and Sources with optional collapsed
rails. Layout helpers live under ``ui.layout``; this module only wires panels.
"""

from __future__ import annotations

import time

import streamlit as st

from ui.panels.chat import render_chat_panel
from ui.layout.chat_scroll import sync_chat_scroll
from ui.layout.column_resize import (
    effective_column_widths,
    set_side_panel_collapsed,
    side_panel_collapsed,
    sync_workspace_column_resize,
)
from ui.layout.sources_scroll import sync_sources_scroll
from ui.layout.studio_scroll import sync_studio_scroll
from ui.runtime import log_ui_timing, rerun_app
from ui.sources import render_sources_panel
from ui.studio import render_studio_panel


def _render_collapsed_rail(*, side: str, expand_icon: str, label: str) -> None:
    """Render a narrow rail with a centered arrow to restore a side panel."""
    with st.container(key=f"{side}_rail"):
        if st.button(
            expand_icon,
            type="tertiary",
            key=f"expand-{side}",
            help=f"Expand {label}",
        ):
            set_side_panel_collapsed(side, False)
            rerun_app()


def render_workspace(model_id: str, reasoning_effort: str | None) -> None:
    """Render the mobile panel switcher and three-column workspace.

    Args:
        model_id: Model id forwarded to the chat panel.
        reasoning_effort: Reasoning effort forwarded to the chat panel.
    """
    panel = st.radio(
        "Workspace panel",
        ["Studio", "Chat", "Sources"],
        format_func=lambda value: {
            "Sources": "Sources",
            "Chat": "Chat",
            "Studio": (
                "Review"
                if st.session_state.get("studio_tab") == "Review"
                else "Journey"
            ),
        }[value],
        horizontal=True,
        key="mobile_panel",
        label_visibility="collapsed",
    )
    previous_panel = st.session_state.get("_last_mobile_panel")
    if panel == "Chat":
        st.session_state.nav_section = "Chat"
    elif panel == "Sources":
        st.session_state.nav_section = "Sources"
        # Expanding Sources on mobile opens the desktop rail when it was
        # collapsed, without fighting a collapse the student just chose.
        if previous_panel != "Sources" and side_panel_collapsed("sources"):
            set_side_panel_collapsed("sources", False)
    else:
        st.session_state.nav_section = st.session_state.get("studio_tab", "Journey")
    st.session_state._last_mobile_panel = panel

    studio_collapsed = side_panel_collapsed("studio")
    sources_collapsed = side_panel_collapsed("sources")

    with st.container(key="notebook_workspace"):
        widths = effective_column_widths()
        studio_column, chat_column, source_column = st.columns(
            widths,
            gap=0,
        )
        # Execute Chat first so a full-script Send (AppTest, ADVANCE remount)
        # starts FastAPI before Journey/Deep Review work. Browser Send uses
        # the composer fragment and skips this parent body entirely.
        with chat_column:
            with st.container(key="chat_panel"):
                chat_started = time.perf_counter()
                render_chat_panel(model_id, reasoning_effort)
                log_ui_timing(
                    chat_panel_ms=round(
                        max(0.0, (time.perf_counter() - chat_started) * 1000.0),
                        1,
                    )
                )
                sync_chat_scroll(mode="reconcile")
        with studio_column:
            if studio_collapsed:
                _render_collapsed_rail(
                    side="studio",
                    expand_icon="›",
                    label="Thinking Path",
                )
            else:
                with st.container(key="studio_panel"):
                    studio_started = time.perf_counter()
                    render_studio_panel()
                    log_ui_timing(
                        studio_ms=round(
                            max(0.0, (time.perf_counter() - studio_started) * 1000.0),
                            1,
                        )
                    )
                    if st.button(
                        "‹",
                        type="tertiary",
                        key="collapse-studio",
                        help="Collapse Thinking Path",
                    ):
                        set_side_panel_collapsed("studio", True)
                        rerun_app()
                    sync_studio_scroll()
        with source_column:
            if sources_collapsed:
                _render_collapsed_rail(
                    side="sources",
                    expand_icon="‹",
                    label="Sources",
                )
            else:
                with st.container(key="sources_panel"):
                    sources_started = time.perf_counter()
                    render_sources_panel()
                    log_ui_timing(
                        sources_ms=round(
                            max(0.0, (time.perf_counter() - sources_started) * 1000.0),
                            1,
                        )
                    )
                    if st.button(
                        "›",
                        type="tertiary",
                        key="collapse-sources",
                        help="Collapse Sources",
                    ):
                        set_side_panel_collapsed("sources", True)
                        rerun_app()
                    sync_sources_scroll()
        sync_workspace_column_resize()
