"""Notebook library dialogs without folder management."""

from __future__ import annotations

from datetime import datetime, timezone
from html import escape
from typing import Any

import streamlit as st
import streamlit.components.v1 as components

from backend.student_journey import (
    DEFAULT_RESPONSE_DETAIL,
    DEFAULT_STAGE,
    THINKING_STAGES,
    current_stage,
    journey_progress,
    normalize_journey,
)

from ui.components import empty_state_html
from ui.html_embed import wrap_component_html
from ui.panels.nav import render_transcript_download_control
from ui.runtime import rerun_app, rerun_fragment, store
from ui.rename import (
    render_enter_to_apply_rename,
    sync_rename_select_all,
)
from ui.session import (
    cancel_notebook_actions,
    delete_notebook,
    dismiss_notebooks_dialog,
    new_notebook,
    notebook_switch_locked,
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
            "current_stage": metadata.get("thinking_stage", DEFAULT_STAGE),
            "response_detail": metadata.get(
                "response_detail", DEFAULT_RESPONSE_DETAIL
            ),
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
        "messages": int(thread.get("messageCount") or 0),
        "last_active": _relative_activity(
            thread.get("lastActivity")
            or thread.get("updatedAt")
            or thread.get("createdAt")
        ),
        "helpful": 0,
        "review": 0,
    }


def _relative_activity(value: Any, *, now: datetime | None = None) -> str:
    """Format a persisted activity timestamp as concise notebook metadata."""
    raw = str(value or "").strip()
    if not raw:
        return "Unknown"
    try:
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return "Unknown"
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    current = now or datetime.now(timezone.utc)
    if current.tzinfo is None:
        current = current.replace(tzinfo=timezone.utc)
    activity_date = parsed.astimezone(current.tzinfo).date()
    elapsed_days = max(0, (current.date() - activity_date).days)
    if elapsed_days == 0:
        return "today"
    if elapsed_days == 1:
        return "yesterday"
    if elapsed_days < 7:
        return f"{elapsed_days} days ago"
    return parsed.astimezone(current.tzinfo).strftime("%d %b %Y")


@st.dialog(
    "Your Notebooks",
    width="large",
    on_dismiss=dismiss_notebooks_dialog,
)
def notebooks_dialog() -> None:
    """Render the notebook library, with an inline actions panel when needed.

    Rename / download / delete stay inside this dialog so delete never
    dismisses Your Notebooks. Only X, outside click, or Esc closes it.
    """
    pending_id = str(st.session_state.get("pending_notebook_actions") or "").strip()
    if pending_id:
        if _render_notebook_actions_panel(pending_id):
            return
        # Missing notebook: pending cleared; show the list in this same open.

    _render_notebook_library_list()


def _return_to_notebook_list() -> None:
    """Return the open dialog to its list view with a fragment rerun.

    Your Notebooks is a Streamlit dialog (and therefore a fragment).  Its
    Actions and Back controls only change dialog-local state, so a fragment
    rerun replaces the dialog body without rebuilding the workspace shell.
    """
    cancel_notebook_actions()
    rerun_fragment()


def _on_notebook_actions(thread_id: str) -> None:
    """Show one notebook's actions in the current dialog fragment.

    Args:
        thread_id: Persisted notebook identifier whose actions should be shown.

    Side effects:
        Updates dialog-local session state.  Because this is a widget callback,
        Streamlit reruns the owning dialog fragment automatically.
    """
    request_notebook_actions(thread_id)


def _on_notebook_actions_back() -> None:
    """Return from notebook Actions to the list in the dialog fragment.

    The callback runs before the fragment body is painted, so clearing the
    pending id makes the same fragment render the list without a second app
    rerun or a stacked action/list body.
    """
    cancel_notebook_actions()


def _on_dialog_new_notebook() -> None:
    """Create a notebook before the workspace paints; leave Your Notebooks closed.

    Runs as ``on_click`` so Chat/Recents see the new ``thread_id`` on the click's
    single remount. Arms the course-materials toast; session init must not.
    """
    st.session_state.pending_notebook_actions = None
    st.session_state.reopen_notebooks_dialog = False
    st.session_state.pop("_notebooks_suppress_dismiss", None)
    st.session_state.toast_course_materials_loading = True
    new_notebook(should_rerun=False)


def _on_dialog_open_notebook(thread_id: str) -> None:
    """Open a notebook before the workspace paints; leave Your Notebooks closed."""
    target = str(thread_id or "").strip()
    if not target:
        return
    st.session_state.pending_notebook_actions = None
    st.session_state.reopen_notebooks_dialog = False
    st.session_state.pop("_notebooks_suppress_dismiss", None)
    select_thread(target, should_rerun=False)


