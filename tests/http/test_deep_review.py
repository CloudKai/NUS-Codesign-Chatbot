"""HTTP Deep Review route: server-owned, ownership-isolated, concurrent-safe."""

from __future__ import annotations

import threading
import time
from datetime import datetime, timedelta, timezone

from fastapi.testclient import TestClient

from backend.api import create_app
from backend.application import CoachApplicationService
from backend.domain import DeepReviewJobStatus
from backend.rate_limit import CoachRateLimiter, reset_coach_rate_limiter_for_tests
from backend.specialists.review_orchestration import (
    COUNTER_SETTINGS_KEY,
    DEEP_REVIEW_ERROR_TIMEOUT,
    DEEP_REVIEW_JOB_KEY,
    DEEP_REVIEW_JOB_RUNNING,
    DEEP_REVIEW_TURN_MESSAGE,
)
from backend.student_journey import learning_review
from backend.student_store import StudentStore


def _coach_payload(thread_id: str, message: str, key: str) -> dict[str, str]:
    """Return one mock coaching JSON body."""
    return {
        "thread_id": thread_id,
        "student_message": message,
        "current_stage": "problem_identification",
        "response_detail": "short",
        "idempotency_key": key,
    }


def _wait_http_job(client: TestClient, thread_id: str, timeout: float = 5.0) -> dict:
    """Poll GET until the Deep Review job is terminal."""
    deadline = time.monotonic() + timeout
    last = None
    while time.monotonic() < deadline:
        response = client.get(f"/api/v1/threads/{thread_id}/deep-review")
        if response.status_code == 200:
            last = response.json()
            if last.get("status") in {
                DeepReviewJobStatus.COMPLETED.value,
                DeepReviewJobStatus.FAILED.value,
            }:
                return last
        time.sleep(0.05)
    raise AssertionError(f"Deep Review job did not finish: {last}")


def test_coach_turn_cannot_choose_specialist_review(tmp_path) -> None:
    store = StudentStore(tmp_path / "http-dr-hint.sqlite3")
    thread_id = store.create_thread(model_id="mock", support_mode="critical-thinking")
    client = TestClient(create_app(store))
    response = client.post(
        "/api/v1/coach/turn",
        json={
            **_coach_payload(thread_id, "I compared two constraints.", "hint-1"),
            "specialist": "review",
        },
    )
    assert response.status_code == 200
    body = response.json()
    assert body["assessment"]["guidance_questions"]
    assert body["assessment"].get("review_depth") != "deep"
    metadata = dict((store.get_thread(thread_id) or {}).get("metadata") or {})
    assert metadata.get("deep_review_snapshot") is None


def test_deep_review_body_rejects_privileged_fields(tmp_path) -> None:
    store = StudentStore(tmp_path / "http-dr-extra.sqlite3")
    thread_id = store.create_thread(model_id="mock", support_mode="critical-thinking")
    client = TestClient(create_app(store))
    response = client.post(
        f"/api/v1/threads/{thread_id}/deep-review",
        json={"specialist": "review", "current_stage": "reflection"},
    )
    assert response.status_code == 422


def test_ineligible_deep_review_returns_400(tmp_path) -> None:
    store = StudentStore(tmp_path / "http-dr-400.sqlite3")
    thread_id = store.create_thread(model_id="mock", support_mode="critical-thinking")
    client = TestClient(create_app(store))
    response = client.post(
        f"/api/v1/threads/{thread_id}/deep-review",
        json={"idempotency_key": "too-soon"},
    )
    assert response.status_code == 400
    assert "not available" in response.json()["detail"].lower()


def test_eligible_deep_review_endpoint_enqueues_server_owned_review(tmp_path) -> None:
    store = StudentStore(tmp_path / "http-dr-ok.sqlite3")
    thread_id = store.create_thread(model_id="mock", support_mode="critical-thinking")
    store.update_thread(thread_id, metadata={COUNTER_SETTINGS_KEY: 3})
    client = TestClient(create_app(store))
    started = time.monotonic()
    response = client.post(
        f"/api/v1/threads/{thread_id}/deep-review",
        json={"idempotency_key": "deep-ok"},
    )
    assert time.monotonic() - started < 1.0
    assert response.status_code == 200
    body = response.json()
    assert body["status"] in {
        DeepReviewJobStatus.QUEUED.value,
        DeepReviewJobStatus.RUNNING.value,
    }
    assert body["review_id"]
    finished = _wait_http_job(client, thread_id)
    assert finished["status"] == DeepReviewJobStatus.COMPLETED.value
    assert finished["review_id"] == body["review_id"]
    assert isinstance(finished.get("snapshot"), dict)
    metadata = dict((store.get_thread(thread_id) or {}).get("metadata") or {})
    assert int(metadata.get(COUNTER_SETTINGS_KEY, -1)) == 0
    snapshot = metadata.get("deep_review_snapshot")
    assert isinstance(snapshot, dict)
    assert snapshot["review_trigger"] == "explicit"
    assert snapshot.get("reviewed_stage_id") == "problem_identification"
    assert "You located the work in a concrete setting." in snapshot.get("strengths", [])
    assert (
        "Name who is affected and what success would look like."
        in snapshot.get("areas_to_develop", [])
    )
    journey = dict(metadata.get("learning_journey") or {})
    assert journey.get("current_stage") == "problem_identification"
    assert all(
        DEEP_REVIEW_TURN_MESSAGE not in str(item.get("content") or "")
        for item in store.get_messages(thread_id)
    )


