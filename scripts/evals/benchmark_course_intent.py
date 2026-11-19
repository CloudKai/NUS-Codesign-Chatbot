"""Measure load time, memory and per-call latency of the local course-intent classifier.

Offline only: sockets are blocked and ``HF_HUB_OFFLINE`` is set. It scores the
gate messages that are eligible for the local classifier (the same eligibility
the API uses), one call per row and pass, with the real turn context (message,
earlier student messages, course titles). The classifier runs inline in the
request thread before generation, so a call's wall time is the latency it adds
to that turn.

Exactly one classifier source is required:

* ``--checkpoint DIR`` (and optionally ``--bundle ZIP``): the real Laya or Laya
  Learn classifier from ``backend.course_intent``. Needs the ``laya`` package
  (and ``vegaml`` for a bundle) and local weights.
* ``--stub-ms MS``: a stand-in that sleeps MS milliseconds. It checks the
  harness only. Its numbers say nothing about Laya and the output is marked so.

Every figure describes the machine it ran on. The output says so; it is not a
production-hardware measurement unless it was run on that hardware.
"""

from __future__ import annotations

import argparse
import importlib.metadata
import os
import platform
import statistics
import sys
import threading
from collections.abc import Mapping, Sequence
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from time import perf_counter, sleep
from typing import Any

_PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

_BYTES_PER_MIB = 1024 * 1024


def memory_snapshot() -> dict[str, Any]:
    """Return this process's resident and peak resident memory in MiB.

    Reads ``/proc/self/status`` (``VmRSS``, ``VmHWM``) where it exists and falls
    back to ``resource.getrusage`` (peak only) elsewhere.
    """
    status = Path("/proc/self/status")
    if status.is_file():
        values: dict[str, float] = {}
        for line in status.read_text(encoding="utf-8").splitlines():
            key, _, rest = line.partition(":")
            if key in {"VmRSS", "VmHWM"}:
                values[key] = int(rest.split()[0]) / 1024  # kB to MiB
        if {"VmRSS", "VmHWM"} <= values.keys():
            return {
                "rss_mib": round(values["VmRSS"], 1),
                "peak_rss_mib": round(values["VmHWM"], 1),
                "source": "/proc/self/status",
            }
    import resource

    peak = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    # Linux reports kB, macOS reports bytes.
    peak_mib = peak / _BYTES_PER_MIB if sys.platform == "darwin" else peak / 1024
    return {"rss_mib": None, "peak_rss_mib": round(peak_mib, 1), "source": "getrusage"}


