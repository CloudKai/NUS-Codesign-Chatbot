"""Gemini-style notebook workspace layout.

Composes the left chat nav, a center Chat/Search/Library view, and Thinking
Path on the right. On narrow viewports a top chrome opens the nav as an
overlay and exposes New chat plus the current-chat ⋮ menu. Layout helpers
live under ``ui.layout``.
"""

from __future__ import annotations

import logging
import time
from html import escape

import streamlit as st

from backend.specialists.review_orchestration import stage_reviews_need_attention
from ui.layout.chat_scroll import sync_chat_scroll
from ui.layout.column_resize import (
    effective_column_widths,
    set_nav_collapsed,
    set_side_panel_collapsed,
    side_panel_collapsed,
    sync_workspace_column_resize,
)
from ui.layout.sources_scroll import sync_sources_scroll
from ui.layout.studio_scroll import sync_studio_scroll
from ui.menu_popovers import menu_popover_widget_key
from ui.panels.chat import mount_awaiting_coach_turn_recovery, render_chat_panel
from ui.panels.nav import (
    close_mobile_drawers,
    mount_pending_delete_chat_dialog,
    render_chat_actions_menu,
    render_nav_panel,
)
from ui.panels.search import render_search_panel
from ui.runtime import get_journey_stage_reviews, log_ui_timing, store
from ui.session import new_notebook, notebook_switch_locked
from ui.sources import render_sources_panel
from ui.studio import mount_stage_review_attention_watch, render_studio_panel

logger = logging.getLogger(__name__)

_MOBILE_JOURNEY_ATTENTION_FLAG = (
    '<span class="cd-mobile-journey-attention" hidden>'
    "Review update available</span>"
)

_MOBILE_PANEL_VALUES = ("Chats", "Chat", "Sources", "Studio")


def _mobile_journey_needs_review_attention() -> bool:
    """Return whether the mobile Analytics control needs an update badge."""
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
    """Mount a hidden DOM flag so CSS can badge the Analytics control."""
    if not _mobile_journey_needs_review_attention():
        return
    with st.container(key="mobile_journey_attention"):
        st.markdown(_MOBILE_JOURNEY_ATTENTION_FLAG, unsafe_allow_html=True)


def _mobile_panel_label(value: str) -> str:
    """Human labels for mobile panel ids (Journey for the Thinking Path)."""
    return {
        "Chats": "Chats",
        "Chat": "Chat",
        "Sources": "Library",
        "Studio": "Journey",
    }.get(value, value)


def _apply_pending_mobile_panel() -> str:
    """Normalize legacy mobile destinations into center and drawer state."""
    pending_panel = st.session_state.pop("pending_mobile_panel", None)
    if pending_panel == "Studio":
        st.session_state.mobile_nav_open = False
        st.session_state.mobile_studio_open = True
        set_side_panel_collapsed("studio", False)
    elif pending_panel == "Sources":
        st.session_state.mobile_panel = "Sources"
        st.session_state.center_view = "library"
        close_mobile_drawers()
    elif pending_panel == "Chats":
        # Legacy Chats tab → open the nav overlay instead.
        st.session_state.mobile_panel = (
            "Sources" if st.session_state.get("center_view") == "library" else "Chat"
        )
        st.session_state.mobile_nav_open = True
        st.session_state.mobile_studio_open = False
        set_nav_collapsed(False)
    elif pending_panel == "Chat":
        if st.session_state.get("mobile_studio_open"):
            # Thinking Path stage selection historically returns to Chat so
            # the persisted coach briefing is visible.
            st.session_state.center_view = "chat"
        st.session_state.mobile_panel = "Chat"
        close_mobile_drawers()

    current_mobile = st.session_state.get("mobile_panel")
    if current_mobile == "Studio":
        # Older callers used Studio as a center replacement. Keep the current
        # Chat/Search/Library destination and open Thinking Path over it.
        st.session_state.mobile_studio_open = True
        st.session_state.mobile_nav_open = False
        set_side_panel_collapsed("studio", False)
        current_mobile = (
            "Sources" if st.session_state.get("center_view") == "library" else "Chat"
        )
        st.session_state.mobile_panel = current_mobile
    if current_mobile not in _MOBILE_PANEL_VALUES:
        st.session_state.mobile_panel = "Chat"
    # Chats is no longer a visible destination; treat it as Chat + overlay.
    if st.session_state.mobile_panel == "Chats":
        st.session_state.mobile_panel = "Chat"
        st.session_state.mobile_nav_open = True
        st.session_state.mobile_studio_open = False
        set_nav_collapsed(False)
    if st.session_state.get("mobile_nav_open") and st.session_state.get(
        "mobile_studio_open"
    ):
        # Defensive normalization for restored or test-injected legacy state.
        st.session_state.mobile_nav_open = False
    return str(st.session_state.mobile_panel)


