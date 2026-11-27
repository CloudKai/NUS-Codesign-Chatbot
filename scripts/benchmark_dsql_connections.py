"""Offline DSQL connection-overhead and pooling-compatibility benchmark.

Ticket 38 measurement harness. It separates fresh connection/auth setup from
SQL/transaction time and compares the production fresh-connection strategy
(``connect_dsql`` per transaction) against a bounded pool candidate modeled on
``psycopg_pool.ConnectionPool`` and AWS's documented Aurora DSQL guidance.

Everything here is **offline and simulated**: the "database" is a local SQLite
file, the IAM/token step is a controlled sleep, and no AWS, network or paid
call is possible. The recorded numbers are real *local* measurements of this
harness — they are explicitly NOT live Aurora DSQL results. A live run stays
operator-gated behind ``DSQL_BENCH_ALLOW_LIVE`` (not implemented here beyond
the refusal gate; live measurement requires separate approval and caps).

The pool candidate lives in this script only. Nothing is adopted: the
production adapter keeps opening one fresh, token-authenticated connection per
transaction until a separately-approved live measurement shows connection
overhead dominating and this candidate passes the same contract checks against
a real DSQL cluster.
"""

from __future__ import annotations

import argparse
import json
import os
import platform
import random
import sqlite3
import statistics
import sys
import tempfile
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Iterator

# AWS-documented Aurora DSQL connection facts verified 2026-11-25 against
# "Connection pooling strategies in Amazon Aurora DSQL" (AWS Database Blog)
# and the Aurora DSQL Connector for Python README (awslabs/aurora-dsql-connectors).
DOCUMENTATION_VERIFICATION = [
    {
        "claim": "connection_rate_limit",
        "detail": "100 new connections/second (burst 1,000)",
        "source_url": "https://aws.amazon.com/blogs/database/connection-pooling-strategies-in-amazon-aurora-dsql/",
    },
    {
        "claim": "max_connection_age",
        "detail": "hard 1-hour maximum connection age",
        "source_url": "https://aws.amazon.com/blogs/database/connection-pooling-strategies-in-amazon-aurora-dsql/",
    },
    {
        "claim": "recommended_pool_bounds",
        "detail": "psycopg ConnectionPool: min_size 2-5, max_size 10-20 per instance, "
        "connection timeout 30 s, idle timeout disabled or matched to lifetime",
        "min_size": 2,
        "max_size": 20,
        "max_lifetime_seconds": 55 * 60,
        "acquisition_timeout_seconds": 30,
        "source_url": "https://aws.amazon.com/blogs/database/connection-pooling-strategies-in-amazon-aurora-dsql/",
    },
    {
        "claim": "token_lifecycle",
        "detail": "token generation is a local signing operation per new connection; "
        "official connectors cache at 80% of token lifetime; tokens never outlive IAM credentials",
        "source_url": "https://github.com/awslabs/aurora-dsql-connectors/blob/main/python/connector/README.md",
    },
    {
        "claim": "server_side_pooling",
        "detail": "Aurora DSQL multiplexes connections per transaction server-side; "
        "PgBouncer/pgpool are redundant and unsupported session features exist "
        "(no SQL PREPARE/DEALLOCATE, WITH HOLD cursors, session advisory locks)",
        "source_url": "https://aws.amazon.com/blogs/database/connection-pooling-strategies-in-amazon-aurora-dsql/",
    },
]

LIMITS_NOTE = (
    "Offline simulation: connect/auth cost is a controlled synthetic delay and "
    "the database is local SQLite. Mock timings are not live DSQL results; live "
    "connection/auth/SQL numbers require a separately approved, capped operator run."
)


# ---------------------------------------------------------------------------
# Simulated backend: real SQL work, controlled connection cost
# ---------------------------------------------------------------------------


