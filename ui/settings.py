"""Preference persistence callbacks shared by the profile menu."""

from __future__ import annotations

import streamlit as st

from backend.models import get_model

from ui.runtime import store


def persist_response_language() -> None:
    """Persist the response language immediately when its setting changes."""
    chosen_language = str(st.session_state.setting_response_language)
    st.session_state.response_language = chosen_language
    store.update_thread(
        st.session_state.thread_id,
        metadata={"response_language": chosen_language},
    )


def apply_selected_model(model_id: str) -> None:
    """Apply a model choice and keep reasoning effort compatible with it."""
    selected = get_model(str(model_id))
    st.session_state.selected_model = selected.id
    efforts = list(selected.reasoning_efforts)
    if efforts:
        current = st.session_state.get("reasoning_effort")
        if current not in efforts:
            current = "medium" if "medium" in efforts else efforts[0]
        st.session_state.reasoning_effort = current
    else:
        st.session_state.reasoning_effort = None


def persist_appearance() -> None:
    """Apply the selected visual theme immediately after the menu reruns."""
    st.session_state.appearance = str(st.session_state.setting_appearance)
