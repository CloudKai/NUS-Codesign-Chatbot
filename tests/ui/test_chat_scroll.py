"""Source contracts for chat transcript scroll policy and compact errors."""

from __future__ import annotations

from pathlib import Path

from ui.layout.chat_scroll import NEAR_BOTTOM_PX


def test_chat_scroll_helper_uses_near_bottom_gating() -> None:
    """Send snaps once; settle does not chase; manual scroll can stop follow."""
    helper = Path("ui/layout/chat_scroll.py").read_text(encoding="utf-8")
    assert "NEAR_BOTTOM_PX = 120" in helper
    assert NEAR_BOTTOM_PX == 120
    assert 'querySelector(".st-key-chat_log")' in helper
    assert 'behavior === "smooth"' in helper
    assert "state().follow = false" in helper
    assert 'MODE === "send"' in helper
    assert 'MODE === "settle"' in helper
    assert "if (root && !isNearBottom(root)) state().follow = false" in helper
    assert "snapToBottom" in helper
    assert "root.scrollTop = root.scrollHeight - root.clientHeight" in helper
    assert "setInterval" not in helper
    assert "MutationObserver" not in helper
    assert helper.count("requestAnimationFrame") <= 4


def test_inflight_wrapper_has_no_card_chrome() -> None:
    """Occupied inflight is a transparent slot, not a bordered card."""
    workspace = Path("ui/assets/styles/10-workspace.css").read_text(encoding="utf-8")
    chat_css = Path("ui/assets/styles/30-chat.css").read_text(encoding="utf-8")
    occupied = workspace.split(
        ".st-key-chat_inflight:has(.cd-user-bubble-text)", 1
    )[1].split("}", 1)[0]
    assert "background:transparent" in occupied
    assert "overflow:visible" in occupied
    assert "min-height:min-content" not in occupied
    assert "box-shadow:none" in chat_css
    assert ".cd-inflight-error" in chat_css


def test_inflight_error_is_compact_and_keeps_safe_copy() -> None:
    """Turn failures stay in-row; category mapping is unchanged."""
    chat = Path("ui/panels/chat.py").read_text(encoding="utf-8")
    assert "def _render_inflight_error(" in chat
    assert "cd-inflight-error" in chat
    assert "student_coach_error_message(error.category" in chat
    assert 'student_coach_error_message("unavailable")' in chat
    assert "_INFLIGHT_ERROR_CAPTION" in chat
    assert "Reload once before resubmitting" in chat
    handle = chat.split("def handle_prompt(", 1)[1].split(
        "def _confirm_edit_earlier_message_dialog", 1
    )[0]
    assert handle.count("_render_inflight_error(") == 2
    assert 'sync_chat_scroll(mode="settle")' in handle
    assert "Reload the notebook before resubmitting" not in handle
    # Attachment failures still use st.error; stream failures do not.
    stream_fail = handle.split("except CoachTurnStreamError as error:", 1)[1]
    assert "st.error(" not in stream_fail


def test_fragment_submit_path_still_owns_inflight() -> None:
    """Send still runs inside the composer fragment against the inflight slot."""
    chat = Path("ui/panels/chat.py").read_text(encoding="utf-8")
    normalized = chat.replace("\r\n", "\n")
    assert 'st.container(key="chat_transcript")' in chat
    assert 'st.container(key="chat_log")' in chat
    assert "@st.fragment\ndef _render_composer_submit_fragment(" in normalized
    composer_block = chat.split("def _render_composer_submit_fragment(", 1)[1].split(
        "def render_chat_panel(", 1
    )[0]
    assert "st.chat_input(" in composer_block
    assert "handle_prompt(" in composer_block
    assert 'st.container(key="chat_inflight")' in composer_block
    assert 'sync_chat_scroll(mode="reconcile")' not in composer_block
    workspace = Path("ui/workspace.py").read_text(encoding="utf-8")
    assert 'sync_chat_scroll(mode="reconcile")' in workspace
    assert "from ui.layout.chat_scroll import sync_chat_scroll" in workspace
    send_block = chat.split("def handle_prompt(", 1)[1].split(
        "def _confirm_edit_earlier_message_dialog", 1
    )[0]
    assert "fragment_to_api_ms" in send_block
    assert "pre_api_ms" in send_block
    assert 'sync_chat_scroll(mode="send")' in send_block
    assert "chat_scroll_send_ms" in send_block
    assert "stream_coach_turn_events(" in send_block
    assert "rerun_app()" in send_block


def test_chat_feed_owns_history_and_inflight_with_composer_as_footer() -> None:
    """The fragment keeps submitted work in one scroll region and the input outside it."""
    chat = Path("ui/panels/chat.py").read_text(encoding="utf-8")
    fragment = chat.split("def _render_composer_submit_fragment(", 1)[1].split(
        "def render_chat_panel(", 1
    )[0]
    assert 'st.container(key="chat_feed")' in fragment
    assert 'st.container(key="chat_log")' in fragment
    assert 'st.container(key="chat_inflight")' in fragment
    assert fragment.index('st.container(key="chat_feed")') < fragment.index(
        'st.container(key="chat_log")'
    )
    assert fragment.index('st.container(key="chat_feed")') < fragment.index(
        'st.container(key="chat_inflight")'
    )
    assert fragment.index('st.container(key="chat_feed")') < fragment.index(
        'st.container(key="chat_composer")'
    )
    assert "stop_before_message_id" in fragment
    assert "_render_inflight_user_prompt(pending_prompt" in fragment
    assert "rerun_fragment()" in chat
    workspace = Path("ui/assets/styles/10-workspace.css").read_text(encoding="utf-8")
    feed_rule = workspace.split(".st-key-chat_feed,", 1)[1].split("}", 1)[0]
    assert "overflow-y:auto" in feed_rule
    assert ".st-key-chat_feed .st-key-chat_log" in workspace
