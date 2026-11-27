"""Offline DSQL connection/pooling benchmark harness contracts.

Ticket 38: a reproducible, offline experiment that separates fresh IAM
connection setup from SQL/transaction time, evaluates a bounded psycopg-style
pool candidate against the documented constraints, records actual local
numbers, and never contacts AWS. Live runs stay operator-gated.
"""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[2]
_PATH = _ROOT / "scripts" / "benchmark_dsql_connections.py"


def _load():
    """Load the benchmark module without requiring a scripts package."""
    spec = importlib.util.spec_from_file_location(
        "co_design_benchmark_dsql_connections", _PATH
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


bench = _load()


def test_offline_benchmark_records_local_numbers_for_both_strategies(
    tmp_path: Path,
) -> None:
    """The offline harness runs both strategies and records real local timings."""
    report = bench.run_benchmark(
        transactions_per_strategy=12,
        concurrency=3,
        simulated_connect_ms=5.0,
        workspace=tmp_path,
    )
    assert report["run"]["kind"] == "offline-simulation"
    assert "not live DSQL results" in report["limits_note"]
    strategies = report["strategies"]
    assert set(strategies) == {"fresh", "pooled"}
    for name, numbers in strategies.items():
        assert numbers["transactions"] == 12
        assert numbers["connections_opened"] >= 1
        assert numbers["wall_seconds"] > 0
        assert numbers["per_transaction_ms"]["p50"] > 0
        assert numbers["per_transaction_ms"]["p95"] >= numbers["per_transaction_ms"]["p50"]
        assert numbers["sql_only_ms"]["p50"] > 0
    # The fresh strategy opens one connection per transaction; the bounded
    # pool reuses connections, so it cannot have opened more.
    assert strategies["fresh"]["connections_opened"] == 12
    assert strategies["pooled"]["connections_opened"] < 12


def test_benchmark_report_carries_documentation_and_a_decision(tmp_path: Path) -> None:
    """Verified DSQL documentation and an explicit keep/change decision."""
    report = bench.run_benchmark(
        transactions_per_strategy=4,
        concurrency=2,
        simulated_connect_ms=1.0,
        workspace=tmp_path,
    )
    claims = {item["claim"]: item for item in report["documentation_verification"]}
    assert claims["connection_rate_limit"]["detail"] == "100 new connections/second (burst 1,000)"
    assert claims["max_connection_age"]["detail"] == "hard 1-hour maximum connection age"
    assert claims["recommended_pool_bounds"]["min_size"] == 2
    assert claims["recommended_pool_bounds"]["max_size"] == 20
    assert claims["recommended_pool_bounds"]["max_lifetime_seconds"] == 55 * 60
    assert all(item["source_url"] for item in claims.values())
    decision = report["recommendation"]
    assert decision["decision"] == "keep-fresh-connection-default"
    assert "no pooling default" in decision["rationale"]


def test_pool_candidate_satisfies_the_documented_constraints(tmp_path: Path) -> None:
    """Bounded acquisition/size/lifetime, reset, isolation and clean shutdown."""
    results = bench.run_pool_contract_checks(workspace=tmp_path)
    passed = {item["check"]: item["passed"] for item in results}
    assert passed == {
        "bounded_acquisition": True,
        "bounded_size": True,
        "lifetime_replacement": True,
        "unhealthy_replacement": True,
        "release_via_context_manager": True,
        "rollback_reset_on_error": True,
        "whole_transaction_occ_retry": True,
        "no_cross_owner_contamination": True,
        "clean_shutdown": True,
    }


def test_live_mode_is_refused_without_explicit_operator_opt_in(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture
) -> None:
    """No live AWS run can start without the explicit cap environment."""
    monkeypatch.delenv("DSQL_BENCH_ALLOW_LIVE", raising=False)
    with pytest.raises(SystemExit) as excinfo:
        bench.main(["--live", "--json-output", str(tmp_path / "live.json")])
    assert excinfo.value.code == 2
    assert "DSQL_BENCH_ALLOW_LIVE" in capsys.readouterr().err
    assert not (tmp_path / "live.json").exists()


def test_main_writes_a_report_file(tmp_path: Path) -> None:
    """The CLI writes a JSON report and exits 0 in offline mode."""
    output = tmp_path / "report.json"
    assert bench.main(["--json-output", str(output)]) == 0
    report = json.loads(output.read_text())
    assert report["run"]["kind"] == "offline-simulation"
    assert report["parameters"]["transactions_per_strategy"] > 0
