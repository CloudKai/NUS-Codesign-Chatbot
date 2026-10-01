"""Coach idempotency lease must outlive timeout-bounded Fast Chat execution."""

from __future__ import annotations

import json
import sqlite3
import threading
from datetime import datetime, timedelta, timezone

from backend.application import CoachApplicationService
from backend.domain import CoachRequest, StageDecision
from backend.learning_service import LearningProgressService
from backend.mock_provider import DeterministicCoachProvider
from backend.repositories import (
    SQLiteNotebookRepository,
    SQLitePhaseTransitionRepository,
)
from backend.settings import (
    COACH_IDEMPOTENCY_LEASE_MARGIN_SECONDS,
    COACH_TURN_STATE_AND_PERSIST_BUDGET_SECONDS,
    LEGACY_COACH_IDEMPOTENCY_LEASE_SECONDS,
    bounded_coach_execution_seconds,
    derived_coach_idempotency_lease_seconds,
    settings,
    timeout_bounded_coach_work_seconds,
)
from backend.student_store import StudentStore
from backend.workflow import CoachWorkflow


_FINGERPRINT = "a" * 64
_START = datetime(2026, 8, 17, 3, 0, tzinfo=timezone.utc)


class _FrozenClock:
    """Deterministic UTC clock for lease expiry tests. No real sleeps."""

    def __init__(self, current: datetime) -> None:
        self.current = current

    def __call__(self) -> datetime:
        """Return the frozen instant."""
        return self.current

    def advance(self, seconds: float) -> None:
        """Move the frozen instant forward by *seconds*."""
        self.current = self.current + timedelta(seconds=seconds)


class _CountingProvider(DeterministicCoachProvider):
    """Deterministic provider that records executions without network access."""

    def __init__(self) -> None:
        super().__init__(StageDecision.STAY)
        self.calls = 0
        self._lock = threading.Lock()

    def assess(self, request: CoachRequest):  # type: ignore[override]
        """Count one provider invocation and return the mock assessment."""
        with self._lock:
            self.calls += 1
        return super().assess(request)


def _service(
    store: StudentStore, provider: DeterministicCoachProvider
) -> CoachApplicationService:
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


def _request(thread_id: str, *, key: str) -> CoachRequest:
    """Return one minimal valid idempotent coaching request."""
    return CoachRequest(
        thread_id=thread_id,
        student_message="Assess this claim.",
        current_stage="problem_identification",
        response_detail="short",
        idempotency_key=key,
    )


def _assessment() -> dict[str, object]:
    """Return a persistable mock assessment payload."""
    return {
        "recommendation": "stay",
        "contribution_summary": "Summary",
        "learning_summary": "Learning",
        "working_conclusion": "Conclusion",
        "understanding_change": "Change",
        "critical_understanding_level": "developing",
        "guidance_questions": ["What next?"],
        "citations": [],
    }


def _marker_metadata(store: StudentStore, marker_id: str) -> dict[str, object]:
    """Read the internal coach-request marker metadata from SQLite."""
    assert store.path is not None
    with sqlite3.connect(store.path) as connection:
        raw = connection.execute(
            "SELECT metadata_text FROM messages WHERE id=?",
            (marker_id,),
        ).fetchone()[0]
    loaded = json.loads(raw)
    assert isinstance(loaded, dict)
    return loaded


def test_legacy_180s_lease_is_below_two_agentcore_windows() -> None:
    """The old hard-coded 180s lease cannot cover two 110s AgentCore invokes."""
    timeout_bounded = timeout_bounded_coach_work_seconds(
        provider_timeout_seconds=110,
        provider_max_retries=0,
        retrieve_timeout_seconds=10,
    )
    lease = derived_coach_idempotency_lease_seconds(
        provider_timeout_seconds=110,
        provider_max_retries=0,
        retrieve_timeout_seconds=10,
    )
    assert timeout_bounded == 240
    assert bounded_coach_execution_seconds(
        provider_timeout_seconds=110,
        provider_max_retries=0,
        retrieve_timeout_seconds=10,
    ) == 250
    assert lease == 270
    assert timeout_bounded > LEGACY_COACH_IDEMPOTENCY_LEASE_SECONDS
    assert lease > timeout_bounded
    bumped = derived_coach_idempotency_lease_seconds(
        provider_timeout_seconds=120,
        provider_max_retries=0,
        retrieve_timeout_seconds=10,
    )
    bumped_work = timeout_bounded_coach_work_seconds(
        provider_timeout_seconds=120,
        provider_max_retries=0,
        retrieve_timeout_seconds=10,
    )
    assert bumped_work == 260
    assert bumped_work > LEGACY_COACH_IDEMPOTENCY_LEASE_SECONDS
    assert bumped == 290
    assert bumped > bumped_work


