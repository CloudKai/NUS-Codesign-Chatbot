"""Real SQLite contention with outcomes asserted at the public student HTTP API."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
import json
from pathlib import Path
import sqlite3
import threading
from typing import Any

from fastapi.testclient import TestClient
from pytest import MonkeyPatch

from backend.api import create_app
from backend.domain import CoachRequest, ProviderAssessmentResult
from backend.mock_provider import DeterministicCoachProvider
from backend.settings import settings
from backend.student_store import StudentStore


def test_busy_waiter_does_not_strand_the_next_answer(
    tmp_path: Path, monkeypatch: MonkeyPatch,
) -> None:
    """A failed uninvoked wait cannot block survivors or consume their allowance.

    The database-boundary fixture gates A's first queued poll while another real
    SQLite connection holds the writer lock through its native two-second timeout.
    SQL inspection synchronizes the fault only; all behavior is verified by HTTP.
    No admission methods are replaced or called by this test.
    """
    import backend.owner_context as owners

    entered, release = threading.Event(), threading.Event()
    poll, locked, busy, unlocked = (threading.Event() for _ in range(4))
    ledger = tmp_path / "generation.sqlite3"
    policy = tmp_path / "policy.json"
    policy.write_text(json.dumps({"ledger_path": str(ledger),
        "monthly_micro_sgd": 400, "headroom_micro_sgd": 100,
        "call_reserve_micro_sgd": 100, "max_running": 1, "max_queued": 3,
        "max_wait_seconds": 8, "lease_seconds": 600,
        "ceiling_evidence": "Synthetic offline fixture, not real pricing"}))
    monkeypatch.setattr(settings, "generation_admission_policy", str(policy))

    class HeldProvider(DeterministicCoachProvider):
        """Keep the first invocation open; retain conservative synthetic charges."""

        usage_provider = "unknown"

        def assess(self, request: CoachRequest) -> ProviderAssessmentResult:
            """Release the deterministic first invocation on an explicit signal."""
            if request.student_message == "Hold first invocation":
                entered.set()
                assert release.wait(12)
            return super().assess(request)

    monkeypatch.setattr(owners, "configured_coach_provider", HeldProvider)
    store = StudentStore(tmp_path / "students.sqlite3")
    threads = [store.create_thread(model_id="mock", support_mode="critical-thinking") for _ in range(5)]
    connect = sqlite3.connect
    selected: list[int] = []

    class ContendedConnection(sqlite3.Connection):
        """Coordinate one native SQLITE_BUSY at the disposable database boundary."""

        def execute(self, sql: str, parameters: Any = ()) -> sqlite3.Cursor:
            """Gate the selected queued caller's next write, leaving SQLite real."""
            if selected == [threading.get_ident()] and not poll.is_set():
                poll.set()
                assert locked.wait(3)
                try:
                    return super().execute(sql, parameters)
                except sqlite3.OperationalError as error:
                    if error.sqlite_errorcode == sqlite3.SQLITE_BUSY:
                        busy.set()
                        assert unlocked.wait(3)
                    raise
            result = super().execute(sql, parameters)
            if sql.startswith("INSERT INTO generation_calls") and parameters[2] == "queued" and not selected:
                selected.append(threading.get_ident())
            return result

    def fault_connect(database: Any, *args: Any, **kwargs: Any) -> sqlite3.Connection:
        """Wrap only connections to the dedicated temporary generation ledger."""
        if Path(database) == ledger:
            kwargs["factory"] = ContendedConnection
        return connect(database, *args, **kwargs)

    def hold_writer() -> None:
        """Hold a real exclusive transaction until SQLite reports its timeout."""
        assert poll.wait(5)
        with closing(connect(ledger, timeout=2)) as db:
            db.execute("BEGIN EXCLUSIVE")
            locked.set()
            try:
                assert busy.wait(5)
            finally:
                db.rollback()
                unlocked.set()

    def body(index: int, key: str) -> dict[str, str]:
        """Build independent notebook requests with stable recovery identities."""
        return {"thread_id": threads[index], "student_message": "Hold first invocation" if index == 0 else "Improve accessibility",
            "current_stage": "problem_identification", "response_detail": "short", "idempotency_key": key}

    with TestClient(create_app(store)) as client, ThreadPoolExecutor(max_workers=4) as pool:
        monkeypatch.setattr(sqlite3, "connect", fault_connect)
        holder = pool.submit(hold_writer)
        active = pool.submit(client.post, "/api/v1/coach/turn", json=body(0, "active"))
        try:
            assert entered.wait(3)
            failed = client.post("/api/v1/coach/turn", json=body(1, "busy"))
            assert busy.is_set(), "Fixture must observe a real native SQLITE_BUSY"
            assert failed.status_code == 429
            assert failed.json()["detail"]["category"] == "generation_unavailable"
            holder.result(timeout=2)
            following = pool.submit(client.post, "/api/v1/coach/turn", json=body(2, "survivor"))
            release.set()
            assert active.result(timeout=2).status_code == 200
            answer = following.result(timeout=2)
            assert answer.status_code == 200
            recovery = client.get(f"/api/v1/threads/{threads[2]}/coach-turn", params={"idempotency_key": "survivor"})
            assert recovery.json() == answer.json()
            assert client.post("/api/v1/coach/turn", json=body(2, "survivor")).json() == answer.json()
            assert client.get(f"/api/v1/threads/{threads[1]}/coach-turn", params={"idempotency_key": "busy"}).json() is None
            assert client.post("/api/v1/coach/turn", json=body(3, "last-funded")).status_code == 200
            exhausted = client.post("/api/v1/coach/turn", json=body(4, "headroom"))
            assert exhausted.status_code == 429
            assert exhausted.json()["detail"]["category"] == "generation_budget"
        finally:
            release.set()
