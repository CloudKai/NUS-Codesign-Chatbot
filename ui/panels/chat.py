"""Discussion panel, message rendering, and composer handling.

Chat scrolling is owned by ``.st-key-chat_feed`` plus
``ui.layout.chat_scroll.sync_chat_scroll``; do not write completed turns
into ``chat_log`` from the composer fragment.
"""

from __future__ import annotations

import base64
import html
import mimetypes
import time
import uuid
from pathlib import Path
from typing import Any

import streamlit as st
import streamlit.components.v1 as components
import streamlit.components.v2 as components_v2
from streamlit.errors import StreamlitAPIException

from backend.domain import CoachRequest, CoachTurn
from backend.learning.hmw import hmw_scaffold_available
from backend.settings import settings
from backend.specialists.review_orchestration import (
    COUNTER_SETTINGS_KEY,
    explicit_deep_review_available,
    parse_coaching_turns_since_deep_review,
)
from backend.student_journey import (
    DEFAULT_RESPONSE_DETAIL,
    DEFAULT_STAGE,
    STAGE_BY_ID,
    advanced_stage_response,
    concise_coach_response,
    normalize_journey,
    personalized_stage_questions,
)
from backend.coaching.workflow_navigation import manual_stage_selection_target

from ui.coach_welcome import (
    COACH_WELCOME_KIND,
    COACH_WELCOME_MARKDOWN,
    render_hmw_scaffold_if_needed,
    transcript_hmw_render_plan,
)
from ui.constants import DEFAULT_APPEARANCE
from ui.layout.chat_scroll import sync_chat_scroll
from ui.layout.composer_layout import sync_composer_layout
from ui.layout.user_message_edit_layout import (
    USER_MESSAGE_EDIT_HEIGHT_PX,
    sync_user_message_edit_layout,
)
from ui.runtime import (
    coach_turn_is_streaming,
    log_ui_timing,
    rerun_app,
    rerun_fragment,
    set_coach_turn_streaming,
    store,
    stream_coach_turn_events,
)
from ui.retry_keys import get_retry_key, remove_retry_key
from ui.session import (
    apply_manual_stage_move,
    awaiting_coach_turn_for_thread,
    awaiting_coach_turn_timed_out,
    clear_awaiting_coach_turn,
    clear_stage_move_notice,
    locked_stage_move_notice,
    set_awaiting_coach_turn,
    set_stage_move_notice,
    reset_chat_history_window,
)
from ui.sources import source_viewer_dialog


_HISTORY_PAGE_SIZE = 6
_HISTORY_TOP_THRESHOLD_PX = 48
_HISTORY_ERROR_TTL_SECONDS = 8.0
_HISTORY_PAGER_HTML = '<span class="cd-history-pager" aria-hidden="true"></span>'
_HISTORY_PAGER_CSS = ".cd-history-pager{display:block;width:1px;height:0;overflow:hidden}"
_HISTORY_PAGER_JS = r"""
export default function(component) {
  const { data, setTriggerValue } = component;
  const doc = window.parent?.document || document;
  const win = window.parent || window;
  const registryKey = '__cdHistoryPagerController';
  const prior = win[registryKey];
  if (prior && typeof prior.cleanup === 'function') prior.cleanup();
  const feed = doc.querySelector('.st-key-chat_feed');
  const hasMore = !!(data && data.has_more && data.cursor);
  const topThreshold = 48;
  let armed = true;
  let touchY = null;
  let pointerY = null;
  let disposed = false;

  const isBusy = () => !!(data && data.busy) ||
    !!(win.__cdChatScroll && win.__cdChatScroll.pagingLocked);
  const canRequest = () => !disposed && hasMore && !isBusy() && feed &&
    feed.clientHeight > 0 && feed.scrollTop <= topThreshold && armed;
  const captureAnchor = (reason) => {
    if (!feed) return;
    const feedRect = feed.getBoundingClientRect();
    const markers = Array.from(feed.querySelectorAll('[data-cd-message-id]'));
    const marker = markers.find((node) => node.getBoundingClientRect().bottom >= feedRect.top);
    win.__cdChatScrollPrependAnchor = {
      top: Number(feed.scrollTop || 0),
      height: Number(feed.scrollHeight || 0),
      messageId: marker ? String(marker.getAttribute('data-cd-message-id') || '') : '',
      offset: marker ? Number(marker.getBoundingClientRect().top - feedRect.top) : 0,
      reason: String(reason || 'intent')
    };
  };
  const request = (reason) => {
    if (!canRequest()) return;
    armed = false;
    captureAnchor(reason);
    setTriggerValue('older', {
      thread_id: String(data.thread_id || ''),
      cursor: String(data.cursor || ''),
      reason: String(reason || 'intent')
    });
  };
  const onScroll = () => {
    if (!feed) return;
    if (feed.scrollTop > topThreshold + 8) armed = true;
  };
  const onWheel = (event) => {
    if (event && Number(event.deltaY) < 0) request('wheel');
  };
  const onTouchStart = (event) => {
    touchY = event.touches && event.touches.length ? event.touches[0].clientY : null;
  };
  const onTouchMove = (event) => {
    if (touchY == null) return;
    const y = event.touches && event.touches.length ? event.touches[0].clientY : null;
    if (y != null && y - touchY > 10) request('touch');
  };
  const onPointerDown = (event) => {
    if (event && event.isPrimary === false) return;
    if (event && event.button != null && Number(event.button) !== 0) return;
    pointerY = Number.isFinite(event.clientY) ? event.clientY : null;
  };
  const onPointerMove = (event) => {
    if (pointerY == null) return;
    // A mouse pointer must still be held down. Touch/pen pointer events carry
    // a non-zero buttons value while the contact is active as well.
    if (event && event.buttons != null && Number(event.buttons) === 0) return;
    if (event.clientY - pointerY > 10) request('pointer');
  };
  const onTouchEnd = () => { touchY = null; };
  const onPointerUp = () => { pointerY = null; };
  const onKeyDown = (event) => {
    const target = event && event.target;
    if (target && (target.closest('textarea,input,[contenteditable="true"]') ||
      target.closest('.st-key-chat_composer'))) return;
    if (event.key === 'ArrowUp' || event.key === 'PageUp' || event.key === 'Home') {
      request('keyboard');
    }
  };
  const onFallbackClick = (event) => {
    const target = event && event.target;
    const button = target && target.closest ? target.closest('button') : null;
    if (button && /^Load 6 earlier messages/.test(String(button.textContent || ''))) {
      captureAnchor('fallback');
    }
  };
  const cleanup = () => {
    disposed = true;
    if (feed) {
      feed.removeEventListener('scroll', onScroll);
      feed.removeEventListener('wheel', onWheel);
      feed.removeEventListener('touchstart', onTouchStart);
      feed.removeEventListener('touchmove', onTouchMove);
      feed.removeEventListener('touchend', onTouchEnd);
      feed.removeEventListener('touchcancel', onTouchEnd);
      feed.removeEventListener('pointerdown', onPointerDown);
      feed.removeEventListener('pointermove', onPointerMove);
      feed.removeEventListener('pointerup', onPointerUp);
      feed.removeEventListener('pointercancel', onPointerUp);
    }
    doc.removeEventListener('keydown', onKeyDown, true);
    doc.removeEventListener('click', onFallbackClick, true);
    if (win[registryKey] && win[registryKey].cleanup === cleanup) delete win[registryKey];
  };
  win[registryKey] = { cleanup };
  if (feed) {
    feed.addEventListener('scroll', onScroll, { passive: true });
    feed.addEventListener('wheel', onWheel, { passive: true });
    feed.addEventListener('touchstart', onTouchStart, { passive: true });
    feed.addEventListener('touchmove', onTouchMove, { passive: true });
    feed.addEventListener('touchend', onTouchEnd, { passive: true });
    feed.addEventListener('touchcancel', onTouchEnd, { passive: true });
    feed.addEventListener('pointerdown', onPointerDown, { passive: true });
    feed.addEventListener('pointermove', onPointerMove, { passive: true });
    feed.addEventListener('pointerup', onPointerUp, { passive: true });
    feed.addEventListener('pointercancel', onPointerUp, { passive: true });
  }
  doc.addEventListener('keydown', onKeyDown, true);
  doc.addEventListener('click', onFallbackClick, true);
}
"""

try:
    _history_pager_component = components_v2.component(
        "cd_history_pager",
        html=_HISTORY_PAGER_HTML,
        css=_HISTORY_PAGER_CSS,
        js=_HISTORY_PAGER_JS,
        isolate_styles=False,
    )
except Exception:  # pragma: no cover - old Streamlit/test import fallback
    _history_pager_component = None


def _duration_ms(started: float) -> float:
    """Return milliseconds elapsed since a ``perf_counter`` mark."""
    return round(max(0.0, (time.perf_counter() - started) * 1000.0), 1)


def _attachment_kind_label(attachment: dict[str, Any]) -> str:
    """Return a compact, student-facing type label for one attachment."""
    mime = str(
        attachment.get("mime_type")
        or attachment.get("mime")
        or attachment.get("type")
        or ""
    ).lower()
    kind = str(attachment.get("kind") or "").lower()
    title = str(attachment.get("title") or attachment.get("name") or "").lower()
    if mime == "application/pdf" or title.endswith(".pdf"):
        return "PDF"
    if kind == "image" or mime.startswith("image/"):
        return "Image"
    if mime.startswith("text/") or title.endswith((".txt", ".md", ".csv")):
        return "Text"
    if "word" in mime or title.endswith((".doc", ".docx")):
        return "Document"
    if "sheet" in mime or title.endswith((".xls", ".xlsx")):
        return "Spreadsheet"
    if "presentation" in mime or title.endswith((".ppt", ".pptx")):
        return "Presentation"
    return "File"


def _attachment_icon(attachment: dict[str, Any]) -> str:
    """Return a Material icon name appropriate for one attachment."""
    return {
        "PDF": ":material/picture_as_pdf:",
        "Image": ":material/image:",
        "Document": ":material/description:",
        "Spreadsheet": ":material/table_chart:",
        "Presentation": ":material/slideshow:",
        "Text": ":material/article:",
    }.get(_attachment_kind_label(attachment), ":material/attach_file:")


def _attachment_size_label(attachment: dict[str, Any]) -> str:
    """Return a compact byte-size label without exposing storage details."""
    try:
        size = max(0, int(attachment.get("size") or 0))
    except (TypeError, ValueError):
        size = 0
    if size < 1024:
        return f"{size} B"
    if size < 1024 * 1024:
        return f"{size / 1024:.1f} KB"
    return f"{size / (1024 * 1024):.1f} MB"


def _attachment_button_label(attachment: dict[str, Any]) -> str:
    """Return a concise attachment label for the compact open control."""
    title = str(attachment.get("title") or attachment.get("name") or "Attachment").strip()
    return f"{title} · {_attachment_kind_label(attachment)} · {_attachment_size_label(attachment)}"


class CoachTurnStreamError(RuntimeError):
    """Raised when a streamed coaching turn ends with a structured error event."""

    def __init__(
        self,
        detail: str,
        *,
        status: Any = None,
        category: str = "",
    ) -> None:
        super().__init__(detail)
        self.detail = str(detail)
        self.status = status
        self.category = str(category or "").strip()


