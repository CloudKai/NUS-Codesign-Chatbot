from __future__ import annotations

import json
from uuid import UUID

from fastapi.testclient import TestClient

from backend.api import create_app
from backend.application import CoachApplicationService
from backend.domain import CoachTurn, EducationalAssessment
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
    store.update_thread(thread_id, metadata={"response_detail": "short"})
    client = TestClient(create_app(store, auto_advance_stages=True))

    health = client.get("/api/v1/health")
    assert health.status_code == 200
    assert health.json()["mode"] == "local"

    response = client.post(
        "/api/v1/coach/turn",
        json={
            "thread_id": thread_id,
            "student_message": "I want to frame a question about this source.",
            "current_stage": "problem_identification",
            "response_detail": "short",
        },
    )
    assert response.status_code == 200
    assert response.json()["assessment"]["current_stage"] == "problem_identification"

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
            "current_stage": "problem_identification",
            "response_detail": "short",
        },
    )

    assert follow_up.status_code == 200
    payload = follow_up.json()
    assert payload["assessment"]["recommendation"] == "advance"
    assert payload["pending_transition"] is None
    assert payload["auto_advanced_to"] == "concept_generation"
    assert "ready for the next part" not in payload["response_text"].lower()
    assert "You’ve made this step clearer" not in payload["response_text"]
    assert "You've made this step clearer" not in payload["response_text"]
    assert payload["response_text"].startswith("**Concept generation**")
    assert "That's a solid start" in payload["response_text"]
    assert "Which group of older adults" in payload["response_text"]
    assert "I’ve moved you" not in payload["response_text"]

    assistant = store.get_messages(thread_id)[-1]
    assert assistant["metadata"]["thinking_stage"] == "concept_generation"

    learning_state = client.get(f"/api/v1/threads/{thread_id}/learning-state")
    assert learning_state.json()["learning_journey"]["current_stage"] == "concept_generation"
    pending = client.get(f"/api/v1/threads/{thread_id}/phase-transitions/pending")
    assert pending.json() is None


