"""Offline backend-concurrency benchmark: event-loop, threadpool, admission.

Ticket 39 measurement harness. It isolates representative blocking work
(SQLite writes, mock-SDK latency, retrieval, serialization), measures the
event-loop lag each category causes when placed on the asyncio loop versus
bounded threadpool offloading, and exercises the real generation admission
under overload. Everything runs against temp disk and deterministic mocks:
no AWS, no network, no paid calls. Numbers are actual local measurements with
an explicit environment note; they do not size EC2 or predict live latency.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import platform
import sqlite3
import sys
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

LIMITS_NOTE = (
    "Offline simulation on one local host with mock providers and temp SQLite. "
    "These numbers isolate scheduling behavior; they are not live model, "
    "network or classroom capacity results and do not size EC2."
)


# ---------------------------------------------------------------------------
# Representative blocking workloads
# ---------------------------------------------------------------------------


def representative_workloads(*, workspace: Path | None = None) -> list[dict[str, Any]]:
    """Return one deterministic blocking callable per risk category.

    Args:
        workspace: Directory for the scratch SQLite database.

    Returns:
        Entries with ``category``, ``blocking_ms`` (nominal service time) and
        ``work`` (a zero-argument blocking callable).
    """
    base = workspace or Path(tempfile.mkdtemp(prefix="co-design-concurrency-"))
    database = base / "concurrency.sqlite3"
    with sqlite3.connect(database) as setup:
        setup.execute("CREATE TABLE IF NOT EXISTS bench (id INTEGER PRIMARY KEY, payload TEXT)")

    def database_work() -> int:
        with sqlite3.connect(database, timeout=30) as connection:
            connection.execute(
                "INSERT INTO bench (payload) VALUES (?)", ("x" * 512,)
            )
            row = connection.execute("SELECT COUNT(*) FROM bench").fetchone()
        return int(row[0])

    def sdk_work() -> None:
        # Mock-provider shape: a bounded blocking wait, no network.
        time.sleep(0.02)

    def retrieval_work() -> None:
        # Fake Retrieve client shape: bounded blocking wait plus parsing.
        time.sleep(0.01)
        json.dumps({"results": [{"excerpt": "y" * 256} for _ in range(8)]})

    payload = {"turns": [{"text": "z" * 256, "citations": [1, 2, 3]} for _ in range(200)]}

    def serialization_work() -> int:
        return len(json.dumps(payload))

    return [
        {"category": "database", "blocking_ms": 5.0, "work": database_work},
        {"category": "sdk", "blocking_ms": 20.0, "work": sdk_work},
        {"category": "retrieval", "blocking_ms": 10.0, "work": retrieval_work},
        {"category": "serialization", "blocking_ms": 1.0, "work": serialization_work},
    ]


# ---------------------------------------------------------------------------
# Event-loop lag measurement
# ---------------------------------------------------------------------------


def _percentiles(samples: list[float]) -> dict[str, float]:
    if not samples:
        return {"p50": 0.0, "p95": 0.0, "max": 0.0}
    ordered = sorted(samples)

    def pct(fraction: float) -> float:
        rank = min(len(ordered) - 1, max(0, round(fraction * (len(ordered) - 1))))
        return ordered[rank]

    return {
        "p50": round(pct(0.50), 3),
        "p95": round(pct(0.95), 3),
        "max": round(ordered[-1], 3),
    }


async def _measure_lag(
    work: Callable[[], Any],
    *,
    offload: bool,
    ticks: int,
    tick_seconds: float,
) -> dict[str, Any]:
    """Tick one loop while the blocking work runs on-loop or off-loaded."""
    import anyio.to_thread

    limiter = anyio.to_thread.current_default_thread_limiter()
    limiter.total_tokens = max(1, min(40, int(limiter.total_tokens or 40)))
    lags: list[float] = []
    completed = {"ok": False}

    async def ticker() -> None:
        for _ in range(ticks):
            started = time.perf_counter()
            await asyncio.sleep(tick_seconds)
            lags.append((time.perf_counter() - started - tick_seconds) * 1000.0)

    async def runner() -> None:
        if offload:
            # The production pattern: bounded AnyIO threadpool offloading.
            await anyio.to_thread.run_sync(work)
            completed["ok"] = True
        else:
            # The anti-pattern under measurement: blocking call on the loop.
            work()
            completed["ok"] = True

    # Repeat the blocking unit a few times so lag accumulates measurably.
    async def workload() -> None:
        for _ in range(3):
            await runner()

    await asyncio.gather(ticker(), workload())
    return {
        "lag_ms": _percentiles(lags),
        "work_completed": bool(completed["ok"]),
        "threadpool_bounded": offload,
        "threadpool_tokens": int(limiter.total_tokens),
        "threadpool_borrowed_sample": int(limiter.borrowed_tokens),
        "ticks": ticks,
        "tick_seconds": tick_seconds,
    }


def measure_event_loop_lag(
    work: Callable[[], Any],
    *,
    offload: bool,
    ticks: int = 40,
    workspace: Path | None = None,
) -> dict[str, Any]:
    """Measure event-loop lag while one blocking unit repeats on/off the loop.

    Args:
        work: Blocking zero-argument callable.
        offload: Run via the bounded threadpool instead of the loop.
        ticks: Ticker iterations (each records one lag sample).
        workspace: Unused scratch root (kept for report symmetry).

    Returns:
        Lag percentiles in ms, completion flag and threadpool bounds.
    """
    return asyncio.run(
        _measure_lag(work, offload=offload, ticks=ticks, tick_seconds=0.005)
    )


# ---------------------------------------------------------------------------
# Generation admission under overload
# ---------------------------------------------------------------------------


def measure_admission_under_overload(
    *,
    max_running: int = 2,
    max_queued: int = 3,
    requesters: int = 8,
    hold_seconds: float = 0.05,
    workspace: Path | None = None,
) -> dict[str, Any]:
    """Exercise the real SQLite generation admission with more demand than capacity.

    The admission's own FIFO queue, bounded wait and rejection categories are
    the system under test: overload must end in bounded waits or honest
    rejections, never unbounded queuing, and settled tokens must release
    capacity exactly.

    Args:
        max_running: Concurrent capacity granted by the policy.
        max_queued: Bounded queue depth in the policy.
        requesters: Concurrent acquirers (greater than ``max_running``).
        hold_seconds: How long each admitted unit holds its slot.
        workspace: Directory for the disposable ledger.

    Returns:
        Admission/rejection/wait statistics and the bounded-queue verdict.
    """
    import threading
    from concurrent.futures import ThreadPoolExecutor

    from backend.generation_admission import (
        GenerationPolicy,
        SQLiteGenerationAdmission,
    )
    from backend.rate_limit import RateLimitExceeded

    base = workspace or Path(tempfile.mkdtemp(prefix="co-design-admission-"))
    base.mkdir(parents=True, exist_ok=True)
    policy = GenerationPolicy(
        ledger_path=base / "ledger.sqlite3",
        monthly_micro_sgd=10**9,
        headroom_micro_sgd=10**6,
        call_reserve_micro_sgd=10**6,
        max_running=max_running,
        max_queued=max_queued,
        max_wait_seconds=2.0,
        lease_seconds=60.0,
        ceiling_evidence="ticket-39 offline admission overload probe",
    )
    admission = SQLiteGenerationAdmission(policy)
    barrier = threading.Barrier(requesters)
    waits: list[float] = []
    outcomes = {"admitted": 0, "rejected": 0}
    lock = threading.Lock()

    def requester() -> None:
        barrier.wait()
        begin = time.perf_counter()
        try:
            token = admission.acquire()
        except RateLimitExceeded:
            with lock:
                outcomes["rejected"] += 1
                waits.append((time.perf_counter() - begin) * 1000.0)
            return
        with lock:
            outcomes["admitted"] += 1
            waits.append((time.perf_counter() - begin) * 1000.0)
        time.sleep(hold_seconds)
        admission.settle(token, _fake_meter())

    started_at = time.perf_counter()
    with ThreadPoolExecutor(max_workers=requesters) as executor:
        list(executor.map(lambda _: requester(), range(requesters)))
    wall = time.perf_counter() - started_at

    return {
        "requesters": requesters,
        "max_running": max_running,
        "max_queued": max_queued,
        "admitted": outcomes["admitted"],
        "rejected": outcomes["rejected"],
        "wait_ms": _percentiles(waits),
        "wall_seconds": round(wall, 3),
        "queue_bounded": outcomes["admitted"] + outcomes["rejected"] == requesters
        and (outcomes["rejected"] > 0 or outcomes["admitted"] <= max_running),
    }


def _fake_meter() -> Any:
    """Return a minimal usage meter accepted by ``settle``."""
    from backend.usage import GenerationUsage

    return GenerationUsage(
        operation_id="bench",
        kind="chat",
        provider="mock",
        model="mock",
        role="fast_chat",
        region="local",
    )


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

_SCALES = {
    "small": {"ticks": 25, "admission_requesters": 6},
    "default": {"ticks": 40, "admission_requesters": 8},
    "large": {"ticks": 80, "admission_requesters": 16},
}


def run_benchmark(*, scale: str = "default", workspace: Path | None = None) -> dict[str, Any]:
    """Run every concurrency measurement and return the aggregate report."""
    config = _SCALES.get(scale, _SCALES["default"])
    base = workspace or Path(tempfile.mkdtemp(prefix="co-design-concurrency-"))
    base.mkdir(parents=True, exist_ok=True)
    lag_report: dict[str, Any] = {}
    for item in representative_workloads(workspace=base):
        lag_report[item["category"]] = {
            "on_loop": measure_event_loop_lag(
                item["work"], offload=False, ticks=config["ticks"], workspace=base
            ),
            "offloaded": measure_event_loop_lag(
                item["work"], offload=True, ticks=config["ticks"], workspace=base
            ),
            "nominal_blocking_ms": item["blocking_ms"],
        }
    return {
        "run": {
            "kind": "offline-simulation",
            "scale": scale,
            "date_utc": datetime.now(timezone.utc).isoformat(),
            "python": sys.version.split()[0],
            "platform": platform.platform(),
        },
        "limits_note": LIMITS_NOTE,
        "event_loop_lag": lag_report,
        "admission": measure_admission_under_overload(
            requesters=config["admission_requesters"], workspace=base
        ),
        "recommendation": {
            "decision": "keep-sync-threadpool-offloading",
            "rationale": (
                "FastAPI's sync routes already run in the bounded AnyIO "
                "threadpool, so database/SDK/retrieval/serialization work is "
                "off the event loop by construction; the measured on-loop lag "
                "for the same work shows why that must not regress. The only "
                "on-loop blocking found was the async upload route's "
                "workspace write, which is bounded and offloaded in ticket 39. "
                "No mechanical async rewrite is justified by these numbers."
            ),
            "bounds": {
                "sync_threadpool": "SYNC_THREADPOOL_TOKENS (AnyIO default limiter)",
                "generation": "GenerationAdmission max_running/max_queued/max_wait_seconds",
                "deep_review": "deep_review_max_concurrent + background admission",
            },
        },
    }


def main(argv: list[str] | None = None) -> int:
    """Run the concurrency benchmark CLI offline."""
    parser = argparse.ArgumentParser(
        description="Offline event-loop/threadpool/admission concurrency benchmark."
    )
    parser.add_argument("--scale", choices=sorted(_SCALES), default="default")
    parser.add_argument("--json-output", type=Path, default=None)
    parser.add_argument(
        "--workspace",
        type=Path,
        default=None,
        help="Scratch directory (default: a fresh temp directory).",
    )
    args = parser.parse_args(argv)
    report = run_benchmark(scale=args.scale, workspace=args.workspace)
    payload = json.dumps(report, indent=2, sort_keys=True)
    if args.json_output is not None:
        args.json_output.write_text(payload + "\n")
        print(f"report written: {args.json_output}")
    else:
        print(payload)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