def student_coach_error_message(category: str = "", *, status: Any = None) -> str:
    """Return student-safe coaching-failure copy for one error category.

    Args:
        category: Stable API category such as ``safety_blocked``.
        status: Optional HTTP status from the stream error event.

    Returns:
        Copy that does not blame the launcher, name the provider, or expose
        AWS or prompt internals.
    """
    normalized = str(category or "").strip().lower()
    try:
        status_code = int(status) if status is not None else None
    except (TypeError, ValueError):
        status_code = None
    if normalized == "safety_blocked":
        return (
            "This turn was blocked by a safety check. Rephrase your message "
            "and try again. Your notebook was not updated."
        )
    if normalized in {"structured_output_failure", "malformed"}:
        return "The coach couldn't complete that reply. Please try again."
    if normalized == "throttled" or status_code == 429:
        return "The coach is busy right now. Wait a moment and try again."
    if normalized == "timeout":
        return "The coach took too long to reply. Try again."
    return "Coaching is temporarily unavailable. Try again in a moment."


# Revise can race an interrupted stream: FastAPI keeps the notebook lease on a
# worker thread after Streamlit stops reading NDJSON. Brief retries bridge that gap.
_REVISE_BUSY_ATTEMPTS = 6
_REVISE_BUSY_SLEEP_SECONDS = 2.0

_EDIT_WAIT_FOR_COACH_MESSAGE = (
    "The coach is still finishing your previous message. "
    "Wait for that reply, then edit again."
)

_EDIT_BUSY_RETRY_MESSAGE = (
    "The coach was still finishing another reply for this notebook. "
    "Your draft is preserved — wait a few seconds, then click Send again."
)

_EDIT_GENERIC_FAILURE_MESSAGE = (
    "Could not finish this edit. Your draft is preserved — click Send "
    "again to retry the same revision attempt without creating another "
    "conversation branch. If the server already applied the revision, "
    "retry resumes the replacement coach reply."
)


def _http_status_from_exception(error: BaseException) -> int | None:
    """Return an HTTP status from an API client exception, when present."""
    response = getattr(error, "response", None)
    if response is None:
        return None
    try:
        return int(getattr(response, "status_code", None))
    except (TypeError, ValueError):
        return None


def _exception_is_coach_busy(error: BaseException) -> bool:
    """Return True when *error* is a notebook-busy / rate-limit conflict."""
    status = _http_status_from_exception(error)
    if status == 429:
        return True
    detail = str(error or "").casefold()
    return "too many requests" in detail or "only one active coaching" in detail


def _coach_turn_busy() -> bool:
    """Return True when a send/revise is streaming or awaiting server completion."""
    return coach_turn_is_streaming() or awaiting_coach_turn_for_thread() is not None


def _edit_failure_message(error: BaseException) -> str:
    """Return student-safe copy for a failed bubble-edit revise call."""
    if _exception_is_coach_busy(error):
        return _EDIT_BUSY_RETRY_MESSAGE
    return _EDIT_GENERIC_FAILURE_MESSAGE


_INFLIGHT_ERROR_CAPTION = (
    "Reload once before resubmitting; the completed turn may already be present."
)


def _render_inflight_error(title: str) -> None:
    """Render a compact turn-failure row without a full-width alert card.

    Args:
        title: Student-safe message from ``student_coach_error_message``.
    """
    escaped_title = html.escape(title)
    escaped_caption = html.escape(_INFLIGHT_ERROR_CAPTION)
    st.markdown(
        '<div class="cd-inflight-error" role="alert">'
        f'<p class="cd-inflight-error-title">{escaped_title}</p>'
        f'<p class="cd-inflight-error-caption">{escaped_caption}</p>'
        "</div>",
        unsafe_allow_html=True,
    )


def render_media(raw_paths: list[str]) -> None:
    for raw_path in raw_paths:
        path = Path(raw_path).resolve()
        workspace_root = settings.workspaces_dir.resolve()
        files_root = settings.files_dir.resolve()
        if not path.is_file() or not (workspace_root in path.parents or files_root in path.parents):
            continue
        mime = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
        if mime.startswith("image/") or path.suffix.lower() == ".svg":
            st.image(str(path), use_container_width=True)
            st.download_button(
                "Download image",
                data=path.read_bytes(),
                file_name=path.name,
                mime=mime,
                key=f"media-{path}-{path.stat().st_mtime_ns}",
                type="tertiary",
            )
        elif mime.startswith("audio/"):
            st.audio(path.read_bytes(), format=mime)


def render_citations(
    message: dict[str, Any],
    *,
    visible_source_ids: set[str] | None = None,
) -> None:
    """Render cited sources: one or two inline, three or more in a dropdown."""
    references = (message.get("metadata") or {}).get("source_refs") or []
    allowed_ids = visible_source_ids
    if allowed_ids is None:
        allowed_ids = {
            str(source.get("id") or "") for source in store.list_sources(st.session_state.thread_id)
        }
    valid_references = [
        reference for reference in references if str(reference.get("id") or "") in allowed_ids
    ]
    if not valid_references:
        return

    def render_reference(reference: dict[str, Any]) -> None:
        """Render a source action that opens the corresponding source viewer."""
        label = str(reference.get("label") or "Source")
        title = str(reference.get("title") or "Untitled source")
        if st.button(
            f"[{label}] {title}",
            key=f"citation_{message['id']}_{reference['id']}",
            type="secondary",
        ):
            source_viewer_dialog(str(reference["id"]))

    if len(valid_references) < 2:
        for reference in valid_references:
            render_reference(reference)
        return

    with st.expander(f"Sources used ({len(valid_references)})", expanded=False):
        for reference in valid_references:
            render_reference(reference)


def _render_copy_control(text: str) -> None:
    """Render a Copy control whose click stays in-iframe (clipboard gesture works).

    Appearance is passed from Streamlit session because the iframe cannot use
    parent ``--cd-*`` variables. Colors match the Edit control in
    ``ui/assets/styles/`` (muted icon on a soft surface wash).
    """
    encoded = base64.b64encode(text.encode("utf-8")).decode("ascii")
    appearance = str(st.session_state.get("appearance") or DEFAULT_APPEARANCE)
    # Mirror [class*="st-key-user_message_actions_"] button tokens.
    if appearance == "Dark":
        icon = "#9AA8B5"
        icon_hover = "#F2F5F7"
        bg = "rgba(23, 28, 34, 0.35)"
        bg_hover = "rgba(42, 52, 62, 0.55)"
        copied = "#5EEAD4"
    else:
        icon = "#5B6B7C"
        icon_hover = "#15202B"
        bg = "rgba(255, 255, 255, 0.35)"
        bg_hover = "rgba(213, 220, 227, 0.55)"
        copied = "#0F766E"
    system_dark = ""
    if appearance == "System":
        system_dark = """
  @media (prefers-color-scheme: dark) {
    button {
      color: #9AA8B5;
      background: rgba(23, 28, 34, 0.35);
    }
    button:hover {
      color: #F2F5F7;
      background: rgba(42, 52, 62, 0.55);
    }
    button.copied { color: #5EEAD4; }
  }
"""
    components.html(
        f"""
<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8" />
<style>
  html, body {{
    margin: 0;
    padding: 0;
    width: 100%;
    height: 100%;
    display: flex;
    align-items: center;
    justify-content: center;
    background: transparent;
    overflow: hidden;
  }}
  button {{
    display: inline-flex;
    align-items: center;
    justify-content: center;
    box-sizing: border-box;
    width: 1.7rem;
    height: 1.7rem;
    margin: 0;
    padding: 0;
    border: 0;
    border-radius: .45rem;
    color: {icon};
    background: {bg};
    opacity: .9;
    cursor: pointer;
    line-height: 0;
  }}
  button:hover {{
    color: {icon_hover};
    background: {bg_hover};
    opacity: 1;
  }}
  button.copied {{
    color: {copied};
  }}
  svg {{
    display: block;
    width: .82rem;
    height: .82rem;
    margin: 0;
    flex: 0 0 auto;
    fill: currentColor;
  }}
{system_dark}
</style>
</head>
<body>
<button id="copy-btn" type="button" title="Copy" aria-label="Copy">
  <svg viewBox="0 0 24 24" aria-hidden="true">
    <path d="M16 1H4c-1.1 0-2 .9-2 2v14h2V3h12V1zm3 4H8c-1.1 0-2 .9-2 2v14c0 1.1.9 2 2 2h11c1.1 0 2-.9 2-2V7c0-1.1-.9-2-2-2zm0 16H8V7h11v14z"/>
  </svg>
</button>
<script>
(() => {{
  const btn = document.getElementById("copy-btn");
  const encoded = "{encoded}";
  const text = new TextDecoder("utf-8").decode(
    Uint8Array.from(atob(encoded), (ch) => ch.charCodeAt(0))
  );
  btn.addEventListener("click", async () => {{
    let ok = false;
    try {{
      await navigator.clipboard.writeText(text);
      ok = true;
    }} catch (err) {{
      const ta = document.createElement("textarea");
      ta.value = text;
      ta.setAttribute("readonly", "");
      ta.style.position = "fixed";
      ta.style.left = "-9999px";
      document.body.appendChild(ta);
      ta.focus();
      ta.select();
      try {{ ok = document.execCommand("copy"); }} catch (e2) {{ ok = false; }}
      ta.remove();
    }}
    if (ok) {{
      btn.classList.add("copied");
      btn.title = "Copied";
      window.setTimeout(() => {{
        btn.classList.remove("copied");
        btn.title = "Copy";
      }}, 1200);
    }}
  }});
}})();
</script>
</body>
</html>
        """,
        height=28,
        width=28,
    )


def _begin_latest_edit_message(message_id: str) -> None:
    """Enter the latest user-turn editor during the current fragment rerun.

    Args:
        message_id: Persisted user-message identifier selected for editing.

    Side effects:
        Sets the in-bubble editor session state. Streamlit's widget callback
        then reruns only the owning chat fragment. Refuses while a coach turn
        is still streaming or awaiting server completion so Edit cannot race
        the notebook concurrency lease.
    """
    selected_id = str(message_id or "").strip()
    if not selected_id:
        return
    if _coach_turn_busy():
        st.session_state.edit_error_message = _EDIT_WAIT_FOR_COACH_MESSAGE
        return
    st.session_state.editing_message = selected_id
    st.session_state.edit_confirm_message_id = None


