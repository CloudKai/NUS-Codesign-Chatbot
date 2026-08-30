"""Source contracts for Gemini-style nav rail and Search pane."""

from __future__ import annotations

from pathlib import Path


def test_workspace_column_order_is_nav_center_studio() -> None:
    """Desktop is nav | center | studio; Library is one center destination."""
    workspace = Path("ui/workspace.py").read_text(encoding="utf-8")
    assert "nav_column, center_column, studio_column" in workspace
    assert "source_column" not in workspace
    center = workspace.split("with center_column:", 1)[1].split("with nav_column:", 1)[0]
    assert 'key="chat_panel"' in center
    assert "render_chat_panel(" in center
    assert "mount_awaiting_coach_turn_recovery()" in center
    chat_branch = center.split("else:", 1)[1]
    assert chat_branch.index("render_chat_panel(") < chat_branch.index(
        "mount_awaiting_coach_turn_recovery()"
    )
    assert center.rindex('key="chat_panel"') < center.rindex(
        "mount_awaiting_coach_turn_recovery()"
    )
    assert "render_search_panel" in workspace
    assert 'center_view == "library"' in workspace
    assert "render_sources_panel" in center
    assert "render_nav_panel" in workspace
    assert "collapse-sources" not in workspace


def test_nav_rail_exposes_new_search_library_and_recents_actions() -> None:
    """Recents ⋮ keeps rename, download, and delete without Gemini-only actions."""
    nav = Path("ui/panels/nav.py").read_text(encoding="utf-8")
    assert 'key="nav-new-chat"' in nav
    assert 'key="nav-search-chats"' in nav
    assert 'key="nav-library"' in nav
    assert "Recents" in nav
    assert "Rename" in nav
    assert "Download transcript" in nav
    assert "Save transcript" in nav
    assert "prepare_transcript_export" in nav
    assert "on_click=prepare_transcript_export" in nav
    # Must not prefetch transcript bytes while painting every Recents row.
    actions = nav.split("def render_chat_actions_menu", 1)[1].split(
        "def _render_recent_menu", 1
    )[0]
    assert "store.download_transcript(" not in actions
    assert "render_transcript_download_control(" in actions
    prepare = nav.split("def prepare_transcript_export", 1)[1].split("\ndef ", 1)[0]
    assert "store.download_transcript(" in prepare
    assert "clear_transcript_export_cache" in nav
    assert "Delete" in nav
    assert "Chat Setting" in nav
    assert "Delete chat?" in nav
    assert "on_dismiss=dismiss_delete_chat_dialog" in nav
    assert "def dismiss_delete_chat_dialog" in nav
    assert ":material/more_vert:" in nav
    assert 'icon=":material/more_vert:"' not in nav
    assert 'icon=":material/more_horiz:"' not in nav
    assert "menu_popover_widget_key" in nav
    assert "nav_rename_" in nav
    assert "Share conversation" not in nav
    assert "Add to notebook" not in nav
    assert '"Pin"' not in nav
    # Recents Chat Setting matches mobile: Rename + visible Apply on one row.
    css_nav = Path("ui/assets/styles/15-nav.css").read_text(encoding="utf-8")
    assert "grid-template-columns:minmax(0,1fr) auto" in css_nav
    nav_rename_css = css_nav.split('st-key-nav_rename_"', 1)[1]
    assert "stFormSubmitButton" in nav_rename_css
    assert "display:flex !important" in nav_rename_css
    # Apply must stay visible (no hide rule for the submit control).
    hide_submit = (
        '[data-testid="stFormSubmitButton"] {\n'
        "        display:none !important;"
    )
    assert hide_submit not in css_nav
    assert "set_nav_collapsed" in nav
    assert "new_notebook(should_rerun=False)" in nav
    assert "select_thread(" in nav
    assert "delete_notebook(" in nav
    assert "on_click=_on_open_search" in nav
    assert "on_click=_on_toggle_library" in nav
    assert "on_click=_on_collapse_nav" in nav
    assert "on_click=_on_expand_nav" in nav
    assert "on_click=_on_close_mobile_nav" in nav
    assert "on_click=_on_new_chat" in nav
    assert "on_click=open_chat_destination" in nav
    assert "on_click=_on_open_delete_chat" in nav
    assert "select_thread(target, should_rerun=False)" in nav
    open_search = nav.split("def _on_open_search", 1)[1].split("\ndef ", 1)[0]
    toggle_library = nav.split("def _on_toggle_library", 1)[1].split("\ndef ", 1)[0]
    collapse_nav = nav.split("def _on_collapse_nav", 1)[1].split("\ndef ", 1)[0]
    expand_nav = nav.split("def _on_expand_nav", 1)[1].split("\ndef ", 1)[0]
    close_mobile = nav.split("def _on_close_mobile_nav", 1)[1].split("\ndef ", 1)[0]
    open_chat = nav.split("def open_chat_destination", 1)[1].split("\ndef ", 1)[0]
    new_chat = nav.split("def _on_new_chat", 1)[1].split("\ndef ", 1)[0]
    open_delete = nav.split("def _on_open_delete_chat", 1)[1].split("\ndef ", 1)[0]
    for callback_body in (
        open_search,
        toggle_library,
        collapse_nav,
        expand_nav,
        close_mobile,
        open_chat,
        new_chat,
        open_delete,
    ):
        assert "rerun_app()" not in callback_body
    assert 'if target == current:' in open_chat
    assert 'toast_course_materials_loading = True' in new_chat
    assert "dismiss_delete_chat_dialog()" in open_search
    assert "dismiss_delete_chat_dialog()" in toggle_library
    assert "dismiss_delete_chat_dialog()" in open_chat
    assert "dismiss_delete_chat_dialog()" in new_chat
    assert "pending_delete_chat_id" in open_delete
    assert "_delete_chat_dialog_dismissed_id" in open_delete
    assert "close_menu_popover" in open_delete
    dismiss_fn = nav.split("def dismiss_delete_chat_dialog", 1)[1].split(
        "\n@st.dialog", 1
    )[0]
    assert "_delete_chat_dialog_dismissed_id" in dismiss_fn
    mount_fn = nav.split("def mount_pending_delete_chat_dialog", 1)[1]
    assert "_delete_chat_dialog_dismissed_id" in mount_fn
    assert "pending == dismissed" in mount_fn
    # Rename apply and delete confirm still remount so titles / transcript stay consistent.
    assert "rerun_app()" in nav
    css = Path("ui/assets/styles/15-nav.css").read_text(encoding="utf-8")
    assert "stIconMaterial" in css
    assert "font-size:0" not in css.split("st-key-nav_recent_")[1].split("st-key-nav_collapsed")[0]
    collapsed = css.split(".st-key-nav_collapsed_actions", 1)[1]
    assert "gap:0 !important" in collapsed
    assert 'display:none !important' in collapsed
    assert "font-size:16px !important" in collapsed
    collapse_btn = css.split('st-key-nav-collapse"]', 1)[1]
    assert "gap:0 !important" in collapse_btn
    assert "align-items:center !important" in collapse_btn
    profile_css = Path("ui/assets/styles/60-profile-topbar.css").read_text(
        encoding="utf-8"
    )
    collapsed_settings = profile_css.split(
        ".st-key-nav_panel:has(.st-key-nav_collapsed_actions)", 1
    )[1]
    assert "font-size:16px !important" in collapsed_settings
    assert "color:var(--cd-text) !important" in collapsed_settings


