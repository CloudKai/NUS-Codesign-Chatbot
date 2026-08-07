"""Deterministic authentication-gate and Cognito profile sync tests."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
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
from backend.student_store import StudentStore
from ui import auth_gate


class FakeUser:
    """Minimal ``st.user`` stand-in for AppTest and unit tests."""

    def __init__(self, *, is_logged_in: bool = True, **claims):
        self.is_logged_in = is_logged_in
        self._claims = dict(claims)

    def get(self, key, default=None):
        return self._claims.get(key, default)

    def __getattr__(self, key):
        if key in self._claims:
            return self._claims[key]
        raise AttributeError(key)


@pytest.fixture
def logged_in_user(monkeypatch: pytest.MonkeyPatch) -> FakeUser:
    """Authenticate Streamlit as a Cognito student for UI tests."""
    user = FakeUser(
        is_logged_in=True,
        sub="cognito-sub-test-1",
        email="student@example.edu",
        given_name="Alex",
        name="Alex Student",
    )
    monkeypatch.setattr(st, "user", user, raising=False)
    monkeypatch.setattr(auth_gate, "is_logged_in", lambda: True)
    return user


@pytest.fixture
def logged_out_user(monkeypatch: pytest.MonkeyPatch) -> FakeUser:
    """Force the signed-out authentication gate."""
    user = FakeUser(is_logged_in=False)
    monkeypatch.setattr(st, "user", user, raising=False)
    monkeypatch.setattr(auth_gate, "is_logged_in", lambda: False)
    monkeypatch.setattr(st, "login", MagicMock(name="login"))
    return user


def test_gitignore_excludes_secrets_toml():
    ignore = Path(".gitignore").read_text(encoding="utf-8")
    assert ".streamlit/secrets.toml" in ignore


def test_secrets_example_uses_placeholders_and_oauth2callback():
    example = Path(".streamlit/secrets.toml.example").read_text(encoding="utf-8")
    assert "oauth2callback" in example
    assert "<cognito-app-client-secret>" in example
    assert "replace-with-persistent-strong-random-secret" in example
    assert "<user-pool-id>" in example
    assert 'prompt = "login"' in example
    assert "/auth/logout" in example
    assert "sk-" not in example


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


def test_sign_in_button_wires_st_login(logged_out_user, monkeypatch):
    login = MagicMock(name="login")
    monkeypatch.setattr(st, "login", login)
    monkeypatch.setattr(
        auth_gate, "auth_credentials_configured", lambda: (True, None)
    )
    app = AppTest.from_file("streamlit_app.py", default_timeout=30).run()
    sign_in = next(
        button for button in app.button if button.label == "Sign in or create an account"
    )
    assert sign_in.key == "auth-sign-in"
    sign_in.click().run()
    login.assert_called_once_with()


def test_start_login_reports_missing_secrets(monkeypatch):
    login = MagicMock(name="login")
    monkeypatch.setattr(st, "login", login)
    monkeypatch.setattr(
        auth_gate,
        "auth_credentials_configured",
        lambda: (False, "missing secrets.toml"),
    )
    state: dict[str, object] = {}

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

    session = _Session()
    monkeypatch.setattr(st, "session_state", session)
    auth_gate.start_login()
    assert "missing secrets.toml" in str(session.get("_auth_config_error"))
    login.assert_not_called()


def test_authenticated_users_see_full_application(logged_in_user, monkeypatch):
    from ui import profile as profile_ui

    monkeypatch.setattr(
        profile_ui,
        "app_logout_url",
        lambda: "http://127.0.0.1:8000/api/v1/auth/logout/callback",
    )
    app = AppTest.from_file("streamlit_app.py", default_timeout=30).run()
    assert not app.exception
    rendered = "\n".join(markdown.value or "" for markdown in app.markdown)
    assert "st-key-chat_composer" in rendered or len(app.chat_input) == 1
    assert 'class="cd-profile-logout-link"' in rendered
    assert 'href="http://127.0.0.1:8000/api/v1/auth/logout/callback"' in rendered
    assert 'target="_self"' in rendered
    assert app.session_state["display_name"] == "Alex"


def test_authenticated_rerun_preserves_student_display_name(logged_in_user):
    app = AppTest.from_file("streamlit_app.py", default_timeout=30).run()
    assert app.session_state["_auth_bound_sub"] == "cognito-sub-test-1"
    app.session_state["display_name"] = "Preferred Name"

    app.run()

    assert not app.exception
    assert app.session_state["display_name"] == "Preferred Name"


def test_authenticated_subject_change_resets_identity_label(logged_in_user):
    app = AppTest.from_file("streamlit_app.py", default_timeout=30).run()
    app.session_state["display_name"] = "First Student"
    app.session_state["profile_display_name"] = "First Student"
    logged_in_user._claims.update(
        sub="cognito-sub-test-2",
        given_name="Second",
        name="Second Student",
    )

    app.run()

    assert not app.exception
    assert app.session_state["_auth_bound_sub"] == "cognito-sub-test-2"
    assert app.session_state["display_name"] == "Second"
    assert app.session_state["profile_display_name"] == "Second"


def test_logged_in_identity_without_sub_is_cleared(monkeypatch):
    """An unusable signed identity must not reach protected app initialization."""
    user = FakeUser(is_logged_in=True, email="student@example.edu")
    local_logout = MagicMock(name="logout_user")
    monkeypatch.setattr(st, "user", user, raising=False)
    monkeypatch.setattr(auth_gate, "is_logged_in", lambda: True)
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


def test_logout_user_navigates_to_local_callback(monkeypatch):
    html = MagicMock(name="components_html")
    link_button = MagicMock(name="link_button")
    stop = MagicMock(name="stop", side_effect=RuntimeError("stop"))
    monkeypatch.setattr(auth_gate.components, "html", html)
    monkeypatch.setattr(st, "link_button", link_button)
    monkeypatch.setattr(st, "stop", stop)
    monkeypatch.setattr(
        auth_gate,
        "app_logout_url",
        lambda: "http://127.0.0.1:8000/api/v1/auth/logout/callback",
    )

    try:
        auth_gate.logout_user()
    except RuntimeError:
        pass

    html.assert_called_once()
    markup = html.call_args.args[0]
    assert "http://127.0.0.1:8000/api/v1/auth/logout/callback" in markup
    assert "window.parent.location.replace" in markup
    link_button.assert_called_once()
    stop.assert_called_once_with()


def test_logout_user_never_calls_st_logout(monkeypatch):
    logout = MagicMock(name="logout")
    monkeypatch.setattr(st, "logout", logout)
    monkeypatch.setattr(auth_gate, "app_logout_url", lambda: None)
    auth_gate.logout_user()
    logout.assert_not_called()
    assert "local API" in str(st.session_state.get("_auth_config_error") or "")


def test_cognito_logout_url_requires_ordered_streamlit_callback(monkeypatch):
    monkeypatch.setattr(
        st,
        "secrets",
        {
            "auth": {
                "redirect_uri": "https://coach.example.edu/oauth2callback",
                "client_id": "client-id",
                "cognito_domain": "https://login.example.edu",
                "logout_uri": (
                    "https://coach.example.edu/api/v1/auth/logout/callback"
                ),
            }
        },
    )

    url = auth_gate.cognito_logout_url()

    assert url is not None
    assert url.startswith("https://login.example.edu/logout?")
    assert "client_id=client-id" in url
    assert (
        "logout_uri=https%3A%2F%2Fcoach.example.edu%2Fapi%2Fv1%2Fauth%2F"
        "logout%2Fcallback"
    ) in url


@pytest.mark.parametrize(
    ("domain", "logout_uri"),
    [
        (
            "javascript:alert(1)",
            "https://coach.example.edu/api/v1/auth/logout/callback",
        ),
        (
            "http://login.example.edu",
            "https://coach.example.edu/api/v1/auth/logout/callback",
        ),
        (
            "https://login.example.edu",
            "https://evil.example/api/v1/auth/logout/callback",
        ),
        ("https://login.example.edu", "https://coach.example.edu/"),
    ],
)
def test_cognito_logout_url_rejects_unsafe_or_unordered_values(
    monkeypatch,
    domain,
    logout_uri,
):
    monkeypatch.setattr(
        st,
        "secrets",
        {
            "auth": {
                "redirect_uri": "https://coach.example.edu/oauth2callback",
                "client_id": "client-id",
                "cognito_domain": domain,
                "logout_uri": logout_uri,
            }
        },
    )

    assert auth_gate.cognito_logout_url() is None


def test_app_logout_url_accepts_loopback_and_rejects_unsafe_base(monkeypatch):
    monkeypatch.setattr(
        auth_gate.settings,
        "api_base_url",
        "http://127.0.0.1:8000",
    )
    assert auth_gate.app_logout_url() == (
        "http://127.0.0.1:8000/api/v1/auth/logout/callback"
    )

    monkeypatch.setattr(
        auth_gate.settings,
        "api_base_url",
        "https://coach.example.edu@evil.test",
    )
    assert auth_gate.app_logout_url() is None


def test_current_user_claims_never_exposes_tokens(monkeypatch):
    user = FakeUser(
        is_logged_in=True,
        sub="safe-sub",
        email="student@example.edu",
        access_token="secret-access-token",
        id_token="secret-id-token",
        refresh_token="secret-refresh-token",
    )
    monkeypatch.setattr(st, "user", user, raising=False)

    claims = auth_gate.current_user_claims()

    assert claims == {"sub": "safe-sub", "email": "student@example.edu"}
    assert not any("token" in key for key in claims)


def test_production_callback_documented_as_oauth2callback():
    example = Path(".streamlit/secrets.toml.example").read_text(encoding="utf-8")
    assert "https://<production-domain>/oauth2callback" in example
    assert "https://<production-domain>/api/v1/auth/logout/callback" in example
