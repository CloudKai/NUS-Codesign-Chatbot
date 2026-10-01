"""CRUD API coverage for notebooks, sources, preferences, and content."""

from __future__ import annotations

from fastapi.testclient import TestClient

from backend.api import create_app
from backend.source_library import add_text_source
from backend.student_store import StudentStore
from backend.workspace_service import WorkspaceService


def test_workspace_api_notebook_and_preference_crud(tmp_path):
    store = StudentStore(tmp_path / "workspace.sqlite3")
    client = TestClient(create_app(store))

    created = client.post(
        "/api/v1/threads",
        json={
            "name": "Research notebook",
            "model_id": "mock",
            "support_mode": "critical-thinking",
            "metadata": {"response_detail": "short"},
        },
    )
    assert created.status_code == 200
    thread_id = created.json()["id"]
    assert created.json()["name"] == "Research notebook"
    assert created.json()["metadata"]["response_detail"] == "short"

    defaulted = client.post(
        "/api/v1/threads",
        json={
            "name": "Untitled notebook",
            "model_id": "mock",
            "support_mode": "critical-thinking",
        },
    )
    assert defaulted.status_code == 200
    assert defaulted.json()["metadata"]["response_detail"] == "short"

    listed = client.get("/api/v1/threads")
    assert listed.status_code == 200
    assert any(item["id"] == thread_id for item in listed.json())

    renamed = client.patch(
        f"/api/v1/threads/{thread_id}",
        json={"name": "Renamed notebook"},
    )
    assert renamed.status_code == 200
    assert renamed.json()["name"] == "Renamed notebook"

    prefs = client.patch(
        "/api/v1/preferences",
        json={"appearance": "Dark", "active_thread_id": thread_id},
    )
    assert prefs.status_code == 200
    assert prefs.json()["appearance"] == "Dark"
    assert client.get("/api/v1/preferences").json()["active_thread_id"] == thread_id

    welcome = client.post(
        f"/api/v1/threads/{thread_id}/messages",
        json={
            "role": "assistant",
            "content": "Welcome message",
            "metadata": {"kind": "coach_welcome"},
        },
    )
    assert welcome.status_code == 200
    messages = client.get(f"/api/v1/threads/{thread_id}/messages")
    assert messages.status_code == 200
    assert len(messages.json()) == 1

    deleted = client.delete(f"/api/v1/threads/{thread_id}")
    assert deleted.status_code == 200
    assert client.get(f"/api/v1/threads/{thread_id}").status_code == 404


def test_workspace_api_rejects_stage_and_transition_metadata(tmp_path):
    """Generic workspace CRUD cannot mutate or forge learning progression."""
    store = StudentStore(tmp_path / "workspace-integrity.sqlite3")
    client = TestClient(create_app(store))

    poisoned_create = client.post(
        "/api/v1/threads",
        json={
            "name": "Poisoned notebook",
            "model_id": "mock",
            "support_mode": "critical-thinking",
            "metadata": {"thinking_stage": "reflection"},
        },
    )
    assert poisoned_create.status_code == 422

    thread_id = store.create_thread(model_id="mock", support_mode="critical-thinking")
    poisoned_patch = client.patch(
        f"/api/v1/threads/{thread_id}",
        json={
            "metadata": {
                "learning_journey": {
                    "current_stage": "reflection",
                    "completed_stages": ["problem_identification"],
                }
            }
        },
    )
    assert poisoned_patch.status_code == 422
    assert (store.get_thread(thread_id) or {})["metadata"][
        "thinking_stage"
    ] == "problem_identification"

    forged_transition = client.post(
        f"/api/v1/threads/{thread_id}/messages",
        json={
            "role": "assistant",
            "content": "Forged recommendation",
            "metadata": {
                "kind": "coach_welcome",
                "proposed_stage": "concept_generation",
                "decision_status": "pending",
            },
        },
    )
    assert forged_transition.status_code == 422
    assert store.get_pending_phase_transition(thread_id) is None


