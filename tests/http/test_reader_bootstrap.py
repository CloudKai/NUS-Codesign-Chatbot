"""Initial CDE2300 reader projections preserve authentication and owner isolation."""

from pathlib import Path

from fastapi.testclient import TestClient
from pytest import MonkeyPatch

from backend.api import create_app
from backend.settings import settings
from backend.student_store import StudentStore
from test_professor_analytics import FakeOIDC, _seed_user


def test_bootstrap_matches_independent_reads_and_uses_one_bulk_list(tmp_path: Path, monkeypatch: MonkeyPatch) -> None:
    """Aggregate only the same reviewed projections with one list read and no model call."""
    root = StudentStore(tmp_path / "bootstrap.sqlite3")
    _seed_user(root, "student", "student")
    owner = StudentStore(root.path, identifier="cognito:student")
    thread = owner.create_thread(name="CDE2300 project", model_id="mock", support_mode="critical-thinking")
    owner.add_message(thread, "user", "A synthetic saved idea")
    oidc = FakeOIDC(root)
    client = TestClient(create_app(root, oidc_client=oidc))
    client.cookies.set(settings.cognito_id_token_cookie_name, oidc.add("student"))
    expected = {"session": client.get("/api/v1/reader/session").json(),
                "listing": client.get("/api/v1/reader/threads").json(),
                "preferences": client.get("/api/v1/reader/preferences").json()}
    from backend.workspace_service import WorkspaceService
    from backend.mock_provider import DeterministicCoachProvider
    original = WorkspaceService.list_threads
    reads = []

    def listed(self):
        reads.append(1)
        return original(self)

    monkeypatch.setattr(WorkspaceService, "list_threads", listed)

    def generation_forbidden(*args, **kwargs):
        raise AssertionError("Bootstrap must never generate model output")

    monkeypatch.setattr(DeterministicCoachProvider, "assess", generation_forbidden)
    result = client.get("/api/v1/reader/bootstrap")
    assert result.status_code == 200
    assert result.json() == expected
    assert len(reads) == 1
    assert result.headers["cache-control"] == "no-store"
    assert "messages" not in result.json()


def test_bootstrap_rejects_anonymous_foreign_origin_and_staff(tmp_path: Path) -> None:
    """The aggregate endpoint uses the existing reader dependency without bypasses."""
    root = StudentStore(tmp_path / "isolation.sqlite3")
    _seed_user(root, "staff", "lecturer")
    oidc = FakeOIDC(root)
    client = TestClient(create_app(root, oidc_client=oidc))
    url = "/api/v1/reader/bootstrap"
    assert client.get(url).status_code == 401
    client.cookies.set(settings.cognito_id_token_cookie_name, oidc.add("staff"))
    assert client.get(url).status_code == 403
    assert client.get(url, headers={"Sec-Fetch-Site": "cross-site"}).status_code == 403
    assert client.get(url, headers={"Origin": "https://foreign.test"}).status_code == 403
    assert client.post(url).status_code == 405


def test_bootstrap_guest_isolation_and_restart(tmp_path: Path, monkeypatch: MonkeyPatch) -> None:
    """Fresh Guest cookies and a restarted app never inherit another owner's list."""
    monkeypatch.setattr(settings, "guest_access_enabled", True)
    root = StudentStore(tmp_path / "guest.sqlite3")
    client = TestClient(create_app(root))
    owner_id, secret = root.create_guest_session()
    _, other = root.create_guest_session()
    profile = root.get_user_by_id(owner_id)
    store = StudentStore(root.path, identifier=profile["identifier"])
    store.create_thread(name="Synthetic private project", model_id="mock", support_mode="critical-thinking")
    client.cookies.set(settings.guest_session_cookie_name, secret)
    first = client.get("/api/v1/reader/bootstrap").json()
    assert first["session"]["owner_id"] == first["listing"]["owner_id"] == first["preferences"]["owner_id"] == owner_id
    restarted = TestClient(create_app(StudentStore(root.path)))
    restarted.cookies.set(settings.guest_session_cookie_name, secret)
    assert restarted.get("/api/v1/reader/bootstrap").json() == first
    client.cookies.set(settings.guest_session_cookie_name, other)
    response = client.get("/api/v1/reader/bootstrap")
    assert response.json()["listing"]["notebooks"] == []
    assert "Synthetic private project" not in response.text