def test_missing_notebook_deep_review_is_404(tmp_path) -> None:
    store = StudentStore(tmp_path / "http-dr-404.sqlite3")
    client = TestClient(create_app(store))
    response = client.post(
        "/api/v1/threads/does-not-exist/deep-review",
        json={},
    )
    assert response.status_code == 404


def test_deep_review_same_notebook_allows_overlapping_coach_turn(
    tmp_path, monkeypatch
) -> None:
    from backend import rate_limit as rate_limit_module

    reset_coach_rate_limiter_for_tests()
    limiter = CoachRateLimiter(
        max_active_per_notebook=1,
        max_active_per_user=2,
        requests_per_minute=20,
        max_concurrent_model_calls=20,
    )
    monkeypatch.setattr(rate_limit_module, "_LIMITER", limiter)
    store = StudentStore(tmp_path / "http-dr-busy.sqlite3")
    thread_id = store.create_thread(model_id="mock", support_mode="critical-thinking")
    store.update_thread(thread_id, metadata={COUNTER_SETTINGS_KEY: 3})
    client = TestClient(create_app(store))
    started = threading.Event()
    release = threading.Event()
    original = CoachApplicationService.execute_deep_review_job

    def slow_execute(self, job_thread_id, review_id):
        started.set()
        assert release.wait(timeout=2)
        return original(self, job_thread_id, review_id)

    monkeypatch.setattr(CoachApplicationService, "execute_deep_review_job", slow_execute)

    posted = client.post(
        f"/api/v1/threads/{thread_id}/deep-review",
        json={"idempotency_key": "busy-deep"},
    )
    assert posted.status_code == 200
    assert started.wait(timeout=2)
    coach = client.post(
        "/api/v1/coach/turn",
        json=_coach_payload(thread_id, "first overlapping send", "busy-1"),
    )
    reviewed_revision = posted.json()["reviewed_revision"]
    release.set()
    finished = _wait_http_job(client, thread_id)

    assert coach.status_code == 200
    assert finished["status"] == DeepReviewJobStatus.COMPLETED.value
    assert finished["reviewed_revision"] == reviewed_revision
    reset_coach_rate_limiter_for_tests()


def test_deep_review_post_returns_before_slow_worker(tmp_path, monkeypatch) -> None:
    store = StudentStore(tmp_path / "http-dr-slow.sqlite3")
    thread_id = store.create_thread(model_id="mock", support_mode="critical-thinking")
    store.update_thread(thread_id, metadata={COUNTER_SETTINGS_KEY: 3})
    client = TestClient(create_app(store))
    original = CoachApplicationService.execute_deep_review_job

    def slow_execute(self, job_thread_id, review_id):
        time.sleep(1.5)
        return original(self, job_thread_id, review_id)

    monkeypatch.setattr(CoachApplicationService, "execute_deep_review_job", slow_execute)
    started = time.monotonic()
    response = client.post(
        f"/api/v1/threads/{thread_id}/deep-review",
        json={"idempotency_key": "slow-deep"},
    )
    elapsed = time.monotonic() - started
    assert response.status_code == 200
    assert elapsed < 0.75
    assert response.json()["status"] in {
        DeepReviewJobStatus.QUEUED.value,
        DeepReviewJobStatus.RUNNING.value,
    }
    finished = _wait_http_job(client, thread_id, timeout=8.0)
    assert finished["status"] == DeepReviewJobStatus.COMPLETED.value


