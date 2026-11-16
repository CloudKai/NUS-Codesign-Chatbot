"""Local durable generation allowance, finite admission, and conservative settlement.

The separate operator-selected SQLite ledger contains no student identities or
content. All workers on one host must use the same file and policy. It is not a
billing cap or a distributed database adapter. Missing policy preserves legacy
local behavior; a funded classroom release requires an evidenced policy.
"""

from __future__ import annotations

import json
import logging
import math
import sqlite3
import time
from collections.abc import Callable
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING, Protocol
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, model_validator

from backend.rate_limit import RateLimitExceeded

if TYPE_CHECKING:
    from backend.usage import GenerationUsage

logger = logging.getLogger("co_design.usage")


def _event(outcome: str, **fields: str) -> None:
    """Emit bounded correlation fields without student content or raw ids."""
    from backend.usage import usage_correlation

    logger.info("%s", json.dumps({"event": "generation_admission", "outcome": outcome,
                                **usage_correlation(), **fields}))


class GenerationRate(BaseModel):
    """Evidenced micro-SGD per million tokens for one exact model and region."""

    model_config = ConfigDict(extra="forbid", frozen=True)
    provider: str
    model: str
    region: str
    input: int = Field(ge=0, le=10**12)
    output: int = Field(ge=0, le=10**12)
    cache_read: int = Field(ge=0, le=10**12)
    cache_write: int = Field(ge=0, le=10**12)
    evidence: str = Field(min_length=1, max_length=1000)


class GenerationPolicy(BaseModel):
    """Finite operator limits; the ceiling covers hidden SDK/model retries too."""

    model_config = ConfigDict(extra="forbid", frozen=True)
    ledger_path: Path
    monthly_micro_sgd: int = Field(gt=0, le=10**12)
    headroom_micro_sgd: int = Field(gt=0, le=10**12)
    call_reserve_micro_sgd: int = Field(gt=0, le=10**12)
    max_running: int = Field(ge=1, le=80)
    max_queued: int = Field(ge=0, le=160)
    max_wait_seconds: float = Field(ge=0, le=30, allow_inf_nan=False)
    lease_seconds: float = Field(ge=1, le=86400, allow_inf_nan=False)
    ceiling_evidence: str = Field(min_length=1, max_length=1000)
    rates: tuple[GenerationRate, ...] = ()

    @model_validator(mode="after")
    def valid_allowance(self) -> GenerationPolicy:
        """Reject unusable headroom, ambiguous prices, and relative ledger paths."""
        if self.headroom_micro_sgd + self.call_reserve_micro_sgd > self.monthly_micro_sgd:
            raise ValueError("Allowance must fund one call after headroom")
        if not self.ledger_path.is_absolute():
            raise ValueError("Ledger path must be absolute")
        keys = [(rate.provider, rate.model, rate.region) for rate in self.rates]
        if len(keys) != len(set(keys)):
            raise ValueError("Duplicate generation rate")
        return self


class GenerationAdmission(Protocol):
    """Replaceable admission and settlement port used by provider accounting."""

    def acquire(self) -> str:
        """Reserve one call or raise a safe finite-wait/allowance rejection."""

    def settle(self, token: str, meter: GenerationUsage) -> None:
        """Reconcile the exact reservation, retaining unknown failed usage."""


