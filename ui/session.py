"""Notebook session initialization and lifecycle helpers.

Owns Streamlit ``session_state`` defaults, notebook create/select/delete, and
journey persistence. Appearance is always loaded from the user preference store
and forced onto ``setting_appearance`` so a stale settings widget cannot rewrite
the database on the next sync.
"""

from __future__ import annotations

from typing import Any

import streamlit as st

from backend.models import (
    DEFAULT_CHAT_MODEL_ID,
    DEFAULT_REASONING_EFFORT,
    MODEL_BY_ID,
    get_model,
    validate_reasoning,
)
from backend.student_journey import (
    DEFAULT_RESPONSE_DETAIL,
    DEFAULT_STAGE,
    default_journey,
    normalize_journey,
)
from backend.student_support import DEFAULT_SUPPORT_MODE

from ui.coach_welcome import seed_coach_welcome
from ui.constants import APPEARANCE_MODES, DEFAULT_APPEARANCE, RESPONSE_LANGUAGES
from ui.layout.column_resize import set_side_panel_collapsed
from ui.rename import bump_rename_epoch, discard_rename_draft
from ui.runtime import rerun_app, store
from ui.retry_keys import purge_notebook_retry_keys
from ui.settings import apply_selected_model


def initialize_session() -> None:
    """Seed session defaults and restore the active notebook plus appearance.

    Side effects:
        - Writes missing keys into ``st.session_state``.
        - Loads appearance from ``StudentStore`` user preferences and realigns
          ``setting_appearance`` to that value.
        - Restores the last-open notebook from preferences when the Streamlit
          session has no valid ``thread_id`` (e.g. browser refresh).
        - Creates or selects a notebook when none is active.
        - Backfills legacy message attachments into the source library.
    """
    defaults: dict[str, Any] = {
        "thread_id": None,
        "selected_model": DEFAULT_CHAT_MODEL_ID,
        "support_mode": DEFAULT_SUPPORT_MODE,
        "reasoning_effort": DEFAULT_REASONING_EFFORT,
        "web_search": False,
        "image_generation": False,
        "allow_model_knowledge": False,
        "response_detail": DEFAULT_RESPONSE_DETAIL,
        "response_language": "English",
        "appearance": DEFAULT_APPEARANCE,
        "learning_journey": default_journey(),
        "assignment": {"title": "", "course": "", "brief": "", "rubric": ""},
        "composer_nonce": 0,
        "pending_edit": None,
        "editing_message": None,
        "edit_confirm_message_id": None,
        "pending_notebook_actions": None,
        "reopen_notebooks_dialog": False,
        "mobile_panel": "Chat",
        "nav_section": "Chat",
        "studio_tab": "Journey",
        "display_name": "Student",
        "review_fingerprint": "",
        "review_seen_fingerprint": "",
    }
    for key, value in defaults.items():
        if key not in st.session_state:
            st.session_state[key] = value
    st.session_state.support_mode = DEFAULT_SUPPORT_MODE
    st.session_state.web_search = False
    st.session_state.image_generation = False
    if st.session_state.selected_model not in MODEL_BY_ID:
        st.session_state.selected_model = DEFAULT_CHAT_MODEL_ID
    apply_selected_model(st.session_state.selected_model)
    preferences = store.get_user_preferences() or {}
    stored_appearance = str(preferences.get("appearance") or "").strip()
    # Prefer an explicit saved choice; otherwise force the app default.
    # Do not keep a leftover session value (e.g. old "Light" default) when the
    # preference store has no appearance key yet.
    if stored_appearance in APPEARANCE_MODES:
        st.session_state.appearance = stored_appearance
    else:
        st.session_state.appearance = DEFAULT_APPEARANCE
    # Always realign the widget key from persisted appearance so a stale
    # popover value cannot rewrite the database on the next sync.
    st.session_state.setting_appearance = st.session_state.appearance
    if not st.session_state.thread_id or not store.get_thread(st.session_state.thread_id):
        preferred_id = str(preferences.get("active_thread_id") or "").strip()
        threads = store.list_threads()
        if preferred_id and store.get_thread(preferred_id):
            select_thread(preferred_id, should_rerun=False)
        elif threads:
            select_thread(threads[0]["id"], should_rerun=False)
        else:
            new_notebook(should_rerun=False)
    store.backfill_legacy_sources(st.session_state.thread_id)


def _persist_active_thread(thread_id: str | None) -> None:
    """Remember which notebook should reopen after a browser refresh."""
    store.update_user_preferences({"active_thread_id": thread_id})


