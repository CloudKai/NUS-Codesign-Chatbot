"""Source contracts for chat transcript scroll policy and compact errors."""

from __future__ import annotations

from pathlib import Path

from ui.layout.chat_scroll import NEAR_BOTTOM_PX


def test_chat_scroll_helper_uses_near_bottom_gating() -> None:
    """Send snaps bottom; reply remount pins coach top; manual scroll stops follow."""
    helper = Path("ui/layout/chat_scroll.py").read_text(encoding="utf-8")
    assert "NEAR_BOTTOM_PX = 120" in helper
    assert "FOLLOW_SNAP_FRAMES = 8" in helper
    assert NEAR_BOTTOM_PX == 120
    assert 'querySelector(".st-key-chat_log")' not in helper
    assert "Element.prototype" not in helper
    assert "scrollIntoView" not in helper
    assert "scrollTo(" not in helper
    assert "api().follow = isNearBottom(root)" in helper
    assert "awaitingReplyReveal" in helper
    assert "shouldRevealReply" in helper
    assert "snapping" in helper
    assert "keepSnappingToBottom" in helper
    assert "keepRevealingCoachReply" in helper
    assert "revealLatestCoachReply" in helper
    assert "latestCoachReply" in helper
    assert (
        '.st-key-chat_log [data-testid="stChatMessage"]'
        ':has([aria-label="Chat message from assistant"])'
    ) in helper
    assert "replyRect.top - rootRect.top" in helper
    assert 'MODE === "send"' in helper
    assert 'MODE === "settle"' in helper
    assert '"reply"' in helper
    assert "snapToBottom" in helper
    assert "root.scrollTop = root.scrollHeight - root.clientHeight" in helper
    # Send uses bottom snap and arms reply reveal; remount pins coach top.
    assert (
        'MODE === "send"' in helper
        and "keepSnappingToBottom(FOLLOW_SNAP_FRAMES)" in helper
    )
    assert "api().awaitingReplyReveal = true" in helper
    assert "keepRevealingCoachReply(FOLLOW_SNAP_FRAMES)" in helper
    assert "shouldRevealReply()" in helper
    assert "ensureScrollDownAfterRemount" in helper
    send_branch = helper.split('MODE === "send"', 1)[1].split(
        'MODE === "settle"', 1
    )[0]
    assert "keepSnappingToBottom" in send_branch
    assert "awaitingReplyReveal = true" in send_branch
    assert "keepRevealingCoachReply" not in send_branch
    # Reply arms reveal like Send (stage-move remount never went through Send).
    reply_branch = helper.split('MODE === "reply"', 1)[1].split(
        "// reconcile:", 1
    )[0]
    assert "awaitingReplyReveal = true" in reply_branch
    assert "api().follow = true" in reply_branch
    assert "keepRevealingCoachReply(FOLLOW_SNAP_FRAMES)" in reply_branch
    assert "ensureScrollDownAfterRemount" in reply_branch
    assert "shouldRevealReply()" not in reply_branch
    # Reconcile stays gated so ordinary paints do not steal the viewport.
    reconcile_tail = helper.split("// reconcile:", 1)[1].split(
        "})();", 1
    )[0]
    assert "shouldRevealReply()" in reconcile_tail
    assert "keepRevealingCoachReply(FOLLOW_SNAP_FRAMES)" in reconcile_tail
    assert 'querySelector(".st-key-chat_feed")' in helper
    scroll_root_fn = helper.split("function scrollRoot()", 1)[1].split(
        "function chatPanel()", 1
    )[0]
    assert 'querySelector(".st-key-chat_feed")' in scroll_root_fn
    assert 'querySelector(".st-key-chat_panel")' not in scroll_root_fn
    assert "function chatPanel()" in helper
    assert 'querySelector(".st-key-chat_panel")' in helper
    assert "cd-chat-scroll-down" in helper
    assert "updateScrollDownButton" in helper
    assert "cd-chat-scroll-down-icon" in helper
    assert "doc.body.appendChild(button)" in helper
    assert "panel.appendChild(button)" not in helper
    assert "composer.appendChild(button)" not in helper
    assert "position:fixed" in Path("ui/assets/styles/30-chat.css").read_text(
        encoding="utf-8"
    ).split(".cd-chat-scroll-down {", 1)[1].split("}", 1)[0]
    assert "onScrollDownClick" in helper
    assert "listenersBound" in helper
    assert 'closest("#cd-chat-scroll-down")' in helper
    assert "button.addEventListener(\"click\"" not in helper
    assert "AbortController" not in helper
    assert "snapFollow" not in helper
    assert "LISTENER_VERSION" not in helper
    assert "cd-chat-scroll-away" not in helper
    assert "keyboard_arrow_down" not in helper
    assert "setInterval" not in helper
    assert "MutationObserver" not in helper
    # One schedule() wrapper owns requestAnimationFrame.
    assert helper.count("requestAnimationFrame") == 1
    assert "function schedule(fn)" in helper
    # Remount must not clear awaitingReplyReveal via viewport sync.
    sync_fn = helper.split("function syncFollowFromViewport()", 1)[1].split(
        "function onScrollDownClick", 1
    )[0]
    assert "awaitingReplyReveal" in sync_fn
    assert "awaitingReplyReveal = false" not in sync_fn
    mark_fn = helper.split("function markUserScroll(", 1)[1].split(
        "function onFeedScroll(", 1
    )[0]
    assert "awaitingReplyReveal = false" in mark_fn


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
    assert "chat_follow_bottom" in workspace
    assert "chat_reveal_coach_reply" in workspace
    assert 'sync_chat_scroll(mode="reply")' in workspace
    assert "pending_mobile_panel" in workspace
    assert 'sync_chat_scroll(mode="send")' in workspace
    assert "chat_scroll_after_stage_select" not in workspace
    assert "switched_to_chat" not in workspace
    assert "from ui.layout.chat_scroll import sync_chat_scroll" in workspace
    assert "mount_awaiting_coach_turn_recovery()" in workspace
    chat = Path("ui/panels/chat.py").read_text(encoding="utf-8")
    assert 'chat_reveal_coach_reply = True' in chat
    # Recovery poller stays outside chat_panel so run_every does not strip
    # the JS scroll-down control appended to that panel node.
    workspace_chat = workspace.split("with chat_column:", 1)[1].split(
        "with studio_column:", 1
    )[0]
    assert workspace_chat.rindex('key="chat_panel"') < workspace_chat.index(
        "mount_awaiting_coach_turn_recovery()"
    )
    assert workspace_chat.rindex("sync_chat_scroll(") < workspace_chat.index(
        "mount_awaiting_coach_turn_recovery()"
    )
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
    assert "_render_inflight_user_prompt(" in fragment
    assert "list(pending.get(\"attachments\") or [])" in fragment
    assert "rerun_fragment()" in chat
    workspace = Path("ui/assets/styles/10-workspace.css").read_text(encoding="utf-8")
    feed_rule = workspace.split(".st-key-chat_feed,", 1)[1].split("}", 1)[0]
    assert "overflow-y:auto" in feed_rule
    assert "height:0" in feed_rule
    assert "max-height:100%" in feed_rule
    assert ".st-key-chat_feed > div" not in workspace
    legacy_selector = (
        '.st-key-chat_panel [data-testid="stLayoutWrapper"]:has(> .st-key-chat_log)'
        ':not(:has(> .st-key-chat_inflight))'
        ':not(:has(> [data-testid="stElementContainer"].st-key-chat_inflight))'
    )
    override_selector = (
        '.st-key-chat_panel .st-key-chat_feed > [data-testid="stLayoutWrapper"]'
        ':has(> .st-key-chat_log)'
        ':not(:has(> .st-key-chat_inflight))'
        ':not(:has(> [data-testid="stElementContainer"].st-key-chat_inflight))'
    )
    override_element_container_selector = (
        '.st-key-chat_panel .st-key-chat_feed > [data-testid="stLayoutWrapper"]'
        ':has(> [data-testid="stElementContainer"].st-key-chat_log)'
        ':not(:has(> .st-key-chat_inflight))'
        ':not(:has(> [data-testid="stElementContainer"].st-key-chat_inflight))'
    )
    assert legacy_selector in workspace
    assert override_selector in workspace
    assert override_element_container_selector in workspace
    legacy = workspace.index(legacy_selector)
    override = workspace.index(override_selector)
    assert override > legacy
    override_block = workspace[override:].split("}", 1)[0]
    assert "flex:0 0 auto" in override_block
    assert "overflow:visible" in override_block
    assert ".st-key-chat_feed .st-key-chat_log" in workspace


