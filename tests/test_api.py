from __future__ import annotations

from fastapi.testclient import TestClient

from backend.api import create_app
from backend.source_library import add_text_source
from backend.student_store import StudentStore


def test_local_api_runs_a_mock_turn_and_auto_advances(tmp_path):
    store = StudentStore(tmp_path / "api.sqlite3")
    thread_id = store.create_thread(model_id="mock", support_mode="critical-thinking")
    client = TestClient(create_app(store, auto_advance_stages=True))

    health = client.get("/api/v1/health")
    assert health.status_code == 200
    assert health.json()["mode"] == "local"

    response = client.post(
        "/api/v1/coach/turn",
        json={
            "thread_id": thread_id,
            "student_message": "I want to frame a question about this source.",
            "current_stage": "focus",
            "response_detail": "short",
        },
    )
    assert response.status_code == 200
    assert response.json()["assessment"]["current_stage"] == "focus"

    pending = client.get(f"/api/v1/threads/{thread_id}/phase-transitions/pending")
    assert pending.status_code == 200
    assert pending.json() is None

    follow_up = client.post(
        "/api/v1/coach/turn",
        json={
            "thread_id": thread_id,
            "student_message": (
                "I want to decide which crossing design gives older pedestrians enough "
                "time and visibility to cross safely."
            ),
            "current_stage": "focus",
            "response_detail": "short",
        },
    )

    assert follow_up.status_code == 200
    payload = follow_up.json()
    assert payload["assessment"]["recommendation"] == "advance"
    assert payload["pending_transition"] is None
    assert payload["auto_advanced_to"] == "evidence"
    assert "ready for the next part" in payload["response_text"]
    assert payload["response_text"].startswith("**Examine evidence**")
    assert "**Questions to explore**" in payload["response_text"]
    assert "Which group of older adults" in payload["response_text"]
    assert "I’ve moved you" not in payload["response_text"]

    assistant = store.get_messages(thread_id)[-1]
    assert assistant["metadata"]["thinking_stage"] == "evidence"

    learning_state = client.get(f"/api/v1/threads/{thread_id}/learning-state")
    assert learning_state.json()["learning_journey"]["current_stage"] == "evidence"
    pending = client.get(f"/api/v1/threads/{thread_id}/phase-transitions/pending")
    assert pending.json() is None


def test_local_api_can_retain_confirmation_mode(tmp_path):
    store = StudentStore(tmp_path / "manual-api.sqlite3")
    thread_id = store.create_thread(model_id="mock", support_mode="critical-thinking")
    client = TestClient(create_app(store, auto_advance_stages=False))
    request = {
        "thread_id": thread_id,
        "current_stage": "focus",
        "response_detail": "short",
    }

    client.post(
        "/api/v1/coach/turn",
        json={**request, "student_message": "I want to evaluate a crossing design."},
    )
    follow_up = client.post(
        "/api/v1/coach/turn",
        json={
            **request,
            "student_message": "Which design gives older pedestrians time to cross?",
        },
    )

    assert follow_up.status_code == 200
    assert follow_up.json()["pending_transition"]["to_stage"] == "evidence"
    state = client.get(f"/api/v1/threads/{thread_id}/learning-state").json()
    assert (state.get("learning_journey") or {}).get("current_stage", "focus") == "focus"

    transition_id = follow_up.json()["pending_transition"]["id"]
    resolved = client.post(
        f"/api/v1/threads/{thread_id}/phase-transitions/{transition_id}/resolve",
        json={"accepted": True},
    )
    assert resolved.status_code == 200
    advanced = client.get(f"/api/v1/threads/{thread_id}/learning-state").json()
    assert (advanced.get("learning_journey") or {}).get("current_stage") == "evidence"


