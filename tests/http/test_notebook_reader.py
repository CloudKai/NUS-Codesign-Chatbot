"""Authenticated notebook pilot behavior through the public HTTP boundary."""

from pathlib import Path

from fastapi.testclient import TestClient
from pytest import MonkeyPatch

from backend.api import create_app
from backend.settings import settings
from backend.student_store import StudentStore
from test_professor_analytics import FakeOIDC, _seed_user


def test_reader_never_uses_anonymous_local_workspace(tmp_path: Path, monkeypatch: MonkeyPatch) -> None:
    """Public reads require credentials even when the internal demo permits none."""
    monkeypatch.setattr(settings, "guest_access_enabled", False)
    store = StudentStore(tmp_path / "reader.sqlite3")
    store.create_thread(name="Private local work", model_id="mock", support_mode="critical-thinking")
    client = TestClient(create_app(store))
    for path in ("session", "threads"):
        response = client.get(f"/api/v1/reader/{path}")
        assert response.status_code == 401
        assert response.headers["cache-control"] == "no-store"
        assert "Private local work" not in response.text
    whitespace = client.get("/api/v1/reader/threads", headers={
        "Cookie": f'{settings.cognito_id_token_cookie_name}="   "',
    })
    assert whitespace.status_code == 401


def test_registered_reader_pages_saved_history_without_private_metadata(tmp_path: Path) -> None:
    """Read saved work with bounded chronological pages and server-derived ownership."""
    root = StudentStore(tmp_path / "registered.sqlite3")
    _seed_user(root, "student", "student")
    _seed_user(root, "other", "student")
    _seed_user(root, "staff", "lecturer")
    student = StudentStore(root.path, identifier="cognito:student")
    thread = student.create_thread(name="Crossing study", model_id="mock", support_mode="critical-thinking")
    for index in range(8):
        student.add_message(thread, "user" if index % 2 == 0 else "assistant", f"Saved turn {index}",
                            metadata={"research_coding": "PRIVATE RESEARCH", "local_path": "/private/path"})
    oidc = FakeOIDC(root)
    client = TestClient(create_app(root, oidc_client=oidc))
    client.cookies.set(settings.cognito_id_token_cookie_name, oidc.add("student"))
    session = client.get("/api/v1/reader/session").json()
    listing = client.get("/api/v1/reader/threads?user_id=other").json()
    assert listing["owner_id"] == session["owner_id"]
    assert listing["notebooks"][0]["name"] == "Crossing study"
    path = f"/api/v1/reader/threads/{thread}/messages/page"
    response = client.get(path, params={"limit": 3})
    assert response.status_code == 200
    page = response.json()
    assert page["owner_id"] == session["owner_id"]
    assert [row["content"] for row in page["messages"]] == ["Saved turn 5", "Saved turn 6", "Saved turn 7"]
    assert "PRIVATE RESEARCH" not in response.text
    assert "/private/path" not in response.text
    older = client.get(path, params={"limit": 3, "cursor": page["next_cursor"]}).json()
    assert [row["content"] for row in older["messages"]] == ["Saved turn 2", "Saved turn 3", "Saved turn 4"]
    assert client.get(path, params={"limit": 101}).status_code == 422
    assert client.post(path, json={}).status_code == 405
    client.cookies.set(settings.cognito_id_token_cookie_name, oidc.add("other"))
    assert client.get(path).status_code == 404
    assert client.get("/api/v1/reader/threads").json()["notebooks"] == []
    client.cookies.set(settings.cognito_id_token_cookie_name, oidc.add("staff"))
    assert client.get("/api/v1/reader/session").status_code == 403


