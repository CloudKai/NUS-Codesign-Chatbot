"""Shared turn lifecycle contracts through the authenticated application API."""

from pathlib import Path
import pytest

from fastapi.testclient import TestClient

from backend.api import create_app
from backend.student_store import StudentStore


def test_recovery_requires_exact_identity_and_survives_restart(tmp_path: Path) -> None:
    """Unrelated replies cannot complete a pending request; saved replies survive restart."""
    database = tmp_path / "recovery.sqlite3"
    store = StudentStore(database)
    thread_id = store.create_thread(model_id="mock", support_mode="critical-thinking")
    client = TestClient(create_app(store, auto_advance_stages=False))
    path = f"/api/v1/threads/{thread_id}/coach-turn"
    request = {
        "thread_id": thread_id,
        "student_message": "Assess my design idea.",
        "current_stage": "problem_identification",
        "response_detail": "short",
        "idempotency_key": "exact-turn",
    }
    assert client.get(path, params={"idempotency_key": "exact-turn"}).json() is None
    unrelated = client.post("/api/v1/coach/turn", json={**request, "idempotency_key": "other-turn"})
    assert unrelated.status_code == 200
    assert client.get(path, params={"idempotency_key": "exact-turn"}).json() is None
    saved = client.post("/api/v1/coach/turn", json=request)
    assert saved.status_code == 200
    restarted = TestClient(create_app(StudentStore(database), auto_advance_stages=False))
    recovered = restarted.get(path, params={"idempotency_key": "exact-turn"})
    assert recovered.status_code == 200
    assert recovered.json() == saved.json()
    assert restarted.post("/api/v1/coach/turn", json=request).json() == saved.json()
    assert len(store.get_messages(thread_id)) == 4
    stranger = StudentStore(database, identifier="unrelated-student")
    assert TestClient(create_app(stranger)).get(path, params={"idempotency_key": "exact-turn"}).status_code == 404


def test_completed_graph_resources_plateau_and_summary_survives_restart(tmp_path: Path) -> None:
    """Many saved turns retain no run checkpoints and keep a restartable summary."""
    database = tmp_path / "plateau.sqlite3"
    store = StudentStore(database)
    thread_id = store.create_thread(model_id="mock", support_mode="critical-thinking")
    client = TestClient(create_app(store, auto_advance_stages=False))
    for index in range(30):
        saved = client.post("/api/v1/coach/turn", json={
            "thread_id": thread_id,
            "student_message": f"Assess design constraint {index}.",
            "current_stage": "problem_identification",
            "response_detail": "short",
            "idempotency_key": f"turn-{index}",
        })
        assert saved.status_code == 200
        summary = client.get(f"/api/v1/threads/{thread_id}/graph").json()
        assert summary["retention"]["completed_checkpoints"] == 0
        assert summary["retention"]["cached_threads"] <= 64
        assert summary["turn"]["response_text"] == saved.json()["response_text"]
    restarted = TestClient(create_app(StudentStore(database), auto_advance_stages=False))
    summary = restarted.get(f"/api/v1/threads/{thread_id}/graph").json()
    assert summary["mode"] == "persisted"
    assert summary["turn"]["response_text"] == saved.json()["response_text"]
    assert summary["steps"] == ["load_context", "assess", "recommend", "format"]


@pytest.mark.parametrize("use_api", [False, True])
@pytest.mark.parametrize("fail_save", [False, True])
def test_stream_lifecycle_matches_across_clients(monkeypatch: pytest.MonkeyPatch, use_api: bool, fail_save: bool) -> None:
    """Both clients acknowledge dispatch, preview, and then saved output or a safe error."""
    from backend.api_client import LocalApiClient
    from backend.domain import CoachRequest
    from ui.services import runtime

    runtime.bind_owner_identifier("local-student")
    store, _, coach, _ = runtime.resources("local-student")
    thread_id = store.create_thread(model_id="mock", support_mode="critical-thinking")
    client = LocalApiClient("http://testserver", session=TestClient(create_app(store)))
    monkeypatch.setattr(runtime, "local_api_enabled", lambda: use_api)
    monkeypatch.setattr(runtime, "local_api_client", lambda: client)
    if fail_save:
        def unavailable_storage(*args: object, **kwargs: object) -> None:
            raise OSError("private storage failure details")
        monkeypatch.setattr(StudentStore, "persist_coach_turn", unavailable_storage)
    events = list(runtime.stream_coach_turn_events(CoachRequest(
        thread_id=thread_id,
        student_message="Assess the accessibility constraint.",
        current_stage="problem_identification",
        response_detail="short",
        idempotency_key="stream-identity",
    )))
    assert events[0] == {
        "event": "started", "thread_id": thread_id,
        "stage": "problem_identification", "idempotency_key": "stream-identity",
    }
    kinds = [event["event"] for event in events]
    assert kinds.index("reply_ready") < len(events) - 1
    if fail_save:
        assert kinds[-1] == "error"
        assert events[-1]["status"] == 503
        assert "private storage" not in str(events)
        assert "done" not in kinds
        assert coach.completed_turn(thread_id, "stream-identity") is None
        assert client.graph_state(thread_id)["mode"] is None
        assert client.graph_state(thread_id)["retention"]["cached_threads"] == 0
    else:
        assert kinds[-1] == "done"
        assert coach.completed_turn(thread_id, "stream-identity").model_dump(mode="json") == events[-1]["turn"]


