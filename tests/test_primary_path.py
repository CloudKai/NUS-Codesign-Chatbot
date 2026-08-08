"""Primary-path integrity tests: stages, restart, isolation, stale transitions."""

from __future__ import annotations

from fastapi.testclient import TestClient

from backend.api import create_app
from backend.source_library import add_text_source
from backend.student_journey import THINKING_STAGES
from backend.student_store import StudentStore


def _advance_message(stage_id: str) -> str:
    return (
        f"For the {stage_id} step I will compare signal timing and curb cuts so "
        "older pedestrians near schools can cross safely with enough time."
    )


def test_confirmation_mode_advances_through_all_six_stages(tmp_path):
    store = StudentStore(tmp_path / "six-stages.sqlite3")
    thread_id = store.create_thread(model_id="mock", support_mode="critical-thinking")
    client = TestClient(create_app(store, auto_advance_stages=False))

    for index, stage in enumerate(THINKING_STAGES[:-1]):
        first = client.post(
            "/api/v1/coach/turn",
            json={
                "thread_id": thread_id,
                "student_message": f"Starting {stage.id} with an initial framing.",
                "current_stage": stage.id,
                "response_detail": "short",
            },
        )
        assert first.status_code == 200, first.text
        assert first.json()["pending_transition"] is None

        follow_up = client.post(
            "/api/v1/coach/turn",
            json={
                "thread_id": thread_id,
                "student_message": _advance_message(stage.id),
                "current_stage": stage.id,
                "response_detail": "short",
            },
        )
        assert follow_up.status_code == 200, follow_up.text
        pending = follow_up.json()["pending_transition"]
        assert pending is not None
        assert pending["to_stage"] == THINKING_STAGES[index + 1].id

        resolved = client.post(
            f"/api/v1/threads/{thread_id}/phase-transitions/{pending['id']}/resolve",
            json={"accepted": True},
        )
        assert resolved.status_code == 200, resolved.text
        state = client.get(f"/api/v1/threads/{thread_id}/learning-state").json()
        assert state["learning_journey"]["current_stage"] == THINKING_STAGES[index + 1].id

    final = client.get(f"/api/v1/threads/{thread_id}/learning-state").json()
    assert final["learning_journey"]["current_stage"] == "conclusion"
    assert set(final["learning_journey"]["completed_stages"]) == {
        stage.id for stage in THINKING_STAGES[:-1]
    }


def test_rejected_and_stale_transitions_do_not_advance(tmp_path):
    store = StudentStore(tmp_path / "stale.sqlite3")
    thread_id = store.create_thread(model_id="mock", support_mode="critical-thinking")
    client = TestClient(create_app(store, auto_advance_stages=False))

    client.post(
        "/api/v1/coach/turn",
        json={
            "thread_id": thread_id,
            "student_message": "I want to evaluate a crossing design.",
            "current_stage": "focus",
            "response_detail": "short",
        },
    )
    follow_up = client.post(
        "/api/v1/coach/turn",
        json={
            "thread_id": thread_id,
            "student_message": _advance_message("focus"),
            "current_stage": "focus",
            "response_detail": "short",
        },
    )
    pending_id = follow_up.json()["pending_transition"]["id"]

    rejected = client.post(
        f"/api/v1/threads/{thread_id}/phase-transitions/{pending_id}/resolve",
        json={"accepted": False},
    )
    assert rejected.status_code == 200
    state = client.get(f"/api/v1/threads/{thread_id}/learning-state").json()
    assert (state.get("learning_journey") or {}).get("current_stage", "focus") == "focus"

    # Create a fresh recommendation, then move the journey out from under it.
    follow_up = client.post(
        "/api/v1/coach/turn",
        json={
            "thread_id": thread_id,
            "student_message": _advance_message("focus") + " Again.",
            "current_stage": "focus",
            "response_detail": "short",
        },
    )
    stale_id = follow_up.json()["pending_transition"]["id"]
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
    stale = client.post(
        f"/api/v1/threads/{thread_id}/phase-transitions/{stale_id}/resolve",
        json={"accepted": True},
    )
    assert stale.status_code == 404
    assert "stage changed" in stale.json()["detail"]


