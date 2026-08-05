"""Repository ports and SQLite adapters for the local demonstration runtime."""

from __future__ import annotations

from typing import Any, Protocol

from .domain import PendingPhaseTransition, TransitionStatus
from .student_store import StudentStore


class NotebookRepository(Protocol):
    """Access notebook metadata and canonical conversation history."""

    def get_thread(self, thread_id: str) -> dict | None:
        """Return an owned notebook or ``None`` when it does not exist."""

    def get_messages(self, thread_id: str) -> list[dict]:
        """Return canonical messages in chronological order."""

    def list_threads(self, search: str = "") -> list[dict]:
        """Return notebooks ordered by recent activity."""

    def create_thread(
        self,
        *,
        name: str,
        model_id: str,
        support_mode: str,
        assignment: dict[str, str] | None = None,
    ) -> str:
        """Create a notebook and return its id."""

    def update_thread(
        self,
        thread_id: str,
        *,
        name: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        """Rename a notebook and/or merge metadata."""

    def delete_thread(self, thread_id: str) -> None:
        """Delete a notebook."""


class SourceRepository(Protocol):
    """Notebook-scoped source library access."""

    def list_sources(
        self, thread_id: str, *, selected_only: bool = False
    ) -> list[dict[str, Any]]:
        """Return sources for a notebook."""

    def get_source(self, thread_id: str, source_id: str) -> dict[str, Any] | None:
        """Return one source or ``None``."""


class PreferenceRepository(Protocol):
    """Local user preference access."""

    def get_preferences(self) -> dict[str, Any]:
        """Return preference metadata."""

    def update_preferences(self, patch: dict[str, Any]) -> None:
        """Merge preference keys."""


class PhaseTransitionRepository(Protocol):
    """Persist and retrieve student-confirmed stage transition requests."""

    def create(self, transition: PendingPhaseTransition) -> PendingPhaseTransition:
        """Persist one pending transition and return its stored representation."""

    def get_pending(self, thread_id: str) -> PendingPhaseTransition | None:
        """Return the newest unresolved transition for a notebook."""

    def resolve(
        self, thread_id: str, transition_id: str, accepted: bool
    ) -> PendingPhaseTransition:
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

    def list_threads(self, search: str = "") -> list[dict]:
        """Return notebooks ordered by recent activity."""
        return self._store.list_threads(search, None)

    def create_thread(
        self,
        *,
        name: str,
        model_id: str,
        support_mode: str,
        assignment: dict[str, str] | None = None,
    ) -> str:
        """Create a notebook through the SQLite store."""
        return self._store.create_thread(
            name=name,
            model_id=model_id,
            support_mode=support_mode,
            assignment=assignment,
        )

    def update_thread(
        self,
        thread_id: str,
        *,
        name: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        """Update notebook name/metadata through the SQLite store."""
        self._store.update_thread(thread_id, name=name, metadata=metadata)

    def delete_thread(self, thread_id: str) -> None:
        """Delete a notebook through the SQLite store."""
        self._store.delete_thread(thread_id)


class SQLiteSourceRepository:
    """Adapter for notebook source rows in SQLite."""

    def __init__(self, store: StudentStore):
        self._store = store

    def list_sources(
        self, thread_id: str, *, selected_only: bool = False
    ) -> list[dict[str, Any]]:
        """Return source rows for a notebook."""
        return self._store.list_sources(thread_id, selected_only=selected_only)

    def get_source(self, thread_id: str, source_id: str) -> dict[str, Any] | None:
        """Return one source row."""
        return self._store.get_source(thread_id, source_id)


class SQLitePreferenceRepository:
    """Adapter for local user preference metadata."""

    def __init__(self, store: StudentStore):
        self._store = store

    def get_preferences(self) -> dict[str, Any]:
        """Return preference metadata."""
        return self._store.get_user_preferences() or {}

    def update_preferences(self, patch: dict[str, Any]) -> None:
        """Merge preference keys."""
        self._store.update_user_preferences(patch)


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

    def resolve(
        self, thread_id: str, transition_id: str, accepted: bool
    ) -> PendingPhaseTransition:
        """Record the student's response to a recommendation."""
        status = TransitionStatus.CONFIRMED if accepted else TransitionStatus.REJECTED
        return PendingPhaseTransition.model_validate(
            self._store.resolve_phase_transition(thread_id, transition_id, status.value)
        )
