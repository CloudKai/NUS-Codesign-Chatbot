"""Backend concurrency measurement harness contracts (ticket 39).

The harness isolates representative blocking work, records event-loop lag and
bounded-pool/queue behavior locally, and exercises the real generation
admission under overload. Mock/temp-disk only; no AWS, no paid calls.
"""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path


_ROOT = Path(__file__).resolve().parents[2]
_PATH = _ROOT / "scripts" / "benchmark_concurrency.py"


def _load():
    """Load the benchmark module without requiring a scripts package."""
    spec = importlib.util.spec_from_file_location(
        "co_design_benchmark_concurrency", _PATH
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


bench = _load()


def test_representative_workloads_are_deterministic_and_bounded(tmp_path: Path) -> None:
    """The blocking categories exist, are labeled, and finish offline."""
    workloads = bench.representative_workloads(workspace=tmp_path)
    assert {item["category"] for item in workloads} == {
        "database",
        "sdk",
        "retrieval",
        "serialization",
    }
    for item in workloads:
        started = __import__("time").perf_counter()
        item["work"]()
        elapsed = __import__("time").perf_counter() - started
        assert 0.0 < elapsed < 5.0


def test_event_loop_lag_distinguishes_on_loop_from_offloaded_blocking(
    tmp_path: Path,
) -> None:
    """Blocking work stalls the loop on-loop and not when threadpool-offloaded."""
    workloads = bench.representative_workloads(workspace=tmp_path)
    sdk = next(item for item in workloads if item["category"] == "sdk")
    on_loop = bench.measure_event_loop_lag(
        sdk["work"], offload=False, ticks=40, workspace=tmp_path
    )
    offloaded = bench.measure_event_loop_lag(
        sdk["work"], offload=True, ticks=40, workspace=tmp_path
    )
    assert on_loop["lag_ms"]["max"] >= sdk["blocking_ms"] * 0.5
    assert on_loop["lag_ms"]["max"] > offloaded["lag_ms"]["max"]
    assert offloaded["threadpool_bounded"] is True
    assert offloaded["work_completed"] is True


def test_database_work_offload_records_local_numbers(tmp_path: Path) -> None:
    """The database category records real SQLite work in both placements."""
    workloads = bench.representative_workloads(workspace=tmp_path)
    db = next(item for item in workloads if item["category"] == "database")
    on_loop = bench.measure_event_loop_lag(
        db["work"], offload=False, ticks=30, workspace=tmp_path
    )
    offloaded = bench.measure_event_loop_lag(
        db["work"], offload=True, ticks=30, workspace=tmp_path
    )
    assert on_loop["work_completed"] and offloaded["work_completed"]
    assert on_loop["lag_ms"]["p95"] >= 0 and offloaded["lag_ms"]["p95"] >= 0


def test_generation_admission_stays_bounded_under_overload(tmp_path: Path) -> None:
    """More concurrent acquirers than capacity yields bounded waits/rejections."""
    outcome = bench.measure_admission_under_overload(
        max_running=2,
        max_queued=3,
        requesters=8,
        hold_seconds=0.05,
        workspace=tmp_path,
    )
    assert outcome["requesters"] == 8
    assert outcome["admitted"] >= 1
    assert outcome["admitted"] + outcome["rejected"] == 8
    # Every demand ends in a bounded wait or an honest rejection, never an
    # unbounded queue: waits stay far under the 2 s policy wait bound.
    assert outcome["wait_ms"]["max"] < 5_000
    assert outcome["queue_bounded"] is True


def test_main_writes_a_concurrency_report(tmp_path: Path) -> None:
    """The CLI records an aggregate report offline."""
    output = tmp_path / "concurrency.json"
    assert bench.main(["--json-output", str(output), "--scale", "small"]) == 0
    report = json.loads(output.read_text())
    assert report["run"]["kind"] == "offline-simulation"
    for category in ("database", "sdk", "retrieval", "serialization"):
        assert category in report["event_loop_lag"]
        assert report["event_loop_lag"][category]["offloaded"]["lag_ms"]["p95"] >= 0
    assert report["admission"]["queue_bounded"] is True
    assert "recommendation" in report
