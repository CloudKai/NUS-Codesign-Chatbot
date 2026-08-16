#!/usr/bin/env python3
"""Deterministic mock-provider load probe for pre-release capacity checks.

This tool never calls paid providers or live AWS. It exercises the FastAPI
surface with the in-process mock coach against a temporary SQLite store.

Virtual users are distinct authenticated owners (Cognito ``sub`` → owner-scoped
store). Do not treat a shared ``local-student`` store as many students.

Examples:

```bash
.venv/bin/python scripts/load_probe.py --users 10 --requests-per-user 5
.venv/bin/python scripts/load_probe.py --scenario distinct-owners --users 100
.venv/bin/python scripts/load_probe.py --scenario two-notebooks
.venv/bin/python scripts/load_probe.py --scenario same-notebook
```

Results are aggregate only (no notebook IDs, emails, or message text).
"""

from __future__ import annotations

import argparse
import statistics
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any, Callable
from uuid import uuid4

from fastapi.testclient import TestClient

from backend.api import create_app
from backend.application import CoachApplicationService
from backend.auth_oidc import CognitoIdentity, CognitoOIDCClient, CognitoOIDCError
from backend.cognito_config import CognitoAuthConfig
from backend.rate_limit import reset_coach_rate_limiter_for_tests
from backend.settings import settings
from backend.student_journey import DEFAULT_STAGE
from backend.student_store import StudentStore


_PROBE_METADATA = {
    "issuer": "https://probe.example.test/pool",
    "authorization_endpoint": "https://probe.example.test/oauth2/authorize",
    "token_endpoint": "https://probe.example.test/oauth2/token",
    "jwks_uri": "https://probe.example.test/oauth2/jwks",
    "revocation_endpoint": "https://probe.example.test/oauth2/revoke",
}


class ProbeOIDC(CognitoOIDCClient):
    """In-memory ID-token verifier so each virtual user is a distinct owner."""

    def verify_id_token(self, id_token: str) -> CognitoIdentity:
        """Map ``probe:<sub>`` cookies onto a verified Cognito identity."""
        token = str(id_token or "").strip()
        prefix = "probe:"
        if not token.startswith(prefix):
            raise CognitoOIDCError("Unknown probe token")
        sub = token[len(prefix) :].strip()
        if not sub:
            raise CognitoOIDCError("Unknown probe token")
        return CognitoIdentity(
            sub=sub,
            email=f"{sub}@probe.example.edu",
            claims={"sub": sub, "email": f"{sub}@probe.example.edu"},
        )


@dataclass
class ProbeReport:
    """Aggregate probe outcome without student or notebook identifiers."""

    scenario: str
    virtual_users: int
    accepted: int
    rate_limited: int
    failed: int
    p50_ms: float
    p95_ms: float
    mean_ms: float
    requests_per_sec: float

    def as_dict(self) -> dict[str, Any]:
        """Return a JSON-serializable aggregate summary."""
        return {
            "scenario": self.scenario,
            "virtual_users": self.virtual_users,
            "accepted": self.accepted,
            "rate_limited": self.rate_limited,
            "failed": self.failed,
            "p50_ms": self.p50_ms,
            "p95_ms": self.p95_ms,
            "mean_ms": self.mean_ms,
            "requests_per_sec": self.requests_per_sec,
            "note": "mock provider only; distinct owners; do not claim live EC2 sizing",
        }


def _cookie_name() -> str:
    """Return the Cognito ID-cookie name used by FastAPI owner resolution."""
    return settings.cognito_id_token_cookie_name


def _force_mock_capacity() -> None:
    """Pin the probe to mock coaching and the intended production ceilings."""
    settings.model_provider = "mock"
    settings.mock_openai = True
    settings.database_provider = "sqlite"
    settings.file_storage_provider = "local"
    settings.auth_cookie_secure = False
    settings.max_active_coach_requests_per_notebook = 1
    settings.max_active_coach_requests_per_user = 2
    settings.coach_requests_per_minute = 10_000
    settings.max_concurrent_model_calls = 120
    reset_coach_rate_limiter_for_tests()


