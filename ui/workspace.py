"""Gemini-style notebook workspace layout.

Composes left chat nav, center Chat/Search, optional Sources (Library), and
Thinking Path on the right. Layout helpers live under ``ui.layout``.
"""

from __future__ import annotations

import logging
import time

import streamlit as st

from backend.specialists.review_orchestration import stage_reviews_need_attention
from ui.layout.chat_scroll import sync_chat_scroll
from ui.layout.column_resize import (
    effective_column_widths,
    library_open,
    set_library_open,
    set_side_panel_collapsed,
    side_panel_collapsed,
    sync_workspace_column_resize,
)
from ui.layout.sources_scroll import sync_sources_scroll
from ui.layout.studio_scroll import sync_studio_scroll
from ui.panels.chat import mount_awaiting_coach_turn_recovery, render_chat_panel
from ui.panels.nav import mount_pending_delete_chat_dialog, render_nav_panel
from ui.panels.search import render_search_panel
from ui.runtime import get_journey_stage_reviews, log_ui_timing, rerun_app
from ui.sources import render_sources_panel
from ui.studio import mount_stage_review_attention_watch, render_studio_panel

logger = logging.getLogger(__name__)

_MOBILE_JOURNEY_ATTENTION_FLAG = (
    '<span class="cd-mobile-journey-attention" hidden>'
    "Review update available</span>"
)

_MOBILE_PANEL_VALUES = ("Chats", "Chat", "Sources", "Studio")


def _mobile_journey_needs_review_attention() -> bool:
    """Return whether the mobile Journey tab should show a review-update badge."""
    thread_id = str(st.session_state.get("thread_id") or "").strip()
    if not thread_id:
        return bool(st.session_state.get("_stage_review_attention"))
    try:
        return stage_reviews_need_attention(get_journey_stage_reviews(thread_id))
    except Exception:
        logger.exception(
            "Could not load Journey review attention for notebook %s",
            thread_id,
        )
        return bool(st.session_state.get("_stage_review_attention"))


def _render_mobile_journey_attention_flag() -> None:
    """Mount a hidden DOM flag so CSS can badge the stable Journey radio."""
    if not _mobile_journey_needs_review_attention():
        return
    with st.container(key="mobile_journey_attention"):
        st.markdown(_MOBILE_JOURNEY_ATTENTION_FLAG, unsafe_allow_html=True)


def _render_collapsed_rail(*, side: str, expand_icon: str, label: str) -> None:
    """Render a narrow rail with a centered arrow to restore Thinking Path."""
    with st.container(key=f"{side}_rail"):
        if st.button(
            expand_icon,
            type="tertiary",
            key=f"expand-{side}",
            help=f"Expand {label}",
        ):
            set_side_panel_collapsed(side, False)
            rerun_app()


def _mobile_panel_label(value: str) -> str:
    """Stable mobile labels. Journey must not remount when the badge appears."""
    return {
        "Chats": "Chats",
        "Chat": "Chat",
        "Sources": "Library",
        "Studio": "Journey",
    }.get(value, value)


def render_workspace(model_id: str, reasoning_effort: str | None) -> None:
    """Render the mobile panel switcher and four-column workspace.

    Args:
        model_id: Model id forwarded to the chat panel.
        reasoning_effort: Reasoning effort forwarded to the chat panel.
    """
    if "center_view" not in st.session_state:
        st.session_state.center_view = "chat"
    center_view = str(st.session_state.get("center_view") or "chat").strip().lower()
    if center_view not in {"chat", "search"}:
        center_view = "chat"
        st.session_state.center_view = "chat"

    pending_panel = st.session_state.pop("pending_mobile_panel", None)
    if pending_panel == "Studio":
        st.session_state.mobile_panel = "Studio"
    elif pending_panel == "Sources":
        st.session_state.mobile_panel = "Sources"
        set_library_open(True)
    elif pending_panel == "Chats":
        st.session_state.mobile_panel = "Chats"
    elif pending_panel == "Chat":
        st.session_state.mobile_panel = "Chat"

    current_mobile = st.session_state.get("mobile_panel")
    if current_mobile not in _MOBILE_PANEL_VALUES:
        st.session_state.mobile_panel = "Chat"

    _render_mobile_journey_attention_flag()
    panel = st.radio(
        "Workspace panel",
        list(_MOBILE_PANEL_VALUES),
        format_func=_mobile_panel_label,
        horizontal=True,
        key="mobile_panel",
        label_visibility="collapsed",
    )
    previous_panel = st.session_state.get("_last_mobile_panel")
    if panel == "Chat":
        st.session_state.nav_section = "Chat"
    elif panel == "Chats":
        st.session_state.nav_section = "Chats"
    elif panel == "Sources":
        st.session_state.nav_section = "Sources"
        if previous_panel != "Sources" and not library_open():
            set_library_open(True)
    else:
        st.session_state.nav_section = st.session_state.get("studio_tab", "Journey")
    st.session_state._last_mobile_panel = panel

    studio_collapsed = side_panel_collapsed("studio")
    sources_visible = library_open()

    with st.container(key="notebook_workspace"):
        widths = effective_column_widths()
        nav_column, center_column, source_column, studio_column = st.columns(
            widths,
            gap=0,
        )
        # Execute Chat first so a full-script Send starts FastAPI before
        # Journey/Deep Review work. Browser Send uses the composer fragment.
        with center_column:
            if center_view == "search":
                search_started = time.perf_counter()
                render_search_panel()
                log_ui_timing(
                    search_panel_ms=round(
                        max(0.0, (time.perf_counter() - search_started) * 1000.0),
                        1,
                    )
                )
            else:
                with st.container(key="chat_panel"):
                    chat_started = time.perf_counter()
                    render_chat_panel(model_id, reasoning_effort)
                    log_ui_timing(
                        chat_panel_ms=round(
                            max(0.0, (time.perf_counter() - chat_started) * 1000.0),
                            1,
                        )
                    )
                if panel == "Chat" and st.session_state.pop(
                    "chat_follow_bottom", False
                ):
                    sync_chat_scroll(mode="send")
                elif st.session_state.pop("chat_reveal_coach_reply", False):
                    sync_chat_scroll(mode="reply")
                else:
                    sync_chat_scroll(mode="reconcile")
            # Recovery / attention pollers stay outside chat_panel (and after
            # Search) so remounts do not tear down scroll helpers.
            mount_awaiting_coach_turn_recovery()
            mount_stage_review_attention_watch()

        with nav_column:
            render_nav_panel()

        with source_column:
            if sources_visible:
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
                        help="Hide Library",
                    ):
                        set_library_open(False)
                        rerun_app()
                    sync_sources_scroll()
            else:
                with st.container(key="sources_hidden"):
                    st.empty()

        with studio_column:
            if studio_collapsed:
                _render_collapsed_rail(
                    side="studio",
                    expand_icon="‹",
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
                        "›",
                        type="tertiary",
                        key="collapse-studio",
                        help="Collapse Thinking Path",
                    ):
                        set_side_panel_collapsed("studio", True)
                        rerun_app()
                    sync_studio_scroll()
        sync_workspace_column_resize()

    mount_pending_delete_chat_dialog()
