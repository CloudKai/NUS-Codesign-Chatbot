"""Time to first visible reply text through the coach stream, mock provider only.

Offline and cost-free: an isolated temporary SQLite file and the deterministic
mock provider. It never calls AWS, Bedrock, AgentCore, a Knowledge Base or any
paid service. The numbers describe this server-side event pipeline, not model
latency (see ``docs/IMPLEMENTATION_STATUS.md``, Phase 4 item 4).

Two provider modes are measured:

* ``plain``: the unmodified mock provider (no added latency). This shows the
  pipeline overhead alone.
* ``simulated``: the mock provider plus a stand-in generation delay: a time to
  first token (``--ttft-ms``), then one pause (``--chunk-ms``) per chunk. The
  numbers are inputs chosen by the caller, not measurements of any model.

The same script runs before and after the streaming change. "First visible
text" is the first ``reply_delta`` event when the stream emits one, otherwise
``reply_ready`` (the validated reply, which older clients render).

Example::

    MOCK_OPENAI=true MODEL_PROVIDER=mock OPENAI_API_KEY= USE_LOCAL_API=false \\
      python scripts/evals/measure_stream_first_text.py --runs 15 --json-output out.json
"""

from __future__ import annotations

import argparse
import inspect
import json
import statistics
import subprocess
import sys
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

_PROJECT_ROOT = Path(__file__).resolve().parents[2]
for extra in (_PROJECT_ROOT, _PROJECT_ROOT / "tests"):
    if str(extra) not in sys.path:
        sys.path.insert(0, str(extra))

from backend.application import CoachApplicationService  # noqa: E402
from backend.coaching.streaming import coach_events  # noqa: E402
from backend.domain import CoachRequest, StageDecision  # noqa: E402
from backend.learning_service import LearningProgressService  # noqa: E402
from backend.mock_provider import DeterministicCoachProvider, mock_needs_sources  # noqa: E402
from backend.repositories import (  # noqa: E402
    SQLiteNotebookRepository,
    SQLitePhaseTransitionRepository,
)
from backend.student_store import StudentStore  # noqa: E402
from backend.workflow import CoachWorkflow  # noqa: E402

try:  # Present once reply text streaming exists; absent in the "before" code.
    from backend.coaching.progress import emit_coach_reply_delta
except ImportError:  # pragma: no cover - exercised only on pre-streaming code
    emit_coach_reply_delta = None  # type: ignore[assignment]

_MESSAGE = (
    "Older pedestrians near schools may not have enough time to cross "
    "the road safely before the light changes."
)


def _chunks(text: str, size: int = 4) -> list[str]:
    """Split text into pieces of ``size`` words, keeping every character."""
    words = text.split(" ")
    return [
        " ".join(words[index : index + size]) + (" " if index + size < len(words) else "")
        for index in range(0, len(words), size)
    ]


class SimulatedLatencyProvider(DeterministicCoachProvider):
    """Mock provider with a stand-in time to first token and per-chunk pauses.

    Text is emitted chunk by chunk as the simulated generation proceeds when
    the stream asks for deltas. Without a bound sink (or on code without
    streaming) the same total time passes and only the finished reply exists.
    """

    def __init__(self, ttft_ms: float, chunk_ms: float) -> None:
        super().__init__(StageDecision.STAY)
        self._ttft = ttft_ms / 1000.0
        self._chunk = chunk_ms / 1000.0

    def assess(self, request: CoachRequest):  # type: ignore[override]
        result = self._assess_turn(request)
        if mock_needs_sources(request):
            result = result.model_copy(update={"needs_sources": True})
        time.sleep(self._ttft)
        for piece in _chunks(result.response_text):
            time.sleep(self._chunk)
            if emit_coach_reply_delta is not None:
                emit_coach_reply_delta(piece)
        return result


def _service(store: StudentStore, provider: DeterministicCoachProvider) -> CoachApplicationService:
    notebooks = SQLiteNotebookRepository(store)
    transitions = SQLitePhaseTransitionRepository(store)
    workflow = CoachWorkflow(provider, transitions)
    learning = LearningProgressService(store, notebooks, transitions)
    return CoachApplicationService(store, notebooks, workflow, learning)


