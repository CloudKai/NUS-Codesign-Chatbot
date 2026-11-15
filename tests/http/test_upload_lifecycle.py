"""Source availability after uploads without a Library/browser revisit."""

from pathlib import Path

from fastapi.testclient import TestClient

from backend.api import create_app
from backend.student_store import StudentStore


def test_completed_upload_enables_source_grounding_without_browser_revisit(tmp_path: Path) -> None:
    """Upload completion alone exposes the saved source and its grounding mode."""
    database = tmp_path / "uploads.sqlite3"
    client = TestClient(create_app(StudentStore(database)))
    notebook = client.post("/api/v1/threads", json={
        "name": "Upload without polling", "model_id": "mock", "support_mode": "critical-thinking",
        "metadata": {"allow_model_knowledge": True},
    }).json()
    thread_id = notebook["id"]
    result = client.post(f"/api/v1/threads/{thread_id}/sources", files=[
        ("files", ("field-notes.txt", b"Older pedestrians need more crossing time.", "text/plain")),
    ])
    assert result.status_code == 200
    saved = result.json()[0]
    assert client.get(f"/api/v1/threads/{thread_id}").json()["metadata"]["allow_model_knowledge"] is False
    restarted = TestClient(create_app(StudentStore(database)))
    sources = restarted.get(f"/api/v1/threads/{thread_id}/sources").json()
    assert sources[0]["id"] == saved["id"]
    assert sources[0]["selected"] is True
    assert sources[0]["has_file"] is True
    assert restarted.get(f"/api/v1/threads/{thread_id}/sources/{saved['id']}/content").content == b"Older pedestrians need more crossing time."


def test_rejected_upload_retry_and_saved_files_stay_owner_and_notebook_scoped(
    tmp_path: Path, monkeypatch,
) -> None:
    """A rejected batch creates no source; corrected retry survives owner/restart guards."""
    from backend.settings import settings

    monkeypatch.setattr(settings, "guest_access_enabled", True)
    monkeypatch.setattr(settings, "public_api_base_url", "https://testserver")
    monkeypatch.setattr(settings, "max_files", 1)
    database = tmp_path / "owned.sqlite3"
    app = create_app(StudentStore(database))
    owner = TestClient(app, base_url="https://testserver")
    other = TestClient(app, base_url="https://testserver")
    headers = {"Origin": "https://testserver"}
    assert owner.post("/api/v1/auth/guest/start", headers=headers).status_code == 200
    assert other.post("/api/v1/auth/guest/start", headers=headers).status_code == 200
    notebooks = [owner.post("/api/v1/threads", json={
        "name": name, "model_id": "mock", "support_mode": "critical-thinking",
        "metadata": {"allow_model_knowledge": True},
    }).json()["id"] for name in ("A", "B")]
    a, b = notebooks
    files = [("files", ("notes.txt", b"Disposable evidence", "text/plain"))]
    rejected = owner.post(f"/api/v1/threads/{a}/sources", files=files * 2)
    assert rejected.status_code == 400
    assert owner.get(f"/api/v1/threads/{a}/sources").json() == []
    assert owner.get(f"/api/v1/threads/{a}").json()["metadata"]["allow_model_knowledge"] is True
    source = owner.post(f"/api/v1/threads/{a}/sources", files=files).json()[0]
    assert owner.get(f"/api/v1/threads/{b}/sources").json() == []
    assert owner.get(f"/api/v1/threads/{b}/sources/{source['id']}/content").status_code == 404
    assert other.get(f"/api/v1/threads/{a}/sources/{source['id']}/content").status_code == 404
    assert other.post(f"/api/v1/threads/{a}/sources", files=files).status_code == 404
    assert owner.get(f"/api/v1/threads/{a}/sources/{source['id']}/content").content == b"Disposable evidence"
    restarted = TestClient(create_app(StudentStore(database)), base_url="https://testserver")
    restarted.cookies.update(owner.cookies)
    assert restarted.get(f"/api/v1/threads/{a}/sources/{source['id']}/content").content == b"Disposable evidence"
