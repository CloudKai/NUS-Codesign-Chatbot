"""Offline monthly SGD inventory and content-free usage reconciliation.

All prices and billing evidence are explicit operator inputs. No SDK, account,
student database, currency feed or network is accessed. Unknown is never zero.
"""

from __future__ import annotations

from collections import Counter
from datetime import date, datetime, timezone
from decimal import Decimal, localcontext
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from backend.usage import GenerationUsage

Money = Annotated[Decimal, Field(ge=0, le=Decimal("1e15"), max_digits=40, decimal_places=18, allow_inf_nan=False)]
CATEGORIES = (
    "hosting", "generation", "retrieval", "ingestion", "storage", "backups",
    "observability", "network", "other",
)


class CostLine(BaseModel):
    """A monthly SGD charge; credit eligibility is independent of applied credits."""

    model_config = ConfigDict(extra="forbid")
    category: Literal["hosting", "generation", "retrieval", "ingestion", "storage", "backups", "observability", "network", "other"]
    name: str = Field(min_length=1, max_length=160)
    gross_sgd: Money | None = None
    credits_sgd: Money | None = None
    credit_eligible: bool | None = None
    basis: Literal["actual", "estimate", "unknown", "not_applicable"] = "unknown"
    evidence: str = Field(min_length=1, max_length=500)

    @model_validator(mode="after")
    def valid_charge(self) -> CostLine:
        """Reject unsupported known charges, over-crediting and ambiguous exclusions."""
        if self.basis == "unknown" and self.gross_sgd is not None:
            raise ValueError("unknown lines must leave gross_sgd null")
        if self.basis in {"actual", "estimate"} and self.gross_sgd is None:
            raise ValueError("known lines require gross_sgd")
        if self.basis == "not_applicable" and (self.gross_sgd != 0 or self.credits_sgd != 0):
            raise ValueError("not_applicable requires explicit zero gross and credits")
        if self.credits_sgd is not None and self.gross_sgd is not None and self.credits_sgd > self.gross_sgd:
            raise ValueError("credits cannot exceed this line's gross charge")
        if self.credit_eligible is False and self.credits_sgd not in {None, Decimal(0)}:
            raise ValueError("ineligible charges cannot receive credits")
        return self


class GenerationRate(BaseModel):
    """Operator-supplied SGD rates per million disjoint token classes."""

    model_config = ConfigDict(extra="forbid")
    provider: Literal["openai", "bedrock", "agentcore"]
    model: str
    region: str = "unknown"
    input_sgd_per_million: Money
    output_sgd_per_million: Money
    cache_read_sgd_per_million: Money
    cache_write_sgd_per_million: Money
    evidence: str = Field(min_length=1)
    as_of: date


class CostInventory(BaseModel):
    """Monthly accounting evidence, rate provenance and explicit coverage attestations."""

    model_config = ConfigDict(extra="forbid")
    month: str = Field(pattern=r"^\d{4}-(0[1-9]|1[0-2])$")
    currency: Literal["SGD"] = "SGD"
    as_of: date
    lines: list[CostLine]
    inventory_complete: bool = False
    usage_complete: bool = False
    rates: list[GenerationRate] = Field(default_factory=list)
    remaining_credits_sgd: Money | None = None
    credit_expiry: date | None = None
    credit_balance_evidence: str | None = None
    assessed_useful_answers: int | None = Field(default=None, ge=0)
    usefulness_evidence: str | None = None

    @model_validator(mode="after")
    def valid_evidence(self) -> CostInventory:
        """Require provenance for assessments/balances and unambiguous price matching."""
        if self.remaining_credits_sgd is not None and not self.credit_balance_evidence:
            raise ValueError("credit balance requires evidence")
        if self.assessed_useful_answers is not None and not self.usefulness_evidence:
            raise ValueError("useful-answer assessment requires evidence")
        keys = [(rate.provider, rate.model, rate.region) for rate in self.rates]
        if len(keys) != len(set(keys)):
            raise ValueError("duplicate provider/model/region rates")
        if any(rate.as_of > self.as_of for rate in self.rates):
            raise ValueError("rate evidence cannot be newer than report as_of")
        return self


