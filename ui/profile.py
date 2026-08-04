"""Profile settings popover for local appearance, language, and help."""

from __future__ import annotations

import streamlit as st

from ui.components import profile_initial
from ui.constants import APPEARANCE_MODES, RESPONSE_LANGUAGES
from ui.runtime import store
from ui.settings import persist_appearance, persist_response_language


def persist_display_name() -> None:
    """Store the local display name used by the profile shell."""
    cleaned = " ".join(str(st.session_state.profile_display_name or "").split())[:80]
    st.session_state.display_name = cleaned or "Student"
    store.update_thread(
        st.session_state.thread_id,
        metadata={"display_name": st.session_state.display_name},
    )


def render_profile_menu() -> None:
    """Render the upper-right profile avatar that opens a compact settings menu."""
    display_name = str(st.session_state.get("display_name") or "Student")
    initial = profile_initial(display_name)
    with st.container(key="topbar_profile"):
        with st.popover(initial, help="Settings"):
            st.markdown('<div class="cd-profile-menu">', unsafe_allow_html=True)
            st.text_input(
                "Display name",
                value=display_name,
                max_chars=80,
                key="profile_display_name",
                on_change=persist_display_name,
                placeholder="Student",
            )
            st.segmented_control(
                "Appearance",
                APPEARANCE_MODES,
                key="setting_appearance",
                on_change=persist_appearance,
            )
            current_language = str(st.session_state.response_language or "English")
            if current_language not in RESPONSE_LANGUAGES:
                current_language = "English"
                st.session_state.response_language = current_language
            st.selectbox(
                "Language",
                RESPONSE_LANGUAGES,
                index=RESPONSE_LANGUAGES.index(current_language),
                key="setting_response_language",
                on_change=persist_response_language,
                help="The coach responds in this language while preserving source names.",
            )
            st.divider()
            st.markdown(
                '<div class="cd-profile-help">'
                '<div class="cd-profile-help-title">Help</div>'
                '<div class="cd-profile-help-body">(Will input myself later)</div>'
                "</div>",
                unsafe_allow_html=True,
            )
            st.markdown("</div>", unsafe_allow_html=True)
