"""Durable, provider-safe idempotency tests for coach submissions."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
import json
import sqlite3
import threading
import time

import pytest
from fastapi.testclient import TestClient

from backend.api import create_app
from backend.application import CoachApplicationService
from backend.domain import CoachRequest, StageDecision
from backend.learning_service import LearningProgressService
from backend.mock_provider import DeterministicCoachProvider
from backend.repositories import (
    SQLiteNotebookRepository,
    SQLitePhaseTransitionRepository,
)
from backend.persistence.dsql_student_store import DsqlStudentStore
from backend.student_store import (
    CoachIdempotencyConflictError,
    CoachRequestInProgressError,
    CoachRequestLeaseLostError,
    StudentStore,
)
from backend.workflow import CoachWorkflow


def _service(store: StudentStore, provider: DeterministicCoachProvider) -> CoachApplicationService:
    """Build the normal application path with an inspectable mock provider."""
    notebooks = SQLiteNotebookRepository(store)
    transitions = SQLitePhaseTransitionRepository(store)
    workflow = CoachWorkflow(provider, transitions)
    return CoachApplicationService(
        store,
        notebooks,
        workflow,
        LearningProgressService(store, notebooks, transitions),
    )


def _request(thread_id: str, *, key: str, message: str = "Assess this claim.") -> CoachRequest:
    """Return one minimal valid idempotent coaching request."""
    return CoachRequest(
        thread_id=thread_id,
        student_message=message,
        current_stage="problem_identification",
        response_detail="short",
        idempotency_key=key,
    )


class CountingProvider(DeterministicCoachProvider):
    """Deterministic provider that records executions without network access."""

    def __init__(self, *, delay_seconds: float = 0.0, fail_first: bool = False) -> None:
        super().__init__(StageDecision.STAY)
        self.calls = 0
        self._delay_seconds = delay_seconds
        self._fail_first = fail_first
        self._lock = threading.Lock()

    def assess(self, request: CoachRequest):  # type: ignore[override]
        """Count one provider invocation and optionally fail the first attempt."""
        with self._lock:
            self.calls += 1
            call_number = self.calls
        if self._delay_seconds:
            time.sleep(self._delay_seconds)
        if self._fail_first and call_number == 1:
            raise RuntimeError("deterministic provider failure")
        return super().assess(request)


class _SqliteDsqlProxy:
    """SQLite transaction facade used to exercise the pathless DSQL adapter."""

    def __init__(self, database) -> None:
        self.connection = sqlite3.connect(database, timeout=30)
        self.connection.row_factory = sqlite3.Row
        self.connection.execute("PRAGMA foreign_keys = ON")

    def execute(self, sql: str, params=None):
        """Execute shared StudentStore SQL inside this test transaction."""
        return self.connection.execute(sql, params or ())

    def __enter__(self):
        return self

    def __exit__(self, exc_type, _exc, _tb) -> None:
        if exc_type is None:
            self.connection.commit()
        else:
            self.connection.rollback()
        self.connection.close()


def _dsql_store_over_sqlite(database, owner: StudentStore) -> DsqlStudentStore:
    """Build one independent DSQL adapter instance over a shared test database."""
    dsql_store = object.__new__(DsqlStudentStore)
    dsql_store.identifier = owner.identifier
    dsql_store.owner_id = owner.owner_id
    dsql_store.path = None
    dsql_store._lock = threading.RLock()
    dsql_store._connection_factory = lambda: _SqliteDsqlProxy(database)
    dsql_store._endpoint = ""
    dsql_store._region = ""
    dsql_store._database = "postgres"
    dsql_store._user = "co_design_app"
    dsql_store._install_occ_wrappers()
    return dsql_store


def test_completed_key_replays_exact_turn_after_service_restart(tmp_path):
    """A completed key survives a new service instance without another provider call."""
    database = tmp_path / "idempotent-restart.sqlite3"
    store = StudentStore(database)
    thread_id = store.create_thread(model_id="mock", support_mode="critical-thinking")
    provider = CountingProvider()
    request = _request(thread_id, key="retry-after-restart-1")

    first = _service(store, provider).submit(request)
    replay = _service(StudentStore(database), provider).submit(request)

    assert replay == first
    assert provider.calls == 1
    assert [message["role"] for message in store.get_messages(thread_id)] == [
        "user",
        "assistant",
    ]


def test_completed_key_replays_full_assessment_fields(tmp_path):
    """Replay must return the durable marker turn, not a slim message reconstruction."""
    store = StudentStore(tmp_path / "idempotent-assessment-replay.sqlite3")
    thread_id = store.create_thread(model_id="mock", support_mode="critical-thinking")
    provider = CountingProvider()
    request = _request(thread_id, key="assessment-replay-key")

    first = _service(store, provider).submit(request)
    replay = _service(store, provider).submit(request)

    assert replay.assessment.confidence == first.assessment.confidence
    assert (
        replay.assessment.contribution_summary
        == first.assessment.contribution_summary
    )
    assert provider.calls == 1


def test_reused_key_with_different_payload_fails_closed(tmp_path):
    """A key cannot silently return an answer for a different student message."""
    store = StudentStore(tmp_path / "idempotent-conflict.sqlite3")
    thread_id = store.create_thread(model_id="mock", support_mode="critical-thinking")
    provider = CountingProvider()
    service = _service(store, provider)

    service.submit(_request(thread_id, key="same-key", message="First claim."))

    with pytest.raises(CoachIdempotencyConflictError):
        service.submit(_request(thread_id, key="same-key", message="Changed claim."))

    assert provider.calls == 1
    assert len(store.get_messages(thread_id)) == 2


def test_api_accepts_header_only_and_rejects_header_body_disagreement(tmp_path):
    """The HTTP retry contract supports the standard header without ambiguity."""
    store = StudentStore(tmp_path / "idempotent-api.sqlite3")
    thread_id = store.create_thread(model_id="mock", support_mode="critical-thinking")
    client = TestClient(create_app(store, auto_advance_stages=False))
    payload = {
        "thread_id": thread_id,
        "student_message": "Assess this claim.",
        "current_stage": "problem_identification",
        "response_detail": "short",
    }

    first = client.post(
        "/api/v1/coach/turn",
        json=payload,
        headers={"Idempotency-Key": "header-only-key"},
    )
    replay = client.post(
        "/api/v1/coach/turn",
        json=payload,
        headers={"Idempotency-Key": "header-only-key"},
    )
    mismatch = client.post(
        "/api/v1/coach/turn",
        json={**payload, "idempotency_key": "body-key"},
        headers={"Idempotency-Key": "different-header-key"},
    )

    assert first.status_code == 200
    assert replay.status_code == 200
    assert replay.json() == first.json()
    assert len(store.get_messages(thread_id)) == 2
    assert mismatch.status_code == 400
    assert mismatch.json()["detail"] == (
        "Idempotency-Key header does not match the request body"
    )


def test_api_maps_an_active_duplicate_to_retryable_conflict(tmp_path, monkeypatch):
    """An occupied lease is a retry signal, not an opaque server failure."""
    store = StudentStore(tmp_path / "idempotent-in-progress-api.sqlite3")
    thread_id = store.create_thread(model_id="mock", support_mode="critical-thinking")

    def in_progress(self, request, **_kwargs):
        raise CoachRequestInProgressError("Retry this request with the same key")

    monkeypatch.setattr(CoachApplicationService, "submit", in_progress)
    client = TestClient(create_app(store, auto_advance_stages=False))
    payload = {
        "thread_id": thread_id,
        "student_message": "Assess this claim.",
        "current_stage": "problem_identification",
        "response_detail": "short",
        "idempotency_key": "occupied-key",
    }

    regular = client.post("/api/v1/coach/turn", json=payload)
    streamed = client.post("/api/v1/coach/turn/stream", json=payload)

    assert regular.status_code == 409
    assert regular.json()["detail"] == "Retry this request with the same key"
    stream_events = [json.loads(line) for line in streamed.text.splitlines()]
    assert stream_events[-1] == {
        "event": "error",
        "detail": "Retry this request with the same key",
        "status": 409,
    }


def test_api_maps_payload_mismatch_to_conflict(tmp_path):
    """Reusing a key for a different body is an HTTP 409, not a silent replay."""
    store = StudentStore(tmp_path / "idempotent-api-conflict.sqlite3")
    thread_id = store.create_thread(model_id="mock", support_mode="critical-thinking")
    client = TestClient(create_app(store, auto_advance_stages=False))
    payload = {
        "thread_id": thread_id,
        "student_message": "Assess this claim.",
        "current_stage": "problem_identification",
        "response_detail": "short",
        "idempotency_key": "payload-conflict-key",
    }

    first = client.post("/api/v1/coach/turn", json=payload)
    conflict = client.post(
        "/api/v1/coach/turn",
        json={**payload, "student_message": "A different claim must not reuse the key."},
    )
    streamed = client.post(
        "/api/v1/coach/turn/stream",
        json={**payload, "student_message": "A different claim must not reuse the key."},
    )

    assert first.status_code == 200
    assert conflict.status_code == 409
    assert "different coach request" in conflict.json()["detail"]
    stream_events = [json.loads(line) for line in streamed.text.splitlines()]
    assert stream_events[-1]["event"] == "error"
    assert stream_events[-1]["status"] == 409
    assert "different coach request" in stream_events[-1]["detail"]
    assert len(store.get_messages(thread_id)) == 2


def test_concurrent_duplicate_waits_for_one_provider_execution(tmp_path):
    """Concurrent same-key submissions converge on one persisted turn."""
    store = StudentStore(tmp_path / "idempotent-concurrent.sqlite3")
    thread_id = store.create_thread(model_id="mock", support_mode="critical-thinking")
    provider = CountingProvider(delay_seconds=0.15)
    service = _service(store, provider)
    request = _request(thread_id, key="concurrent-key")
    barrier = threading.Barrier(2)

    def submit_after_barrier():
        barrier.wait()
        return service.submit(request)

    with ThreadPoolExecutor(max_workers=2) as executor:
        first_future = executor.submit(submit_after_barrier)
        second_future = executor.submit(submit_after_barrier)
        first = first_future.result(timeout=5)
        second = second_future.result(timeout=5)

    assert first == second
    assert provider.calls == 1
    assert len(store.get_messages(thread_id)) == 2


def test_five_concurrent_duplicates_converge_on_one_provider_turn(tmp_path):
    """Five same-key waiters must still share exactly one provider execution."""
    store = StudentStore(tmp_path / "idempotent-five-way.sqlite3")
    thread_id = store.create_thread(model_id="mock", support_mode="critical-thinking")
    provider = CountingProvider(delay_seconds=0.2)
    service = _service(store, provider)
    request = _request(thread_id, key="five-way-key")
    workers = 5
    barrier = threading.Barrier(workers)

    def submit_after_barrier():
        barrier.wait()
        return service.submit(request)

    with ThreadPoolExecutor(max_workers=workers) as executor:
        futures = [executor.submit(submit_after_barrier) for _ in range(workers)]
        turns = [future.result(timeout=8) for future in futures]

    assert all(turn == turns[0] for turn in turns)
    assert provider.calls == 1
    assert len(store.get_messages(thread_id)) == 2


def test_complete_is_idempotent_after_waiter_promotes_persisted_turn(tmp_path):
    """Promotion between persist and complete must not fail the lease owner.

    After the winner commits the user/assistant pair, a waiter may observe those
    rows and mark the reservation completed before the winner calls
    ``complete_coach_request``. That path remains valid restart recovery; the
    owner's complete must become a no-op instead of ``CoachRequestLeaseLostError``.
    """
    store = StudentStore(tmp_path / "idempotent-promote-race.sqlite3")
    thread_id = store.create_thread(model_id="mock", support_mode="critical-thinking")
    key = "promote-between-persist-complete"
    fingerprint = "e" * 64
    claimed = store.claim_coach_request(
        thread_id,
        idempotency_key=key,
        request_fingerprint=fingerprint,
        lease_seconds=60,
    )
    assert claimed.state == "claimed"
    assert claimed.lease_token

    store.persist_coach_turn(
        thread_id,
        expected_stage="problem_identification",
        expected_conversation_revision=0,
        user_content="Assess this claim.",
        user_metadata={"coach_idempotency_key": key},
        assistant_content="A durable assistant reply.",
        assistant_metadata={
            "assessment": {
                "recommendation": "stay",
                "contribution_summary": "Summary",
                "learning_summary": "Learning",
                "working_conclusion": "Conclusion",
                "understanding_change": "Change",
                "critical_understanding_level": "developing",
                "guidance_questions": ["What next?"],
                "citations": [],
            },
            "coach_idempotency_key": key,
            "from_stage": "problem_identification",
        },
        summary_metadata={},
        idempotency_marker_id=claimed.marker_id,
        idempotency_key=key,
        idempotency_lease_token=claimed.lease_token,
        idempotency_fingerprint=fingerprint,
    )

    promoted = store.claim_coach_request(
        thread_id,
        idempotency_key=key,
        request_fingerprint=fingerprint,
        lease_seconds=60,
    )
    assert promoted.state == "completed"
    assert isinstance(promoted.turn_payload, dict)

    store.complete_coach_request(
        thread_id,
        marker_id=claimed.marker_id,
        idempotency_key=key,
        request_fingerprint=fingerprint,
        lease_token=str(claimed.lease_token),
        turn_payload={"response_text": "Owner payload after promotion"},
    )
    replay = store.claim_coach_request(
        thread_id,
        idempotency_key=key,
        request_fingerprint=fingerprint,
        lease_seconds=60,
    )

    assert replay.state == "completed"
    assert replay.turn_payload == promoted.turn_payload
    assert len(store.get_messages(thread_id)) == 2


def test_provider_failure_releases_key_for_a_real_retry(tmp_path):
    """A failed provider call is never replayed as a false completed response."""
    store = StudentStore(tmp_path / "idempotent-provider-failure.sqlite3")
    thread_id = store.create_thread(model_id="mock", support_mode="critical-thinking")
    provider = CountingProvider(fail_first=True)
    service = _service(store, provider)
    request = _request(thread_id, key="retry-provider-failure")

    with pytest.raises(RuntimeError, match="deterministic provider failure"):
        service.submit(request)
    completed = service.submit(request)

    assert completed.response_text
    assert provider.calls == 2
    assert len(store.get_messages(thread_id)) == 2


def test_expired_lease_cannot_commit_after_another_worker_claims_it(tmp_path):
    """An old worker must not append a second turn after lease takeover."""
    store = StudentStore(tmp_path / "idempotent-lease.sqlite3")
    thread_id = store.create_thread(model_id="mock", support_mode="critical-thinking")
    key = "lease-takeover"
    fingerprint = "a" * 64
    first = store.claim_coach_request(
        thread_id,
        idempotency_key=key,
        request_fingerprint=fingerprint,
        lease_seconds=60,
    )

    assert store.path is not None
    with sqlite3.connect(store.path) as connection:
        metadata = json.loads(
            connection.execute(
                "SELECT metadata_text FROM messages WHERE id=?", (first.marker_id,)
            ).fetchone()[0]
        )
        metadata["lease_expires_at"] = "2000-01-01T00:00:00+00:00"
        connection.execute(
            "UPDATE messages SET metadata_text=? WHERE id=?",
            (json.dumps(metadata), first.marker_id),
        )

    second = store.claim_coach_request(
        thread_id,
        idempotency_key=key,
        request_fingerprint=fingerprint,
        lease_seconds=60,
    )
    assert second.state == "claimed"
    assert second.lease_token != first.lease_token

    with pytest.raises(CoachRequestLeaseLostError):
        store.persist_coach_turn(
            thread_id,
            expected_stage="problem_identification",
        expected_conversation_revision=0,
            user_content="This old worker must not persist.",
            user_metadata={},
            assistant_content="This response must not be written.",
            assistant_metadata={"assessment": {}},
            summary_metadata={},
            idempotency_marker_id=first.marker_id,
            idempotency_key=key,
            idempotency_lease_token=first.lease_token,
            idempotency_fingerprint=fingerprint,
        )

    assert store.get_messages(thread_id) == []


def test_dsql_store_wraps_idempotency_writes_in_occ_transactions(tmp_path, monkeypatch):
    """The DSQL adapter applies its retry wrapper to all marker mutations.

    A SQLite-backed connection proxy is used only to exercise the inherited
    SQL contract; it makes no AWS or Aurora DSQL connection.
    """
    database = tmp_path / "dsql-idempotency.sqlite3"
    sqlite_store = StudentStore(database)
    thread_id = sqlite_store.create_thread(
        model_id="mock", support_mode="critical-thinking"
    )

    dsql_store = _dsql_store_over_sqlite(database, sqlite_store)

    import backend.persistence.dsql_student_store as dsql_module

    original_transaction = dsql_module.run_dsql_transaction
    transaction_calls = 0

    def tracked_transaction(work, **kwargs):
        nonlocal transaction_calls
        transaction_calls += 1
        return original_transaction(work, **kwargs)

    monkeypatch.setattr(dsql_module, "run_dsql_transaction", tracked_transaction)
    claimed = dsql_store.claim_coach_request(
        thread_id,
        idempotency_key="dsql-wrapper-key",
        request_fingerprint="b" * 64,
    )
    dsql_store.complete_coach_request(
        thread_id,
        marker_id=claimed.marker_id,
        idempotency_key="dsql-wrapper-key",
        request_fingerprint="b" * 64,
        lease_token=str(claimed.lease_token),
        turn_payload={"response_text": "Stored turn"},
    )
    replay = dsql_store.claim_coach_request(
        thread_id,
        idempotency_key="dsql-wrapper-key",
        request_fingerprint="b" * 64,
    )

    assert transaction_calls == 3
    assert replay.state == "completed"
    assert replay.turn_payload == {"response_text": "Stored turn"}


def test_independent_dsql_stores_converge_on_one_provider_turn(tmp_path):
    """Process-independent DSQL adapters share one durable request reservation."""
    database = tmp_path / "dsql-concurrent-idempotency.sqlite3"
    owner = StudentStore(database)
    thread_id = owner.create_thread(
        model_id="mock", support_mode="critical-thinking"
    )
    first_store = _dsql_store_over_sqlite(database, owner)
    second_store = _dsql_store_over_sqlite(database, owner)
    provider = CountingProvider(delay_seconds=0.15)
    services = (_service(first_store, provider), _service(second_store, provider))
    request = _request(thread_id, key="dsql-concurrent-key")
    barrier = threading.Barrier(2)

    def submit(service: CoachApplicationService):
        barrier.wait()
        return service.submit(request)

    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = [executor.submit(submit, service) for service in services]
        turns = [future.result(timeout=8) for future in futures]

    restarted = _dsql_store_over_sqlite(database, owner)
    replay = _service(restarted, provider).submit(request)

    assert turns[0] == turns[1] == replay
    assert provider.calls == 1
    assert len(restarted.get_messages(thread_id)) == 2
    with pytest.raises(CoachIdempotencyConflictError):
        _service(restarted, provider).submit(
            _request(
                thread_id,
                key="dsql-concurrent-key",
                message="A changed request cannot reuse the key.",
            )
        )
    assert provider.calls == 1


def test_dsql_provider_failure_releases_key_for_retry(tmp_path):
    """A failed DSQL-backed attempt can be claimed by an independent worker."""
    database = tmp_path / "dsql-failure-idempotency.sqlite3"
    owner = StudentStore(database)
    thread_id = owner.create_thread(
        model_id="mock", support_mode="critical-thinking"
    )
    provider = CountingProvider(fail_first=True)
    request = _request(thread_id, key="dsql-provider-retry")

    with pytest.raises(RuntimeError, match="deterministic provider failure"):
        _service(_dsql_store_over_sqlite(database, owner), provider).submit(request)
    completed = _service(
        _dsql_store_over_sqlite(database, owner), provider
    ).submit(request)

    assert completed.response_text
    assert provider.calls == 2
    assert len(owner.get_messages(thread_id)) == 2


def test_dsql_expired_lease_rejects_the_stale_worker(tmp_path):
    """Lease takeover is enforced across independent DSQL adapter instances."""
    database = tmp_path / "dsql-lease-idempotency.sqlite3"
    owner = StudentStore(database)
    thread_id = owner.create_thread(
        model_id="mock", support_mode="critical-thinking"
    )
    first_store = _dsql_store_over_sqlite(database, owner)
    second_store = _dsql_store_over_sqlite(database, owner)
    fingerprint = "c" * 64
    first = first_store.claim_coach_request(
        thread_id,
        idempotency_key="dsql-lease-key",
        request_fingerprint=fingerprint,
        lease_seconds=60,
    )
    with sqlite3.connect(database) as connection:
        metadata = json.loads(
            connection.execute(
                "SELECT metadata_text FROM messages WHERE id=?", (first.marker_id,)
            ).fetchone()[0]
        )
        metadata["lease_expires_at"] = "2000-01-01T00:00:00+00:00"
        connection.execute(
            "UPDATE messages SET metadata_text=? WHERE id=?",
            (json.dumps(metadata), first.marker_id),
        )

    second = second_store.claim_coach_request(
        thread_id,
        idempotency_key="dsql-lease-key",
        request_fingerprint=fingerprint,
        lease_seconds=60,
    )
    assert second.lease_token != first.lease_token
    with pytest.raises(CoachRequestLeaseLostError):
        first_store.persist_coach_turn(
            thread_id,
            expected_stage="problem_identification",
        expected_conversation_revision=0,
            user_content="The stale worker must roll back.",
            user_metadata={},
            assistant_content="This must not be stored.",
            assistant_metadata={"assessment": {}},
            summary_metadata={},
            idempotency_marker_id=first.marker_id,
            idempotency_key="dsql-lease-key",
            idempotency_lease_token=first.lease_token,
            idempotency_fingerprint=fingerprint,
        )
    assert owner.get_messages(thread_id) == []


def test_dsql_claim_retries_the_whole_unit_after_sqlstate_40001(
    tmp_path, monkeypatch
):
    """A serialization conflict retries the complete marker claim operation."""
    database = tmp_path / "dsql-occ-idempotency.sqlite3"
    owner = StudentStore(database)
    thread_id = owner.create_thread(
        model_id="mock", support_mode="critical-thinking"
    )
    store = _dsql_store_over_sqlite(database, owner)

    class SerializationFailure(RuntimeError):
        sqlstate = "40001"

    import backend.persistence.dsql_student_store as dsql_module

    original_transaction = dsql_module.run_dsql_transaction
    attempts = 0

    def retry_with_injected_conflict(work, **_kwargs):
        def flaky_work():
            nonlocal attempts
            attempts += 1
            if attempts == 1:
                raise SerializationFailure("could not serialize access")
            return work()

        return original_transaction(flaky_work, sleep=lambda _seconds: None)

    monkeypatch.setattr(
        dsql_module, "run_dsql_transaction", retry_with_injected_conflict
    )
    claimed = store.claim_coach_request(
        thread_id,
        idempotency_key="dsql-occ-key",
        request_fingerprint="d" * 64,
    )

    assert claimed.state == "claimed"
    assert attempts == 2
    with sqlite3.connect(database) as connection:
        marker_count = connection.execute(
            "SELECT COUNT(*) FROM messages WHERE id=?", (claimed.marker_id,)
        ).fetchone()[0]
    assert marker_count == 1


def test_revise_retry_replays_when_persist_committed_before_marker_complete(tmp_path):
    """Same revise key after persist-before-complete must not supersede again.

    Application recovers a durable recorded coach turn before calling revise, so
    a retry cannot bump ``conversation_revision`` or alter the active branch.
    Uses a normal durable turn (not a live revise mutation) so the assertion
    stays valid while store revise finishes migrating to append-only.
    """
    store = StudentStore(tmp_path / "revise-persist-before-complete.sqlite3")
    thread_id = store.create_thread(model_id="mock", support_mode="critical-thinking")
    provider = CountingProvider()
    service = _service(store, provider)
    revise_key = "revise-persist-before-complete"

    first = service.submit(
        _request(thread_id, key=revise_key, message="Durable revised claim.")
    )
    revision_after = int(
        (store.get_thread(thread_id) or {}).get("conversation_revision") or 0
    )
    active_after = [
        (message["id"], message["role"], message["content"])
        for message in store.get_messages(thread_id)
    ]
    assert provider.calls == 1

    marker_id = store._coach_marker_id(thread_id, revise_key)
    assert store.path is not None
    with sqlite3.connect(store.path) as connection:
        metadata = json.loads(
            connection.execute(
                "SELECT metadata_text FROM messages WHERE id=?",
                (marker_id,),
            ).fetchone()[0]
        )
        metadata["status"] = "pending"
        metadata.pop("turn", None)
        metadata["lease_token"] = "interrupted-lease"
        metadata["lease_expires_at"] = "2000-01-01T00:00:00+00:00"
        connection.execute(
            "UPDATE messages SET metadata_text=? WHERE id=?",
            (json.dumps(metadata, ensure_ascii=False), marker_id),
        )
        connection.commit()

    revise_calls: list[tuple[str, str, str]] = []
    original_revise = store.revise_conversation_from_user_message

    def tracking_revise(thread, message, content, **kwargs):
        revise_calls.append((thread, message, content))
        return original_revise(thread, message, content, **kwargs)

    store.revise_conversation_from_user_message = tracking_revise  # type: ignore[method-assign]

    replay = service.revise_and_resubmit(
        thread_id,
        "unused-original-user-id",
        "Durable revised claim.",
        idempotency_key=revise_key,
    )

    assert replay.response_text == first.response_text
    assert replay.pending_transition == first.pending_transition
    assert replay.auto_advanced_to == first.auto_advanced_to
    assert replay.assessment.recommendation == first.assessment.recommendation
    assert replay.assessment.response_mode == first.assessment.response_mode
    assert provider.calls == 1
    assert revise_calls == []
    assert int(
        (store.get_thread(thread_id) or {}).get("conversation_revision") or 0
    ) == revision_after
    assert [
        (message["id"], message["role"], message["content"])
        for message in store.get_messages(thread_id)
    ] == active_after