def test_guest_reader_is_isolated_and_origin_guarded(tmp_path: Path, monkeypatch: MonkeyPatch) -> None:
    """Guest and registered cookies retain existing precedence and CSRF controls."""
    monkeypatch.setattr(settings, "guest_access_enabled", True)
    monkeypatch.setattr(settings, "public_api_base_url", "https://testserver")
    monkeypatch.setattr(settings, "ui_base_url", "https://testserver")
    root = StudentStore(tmp_path / "guest.sqlite3")
    client = TestClient(create_app(root, oidc_client=FakeOIDC(root)), base_url="https://testserver")
    assert client.post("/api/v1/auth/guest/start", headers={"Origin": "https://evil.test"}).status_code == 403
    assert client.post("/api/v1/auth/guest/start", headers={"Origin": "https://testserver"}).status_code == 200
    session = client.get("/api/v1/reader/session")
    assert session.status_code == 200
    assert session.json()["kind"] == "guest"
    assert client.get("/api/v1/reader/threads", headers={"Sec-Fetch-Site": "cross-site"}).status_code == 403
    assert client.get("/api/v1/reader/threads", headers={"Origin": "https://evil.test"}).status_code == 403
    assert client.get("/api/v1/reader/threads").json()["notebooks"] == []
    profile = root.get_user_by_id(session.json()["owner_id"])
    assert profile is not None
    guest = StudentStore(root.path, identifier=profile["identifier"])
    notebook = guest.create_thread(name="Guest saved project", model_id="mock", support_mode="critical-thinking")
    guest.add_message(notebook, "user", "My saved crossing idea")
    url = f"/api/v1/reader/threads/{notebook}/messages/page"
    assert client.get(url).json()["messages"][0]["content"] == "My saved crossing idea"
    other_id, other_secret = root.create_guest_session()
    other = TestClient(create_app(root, oidc_client=FakeOIDC(root)), base_url="https://testserver")
    other.cookies.set(settings.guest_session_cookie_name, other_secret)
    assert other.get(url).status_code == 404
    assert other.get("/api/v1/reader/session").json()["owner_id"] == other_id
    restarted = TestClient(create_app(StudentStore(root.path), oidc_client=FakeOIDC(root)), base_url="https://testserver")
    restarted.cookies.update(client.cookies)
    assert restarted.get(url).json()["messages"][0]["content"] == "My saved crossing idea"
    assert client.get("/api/v1/professor/overview").status_code == 401
    client.cookies.set(settings.cognito_id_token_cookie_name, "invalid-registered-cookie")
    assert client.get("/api/v1/reader/session").status_code == 401


def test_pilot_serves_only_built_public_assets(tmp_path: Path) -> None:
    """The static shell works without exposing source files or private paths."""
    client = TestClient(create_app(StudentStore(tmp_path / "static.sqlite3")))
    response = client.get("/pilot/")
    assert response.status_code == 200
    assert '<div id="root">' in response.text
    assert "default-src 'self'" in response.headers["content-security-policy"]
    assert client.get("/pilot/package.json").status_code == 404
    assert client.get("/pilot/src/App.tsx").status_code == 404
    assert client.get("/pilot/assets/unknown.js").status_code == 404



def test_default_workspace_and_streamlit_gate(tmp_path: Path, monkeypatch: MonkeyPatch) -> None:
    """Only persisted staff and the exact enabled Cognito account reach Streamlit."""
    monkeypatch.setattr(settings, "guest_access_enabled", True)
    monkeypatch.setattr(settings, "streamlit_access_subjects", frozenset({"enabled"}))
    root = StudentStore(tmp_path / "routing.sqlite3")
    oidc = FakeOIDC(root)
    for subject, role in (("lecturer", "lecturer"), ("admin", "admin"), ("enabled", "student"), ("student", "student")):
        _seed_user(root, subject, role)
        oidc.add(subject)
    app = create_app(root, oidc_client=oidc)
    gate = "/api/v1/auth/streamlit-access"
    client = TestClient(app, follow_redirects=False)
    _, guest_secret = root.create_guest_session()

    for cookie in ({}, {settings.guest_session_cookie_name: guest_secret}, {settings.cognito_id_token_cookie_name: "invalid"}):
        client.cookies.clear()
        client.cookies.update(cookie)
        response = client.get(gate, headers={"X-User-Id": "lecturer", "X-Role": "lecturer"})
        assert response.status_code == 403
        assert response.headers["cache-control"] == "no-store"
        home = client.get("/")
        assert home.status_code == 200
        assert '<div id="root">' in home.text
        assert home.headers["vary"] == "Cookie"

    for subject in ("lecturer", "admin", "enabled", "student"):
        client.cookies.clear()
        client.cookies.set(settings.cognito_id_token_cookie_name, f"token-{subject}")
        allowed = subject != "student"
        assert client.get(gate).status_code == (204 if allowed else 403)
        assert client.get("/api/v1/auth/me").json()["user"]["streamlit_access"] is allowed
        for path in ("/", "/pilot/"):
            response = client.get(f"{path}?auth_refreshed=1")
            assert response.status_code == (302 if allowed else 200)
            assert response.headers["cache-control"] == "no-store"
            if allowed:
                assert response.headers["location"] == "/streamlit/?auth_refreshed=1"

    client.cookies.set(settings.cognito_id_token_cookie_name, "token-lecturer")
    _seed_user(root, "lecturer", "student")
    assert client.get(gate).status_code == 403

    client.cookies.clear()
    client.cookies.set(settings.cognito_session_hint_cookie_name, "1")
    assert client.get("/").headers["location"] == "/api/v1/auth/refresh"
    assert client.get("/?auth_refreshed=1").status_code == 200