def _seed_owner(store: StudentStore, *, sub: str) -> dict[str, str]:
    """Create one Cognito-backed owner and return their ID-cookie mapping."""
    store.upsert_cognito_user(
        cognito_sub=sub,
        identifier=f"cognito:{sub}",
        email=f"{sub}@probe.example.edu",
        display_name=sub,
    )
    return {_cookie_name(): f"probe:{sub}"}


def _percentile(ordered: list[float], fraction: float) -> float:
    """Return a simple percentile from an already-sorted latency list."""
    if not ordered:
        return 0.0
    index = int(fraction * (len(ordered) - 1))
    return ordered[index]


def _summarize(
    *,
    scenario: str,
    virtual_users: int,
    latencies_ms: list[float],
    accepted: int,
    rate_limited: int,
    failed: int,
    wall_seconds: float,
) -> ProbeReport:
    """Build an aggregate report from collected counters."""
    ordered = sorted(latencies_ms)
    total = len(ordered)
    return ProbeReport(
        scenario=scenario,
        virtual_users=virtual_users,
        accepted=accepted,
        rate_limited=rate_limited,
        failed=failed,
        p50_ms=round(_percentile(ordered, 0.50), 1),
        p95_ms=round(_percentile(ordered, 0.95), 1),
        mean_ms=round(statistics.fmean(latencies_ms), 1) if latencies_ms else 0.0,
        requests_per_sec=round(total / wall_seconds, 2) if wall_seconds and total else 0.0,
    )


def _coach_payload(thread_id: str, *, key: str) -> dict[str, str]:
    """Return one privacy-safe mock coaching payload."""
    return {
        "thread_id": thread_id,
        "student_message": "Load probe claim",
        "current_stage": DEFAULT_STAGE,
        "response_detail": "short",
        "idempotency_key": key,
    }


def _create_notebook(client: TestClient, cookies: dict[str, str], *, label: str) -> str:
    """Create one notebook for an authenticated probe owner."""
    response = client.post(
        "/api/v1/threads",
        cookies=cookies,
        json={
            "name": label,
            "model_id": "mock",
            "support_mode": "critical-thinking",
        },
    )
    if response.status_code >= 400:
        raise RuntimeError("probe notebook create failed")
    return str(response.json()["id"])


def _build_client(tmp: Path) -> tuple[TestClient, StudentStore, ProbeOIDC]:
    """Return a mock FastAPI client with distinct-owner OIDC."""
    store = StudentStore(tmp / "load.sqlite3")
    oidc = ProbeOIDC(
        CognitoAuthConfig(
            client_id="probe-client",
            client_secret="probe-secret",
            server_metadata_url=(
                "https://probe.example.test/.well-known/openid-configuration"
            ),
            redirect_uri="http://127.0.0.1:8000/api/v1/auth/callback",
        ),
        store=store,
        metadata_loader=lambda _url: _PROBE_METADATA,
    )
    client = TestClient(create_app(store, oidc_client=oidc))
    return client, store, oidc


def run_sequential_probe(*, users: int, requests_per_user: int) -> ProbeReport:
    """Run sequential coaching turns for distinct authenticated owners."""
    _force_mock_capacity()
    latencies_ms: list[float] = []
    accepted = 0
    rate_limited = 0
    failed = 0
    lock = threading.Lock()

    with TemporaryDirectory(prefix="co-design-load-") as tmp:
        client, store, _oidc = _build_client(Path(tmp))

        def worker(user_index: int) -> None:
            nonlocal accepted, rate_limited, failed
            sub = f"seq-{user_index}-{uuid4().hex[:8]}"
            cookies = _seed_owner(store, sub=sub)
            try:
                thread_id = _create_notebook(
                    client, cookies, label=f"probe-{user_index}"
                )
            except RuntimeError:
                with lock:
                    failed += 1
                return
            for index in range(requests_per_user):
                started = time.perf_counter()
                response = client.post(
                    "/api/v1/coach/turn",
                    cookies=cookies,
                    json=_coach_payload(
                        thread_id, key=f"seq-{user_index}-{index}-{uuid4()}"
                    ),
                )
                elapsed_ms = (time.perf_counter() - started) * 1000.0
                with lock:
                    latencies_ms.append(elapsed_ms)
                    if response.status_code == 200:
                        accepted += 1
                    elif response.status_code == 429:
                        rate_limited += 1
                    else:
                        failed += 1

        started_all = time.perf_counter()
        with ThreadPoolExecutor(max_workers=users) as executor:
            futures = [executor.submit(worker, index) for index in range(users)]
            for future in as_completed(futures):
                future.result()
        wall_seconds = time.perf_counter() - started_all

    return _summarize(
        scenario="sequential",
        virtual_users=users,
        latencies_ms=latencies_ms,
        accepted=accepted,
        rate_limited=rate_limited,
        failed=failed,
        wall_seconds=wall_seconds,
    )


