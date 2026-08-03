"""Notebook library dialogs without folder management."""

from __future__ import annotations

from html import escape
from typing import Any

import streamlit as st

from backend.student_journey import (
    THINKING_STAGES,
    current_stage,
    journey_progress,
    normalize_journey,
)

from ui.components import empty_state_html
from ui.runtime import rerun, store
from ui.session import (
    cancel_notebook_actions,
    delete_notebook,
    new_notebook,
    request_notebook_actions,
    select_thread,
)


def thread_overview(thread: dict[str, Any]) -> dict[str, Any]:
    """Summarize a notebook card for the library list."""
    metadata = thread.get("metadata") or {}
    journey = normalize_journey(
        metadata.get("learning_journey")
        if isinstance(metadata.get("learning_journey"), dict)
        else {
            "current_stage": metadata.get("thinking_stage", "focus"),
            "response_detail": metadata.get("response_detail", "short"),
        }
    )
    stage = current_stage(journey)
    stage_index = next(
        index
        for index, item in enumerate(THINKING_STAGES, start=1)
        if item.id == stage.id
    )
    summary = str(journey.get("working_conclusion") or "").strip()
    if not summary:
        for item in reversed(THINKING_STAGES):
            note = str(journey["stage_notes"].get(item.id, "") or "").strip()
            if note:
                summary = note
                break
    if not summary:
        summary = str(thread.get("latestUserMessage") or "").strip()
    return {
        "stage": stage,
        "stage_index": stage_index,
        "progress": journey_progress(journey),
        "summary": " ".join(summary.split())[:160] or "No learning summary yet.",
        "turns": int(thread.get("studentTurnCount") or 0),
        "helpful": int(thread.get("helpfulCount") or 0),
        "review": int(thread.get("needsReviewCount") or 0),
    }


@st.dialog("Your notebooks", width="large")
def notebooks_dialog() -> None:
    """Render a folder-free notebook library with search and actions."""
    st.caption("Continue a discussion or start a new inquiry.")
    search_column, new_column = st.columns([0.77, 0.23])
    search = search_column.text_input(
        "Search notebooks",
        placeholder="Search notebooks",
        label_visibility="collapsed",
        key="notebook-search",
    )
    if new_column.button(
        "New notebook",
        icon=":material/add:",
        type="primary",
        use_container_width=True,
    ):
        new_notebook()

    threads = store.list_threads(search, None)
    st.caption(f"{len(threads)} notebook{'s' if len(threads) != 1 else ''}")
    with st.container(key="notebook_library_scroll"):
        st.markdown('<div class="cd-notebook-list">', unsafe_allow_html=True)
        if not threads:
            st.markdown(
                empty_state_html(
                    title="No notebooks yet",
                    body="Start a new notebook to begin a critical-thinking discussion.",
                ),
                unsafe_allow_html=True,
            )
            return
        active_id = st.session_state.get("thread_id")
        for thread in threads:
            overview = thread_overview(thread)
            safe_id = thread["id"].replace("-", "_")
            is_active = thread["id"] == active_id
            card_class = "cd-notebook-card is-active" if is_active else "cd-notebook-card"
            with st.container(key=f"notebook_card_{safe_id}"):
                st.markdown(f'<div class="{card_class}">', unsafe_allow_html=True)
                title_column, open_column, menu_column = st.columns(
                    [0.72, 0.18, 0.1],
                    gap="small",
                )
                title_column.markdown(
                    '<div class="notebook-card-title">'
                    f"{escape(thread.get('name') or 'Untitled notebook')}</div>",
                    unsafe_allow_html=True,
                )
                if open_column.button(
                    "Open",
                    use_container_width=True,
                    type="primary" if is_active else "tertiary",
                    key=f"open-notebook-{thread['id']}",
                ):
                    select_thread(thread["id"])
                if menu_column.button(
                    "Notebook actions",
                    icon=":material/more_horiz:",
                    type="tertiary",
                    key=f"notebook-actions-{thread['id']}",
                    help="Rename or delete this notebook",
                ):
                    request_notebook_actions(thread["id"])
                    rerun()
                st.markdown(
                    f'<div class="notebook-card-meta">'
                    f"{escape(overview['stage'].short_label)} · "
                    f"phase {overview['stage_index']} of 6</div>"
                    f'<div class="notebook-card-summary">'
                    f"{escape(overview['summary'])}</div>",
                    unsafe_allow_html=True,
                )
                st.markdown("</div>", unsafe_allow_html=True)
        st.markdown("</div>", unsafe_allow_html=True)


@st.dialog(
    "Notebook actions",
    width="small",
    on_dismiss=cancel_notebook_actions,
)
def notebook_actions_dialog() -> None:
    """Rename or delete a notebook with confirmation."""
    thread_id = st.session_state.get("pending_notebook_actions")
    thread = store.get_thread(thread_id) if thread_id else None
    if not thread:
        cancel_notebook_actions()
        return
    title = escape(thread.get("name") or "Untitled notebook")
    overview = thread_overview(thread)
    st.markdown(
        '<div class="notebook-actions-context">Editing '
        f'<strong>“{title}”</strong></div>',
        unsafe_allow_html=True,
    )
    st.caption(
        f"{overview['stage'].short_label} · phase {overview['stage_index']} of 6"
    )

    renamed = st.text_input(
        "Rename",
        value=thread.get("name") or "",
        key=f"rename-notebook-{thread_id}",
    )
    if st.button(
        "Save title",
        icon=":material/edit:",
        use_container_width=True,
        key=f"rename-notebook-button-{thread_id}",
    ):
        store.update_thread(thread_id, name=renamed)
        rerun()

    messages = store.get_messages(thread_id)
    if messages:
        transcript = "\n\n".join(
            f"{message['role'].title()}: {message['content']}"
            for message in messages
        )
        st.download_button(
            "Download transcript",
            transcript,
            file_name=f"{thread.get('name') or 'notebook'}.txt",
            mime="text/plain",
            use_container_width=True,
            key=f"download-notebook-{thread_id}",
        )

    with st.container(key="notebook_action_danger"):
        st.markdown("#### Delete notebook")
        confirm = st.checkbox(
            "I understand this cannot be undone",
            key=f"confirm-delete-{thread_id}",
        )
        if st.button(
            "Delete permanently",
            icon=":material/delete:",
            use_container_width=True,
            disabled=not confirm,
        ):
            delete_notebook(thread_id)
            rerun()
