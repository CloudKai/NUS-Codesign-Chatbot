"""Three-column notebook workspace layout.

Composes Thinking Path (studio), Chat, and Sources with optional collapsed
rails. Layout helpers live under ``ui.layout``; this module only wires panels.
"""

from __future__ import annotations

import logging
import time

import streamlit as st

from backend.specialists.review_orchestration import stage_reviews_need_attention
from ui.panels.chat import mount_awaiting_coach_turn_recovery, render_chat_panel
from ui.layout.chat_scroll import sync_chat_scroll
from ui.layout.column_resize import (
    effective_column_widths,
    set_side_panel_collapsed,
    side_panel_collapsed,
    sync_workspace_column_resize,
)
from ui.layout.sources_scroll import sync_sources_scroll
from ui.layout.studio_scroll import sync_studio_scroll
from ui.runtime import get_journey_stage_reviews, log_ui_timing, rerun_app
from ui.sources import render_sources_panel
from ui.studio import mount_stage_review_attention_watch, render_studio_panel

logger = logging.getLogger(__name__)

_MOBILE_JOURNEY_ATTENTION_FLAG = (
    '<span class="cd-mobile-journey-attention" hidden>'
    "Review update available</span>"
)


def _mobile_journey_needs_review_attention() -> bool:
    """Return whether the mobile Journey tab should show a review-update badge.

    Reads the durable stage-review blob. Falls back to the attention-watch
    session flag if the notebook cannot be loaded.
    """
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
    """Mount a hidden DOM flag so CSS can badge the stable Journey radio.

    The radio label string stays ``Journey``. Changing it to include ``🛑``
    remounts the widget and can blank the mobile workspace.
    """
    if not _mobile_journey_needs_review_attention():
        return
    with st.container(key="mobile_journey_attention"):
        st.markdown(_MOBILE_JOURNEY_ATTENTION_FLAG, unsafe_allow_html=True)


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
    pending_panel = st.session_state.pop("pending_mobile_panel", None)
    if pending_panel in {"Studio", "Chat", "Sources"}:
        st.session_state.mobile_panel = pending_panel

    def _studio_mobile_label(value: str) -> str:
        """Label the Studio rail as Journey with a stable string.

        Keep this label identical across unread/read states. Appending ``🛑``
        remounts Streamlit radio options; on narrow viewports the column CSS
        keys off ``input:checked``, and a remount with no checked option hides
        every workspace column (blank screen). The stop badge is painted with
        CSS from ``cd-mobile-journey-attention``, and Review still shows ``🛑``
        on the inner Thinking Path tab.
        """
        if value != "Studio":
            return {"Sources": "Sources", "Chat": "Chat"}.get(value, value)
        return "Journey"

    _render_mobile_journey_attention_flag()
    panel = st.radio(
        "Workspace panel",
        ["Studio", "Chat", "Sources"],
        format_func=_studio_mobile_label,
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
            # Scroll helper and recovery poller stay outside chat_panel so
            # Streamlit remounts of that block (Send / tab switch) do not tear
            # down the components.html iframe or the body-hosted scroll button.
            if panel == "Chat" and st.session_state.pop(
                "chat_follow_bottom", False
            ):
                sync_chat_scroll(mode="send")
            elif st.session_state.pop("chat_reveal_coach_reply", False):
                sync_chat_scroll(mode="reply")
            else:
                sync_chat_scroll(mode="reconcile")
            mount_awaiting_coach_turn_recovery()
            mount_stage_review_attention_watch()
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