def render_message(
    message: dict[str, Any],
    *,
    visible_source_ids: set[str] | None = None,
    latest_user_message_id: str | None = None,
    allow_edit: bool = True,
) -> None:
    role = message["role"]
    with st.chat_message(
        role,
        avatar=(":material/auto_awesome:" if role == "assistant" else ":material/person:"),
    ):
        st.markdown(
            f'<span data-cd-message-id="{html.escape(str(message.get("id") or ""), quote=True)}" '
            'aria-hidden="true" '
            'style="display:block;width:0;height:0;position:relative;overflow:visible;'
            'pointer-events:none"></span>',
            unsafe_allow_html=True,
        )
        metadata = message.get("metadata") or {}
        if role == "user" and st.session_state.editing_message == message["id"]:
            safe_id = message["id"].replace("-", "_")
            with st.container(key=f"user_message_edit_{safe_id}"):
                edit_key = f"edit-text-{message['id']}"
                # Prefer a restored draft already in session state (failed revise
                # retry). Only pass ``value`` when the widget key is unset.
                text_area_kwargs: dict[str, Any] = {
                    "key": edit_key,
                    "label_visibility": "collapsed",
                    "height": USER_MESSAGE_EDIT_HEIGHT_PX,
                }
                if edit_key not in st.session_state:
                    text_area_kwargs["value"] = message["content"]
                revised = st.text_area("Edit message", **text_area_kwargs)
                edit_attachments = [
                    item
                    for item in (metadata.get("attachments") or [])
                    if isinstance(item, dict)
                ]
                for attachment in edit_attachments:
                    attachment_id = str(attachment.get("id") or "").strip()
                    if not attachment_id:
                        continue
                    with st.container(
                        key=f"user_edit_attachment_card_{safe_id}_{attachment_id.replace('-', '_')}"
                    ):
                        label = _attachment_button_label(attachment)
                        if st.button(
                            label,
                            key=f"open-edit-attachment-{message['id']}-{attachment_id}",
                            icon=_attachment_icon(attachment),
                            help=f"Open {label}",
                            type="tertiary",
                            width="content",
                        ):
                            source_viewer_dialog(attachment_id)
                sync_user_message_edit_layout()
                with st.container(key=f"user_message_edit_actions_{safe_id}"):
                    cancel_column, send_column = st.columns(2, gap="small")
                    if cancel_column.button(
                        "Cancel",
                        key=f"cancel-{message['id']}",
                        type="secondary",
                    ):
                        st.session_state.editing_message = None
                        st.session_state.pop(edit_key, None)
                        rerun_fragment()
                    if send_column.button(
                        "Send",
                        key=f"save-{message['id']}",
                        type="primary",
                    ):
                        if not revised.strip():
                            st.error("Enter a message before resending.")
                            return
                        if _coach_turn_busy():
                            st.session_state.edit_error_message = (
                                _EDIT_WAIT_FOR_COACH_MESSAGE
                            )
                            _rerun_edit_fragment()
                            return
                        draft = revised.strip()
                        thread_id = st.session_state.thread_id
                        idempotency_key = get_retry_key(
                            st.session_state,
                            thread_id=thread_id,
                            stage=f"revise:{message['id']}",
                            prompt=draft,
                        )
                        # Keep only the bounded prefix captured by the render
                        # that owned this editor.  A fragment rerun can receive
                        # stale/empty function arguments while the revise call
                        # is in flight; the prefix keeps that transient view
                        # visible without becoming a second transcript store.
                        snapshot = st.session_state.get("_chat_edit_prefix_snapshot")
                        if (
                            isinstance(snapshot, dict)
                            and str(snapshot.get("message_id") or "") == message["id"]
                        ):
                            prefix_messages = list(snapshot.get("prefix") or [])
                            target_found = bool(snapshot.get("target_found"))
                        else:
                            prefix_messages, target_found = _edit_render_plan(
                                None,
                                message["id"],
                            )
                        st.session_state.pending_edit = {
                            "message_id": message["id"],
                            "prompt": draft,
                            "idempotency_key": idempotency_key,
                            # Keep the authoritative descriptor with the one
                            # transient revised row while the suffix is hidden.
                            "attachments": [
                                item
                                for item in (metadata.get("attachments") or [])
                                if isinstance(item, dict)
                            ],
                            "render_prefix": prefix_messages,
                            "render_target_found": target_found,
                        }
                        st.session_state.editing_message = None
                        # Stay inside the chat fragment while the replacement
                        # turn is running so the prefix history and in-flight
                        # edit remain visible. _submit_pending_edit performs
                        # the full app rerun only after authoritative success.
                        rerun_fragment()
            return
        if role == "user":
            safe_id = message["id"].replace("-", "_")
            content = str(message["content"])
            # Pending-edit inflight uses a distinct container key. Cancel-only
            # reclaims the edit-actions slot so Streamlit does not remount Send.
            row_key = (
                f"user_message_pending_{safe_id}"
                if not allow_edit
                else f"user_message_row_{safe_id}"
            )
            with st.container(key=row_key):
                # Own the bubble padding in HTML we control (Streamlit chat chrome
                # keeps resetting padding on stChatMessage).
                escaped = html.escape(content).replace("\n", "<br />")
                st.markdown(
                    f'<div class="cd-user-bubble-text">{escaped}</div>',
                    unsafe_allow_html=True,
                )
                attachments = metadata.get("attachments") or []
                if attachments:
                    attachment_items = [item for item in attachments if isinstance(item, dict)]
                    for attachment in attachment_items:
                        attachment_id = str(attachment.get("id") or "")
                        if not attachment_id:
                            continue
                        with st.container(
                            key=f"message_attachment_card_{safe_id}_{attachment_id.replace('-', '_')}"
                        ):
                            label = _attachment_button_label(attachment)
                            if st.button(
                                label,
                                key=f"open-attachment-{message['id']}-{attachment_id}",
                                icon=_attachment_icon(attachment),
                                help=f"Open {label}",
                                type="tertiary",
                                width="content",
                            ):
                                source_viewer_dialog(attachment_id)
                if not allow_edit:
                    # Reclaim the edit-actions slot with Cancel only so Streamlit
                    # does not remount the previous Cancel/Send pair into this
                    # pending bubble. Cancel aborts the revise with no change.
                    with st.container(key=f"user_message_edit_actions_{safe_id}"):
                        if st.button(
                            "Cancel",
                            key=f"cancel-{message['id']}",
                            type="secondary",
                            use_container_width=True,
                        ):
                            _abort_pending_edit_noop()
                    return
                with st.container(key=f"user_message_actions_{safe_id}"):
                    _, copy_column, edit_column = st.columns(
                        [0.76, 0.12, 0.12],
                        gap="small",
                    )
                    with copy_column:
                        _render_copy_control(content)
                    edit_kwargs: dict[str, Any] = {
                        "icon": ":material/edit:",
                        "key": f"edit-{message['id']}",
                        "help": "Edit",
                        "type": "tertiary",
                    }
                    if latest_user_message_id == message["id"]:
                        # The button is rendered inside the composer fragment.
                        # Its callback runs before that fragment rerenders, so
                        # editing the latest turn does not remount the whole
                        # workspace.
                        edit_column.button(
                            "",
                            **edit_kwargs,
                            on_click=_begin_latest_edit_message,
                            args=(message["id"],),
                        )
                    elif edit_column.button("", **edit_kwargs):
                        # Earlier turns retain the app-scoped confirmation
                        # dialog, whose owner is render_chat_panel().
                        st.session_state.edit_confirm_message_id = message["id"]
                        rerun_app()
            return

        st.markdown(
            '<div class="message-meta coach-welcome">Coach</div>'
            if metadata.get("kind") == COACH_WELCOME_KIND
            else '<div class="message-meta">Coach</div>',
            unsafe_allow_html=True,
        )
        display_content = str(message["content"])
        if metadata.get("kind") == COACH_WELCOME_KIND:
            # Existing notebooks may contain the older persisted welcome copy.
            # Render the current shared welcome text without mutating history.
            display_content = COACH_WELCOME_MARKDOWN
            title, _, body = display_content.partition("\n\n")
            title_text = title.removeprefix("**").removesuffix("**").strip() or title
            st.markdown(
                f'<div class="coach-welcome-title">{html.escape(title_text)}</div>',
                unsafe_allow_html=True,
            )
            if body.strip():
                st.markdown(body.strip())
            return
        auto_advanced_to = str(metadata.get("auto_advanced_to") or "")
        if auto_advanced_to in STAGE_BY_ID and "**Thinking Path:**" in display_content:
            assessment = metadata.get("assessment") or {}
            questions = assessment.get("guidance_questions") or list(
                personalized_stage_questions(
                    auto_advanced_to,
                    str(assessment.get("contribution_summary") or display_content),
                    has_course_sources=bool(metadata.get("source_ids")),
                )
            )
            display_content = advanced_stage_response(
                display_content,
                str(metadata.get("thinking_stage") or DEFAULT_STAGE),
                auto_advanced_to,
                questions,
            )
        st.markdown(concise_coach_response(display_content))
        render_citations(message, visible_source_ids=visible_source_ids)
        web_sources = metadata.get("sources") or []
        if web_sources:
            with st.expander(f"Web sources ({len(web_sources)})"):
                for source in web_sources:
                    title = source.get("title") or source.get("url")
                    st.markdown(f"- [{title}]({source.get('url')})")
        render_media(metadata.get("artifacts") or [])


def normalize_composer_value(value: Any) -> tuple[str, list[Any]]:
    if value is None:
        return "", []
    if isinstance(value, str):
        return value.strip(), []
    prompt = str(getattr(value, "text", "") or "").strip()
    uploads = list(getattr(value, "files", []) or [])
    if not prompt and uploads:
        prompt = "Help me understand the source material I just added."
    return prompt, uploads


def assistant_message_from_turn(
    turn: CoachTurn,
    *,
    thinking_stage: str,
    message_id: str,
) -> dict[str, Any]:
    """Project a validated ``CoachTurn`` into the chat-message render shape.

    The ``done`` payload is authoritative server output. This mapping only
    copies fields the chat renderer already understands; it does not invent
    transcript rows.

    Args:
        turn: Validated coaching result from the stream ``done`` event.
        thinking_stage: Stage to show on the assistant bubble metadata.
        message_id: Stable id for citation widget keys in this script run.

    Returns:
        A message dict compatible with ``render_message``.
    """
    citations = list(turn.assessment.citations or [])
    source_refs = [
        {
            "id": citation.source_id,
            "label": citation.label,
            "title": citation.title,
        }
        for citation in citations
    ]
    metadata: dict[str, Any] = {
        "thinking_stage": thinking_stage,
        "assessment": turn.assessment.model_dump(mode="json"),
        "source_refs": source_refs,
        "source_ids": [citation.source_id for citation in citations],
        "workflow": "langgraph",
    }
    if turn.auto_advanced_to:
        metadata["auto_advanced_to"] = turn.auto_advanced_to
    if turn.pending_transition is not None:
        metadata["pending_transition_id"] = turn.pending_transition.id
        metadata["proposed_stage"] = turn.pending_transition.to_stage
        metadata["from_stage"] = turn.pending_transition.from_stage
        metadata["decision_status"] = "pending"
    return {
        "id": message_id,
        "role": "assistant",
        "content": turn.response_text,
        "metadata": metadata,
    }


def _deep_review_counter(metadata: dict[str, Any]) -> int:
    """Return the persisted Deep Review coaching-turn counter."""
    return parse_coaching_turns_since_deep_review(metadata.get(COUNTER_SETTINGS_KEY))


def _deep_review_is_available(metadata: dict[str, Any]) -> bool:
    """Return whether notebook metadata currently unlocks Deep Review."""
    journey = normalize_journey(metadata.get("learning_journey"))
    return explicit_deep_review_available(
        completed_stages=journey.get("completed_stages") or [],
    )