def percentile(values: Sequence[float], q: int) -> float | None:
    """Return the nearest-rank percentile ``q`` of ``values`` (None when empty)."""
    if not values:
        return None
    ordered = sorted(values)
    return round(ordered[max(0, (q * len(ordered) + 99) // 100 - 1)], 2)


def latency_summary(values: Sequence[float]) -> dict[str, Any]:
    """Summarize call times in milliseconds."""
    return {
        "calls": len(values),
        "mean_ms": round(statistics.fmean(values), 2) if values else None,
        "p50_ms": percentile(values, 50),
        "p95_ms": percentile(values, 95),
        "p99_ms": percentile(values, 99),
        "max_ms": round(max(values), 2) if values else None,
    }


class StubClassifier:
    """Sleep for a fixed time and return a fixed score. Not a model."""

    def __init__(self, delay_ms: float) -> None:
        self._delay = delay_ms / 1000
        self._inference = threading.Lock()

    def score(
        self, message: str, history: Sequence[Mapping[str, Any]], titles: Sequence[str]
    ) -> float | None:
        """Hold the single slot for the delay, or abstain when busy (like the real adapters)."""
        if not self._inference.acquire(blocking=False):
            return None
        try:
            sleep(self._delay)
            return 0.5
        finally:
            self._inference.release()


def package_versions() -> dict[str, str | None]:
    """Return installed versions of the packages that decide memory and speed."""
    versions: dict[str, str | None] = {}
    for name in ("laya", "vegaml", "torch", "transformers", "safetensors", "numpy"):
        try:
            versions[name] = importlib.metadata.version(name)
        except importlib.metadata.PackageNotFoundError:
            versions[name] = None
    return versions


def environment_block() -> dict[str, Any]:
    """Describe the machine and runtime the figures were taken on."""
    torch_threads = None
    if "torch" in sys.modules:
        torch_threads = sys.modules["torch"].get_num_threads()
    return {
        "measured_on": "this machine only; not production hardware unless run there",
        "platform": platform.platform(),
        "machine": platform.machine(),
        "python": platform.python_version(),
        "cpu_count": os.cpu_count(),
        "torch_threads": torch_threads,
        "packages": package_versions(),
    }


def build_classifier(args: argparse.Namespace) -> tuple[Any, str]:
    """Return ``(classifier, kind)`` for the chosen source."""
    if args.stub_ms is not None:
        return StubClassifier(args.stub_ms), "stub"
    from backend.course_intent import LayaCourseIntentClassifier, LayaLearnCourseIntentClassifier

    if args.bundle is not None:
        return LayaLearnCourseIntentClassifier(args.checkpoint, args.bundle), "laya_learn"
    return LayaCourseIntentClassifier(args.checkpoint), "laya"


def score_rows(
    classifier: Any,
    rows: Sequence[Any],
    titles: Sequence[str],
    *,
    concurrency: int,
) -> dict[str, Any]:
    """Score ``rows`` once each and return per-call timings and outcome counts.

    A ``None`` score is a busy or abstaining call. An exception is counted and
    the call is left out of the latency figures, as the API treats it as no score.
    """

    def one(row: Any) -> tuple[str, float, float | None, bool]:
        started = perf_counter()
        try:
            score = classifier.score(row.message, row.history, titles)
            failed = False
        except Exception:  # production logs the category and continues without a score
            score, failed = None, True
        return row.id, (perf_counter() - started) * 1000, score, failed

    started = perf_counter()
    if concurrency == 1:
        results = [one(row) for row in rows]
    else:
        with ThreadPoolExecutor(max_workers=concurrency) as pool:
            results = list(pool.map(one, rows))
    wall = perf_counter() - started
    scored = [ms for _, ms, score, failed in results if score is not None and not failed]
    return {
        "concurrency": concurrency,
        "calls": len(results),
        "scored": len(scored),
        "abstained_or_busy": sum(score is None and not failed for _, _, score, failed in results),
        "errors": sum(failed for *_, failed in results),
        "wall_seconds": round(wall, 3),
        "latency_of_scored_calls": latency_summary(scored),
    }


def run_benchmark(args: argparse.Namespace, rows: Sequence[Any], titles: Sequence[str]) -> dict[str, Any]:
    """Load the classifier, warm it, then time ``args.passes`` passes over ``rows``."""
    memory_before = memory_snapshot()
    load_started = perf_counter()
    classifier, kind = build_classifier(args)
    load_ms = (perf_counter() - load_started) * 1000
    memory_loaded = memory_snapshot()
    for row in rows[: args.warmup]:
        classifier.score(row.message, row.history, titles)
    memory_warm = memory_snapshot()
    passes = [
        score_rows(classifier, rows, titles, concurrency=args.concurrency)
        for _ in range(args.passes)
    ]
    memory_after = memory_snapshot()
    return {
        "classifier_kind": kind,
        "real_model": kind != "stub",
        "load_ms": round(load_ms, 2),
        "warmup_calls": min(args.warmup, len(rows)),
        "memory": {
            "before_load": memory_before,
            "after_load": memory_loaded,
            "after_warmup": memory_warm,
            "after_passes": memory_after,
            "load_delta_rss_mib": _delta(memory_loaded, memory_before, "rss_mib"),
            "peak_rss_mib": memory_after["peak_rss_mib"],
        },
        "passes": passes,
    }


def _delta(after: Mapping[str, Any], before: Mapping[str, Any], key: str) -> float | None:
    if after.get(key) is None or before.get(key) is None:
        return None
    return round(after[key] - before[key], 1)


def build_parser() -> argparse.ArgumentParser:
    """Build the command line."""
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--checkpoint", type=Path, help="local Laya or Vega checkpoint directory")
    parser.add_argument("--bundle", type=Path, help="Laya Learn bundle ZIP (needs --checkpoint)")
    parser.add_argument(
        "--stub-ms", type=float, help="use a stand-in classifier that sleeps this long (harness check)"
    )
    parser.add_argument("--passes", type=int, default=3, help="timed passes over the eligible rows")
    parser.add_argument("--warmup", type=int, default=5, help="untimed calls before the passes")
    parser.add_argument("--concurrency", type=int, default=1, help="worker threads per pass")
    parser.add_argument("--json-output", type=Path, help="write the result as JSON")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """Run the benchmark offline and print the result as JSON."""
    import json

    parser = build_parser()
    args = parser.parse_args(argv)
    if (args.stub_ms is None) == (args.checkpoint is None):
        parser.error("give exactly one of --checkpoint or --stub-ms")
    if args.bundle is not None and args.checkpoint is None:
        parser.error("--bundle needs --checkpoint")
    if args.stub_ms is not None and args.stub_ms < 0:
        parser.error("--stub-ms must not be negative")
    if args.passes < 1 or args.warmup < 0 or args.concurrency < 1:
        parser.error("passes and concurrency must be positive and warmup not negative")

    os.environ["HF_HUB_OFFLINE"] = "1"
    from scripts.evals import evaluate_combined_gate as combined
    from scripts.evals import evaluate_retrieval as retrieval

    retrieval._block_network()
    materials = retrieval.load_materials(retrieval.MATERIALS_PATH)
    questions = retrieval.load_questions(retrieval.QUESTIONS_PATH, materials)
    messages = retrieval.load_messages(
        retrieval.MESSAGES_PATH, materials, [row["id"] for row in questions]
    )
    rows = [row for row in combined.prepare_rows(messages) if row.eligible]
    titles = retrieval.eval_course_titles(materials)
    result = {
        "gate_messages": len(messages),
        "eligible_rows": len(rows),
        "course_titles": len(titles),
        "environment": environment_block(),
        **run_benchmark(args, rows, titles),
    }
    if args.json_output is not None:
        retrieval._write_json_output(args.json_output, result)
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