def test_message_attachments_render_as_compact_authorized_file_cards() -> None:
    """Persisted turn attachments use a compact card and existing viewer path."""
    chat = Path("ui/panels/chat.py").read_text(encoding="utf-8")
    styles = Path("ui/assets/styles/30-chat.css").read_text(encoding="utf-8")
    assert "message_attachment_card_" in chat
    assert "_attachment_kind_label(attachment)" in chat
    assert "_attachment_button_label(attachment)" in chat
    assert "source_viewer_dialog(attachment_id)" in chat
    assert "Open attachment ·" not in chat
    assert '[class*="st-key-message_attachment_card_"]' in styles
    assert '[class*="st-key-user_edit_attachment_card_"]' in styles
    assert '[class*="st-key-inflight_attachment_card_"]' in styles
    assert "text-overflow:ellipsis" in styles


def test_narrow_chat_feed_owns_touch_scroll_without_changing_textarea_ownership() -> None:
    """Tablet/mobile feed scrolling does not steal edit or composer scrolling."""
    responsive = Path("ui/assets/styles/90-responsive.css").read_text(encoding="utf-8")
    mobile_tablet = responsive.split("@media (max-width:1050px)", 1)[1].split(
        "/* Mid-width desktop", 1
    )[0]
    feed_rule = mobile_tablet.split(".st-key-chat_feed,", 1)[1].split("}", 1)[0]
    bubble_rule = mobile_tablet.split(".cd-user-bubble-text", 1)[1].split("}", 1)[0]

    assert "touch-action:pan-y" in feed_rule
    assert "-webkit-overflow-scrolling:touch" in feed_rule
    assert "overscroll-behavior-y:contain" in feed_rule
    assert "max-height:none !important" in bubble_rule
    assert "overflow-y:visible !important" in bubble_rule
    assert "overflow-y:auto" not in bubble_rule
    assert "attachment" not in mobile_tablet.lower()
    assert "citation" not in mobile_tablet.lower()

    chat = Path("ui/assets/styles/30-chat.css").read_text(encoding="utf-8")
    desktop_bubble = chat.split(".cd-user-bubble-text {", 1)[1].split("}", 1)[0]
    edit_textarea = chat.split(
        '[class*="st-key-user_message_edit_"] textarea {', 1
    )[1].split("}", 1)[0]
    composer_textarea = chat.split(
        ".st-key-chat_composer [data-testid=\"stChatInput\"] textarea,", 1
    )[1].split("}", 1)[0]
    assert "max-height:var(--cd-user-bubble-max-height)" in desktop_bubble
    assert "overflow-y:auto" in desktop_bubble
    assert "max-height:var(--cd-user-bubble-max-height) !important" in edit_textarea
    assert "overflow-y:auto !important" in edit_textarea
    assert "max-height:calc(1em * 1.45 * 5) !important" in composer_textarea
    assert "overflow-y:auto !important" in composer_textarea

    assert ".cd-chat-scroll-down" in chat
    assert "opacity:0" in chat.split(".cd-chat-scroll-down {", 1)[1].split("}", 1)[0]
    assert "pointer-events:none" in chat.split(".cd-chat-scroll-down {", 1)[1].split(
        "}", 1
    )[0]
    assert "display:none" not in chat.split(".cd-chat-scroll-down {", 1)[1].split(
        "}", 1
    )[0]
    assert "bottom:calc(100% + .35rem)" not in chat
    assert ".cd-chat-scroll-down.cd-chat-scroll-down-visible" in chat
    assert "opacity:1" in chat.split(
        ".cd-chat-scroll-down.cd-chat-scroll-down-visible {", 1
    )[1].split("}", 1)[0]
    workspace = Path("ui/assets/styles/10-workspace.css").read_text(encoding="utf-8")
    transcript_rule = workspace.split(
        ".st-key-chat_transcript,\n    [data-testid=\"stElementContainer\"].st-key-chat_transcript",
        1,
    )[1].split("}", 1)[0]
    assert "gap:0 !important" in transcript_rule
    assert "cd-chat-scroll-away" not in workspace
    attachment_cards = chat.split(
        '[class*="st-key-message_attachment_card_"],', 1
    )[1].split("}", 1)[0]
    assert "overflow:hidden !important" in attachment_cards
    chat_panel = Path("ui/panels/chat.py").read_text(encoding="utf-8")
    assert "citation_" in chat_panel
    assert "render_citations(message, visible_source_ids=visible_source_ids)" in chat_panel
    assert "citation" not in bubble_rule.lower()