def apply_completed_turn_to_session(
    turn: CoachTurn,
    *,
    thread_id: str,
    pre_stage: str,
    pre_deep_review_available: bool,
    pre_deep_review_counter: int,
) -> bool:
    """Update session journey from the completed turn and decide a studio rerun.

    Args:
        turn: Validated ``done`` payload.
        thread_id: Active notebook id.
        pre_stage: Thinking Path stage captured before the stream started.
        pre_deep_review_available: Deep Review entitlement before the stream.
        pre_deep_review_counter: Persisted coaching-turn counter before the stream.

    Returns:
        True when Thinking Path, pending Next, or Deep Review progress changed.
        Callers always remount after a successful persist; the flag remains
        for tests and session journey updates.
    """
    store.forget_turn_reads(thread_id)
    reset_chat_history_window(thread_id)
    updated_thread = store.get_thread(thread_id) or {}
    updated_meta = dict(updated_thread.get("metadata") or {})
    updated_journey = normalize_journey(updated_meta.get("learning_journey"))
    if turn.auto_advanced_to:
        updated_journey["current_stage"] = turn.auto_advanced_to
        completed = list(updated_journey.get("completed_stages") or [])
        if pre_stage not in completed and pre_stage != turn.auto_advanced_to:
            updated_journey["completed_stages"] = [*completed, pre_stage]
        updated_journey = normalize_journey(updated_journey)
    st.session_state.learning_journey = updated_journey
    st.session_state.response_detail = updated_journey["response_detail"]
    post_available = _deep_review_is_available(updated_meta)
    post_counter = _deep_review_counter(updated_meta)
    return bool(
        turn.auto_advanced_to
        or turn.pending_transition is not None
        or updated_journey["current_stage"] != pre_stage
        or post_available != pre_deep_review_available
        or post_counter != pre_deep_review_counter
    )


def _awaiting_turn_has_assistant_reply(
    messages: list[dict[str, Any]],
    *,
    baseline_message_count: int,
    total_count: int | None = None,
) -> bool:
    """Return True when persisted history advanced with a new assistant row."""
    if total_count is not None and int(total_count) <= int(baseline_message_count or 0):
        return False
    rows = [message for message in messages if isinstance(message, dict)]
    # A bounded newest page is sufficient during recovery: any newly persisted
    # coach reply is necessarily among the newest rows.
    start = 0 if total_count is not None else max(0, int(baseline_message_count or 0))
    for message in rows[start:]:
        if str(message.get("role") or "").strip().lower() != "assistant":
            continue
        if str(message.get("content") or "").strip():
            return True
    return False


def _sync_session_journey_from_thread(thread_id: str) -> None:
    """Refresh session journey fields from the authoritative notebook row."""
    updated_thread = store.get_thread(thread_id) or {}
    updated_meta = dict(updated_thread.get("metadata") or {})
    updated_journey = normalize_journey(updated_meta.get("learning_journey"))
    st.session_state.learning_journey = updated_journey
    st.session_state.response_detail = updated_journey["response_detail"]


def _abandon_awaiting_coach_turn(*, message: str) -> None:
    """Clear a stuck awaiting lock and remount so the composer unlocks."""
    clear_awaiting_coach_turn()
    st.session_state.edit_error_message = message
    st.session_state.composer_nonce = int(
        st.session_state.get("composer_nonce") or 0
    ) + 1
    rerun_app()


def _try_complete_awaiting_coach_turn() -> bool:
    """Clear the awaiting marker once the persisted assistant reply exists.

    Returns:
        True when the marker was cleared and ``rerun_app()`` was requested so
        the caller should stop rendering recovery chrome.
    """
    pending = awaiting_coach_turn_for_thread()
    if pending is None or coach_turn_is_streaming():
        return False
    thread_id = str(pending.get("thread_id") or "").strip()
    if not thread_id:
        clear_awaiting_coach_turn()
        return False
    if awaiting_coach_turn_timed_out(pending):
        _abandon_awaiting_coach_turn(
            message=(
                "The coach reply did not arrive after leaving Chat. "
                "Send again if it is still missing."
            )
        )
        return True
    store.forget_turn_reads(thread_id)
    page = store.get_message_page(thread_id, limit=6)
    messages = page.messages if hasattr(page, "messages") else (page or {}).get("messages", [])
    total_count = (
        int(page.total_count)
        if hasattr(page, "total_count")
        else int((page or {}).get("total_count", len(messages)))
    )
    baseline = int(pending.get("baseline_message_count") or 0)
    if not _awaiting_turn_has_assistant_reply(
        messages, baseline_message_count=baseline, total_count=total_count
    ):
        return False
    _sync_session_journey_from_thread(thread_id)
    reset_chat_history_window(thread_id)
    clear_awaiting_coach_turn()
    st.session_state.composer_nonce = int(
        st.session_state.get("composer_nonce") or 0
    ) + 1
    st.session_state.chat_reveal_coach_reply = True
    rerun_app()
    return True


def _clear_stale_streaming_for_awaiting_recovery() -> None:
    """Clear a stuck streaming flag after Chat remount tore down the send UI.

    Parent ``render_chat_panel`` only runs on a full script remount. While
    ``handle_prompt`` holds the composer fragment, the parent body does not
    re-execute, so clearing here cannot race an in-flight send. A stuck
    ``_coach_turn_streaming`` would otherwise skip the recovery poller and
    leave the composer disabled forever.
    """
    if awaiting_coach_turn_for_thread() is None:
        return
    if not coach_turn_is_streaming():
        return
    set_coach_turn_streaming(False)


@st.fragment(run_every="2s")
def _recover_awaiting_coach_turn_fragment() -> None:
    """Poll for a persisted reply after Chat remount interrupted the stream UI.

    Mount via ``mount_awaiting_coach_turn_recovery`` outside ``chat_panel``.
    Nested ``run_every`` inside the composer fragment is unreliable, and
    mounting under ``.st-key-chat_panel`` remounts that block every tick and
    strips the JS-appended scroll-down control.
    """
    if awaiting_coach_turn_for_thread() is None:
        return
    if coach_turn_is_streaming():
        return
    _try_complete_awaiting_coach_turn()


def mount_awaiting_coach_turn_recovery() -> None:
    """Register the awaiting-turn poller outside ``.st-key-chat_panel``.

    Call from the workspace column on every paint so Streamlit keeps the
    ``run_every`` timer registered even while idle. Idle ticks no-op. Keep
    this outside the chat panel so fragment remounts do not churn panel DOM.
    """
    _recover_awaiting_coach_turn_fragment()


def _render_awaiting_coach_recovery() -> None:
    """Show the pending student bubble while a remounted turn is recovering.

    The finishing status and Stop control live in the composer so they stay
    visible next to the locked input (native chat_input Stop is unavailable
    once the composer is disabled for awaiting).
    """
    pending = awaiting_coach_turn_for_thread()
    if pending is None or coach_turn_is_streaming():
        return
    # Complete immediately when the user returns and the reply is already saved.
    if _try_complete_awaiting_coach_turn():
        return
    prompt = str(pending.get("prompt") or "").strip()
    if prompt:
        _render_inflight_user_prompt(prompt, [])


def _render_awaiting_composer_controls() -> None:
    """Render finishing status + Stop in the composer while awaiting recovery."""
    pending = awaiting_coach_turn_for_thread()
    if pending is None or coach_turn_is_streaming():
        return
    st.status(
        "Coach is finishing…",
        expanded=False,
        type="compact",
    )
    if st.button(
        "Stop waiting",
        key="abandon_awaiting_coach_turn",
        type="secondary",
        icon=":material/stop_circle:",
        use_container_width=True,
    ):
        _abandon_awaiting_coach_turn(
            message=(
                "Stopped waiting for the coach reply. "
                "Send again if it is still missing."
            )
        )


def _render_inflight_user_prompt(prompt: str, uploads: list[Any]) -> None:
    """Paint the in-flight student prompt with history bubble markup.

    The pending row has no persisted message id, so it omits edit/copy
    actions. Before storage, uploads are local file objects; after storage,
    sanitized attachment descriptors retain their authorized source IDs so
    the current turn can display and reopen them.
    """
    with st.chat_message("user", avatar=":material/person:"):
        escaped = html.escape(prompt).replace("\n", "<br />")
        with st.container(key="inflight_user_message_row"):
            st.markdown(
                f'<div class="cd-user-bubble-text">{escaped}</div>',
                unsafe_allow_html=True,
            )
            for index, upload in enumerate(uploads):
                if isinstance(upload, dict):
                    attachment_id = str(upload.get("id") or "").strip()
                    if not attachment_id:
                        continue
                    with st.container(key=f"inflight_attachment_card_{attachment_id.replace('-', '_')}"):
                        label = _attachment_button_label(upload)
                        if st.button(
                            label,
                            key=f"open-inflight-attachment-{attachment_id}",
                            icon=_attachment_icon(upload),
                            help=f"Open {label}",
                            type="tertiary",
                            width="content",
                        ):
                            source_viewer_dialog(attachment_id)
                else:
                    name = str(getattr(upload, "name", "Attachment") or "Attachment")
                    st.caption(("Attached · " if index == 0 else "") + name)


def _edit_render_plan(
    messages: list[dict[str, Any]] | tuple[dict[str, Any], ...] | None,
    message_id: str,
) -> tuple[list[dict[str, Any]], bool]:
    """Return the active transcript prefix for one in-flight edit.

    The prefix is intentionally a transient render value only.  The persisted
    transcript remains authoritative; this helper merely prevents a fragment
    rerun from replacing the visible branch with an empty feed while revise is
    running. While the in-bubble editor is open, callers use this prefix for
    snapshots; pending-edit loading then appends the draft row via
    ``_pending_edit_history_messages``.

    Args:
        messages: Active messages loaded before the edit rerun.
        message_id: User-message id being revised.

    Returns:
        ``(prefix, found)`` where ``prefix`` contains only rows before the
        target and ``found`` reports whether the target was present.
    """
    target = str(message_id or "")
    rows = [message for message in (messages or ()) if isinstance(message, dict)]
    if not target:
        return rows, False
    for index, message in enumerate(rows):
        if str(message.get("id") or "") == target:
            return rows[:index], True
    return rows, False


