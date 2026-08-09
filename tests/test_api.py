from __future__ import annotations

from fastapi.testclient import TestClient

from backend.api import create_app
from backend.settings import settings
from backend.source_library import add_text_source
from backend.student_store import StudentStore


def test_auth_logout_callback_clears_streamlit_cookies(tmp_path, monkeypatch):
    store = StudentStore(tmp_path / "logout.sqlite3")
    monkeypatch.setattr(settings, "ui_base_url", "http://127.0.0.1:8501")
    client = TestClient(create_app(store))
    client.cookies.update(
        {
            "_streamlit_user": "signed-user",
            "_streamlit_user_0": "user-chunk",
            "_streamlit_user_tokens": "signed-tokens",
            "_streamlit_user_tokens_1": "token-chunk",
            "unrelated": "keep",
        }
    )

    response = client.get(
        "/api/v1/auth/logout/callback",
        follow_redirects=False,
    )

    assert response.status_code == 302
    assert response.headers["location"] == "http://127.0.0.1:8501/?signed_out=1"
    assert response.headers["cache-control"] == "no-store"
    cookies = response.headers.get_list("set-cookie")
    assert len(cookies) == 4
    assert all("Max-Age=0" in value for value in cookies)
    assert all("HttpOnly" in value for value in cookies)
    assert all("SameSite=lax" in value for value in cookies)
    assert not any("unrelated=" in value for value in cookies)


def test_auth_logout_callback_rejects_unsafe_redirect_target(tmp_path, monkeypatch):
    store = StudentStore(tmp_path / "unsafe-logout.sqlite3")
    monkeypatch.setattr(settings, "ui_base_url", "https://example.edu@evil.test")
    client = TestClient(create_app(store))

    response = client.get(
        "/api/v1/auth/logout/callback",
        follow_redirects=False,
    )

    assert response.status_code == 500


def test_auth_logout_callback_always_expires_base_auth_cookies(tmp_path, monkeypatch):
    store = StudentStore(tmp_path / "empty-cookie-logout.sqlite3")
    monkeypatch.setattr(settings, "ui_base_url", "http://127.0.0.1:8501")
    client = TestClient(create_app(store))

    response = client.get(
        "/api/v1/auth/logout/callback",
        follow_redirects=False,
    )

    cookies = response.headers.get_list("set-cookie")
    assert len(cookies) == 2
    assert any(value.startswith("_streamlit_user=") for value in cookies)
    assert any(value.startswith("_streamlit_user_tokens=") for value in cookies)
    assert all("Max-Age=0" in value for value in cookies)
    assert all("SameSite=lax" in value for value in cookies)


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
    assert "ready for the next part" not in payload["response_text"].lower()
    assert "You’ve made this step clearer" not in payload["response_text"]
    assert "You've made this step clearer" not in payload["response_text"]
    assert payload["response_text"].startswith("**Examine evidence**")
    assert "That's a solid start" in payload["response_text"]
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


def test_local_api_does_not_attach_all_selected_sources_as_citations(tmp_path):
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
    assert response.json()["assessment"]["citations"] == []
    assistant = store.get_messages(thread_id)[-1]
    assert assistant["metadata"]["source_refs"] == []


