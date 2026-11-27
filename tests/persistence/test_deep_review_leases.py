"""SQLite Deep Review lease worker contracts: claims, heartbeats, fencing.

These are the deterministic store-level fault contracts behind restart
recovery: an atomic claim refuses a live lease, recovers an expired one
within bounded attempts, heartbeats only for the current owner, and a
superseded claimant can never commit a duplicate or stale result. DSQL OCC
coverage for the same writes lives in ``test_deep_review_dsql.py``. No AWS,
no live model.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

from backend.specialists.review_orchestration import (
    DEEP_REVIEW_JOB_KEY,
    deep_review_snapshot_payload,
    parse_deep_review_job,
)
from backend.student_store import StudentStore


def _snapshot(*, strengths: list[str]) -> dict[str, object]:
    """Return one durable Deep Review snapshot for store-level completion."""
    return deep_review_snapshot_payload(
        conversation_revision=0,
        created_at="2026-11-25T00:00:00+00:00",
        synthesis="Frozen problem-identification Deep Review.",
        summary="Frozen problem-identification Deep Review.",
        strengths=list(strengths),
        areas_to_develop=["Frozen PI area"],
        facione_scores={"analysis": 2},
        working_conclusion="Working concept.",
        readiness_candidate=False,
        readiness_evidence=[],
        missing_requirements=[],
        model_id="global.anthropic.claude-sonnet-4-6",
        reviewed_stage_id="problem_identification",
    )


def _store(tmp_path) -> tuple[StudentStore, str]:
    """Return one store plus an unlocked eligible notebook id."""
    store = StudentStore(tmp_path / "dr-leases.sqlite3")
    thread_id = store.create_thread(model_id="mock", support_mode="critical-thinking")
    return store, thread_id


def _job(store: StudentStore, thread_id: str) -> dict[str, object] | None:
    """Return the parsed durable job envelope when present."""
    metadata = dict((store.get_thread(thread_id) or {}).get("metadata") or {})
    return parse_deep_review_job(metadata.get(DEEP_REVIEW_JOB_KEY))


def _expire_lease(store: StudentStore, thread_id: str, review_id: str) -> None:
    """Backdate the persisted lease so the claim has lapsed."""
    job = _job(store, thread_id)
    assert job is not None and job.get("review_id") == review_id
    job["lease_expires_at"] = (
        datetime.now(timezone.utc) - timedelta(seconds=1)
    ).isoformat()
    store.update_thread(thread_id, metadata={DEEP_REVIEW_JOB_KEY: job})


def test_live_lease_refuses_a_second_claimant(tmp_path) -> None:
    """Two workers cannot both own one queued job: the claim is atomic."""
    store, thread_id = _store(tmp_path)
    store.start_or_get_deep_review_job(
        thread_id,
        review_id="lease-review",
        reviewed_revision=0,
        stage_at_start="problem_identification",
        source_ids=[],
        message_ids=[],
    )
    assert (
        store.mark_deep_review_job_running(
            thread_id,
            "lease-review",
            lease_owner="worker-a",
            lease_seconds=240,
            max_attempts=2,
        )
        is True
    )
    assert (
        store.mark_deep_review_job_running(
            thread_id,
            "lease-review",
            lease_owner="worker-b",
            lease_seconds=240,
            max_attempts=2,
        )
        is False
    )
    job = _job(store, thread_id)
    assert job is not None
    assert job.get("lease_owner") == "worker-a"
    assert int(job.get("attempts") or 0) == 1


def test_expired_lease_is_reclaimed_and_increments_attempts(tmp_path) -> None:
    """A crashed claim is safely re-claimed; the attempt is accounted."""
    store, thread_id = _store(tmp_path)
    store.start_or_get_deep_review_job(
        thread_id,
        review_id="lease-review",
        reviewed_revision=0,
        stage_at_start="problem_identification",
        source_ids=[],
        message_ids=[],
    )
    assert (
        store.mark_deep_review_job_running(
            thread_id,
            "lease-review",
            lease_owner="worker-a",
            lease_seconds=240,
            max_attempts=2,
        )
        is True
    )
    _expire_lease(store, thread_id, "lease-review")
    assert (
        store.mark_deep_review_job_running(
            thread_id,
            "lease-review",
            lease_owner="worker-b",
            lease_seconds=240,
            max_attempts=2,
        )
        is True
    )
    job = _job(store, thread_id)
    assert job is not None
    assert job.get("lease_owner") == "worker-b"
    assert int(job.get("attempts") or 0) == 2


def test_expired_invoked_review_is_not_reclaimed(tmp_path: Path) -> None:
    """A replacement worker cannot repeat an invocation with an unknown outcome."""
    store, thread_id = _store(tmp_path)
    review_id = "invoked-review"
    store.start_or_get_deep_review_job(
        thread_id,
        review_id=review_id,
        reviewed_revision=0,
        stage_at_start="problem_identification",
        source_ids=[],
        message_ids=[],
    )
    assert store.mark_deep_review_job_running(
        thread_id, review_id, lease_owner="worker-a", lease_seconds=240, max_attempts=2
    )
    assert store.mark_deep_review_job_invoked(
        thread_id, review_id, lease_owner="worker-a", lease_seconds=240
    )
    _expire_lease(store, thread_id, review_id)

    restarted_store = StudentStore(tmp_path / "dr-leases.sqlite3")
    assert not restarted_store.mark_deep_review_job_running(
        thread_id, review_id, lease_owner="worker-b", lease_seconds=240, max_attempts=2
    )
    assert restarted_store.mark_deep_review_job_ambiguous(thread_id, review_id)
    job = _job(restarted_store, thread_id)
    assert job is not None
    assert job["status"] == "ambiguous"
    assert job["attempts"] == 1


def test_only_first_invocation_is_authorized_for_a_claim(tmp_path: Path) -> None:
    """The current worker cannot acquire the same invocation permission twice."""
    store, thread_id = _store(tmp_path)
    review_id = "same-worker-review"
    store.start_or_get_deep_review_job(
        thread_id,
        review_id=review_id,
        reviewed_revision=0,
        stage_at_start="problem_identification",
        source_ids=[],
        message_ids=[],
    )
    lease = {"lease_owner": "worker", "lease_seconds": 240}
    assert store.mark_deep_review_job_running(thread_id, review_id, **lease)
    assert store.mark_deep_review_job_invoked(thread_id, review_id, **lease)
    assert not store.mark_deep_review_job_invoked(thread_id, review_id, **lease)


def test_reconciled_ambiguous_review_ignores_late_worker_writes(tmp_path: Path) -> None:
    """Once recovery marks the outcome unknown, a detached worker cannot publish."""
    store, thread_id = _store(tmp_path)
    review_id = "late-review"
    store.start_or_get_deep_review_job(
        thread_id,
        review_id=review_id,
        reviewed_revision=0,
        stage_at_start="problem_identification",
        source_ids=[],
        message_ids=[],
    )
    _claim(store, thread_id, review_id)
    assert store.mark_deep_review_job_invoked(
        thread_id, review_id, lease_owner="worker-a", lease_seconds=240
    )
    _expire_lease(store, thread_id, review_id)
    assert store.mark_deep_review_job_ambiguous(thread_id, review_id)

    store.fail_deep_review_job(
        thread_id, review_id=review_id, error_code="review_timeout", lease_owner="worker-a"
    )
    store.complete_deep_review_job(
        thread_id, review_id=review_id, snapshot=_snapshot(strengths=["Late review"]),
        lease_owner="worker-a",
    )

    job = _job(store, thread_id)
    assert job is not None and job["status"] == "ambiguous"
    assert "deep_review_snapshot" not in (store.get_thread(thread_id) or {})["metadata"]


def test_claim_refuses_when_attempts_are_exhausted(tmp_path) -> None:
    """Bounded recovery: no claimant may run past the attempt budget."""
    store, thread_id = _store(tmp_path)
    store.start_or_get_deep_review_job(
        thread_id,
        review_id="lease-review",
        reviewed_revision=0,
        stage_at_start="problem_identification",
        source_ids=[],
        message_ids=[],
    )
    assert (
        store.mark_deep_review_job_running(
            thread_id,
            "lease-review",
            lease_owner="worker-a",
            lease_seconds=240,
            max_attempts=2,
        )
        is True
    )
    _expire_lease(store, thread_id, "lease-review")
    assert (
        store.mark_deep_review_job_running(
            thread_id,
            "lease-review",
            lease_owner="worker-b",
            lease_seconds=240,
            max_attempts=2,
        )
        is True
    )
    _expire_lease(store, thread_id, "lease-review")
    assert (
        store.mark_deep_review_job_running(
            thread_id,
            "lease-review",
            lease_owner="worker-c",
            lease_seconds=240,
            max_attempts=2,
        )
        is False
    )
    job = _job(store, thread_id)
    assert job is not None
    assert int(job.get("attempts") or 0) == 2


def test_heartbeat_extends_only_the_current_owner_s_lease(tmp_path) -> None:
    """The owner's lease is renewed; a superseded worker cannot renew."""
    store, thread_id = _store(tmp_path)
    store.start_or_get_deep_review_job(
        thread_id,
        review_id="lease-review",
        reviewed_revision=0,
        stage_at_start="problem_identification",
        source_ids=[],
        message_ids=[],
    )
    assert (
        store.mark_deep_review_job_running(
            thread_id,
            "lease-review",
            lease_owner="worker-a",
            lease_seconds=240,
            max_attempts=2,
        )
        is True
    )
    assert (
        store.heartbeat_deep_review_job(
            thread_id, "lease-review", lease_owner="worker-b", lease_seconds=240
        )
        is False
    )
    before = _job(store, thread_id)
    assert before is not None
    expiry_before = before.get("lease_expires_at")
    assert (
        store.heartbeat_deep_review_job(
            thread_id, "lease-review", lease_owner="worker-a", lease_seconds=240
        )
        is True
    )
    after = _job(store, thread_id)
    assert after is not None
    assert after.get("lease_expires_at") is not None
    assert after.get("lease_expires_at") != expiry_before


