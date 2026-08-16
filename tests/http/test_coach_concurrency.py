"""Application-level notebook concurrency and idempotency interaction tests."""

from __future__ import annotations

import threading
from concurrent.futures import ThreadPoolExecutor

import pytest
from fastapi.testclient import TestClient

from backend.api import create_app
from backend.application import CoachApplicationService
from backend.domain import CoachRequest, StageDecision
from backend.learning_service import LearningProgressService
from backend.mock_provider import DeterministicCoachProvider
from backend.rate_limit import (
    CoachRateLimiter,
    RateLimitExceeded,
    reset_coach_rate_limiter_for_tests,
)
from backend.repositories import (
    SQLiteNotebookRepository,
    SQLitePhaseTransitionRepository,
)
from backend.student_store import StudentStore
from backend.workflow import CoachWorkflow


@pytest.fixture(autouse=True)
def _reset_limiter():
    reset_coach_rate_limiter_for_tests()
    yield
    reset_coach_rate_limiter_for_tests()


def _service(
    store: StudentStore, provider: DeterministicCoachProvider | None = None
) -> CoachApplicationService:
    """Build the normal application path with an inspectable mock provider."""
    notebooks = SQLiteNotebookRepository(store)
    transitions = SQLitePhaseTransitionRepository(store)
    workflow = CoachWorkflow(provider or DeterministicCoachProvider(StageDecision.STAY), transitions)
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


def _inject_limiter(monkeypatch: pytest.MonkeyPatch, limiter: CoachRateLimiter) -> None:
    """Replace the process limiter with an explicit test instance."""
    from backend import rate_limit as rate_limit_module

    monkeypatch.setattr(rate_limit_module, "_LIMITER", limiter)


class CountingProvider(DeterministicCoachProvider):
    """Deterministic provider that records executions without network access."""

    def __init__(self, *, delay_seconds: float = 0.0, fail: bool = False) -> None:
        super().__init__(StageDecision.STAY)
        self.calls = 0
        self._delay_seconds = delay_seconds
        self._fail = fail
        self._lock = threading.Lock()
        self.thread_ids: list[str] = []

    def assess(self, request: CoachRequest):  # type: ignore[override]
        """Count one provider invocation and optionally fail."""
        with self._lock:
            self.calls += 1
            self.thread_ids.append(str(request.thread_id))
        if self._delay_seconds:
            import time

            time.sleep(self._delay_seconds)
        if self._fail:
            raise RuntimeError("deterministic provider failure")
        return super().assess(request)


def test_two_notebooks_same_owner_execute_concurrently(tmp_path, monkeypatch):
    """One authenticated owner may run two different notebooks at once."""
    limiter = CoachRateLimiter(
        max_active_per_notebook=1,
        max_active_per_user=2,
        requests_per_minute=20,
        max_concurrent_model_calls=20,
    )
    _inject_limiter(monkeypatch, limiter)
    store = StudentStore(tmp_path / "two-notebooks.sqlite3")
    first = store.create_thread(model_id="mock", support_mode="critical-thinking")
    second = store.create_thread(model_id="mock", support_mode="critical-thinking")
    provider = CountingProvider()
    started = threading.Barrier(2)
    original = CoachApplicationService._submit_once

    def gated_submit_once(self, request, **kwargs):
        started.wait(timeout=2)
        return original(self, request, **kwargs)

    monkeypatch.setattr(CoachApplicationService, "_submit_once", gated_submit_once)
    service = _service(store, provider)

    def run(thread_id: str, key: str):
        return service.submit(_request(thread_id, key=key, message=key))

    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = [
            executor.submit(run, first, "nb-1"),
            executor.submit(run, second, "nb-2"),
        ]
        results = [future.result(timeout=8) for future in futures]

    assert all(turn.response_text for turn in results)
    assert provider.calls == 2
    assert sorted(provider.thread_ids) == sorted([first, second])