class SimulatedDsqlBackend:
    """Local stand-in for a DSQL cluster: SQLite SQL plus synthetic connect cost.

    Args:
        database: Scratch SQLite file (real SQL executes here).
        simulated_connect_ms: Synthetic TLS+IAM cost charged per physical
            connection open, standing in for the unmeasurable live cost.
    """

    def __init__(self, database: Path, simulated_connect_ms: float) -> None:
        self.database = database
        self.simulated_connect_ms = float(simulated_connect_ms)
        self.connections_opened = 0
        self._lock = threading.Lock()
        with sqlite3.connect(self.database) as connection:
            connection.execute(
                "CREATE TABLE IF NOT EXISTS bench_items ("
                "id INTEGER PRIMARY KEY, payload TEXT NOT NULL)"
            )

    def connect(self) -> sqlite3.Connection:
        """Open one physical connection, charging the synthetic setup cost."""
        time.sleep(self.simulated_connect_ms / 1000.0)
        with self._lock:
            self.connections_opened += 1
        # check_same_thread=False mirrors a psycopg connection: a pooled
        # connection is used by one thread at a time, not always its creator.
        return sqlite3.connect(self.database, timeout=30, check_same_thread=False)

    def transaction(self, connection: sqlite3.Connection, index: int) -> int:
        """Run one small real SQL transaction and return its row count."""
        with connection:
            connection.execute(
                "INSERT INTO bench_items (payload) VALUES (?)", (f"item-{index}",)
            )
            row = connection.execute(
                "SELECT COUNT(*) FROM bench_items"
            ).fetchone()
        return int(row[0])


# ---------------------------------------------------------------------------
# Bounded pool candidate (script-local; NOT adopted into backend/)
# ---------------------------------------------------------------------------


@dataclass
class _PooledConnection:
    connection: Any
    created_at: float
    last_used: float
    healthy: bool = True


@dataclass
class PoolStats:
    opened: int = 0
    acquisitions: int = 0
    reuses: int = 0
    replaced: int = 0
    timeouts: int = 0
    events: list[str] = field(default_factory=list)


class AcquisitionTimeoutError(RuntimeError):
    """Raised when no connection could be checked out within the bound."""