def test_duplicate_deep_review_post_reuses_inflight_job(tmp_path, monkeypatch) -> None:
    store = StudentStore(tmp_path / "http-dr-dup.sqlite3")
    thread_id = store.create_thread(model_id="mock", support_mode="critical-thinking")
    store.update_thread(thread_id, metadata={COUNTER_SETTINGS_KEY: 3})
    client = TestClient(create_app(store))
    started = threading.Event()
    release = threading.Event()
    calls = {"count": 0}
    original = CoachApplicationService.execute_deep_review_job

    def slow_execute(self, job_thread_id, review_id):
        calls["count"] += 1
        started.set()
        assert release.wait(timeout=2)
        return original(self, job_thread_id, review_id)

    monkeypatch.setattr(CoachApplicationService, "execute_deep_review_job", slow_execute)
    first = client.post(
        f"/api/v1/threads/{thread_id}/deep-review",
        json={"idempotency_key": "dup-1"},
    )
    assert started.wait(timeout=2)
    second = client.post(
        f"/api/v1/threads/{thread_id}/deep-review",
        json={"idempotency_key": "dup-2"},
    )
    release.set()
    assert first.status_code == 200
    assert second.status_code == 200
    assert first.json()["review_id"] == second.json()["review_id"]
    finished = _wait_http_job(client, thread_id)
    assert finished["status"] == DeepReviewJobStatus.COMPLETED.value
    assert calls["count"] == 1


def test_chat_during_review_does_not_change_reviewed_revision(
    tmp_path, monkeypatch
) -> None:
    store = StudentStore(tmp_path / "http-dr-rev.sqlite3")
    thread_id = store.create_thread(model_id="mock", support_mode="critical-thinking")
    store.update_thread(thread_id, metadata={COUNTER_SETTINGS_KEY: 3})
    client = TestClient(create_app(store))
    started = threading.Event()
    release = threading.Event()
    original = CoachApplicationService.execute_deep_review_job

    def slow_execute(self, job_thread_id, review_id):
        started.set()
        assert release.wait(timeout=2)
        return original(self, job_thread_id, review_id)

    monkeypatch.setattr(CoachApplicationService, "execute_deep_review_job", slow_execute)
    posted = client.post(
        f"/api/v1/threads/{thread_id}/deep-review",
        json={"idempotency_key": "rev-deep"},
    )
    assert started.wait(timeout=2)
    frozen = posted.json()["reviewed_revision"]
    coach = client.post(
        "/api/v1/coach/turn",
        json=_coach_payload(thread_id, "I compared two later constraints.", "rev-chat"),
    )
    release.set()
    finished = _wait_http_job(client, thread_id)
    assert coach.status_code == 200
    assert finished["reviewed_revision"] == frozen
    assert finished["snapshot"]["reviewed_through_revision"] == frozen


def test_stage_advance_during_review_is_not_reverted(tmp_path, monkeypatch) -> None:
    store = StudentStore(tmp_path / "http-dr-stage.sqlite3")
    thread_id = store.create_thread(model_id="mock", support_mode="critical-thinking")
    store.update_thread(thread_id, metadata={COUNTER_SETTINGS_KEY: 3})
    client = TestClient(create_app(store))
    started = threading.Event()
    release = threading.Event()
    original = CoachApplicationService.execute_deep_review_job

    def slow_execute(self, job_thread_id, review_id):
        started.set()
        assert release.wait(timeout=2)
        return original(self, job_thread_id, review_id)

    monkeypatch.setattr(CoachApplicationService, "execute_deep_review_job", slow_execute)
    posted = client.post(
        f"/api/v1/threads/{thread_id}/deep-review",
        json={"idempotency_key": "stage-deep"},
    )
    assert posted.status_code == 200
    assert started.wait(timeout=2)
    metadata = dict((store.get_thread(thread_id) or {}).get("metadata") or {})
    journey = dict(metadata.get("learning_journey") or {})
    journey["completed_stages"] = ["problem_identification"]
    metadata["learning_journey"] = journey
    store.update_thread(thread_id, metadata=metadata)
    store.select_learning_stage(thread_id, "concept_generation")
    release.set()
    finished = _wait_http_job(client, thread_id)
    assert finished["status"] == DeepReviewJobStatus.COMPLETED.value
    metadata = dict((store.get_thread(thread_id) or {}).get("metadata") or {})
    journey = dict(metadata.get("learning_journey") or {})
    assert journey.get("current_stage") == "concept_generation"
    snapshot = metadata.get("deep_review_snapshot")
    assert isinstance(snapshot, dict)
    assert snapshot.get("reviewed_stage_id") == "problem_identification"
    review = learning_review(
        store.get_messages(thread_id),
        journey,
        deep_review_snapshot=snapshot,
    )
    by_stage = {
        section["stage_id"]: section["items"]
        for section in review["strength_sections"]
    }
    deep_strength = "You located the work in a concrete setting."
    assert deep_strength in by_stage["problem_identification"]
    assert deep_strength not in by_stage["concept_generation"]