def test_overlapping_same_notebook_only_one_enters_provider(tmp_path, monkeypatch):
    """Two overlapping executions for one notebook cannot both call the provider."""
    limiter = CoachRateLimiter(
        max_active_per_notebook=1,
        max_active_per_user=2,
        requests_per_minute=20,
        max_concurrent_model_calls=20,
    )
    _inject_limiter(monkeypatch, limiter)
    store = StudentStore(tmp_path / "same-notebook.sqlite3")
    thread_id = store.create_thread(model_id="mock", support_mode="critical-thinking")
    provider = CountingProvider()
    service = _service(store, provider)
    started = threading.Event()
    release = threading.Event()
    original = CoachApplicationService._submit_once

    def slow_submit_once(self, request, **kwargs):
        started.set()
        assert release.wait(timeout=2)
        return original(self, request, **kwargs)

    monkeypatch.setattr(CoachApplicationService, "_submit_once", slow_submit_once)

    def first():
        return service.submit(_request(thread_id, key="first"))

    with ThreadPoolExecutor(max_workers=1) as executor:
        future = executor.submit(first)
        assert started.wait(timeout=2)
        with pytest.raises(RateLimitExceeded) as raised:
            service.submit(_request(thread_id, key="second", message="second"))
        assert raised.value.category == "notebook_concurrency"
        release.set()
        first_turn = future.result(timeout=5)

    assert first_turn.response_text
    assert provider.calls == 1
    revision = int(
        (store.get_thread(thread_id) or {}).get("conversation_revision")
        or (store.get_thread(thread_id) or {}).get("metadata", {}).get(
            "conversation_revision"
        )
        or 0
    )
    assert revision >= 0
    messages = store.get_messages(thread_id)
    assert len(messages) == 2


def test_different_owners_do_not_block_each_other(tmp_path, monkeypatch):
    """Unrelated students may coach at the same time."""
    limiter = CoachRateLimiter(
        max_active_per_notebook=1,
        max_active_per_user=2,
        requests_per_minute=20,
        max_concurrent_model_calls=20,
    )
    _inject_limiter(monkeypatch, limiter)
    db = tmp_path / "owners.sqlite3"
    store_a = StudentStore(db, identifier="cognito:owner-a")
    store_b = StudentStore(db, identifier="cognito:owner-b")
    assert store_a.owner_id != store_b.owner_id
    thread_a = store_a.create_thread(model_id="mock", support_mode="critical-thinking")
    thread_b = store_b.create_thread(model_id="mock", support_mode="critical-thinking")
    started = threading.Barrier(2)
    original = CoachApplicationService._submit_once

    def gated_submit_once(self, request, **kwargs):
        started.wait(timeout=2)
        return original(self, request, **kwargs)

    monkeypatch.setattr(CoachApplicationService, "_submit_once", gated_submit_once)
    service_a = _service(store_a)
    service_b = _service(store_b)

    with ThreadPoolExecutor(max_workers=2) as executor:
        future_a = executor.submit(
            service_a.submit, _request(thread_a, key="owner-a")
        )
        future_b = executor.submit(
            service_b.submit, _request(thread_b, key="owner-b")
        )
        turn_a = future_a.result(timeout=8)
        turn_b = future_b.result(timeout=8)

    assert turn_a.response_text
    assert turn_b.response_text
    assert store_a.get_thread(thread_b) is None
    assert store_b.get_thread(thread_a) is None