def _pending_edit_history_messages(
    messages: list[dict[str, Any]] | tuple[dict[str, Any], ...] | None,
    pending: dict[str, Any],
) -> tuple[list[dict[str, Any]], bool]:
    """Build the truncated transcript for in-place pending-edit loading.

    Returns the messages above the edit plus one user row that shows the draft
    text in the original bubble position. Later turns are omitted so Coach
    thinking can appear directly under that bubble (ChatGPT/Gemini style).

    Args:
        messages: Active persisted messages for this branch.
        pending: ``pending_edit`` session payload (message id, draft, attachments).

    Returns:
        ``(visible_rows, found)`` where ``found`` is False when the target
        cannot be matched (including stale-prefix fallback failure).
    """
    message_id = str(pending.get("message_id") or "")
    draft = str(pending.get("prompt") or "").strip()
    rows = [message for message in (messages or ()) if isinstance(message, dict)]
    prefix, found = _edit_render_plan(rows, message_id)
    original: dict[str, Any] | None = None
    if found:
        original = next(
            (
                message
                for message in rows
                if str(message.get("id") or "") == message_id
            ),
            None,
        )
    elif pending.get("render_target_found"):
        saved_prefix = pending.get("render_prefix")
        if isinstance(saved_prefix, list):
            prefix = [item for item in saved_prefix if isinstance(item, dict)]
            found = True
    if not found or not message_id:
        return [], False

    attachments = pending.get("attachments")
    if not isinstance(attachments, list):
        attachments = []
    attachment_rows = [item for item in attachments if isinstance(item, dict)]
    metadata: dict[str, Any] = {}
    if isinstance(original, dict):
        raw_meta = original.get("metadata")
        if isinstance(raw_meta, dict):
            metadata = dict(raw_meta)
        if not attachment_rows:
            attachment_rows = [
                item
                for item in (metadata.get("attachments") or [])
                if isinstance(item, dict)
            ]
    metadata["attachments"] = attachment_rows
    content = draft
    if not content and isinstance(original, dict):
        content = str(original.get("content") or "")
    edited_row: dict[str, Any] = {
        "id": message_id,
        "role": "user",
        "content": content,
        "metadata": metadata,
    }
    return [*prefix, edited_row], True


def handle_prompt(
    prompt: str,
    uploads: list[Any],
    model_id: str,
    reasoning_effort: str | None,
    target: Any,
    existing_user_message_id: str | None = None,
    *,
    visible_source_ids: set[str] | None = None,
    request_id: str | None = None,
    fragment_started: float | None = None,
    fragment_spans: dict[str, float] | None = None,
) -> None:
    """Submit one student turn through the typed coaching workflow.

    Uploads are private turn attachments. The coach path always uses ``CoachRequest``
    via the local API or in-process ``CoachApplicationService``, streaming
    progress events and then the final validated reply. On ``done``, this
    helper never keeps completed history only in the composer fragment:
    it remounts once so ``chat_log`` reads persisted messages. ``target``
    must be the in-flight sibling, never ``chat_log``: re-entering that
    keyed history container reuses the last assistant ``st.chat_message``.
    """
    cleaned_prompt = str(prompt or "").strip()
    # Feature-gated exact stage command: journey + assistant briefing only.
    if (
        existing_user_message_id is None
        and settings.student_stage_selection
        and cleaned_prompt
    ):
        manual_target = manual_stage_selection_target(cleaned_prompt)
        if manual_target is not None:
            thread_id = str(st.session_state.thread_id or "").strip()
            try:
                moved = apply_manual_stage_move(thread_id, manual_target)
                store.forget_turn_reads(thread_id)
                st.session_state.composer_nonce = (
                    int(st.session_state.get("composer_nonce") or 0) + 1
                )
                if moved:
                    st.session_state.chat_reveal_coach_reply = True
                rerun_app()
            except Exception as exc:
                detail = str(exc or "")
                response = getattr(exc, "response", None)
                if response is not None:
                    try:
                        payload = response.json()
                    except Exception:
                        payload = None
                    if isinstance(payload, dict):
                        detail = str(payload.get("detail") or detail)
                    elif not detail:
                        detail = str(getattr(response, "text", "") or "")
                if "locked" in detail.casefold():
                    set_stage_move_notice(
                        locked_stage_move_notice(manual_target)
                    )
                    st.session_state.composer_nonce = (
                        int(st.session_state.get("composer_nonce") or 0) + 1
                    )
                    rerun_app()
                else:
                    st.error(
                        "The Thinking Path stage could not be updated. Try again."
                    )
            return

    clear_stage_move_notice()
    set_coach_turn_streaming(True)
    handle_started = time.perf_counter()
    request_id = str(request_id or uuid.uuid4())
    api_origin = fragment_started if fragment_started is not None else handle_started
    spans: dict[str, float] = dict(fragment_spans or {})
    try:
        journey = normalize_journey(st.session_state.learning_journey)
        list_started = time.perf_counter()
        if visible_source_ids is None:
            sources = store.list_sources(st.session_state.thread_id)
            selected_sources = [source for source in sources if source.get("selected")]
            visible_source_ids = {str(source.get("id") or "") for source in sources}
            allow_model_knowledge = not selected_sources
        else:
            allow_model_knowledge = bool(st.session_state.get("allow_model_knowledge", True))
        spans["source_list_ms"] = _duration_ms(list_started)
        attachment_source_ids: list[str] = []
        st.session_state.allow_model_knowledge = allow_model_knowledge
        thread_started = time.perf_counter()
        pre_thread = store.get_thread(st.session_state.thread_id) or {}
        spans["thread_lookup_ms"] = _duration_ms(thread_started)
        pre_meta = dict(pre_thread.get("metadata") or {})
        pre_stage = str(journey.get("current_stage") or DEFAULT_STAGE)
        pre_deep_review_available = _deep_review_is_available(pre_meta)
        pre_deep_review_counter = _deep_review_counter(pre_meta)
        with target:
            pending_started = time.perf_counter()
            if existing_user_message_id is None:
                _render_inflight_user_prompt(prompt, uploads)
            spans["pending_user_render_ms"] = _duration_ms(pending_started)
            scroll_started = time.perf_counter()
            sync_chat_scroll(mode="send")
            spans["chat_scroll_send_ms"] = _duration_ms(scroll_started)
            # Keep the same private attachment records when a provider failure
            # is retried with the same prompt/idempotency scope. Attachments never
            # become selected notebook Sources.
            idempotency_key = get_retry_key(
                st.session_state,
                thread_id=st.session_state.thread_id,
                stage=journey["current_stage"],
                prompt=prompt,
            )
            attachment_records = st.session_state.setdefault("coach_turn_attachments", {})
            thinking: Any | None = None
            existing_attachments = attachment_records.get(idempotency_key)
            if isinstance(existing_attachments, list):
                attachment_source_ids = [
                    str(item.get("id") or "")
                    for item in existing_attachments
                    if isinstance(item, dict) and str(item.get("id") or "")
                ]
            elif uploads:
                thinking = st.status(
                    "Uploading attachment…",
                    expanded=False,
                    type="compact",
                )
                try:
                    upload_started = time.perf_counter()
                    attachment_records[idempotency_key] = store.upload_attachments(
                        st.session_state.thread_id,
                        [
                            (
                                upload.name,
                                upload.getvalue(),
                                getattr(upload, "type", None),
                            )
                            for upload in uploads
                        ],
                    )
                    spans["source_upload_ms"] = _duration_ms(upload_started)
                except Exception:
                    # The source service owns transactional/file cleanup. Do not
                    # submit a coach request when its prerequisite upload failed.
                    # Avoid surfacing raw exception text (paths, internals) in the UI.
                    thinking.update(label="Attachment upload failed", state="error")
                    st.error("The attachment could not be added, so no message was sent.")
                    st.caption("Remove or replace the attachment and try again.")
                    sync_chat_scroll(mode="settle")
                    return
                attachment_source_ids = [
                    str(item.get("id") or "")
                    for item in attachment_records[idempotency_key]
                    if isinstance(item, dict) and str(item.get("id") or "")
                ]
                thinking.update(label="Coach is thinking…", state="running")
            else:
                spans["source_upload_ms"] = 0.0
            # Preserve this key only while the same submitted text is unresolved.
            # The session helper stores a SHA-256 scope, never the prompt itself.
            build_started = time.perf_counter()
            # Leave source_ids/context empty so the application service loads them.
            request = CoachRequest(
                thread_id=st.session_state.thread_id,
                student_message=prompt,
                current_stage=journey["current_stage"],
                response_detail=journey["response_detail"],
                allow_model_knowledge=allow_model_knowledge,
                response_language=st.session_state.get("response_language", "English"),
                model_id=model_id,
                reasoning_effort=reasoning_effort,
                idempotency_key=idempotency_key,
                attachment_source_ids=attachment_source_ids,
            )
            spans["request_build_ms"] = _duration_ms(build_started)
            history_window = st.session_state.get("_chat_history_window")
            if (
                isinstance(history_window, dict)
                and str(history_window.get("thread_id") or "")
                == str(st.session_state.thread_id or "")
                and history_window.get("loaded")
            ):
                # The composer fragment already loaded this authoritative
                # page before accepting the prompt. Reuse its visible count
                # instead of issuing a duplicate one-row page read.
                baseline_message_count = int(
                    history_window.get("total_count") or 0
                )
            else:
                baseline_page = store.get_message_page(
                    st.session_state.thread_id, limit=1
                )
                baseline_message_count = (
                    int(baseline_page.total_count)
                    if hasattr(baseline_page, "total_count")
                    else int((baseline_page or {}).get("total_count", 0))
                )
            thinking_started = time.perf_counter()
            if thinking is None:
                thinking = st.status(
                    "Coach is thinking…",
                    expanded=False,
                    type="compact",
                )
            spans["thinking_render_ms"] = _duration_ms(thinking_started)
            try:
                turn: CoachTurn | None = None
                thinking_closed = False
                awaiting_armed = False
                log_ui_timing(
                    request_id=request_id,
                    fragment_to_api_ms=_duration_ms(api_origin),
                    pre_api_ms=_duration_ms(handle_started),
                    fragment_enter_ms=float(spans.get("fragment_enter_ms") or 0.0),
                    prompt_accept_ms=float(spans.get("prompt_accept_ms") or 0.0),
                    composer_layout_ms=float(spans.get("composer_layout_ms") or 0.0),
                    source_list_ms=float(spans.get("source_list_ms") or 0.0),
                    thread_lookup_ms=float(spans.get("thread_lookup_ms") or 0.0),
                    pending_user_render_ms=float(spans.get("pending_user_render_ms") or 0.0),
                    chat_scroll_send_ms=float(spans.get("chat_scroll_send_ms") or 0.0),
                    source_upload_ms=float(spans.get("source_upload_ms") or 0.0),
                    request_build_ms=float(spans.get("request_build_ms") or 0.0),
                    thinking_render_ms=float(spans.get("thinking_render_ms") or 0.0),
                    fragment_enter_epoch_ms=(
                        int(spans["fragment_enter_epoch_ms"])
                        if "fragment_enter_epoch_ms" in spans
                        else None
                    ),
                    upload_count=len(uploads),
                )

                def _close_thinking(*, label: str, state: str) -> None:
                    nonlocal thinking_closed
                    if thinking_closed:
                        return
                    thinking.update(label=label, state=state)
                    thinking_closed = True

                def _arm_awaiting_after_server_ack() -> None:
                    """Lock recovery only after the API has accepted the turn.

                    Arming before the first stream event left Chat locked when a
                    tab switch aborted the HTTP request before FastAPI started
                    the worker — recovery then polled forever for a reply that
                    would never be persisted.
                    """
                    nonlocal awaiting_armed
                    if awaiting_armed:
                        return
                    set_awaiting_coach_turn(
                        thread_id=str(st.session_state.thread_id or ""),
                        idempotency_key=str(idempotency_key or ""),
                        prompt=str(prompt or ""),
                        baseline_message_count=baseline_message_count,
                    )
                    awaiting_armed = True

                for event in stream_coach_turn_events(request, request_id=request_id):
                    _arm_awaiting_after_server_ack()
                    kind = event.get("event")
                    if kind == "started" or kind == "graph":
                        continue
                    if kind == "status":
                        phase = str(event.get("phase") or "").strip()
                        label = str(event.get("label") or "").strip()
                        if phase == "retrieving":
                            thinking.update(label=label or "Searching course materials…")
                        elif phase == "thinking":
                            thinking.update(label=label or "Coach is thinking…")
                        elif phase == "saving":
                            thinking.update(label=label or "Saving response…")
                        continue
                    if kind == "token":
                        continue
                    elif kind == "done":
                        turn = CoachTurn.model_validate(event["turn"])
                    elif kind == "error":
                        _close_thinking(label="Coaching failed", state="error")
                        raise CoachTurnStreamError(
                            str(event.get("detail") or "Coaching failed"),
                            status=event.get("status"),
                            category=str(event.get("category") or ""),
                        )
                if turn is None or not str(turn.response_text or "").strip():
                    _close_thinking(label="Coaching failed", state="error")
                    raise CoachTurnStreamError(
                        "The coach reply could not be completed",
                        category="structured_output_failure",
                    )
                _close_thinking(label="Coach reply ready", state="complete")
                # Drop the retry key only after the reply is complete. The
                # composer is a trigger widget, so this run's submitted value
                # cannot fire again.
                remove_retry_key(
                    st.session_state,
                    thread_id=st.session_state.thread_id,
                    stage=journey["current_stage"],
                    prompt=prompt,
                )
                attachment_records.pop(idempotency_key, None)
                apply_completed_turn_to_session(
                    turn,
                    thread_id=st.session_state.thread_id,
                    pre_stage=pre_stage,
                    pre_deep_review_available=pre_deep_review_available,
                    pre_deep_review_counter=pre_deep_review_counter,
                )
                clear_awaiting_coach_turn()
                # Always remount from persisted history. Painting completed
                # turns only in this fragment would drop them on the next
                # Send. Do not also render_message here or the remount would
                # duplicate the bubble.
                st.session_state.composer_nonce += 1
                # Prefer reply-top pin on remount when the student did not
                # scroll away (JS awaitingReplyReveal survives feed reset).
                st.session_state.chat_reveal_coach_reply = True
                rerun_app()
                return
            except CoachTurnStreamError as error:
                clear_awaiting_coach_turn()
                try:
                    thinking.update(label="Coaching failed", state="error")
                except Exception:
                    pass
                _render_inflight_error(
                    student_coach_error_message(error.category, status=error.status)
                )
                sync_chat_scroll(mode="settle")
                return
            except Exception:
                clear_awaiting_coach_turn()
                try:
                    thinking.update(label="Coaching failed", state="error")
                except Exception:
                    pass
                _render_inflight_error(student_coach_error_message("unavailable"))
                sync_chat_scroll(mode="settle")
                return
    finally:
        set_coach_turn_streaming(False)


