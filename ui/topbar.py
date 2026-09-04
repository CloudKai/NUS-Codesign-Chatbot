"""Nonvisual workspace preparation retained from the retired top bar."""

from __future__ import annotations

import streamlit as st

from backend.title_service import NotebookTitleService

from ui.runtime import store
from ui.settings import apply_selected_model


def prepare_workspace_context() -> tuple[str, str | None]:
    """Prepare title compatibility and return the active model configuration.

    The Gemini-inspired shell no longer renders a global top bar, but legacy
    notebook-title normalization and model selection must still run before the
    workspace mounts.

    Returns:
        The selected model id and optional reasoning effort.
    """
    thread = store.get_thread(st.session_state.thread_id) or {}
    legacy_title_replacement = NotebookTitleService.replacement_for_legacy_title(
        str(thread.get("name") or ""),
        store.get_oldest_user_messages(st.session_state.thread_id, limit=2),
    )
    if legacy_title_replacement:
        store.update_thread(
            st.session_state.thread_id,
            name=legacy_title_replacement,
        )
        thread = store.get_thread(st.session_state.thread_id) or thread
    chosen_model = st.session_state.selected_model
    apply_selected_model(chosen_model)
    chosen_effort = st.session_state.reasoning_effort
    return chosen_model, chosen_effort
