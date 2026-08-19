"""Server-owned explicit Deep Review application path. No AWS."""

from __future__ import annotations

import json
import threading
import time
from datetime import datetime, timedelta, timezone
from typing import Any

import pytest

from backend.agentcore_provider import AgentCoreCoachProvider
from backend.application import CoachApplicationService, _coach_request_fingerprint
from backend.settings import settings
from backend.domain import (
    CoachRequest,
    DeepReviewJobStatus,
    EducationalAssessment,
    FacioneDimensionScores,
    StageDecision,
)
from backend.learning_service import LearningProgressService
from backend.repositories import (
    SQLiteNotebookRepository,
    SQLitePhaseTransitionRepository,
)
from backend.source_library import add_text_source
from backend.sources.chunk_cache import reset_student_source_chunk_cache
from backend.specialists.review_orchestration import (
    COUNTER_SETTINGS_KEY,
    DEEP_REVIEW_JOB_KEY,
    DEEP_REVIEW_SNAPSHOT_KEY,
    DEEP_REVIEW_TURN_MESSAGE,
    explicit_deep_review_available,
    parse_deep_review_job,
)
from backend.student_journey import learning_review
from backend.student_store import StudentStore
from backend.workflow import CoachWorkflow
from counting_file_storage import CountingFileStorage, install_counting_storage
from fake_agentcore_runtime import FakeAgentCoreRuntime

_RUNTIME_ARN = (
    "arn:aws:bedrock-agentcore:us-west-2:123456789012:runtime/test-harness"
)


@pytest.fixture(autouse=True)
def _pin_deep_review_sonnet(monkeypatch: pytest.MonkeyPatch) -> None:
    """Keep snapshot model_id independent of operator .env role leftovers."""
    monkeypatch.setattr(settings, "review_deep_model_provider", "bedrock")
    monkeypatch.setattr(
        settings, "review_deep_model_id", "global.anthropic.claude-sonnet-4-6"
    )


def _assessment() -> EducationalAssessment:
    """Return one valid coaching assessment."""
    return EducationalAssessment(
        current_stage="problem_identification",
        contribution_summary="The student compared two design constraints.",
        stage_assessment="The contribution is usable but can be developed further.",
        critical_understanding_level="Developing",
        confidence=0.7,
        recommendation=StageDecision.STAY,
        recommendation_rationale="More evidence is still needed.",
        guidance_questions=["What trade-off still needs evidence?"],
        learning_summary="The student is developing the problem.",
        citations=[],
        facione_scores=FacioneDimensionScores(),
    )


def _coaching_payload() -> dict[str, Any]:
    """Return one lightweight fast-chat coaching body."""
    return {
        "mode": "coaching",
        "response_text": "What assumption is carrying this preference?",
        "recommendation": "stay",
        "recommendation_rationale": "More evidence is still needed.",
        "citations": [],
        "needs_source_retrieval": False,
    }


def _deep_payload(
    *,
    synthesis: str = "Formative Deep Review A.",
    strengths: list[str] | None = None,
    areas_to_develop: list[str] | None = None,
    current_stage: str = "problem_identification",
) -> dict[str, Any]:
    """Return one explicit Deep Review body that stays on the current stage."""
    return {
        "response_text": synthesis,
        "strengths": list(strengths or ["Named a real constraint"]),
        "areas_to_develop": list(areas_to_develop or ["Name who is affected"]),
        "synthesis": synthesis,
        "current_stage": current_stage,
        "recommendation": "advance",
        "rationale_summary": "Readiness information only.",
        "working_conclusion": "Option B is the working concept.",
        "facione_profile": {
            "interpretation": 2,
            "analysis": 2,
            "inference": 2,
            "evaluation": 2,
            "explanation": 2,
            "self_regulation": 2,
        },
    }


def _provider(client: FakeAgentCoreRuntime) -> AgentCoreCoachProvider:
    """Build the AgentCore adapter around a fake runtime."""
    return AgentCoreCoachProvider(
        _RUNTIME_ARN,
        region="us-west-2",
        qualifier="DEFAULT",
        timeout_seconds=110.0,
        max_retries=0,
        client=client,
    )


