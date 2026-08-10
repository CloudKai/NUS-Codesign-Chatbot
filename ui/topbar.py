"""Top navigation bar for the notebook workspace."""

from __future__ import annotations

import streamlit as st

from backend.title_service import NotebookTitleService
from backend.student_journey import RESPONSE_DETAILS, normalize_journey

from ui.notebooks import notebooks_dialog
from ui.menu_popovers import close_menu_popover, menu_popover_widget_key
from ui.profile import inject_profile_leave_helper, render_profile_menu
from ui.rename import bump_rename_epoch, render_enter_to_apply_rename
from ui.runtime import rerun_app, rerun_fragment, store
from ui.session import save_journey
from ui.settings import apply_selected_model


GUIDANCE_LABELS = {
    "short": "Quick",
    "long": "Complex",
}


@st.fragment
def _render_guidance_fragment() -> None:
    """Guidance Level control; fragment-scoped so Chat/Journey do not redraw."""
    st.session_state["_topbar_guidance_fragment_runs"] = (
        int(st.session_state.get("_topbar_guidance_fragment_runs") or 0) + 1
    )
    journey = normalize_journey(st.session_state.learning_journey)
    current_detail = journey["response_detail"]
    with st.container(key="topbar_mode"):
        with st.popover(
            GUIDANCE_LABELS[current_detail],
            key=menu_popover_widget_key("topbar-guidance"),
        ):
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
                    close_menu_popover("topbar-guidance")
                    rerun_fragment()


@st.fragment
def _render_profile_fragment() -> None:
    """Profile menu; local preference edits stay fragment-scoped."""
    st.session_state["_topbar_profile_fragment_runs"] = (
        int(st.session_state.get("_topbar_profile_fragment_runs") or 0) + 1
    )
    render_profile_menu()


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
                    rerun_app()
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
            with guidance_menu_column:
                _render_guidance_fragment()
        with profile_column.container(key="topbar_profile_slot"):
            _render_profile_fragment()
        inject_profile_leave_helper()
        chosen_model = st.session_state.selected_model
        apply_selected_model(chosen_model)
        chosen_effort = st.session_state.reasoning_effort
    return chosen_model, chosen_effort
