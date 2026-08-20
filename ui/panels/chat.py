"""Discussion panel, message rendering, and composer handling.

Chat scrolling is owned by ``.st-key-chat_panel`` plus
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

from ui.coach_welcome import (
    COACH_WELCOME_KIND,
    render_hmw_scaffold_if_needed,
    seed_coach_welcome,
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
    log_ui_timing,
    rerun_app,
    set_coach_turn_streaming,
    store,
    stream_coach_turn_events,
)
from ui.retry_keys import get_retry_key, remove_retry_key
from ui.sources import source_viewer_dialog


def _duration_ms(started: float) -> float:
    """Return milliseconds elapsed since a ``perf_counter`` mark."""
    return round(max(0.0, (time.perf_counter() - started) * 1000.0), 1)


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
        if not path.is_file() or not (
            workspace_root in path.parents or files_root in path.parents
        ):
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
            str(source.get("id") or "")
            for source in store.list_sources(st.session_state.thread_id)
        }
    valid_references = [
        reference
        for reference in references
        if str(reference.get("id") or "") in allowed_ids
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


def render_message(
    message: dict[str, Any],
    *,
    visible_source_ids: set[str] | None = None,
) -> None:
    role = message["role"]
    with st.chat_message(
        role,
        avatar=(
            ":material/auto_awesome:"
            if role == "assistant"
            else ":material/person:"
        ),
    ):
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
                        rerun_app()
                    if send_column.button(
                        "Send",
                        key=f"save-{message['id']}",
                        type="primary",
                    ):
                        if not revised.strip():
                            st.error("Enter a message before resending.")
                            return
                        draft = revised.strip()
                        thread_id = st.session_state.thread_id
                        idempotency_key = get_retry_key(
                            st.session_state,
                            thread_id=thread_id,
                            stage=f"revise:{message['id']}",
                            prompt=draft,
                        )
                        st.session_state.pending_edit = {
                            "message_id": message["id"],
                            "prompt": draft,
                            "idempotency_key": idempotency_key,
                        }
                        st.session_state.editing_message = None
                        rerun_app()
            return
        if role == "user":
            safe_id = message["id"].replace("-", "_")
            content = str(message["content"])
            with st.container(key=f"user_message_row_{safe_id}"):
                # Own the bubble padding in HTML we control (Streamlit chat chrome
                # keeps resetting padding on stChatMessage).
                escaped = html.escape(content).replace("\n", "<br />")
                st.markdown(
                    f'<div class="cd-user-bubble-text">{escaped}</div>',
                    unsafe_allow_html=True,
                )
                with st.container(key=f"user_message_actions_{safe_id}"):
                    _, copy_column, edit_column = st.columns(
                        [0.76, 0.12, 0.12],
                        gap="small",
                    )
                    with copy_column:
                        _render_copy_control(content)
                    if edit_column.button(
                        "",
                        icon=":material/edit:",
                        key=f"edit-{message['id']}",
                        help="Edit",
                        type="tertiary",
                    ):
                        messages = store.get_messages(st.session_state.thread_id)
                        latest_user = next(
                            (
                                item
                                for item in reversed(messages)
                                if item.get("role") == "user"
                            ),
                            None,
                        )
                        if latest_user and latest_user.get("id") != message["id"]:
                            st.session_state.edit_confirm_message_id = message["id"]
                        else:
                            st.session_state.editing_message = message["id"]
                            st.session_state.edit_confirm_message_id = None
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
    return parse_coaching_turns_since_deep_review(
        metadata.get(COUNTER_SETTINGS_KEY)
    )


def _deep_review_is_available(metadata: dict[str, Any]) -> bool:
    """Return whether notebook metadata currently unlocks Deep Review."""
    return explicit_deep_review_available(
        coaching_turns_since_deep_review=_deep_review_counter(metadata),
        interval=settings.deep_review_interval_turns,
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


def _render_inflight_user_prompt(prompt: str, uploads: list[Any]) -> None:
    """Paint the in-flight student prompt with history bubble markup.

    The pending row has no persisted message id, so it omits edit/copy
    actions. Uploads are named only; they are not source ids.
    """
    with st.chat_message("user", avatar=":material/person:"):
        escaped = html.escape(prompt).replace("\n", "<br />")
        with st.container(key="inflight_user_message_row"):
            st.markdown(
                f'<div class="cd-user-bubble-text">{escaped}</div>',
                unsafe_allow_html=True,
            )
            if uploads:
                st.caption(
                    "Adding to Sources · "
                    + ", ".join(upload.name for upload in uploads)
                )


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

    Uploads become sources first. The coach path always uses ``CoachRequest``
    via the local API or in-process ``CoachApplicationService``, streaming
    progress events and then the final validated reply. On ``done``, this
    helper never keeps completed history only in the composer fragment:
    it remounts once so ``chat_log`` reads persisted messages. ``target``
    must be the in-flight sibling, never ``chat_log``: re-entering that
    keyed history container reuses the last assistant ``st.chat_message``.
    """
    set_coach_turn_streaming(True)
    handle_started = time.perf_counter()
    request_id = str(request_id or uuid.uuid4())
    api_origin = (
        fragment_started if fragment_started is not None else handle_started
    )
    spans: dict[str, float] = dict(fragment_spans or {})
    try:
        journey = normalize_journey(st.session_state.learning_journey)
        list_started = time.perf_counter()
        if uploads:
            sources = store.list_sources(st.session_state.thread_id)
            selected_sources = [source for source in sources if source.get("selected")]
            visible_source_ids = {
                str(source.get("id") or "") for source in sources
            }
            allow_model_knowledge = not selected_sources
        elif visible_source_ids is None:
            sources = store.list_sources(st.session_state.thread_id)
            selected_sources = [source for source in sources if source.get("selected")]
            visible_source_ids = {
                str(source.get("id") or "") for source in sources
            }
            allow_model_knowledge = not selected_sources
        else:
            allow_model_knowledge = bool(
                st.session_state.get("allow_model_knowledge", True)
            )
        spans["source_list_ms"] = _duration_ms(list_started)
        if uploads:
            allow_model_knowledge = False
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
            if uploads:
                try:
                    upload_started = time.perf_counter()
                    store.upload_sources(
                        st.session_state.thread_id,
                        [
                            (
                                upload.name,
                                upload.getvalue(),
                                getattr(upload, "type", None),
                            )
                            for upload in uploads
                        ],
                        origin="chat_composer",
                    )
                    spans["source_upload_ms"] = _duration_ms(upload_started)
                except Exception:
                    # The source service owns transactional/file cleanup. Do not
                    # submit a coach request when its prerequisite upload failed.
                    # Avoid surfacing raw exception text (paths, internals) in the UI.
                    st.error("The attachment could not be added, so no message was sent.")
                    st.caption("Remove or replace the attachment and try again.")
                    sync_chat_scroll(mode="settle")
                    return
                # Drop the pre-upload source memo before persist. The later
                # remount reloads Sources from the post-upload catalog.
                store.forget_source_reads(st.session_state.thread_id)
                post_list_started = time.perf_counter()
                sources = store.list_sources(st.session_state.thread_id)
                visible_source_ids = {
                    str(source.get("id") or "") for source in sources
                }
                spans["source_list_ms"] = round(
                    float(spans.get("source_list_ms") or 0.0)
                    + _duration_ms(post_list_started),
                    1,
                )
            else:
                spans["source_upload_ms"] = 0.0
            # Preserve this key only while the same submitted text is unresolved.
            # The session helper stores a SHA-256 scope, never the prompt itself.
            build_started = time.perf_counter()
            idempotency_key = get_retry_key(
                st.session_state,
                thread_id=st.session_state.thread_id,
                stage=journey["current_stage"],
                prompt=prompt,
            )

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
            )
            spans["request_build_ms"] = _duration_ms(build_started)
            thinking_started = time.perf_counter()
            thinking = st.status(
                "Coach is thinking…",
                expanded=False,
                type="compact",
            )
            spans["thinking_render_ms"] = _duration_ms(thinking_started)
            try:
                turn: CoachTurn | None = None
                thinking_closed = False
                log_ui_timing(
                    request_id=request_id,
                    fragment_to_api_ms=_duration_ms(api_origin),
                    pre_api_ms=_duration_ms(handle_started),
                    fragment_enter_ms=float(spans.get("fragment_enter_ms") or 0.0),
                    prompt_accept_ms=float(spans.get("prompt_accept_ms") or 0.0),
                    composer_layout_ms=float(spans.get("composer_layout_ms") or 0.0),
                    source_list_ms=float(spans.get("source_list_ms") or 0.0),
                    thread_lookup_ms=float(spans.get("thread_lookup_ms") or 0.0),
                    pending_user_render_ms=float(
                        spans.get("pending_user_render_ms") or 0.0
                    ),
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

                for event in stream_coach_turn_events(
                    request, request_id=request_id
                ):
                    kind = event.get("event")
                    if kind == "started" or kind == "graph":
                        continue
                    if kind == "status":
                        phase = str(event.get("phase") or "").strip()
                        label = str(event.get("label") or "").strip()
                        if phase == "retrieving":
                            thinking.update(
                                label=label or "Searching course materials…"
                            )
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
                apply_completed_turn_to_session(
                    turn,
                    thread_id=st.session_state.thread_id,
                    pre_stage=pre_stage,
                    pre_deep_review_available=pre_deep_review_available,
                    pre_deep_review_counter=pre_deep_review_counter,
                )
                # Always remount from persisted history. Painting completed
                # turns only in this fragment would drop them on the next
                # Send. Do not also render_message here or the remount would
                # duplicate the bubble.
                st.session_state.composer_nonce += 1
                rerun_app()
                return
            except CoachTurnStreamError as error:
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

    On failure, clears ``pending_edit`` so a later rerun does not auto-resubmit;
    the student must click Send again. The revise retry key stays in session.

    Returns:
        True when revise succeeded and a rerun was requested; False when the
        edit could not run so the chat panel should keep rendering. On failure,
        clears ``pending_edit``, restores the in-bubble editor draft, and keeps
        the stable revise idempotency key for an explicit Send retry.
    """
    pending = st.session_state.get("pending_edit")
    if not isinstance(pending, dict):
        return False
    message_id = str(pending.get("message_id") or "")
    draft = str(pending.get("prompt") or "").strip()
    if not message_id or not draft:
        st.session_state.pop("pending_edit", None)
        _restore_pending_edit_draft(message_id, draft)
        st.error("Enter a message before resending.")
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
    set_coach_turn_streaming(True)
    thinking = st.status(
        "Coach is thinking…",
        expanded=False,
        type="compact",
    )
    try:
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
                response_language=st.session_state.get("response_language") or "English",
            )
            thinking.update(label="Coach reply ready", state="complete")
        except Exception:
            thinking.update(label="Coaching failed", state="error")
            # Drop pending_edit so the next rerun does not auto-resubmit. Keep the
            # stable retry key in session and reopen the editor so the student must
            # click Send again to retry the same revision attempt.
            st.session_state.pop("pending_edit", None)
            _restore_pending_edit_draft(message_id, draft)
            st.error(
                "Could not finish this edit. Your draft is preserved — click Send "
                "again to retry the same revision attempt without creating another "
                "conversation branch. If the server already applied the revision, "
                "retry resumes the replacement coach reply."
            )
            return False
        remove_retry_key(
            st.session_state,
            thread_id=thread_id,
            stage=f"revise:{message_id}",
            prompt=draft,
        )
        st.session_state.pop("pending_edit", None)
        st.session_state.editing_message = None
        updated_thread = store.get_thread(thread_id) or {}
        updated_metadata = updated_thread.get("metadata") or {}
        updated_journey = normalize_journey(updated_metadata.get("learning_journey"))
        st.session_state.learning_journey = updated_journey
        st.session_state.response_detail = updated_journey["response_detail"]
        st.session_state.composer_nonce += 1
        rerun_app()
        return True
    finally:
        set_coach_turn_streaming(False)


@st.fragment
def _render_composer_submit_fragment(
    model_id: str,
    reasoning_effort: str | None,
    visible_source_ids: set[str],
) -> None:
    """Render the inflight slot and composer; submit without remounting rails.

    Streamlit 1.60 reruns only this fragment when ``st.chat_input`` submits,
    so Journey, Deep Review, Sources, and chat history are not rebuilt
    before FastAPI starts. After a successful persisted turn, one
    ``rerun_app()`` reconciles the authoritative transcript, Thinking Path,
    and Deep Review caption.

    Args:
        model_id: Selected coaching model id for the next turn.
        reasoning_effort: Compatible reasoning effort, or None.
        visible_source_ids: Source ids currently shown in this notebook.
    """
    fragment_started = time.perf_counter()
    fragment_enter_epoch_ms = int(time.time() * 1000)
    request_id = str(uuid.uuid4())
    chat_inflight = st.container(key="chat_inflight")
    with st.container(key="chat_composer"):
        fragment_enter_ms = _duration_ms(fragment_started)
        prompt_started = time.perf_counter()
        composer_value = st.chat_input(
            "Ask a question or share your thinking",
            key=f"composer-{st.session_state.composer_nonce}",
            accept_file="multiple",
            accept_audio=False,
            max_upload_size=settings.max_file_size_mb,
            submit_mode="stop",
            height="content",
        )
        prompt_accept_ms = _duration_ms(prompt_started)
        layout_started = time.perf_counter()
        sync_composer_layout(max_file_size_mb=settings.max_file_size_mb)
        composer_layout_ms = _duration_ms(layout_started)
    prompt, uploads = normalize_composer_value(composer_value)
    if prompt:
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
    if st.session_state.get("pending_edit"):
        # Successful revise calls ``rerun_app()``. On failure, keep rendering the
        # active chat instead of blanking the panel.
        if _submit_pending_edit(
            model_id=model_id,
            reasoning_effort=reasoning_effort,
        ):
            return

    sources = store.list_sources(st.session_state.thread_id)
    selected_sources = [source for source in sources if source.get("selected")]
    allow_model_knowledge = not selected_sources
    st.session_state.allow_model_knowledge = allow_model_knowledge
    seed_coach_welcome(store, st.session_state.thread_id)
    messages = store.get_messages(st.session_state.thread_id)
    visible_source_ids = {
        str(source.get("id") or "") for source in sources
    }
    if st.session_state.get("edit_confirm_message_id"):
        _confirm_edit_earlier_message_dialog()

    journey = normalize_journey(st.session_state.get("learning_journey"))
    hmw_available = hmw_scaffold_available(
        str(journey.get("current_stage") or DEFAULT_STAGE),
        messages,
        enabled=settings.hmw_scaffold_enabled,
    )
    chat_transcript = st.container(key="chat_transcript")
    with chat_transcript:
        chat_log = st.container(key="chat_log")
        history_started = time.perf_counter()
        with chat_log:
            for kind, message in transcript_hmw_render_plan(
                messages,
                hmw_available=hmw_available,
            ):
                if kind == "hmw":
                    render_hmw_scaffold_if_needed(available=True)
                    continue
                if message is None:
                    continue
                render_message(message, visible_source_ids=visible_source_ids)
        log_ui_timing(
            chat_history_ms=round(
                max(0.0, (time.perf_counter() - history_started) * 1000.0),
                1,
            ),
            message_count=len(messages),
        )
        _render_composer_submit_fragment(
            model_id,
            reasoning_effort,
            visible_source_ids,
        )