def _service(store: StudentStore, client: FakeAgentCoreRuntime) -> CoachApplicationService:
    """Build the application path with the AgentCore adapter injected."""
    notebooks = SQLiteNotebookRepository(store)
    transitions = SQLitePhaseTransitionRepository(store)
    return CoachApplicationService(
        store,
        notebooks,
        CoachWorkflow(_provider(client), transitions),
        LearningProgressService(store, notebooks, transitions),
    )


def _decoded(call: dict[str, Any]) -> dict[str, Any]:
    """Decode one recorded InvokeAgentRuntime payload."""
    raw = call["payload"]
    if isinstance(raw, (bytes, bytearray)):
        return json.loads(bytes(raw).decode("utf-8"))
    return json.loads(str(raw))


def _phases(client: FakeAgentCoreRuntime) -> list[str]:
    """Return payload phases in invoke order."""
    return [str(_decoded(call).get("phase") or "") for call in client.calls]


def _counter(store: StudentStore, thread_id: str) -> int:
    """Return the persisted Deep Review counter."""
    metadata = dict((store.get_thread(thread_id) or {}).get("metadata") or {})
    try:
        return int(metadata.get(COUNTER_SETTINGS_KEY) or 0)
    except (TypeError, ValueError):
        return 0


def _snapshot(store: StudentStore, thread_id: str) -> dict[str, Any] | None:
    """Return the durable Deep Review snapshot when present."""
    metadata = dict((store.get_thread(thread_id) or {}).get("metadata") or {})
    raw = metadata.get(DEEP_REVIEW_SNAPSHOT_KEY)
    return raw if isinstance(raw, dict) else None


def _job_blob(store: StudentStore, thread_id: str) -> dict[str, Any] | None:
    """Return the persisted Deep Review job blob when present."""
    metadata = dict((store.get_thread(thread_id) or {}).get("metadata") or {})
    return parse_deep_review_job(metadata.get(DEEP_REVIEW_JOB_KEY))


def _current_stage(store: StudentStore, thread_id: str) -> str:
    """Return the live Thinking Path stage from notebook metadata."""
    journey = dict(
        ((store.get_thread(thread_id) or {}).get("metadata") or {}).get(
            "learning_journey"
        )
        or {}
    )
    return str(journey.get("current_stage") or "")


def _assistant_assessments(store: StudentStore, thread_id: str) -> list[dict[str, Any]]:
    """Return assistant assessment payloads in transcript order."""
    found: list[dict[str, Any]] = []
    for item in store.get_messages(thread_id):
        if item.get("role") != "assistant":
            continue
        assessment = (item.get("metadata") or {}).get("assessment")
        if isinstance(assessment, dict):
            found.append(dict(assessment))
    return found


def _add_incremental_assessment(
    store: StudentStore,
    thread_id: str,
    *,
    stage: str,
    strengths: list[str],
    improvements: list[str] | None = None,
) -> None:
    """Persist one message-derived Review-tab assessment without Deep Review."""
    store.add_message(
        thread_id,
        "assistant",
        "Incremental coach reply.",
        metadata={
            "assessment": {
                "current_stage": stage,
                "recommendation": "stay",
                "review_strengths": list(strengths),
                "review_improvements": list(improvements or []),
                "learning_summary": "Incremental summary.",
                "stage_assessment": "Incremental note.",
                "contribution_summary": "Draft.",
            }
        },
    )


def _review_items(
    store: StudentStore, thread_id: str, key: str, stage_id: str
) -> list[str]:
    """Return one stage's Review-tab items from persisted messages + snapshot."""
    thread = store.get_thread(thread_id) or {}
    metadata = dict(thread.get("metadata") or {})
    review = learning_review(
        store.get_messages(thread_id),
        metadata.get("learning_journey") or {},
        deep_review_snapshot=_snapshot(store, thread_id),
    )
    return next(
        section["items"]
        for section in review[key]
        if section["stage_id"] == stage_id
    )