def test_search_pane_uses_fuzzy_ranking_and_clickable_rows() -> None:
    """Search ranks chats fuzzily; the row itself opens the chat."""
    search = Path("ui/panels/search.py").read_text(encoding="utf-8")
    assert "SequenceMatcher" in search
    assert "_rank_threads" in search
    assert "_FUZZY_THRESHOLD" in search
    assert 'store.list_threads("", None)' in search
    assert "No results found" in search
    assert "Results" in search
    assert "Recent" in search
    assert "on_click=open_chat_destination" in search
    assert "open_chat_destination" in search
    assert 'key=f"search-open-{thread_id}"' in search
    assert '"Open"' not in search
    assert "st.markdown(body" not in search
    assert "select_thread(" not in search
    css = Path("ui/assets/styles/15-nav.css").read_text(encoding="utf-8")
    assert "st-key-search_row_" in css
    assert "white-space:pre-line" in css


def test_column_resize_supports_nav_and_studio_dividers() -> None:
    """Desktop stores three ratios and drags both vertical dividers."""
    resize = Path("ui/layout/column_resize.py").read_text(encoding="utf-8")
    assert "nav_collapsed" in resize
    assert "NAV_COLLAPSED_PX" in resize
    assert "NAV_MIN_PX" in resize
    assert "NAV_MAX_PX" in resize
    assert "_RAIL_WIDTH_PX = 72" in resize
    assert "parsed.length !== 3" in resize
    assert 'kind === "nav"' in resize
    assert 'beginDrag("nav"' in resize
    assert 'beginDrag("studio"' in resize
    assert "Resize navigation" in resize
    assert "Resize Thinking Path" in resize
    assert 'return "nav"' in resize
    assert 'return "center"' in resize
    assert 'return "studio"' in resize
    assert ".st-key-search_panel" in resize
    assert ".st-key-sources_panel" in resize
    assert 'MOBILE_QUERY = "(max-width: 1050px)"' in resize
    assert "setMobile(column, roles[index])" in resize
    assert 'role === "nav" || role === "studio"' in resize
    assert '"min(20.5rem, 88vw)"' in resize
    assert "cd_workspace_column_widths_v4" in resize
    assert "APP_RUN" in resize
    assert "navCollapsed = NAV_COLLAPSED" in resize
    assert "studioCollapsed = STUDIO_COLLAPSED" in resize
    assert '"cd-shell-optimistic-resize"' in resize
    assert "setOptimisticResize(\"nav-collapsed\")" in resize
    assert "applyLayout(found.columns, found.roles, ratios, true" in resize
    assert "applyLayout(found.columns, found.roles, ratios, false" in resize
    assert "function install(authoritative = false)" in resize
    assert "if (authoritative) clearOptimisticStateWhenAuthoritative();" in resize
    assert "if (!install(true))" in resize
    assert "if (install(false) || attempts > 50)" in resize
    assert "if (install(true) || attempts > 50)" not in resize
    assert "reinstall(false)" in resize
    assert "OPTIMISTIC_SHELL_CLASSES" in resize
    assert "function columnIsCollapsed(found, role)" in resize
    assert "const navCollapsed = columnIsCollapsed(found, \"nav\")" in resize
    assert "const studioCollapsed = columnIsCollapsed(found, \"studio\")" in resize
    assert "ratios, true, studioCollapsed" in resize
    assert "ratios, false, studioCollapsed" in resize
    assert "ratios, navCollapsed, true" in resize
    assert "ratios, navCollapsed, false" in resize
    assert "__cdWorkspaceLayoutGeneration" in resize
    assert "__cdWorkspaceLayoutRetryTimer" in resize
    workspace_css = Path("ui/assets/styles/10-workspace.css").read_text(
        encoding="utf-8"
    )
    assert "body.cd-shell-optimistic-resize" in workspace_css
    assert "body.cd-shell-optimistic-resize .cd-col-resize-handle" in workspace_css
    assert "pointer-events:none !important" in workspace_css
    assert "transition:flex-basis 180ms ease" in workspace_css


