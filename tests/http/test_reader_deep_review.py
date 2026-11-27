"""Student reader controls for durable Deep Review."""

from pathlib import Path

from fastapi.testclient import TestClient
from pytest import MonkeyPatch

from backend.api import create_app
from backend.coaching import deep_review_jobs
from backend.settings import settings
from backend.student_journey import THINKING_STAGES
from backend.student_store import StudentStore
from test_professor_analytics import FakeOIDC, _seed_user


def test_reader_deep_review_enqueues_and_cancels_the_displayed_job(
    tmp_path: Path, monkeypatch: MonkeyPatch,
) -> None:
    """The browser can inspect eligibility, start and cancel exactly the displayed job."""
    monkeypatch.setattr(settings, "public_api_base_url", "https://testserver")
    monkeypatch.setattr(deep_review_jobs, "submit_deep_review_job", lambda *_: True)
    root = StudentStore(tmp_path / "reader-review.sqlite3")
    _seed_user(root, "student", "student")
    oidc = FakeOIDC(root)
    owner = StudentStore(root.path, identifier="cognito:student")
    thread_id = owner.create_thread(model_id="mock", support_mode="critical-thinking")
    path = f"/api/v1/reader/threads/{thread_id}/deep-review"
    origin = {"Origin": "https://testserver"}
    client = TestClient(create_app(root, oidc_client=oidc), base_url="https://testserver")
    client.cookies.set(settings.cognito_id_token_cookie_name, oidc.add("student"))

    status = client.get(path)
    assert status.status_code == 200
    assert status.json()["eligible"] is False and status.json()["job"] is None
    assert client.post(path, headers=origin).status_code == 400

    owner.update_thread(thread_id, metadata={
        "learning_journey": {"completed_stages": [stage.id for stage in THINKING_STAGES]},
    })
    started = client.post(path, headers=origin)
    assert started.status_code == 200
    job = started.json()["job"]
    assert job["status"] == "queued"
    stale = client.post(f"{path}/cancel", headers=origin, json={"review_id": "previous-job"})
    assert stale.status_code == 409
    assert client.get(path).json()["job"]["status"] == "queued"
    cancelled = client.post(f"{path}/cancel", headers=origin, json={"review_id": job["review_id"]})
    assert cancelled.status_code == 200 and cancelled.json()["job"]["status"] == "cancelled"
    assert client.get(path).json()["job"]["status"] == "cancelled"
