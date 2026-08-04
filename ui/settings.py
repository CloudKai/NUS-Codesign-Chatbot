"""Preference persistence callbacks shared by the profile menu.

``persist_*`` functions are wired to widget ``on_change``. Appearance is stored
in user preferences (not thread metadata). ``sync_appearance_from_widget`` only
writes when the settings control is ahead of session state after init.
"""

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
            current = efforts[0]
        st.session_state.reasoning_effort = current
    else:
        st.session_state.reasoning_effort = None


def persist_appearance() -> None:
    """Apply and persist the selected visual theme for this local user."""
    from ui.constants import APPEARANCE_MODES

    if "setting_appearance" in st.session_state:
        chosen = str(st.session_state.setting_appearance)
    elif "appearance" in st.session_state:
        chosen = str(st.session_state.appearance)
    else:
        chosen = "Light"
    if chosen not in APPEARANCE_MODES:
        chosen = "Light"
    st.session_state.appearance = chosen
    st.session_state.setting_appearance = chosen
    store.update_user_preferences({"appearance": chosen})


def sync_appearance_from_widget() -> bool:
    """Align session appearance with the settings control before theme CSS runs.

    Persists only when the widget is ahead of session state (for example when
    ``on_change`` did not run). Returns True when the theme value changed.
    """
    from ui.constants import APPEARANCE_MODES

    if "setting_appearance" not in st.session_state:
        return False
    chosen = str(st.session_state.setting_appearance)
    if chosen not in APPEARANCE_MODES:
        return False
    current = (
        str(st.session_state.appearance)
        if "appearance" in st.session_state
        else ""
    )
    if chosen == current:
        return False
    persist_appearance()
    return True