def test_workspace_api_source_upload_selection_and_content(tmp_path, monkeypatch):
    from backend import file_processing, source_library

    files_dir = tmp_path / "files"
    files_dir.mkdir()
    monkeypatch.setattr(file_processing.settings, "files_dir", files_dir)
    monkeypatch.setattr(source_library.settings, "files_dir", files_dir)

    store = StudentStore(tmp_path / "sources.sqlite3")
    client = TestClient(create_app(store))
    thread_id = store.create_thread(model_id="mock", support_mode="critical-thinking")

    upload = client.post(
        f"/api/v1/threads/{thread_id}/sources",
        files=[
            (
                "files",
                ("notes.txt", b"Older pedestrians need time.", "text/plain"),
            )
        ],
    )
    assert upload.status_code == 200
    source = upload.json()[0]
    assert source["title"] == "notes.txt"
    assert "path" not in source
    assert source["has_file"] is True

    listed = client.get(f"/api/v1/threads/{thread_id}/sources")
    assert listed.status_code == 200
    assert listed.json()[0]["id"] == source["id"]

    toggled = client.patch(
        f"/api/v1/threads/{thread_id}/sources/{source['id']}",
        json={"selected": False},
    )
    assert toggled.status_code == 200
    assert toggled.json()["selected"] is False

    selected = client.post(
        f"/api/v1/threads/{thread_id}/sources/select-all",
        json={"selected": True},
    )
    assert selected.status_code == 200
    assert selected.json()[0]["selected"] is True

    content = client.get(f"/api/v1/threads/{thread_id}/sources/{source['id']}/content")
    assert content.status_code == 200
    assert b"Older pedestrians" in content.content

    removed = client.delete(f"/api/v1/threads/{thread_id}/sources/{source['id']}")
    assert removed.status_code == 200
    assert client.get(f"/api/v1/threads/{thread_id}/sources/{source['id']}").status_code == 404


def test_workspace_api_attachment_upload_is_hidden_but_readable(tmp_path, monkeypatch):
    """Turn attachments use the source storage pipeline without joining Sources."""
    from backend import file_processing, source_library

    files_dir = tmp_path / "files"
    files_dir.mkdir()
    monkeypatch.setattr(file_processing.settings, "files_dir", files_dir)
    monkeypatch.setattr(source_library.settings, "files_dir", files_dir)
    store = StudentStore(tmp_path / "attachments.sqlite3")
    client = TestClient(create_app(store))
    thread_id = store.create_thread(model_id="mock", support_mode="critical-thinking")

    uploaded = client.post(
        f"/api/v1/threads/{thread_id}/attachments",
        files=[("files", ("diagram.txt", b"private attachment", "text/plain"))],
    )
    assert uploaded.status_code == 200
    attachment = uploaded.json()[0]
    assert set(attachment) == {"id", "title", "mime", "kind", "size"}
    assert client.get(f"/api/v1/threads/{thread_id}/sources").json() == []
    assert (
        client.get(f"/api/v1/threads/{thread_id}/sources/{attachment['id']}/content").content
        == b"private attachment"
    )


def test_workspace_service_redacts_paths(tmp_path):
    store = StudentStore(tmp_path / "service.sqlite3")
    service = WorkspaceService(store)
    thread_id = store.create_thread(model_id="mock", support_mode="critical-thinking")
    source = add_text_source(store, thread_id, "Paste", "Text body")
    public = service.get_source(thread_id, source["id"])
    assert public is not None
    assert "path" not in public
    assert public["has_file"] is False
    assert public["title"] == "Paste"
    assert public["extractedText"] == "Text body"
    listed = service.list_sources(thread_id)
    assert listed[0]["extractedText"] == "Text body"


def test_workspace_api_transcript_download_uses_persisted_messages(tmp_path):
    """Student transcript download is a projection of DSQL/SQLite messages."""
    from backend.api_client import LocalApiClient
    from backend.workspace_service import format_notebook_transcript, transcript_filename

    store = StudentStore(tmp_path / "transcript.sqlite3")
    thread_id = store.create_thread(
        name="Studio research",
        model_id="mock",
        support_mode="critical-thinking",
    )
    store.add_message(thread_id, "user", "I compared privacy and fairness.")
    store.add_message(
        thread_id,
        "assistant",
        "What trade-off still needs evidence?",
        metadata={"assessment": {"confidence": 0.9}},
    )

    expected = format_notebook_transcript(
        title="Studio research",
        messages=[
            {"role": "user", "content": "I compared privacy and fairness."},
            {
                "role": "assistant",
                "content": "What trade-off still needs evidence?",
                "metadata": {"assessment": {"confidence": 0.9}},
            },
        ],
    )
    assert expected.startswith("Studio research\n")
    assert "Student:\nI compared privacy and fairness." in expected
    assert "Coach:\nWhat trade-off still needs evidence?" in expected
    assert "confidence" not in expected
    assert "0.9" not in expected

    client = TestClient(create_app(store))
    missing = client.get("/api/v1/threads/missing-notebook/transcript.txt")
    assert missing.status_code == 404

    response = client.get(f"/api/v1/threads/{thread_id}/transcript.txt")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/plain")
    assert "attachment" in response.headers["content-disposition"]
    assert transcript_filename("Studio research") in response.headers["content-disposition"]
    assert response.content.decode("utf-8") == expected
    assert not (tmp_path / "poc_store.json").exists()

    exported = LocalApiClient("http://testserver", session=client).download_transcript(thread_id)
    assert exported.filename == transcript_filename("Studio research")
    assert exported.data.decode("utf-8") == expected