def _unlock(store: StudentStore, thread_id: str) -> None:
    """Grant one explicit Deep Review entitlement without stacking credits."""
    store.update_thread(thread_id, metadata={COUNTER_SETTINGS_KEY: 3})


def _coach(service: CoachApplicationService, thread_id: str, key: str, message: str) -> None:
    """Submit one normal coaching turn."""
    service.submit(
        CoachRequest(
            thread_id=thread_id,
            student_message=message,
            current_stage="problem_identification",
            response_detail="short",
            idempotency_key=key,
        )
    )


def _wait_job(
    service: CoachApplicationService, thread_id: str, timeout: float = 5.0
):
    """Poll until the background Deep Review job is terminal."""
    deadline = time.monotonic() + timeout
    last = None
    while time.monotonic() < deadline:
        last = service.get_deep_review_job(thread_id)
        if last is not None and last.status in {
            DeepReviewJobStatus.COMPLETED,
            DeepReviewJobStatus.FAILED,
        }:
            return last
        time.sleep(0.05)
    raise AssertionError(f"Deep Review job did not finish: {last}")


def _assert_no_review_transcript(store: StudentStore, thread_id: str) -> None:
    """Background Deep Review must not insert Start Deep Review transcript rows."""
    assert all(
        DEEP_REVIEW_TURN_MESSAGE not in str(item.get("content") or "")
        for item in store.get_messages(thread_id)
    )


def test_eligibility_requires_persisted_interval() -> None:
    assert explicit_deep_review_available(
        coaching_turns_since_deep_review=2, interval=3
    ) is False
    assert explicit_deep_review_available(
        coaching_turns_since_deep_review=3, interval=3
    ) is True
    assert explicit_deep_review_available(
        coaching_turns_since_deep_review=6, interval=3
    ) is True


def test_locked_deep_review_is_rejected_without_sonnet(tmp_path) -> None:
    store = StudentStore(tmp_path / "dr-locked.sqlite3")
    thread_id = store.create_thread(model_id="mock", support_mode="critical-thinking")
    client = FakeAgentCoreRuntime(payload=_coaching_payload(), deep_payload=_deep_payload())
    service = _service(store, client)
    with pytest.raises(ValueError, match="not available"):
        service.enqueue_deep_review(thread_id, idempotency_key="locked")
    assert client.calls == []
    assert _counter(store, thread_id) == 0


def test_eligible_deep_review_is_one_sonnet_call_and_resets_counter(tmp_path) -> None:
    store = StudentStore(tmp_path / "dr-ok.sqlite3")
    thread_id = store.create_thread(model_id="mock", support_mode="critical-thinking")
    _unlock(store, thread_id)
    client = FakeAgentCoreRuntime(payload=_coaching_payload(), deep_payload=_deep_payload())
    service = _service(store, client)
    job = service.enqueue_deep_review(thread_id, idempotency_key="deep-1")
    assert job.status in {DeepReviewJobStatus.QUEUED, DeepReviewJobStatus.RUNNING}
    finished = _wait_job(service, thread_id)
    assert finished.status is DeepReviewJobStatus.COMPLETED
    assert _phases(client) == ["review"]
    assert _counter(store, thread_id) == 0
    snapshot = _snapshot(store, thread_id)
    assert snapshot is not None
    assert snapshot["review_depth"] == "deep"
    assert snapshot["review_trigger"] == "explicit"
    assert snapshot["model_id"] == "global.anthropic.claude-sonnet-4-6"
    assert snapshot["reviewed_stage_id"] == "problem_identification"
    assert snapshot["strengths"] == ["Named a real constraint"]
    assert snapshot["areas_to_develop"] == ["Name who is affected"]
    assert "Formative Deep Review A" in snapshot["synthesis"]
    thread = store.get_thread(thread_id) or {}
    journey = dict((thread.get("metadata") or {}).get("learning_journey") or {})
    assert journey.get("current_stage") == "problem_identification"
    _assert_no_review_transcript(store, thread_id)


