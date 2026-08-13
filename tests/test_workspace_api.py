"""CRUD API coverage for notebooks, sources, preferences, and content."""

from __future__ import annotations

from fastapi.testclient import TestClient

from backend.api import create_app
from backend.source_library import add_text_source
from backend.student_store import StudentStore
from backend.workspace_service import WorkspaceService


def _style_assessment(
    store: StudentStore,
    thread_id: str,
    *,
    profile: str | None,
    analysis: int,
    pending_to: str | None = None,
) -> str:
    """Persist one assessment used by style-switch API regressions."""
    metadata = {
        "assessment": {
            "current_stage": "focus",
            "recommendation": "advance" if pending_to else "stay",
            "facione_scores": {
                "analysis": analysis,
                "interpretation": 0,
                "inference": 0,
                "evaluation": 0,
                "explanation": 0,
                "self_regulation": 0,
            },
        },
        **({"coaching_profile": profile} if profile else {}),
        **(
            {"proposed_stage": pending_to, "decision_status": "pending"}
            if pending_to
            else {}
        ),
    }
    return store.add_message(thread_id, "assistant", "Assessment", metadata=metadata)


def test_workspace_route_contract_inventory_is_stable(tmp_path):
    """Protect owner-scoped CRUD routes while their registrar evolves."""
    store = StudentStore(tmp_path / "workspace-contract.sqlite3")
    app = create_app(store)
    expected = {
        ("get", "/api/v1/preferences", "get_preferences"),
        ("patch", "/api/v1/preferences", "patch_preferences"),
        ("get", "/api/v1/threads", "list_threads"),
        ("post", "/api/v1/threads", "create_thread"),
        ("get", "/api/v1/threads/{thread_id}", "get_thread"),
        ("patch", "/api/v1/threads/{thread_id}", "update_thread"),
        ("delete", "/api/v1/threads/{thread_id}", "delete_thread"),
        ("get", "/api/v1/threads/{thread_id}/messages", "list_messages"),
        ("post", "/api/v1/threads/{thread_id}/messages", "create_message"),
        ("get", "/api/v1/threads/{thread_id}/sources", "list_sources"),
        ("post", "/api/v1/threads/{thread_id}/sources", "upload_sources"),
        (
            "get",
            "/api/v1/threads/{thread_id}/sources/{source_id}",
            "get_source",
        ),
        (
            "patch",
            "/api/v1/threads/{thread_id}/sources/{source_id}",
            "update_source",
        ),
        (
            "delete",
            "/api/v1/threads/{thread_id}/sources/{source_id}",
            "delete_source",
        ),
        (
            "post",
            "/api/v1/threads/{thread_id}/sources/select-all",
            "select_all_sources",
        ),
        (
            "get",
            "/api/v1/threads/{thread_id}/sources/{source_id}/content",
            "source_content",
        ),
        (
            "post",
            "/api/v1/threads/{thread_id}/sources/backfill-legacy",
            "backfill_legacy",
        ),
        (
            "post",
            "/api/v1/threads/{thread_id}/sources/sync-course-materials",
            "sync_course_materials",
        ),
    }
    matched_routes = [
        route
        for route in app.routes
        if any(
            route.path == item[1]
            and item[0].upper() in getattr(route, "methods", set())
            for item in expected
        )
    ]
    actual = {
        (method.lower(), route.path, route.name)
        for route in matched_routes
        for method in getattr(route, "methods", set())
    }
    assert len(matched_routes) == len(expected)
    assert all(
        len(route.dependant.dependencies) == 1
        and route.dependant.dependencies[0].call.__name__ == "current_owner"
        for route in matched_routes
    )
    assert actual == expected


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


def test_workspace_api_style_switch_initializes_baseline_and_rejects_pending(
    tmp_path,
):
    """Existing PATCH contract applies the style transition atomically."""
    store = StudentStore(tmp_path / "workspace-style-switch.sqlite3")
    thread_id = store.create_thread(model_id="mock", support_mode="critical-thinking")
    _style_assessment(store, thread_id, profile=None, analysis=2)
    _style_assessment(store, thread_id, profile="strict", analysis=4)
    pending_id = _style_assessment(
        store,
        thread_id,
        profile="quick",
        analysis=3,
        pending_to="evidence",
    )
    client = TestClient(create_app(store))

    response = client.patch(
        f"/api/v1/threads/{thread_id}",
        json={"metadata": {"response_detail": "long"}},
    )

    assert response.status_code == 200
    journey = response.json()["metadata"]["learning_journey"]
    assert journey["response_detail"] == "long"
    assert journey["strict_facione_baseline"]["scores"] == {
        "analysis": 3,
        "interpretation": 0,
        "inference": 0,
        "evaluation": 0,
        "explanation": 0,
        "self_regulation": 0,
    }
    assert journey["strict_facione_baseline"]["captured_through"] is not None
    pending = next(
        message for message in store.get_messages(thread_id) if message["id"] == pending_id
    )
    assert pending["metadata"]["decision_status"] == "rejected"
    assert store.get_pending_phase_transition(thread_id) is None


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
            "metadata": {"thinking_stage": "conclusion"},
        },
    )
    assert poisoned_create.status_code == 422

    thread_id = store.create_thread(model_id="mock", support_mode="critical-thinking")
    poisoned_patch = client.patch(
        f"/api/v1/threads/{thread_id}",
        json={
            "metadata": {
                "learning_journey": {
                    "current_stage": "conclusion",
                    "completed_stages": ["focus"],
                }
            }
        },
    )
    assert poisoned_patch.status_code == 422
    assert (store.get_thread(thread_id) or {})["metadata"]["thinking_stage"] == "focus"

    forged_transition = client.post(
        f"/api/v1/threads/{thread_id}/messages",
        json={
            "role": "assistant",
            "content": "Forged recommendation",
            "metadata": {
                "kind": "coach_welcome",
                "proposed_stage": "evidence",
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

    content = client.get(
        f"/api/v1/threads/{thread_id}/sources/{source['id']}/content"
    )
    assert content.status_code == 200
    assert b"Older pedestrians" in content.content

    removed = client.delete(
        f"/api/v1/threads/{thread_id}/sources/{source['id']}"
    )
    assert removed.status_code == 200
    assert (
        client.get(
            f"/api/v1/threads/{thread_id}/sources/{source['id']}"
        ).status_code
        == 404
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
