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
    assert "Delete" in nav
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
    assert "set_nav_collapsed" in nav
    assert "new_notebook()" in nav
    assert "select_thread(" in nav
    assert "delete_notebook(" in nav
    css = Path("ui/assets/styles/15-nav.css").read_text(encoding="utf-8")
    assert "stIconMaterial" in css
    assert "font-size:0" not in css.split("st-key-nav_recent_")[1].split("st-key-nav_collapsed")[0]


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
    assert 'center_view = "chat"' in search
    assert "select_thread(" in search
    assert 'key=f"search-open-{thread_id}"' in search
    assert '"Open"' not in search
    assert "st.markdown(body" not in search
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


def test_mobile_library_updates_the_rendered_center_in_the_same_pass() -> None:
    """Changing the mobile destination must not leave one blank render frame."""
    workspace = Path("ui/workspace.py").read_text(encoding="utf-8")
    sources_branch = workspace.split('elif panel == "Sources":', 1)[1].split(
        "else:", 1
    )[0]
    assert 'st.session_state.center_view = "library"' in sources_branch
    assert 'center_view = "library"' in sources_branch