def test_failed_deep_review_leaves_counter_and_snapshot_unchanged(tmp_path) -> None:
    store = StudentStore(tmp_path / "dr-fail.sqlite3")
    thread_id = store.create_thread(model_id="mock", support_mode="critical-thinking")
    _unlock(store, thread_id)
    client = FakeAgentCoreRuntime(deep_error=TimeoutError("deep-timeout"))
    service = _service(store, client)
    job = service.enqueue_deep_review(thread_id, idempotency_key="deep-fail")
    assert job.status in {DeepReviewJobStatus.QUEUED, DeepReviewJobStatus.RUNNING}
    finished = _wait_job(service, thread_id)
    assert finished.status is DeepReviewJobStatus.FAILED
    assert _counter(store, thread_id) == 3
    assert _snapshot(store, thread_id) is None
    assert all(item["role"] != "assistant" for item in store.get_messages(thread_id))
    _assert_no_review_transcript(store, thread_id)


def test_failed_deep_review_preserves_previous_snapshot_feedback(tmp_path) -> None:
    store = StudentStore(tmp_path / "dr-fail-keep.sqlite3")
    thread_id = store.create_thread(model_id="mock", support_mode="critical-thinking")
    _unlock(store, thread_id)
    first = _service(
        store,
        FakeAgentCoreRuntime(
            deep_payload=_deep_payload(strengths=["Previous deep strength"])
        ),
    )
    first.enqueue_deep_review(thread_id, idempotency_key="deep-keep")
    assert _wait_job(first, thread_id).status is DeepReviewJobStatus.COMPLETED
    previous = _snapshot(store, thread_id)
    assert previous is not None
    assert previous["strengths"] == ["Previous deep strength"]
    _unlock(store, thread_id)
    failing = _service(store, FakeAgentCoreRuntime(deep_error=TimeoutError("deep-timeout")))
    failing.enqueue_deep_review(thread_id, idempotency_key="deep-fail-keep")
    assert _wait_job(failing, thread_id).status is DeepReviewJobStatus.FAILED
    assert _snapshot(store, thread_id) == previous
    assert "Previous deep strength" in _review_items(
        store, thread_id, "strength_sections", "problem_identification"
    )


def test_completed_deep_review_cannot_start_another_until_eligible(tmp_path) -> None:
    store = StudentStore(tmp_path / "dr-idem.sqlite3")
    thread_id = store.create_thread(model_id="mock", support_mode="critical-thinking")
    _unlock(store, thread_id)
    client = FakeAgentCoreRuntime(deep_payload=_deep_payload())
    service = _service(store, client)
    service.enqueue_deep_review(thread_id, idempotency_key="same-deep")
    assert _wait_job(service, thread_id).status is DeepReviewJobStatus.COMPLETED
    replay_client = FakeAgentCoreRuntime(deep_payload=_deep_payload(synthesis="Must not run."))
    replay_service = _service(store, replay_client)
    with pytest.raises(ValueError, match="not available"):
        replay_service.enqueue_deep_review(thread_id, idempotency_key="same-deep")
    assert replay_client.calls == []
    assert _counter(store, thread_id) == 0


def test_normal_coaching_does_not_overwrite_snapshot(tmp_path) -> None:
    store = StudentStore(tmp_path / "dr-snap.sqlite3")
    thread_id = store.create_thread(model_id="mock", support_mode="critical-thinking")
    _unlock(store, thread_id)
    deep_client = FakeAgentCoreRuntime(deep_payload=_deep_payload())
    deep_service = _service(store, deep_client)
    deep_service.enqueue_deep_review(thread_id, idempotency_key="deep-a")
    assert _wait_job(deep_service, thread_id).status is DeepReviewJobStatus.COMPLETED
    first = _snapshot(store, thread_id)
    assert first is not None
    coach_client = FakeAgentCoreRuntime(payload=_coaching_payload())
    _coach(
        _service(store, coach_client),
        thread_id,
        "coach-after",
        "I still prefer option B because maintenance is manageable.",
    )
    assert _phases(coach_client) == ["fast_chat"]
    after = _snapshot(store, thread_id)
    assert after == first
    review = learning_review(
        store.get_messages(thread_id),
        (store.get_thread(thread_id) or {}).get("metadata") or {},
        deep_review_snapshot=after,
    )
    assert "Formative Deep Review A" in str(review.get("summary") or "")
    assert "Named a real constraint" in _review_items(
        store, thread_id, "strength_sections", "problem_identification"
    )
    assert "Name who is affected" in _review_items(
        store, thread_id, "improvement_sections", "problem_identification"
    )


