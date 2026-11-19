"""Check the offline Laya memory and latency harness with stand-in classifiers."""

from __future__ import annotations

import json
import threading
from types import SimpleNamespace
from typing import Any

import pytest

from scripts.evals import benchmark_course_intent as bench


def _rows(count: int) -> list[Any]:
    return [SimpleNamespace(id=f"r{i}", message="what is a job story?", history=()) for i in range(count)]


def test_percentile_uses_nearest_rank_and_handles_empty() -> None:
    values = [float(n) for n in range(1, 101)]
    assert bench.percentile(values, 50) == 50.0
    assert bench.percentile(values, 95) == 95.0
    assert bench.percentile(values, 99) == 99.0
    assert bench.percentile([7.0], 95) == 7.0
    assert bench.percentile([], 95) is None
    assert bench.latency_summary([])["calls"] == 0


def test_memory_snapshot_reports_resident_and_peak() -> None:
    snapshot = bench.memory_snapshot()
    assert snapshot["peak_rss_mib"] > 0
    assert snapshot["source"] in {"/proc/self/status", "getrusage"}


def test_score_rows_counts_scored_busy_and_failed_calls() -> None:
    class Mixed:
        def score(self, message: str, history: Any, titles: Any) -> float | None:
            if message == "boom":
                raise RuntimeError("inference failed")
            return None if message == "busy" else 0.9

    rows = [
        SimpleNamespace(id="a", message="ok", history=()),
        SimpleNamespace(id="b", message="busy", history=()),
        SimpleNamespace(id="c", message="boom", history=()),
    ]
    result = bench.score_rows(Mixed(), rows, ["Week 2"], concurrency=1)
    assert (result["calls"], result["scored"]) == (3, 1)
    assert (result["abstained_or_busy"], result["errors"]) == (1, 1)
    assert result["latency_of_scored_calls"]["calls"] == 1


def test_single_slot_classifier_abstains_under_concurrency() -> None:
    gate = threading.Event()

    class Slow:
        def __init__(self) -> None:
            self._lock = threading.Lock()

        def score(self, message: str, history: Any, titles: Any) -> float | None:
            if not self._lock.acquire(blocking=False):
                return None
            try:
                gate.wait(timeout=0.2)
                return 0.5
            finally:
                self._lock.release()

    result = bench.score_rows(Slow(), _rows(8), [], concurrency=8)
    assert result["scored"] >= 1
    assert result["abstained_or_busy"] >= 1
    assert result["scored"] + result["abstained_or_busy"] == 8


def test_main_with_stub_writes_marked_json(tmp_path, capsys) -> None:
    output = tmp_path / "bench.json"
    code = bench.main(
        ["--stub-ms", "0", "--passes", "2", "--warmup", "1", "--json-output", str(output)]
    )
    assert code == 0
    data = json.loads(output.read_text(encoding="utf-8"))
    assert json.loads(capsys.readouterr().out)["classifier_kind"] == "stub"
    assert data["classifier_kind"] == "stub" and data["real_model"] is False
    assert data["eligible_rows"] > 0 and data["gate_messages"] == 295
    assert len(data["passes"]) == 2
    assert data["warmup_calls"] == 1 and data["first_call_ms"] is not None
    assert data["passes"][0]["scored"] == data["eligible_rows"]
    assert data["memory"]["peak_rss_mib"] > 0
    assert "not production hardware" in data["environment"]["measured_on"]
    assert data["run"]["generated_at_utc"]


@pytest.mark.parametrize(
    "argv",
    [[], ["--checkpoint", "x", "--stub-ms", "1"], ["--bundle", "b.zip", "--stub-ms", "1"], ["--stub-ms", "-1"]],
)
def test_main_rejects_ambiguous_or_invalid_sources(argv: list[str]) -> None:
    with pytest.raises(SystemExit):
        bench.main(argv)


def test_real_classifier_without_laya_package_fails_clearly(tmp_path, monkeypatch) -> None:
    import sys

    checkpoint = tmp_path / "ckpt"
    checkpoint.mkdir()
    (checkpoint / "model.safetensors").touch()
    monkeypatch.setitem(sys.modules, "laya", None)
    with pytest.raises(ImportError):
        bench.main(["--checkpoint", str(checkpoint)])
