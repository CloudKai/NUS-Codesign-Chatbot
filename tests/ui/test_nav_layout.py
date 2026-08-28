"""Source contracts for Gemini-style nav rail and Search pane."""

from __future__ import annotations

from pathlib import Path


def test_workspace_column_order_is_nav_center_sources_studio() -> None:
    """Desktop columns are nav | center | sources | studio; Chat still runs first."""
    workspace = Path("ui/workspace.py").read_text(encoding="utf-8")
    assert "nav_column, center_column, source_column, studio_column" in workspace
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
    assert "render_nav_panel" in workspace
    assert "set_library_open" in workspace
    assert "sources_hidden" in workspace


def test_nav_rail_exposes_new_search_library_and_recents_actions() -> None:
    """Recents ⋮ offers Rename and Delete only; no Gemini share/pin/notebook."""
    nav = Path("ui/panels/nav.py").read_text(encoding="utf-8")
    assert 'key="nav-new-chat"' in nav
    assert 'key="nav-search-chats"' in nav
    assert 'key="nav-library"' in nav
    assert "Recents" in nav
    assert "Rename" in nav
    assert "Delete" in nav
    assert "Delete chat?" in nav
    assert "Share conversation" not in nav
    assert "Add to notebook" not in nav
    assert '"Pin"' not in nav
    assert "set_nav_collapsed" in nav
    assert "new_notebook()" in nav
    assert "select_thread(" in nav
    assert "delete_notebook(" in nav


def test_search_pane_uses_substring_list_threads_and_empty_copy() -> None:
    """Search is case-insensitive substring via list_threads, not fuzzy."""
    search = Path("ui/panels/search.py").read_text(encoding="utf-8")
    assert "store.list_threads(needle" in search
    assert "No results found" in search
    assert "Results" in search
    assert "Recent" in search
    assert "<mark>" in search
    assert "store.list_threads(needle" in search
    assert 'center_view = "chat"' in search
    assert "select_thread(" in search


def test_column_resize_hides_library_without_sources_rail() -> None:
    """Library off zeros Sources; nav uses fixed px; studio keeps a rail."""
    resize = Path("ui/layout/column_resize.py").read_text(encoding="utf-8")
    assert "library_open" in resize
    assert "nav_collapsed" in resize
    assert "SOURCES_HIDDEN" in resize
    assert "NAV_EXPANDED_PX" in resize
    assert "NAV_COLLAPSED_PX" in resize
    assert "setHidden" in resize
    assert 'return "nav"' in resize
    assert 'return "center"' in resize
    assert ".st-key-search_panel" in resize
