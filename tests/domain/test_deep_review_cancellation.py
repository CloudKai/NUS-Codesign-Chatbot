"""Deep Review cancellation, ambiguity and clean-shutdown execution contracts.

Ticket 36: explicit cancel-requested/cancelled paths, honest ambiguous
reconciliation after a crash around the billable invocation, and a clean
worker-pool shutdown that never loses durable work. Deterministic fakes only;
no AWS, no paid calls.
"""

from __future__ import annotations

import time
from datetime import datetime, timedelta, timezone
from typing import Any

import pytest

from backend.coaching import deep_review_jobs
from backend.settings import settings
from backend.specialists.review_orchestration import (
    COUNTER_SETTINGS_KEY,
    DEEP_REVIEW_ERROR_CANCELLED,
    DEEP_REVIEW_ERROR_OUTCOME_UNKNOWN,
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


def _captured_submit() -> tuple[list[tuple[Any, str, str]], Any]:
    """Return a submit spy that records dispatches without running workers."""
    dispatched: list[tuple[Any, str, str]] = []

    def capture(service: Any, thread_id: str, review_id: str) -> bool:
        dispatched.append((service, thread_id, review_id))
        return True

    return dispatched, capture


def _cancel_during_claim(store: StudentStore, thread_id: str, review_id: str) -> None:
    """Wrap the store claim so a cancel request lands right after it.

    This is the deterministic stand-in for a student pressing cancel between
    the worker's atomic claim and its pre-invocation boundary.
    """
    real_claim = store.mark_deep_review_job_running

    def claim_then_cancel(*args: Any, **kwargs: Any) -> bool:
        claimed = real_claim(*args, **kwargs)
        if claimed:
            store.request_deep_review_cancellation(thread_id, review_id)
        return claimed

    store.mark_deep_review_job_running = claim_then_cancel  # type: ignore[method-assign]


def test_cancelling_a_queued_job_never_invokes_and_stays_cancelled(
    tmp_path,
) -> None:
    """Student cancellation of unclaimed work is final and bills nothing."""
    store = StudentStore(tmp_path / "dr-cancel-queued.sqlite3")
    thread_id = store.create_thread(model_id="mock", support_mode="critical-thinking")
    _unlock(store, thread_id)
    _, capture = _captured_submit()

    import backend.coaching.deep_review_jobs as jobs_module

    real_submit = jobs_module.submit_deep_review_job
    jobs_module.submit_deep_review_job = capture  # type: ignore[assignment]
    try:
        service = _service(store, FakeAgentCoreRuntime())
        job = service.enqueue_deep_review(thread_id, idempotency_key="cancel-one")
        assert job.status.value == "queued"
    finally:
        jobs_module.submit_deep_review_job = real_submit  # type: ignore[assignment]

    view = service.cancel_deep_review(thread_id)
    assert view is not None
    assert view.status.value == "cancelled"
    assert view.error_code == DEEP_REVIEW_ERROR_CANCELLED

    # Recovery never resurrects cancelled work: no invocation, no snapshot.
    restarted = _service(
        store, FakeAgentCoreRuntime(deep_payload=_deep_payload(synthesis="Too late."))
    )
    for _ in range(5):
        view = restarted.get_deep_review_job(thread_id)
        time.sleep(0.05)
    assert view is not None
    assert view.status.value == "cancelled"
    assert _snapshot(store, thread_id) is None
    assert _counter(store, thread_id) == 3


def test_worker_with_a_live_claim_cancels_before_the_invocation(tmp_path) -> None:
    """The claimed worker's pre-invocation boundary honors the cancel request."""
    store = StudentStore(tmp_path / "dr-cancel-claim.sqlite3")
    thread_id = store.create_thread(model_id="mock", support_mode="critical-thinking")
    _unlock(store, thread_id)
    runtime = FakeAgentCoreRuntime(deep_payload=_deep_payload(synthesis="Raced."))
    dispatched, capture = _captured_submit()

    import backend.coaching.deep_review_jobs as jobs_module

    real_submit = jobs_module.submit_deep_review_job
    jobs_module.submit_deep_review_job = capture  # type: ignore[assignment]
    try:
        service = _service(store, runtime)
        job = service.enqueue_deep_review(thread_id, idempotency_key="cancel-two")
    finally:
        jobs_module.submit_deep_review_job = real_submit  # type: ignore[assignment]

    # The worker claims, and only then the student cancels.
    _cancel_during_claim(store, thread_id, job.review_id)
    dispatched[0][0].execute_deep_review_job(thread_id, job.review_id)

    blob = _job_blob(store, thread_id)
    assert blob is not None
    assert blob["status"] == "cancelled"
    assert blob["error_code"] == DEEP_REVIEW_ERROR_CANCELLED
    # The pre-invocation boundary honored the request: no provider call.
    assert runtime.calls == []
    assert _snapshot(store, thread_id) is None


def test_cancel_returns_none_without_a_job(tmp_path) -> None:
    """Cancelling a notebook that never queued a review is a 404 seam."""
    store = StudentStore(tmp_path / "dr-cancel-none.sqlite3")
    thread_id = store.create_thread(model_id="mock", support_mode="critical-thinking")
    service = _service(store, FakeAgentCoreRuntime())
    assert service.cancel_deep_review(thread_id) is None


@pytest.mark.parametrize("cancellation_requested", [False, True])
def test_crash_after_invocation_surfaces_ambiguity_not_a_rerun(
    tmp_path, cancellation_requested: bool
) -> None:
    """A lost worker after the billable invoke is ambiguous, never re-run."""
    store = StudentStore(tmp_path / "dr-ambiguous.sqlite3")
    thread_id = store.create_thread(model_id="mock", support_mode="critical-thinking")
    _unlock(store, thread_id)
    _, capture = _captured_submit()

    import backend.coaching.deep_review_jobs as jobs_module

    real_submit = jobs_module.submit_deep_review_job
    jobs_module.submit_deep_review_job = capture  # type: ignore[assignment]
    try:
        service = _service(store, FakeAgentCoreRuntime())
        job = service.enqueue_deep_review(thread_id, idempotency_key="amb-one")
    finally:
        jobs_module.submit_deep_review_job = real_submit  # type: ignore[assignment]

    # The worker claims and durably marks the invocation started, then the
    # process dies before any result commit: lease lapsed, invoked_at set.
    assert (
        store.mark_deep_review_job_running(
            thread_id,
            job.review_id,
            lease_owner="crashed-worker",
            lease_seconds=60,
            max_attempts=3,
        )
        is True
    )
    assert (
        store.mark_deep_review_job_invoked(
            thread_id, job.review_id, lease_owner="crashed-worker", lease_seconds=60
        )
        is True
    )
    if cancellation_requested:
        assert store.request_deep_review_cancellation(thread_id, job.review_id)
    blob = _job_blob(store, thread_id)
    assert blob is not None and blob["invoked_at"] is not None
    blob["lease_expires_at"] = (
        datetime.now(timezone.utc) - timedelta(seconds=1)
    ).isoformat()
    store.update_thread(thread_id, metadata={DEEP_REVIEW_JOB_KEY: blob})

    recovery_submissions: list[str] = []

    def no_resubmit(sub_service: Any, sub_thread: str, review_id: str) -> bool:
        recovery_submissions.append(review_id)
        return True

    import backend.coaching.deep_review_jobs as jobs_module

    jobs_module.submit_deep_review_job = no_resubmit  # type: ignore[assignment]
    try:
        restarted = _service(store, FakeAgentCoreRuntime())
        view = restarted.get_deep_review_job(thread_id)
    finally:
        jobs_module.submit_deep_review_job = real_submit  # type: ignore[assignment]

    # Honest reconciliation: ambiguous outcome, explicit code, no silent rerun.
    assert view is not None
    assert view.status.value == "ambiguous"
    assert view.error_code == DEEP_REVIEW_ERROR_OUTCOME_UNKNOWN
    assert recovery_submissions == []
    assert _snapshot(store, thread_id) is None
    # Accounting is retained: the periodic counter is not reset and the next
    # read never re-queues the uncertain job.
    assert _counter(store, thread_id) == 3
    again = restarted.get_deep_review_job(thread_id)
    assert again is not None and again.status.value == "ambiguous"


def test_ambiguity_takes_precedence_over_attempt_exhaustion(tmp_path) -> None:
    """Exhausted attempts after an unknown-outcome invoke still read ambiguous."""
    store = StudentStore(tmp_path / "dr-ambiguous-attempts.sqlite3")
    thread_id = store.create_thread(model_id="mock", support_mode="critical-thinking")
    _unlock(store, thread_id)
    stale = (datetime.now(timezone.utc) - timedelta(minutes=10)).isoformat()
    store.update_thread(
        thread_id,
        metadata={
            COUNTER_SETTINGS_KEY: 2,
            DEEP_REVIEW_JOB_KEY: {
                "review_id": "amb-exhausted",
                "status": "running",
                "reviewed_revision": 0,
                "stage_at_start": "problem_identification",
                "source_ids": [],
                "message_ids": [],
                "started_at": stale,
                "updated_at": stale,
                "invoked_at": stale,
                "error_code": None,
                "attempts": 99,
            },
        },
    )
    import backend.coaching.deep_review_jobs as jobs_module

    real_submit = jobs_module.submit_deep_review_job
    jobs_module.submit_deep_review_job = (
        lambda *args, **kwargs: True
    )  # type: ignore[assignment]
    try:
        service = _service(store, FakeAgentCoreRuntime())
        view = service.get_deep_review_job(thread_id)
    finally:
        jobs_module.submit_deep_review_job = real_submit  # type: ignore[assignment]
    assert view is not None
    assert view.status.value == "ambiguous"
    assert view.error_code == DEEP_REVIEW_ERROR_OUTCOME_UNKNOWN


def test_cancel_requested_job_after_a_crash_is_cancelled_not_rerun(tmp_path) -> None:
    """A lost worker after a cancel request honors the cancellation."""
    store = StudentStore(tmp_path / "dr-cancel-crash.sqlite3")
    thread_id = store.create_thread(model_id="mock", support_mode="critical-thinking")
    _unlock(store, thread_id)
    stale = (datetime.now(timezone.utc) - timedelta(minutes=10)).isoformat()
    store.update_thread(
        thread_id,
        metadata={
            COUNTER_SETTINGS_KEY: 1,
            DEEP_REVIEW_JOB_KEY: {
                "review_id": "cancel-crash",
                "status": "cancel_requested",
                "reviewed_revision": 0,
                "stage_at_start": "problem_identification",
                "source_ids": [],
                "message_ids": [],
                "started_at": stale,
                "updated_at": stale,
                "invoked_at": None,
                "error_code": None,
                "attempts": 1,
            },
        },
    )
    import backend.coaching.deep_review_jobs as jobs_module

    real_submit = jobs_module.submit_deep_review_job
    resubmitted: list[str] = []
    jobs_module.submit_deep_review_job = (
        lambda *args, **kwargs: resubmitted.append("x") or True
    )  # type: ignore[assignment]
    try:
        service = _service(store, FakeAgentCoreRuntime())
        view = service.get_deep_review_job(thread_id)
    finally:
        jobs_module.submit_deep_review_job = real_submit  # type: ignore[assignment]
    assert view is not None
    assert view.status.value == "cancelled"
    assert view.error_code == DEEP_REVIEW_ERROR_CANCELLED
    assert resubmitted == []


def test_explicit_reenqueue_after_ambiguity_runs_a_new_job(tmp_path) -> None:
    """Reconciliation is explicit: a new enqueue starts a fresh billable job."""
    store = StudentStore(tmp_path / "dr-ambiguous-retry.sqlite3")
    thread_id = store.create_thread(model_id="mock", support_mode="critical-thinking")
    _unlock(store, thread_id)
    stale = (datetime.now(timezone.utc) - timedelta(minutes=10)).isoformat()
    store.update_thread(
        thread_id,
        metadata={
            COUNTER_SETTINGS_KEY: 3,
            DEEP_REVIEW_JOB_KEY: {
                "review_id": "amb-old",
                "status": "ambiguous",
                "reviewed_revision": 0,
                "stage_at_start": "problem_identification",
                "source_ids": [],
                "message_ids": [],
                "started_at": stale,
                "updated_at": stale,
                "invoked_at": stale,
                "error_code": DEEP_REVIEW_ERROR_OUTCOME_UNKNOWN,
                "attempts": 1,
            },
        },
    )
    service = _service(
        store,
        FakeAgentCoreRuntime(deep_payload=_deep_payload(synthesis="Explicit retry.")),
    )
    job = service.enqueue_deep_review(thread_id, idempotency_key="retry")
    assert job.review_id != "amb-old"
    deadline = time.monotonic() + 10.0
    view = service.get_deep_review_job(thread_id)
    while time.monotonic() < deadline and view is not None and view.status.value in {
        "queued",
        "running",
    }:
        time.sleep(0.05)
        view = service.get_deep_review_job(thread_id)
    assert view is not None
    assert view.status.value == "completed", view
    snapshot = _snapshot(store, thread_id)
    assert snapshot is not None
    assert "Explicit retry." in str(snapshot.get("synthesis") or "")


def test_shutdown_does_not_lose_queued_work_or_hang(tmp_path) -> None:
    """Clean shutdown drops process-local dispatch only; the envelope recovers."""
    store = StudentStore(tmp_path / "dr-shutdown.sqlite3")
    thread_id = store.create_thread(model_id="mock", support_mode="critical-thinking")
    _unlock(store, thread_id)
    _, capture = _captured_submit()

    import backend.coaching.deep_review_jobs as jobs_module

    real_submit = jobs_module.submit_deep_review_job
    jobs_module.submit_deep_review_job = capture  # type: ignore[assignment]
    try:
        service = _service(store, FakeAgentCoreRuntime())
        job = service.enqueue_deep_review(thread_id, idempotency_key="shutdown-one")
        assert job.status.value == "queued"
    finally:
        jobs_module.submit_deep_review_job = real_submit  # type: ignore[assignment]

    deep_review_jobs.shutdown_deep_review_executor()
    # A fresh pool can still be created for later jobs (no shutdown hang).
    assert deep_review_jobs.submit_deep_review_job(service, thread_id, "after-shutdown")

    restarted = _service(
        store,
        FakeAgentCoreRuntime(
            deep_payload=_deep_payload(synthesis="Recovered after shutdown.")
        ),
    )
    deadline = time.monotonic() + 10.0
    view = restarted.get_deep_review_job(thread_id)
    while time.monotonic() < deadline and view is not None and view.status.value in {
        "queued",
        "running",
    }:
        time.sleep(0.05)
        view = restarted.get_deep_review_job(thread_id)
    assert view is not None
    assert view.status.value == "completed", view
    assert _counter(store, thread_id) == 0