def test_complex_guidance_is_stricter_before_recommending_advance(tmp_path):
    store = StudentStore(tmp_path / "complex-api.sqlite3")
    thread_id = store.create_thread(model_id="mock", support_mode="critical-thinking")
    client = TestClient(create_app(store, auto_advance_stages=False))
    request = {
        "thread_id": thread_id,
        "current_stage": "focus",
        "response_detail": "long",
    }

    client.post(
        "/api/v1/coach/turn",
        json={**request, "student_message": "I want to evaluate a crossing design."},
    )
    second = client.post(
        "/api/v1/coach/turn",
        json={
            **request,
            "student_message": "Which design gives older pedestrians time to cross?",
        },
    )
    assert second.status_code == 200
    assert second.json()["pending_transition"] is None

    third = client.post(
        "/api/v1/coach/turn",
        json={
            **request,
            "student_message": (
                "I will compare signal timing and curb cuts for older pedestrians "
                "near schools."
            ),
        },
    )
    assert third.status_code == 200
    assert third.json()["pending_transition"]["to_stage"] == "evidence"


def test_first_coaching_turn_generates_a_concise_model_assisted_title(tmp_path):
    store = StudentStore(tmp_path / "title-api.sqlite3")
    thread_id = store.create_thread(model_id="mock", support_mode="critical-thinking")
    client = TestClient(create_app(store))

    response = client.post(
        "/api/v1/coach/turn",
        json={
            "thread_id": thread_id,
            "student_message": "Helping elderly people cross the road safely without danger.",
            "current_stage": "focus",
            "response_detail": "short",
        },
    )

    assert response.status_code == 200
    assert store.get_thread(thread_id)["name"] == "Elderly Road Safety"


def test_local_api_persists_selected_source_citations(tmp_path):
    store = StudentStore(tmp_path / "source-api.sqlite3")
    thread_id = store.create_thread(model_id="mock", support_mode="critical-thinking")
    source = add_text_source(
        store,
        thread_id,
        "Week 1 lecture",
        "Older pedestrians may require longer crossing intervals.",
    )
    client = TestClient(create_app(store))

    response = client.post(
        "/api/v1/coach/turn",
        json={
            "thread_id": thread_id,
            "student_message": "What should I evaluate in this crossing design?",
            "current_stage": "focus",
            "response_detail": "short",
            "source_ids": [source["id"]],
            "source_context": "--- [S1] Week 1 lecture ---\nOlder pedestrians may require longer crossing intervals.",
        },
    )

    assert response.status_code == 200
    citation = response.json()["assessment"]["citations"][0]
    assert citation["source_id"] == source["id"]
    assert citation["label"] == "S1"
    assistant = store.get_messages(thread_id)[-1]
    assert assistant["metadata"]["source_refs"][0]["id"] == source["id"]


def test_local_api_resolves_selected_images_into_coach_turn(tmp_path, monkeypatch):
    from backend import file_processing, source_library
    from backend.source_library import add_file_sources

    files_dir = tmp_path / "files"
    files_dir.mkdir()
    monkeypatch.setattr(file_processing.settings, "files_dir", files_dir)
    monkeypatch.setattr(source_library.settings, "files_dir", files_dir)

    store = StudentStore(tmp_path / "image-api.sqlite3")
    thread_id = store.create_thread(model_id="mock", support_mode="critical-thinking")
    # Minimal valid 1x1 PNG.
    png = (
        b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01"
        b"\x08\x02\x00\x00\x00\x90wS\xde\x00\x00\x00\x0cIDATx\x9cc\xf8\x0f"
        b"\x00\x00\x01\x01\x00\x05\x18\xd8N\x00\x00\x00\x00IEND\xaeB`\x82"
    )
    created = add_file_sources(
        store,
        thread_id,
        [("crossing.png", png, "image/png")],
        origin="test",
    )
    assert created[0]["kind"] == "image"
    client = TestClient(create_app(store))

    response = client.post(
        "/api/v1/coach/turn",
        json={
            "thread_id": thread_id,
            "student_message": "What does this crossing photo show for older adults?",
            "current_stage": "focus",
            "response_detail": "short",
            "source_ids": [created[0]["id"]],
            "source_context": (
                "--- [S1] crossing.png ---\n"
                "[Image source. Inspect the accompanying image input.]"
            ),
        },
    )

    assert response.status_code == 200
    assert "selected image source" in response.json()["response_text"]