def _current_chat_title() -> str:
    """Return the active notebook title for the mobile header."""
    thread_id = str(st.session_state.get("thread_id") or "").strip()
    if not thread_id:
        return "New chat"
    thread = store.get_thread(thread_id) or {}
    title = str(thread.get("name") or "").strip()
    return title or "Untitled notebook"


def _on_open_mobile_nav() -> None:
    """Open the nav overlay before chrome markers and column widths are read."""
    st.session_state.mobile_nav_open = True
    st.session_state.mobile_studio_open = False
    set_nav_collapsed(False)


def _on_open_mobile_studio() -> None:
    """Open Thinking Path before studio collapse / drawer markers are read."""
    st.session_state.mobile_nav_open = False
    st.session_state.mobile_studio_open = True
    set_side_panel_collapsed("studio", False)


def _on_close_mobile_drawers() -> None:
    """Dismiss both drawers before overlay markers are rendered."""
    close_mobile_drawers()


def _on_expand_side_panel(side: str) -> None:
    """Restore a collapsed side panel before widths are chosen."""
    set_side_panel_collapsed(side, False)


def _on_close_mobile_studio() -> None:
    """Close the mobile Thinking Path drawer before markers are rendered."""
    st.session_state.mobile_studio_open = False


def _on_collapse_studio() -> None:
    """Collapse Thinking Path before column widths are chosen."""
    set_side_panel_collapsed("studio", True)


def _render_mobile_header(panel: str) -> None:
    """Gemini mobile chrome: menu, title, Analytics, new chat, and chat ⋮."""
    nav_open = bool(st.session_state.get("mobile_nav_open"))
    studio_open = bool(st.session_state.get("mobile_studio_open"))
    locked = notebook_switch_locked()
    thread_id = str(st.session_state.get("thread_id") or "").strip()
    title = _current_chat_title()

    with st.container(key="mobile_panel"):
        markers = (
            f'<div class="cd-mobile-view" data-panel="{escape(panel, quote=True)}" '
            'hidden></div>'
        )
        if nav_open:
            markers += '<div class="cd-mobile-nav-open" hidden></div>'
        if studio_open:
            markers += '<div class="cd-mobile-studio-open" hidden></div>'
        st.markdown(markers, unsafe_allow_html=True)

        menu_col, title_col, analyse_col, new_col, more_col = st.columns(
            [0.12, 0.52, 0.12, 0.12, 0.12],
            gap="small",
        )
        with menu_col:
            with st.container(key="mobile_nav_menu"):
                st.button(
                    "Open menu",
                    icon=":material/menu:",
                    type="tertiary",
                    key="mobile-nav-menu",
                    help="Open menu",
                    on_click=_on_open_mobile_nav,
                )
        with title_col:
            st.markdown(
                f'<div class="cd-mobile-header-title">{escape(title)}</div>',
                unsafe_allow_html=True,
            )
        with analyse_col:
            with st.container(key="mobile_analyse"):
                st.button(
                    "Analyse / Thinking Path",
                    icon=":material/analytics:",
                    type="tertiary",
                    key="mobile-analytics",
                    help="Analyse / Thinking Path",
                    on_click=_on_open_mobile_studio,
                )
        with new_col:
            if st.button(
                "New chat",
                icon=":material/edit_square:",
                type="tertiary",
                key="mobile-new-chat",
                help="New chat",
                disabled=locked,
            ):
                # Notebook create remounts via ``new_notebook`` (not on_click).
                close_mobile_drawers()
                st.session_state.center_view = "chat"
                st.session_state.mobile_panel = "Chat"
                new_notebook()
        with more_col:
            with st.container(key="mobile_chat_menu"):
                if not thread_id:
                    st.button(
                        "Chat actions",
                        icon=":material/more_vert:",
                        type="tertiary",
                        key="mobile-chat-menu-disabled",
                        help="Chat actions",
                        disabled=True,
                    )
                else:
                    menu = st.popover(
                        ":material/more_vert:",
                        type="tertiary",
                        help="Chat actions",
                        disabled=locked,
                        key=menu_popover_widget_key("mobile-chat", thread_id),
                    )
                    with menu:
                        render_chat_actions_menu(
                            thread_id,
                            title=title,
                            menu_scope="mobile-chat",
                        )

    with st.container(key="mobile_drawer_backdrop"):
        st.button(
            "Close drawer",
            key="mobile-drawer-backdrop",
            type="tertiary",
            use_container_width=True,
            on_click=_on_close_mobile_drawers,
        )


