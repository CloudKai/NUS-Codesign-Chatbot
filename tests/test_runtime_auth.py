"""Authenticated runtime ownership and local API boundary tests."""

from __future__ import annotations

import streamlit as st

from backend.settings import settings
from ui import runtime


def test_cognito_owner_uses_multi_user_local_api(monkeypatch):
    """Cognito sessions call FastAPI; ownership is resolved from the ID cookie."""
    monkeypatch.setattr(settings, "use_local_api", True)
    monkeypatch.setattr(
        st,
        "session_state",
        {"_auth_store_identifier": "cognito:student-a"},
    )

    assert runtime.local_api_enabled() is True


def test_local_student_can_use_local_api(monkeypatch):
    """The original loopback API remains available for the single-user demo."""
    monkeypatch.setattr(settings, "use_local_api", True)
    monkeypatch.setattr(
        st,
        "session_state",
        {"_auth_store_identifier": "local-student"},
    )

    assert runtime.local_api_enabled() is True


def test_api_mode_can_be_disabled(monkeypatch):
    """USE_LOCAL_API=false keeps the in-process fallback for tests/legacy."""
    monkeypatch.setattr(settings, "use_local_api", False)
    monkeypatch.setattr(
        st,
        "session_state",
        {"_auth_store_identifier": "cognito:student-a"},
    )

    assert runtime.local_api_enabled() is False


def test_cached_resources_are_isolated_by_cognito_subject():
    """Distinct Cognito subjects receive distinct owners on the shared database."""
    first_store, _, _, _ = runtime.resources("cognito:student-a")
    second_store, _, _, _ = runtime.resources("cognito:student-b")

    thread_id = first_store.create_thread(model_id="mock", support_mode="critical-thinking")

    assert first_store.get_thread(thread_id) is not None
    assert second_store.get_thread(thread_id) is None
    assert first_store.owner_id != second_store.owner_id