def test_stale_running_deep_review_is_failed_on_get(tmp_path) -> None:
    store = StudentStore(tmp_path / "http-dr-stale.sqlite3")
    thread_id = store.create_thread(model_id="mock", support_mode="critical-thinking")
    stale_started = (datetime.now(timezone.utc) - timedelta(minutes=10)).isoformat()
    store.update_thread(
        thread_id,
        metadata={
            COUNTER_SETTINGS_KEY: 3,
            DEEP_REVIEW_JOB_KEY: {
                "review_id": "stale-review",
                "status": DEEP_REVIEW_JOB_RUNNING,
                "reviewed_revision": 0,
                "stage_at_start": "problem_identification",
                "source_ids": [],
                "message_ids": [],
                "started_at": stale_started,
                "updated_at": stale_started,
                "error_code": None,
            },
        },
    )
    client = TestClient(create_app(store))
    response = client.get(f"/api/v1/threads/{thread_id}/deep-review")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == DeepReviewJobStatus.FAILED.value
    assert body["error_code"] == DEEP_REVIEW_ERROR_TIMEOUT
    assert int(
        dict((store.get_thread(thread_id) or {}).get("metadata") or {}).get(
            COUNTER_SETTINGS_KEY, -1
        )
    ) == 3


def test_another_user_cannot_read_or_invoke_deep_review(tmp_path) -> None:
    db = tmp_path / "http-dr-owner.sqlite3"
    owner_a = StudentStore(db, identifier="cognito:a")
    thread_id = owner_a.create_thread(model_id="mock", support_mode="critical-thinking")
    owner_a.update_thread(thread_id, metadata={COUNTER_SETTINGS_KEY: 3})
    owner_b = StudentStore(db, identifier="cognito:b")
    client_b = TestClient(create_app(owner_b))
    response = client_b.post(
        f"/api/v1/threads/{thread_id}/deep-review",
        json={"idempotency_key": "foreign"},
    )
    assert response.status_code == 404
    client_a = TestClient(create_app(owner_a))
    posted = client_a.post(
        f"/api/v1/threads/{thread_id}/deep-review",
        json={"idempotency_key": "owned"},
    )
    assert posted.status_code == 200
    foreign_get = client_b.get(f"/api/v1/threads/{thread_id}/deep-review")
    assert foreign_get.status_code == 404
    owned_get = client_a.get(f"/api/v1/threads/{thread_id}/deep-review")
    assert owned_get.status_code == 200


def test_coach_turn_idempotency_key_does_not_block_http_deep_review(tmp_path) -> None:
    store = StudentStore(tmp_path / "http-dr-poison.sqlite3")
    thread_id = store.create_thread(model_id="mock", support_mode="critical-thinking")
    client = TestClient(create_app(store))
    poisoned = client.post(
        "/api/v1/coach/turn",
        json=_coach_payload(thread_id, DEEP_REVIEW_TURN_MESSAGE, "shared-deep"),
    )
    assert poisoned.status_code == 200
    store.update_thread(thread_id, metadata={COUNTER_SETTINGS_KEY: 3})
    response = client.post(
        f"/api/v1/threads/{thread_id}/deep-review",
        json={"idempotency_key": "shared-deep"},
    )
    assert response.status_code == 200
    finished = _wait_http_job(client, thread_id)
    assert finished["status"] == DeepReviewJobStatus.COMPLETED.value
    metadata = dict((store.get_thread(thread_id) or {}).get("metadata") or {})
    assert metadata.get("deep_review_snapshot") is not None
    assert int(metadata.get(COUNTER_SETTINGS_KEY) or 0) == 0


def test_mock_review_phrasing_does_not_reset_deep_review_counter(tmp_path) -> None:
    store = StudentStore(tmp_path / "http-dr-mock-review.sqlite3")
    thread_id = store.create_thread(model_id="mock", support_mode="critical-thinking")
    store.update_thread(thread_id, metadata={COUNTER_SETTINGS_KEY: 3})
    client = TestClient(create_app(store))
    response = client.post(
        "/api/v1/coach/turn",
        json=_coach_payload(thread_id, "Can you review my progress?", "review-phrase"),
    )
    assert response.status_code == 200
    body = response.json()
    assert body["assessment"].get("review_depth") != "deep"
    metadata = dict((store.get_thread(thread_id) or {}).get("metadata") or {})
    assert metadata.get("deep_review_snapshot") is None
    assert int(metadata.get(COUNTER_SETTINGS_KEY) or 0) == 3