def test_local_api_can_retain_confirmation_mode(tmp_path, caplog):
    store = StudentStore(tmp_path / "manual-api.sqlite3")
    thread_id = store.create_thread(model_id="mock", support_mode="critical-thinking")
    store.update_thread(thread_id, metadata={"response_detail": "short"})
    client = TestClient(create_app(store, auto_advance_stages=False))
    request = {
        "thread_id": thread_id,
        "current_stage": "problem_identification",
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
    assert follow_up.json()["pending_transition"]["to_stage"] == "concept_generation"
    state = client.get(f"/api/v1/threads/{thread_id}/learning-state").json()
    assert (state.get("learning_journey") or {}).get("current_stage", "problem_identification") == "problem_identification"

    transition_id = follow_up.json()["pending_transition"]["id"]
    with caplog.at_level("INFO", logger="co_design.operational"):
        resolved = client.post(
            f"/api/v1/threads/{thread_id}/phase-transitions/{transition_id}/resolve",
            json={"accepted": True},
        )
    assert resolved.status_code == 200
    stage_event = next(
        json.loads(record.getMessage())
        for record in caplog.records
        if record.name == "co_design.operational"
        and '"event":"stage_transition"' in record.getMessage()
    )
    assert stage_event == {"event": "stage_transition", "outcome": "accepted"}
    assert thread_id not in json.dumps(stage_event)
    assert transition_id not in json.dumps(stage_event)
    advanced = client.get(f"/api/v1/threads/{thread_id}/learning-state").json()
    assert (advanced.get("learning_journey") or {}).get("current_stage") == "concept_generation"


def test_confirm_advance_api_does_not_blank_existing_progress(tmp_path):
    store = StudentStore(tmp_path / "confirm-keep-progress.sqlite3")
    thread_id = store.create_thread(model_id="mock", support_mode="critical-thinking")
    store.update_thread(
        thread_id,
        metadata={
            "learning_summary": "previous summary",
            "working_conclusion": "previous conclusion",
            "understanding_change": "previous change",
            "critical_understanding": "Developing",
        },
    )
    created = store.create_phase_transition(
        {
            "thread_id": thread_id,
            "from_stage": "problem_identification",
            "to_stage": "concept_generation",
            "assessment": {
                "current_stage": "problem_identification",
                "contribution_summary": "The student named a focused question.",
                "recommendation": "advance",
                "learning_summary": "",
                "working_conclusion": "",
                "understanding_change": "",
                "critical_understanding_level": "",
            },
        }
    )
    client = TestClient(create_app(store, auto_advance_stages=False))

    resolved = client.post(
        f"/api/v1/threads/{thread_id}/phase-transitions/{created['id']}/resolve",
        json={"accepted": True},
    )

    assert resolved.status_code == 200
    state = client.get(f"/api/v1/threads/{thread_id}/learning-state").json()
    assert (state.get("learning_journey") or {}).get("current_stage") == (
        "concept_generation"
    )
    assert state.get("learning_summary") == "previous summary"
    assert state.get("working_conclusion") == "previous conclusion"
    assert state.get("understanding_change") == "previous change"
    assert state.get("critical_understanding") == "Developing"


def test_select_stage_api_requires_flag_and_valid_stage(tmp_path, monkeypatch, caplog):
    store = StudentStore(tmp_path / "select-api.sqlite3")
    thread_id = store.create_thread(model_id="mock", support_mode="critical-thinking")
    client = TestClient(create_app(store, auto_advance_stages=False))
    monkeypatch.setattr(settings, "student_stage_selection", False)

    disabled = client.post(
        f"/api/v1/threads/{thread_id}/learning-state/select-stage",
        json={"stage_id": "concept_generation"},
    )
    assert disabled.status_code == 400
    assert "not enabled" in disabled.json()["detail"].lower()

    monkeypatch.setattr(settings, "student_stage_selection", True)
    unknown = client.post(
        f"/api/v1/threads/{thread_id}/learning-state/select-stage",
        json={"stage_id": "nope"},
    )
    assert unknown.status_code == 400

    missing = client.post(
        "/api/v1/threads/missing-notebook/learning-state/select-stage",
        json={"stage_id": "concept_generation"},
    )
    assert missing.status_code == 404

    with caplog.at_level("INFO", logger="co_design.operational"):
        selected = client.post(
            f"/api/v1/threads/{thread_id}/learning-state/select-stage",
            json={"stage_id": "concept_generation"},
        )
    assert selected.status_code == 200
    body = selected.json()
    assert body["thinking_stage"] == "concept_generation"
    assert body["learning_journey"]["current_stage"] == "concept_generation"
    assert body["learning_journey"]["completed_stages"] == []
    stage_event = next(
        json.loads(record.getMessage())
        for record in caplog.records
        if record.name == "co_design.operational"
        and '"event":"stage_transition"' in record.getMessage()
    )
    assert stage_event["outcome"] == "selected"


def test_strict_guidance_is_stricter_before_recommending_advance(tmp_path):
    store = StudentStore(tmp_path / "complex-api.sqlite3")
    thread_id = store.create_thread(model_id="mock", support_mode="critical-thinking")
    store.update_thread(
        thread_id,
        metadata={
            "response_detail": "long",
            "learning_journey": {
                "current_stage": "problem_identification",
                "completed_stages": [],
                "stage_notes": {},
                "response_detail": "long",
            },
        },
    )
    client = TestClient(create_app(store, auto_advance_stages=False))
    request = {
        "thread_id": thread_id,
        "current_stage": "problem_identification",
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
    assert third.json()["pending_transition"]["to_stage"] == "concept_generation"


def test_first_coaching_turn_generates_a_concise_model_assisted_title(tmp_path):
    store = StudentStore(tmp_path / "title-api.sqlite3")
    thread_id = store.create_thread(model_id="mock", support_mode="critical-thinking")
    client = TestClient(create_app(store))

    response = client.post(
        "/api/v1/coach/turn",
        json={
            "thread_id": thread_id,
            "student_message": "Helping elderly people cross the road safely without danger.",
            "current_stage": "problem_identification",
            "response_detail": "short",
        },
    )

    assert response.status_code == 200
    assert store.get_thread(thread_id)["name"] == "Elderly Road Safety"


def test_local_api_grounds_mock_reply_in_retrieved_selected_source(tmp_path):
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
            "current_stage": "problem_identification",
            "response_detail": "short",
            "source_ids": [source["id"]],
            "source_context": "--- [S1] Week 1 lecture ---\nOlder pedestrians may require longer crossing intervals.",
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert "Older pedestrians may require longer crossing intervals." in payload[
        "response_text"
    ]
    assert "[S1]" in payload["response_text"]
    assert payload["assessment"]["citations"] == [
        {
            "source_id": source["id"],
            "label": "S1",
            "title": "Week 1 lecture",
            "excerpt": "Older pedestrians may require longer crossing intervals.",
        }
    ]
    assistant = store.get_messages(thread_id)[-1]
    assert assistant["metadata"]["source_refs"] == [
        {"id": source["id"], "label": "S1", "title": "Week 1 lecture"}
    ]


def test_local_api_persists_mock_response_citations(tmp_path):
    store = StudentStore(tmp_path / "cited-api.sqlite3")
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
            "student_message": "What does the lecture say about crossings?",
            "current_stage": "problem_identification",
            "response_detail": "short",
            "source_ids": [source["id"]],
            "source_context": "--- [S1] Week 1 lecture ---\nOlder pedestrians may require longer crossing intervals.",
        },
    )

    assert response.status_code == 200
    assert "[S1]" in response.json()["response_text"]
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
            "current_stage": "problem_identification",
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
                "current_stage": "concept_generation",
                "completed_stages": ["problem_identification"],
                "stage_notes": {},
            },
            "thinking_stage": "concept_generation",
        },
    )
    client = TestClient(create_app(store, auto_advance_stages=False))

    response = client.post(
        "/api/v1/coach/turn",
        json={
            "thread_id": thread_id,
            "student_message": "Trying to jump back to focus.",
            "current_stage": "problem_identification",
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
            "current_stage": "problem_identification",
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
            "current_stage": "problem_identification",
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
            "current_stage": "problem_identification",
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
            "current_stage": "problem_identification",
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
            "current_stage": "problem_identification",
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
            "current_stage": "problem_identification",
            "response_detail": "short",
        },
    )

    assert response.status_code == 503
    detail = response.json()["detail"]
    assert detail["message"] == "mock provider offline"
    assert detail["category"] == "unavailable"


