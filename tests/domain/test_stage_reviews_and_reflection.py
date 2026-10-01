"""Stage-completion Journey reviews, Reflection DONE, and Deep Review unlock."""

from __future__ import annotations

from pathlib import Path

import pytest

from backend.application import CoachApplicationService
from backend.coaching.stage_review_jobs import (
    reset_stage_review_jobs_for_tests,
    submit_stage_review_job,
)
from backend.domain import CoachRequest
from backend.learning.journey import (
    complete_and_advance,
    default_journey,
    journey_progress,
    mark_stage_completed,
    set_current_stage,
)
from backend.learning.stages import THINKING_STAGES
from backend.learning_service import LearningProgressService
from backend.mock_provider import DeterministicCoachProvider
from backend.repositories import SQLiteNotebookRepository, SQLitePhaseTransitionRepository
from backend.specialists.review_orchestration import (
    JOURNEY_STAGE_REVIEWS_KEY,
    STAGE_REVIEW_COMPLETE,
    explicit_deep_review_available,
    newly_completed_stage_ids,
    parse_journey_stage_reviews,
    public_journey_stage_reviews,
    stage_review_should_enqueue,
)
from backend.student_store import StudentStore
from backend.workflow import CoachWorkflow


@pytest.fixture(autouse=True)
def _reset_stage_review_pool() -> None:
    reset_stage_review_jobs_for_tests()
    yield
    reset_stage_review_jobs_for_tests()


def _services(store: StudentStore) -> CoachApplicationService:
    notebooks = SQLiteNotebookRepository(store)
    transitions = SQLitePhaseTransitionRepository(store)
    learning = LearningProgressService(store, notebooks, transitions)
    workflow = CoachWorkflow(DeterministicCoachProvider(), transitions)
    coach = CoachApplicationService(
        store,
        notebooks,
        workflow,
        learning,
        auto_advance_stages=False,
    )

    def _enqueue(thread_id: str, stage_id: str) -> None:
        submit_stage_review_job(coach, thread_id, stage_id)

    learning.set_stage_review_enqueue(_enqueue)
    return coach


def test_mark_stage_completed_allows_reflection_in_place() -> None:
    journey = default_journey()
    for stage in THINKING_STAGES[:-1]:
        journey = mark_stage_completed(journey, stage.id)
        journey = set_current_stage(
            journey, THINKING_STAGES[THINKING_STAGES.index(stage) + 1].id
        )
    journey = mark_stage_completed(journey, "reflection")
    assert journey["completed_stages"][-1] == "reflection"
    assert journey["current_stage"] == "reflection"
    assert journey_progress(journey) == 100


def test_revisit_does_not_shrink_completed_stages() -> None:
    journey = default_journey()
    journey = complete_and_advance(journey, note="PI done")
    journey = complete_and_advance(journey, note="CG done")
    completed = list(journey["completed_stages"])
    journey = set_current_stage(journey, "problem_identification")
    assert journey["current_stage"] == "problem_identification"
    assert journey["completed_stages"] == completed


def test_explicit_deep_review_requires_all_stages_including_reflection() -> None:
    assert not explicit_deep_review_available(completed_stages=[])
    prefix = [stage.id for stage in THINKING_STAGES[:-1]]
    assert not explicit_deep_review_available(completed_stages=prefix)
    all_ids = [stage.id for stage in THINKING_STAGES]
    assert explicit_deep_review_available(completed_stages=all_ids)


def test_newly_completed_stage_ids_are_ordered() -> None:
    assert newly_completed_stage_ids(
        ["problem_identification"],
        ["problem_identification", "concept_generation", "design_specification"],
    ) == ["concept_generation", "design_specification"]


def test_stage_review_should_enqueue_idempotent() -> None:
    blob = {
        "jobs": {"problem_identification": {"status": STAGE_REVIEW_COMPLETE}},
        "reviews": {
            "problem_identification": {
                "summary": "Done.",
                "strengths": ["Clear focus"],
                "areas_to_revisit": [],
                "conversation_revision": 3,
            }
        },
        "unread": False,
    }
    assert not stage_review_should_enqueue(blob, stage_id="problem_identification")
    assert not stage_review_should_enqueue(
        blob, stage_id="problem_identification", notebook_revision=3
    )
    assert stage_review_should_enqueue(
        blob, stage_id="problem_identification", notebook_revision=4
    )
    assert stage_review_should_enqueue(None, stage_id="problem_identification")


