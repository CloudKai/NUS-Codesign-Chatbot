"""Gemini-style left chat navigation rail.

Owns New chat, Search chats, Library toggle, and Recents with Rename/Delete.
Does not implement notebook persistence; uses ``ui.session`` and ``store``.
"""

from __future__ import annotations

from html import escape
from typing import Any

import streamlit as st

from ui.constants import PRODUCT_TITLE
from ui.layout.column_resize import (
    library_open,
    nav_collapsed,
    set_library_open,
    set_nav_collapsed,
)
from ui.rename import (
    bump_rename_epoch,
    discard_rename_draft,
    render_enter_to_apply_rename,
)
from ui.runtime import rerun_app, store
from ui.session import (
    delete_notebook,
    new_notebook,
    notebook_switch_locked,
    select_thread,
)


def render_nav_panel() -> None:
    """Render the collapsible left chat rail (expanded or icon-only)."""
    collapsed = nav_collapsed()
    with st.container(key="nav_panel"):
        if collapsed:
            _render_collapsed_nav()
        else:
            _render_expanded_nav()


def _render_collapsed_nav() -> None:
    """Icon-only New / Search / Library plus expand control."""
    with st.container(key="nav_collapsed_actions"):
        if st.button(
            "",
            icon=":material/dock_to_right:",
            type="tertiary",
            key="nav-expand",
            help="Open sidebar",
        ):
            set_nav_collapsed(False)
            rerun_app()
        locked = notebook_switch_locked()
        if st.button(
            "",
            icon=":material/edit_square:",
            type="tertiary",
            key="nav-new-chat-collapsed",
            help="New chat",
            disabled=locked,
        ):
            st.session_state.center_view = "chat"
            new_notebook()
        if st.button(
            "",
            icon=":material/search:",
            type="tertiary",
            key="nav-search-collapsed",
            help="Search chats",
        ):
            st.session_state.center_view = "search"
            st.session_state.pending_mobile_panel = "Chat"
            rerun_app()
        library_on = library_open()
        if st.button(
            "",
            icon=":material/grid_view:",
            type="primary" if library_on else "tertiary",
            key="nav-library-collapsed",
            help="Library",
        ):
            set_library_open(not library_on)
            rerun_app()


def _render_expanded_nav() -> None:
    """Full rail: brand, primary actions, scrollable Recents."""
    with st.container(key="nav_header"):
        brand_col, collapse_col = st.columns([0.82, 0.18], gap="small")
        brand_col.markdown(
            f'<div class="cd-nav-brand">'
            f'<span class="brand-mark">C</span>'
            f'<span class="cd-nav-brand-title">{escape(PRODUCT_TITLE.split()[0])}</span>'
            f"</div>",
            unsafe_allow_html=True,
        )
        if collapse_col.button(
            "",
            icon=":material/dock_to_right:",
            type="tertiary",
            key="nav-collapse",
            help="Close sidebar",
        ):
            set_nav_collapsed(True)
            rerun_app()

    locked = notebook_switch_locked()
    with st.container(key="nav_primary"):
        if st.button(
            "New chat",
            icon=":material/edit_square:",
            type="tertiary",
            key="nav-new-chat",
            use_container_width=True,
            disabled=locked,
            help="Wait for the coach reply" if locked else None,
        ):
            st.session_state.center_view = "chat"
            new_notebook()
        if st.button(
            "Search chats",
            icon=":material/search:",
            type="tertiary",
            key="nav-search-chats",
            use_container_width=True,
        ):
            st.session_state.center_view = "search"
            st.session_state.pending_mobile_panel = "Chat"
            rerun_app()
        library_on = library_open()
        if st.button(
            "Library",
            icon=":material/grid_view:",
            type="primary" if library_on else "tertiary",
            key="nav-library",
            use_container_width=True,
        ):
            set_library_open(not library_on)
            if not library_on:
                st.session_state.pending_mobile_panel = "Sources"
            rerun_app()

    st.markdown(
        '<div class="cd-nav-section-label">Recents</div>',
        unsafe_allow_html=True,
    )
    if locked:
        st.caption("Wait for the coach reply before switching chats.")

    threads = store.list_threads("", None)
    active_id = str(st.session_state.get("thread_id") or "")
    with st.container(key="nav_recents_scroll", height="stretch"):
        if not threads:
            st.caption("No chats yet.")
            return
        for thread in threads:
            _render_recent_row(thread, active_id=active_id, locked=locked)