def test_mobile_library_updates_the_rendered_center_in_the_same_pass() -> None:
    """Changing the mobile destination must not leave one blank render frame."""
    workspace = Path("ui/workspace.py").read_text(encoding="utf-8")
    sources_branch = workspace.split('elif panel == "Sources":', 1)[1].split(
        "else:", 1
    )[0]
    assert 'st.session_state.center_view = "library"' in sources_branch
    assert 'center_view = "library"' in sources_branch


def test_workspace_chrome_uses_on_click_without_extra_rerun() -> None:
    """Drawer/collapse chrome applies flags before render; no second remount."""
    workspace = Path("ui/workspace.py").read_text(encoding="utf-8")
    assert "on_click=_on_open_mobile_nav" in workspace
    assert "on_click=_on_open_mobile_studio" in workspace
    assert "on_click=_on_close_mobile_drawers" in workspace
    assert "on_click=_on_expand_side_panel" in workspace
    assert "on_click=_on_close_mobile_studio" in workspace
    assert "on_click=_on_collapse_studio" in workspace
    assert "on_click=_on_mobile_new_chat" in workspace
    assert "new_notebook(should_rerun=False)" in workspace
    for name in (
        "_on_open_mobile_nav",
        "_on_open_mobile_studio",
        "_on_close_mobile_drawers",
        "_on_expand_side_panel",
        "_on_close_mobile_studio",
        "_on_collapse_studio",
        "_on_mobile_new_chat",
    ):
        body = workspace.split(f"def {name}", 1)[1].split("\ndef ", 1)[0]
        assert "rerun_app()" not in body
    mobile_new = workspace.split("def _on_mobile_new_chat", 1)[1].split("\ndef ", 1)[0]
    assert 'toast_course_materials_loading = True' in mobile_new
    assert "dismiss_delete_chat_dialog()" in mobile_new
    assert "rerun_app" not in workspace
