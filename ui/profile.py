"""Profile dialog for local appearance, language, and session reset."""

from __future__ import annotations

import streamlit as st

from ui.components import profile_initial
from ui.constants import APPEARANCE_MODES, RESPONSE_LANGUAGES
from ui.runtime import store
from ui.session import new_notebook
from ui.settings import persist_appearance, persist_response_language


def persist_display_name() -> None:
    """Store the local display name used by the profile shell."""
    cleaned = " ".join(str(st.session_state.profile_display_name or "").split())[:80]
    st.session_state.display_name = cleaned or "Student"
    store.update_thread(
        st.session_state.thread_id,
        metadata={"display_name": st.session_state.display_name},
    )


@st.dialog("Profile", width="small")
def profile_dialog() -> None:
    """Render account preferences formerly housed in the Setting dialog."""
    display_name = str(st.session_state.get("display_name") or "Student")
    initial = profile_initial(display_name)
    st.markdown(
        '<div class="cd-profile-menu">'
        f'<div class="cd-profile-avatar">{initial}</div>'
        "</div>",
        unsafe_allow_html=True,
    )
    st.text_input(
        "Display name",
        value=display_name,
        max_chars=80,
        key="profile_display_name",
        on_change=persist_display_name,
    )
    st.caption("Account details stay on this device for the local demo.")
    st.divider()
    st.segmented_control(
        "Appearance",
        APPEARANCE_MODES,
        default=st.session_state.appearance,
        key="setting_appearance",
        on_change=persist_appearance,
        help="System follows your device theme.",
    )
    current_language = st.session_state.response_language
    st.selectbox(
        "Response language",
        RESPONSE_LANGUAGES,
        index=RESPONSE_LANGUAGES.index(current_language),
        key="setting_response_language",
        on_change=persist_response_language,
        help="The coach responds in this language while preserving source names.",
    )
    st.divider()
    st.markdown("**Help and support**")
    st.caption("Contact: (Will input myself later)")
    st.divider()
    if st.button(
        "Log out",
        icon=":material/logout:",
        use_container_width=True,
        key="profile-logout",
        help="Start a fresh local notebook session.",
    ):
        st.session_state.display_name = "Student"
        new_notebook(should_rerun=True)


def render_profile_menu() -> None:
    """Render the upper-right profile avatar that opens the profile dialog."""
    display_name = str(st.session_state.get("display_name") or "Student")
    initial = profile_initial(display_name)
    with st.container(key="topbar_profile"):
        if st.button(
            initial,
            type="tertiary",
            key="open-profile",
        ):
            profile_dialog()
