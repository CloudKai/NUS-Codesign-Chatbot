"""Render low/expected/high monthly SGD operating-cost scenarios offline.

Run from the repository root with ``python -m scripts.cost_scenarios``. The
renderer reads one explicit scenario configuration (dated public-pricing
estimates, measured local anchors, regional trade-off notes) and reports
gross/credits/cash/post-credit totals using the ticket-07 accounting
semantics. It never opens an account, a database or the network, never makes a
live call, and never turns an estimate into a verified bill.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import date
from decimal import Decimal, DecimalException, localcontext
from pathlib import Path
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from backend.cost_accounting import CATEGORIES, _amount

Money = Annotated[Decimal, Field(ge=0, le=Decimal("1e15"), max_digits=40, decimal_places=18, allow_inf_nan=False)]
Category = Literal[
    "hosting", "generation", "retrieval", "ingestion", "storage", "backups",
    "observability", "network", "other",
]

LIMITATIONS = [
    "Prices are dated planning inputs. Public list rates are identified by source where checked; other rates still need verification. No amounts are reconciled with a bill. Replace estimates with billing evidence before any gate decision.",
    "Gross estimates exclude GST/taxes and promotional credits. Account-wide Aurora DSQL free usage is not deducted; its availability and consumption on this account are unverified. A missing cost line leaves gross, post-credit baseline, and cash unknown.",
    "Measured anchors come from local mock/offline tickets (38/39/40/48) and the separately capped 2026-11-24 live checks; none is a live cost or latency measurement of the current production stack.",
    "Regional latency, availability and data-residency rows are documentation-based planning notes; no live regional call was made and no region migration is proposed or performed.",
    "This renderer makes no generation, admission, funding or deployment decision; the classroom cost/capacity release gates in CLASSROOM_CAPACITY_GATE.md remain open.",
]


class FxAssumption(BaseModel):
    """Operator-supplied planning FX rate; never a fetched market rate."""

    model_config = ConfigDict(extra="forbid")
    sgd_per_usd: Money
    as_of: date
    evidence: str = Field(min_length=1, max_length=500)


class ScenarioLine(BaseModel):
    """One monthly cost line with explicit measured/assumed quantity and dated price."""

    model_config = ConfigDict(extra="forbid")
    category: Category
    name: str = Field(min_length=1, max_length=160)
    quantity: Decimal | None = Field(default=None, ge=0)
    unit: str = Field(min_length=1, max_length=40)
    unit_price_usd: Decimal | None = Field(default=None, ge=0)
    cost_basis: Literal["estimate", "unknown", "not_applicable"]
    quantity_basis: Literal["measured_local", "assumption", "unknown"]
    price_as_of: date | None = None
    evidence: str = Field(min_length=1, max_length=500)

    @model_validator(mode="after")
    def valid_line(self) -> ScenarioLine:
        """Validate estimate inputs, including a listed rate with unknown quantity."""
        if self.cost_basis == "estimate":
            if self.quantity is None or self.unit_price_usd is None or self.price_as_of is None:
                raise ValueError("estimate lines require quantity, unit_price_usd and price_as_of")
        elif self.cost_basis == "unknown":
            if self.quantity is not None:
                raise ValueError("unknown lines must leave quantity null")
            if self.unit_price_usd is not None and self.price_as_of is None:
                raise ValueError("a published rate for unknown usage requires price_as_of")
        else:
            if self.quantity != 0 or self.unit_price_usd != 0:
                raise ValueError("not_applicable lines require explicit zero quantity and price")
        return self


class MeasuredAnchor(BaseModel):
    """A measured local number carried into the scenarios with its source."""

    model_config = ConfigDict(extra="forbid")
    label: str = Field(min_length=1, max_length=200)
    value: str = Field(min_length=1, max_length=500)
    source: str = Field(min_length=1, max_length=300)
    measured: Literal[True]


class RegionalRow(BaseModel):
    """A documentation-based regional trade-off note for one component."""

    model_config = ConfigDict(extra="forbid")
    component: str = Field(min_length=1, max_length=160)
    documented_region: str = Field(min_length=1, max_length=80)
    documented_evidence: str = Field(min_length=1, max_length=300)
    singapore_latency: str | None = None
    latency_basis: Literal["measured", "estimate", "unknown"]
    measured_source: str | None = None
    data_residency: str = Field(min_length=1, max_length=500)
    availability_note: str = Field(min_length=1, max_length=500)
    migration_note: str = Field(min_length=1, max_length=500)

    @model_validator(mode="after")
    def valid_row(self) -> RegionalRow:
        """Only recorded datapoints may claim measured latency; migration is never automatic."""
        if self.latency_basis == "measured":
            if not self.measured_source:
                raise ValueError("measured latency requires recorded measured_source")
        elif self.measured_source is not None:
            raise ValueError("estimate/unknown latency rows cannot carry a measured_source")
        if "no automatic region migration" not in self.migration_note.lower():
            raise ValueError("migration_note must state that no automatic region migration is performed")
        return self


class Scenario(BaseModel):
    """One named scenario covering every inventory category exactly once."""

    model_config = ConfigDict(extra="forbid")
    name: str = Field(min_length=1, max_length=40)
    students: int = Field(ge=1, le=100000)
    description: str = Field(min_length=1, max_length=1000)
    deployment_assumption: str = Field(min_length=1, max_length=500)
    lines: list[ScenarioLine] = Field(min_length=9)

    @model_validator(mode="after")
    def complete_categories(self) -> Scenario:
        """Every inventory category must be covered at least once (cost_report semantics)."""
        seen = {line.category for line in self.lines}
        missing = [category for category in CATEGORIES if category not in seen]
        if missing:
            raise ValueError(f"scenarios must cover every category; missing: {missing}")
        return self


class ScenarioConfig(BaseModel):
    """The complete offline scenario configuration."""

    model_config = ConfigDict(extra="forbid")
    kind: Literal["cost-scenario-config"]
    as_of: date
    pricing_caveat: str = Field(min_length=1, max_length=2000)
    fx: FxAssumption
    measured_local_anchors: list[MeasuredAnchor] = Field(min_length=1)
    regional_assessment: list[RegionalRow] = Field(min_length=1)
    s30_objective_sgd: Money = Decimal("30")
    scenarios: list[Scenario] = Field(min_length=1)


def _line_gross(line: ScenarioLine, fx: FxAssumption) -> Decimal | None:
    """Return the SGD gross for one line, or None when the cost is unknown."""
    if line.cost_basis == "unknown":
        return None
    if line.cost_basis == "not_applicable":
        return Decimal(0)
    with localcontext() as context:
        context.prec = 64
        return line.quantity * line.unit_price_usd * fx.sgd_per_usd


def _render_scenario(scenario: Scenario, config: ScenarioConfig) -> dict[str, object]:
    """Compute one scenario's labelled lines and honest totals."""
    grosses = [_line_gross(line, config.fx) for line in scenario.lines]
    unknowns = [f"gross:{line.name}" for line, gross in zip(scenario.lines, grosses) if gross is None]
    ordered = sorted(
        zip(scenario.lines, grosses),
        key=lambda pair: CATEGORIES.index(pair[0].category),
    )
    lines = []
    for line, gross in ordered:
        lines.append({
            "category": line.category,
            "name": line.name,
            "quantity": None if line.quantity is None else str(line.quantity),
            "unit": line.unit,
            "unit_price_usd": None if line.unit_price_usd is None else str(line.unit_price_usd),
            "cost_basis": line.cost_basis,
            "quantity_basis": line.quantity_basis,
            "price_as_of": line.price_as_of.isoformat() if line.price_as_of else None,
            "gross_sgd": _amount(gross),
            "evidence": line.evidence,
        })
    priced_subtotal = sum((gross for gross in grosses if gross is not None), Decimal(0))
    return {
        "name": scenario.name,
        "students": scenario.students,
        "description": scenario.description,
        "deployment_assumption": scenario.deployment_assumption,
        "lines": lines,
        "estimated_gross_sgd": None if unknowns else _amount(priced_subtotal),
        "priced_subtotal_sgd": _amount(priced_subtotal),
        "credits_sgd": None,
        "cash_sgd": None,
        "credit_runway_months": None,
        "bill_verified": False,
        "totals_note": (
            "Planning estimate, not a bill. The priced subtotal covers only lines with cost estimates. "
            "A full gross estimate requires a cost for every applicable line."
        ),
        "post_credit_baseline_note": (
            "The complete estimated gross, when available, is the baseline after credits end. "
            "A priced subtotal cannot establish that baseline. Credits and cash require evidence "
            "via scripts.cost_report."
        ),
        "unknowns": unknowns,
    }