def test_completed_idempotency_replay_does_not_consume_a_slot(tmp_path, monkeypatch):
    """Completed replays skip the limiter even when the user is at capacity."""
    limiter = CoachRateLimiter(
        max_active_per_notebook=1,
        max_active_per_user=2,
        requests_per_minute=20,
        max_concurrent_model_calls=20,
    )
    _inject_limiter(monkeypatch, limiter)
    store = StudentStore(tmp_path / "replay.sqlite3")
    first = store.create_thread(model_id="mock", support_mode="critical-thinking")
    second = store.create_thread(model_id="mock", support_mode="critical-thinking")
    third = store.create_thread(model_id="mock", support_mode="critical-thinking")
    provider = CountingProvider()
    service = _service(store, provider)
    completed = service.submit(_request(first, key="replay-me"))
    assert provider.calls == 1

    limiter.acquire(str(store.owner_id), second)
    limiter.acquire(str(store.owner_id), third)
    replayed = service.submit(_request(first, key="replay-me"))
    limiter.release(str(store.owner_id), second)
    limiter.release(str(store.owner_id), third)

    assert replayed.model_dump(mode="json") == completed.model_dump(mode="json")
    assert provider.calls == 1


def test_failed_provider_releases_limiter_slot(tmp_path, monkeypatch):
    """A provider failure must not leak the notebook or user counter."""
    limiter = CoachRateLimiter(
        max_active_per_notebook=1,
        max_active_per_user=2,
        requests_per_minute=20,
        max_concurrent_model_calls=20,
    )
    _inject_limiter(monkeypatch, limiter)
    store = StudentStore(tmp_path / "provider-fail.sqlite3")
    thread_id = store.create_thread(model_id="mock", support_mode="critical-thinking")
    failing = CountingProvider(fail=True)
    with pytest.raises(RuntimeError, match="deterministic provider failure"):
        _service(store, failing).submit(_request(thread_id, key="fail-once"))
    assert limiter._global_active == 0  # noqa: SLF001
    recovered = _service(store, CountingProvider()).submit(
        _request(thread_id, key="fail-once")
    )
    assert recovered.response_text


def test_failed_persistence_releases_limiter_slot(tmp_path, monkeypatch):
    """A persist failure inside the claimed execution still releases capacity."""
    limiter = CoachRateLimiter(
        max_active_per_notebook=1,
        max_active_per_user=2,
        requests_per_minute=20,
        max_concurrent_model_calls=20,
    )
    _inject_limiter(monkeypatch, limiter)
    store = StudentStore(tmp_path / "persist-fail.sqlite3")
    thread_id = store.create_thread(model_id="mock", support_mode="critical-thinking")
    service = _service(store)
    original = store.persist_coach_turn

    def boom(*args, **kwargs):
        raise RuntimeError("deterministic persist failure")

    monkeypatch.setattr(store, "persist_coach_turn", boom)
    with pytest.raises(RuntimeError, match="deterministic persist failure"):
        service.submit(_request(thread_id, key="persist-fail"))
    assert limiter._global_active == 0  # noqa: SLF001
    monkeypatch.setattr(store, "persist_coach_turn", original)
    recovered = service.submit(_request(thread_id, key="persist-fail"))
    assert recovered.response_text


def test_api_two_notebooks_same_owner_are_accepted(tmp_path, monkeypatch):
    """HTTP path: one local owner may coach two notebooks concurrently."""
    from backend import rate_limit as rate_limit_module

    limiter = CoachRateLimiter(
        max_active_per_notebook=1,
        max_active_per_user=2,
        requests_per_minute=20,
        max_concurrent_model_calls=20,
    )
    monkeypatch.setattr(rate_limit_module, "_LIMITER", limiter)
    store = StudentStore(tmp_path / "http-two-nb.sqlite3")
    first = store.create_thread(model_id="mock", support_mode="critical-thinking")
    second = store.create_thread(model_id="mock", support_mode="critical-thinking")
    client = TestClient(create_app(store))
    started = threading.Barrier(2)
    original = CoachApplicationService._submit_once

    def gated_submit_once(self, request, **kwargs):
        started.wait(timeout=2)
        return original(self, request, **kwargs)

    monkeypatch.setattr(CoachApplicationService, "_submit_once", gated_submit_once)

    def post(thread_id: str, key: str):
        return client.post(
            "/api/v1/coach/turn",
            json={
                "thread_id": thread_id,
                "student_message": key,
                "current_stage": "problem_identification",
                "response_detail": "short",
                "idempotency_key": key,
            },
        )

    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = [
            executor.submit(post, first, "http-nb-1"),
            executor.submit(post, second, "http-nb-2"),
        ]
        responses = [future.result(timeout=8) for future in futures]

    assert [response.status_code for response in responses] == [200, 200]