@st.dialog("Edit this message?")
def _confirm_edit_earlier_message_dialog() -> None:
    """Warn that editing a non-latest user turn starts a new conversation revision."""
    st.write(
        "Editing this message creates a new conversation revision. "
        "Later turns leave the active view but remain in revision history."
    )
    cancel_column, continue_column = st.columns(2)
    if cancel_column.button("Cancel", use_container_width=True):
        st.session_state.edit_confirm_message_id = None
        rerun_app()
    if continue_column.button(
        "Edit & continue",
        type="primary",
        use_container_width=True,
    ):
        message_id = st.session_state.get("edit_confirm_message_id")
        st.session_state.edit_confirm_message_id = None
        if _coach_turn_busy():
            st.session_state.edit_error_message = _EDIT_WAIT_FOR_COACH_MESSAGE
            rerun_app()
            return
        if message_id:
            st.session_state.editing_message = message_id
        rerun_app()


def _restore_pending_edit_draft(message_id: str, draft: str) -> None:
    """Re-open the in-bubble editor with the failed revise draft for retry."""
    if not message_id:
        return
    st.session_state.editing_message = message_id
    if draft:
        st.session_state[f"edit-text-{message_id}"] = draft


def _abort_pending_edit_noop() -> None:
    """Stop an in-flight edit and restore the pre-edit transcript view.

    Clears the pending revise attempt without reopening the editor and without
    applying a replacement coach turn. Server work already in flight may still
    finish; the UI ignores that result for this attempt.
    """
    st.session_state.pop("pending_edit", None)
    st.session_state.pop("_chat_edit_prefix_snapshot", None)
    st.session_state.pop("_pending_edit_worker", None)
    st.session_state.editing_message = None
    clear_awaiting_coach_turn()
    set_coach_turn_streaming(False)
    st.session_state.composer_nonce = int(
        st.session_state.get("composer_nonce") or 0
    ) + 1
    _rerun_edit_fragment()


def _rerun_edit_fragment() -> None:
    """Rerun the chat fragment when already in a fragment-scoped run.

    A pending edit can also be restored by a full app rerun (for example after
    a browser refresh or an explicit retry). Streamlit rejects fragment scope
    in that context; fall back to a full app remount so the restored editor is
    painted instead of leaving the truncated pending-edit view on screen.
    """
    try:
        rerun_fragment()
    except StreamlitAPIException as error:
        if 'scope="fragment"' not in str(error):
            raise
        rerun_app()


def _submit_pending_edit(
    *,
    model_id: str,
    reasoning_effort: str | None,
) -> bool:
    """Apply a bubble edit via the server revise endpoint and reload state.

    Keeps one stable idempotency key for the logical edit attempt until it
    succeeds or the student abandons editing. When the append-only revision
    already committed but provider generation failed, the same key + original
    message id lets the server resume the replacement without bumping again.

    Runs on the Streamlit script thread so auth cookies and session state stay
    valid (background workers cannot read script-thread cookie context).

    On failure, clears ``pending_edit`` so a later rerun does not auto-resubmit;
    the student must click Send again. The revise retry key stays in session.

    Returns:
        True when revise succeeded and a rerun was requested; False when the
        edit could not run so the chat panel should keep rendering. On failure,
        clears ``pending_edit``, restores the in-bubble editor draft, and keeps
        the stable revise idempotency key for an explicit Send retry. The safe
        error is shown on the next fragment render when fragment scope is
        available, or in the current full-run fallback.
    """
    pending = st.session_state.get("pending_edit")
    if not isinstance(pending, dict):
        return False
    message_id = str(pending.get("message_id") or "")
    draft = str(pending.get("prompt") or "").strip()
    if not message_id or not draft:
        st.session_state.pop("pending_edit", None)
        st.session_state.pop("_chat_edit_prefix_snapshot", None)
        _restore_pending_edit_draft(message_id, draft)
        st.session_state.edit_error_message = "Enter a message before resending."
        _rerun_edit_fragment()
        return False
    thread_id = st.session_state.thread_id
    pending_key = str(pending.get("idempotency_key") or "").strip()

    def _reuse_pending_key() -> str:
        return pending_key

    # Always register under the revise scope so clearing pending_edit on
    # failure still lets an explicit Send reuse the same UUID.
    idempotency_key = get_retry_key(
        st.session_state,
        thread_id=thread_id,
        stage=f"revise:{message_id}",
        prompt=draft,
        new_key=_reuse_pending_key if pending_key else None,
    )
    # Persist the stable key before the network call so browser reruns reuse it.
    pending = {
        **pending,
        "message_id": message_id,
        "prompt": draft,
        "idempotency_key": idempotency_key,
    }
    st.session_state.pending_edit = pending
    # A prior send may still hold the notebook lease on the API worker even
    # after Streamlit interrupted the NDJSON reader. Do not race it.
    if awaiting_coach_turn_for_thread() is not None:
        st.session_state.pop("pending_edit", None)
        st.session_state.pop("_chat_edit_prefix_snapshot", None)
        _restore_pending_edit_draft(message_id, draft)
        st.session_state.edit_error_message = _EDIT_WAIT_FOR_COACH_MESSAGE
        _rerun_edit_fragment()
        return False
    set_coach_turn_streaming(True)
    baseline_page = store.get_message_page(thread_id, limit=1)
    baseline_messages = (
        baseline_page.messages
        if hasattr(baseline_page, "messages")
        else (baseline_page or {}).get("messages", [])
    )
    baseline_total = (
        int(baseline_page.total_count)
        if hasattr(baseline_page, "total_count")
        else int((baseline_page or {}).get("total_count", len(baseline_messages)))
    )
    set_awaiting_coach_turn(
        thread_id=str(thread_id or ""),
        idempotency_key=str(idempotency_key or ""),
        prompt=draft,
        baseline_message_count=baseline_total,
    )
    thinking = st.status(
        "Coach is thinking…",
        expanded=False,
        type="compact",
    )
    try:
        try:
            last_error: BaseException | None = None
            for attempt in range(_REVISE_BUSY_ATTEMPTS):
                try:
                    store.revise_message(
                        thread_id,
                        message_id,
                        draft,
                        idempotency_key=idempotency_key,
                        model_id=model_id,
                        reasoning_effort=reasoning_effort,
                        response_detail=st.session_state.get("response_detail")
                        or DEFAULT_RESPONSE_DETAIL,
                        response_language=st.session_state.get("response_language")
                        or "English",
                    )
                    last_error = None
                    break
                except Exception as error:
                    last_error = error
                    if (
                        _exception_is_coach_busy(error)
                        and attempt + 1 < _REVISE_BUSY_ATTEMPTS
                    ):
                        thinking.update(
                            label="Waiting for the previous coach reply to finish…",
                            state="running",
                        )
                        time.sleep(_REVISE_BUSY_SLEEP_SECONDS)
                        continue
                    raise
            if last_error is not None:
                raise last_error
            thinking.update(label="Coach reply ready", state="complete")
        except Exception as error:
            clear_awaiting_coach_turn()
            thinking.update(label="Coaching failed", state="error")
            # Drop pending_edit so the next rerun does not auto-resubmit. Keep the
            # stable retry key in session and reopen the editor so the student must
            # click Send again to retry the same revision attempt.
            st.session_state.pop("pending_edit", None)
            st.session_state.pop("_chat_edit_prefix_snapshot", None)
            _restore_pending_edit_draft(message_id, draft)
            st.session_state.edit_error_message = _edit_failure_message(error)
            _rerun_edit_fragment()
            return False
        remove_retry_key(
            st.session_state,
            thread_id=thread_id,
            stage=f"revise:{message_id}",
            prompt=draft,
        )
        st.session_state.pop("pending_edit", None)
        st.session_state.pop("_chat_edit_prefix_snapshot", None)
        st.session_state.editing_message = None
        updated_thread = store.get_thread(thread_id) or {}
        updated_metadata = updated_thread.get("metadata") or {}
        updated_journey = normalize_journey(updated_metadata.get("learning_journey"))
        st.session_state.learning_journey = updated_journey
        st.session_state.response_detail = updated_journey["response_detail"]
        reset_chat_history_window(thread_id)
        clear_awaiting_coach_turn()
        st.session_state.composer_nonce += 1
        st.session_state.chat_reveal_coach_reply = True
        rerun_app()
        return True
    finally:
        set_coach_turn_streaming(False)