class SQLiteGenerationAdmission:
    """Serialize local reservations across owners, processes and restarts."""

    def __init__(self, policy: GenerationPolicy, *, clock: Callable[[], float] = time.time) -> None:
        """Open an explicit dedicated ledger; never migrate a student database."""
        self.policy = policy
        self._clock = clock
        # Opening an existing unrelated SQLite file must not silently mutate it.
        with closing(sqlite3.connect(policy.ledger_path, timeout=2)) as db:
            tables = {row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            if tables and tables != {"generation_calls"}:
                raise ValueError("Use a dedicated generation ledger")
            db.execute("""CREATE TABLE IF NOT EXISTS generation_calls (
                token TEXT PRIMARY KEY, period TEXT NOT NULL, state TEXT NOT NULL,
                amount INTEGER NOT NULL, deadline REAL NOT NULL, created REAL NOT NULL
            )""")
            db.commit()

    def _connection(self) -> sqlite3.Connection:
        """Begin a short serialized write transaction with a bounded lock wait."""
        db = sqlite3.connect(self.policy.ledger_path, timeout=2)
        db.execute("BEGIN IMMEDIATE")
        return db

    def _expire(self, db: sqlite3.Connection, now: float) -> None:
        """Release abandoned waits; quarantine expired invokes without refunds.

        Expiry cannot prove an external call stopped. Uncertain calls retain
        both charge and slot until their original worker settles, or an operator
        confirms all workers stopped. Restart never creates free generation.
        """
        db.execute("UPDATE generation_calls SET state='settled', amount=0 WHERE state='queued' AND deadline<=?", (now,))
        db.execute("UPDATE generation_calls SET state='uncertain' WHERE state='running' AND deadline<=?", (now,))

    def _reject(self, category: str, seconds: int) -> None:
        """Raise public guidance without exposing amounts, paths or identity."""
        message = (
            "Generation admission needs operator attention. Saved notebooks, sources and export remain available. Ask your lecturer for help."
            if category == "generation_unavailable" else
            "The generation allowance is used up. It resets on the first day of next month at 00:00 UTC. "
            "You can still read notebooks, use sources and export your work. Ask your lecturer for help."
            if category == "generation_budget" else
            "The generation waiting limit was reached. Your reply has not been generated. "
            "Retry shortly; notebooks, sources and export remain available."
        )
        _event("rejected", category=category)
        raise RateLimitExceeded(max(1, seconds), message, category=category)

    def acquire(self) -> str:
        """Reserve cost before invocation, with bounded FIFO waiting and capacity."""
        from backend.coaching.progress import emit_coach_progress

        token = uuid4().hex
        started = time.monotonic()
        queued = False
        now = self._clock()
        instant = datetime.fromtimestamp(now, timezone.utc)
        period = instant.strftime("%Y-%m")
        next_month = datetime(instant.year + (instant.month == 12), instant.month % 12 + 1, 1, tzinfo=timezone.utc)
        retry = math.ceil(next_month.timestamp() - now)
        try:
            with closing(self._connection()) as db, db:
                self._expire(db, now)
                spent = db.execute("SELECT COALESCE(SUM(amount),0) FROM generation_calls WHERE period=?", (period,)).fetchone()[0]
                if spent + self.policy.call_reserve_micro_sgd > self.policy.monthly_micro_sgd - self.policy.headroom_micro_sgd:
                    self._reject("generation_budget", retry)
                if db.execute("SELECT 1 FROM generation_calls WHERE state='overrun' LIMIT 1").fetchone():
                    self._reject("generation_unavailable", 1)
                running = db.execute("SELECT COUNT(*) FROM generation_calls WHERE state IN ('running','uncertain')").fetchone()[0]
                waiting = db.execute("SELECT COUNT(*) FROM generation_calls WHERE state='queued'").fetchone()[0]
                queued = running >= self.policy.max_running or waiting > 0
                if queued and (waiting >= self.policy.max_queued or self.policy.max_wait_seconds == 0):
                    self._reject("generation_capacity", 1)
                db.execute("INSERT INTO generation_calls VALUES (?,?,?,?,?,?)", (
                    token, period, "queued" if queued else "running", self.policy.call_reserve_micro_sgd,
                    now + (self.policy.max_wait_seconds if queued else self.policy.lease_seconds), now,
                ))
            if queued:
                emit_coach_progress("queued")
                _event("queued")
            while queued:
                time.sleep(min(0.02, self.policy.max_wait_seconds))
                now = self._clock()
                with closing(self._connection()) as db, db:
                    self._expire(db, now)
                    row = db.execute("SELECT state FROM generation_calls WHERE token=?", (token,)).fetchone()
                    if row[0] != "queued" or time.monotonic() - started >= self.policy.max_wait_seconds:
                        db.execute("UPDATE generation_calls SET state='settled',amount=0 WHERE token=? AND state='queued'", (token,))
                        db.commit()
                        self._reject("generation_wait", 1)
                    if db.execute("SELECT 1 FROM generation_calls WHERE state='overrun' LIMIT 1").fetchone():
                        db.execute("UPDATE generation_calls SET state='settled',amount=0 WHERE token=?", (token,))
                        db.commit()
                        self._reject("generation_unavailable", 1)
                    running = db.execute("SELECT COUNT(*) FROM generation_calls WHERE state IN ('running','uncertain')").fetchone()[0]
                    first = db.execute("SELECT token FROM generation_calls WHERE state='queued' ORDER BY created,token LIMIT 1").fetchone()
                    if running < self.policy.max_running and first[0] == token:
                        db.execute("UPDATE generation_calls SET state='running',deadline=? WHERE token=?", (now + self.policy.lease_seconds, token))
                        queued = False
            emit_coach_progress("thinking")
            _event("admitted")
            return token
        except sqlite3.Error as error:
            raise RateLimitExceeded(2, "Generation admission is unavailable. Your saved work remains available.", category="generation_unavailable") from error

    def settle(self, token: str, meter: GenerationUsage) -> None:
        """Settle once; unknown/retried usage retains the ceiling, overruns block.

        Exact, complete meters may refund unused reservation. An observed cost
        above its ceiling is retained in full and quarantines future calls until
        an operator fixes the disproven policy. It cannot undo an external bill.
        """
        charge = self.policy.call_reserve_micro_sgd
        rate = next((r for r in self.policy.rates if (r.provider, r.model, r.region) == (meter.provider, meter.model, meter.region)), None)
        values = (meter.input_tokens, meter.output_tokens, meter.cache_read_tokens, meter.cache_write_tokens)
        if rate is not None and all(v is not None for v in values) and meter.sdk_retries == 0 and meter.model_calls is not None:
            numerator = sum(int(v) * price for v, price in zip(values, (rate.input, rate.output, rate.cache_read, rate.cache_write)))
            charge = min((numerator + 999999) // 1000000, 10**15)
        try:
            with closing(self._connection()) as db, db:
                db.execute("UPDATE generation_calls SET state=?,amount=? WHERE token=? AND state IN ('running','uncertain')", (
                    "overrun" if charge > self.policy.call_reserve_micro_sgd else "settled", charge, token,
                ))
        except sqlite3.Error:
            # Do not replace a saved reply/provider error with a ledger write error.
            # Its reservation remains charged, and expires into quarantine.
            _event("settlement_unavailable")

    def recover_stopped_workers(self) -> int:
        """Release orphan capacity only after the operator has stopped all workers.

        All invoked/uncertain charges stay reserved in their original UTC month;
        only work that never invoked receives a refund. Back up the ledger first.
        """
        with closing(self._connection()) as db, db:
            db.execute("UPDATE generation_calls SET amount=0 WHERE state='queued'")
            result = db.execute("UPDATE generation_calls SET state='settled' WHERE state IN ('queued','running','uncertain')")
            return result.rowcount



def configured_generation_admission() -> GenerationAdmission | None:
    """Load an explicit local policy; invalid configuration fails closed at startup."""
    from backend.settings import settings

    if not settings.generation_admission_policy:
        return None
    try:
        policy = GenerationPolicy.model_validate_json(Path(settings.generation_admission_policy).read_text())
        return SQLiteGenerationAdmission(policy)
    except (OSError, ValueError, sqlite3.Error):
        raise ValueError("Invalid generation admission configuration") from None