def test_client_supplied_owner_header_is_ignored_for_limiter(tmp_path, monkeypatch):
    """Browser X-User-Id must not create a separate limiter identity."""
    from backend import rate_limit as rate_limit_module

    limiter = CoachRateLimiter(
        max_active_per_notebook=1,
        max_active_per_user=2,
        requests_per_minute=20,
        max_concurrent_model_calls=20,
    )
    monkeypatch.setattr(rate_limit_module, "_LIMITER", limiter)
    store = StudentStore(tmp_path / "spoof.sqlite3")
    thread_id = store.create_thread(model_id="mock", support_mode="critical-thinking")
    client = TestClient(create_app(store))
    started = threading.Event()
    release = threading.Event()
    original = CoachApplicationService._submit_once

    def slow_submit_once(self, request, **kwargs):
        started.set()
        assert release.wait(timeout=2)
        return original(self, request, **kwargs)

    monkeypatch.setattr(CoachApplicationService, "_submit_once", slow_submit_once)

    def first_call():
        return client.post(
            "/api/v1/coach/turn",
            json={
                "thread_id": thread_id,
                "student_message": "first",
                "current_stage": "problem_identification",
                "response_detail": "short",
                "idempotency_key": "spoof-1",
            },
        )

    with ThreadPoolExecutor(max_workers=1) as executor:
        future = executor.submit(first_call)
        assert started.wait(timeout=2)
        spoofed = client.post(
            "/api/v1/coach/turn",
            headers={"X-User-Id": "attacker", "X-Owner-Id": "attacker"},
            json={
                "thread_id": thread_id,
                "student_message": "second",
                "current_stage": "problem_identification",
                "response_detail": "short",
                "idempotency_key": "spoof-2",
            },
        )
        release.set()
        first = future.result(timeout=5)

    assert first.status_code == 200
    assert spoofed.status_code == 429


def _conversation_revision(store: StudentStore, thread_id: str) -> int:
    """Return the durable notebook conversation revision."""
    thread = store.get_thread(thread_id) or {}
    metadata = dict(thread.get("metadata") or {})
    if metadata.get("conversation_revision") is not None:
        return int(metadata["conversation_revision"])
    return int(thread.get("conversation_revision") or 0)


def _user_message_id(store: StudentStore, thread_id: str) -> str:
    """Return the first active user message id."""
    for message in store.get_messages(thread_id):
        if str(message.get("role") or "") == "user":
            return str(message["id"])
    raise AssertionError("expected a user message")


def test_overlapping_revise_is_rejected_before_notebook_mutation(tmp_path, monkeypatch):
    """An in-flight send must 429 revise before any conversation mutation."""
    limiter = CoachRateLimiter(
        max_active_per_notebook=1,
        max_active_per_user=2,
        requests_per_minute=20,
        max_concurrent_model_calls=20,
    )
    _inject_limiter(monkeypatch, limiter)
    store = StudentStore(tmp_path / "revise-busy.sqlite3")
    thread_id = store.create_thread(model_id="mock", support_mode="critical-thinking")
    service = _service(store)
    service.submit(_request(thread_id, key="seed-revise-busy", message="Original"))
    user_id = _user_message_id(store, thread_id)
    before_messages = store.get_messages(thread_id)
    before_revision = _conversation_revision(store, thread_id)
    started = threading.Event()
    release = threading.Event()
    original = CoachApplicationService._submit_once

    def slow_submit_once(self, request, **kwargs):
        started.set()
        assert release.wait(timeout=2)
        return original(self, request, **kwargs)

    monkeypatch.setattr(CoachApplicationService, "_submit_once", slow_submit_once)

    def first():
        return service.submit(_request(thread_id, key="in-flight-send", message="Second"))

    with ThreadPoolExecutor(max_workers=1) as executor:
        future = executor.submit(first)
        assert started.wait(timeout=2)
        with pytest.raises(RateLimitExceeded) as raised:
            service.revise_and_resubmit(
                thread_id,
                user_id,
                "NOTEBOOK_A_ONLY edited",
                idempotency_key="revise-while-busy",
            )
        assert raised.value.category == "notebook_concurrency"
        after_messages = store.get_messages(thread_id)
        assert [item["content"] for item in after_messages] == [
            item["content"] for item in before_messages
        ]
        assert _conversation_revision(store, thread_id) == before_revision
        release.set()
        first_turn = future.result(timeout=5)

    assert first_turn.response_text
    assert limiter._global_active == 0  # noqa: SLF001


