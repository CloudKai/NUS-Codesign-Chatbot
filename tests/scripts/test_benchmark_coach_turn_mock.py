"""Mock coach-turn benchmark: isolated SQLite only, no AWS."""

from __future__ import annotations

import importlib.util
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[2]
_PATH = _ROOT / "scripts" / "benchmark_coach_turn_mock.py"


def _load():
    """Load the benchmark module without requiring a scripts package."""
    spec = importlib.util.spec_from_file_location(
        "co_design_benchmark_coach_turn_mock", _PATH
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


_BENCH = _load()


def test_live_aws_flag_is_refused() -> None:
    assert _BENCH.main(["--i-approve-live-aws"]) == 2


def test_fresh_bucket_uses_mock_provider_and_no_agentcore() -> None:
    row = _BENCH.measure_bucket(0)
    assert row["history_size"] == 0
    assert row["provider"] == "mock"
    assert row["agentcore_invokes"] == 0
    assert row["event_loop_cycle_count"] is None
    assert int(row["submit_ms"]) >= 0
    assert str(row["recommendation"])