def test_next_successful_deep_review_replaces_snapshot(tmp_path) -> None:
    store = StudentStore(tmp_path / "dr-replace.sqlite3")
    thread_id = store.create_thread(model_id="mock", support_mode="critical-thinking")
    _unlock(store, thread_id)
    first_service = _service(
        store,
        FakeAgentCoreRuntime(deep_payload=_deep_payload(strengths=["Old deep strength"])),
    )
    first_service.enqueue_deep_review(thread_id, idempotency_key="deep-a")
    assert _wait_job(first_service, thread_id).status is DeepReviewJobStatus.COMPLETED
    _unlock(store, thread_id)
    second_service = _service(
        store,
        FakeAgentCoreRuntime(
            deep_payload=_deep_payload(
                synthesis="Formative Deep Review C.",
                strengths=["New deep strength"],
            )
        ),
    )
    second_service.enqueue_deep_review(thread_id, idempotency_key="deep-c")
    assert _wait_job(second_service, thread_id).status is DeepReviewJobStatus.COMPLETED
    snapshot = _snapshot(store, thread_id)
    assert snapshot is not None
    assert "Deep Review C" in snapshot["synthesis"]
    assert "Deep Review A" not in snapshot["synthesis"]
    items = _review_items(
        store, thread_id, "strength_sections", "problem_identification"
    )
    assert "New deep strength" in items
    assert "Old deep strength" not in items


def test_submit_cannot_select_review_specialist(tmp_path) -> None:
    store = StudentStore(tmp_path / "dr-hint.sqlite3")
    thread_id = store.create_thread(model_id="mock", support_mode="critical-thinking")
    client = FakeAgentCoreRuntime(payload=_coaching_payload(), deep_payload=_deep_payload())
    _service(store, client).submit(
        CoachRequest(
            thread_id=thread_id,
            student_message="I compared two constraints for Holland Road.",
            current_stage="problem_identification",
            response_detail="short",
            specialist="review",
            idempotency_key="hint-review",
        )
    )
    assert _phases(client) == ["fast_chat"]
    assert _snapshot(store, thread_id) is None
    assert _counter(store, thread_id) == 1


def test_deep_review_fingerprint_differs_from_coach_turn() -> None:
    request = CoachRequest(
        thread_id="thread-demo",
        student_message=DEEP_REVIEW_TURN_MESSAGE,
        current_stage="problem_identification",
        response_detail="short",
        idempotency_key="shared",
    )
    coach = _coach_request_fingerprint(request)
    same_surface = _coach_request_fingerprint(request, surface="coach_turn")
    deep = _coach_request_fingerprint(request, surface="deep_review")
    assert coach == same_surface
    assert deep != coach


def test_snapshot_reviewed_stage_survives_later_stage_change(tmp_path) -> None:
    store = StudentStore(tmp_path / "dr-stage.sqlite3")
    thread_id = store.create_thread(model_id="mock", support_mode="critical-thinking")
    _unlock(store, thread_id)
    client = FakeAgentCoreRuntime(deep_payload=_deep_payload(strengths=["Frozen deep strength"]))
    service = _service(store, client)
    job = service.enqueue_deep_review(thread_id, idempotency_key="deep-frozen-stage")
    assert job.status in {DeepReviewJobStatus.QUEUED, DeepReviewJobStatus.RUNNING}
    store.select_learning_stage(thread_id, "concept_generation")
    finished = _wait_job(service, thread_id)
    assert finished.status is DeepReviewJobStatus.COMPLETED
    snapshot = _snapshot(store, thread_id)
    assert snapshot is not None
    assert snapshot["reviewed_stage_id"] == "problem_identification"
    journey = dict(
        ((store.get_thread(thread_id) or {}).get("metadata") or {}).get(
            "learning_journey"
        )
        or {}
    )
    assert journey.get("current_stage") == "concept_generation"
    assert "Frozen deep strength" in _review_items(
        store, thread_id, "strength_sections", "problem_identification"
    )
    assert "Frozen deep strength" not in _review_items(
        store, thread_id, "strength_sections", "concept_generation"
    )