def test_operational_metrics_are_aggregate_and_do_not_log_student_content(
    tmp_path, caplog
):
    """API logs aggregate latency/retrieval/citation outcomes, never prompt text."""
    store = StudentStore(tmp_path / "operational-metrics.sqlite3")
    thread_id = store.create_thread(model_id="mock", support_mode="critical-thinking")
    source = add_text_source(
        store,
        thread_id,
        "Road evidence",
        "The trial reports an 18 percent capacity loss in low light.",
    )
    sensitive_prompt = "PRIVATE_STUDENT_PROMPT_DO_NOT_LOG"
    client = TestClient(create_app(store))

    with caplog.at_level("INFO", logger="co_design.operational"):
        response = client.post(
            "/api/v1/coach/turn",
            json={
                "thread_id": thread_id,
                "student_message": "PRIVATE_STUDENT_PROMPT_DO_NOT_LOG What does the selected source say?",
                "current_stage": "problem_identification",
                "source_ids": [source["id"]],
                "response_detail": "short",
            },
        )

    assert response.status_code == 200
    messages = [
        json.loads(record.getMessage())
        for record in caplog.records
        if record.name == "co_design.operational"
    ]
    coach = next(message for message in messages if message["event"] == "coach_turn")
    http = next(message for message in messages if message["event"] == "http_request")
    assert coach == {
        "citation_count": 1,
        "citation_outcome": "cited",
        "event": "coach_turn",
        "outcome": "ok",
        "provider": "mock",
        "recommendation": "stay",
        "retrieval_outcome": "cited",
        "selected_source_count": 1,
        "transition_outcome": "none",
    }
    assert http["method"] == "POST"
    assert http["route"] == "/api/v1/coach/turn"
    assert http["status_code"] == 200
    assert isinstance(http["duration_ms"], float)
    rendered_metrics = "\n".join(record.getMessage() for record in caplog.records)
    assert sensitive_prompt not in rendered_metrics
    assert source["id"] not in rendered_metrics
    assert thread_id not in rendered_metrics


