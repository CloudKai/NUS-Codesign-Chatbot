"""Budget and admission behavior through the student HTTP interface."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from backend.api import create_app
from backend.mock_provider import DeterministicCoachProvider
from backend.settings import settings
from backend.student_store import StudentStore


class UnknownUsageProvider(DeterministicCoachProvider):
    """Offline provider whose usage cannot be reconciled to a smaller charge."""

    usage_provider = "unknown"


def _setup(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, **overrides: object) -> StudentStore:
    """Configure an explicit synthetic allowance without touching local data."""
    import backend.owner_context as owners

    policy = {
        "ledger_path": str(tmp_path / "generation.sqlite3"),
        "monthly_micro_sgd": 300, "headroom_micro_sgd": 100,
        "call_reserve_micro_sgd": 100, "max_running": 2, "max_queued": 2,
        "max_wait_seconds": 0.2, "lease_seconds": 600,
        "ceiling_evidence": "synthetic offline fixture; not actual pricing",
        **overrides,
    }
    path = tmp_path / "policy.json"
    path.write_text(json.dumps(policy))
    monkeypatch.setattr(settings, "generation_admission_policy", str(path), raising=False)
    monkeypatch.setattr(owners, "configured_coach_provider", UnknownUsageProvider)
    return StudentStore(tmp_path / "students.sqlite3")


def _body(thread_id: str, key: str) -> dict[str, str]:
    """Build a valid ordinary project-coaching submission."""
    return {"thread_id": thread_id, "student_message": "Improve accessibility for older users",
            "current_stage": "problem_identification", "response_detail": "short",
            "idempotency_key": key}


def test_budget_survives_restart_and_replays_leave_read_access(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Two funded calls, one replay, and a restart cannot spend the headroom."""
    store = _setup(tmp_path, monkeypatch)
    thread = store.create_thread(model_id="mock", support_mode="critical-thinking")
    with TestClient(create_app(store)) as client:
        first = client.post("/api/v1/coach/turn", json=_body(thread, "first"))
        assert first.status_code == 200
        assert client.post("/api/v1/coach/turn", json=_body(thread, "first")).json() == first.json()
        assert client.post("/api/v1/coach/turn", json=_body(thread, "second")).status_code == 200
    with TestClient(create_app(StudentStore(store.path))) as client:
        rejected = client.post("/api/v1/coach/turn", json=_body(thread, "third"))
        assert rejected.status_code == 429
        assert rejected.json()["detail"]["category"] == "generation_budget"
        assert "UTC" in rejected.json()["detail"]["message"]
        assert int(rejected.headers["retry-after"]) > 0
        assert client.get(f"/api/v1/threads/{thread}").status_code == 200
        assert client.get(f"/api/v1/threads/{thread}/messages").status_code == 200
        assert client.get(f"/api/v1/threads/{thread}/sources").status_code == 200
        assert client.get(f"/api/v1/threads/{thread}/transcript.txt").status_code == 200
        assert client.post("/api/v1/coach/turn", json=_body(thread, "first")).json() == first.json()