def _page_payload(page: Any) -> dict[str, Any]:
    """Normalize a local/API page model into a serializable mapping."""
    if hasattr(page, "model_dump"):
        value = page.model_dump(mode="json")
    elif isinstance(page, dict):
        value = dict(page)
    else:
        value = {}
    messages = value.get("messages")
    value["messages"] = [item for item in messages or () if isinstance(item, dict)]
    value["next_cursor"] = value.get("next_cursor") or None
    value["total_count"] = max(0, int(value.get("total_count") or 0))
    value["conversation_revision"] = max(
        0, int(value.get("conversation_revision") or 0)
    )
    value["source_ids"] = [str(item) for item in value.get("source_ids") or () if str(item).strip()]
    value["hmw_scaffold"] = (
        value.get("hmw_scaffold") if isinstance(value.get("hmw_scaffold"), dict) else {}
    )
    return value


def _history_projection(state: dict[str, Any]) -> dict[str, Any]:
    """Return the normalized server projection carried by a history window."""
    projection = state.get("hmw_scaffold")
    return projection if isinstance(projection, dict) else {}


def _history_anchor_message_id(state: dict[str, Any]) -> str | None:
    """Return the server anchor, or ``None`` for legacy local projections.

    A present ``available`` flag means the page came from the authoritative
    history projection. In that mode an empty anchor is meaningful: the HMW
    card must stay hidden until a valid exact anchor can be loaded.
    """
    projection = _history_projection(state)
    if "available" not in projection:
        return None
    return str(projection.get("anchor_message_id") or "")


def _history_hmw_available(
    state: dict[str, Any],
    journey: dict[str, Any] | None = None,
) -> bool:
    """Return the conservative HMW gate for the loaded notebook window.

    The server projection is authoritative for readiness. The session journey
    is an additional display guard so a just-selected non-PI stage cannot
    leave a stale card visible during the short remount before its projection
    refreshes.
    """
    projection = _history_projection(state)
    current = journey or normalize_journey(st.session_state.get("learning_journey"))
    if str(current.get("current_stage") or DEFAULT_STAGE) != DEFAULT_STAGE:
        return False
    if "available" not in projection:
        # Compatibility with an older in-process adapter that predates the
        # page projection; the normal API/local service path always supplies
        # ``available`` above.
        return hmw_scaffold_available(
            str(current.get("current_stage") or DEFAULT_STAGE),
            state.get("messages") or [],
            enabled=settings.hmw_scaffold_enabled,
            response_detail=str(current.get("response_detail") or ""),
        )
    return bool(projection.get("available"))


def _refresh_loaded_history_window(thread_id: str) -> None:
    """Detect out-of-band transcript writes without dropping loaded pages.

    Normal chat mutations explicitly reset the window. This bounded probe is
    for app remounts that can follow an external worker or another browser
    tab: when the total/revision/projection changes, the next render starts at
    the newest six; otherwise already-prepended pages remain in session.
    """
    state = st.session_state.get("_chat_history_window")
    if not isinstance(state, dict) or not state.get("loaded"):
        return
    try:
        probe = _page_payload(
            store.get_message_page(thread_id, limit=_HISTORY_PAGE_SIZE)
        )
    except Exception:
        return
    if (
        probe["total_count"] != int(state.get("total_count") or 0)
        or probe["conversation_revision"]
        != int(state.get("conversation_revision") or 0)
        or probe["hmw_scaffold"] != _history_projection(state)
        or probe["messages"]
        != list(state.get("messages") or [])[-len(probe["messages"]) :]
    ):
        reset_chat_history_window(thread_id)


def _message_source_ids_for_render(message: Any) -> set[str]:
    """Collect source and private-attachment ids from a loaded message.

    The page API returns an aggregate source projection, while individual
    message metadata still carries private attachment descriptors. Keeping
    both sets merged as pages are prepended lets citation and attachment
    buttons resolve without reopening the full transcript.
    """
    if not isinstance(message, dict):
        return set()
    metadata = message.get("metadata")
    if not isinstance(metadata, dict):
        return set()
    values: list[Any] = [
        metadata.get("source_ids"),
        metadata.get("attachment_source_ids"),
        metadata.get("source_refs"),
        metadata.get("attachments"),
    ]
    source_ids: set[str] = set()

    def add(value: Any) -> None:
        if isinstance(value, str):
            cleaned = value.strip()
            if cleaned:
                source_ids.add(cleaned)
        elif isinstance(value, dict):
            for key in ("id", "source_id", "sourceId"):
                if value.get(key):
                    add(value[key])
                    break
        elif isinstance(value, (list, tuple, set)):
            for item in value:
                add(item)

    for value in values:
        add(value)
    return source_ids


def _history_window(thread_id: str) -> dict[str, Any]:
    """Return the serializable bounded history window for the active notebook."""
    existing = st.session_state.get("_chat_history_window")
    if not isinstance(existing, dict) or str(existing.get("thread_id") or "") != str(thread_id):
        reset_chat_history_window(thread_id)
        existing = st.session_state._chat_history_window
    return existing


def _history_page_is_stale(error: BaseException) -> bool:
    """Return whether a page failure means its revision-bound cursor is stale."""
    status = getattr(error, "status_code", None)
    response = getattr(error, "response", None)
    if status is None and response is not None:
        status = getattr(response, "status_code", None)
    try:
        if int(status or 0) == 409:
            return True
    except (TypeError, ValueError):
        pass
    text = str(error).lower()
    return "revision" in text or "stale cursor" in text or "notebook changed" in text


def _load_initial_history_window(thread_id: str) -> dict[str, Any]:
    """Fetch newest six visible messages after an explicit notebook reset."""
    state = _history_window(thread_id)
    if state.get("loaded"):
        return state
    try:
        payload = _page_payload(
            store.get_message_page(thread_id, limit=_HISTORY_PAGE_SIZE)
        )
    except Exception:
        # Keep the empty/unloaded state so a later app rerun can retry. The
        # error is intentionally short-lived and rendered by the pager rather
        # than exposing transport or storage details to the student.
        state["error"] = "Chat history is temporarily unavailable. Try again."
        state["error_at"] = time.time()
        return state
    state.update(
        {
            "messages": payload["messages"],
            "next_cursor": payload["next_cursor"],
            "total_count": payload["total_count"],
            "conversation_revision": payload["conversation_revision"],
            "source_ids": payload["source_ids"],
            "hmw_scaffold": payload["hmw_scaffold"],
            "loaded": True,
            "prepend_pending": False,
            "loading": False,
            "error": None,
            "error_at": 0.0,
        }
    )
    return state


def _prepend_history_page(thread_id: str) -> bool:
    """Prepend one older page, deduplicating by persisted message id."""
    if (
        coach_turn_is_streaming()
        or awaiting_coach_turn_for_thread() is not None
        or isinstance(st.session_state.get("pending_edit"), dict)
        or bool(st.session_state.get("editing_message"))
    ):
        return False
    state = _history_window(thread_id)
    if state.get("loading"):
        return False
    cursor = str(state.get("next_cursor") or "").strip()
    if not cursor:
        return False
    state["loading"] = True
    try:
        payload = _page_payload(
            store.get_message_page(thread_id, limit=_HISTORY_PAGE_SIZE, cursor=cursor)
        )
    except Exception as error:
        # Keep already loaded rows and cursor intact so a transient network
        # failure can be retried. A revision conflict cannot be merged safely;
        # reset to a fresh newest page while retaining a student-safe notice.
        if _history_page_is_stale(error):
            reset_chat_history_window(thread_id)
            fresh = _load_initial_history_window(thread_id)
            # Keep the object already held by this render in sync with the
            # replacement session value; otherwise the current run could paint
            # a detached stale transcript after the reset.
            state.clear()
            state.update(fresh)
            # Keep the ordinary open flag for the outer workspace rerun. This
            # separate marker is consumed only by a component-triggered
            # fragment rerun, where the outer mode="open" call cannot run.
            state["_history_stale_open_pending"] = True
            return False
        state["error"] = "Earlier messages could not be loaded. Try again."
        state["error_at"] = time.time()
        state["prepend_pending"] = False
        state["loading"] = False
        return False
    by_id: dict[str, dict[str, Any]] = {}
    for item in [*payload["messages"], *state.get("messages", [])]:
        message_id = str(item.get("id") or "").strip()
        if message_id:
            by_id[message_id] = item
    ordered = sorted(
        by_id.values(),
        key=lambda item: (str(item.get("created_at") or ""), str(item.get("id") or "")),
    )
    source_ids = list(dict.fromkeys([*state.get("source_ids", []), *payload["source_ids"]]))
    state.update(
        {
            "messages": ordered,
            "next_cursor": payload["next_cursor"],
            "total_count": payload["total_count"],
            "conversation_revision": payload["conversation_revision"],
            "source_ids": source_ids,
            "hmw_scaffold": payload["hmw_scaffold"],
            "loaded": True,
            "prepend_pending": True,
            "open_pending": False,
            "loading": False,
            "error": None,
            "error_at": 0.0,
        }
    )
    return True


def _render_history_pager(thread_id: str, state: dict[str, Any]) -> None:
    """Mount the bidirectional upward trigger and accessible fallback button."""
    error_text = str(state.get("error") or "").strip()
    error_at = float(state.get("error_at") or 0.0)
    if error_text and (not error_at or time.time() - error_at <= _HISTORY_ERROR_TTL_SECONDS):
        st.caption(error_text)
    elif error_text:
        state["error"] = None
        state["error_at"] = 0.0
    cursor = str(state.get("next_cursor") or "").strip()
    has_more = bool(cursor)
    busy = bool(
        coach_turn_is_streaming()
        or awaiting_coach_turn_for_thread() is not None
        or isinstance(st.session_state.get("pending_edit"), dict)
        or bool(st.session_state.get("editing_message"))
        or bool(state.get("loading"))
    )
    component_data = {
        "thread_id": str(thread_id),
        "cursor": cursor,
        "has_more": has_more,
        "busy": busy,
    }
    if _history_pager_component is not None:
        try:
            result = _history_pager_component(
                key=f"history-pager-{thread_id}",
                data=component_data,
                width=1,
                height=0,
                on_older_change=lambda: None,
            )
            trigger = getattr(result, "older", None)
            if isinstance(trigger, dict) and str(trigger.get("cursor") or "") == cursor:
                if _prepend_history_page(thread_id):
                    st.session_state._chat_history_window["_component_prepend"] = True
        except Exception:
            # The visible fallback remains available when a browser/component
            # runtime does not support the Streamlit 1.60 bidi API.
            pass
    if has_more:
        st.button(
            f"Load {_HISTORY_PAGE_SIZE} earlier messages",
            key=f"load-earlier-{thread_id}-{cursor[:24]}",
            disabled=busy,
            on_click=_prepend_history_page,
            args=(thread_id,),
            help="Load the previous six messages",
            type="tertiary",
        )