def _render_recent_row(
    thread: dict[str, Any],
    *,
    active_id: str,
    locked: bool,
) -> None:
    """One Recents row: open chat + ⋮ Rename / Delete."""
    thread_id = str(thread.get("id") or "")
    if not thread_id:
        return
    safe_id = thread_id.replace("-", "_")
    title = str(thread.get("name") or "Untitled notebook").strip() or "Untitled notebook"
    is_active = thread_id == active_id
    open_disabled = locked and not is_active
    row_key = f"nav_recent_{safe_id}"
    with st.container(key=row_key):
        title_col, menu_col = st.columns([0.86, 0.14], gap="small")
        with title_col:
            if st.button(
                title,
                type="primary" if is_active else "tertiary",
                key=f"nav-open-{thread_id}",
                use_container_width=True,
                disabled=open_disabled,
                help="Wait for the coach reply" if open_disabled else None,
            ):
                st.session_state.center_view = "chat"
                select_thread(thread_id)
        with menu_col:
            with st.popover(
                "",
                icon=":material/more_vert:",
                help="Chat actions",
                disabled=locked,
                key=f"nav-menu-{thread_id}",
            ):
                _render_recent_menu(thread_id, title=title)


def _render_recent_menu(thread_id: str, *, title: str) -> None:
    """Popover actions: Rename and Delete only."""
    if st.button(
        "Rename",
        icon=":material/edit:",
        type="tertiary",
        key=f"nav-rename-open-{thread_id}",
        use_container_width=True,
    ):
        st.session_state[f"nav_renaming_{thread_id}"] = True
        rerun_app()
    if st.button(
        "Delete",
        icon=":material/delete:",
        type="tertiary",
        key=f"nav-delete-open-{thread_id}",
        use_container_width=True,
    ):
        st.session_state.pending_delete_chat_id = thread_id
        rerun_app()

    if st.session_state.get(f"nav_renaming_{thread_id}"):
        applied, cleaned = render_enter_to_apply_rename(
            kind="notebook",
            item_id=str(thread_id),
            label="Rename",
            current_value=title,
        )
        if applied and cleaned and cleaned != title:
            store.update_thread(thread_id, name=cleaned)
            st.session_state.pop(f"nav_renaming_{thread_id}", None)
            bump_rename_epoch("notebook", thread_id)
            rerun_app()
        if st.button(
            "Cancel rename",
            type="tertiary",
            key=f"nav-rename-cancel-{thread_id}",
        ):
            discard_rename_draft("notebook", thread_id)
            bump_rename_epoch("notebook", thread_id)
            st.session_state.pop(f"nav_renaming_{thread_id}", None)
            rerun_app()


@st.dialog("Delete chat?")
def confirm_delete_chat_dialog() -> None:
    """Confirm permanent chat deletion from the Recents ⋮ menu."""
    thread_id = str(st.session_state.get("pending_delete_chat_id") or "").strip()
    if not thread_id:
        return
    thread = store.get_thread(thread_id) or {}
    name = str(thread.get("name") or "Untitled notebook").strip() or "Untitled notebook"
    st.write(
        f"This will permanently delete **{name}**, including prompts, "
        "responses, and feedback. This cannot be undone."
    )
    cancel_col, delete_col = st.columns(2)
    if cancel_col.button("Cancel", use_container_width=True, key="nav-delete-cancel"):
        st.session_state.pop("pending_delete_chat_id", None)
        rerun_app()
    locked = notebook_switch_locked()
    if delete_col.button(
        "Delete",
        type="primary",
        use_container_width=True,
        disabled=locked,
        key="nav-delete-confirm",
    ):
        delete_notebook(thread_id)
        st.session_state.pop("pending_delete_chat_id", None)
        # Defer notebook switch until the next script run (before widgets).
        if not st.session_state.get("thread_id"):
            threads = store.list_threads()
            if threads:
                st.session_state["_pending_select_thread"] = threads[0]["id"]
            else:
                st.session_state["_pending_new_notebook"] = True
        rerun_app()


def mount_pending_delete_chat_dialog() -> None:
    """Open the delete confirmation dialog when Recents requested it."""
    if st.session_state.get("pending_delete_chat_id"):
        confirm_delete_chat_dialog()