def run_distinct_owner_probe(*, users: int) -> ProbeReport:
    """Fire one concurrent coaching turn per distinct authenticated owner."""
    _force_mock_capacity()
    latencies_ms: list[float] = []
    accepted = 0
    rate_limited = 0
    failed = 0
    lock = threading.Lock()

    with TemporaryDirectory(prefix="co-design-load-") as tmp:
        client, store, _oidc = _build_client(Path(tmp))
        prepared: list[tuple[dict[str, str], str]] = []
        for index in range(users):
            sub = f"owner-{index}-{uuid4().hex[:8]}"
            cookies = _seed_owner(store, sub=sub)
            thread_id = _create_notebook(client, cookies, label=f"owner-{index}")
            prepared.append((cookies, thread_id))

        def worker(item: tuple[dict[str, str], str]) -> None:
            nonlocal accepted, rate_limited, failed
            cookies, thread_id = item
            started = time.perf_counter()
            response = client.post(
                "/api/v1/coach/turn",
                cookies=cookies,
                json=_coach_payload(thread_id, key=f"owner-{uuid4()}"),
            )
            elapsed_ms = (time.perf_counter() - started) * 1000.0
            with lock:
                latencies_ms.append(elapsed_ms)
                if response.status_code == 200:
                    accepted += 1
                elif response.status_code == 429:
                    rate_limited += 1
                else:
                    failed += 1

        started_all = time.perf_counter()
        with ThreadPoolExecutor(max_workers=users) as executor:
            futures = [executor.submit(worker, item) for item in prepared]
            for future in as_completed(futures):
                future.result()
        wall_seconds = time.perf_counter() - started_all

    return _summarize(
        scenario="distinct-owners",
        virtual_users=users,
        latencies_ms=latencies_ms,
        accepted=accepted,
        rate_limited=rate_limited,
        failed=failed,
        wall_seconds=wall_seconds,
    )


def _gated_submit(hold: threading.Event, started: threading.Event) -> Callable:
    """Return a ``_submit_once`` wrapper that holds until *hold* is set."""
    original = CoachApplicationService._submit_once

    def wrapped(self, request, **kwargs):
        started.set()
        assert hold.wait(timeout=5)
        return original(self, request, **kwargs)

    return wrapped


def run_two_notebooks_probe() -> ProbeReport:
    """One owner, two notebooks, two simultaneous turns must both be accepted."""
    _force_mock_capacity()
    hold = threading.Event()
    started = threading.Barrier(2)
    original = CoachApplicationService._submit_once

    def gated(self, request, **kwargs):
        started.wait(timeout=5)
        hold.set()
        return original(self, request, **kwargs)

    CoachApplicationService._submit_once = gated  # type: ignore[method-assign]
    try:
        with TemporaryDirectory(prefix="co-design-load-") as tmp:
            client, store, _oidc = _build_client(Path(tmp))
            cookies = _seed_owner(store, sub=f"two-nb-{uuid4().hex[:8]}")
            first = _create_notebook(client, cookies, label="nb-1")
            second = _create_notebook(client, cookies, label="nb-2")
            statuses: list[int] = []
            latencies_ms: list[float] = []

            def worker(thread_id: str) -> None:
                started_at = time.perf_counter()
                response = client.post(
                    "/api/v1/coach/turn",
                    cookies=cookies,
                    json=_coach_payload(thread_id, key=f"two-{uuid4()}"),
                )
                latencies_ms.append((time.perf_counter() - started_at) * 1000.0)
                statuses.append(response.status_code)

            wall_started = time.perf_counter()
            with ThreadPoolExecutor(max_workers=2) as executor:
                futures = [executor.submit(worker, first), executor.submit(worker, second)]
                for future in as_completed(futures):
                    future.result()
            wall_seconds = time.perf_counter() - wall_started
    finally:
        CoachApplicationService._submit_once = original  # type: ignore[method-assign]

    accepted = sum(1 for status in statuses if status == 200)
    rate_limited = sum(1 for status in statuses if status == 429)
    failed = sum(1 for status in statuses if status not in {200, 429})
    return _summarize(
        scenario="two-notebooks",
        virtual_users=1,
        latencies_ms=latencies_ms,
        accepted=accepted,
        rate_limited=rate_limited,
        failed=failed,
        wall_seconds=wall_seconds,
    )