def test_settings_lease_is_derived_from_configured_timeouts() -> None:
    """A future AgentCore timeout bump that outgrows the lease must fail here.

    The lease is not a restated constant. It is recomputed from the live
    ``AGENTCORE_TIMEOUT_SECONDS``, ``AGENTCORE_MAX_RETRIES``, and Retrieve
    timeout so a silent return to 180s cannot hide behind a copied number.
    """
    timeout = float(settings.agentcore_timeout_seconds)
    retries = int(settings.agentcore_max_retries)
    retrieve = int(settings.knowledge_base_retrieve_timeout_seconds)
    timeout_bounded = timeout_bounded_coach_work_seconds(
        provider_timeout_seconds=timeout,
        provider_max_retries=retries,
        retrieve_timeout_seconds=retrieve,
    )
    independent = (
        timeout_bounded
        + COACH_TURN_STATE_AND_PERSIST_BUDGET_SECONDS
        + COACH_IDEMPOTENCY_LEASE_MARGIN_SECONDS
    )
    lease = int(settings.coach_idempotency_lease_seconds)
    two_provider_windows = 2 * timeout * (retries + 1)

    assert lease == independent
    assert lease == derived_coach_idempotency_lease_seconds(
        provider_timeout_seconds=timeout,
        provider_max_retries=retries,
        retrieve_timeout_seconds=retrieve,
    )
    assert lease == int(settings.coach_turn_bounded_execution_seconds) + (
        COACH_IDEMPOTENCY_LEASE_MARGIN_SECONDS
    )
    assert lease > timeout_bounded
    assert lease > two_provider_windows

    bumped_timeout = timeout + 10.0
    bumped_bounded = timeout_bounded_coach_work_seconds(
        provider_timeout_seconds=bumped_timeout,
        provider_max_retries=retries,
        retrieve_timeout_seconds=retrieve,
    )
    bumped_lease = derived_coach_idempotency_lease_seconds(
        provider_timeout_seconds=bumped_timeout,
        provider_max_retries=retries,
        retrieve_timeout_seconds=retrieve,
    )
    assert bumped_lease > lease
    assert bumped_lease > bumped_bounded


def test_claim_default_lease_matches_derived_settings(
    tmp_path, monkeypatch
) -> None:
    """``claim_coach_request`` without ``lease_seconds`` uses the derived lease."""
    clock = _FrozenClock(_START)
    monkeypatch.setattr("backend.student_store._utc_now_datetime", clock)
    store = StudentStore(tmp_path / "lease-default.sqlite3")
    thread_id = store.create_thread(model_id="mock", support_mode="critical-thinking")

    claimed = store.claim_coach_request(
        thread_id,
        idempotency_key="default-lease",
        request_fingerprint=_FINGERPRINT,
    )
    metadata = _marker_metadata(store, claimed.marker_id)
    expiry = datetime.fromisoformat(str(metadata["lease_expires_at"]))
    expected = _START + timedelta(seconds=int(settings.coach_idempotency_lease_seconds))

    assert claimed.state == "claimed"
    assert expiry == expected


def test_lease_cannot_be_reclaimed_during_bounded_execution(
    tmp_path, monkeypatch
) -> None:
    """A retry must not take the marker while timeout-bounded work can still run."""
    clock = _FrozenClock(_START)
    monkeypatch.setattr("backend.student_store._utc_now_datetime", clock)
    store = StudentStore(tmp_path / "lease-window.sqlite3")
    thread_id = store.create_thread(model_id="mock", support_mode="critical-thinking")
    first = store.claim_coach_request(
        thread_id,
        idempotency_key="bounded-window",
        request_fingerprint=_FINGERPRINT,
    )
    assert first.state == "claimed"

    clock.advance(int(settings.coach_turn_bounded_execution_seconds))
    during = store.claim_coach_request(
        thread_id,
        idempotency_key="bounded-window",
        request_fingerprint=_FINGERPRINT,
    )
    assert during.state == "in_progress"
    assert during.lease_token is None
    assert _marker_metadata(store, first.marker_id)["lease_token"] == first.lease_token


def test_stale_lease_can_be_reclaimed_after_expiry(tmp_path, monkeypatch) -> None:
    """A genuinely abandoned lease is recoverable once the derived window ends."""
    clock = _FrozenClock(_START)
    monkeypatch.setattr("backend.student_store._utc_now_datetime", clock)
    store = StudentStore(tmp_path / "lease-reclaim.sqlite3")
    thread_id = store.create_thread(model_id="mock", support_mode="critical-thinking")
    first = store.claim_coach_request(
        thread_id,
        idempotency_key="abandoned-lease",
        request_fingerprint=_FINGERPRINT,
    )

    clock.advance(int(settings.coach_idempotency_lease_seconds))
    second = store.claim_coach_request(
        thread_id,
        idempotency_key="abandoned-lease",
        request_fingerprint=_FINGERPRINT,
    )

    assert second.state == "claimed"
    assert second.lease_token != first.lease_token