def test_stream_exposes_bounded_queue_and_timeout(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An occupied slot produces a truthful queue event then a finite rejection."""
    import threading
    from concurrent.futures import ThreadPoolExecutor
    from backend.domain import CoachRequest, ProviderAssessmentResult
    import backend.owner_context as owners

    entered, release = threading.Event(), threading.Event()

    class SlowProvider(UnknownUsageProvider):
        """Hold an external provider boundary until the test releases it."""

        def assess(self, request: CoachRequest) -> ProviderAssessmentResult:
            """Wait only for the first admitted student message."""
            entered.set()
            assert release.wait(5)
            return super().assess(request)

    store = _setup(tmp_path, monkeypatch, monthly_micro_sgd=1000, max_running=1, max_queued=1)
    monkeypatch.setattr(owners, "configured_coach_provider", SlowProvider)
    threads = [store.create_thread(model_id="mock", support_mode="critical-thinking") for _ in range(3)]
    with TestClient(create_app(store)) as client, ThreadPoolExecutor(max_workers=2) as pool:
        future = pool.submit(client.post, "/api/v1/coach/turn", json=_body(threads[0], "active"))
        try:
            assert entered.wait(3)
            response = client.post("/api/v1/coach/turn/stream", json=_body(threads[1], "wait"))
            events = [json.loads(line) for line in response.text.splitlines()]
            assert any(event.get("phase") == "queued" for event in events)
            assert events[-1]["category"] == "generation_wait"
            assert events[-1]["status"] == 429
            assert not any(event.get("phase") == "thinking" for event in events)
            assert not any(event["event"] in {"reply_ready", "done"} for event in events)
        finally:
            release.set()
        assert future.result().status_code == 200
        assert client.post("/api/v1/coach/turn", json=_body(threads[2], "later")).status_code == 200


def test_exhausted_deep_review_reports_budget_rejection(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A review cannot conceal budget exhaustion as a generic model failure."""
    import time
    from backend.student_journey import THINKING_STAGES, normalize_journey

    store = _setup(tmp_path, monkeypatch, monthly_micro_sgd=200)
    chat = store.create_thread(model_id="mock", support_mode="critical-thinking")
    review = store.create_thread(model_id="mock", support_mode="critical-thinking")
    journey = normalize_journey(None)
    journey["completed_stages"] = [stage.id for stage in THINKING_STAGES]
    store.update_thread(review, metadata={"learning_journey": journey})
    with TestClient(create_app(store)) as client:
        assert client.post("/api/v1/coach/turn", json=_body(chat, "spend")).status_code == 200
        result = client.post(f"/api/v1/threads/{review}/deep-review", json={})
        assert result.status_code == 200
        deadline = time.monotonic() + 3
        while time.monotonic() < deadline:
            result = client.get(f"/api/v1/threads/{review}/deep-review")
            if result.json()["status"] == "failed":
                break
            time.sleep(0.01)
        assert result.json()["status"] == "failed"
        assert result.json()["error_code"] == "generation_budget"


def test_background_reviews_have_bounded_submission_capacity(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A full background pool rejects work instead of hiding an unbounded queue."""
    import threading
    from backend.domain import CoachRequest, ProviderAssessmentResult
    from backend.student_journey import THINKING_STAGES, normalize_journey
    import backend.owner_context as owners

    entered, release = threading.Event(), threading.Event()

    class SlowReview(UnknownUsageProvider):
        """Offline review that keeps the sole background allowance occupied."""

        def assess(self, request: CoachRequest) -> ProviderAssessmentResult:
            """Hold the external operation while another review arrives."""
            entered.set()
            assert release.wait(5)
            return super().assess(request)

    store = _setup(tmp_path, monkeypatch, monthly_micro_sgd=1000)
    monkeypatch.setattr(settings, "generation_background_jobs", 1, raising=False)
    monkeypatch.setattr(owners, "configured_coach_provider", SlowReview)
    threads = [store.create_thread(model_id="mock", support_mode="critical-thinking") for _ in range(2)]
    journey = normalize_journey(None)
    journey["completed_stages"] = [stage.id for stage in THINKING_STAGES]
    for thread in threads:
        store.update_thread(thread, metadata={"learning_journey": journey})
    checkpoint = store.create_thread(model_id="mock", support_mode="critical-thinking")
    store.update_thread(checkpoint, metadata={"learning_journey": journey,
        "journey_stage_reviews": {"jobs": {"problem_identification": {
            "status": "queued", "job_id": "offline-checkpoint", "conversation_revision": 0,
        }}}})
    with TestClient(create_app(store)) as client:
        try:
            assert client.post(f"/api/v1/threads/{threads[0]}/deep-review", json={}).status_code == 200
            assert entered.wait(3)
            result = client.post(f"/api/v1/threads/{threads[1]}/deep-review", json={})
            assert result.json()["status"] == "failed"
            assert result.json()["error_code"] == "generation_capacity"
            stages = client.get(f"/api/v1/threads/{checkpoint}/journey-stage-reviews").json()
            assert stages["jobs"]["problem_identification"]["status"] == "failed"
            assert stages["jobs"]["problem_identification"]["error_code"] == "generation_capacity"
        finally:
            release.set()


def test_failed_call_retains_charge_and_known_retry_reconciles(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Unknown failure costs 100; a complete retry costs 20, preserving 80."""
    from backend.domain import CoachRequest, ProviderAssessmentResult
    from backend.providers import ProviderUnavailableError
    from backend.usage import generation_call
    import backend.owner_context as owners

    class MeteredProvider(UnknownUsageProvider):
        """External model boundary with synthetic complete numeric meters."""

        usage_metered = True
        attempts = 0

        def assess(self, request: CoachRequest) -> ProviderAssessmentResult:
            """Timeout once, then return a complete 100/100 token result."""
            with generation_call("mock", "fixture", "fast_chat", region="offline") as meter:
                self.attempts += 1
                if self.attempts == 1:
                    raise ProviderUnavailableError("offline timeout")
                meter.input_tokens = meter.output_tokens = 100
                meter.cache_read_tokens = meter.cache_write_tokens = 0
                meter.sdk_retries = 0
                meter.model_calls = 1
                return super().assess(request)

    store = _setup(tmp_path, monkeypatch, rates=[{
        "provider": "mock", "model": "fixture", "region": "offline",
        "input": 100000, "output": 100000, "cache_read": 0, "cache_write": 0,
        "evidence": "synthetic rates: 20 micro SGD for 100 input + 100 output",
    }])
    monkeypatch.setattr(owners, "configured_coach_provider", MeteredProvider)
    thread = store.create_thread(model_id="mock", support_mode="critical-thinking")
    with TestClient(create_app(store)) as client:
        assert client.post("/api/v1/coach/turn", json=_body(thread, "retry")).status_code == 503
        assert client.post("/api/v1/coach/turn", json=_body(thread, "retry")).status_code == 200
        assert client.post("/api/v1/coach/turn", json=_body(thread, "new")).status_code == 429


def test_concurrent_owners_cannot_race_the_last_reservation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Two owner-scoped app instances share the final funded call atomically."""
    from concurrent.futures import ThreadPoolExecutor
    import threading

    store = _setup(tmp_path, monkeypatch, monthly_micro_sgd=200)
    other = StudentStore(store.path, identifier="other-offline-owner")
    one = store.create_thread(model_id="mock", support_mode="critical-thinking")
    two = other.create_thread(model_id="mock", support_mode="critical-thinking")
    barrier = threading.Barrier(2)
    with TestClient(create_app(store)) as client, TestClient(create_app(other)) as second:
        def submit(api: TestClient, thread: str) -> int:
            """Synchronize independent owner arrivals at the public API."""
            barrier.wait(3)
            return api.post("/api/v1/coach/turn", json=_body(thread, "same-public-key")).status_code
        with ThreadPoolExecutor(max_workers=2) as pool:
            futures = [pool.submit(submit, client, one), pool.submit(submit, second, two)]
            assert sorted(f.result() for f in futures) == [200, 429]


def test_expired_invocation_keeps_charge_and_capacity_until_worker_settles(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A restarted worker cannot treat an expired, possibly billed call as free."""
    from backend.generation_admission import GenerationPolicy, SQLiteGenerationAdmission
    from backend.usage import GenerationUsage

    store = _setup(tmp_path, monkeypatch, monthly_micro_sgd=500, max_running=1, max_queued=0, lease_seconds=1)
    policy = GenerationPolicy.model_validate_json((tmp_path / "policy.json").read_text())
    now = [1794830400.0]
    original = SQLiteGenerationAdmission(policy, clock=lambda: now[0])
    token = original.acquire()  # Fixture: a worker crashed after starting a call.
    now[0] += 2
    restarted = SQLiteGenerationAdmission(policy, clock=lambda: now[0])
    thread = store.create_thread(model_id="mock", support_mode="critical-thinking")
    with TestClient(create_app(store, generation_admission=restarted)) as client:
        blocked = client.post("/api/v1/coach/turn", json=_body(thread, "expired"))
        assert blocked.status_code == 429
        assert blocked.json()["detail"]["category"] == "generation_capacity"
        original.settle(token, GenerationUsage(operation_id="offline", kind="chat", provider="unknown"))
        assert client.post("/api/v1/coach/turn", json=_body(thread, "after-settlement")).status_code == 200


def test_duplicate_pending_requests_share_funded_execution(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Exact concurrent retries both recover one saved answer at the final call."""
    import threading
    from concurrent.futures import ThreadPoolExecutor
    from backend.domain import CoachRequest, ProviderAssessmentResult
    import backend.owner_context as owners

    entered, release = threading.Event(), threading.Event()

    class PendingProvider(UnknownUsageProvider):
        """Hold the external call while the exact HTTP retry arrives."""

        def assess(self, request: CoachRequest) -> ProviderAssessmentResult:
            """Return one deterministic answer after release."""
            entered.set()
            assert release.wait(5)
            return super().assess(request)

    store = _setup(tmp_path, monkeypatch, monthly_micro_sgd=200)
    monkeypatch.setattr(owners, "configured_coach_provider", PendingProvider)
    thread = store.create_thread(model_id="mock", support_mode="critical-thinking")
    with TestClient(create_app(store)) as client, ThreadPoolExecutor(max_workers=2) as pool:
        first = pool.submit(client.post, "/api/v1/coach/turn", json=_body(thread, "same"))
        assert entered.wait(3)
        duplicate = pool.submit(client.post, "/api/v1/coach/turn", json=_body(thread, "same"))
        release.set()
        assert first.result().status_code == duplicate.result().status_code == 200
        assert first.result().json() == duplicate.result().json()
        assert client.post("/api/v1/coach/turn", json=_body(thread, "unfunded")).status_code == 429


def test_background_queue_expiry_is_terminal_without_browser_polling(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A review waiting behind a slow worker expires independently of a tab."""
    import threading
    import time
    from backend.domain import CoachRequest, ProviderAssessmentResult
    from backend.student_journey import THINKING_STAGES, normalize_journey
    import backend.owner_context as owners

    entered, release = threading.Event(), threading.Event()

    class SlowWorker(UnknownUsageProvider):
        """Occupy the one offline review worker beyond the queue deadline."""

        def assess(self, request: CoachRequest) -> ProviderAssessmentResult:
            """Hold generation until the test checks the other review."""
            entered.set()
            assert release.wait(5)
            return super().assess(request)

    store = _setup(tmp_path, monkeypatch, monthly_micro_sgd=1000)
    monkeypatch.setattr(settings, "deep_review_max_concurrent", 1)
    monkeypatch.setattr(settings, "generation_background_jobs", 2)
    monkeypatch.setattr(settings, "generation_background_wait_seconds", 1)
    monkeypatch.setattr(owners, "configured_coach_provider", SlowWorker)
    threads = [store.create_thread(model_id="mock", support_mode="critical-thinking") for _ in range(2)]
    journey = normalize_journey(None)
    journey["completed_stages"] = [stage.id for stage in THINKING_STAGES]
    for thread in threads:
        store.update_thread(thread, metadata={"learning_journey": journey})
    with TestClient(create_app(store)) as client:
        try:
            client.post(f"/api/v1/threads/{threads[0]}/deep-review", json={})
            assert entered.wait(3)
            queued = client.post(f"/api/v1/threads/{threads[1]}/deep-review", json={}).json()
            assert queued["status"] == "queued"
            time.sleep(1.2)  # No browser/status reads drive the expiry timer.
            expired = client.get(f"/api/v1/threads/{threads[1]}/deep-review").json()
            assert expired["status"] == "failed"
            assert expired["error_code"] == "generation_wait"
        finally:
            release.set()


def test_structured_output_recovery_requires_a_second_funded_call(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A provider recovery cannot bypass exhaustion or turn it into a 503."""
    from backend.agentcore_provider import AgentCoreCoachProvider
    from fake_agentcore_runtime import FakeAgentCoreRuntime
    import backend.owner_context as owners

    store = _setup(tmp_path, monkeypatch, monthly_micro_sgd=200)
    runtime = FakeAgentCoreRuntime(payloads=[{
        "ok": False, "error": True, "category": "structured_output_failure",
        "model_input_tokens": 100, "model_output_tokens": 40,
    }])
    provider = AgentCoreCoachProvider(
        "arn:aws:bedrock-agentcore:us-west-2:123456789012:runtime/test",
        region="us-west-2", client=runtime, max_retries=0,
    )
    monkeypatch.setattr(owners, "configured_coach_provider", lambda: provider)
    thread = store.create_thread(model_id="mock", support_mode="critical-thinking")
    with TestClient(create_app(store)) as client:
        result = client.post("/api/v1/coach/turn", json=_body(thread, "recovery"))
        assert result.status_code == 429
        assert result.json()["detail"]["category"] == "generation_budget"
        assert client.get(f"/api/v1/threads/{thread}/coach-turn", params={"idempotency_key": "recovery"}).json() is None