def test_superseded_claimant_cannot_commit_and_new_owner_is_authoritative(
    tmp_path,
) -> None:
    """A lapsed claimant's terminal writes are fenced; the live owner commits."""
    store, thread_id = _store(tmp_path)
    store.start_or_get_deep_review_job(
        thread_id,
        review_id="lease-review",
        reviewed_revision=0,
        stage_at_start="problem_identification",
        source_ids=[],
        message_ids=[],
    )
    assert (
        store.mark_deep_review_job_running(
            thread_id,
            "lease-review",
            lease_owner="worker-a",
            lease_seconds=240,
            max_attempts=2,
        )
        is True
    )
    _expire_lease(store, thread_id, "lease-review")
    assert (
        store.mark_deep_review_job_running(
            thread_id,
            "lease-review",
            lease_owner="worker-b",
            lease_seconds=240,
            max_attempts=2,
        )
        is True
    )

    # The live owner completes first: its snapshot is the authoritative one.
    store.complete_deep_review_job(
        thread_id,
        review_id="lease-review",
        snapshot=_snapshot(strengths=["Owner B strength"]),
        lease_owner="worker-b",
    )

    # The superseded claimant can neither commit a duplicate result nor
    # overwrite the winner's terminal state with a failure.
    store.complete_deep_review_job(
        thread_id,
        review_id="lease-review",
        snapshot=_snapshot(strengths=["Superseded A strength"]),
        lease_owner="worker-a",
    )
    store.fail_deep_review_job(
        thread_id,
        review_id="lease-review",
        error_code="review_timeout",
        lease_owner="worker-a",
    )
    job = _job(store, thread_id)
    assert job is not None
    assert job.get("status") == "completed"
    metadata = dict((store.get_thread(thread_id) or {}).get("metadata") or {})
    snapshot = metadata.get("deep_review_snapshot")
    assert isinstance(snapshot, dict)
    assert snapshot.get("strengths") == ["Owner B strength"]
    assert "Superseded A strength" not in str(snapshot.get("strengths"))
    # Completion stays idempotent for the owner, too.
    store.complete_deep_review_job(
        thread_id,
        review_id="lease-review",
        snapshot=_snapshot(strengths=["Duplicate B strength"]),
        lease_owner="worker-b",
    )
    metadata = dict((store.get_thread(thread_id) or {}).get("metadata") or {})
    snapshot = metadata.get("deep_review_snapshot")
    assert isinstance(snapshot, dict)
    assert snapshot.get("strengths") == ["Owner B strength"]


