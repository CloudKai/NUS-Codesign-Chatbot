"""Repository ports and SQLite adapters for the local demonstration runtime."""

from __future__ import annotations

from typing import Protocol

from .domain import PendingPhaseTransition, TransitionStatus
from .student_store import StudentStore


class NotebookRepository(Protocol):
    """Access notebook metadata and canonical conversation history."""

    def get_thread(self, thread_id: str) -> dict | None:
        """Return an owned notebook or ``None`` when it does not exist."""

    def get_messages(self, thread_id: str) -> list[dict]:
        """Return canonical messages in chronological order."""


class PhaseTransitionRepository(Protocol):
    """Persist and retrieve student-confirmed stage transition requests."""

    def create(self, transition: PendingPhaseTransition) -> PendingPhaseTransition:
        """Persist one pending transition and return its stored representation."""

    def get_pending(self, thread_id: str) -> PendingPhaseTransition | None:
        """Return the newest unresolved transition for a notebook."""

    def resolve(self, thread_id: str, transition_id: str, accepted: bool) -> PendingPhaseTransition:
        """Mark a transition confirmed or rejected without changing journey state."""


class SQLiteNotebookRepository:
    """Adapter that exposes existing ``StudentStore`` notebooks through a narrow port."""

    def __init__(self, store: StudentStore):
        self._store = store

    def get_thread(self, thread_id: str) -> dict | None:
        """Return the owned notebook record from the existing SQLite store."""
        return self._store.get_thread(thread_id)

    def get_messages(self, thread_id: str) -> list[dict]:
        """Return the notebook's existing canonical message history."""
        return self._store.get_messages(thread_id)


class SQLitePhaseTransitionRepository:
    """Adapter for persisted, student-confirmed phase transition decisions."""

    def __init__(self, store: StudentStore):
        self._store = store

    def create(self, transition: PendingPhaseTransition) -> PendingPhaseTransition:
        """Persist one recommendation through the legacy-compatible SQLite store."""
        return PendingPhaseTransition.model_validate(
            self._store.create_phase_transition(transition.model_dump(mode="json"))
        )

    def get_pending(self, thread_id: str) -> PendingPhaseTransition | None:
        """Return the active recommendation, if a student has not acted on it yet."""
        value = self._store.get_pending_phase_transition(thread_id)
        return PendingPhaseTransition.model_validate(value) if value else None

    def resolve(self, thread_id: str, transition_id: str, accepted: bool) -> PendingPhaseTransition:
        """Record the student's response to a recommendation."""
        status = TransitionStatus.CONFIRMED if accepted else TransitionStatus.REJECTED
        return PendingPhaseTransition.model_validate(
            self._store.resolve_phase_transition(thread_id, transition_id, status.value)
        )
