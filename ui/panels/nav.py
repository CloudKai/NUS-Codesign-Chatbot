"""Gemini-style left chat navigation rail.

Owns New chat, Search chats, Library toggle, and Recents with Rename/Delete.
Does not implement notebook persistence; uses ``ui.session`` and ``store``.
"""

from __future__ import annotations

from html import escape
from typing import Any

import streamlit as st

from ui.constants import PRODUCT_TITLE
from ui.layout.column_resize import nav_collapsed, set_nav_collapsed
from ui.profile import render_profile_menu
from ui.menu_popovers import close_menu_popover, menu_popover_widget_key
from ui.rename import (
    bump_rename_epoch,
    discard_rename_draft,
    render_enter_to_apply_rename,
    sync_rename_select_all,
)
from ui.runtime import rerun_app, store
from ui.session import (
    delete_notebook,
    new_notebook,
    notebook_switch_locked,
    select_thread,
)


def close_mobile_nav_overlay() -> None:
    """Dismiss the Gemini-style mobile nav drawer when open."""
    if st.session_state.get("mobile_nav_open"):
        st.session_state.mobile_nav_open = False


def close_mobile_drawers() -> None:
    """Dismiss both mobile drawers without changing the center destination."""
    st.session_state.mobile_nav_open = False
    st.session_state.mobile_studio_open = False


def _finish_mobile_nav_destination() -> None:
    """Close both mobile drawers after a nav destination is chosen."""
    close_mobile_drawers()


def _on_expand_nav() -> None:
    """Expand the left rail before the script body chooses collapsed vs full."""
    set_nav_collapsed(False)


def _on_collapse_nav() -> None:
    """Collapse the left rail before the script body chooses collapsed vs full."""
    set_nav_collapsed(True)


def _on_close_mobile_nav() -> None:
    """Dismiss the mobile nav overlay before chrome markers are rendered."""
    close_mobile_nav_overlay()


def _on_open_search() -> None:
    """Route to Search and close drawers before ``center_view`` is read."""
    _finish_mobile_nav_destination()
    st.session_state.center_view = "search"
    st.session_state.pending_mobile_panel = "Chat"


def _on_toggle_library() -> None:
    """Toggle Library/Chat and close drawers before ``center_view`` is read."""
    _finish_mobile_nav_destination()
    library_on = st.session_state.get("center_view") == "library"
    st.session_state.center_view = "chat" if library_on else "library"
    st.session_state.pending_mobile_panel = "Chat" if library_on else "Sources"


def _on_new_chat() -> None:
    """Create a notebook before Chat paints so one remount owns the new thread.

    Runs as ``on_click`` (before the script body) so Recents, Chat, and Thinking
    Path all see the new ``thread_id`` without a nested full-app remount. Sets
    the course-materials toast flag here because
    ``new_notebook(should_rerun=False)`` skips that path (session init must not
    toast).
    """
    _finish_mobile_nav_destination()
    st.session_state.center_view = "chat"
    st.session_state.mobile_panel = "Chat"
    st.session_state.pending_mobile_panel = "Chat"
    st.session_state.nav_section = "Chat"
    st.session_state.toast_course_materials_loading = True
    new_notebook(should_rerun=False)


def open_chat_destination(thread_id: str) -> None:
    """Route to a chat before render; natural click remount loads the transcript.

    Closes mobile drawers and sets Chat as the center destination. When the
    tapped notebook is already active, skips ``select_thread`` so the menu
    dismiss does not re-fetch metadata. Otherwise loads the thread with
    ``should_rerun=False`` so the click's single remount is enough.

    Args:
        thread_id: Persisted notebook identifier to open.
    """
    _finish_mobile_nav_destination()
    st.session_state.center_view = "chat"
    st.session_state.mobile_panel = "Chat"
    target = str(thread_id or "").strip()
    if not target:
        return
    current = str(st.session_state.get("thread_id") or "").strip()
    if target == current:
        return
    select_thread(target, should_rerun=False)