def test_operational_metrics_use_store_selected_sources_when_client_omits_ids(
    tmp_path, caplog
):
    """UI-style empty source_ids still report the notebook's selected sources."""
    store = StudentStore(tmp_path / "operational-metrics-ui.sqlite3")
    thread_id = store.create_thread(model_id="mock", support_mode="critical-thinking")
    add_text_source(
        store,
        thread_id,
        "Road evidence",
        "The trial reports an 18 percent capacity loss in low light.",
    )
    client = TestClient(create_app(store))

    with caplog.at_level("INFO", logger="co_design.operational"):
        response = client.post(
            "/api/v1/coach/turn",
            json={
                "thread_id": thread_id,
                "student_message": "What does the evidence say?",
                "current_stage": "problem_identification",
                "response_detail": "short",
            },
        )

    assert response.status_code == 200
    coach = next(
        json.loads(record.getMessage())
        for record in caplog.records
        if record.name == "co_design.operational"
        and '"event":"coach_turn"' in record.getMessage()
    )
    assert coach["selected_source_count"] == 1
    assert coach["retrieval_outcome"] == "cited"


def test_operational_metrics_record_provider_failure_without_thread_identifier(
    tmp_path, monkeypatch, caplog
):
    """Unavailable providers are countable without logging a notebook identity."""
    from backend.providers import ProviderUnavailableError
    from backend.workflow import CoachWorkflow

    store = StudentStore(tmp_path / "provider-metric.sqlite3")
    thread_id = store.create_thread(model_id="mock", support_mode="critical-thinking")

    def fail_run(self, request):
        raise ProviderUnavailableError("offline")

    monkeypatch.setattr(CoachWorkflow, "run", fail_run)
    client = TestClient(create_app(store))
    with caplog.at_level("INFO", logger="co_design.operational"):
        response = client.post(
            "/api/v1/coach/turn",
            json={
                "thread_id": thread_id,
                "student_message": "private message",
                "current_stage": "problem_identification",
                "response_detail": "short",
            },
        )

    assert response.status_code == 503
    coach = next(
        json.loads(record.getMessage())
        for record in caplog.records
        if record.name == "co_design.operational"
        and '"event":"coach_turn"' in record.getMessage()
    )
    assert coach["outcome"] == "provider_unavailable"
    assert coach["retrieval_outcome"] == "not_requested"
    assert thread_id not in json.dumps(coach)


def test_local_api_maps_safety_blocked_to_structured_503(tmp_path, monkeypatch, caplog):
    """Guardrail blocks stay 503 with a category, never prompt or AWS bodies."""
    from backend.providers import ProviderUnavailableError
    from backend.workflow import CoachWorkflow

    store = StudentStore(tmp_path / "provider-blocked.sqlite3")
    thread_id = store.create_thread(model_id="mock", support_mode="critical-thinking")

    def fail_run(self, request):
        raise ProviderUnavailableError(
            "AgentCore blocked this turn", category="safety_blocked"
        )

    monkeypatch.setattr(CoachWorkflow, "run", fail_run)
    client = TestClient(create_app(store))
    with caplog.at_level("INFO", logger="co_design.operational"):
        response = client.post(
            "/api/v1/coach/turn",
            json={
                "thread_id": thread_id,
                "student_message": "PRIVATE_STUDENT_PROMPT_DO_NOT_LOG",
                "current_stage": "problem_identification",
                "response_detail": "short",
            },
        )
        stream = client.post(
            "/api/v1/coach/turn/stream",
            json={
                "thread_id": thread_id,
                "student_message": "PRIVATE_STUDENT_PROMPT_DO_NOT_LOG",
                "current_stage": "problem_identification",
                "response_detail": "short",
            },
        )

    assert response.status_code == 503
    detail = response.json()["detail"]
    assert detail["category"] == "safety_blocked"
    assert detail["message"] == "AgentCore blocked this turn"
    assert "PROMPT_ATTACK" not in response.text
    assert "PRIVATE_STUDENT_PROMPT_DO_NOT_LOG" not in response.text
    events = [
        json.loads(line)
        for line in stream.text.splitlines()
        if line.strip()
    ]
    error = next(event for event in events if event.get("event") == "error")
    assert error["status"] == 503
    assert error["category"] == "safety_blocked"
    assert error["detail"] == "AgentCore blocked this turn"
    coach = next(
        json.loads(record.getMessage())
        for record in caplog.records
        if record.name == "co_design.operational"
        and '"event":"coach_turn"' in record.getMessage()
        and '"outcome":"safety_blocked"' in record.getMessage()
    )
    assert coach["outcome"] == "safety_blocked"
    assert thread_id not in json.dumps(coach)