def _claim(
    store: StudentStore,
    thread_id: str,
    review_id: str,
    lease_owner: str = "worker-a",
) -> None:
    """Claim one job for *lease_owner* with a live lease."""
    assert (
        store.mark_deep_review_job_running(
            thread_id,
            review_id,
            lease_owner=lease_owner,
            lease_seconds=240,
            max_attempts=3,
        )
        is True
    )


def test_cancelling_a_queued_job_is_terminal_without_a_worker(tmp_path) -> None:
    """A queued job cannot have invoked anything, so cancellation is final."""
    store, thread_id = _store(tmp_path)
    store.start_or_get_deep_review_job(
        thread_id,
        review_id="cancel-queued",
        reviewed_revision=0,
        stage_at_start="problem_identification",
        source_ids=[],
        message_ids=[],
    )
    assert store.request_deep_review_cancellation(thread_id, "cancel-queued") is True
    job = _job(store, thread_id)
    assert job is not None
    assert job.get("status") == "cancelled"
    assert job.get("lease_owner") is None
    assert job.get("lease_expires_at") is None


def test_cancelling_a_running_job_records_the_request_and_keeps_the_lease(
    tmp_path,
) -> None:
    """A claimed job first shows cancel-requested; its live worker decides."""
    store, thread_id = _store(tmp_path)
    store.start_or_get_deep_review_job(
        thread_id,
        review_id="cancel-running",
        reviewed_revision=0,
        stage_at_start="problem_identification",
        source_ids=[],
        message_ids=[],
    )
    _claim(store, thread_id, "cancel-running", lease_owner="worker-a")
    assert (
        store.request_deep_review_cancellation(thread_id, "cancel-running") is True
    )
    job = _job(store, thread_id)
    assert job is not None
    assert job.get("status") == "cancel_requested"
    # The live claim is untouched: only the worker (or lease expiry) may
    # move a claimed job to a terminal state.
    assert job.get("lease_owner") == "worker-a"
    assert job.get("lease_expires_at") is not None
    # Idempotent: a second request does not regress or fail.
    assert (
        store.request_deep_review_cancellation(thread_id, "cancel-running") is True
    )
    assert (_job(store, thread_id) or {}).get("status") == "cancel_requested"