def test_restart_recovers_messages_journey_and_pending_transition(tmp_path):
    database = tmp_path / "restart.sqlite3"
    store = StudentStore(database)
    thread_id = store.create_thread(model_id="mock", support_mode="critical-thinking")
    client = TestClient(create_app(store, auto_advance_stages=False))

    client.post(
        "/api/v1/coach/turn",
        json={
            "thread_id": thread_id,
            "student_message": "I want to evaluate a crossing design.",
            "current_stage": "focus",
            "response_detail": "short",
        },
    )
    follow_up = client.post(
        "/api/v1/coach/turn",
        json={
            "thread_id": thread_id,
            "student_message": _advance_message("focus"),
            "current_stage": "focus",
            "response_detail": "short",
        },
    )
    pending_id = follow_up.json()["pending_transition"]["id"]
    message_count = len(store.get_messages(thread_id))

    reopened = StudentStore(database)
    assert len(reopened.get_messages(thread_id)) == message_count
    pending = reopened.get_pending_phase_transition(thread_id)
    assert pending is not None
    assert pending["id"] == pending_id
    assert (reopened.get_thread(thread_id) or {})["metadata"].get(
        "learning_summary"
    )

    restarted = TestClient(create_app(reopened, auto_advance_stages=False))
    pending_response = restarted.get(
        f"/api/v1/threads/{thread_id}/phase-transitions/pending"
    )
    assert pending_response.status_code == 200
    assert pending_response.json()["id"] == pending_id


def test_sources_and_history_stay_isolated_across_notebooks(tmp_path):
    store = StudentStore(tmp_path / "isolation.sqlite3")
    thread_a = store.create_thread(model_id="mock", support_mode="critical-thinking")
    thread_b = store.create_thread(model_id="mock", support_mode="critical-thinking")
    source_a = add_text_source(
        store,
        thread_a,
        "Notebook A evidence",
        "Older pedestrians need longer crossing intervals.",
    )
    client = TestClient(create_app(store, auto_advance_stages=False))

    assert store.list_sources(thread_b) == []
    assert store.get_source(thread_b, source_a["id"]) is None

    spoof = client.post(
        "/api/v1/coach/turn",
        json={
            "thread_id": thread_b,
            "student_message": "Using another notebook's source.",
            "current_stage": "focus",
            "response_detail": "short",
            "source_ids": [source_a["id"]],
        },
    )
    assert spoof.status_code == 400
    assert "unknown" in spoof.json()["detail"]

    client.post(
        "/api/v1/coach/turn",
        json={
            "thread_id": thread_a,
            "student_message": "Notebook A contribution.",
            "current_stage": "focus",
            "response_detail": "short",
            "source_ids": [source_a["id"]],
        },
    )
    assert store.get_messages(thread_b) == []
    assert len(store.get_messages(thread_a)) >= 2


def test_phase_transitions_persist_on_messages_across_reopen(tmp_path):
    database = tmp_path / "schema.sqlite3"
    store = StudentStore(database)
    thread_id = store.create_thread(model_id="mock", support_mode="critical-thinking")
    # Re-open the same file to ensure schema initialization is idempotent.
    reopened = StudentStore(database)
    assert reopened.get_thread(thread_id) is not None
    assert reopened.get_pending_phase_transition(thread_id) is None
    created = reopened.create_phase_transition(
        {
            "thread_id": thread_id,
            "from_stage": "focus",
            "to_stage": "evidence",
            "assessment": {
                "current_stage": "focus",
                "contribution_summary": "Schema check",
                "stage_assessment": "Ready for schema compatibility.",
                "critical_understanding_level": "Emerging",
                "confidence": 0.5,
                "recommendation": "advance",
                "recommendation_rationale": "Compatibility probe.",
                "learning_summary": "Schema probe summary.",
            },
        }
    )
    assert created["status"] == "pending"
    assert reopened.get_pending_phase_transition(thread_id)["id"] == created["id"]
    with reopened._connect() as connection:
        tables = {
            str(row["name"])
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
        }
    assert "phase_transitions" not in tables
    assert "messages" in tables
    assert "notebooks" in tables
