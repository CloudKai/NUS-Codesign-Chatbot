"""Static and helper checks for explicit Streamlit rerun scope helpers."""

from __future__ import annotations

from pathlib import Path

from ui.sources import (
    _select_all_widget_key,
    _source_selected_widget_key,
)


def test_runtime_exposes_explicit_rerun_helpers_only() -> None:
    source = Path("ui/runtime.py").read_text(encoding="utf-8")
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
    source = Path("ui/sources.py").read_text(encoding="utf-8")
    assert "rerun_fragment()" in source
    assert "on_change=_persist_source_selected" in source
    assert "on_change=_persist_select_all_sources" in source
    # Course-sync remount must stay app-scoped.
    assert source.count("rerun_app()") >= 2
    assert 'on_change="rerun"' not in source


def test_studio_panel_is_fragment_with_scoped_preview_toggles() -> None:
    source = Path("ui/studio.py").read_text(encoding="utf-8")
    assert "@st.fragment\ndef render_studio_panel()" in source.replace("\r\n", "\n")
    assert "rerun_fragment()" in source
    assert "_select_journey_stage" in source
    # Stage selection / transition confirmation remain full-app.
    select_block = source.split("def _select_journey_stage", 1)[1].split(
        "def render_journey_track", 1
    )[0]
    assert "rerun_app()" in select_block