def test_same_key_retry_does_not_duplicate_provider_execution(tmp_path) -> None:
    """A completed key replays the stored turn and must not call the provider again."""
    store = StudentStore(tmp_path / "lease-no-duplicate.sqlite3")
    thread_id = store.create_thread(model_id="mock", support_mode="critical-thinking")
    provider = _CountingProvider()
    service = _service(store, provider)
    request = _request(thread_id, key="no-duplicate-key")

    first = service.submit(request)
    replay = service.submit(request)

    assert replay == first
    assert provider.calls == 1
    assert [message["role"] for message in store.get_messages(thread_id)] == [
        "user",
        "assistant",
    ]


def test_in_progress_claim_is_not_a_second_provider_slot(
    tmp_path, monkeypatch
) -> None:
    """Two stores sharing one DB must not both claim during the derived lease."""
    clock = _FrozenClock(_START)
    monkeypatch.setattr("backend.student_store._utc_now_datetime", clock)
    database = tmp_path / "lease-two-stores.sqlite3"
    first_store = StudentStore(database)
    thread_id = first_store.create_thread(
        model_id="mock", support_mode="critical-thinking"
    )
    first = first_store.claim_coach_request(
        thread_id,
        idempotency_key="cross-store-mutex",
        request_fingerprint=_FINGERPRINT,
    )
    second_store = StudentStore(database)
    second = second_store.claim_coach_request(
        thread_id,
        idempotency_key="cross-store-mutex",
        request_fingerprint=_FINGERPRINT,
    )

    assert first.state == "claimed"
    assert second.state == "in_progress"


def test_completed_marker_replays_the_stored_payload(tmp_path) -> None:
    """``complete_coach_request`` is the replay source when rows are not yet scanned."""
    store = StudentStore(tmp_path / "lease-complete-replay.sqlite3")
    thread_id = store.create_thread(model_id="mock", support_mode="critical-thinking")
    key = "replay-complete-payload"
    claimed = store.claim_coach_request(
        thread_id,
        idempotency_key=key,
        request_fingerprint=_FINGERPRINT,
    )
    payload = {
        "response_text": "Stored without message rows yet.",
        "assessment": _assessment(),
    }
    store.complete_coach_request(
        thread_id,
        marker_id=claimed.marker_id,
        idempotency_key=key,
        request_fingerprint=_FINGERPRINT,
        lease_token=str(claimed.lease_token),
        turn_payload=payload,
    )

    replay = store.claim_coach_request(
        thread_id,
        idempotency_key=key,
        request_fingerprint=_FINGERPRINT,
    )
    assert replay.state == "completed"
    assert replay.turn_payload == payload


def test_persisted_turn_replays_from_the_same_idempotency_key(tmp_path) -> None:
    """A successfully persisted turn is recovered even if complete never ran."""
    store = StudentStore(tmp_path / "lease-persist-replay.sqlite3")
    thread_id = store.create_thread(model_id="mock", support_mode="critical-thinking")
    key = "replay-persisted-rows"
    claimed = store.claim_coach_request(
        thread_id,
        idempotency_key=key,
        request_fingerprint=_FINGERPRINT,
    )
    assert claimed.lease_token

    store.persist_coach_turn(
        thread_id,
        expected_stage="problem_identification",
        expected_conversation_revision=0,
        user_content="Assess this claim.",
        user_metadata={"coach_idempotency_key": key},
        assistant_content="A durable assistant reply.",
        assistant_metadata={
            "assessment": _assessment(),
            "coach_idempotency_key": key,
            "from_stage": "problem_identification",
        },
        summary_metadata={},
        idempotency_marker_id=claimed.marker_id,
        idempotency_key=key,
        idempotency_lease_token=claimed.lease_token,
        idempotency_fingerprint=_FINGERPRINT,
    )

    replay = store.claim_coach_request(
        thread_id,
        idempotency_key=key,
        request_fingerprint=_FINGERPRINT,
    )
    assert replay.state == "completed"
    assert isinstance(replay.turn_payload, dict)
    assert replay.turn_payload.get("response_text") == "A durable assistant reply."
    assert replay.turn_payload.get("assessment") == _assessment()
    assert len(store.get_messages(thread_id)) == 2
