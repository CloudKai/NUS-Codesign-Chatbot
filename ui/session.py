"""Notebook session initialization and lifecycle helpers."""

from __future__ import annotations

from typing import Any

import streamlit as st

from backend.models import MODEL_BY_ID
from backend.settings import settings
from backend.source_library import backfill_legacy_sources
from backend.student_journey import default_journey, normalize_journey
from backend.student_support import DEFAULT_SUPPORT_MODE

from ui.constants import RESPONSE_LANGUAGES
from ui.runtime import rerun, store

def initialize_session() -> None:
    defaults: dict[str, Any] = {
        "thread_id": None,
        "selected_model": settings.default_model,
        "support_mode": DEFAULT_SUPPORT_MODE,
        "reasoning_effort": "medium",
        "web_search": False,
        "image_generation": False,
        "speak_response": False,
        "allow_model_knowledge": False,
        "response_detail": "short",
        "response_language": "English",
        "appearance": "Light",
        "learning_journey": default_journey(),
        "assignment": {"title": "", "course": "", "brief": "", "rubric": ""},
        "composer_nonce": 0,
        "pending_edit": None,
        "editing_message": None,
        "pending_notebook_actions": None,
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
    st.session_state.speak_response = False
    if st.session_state.selected_model not in MODEL_BY_ID:
        st.session_state.selected_model = settings.default_model
    if not st.session_state.thread_id or not store.get_thread(st.session_state.thread_id):
        threads = store.list_threads()
        if threads:
            select_thread(threads[0]["id"], should_rerun=False)
        else:
            new_notebook(should_rerun=False)
    backfill_legacy_sources(store, st.session_state.thread_id)


def new_notebook(should_rerun: bool = True) -> None:
    journey = default_journey()
    thread_id = store.create_thread(
        name="Untitled notebook",
        model_id=st.session_state.get("selected_model", settings.default_model),
        support_mode=DEFAULT_SUPPORT_MODE,
        assignment={"title": "", "course": "", "brief": "", "rubric": ""},
    )
    store.update_thread(
        thread_id,
        metadata={
            "learning_journey": journey,
            "thinking_stage": journey["current_stage"],
            "response_detail": journey["response_detail"],
            "response_language": "English",
            "allow_model_knowledge": False,
        },
    )
    st.session_state.thread_id = thread_id
    st.session_state.support_mode = DEFAULT_SUPPORT_MODE
    st.session_state.learning_journey = journey
    st.session_state.response_detail = journey["response_detail"]
    st.session_state.response_language = "English"
    st.session_state.assignment = {"title": "", "course": "", "brief": "", "rubric": ""}
    st.session_state.allow_model_knowledge = False
    st.session_state.editing_message = None
    st.session_state.mobile_panel = "Sources"
    if should_rerun:
        rerun()


def delete_notebook(thread_id: str) -> None:
    st.session_state.pending_notebook_actions = None
    store.delete_thread(thread_id)
    if thread_id == st.session_state.thread_id:
        st.session_state.thread_id = None


def request_notebook_actions(thread_id: str) -> None:
    st.session_state.pending_notebook_actions = thread_id


def cancel_notebook_actions() -> None:
    st.session_state.pending_notebook_actions = None


def select_thread(thread_id: str, should_rerun: bool = True) -> None:
    thread = store.get_thread(thread_id)
    if not thread:
        return
    metadata = thread.get("metadata") or {}
    selected = metadata.get("selected_model")
    if selected in MODEL_BY_ID:
        st.session_state.selected_model = selected
    st.session_state.support_mode = DEFAULT_SUPPORT_MODE
    st.session_state.allow_model_knowledge = False
    raw_journey = metadata.get("learning_journey")
    if not isinstance(raw_journey, dict):
        raw_journey = {
            "current_stage": metadata.get("thinking_stage", "focus"),
            "response_detail": metadata.get("response_detail", "short"),
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
    backfill_legacy_sources(store, thread_id)
    if should_rerun:
        rerun()


def save_journey(journey: dict[str, Any]) -> None:
    normalized = normalize_journey(journey)
    st.session_state.learning_journey = normalized
    st.session_state.response_detail = normalized["response_detail"]
    store.update_thread(
        st.session_state.thread_id,
        metadata={
            "learning_journey": normalized,
            "thinking_stage": normalized["current_stage"],
            "response_detail": normalized["response_detail"],
            "response_language": st.session_state.get("response_language", "English"),
        },
    )
