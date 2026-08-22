"""Static and helper checks for explicit Streamlit rerun scope helpers."""

from __future__ import annotations

import inspect
from pathlib import Path
from types import SimpleNamespace

import ui.runtime as runtime_module
import ui.sources as sources_module
import ui.studio as studio_module
from ui.panels.chat import _edit_render_plan
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
    assert "uploads_active = any(" in source
    assert "sync_future.done() and not uploads_active" in source
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
        "store.upload_attachments("
    )
    assert send_block.index("set_coach_turn_streaming(True)") < send_block.index(
        "stream_coach_turn_events("
    )
    assert "finally:" in send_block
    assert "pre_api_ms" in send_block
    assert "fragment_to_api_ms" in send_block
    assert "composer_layout_ms" in send_block
    assert "thread_lookup_ms" in send_block
    assert "pending_user_render_ms" in send_block
    assert "chat_scroll_send_ms" in send_block
    assert "thinking_render_ms" in send_block
    assert "request_build_ms" in send_block
    assert "rerun_app()" in send_block
    done_block = send_block.split("if turn is None", 1)[1].split(
        "except CoachTurnStreamError", 1
    )[0]
    assert "rerun_app()" in done_block
    assert "render_message(" not in done_block
    normalized = chat.replace("\r\n", "\n")
    assert "@st.fragment\ndef _render_composer_submit_fragment(" in normalized
    composer_block = chat.split("def _render_composer_submit_fragment(", 1)[1].split(
        "def render_chat_panel(", 1
    )[0]
    assert "st.chat_input(" in composer_block
    assert "handle_prompt(" in composer_block
    assert "sync_composer_layout(" in composer_block
    assert "prompt_accept_ms" in composer_block
    assert "composer_layout_ms" in composer_block
    assert "fragment_spans=" in composer_block
    revise_block = chat.split("def _submit_pending_edit(", 1)[1].split(
        "def _render_composer_submit_fragment(", 1
    )[0]
    assert revise_block.index("set_coach_turn_streaming(True)") < revise_block.index(
        "store.revise_message("
    )
    assert "finally:" in revise_block


def test_edit_send_stays_in_chat_fragment_until_revision_completes() -> None:
    """Edit submission preserves the prefix transcript during the wait."""
    chat = Path("ui/panels/chat.py").read_text(encoding="utf-8")
    edit_block = chat.split(
        'if role == "user" and st.session_state.editing_message == message["id"]:',
        1,
    )[1].split('        if role == "user":', 1)[0]
    send_block = edit_block.split('if send_column.button(', 1)[1].rsplit(
        "            return", 1
    )[0]
    assert "st.session_state.pending_edit" in send_block
    assert "rerun_fragment()" in send_block
    assert "rerun_app()" not in send_block

    composer_block = chat.split("def _render_composer_submit_fragment(", 1)[1].split(
        "def render_chat_panel(", 1
    )[0]
    assert "stop_before_message_id=pending_message_id or None" in composer_block
    assert "_render_inflight_user_prompt(" in composer_block
    assert "list(pending.get(\"attachments\") or [])" in composer_block
    assert '"attachments": [' in edit_block
    assert "inflight_attachment_card_" in chat
    assert "user_edit_attachment_card_" in chat

    revise_block = chat.split("def _submit_pending_edit(", 1)[1].split(
        "def _render_chat_history(", 1
    )[0]
    assert "rerun_app()" in revise_block


def test_edit_render_plan_keeps_only_prefix_for_any_branch_position() -> None:
    """An in-flight edit renders its logical prefix, including first/latest edits."""
    messages = [
        {"id": "u1", "role": "user", "content": "U1"},
        {"id": "a1", "role": "assistant", "content": "A1"},
        {"id": "u2", "role": "user", "content": "U2"},
        {"id": "a2", "role": "assistant", "content": "A2"},
        {"id": "u3", "role": "user", "content": "U3"},
    ]

    prefix, found = _edit_render_plan(messages, "u2")
    assert found is True
    assert [item["id"] for item in prefix] == ["u1", "a1"]

    prefix, found = _edit_render_plan(messages, "u3")
    assert found is True
    assert [item["id"] for item in prefix] == ["u1", "a1", "u2", "a2"]

    prefix, found = _edit_render_plan(messages, "u1")
    assert found is True
    assert prefix == []


def test_edit_render_plan_stale_target_reports_failure_without_blank_fallback() -> None:
    """A missing target is distinguished from a valid first-message empty prefix."""
    messages = [{"id": "u1", "role": "user", "content": "U1"}]
    prefix, found = _edit_render_plan(messages, "missing")
    assert found is False
    assert [item["id"] for item in prefix] == ["u1"]


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
    assert "_render_language_fragment" not in normalized_profile
    assert "@st.fragment\ndef _render_coaching_style_fragment" in normalized_profile
    assert "rerun_app()" not in profile
    profile_render_block = profile.split("def render_profile_menu", 1)[1].split(
        "def inject_profile_leave_helper", 1
    )[0]
    assert "on_change=persist_appearance" in profile_render_block
    assert 'key="profile_coaching_style"' in profile
    assert "_render_language_dropdown" not in profile
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
    assert 'close_menu_popover("profile-language")' not in profile
    assert 'close_menu_popover("source-sort", thread_id)' in sources
    assert 'menu_popover_widget_key("source-sort", thread_id)' in sources
