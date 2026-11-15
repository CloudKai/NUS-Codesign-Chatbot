"""Guest admission contracts at the existing browser HTTP boundary."""

from pathlib import Path
from concurrent.futures import ThreadPoolExecutor

import pytest
from fastapi.testclient import TestClient

from backend.api import create_app
from backend.auth_oidc import CognitoIdentity, CognitoOIDCError
from backend.guest_admission import GuestAdmissionLimiter
from backend.settings import settings
from backend.student_store import StudentStore


def test_new_guests_are_bounded_but_existing_workspace_reopens(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Full admission rejects new identities while preserving the saved Guest."""
    monkeypatch.setattr(settings, "guest_access_enabled", True)
    monkeypatch.setattr(settings, "public_api_base_url", "https://testserver")
    monkeypatch.setattr(settings, "auth_cookie_secure", False)
    monkeypatch.setattr(settings, "guest_starts_per_minute", 1, raising=False)
    store = StudentStore(tmp_path / "admission.sqlite3")
    client = TestClient(create_app(store), base_url="https://testserver")
    headers = {"Origin": "https://testserver"}
    started = client.post("/api/v1/auth/guest/start", headers=headers)
    assert started.status_code == 200
    secret = client.cookies.get(settings.guest_session_cookie_name)
    notebook = client.post("/api/v1/threads", json={"name": "Saved work", "model_id": "mock", "support_mode": "critical-thinking"})
    assert notebook.status_code == 200
    client.cookies.clear()

    rejected = client.post("/api/v1/auth/guest/start", headers=headers)
    assert rejected.status_code == 429
    assert 1 <= int(rejected.headers["Retry-After"]) <= 60
    assert "retry" in rejected.json()["detail"].lower()
    assert rejected.headers["Cache-Control"] == "no-store"
    assert "set-cookie" not in rejected.headers

    client.cookies.set(settings.guest_session_cookie_name, secret)
    reused = client.post("/api/v1/auth/guest/start", headers=headers)
    assert reused.status_code == 200
    assert reused.json() == started.json()
    assert client.get("/api/v1/threads").json()[0]["name"] == "Saved work"


def test_hourly_bound_survives_minute_rollover_and_eventually_recovers(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Repeated minute bursts hit the longer bound; the clock releases capacity."""
    monkeypatch.setattr(settings, "guest_access_enabled", True)
    monkeypatch.setattr(settings, "public_api_base_url", "https://testserver")
    moment = [0.0]
    limiter = GuestAdmissionLimiter(per_minute=1, per_hour=2, clock=lambda: moment[0])
    client = TestClient(create_app(StudentStore(tmp_path / "hour.sqlite3"),
                                   guest_admission=limiter), base_url="https://testserver")
    headers = {"Origin": "https://testserver"}
    for now in (0.0, 60.0):
        moment[0] = now
        client.cookies.clear()
        assert client.post("/api/v1/auth/guest/start", headers=headers).status_code == 200
    client.cookies.clear()
    moment[0] = 120.0
    rejected = client.post("/api/v1/auth/guest/start", headers=headers)
    assert rejected.status_code == 429
    assert rejected.headers["Retry-After"] == "3480"
    moment[0] = 3599.5
    assert client.post("/api/v1/auth/guest/start", headers=headers).headers["Retry-After"] == "1"
    moment[0] = 3600.0
    assert client.post("/api/v1/auth/guest/start", headers=headers).status_code == 200


def test_eighty_shared_network_arrivals_and_concurrent_excess(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """One classroom shares an address; concurrent excess cannot exceed the cap."""
    monkeypatch.setattr(settings, "guest_access_enabled", True)
    monkeypatch.setattr(settings, "public_api_base_url", "https://testserver")
    app = create_app(StudentStore(tmp_path / "classroom.sqlite3"),
                     guest_admission=GuestAdmissionLimiter(clock=lambda: 0.0))

    def arrive(_: int) -> tuple[int, str | None]:
        """Start an independent browser with the same network address."""
        with TestClient(app, base_url="https://testserver", client=("192.0.2.10", 5000)) as client:
            result = client.post("/api/v1/auth/guest/start", headers={
                "Origin": "https://testserver", "X-Forwarded-For": "192.0.2.10",
            })
            return result.status_code, result.json().get("guest_id")

    with ThreadPoolExecutor(max_workers=16) as pool:
        classroom = list(pool.map(arrive, range(80)))
        excess = list(pool.map(arrive, range(80)))
    assert all(status == 200 for status, _ in classroom)
    assert len({identity for _, identity in classroom}) == 80
    assert sum(status == 200 for status, _ in excess) == 40
    assert sum(status == 429 for status, _ in excess) == 40


def test_full_admission_preserves_legacy_guest_and_registered_precedence(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Old Guest cookies remain usable; registered credentials never downgrade."""
    monkeypatch.setattr(settings, "guest_access_enabled", True)
    monkeypatch.setattr(settings, "public_api_base_url", "https://testserver")
    store = StudentStore(tmp_path / "legacy.sqlite3")
    _, secret = store.create_guest_session()

    class OIDC:
        """Deterministic external identity verifier for cookie priority."""

        def verify_id_token(self, token: str) -> CognitoIdentity:
            """Accept one fixed registered token and reject invalid credentials."""
            if token != "registered":
                raise CognitoOIDCError("invalid")
            return CognitoIdentity(sub="registered-owner", email=None, claims={"sub": "registered-owner"})

    limiter = GuestAdmissionLimiter(per_minute=1, clock=lambda: 0.0)
    client = TestClient(create_app(store, oidc_client=OIDC(), guest_admission=limiter),
                        base_url="https://testserver")
    headers = {"Origin": "https://testserver"}
    assert client.post("/api/v1/auth/guest/start", headers=headers).status_code == 200
    client.cookies.clear()
    client.cookies.set(settings.guest_session_cookie_name, "invalid")
    assert client.post("/api/v1/auth/guest/start", headers=headers).status_code == 429
    client.cookies.set(settings.guest_session_cookie_name, secret)
    assert client.post("/api/v1/auth/guest/start", headers=headers).status_code == 200
    for token, expected in (("registered", 409), ("invalid", 401)):
        client.cookies.set(settings.cognito_id_token_cookie_name, token)
        assert client.post("/api/v1/auth/guest/start", headers=headers).status_code == expected
    client.cookies.clear()
    assert client.post("/api/v1/auth/guest/start", headers={"Origin": "https://evil.example"}).status_code == 403
