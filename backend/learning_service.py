"""Application service for confirmation-gated and student-selected stage progression."""

from __future__ import annotations

from typing import Any

from .domain import PendingPhaseTransition
from .repositories import NotebookRepository, PhaseTransitionRepository
from .settings import settings
from .student_journey import (
    STAGE_BY_ID,
    complete_and_advance,
    current_stage,
    normalize_journey,
)
from .student_store import StudentStore


class LearningProgressService:
    """Apply student-confirmed recommendations and optional stage selection."""

    def __init__(
        self,
        store: StudentStore,
        notebooks: NotebookRepository,
        transitions: PhaseTransitionRepository,
    ) -> None:
        self._store = store
        self._notebooks = notebooks
        self._transitions = transitions

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
        without the matching Thinking Path stage (or the reverse).
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
            next_journey = complete_and_advance(
                journey,
                note=pending.assessment.contribution_summary,
            )
            if current_stage(next_journey).id != pending.to_stage:
                raise ValueError(
                    "Confirmed transition does not match the learning journey"
                )
            metadata_patch = {
                "learning_journey": next_journey,
                "thinking_stage": pending.to_stage,
                "learning_summary": pending.assessment.learning_summary,
                "working_conclusion": pending.assessment.working_conclusion,
                "understanding_change": pending.assessment.understanding_change,
                "critical_understanding": pending.assessment.critical_understanding_level,
            }

        resolved = self._store.apply_phase_transition_decision(
            thread_id,
            transition_id,
            accepted=accepted,
            metadata_patch=metadata_patch,
            expected_from_stage=pending.from_stage if accepted else None,
        )
        return PendingPhaseTransition.model_validate(resolved)

    def select_stage(self, thread_id: str, stage_id: str) -> dict[str, Any]:
        """Move the notebook to a student-chosen Thinking Path stage.

        Requires ``STUDENT_STAGE_SELECTION=true``. Does not mark skipped stages
        complete; rejects any pending ADVANCE recommendation for the notebook.

        Returns:
            Updated notebook metadata including ``learning_journey``.

        Raises:
            ValueError: When selection is disabled, the stage is unknown, or the
                notebook is missing.
        """
        if not settings.student_stage_selection:
            raise ValueError("Student stage selection is not enabled")
        cleaned = str(stage_id or "").strip()
        if cleaned not in STAGE_BY_ID:
            raise ValueError(f"Unknown thinking stage: {cleaned}")
        if not self._notebooks.get_thread(thread_id):
            raise ValueError("Notebook not found")
        return self._store.select_learning_stage(thread_id, cleaned)