def build_report(config_text: str) -> dict[str, object]:
    """Validate the scenario configuration and render the offline report."""
    config = ScenarioConfig.model_validate_json(config_text)
    for scenario in config.scenarios:
        for line in scenario.lines:
            if line.price_as_of is not None and line.price_as_of > config.as_of:
                raise ValueError(f"line '{line.name}' is priced after the report as_of date")
    scenarios = [_render_scenario(scenario, config) for scenario in config.scenarios]
    totals = ", ".join(
        f"{scenario['name']} S${scenario['estimated_gross_sgd']}"
        if scenario["estimated_gross_sgd"] is not None
        else f"{scenario['name']} unknown (priced subtotal S${scenario['priced_subtotal_sgd']})"
        for scenario in scenarios
    )
    statement = (
        f"Estimated gross (all-estimate basis, before credits/GST/bill verification): {totals}. "
        "None of these estimates demonstrates that post-credit cost plus approved headroom stays "
        "within the objective; the gate remains unresolved pending verified billing evidence and a "
        "separately approved positive headroom (C + H <= objective, credits not deducted). The "
        "existing classroom cost/capacity release gates stay open and no funding decision is made here."
    )
    return {
        "kind": "cost-scenario-report",
        "as_of": config.as_of.isoformat(),
        "pricing_caveat": config.pricing_caveat,
        "fx": {
            "sgd_per_usd": str(config.fx.sgd_per_usd),
            "as_of": config.fx.as_of.isoformat(),
            "evidence": config.fx.evidence,
        },
        "measured_local_anchors": [anchor.model_dump() for anchor in config.measured_local_anchors],
        "scenarios": scenarios,
        "regional_assessment": [row.model_dump() for row in config.regional_assessment],
        "s30_assessment": {
            "objective_sgd": _amount(config.s30_objective_sgd),
            "status": "unresolved",
            "statement": statement,
        },
        "limitations": LIMITATIONS,
    }


def main(argv: list[str] | None = None) -> int:
    """Print the JSON report, or return 2 on invalid input without echoing content."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        report = build_report(args.config.read_text())
    except (OSError, ValueError, ValidationError, TypeError, DecimalException):
        print("Invalid scenario configuration; check the documented schema and evidence.", file=sys.stderr)
        return 2
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
