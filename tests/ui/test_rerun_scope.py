"""UI checks for explicit Streamlit rerun-scope helpers."""

from __future__ import annotations

import inspect
from pathlib import Path
from types import SimpleNamespace

import ui.runtime as runtime_module
import ui.sources as sources_module
import ui.studio as studio_module
from ui.sources import (
    _select_all_widget_key,
    _source_selected_widget_key,
)


def test_runtime_exposes_explicit_rerun_helpers_only() -> None:
    source = Path(inspect.getfile(runtime_module)).read_text(encoding="utf-8")
    assert "def rerun_app()" in source
    assert "def rerun_fragment()" in source
    assert "def rerun()" not in source
    assert 'st.rerun(scope="fragment")' in source


def test_ui_modules_do_not_import_generic_rerun() -> None:
    ui_root = Path("ui")
    offenders: list[str] = []
    for path in ui_root.rglob("*.py"):
        text = path.read_text(encoding="utf-8")
        if "from ui.runtime import rerun," in text or "from ui.runtime import rerun\n" in text:
            offenders.append(str(path))
        if "from ui.runtime import rerun " in text:
            offenders.append(str(path))
    assert offenders == []


def test_sources_selection_keys_are_stable() -> None:
    assert _source_selected_widget_key("abc-123") == "source-selected-abc-123"
    assert _select_all_widget_key("thread-1", 3) == "all-sources-thread-1-3"
    # Count changes remount select-all; selected-count is not part of the key.
    assert _select_all_widget_key("thread-1", 2) != _select_all_widget_key(
        "thread-1", 3
    )


def test_sources_local_paths_use_fragment_rerun() -> None:
    source = Path(inspect.getfile(sources_module)).read_text(encoding="utf-8")
    assert "rerun_fragment()" in source
    assert "on_change=_persist_source_selected" in source
    assert "on_change=_persist_select_all_sources" in source
    # Course-sync remount must stay app-scoped.
    assert source.count("rerun_app()") >= 2
    assert 'on_change="rerun"' not in source


def test_studio_panel_is_fragment_with_scoped_preview_toggles() -> None:
    source = Path(inspect.getfile(studio_module)).read_text(encoding="utf-8")
    assert "@st.fragment\ndef render_studio_panel()" in source.replace("\r\n", "\n")
    assert "rerun_fragment()" in source
    assert "_select_journey_stage" in source
    # Stage selection / transition confirmation remain full-app.
    select_block = source.split("def _select_journey_stage", 1)[1].split(
        "def render_journey_track", 1
    )[0]
    assert "rerun_app()" in select_block


def test_profile_coaching_style_and_preferences_use_correct_rerun_scope() -> None:
    profile = Path("ui/profile.py").read_text(encoding="utf-8")
    assert "@st.fragment\ndef _render_coaching_style_fragment()" not in (
        profile.replace("\r\n", "\n")
    )
    guidance_block = profile.split("def _render_coaching_style_fragment", 1)[1].split(
        "def render_topbar", 1
    )[0].split("def render_profile_menu", 1)[0]
    assert "on_change=_persist_coaching_style" in guidance_block
    persist_block = profile.split("def _select_coaching_style", 1)[1].split(
        "@st.fragment", 1
    )[0]
    assert "rerun_app()" not in persist_block
    assert "_coaching_style_app_rerun_pending" not in profile
    normalized_profile = profile.replace("\r\n", "\n")
    assert "@st.fragment\ndef _render_display_name_fragment" in normalized_profile
    profile_render_block = profile.split("def render_profile_menu", 1)[1].split(
        "def inject_profile_leave_helper", 1
    )[0]
    assert "on_change=persist_appearance" in profile_render_block
    assert "_render_language_fragment" not in profile
    assert "persist_response_language" not in profile
    display_block = profile.split("def persist_display_name", 1)[1].split(
        "def _sync_profile_avatar_initial", 1
    )[0]
    assert "rerun_fragment()" not in display_block


def test_menu_popover_key_bumps_to_remount_closed(monkeypatch) -> None:
    import ui.menu_popovers as menu_popovers

    fake_state: dict[str, object] = {}
    monkeypatch.setattr(
        menu_popovers,
        "st",
        SimpleNamespace(session_state=fake_state),
    )
    first = menu_popovers.menu_popover_widget_key("source-sort", "thread-a")
    menu_popovers.close_menu_popover("source-sort", "thread-a")
    second = menu_popovers.menu_popover_widget_key("source-sort", "thread-a")
    assert first != second
    assert first.endswith("-0")
    assert second.endswith("-1")


def test_select_menus_close_after_pick() -> None:
    profile = Path("ui/profile.py").read_text(encoding="utf-8")
    sources = Path(inspect.getfile(sources_module)).read_text(encoding="utf-8")
    assert "profile-language" not in profile
    assert 'close_menu_popover("source-sort", thread_id)' in sources
    assert 'menu_popover_widget_key("source-sort", thread_id)' in sources