def measure_once(provider: DeterministicCoachProvider, index: int) -> dict[str, Any]:
    """Run one streamed turn and return event marks in ms from dispatch."""
    with tempfile.TemporaryDirectory() as tmp:
        store = StudentStore(Path(tmp) / "stream.sqlite3")
        thread_id = store.create_thread(model_id="mock", support_mode="critical-thinking")
        coach = _service(store, provider)
        request = CoachRequest(
            thread_id=thread_id,
            student_message=_MESSAGE,
            current_stage="problem_identification",
            response_detail="long",
            idempotency_key=f"first-text-{index}",
        )
        options = (
            {"reply_deltas": True}
            if "reply_deltas" in inspect.signature(coach_events).parameters
            else {}
        )
        marks: dict[str, float] = {}
        delta_count = 0
        started = time.perf_counter()
        for item in coach_events(coach, request, **options):
            if isinstance(item, BaseException):
                raise item
            elapsed = (time.perf_counter() - started) * 1000.0
            kind = str(item.get("event"))
            if kind == "reply_delta":
                delta_count += 1
            marks.setdefault(kind, elapsed)
        first_visible = marks.get("reply_delta", marks["reply_ready"])
        return {
            "started_ms": marks["started"],
            "first_reply_delta_ms": marks.get("reply_delta"),
            "reply_ready_ms": marks["reply_ready"],
            "done_ms": marks["done"],
            "first_visible_text_ms": first_visible,
            "first_visible_event": "reply_delta" if "reply_delta" in marks else "reply_ready",
            "reply_delta_events": delta_count,
        }


def _summary(rows: list[dict[str, Any]], key: str) -> dict[str, float] | None:
    values = [row[key] for row in rows if row.get(key) is not None]
    if not values:
        return None
    return {
        "median": round(statistics.median(values), 1),
        "min": round(min(values), 1),
        "max": round(max(values), 1),
    }


def run_mode(name: str, provider: DeterministicCoachProvider, runs: int) -> dict[str, Any]:
    rows = [measure_once(provider, index) for index in range(runs)]
    return {
        "mode": name,
        "runs": runs,
        "first_visible_event": rows[0]["first_visible_event"],
        "reply_delta_events_per_run": rows[0]["reply_delta_events"],
        "first_visible_text_ms": _summary(rows, "first_visible_text_ms"),
        "first_reply_delta_ms": _summary(rows, "first_reply_delta_ms"),
        "reply_ready_ms": _summary(rows, "reply_ready_ms"),
        "done_ms": _summary(rows, "done_ms"),
    }


def _git_sha() -> str:
    try:
        return subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"], cwd=_PROJECT_ROOT,
            capture_output=True, text=True, check=True, timeout=10,
        ).stdout.strip()
    except Exception:
        return "unknown"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--runs", type=int, default=15, help="Repetitions per mode.")
    parser.add_argument("--ttft-ms", type=float, default=150.0, help="Stand-in time to first token.")
    parser.add_argument("--chunk-ms", type=float, default=20.0, help="Stand-in pause per chunk.")
    parser.add_argument("--label", default="", help="Free text recorded in the output, e.g. before or after.")
    parser.add_argument("--json-output", help="Write the result JSON to this path.")
    parser.add_argument("--i-approve-live-aws", action="store_true", help="Rejected. This script never calls AWS.")
    args = parser.parse_args(argv)
    if args.i_approve_live_aws:
        print("This measurement refuses live AWS.", file=sys.stderr)
        return 2
    if args.runs < 1:
        parser.error("--runs must be at least 1")
    plain = run_mode("plain_mock", DeterministicCoachProvider(StageDecision.STAY), args.runs)
    simulated = run_mode(
        "simulated_latency_mock", SimulatedLatencyProvider(args.ttft_ms, args.chunk_ms), args.runs
    )
    result = {
        "label": args.label,
        "git_sha": _git_sha(),
        "utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "provider": "mock",
        "real_model": False,
        "simulated": {"ttft_ms": args.ttft_ms, "chunk_ms": args.chunk_ms, "words_per_chunk": 4},
        "modes": [plain, simulated],
    }
    text = json.dumps(result, indent=2, sort_keys=True)
    print(text)
    if args.json_output:
        Path(args.json_output).write_text(text + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
