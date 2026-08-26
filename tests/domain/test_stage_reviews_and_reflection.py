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
        "reviews": {},
        "unread": False,
    }
    assert not stage_review_should_enqueue(blob, stage_id="problem_identification")
    assert stage_review_should_enqueue(None, stage_id="problem_identification")


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
    cleared = coach.mark_journey_stage_reviews_read(thread_id)
    assert cleared["unread"] is False
    again, created_again = store.start_or_get_stage_review_job(
        thread_id, stage_id="problem_identification"
    )
    assert created_again is False
    assert again["jobs"]["problem_identification"]["status"] == STAGE_REVIEW_COMPLETE


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