def test_revise_succeeds_after_notebook_slot_is_released(tmp_path, monkeypatch):
    limiter = CoachRateLimiter(
        max_active_per_notebook=1,
        max_active_per_user=2,
        requests_per_minute=20,
        max_concurrent_model_calls=20,
    )
    _inject_limiter(monkeypatch, limiter)
    store = StudentStore(tmp_path / "revise-after-free.sqlite3")
    thread_id = store.create_thread(model_id="mock", support_mode="critical-thinking")
    service = _service(store)
    service.submit(_request(thread_id, key="seed-free", message="Original"))
    user_id = _user_message_id(store, thread_id)
    turn = service.revise_and_resubmit(
        thread_id,
        user_id,
        "Edited after free",
        idempotency_key="revise-after-free",
    )
    assert turn.response_text
    messages = store.get_messages(thread_id)
    assert messages[0]["content"] == "Edited after free"
    assert _conversation_revision(store, thread_id) == 1
    assert limiter._global_active == 0  # noqa: SLF001


def test_same_key_revise_retry_does_not_mutate_twice(tmp_path, monkeypatch):
    limiter = CoachRateLimiter(
        max_active_per_notebook=1,
        max_active_per_user=2,
        requests_per_minute=20,
        max_concurrent_model_calls=20,
    )
    _inject_limiter(monkeypatch, limiter)
    store = StudentStore(tmp_path / "revise-same-key.sqlite3")
    thread_id = store.create_thread(model_id="mock", support_mode="critical-thinking")
    service = _service(store)
    service.submit(_request(thread_id, key="seed-same-key", message="Original"))
    user_id = _user_message_id(store, thread_id)
    first = service.revise_and_resubmit(
        thread_id,
        user_id,
        "Edited once",
        idempotency_key="revise-same-key",
    )
    second = service.revise_and_resubmit(
        thread_id,
        user_id,
        "Edited once",
        idempotency_key="revise-same-key",
    )
    assert first.response_text == second.response_text
    messages = store.get_messages(thread_id)
    assert [item["content"] for item in messages if item["role"] == "user"] == [
        "Edited once"
    ]
    assert _conversation_revision(store, thread_id) == 1
    assert limiter._global_active == 0  # noqa: SLF001


def test_provider_failure_after_revision_releases_exact_lease(tmp_path, monkeypatch):
    limiter = CoachRateLimiter(
        max_active_per_notebook=1,
        max_active_per_user=2,
        requests_per_minute=20,
        max_concurrent_model_calls=20,
    )
    _inject_limiter(monkeypatch, limiter)
    store = StudentStore(tmp_path / "revise-provider-fail.sqlite3")
    thread_id = store.create_thread(model_id="mock", support_mode="critical-thinking")
    seed = _service(store)
    seed.submit(_request(thread_id, key="seed-fail-revise", message="Original"))
    user_id = _user_message_id(store, thread_id)
    failing = _service(store, CountingProvider(fail=True))
    with pytest.raises(RuntimeError, match="deterministic provider failure"):
        failing.revise_and_resubmit(
            thread_id,
            user_id,
            "Edited then failed",
            idempotency_key="revise-fail-once",
        )
    assert limiter._global_active == 0  # noqa: SLF001
    assert _conversation_revision(store, thread_id) == 1
    recovered = _service(store, CountingProvider()).revise_and_resubmit(
        thread_id,
        user_id,
        "Edited then failed",
        idempotency_key="revise-fail-once",
    )
    assert recovered.response_text
    assert _conversation_revision(store, thread_id) == 1
    assert limiter._global_active == 0  # noqa: SLF001