def test_local_api_maps_structured_output_failure_to_structured_503(
    tmp_path, monkeypatch, caplog
):
    """Malformed AgentResult stays 503 with a category, never JSONDecodeError."""
    from backend.providers import ProviderUnavailableError
    from backend.workflow import CoachWorkflow

    store = StudentStore(tmp_path / "provider-structured.sqlite3")
    thread_id = store.create_thread(model_id="mock", support_mode="critical-thinking")

    def fail_run(self, request):
        raise ProviderUnavailableError(
            "The coach reply could not be completed",
            category="structured_output_failure",
        )

    monkeypatch.setattr(CoachWorkflow, "run", fail_run)
    client = TestClient(create_app(store))
    with caplog.at_level("INFO", logger="co_design.operational"):
        response = client.post(
            "/api/v1/coach/turn",
            json={
                "thread_id": thread_id,
                "student_message": "A quiet residential street",
                "current_stage": "problem_identification",
                "response_detail": "short",
            },
        )
        stream = client.post(
            "/api/v1/coach/turn/stream",
            json={
                "thread_id": thread_id,
                "student_message": "A quiet residential street",
                "current_stage": "problem_identification",
                "response_detail": "short",
            },
        )

    assert response.status_code == 503
    detail = response.json()["detail"]
    assert detail["category"] == "structured_output_failure"
    assert "JSONDecodeError" not in response.text
    assert "AgentResult" not in response.text
    events = [
        json.loads(line)
        for line in stream.text.splitlines()
        if line.strip()
    ]
    error = next(event for event in events if event.get("event") == "error")
    assert error["status"] == 503
    assert error["category"] == "structured_output_failure"
    coach = next(
        json.loads(record.getMessage())
        for record in caplog.records
        if record.name == "co_design.operational"
        and '"event":"coach_turn"' in record.getMessage()
        and '"outcome":"structured_output_failure"' in record.getMessage()
    )
    assert coach["outcome"] == "structured_output_failure"
    assert thread_id not in json.dumps(coach)
    assert store.get_messages(thread_id) == []


def test_operational_metrics_do_not_log_unmatched_url_values(tmp_path, caplog):
    """Unknown paths use one bounded label instead of logging attacker input."""
    client = TestClient(create_app(StudentStore(tmp_path / "route-metric.sqlite3")))
    sensitive_path_value = "private-student@example.edu"

    with caplog.at_level("INFO", logger="co_design.operational"):
        response = client.get(f"/not-a-route/{sensitive_path_value}")

    assert response.status_code == 404
    event = next(
        json.loads(record.getMessage())
        for record in caplog.records
        if record.name == "co_design.operational"
        and '"event":"http_request"' in record.getMessage()
    )
    assert event["route"] == "<unmatched>"
    assert sensitive_path_value not in json.dumps(event)


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

    untrusted = "attacker value " * 40
    replaced = client.get("/api/v1/health", headers={"X-Request-ID": untrusted})
    generated_request_id = replaced.headers["x-request-id"]
    assert generated_request_id != untrusted
    assert str(UUID(generated_request_id)) == generated_request_id

    with client.stream(
        "POST",
        "/api/v1/coach/turn/stream",
        json={
            "thread_id": thread_id,
            "student_message": "I want to evaluate a crossing design.",
            "current_stage": "problem_identification",
            "response_detail": "short",
        },
    ) as response:
        assert response.status_code == 200
        lines = [line for line in response.iter_lines() if line]
    events = [__import__("json").loads(line) for line in lines]
    kinds = [event["event"] for event in events]
    assert kinds[0] == "started"
    assert kinds[1] == "status"
    assert events[1].get("phase") == "thinking"
    assert "token" not in kinds
    assert "saving" in [event.get("phase") for event in events if event.get("event") == "status"]
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