def render_nav_panel() -> None:
    """Render the collapsible left chat rail (expanded or icon-only)."""
    # Mobile overlay always uses the full rail, not the icon-only strip.
    collapsed = nav_collapsed() and not bool(st.session_state.get("mobile_nav_open"))
    with st.container(key="nav_panel"):
        if collapsed:
            _render_collapsed_nav()
        else:
            _render_expanded_nav()


def _render_collapsed_nav() -> None:
    """Icon-only New / Search / Library plus expand control."""
    with st.container(key="nav_collapsed_actions"):
        st.button(
            "Expand sidebar",
            icon=":material/dock_to_right:",
            type="tertiary",
            key="nav-expand",
            help="Open sidebar",
            on_click=_on_expand_nav,
        )
        locked = notebook_switch_locked()
        st.button(
            "New chat",
            icon=":material/edit_square:",
            type="tertiary",
            key="nav-new-chat-collapsed",
            help="New chat",
            disabled=locked,
            on_click=_on_new_chat,
        )
        st.button(
            "Search chats",
            icon=":material/search:",
            type="tertiary",
            key="nav-search-collapsed",
            help="Search chats",
            on_click=_on_open_search,
        )
        library_on = st.session_state.get("center_view") == "library"
        st.button(
            "Library",
            icon=":material/grid_view:",
            type="primary" if library_on else "tertiary",
            key="nav-library-collapsed",
            help="Library",
            on_click=_on_toggle_library,
        )
    render_profile_menu(collapsed=True)


def _render_expanded_nav() -> None:
    """Full rail: brand, primary actions, scrollable Recents."""
    overlay_open = bool(st.session_state.get("mobile_nav_open"))
    with st.container(key="nav_header"):
        brand_col, collapse_col = st.columns([0.78, 0.22], gap="small")
        brand_col.markdown(
            f'<div class="cd-nav-brand">'
            f'<span class="brand-mark">C</span>'
            f'<span class="cd-nav-brand-title">{escape(PRODUCT_TITLE.split()[0])}</span>'
            f"</div>",
            unsafe_allow_html=True,
        )
        if overlay_open:
            collapse_col.button(
                "Close menu",
                icon=":material/close:",
                type="tertiary",
                key="mobile-nav-close",
                help="Close menu",
                on_click=_on_close_mobile_nav,
            )
        else:
            collapse_col.button(
                "Collapse sidebar",
                icon=":material/dock_to_right:",
                type="tertiary",
                key="nav-collapse",
                help="Close sidebar",
                on_click=_on_collapse_nav,
            )

    locked = notebook_switch_locked()
    with st.container(key="nav_primary"):
        st.button(
            "New chat",
            icon=":material/edit_square:",
            type="tertiary",
            key="nav-new-chat",
            use_container_width=True,
            disabled=locked,
            help="Wait for the coach reply" if locked else None,
            on_click=_on_new_chat,
        )
        st.button(
            "Search chats",
            icon=":material/search:",
            type="tertiary",
            key="nav-search-chats",
            use_container_width=True,
            on_click=_on_open_search,
        )
        library_on = st.session_state.get("center_view") == "library"
        st.button(
            "Library",
            icon=":material/grid_view:",
            type="primary" if library_on else "tertiary",
            key="nav-library",
            use_container_width=True,
            on_click=_on_toggle_library,
        )
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
        else:
            for thread in threads:
                _render_recent_row(thread, active_id=active_id, locked=locked)
    render_profile_menu()