def test_coach_turn_idempotency_key_does_not_block_deep_review_job(tmp_path) -> None:
    store = StudentStore(tmp_path / "dr-poison.sqlite3")
    thread_id = store.create_thread(model_id="mock", support_mode="critical-thinking")
    client = FakeAgentCoreRuntime(payload=_coaching_payload(), deep_payload=_deep_payload())
    service = _service(store, client)
    _coach(service, thread_id, "shared-key", DEEP_REVIEW_TURN_MESSAGE)
    assert _phases(client) == ["fast_chat"]
    _unlock(store, thread_id)
    job = service.enqueue_deep_review(thread_id, idempotency_key="shared-key")
    assert job.status in {DeepReviewJobStatus.QUEUED, DeepReviewJobStatus.RUNNING}
    finished = _wait_job(service, thread_id)
    assert finished.status is DeepReviewJobStatus.COMPLETED
    assert "review" in _phases(client)
    assert _snapshot(store, thread_id) is not None
    assert _counter(store, thread_id) == 0


def test_deep_review_selected_source_uses_chunk_artifact(
    tmp_path, monkeypatch
) -> None:
    """Eligible Deep Review hydrates selected sources like Fast Chat (C<=1, E=0)."""
    reset_student_source_chunk_cache()
    storage = CountingFileStorage()
    install_counting_storage(monkeypatch, storage)
    store = StudentStore(tmp_path / "dr-chunks.sqlite3")
    thread_id = store.create_thread(model_id="mock", support_mode="critical-thinking")
    add_text_source(
        store,
        thread_id,
        "Lecture notes",
        "Lecture notes on accessibility explain longer crossing times.",
    )
    _unlock(store, thread_id)
    client = FakeAgentCoreRuntime(
        payload=_coaching_payload(),
        deep_payload=_deep_payload(),
    )
    service = _service(store, client)
    storage.reset_counts()
    job = service.enqueue_deep_review(thread_id, idempotency_key="deep-chunks")
    assert job.status in {DeepReviewJobStatus.QUEUED, DeepReviewJobStatus.RUNNING}
    finished = _wait_job(service, thread_id)
    assert finished.status is DeepReviewJobStatus.COMPLETED
    assert _phases(client) == ["review"]
    snapshot = _snapshot(store, thread_id)
    assert snapshot is not None
    assert snapshot["review_depth"] == "deep"
    assert snapshot["review_trigger"] == "explicit"
    counts = storage.counts()
    assert counts.extracted_gets == 0
    assert counts.chunks_gets <= 1
    assert _counter(store, thread_id) == 0
    reset_student_source_chunk_cache()


