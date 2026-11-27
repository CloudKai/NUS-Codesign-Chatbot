"""Offline cost-scenario and regional trade-off renderer contracts (ticket 49).

Ticket 49: low/expected/high monthly SGD scenarios with dated public-pricing
estimates, measured local anchors from tickets 38/39/40/48 clearly labelled,
gross/credits/cash/post-credit distinction, honest unresolved S$30 assessment,
and documented regional trade-offs — all offline, no live calls.
"""

from __future__ import annotations

import ast
import importlib.util
import json
import sys
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[2]
_PATH = _ROOT / "scripts" / "cost_scenarios.py"
_CONFIG = _ROOT / "docs" / "examples" / "cost-scenarios" / "scenarios-2026-11.json"

CATEGORIES = {
    "hosting", "generation", "retrieval", "ingestion", "storage", "backups",
    "observability", "network", "other",
}


def _load():
    """Load the scenario renderer module without requiring a scripts package."""
    spec = importlib.util.spec_from_file_location("co_design_cost_scenarios", _PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _render(config: Path):
    """Render the report through the public CLI entry point."""
    module = _load()
    return module.main(["--config", str(config)])


def test_shipped_config_renders_three_complete_scenarios() -> None:
    """The shipped reproducible command renders low/expected/high scenarios."""
    exit_code = _render(_CONFIG)
    assert exit_code == 0


def test_every_scenario_covers_all_cost_categories(tmp_path: Path) -> None:
    """Each scenario carries all nine inventory categories exactly once."""
    module = _load()
    report = module.build_report(_CONFIG.read_text())
    assert [scenario["name"] for scenario in report["scenarios"]] == [
        "low", "expected", "high",
    ]
    for scenario in report["scenarios"]:
        categories = [line["category"] for line in scenario["lines"]]
        assert set(categories) == CATEGORIES


def test_priced_subtotals_increase_and_are_labelled_estimates() -> None:
    """Priced subtotals rise from low to high while DSQL activity is unmeasured."""
    module = _load()
    report = module.build_report(_CONFIG.read_text())
    totals = [float(scenario["priced_subtotal_sgd"]) for scenario in report["scenarios"]]
    assert totals[0] < totals[1] < totals[2]
    for scenario in report["scenarios"]:
        assert scenario["estimated_gross_sgd"] is None
        for line in scenario["lines"]:
            if line["cost_basis"] == "estimate":
                assert line["price_as_of"] <= report["as_of"]
                assert line["evidence"].strip()
            elif line["cost_basis"] == "not_applicable":
                assert float(line["gross_sgd"]) == 0.0
                assert line["evidence"].strip()
        assert scenario["bill_verified"] is False
        assert "not a bill" in scenario["totals_note"]


def test_dsql_uses_regional_activity_and_storage_rates() -> None:
    """Show Oregon list rates and leave gross unknown until DPU usage is supplied."""
    report = _load().build_report(_CONFIG.read_text())
    for scenario, expected_storage in zip(report["scenarios"], ("0.858000", "2.145000", "6.435000"), strict=True):
        activity, storage = (
            line for line in scenario["lines"] if line["name"].startswith("Aurora DSQL")
        )
        assert (activity["unit"], activity["unit_price_usd"]) == ("DPU", "0.000008")
        assert activity["quantity"] is None
        assert activity["gross_sgd"] is None
        assert activity["price_as_of"] == "2026-09-11"
        assert (storage["unit"], storage["unit_price_usd"]) == ("GB-month", "0.33")
        assert storage["gross_sgd"] == expected_storage
        assert storage["price_as_of"] == "2026-09-11"
        assert scenario["unknowns"] == ["gross:Aurora DSQL activity"]
        assert all(line["unit"] not in {"DSQLU-hour", "Mrequests"} for line in scenario["lines"]
                   if "DSQL" in line["name"])


def test_measured_local_anchors_are_labelled_and_sourced() -> None:
    """Measured ticket-38/39/40/48 numbers appear as labelled anchors, never as live cost truth."""
    module = _load()
    report = module.build_report(_CONFIG.read_text())
    anchors = report["measured_local_anchors"]
    sources = " ".join(anchor["source"] for anchor in anchors)
    for ticket in ("ticket 38", "ticket 39", "ticket 40", "ticket 48"):
        assert ticket in sources
    for anchor in anchors:
        assert anchor["measured"] is True
        assert anchor["source"].strip()
    for scenario in report["scenarios"]:
        for line in scenario["lines"]:
            assert line["quantity_basis"] in {"measured_local", "assumption", "unknown"}


def test_credits_cash_and_post_credit_are_distinguished_honestly() -> None:
    """No verified credit balance exists, so credits/cash stay null and gross is the baseline."""
    module = _load()
    report = module.build_report(_CONFIG.read_text())
    for scenario in report["scenarios"]:
        assert scenario["credits_sgd"] is None
        assert scenario["cash_sgd"] is None
        assert scenario["credit_runway_months"] is None
        assert scenario["post_credit_baseline_note"]


def test_s30_gate_stays_unresolved_with_all_three_totals() -> None:
    """The report assesses the S$30 objective honestly without claiming feasibility."""
    module = _load()
    report = module.build_report(_CONFIG.read_text())
    assessment = report["s30_assessment"]
    assert assessment["status"] == "unresolved"
    assert assessment["objective_sgd"] == "30.000000"
    for scenario in report["scenarios"]:
        assert f"{scenario['name']} unknown" in assessment["statement"]
        assert scenario["priced_subtotal_sgd"] in assessment["statement"]
    assert "feasib" not in assessment["statement"].lower().replace("infeasible", "")


def test_regional_trade_offs_are_documented_without_live_claims() -> None:
    """Regional rows cite the documented us-west-2 topology; only recorded datapoints are measured."""
    module = _load()
    report = module.build_report(_CONFIG.read_text())
    rows = report["regional_assessment"]
    assert len(rows) >= 5
    documented = " ".join(row["documented_evidence"] for row in rows)
    assert "compose.prod.yaml" in documented
    assert "us-west-2" in documented
    for row in rows:
        assert row["latency_basis"] in {"measured", "estimate", "unknown"}
        if row["latency_basis"] == "measured":
            assert row["measured_source"].strip()
        else:
            assert row["measured_source"] is None
        assert "no automatic region migration" in row["migration_note"].lower()


def test_unknown_price_line_nulls_scenario_totals(tmp_path: Path) -> None:
    """An unknown-basis line suppresses the scenario total and is named in unknowns."""
    module = _load()
    config = json.loads(_CONFIG.read_text())
    config["scenarios"] = [dict(config["scenarios"][0], name="only")]
    lines = config["scenarios"][0]["lines"]
    activity = next(line for line in lines if line["name"] == "Aurora DSQL activity")
    activity.update(quantity="1000000", quantity_basis="assumption", cost_basis="estimate")
    complete = module.build_report(json.dumps(config))["scenarios"][0]
    assert complete["estimated_gross_sgd"] == "41.304250"
    lines.append({
        "category": "hosting",
        "name": "Unverifiable mystery service",
        "quantity": None,
        "unit": "month",
        "unit_price_usd": None,
        "cost_basis": "unknown",
        "quantity_basis": "unknown",
        "evidence": "No price evidence is available for this line.",
    })
    path = tmp_path / "broken.json"
    path.write_text(json.dumps(config))
    report = module.build_report(path.read_text())
    scenario = report["scenarios"][0]
    assert scenario["estimated_gross_sgd"] is None
    assert scenario["priced_subtotal_sgd"] == complete["estimated_gross_sgd"]
    assert any("Unverifiable mystery service" in item for item in scenario["unknowns"])


def test_invalid_config_exits_two_without_echoing_content(
    tmp_path: Path, capsys: pytest.CaptureFixture[str],
) -> None:
    """Invalid input returns exit 2 with a generic message and no echoed payload."""
    bad = tmp_path / "bad.json"
    bad.write_text(json.dumps({"scenarios": "not-a-list"}))
    module = _load()
    assert module.main(["--config", str(bad)]) == 2
    captured = capsys.readouterr()
    assert captured.out.strip() == ""
    assert captured.err.strip()


def test_renderer_is_offline_static() -> None:
    """The script imports no network, AWS or database client at module level."""
    tree = ast.parse(_PATH.read_text())
    forbidden = {"boto3", "botocore", "requests", "httpx", "urllib", "socket", "psycopg"}
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            assert node.names[0].name.split(".")[0] not in forbidden
        elif isinstance(node, ast.ImportFrom) and node.module:
            assert node.module.split(".")[0] not in forbidden