@pytest.mark.parametrize("leave_after", ["started", "reply_ready"])
def test_leaving_stream_still_saves_one_exact_recoverable_turn(monkeypatch: pytest.MonkeyPatch, leave_after: str) -> None:
    """Closing a reader after dispatch or preview cannot cancel or duplicate saving."""
    import time
    from backend.api_client import LocalApiClient
    from backend.domain import CoachRequest
    from ui.services import runtime

    runtime.bind_owner_identifier("local-student")
    store, _, _, _ = runtime.resources("local-student")
    thread_id = store.create_thread(model_id="mock", support_mode="critical-thinking")
    client = LocalApiClient("http://testserver", session=TestClient(create_app(store)))
    monkeypatch.setattr(runtime, "local_api_enabled", lambda: False)
    request = CoachRequest(
        thread_id=thread_id, student_message="Assess my access constraint.",
        current_stage="problem_identification", response_detail="short",
        idempotency_key="left-stream",
    )
    stream = runtime.stream_coach_turn_events(request)
    for event in stream:
        if event["event"] == leave_after:
            break
    stream.close()
    deadline = time.monotonic() + 5
    recovered = None
    while recovered is None and time.monotonic() < deadline:
        recovered = client.completed_turn(thread_id, "left-stream")
        time.sleep(0.01)
    assert recovered is not None
    assert client.coach_turn(request) == recovered
    assert len(client.get_messages(thread_id)) == 2


def test_graph_summaries_are_bounded_across_notebooks(tmp_path: Path) -> None:
    """Evicted notebook summaries remain recoverable from saved transcript state."""
    store = StudentStore(tmp_path / "many-notebooks.sqlite3")
    client = TestClient(create_app(store))
    first_thread = ""
    for index in range(70):
        thread_id = store.create_thread(model_id="mock", support_mode="critical-thinking")
        first_thread = first_thread or thread_id
        assert client.post("/api/v1/coach/turn", json={
            "thread_id": thread_id, "student_message": "Assess this constraint.",
            "current_stage": "problem_identification", "response_detail": "short",
            "idempotency_key": f"notebook-{index}",
        }).status_code == 200
    summary = client.get(f"/api/v1/threads/{first_thread}/graph").json()
    assert summary["mode"] == "persisted"
    assert summary["turn"]["response_text"]
    assert summary["retention"] == {"cached_threads": 64, "completed_checkpoints": 0}


@pytest.mark.parametrize("interference", ["conflicting_retry", "summary_eviction"])
def test_other_requests_preserve_active_memory(monkeypatch: pytest.MonkeyPatch, interference: str) -> None:
    """A conflicting retry or summary eviction cannot erase memory awaiting save."""
    from backend.api_client import LocalApiClient
    from backend.domain import CoachRequest
    from backend.mock_provider import DeterministicCoachProvider
    from ui.services import runtime

    memory = {"version": "v1", "summary": "Keep the student access constraint."}
    original = DeterministicCoachProvider.assess

    def assess(self: DeterministicCoachProvider, request: CoachRequest):
        return original(self, request).model_copy(update={"conversation_memory": memory})

    monkeypatch.setattr(DeterministicCoachProvider, "assess", assess)
    runtime.bind_owner_identifier("local-student")
    store, _, coach, _ = runtime.resources("local-student")
    thread_id = store.create_thread(model_id="mock", support_mode="critical-thinking")
    client = TestClient(create_app(store))
    request = CoachRequest(
        thread_id=thread_id, student_message="Assess my access constraint.",
        current_stage="problem_identification", response_detail="short",
        idempotency_key="active-request",
    )

    def reject_conflicting_retry(_text: str) -> None:
        from backend.student_store import CoachIdempotencyConflictError

        if interference == "conflicting_retry":
            with pytest.raises(CoachIdempotencyConflictError):
                coach.submit(request.model_copy(update={"student_message": "Different input."}))
        else:
            for index in range(65):
                other_thread = store.create_thread(model_id="mock", support_mode="critical-thinking")
                coach.submit(request.model_copy(update={
                    "thread_id": other_thread, "idempotency_key": f"other-{index}",
                }))

    coach.submit(request, reply=reject_conflicting_retry)
    saved = LocalApiClient("http://testserver", session=client).get_thread(thread_id)
    assert saved["metadata"]["conversation_memory"] == memory