def _render_collapsed_rail(*, side: str, label: str) -> None:
    """Render an icon rail that restores the collapsed Thinking Path."""
    with st.container(key=f"{side}_rail"):
        st.button(
            "Analyse",
            icon=":material/analytics:",
            type="tertiary",
            key=f"expand-{side}",
            help=f"Expand Analyse / {label}",
            on_click=_on_expand_side_panel,
            args=(side,),
        )


def render_workspace(model_id: str, reasoning_effort: str | None) -> None:
    """Render the mobile chrome and three-region workspace.

    Args:
        model_id: Model id forwarded to the chat panel.
        reasoning_effort: Reasoning effort forwarded to the chat panel.
    """
    if "center_view" not in st.session_state:
        st.session_state.center_view = "chat"
    if "mobile_nav_open" not in st.session_state:
        st.session_state.mobile_nav_open = False
    if "mobile_studio_open" not in st.session_state:
        st.session_state.mobile_studio_open = False
    center_view = str(st.session_state.get("center_view") or "chat").strip().lower()
    if center_view not in {"chat", "search", "library"}:
        center_view = "chat"
        st.session_state.center_view = "chat"

    panel = _apply_pending_mobile_panel()
    center_view = str(st.session_state.get("center_view") or "chat").strip().lower()

    _render_mobile_journey_attention_flag()
    _render_mobile_header(panel)

    if panel == "Chat":
        st.session_state.nav_section = "Chat"
    elif panel == "Sources":
        st.session_state.nav_section = "Sources"
        # Keep the local render variable in sync with the compatibility state
        # so Library never leaves a one-frame Chat/blank flash on mobile.
        st.session_state.center_view = "library"
        center_view = "library"
    else:
        st.session_state.nav_section = "Chat"

    studio_collapsed = side_panel_collapsed("studio")
    if st.session_state.get("mobile_studio_open") and studio_collapsed:
        # An active mobile drawer must mount the full Thinking Path even when
        # the same session last used the collapsed desktop rail.
        set_side_panel_collapsed("studio", False)
        studio_collapsed = False

    with st.container(key="notebook_workspace"):
        widths = effective_column_widths()
        nav_column, center_column, studio_column = st.columns(
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
            elif center_view == "library":
                with st.container(key="sources_panel"):
                    sources_started = time.perf_counter()
                    render_sources_panel()
                    log_ui_timing(
                        sources_ms=round(
                            max(
                                0.0,
                                (time.perf_counter() - sources_started) * 1000.0,
                            ),
                            1,
                        )
                    )
                    sync_sources_scroll()
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

        with studio_column:
            if studio_collapsed:
                _render_collapsed_rail(
                    side="studio",
                    label="Thinking Path",
                )
            else:
                with st.container(key="studio_panel"):
                    with st.container(key="mobile_studio_close"):
                        st.button(
                            "Close Thinking Path",
                            icon=":material/close:",
                            type="tertiary",
                            key="mobile-studio-close",
                            help="Close Thinking Path",
                            on_click=_on_close_mobile_studio,
                        )
                    studio_started = time.perf_counter()
                    render_studio_panel()
                    log_ui_timing(
                        studio_ms=round(
                            max(0.0, (time.perf_counter() - studio_started) * 1000.0),
                            1,
                        )
                    )
                    st.button(
                        "Collapse Thinking Path",
                        icon=":material/dock_to_left:",
                        type="tertiary",
                        key="collapse-studio",
                        help="Collapse Thinking Path",
                        on_click=_on_collapse_studio,
                    )
                    sync_studio_scroll()
        sync_workspace_column_resize()

    mount_pending_delete_chat_dialog()
