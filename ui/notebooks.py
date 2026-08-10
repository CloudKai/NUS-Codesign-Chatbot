"""Notebook library dialogs without folder management."""

from __future__ import annotations

from html import escape
from typing import Any

import streamlit as st
import streamlit.components.v1 as components

from backend.student_journey import (
    THINKING_STAGES,
    current_stage,
    journey_progress,
    normalize_journey,
)

from ui.components import empty_state_html
from ui.runtime import rerun, store
from ui.rename import (
    render_enter_to_apply_rename,
    sync_rename_select_all,
)
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
        "helpful": 0,
        "review": 0,
    }


@st.dialog("Your Notebooks", width="large")
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
    with st.container(key="notebook_library_scroll", height=360):
        if not threads:
            st.markdown(
                empty_state_html(
                    title="No notebooks yet",
                    body="Start a new notebook to begin a critical-thinking discussion.",
                ),
                unsafe_allow_html=True,
            )
        else:
            active_id = st.session_state.get("thread_id")
            for thread in threads:
                overview = thread_overview(thread)
                safe_id = thread["id"].replace("-", "_")
                is_active = thread["id"] == active_id
                card_key = f"notebook_card_{safe_id}"
                with st.container(key=card_key):
                    title_column, open_column, menu_column = st.columns(
                        [0.68, 0.2, 0.12],
                        gap="small",
                    )
                    current_badge = (
                        '<span class="notebook-current-badge">Current</span>'
                        if is_active
                        else ""
                    )
                    title_column.markdown(
                        '<div class="notebook-card-copy">'
                        '<div class="notebook-card-title">'
                        f"{escape(thread.get('name') or 'Untitled notebook')}"
                        f"{current_badge}</div>"
                        f'<div class="notebook-card-meta">'
                        f"{escape(overview['stage'].short_label)} · "
                        f"{overview['stage_index']} of 6</div>"
                        "</div>",
                        unsafe_allow_html=True,
                    )
                    if open_column.button(
                        "Open",
                        use_container_width=True,
                        type="secondary",
                        key=f"open-notebook-{thread['id']}",
                    ):
                        select_thread(thread["id"])
                    if menu_column.button(
                        "⋯",
                        type="tertiary",
                        key=f"notebook-actions-{thread['id']}",
                        help="Rename or delete this notebook",
                    ):
                        request_notebook_actions(thread["id"])
                        rerun()

    _sync_notebook_library_scroll()


def _sync_notebook_library_scroll() -> None:
    """Keep the notebook list scrollable and pinned to the top on open."""
    components.html(
        """
<script>
(() => {
  const doc = window.parent.document;
  const win = window.parent;

  function scrollRoot() {
    return doc.querySelector(".st-key-notebook_library_scroll");
  }

  function clearNestedScroll(root) {
    root
      .querySelectorAll(
        "[data-testid='stLayoutWrapper'], [data-testid='stElementContainer'], [class*='st-key-notebook_card_']"
      )
      .forEach((node) => {
        if (node === root) return;
        node.style.setProperty("height", "auto", "important");
        node.style.setProperty("max-height", "none", "important");
        node.style.setProperty("min-height", "0", "important");
        node.style.setProperty("flex", "0 0 auto", "important");
        node.style.setProperty("overflow", "visible", "important");
      });
  }

  function apply() {
    const dialog = doc.querySelector('[role="dialog"]:has(.st-key-notebook-search)');
    const root = scrollRoot();
    if (!dialog || !root) return false;

    const dialogBody = dialog.querySelector(":scope > [data-testid='stVerticalBlock']");
    if (dialogBody) {
      dialogBody.style.setProperty("gap", "0", "important");
      dialogBody.style.setProperty("row-gap", "0", "important");
    }

    clearNestedScroll(root);
    root.style.setProperty("padding", "0", "important");
    root.style.setProperty("height", "360px", "important");
    root.style.setProperty("max-height", "360px", "important");
    root.style.setProperty("min-height", "0", "important");
    root.style.setProperty("overflow-y", "auto", "important");
    root.style.setProperty("overflow-x", "hidden", "important");
    root.style.setProperty("overscroll-behavior", "contain", "important");
    root.style.setProperty("scrollbar-width", "thin", "important");
    root.classList.toggle(
      "is-scrollable",
      root.scrollHeight > root.clientHeight + 1
    );
    if (!root.dataset.cdNotebookScrollReady) {
      root.scrollTop = 0;
      root.dataset.cdNotebookScrollReady = "1";
    }

    return true;
  }

  function schedule() {
    win.requestAnimationFrame(apply);
  }

  function boot() {
    if (apply()) return;
    let attempts = 0;
    const timer = win.setInterval(() => {
      attempts += 1;
      if (apply() || attempts > 80) win.clearInterval(timer);
    }, 80);
  }

  boot();
  win.addEventListener("resize", schedule);
})();
</script>
        """,
        height=0,
    )


@st.dialog(
    "Notebook Actions",
    width="small",
    on_dismiss=cancel_notebook_actions,
)
def notebook_actions_dialog() -> None:
    """Rename only when Enter submits the form; delete with confirmation.

    Dismissing (X, click outside, or Esc) clears the pending action and reopens
    Your Notebooks on the next script run.
    """
    thread_id = st.session_state.get("pending_notebook_actions")
    thread = store.get_thread(thread_id) if thread_id else None
    if not thread:
        cancel_notebook_actions()
        return

    current_title = str(thread.get("name") or "").strip() or "Untitled notebook"
    overview = thread_overview(thread)
    with st.container(key="notebook_actions_panel"):
        applied, cleaned = render_enter_to_apply_rename(
            kind="notebook",
            item_id=str(thread_id),
            label="Rename",
            current_value=current_title,
        )
        st.caption(
            f"{overview['stage'].short_label} · phase {overview['stage_index']} of 6"
        )
        if applied and cleaned and cleaned != current_title:
            store.update_thread(thread_id, name=cleaned)
            rerun()
        sync_rename_select_all(
            root_selector='[role="dialog"]:has(.st-key-notebook_actions_panel)',
            aria_label="Rename",
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