def test_cancel_request_refuses_terminal_jobs(tmp_path) -> None:
    """Completed, failed, cancelled and ambiguous jobs are already terminal."""
    store, thread_id = _store(tmp_path)
    store.start_or_get_deep_review_job(
        thread_id,
        review_id="cancel-terminal",
        reviewed_revision=0,
        stage_at_start="problem_identification",
        source_ids=[],
        message_ids=[],
    )
    store.complete_deep_review_job(
        thread_id,
        review_id="cancel-terminal",
        snapshot=_snapshot(strengths=["Done"]),
    )
    assert (
        store.request_deep_review_cancellation(thread_id, "cancel-terminal") is False
    )
    assert (_job(store, thread_id) or {}).get("status") == "completed"


def test_worker_acknowledges_a_cancel_request_before_invocation(tmp_path) -> None:
    """The claimed worker's pre-invocation boundary cancels without a result."""
    store, thread_id = _store(tmp_path)
    store.start_or_get_deep_review_job(
        thread_id,
        review_id="cancel-ack",
        reviewed_revision=0,
        stage_at_start="problem_identification",
        source_ids=[],
        message_ids=[],
    )
    _claim(store, thread_id, "cancel-ack", lease_owner="worker-a")
    assert store.request_deep_review_cancellation(thread_id, "cancel-ack") is True
    assert (
        store.cancel_deep_review_job(
            thread_id, "cancel-ack", lease_owner="worker-a"
        )
        is True
    )
    job = _job(store, thread_id)
    assert job is not None
    assert job.get("status") == "cancelled"
    assert job.get("error_code") == "review_cancelled"
    assert job.get("lease_owner") is None
    # A worker that never held the request cannot acknowledge it.
    store.start_or_get_deep_review_job(
        thread_id,
        review_id="cancel-ack-2",
        reviewed_revision=0,
        stage_at_start="problem_identification",
        source_ids=[],
        message_ids=[],
    )
    _claim(store, thread_id, "cancel-ack-2", lease_owner="worker-a")
    assert store.request_deep_review_cancellation(thread_id, "cancel-ack-2") is True
    assert (
        store.cancel_deep_review_job(
            thread_id, "cancel-ack-2", lease_owner="worker-b"
        )
        is False
    )
    assert (_job(store, thread_id) or {}).get("status") == "cancel_requested"


def test_cancellation_survives_a_lease_owner_change(tmp_path) -> None:
    """A cancel request is not silently dropped when the claim is re-claimed."""
    store, thread_id = _store(tmp_path)
    store.start_or_get_deep_review_job(
        thread_id,
        review_id="cancel-reclaim",
        reviewed_revision=0,
        stage_at_start="problem_identification",
        source_ids=[],
        message_ids=[],
    )
    _claim(store, thread_id, "cancel-reclaim", lease_owner="worker-a")
    assert store.request_deep_review_cancellation(thread_id, "cancel-reclaim") is True
    _expire_lease(store, thread_id, "cancel-reclaim")
    # A recovery claim of a cancel-requested job is refused: the student has
    # already asked for cancellation, so no new worker may start an invocation.
    assert (
        store.mark_deep_review_job_running(
            thread_id,
            "cancel-reclaim",
            lease_owner="worker-b",
            lease_seconds=240,
            max_attempts=3,
        )
        is False
    )
    assert (_job(store, thread_id) or {}).get("status") == "cancel_requested"