def test_stage_reviews_need_attention_for_unread_or_active_jobs() -> None:
    from backend.specialists.review_orchestration import stage_reviews_need_attention

    assert not stage_reviews_need_attention(None)
    assert not stage_reviews_need_attention(
        {"jobs": {}, "reviews": {}, "unread": False}
    )
    assert stage_reviews_need_attention(
        {"jobs": {}, "reviews": {}, "unread": True}
    )
    assert stage_reviews_need_attention(
        {
            "jobs": {"problem_identification": {"status": "queued"}},
            "reviews": {},
            "unread": False,
        }
    )
    assert stage_reviews_need_attention(
        {
            "jobs": {"problem_identification": {"status": "running"}},
            "reviews": {},
            "unread": False,
        }
    )
    assert not stage_reviews_need_attention(
        {
            "jobs": {"problem_identification": {"status": STAGE_REVIEW_COMPLETE}},
            "reviews": {},
            "unread": False,
        }
    )


def test_public_stage_reviews_hide_internal_queue_metadata() -> None:
    """Student projection preserves status/review fields without worker tokens."""
    public = public_journey_stage_reviews(
        {
            "jobs": {
                "problem_identification": {
                    "status": "queued",
                    "updated_at": "2026-09-03T00:00:00+00:00",
                    "error_code": None,
                    "job_id": "job-secret",
                    "lease_token": "lease-secret",
                    "message_ids": ["message-private"],
                    "target_token": "dirty-secret",
                    "scope_frozen": True,
                    "scope_version": 1,
                }
            },
            "reviews": {
                "problem_identification": {
                    "stage": "problem_identification",
                    "summary": "A bounded checkpoint.",
                    "strengths": ["Names a stakeholder."],
                    "areas_to_revisit": [],
                    "important_message_ids": ["message-private"],
                    "facione_scores": {"analysis": 2},
                }
            },
            "revisit_dirty": {
                "problem_identification": {"token": "dirty-secret"}
            },
            "unread": True,
        }
    )

    assert set(public) == {"jobs", "reviews", "unread"}
    assert public["jobs"]["problem_identification"] == {
        "status": "queued",
        "updated_at": "2026-09-03T00:00:00+00:00",
        "error_code": None,
    }
    assert "important_message_ids" not in public["reviews"]["problem_identification"]
    assert "revisit_dirty" not in public