def test_production_readiness_requires_local_cognito_configuration_check(
    tmp_path, monkeypatch
):
    """DSQL/S3 readiness must fail closed when non-secret Cognito config is invalid."""

    class ReadyStorage:
        def ping(self) -> None:
            return None

    calls: list[bool] = []

    def invalid_cognito(*, require_https: bool) -> None:
        calls.append(require_https)
        raise ValueError("Cognito callback must use HTTPS in production")

    monkeypatch.setattr(settings, "database_provider", "sqlite")
    monkeypatch.setattr(settings, "file_storage_provider", "s3")
    monkeypatch.setattr(settings, "user_uploads_bucket", "test-uploads")
    monkeypatch.setattr("backend.persistence.factory.get_file_storage", lambda: ReadyStorage())
    monkeypatch.setattr("backend.api.validate_cognito_readiness", invalid_cognito)
    client = TestClient(create_app(StudentStore(tmp_path / "prod-ready.sqlite3")))

    response = client.get("/api/v1/ready")

    assert response.status_code == 503
    assert response.json()["detail"] == "Cognito callback must use HTTPS in production"
    assert calls == [True]


def test_production_readiness_redacts_dependency_error_details(tmp_path, monkeypatch):
    """IAM/provider exception details must not become a readiness response body."""

    class DeniedStorage:
        def ping(self) -> None:
            raise PermissionError("AccessDenied private-bucket-name")

    monkeypatch.setattr(settings, "file_storage_provider", "s3")
    monkeypatch.setattr(settings, "user_uploads_bucket", "test-uploads")
    monkeypatch.setattr("backend.persistence.factory.get_file_storage", lambda: DeniedStorage())
    client = TestClient(create_app(StudentStore(tmp_path / "prod-ready-denied.sqlite3")))

    response = client.get("/api/v1/ready")

    assert response.status_code == 503
    assert response.json()["detail"] == "File storage not ready"
    assert "private-bucket-name" not in response.text


def test_production_readiness_reports_cognito_configured_without_discovery(
    tmp_path, monkeypatch
):
    """A validated production config adds no OIDC network dependency to ready."""

    class ReadyStorage:
        def ping(self) -> None:
            return None

    calls: list[bool] = []
    monkeypatch.setattr(settings, "database_provider", "sqlite")
    monkeypatch.setattr(settings, "file_storage_provider", "s3")
    monkeypatch.setattr(settings, "user_uploads_bucket", "test-uploads")
    monkeypatch.setattr("backend.persistence.factory.get_file_storage", lambda: ReadyStorage())
    monkeypatch.setattr(
        "backend.api.validate_cognito_readiness",
        lambda *, require_https: calls.append(require_https),
    )
    client = TestClient(create_app(StudentStore(tmp_path / "prod-ready-ok.sqlite3")))

    response = client.get("/api/v1/ready")

    assert response.status_code == 200
    assert response.json()["mode"] == "production"
    assert response.json()["cognito_configured"] == "true"
    assert calls == [True]


def test_qa_null_recommendation_does_not_crash_coach_metrics(tmp_path, monkeypatch):
    """Q&A turns persist recommendation=None and must still emit done."""
    store = StudentStore(tmp_path / "qa-metric.sqlite3")
    thread_id = store.create_thread(model_id="mock", support_mode="critical-thinking")
    turn = CoachTurn(
        response_text="Week 1 covers the course framing [S1].",
        assessment=EducationalAssessment(
            current_stage="problem_identification",
            recommendation=None,
            response_mode="qa",
        ),
    )

    def _qa_submit(self, request, **_kwargs):
        del self, request
        return turn

    monkeypatch.setattr(CoachApplicationService, "submit", _qa_submit)
    client = TestClient(create_app(store, auto_advance_stages=False))
    payload = {
        "thread_id": thread_id,
        "student_message": "What is in Week 1 lecture?",
        "current_stage": "problem_identification",
        "response_detail": "short",
        "idempotency_key": "qa-metric-key",
    }
    regular = client.post("/api/v1/coach/turn", json=payload)
    streamed = client.post("/api/v1/coach/turn/stream", json=payload)
    assert regular.status_code == 200
    assert regular.json()["assessment"]["recommendation"] is None
    events = [json.loads(line) for line in streamed.text.splitlines() if line.strip()]
    assert events[-1]["event"] == "done"
    assert events[-1]["turn"]["assessment"]["recommendation"] is None
