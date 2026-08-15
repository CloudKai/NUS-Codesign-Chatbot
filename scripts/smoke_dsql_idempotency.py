#!/usr/bin/env python3
"""Run an explicitly approved live DSQL coach-idempotency smoke.

This operator tool performs runtime DML only through ``co_design_app``. It uses
the deterministic mock provider, creates no schema objects, never reads or
writes S3, and removes its disposable notebook rows in ``finally``.
"""

from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import sys
import threading
from uuid import uuid4

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backend.application import CoachApplicationService
from backend.domain import CoachRequest, EducationalAssessment, StageDecision
from backend.learning_service import LearningProgressService
from backend.mock_provider import DeterministicCoachProvider
from backend.persistence.dsql_connection import run_dsql_transaction
from backend.persistence.dsql_schema import RUNTIME_ROLE_NAME
from backend.persistence.factory import create_student_store
from backend.persistence.dsql_student_store import DsqlStudentStore
from backend.repositories import SQLiteNotebookRepository, SQLitePhaseTransitionRepository
from backend.settings import settings
from backend.student_journey import DEFAULT_STAGE
from backend.student_store import CoachIdempotencyConflictError
from backend.workflow import CoachWorkflow


class _CountingMockProvider(DeterministicCoachProvider):
    """Deterministic provider that proves concurrent requests execute once."""

    def __init__(self, *, fail_first: bool = False) -> None:
        super().__init__(StageDecision.STAY)
        self.calls = 0
        self._fail_first = fail_first
        self._lock = threading.Lock()

    def assess(self, request: CoachRequest) -> tuple[str, EducationalAssessment]:
        """Count executions and optionally fail the first attempt."""
        with self._lock:
            self.calls += 1
            call_number = self.calls
        if self._fail_first and call_number == 1:
            raise RuntimeError("intentional mock provider failure")
        return super().assess(request)


def _service(
    store: DsqlStudentStore,
    provider: DeterministicCoachProvider,
) -> CoachApplicationService:
    """Build the normal application path over one independent DSQL store."""
    notebooks = SQLiteNotebookRepository(store)
    transitions = SQLitePhaseTransitionRepository(store)
    workflow = CoachWorkflow(provider, transitions)
    return CoachApplicationService(
        store,
        notebooks,
        workflow,
        LearningProgressService(store, notebooks, transitions),
        auto_advance_stages=False,
    )


def _cleanup_notebook_rows(store: DsqlStudentStore, thread_id: str) -> None:
    """Delete smoke rows with runtime DML without invoking S3 prefix cleanup."""

    def cleanup() -> None:
        with store._connect() as connection:
            connection.execute("DELETE FROM messages WHERE notebook_id=?", (thread_id,))
            connection.execute("DELETE FROM sources WHERE notebook_id=?", (thread_id,))
            connection.execute(
                "DELETE FROM notebooks WHERE id=? AND user_id=?",
                (thread_id, store.owner_id),
            )

    run_dsql_transaction(cleanup)


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Live runtime-role DSQL coach-idempotency smoke (mock provider only)."
    )
    parser.add_argument(
        "--confirm-live",
        action="store_true",
        help="Required acknowledgement that this performs live DSQL writes.",
    )
    parser.add_argument(
        "--identifier",
        required=True,
        help="Existing owner identifier in the form cognito:<sub>.",
    )
    return parser.parse_args()


def _validate_guardrails(args: argparse.Namespace) -> str:
    """Fail closed unless the caller selected the production runtime boundary."""
    if not args.confirm_live:
        raise SystemExit("Refusing live DSQL writes without --confirm-live")
    if settings.database_provider != "dsql":
        raise SystemExit("DATABASE_PROVIDER must be dsql")
    if settings.dsql_user != RUNTIME_ROLE_NAME:
        raise SystemExit(f"DSQL_USER must be {RUNTIME_ROLE_NAME}")
    identifier = str(args.identifier or "").strip()
    if not identifier.startswith("cognito:") or not identifier.removeprefix(
        "cognito:"
    ).strip():
        raise SystemExit("--identifier must be in the form cognito:<sub>")
    return identifier


def run(identifier: str) -> None:
    """Execute concurrency, replay, conflict, and failure-release assertions."""
    first_store = create_student_store(identifier=identifier)
    second_store = create_student_store(identifier=identifier)
    if not isinstance(first_store, DsqlStudentStore) or not isinstance(
        second_store, DsqlStudentStore
    ):
        raise RuntimeError("The smoke did not construct DSQL-backed stores")

    thread_id = first_store.create_thread(
        name=f"DSQL idempotency smoke {uuid4()}",
        model_id="mock",
        support_mode="critical-thinking",
    )
    try:
        provider = _CountingMockProvider()
        request = CoachRequest(
            thread_id=thread_id,
            student_message="Check this disposable DSQL idempotency claim.",
            current_stage=DEFAULT_STAGE,
            response_detail="short",
            idempotency_key=f"live-dsql-{uuid4()}",
        )
        services = (_service(first_store, provider), _service(second_store, provider))
        barrier = threading.Barrier(2)

        def submit(service: CoachApplicationService):
            barrier.wait()
            return service.submit(request)

        with ThreadPoolExecutor(max_workers=2) as executor:
            futures = [executor.submit(submit, service) for service in services]
            turns = [future.result(timeout=180) for future in futures]

        restarted = create_student_store(identifier=identifier)
        if not isinstance(restarted, DsqlStudentStore):
            raise RuntimeError("Restarted smoke store is not DSQL-backed")
        replay = _service(restarted, provider).submit(request)
        if turns[0] != turns[1] or replay != turns[0] or provider.calls != 1:
            raise AssertionError("Concurrent DSQL replay did not converge exactly once")
        if len(restarted.get_messages(thread_id)) != 2:
            raise AssertionError("Concurrent DSQL turn persisted duplicate messages")

        changed = request.model_copy(
            update={"student_message": "Changed input must conflict with the same key."}
        )
        try:
            _service(restarted, provider).submit(changed)
        except CoachIdempotencyConflictError:
            pass
        else:
            raise AssertionError("Changed DSQL request reused a completed key")

        failing_provider = _CountingMockProvider(fail_first=True)
        retry_request = request.model_copy(
            update={
                "student_message": "A failed mock provider call must release this key.",
                "idempotency_key": f"live-dsql-failure-{uuid4()}",
            }
        )
        try:
            _service(first_store, failing_provider).submit(retry_request)
        except RuntimeError as error:
            if "intentional mock provider failure" not in str(error):
                raise
        else:
            raise AssertionError("The intentional mock failure did not occur")
        recovered = _service(second_store, failing_provider).submit(retry_request)
        if not recovered.response_text or failing_provider.calls != 2:
            raise AssertionError("Failed DSQL request did not recover on retry")
    finally:
        _cleanup_notebook_rows(first_store, thread_id)


def main() -> None:
    """Parse explicit live guardrails, run the smoke, and print no identifiers."""
    args = _parse_args()
    run(_validate_guardrails(args))
    print("Live DSQL coach-idempotency smoke passed; disposable notebook removed.")


if __name__ == "__main__":
    main()