def test_guardrail_provider_unavailable_releases_exact_lease(tmp_path, monkeypatch):
    from backend.providers import ProviderUnavailableError

    limiter = CoachRateLimiter(
        max_active_per_notebook=1,
        max_active_per_user=2,
        requests_per_minute=20,
        max_concurrent_model_calls=20,
    )
    _inject_limiter(monkeypatch, limiter)
    store = StudentStore(tmp_path / "guardrail-release.sqlite3")
    thread_id = store.create_thread(model_id="mock", support_mode="critical-thinking")

    class GuardrailProvider:
        def assess(self, request: CoachRequest):
            raise ProviderUnavailableError(
                "blocked this turn", category="safety_blocked"
            )

    with pytest.raises(ProviderUnavailableError) as raised:
        _service(store, GuardrailProvider()).submit(  # type: ignore[arg-type]
            _request(thread_id, key="guardrail-blocked")
        )
    assert raised.value.category == "safety_blocked"
    assert limiter._global_active == 0  # noqa: SLF001
    recovered = _service(store).submit(_request(thread_id, key="guardrail-blocked"))
    assert recovered.response_text


def test_api_overlapping_revise_returns_429_without_mutation(tmp_path, monkeypatch):
    from backend import rate_limit as rate_limit_module

    limiter = CoachRateLimiter(
        max_active_per_notebook=1,
        max_active_per_user=2,
        requests_per_minute=20,
        max_concurrent_model_calls=20,
    )
    monkeypatch.setattr(rate_limit_module, "_LIMITER", limiter)
    store = StudentStore(tmp_path / "http-revise-busy.sqlite3")
    thread_id = store.create_thread(model_id="mock", support_mode="critical-thinking")
    client = TestClient(create_app(store))
    seed = client.post(
        "/api/v1/coach/turn",
        json={
            "thread_id": thread_id,
            "student_message": "Original",
            "current_stage": "problem_identification",
            "response_detail": "short",
            "idempotency_key": "http-seed",
        },
    )
    assert seed.status_code == 200, seed.text
    user_id = _user_message_id(store, thread_id)
    before = [item["content"] for item in store.get_messages(thread_id)]
    started = threading.Event()
    release = threading.Event()
    original = CoachApplicationService._submit_once

    def slow_submit_once(self, request, **kwargs):
        started.set()
        assert release.wait(timeout=2)
        return original(self, request, **kwargs)

    monkeypatch.setattr(CoachApplicationService, "_submit_once", slow_submit_once)

    def first_call():
        return client.post(
            "/api/v1/coach/turn",
            json={
                "thread_id": thread_id,
                "student_message": "Second",
                "current_stage": "problem_identification",
                "response_detail": "short",
                "idempotency_key": "http-in-flight",
            },
        )

    with ThreadPoolExecutor(max_workers=1) as executor:
        future = executor.submit(first_call)
        assert started.wait(timeout=2)
        revise = client.post(
            f"/api/v1/threads/{thread_id}/messages/{user_id}/revise",
            json={
                "content": "Should not land",
                "idempotency_key": "http-revise-busy",
            },
        )
        release.set()
        first = future.result(timeout=5)

    assert first.status_code == 200, first.text
    assert revise.status_code == 429
    assert [item["content"] for item in store.get_messages(thread_id)][0] == before[0]
    assert "Should not land" not in [
        item["content"] for item in store.get_messages(thread_id)
    ]
