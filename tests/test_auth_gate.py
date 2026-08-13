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
        lambda _user=None: {
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
    monkeypatch.setattr(auth_gate, "current_user_claims", lambda _user=None: {})
    monkeypatch.setattr(auth_gate, "should_attempt_session_refresh", lambda: False)
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
    assert "CDE2300 Design Thinking Companion" in rendered
    assert "Product Design and Innovation" in rendered
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
    assert "authentication authority" in source.lower()


def test_sign_in_button_arms_redirecting_ui(logged_out_user, monkeypatch):
    clock = [1_000.0]
    monkeypatch.setattr(auth_gate.time, "time", lambda: clock[0])
    app = AppTest.from_file("streamlit_app.py", default_timeout=30).run()
    sign_in = next(
        button for button in app.button if button.label == "Sign in or create an account"
    )
    assert sign_in.key == "auth-sign-in-button"
    sign_in.click().run()
    rendered = "\n".join(markdown.value or "" for markdown in app.markdown)
    assert "Redirecting..." in rendered
    assert 'data-cd-auth-redirect="1"' in rendered
    assert 'href="http://127.0.0.1:8000/api/v1/auth/login"' in rendered
    assert 'target="_self"' in rendered
    assert rendered.count('<a data-cd-auth-redirect="1"') == 1
    assert "Continue to sign-in" not in rendered
    assert sum(
        button.label == "Sign in or create an account" for button in app.button
    ) == 1
    assert rendered.index("Redirecting...") < rendered.index(
        "data-cd-auth-redirect"
    )
    cooled = next(
        button for button in app.button if button.label == "Sign in or create an account"
    )
    assert cooled.disabled is True
    assert app.session_state["_auth_signin_cooldown_until"] == 1_005.0

    # An ordinary rerun/remount does not move the absolute server deadline.
    app.run()
    assert app.session_state["_auth_signin_cooldown_until"] == 1_005.0

    # Once expired, the original button is enabled, while Redirecting remains.
    clock[0] = 1_005.01
    app.run()
    rendered = "\n".join(markdown.value or "" for markdown in app.markdown)
    assert "Redirecting..." in rendered
    retry = next(
        button for button in app.button if button.label == "Sign in or create an account"
    )
    assert retry.disabled is False

    # A deliberate retry arms exactly one new launch with a fresh deadline.
    retry.click().run()
    assert app.session_state["_auth_signin_cooldown_until"] == 1_010.01
    retrying = next(
        button for button in app.button if button.label == "Sign in or create an account"
    )
    assert retrying.disabled is True


def test_sign_in_button_cooldown_reenable_helpers(monkeypatch):
    """The cooldown should disable immediately and clear after the window."""
    monkeypatch.setattr(auth_gate.time, "time", lambda: 1_000.0)
    st.session_state.clear()
    st.session_state["_auth_refresh_attempted"] = True
    monkeypatch.setattr(
        auth_gate,
        "auth_login_url",
        lambda: "http://127.0.0.1:8000/api/v1/auth/login",
    )
    auth_gate.start_login()
    assert st.session_state.get("_auth_launch_cognito") is True
    assert st.session_state.get("_auth_refresh_attempted") is True
    assert auth_gate._signin_cooldown_active() is True
    monkeypatch.setattr(auth_gate.time, "time", lambda: 1_000.0 + 5.01)
    assert auth_gate._signin_cooldown_active() is False


def test_cognito_return_clears_legacy_cooldown_marker_and_pending_ui(monkeypatch):
    """Browser Return must show normal sign-in instead of stale Redirecting UI."""
    marker = {auth_gate._SIGNIN_COOLDOWN_QUERY_PARAM: "1004.5"}
    monkeypatch.setattr(auth_gate.st, "query_params", marker, raising=False)
    st.session_state.clear()
    st.session_state["_auth_signin_redirecting"] = True
    st.session_state["_auth_signin_cooldown_until"] = 1004.5

    auth_gate._restore_signin_pending_state_from_query_marker()

    assert "_auth_signin_redirecting" not in st.session_state
    assert "_auth_signin_cooldown_until" not in st.session_state
    assert marker == {}


def test_legacy_cooldown_marker_is_consumed_regardless_of_value(monkeypatch):
    """Legacy URL state is cleanup-only and never restores Redirecting UI."""
    marker = {auth_gate._SIGNIN_COOLDOWN_QUERY_PARAM: "1005.0"}
    monkeypatch.setattr(auth_gate.st, "query_params", marker, raising=False)
    st.session_state.clear()

    auth_gate._restore_signin_pending_state_from_query_marker()

    assert "_auth_signin_redirecting" not in st.session_state
    assert "_auth_signin_cooldown_until" not in st.session_state
    assert marker == {}


@pytest.mark.parametrize(
    "value", ["not-a-deadline", "nan", "inf", "969.99", "1006.01"]
)
def test_signin_cooldown_restore_rejects_malformed_stale_or_future_marker(
    monkeypatch, value
):
    """Invalid or non-server-plausible markers cannot disable the button."""
    monkeypatch.setattr(auth_gate.time, "time", lambda: 1_000.0)
    marker = {auth_gate._SIGNIN_COOLDOWN_QUERY_PARAM: value}
    monkeypatch.setattr(auth_gate.st, "query_params", marker, raising=False)
    st.session_state.clear()

    auth_gate._restore_signin_pending_state_from_query_marker()

    assert "_auth_signin_redirecting" not in st.session_state
    assert "_auth_signin_cooldown_until" not in st.session_state
    assert marker == {}


def test_start_login_keeps_cooldown_out_of_url(
    monkeypatch,
):
    """Cognito Return must not inherit stale redirect UI from the browser URL."""
    marker: dict[str, str] = {}
    monkeypatch.setattr(auth_gate.st, "query_params", marker, raising=False)
    monkeypatch.setattr(auth_gate.time, "time", lambda: 1_000.0)
    monkeypatch.setattr(
        auth_gate,
        "auth_login_url",
        lambda: "http://127.0.0.1:8000/api/v1/auth/login",
    )
    st.session_state.clear()

    auth_gate.start_login()

    assert st.session_state["_auth_signin_cooldown_until"] == 1005.0
    assert marker == {}


def test_auth_gate_uses_server_authoritative_cooldown_and_same_document_redirect():
    source = Path("ui/auth_gate.py").read_text(encoding="utf-8")
    assert "def start_login" in source
    assert "_auth_launch_cognito" in source
    assert 'pop("_auth_launch_cognito"' in source
    assert "data-cd-auth-redirect" in source
    assert 'target="_self"' in source
    assert "querySelector" in source
    assert "@st.fragment(run_every=0.5)" in source
    assert "def _render_signin_cooldown_fragment" in source
    assert "rerun_app()" in source
    assert "st.rerun()" not in source
    assert "removeAttribute('disabled')" not in source
    assert "removeAttribute('aria-disabled')" not in source
    assert "button.disabled = false" not in source
    assert "streamlit.components.v1" not in source
    assert "components.html" not in source
    assert source.count("st.html(") == 3
    assert source.count("unsafe_allow_javascript=True") == 3
    login_source = source.split("def _click_login_link", 1)[1].split(
        "@st.dialog", 1
    )[0]
    assert "link.click()" in login_source
    assert "location.replace(" in login_source
    assert "setTimeout(go, 280)" in login_source
    assert "window.parent" not in login_source


def test_signin_pending_state_is_cleared_on_success_logout_and_config_failure(
    monkeypatch,
):
    """Transient sign-in state cannot survive a completed or failed flow."""
    monkeypatch.setattr(auth_gate, "authenticated_user", _REAL_AUTHENTICATED_USER)
    st.session_state.clear()
    st.session_state.update(
        {
            "_auth_launch_cognito": True,
            "_auth_signin_cooldown_until": 1234.0,
            "_auth_signin_redirecting": True,
        }
    )
    monkeypatch.setattr(
        auth_gate,
        "_cookie_value",
        lambda _name: "validated-cookie",
    )
    monkeypatch.setattr("ui.runtime.local_api_client", lambda: MagicMock(
        auth_me=lambda _token: {"cognito_sub": "accepted-sub"}
    ))

    assert auth_gate.authenticated_user() == {"cognito_sub": "accepted-sub"}
    assert "_auth_launch_cognito" not in st.session_state
    assert "_auth_signin_cooldown_until" not in st.session_state
    assert "_auth_signin_redirecting" not in st.session_state

    st.session_state.update(
        {
            "_auth_launch_cognito": True,
            "_auth_signin_cooldown_until": 1234.0,
            "_auth_signin_redirecting": True,
        }
    )
    monkeypatch.setattr(auth_gate, "auth_login_url", lambda: None)
    auth_gate.start_login()
    assert "_auth_launch_cognito" not in st.session_state
    assert "_auth_signin_cooldown_until" not in st.session_state
    assert "_auth_signin_redirecting" not in st.session_state

    st.session_state.update(
        {
            "_auth_launch_cognito": True,
            "_auth_signin_cooldown_until": 1234.0,
            "_auth_signin_redirecting": True,
        }
    )
    auth_gate.logout_user()
    assert "_auth_launch_cognito" not in st.session_state
    assert "_auth_signin_cooldown_until" not in st.session_state
    assert "_auth_signin_redirecting" not in st.session_state


def test_auth_config_error_shows_gap_and_hides_sign_in(logged_out_user, monkeypatch):
    monkeypatch.setattr(auth_gate, "auth_login_url", lambda: None)
    app = AppTest.from_file("streamlit_app.py", default_timeout=30).run()
    assert not app.exception
    rendered = "\n".join(markdown.value or "" for markdown in app.markdown)
    assert "cd-auth-gap-after-course-notice--spacer" in rendered
    assert any("temporarily unavailable" in (err.value or "") for err in app.error)
    assert not any(
        button.label == "Sign in or create an account" for button in app.button
    )


def test_auth_gate_handles_auth_error_query_param():
    source = Path("ui/auth_gate.py").read_text(encoding="utf-8")
    assert 'query_params.get("auth_error") == "1"' in source
    assert "Sign-in did not complete" in source
    assert "auth-config-error" in source


def test_env_example_documents_cognito_cookies_and_fastapi_callback():
    example = Path(".env.example").read_text(encoding="utf-8")
    assert "COGNITO_REFRESH_COOKIE_NAME=co_design_refresh" in example
    assert "COGNITO_ID_TOKEN_COOKIE_NAME=co_design_id" in example
    assert "COGNITO_SESSION_HINT_COOKIE_NAME=co_design_session" in example
    assert "COGNITO_REFRESH_COOKIE_MAX_AGE=2592000" in example
    assert "AUTH_COOKIE_SECURE=false" in example
    assert "APP_SESSION_" not in example
    assert "COGNITO_REDIRECT_URI=http://127.0.0.1:8000/api/v1/auth/callback" in example
    assert "CO_DESIGN_PUBLIC_API_URL=http://127.0.0.1:8000" in example
    assert "authoritative" in example.lower() or "app-client" in example.lower()


def test_should_attempt_session_refresh_requires_existing_session_hint(monkeypatch):
    """Cold visitors skip refresh; expired established sessions bridge once."""
    st.session_state.clear()
    monkeypatch.setattr(auth_gate.st, "query_params", {})
    monkeypatch.setattr(auth_gate, "_cookie_value", lambda _name: None)
    assert auth_gate.should_attempt_session_refresh() is False

    monkeypatch.setattr(
        auth_gate,
        "_cookie_value",
        lambda name: "1"
        if name == settings.cognito_session_hint_cookie_name
        else None,
    )
    assert auth_gate.should_attempt_session_refresh() is True

    st.session_state["_auth_refresh_attempted"] = True
    assert auth_gate.should_attempt_session_refresh() is False


@pytest.mark.parametrize(
    "pending_key", ["_auth_launch_cognito", "_auth_signin_redirecting"]
)
def test_should_attempt_session_refresh_never_intercepts_login_redirect(
    monkeypatch, pending_key
):
    """A Sign in click must reach Cognito instead of re-entering refresh."""
    st.session_state.clear()
    st.session_state[pending_key] = True
    monkeypatch.setattr(auth_gate.st, "query_params", {})
    monkeypatch.setattr(auth_gate, "_cookie_value", lambda _name: "1")

    assert auth_gate.should_attempt_session_refresh() is False


def test_should_attempt_session_refresh_skips_auth_required_marker(monkeypatch):
    st.session_state.clear()
    monkeypatch.setattr(
        auth_gate.st,
        "query_params",
        {"auth_required": "1"},
    )
    assert auth_gate.should_attempt_session_refresh() is False


def test_session_refresh_renders_spinner_over_shell_without_visible_fallback(
    monkeypatch,
):
    """Refresh UI is a centered loader, not the former bare text/link page."""
    rendered: list[str] = []
    scripts: list[str] = []
    monkeypatch.setattr(
        auth_gate,
        "auth_refresh_url",
        lambda: "https://app.example/api/v1/auth/refresh",
    )
    monkeypatch.setattr(
        auth_gate.st,
        "markdown",
        lambda body, **_kwargs: rendered.append(str(body)),
    )
    monkeypatch.setattr(
        auth_gate.st,
        "html",
        lambda body, **_kwargs: scripts.append(str(body)),
    )
    st.session_state.clear()

    assert auth_gate.redirect_to_session_refresh() is True

    markup = "\n".join(rendered)
    script = "\n".join(scripts)
    assert "cd-auth-session-spinner" in markup
    assert "If nothing happens" not in markup
    assert ">Continue</a>" in markup
    assert 'aria-hidden="true"' in markup
    assert "window.location.replace(url)" in script


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


def test_authenticated_refresh_marker_is_removed_without_losing_other_params(
    monkeypatch,
):
    """Successful refresh returns to a clean UI URL after verification."""
    marker = {"auth_refreshed": "1", "notebook": "current"}
    monkeypatch.setattr(auth_gate.st, "query_params", marker, raising=False)

    auth_gate.clear_authenticated_refresh_marker()

    assert marker == {"notebook": "current"}


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
        lambda _user=None: {
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
    monkeypatch.setattr(
        auth_gate,
        "current_user_claims",
        lambda _user=None: {"email": "x@y.z"},
    )
    monkeypatch.setattr(auth_gate, "logout_user", local_logout)

    app = AppTest.from_file("streamlit_app.py", default_timeout=30).run()

    assert not app.exception
    local_logout.assert_called_once_with()
    assert len(app.chat_input) == 0


def test_signed_out_shell_contains_no_real_student_data(logged_out_user):
    app = AppTest.from_file("streamlit_app.py", default_timeout=30).run()
    rendered = "\n".join(markdown.value or "" for markdown in app.markdown)
    assert "Welcome back. What are you working through today?" in rendered
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
    html = MagicMock(name="streamlit_html")
    link_button = MagicMock(name="link_button")
    stop = MagicMock(name="stop", side_effect=RuntimeError("stop"))
    monkeypatch.setattr(st, "html", html)
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
    assert "window.location.replace" in markup
    assert html.call_args.kwargs == {"unsafe_allow_javascript": True}
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
    assert "co_design_id" in source or "cognito_id_token_cookie_name" in source
    assert "_auth_me_token" not in source
    assert "_auth_me_user" not in source


def test_authenticated_user_revalidates_without_caching_raw_token(monkeypatch):
    """Expired Cognito cookies must not keep authenticating via Streamlit state."""
    # Undo the suite-wide authenticated_user stub from conftest.
    monkeypatch.setattr(auth_gate, "authenticated_user", _REAL_AUTHENTICATED_USER)

    calls: list[str | None] = []
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
        cookies = _Cookies(
            {
                settings.cognito_id_token_cookie_name: "raw-id-token",
                settings.cognito_refresh_cookie_name: "raw-refresh-token",
            }
        )

    class _Client:
        def auth_me(self, id_token: str | None = None):
            calls.append(id_token)
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
    assert "raw-id-token" not in session_obj.values()
    assert "raw-refresh-token" not in session_obj.values()

    second = auth_gate.authenticated_user()
    assert second is None
    assert calls == ["raw-id-token", "raw-id-token"]
    assert "_auth_me_token" not in session_obj
    assert "raw-id-token" not in session_obj


def test_owner_binding_remains_cognito_sub(logged_in_user):
    app = AppTest.from_file("streamlit_app.py", default_timeout=30).run()
    assert app.session_state["_auth_bound_sub"] == "cognito-sub-test-1"
    assert app.session_state["_auth_store_identifier"] == "cognito:cognito-sub-test-1"
