"""Deterministic authentication-gate and Cognito profile sync tests."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import pytest
import streamlit as st
from streamlit.testing.v1 import AppTest

from backend.auth_profiles import (
    resolve_display_name,
    resolve_role,
    store_identifier_for_sub,
    sync_authenticated_user,
)
from backend.settings import settings
from backend.student_store import StudentStore
from ui import auth_gate

# Capture before per-test conftest stubs replace ``authenticated_user``.
_REAL_AUTHENTICATED_USER = auth_gate.authenticated_user


@pytest.fixture
def logged_in_user(monkeypatch: pytest.MonkeyPatch) -> dict:
    """Authenticate Streamlit via FastAPI session user profile."""
    user = {
        "id": "user-1",
        "cognito_sub": "cognito-sub-test-1",
        "email": "student@example.edu",
        "display_name": "Alex",
        "role": "student",
    }
    monkeypatch.setattr(auth_gate, "is_logged_in", lambda: True)
    monkeypatch.setattr(auth_gate, "authenticated_user", lambda: dict(user))
    monkeypatch.setattr(
        auth_gate,
        "current_user_claims",
        lambda: {
            "sub": "cognito-sub-test-1",
            "email": "student@example.edu",
            "given_name": "Alex",
            "name": "Alex Student",
        },
    )
    return user


@pytest.fixture
def logged_out_user(monkeypatch: pytest.MonkeyPatch) -> None:
    """Force the signed-out authentication gate."""
    monkeypatch.setattr(auth_gate, "is_logged_in", lambda: False)
    monkeypatch.setattr(auth_gate, "authenticated_user", lambda: None)
    monkeypatch.setattr(auth_gate, "current_user_claims", lambda: {})
    monkeypatch.setattr(
        auth_gate,
        "auth_login_url",
        lambda: "http://127.0.0.1:8000/api/v1/auth/login",
    )


def test_gitignore_excludes_secrets_toml():
    ignore = Path(".gitignore").read_text(encoding="utf-8")
    assert ".streamlit/secrets.toml" in ignore


def test_secrets_example_documents_fastapi_callback():
    example = Path(".streamlit/secrets.toml.example").read_text(encoding="utf-8")
    assert "/api/v1/auth/callback" in example
    assert "<cognito-app-client-secret>" in example
    assert "<user-pool-id>" in example
    assert 'prompt = "login"' in example
    assert "does not persist" in example.lower() or "application session" in example.lower()
    assert "sk-" not in example
    assert "oauth2callback" not in example


def test_unauthenticated_users_see_auth_gate(logged_out_user):
    app = AppTest.from_file("streamlit_app.py", default_timeout=30).run()
    assert not app.exception
    rendered = "\n".join(markdown.value or "" for markdown in app.markdown)
    assert "st-key-auth_shell" in rendered or "cd-auth-shell" in rendered
    assert "Critical Thinking Companion" in rendered
    assert any(
        button.label == "Sign in or create an account" for button in app.button
    )
    assert "never graded" in rendered.lower()
    assert "whether it benefits their learning" in rendered.lower()
    assert not any(
        (button.key or "").startswith("composer-model-") for button in app.button
    )
    assert len(app.chat_input) == 0


def test_auth_gate_is_non_dismissible(logged_out_user):
    source = Path("ui/auth_gate.py").read_text(encoding="utf-8")
    assert 'dismissible=False' in source
    assert "@st.dialog(" in source
    assert 'width="small"' in source
    assert "st.login(" not in source
    assert "Streamlit native OIDC" in source or "session authority" in source.lower()


def test_sign_in_button_navigates_to_fastapi_login(logged_out_user, monkeypatch):
    start = MagicMock(name="start_login")
    monkeypatch.setattr(auth_gate, "start_login", start)
    app = AppTest.from_file("streamlit_app.py", default_timeout=30).run()
    sign_in = next(
        button for button in app.button if button.label == "Sign in or create an account"
    )
    assert sign_in.key == "auth-sign-in"
    sign_in.click().run()
    start.assert_called_once_with()


def test_start_login_reports_missing_url(monkeypatch):
    monkeypatch.setattr(auth_gate, "auth_login_url", lambda: None)
    session: dict[str, object] = {}

    class _Session(dict):
        def __getattr__(self, key):
            try:
                return self[key]
            except KeyError as exc:
                raise AttributeError(key) from exc

        def __setattr__(self, key, value):
            self[key] = value

        def pop(self, key, default=None):
            return dict.pop(self, key, default)

    session_obj = _Session()
    monkeypatch.setattr(st, "session_state", session_obj)
    auth_gate.start_login()
    assert "unavailable" in str(session_obj.get("_auth_config_error")).lower()


def test_authenticated_users_see_full_application(logged_in_user, monkeypatch):
    from ui import profile as profile_ui

    monkeypatch.setattr(
        profile_ui,
        "app_logout_url",
        lambda: "http://127.0.0.1:8000/api/v1/auth/logout",
    )
    app = AppTest.from_file("streamlit_app.py", default_timeout=30).run()
    assert not app.exception
    rendered = "\n".join(markdown.value or "" for markdown in app.markdown)
    assert "st-key-chat_composer" in rendered or len(app.chat_input) == 1
    assert 'class="cd-profile-logout-link"' in rendered
    assert 'href="http://127.0.0.1:8000/api/v1/auth/logout"' in rendered
    assert 'target="_self"' in rendered
    assert app.session_state["display_name"] == "Alex"


def test_authenticated_rerun_preserves_student_display_name(logged_in_user):
    app = AppTest.from_file("streamlit_app.py", default_timeout=30).run()
    assert app.session_state["_auth_bound_sub"] == "cognito-sub-test-1"
    app.session_state["display_name"] = "Preferred Name"

    app.run()

    assert not app.exception
    assert app.session_state["display_name"] == "Preferred Name"


def test_authenticated_subject_change_resets_identity_label(logged_in_user, monkeypatch):
    app = AppTest.from_file("streamlit_app.py", default_timeout=30).run()
    app.session_state["display_name"] = "First Student"
    app.session_state["profile_display_name"] = "First Student"
    monkeypatch.setattr(
        auth_gate,
        "authenticated_user",
        lambda: {
            "id": "user-2",
            "cognito_sub": "cognito-sub-test-2",
            "email": "second@example.edu",
            "display_name": "Second",
            "role": "student",
        },
    )
    monkeypatch.setattr(
        auth_gate,
        "current_user_claims",
        lambda: {
            "sub": "cognito-sub-test-2",
            "email": "second@example.edu",
            "given_name": "Second",
            "name": "Second Student",
        },
    )

    app.run()

    assert not app.exception
    assert app.session_state["_auth_bound_sub"] == "cognito-sub-test-2"
    assert app.session_state["display_name"] == "Second"
    assert app.session_state["profile_display_name"] == "Second"


def test_logged_in_identity_without_sub_is_cleared(monkeypatch):
    """An unusable signed identity must not reach protected app initialization."""
    local_logout = MagicMock(name="logout_user")
    monkeypatch.setattr(auth_gate, "is_logged_in", lambda: True)
    monkeypatch.setattr(
        auth_gate,
        "authenticated_user",
        lambda: {"id": "x", "cognito_sub": "", "display_name": "X"},
    )
    monkeypatch.setattr(auth_gate, "current_user_claims", lambda: {"email": "x@y.z"})
    monkeypatch.setattr(auth_gate, "logout_user", local_logout)

    app = AppTest.from_file("streamlit_app.py", default_timeout=30).run()

    assert not app.exception
    local_logout.assert_called_once_with()
    assert len(app.chat_input) == 0


def test_signed_out_shell_contains_no_real_student_data(logged_out_user):
    app = AppTest.from_file("streamlit_app.py", default_timeout=30).run()
    rendered = "\n".join(markdown.value or "" for markdown in app.markdown)
    assert "Welcome to your critical-thinking coach" in rendered
    assert "Lecture evidence" not in rendered
    assert "student@example.edu" not in rendered
    assert "cognito-sub" not in rendered


def test_resolve_display_name_fallbacks():
    assert resolve_display_name({"given_name": "Kai"}) == "Kai"
    assert resolve_display_name({"name": "Kai Ming"}) == "Kai Ming"
    assert resolve_display_name({"email": "kai@nus.edu"}) == "kai"
    assert resolve_display_name({}) == "Student"


def test_existing_database_role_is_preserved_and_unknown_roles_are_students():
    assert resolve_role(None) == "student"
    assert resolve_role("student") == "student"
    assert resolve_role("admin") == "admin"
    assert resolve_role("lecturer") == "lecturer"
    assert resolve_role("hacker") == "student"


def test_cognito_sub_used_for_lookup_and_first_login_creates_profile(tmp_path):
    db = tmp_path / "users.sqlite3"
    store = StudentStore(path=db, identifier="cognito:sub-abc")
    profile = sync_authenticated_user(
        {"sub": "sub-abc", "email": "a@example.edu", "given_name": "Ada"},
        store=store,
    )
    assert profile.created is True
    assert profile.cognito_sub == "sub-abc"
    assert profile.store_identifier == store_identifier_for_sub("sub-abc")
    assert profile.display_name == "Ada"
    assert profile.role == "student"
    loaded = store.get_user_by_cognito_sub("sub-abc")
    assert loaded is not None
    assert loaded["id"] == profile.user_id


def test_subsequent_login_reuses_profile_and_preserves_admin(tmp_path):
    db = tmp_path / "users.sqlite3"
    store = StudentStore(path=db, identifier="cognito:sub-xyz")
    first = sync_authenticated_user(
        {"sub": "sub-xyz", "email": "one@example.edu", "given_name": "One"},
        store=store,
    )
    with store._lock, store._connect() as connection:
        connection.execute(
            "UPDATE users SET role = ? WHERE id = ?",
            ("admin", first.user_id),
        )
    second = sync_authenticated_user(
        {
            "sub": "sub-xyz",
            "email": "two@example.edu",
            "given_name": "Two",
            "custom:role": "admin",
        },
        store=store,
    )
    assert second.created is False
    assert second.user_id == first.user_id
    assert second.display_name == "Two"
    assert second.role == "admin"
    loaded = store.get_user_by_cognito_sub("sub-xyz")
    assert loaded is not None
    assert loaded["email"] == "two@example.edu"


def test_profile_upsert_reuses_subject_across_store_instances(tmp_path):
    """Separate app workers converge on the unique Cognito subject row."""
    db = tmp_path / "users.sqlite3"
    first_store = StudentStore(path=db, identifier="cognito:shared-sub")
    first = sync_authenticated_user(
        {"sub": "shared-sub", "email": "one@example.edu"},
        store=first_store,
    )
    second_store = StudentStore(path=db, identifier="cognito:shared-sub")

    second = sync_authenticated_user(
        {"sub": "shared-sub", "email": "two@example.edu"},
        store=second_store,
    )

    assert second.created is False
    assert second.user_id == first.user_id
    loaded = second_store.get_user_by_cognito_sub("shared-sub")
    assert loaded is not None
    assert loaded["email"] == "two@example.edu"


def test_missing_given_name_falls_back_safely(tmp_path):
    db = tmp_path / "users.sqlite3"
    store = StudentStore(path=db, identifier="cognito:sub-fallback")
    profile = sync_authenticated_user(
        {"sub": "sub-fallback", "email": "fallback@example.edu"},
        store=store,
    )
    assert profile.display_name == "fallback"


def test_logout_user_navigates_to_fastapi_logout(monkeypatch):
    html = MagicMock(name="components_html")
    link_button = MagicMock(name="link_button")
    stop = MagicMock(name="stop", side_effect=RuntimeError("stop"))
    monkeypatch.setattr(auth_gate.components, "html", html)
    monkeypatch.setattr(st, "link_button", link_button)
    monkeypatch.setattr(st, "stop", stop)
    monkeypatch.setattr(
        auth_gate,
        "app_logout_url",
        lambda: "http://127.0.0.1:8000/api/v1/auth/logout",
    )

    try:
        auth_gate.logout_user()
    except RuntimeError:
        pass

    html.assert_called_once()
    markup = html.call_args.args[0]
    assert "http://127.0.0.1:8000/api/v1/auth/logout" in markup
    assert "window.parent.location.replace" in markup
    link_button.assert_called_once()
    stop.assert_called_once_with()


def test_logout_user_never_calls_st_logout(monkeypatch):
    logout = MagicMock(name="logout")
    monkeypatch.setattr(st, "logout", logout)
    monkeypatch.setattr(auth_gate, "app_logout_url", lambda: None)
    auth_gate.logout_user()
    logout.assert_not_called()
    assert "application API" in str(st.session_state.get("_auth_config_error") or "")


def test_app_logout_url_uses_public_origin_and_rejects_unsafe_base(monkeypatch):
    monkeypatch.setattr(
        auth_gate.settings,
        "api_base_url",
        "http://app:8000",
    )
    monkeypatch.setattr(
        auth_gate.settings,
        "public_api_base_url",
        "https://coach.example.edu",
    )
    assert auth_gate.app_logout_url() == (
        "https://coach.example.edu/api/v1/auth/logout"
    )

    monkeypatch.setattr(
        auth_gate.settings,
        "public_api_base_url",
        "https://coach.example.edu@evil.test",
    )
    assert auth_gate.app_logout_url() is None


def test_auth_source_does_not_use_streamlit_oidc_authority():
    source = Path("ui/auth_gate.py").read_text(encoding="utf-8")
    assert "st.login(" not in source
    assert "st.logout(" not in source
    assert "is_logged_in" in source
    assert "/api/v1/auth/me" in source
    assert "co_design_session" in source or "app_session_cookie_name" in source
    assert "_auth_me_token" not in source
    assert "_auth_me_user" not in source


def test_authenticated_user_revalidates_without_caching_raw_token(monkeypatch):
    """Revoked/expired sessions must not keep authenticating via Streamlit state."""
    # Undo the suite-wide authenticated_user stub from conftest.
    monkeypatch.setattr(auth_gate, "authenticated_user", _REAL_AUTHENTICATED_USER)

    calls: list[str] = []
    responses: list[dict | None] = [
        {
            "id": "u1",
            "cognito_sub": "sub-live",
            "email": "a@example.edu",
            "display_name": "A",
            "role": "student",
        },
        None,  # revoked / expired on next rerun
    ]

    class _Cookies(dict):
        pass

    class _Context:
        cookies = _Cookies({settings.app_session_cookie_name: "raw-session-token"})

    class _Client:
        def auth_me(self, session_token: str):
            calls.append(session_token)
            return responses[min(len(calls) - 1, len(responses) - 1)]

    class _Session(dict):
        def __getattr__(self, key):
            try:
                return self[key]
            except KeyError as exc:
                raise AttributeError(key) from exc

        def __setattr__(self, key, value):
            self[key] = value

        def pop(self, key, default=None):
            return dict.pop(self, key, default)

    session_obj = _Session()
    monkeypatch.setattr(st, "context", _Context())
    monkeypatch.setattr(st, "session_state", session_obj)
    monkeypatch.setattr(
        "ui.runtime.local_api_client",
        lambda: _Client(),
    )

    first = auth_gate.authenticated_user()
    assert first is not None
    assert first["cognito_sub"] == "sub-live"
    assert "_auth_me_token" not in session_obj
    assert "_auth_me_user" not in session_obj
    assert "raw-session-token" not in session_obj.values()
    assert "raw-session-token" not in session_obj

    second = auth_gate.authenticated_user()
    assert second is None
    assert calls == ["raw-session-token", "raw-session-token"]
    assert "_auth_me_token" not in session_obj
    assert "raw-session-token" not in session_obj


def test_owner_binding_remains_cognito_sub(logged_in_user):
    app = AppTest.from_file("streamlit_app.py", default_timeout=30).run()
    assert app.session_state["_auth_bound_sub"] == "cognito-sub-test-1"
    assert app.session_state["_auth_store_identifier"] == "cognito:cognito-sub-test-1"