def _render_notebook_library_list() -> None:
    """Search, create, open, and open the inline actions panel."""
    locked = notebook_switch_locked()
    st.caption("Continue a discussion or start a new inquiry.")
    if locked:
        st.caption("Wait for the coach reply before switching notebooks.")
    search_column, new_column = st.columns([0.77, 0.23])
    search = search_column.text_input(
        "Search notebooks",
        placeholder="Search notebooks",
        label_visibility="collapsed",
        key="notebook-search",
    )
    new_column.button(
        "New notebook",
        icon=":material/add:",
        type="primary",
        use_container_width=True,
        disabled=locked,
        help="Wait for the coach reply" if locked else None,
        on_click=_on_dialog_new_notebook,
    )

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
                    notebook_title = escape(
                        thread.get("name") or "Untitled notebook"
                    )
                    title_column.markdown(
                        '<div class="notebook-card-copy">'
                        '<div class="notebook-card-title">'
                        f'<span class="notebook-card-title-text" title="{notebook_title}">'
                        f"{notebook_title}"
                        "</span>"
                        f"{current_badge}</div>"
                        f'<div class="notebook-card-meta">'
                        f"{escape(overview['stage'].label)} · "
                        f"{overview['stage_index']} of {len(THINKING_STAGES)} stages</div>"
                        f'<div class="notebook-card-activity">'
                        f"Last active {escape(overview['last_active'])}</div>"
                        "</div>",
                        unsafe_allow_html=True,
                    )
                    open_disabled = locked and not is_active
                    open_column.button(
                        "Open",
                        use_container_width=True,
                        type="secondary",
                        key=f"open-notebook-{thread['id']}",
                        disabled=open_disabled,
                        help="Wait for the coach reply" if open_disabled else None,
                        on_click=_on_dialog_open_notebook,
                        args=(thread["id"],),
                    )
                    actions_disabled = locked
                    menu_column.button(
                        "⋯",
                        type="tertiary",
                        key=f"notebook-actions-{thread['id']}",
                        disabled=actions_disabled,
                        help="Wait for the coach reply" if actions_disabled else None,
                        on_click=_on_notebook_actions,
                        args=(thread["id"],),
                    )

    _sync_notebook_library_scroll()


def _render_notebook_actions_panel(thread_id: str) -> bool:
    """Render rename / download / delete for one notebook.

    Returns:
        ``True`` when the actions panel owns the dialog body.
        ``False`` only when the notebook is missing so the list can render.
        Back and rename return to the list with a dialog-fragment rerun so the
        application workspace is not rebuilt. Delete keeps its app-scoped
        rerun when the active notebook must be reconciled.
    """
    thread = store.get_thread(thread_id)
    if not thread:
        cancel_notebook_actions()
        return False

    st.button(
        "Back to notebooks",
        icon=":material/arrow_back:",
        type="tertiary",
        key=f"notebook-actions-back-{thread_id}",
        on_click=_on_notebook_actions_back,
    )

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
            f"{overview['stage'].label} · phase {overview['stage_index']} "
            f"of {len(THINKING_STAGES)}"
        )
        if applied and cleaned and cleaned != current_title:
            store.update_thread(thread_id, name=cleaned)
            _return_to_notebook_list()
        sync_rename_select_all(
            root_selector='[role="dialog"]:has(.st-key-notebook_actions_panel)',
            aria_label="Rename",
        )

        with st.container(key="notebook_action_export"):
            render_transcript_download_control(
                str(thread_id),
                key_prefix="notebook-actions",
                button_type="secondary",
                help_text="Save this notebook's chat from persisted messages",
            )

        with st.container(key="notebook_action_danger"):
            st.markdown("#### Delete notebook")
            locked = notebook_switch_locked()
            if locked:
                st.caption("Wait for the coach reply before deleting this notebook.")
            confirm = st.checkbox(
                "I understand this cannot be undone",
                key=f"confirm-delete-{thread_id}",
                disabled=locked,
            )
            if st.button(
                "Delete permanently",
                icon=":material/delete:",
                use_container_width=True,
                disabled=locked or not confirm,
                key=f"delete-notebook-{thread_id}",
            ):
                # Remount list-only; do not draw the library under this panel.
                delete_notebook(thread_id)
                rerun_app()

    return True


def _sync_notebook_library_scroll() -> None:
    """Keep the notebook list scrollable and pinned to the top on open."""
    components.html(
        wrap_component_html(
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
            """
        ),
        height=0,
    )