class OperationUsage(BaseModel):
    """Allowlisted final outcome for one application operation."""

    model_config = ConfigDict(extra="forbid")
    event: Literal["operation_usage"]
    event_id: str
    timestamp: datetime
    operation_id: str
    kind: Literal["chat", "deep_review", "stage_checkpoint"]
    session_key: str = Field(pattern=r"^[a-f0-9]{32}$")
    success: bool
    answer_delivered: bool
    replayed: bool
    generation_attempts: int = Field(ge=0)
    useful_answer: None = None


def _amount(value: Decimal | None) -> str | None:
    """Return six-decimal SGD precision without float rounding."""
    if value is None:
        return None
    with localcontext() as context:
        context.prec = 64
        return str(value.quantize(Decimal("0.000001")))


def _sum_known(values: list[Decimal | None]) -> Decimal | None:
    """Sum complete inputs, retaining null if any component is unavailable."""
    return sum(values, Decimal(0)) if all(value is not None for value in values) else None


def cost_report(inventory: CostInventory, raw_events: list[dict[str, Any]]) -> dict[str, Any]:
    """Reconcile a UTC month of usage with an explicit SGD charge inventory.

    Duplicate exported events are counted once; conflicting duplicates fail.
    Generation estimates are separate from inventory charges to avoid adding
    model prices twice. Billing and log coverage must be explicitly attested.
    """
    events: dict[str, GenerationUsage | OperationUsage] = {}
    for raw in raw_events:
        if not isinstance(raw, dict):
            raise ValueError("usage events must be JSON objects")
        model = GenerationUsage if raw.get("event") == "generation_usage" else OperationUsage
        event = model.model_validate(raw)
        if event.timestamp.tzinfo is None:
            raise ValueError("usage timestamps must include a timezone")
        if event.timestamp.astimezone(timezone.utc).strftime("%Y-%m") != inventory.month:
            continue
        existing = events.get(event.event_id)
        if existing is not None and existing != event:
            raise ValueError("conflicting duplicate usage event")
        events[event.event_id] = event
    attempts = [event for event in events.values() if isinstance(event, GenerationUsage)]
    operations = [event for event in events.values() if isinstance(event, OperationUsage)]
    missing = [category for category in CATEGORIES if not any(line.category == category for line in inventory.lines)]
    unknowns = [f"missing_category:{category}" for category in missing]
    if not inventory.inventory_complete:
        unknowns.append("inventory_coverage_unconfirmed")
    for line in inventory.lines:
        if line.gross_sgd is None:
            unknowns.append(f"gross:{line.name}")
        if line.credits_sgd is None:
            unknowns.append(f"credits:{line.name}")
    gross = _sum_known([line.gross_sgd for line in inventory.lines])
    credits = _sum_known([line.credits_sgd for line in inventory.lines])
    coverage = inventory.inventory_complete and not missing
    if not coverage:
        gross = credits = None
    cash = gross - credits if gross is not None and credits is not None else None
    known_gross = sum((line.gross_sgd for line in inventory.lines if line.gross_sgd is not None), Decimal(0))
    generation_known = Decimal(0)
    unpriced = 0
    for attempt in attempts:
        if attempt.provider == "mock":
            continue
        rate = next((rate for rate in inventory.rates if rate.provider == attempt.provider and rate.model == attempt.model and rate.region == attempt.region), None)
        meters = [attempt.input_tokens, attempt.output_tokens, attempt.cache_read_tokens, attempt.cache_write_tokens]
        if rate is None or any(value is None for value in meters):
            unpriced += 1
            continue
        generation_known += sum((Decimal(value) * price for value, price in zip(meters, [
            rate.input_sgd_per_million, rate.output_sgd_per_million,
            rate.cache_read_sgd_per_million, rate.cache_write_sgd_per_million,
        ])), Decimal(0)) / Decimal(1_000_000)
    generation_complete = inventory.usage_complete and not unpriced
    if not inventory.usage_complete:
        unknowns.append("usage_coverage_unconfirmed")
    if unpriced:
        unknowns.append("unpriced_generation_attempts")
    retry_coverage_unknown = any(event.model_calls is None or event.sdk_retries is None or event.sdk_retries > 0 for event in attempts if event.provider != "mock")
    if retry_coverage_unknown:
        generation_complete = False
        unknowns.append("hidden_retry_usage_unreconciled")
    if inventory.remaining_credits_sgd is None:
        unknowns.append("credit_balance_unavailable")
    if inventory.credit_expiry is None:
        unknowns.append("credit_expiry_unavailable")
    if inventory.assessed_useful_answers is None:
        unknowns.append("useful_answer_assessment_unavailable")
    counts = Counter(event.operation_id for event in attempts)
    attempt_ids = set(counts)
    outcome_ids = {event.operation_id for event in operations}
    unmatched = len(attempt_ids - outcome_ids)
    missing_attempts = sum(max(0, event.generation_attempts - counts[event.operation_id]) for event in operations)
    if unmatched or missing_attempts:
        generation_complete = False
        unknowns.append("incomplete_operation_events")
    usage_complete = inventory.usage_complete and not unmatched and not missing_attempts
    delivered = sum(event.answer_delivered for event in operations)
    useful = inventory.assessed_useful_answers
    if useful is not None and useful > delivered:
        raise ValueError("assessed useful answers cannot exceed delivered answers in this export")
    sessions = len({event.session_key for event in operations if event.kind == "chat" and not event.replayed})
    eligible = _sum_known([
        line.gross_sgd if line.credit_eligible is True else Decimal(0) if line.credit_eligible is False or line.basis == "not_applicable" else None
        for line in inventory.lines
    ]) if coverage else None
    runway = None
    if inventory.remaining_credits_sgd is not None and inventory.credit_expiry is not None and eligible is not None and eligible > 0:
        expiry_months = Decimal(max(0, (inventory.credit_expiry - inventory.as_of).days)) / Decimal("30.4375")
        runway = min(inventory.remaining_credits_sgd / eligible, expiry_months)
    return {
        "month": inventory.month, "currency": "SGD", "as_of": inventory.as_of.isoformat(),
        "inventory": [line.model_dump(mode="json") for line in inventory.lines],
        "inventory_complete": coverage and gross is not None and credits is not None,
        "gross_sgd": _amount(gross), "credits_sgd": _amount(credits), "cash_sgd": _amount(cash),
        "post_credit_monthly_sgd": _amount(gross), "known_gross_subtotal_sgd": _amount(known_gross),
        "remaining_credits_sgd": _amount(inventory.remaining_credits_sgd),
        "credit_runway_months": _amount(runway), "credit_expiry": str(inventory.credit_expiry) if inventory.credit_expiry else None,
        "runway_basis": "constant eligible monthly gross, capped by expiry; restricted balances require separate inventories",
        "generation_estimate_sgd": _amount(generation_known) if generation_complete else None,
        "known_generation_subtotal_sgd": _amount(generation_known),
        "generation_estimate_included_in_inventory": False,
        "generation_rates": [rate.model_dump(mode="json") for rate in inventory.rates],
        "usage": {
            "generation_attempts": len(attempts), "failed_generation_attempts": sum(not event.success for event in attempts),
            "deep_review_attempts": sum(event.kind == "deep_review" for event in attempts),
            "stage_checkpoint_attempts": sum(event.kind == "stage_checkpoint" for event in attempts),
            "extra_generation_attempts": sum(max(0, counts[event.operation_id] - 1) for event in operations),
            "unknown_model_call_counts": sum(event.model_calls is None for event in attempts),
            "unknown_sdk_retry_counts": sum(event.sdk_retries is None for event in attempts),
            "unpriced_attempts": unpriced, "operations_without_all_attempts": missing_attempts,
            "attempt_operations_without_outcome": unmatched,
            "failed_operations": sum(not event.success for event in operations),
            "replays": sum(event.replayed for event in operations), "delivered_answers": delivered,
            "assessed_useful_answers": useful, "notebook_day_sessions": sessions,
        },
        "cost_per_delivered_answer_sgd": _amount(gross / delivered) if gross is not None and delivered and usage_complete else None,
        "cost_per_useful_answer_sgd": _amount(gross / useful) if gross is not None and useful and usage_complete else None,
        "cost_per_notebook_day_session_sgd": _amount(gross / sessions) if gross is not None and sessions and usage_complete else None,
        "usefulness_evidence": inventory.usefulness_evidence,
        "credit_balance_evidence": inventory.credit_balance_evidence,
        "unknown_inputs": unknowns,
        "limitations": ["Application logs are not an invoice; reconcile hidden retries, failed calls and missing exports with billing evidence.",
                        "Delivered answers are not assessed usefulness. Sessions are notebook/UTC-day proxies, not people.",
                        "Generation estimates exclude runtime/SDK charges and are never added to inventory totals.",
                        "Operator prices must use disjoint token classes, a matching region and SGD conversion evidence."],
    }
