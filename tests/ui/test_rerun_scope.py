"""Static and helper checks for explicit Streamlit rerun scope helpers."""

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
    assert "def coach_turn_is_streaming()" in source
    assert "def set_coach_turn_streaming(" in source
    assert "def rerun()" not in source
    assert 'st.rerun(scope="fragment")' in source


def test_coach_turn_is_streaming_reads_session_flag(monkeypatch) -> None:
    """Fragments consult the session flag, not a second Streamlit widget."""
    fake_state: dict[str, object] = {}
    monkeypatch.setattr(
        runtime_module,
        "st",
        SimpleNamespace(session_state=fake_state),
    )
    runtime_module._streaming_session_ids.clear()
    assert runtime_module.coach_turn_is_streaming() is False
    fake_state["_coach_turn_streaming"] = True
    assert runtime_module.coach_turn_is_streaming() is True
    fake_state["_coach_turn_streaming"] = False
    assert runtime_module.coach_turn_is_streaming() is False


def test_coach_turn_is_streaming_reads_in_process_session_id(monkeypatch) -> None:
    """A fragment tick without in-flight session_state still sees this session."""
    fake_state: dict[str, object] = {}
    monkeypatch.setattr(
        runtime_module,
        "st",
        SimpleNamespace(session_state=fake_state),
    )
    monkeypatch.setattr(
        runtime_module,
        "get_script_run_ctx",
        lambda suppress_warning=False: SimpleNamespace(session_id="sess-1"),
    )
    runtime_module._streaming_session_ids.clear()
    try:
        assert runtime_module.coach_turn_is_streaming() is False
        runtime_module.set_coach_turn_streaming(True)
        fake_state.clear()
        assert runtime_module.coach_turn_is_streaming() is True
        runtime_module.set_coach_turn_streaming(False)
        assert runtime_module.coach_turn_is_streaming() is False
    finally:
        runtime_module._streaming_session_ids.clear()


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
    assert "coach_turn_is_streaming()" in source
    assert "if coach_turn_is_streaming() or sync_future.done():" in source
    polling = source.split("def _render_sources_panel_polling", 1)[1].split(
        "def _render_sources_panel_body", 1
    )[0]
    assert "if coach_turn_is_streaming():" in polling
    assert polling.index("if coach_turn_is_streaming():") < polling.index(
        "rerun_app()"
    )
    stable = source.split("def _render_sources_panel_stable", 1)[1].split(
        "def _render_sources_panel_polling", 1
    )[0]
    assert "if coach_turn_is_streaming():" in stable
    assert stable.index("if coach_turn_is_streaming():") < stable.index("rerun_app()")


def test_studio_deep_review_poll_skips_app_rerun_while_streaming() -> None:
    """A finishing Deep Review job must not remount the app during a coach stream."""
    source = Path(inspect.getfile(studio_module)).read_text(encoding="utf-8")
    assert "coach_turn_is_streaming()" in source
    stable = source.split("def _render_deep_review_stable", 1)[1].split(
        "def _render_deep_review_polling", 1
    )[0]
    assert "if not coach_turn_is_streaming():" in stable
    assert stable.index("if not coach_turn_is_streaming():") < stable.index(
        "rerun_app()"
    )
    polling = source.split("def _render_deep_review_polling", 1)[1].split(
        "def _review_fingerprint", 1
    )[0]
    assert "if not coach_turn_is_streaming():" in polling
    assert polling.index("if not coach_turn_is_streaming():") < polling.index(
        "rerun_app()"
    )


def test_chat_marks_streaming_around_coach_send_and_revise() -> None:
    """handle_prompt and revise set the flag before the blocking call and clear it."""
    chat = Path("ui/panels/chat.py").read_text(encoding="utf-8")
    assert 'st.session_state["_coach_turn_streaming"] = True' not in chat
    assert chat.count("set_coach_turn_streaming(True)") == 2
    assert chat.count("set_coach_turn_streaming(False)") >= 2
    send_block = chat.split("def handle_prompt(", 1)[1].split(
        "def _confirm_edit_earlier_message_dialog", 1
    )[0]
    assert send_block.index("set_coach_turn_streaming(True)") < send_block.index(
        "store.upload_sources("
    )
    assert send_block.index("set_coach_turn_streaming(True)") < send_block.index(
        "stream_coach_turn_events("
    )
    assert "finally:" in send_block
    assert "pre_api_ms" in send_block
    normalized = chat.replace("\r\n", "\n")
    assert "@st.fragment\ndef _render_composer_submit_fragment(" in normalized
    composer_block = chat.split("def _render_composer_submit_fragment(", 1)[1].split(
        "def render_chat_panel(", 1
    )[0]
    assert "st.chat_input(" in composer_block
    assert "handle_prompt(" in composer_block
    revise_block = chat.split("def _submit_pending_edit(", 1)[1].split(
        "def _render_composer_submit_fragment(", 1
    )[0]
    assert revise_block.index("set_coach_turn_streaming(True)") < revise_block.index(
        "store.revise_message("
    )
    assert "finally:" in revise_block


def test_workspace_renders_chat_before_studio() -> None:
    """Send must not wait on Journey/Deep Review before FastAPI starts."""
    source = Path("ui/workspace.py").read_text(encoding="utf-8")
    chat_idx = source.index("render_chat_panel(")
    studio_idx = source.index("render_studio_panel()")
    sources_idx = source.index("render_sources_panel()")
    assert chat_idx < studio_idx < sources_idx


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


def test_topbar_guidance_and_profile_use_correct_rerun_scope() -> None:
    topbar = Path("ui/topbar.py").read_text(encoding="utf-8")
    profile = Path("ui/profile.py").read_text(encoding="utf-8")
    assert "_render_guidance_fragment" not in topbar
    assert "_render_profile_fragment" not in topbar
    normalized_profile = profile.replace("\r\n", "\n")
    assert "@st.fragment\ndef _render_display_name_fragment" in normalized_profile
    assert "@st.fragment\ndef _render_language_fragment" in normalized_profile
    assert "@st.fragment\ndef _render_coaching_style_fragment" in normalized_profile
    assert "rerun_fragment()" in profile
    assert "rerun_app()" not in profile
    profile_render_block = profile.split("def render_profile_menu", 1)[1].split(
        "def _render_language_dropdown", 1
    )[0]
    assert "on_change=persist_appearance" in profile_render_block
    assert 'key="profile_coaching_style"' in profile
    language_block = profile.split("def _render_language_dropdown", 1)[1]
    assert "persist_response_language()" in language_block
    assert "rerun_fragment()" in language_block
    display_block = profile.split("def persist_display_name", 1)[1].split(
        "def _sync_profile_avatar_initial", 1
    )[0]
    assert "rerun_fragment()" not in display_block
    coaching_block = profile.split("def _render_coaching_style_fragment", 1)[1].split(
        "def render_profile_menu", 1
    )[0]
    assert "save_journey(journey)" in profile
    assert "rerun_app()" not in coaching_block


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
    assert 'close_menu_popover("profile-language")' in profile
    assert 'menu_popover_widget_key("profile-language")' in profile
    assert 'close_menu_popover("source-sort", thread_id)' in sources
    assert 'menu_popover_widget_key("source-sort", thread_id)' in sources