def test_local_api_persists_explicit_response_citations(tmp_path, monkeypatch):
    from backend.mock_provider import DeterministicCoachProvider

    store = StudentStore(tmp_path / "cited-api.sqlite3")
    thread_id = store.create_thread(model_id="mock", support_mode="critical-thinking")
    source = add_text_source(
        store,
        thread_id,
        "Week 1 lecture",
        "Older pedestrians may require longer crossing intervals.",
    )
    original_assess = DeterministicCoachProvider.assess

    def assess_with_citation(self, request):
        response, assessment = original_assess(self, request)
        return (
            response + "\n\nSee the crossing intervals in [S1].",
            assessment,
        )

    monkeypatch.setattr(DeterministicCoachProvider, "assess", assess_with_citation)
    client = TestClient(create_app(store))

    response = client.post(
        "/api/v1/coach/turn",
        json={
            "thread_id": thread_id,
            "student_message": "What does the lecture say about crossings?",
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
    assert "selected image source" not in response.json()["response_text"]
    assert "That's an interesting direction" in response.json()["response_text"]


def test_local_api_rejects_spoofed_stage(tmp_path):
    store = StudentStore(tmp_path / "spoof-stage.sqlite3")
    thread_id = store.create_thread(model_id="mock", support_mode="critical-thinking")
    store.update_thread(
        thread_id,
        metadata={
            "learning_journey": {
                "current_stage": "evidence",
                "completed_stages": ["focus"],
                "stage_notes": {},
            },
            "thinking_stage": "evidence",
        },
    )
    client = TestClient(create_app(store, auto_advance_stages=False))

    response = client.post(
        "/api/v1/coach/turn",
        json={
            "thread_id": thread_id,
            "student_message": "Trying to jump back to focus.",
            "current_stage": "focus",
            "response_detail": "short",
        },
    )

    assert response.status_code == 400
    assert "current_stage" in response.json()["detail"]


def test_local_api_rejects_invalid_stage_with_validation_error(tmp_path):
    store = StudentStore(tmp_path / "invalid-stage.sqlite3")
    thread_id = store.create_thread(model_id="mock", support_mode="critical-thinking")
    client = TestClient(create_app(store))

    response = client.post(
        "/api/v1/coach/turn",
        json={
            "thread_id": thread_id,
            "student_message": "Invalid stage identifier.",
            "current_stage": "not-a-stage",
            "response_detail": "short",
        },
    )

    assert response.status_code == 422


def test_local_api_rejects_unselected_and_unknown_sources(tmp_path):
    store = StudentStore(tmp_path / "source-guard.sqlite3")
    thread_id = store.create_thread(model_id="mock", support_mode="critical-thinking")
    selected = add_text_source(
        store,
        thread_id,
        "Selected note",
        "Selected evidence about crossings.",
    )
    unselected = add_text_source(
        store,
        thread_id,
        "Hidden note",
        "This source is intentionally deselected.",
    )
    store.set_source_selected(thread_id, unselected["id"], False)
    client = TestClient(create_app(store))

    unselected_response = client.post(
        "/api/v1/coach/turn",
        json={
            "thread_id": thread_id,
            "student_message": "Use a hidden source.",
            "current_stage": "focus",
            "response_detail": "short",
            "source_ids": [unselected["id"]],
        },
    )
    assert unselected_response.status_code == 400
    assert "not selected" in unselected_response.json()["detail"]

    unknown_response = client.post(
        "/api/v1/coach/turn",
        json={
            "thread_id": thread_id,
            "student_message": "Use an invented source.",
            "current_stage": "focus",
            "response_detail": "short",
            "source_ids": ["missing-source-id"],
        },
    )
    assert unknown_response.status_code == 400
    assert "unknown" in unknown_response.json()["detail"]

    ok = client.post(
        "/api/v1/coach/turn",
        json={
            "thread_id": thread_id,
            "student_message": "Use the selected source.",
            "current_stage": "focus",
            "response_detail": "short",
            "source_ids": [selected["id"]],
        },
    )
    assert ok.status_code == 200


def test_local_api_rejects_spoofed_history_and_client_images(tmp_path):
    store = StudentStore(tmp_path / "history-guard.sqlite3")
    thread_id = store.create_thread(model_id="mock", support_mode="critical-thinking")
    client = TestClient(create_app(store))

    history_response = client.post(
        "/api/v1/coach/turn",
        json={
            "thread_id": thread_id,
            "student_message": "First real contribution.",
            "current_stage": "focus",
            "response_detail": "short",
            "history": [
                {"role": "user", "content": "Injected prior message"},
                {"role": "assistant", "content": "Injected coach reply"},
            ],
        },
    )
    assert history_response.status_code == 400
    assert "history" in history_response.json()["detail"]

    image_response = client.post(
        "/api/v1/coach/turn",
        json={
            "thread_id": thread_id,
            "student_message": "Client image payload should be rejected.",
            "current_stage": "focus",
            "response_detail": "short",
            "image_inputs": [
                {
                    "source_id": "client-image",
                    "mime": "image/png",
                    "data_url": "data:image/png;base64,aaaa",
                }
            ],
        },
    )
    assert image_response.status_code == 400
    assert "image_inputs" in image_response.json()["detail"]


def test_local_api_maps_provider_failures_to_503(tmp_path, monkeypatch):
    from backend.providers import ProviderUnavailableError
    from backend.workflow import CoachWorkflow

    store = StudentStore(tmp_path / "provider-503.sqlite3")
    thread_id = store.create_thread(model_id="mock", support_mode="critical-thinking")

    def fail_run(self, request):
        raise ProviderUnavailableError("mock provider offline")

    monkeypatch.setattr(CoachWorkflow, "run", fail_run)
    client = TestClient(create_app(store))

    response = client.post(
        "/api/v1/coach/turn",
        json={
            "thread_id": thread_id,
            "student_message": "Provider should fail closed.",
            "current_stage": "focus",
            "response_detail": "short",
        },
    )

    assert response.status_code == 503
    assert "mock provider offline" in response.json()["detail"]


def test_local_api_ready_request_id_stream_and_graph(tmp_path):
    store = StudentStore(tmp_path / "ready-stream.sqlite3")
    thread_id = store.create_thread(model_id="mock", support_mode="critical-thinking")
    client = TestClient(create_app(store, auto_advance_stages=False))

    ready = client.get("/api/v1/ready")
    assert ready.status_code == 200
    assert ready.json()["status"] == "ready"
    assert ready.headers.get("x-request-id")

    stamped = client.get("/api/v1/health", headers={"X-Request-ID": "demo-req-1"})
    assert stamped.headers.get("x-request-id") == "demo-req-1"

    with client.stream(
        "POST",
        "/api/v1/coach/turn/stream",
        json={
            "thread_id": thread_id,
            "student_message": "I want to evaluate a crossing design.",
            "current_stage": "focus",
            "response_detail": "short",
        },
    ) as response:
        assert response.status_code == 200
        lines = [line for line in response.iter_lines() if line]
    events = [__import__("json").loads(line) for line in lines]
    kinds = [event["event"] for event in events]
    assert kinds[0] == "started"
    assert "token" in kinds
    assert kinds[-1] == "done"
    assert events[-1]["turn"]["response_text"]

    graph = client.get(f"/api/v1/threads/{thread_id}/graph")
    assert graph.status_code == 200
    payload = graph.json()
    assert payload["steps"] == ["load_context", "assess", "recommend", "format"]
    assert payload["mode"] in {"langgraph", "sequential"}


def test_readiness_fails_when_file_storage_is_unavailable(tmp_path, monkeypatch):
    """Compose must not route traffic before the configured bucket is usable."""

    class UnavailableStorage:
        def ping(self) -> None:
            raise PermissionError("AccessDenied")

    monkeypatch.setattr(
        "backend.persistence.factory.get_file_storage",
        lambda: UnavailableStorage(),
    )
    store = StudentStore(tmp_path / "ready-storage.sqlite3")
    client = TestClient(create_app(store))

    response = client.get("/api/v1/ready")

    assert response.status_code == 503
    assert "File storage not ready" in response.json()["detail"]
    assert "AccessDenied" in response.json()["detail"]