def test_execute_stage_review_job_persists_checkpoint_and_unread(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("STUDENT_STAGE_SELECTION", "true")
    store = StudentStore(tmp_path / "stage-reviews.sqlite3")
    coach = _services(store)
    thread_id = store.create_thread(model_id="mock", support_mode="critical-thinking")
    journey = default_journey()
    journey = mark_stage_completed(journey, "problem_identification")
    store.update_thread(
        thread_id,
        metadata={
            "learning_journey": journey,
            "thinking_stage": "problem_identification",
        },
    )
    blob, created = store.start_or_get_stage_review_job(
        thread_id, stage_id="problem_identification"
    )
    assert created is True
    coach.execute_stage_review_job(thread_id, "problem_identification")
    updated = store.get_thread(thread_id) or {}
    blob = parse_journey_stage_reviews(
        (updated.get("metadata") or {}).get(JOURNEY_STAGE_REVIEWS_KEY)
    )
    assert blob["jobs"]["problem_identification"]["status"] == STAGE_REVIEW_COMPLETE
    assert blob["unread"] is True
    assert "problem_identification" in blob["reviews"]
    checkpoint = blob["reviews"]["problem_identification"]
    assert checkpoint["facione_scores"]["analysis"] >= 1
    assert "conversation_revision" in checkpoint
    cleared = coach.mark_journey_stage_reviews_read(thread_id)
    assert cleared["unread"] is False
    again, created_again = store.start_or_get_stage_review_job(
        thread_id, stage_id="problem_identification"
    )
    assert created_again is False
    assert again["jobs"]["problem_identification"]["status"] == STAGE_REVIEW_COMPLETE


def test_stage_review_revisit_reenqueues_and_replaces_checkpoint(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A later revision on a completed stage re-queues Haiku and overwrites the slice."""
    monkeypatch.setenv("STUDENT_STAGE_SELECTION", "true")
    store = StudentStore(tmp_path / "stage-revisit.sqlite3")
    coach = _services(store)
    thread_id = store.create_thread(model_id="mock", support_mode="critical-thinking")
    journey = default_journey()
    journey = mark_stage_completed(journey, "problem_identification")
    journey = set_current_stage(journey, "problem_identification")
    store.update_thread(
        thread_id,
        metadata={
            "learning_journey": journey,
            "thinking_stage": "problem_identification",
        },
    )

    def _set_revision(revision: int) -> None:
        with store._lock, store._connect() as connection:
            connection.execute(
                "UPDATE notebooks SET conversation_revision=? WHERE id=? AND user_id=?",
                (revision, thread_id, store.owner_id),
            )

    _set_revision(2)
    blob, created = store.start_or_get_stage_review_job(
        thread_id, stage_id="problem_identification", notebook_revision=2
    )
    assert created is True
    coach.execute_stage_review_job(thread_id, "problem_identification")
    first = parse_journey_stage_reviews(
        (store.get_thread(thread_id) or {}).get("metadata", {}).get(
            JOURNEY_STAGE_REVIEWS_KEY
        )
    )
    assert first["reviews"]["problem_identification"]["conversation_revision"] == 2
    store.mark_journey_stage_reviews_read(thread_id)

    _, created_same = store.start_or_get_stage_review_job(
        thread_id, stage_id="problem_identification", notebook_revision=2
    )
    assert created_same is False

    _set_revision(5)
    queued_blob, created_refresh = store.start_or_get_stage_review_job(
        thread_id, stage_id="problem_identification", notebook_revision=5
    )
    assert created_refresh is True
    assert queued_blob["jobs"]["problem_identification"]["status"] == "queued"
    # Prior checkpoint remains until the refresh completes.
    assert "problem_identification" in queued_blob["reviews"]
    coach.execute_stage_review_job(thread_id, "problem_identification")
    second = parse_journey_stage_reviews(
        (store.get_thread(thread_id) or {}).get("metadata", {}).get(
            JOURNEY_STAGE_REVIEWS_KEY
        )
    )
    assert second["jobs"]["problem_identification"]["status"] == STAGE_REVIEW_COMPLETE
    assert second["unread"] is True
    assert second["reviews"]["problem_identification"]["conversation_revision"] == 5
    assert second["reviews"]["problem_identification"]["facione_scores"]["analysis"] >= 1


def test_completed_stage_revisit_waits_for_actual_exit(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Several revisit turns coalesce into one refresh when the stage is left."""
    from backend.settings import settings as runtime_settings

    monkeypatch.setattr(runtime_settings, "student_stage_selection", True)
    store = StudentStore(tmp_path / "stage-revisit-enqueue.sqlite3")
    coach = _services(store)
    thread_id = store.create_thread(model_id="mock", support_mode="critical-thinking")
    journey = default_journey()
    journey = mark_stage_completed(journey, "problem_identification")
    journey = set_current_stage(journey, "problem_identification")
    store.update_thread(
        thread_id,
        metadata={
            "learning_journey": journey,
            "thinking_stage": "problem_identification",
        },
    )
    store.start_or_get_stage_review_job(
        thread_id, stage_id="problem_identification"
    )
    coach.execute_stage_review_job(thread_id, "problem_identification")
    store.mark_journey_stage_reviews_read(thread_id)

    submitted: list[tuple[str, str]] = []

    def _capture(_coach: object, _thread: str, stage: str) -> None:
        submitted.append((_thread, stage))

    monkeypatch.setattr(
        "backend.coaching.stage_review_jobs.submit_stage_review_job",
        _capture,
    )
    coach._progress.set_stage_review_enqueue(  # noqa: SLF001 - test seam
        lambda queued_thread, stage: submitted.append((queued_thread, stage))
    )

    for index, message in enumerate(
        (
            "I now think slower walking speed is the most important constraint.",
            "The crossing should also work for people using mobility aids.",
            "A short pilot at two junctions would test that assumption.",
        )
    ):
        coach.submit(
            CoachRequest(
                thread_id=thread_id,
                student_message=message,
                current_stage="problem_identification",
                response_detail="short",
                idempotency_key=f"revisit-{index}",
            )
        )
        internal = parse_journey_stage_reviews(
            (store.get_thread(thread_id) or {}).get("metadata", {}).get(
                JOURNEY_STAGE_REVIEWS_KEY
            )
        )
        assert internal["jobs"]["problem_identification"]["status"] == STAGE_REVIEW_COMPLETE
        assert "problem_identification" in internal["revisit_dirty"]
        assert submitted == []

    coach._progress.select_stage(  # noqa: SLF001 - exercise direct Journey exit
        thread_id, "concept_generation"
    )
    assert submitted == [(thread_id, "problem_identification")]

    queued = parse_journey_stage_reviews(
        (store.get_thread(thread_id) or {}).get("metadata", {}).get(
            JOURNEY_STAGE_REVIEWS_KEY
        )
    )
    job = queued["jobs"]["problem_identification"]
    assert job["status"] == "queued"
    assert job["reason"] == "revisit_exit"
    assert job["scope_frozen"] is True
    assert job["target_token"] == queued["revisit_dirty"]["problem_identification"][
        "token"
    ]

    frozen_ids = set(job["message_ids"])
    frozen_messages = [
        row
        for row in store.get_messages(thread_id)
        if str(row.get("id") or "") in frozen_ids
    ]
    frozen_user_text = {
        str(row.get("content") or "")
        for row in frozen_messages
        if row.get("role") == "user"
    }
    assert frozen_user_text.issuperset(
        {
            "I now think slower walking speed is the most important constraint.",
            "The crossing should also work for people using mobility aids.",
            "A short pilot at two junctions would test that assumption.",
        }
    )


def test_failed_completion_worker_preserves_revisit_refresh_after_exit(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A failed older checkpoint cannot strand newer work made before exit."""
    store = StudentStore(tmp_path / "stage-revisit-failure.sqlite3")
    coach = _services(store)
    thread_id = store.create_thread(model_id="mock", support_mode="critical-thinking")
    journey = mark_stage_completed(default_journey(), "problem_identification")
    store.update_thread(
        thread_id,
        metadata={
            "learning_journey": journey,
            "thinking_stage": "problem_identification",
        },
    )
    queued, created = store.start_or_get_stage_review_job(
        thread_id,
        stage_id="problem_identification",
    )
    assert created is True
    old_job_id = queued["jobs"]["problem_identification"]["job_id"]

    # Model a substantive revisit that arrives while the older completion job
    # is still queued. The real coach-turn transaction writes this same marker.
    queued["revisit_dirty"]["problem_identification"] = {
        "token": "newer-revisit",
        "conversation_revision": 0,
        "updated_at": "2026-09-03T00:00:00+00:00",
    }
    store.update_thread(thread_id, metadata={JOURNEY_STAGE_REVIEWS_KEY: queued})
    store.select_learning_stage(thread_id, "concept_generation")

    submitted: list[tuple[str, str]] = []
    monkeypatch.setattr(
        "backend.coaching.stage_review_jobs.submit_stage_review_job",
        lambda _coach, queued_thread, stage: submitted.append(
            (queued_thread, stage)
        ),
    )

    def _fail_checkpoint(_request: CoachRequest) -> object:
        raise RuntimeError("deterministic checkpoint failure")

    monkeypatch.setattr(
        coach._workflow.provider,  # noqa: SLF001 - deterministic failure seam
        "assess_stage_checkpoint",
        _fail_checkpoint,
    )
    coach.execute_stage_review_job(
        thread_id,
        "problem_identification",
        old_job_id,
    )

    recovered = parse_journey_stage_reviews(
        (store.get_thread(thread_id) or {}).get("metadata", {}).get(
            JOURNEY_STAGE_REVIEWS_KEY
        )
    )
    replacement = recovered["jobs"]["problem_identification"]
    assert replacement["status"] == "queued"
    assert replacement["job_id"] != old_job_id
    assert replacement["reason"] == "revisit_exit"
    assert replacement["target_token"] == "newer-revisit"
    assert submitted == [(thread_id, "problem_identification")]


def test_deep_review_enqueue_blocked_until_reflection_complete(
    tmp_path: Path,
) -> None:
    store = StudentStore(tmp_path / "deep-unlock.sqlite3")
    coach = _services(store)
    thread_id = store.create_thread(model_id="mock", support_mode="critical-thinking")
    journey = default_journey()
    for stage in THINKING_STAGES[:-1]:
        journey = mark_stage_completed(journey, stage.id)
        if stage.id != THINKING_STAGES[-2].id:
            journey = set_current_stage(
                journey, THINKING_STAGES[THINKING_STAGES.index(stage) + 1].id
            )
        else:
            journey = set_current_stage(journey, "reflection")
    store.update_thread(
        thread_id,
        metadata={"learning_journey": journey, "thinking_stage": "reflection"},
    )
    with pytest.raises(ValueError, match="Reflection"):
        coach.enqueue_deep_review(thread_id)
    journey = mark_stage_completed(journey, "reflection")
    store.update_thread(
        thread_id,
        metadata={"learning_journey": journey, "thinking_stage": "reflection"},
    )
    job = coach.enqueue_deep_review(thread_id)
    assert job.status.value in {"queued", "running", "completed"}
