"""Top navigation bar for the notebook workspace."""

from __future__ import annotations

import streamlit as st

from backend.title_service import NotebookTitleService
from backend.student_journey import RESPONSE_DETAILS, normalize_journey

from ui.notebooks import notebooks_dialog
from ui.profile import inject_profile_leave_helper, render_profile_menu
from ui.rename import bump_rename_epoch, render_enter_to_apply_rename
from ui.runtime import rerun, store
from ui.session import save_journey
from ui.settings import apply_selected_model


GUIDANCE_LABELS = {
    "short": "Quick",
    "long": "Complex",
}


def _render_guidance_dropdown(journey: dict) -> None:
    """Render a compact guidance menu with no editable text field."""
    current_detail = journey["response_detail"]
    with st.container(key="topbar_mode"):
        with st.popover(GUIDANCE_LABELS[current_detail]):
            for detail in RESPONSE_DETAILS:
                label = GUIDANCE_LABELS[detail]
                if st.button(
                    label,
                    key=f"topbar-guidance-{detail}",
                    use_container_width=True,
                    type="tertiary",
                ):
                    if detail != current_detail:
                        journey["response_detail"] = detail
                        save_journey(journey)
                        rerun()


def render_topbar() -> tuple[str, str | None]:
    """Render brand, notebook title, chats library, guidance, and profile."""
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
            """
            <div class="brand-lockup">
              <div class="brand-mark">C</div>
              <div class="brand-caption">Critical Thinking Companion</div>
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
                    rerun()
        with controls_column.container(key="topbar_actions"):
            chats_column, guidance_label_column, guidance_menu_column = st.columns(
                [0.28, 0.40, 0.32],
                gap="small",
            )
            with chats_column.container(key="topbar_navigation"):
                if st.button(
                    "Notebooks",
                    icon=":material/library_books:",
                    type="tertiary",
                    key="open-notebooks",
                ):
                    notebooks_dialog()
            guidance_label_column.markdown(
                '<p class="topbar-guidance-label">Guidance Level:</p>',
                unsafe_allow_html=True,
            )
            journey = normalize_journey(st.session_state.learning_journey)
            with guidance_menu_column:
                _render_guidance_dropdown(journey)
        with profile_column.container(key="topbar_profile_slot"):
            render_profile_menu()
        inject_profile_leave_helper()
        chosen_model = st.session_state.selected_model
        apply_selected_model(chosen_model)
        chosen_effort = st.session_state.reasoning_effort
    return chosen_model, chosen_effort