def test_later_deep_review_on_new_stage_replaces_prior_snapshot_contribution(
    tmp_path,
) -> None:
    """Review A @ stage 1 then Review B @ stage 2 keeps only snapshot B."""
    store = StudentStore(tmp_path / "dr-cross-stage.sqlite3")
    thread_id = store.create_thread(model_id="mock", support_mode="critical-thinking")
    _add_incremental_assessment(
        store,
        thread_id,
        stage="problem_identification",
        strengths=["Problem incremental strength"],
    )
    _unlock(store, thread_id)
    review_a = _service(
        store,
        FakeAgentCoreRuntime(
            deep_payload=_deep_payload(
                synthesis="Formative Deep Review A.",
                strengths=["Problem deep strength"],
                areas_to_develop=["Problem deep area"],
            )
        ),
    )
    review_a.enqueue_deep_review(thread_id, idempotency_key="deep-a")
    assert _wait_job(review_a, thread_id).status is DeepReviewJobStatus.COMPLETED
    snapshot_a = _snapshot(store, thread_id)
    assert snapshot_a is not None
    assert snapshot_a["reviewed_stage_id"] == "problem_identification"
    assert "Problem deep strength" in _review_items(
        store, thread_id, "strength_sections", "problem_identification"
    )
    assert "Problem deep area" in _review_items(
        store, thread_id, "improvement_sections", "problem_identification"
    )

    store.select_learning_stage(thread_id, "concept_generation")
    _add_incremental_assessment(
        store,
        thread_id,
        stage="concept_generation",
        strengths=["Concept incremental strength"],
    )
    assessments_before_b = _assistant_assessments(store, thread_id)
    message_ids_before_b = [
        str(item.get("id") or "") for item in store.get_messages(thread_id)
    ]
    _unlock(store, thread_id)
    review_b = _service(
        store,
        FakeAgentCoreRuntime(
            deep_payload=_deep_payload(
                synthesis="Formative Deep Review B.",
                strengths=["Concept deep strength"],
                areas_to_develop=["Concept deep area"],
                current_stage="concept_generation",
            )
        ),
    )
    review_b.enqueue_deep_review(thread_id, idempotency_key="deep-b")
    assert _wait_job(review_b, thread_id).status is DeepReviewJobStatus.COMPLETED

    snapshot = _snapshot(store, thread_id)
    assert snapshot is not None
    assert snapshot["reviewed_stage_id"] == "concept_generation"
    assert "Deep Review B" in str(snapshot.get("synthesis") or "")
    assert "Deep Review A" not in str(snapshot.get("synthesis") or "")
    metadata = dict((store.get_thread(thread_id) or {}).get("metadata") or {})
    assert isinstance(metadata.get(DEEP_REVIEW_SNAPSHOT_KEY), dict)
    assert _current_stage(store, thread_id) == "concept_generation"

    problem_strengths = _review_items(
        store, thread_id, "strength_sections", "problem_identification"
    )
    problem_areas = _review_items(
        store, thread_id, "improvement_sections", "problem_identification"
    )
    concept_strengths = _review_items(
        store, thread_id, "strength_sections", "concept_generation"
    )
    concept_areas = _review_items(
        store, thread_id, "improvement_sections", "concept_generation"
    )
    assert "Problem deep strength" not in problem_strengths
    assert "Problem deep area" not in problem_areas
    assert "Problem incremental strength" in problem_strengths
    assert "Concept deep strength" in concept_strengths
    assert "Concept deep area" in concept_areas
    assert "Concept incremental strength" in concept_strengths
    assert _assistant_assessments(store, thread_id) == assessments_before_b
    assert [
        str(item.get("id") or "") for item in store.get_messages(thread_id)
    ] == message_ids_before_b
    _assert_no_review_transcript(store, thread_id)


