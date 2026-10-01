"""Application service for confirmation-gated and student-selected stage progression."""

from __future__ import annotations

import logging
from typing import Any, Callable

from .domain import PendingPhaseTransition
from .repositories import NotebookRepository, PhaseTransitionRepository
from .settings import settings
from .specialists.review_orchestration import (
    DEEP_REVIEW_SNAPSHOT_KEY,
    JOURNEY_STAGE_REVIEWS_KEY,
)
from .student_journey import (
    STAGE_BY_ID,
    complete_and_advance,
    compose_stage_move_briefing,
    current_stage,
    normalize_journey,
)
from .student_store import StudentStore

logger = logging.getLogger(__name__)

StageReviewEnqueue = Callable[[str, str], None]


class LearningProgressService:
    """Apply student-confirmed recommendations and optional stage selection."""

    def __init__(
        self,
        store: StudentStore,
        notebooks: NotebookRepository,
        transitions: PhaseTransitionRepository,
        *,
        enqueue_stage_review: StageReviewEnqueue | None = None,
    ) -> None:
        self._store = store
        self._notebooks = notebooks
        self._transitions = transitions
        self._enqueue_stage_review = enqueue_stage_review

    def set_stage_review_enqueue(self, enqueue: StageReviewEnqueue | None) -> None:
        """Attach the background stage-review submitter after coach construction."""
        self._enqueue_stage_review = enqueue

    def _submit_durable_stage_review_jobs(self, thread_id: str) -> None:
        """Submit only stage-review jobs already committed by the store.

        Stage-change transactions queue completion/refresh work atomically;
        this callback is deliberately post-commit and only hands durable rows
        to the process-local executor.
        """
        if self._enqueue_stage_review is None:
            return
        thread = self._notebooks.get_thread(thread_id)
        if not thread:
            return
        blob = (thread.get("metadata") or {}).get(JOURNEY_STAGE_REVIEWS_KEY)
        if not isinstance(blob, dict):
            return
        jobs = blob.get("jobs")
        if not isinstance(jobs, dict):
            return
        for stage_id, job in jobs.items():
            if not isinstance(job, dict):
                continue
            if str(job.get("status") or "").strip().lower() != "queued":
                continue
            self._enqueue_stage_review(thread_id, str(stage_id).strip())

    def get_pending(self, thread_id: str) -> PendingPhaseTransition | None:
        """Return the unresolved recommendation for one owned notebook."""
        if not self._notebooks.get_thread(thread_id):
            raise ValueError("Notebook not found")
        return self._transitions.get_pending(thread_id)

    def resolve(
        self,
        thread_id: str,
        transition_id: str,
        accepted: bool,
    ) -> PendingPhaseTransition:
        """Record a student choice and advance only when the current stage matches.

        Journey metadata and transition status are updated in one SQLite
        transaction so a mid-flight failure cannot leave a confirmed transition
        without the matching Thinking Path stage (or the reverse). Empty
        progress strings from a slim Fast Chat assessment are omitted so they
        cannot blank previously stored notebook progress. ``learning_journey``
        and ``thinking_stage`` are always written on ADVANCE.
        """
        pending = self._transitions.get_pending(thread_id)
        if not pending or pending.id != transition_id:
            raise ValueError("Pending transition not found")
        thread = self._notebooks.get_thread(thread_id)
        if not thread:
            raise ValueError("Notebook not found")
        metadata = dict(thread.get("metadata") or {})
        journey = normalize_journey(metadata.get("learning_journey"))
        if accepted and current_stage(journey).id != pending.from_stage:
            raise ValueError("The notebook stage changed; request a new recommendation")

        metadata_patch: dict | None = None
        if accepted:
            from backend.coaching.progress_fields import overlay_progress_fields

            next_journey = complete_and_advance(
                journey,
                note=pending.assessment.contribution_summary,
            )
            if current_stage(next_journey).id != pending.to_stage:
                raise ValueError(
                    "Confirmed transition does not match the learning journey"
                )
            progress_update = overlay_progress_fields(
                {
                    "learning_summary": metadata.get("learning_summary")
                    or (metadata.get("learning_journey") or {}).get(
                        "learning_summary"
                    ),
                    "working_conclusion": metadata.get("working_conclusion")
                    or journey.get("working_conclusion"),
                    "understanding_change": metadata.get("understanding_change")
                    or (metadata.get("learning_journey") or {}).get(
                        "understanding_change"
                    ),
                    "critical_understanding": metadata.get("critical_understanding")
                    or (metadata.get("learning_journey") or {}).get(
                        "critical_understanding"
                    ),
                },
                {
                    "learning_summary": pending.assessment.learning_summary,
                    "working_conclusion": pending.assessment.working_conclusion,
                    "understanding_change": pending.assessment.understanding_change,
                    "critical_understanding": (
                        pending.assessment.critical_understanding_level
                    ),
                },
            )
            if progress_update:
                next_journey = {**next_journey, **progress_update}
            metadata_patch = {
                "learning_journey": next_journey,
                "thinking_stage": pending.to_stage,
                **progress_update,
            }

        resolved = self._store.apply_phase_transition_decision(
            thread_id,
            transition_id,
            accepted=accepted,
            metadata_patch=metadata_patch,
            expected_from_stage=pending.from_stage if accepted else None,
        )
        if accepted:
            try:
                self._submit_durable_stage_review_jobs(thread_id)
            except Exception:
                logger.exception(
                    "stage_review_enqueue_after_confirm_failed thread_id=%s",
                    thread_id,
                )
        return PendingPhaseTransition.model_validate(resolved)

    def select_stage(self, thread_id: str, stage_id: str) -> dict[str, Any]:
        """Move the notebook to a student-chosen Thinking Path stage.

        Requires ``STUDENT_STAGE_SELECTION=true``. Allows only the canonical
        prerequisite-gated frontier (including revisits), does not mark
        skipped stages complete, and rejects/resolves any pending ADVANCE
        recommendation for the notebook atomically.

        When focus actually changes, persists one assistant-only briefing
        bubble (``Moved to Stage:`` plus enter/revisit commands). Already-on-
        stage selections write no chat row. Does not bump the Deep Review
        coaching-turn counter.

        Returns:
            Updated notebook metadata including ``learning_journey``.

        Raises:
            ValueError: When selection is disabled, the stage is unknown or
                locked, or the notebook is missing.
        """
        if not settings.student_stage_selection:
            raise ValueError("Student stage selection is not enabled")
        cleaned = str(stage_id or "").strip()
        if cleaned not in STAGE_BY_ID:
            raise ValueError(f"Unknown thinking stage: {cleaned}")
        thread = self._notebooks.get_thread(thread_id)
        if not thread:
            raise ValueError("Notebook not found")
        metadata = dict(thread.get("metadata") or {})
        prior_journey = normalize_journey(metadata.get("learning_journey"))
        prior_stage = str(prior_journey.get("current_stage") or "").strip()
        briefing: str | None = None
        if prior_stage != cleaned:
            messages = self._store.get_messages(thread_id)
            snapshot = metadata.get(DEEP_REVIEW_SNAPSHOT_KEY)
            reviews = metadata.get(JOURNEY_STAGE_REVIEWS_KEY)
            briefing = compose_stage_move_briefing(
                target_stage=cleaned,
                journey=prior_journey,
                messages=messages,
                deep_review_snapshot=(
                    snapshot if isinstance(snapshot, dict) else None
                ),
                journey_stage_reviews=(
                    reviews if isinstance(reviews, dict) else None
                ),
                already_selected=False,
            )
        updated = self._store.select_learning_stage(thread_id, cleaned)
        if briefing:
            self._store.add_message(
                thread_id,
                "assistant",
                briefing,
                metadata={
                    "thinking_stage": cleaned,
                    "stage_move_briefing": True,
                    "assessment": {
                        "current_stage": cleaned,
                        "contribution_summary": (
                            "Applied the student's explicit stage selection."
                        ),
                        "stage_assessment": (
                            "Stage selected from the authoritative notebook journey."
                        ),
                        "recommendation": None,
                        "response_mode": "qa",
                    },
                },
            )
        try:
            self._submit_durable_stage_review_jobs(thread_id)
        except Exception:
            logger.exception(
                "stage_review_enqueue_after_select_failed thread_id=%s", thread_id
            )
        return updated