def run_same_notebook_probe() -> ProbeReport:
    """One owner, one notebook, two overlapping turns: only one may execute."""
    _force_mock_capacity()
    hold = threading.Event()
    started = threading.Event()
    original = CoachApplicationService._submit_once
    CoachApplicationService._submit_once = _gated_submit(hold, started)  # type: ignore[method-assign]
    statuses: list[int] = []
    latencies_ms: list[float] = []
    wall_seconds = 0.0
    try:
        with TemporaryDirectory(prefix="co-design-load-") as tmp:
            client, store, _oidc = _build_client(Path(tmp))
            cookies = _seed_owner(store, sub=f"same-nb-{uuid4().hex[:8]}")
            thread_id = _create_notebook(client, cookies, label="nb-1")

            def first() -> None:
                started_at = time.perf_counter()
                response = client.post(
                    "/api/v1/coach/turn",
                    cookies=cookies,
                    json=_coach_payload(thread_id, key=f"same-1-{uuid4()}"),
                )
                latencies_ms.append((time.perf_counter() - started_at) * 1000.0)
                statuses.append(response.status_code)

            wall_started = time.perf_counter()
            with ThreadPoolExecutor(max_workers=1) as executor:
                future = executor.submit(first)
                assert started.wait(timeout=5)
                started_at = time.perf_counter()
                second = client.post(
                    "/api/v1/coach/turn",
                    cookies=cookies,
                    json=_coach_payload(thread_id, key=f"same-2-{uuid4()}"),
                )
                latencies_ms.append((time.perf_counter() - started_at) * 1000.0)
                statuses.append(second.status_code)
                hold.set()
                future.result(timeout=8)
            wall_seconds = time.perf_counter() - wall_started
    finally:
        CoachApplicationService._submit_once = original  # type: ignore[method-assign]

    accepted = sum(1 for status in statuses if status == 200)
    rate_limited = sum(1 for status in statuses if status == 429)
    failed = sum(1 for status in statuses if status not in {200, 429})
    return _summarize(
        scenario="same-notebook",
        virtual_users=1,
        latencies_ms=latencies_ms,
        accepted=accepted,
        rate_limited=rate_limited,
        failed=failed,
        wall_seconds=wall_seconds,
    )


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--scenario",
        choices=("sequential", "distinct-owners", "two-notebooks", "same-notebook"),
        default="sequential",
    )
    parser.add_argument("--users", type=int, default=10)
    parser.add_argument("--requests-per-user", type=int, default=3)
    return parser.parse_args()


def main() -> None:
    """Run the selected mock-only concurrency probe and print aggregates."""
    args = _parse_args()
    users = max(1, min(int(args.users), 120))
    requests_per_user = max(1, min(int(args.requests_per_user), 20))
    if args.scenario == "sequential":
        report = run_sequential_probe(users=users, requests_per_user=requests_per_user)
    elif args.scenario == "distinct-owners":
        report = run_distinct_owner_probe(users=users)
    elif args.scenario == "two-notebooks":
        report = run_two_notebooks_probe()
    else:
        report = run_same_notebook_probe()
    print(report.as_dict())


if __name__ == "__main__":
    main()
