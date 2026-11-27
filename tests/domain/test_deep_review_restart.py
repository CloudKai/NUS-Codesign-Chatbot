"""Deep Review jobs survive a real restart through the persisted lease worker.

Restart is simulated the way production fails: the process-local executor and
its submitted-set are wiped (``reset_deep_review_jobs_for_tests``) while the
durable SQLite store keeps the persisted job envelope. No AWS, no live model.
"""

from __future__ import annotations

import time
from typing import Any

import pytest

from backend.coaching import deep_review_jobs
from backend.settings import settings
from backend.specialists.review_orchestration import (
    COUNTER_SETTINGS_KEY,
    DEEP_REVIEW_JOB_KEY,
)
from backend.student_store import StudentStore
from fake_agentcore_runtime import FakeAgentCoreRuntime
from test_deep_review_execution import (
    _counter,
    _deep_payload,
    _job_blob,
    _service,
    _snapshot,
    _unlock,
)


@pytest.fixture(autouse=True)
def _worker_pool(monkeypatch: pytest.MonkeyPatch) -> None:
    """Give recovery workers capacity and isolate the process-local pool."""
    monkeypatch.setattr(settings, "deep_review_max_concurrent", 8)
    deep_review_jobs.reset_deep_review_jobs_for_tests()
    yield
    deep_review_jobs.reset_deep_review_jobs_for_tests()


def _wait_for_job(service: Any, thread_id: str, review_id: str) -> Any:
    """Poll the public GET seam until the job leaves queued/running."""
    deadline = time.monotonic() + 10.0
    view = service.get_deep_review_job(thread_id)
    while time.monotonic() < deadline:
        view = service.get_deep_review_job(thread_id)
        if view is None or str(view.status.value) not in {"queued", "running"}:
            return view
        time.sleep(0.05)
    return view


def test_queued_deep_review_survives_restart_and_completes(
    tmp_path, monkeypatch
) -> None:
    """A crash before invocation leaves recoverable queued work for the next process."""
    store = StudentStore(tmp_path / "dr-restart-queued.sqlite3")
    thread_id = store.create_thread(model_id="mock", support_mode="critical-thinking")
    _unlock(store, thread_id)
    real_submit = deep_review_jobs.submit_deep_review_job
    crashed: list[str] = []

    def crash_before_invocation(service, submit_thread_id: str, review_id: str):
        """First process dies after the durable enqueue, before any worker runs."""
        if not crashed:
            crashed.append(review_id)
            return True
        return real_submit(service, submit_thread_id, review_id)

    monkeypatch.setattr(
        deep_review_jobs, "submit_deep_review_job", crash_before_invocation
    )
    first = _service(store, FakeAgentCoreRuntime())
    job = first.enqueue_deep_review(thread_id, idempotency_key="restart-one")
    assert job.status.value == "queued"
    assert crashed == [job.review_id]
    assert _snapshot(store, thread_id) is None

    # Restart: fresh process, same durable store, working submitter.
    deep_review_jobs.reset_deep_review_jobs_for_tests()
    restarted = _service(
        store,
        FakeAgentCoreRuntime(
            deep_payload=_deep_payload(synthesis="Recovered after restart.")
        ),
    )
    view = _wait_for_job(restarted, thread_id, job.review_id)
    assert view is not None
    assert view.status.value == "completed", view
    snapshot = _snapshot(store, thread_id)
    assert snapshot is not None
    assert "Recovered after restart." in str(snapshot.get("synthesis") or "")
    assert _counter(store, thread_id) == 0
    persisted = _job_blob(store, thread_id)
    assert persisted is not None and persisted["review_id"] == job.review_id


def _expired_running_job(store: StudentStore, thread_id: str, review_id: str,
                         attempts: int) -> None:
    """Seed one durable running job whose claim lease has already expired."""
    from datetime import datetime, timedelta, timezone

    stale = (datetime.now(timezone.utc) - timedelta(minutes=10)).isoformat()
    store.update_thread(thread_id, metadata={
        COUNTER_SETTINGS_KEY: 3,
        DEEP_REVIEW_JOB_KEY: {
            "review_id": review_id,
            "status": "running",
            "reviewed_revision": 0,
            "stage_at_start": "reflection",
            "source_ids": [],
            "message_ids": [],
            "started_at": stale,
            "updated_at": stale,
            "error_code": None,
            "attempts": attempts,
        },
    })


def test_expired_running_lease_is_reclaimed_after_restart(tmp_path) -> None:
    """A crash after claim, before completion, is recovered within bounded attempts."""
    store = StudentStore(tmp_path / "dr-restart-lease.sqlite3")
    thread_id = store.create_thread(model_id="mock", support_mode="critical-thinking")
    _unlock(store, thread_id)
    _expired_running_job(store, thread_id, "crash-after-claim", attempts=1)
    deep_review_jobs.reset_deep_review_jobs_for_tests()
    restarted = _service(
        store,
        FakeAgentCoreRuntime(
            deep_payload=_deep_payload(
                synthesis="Recovered claim.", current_stage="reflection"
            )
        ),
    )
    view = _wait_for_job(restarted, thread_id, "crash-after-claim")
    assert view is not None
    assert view.status.value == "completed", view
    snapshot = _snapshot(store, thread_id)
    assert snapshot is not None
    assert "Recovered claim." in str(snapshot.get("synthesis") or "")
    assert _counter(store, thread_id) == 0
    persisted = _job_blob(store, thread_id)
    assert persisted is not None
    assert int(persisted.get("attempts") or 0) == 2
