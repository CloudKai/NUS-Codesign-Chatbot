"""Request-scoped turn snapshot reduces repeated notebook-row reads."""

from __future__ import annotations

import json
import logging
from typing import Any

from backend.application import CoachApplicationService
from backend.domain import CoachRequest, StageDecision
from backend.learning_service import LearningProgressService
from backend.mock_provider import DeterministicCoachProvider
from backend.repositories import (
    SQLiteNotebookRepository,
    SQLitePhaseTransitionRepository,
)
from backend.student_store import StudentStore
from backend.workflow import CoachWorkflow


class CountingStudentStore:
    """Delegating store that counts notebook-row and contract reads."""

    def __init__(self, inner: StudentStore) -> None:
        self._inner = inner
        self.get_thread_calls = 0
        self.list_sources_calls = 0
        self.contract_ready_calls = 0

    def get_thread(self, thread_id: str) -> dict[str, Any] | None:
        """Count one notebook-row lookup."""
        self.get_thread_calls += 1
        return self._inner.get_thread(thread_id)

    def list_sources(
        self, thread_id: str, *, selected_only: bool = False
    ) -> list[dict[str, Any]]:
        """Count one notebook source listing."""
        self.list_sources_calls += 1
        return self._inner.list_sources(thread_id, selected_only=selected_only)

    def research_workflow_contract_ready(self) -> bool:
        """Count the per-turn workflow-contract check."""
        self.contract_ready_calls += 1
        return self._inner.research_workflow_contract_ready()

    def __getattr__(self, name: str) -> Any:
        return getattr(self._inner, name)


def _service(store: CountingStudentStore) -> CoachApplicationService:
    """Build the application path over the counting store wrapper."""
    notebooks = SQLiteNotebookRepository(store)  # type: ignore[arg-type]
    transitions = SQLitePhaseTransitionRepository(store)  # type: ignore[arg-type]
    return CoachApplicationService(
        store,  # type: ignore[arg-type]
        notebooks,
        CoachWorkflow(DeterministicCoachProvider(StageDecision.STAY), transitions),
        LearningProgressService(store, notebooks, transitions),  # type: ignore[arg-type]
    )


def test_normal_submit_loads_notebook_twice(tmp_path, caplog) -> None:
    """Normal ``submit()`` re-reads the notebook for authority, not for the title.

    Before: 3 ``get_thread`` calls (existence/fingerprint, authoritative re-read,
    title check). After: 2. The workflow-contract marker is still checked once
    per turn and is not process-cached because it can be reset per database.
    """
    inner = StudentStore(tmp_path / "snapshot.sqlite3")
    store = CountingStudentStore(inner)
    thread_id = store.create_thread(model_id="mock", support_mode="critical-thinking")
    store.get_thread_calls = 0
    store.list_sources_calls = 0
    store.contract_ready_calls = 0
    caplog.set_level(logging.INFO, logger="co_design.operational")
    service = _service(store)

    service.submit(
        CoachRequest(
            thread_id=thread_id,
            student_message="I think option B is stronger because older users wait less.",
            current_stage="problem_identification",
            response_detail="short",
            idempotency_key="turn-snapshot",
        )
    )

    assert store.get_thread_calls == 2
    assert store.list_sources_calls == 1
    assert store.contract_ready_calls == 1
    events = [
        json.loads(record.message)
        for record in caplog.records
        if record.message.startswith("{") and "coach_turn_perf" in record.message
    ]
    assert events
    payload = events[-1]
    assert payload["notebook_load_count"] == 2
    assert payload["retrieval_count"] == 0
    assert payload["citation_source_resolution_count"] == 0
    assert payload["source_catalog_load_count"] == 0