def new_notebook(should_rerun: bool = True) -> None:
    """Create an untitled notebook with a fresh Focus-stage journey.

    User-initiated creates stay on Chat with Sources open so course materials
    can load. Shows a short loading toast, then reruns the app.

    Args:
        should_rerun: When True, trigger a Streamlit rerun after session updates.
    """
    journey = default_journey()
    thread_id = store.create_thread(
        name="Untitled notebook",
        model_id=st.session_state.get("selected_model") or DEFAULT_CHAT_MODEL_ID,
        support_mode=DEFAULT_SUPPORT_MODE,
        assignment={"title": "", "course": "", "brief": "", "rubric": ""},
    )
    store.update_thread(
        thread_id,
        metadata={
            "response_detail": journey["response_detail"],
            "response_language": "English",
            "allow_model_knowledge": False,
        },
    )
    seed_coach_welcome(store, thread_id)
    st.session_state.thread_id = thread_id
    st.session_state.support_mode = DEFAULT_SUPPORT_MODE
    st.session_state.learning_journey = journey
    st.session_state.response_detail = journey["response_detail"]
    st.session_state.response_language = "English"
    st.session_state.assignment = {"title": "", "course": "", "brief": "", "rubric": ""}
    st.session_state.allow_model_knowledge = False
    st.session_state.editing_message = None
    st.session_state.pending_edit = None
    st.session_state.edit_confirm_message_id = None
    _persist_active_thread(thread_id)
    if should_rerun:
        st.session_state.mobile_panel = "Chat"
        st.session_state.nav_section = "Chat"
        set_side_panel_collapsed("sources", False)
        st.session_state.toast_course_materials_loading = True
        rerun_app()


def delete_notebook(thread_id: str) -> None:
    """Delete a notebook and return to the notebook library dialog."""
    st.session_state.pending_notebook_actions = None
    st.session_state.reopen_notebooks_dialog = True
    store.delete_thread(thread_id)
    purge_notebook_retry_keys(st.session_state, thread_id)
    if thread_id == st.session_state.thread_id:
        st.session_state.thread_id = None
        _persist_active_thread(None)


def request_notebook_actions(thread_id: str) -> None:
    """Open the notebook actions dialog for ``thread_id`` on the next render."""
    st.session_state.pending_notebook_actions = thread_id
    st.session_state.reopen_notebooks_dialog = False


def cancel_notebook_actions() -> None:
    """Close notebook actions and reopen Your Notebooks on the next run.

    Used for the dialog X, click-outside, and Esc dismiss paths. Uncommitted
    rename drafts are discarded so the field restores the saved title.
    """
    thread_id = st.session_state.get("pending_notebook_actions")
    if thread_id:
        discard_rename_draft("notebook", str(thread_id))
        bump_rename_epoch("notebook", str(thread_id))
    st.session_state.pending_notebook_actions = None
    st.session_state.reopen_notebooks_dialog = True


def select_thread(thread_id: str, should_rerun: bool = True) -> None:
    """Load a notebook into session state (journey, language, assignment).

    Args:
        thread_id: Persisted notebook identifier.
        should_rerun: When True, trigger a Streamlit rerun after loading.
    """
    thread = store.get_thread(thread_id)
    if not thread:
        return
    metadata = thread.get("metadata") or {}
    selected = metadata.get("selected_model")
    if selected in MODEL_BY_ID:
        apply_selected_model(str(selected))
    else:
        apply_selected_model(DEFAULT_CHAT_MODEL_ID)
    # Keep effort compatible with the restored model choice.
    st.session_state.reasoning_effort = validate_reasoning(
        get_model(st.session_state.selected_model),
        metadata.get("reasoning_effort"),
    )
    st.session_state.support_mode = DEFAULT_SUPPORT_MODE
    st.session_state.allow_model_knowledge = False
    raw_journey = metadata.get("learning_journey")
    if not isinstance(raw_journey, dict):
        raw_journey = {
            "current_stage": metadata.get("thinking_stage", DEFAULT_STAGE),
            "response_detail": metadata.get(
                "response_detail", DEFAULT_RESPONSE_DETAIL
            ),
        }
    journey = normalize_journey(raw_journey)
    st.session_state.learning_journey = journey
    st.session_state.response_detail = journey["response_detail"]
    language = str(metadata.get("response_language") or "English")
    st.session_state.response_language = (
        language if language in RESPONSE_LANGUAGES else "English"
    )
    st.session_state.assignment = {
        **{"title": "", "course": "", "brief": "", "rubric": ""},
        **(metadata.get("assignment") or {}),
    }
    display_name = str(metadata.get("display_name") or "").strip()
    if display_name:
        st.session_state.display_name = display_name
    st.session_state.thread_id = thread_id
    st.session_state.editing_message = None
    st.session_state.pending_edit = None
    st.session_state.edit_confirm_message_id = None
    _persist_active_thread(thread_id)
    store.backfill_legacy_sources(thread_id)
    seed_coach_welcome(store, thread_id)
    if should_rerun:
        rerun_app()


def save_journey(journey: dict[str, Any]) -> None:
    """Normalize local display state and persist student-editable settings only.

    The session copy of ``current_stage`` is never sent back through generic
    notebook metadata; FastAPI and the learning service own persisted stages.
    """
    normalized = normalize_journey(journey)
    st.session_state.learning_journey = normalized
    st.session_state.response_detail = normalized["response_detail"]
    store.update_thread(
        st.session_state.thread_id,
        metadata={
            "response_detail": normalized["response_detail"],
            "response_language": st.session_state.get("response_language", "English"),
        },
    )
