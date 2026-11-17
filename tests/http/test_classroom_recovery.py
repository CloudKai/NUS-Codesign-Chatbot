"""Classroom recovery characterization through the existing student HTTP API."""

from contextlib import closing
import json
from pathlib import Path
import shutil
import sqlite3

from fastapi.testclient import TestClient
from pytest import MonkeyPatch

from backend.api import create_app
from backend.mock_provider import DeterministicCoachProvider
from backend.settings import settings
from backend.student_store import StudentStore


def test_independent_restore_keeps_saved_answers_and_spent_allowance(
    tmp_path: Path, monkeypatch: MonkeyPatch,
) -> None:
    """A stopped backup restores exact replays without renewing spent funding.

    Fixture setup uses disposable stores. All behavioral assertions use HTTP,
    including source bytes, active history, exact-key recovery and exhaustion.
    This characterizes existing services; it introduces no second recovery engine.
    """
    import backend.owner_context as owners

    class UnpricedMock(DeterministicCoachProvider):
        """Retain the synthetic conservative charge after each offline call."""

        usage_provider = "unknown"

    policy = tmp_path / "policy.json"
    ledger = tmp_path / "generation.sqlite3"
    database = tmp_path / "students.sqlite3"
    policy.write_text(json.dumps({"ledger_path": str(ledger),
        "monthly_micro_sgd": 300, "headroom_micro_sgd": 100,
        "call_reserve_micro_sgd": 100, "max_running": 2, "max_queued": 2,
        "max_wait_seconds": .2, "lease_seconds": 600,
        "ceiling_evidence": "Synthetic fixture, not billing evidence"}))
    monkeypatch.setattr(settings, "generation_admission_policy", str(policy))
    monkeypatch.setattr(owners, "configured_coach_provider", UnpricedMock)
    store = StudentStore(database)
    thread = store.create_thread(model_id="mock", support_mode="critical-thinking")
    path = f"/api/v1/threads/{thread}"
    payload = {"thread_id": thread, "student_message": "What is analogy?",
        "interaction_intent": "lecture_help", "current_stage": "problem_identification",
        "response_detail": "short", "idempotency_key": "first"}
    source_bytes = b"Analogy transfers relationships between designs."
    with TestClient(create_app(store)) as client:
        source = client.post(f"{path}/sources", files={"files": ("notes.txt", source_bytes, "text/plain")}).json()[0]
        first = client.post("/api/v1/coach/turn", json=payload)
        assert first.status_code == 200
        assert first.json()["assessment"]["citations"][0]["source_id"] == source["id"]
        assert client.post("/api/v1/coach/turn", json={**payload, "idempotency_key": "second"}).status_code == 200
        messages = client.get(f"{path}/messages").json()
        export = client.get(f"{path}/transcript.txt").content

    # Every writer is stopped. Backups are independent of the unavailable
    # originals; SQLite backup includes any WAL pages before their removal.
    backups = tmp_path / "backup"
    backups.mkdir()
    for original in (database, ledger):
        with closing(sqlite3.connect(original)) as source_db, closing(sqlite3.connect(backups / original.name)) as target:
            source_db.backup(target)
        original.rename(original.with_suffix(".unavailable"))
        shutil.copy2(backups / original.name, original)

    with TestClient(create_app(StudentStore(database))) as restored:
        replay = restored.post("/api/v1/coach/turn", json=payload)
        assert replay.status_code == 200 and replay.json() == first.json()
        assert restored.get(f"{path}/messages").json() == messages
        assert restored.get(f"{path}/transcript.txt").content == export
        assert restored.get(f"{path}/sources/{source['id']}/content").content == source_bytes
        exhausted = restored.post("/api/v1/coach/turn", json={**payload, "idempotency_key": "unfunded"})
        assert exhausted.status_code == 429
        assert exhausted.json()["detail"]["category"] == "generation_budget"
        assert restored.get(f"{path}/messages").json() == messages