def test_stale_worker_cannot_overwrite_later_completed_deep_review(
    tmp_path, monkeypatch
) -> None:
    """A late worker A completion must not replace successful Review B."""
    monkeypatch.setattr(settings, "deep_review_max_concurrent", 8)
    store = StudentStore(tmp_path / "dr-stale-worker.sqlite3")
    thread_id = store.create_thread(model_id="mock", support_mode="critical-thinking")
    _unlock(store, thread_id)
    original_complete = store.complete_deep_review_job
    first_id: dict[str, str | None] = {"review_id": None}
    attempted_a: dict[str, Any] = {}
    started = threading.Event()
    release = threading.Event()
    stale_complete_finished = threading.Event()

    def gated_complete(
        target_thread_id: str, *, review_id: str, snapshot: dict[str, Any]
    ) -> None:
        if first_id["review_id"] is None:
            first_id["review_id"] = review_id
            attempted_a["snapshot"] = dict(snapshot)
            started.set()
            assert release.wait(timeout=8.0), "stale worker A was not released"
            try:
                return original_complete(
                    target_thread_id, review_id=review_id, snapshot=snapshot
                )
            finally:
                stale_complete_finished.set()
        return original_complete(
            target_thread_id, review_id=review_id, snapshot=snapshot
        )

    store.complete_deep_review_job = gated_complete  # type: ignore[method-assign]
    try:
        review_a = _service(
            store,
            FakeAgentCoreRuntime(
                deep_payload=_deep_payload(
                    synthesis="Formative Deep Review A.",
                    strengths=["Review A strength"],
                    areas_to_develop=["Review A area"],
                )
            ),
        )
        job_a = review_a.enqueue_deep_review(thread_id, idempotency_key="deep-a")
        assert started.wait(timeout=8.0), "worker A never reached completion"
        review_a_id = str(first_id["review_id"] or "")
        assert review_a_id
        assert job_a.review_id == review_a_id
        assert "Review A strength" in list(
            (attempted_a.get("snapshot") or {}).get("strengths") or []
        )

        stale_started = (datetime.now(timezone.utc) - timedelta(minutes=10)).isoformat()
        job_blob = dict(_job_blob(store, thread_id) or {})
        assert job_blob.get("review_id") == review_a_id
        job_blob["started_at"] = stale_started
        job_blob["updated_at"] = stale_started
        store.update_thread(thread_id, metadata={DEEP_REVIEW_JOB_KEY: job_blob})
        failed = review_a.get_deep_review_job(thread_id)
        assert failed is not None
        assert failed.review_id == review_a_id
        assert failed.status is DeepReviewJobStatus.FAILED
        assert _snapshot(store, thread_id) is None
        assert _counter(store, thread_id) == 3

        _unlock(store, thread_id)
        review_b = _service(
            store,
            FakeAgentCoreRuntime(
                deep_payload=_deep_payload(
                    synthesis="Formative Deep Review B.",
                    strengths=["Review B strength"],
                    areas_to_develop=["Review B area"],
                )
            ),
        )
        job_b = review_b.enqueue_deep_review(thread_id, idempotency_key="deep-b")
        assert job_b.review_id != review_a_id
        finished_b = _wait_job(review_b, thread_id, timeout=8.0)
        assert finished_b.status is DeepReviewJobStatus.COMPLETED
        assert finished_b.review_id == job_b.review_id
        snapshot_b = _snapshot(store, thread_id)
        assert snapshot_b is not None
        assert snapshot_b["reviewed_stage_id"] == "problem_identification"
        assert "Review B strength" in list(snapshot_b.get("strengths") or [])
        assert "Review A strength" not in list(snapshot_b.get("strengths") or [])
        stage_before_stale_complete = _current_stage(store, thread_id)
        counter_after_b = _counter(store, thread_id)
        assert counter_after_b == 0

        release.set()
        assert stale_complete_finished.wait(
            timeout=8.0
        ), "stale worker A never attempted completion"
        store.complete_deep_review_job = original_complete  # type: ignore[method-assign]
        original_complete(
            thread_id,
            review_id=review_a_id,
            snapshot=dict(attempted_a["snapshot"]),
        )

        job = _job_blob(store, thread_id)
        snapshot = _snapshot(store, thread_id)
        assert job is not None
        assert job.get("review_id") == job_b.review_id
        assert job.get("status") == DeepReviewJobStatus.COMPLETED.value
        assert snapshot is not None
        assert snapshot["reviewed_stage_id"] == "problem_identification"
        assert "Review B strength" in list(snapshot.get("strengths") or [])
        assert "Review A strength" not in list(snapshot.get("strengths") or [])
        assert "Review A area" not in list(snapshot.get("areas_to_develop") or [])
        assert _counter(store, thread_id) == 0
        assert _current_stage(store, thread_id) == stage_before_stale_complete
        _assert_no_review_transcript(store, thread_id)
    finally:
        release.set()
        store.complete_deep_review_job = original_complete  # type: ignore[method-assign]
        stale_complete_finished.wait(timeout=8.0)