def _render_chat_history(
    messages: list[dict[str, Any]],
    *,
    hmw_available: bool,
    hmw_anchor_message_id: str | None = None,
    visible_source_ids: set[str],
    stop_before_message_id: str | None = None,
    allow_edit: bool = True,
) -> bool:
    """Render persisted history, optionally stopping before an edited message.

    Args:
        messages: Rows to paint (full branch, or truncated pending-edit view).
        hmw_available: Whether the HMW scaffold may appear in this branch.
        hmw_anchor_message_id: Server-projected persisted anchor id. This may
            be outside the currently loaded window.
        visible_source_ids: Source ids currently shown in this notebook.
        stop_before_message_id: Optional id to stop before (editor-open paths).
        allow_edit: When False, hide Edit on user bubbles (pending-edit inflight).

    Returns:
        True when ``stop_before_message_id`` was found. The edit flow uses this
        to hide the obsolete branch while the replacement turn is running.
    """
    latest_user = next(
        (item for item in reversed(messages) if item.get("role") == "user"),
        None,
    )
    latest_user_message_id = (
        str(latest_user.get("id") or "") if latest_user else None
    )
    found = False
    for kind, message in transcript_hmw_render_plan(
        messages,
        hmw_available=hmw_available,
        anchor_message_id=hmw_anchor_message_id,
    ):
        if kind == "hmw":
            render_hmw_scaffold_if_needed(available=True)
            continue
        if message is None:
            continue
        if stop_before_message_id and message.get("id") == stop_before_message_id:
            found = True
            break
        render_message(
            message,
            visible_source_ids=visible_source_ids,
            latest_user_message_id=latest_user_message_id,
            allow_edit=allow_edit,
        )
    return found


@st.fragment
def _render_composer_submit_fragment(
    messages: list[dict[str, Any]],
    hmw_available: bool,
    model_id: str,
    reasoning_effort: str | None,
    visible_source_ids: set[str],
) -> None:
    """Render one scrollable feed plus its fixed composer footer.

    Streamlit 1.60 reruns only this fragment when ``st.chat_input`` submits,
    so Journey, Deep Review, Sources, and chat history are not rebuilt
    before FastAPI starts. After a successful persisted turn, one
    ``rerun_app()`` reconciles the authoritative transcript, Thinking Path,
    and Deep Review caption.

    Args:
        messages: Active persisted branch loaded by the parent app run.
        hmw_available: Server-owned HMW visibility projection for this branch.
        model_id: Selected coaching model id for the next turn.
        reasoning_effort: Compatible reasoning effort, or None.
        visible_source_ids: Source ids currently shown in this notebook.
    """
    fragment_started = time.perf_counter()
    fragment_enter_epoch_ms = int(time.time() * 1000)
    request_id = str(uuid.uuid4())
    thread_id = str(st.session_state.get("thread_id") or "").strip()
    history_state: dict[str, Any] = {}
    if thread_id:
        history_state = _load_initial_history_window(thread_id)
        messages = list(history_state.get("messages") or [])
        # The parent may only know sources from the first page. Merge every
        # loaded page's aggregate and per-message references before rendering
        # citation/attachment controls.
        visible_source_ids = set(visible_source_ids)
        visible_source_ids.update(
            str(source_id)
            for source_id in history_state.get("source_ids") or []
            if str(source_id).strip()
        )
        for loaded_message in messages:
            visible_source_ids.update(
                _message_source_ids_for_render(loaded_message)
            )
        hmw_available = _history_hmw_available(history_state)
    pending = st.session_state.get("pending_edit")
    # Interrupt during an in-flight send can open the editor while the API
    # worker still holds the notebook lease. Close the editor until recovery.
    if (
        not isinstance(pending, dict)
        and st.session_state.get("editing_message")
        and awaiting_coach_turn_for_thread() is not None
    ):
        st.session_state.editing_message = None
        st.session_state.edit_error_message = _EDIT_WAIT_FOR_COACH_MESSAGE
    # This is a bounded, one-action render snapshot. It is not used as
    # conversation authority and is cleared when the revise attempt ends.
    if not isinstance(pending, dict):
        editing_message_id = str(st.session_state.get("editing_message") or "")
        if editing_message_id:
            prefix, target_found = _edit_render_plan(messages, editing_message_id)
            st.session_state._chat_edit_prefix_snapshot = {
                "message_id": editing_message_id,
                "prefix": prefix,
                "target_found": target_found,
            }
        else:
            st.session_state.pop("_chat_edit_prefix_snapshot", None)
    pending_message_id = ""
    if isinstance(pending, dict):
        pending_message_id = str(pending.get("message_id") or "")
    awaiting_locked = awaiting_coach_turn_for_thread() is not None
    history_allow_edit = not awaiting_locked and not pending_message_id

    with st.container(key="chat_transcript"):
        with st.container(key="chat_feed"):
            _render_history_pager(thread_id, history_state)
            # A component trigger can update the session window before this
            # fragment paints its transcript. Read it again so the prepended
            # page appears in the same rerun.
            messages = list(history_state.get("messages") or [])
            visible_source_ids.update(
                str(source_id)
                for source_id in history_state.get("source_ids") or []
                if str(source_id).strip()
            )
            for loaded_message in messages:
                visible_source_ids.update(
                    _message_source_ids_for_render(loaded_message)
                )
            hmw_available = _history_hmw_available(history_state)
            chat_log = st.container(key="chat_log")
            with chat_log:
                history_started = time.perf_counter()
                found_edit = False
                if pending_message_id and isinstance(pending, dict):
                    # In-place edit: keep the edited bubble (draft text) in
                    # chat_log and drop later turns. Thinking belongs only in
                    # chat_inflight — do not paint a second inflight user bubble.
                    render_messages, found_edit = _pending_edit_history_messages(
                        messages,
                        pending,
                    )
                    if found_edit:
                        _render_chat_history(
                            render_messages,
                            hmw_available=hmw_available,
                            hmw_anchor_message_id=_history_anchor_message_id(
                                history_state
                            ),
                            visible_source_ids=visible_source_ids,
                            allow_edit=False,
                        )
                elif not pending_message_id:
                    _render_chat_history(
                        messages,
                        hmw_available=hmw_available,
                        hmw_anchor_message_id=_history_anchor_message_id(
                            history_state
                        ),
                        visible_source_ids=visible_source_ids,
                        allow_edit=history_allow_edit,
                    )
                log_ui_timing(
                    chat_history_ms=round(
                        max(0.0, (time.perf_counter() - history_started) * 1000.0),
                        1,
                    ),
                    message_count=len(messages),
                )
            chat_inflight = st.container(key="chat_inflight")
            with chat_inflight:
                if pending_message_id and found_edit:
                    # Cancel in the pending bubble may have already cleared
                    # pending_edit; only submit while the attempt is still armed.
                    if isinstance(st.session_state.get("pending_edit"), dict):
                        _submit_pending_edit(
                            model_id=model_id,
                            reasoning_effort=reasoning_effort,
                        )
                elif pending_message_id and not found_edit:
                    st.session_state.pop("pending_edit", None)
                    st.session_state.pop("_chat_edit_prefix_snapshot", None)
                    st.session_state.edit_error_message = (
                        "This edit could not be matched to the active conversation. "
                        "Reload the notebook before trying again."
                    )
                    _rerun_edit_fragment()
                else:
                    _render_awaiting_coach_recovery()
                edit_error = st.session_state.pop("edit_error_message", None)
                if edit_error:
                    st.error(str(edit_error))

        with st.container(key="chat_composer"):
            fragment_enter_ms = _duration_ms(fragment_started)
            prompt_started = time.perf_counter()
            notice = str(st.session_state.get("stage_move_notice") or "").strip()
            if notice:
                with st.container(key="stage_move_notice"):
                    st.markdown(
                        f'<p class="cd-stage-move-notice">'
                        f"{html.escape(notice)}"
                        f"</p>",
                        unsafe_allow_html=True,
                    )
            if awaiting_locked and not coach_turn_is_streaming():
                _render_awaiting_composer_controls()
            composer_value = st.chat_input(
                "Ask a question or share your thinking",
                key=f"composer-{st.session_state.composer_nonce}",
                accept_file="multiple",
                accept_audio=False,
                max_upload_size=settings.max_file_size_mb,
                submit_mode="stop",
                height="content",
                disabled=awaiting_locked,
            )
            prompt_accept_ms = _duration_ms(prompt_started)
            layout_started = time.perf_counter()
            sync_composer_layout(max_file_size_mb=settings.max_file_size_mb)
            composer_layout_ms = _duration_ms(layout_started)
    # A stale cursor means the accumulated window was replaced with the
    # newest page. Component-triggered fragment reruns do not execute the
    # outer workspace block, so consume only the stale-recovery flag here;
    # ordinary notebook opens leave open_pending for workspace.py.
    if history_state.get("_history_stale_open_pending"):
        history_state["_history_stale_open_pending"] = False
        history_state["prepend_pending"] = False
        sync_chat_scroll(mode="open")
    elif history_state.get("prepend_pending"):
        history_state["prepend_pending"] = False
        sync_chat_scroll(mode="prepend")
    prompt, uploads = normalize_composer_value(composer_value)
    if prompt and not pending_message_id and not awaiting_locked:
        handle_prompt(
            prompt,
            uploads,
            model_id,
            reasoning_effort,
            chat_inflight,
            existing_user_message_id=None,
            visible_source_ids=visible_source_ids,
            request_id=request_id,
            fragment_started=fragment_started,
            fragment_spans={
                "fragment_enter_ms": fragment_enter_ms,
                "prompt_accept_ms": prompt_accept_ms,
                "composer_layout_ms": composer_layout_ms,
                "fragment_enter_epoch_ms": float(fragment_enter_epoch_ms),
            },
        )


def render_chat_panel(model_id: str, reasoning_effort: str | None) -> None:
    """Render the discussion log, in-flight turn slot, and chat composer.

    Args:
        model_id: Selected coaching model id for the next turn.
        reasoning_effort: Compatible reasoning effort for that model, or None.
    """
    sources = store.list_sources(st.session_state.thread_id)
    selected_sources = [source for source in sources if source.get("selected")]
    allow_model_knowledge = not selected_sources
    st.session_state.allow_model_knowledge = allow_model_knowledge
    # Recovery poller mounts from workspace outside this panel so its
    # run_every ticks do not strip the JS scroll-down control. Still clear a
    # stuck streaming flag and try to complete on every chat paint.
    _clear_stale_streaming_for_awaiting_recovery()
    if (
        awaiting_coach_turn_for_thread() is not None
        and not coach_turn_is_streaming()
    ):
        _try_complete_awaiting_coach_turn()
    _refresh_loaded_history_window(st.session_state.thread_id)
    history_state = _load_initial_history_window(st.session_state.thread_id)
    messages = list(history_state.get("messages") or [])
    visible_source_ids = {
        str(source.get("id") or "") for source in sources
    }
    visible_source_ids.update(
        str(source_id)
        for source_id in history_state.get("source_ids") or []
        if str(source_id).strip()
    )
    # Private attachments are absent from Sources but remain safe to open from
    # their authoritative message history (including a Coach citation to one).
    for message in messages:
        visible_source_ids.update(_message_source_ids_for_render(message))
    if st.session_state.get("edit_confirm_message_id"):
        _confirm_edit_earlier_message_dialog()

    journey = normalize_journey(st.session_state.get("learning_journey"))
    hmw_available = _history_hmw_available(history_state, journey)
    _render_composer_submit_fragment(
        messages,
        hmw_available,
        model_id,
        reasoning_effort,
        visible_source_ids,
    )