def _render_recent_row(
    thread: dict[str, Any],
    *,
    active_id: str,
    locked: bool,
) -> None:
    """One Recents row with open, rename, download, and delete actions."""
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
            st.button(
                title,
                type="primary" if is_active else "tertiary",
                key=f"nav-open-{thread_id}",
                use_container_width=True,
                disabled=open_disabled,
                help="Wait for the coach reply" if open_disabled else None,
                on_click=open_chat_destination,
                args=(thread_id,),
            )
        with menu_col:
            # Icon in the label (not icon=) so Streamlit omits expand_more chrome.
            menu = st.popover(
                ":material/more_vert:",
                type="tertiary",
                help="Chat actions",
                disabled=locked,
                key=menu_popover_widget_key("nav-chat", thread_id),
            )
            was_open_key = f"nav-menu-was-open-{thread_id}"
            was_open = bool(st.session_state.get(was_open_key))
            is_open = bool(menu.open)
            if was_open and not is_open:
                discard_rename_draft("notebook", thread_id)
                bump_rename_epoch("notebook", thread_id)
            st.session_state[was_open_key] = is_open
            with menu:
                render_chat_actions_menu(
                    thread_id,
                    title=title,
                    menu_scope="nav-chat",
                )


def _on_open_delete_chat(thread_id: str, menu_scope: str) -> None:
    """Arm the delete dialog before render so one remount opens it.

    Closes the Recents/mobile chat ⋮ popover via epoch bump. Does not call a
    nested full-app remount; ``mount_pending_delete_chat_dialog`` at the end of
    the workspace paint opens the confirmation on this same script run.
    """
    target = str(thread_id or "").strip()
    if not target:
        return
    st.session_state.pending_delete_chat_id = target
    close_menu_popover(menu_scope, target)


def render_chat_actions_menu(
    thread_id: str,
    *,
    title: str,
    menu_scope: str = "nav-chat",
) -> None:
    """Popover body: Rename, download transcript, and Delete."""
    safe_id = thread_id.replace("-", "_")
    rename_key = (
        f"nav_rename_{safe_id}"
        if menu_scope == "nav-chat"
        else f"mobile_rename_{safe_id}"
    )
    danger_key = (
        f"nav_action_danger_{safe_id}"
        if menu_scope == "nav-chat"
        else f"mobile_action_danger_{safe_id}"
    )
    st.markdown(
        '<div class="cd-chat-setting-heading">Chat Setting</div>',
        unsafe_allow_html=True,
    )
    with st.container(key=rename_key):
        applied, cleaned = render_enter_to_apply_rename(
            kind="notebook",
            item_id=str(thread_id),
            label="Rename",
            current_value=title,
            key_namespace=menu_scope,
        )
    if applied and cleaned and cleaned != title:
        store.update_thread(thread_id, name=cleaned)
        close_menu_popover(menu_scope, thread_id)
        bump_rename_epoch("notebook", thread_id)
        rerun_app()
    sync_rename_select_all(
        root_selector=(
            f'[data-testid="stPopoverBody"]'
            f":has(.st-key-{rename_key})"
        ),
        aria_label="Rename",
    )

    try:
        transcript = store.download_transcript(thread_id)
    except ValueError:
        transcript = None
    if transcript is not None:
        st.download_button(
            "Download transcript",
            data=transcript.data,
            file_name=transcript.filename,
            mime="text/plain",
            key=f"{menu_scope}-download-transcript-{thread_id}",
            type="tertiary",
            icon=":material/download:",
            help="Save this chat transcript",
            use_container_width=True,
        )

    with st.container(key=danger_key):
        st.button(
            "Delete",
            icon=":material/delete:",
            type="tertiary",
            key=f"{menu_scope}-delete-open-{thread_id}",
            use_container_width=True,
            on_click=_on_open_delete_chat,
            args=(thread_id, menu_scope),
        )

def _render_recent_menu(thread_id: str, *, title: str, safe_id: str) -> None:
    """Backward-compatible wrapper for Recents popover body."""
    del safe_id
    render_chat_actions_menu(thread_id, title=title, menu_scope="nav-chat")


def dismiss_delete_chat_dialog() -> None:
    """Clear pending delete when the dialog is closed via X / outside / Esc.

    Without this, clicking away leaves ``pending_delete_chat_id`` set and the
    confirmation remounts on every later rerun (including New chat).
    """
    st.session_state.pop("pending_delete_chat_id", None)


@st.dialog("Delete chat?", on_dismiss=dismiss_delete_chat_dialog)
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
        dismiss_delete_chat_dialog()
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
        dismiss_delete_chat_dialog()
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
