"""Three-column notebook workspace layout.

Composes Thinking Path (studio), Chat, and Sources with optional collapsed
rails. Layout helpers live under ``ui.layout``; this module only wires panels.
"""

from __future__ import annotations

import streamlit as st

from ui.chat import render_chat_panel
from ui.layout.column_resize import (
    effective_column_widths,
    set_side_panel_collapsed,
    side_panel_collapsed,
    sync_workspace_column_resize,
)
from ui.layout.sources_scroll import sync_sources_scroll
from ui.runtime import rerun
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
            rerun()


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
        with studio_column:
            if studio_collapsed:
                _render_collapsed_rail(
                    side="studio",
                    expand_icon="›",
                    label="Thinking Path",
                )
            else:
                with st.container(key="studio_panel"):
                    # Render content first so the absolute collapse control cannot
                    # leave a leading spacer above "Thinking Path".
                    render_studio_panel()
                    if st.button(
                        "‹",
                        type="tertiary",
                        key="collapse-studio",
                        help="Collapse Thinking Path",
                    ):
                        set_side_panel_collapsed("studio", True)
                        rerun()
        with chat_column:
            with st.container(key="chat_panel"):
                render_chat_panel(model_id, reasoning_effort)
        with source_column:
            if sources_collapsed:
                _render_collapsed_rail(
                    side="sources",
                    expand_icon="‹",
                    label="Sources",
                )
            else:
                with st.container(key="sources_panel"):
                    # Same order as studio: header content before collapse control.
                    render_sources_panel()
                    if st.button(
                        "›",
                        type="tertiary",
                        key="collapse-sources",
                        help="Collapse Sources",
                    ):
                        set_side_panel_collapsed("sources", True)
                        rerun()
                    sync_sources_scroll()
        sync_workspace_column_resize()
