"""Discussion panel, message rendering, and composer handling."""

from __future__ import annotations

import base64
import html
import mimetypes
from pathlib import Path
from typing import Any

import streamlit as st
import streamlit.components.v1 as components

from backend.chat_service import ChatOptions
from backend.domain import CoachRequest
from backend.models import MODEL_REGISTRY, get_model
from backend.settings import settings
from backend.source_library import add_file_sources, selected_source_context
from backend.student_journey import (
    STAGE_BY_ID,
    advanced_stage_response,
    concise_coach_response,
    normalize_journey,
    personalized_stage_questions,
)
from backend.student_support import DEFAULT_SUPPORT_MODE

from ui.coach_welcome import COACH_WELCOME_KIND, seed_coach_welcome
from ui.layout.composer_layout import sync_composer_layout
from ui.runtime import engine, local_api_client, local_api_enabled, rerun, store
from ui.settings import apply_selected_model
from ui.sources import source_viewer_dialog


def _render_composer_model_picker() -> None:
    """Render a compact model dropdown beside the attach control."""
    current = get_model(st.session_state.selected_model)
    with st.container(key="composer_model_slot"):
        with st.popover(current.label):
            for model in MODEL_REGISTRY:
                label = f"{model.label}{' · Legacy' if model.deprecated else ''}"
                if st.button(
                    label,
                    key=f"composer-model-{model.id}",
                    use_container_width=True,
                    type="primary" if model.id == current.id else "tertiary",
                ):
                    if model.id != current.id:
                        apply_selected_model(model.id)
                        store.update_thread(
                            st.session_state.thread_id,
                            metadata={"selected_model": model.id},
                        )
                        rerun()

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


def render_citations(message: dict[str, Any]) -> None:
    """Render cited sources: one or two inline, three or more in a dropdown."""
    references = (message.get("metadata") or {}).get("source_refs") or []
    valid_references = [
        reference
        for reference in references
        if store.get_source(st.session_state.thread_id, str(reference.get("id") or ""))
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
    """Render a Copy control whose click stays in-iframe (clipboard gesture works)."""
    encoded = base64.b64encode(text.encode("utf-8")).decode("ascii")
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
    background: transparent;
    overflow: hidden;
  }}
  button {{
    display: inline-flex;
    align-items: center;
    justify-content: center;
    width: 28px;
    height: 28px;
    margin: 0;
    padding: 0;
    border: 0;
    border-radius: 7px;
    color: #9aa8b5;
    background: rgba(15, 20, 25, 0.72);
    cursor: pointer;
  }}
  button:hover {{
    color: #f2f5f7;
    background: rgba(15, 20, 25, 0.9);
  }}
  button.copied {{
    color: #5eead4;
  }}
  svg {{
    width: 15px;
    height: 15px;
    fill: currentColor;
  }}
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
        height=30,
        width=34,
    )


def render_message(message: dict[str, Any]) -> None:
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
                revised = st.text_area(
                    "Edit message",
                    value=message["content"],
                    key=f"edit-text-{message['id']}",
                    label_visibility="collapsed",
                    height=120,
                )
                with st.container(key=f"user_message_edit_actions_{safe_id}"):
                    cancel_column, send_column = st.columns(2, gap="small")
                    if cancel_column.button(
                        "Cancel",
                        key=f"cancel-{message['id']}",
                        type="secondary",
                    ):
                        st.session_state.editing_message = None
                        rerun()
                    if send_column.button(
                        "Send",
                        key=f"save-{message['id']}",
                        type="primary",
                    ):
                        if not revised.strip():
                            st.error("Enter a message before resending.")
                            return
                        st.session_state.pending_edit = {
                            "message_id": message["id"],
                            "prompt": revised.strip(),
                        }
                        st.session_state.editing_message = None
                        rerun()
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
                        st.session_state.editing_message = message["id"]
                        rerun()
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
                str(metadata.get("thinking_stage") or "focus"),
                auto_advanced_to,
                questions,
            )
        st.markdown(concise_coach_response(display_content))
        render_citations(message)
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