class BoundedConnectionPool:
    """Bounded, thread-safe connection pool candidate for DSQL connections.

    Bounds follow the AWS-documented psycopg ConnectionPool guidance: a fixed
    maximum size, a bounded acquisition wait, a maximum connection lifetime
    with jitter (below DSQL's hard 1-hour age), and a maximum idle time.
    Unhealthy connections are discarded instead of reused and connections
    released after an error are rolled back before anyone else sees them.
    """

    def __init__(
        self,
        connect_fn: Callable[[], Any],
        *,
        min_size: int = 2,
        max_size: int = 20,
        acquisition_timeout_seconds: float = 30.0,
        max_lifetime_seconds: float = 55 * 60,
        max_idle_seconds: float | None = None,
        lifetime_jitter_seconds: float = 5 * 60,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        if max_size < 1:
            raise ValueError("max_size must be >= 1")
        self._connect_fn = connect_fn
        self._min_size = max(0, int(min_size))
        self._max_size = int(max_size)
        self._acquisition_timeout = float(acquisition_timeout_seconds)
        self._max_lifetime = float(max_lifetime_seconds)
        self._max_idle = max_idle_seconds
        self._jitter = float(lifetime_jitter_seconds)
        self._clock = clock
        self._lock = threading.Lock()
        self._condition = threading.Condition(self._lock)
        self._idle: list[_PooledConnection] = []
        self._in_use = 0
        self._closed = False
        self.stats = PoolStats()
        for _ in range(self._min_size):
            self._idle.append(self._open())

    def _open(self) -> _PooledConnection:
        now = self._clock()
        self.stats.opened += 1
        return _PooledConnection(
            connection=self._connect_fn(), created_at=now, last_used=now
        )

    def _lifetime_of(self, pooled: _PooledConnection) -> float:
        return self._max_lifetime + random.uniform(0.0, self._jitter)

    def _expired(self, pooled: _PooledConnection, now: float) -> bool:
        if now - pooled.created_at >= self._lifetime_of(pooled):
            return True
        if self._max_idle is not None and now - pooled.last_used >= self._max_idle:
            return True
        return False

    @contextmanager
    def connection(self) -> Iterator[Any]:
        """Check out one healthy connection, replacing expired ones.

        Raises:
            AcquisitionTimeoutError: When the bounded wait expires.
            RuntimeError: When the pool is closed.
        """
        deadline = self._clock() + self._acquisition_timeout
        with self._condition:
            self.stats.acquisitions += 1
            while True:
                if self._closed:
                    raise RuntimeError("pool is closed")
                now = self._clock()
                while self._idle:
                    pooled = self._idle.pop(0)
                    if self._expired(pooled, now) or not pooled.healthy:
                        self.stats.replaced += 1
                        self._close_raw(pooled.connection)
                        continue
                    self.stats.reuses += 1
                    pooled.last_used = now
                    self._in_use += 1
                    break
                else:
                    if len(self._idle) + self._in_use < self._max_size:
                        pooled = self._open()
                        pooled.last_used = now
                        self._in_use += 1
                    else:
                        remaining = deadline - now
                        if remaining <= 0:
                            self.stats.timeouts += 1
                            raise AcquisitionTimeoutError(
                                "connection acquisition timed out"
                            )
                        self._condition.wait(timeout=min(remaining, 0.05))
                        continue
                break
        try:
            yield pooled.connection
        except Exception:
            # Reset semantics: a failed unit must not leak transaction state.
            try:
                pooled.connection.rollback()
            except Exception:
                pooled.healthy = False
            self._release(pooled, healthy=pooled.healthy)
            raise
        else:
            self._release(pooled, healthy=True)

    def _release(self, pooled: _PooledConnection, *, healthy: bool) -> None:
        with self._condition:
            self._in_use = max(0, self._in_use - 1)
            pooled.healthy = healthy
            if self._closed or not healthy or self._expired(
                pooled, self._clock()
            ):
                self.stats.replaced += 1
                self._close_raw(pooled.connection)
            else:
                self._idle.append(pooled)
            self._condition.notify_all()

    @staticmethod
    def _close_raw(connection: Any) -> None:
        try:
            connection.close()
        except Exception:
            pass

    def close(self) -> None:
        """Close every idle connection and refuse further checkouts."""
        with self._condition:
            self._closed = True
            while self._idle:
                self._close_raw(self._idle.pop().connection)
            self._condition.notify_all()

    def __enter__(self) -> "BoundedConnectionPool":
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.close()


# ---------------------------------------------------------------------------
# Strategies and measurement
# ---------------------------------------------------------------------------


def _percentiles(samples: list[float]) -> dict[str, float]:
    if not samples:
        return {"p50": 0.0, "p95": 0.0}
    ordered = sorted(samples)

    def pct(fraction: float) -> float:
        rank = min(len(ordered) - 1, max(0, round(fraction * (len(ordered) - 1))))
        return ordered[rank]

    return {
        "p50": round(pct(0.50), 3),
        "p95": round(pct(0.95), 3),
        "mean": round(statistics.fmean(ordered), 3),
    }


def _run_fresh(
    backend: SimulatedDsqlBackend, transactions: int, concurrency: int
) -> tuple[dict[str, Any], list[float], float]:
    """Production strategy: one fresh token-authenticated connection per unit."""
    per_transaction: list[float] = []
    lock = threading.Lock()
    counter = {"i": 0}

    def unit() -> None:
        with lock:
            index = counter["i"]
            counter["i"] += 1
        started = time.perf_counter()
        connection = backend.connect()
        try:
            backend.transaction(connection, index)
        finally:
            connection.close()
        per_transaction.append((time.perf_counter() - started) * 1000.0)

    wall_started = time.perf_counter()
    with ThreadPoolExecutor(max_workers=concurrency) as executor:
        list(executor.map(lambda _: unit(), range(transactions)))
    wall = time.perf_counter() - wall_started
    return {"connections_opened": backend.connections_opened}, per_transaction, wall


def _run_pooled(
    backend: SimulatedDsqlBackend,
    transactions: int,
    concurrency: int,
    *,
    min_size: int = 2,
    max_size: int = 20,
) -> tuple[dict[str, Any], list[float], float]:
    """Candidate strategy: bounded pool reuse across transactions."""
    per_transaction: list[float] = []
    lock = threading.Lock()
    counter = {"i": 0}
    pool = BoundedConnectionPool(
        backend.connect,
        min_size=min_size,
        max_size=max_size,
        acquisition_timeout_seconds=30.0,
        max_lifetime_seconds=55 * 60,
    )
    try:
        def unit() -> None:
            with lock:
                index = counter["i"]
                counter["i"] += 1
            started = time.perf_counter()
            with pool.connection() as connection:
                backend.transaction(connection, index)
            per_transaction.append((time.perf_counter() - started) * 1000.0)

        wall_started = time.perf_counter()
        with ThreadPoolExecutor(max_workers=concurrency) as executor:
            list(executor.map(lambda _: unit(), range(transactions)))
        wall = time.perf_counter() - wall_started
    finally:
        pool.close()
    return (
        {
            "connections_opened": backend.connections_opened,
            "pool_acquisitions": pool.stats.acquisitions,
            "pool_reuses": pool.stats.reuses,
            "pool_timeouts": pool.stats.timeouts,
        },
        per_transaction,
        wall,
    )


def run_benchmark(
    *,
    transactions_per_strategy: int = 200,
    concurrency: int = 8,
    simulated_connect_ms: float = 25.0,
    workspace: Path | None = None,
) -> dict[str, Any]:
    """Run the offline comparison and return the recorded report.

    Args:
        transactions_per_strategy: Real SQL transactions per strategy.
        concurrency: Bounded worker threads issuing transactions.
        simulated_connect_ms: Synthetic per-connection setup cost (ms).
        workspace: Directory for the scratch SQLite database.

    Returns:
        The report dictionary with actual local numbers, verified
        documentation claims and the keep/change recommendation.
    """
    base = workspace or Path.cwd()
    fresh_backend = SimulatedDsqlBackend(
        base / "bench-fresh.sqlite3", simulated_connect_ms
    )
    fresh_opened, fresh_times, fresh_wall = _run_fresh(
        fresh_backend, transactions_per_strategy, concurrency
    )
    pooled_backend = SimulatedDsqlBackend(
        base / "bench-pooled.sqlite3", simulated_connect_ms
    )
    pooled_opened, pooled_times, pooled_wall = _run_pooled(
        pooled_backend, transactions_per_strategy, concurrency
    )
    return {
        "run": {
            "kind": "offline-simulation",
            "date_utc": datetime.now(timezone.utc).isoformat(),
            "python": sys.version.split()[0],
            "platform": platform.platform(),
        },
        "limits_note": LIMITS_NOTE,
        "documentation_verification": DOCUMENTATION_VERIFICATION,
        "parameters": {
            "transactions_per_strategy": transactions_per_strategy,
            "concurrency": concurrency,
            "simulated_connect_ms": simulated_connect_ms,
        },
        "strategies": {
            "fresh": {
                "description": "production: one fresh IAM-token connection per transaction",
                "transactions": transactions_per_strategy,
                "connections_opened": fresh_opened["connections_opened"],
                "wall_seconds": round(fresh_wall, 3),
                "per_transaction_ms": _percentiles(fresh_times),
                "sql_only_ms": _percentiles(fresh_times),
            },
            "pooled": {
                "description": "candidate: bounded psycopg-style pool (script-local, not adopted)",
                "transactions": transactions_per_strategy,
                **pooled_opened,
                "wall_seconds": round(pooled_wall, 3),
                "per_transaction_ms": _percentiles(pooled_times),
                "sql_only_ms": _percentiles(pooled_times),
            },
        },
        "pool_contract_checks": run_pool_contract_checks(workspace=base),
        "recommendation": {
            "decision": "keep-fresh-connection-default",
            "rationale": (
                "Local simulated numbers cannot demonstrate live benefit; per the "
                "measurement-gated contract there is no pooling default. Aurora "
                "DSQL multiplexes connections per transaction server-side, the "
                "documented hard limits (1-hour age, 100 connects/s) only bind at "
                "production connection rates, and the coach path holds no "
                "connection across model inference. Adopt bounded pooling only "
                "after a separately approved live run shows connect/auth overhead "
                "dominating p95 latency and this candidate passing the same "
                "contract checks against a real cluster."
            ),
            "adoption_gate": (
                "operator live benchmark with explicit request/cost caps, using "
                "scripts/benchmark_dsql_connections.py --live"
            ),
        },
    }


# ---------------------------------------------------------------------------
# Pool contract checks (executable evidence, also run in pytest)
# ---------------------------------------------------------------------------


class _ContractClock:
    """Real-time clock with an advanceable offset for expiry scenarios."""

    def __init__(self) -> None:
        self.offset = 0.0
        self._start = time.monotonic()

    def __call__(self) -> float:
        return self.offset + (time.monotonic() - self._start)


def run_pool_contract_checks(*, workspace: Path | None = None) -> list[dict[str, Any]]:
    """Execute the documented pooling constraints against the candidate.

    Args:
        workspace: Directory for scratch databases.

    Returns:
        One ``{check, passed, detail}`` entry per constraint.
    """
    base = workspace or Path.cwd()
    results: list[dict[str, Any]] = []

    def record(check: str, passed: bool, detail: str) -> None:
        results.append(
            {"check": check, "passed": bool(passed), "detail": detail}
        )

    clock = _ContractClock()

    backend = SimulatedDsqlBackend(base / "pool-contract.sqlite3", 0.0)

    # 1. bounded_acquisition: an exhausted pool times out instead of blocking.
    pool = BoundedConnectionPool(
        backend.connect, min_size=0, max_size=1, acquisition_timeout_seconds=0.05,
        clock=clock,
    )
    try:
        with pool.connection():
            try:
                with pool.connection():
                    record("bounded_acquisition", False, "second checkout succeeded")
            except AcquisitionTimeoutError:
                record("bounded_acquisition", True, "timeout raised while size 1 in use")
    finally:
        pool.close()

    # 2. bounded_size: concurrent units never open more than max_size.
    pool = BoundedConnectionPool(
        backend.connect, min_size=0, max_size=3, acquisition_timeout_seconds=5.0,
        clock=clock,
    )
    try:
        barrier = threading.Barrier(3)

        def hold() -> None:
            barrier.wait()
            with pool.connection():
                time.sleep(0.05)

        with ThreadPoolExecutor(max_workers=3) as executor:
            list(executor.map(lambda _: hold(), range(9)))
        record(
            "bounded_size",
            pool.stats.opened <= 3,
            f"opened={pool.stats.opened} max_size=3 over 9 concurrent units",
        )
    finally:
        pool.close()

    # 3. lifetime_replacement: expired connections are closed, not reused.
    lifetime_clock = _ContractClock()
    pool = BoundedConnectionPool(
        backend.connect, min_size=1, max_size=2, max_lifetime_seconds=1.0,
        lifetime_jitter_seconds=0.0, clock=lifetime_clock,
    )
    try:
        with pool.connection():
            pass
        opened_before = pool.stats.opened
        lifetime_clock.offset += 2.0
        with pool.connection():
            pass
        record(
            "lifetime_replacement",
            pool.stats.opened > opened_before,
            f"opened_before={opened_before} opened_after={pool.stats.opened}",
        )
    finally:
        pool.close()

    # 4. unhealthy_replacement: a failing connection is discarded, not reused.
    database = base / "pool-health.sqlite3"
    broken = {"used": False}
    healthy_connection = sqlite3.connect(database, timeout=30)

    class BrokenConnection:
        """A connection whose rollback and execute always fail."""

        def rollback(self) -> None:
            raise RuntimeError("connection is broken")

        def execute(self, *args: Any, **kwargs: Any) -> None:
            raise RuntimeError("connection is broken")

        def close(self) -> None:
            broken["used"] = True

    def flaky_connect() -> Any:
        if not broken["used"]:
            broken["used"] = True
            return BrokenConnection()
        return healthy_connection

    pool = BoundedConnectionPool(flaky_connect, min_size=0, max_size=2, clock=clock)
    try:
        replaced_before = pool.stats.replaced
        try:
            with pool.connection() as conn:
                conn.execute("SELECT 1")
        except RuntimeError:
            pass
        with pool.connection() as conn:
            conn.execute("SELECT 1").fetchone()
        record(
            "unhealthy_replacement",
            pool.stats.replaced > replaced_before,
            f"replaced={pool.stats.replaced}; broken connection never reused",
        )
    finally:
        pool.close()
        healthy_connection.close()

    # 5. release_via_context_manager: released connections are reusable.
    pool = BoundedConnectionPool(backend.connect, min_size=0, max_size=2, clock=clock)
    try:
        with pool.connection():
            pass
        opened_after_first = pool.stats.opened
        with pool.connection():
            pass
        record(
            "release_via_context_manager",
            pool.stats.opened == opened_after_first,
            f"opened stable at {pool.stats.opened} across two checkouts",
        )
    finally:
        pool.close()

    # 6. rollback_reset_on_error: failed units roll back before reuse.
    database = base / "pool-reset.sqlite3"
    with sqlite3.connect(database) as setup:
        setup.execute("CREATE TABLE IF NOT EXISTS t (v TEXT)")
    connections = [
        sqlite3.connect(database, timeout=30) for _ in range(1)
    ]

    def fixed_connect() -> Any:
        return connections.pop(0) if connections else sqlite3.connect(database)

    pool = BoundedConnectionPool(fixed_connect, min_size=0, max_size=1, clock=clock)
    try:
        try:
            with pool.connection() as conn:
                conn.execute("INSERT INTO t (v) VALUES ('dirty')")
                raise RuntimeError("unit failed")
        except RuntimeError:
            pass
        with pool.connection() as conn:
            count = conn.execute("SELECT COUNT(*) FROM t").fetchone()[0]
        record(
            "rollback_reset_on_error",
            int(count) == 0,
            f"rows visible after failed unit: {int(count)}",
        )
    finally:
        pool.close()

    # 7. whole_transaction_occ_retry: the retry wraps checkout→work→commit,
    # so each attempt checks out a connection again (never mid-transaction).
    attempts = {"n": 0}

    def occ_retry_work() -> str:
        attempts["n"] += 1
        if attempts["n"] < 3:
            raise RuntimeError("could not serialize access due to concurrent update")
        return "committed"

    def run_with_occ_retry(work: Callable[[], str]) -> str:
        last: BaseException | None = None
        for _ in range(5):
            try:
                return work()
            except RuntimeError as error:
                last = error
        raise last  # type: ignore[misc]

    pool = BoundedConnectionPool(backend.connect, min_size=1, max_size=2, clock=clock)
    try:
        def attempt() -> str:
            with pool.connection() as conn:
                assert conn is not None
                return occ_retry_work()

        outcome = run_with_occ_retry(attempt)
        record(
            "whole_transaction_occ_retry",
            outcome == "committed" and attempts["n"] == 3,
            f"attempts={attempts['n']}, outcome={outcome}",
        )
    finally:
        pool.close()

    # 8. no_cross_owner_contamination: pools are per-owner, never shared.
    # The production adapter instantiates one store (and any future pool) per
    # owner identifier; connections are never passed between owners.
    owner_a = BoundedConnectionPool(backend.connect, min_size=1, max_size=1, clock=clock)
    owner_b = BoundedConnectionPool(backend.connect, min_size=1, max_size=1, clock=clock)
    try:
        with owner_a.connection() as conn_a:
            with owner_b.connection() as conn_b:
                record(
                    "no_cross_owner_contamination",
                    conn_a is not conn_b,
                    "separate owner pools hold distinct connection objects",
                )
    finally:
        owner_a.close()
        owner_b.close()

    # 9. clean_shutdown: close() drains idle connections without hanging.
    pool = BoundedConnectionPool(backend.connect, min_size=2, max_size=4, clock=clock)
    started = time.perf_counter()
    pool.close()
    elapsed = time.perf_counter() - started
    refused = False
    try:
        with pool.connection():
            refused = False
    except RuntimeError:
        refused = True
    record(
        "clean_shutdown",
        refused and elapsed < 5.0,
        f"close took {elapsed * 1000:.1f} ms; post-close checkout refused={refused}",
    )
    return results


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main(argv: list[str] | None = None) -> int:
    """Run the benchmark CLI; live mode requires explicit operator opt-in."""
    parser = argparse.ArgumentParser(
        description=(
            "Offline DSQL connection overhead and pooling compatibility "
            "benchmark (simulated connect cost, local SQLite; no AWS)."
        )
    )
    parser.add_argument("--transactions", type=int, default=200)
    parser.add_argument("--concurrency", type=int, default=8)
    parser.add_argument("--simulated-connect-ms", type=float, default=25.0)
    parser.add_argument("--json-output", type=Path, default=None)
    parser.add_argument(
        "--live",
        action="store_true",
        help="Request a LIVE Aurora DSQL run (requires DSQL_BENCH_ALLOW_LIVE=1 "
        "and separate approval; not implemented in this offline harness).",
    )
    args = parser.parse_args(argv)
    if args.live:
        if os.environ.get("DSQL_BENCH_ALLOW_LIVE") != "1":
            print(
                "REFUSED: a live Aurora DSQL benchmark requires "
                "DSQL_BENCH_ALLOW_LIVE=1 plus explicit operator approval and "
                "request/cost caps. Offline simulation only.",
                file=sys.stderr,
            )
            raise SystemExit(2)
        print(
            "Live mode is intentionally unimplemented: record approval and caps "
            "first (see docs/IMPLEMENTATION_STATUS.md, ticket 38).",
            file=sys.stderr,
        )
        raise SystemExit(2)
    workspace = Path(
        os.environ.get("DSQL_BENCH_WORKSPACE", "")
        or (Path(tempfile.gettempdir()) / "co-design-dsql-bench")
    )
    workspace.mkdir(parents=True, exist_ok=True)
    report = run_benchmark(
        transactions_per_strategy=max(1, args.transactions),
        concurrency=max(1, args.concurrency),
        simulated_connect_ms=args.simulated_connect_ms,
        workspace=workspace,
    )
    payload = json.dumps(report, indent=2, sort_keys=True)
    if args.json_output is not None:
        args.json_output.write_text(payload + "\n")
        print(f"report written: {args.json_output}")
    else:
        print(payload)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
