"""Cached runtime resources shared across Streamlit UI modules."""

from __future__ import annotations

from typing import Any

import streamlit as st

from backend.api_client import LocalApiClient
from backend.chat_service import StudentChatEngine
from backend.settings import settings
from backend.source_library import CourseMaterialSyncCoordinator
from backend.student_store import StudentStore


@st.cache_resource
def resources() -> tuple[StudentStore, StudentChatEngine]:
    store = StudentStore()
    return store, StudentChatEngine(store)


def _resolve_resources() -> tuple[StudentStore, StudentChatEngine]:
    """Return a store/engine pair, refreshing if hot-reload left a stale class."""
    store, engine = resources()
    if not hasattr(store, "get_user_preferences") or not hasattr(
        store, "update_user_preferences"
    ):
        resources.clear()
        store, engine = resources()
    return store, engine


class _LazyStore:
    """Proxy so importers always hit the current cached StudentStore instance."""

    def __getattr__(self, name: str) -> Any:
        store, _ = _resolve_resources()
        return getattr(store, name)


class _LazyEngine:
    """Proxy so importers always hit the current cached StudentChatEngine."""

    def __getattr__(self, name: str) -> Any:
        _, engine = _resolve_resources()
        return getattr(engine, name)


store = _LazyStore()
engine = _LazyEngine()


@st.cache_resource
def course_material_sync() -> CourseMaterialSyncCoordinator:
    """Share background source imports across Streamlit reruns and refreshes."""
    return CourseMaterialSyncCoordinator()


@st.cache_resource
def local_api_client() -> LocalApiClient:
    """Create the typed client used when the optional local API mode is enabled."""
    return LocalApiClient(
        str(getattr(settings, "api_base_url", "http://127.0.0.1:8000"))
    )


def local_api_enabled() -> bool:
    """Read API mode safely across Streamlit's cached-module hot reloads.

    Streamlit can rerun this script while retaining an older ``Settings``
    instance. ``getattr`` keeps that transition recoverable and a normal full
    restart will load the current settings schema.
    """
    return bool(getattr(settings, "use_local_api", False))


def rerun() -> None:
    st.rerun()
