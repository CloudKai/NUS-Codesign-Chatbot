"""Top navigation bar for the notebook workspace."""

from __future__ import annotations

import streamlit as st

from backend.title_service import NotebookTitleService

from ui.notebooks import notebooks_dialog
from ui.constants import PRODUCT_SUBTITLE, PRODUCT_TITLE
from ui.profile import inject_profile_leave_helper, render_profile_menu
from ui.rename import bump_rename_epoch, render_enter_to_apply_rename
from ui.runtime import rerun_app, store
from ui.settings import apply_selected_model


def render_topbar() -> tuple[str, str | None]:
    """Render course identity, notebook title, notebook library, and profile."""
    thread = store.get_thread(st.session_state.thread_id) or {}
    legacy_title_replacement = NotebookTitleService.replacement_for_legacy_title(
        str(thread.get("name") or ""),
        [
            str(message.get("content") or "")
            for message in store.get_messages(st.session_state.thread_id)
            if message.get("role") == "user"
        ],
    )
    if legacy_title_replacement:
        store.update_thread(
            st.session_state.thread_id,
            name=legacy_title_replacement,
        )
        thread = store.get_thread(st.session_state.thread_id) or thread
    current_title = thread.get("name") or "Untitled notebook"
    with st.container(key="notebook_topbar"):
        brand_column, title_column, controls_column, profile_column = st.columns(
            [1.35, 2.4, 1.2, 0.32],
            gap="small",
        )
        brand_column.markdown(
            f"""
            <div class="brand-lockup">
              <div class="brand-mark">C</div>
              <div class="brand-copy">
                <div class="brand-title">{PRODUCT_TITLE}</div>
                <div class="brand-subtitle">{PRODUCT_SUBTITLE}</div>
              </div>
            </div>
            """,
            unsafe_allow_html=True,
        )
        with title_column:
            with st.container(key="current_notebook_identity"):
                thread_id = str(st.session_state.thread_id)
                applied, cleaned_title = render_enter_to_apply_rename(
                    kind="topbar",
                    item_id=thread_id,
                    label="Notebook title",
                    current_value=str(current_title),
                    max_chars=50,
                    label_visibility="collapsed",
                )
                if applied and cleaned_title and cleaned_title != current_title:
                    store.update_thread(thread_id, name=cleaned_title)
                    bump_rename_epoch("topbar", thread_id)
                    rerun_app()
        with controls_column.container(key="topbar_actions"):
            with st.container(key="topbar_navigation"):
                if st.button(
                    "Notebooks",
                    icon=":material/library_books:",
                    type="tertiary",
                    key="open-notebooks",
                ):
                    notebooks_dialog()
        with profile_column.container(key="topbar_profile_slot"):
            # Appearance owns an app-scoped widget rerun; display name and
            # language/coaching style remain nested fragments in the menu.
            render_profile_menu()
        inject_profile_leave_helper()
        chosen_model = st.session_state.selected_model
        apply_selected_model(chosen_model)
        chosen_effort = st.session_state.reasoning_effort
    return chosen_model, chosen_effort