def handle_prompt(
    prompt: str,
    uploads: list[Any],
    model_id: str,
    reasoning_effort: str | None,
    target: Any,
    existing_user_message_id: str | None = None,
) -> None:
    """Submit one student turn via the local API or legacy chat engine.

    When ``USE_LOCAL_API`` is enabled, uploads are added as sources and the
    typed ``CoachRequest`` path runs (stage recommendations, image grounding).
    Otherwise the legacy ``StudentChatEngine`` streams a response without
    mutating the learning journey.
    """
    journey = normalize_journey(st.session_state.learning_journey)
    selected_sources = store.list_sources(
        st.session_state.thread_id,
        selected_only=True,
    )
    allow_model_knowledge = not selected_sources and not uploads
    st.session_state.allow_model_knowledge = allow_model_knowledge
    options = ChatOptions(
        model_id=model_id,
        reasoning_effort=reasoning_effort,
        support_mode=DEFAULT_SUPPORT_MODE,
        web_search=False,
        image_generation=False,
        local_analysis=False,
        assignment=st.session_state.assignment,
        thinking_stage=journey["current_stage"],
        response_detail=journey["response_detail"],
        response_language=st.session_state.response_language,
        source_ids=[source["id"] for source in selected_sources],
        allow_model_knowledge=allow_model_knowledge,
        existing_user_message_id=existing_user_message_id,
    )
    upload_tuples = [
        (upload.name, upload.getvalue(), getattr(upload, "type", None))
        for upload in uploads
    ]
    with target:
        if existing_user_message_id is None:
            with st.chat_message("user", avatar=":material/person:"):
                st.write(prompt)
                if uploads:
                    st.caption(
                        "Adding to Sources · "
                        + ", ".join(upload.name for upload in uploads)
                    )
        if local_api_enabled():
            if upload_tuples:
                add_file_sources(
                    store,
                    st.session_state.thread_id,
                    upload_tuples,
                    origin="chat_composer",
                )
                selected_sources = store.list_sources(
                    st.session_state.thread_id,
                    selected_only=True,
                )
            source_context, source_references = selected_source_context(selected_sources)
            request = CoachRequest(
                thread_id=st.session_state.thread_id,
                student_message=prompt,
                current_stage=journey["current_stage"],
                response_detail=journey["response_detail"],
                source_ids=[reference["id"] for reference in source_references],
                source_context=source_context,
                allow_model_knowledge=allow_model_knowledge,
            )
            with st.chat_message("assistant", avatar=":material/auto_awesome:"):
                try:
                    turn = local_api_client().coach_turn(request)
                    st.write(turn.response_text)
                    if turn.pending_transition:
                        st.caption("The coach has recommended a next step in Thinking Path.")
                except Exception as exc:
                    st.error(
                        "The local coaching API is unavailable. Start it with "
                        "`sh scripts/start.sh`, then retry. "
                        f"({exc})"
                    )
                    if st.button(
                        "Retry",
                        icon=":material/refresh:",
                        key="retry-coach-api",
                    ):
                        st.session_state.pending_edit = {
                            "message_id": existing_user_message_id,
                            "prompt": prompt,
                        }
                        rerun()
                    return
        else:
            stream = engine.submit(
                st.session_state.thread_id,
                prompt,
                options,
                upload_tuples,
            )
            with st.chat_message("assistant", avatar=":material/auto_awesome:"):
                st.write_stream(stream)
                if stream.sources:
                    with st.expander(f"Web sources ({len(stream.sources)})"):
                        for source in stream.sources:
                            st.markdown(f"- [{source['title']}]({source['url']})")
                render_media([str(path) for path in stream.artifacts])
    updated_thread = store.get_thread(st.session_state.thread_id) or {}
    updated_metadata = updated_thread.get("metadata") or {}
    updated_journey = normalize_journey(updated_metadata.get("learning_journey"))
    st.session_state.learning_journey = updated_journey
    st.session_state.response_detail = updated_journey["response_detail"]
    st.session_state.composer_nonce += 1
    rerun()


def render_chat_panel(model_id: str, reasoning_effort: str | None) -> None:
    """Render the discussion log, coach welcome history, and chat composer.

    Args:
        model_id: Locked coaching model id for the next turn.
        reasoning_effort: Compatible reasoning effort for that model, or None.
    """
    selected_sources = store.list_sources(
        st.session_state.thread_id,
        selected_only=True,
    )
    allow_model_knowledge = not selected_sources
    st.session_state.allow_model_knowledge = allow_model_knowledge
    seed_coach_welcome(store, st.session_state.thread_id)
    messages = store.get_messages(st.session_state.thread_id)
    chat_log = st.container(key="chat_log")
    with chat_log:
        for message in messages:
            render_message(message)
        if messages and messages[-1]["role"] == "assistant":
            previous_user = next(
                (
                    message
                    for message in reversed(messages[:-1])
                    if message["role"] == "user"
                ),
                None,
            )
            if previous_user and st.button(
                "Regenerate",
                icon=":material/refresh:",
                type="tertiary",
                key="regenerate-response",
            ):
                st.session_state.pending_edit = {
                    "message_id": previous_user["id"],
                    "prompt": previous_user["content"],
                }
                rerun()
    with st.container(key="chat_composer"):
        _render_composer_model_picker()
        composer_value = st.chat_input(
            "Ask a question or share your thinking",
            key=f"composer-{st.session_state.composer_nonce}",
            accept_file="multiple",
            accept_audio=False,
            max_upload_size=settings.max_file_size_mb,
            submit_mode="stop",
            height="content",
        )
        sync_composer_layout()
    pending_edit = st.session_state.pop("pending_edit", None)
    prompt, uploads = normalize_composer_value(
        (pending_edit or {}).get("prompt") or composer_value
    )
    if prompt:
        handle_prompt(
            prompt,
            uploads,
            model_id,
            reasoning_effort,
            chat_log,
            existing_user_message_id=(pending_edit or {}).get("message_id"),
        )
