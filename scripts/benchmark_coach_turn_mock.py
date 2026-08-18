"""Informational mock coach-turn latency buckets. Not an SLO. No AWS.

Uses an isolated SQLite file and the deterministic mock provider. Never
touches production DSQL, AgentCore, Bedrock, or student data directories.

Example::

    .venv/bin/python scripts/benchmark_coach_turn_mock.py
"""

from __future__ import annotations

import argparse
import json
import sys
import tempfile
import time
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parents[1]
_TESTS_DIR = _PROJECT_ROOT / "tests"
for extra in (_PROJECT_ROOT, _TESTS_DIR):
    if str(extra) not in sys.path:
        sys.path.insert(0, str(extra))

from backend.application import CoachApplicationService  # noqa: E402
from backend.domain import CoachRequest, StageDecision  # noqa: E402
from backend.learning_service import LearningProgressService  # noqa: E402
from backend.mock_provider import DeterministicCoachProvider  # noqa: E402
from backend.repositories import (  # noqa: E402
    SQLiteNotebookRepository,
    SQLitePhaseTransitionRepository,
)
from backend.student_store import StudentStore  # noqa: E402
from backend.workflow import CoachWorkflow  # noqa: E402

_BUCKETS = (
    ("fresh", 0),
    ("medium", 20),
    ("heavy", 50),
)


def _service(store: StudentStore) -> CoachApplicationService:
    """Build one in-process coach service over the mock provider."""
    notebooks = SQLiteNotebookRepository(store)
    transitions = SQLitePhaseTransitionRepository(store)
    workflow = CoachWorkflow(DeterministicCoachProvider(StageDecision.STAY), transitions)
    learning = LearningProgressService(store, notebooks, transitions)
    return CoachApplicationService(store, notebooks, workflow, learning)


def measure_bucket(history_size: int) -> dict[str, object]:
    """Submit one mock coaching turn after seeding ``history_size`` messages.

    Args:
        history_size: Prior transcript messages to insert. The current
            student message is not counted in this number.

    Returns:
        Timing and count fields only. No student-text payload.
    """
    with tempfile.TemporaryDirectory() as tmp:
        store = StudentStore(Path(tmp) / "bench.sqlite3")
        thread_id = store.create_thread(
            model_id="mock", support_mode="critical-thinking"
        )
        for index in range(history_size):
            role = "user" if index % 2 == 0 else "assistant"
            store.add_message(
                thread_id,
                role,
                f"historic-turn-{index} older pedestrians at a crossing.",
            )
        service = _service(store)
        started = time.perf_counter()
        turn = service.submit(
            CoachRequest(
                thread_id=thread_id,
                student_message=(
                    "Older pedestrians near schools may not have enough "
                    "time to cross safely."
                ),
                current_stage="problem_identification",
                response_detail="long",
                idempotency_key=f"bench-{history_size}",
            )
        )
        elapsed_ms = round((time.perf_counter() - started) * 1000.0, 1)
        return {
            "history_size": history_size,
            "submit_ms": elapsed_ms,
            "provider": "mock",
            "agentcore_invokes": 0,
            "event_loop_cycle_count": None,
            "response_chars": len(str(turn.response_text or "")),
            "recommendation": str(turn.assessment.recommendation or ""),
        }


def main(argv: list[str] | None = None) -> int:
    """Print mock coach-turn buckets as JSON lines."""
    parser = argparse.ArgumentParser(
        description=(
            "Measure mock CoachApplicationService submit time by history "
            "size. Isolated SQLite only; not a latency SLO."
        )
    )
    parser.add_argument(
        "--i-approve-live-aws",
        action="store_true",
        help="Rejected. This script never calls AWS.",
    )
    args = parser.parse_args(argv)
    if args.i_approve_live_aws:
        print("This benchmark refuses live AWS.", file=sys.stderr)
        return 2
    rows = []
    for name, size in _BUCKETS:
        row = measure_bucket(size)
        row["bucket"] = name
        rows.append(row)
        print(json.dumps(row, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
