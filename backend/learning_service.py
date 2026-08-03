"""Application service for confirmation-gated learning-stage progression."""

from __future__ import annotations

from .domain import PendingPhaseTransition
from .repositories import NotebookRepository, PhaseTransitionRepository
from .student_journey import complete_and_advance, current_stage, normalize_journey
from .student_store import StudentStore


class LearningProgressService:
    """Apply only student-confirmed recommendations to persisted learning state."""

    def __init__(
        self,
        store: StudentStore,
        notebooks: NotebookRepository,
        transitions: PhaseTransitionRepository,
    ) -> None:
        self._store = store
        self._notebooks = notebooks
        self._transitions = transitions

    def resolve(
        self,
        thread_id: str,
        transition_id: str,
        accepted: bool,
    ) -> PendingPhaseTransition:
        """Record a student choice and advance only when the current stage matches.

        The transition audit record is written before the journey state changes.
        A stale recommendation cannot advance a notebook after another update.
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

        resolved = self._transitions.resolve(thread_id, transition_id, accepted)
        if not accepted:
            return resolved

        next_journey = complete_and_advance(
            journey,
            note=pending.assessment.contribution_summary,
        )
        if current_stage(next_journey).id != pending.to_stage:
            raise ValueError("Confirmed transition does not match the learning journey")
        self._store.update_thread(
            thread_id,
            metadata={
                "learning_journey": next_journey,
                "thinking_stage": pending.to_stage,
                "learning_summary": pending.assessment.learning_summary,
                "working_conclusion": pending.assessment.working_conclusion,
                "understanding_change": pending.assessment.understanding_change,
                "critical_understanding": pending.assessment.critical_understanding_level,
            },
        )
        return resolved
