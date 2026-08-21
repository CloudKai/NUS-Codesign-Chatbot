#!/usr/bin/env python3
"""Deterministic mock-provider load probe for pre-release capacity checks.

This tool never calls paid providers or live AWS. It exercises the FastAPI
surface with the in-process mock coach against a temporary SQLite store.

Virtual users are distinct authenticated owners (Cognito ``sub`` → owner-scoped
store). Do not treat a shared ``local-student`` store as many students.

Fake provider delays and fake Knowledge Base ``Retrieve`` clients are
script-only. They do not change production configuration, Fast Chat prompts,
RAG validation, citations, stage progression, Deep Review, Guardrails, or
AgentCore structured-output logic.

Latency here is mock/fake-sleep latency. It is not Haiku or AgentCore latency.
This answers whether FastAPI, rate limits, ownership, persistence, and the
Retrieve pool can hold many simultaneous requests. It does not size EC2.

Examples:

```bash
.venv/bin/python scripts/load_probe.py --users 10 --requests-per-user 5
.venv/bin/python scripts/load_probe.py --scenario distinct-owners --users 100
.venv/bin/python scripts/load_probe.py --scenario two-notebooks
.venv/bin/python scripts/load_probe.py --scenario same-notebook
.venv/bin/python scripts/load_probe.py --scenario slow-distinct-owners --users 10
.venv/bin/python scripts/load_probe.py --scenario kb-pool --kb-workers 4 --users 16
.venv/bin/python scripts/load_probe.py --run-phase existing
```

Results are aggregate only (no notebook IDs, emails, or message text).
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import resource
import statistics
import sys
import tempfile
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any, Callable, Iterator
from uuid import uuid4

_PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))


def _bootstrap_free_local_env() -> None:
    """Force mock/sqlite/local paths before backend import so .env cannot reach AWS.

    ``load_dotenv`` does not override existing environment variables. Setting
    these first keeps CLI runs at $0 AWS even when the operator ``.env`` is
    production-shaped. Pytest already bootstraps via ``tests/conftest.py``.
    """
    bootstrap = Path(tempfile.mkdtemp(prefix="co-design-load-bootstrap-"))
    for child in ("files", "workspaces", "lecture_notes"):
        (bootstrap / child).mkdir(parents=True, exist_ok=True)
    os.environ["APP_ENV"] = "development"
    os.environ["MOCK_OPENAI"] = "true"
    os.environ["MODEL_PROVIDER"] = "mock"
    os.environ["OPENAI_API_KEY"] = ""
    os.environ["DATABASE_PROVIDER"] = "sqlite"
    os.environ["FILE_STORAGE_PROVIDER"] = "local"
    os.environ["COURSE_MATERIAL_SYNC_ENABLED"] = "false"
    os.environ["KNOWLEDGE_BASE_ID"] = ""
    os.environ["AGENTCORE_RUNTIME_ARN"] = ""
    os.environ["APP_DATA_DIR"] = str(bootstrap)
    os.environ["APP_DATABASE_PATH"] = str(bootstrap / "co_design.sqlite3")
    os.environ["APP_FILES_DIR"] = str(bootstrap / "files")
    os.environ["APP_WORKSPACES_DIR"] = str(bootstrap / "workspaces")
    os.environ["LECTURE_NOTES_DIR"] = str(bootstrap / "lecture_notes")


if "backend.settings" not in sys.modules:
    _bootstrap_free_local_env()

from fastapi.testclient import TestClient

from backend.api import create_app
from backend.application import CoachApplicationService
from backend.auth_oidc import CognitoIdentity, CognitoOIDCClient, CognitoOIDCError
from backend.bedrock_retrieve import (
    BedrockKnowledgeBaseRetriever,
    reset_shared_retrieve_executor,
    retrieve_pool_stats,
)
from backend.cognito_config import CognitoAuthConfig
from backend.mock_provider import DeterministicCoachProvider
from backend.rate_limit import reset_coach_rate_limiter_for_tests
from backend.retrieval import RetrievalQuery, RetrievalSource
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

_COURSE_BUCKET = "cde2300-course-content-s3"
_COURSE_KEY = "course/lectureNotes/crossing.pdf"
_COURSE_EXCERPT = "Older adults need longer crossing time at signalized intersections."

_CAPACITY_SETTING_NAMES = (
    "app_env",
    "course_material_sync_enabled",
    "model_provider",
    "mock_openai",
    "database_provider",
    "file_storage_provider",
    "auth_cookie_secure",
    "max_active_coach_requests_per_notebook",
    "max_active_coach_requests_per_user",
    "coach_requests_per_minute",
    "max_concurrent_model_calls",
    "sync_threadpool_tokens",
    "knowledge_base_id",
    "knowledge_base_retrieve_executor_workers",
)

_EXISTING_USER_COUNTS = (10, 25, 50, 90, 120)
_SLOW_USER_COUNTS = (10, 25, 50, 90)
_SLOW_DELAYS_MS = (5000, 8000, 10000, 12000)
_DEFAULT_SLOW_DELAY_MS = 10000
_KB_WORKER_COUNTS = (4, 8, 12, 16)
_KB_DELAYS_MS = (500, 1000, 3000)
_KB_CONCURRENCY = (4, 8, 16, 30, 50, 90)


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
    users: int
    accepted: int
    rate_limited: int
    failed: int
    p50_ms: float
    p95_ms: float
    mean_ms: float
    requests_per_sec: float
    requests: int | None = None
    fake_provider_delay_ms: int | None = None
    fake_kb_delay_ms: int | None = None
    kb_workers: int | None = None
    capacity_exhausted: int | None = None
    peak_threads: int | None = None
    peak_kb_admitted: int | None = None
    peak_kb_worker_threads: int | None = None
    rss_peak_kb: int | None = None
    ownership_violations: int | None = None
    structurally_invalid: int | None = None
    unexpected_queueing: int | None = None
    pool_recovered: int | None = None
    provider_calls: int | None = None
    assistant_turns_after_failure: int | None = None
    note: str = (
        "mock/fake only; distinct owners; not AgentCore/Haiku latency; "
        "do not claim live EC2 sizing"
    )

    @property
    def virtual_users(self) -> int:
        """Backward-compatible alias for ``users``."""
        return self.users

    def as_dict(self) -> dict[str, Any]:
        """Return a JSON-serializable aggregate summary with nulls for n/a."""
        requests = self.requests
        if requests is None:
            requests = self.accepted + self.rate_limited + self.failed
        return {
            "scenario": self.scenario,
            "users": self.users,
            "virtual_users": self.users,
            "fake_provider_delay_ms": self.fake_provider_delay_ms,
            "fake_kb_delay_ms": self.fake_kb_delay_ms,
            "kb_workers": self.kb_workers,
            "requests": requests,
            "accepted": self.accepted,
            "rate_limited": self.rate_limited,
            "capacity_exhausted": self.capacity_exhausted,
            "failed": self.failed,
            "p50_ms": self.p50_ms,
            "p95_ms": self.p95_ms,
            "mean_ms": self.mean_ms,
            "requests_per_sec": self.requests_per_sec,
            "peak_threads": self.peak_threads,
            "peak_kb_admitted": self.peak_kb_admitted,
            "peak_kb_worker_threads": self.peak_kb_worker_threads,
            "rss_peak_kb": self.rss_peak_kb,
            "process_max_rss_kb": self.rss_peak_kb,
            "ownership_violations": self.ownership_violations,
            "structurally_invalid": self.structurally_invalid,
            "unexpected_queueing": self.unexpected_queueing,
            "pool_recovered": self.pool_recovered,
            "provider_calls": self.provider_calls,
            "assistant_turns_after_failure": self.assistant_turns_after_failure,
            "note": self.note,
        }


class _ResourceSampler:
    """Sample Python threads, KB pool occupancy, and RSS during a burst."""

    def __init__(self) -> None:
        self.peak_threads = threading.active_count()
        self.peak_kb_admitted = 0
        self.peak_kb_worker_threads = 0
        self.rss_peak_kb = _rss_kb()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def _sample(self) -> None:
        """Capture one occupancy snapshot. Never logs request content."""
        self.peak_threads = max(self.peak_threads, threading.active_count())
        stats = retrieve_pool_stats()
        self.peak_kb_admitted = max(self.peak_kb_admitted, int(stats["admitted"]))
        self.peak_kb_worker_threads = max(
            self.peak_kb_worker_threads, int(stats["worker_threads"])
        )
        rss = _rss_kb()
        if rss is not None:
            self.rss_peak_kb = max(self.rss_peak_kb or 0, rss)

    def start(self) -> None:
        """Start the background sampler thread."""
        self._sample()

        def loop() -> None:
            while not self._stop.wait(0.02):
                self._sample()

        self._thread = threading.Thread(
            target=loop, name="load-probe-sampler", daemon=True
        )
        self._thread.start()

    def stop(self) -> None:
        """Stop sampling and take a final snapshot."""
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=1.0)
        self._sample()


class _FakeSleepRetrieveClient:
    """Injected Retrieve client: sleep, then return valid fake hits. No AWS."""

    def __init__(self, delay_seconds: float, *, foreign_bucket: bool = False) -> None:
        self.delay_seconds = max(0.0, float(delay_seconds))
        self.foreign_bucket = bool(foreign_bucket)
        self.calls = 0
        self.in_flight = 0
        self.peak_in_flight = 0
        self._lock = threading.Lock()

    def retrieve(self, **kwargs: Any) -> dict[str, Any]:
        """Sleep, then return realistic ``retrievalResults``. Never calls AWS."""
        del kwargs
        with self._lock:
            self.calls += 1
            self.in_flight += 1
            self.peak_in_flight = max(self.peak_in_flight, self.in_flight)
        try:
            if self.delay_seconds:
                time.sleep(self.delay_seconds)
            bucket = "unrelated-bucket" if self.foreign_bucket else _COURSE_BUCKET
            key = "users/secret.pdf" if self.foreign_bucket else _COURSE_KEY
            return {
                "retrievalResults": [
                    {
                        "content": {"text": _COURSE_EXCERPT},
                        "location": {
                            "type": "S3",
                            "s3Location": {"uri": f"s3://{bucket}/{key}"},
                        },
                        "score": 0.91,
                    }
                ]
            }
        finally:
            with self._lock:
                self.in_flight -= 1


def _rss_kb() -> int | None:
    """Return process-lifetime maximum RSS in KiB when the platform reports it.

    ``resource.getrusage(RUSAGE_SELF).ru_maxrss`` is a high-water mark for
    the whole Python process, not exact per-scenario incremental memory.
    macOS reports bytes; Linux reports KiB. The JSON field ``rss_peak_kb``
    is kept for compatibility; ``process_max_rss_kb`` is the same value
    with a clearer name.
    """
    try:
        usage = resource.getrusage(resource.RUSAGE_SELF)
    except Exception:
        return None
    rss = int(getattr(usage, "ru_maxrss", 0) or 0)
    if rss <= 0:
        return None
    if sys.platform == "darwin":
        return rss // 1024
    return rss


def _cookie_name() -> str:
    """Return the Cognito ID-cookie name used by FastAPI owner resolution."""
    return settings.cognito_id_token_cookie_name


def _snapshot_capacity_settings() -> dict[str, Any]:
    """Copy settings the probe mutates so callers can restore them."""
    return {name: getattr(settings, name) for name in _CAPACITY_SETTING_NAMES}


def _restore_capacity_settings(snapshot: dict[str, Any]) -> None:
    """Restore settings mutated by the probe. Does not contact AWS."""
    for name, value in snapshot.items():
        setattr(settings, name, value)
    reset_coach_rate_limiter_for_tests()


def _force_mock_capacity() -> None:
    """Pin the probe to mock coaching and the intended production ceilings.

    Defense in depth when ``backend.settings`` was already imported before
    this module: force development and disable course-material sync even if
    the process previously loaded production-shaped settings.

    Knowledge Base id is cleared so ``configured_context_retriever`` cannot
    construct a live bedrock-agent-runtime client. The KB pool scenario
    injects a fake client into the real retriever instead.
    """
    settings.app_env = "development"
    settings.course_material_sync_enabled = False
    settings.model_provider = "mock"
    settings.mock_openai = True
    settings.database_provider = "sqlite"
    settings.file_storage_provider = "local"
    settings.auth_cookie_secure = False
    settings.max_active_coach_requests_per_notebook = 1
    settings.max_active_coach_requests_per_user = 2
    settings.coach_requests_per_minute = 10_000
    settings.max_concurrent_model_calls = 120
    settings.sync_threadpool_tokens = 120
    settings.knowledge_base_id = ""
    reset_coach_rate_limiter_for_tests()
    if (settings.app_env or "").strip().lower() != "development":
        raise RuntimeError("load probe refused: app_env is not development")
    if settings.course_material_sync_enabled:
        raise RuntimeError("load probe refused: course material sync must stay disabled")
    if settings.model_provider != "mock":
        raise RuntimeError("load probe refused: model provider is not mock")
    if settings.database_provider != "sqlite":
        raise RuntimeError("load probe refused: database provider is not sqlite")
    if str(settings.knowledge_base_id or "").strip():
        raise RuntimeError("load probe refused: knowledge base id must stay empty")


@contextmanager
def _fake_slow_provider(delay_ms: int) -> Iterator[dict[str, int]]:
    """Sleep inside ``DeterministicCoachProvider.assess`` then call the original.

    Restores the unbound method on exit so production mock behaviour cannot
    leak across tests. Never contacts a model or AWS.
    """
    original = DeterministicCoachProvider.assess
    calls = {"n": 0}
    lock = threading.Lock()
    delay_seconds = max(0, int(delay_ms)) / 1000.0

    def delayed(self: DeterministicCoachProvider, request: Any) -> Any:
        with lock:
            calls["n"] += 1
        if delay_seconds:
            time.sleep(delay_seconds)
        return original(self, request)

    DeterministicCoachProvider.assess = delayed  # type: ignore[method-assign]
    try:
        yield calls
    finally:
        DeterministicCoachProvider.assess = original  # type: ignore[method-assign]


@contextmanager
def _failing_provider() -> Iterator[dict[str, int]]:
    """Raise after the fake delay hook so failed turns can be inspected."""
    original = DeterministicCoachProvider.assess
    calls = {"n": 0}
    lock = threading.Lock()

    def failing(self: DeterministicCoachProvider, request: Any) -> Any:
        del self, request
        with lock:
            calls["n"] += 1
        raise RuntimeError("probe-only deterministic provider failure")

    DeterministicCoachProvider.assess = failing  # type: ignore[method-assign]
    try:
        yield calls
    finally:
        DeterministicCoachProvider.assess = original  # type: ignore[method-assign]


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
    users: int,
    latencies_ms: list[float],
    accepted: int,
    rate_limited: int,
    failed: int,
    wall_seconds: float,
    requests: int | None = None,
    fake_provider_delay_ms: int | None = None,
    fake_kb_delay_ms: int | None = None,
    kb_workers: int | None = None,
    capacity_exhausted: int | None = None,
    peak_threads: int | None = None,
    peak_kb_admitted: int | None = None,
    peak_kb_worker_threads: int | None = None,
    rss_peak_kb: int | None = None,
    ownership_violations: int | None = None,
    structurally_invalid: int | None = None,
    unexpected_queueing: int | None = None,
    pool_recovered: int | None = None,
    provider_calls: int | None = None,
    assistant_turns_after_failure: int | None = None,
) -> ProbeReport:
    """Build an aggregate report from collected counters."""
    ordered = sorted(latencies_ms)
    total = requests if requests is not None else len(ordered)
    return ProbeReport(
        scenario=scenario,
        users=users,
        accepted=accepted,
        rate_limited=rate_limited,
        failed=failed,
        p50_ms=round(_percentile(ordered, 0.50), 1),
        p95_ms=round(_percentile(ordered, 0.95), 1),
        mean_ms=round(statistics.fmean(latencies_ms), 1) if latencies_ms else 0.0,
        requests_per_sec=round(total / wall_seconds, 2) if wall_seconds and total else 0.0,
        requests=total,
        fake_provider_delay_ms=fake_provider_delay_ms,
        fake_kb_delay_ms=fake_kb_delay_ms,
        kb_workers=kb_workers,
        capacity_exhausted=capacity_exhausted,
        peak_threads=peak_threads,
        peak_kb_admitted=peak_kb_admitted,
        peak_kb_worker_threads=peak_kb_worker_threads,
        rss_peak_kb=rss_peak_kb,
        ownership_violations=ownership_violations,
        structurally_invalid=structurally_invalid,
        unexpected_queueing=unexpected_queueing,
        pool_recovered=pool_recovered,
        provider_calls=provider_calls,
        assistant_turns_after_failure=assistant_turns_after_failure,
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


def _build_client(
    tmp: Path, *, raise_server_exceptions: bool = True
) -> tuple[TestClient, StudentStore, ProbeOIDC]:
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
    client = TestClient(
        create_app(store, oidc_client=oidc),
        raise_server_exceptions=raise_server_exceptions,
    )
    return client, store, oidc


def _turn_is_structurally_valid(payload: Any) -> bool:
    """Return whether a 200 body looks like a CoachTurn without copying text."""
    if not isinstance(payload, dict):
        return False
    text = payload.get("response_text")
    assessment = payload.get("assessment")
    return isinstance(text, str) and bool(text.strip()) and isinstance(assessment, dict)


def _count_assistant_messages(payload: Any) -> int:
    """Count assistant rows without retaining message text."""
    if not isinstance(payload, list):
        return -1
    return sum(1 for item in payload if isinstance(item, dict) and item.get("role") == "assistant")


def _ownership_violations(
    client: TestClient, prepared: list[tuple[dict[str, str], str]]
) -> int:
    """Count cross-owner notebook or message visibility failures."""
    violations = 0
    all_ids = [thread_id for _cookies, thread_id in prepared]
    for index, (cookies, thread_id) in enumerate(prepared):
        listed = client.get("/api/v1/threads", cookies=cookies)
        if listed.status_code != 200:
            violations += 1
            continue
        body = listed.json()
        ids = {str(item.get("id")) for item in body if isinstance(item, dict)}
        if thread_id not in ids:
            violations += 1
        foreign = [other for i, other in enumerate(all_ids) if i != index]
        if any(other in ids for other in foreign):
            violations += 1
        if foreign:
            leaked = client.get(
                f"/api/v1/threads/{foreign[0]}/messages", cookies=cookies
            )
            if leaked.status_code != 404:
                violations += 1
    return violations


def _course_query() -> RetrievalQuery:
    """Return one selected course-source query for the fake Retrieve client."""
    return RetrievalQuery(
        current_message="What crossing time do older pedestrians need?",
        current_stage="problem_identification",
        sources=(
            RetrievalSource(
                source_id="src-lecture",
                label="S1",
                title="Lecture",
                text="Local extracted course text should not be required for KB hits.",
                group="lectureNotes",
                object_key=_COURSE_KEY,
            ),
        ),
    )


def _wait_pool_idle(*, timeout_seconds: float) -> bool:
    """Wait until admitted Retrieve slots return to zero."""
    deadline = time.monotonic() + max(0.05, timeout_seconds)
    while time.monotonic() < deadline:
        if int(retrieve_pool_stats()["admitted"]) == 0:
            return True
        time.sleep(0.02)
    return int(retrieve_pool_stats()["admitted"]) == 0


def run_sequential_probe(*, users: int, requests_per_user: int) -> ProbeReport:
    """Run sequential coaching turns for distinct authenticated owners."""
    snapshot = _snapshot_capacity_settings()
    _force_mock_capacity()
    latencies_ms: list[float] = []
    accepted = 0
    rate_limited = 0
    failed = 0
    lock = threading.Lock()
    sampler = _ResourceSampler()
    try:
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

            sampler.start()
            started_all = time.perf_counter()
            with ThreadPoolExecutor(max_workers=users) as executor:
                futures = [executor.submit(worker, index) for index in range(users)]
                for future in as_completed(futures):
                    future.result()
            wall_seconds = time.perf_counter() - started_all
            sampler.stop()
    finally:
        _restore_capacity_settings(snapshot)

    return _summarize(
        scenario="sequential",
        users=users,
        latencies_ms=latencies_ms,
        accepted=accepted,
        rate_limited=rate_limited,
        failed=failed,
        wall_seconds=wall_seconds,
        fake_provider_delay_ms=0,
        peak_threads=sampler.peak_threads,
        rss_peak_kb=sampler.rss_peak_kb,
    )


def run_distinct_owner_probe(
    *,
    users: int,
    provider_delay_ms: int = 0,
    check_isolation: bool = False,
) -> ProbeReport:
    """Fire one concurrent coaching turn per distinct authenticated owner."""
    snapshot = _snapshot_capacity_settings()
    _force_mock_capacity()
    latencies_ms: list[float] = []
    accepted = 0
    rate_limited = 0
    failed = 0
    structurally_invalid = 0
    lock = threading.Lock()
    sampler = _ResourceSampler()
    delay_ms = max(0, int(provider_delay_ms))
    scenario = "slow-distinct-owners" if delay_ms else "distinct-owners"
    ownership_violations = 0
    provider_calls = 0
    try:
        with _fake_slow_provider(delay_ms) as calls:
            with TemporaryDirectory(prefix="co-design-load-") as tmp:
                client, store, _oidc = _build_client(Path(tmp))
                prepared: list[tuple[dict[str, str], str]] = []
                for index in range(users):
                    sub = f"owner-{index}-{uuid4().hex[:8]}"
                    cookies = _seed_owner(store, sub=sub)
                    thread_id = _create_notebook(client, cookies, label=f"owner-{index}")
                    prepared.append((cookies, thread_id))

                def worker(item: tuple[dict[str, str], str]) -> None:
                    nonlocal accepted, rate_limited, failed, structurally_invalid
                    cookies, thread_id = item
                    started = time.perf_counter()
                    response = client.post(
                        "/api/v1/coach/turn",
                        cookies=cookies,
                        json=_coach_payload(thread_id, key=f"owner-{uuid4()}"),
                    )
                    elapsed_ms = (time.perf_counter() - started) * 1000.0
                    valid = False
                    if response.status_code == 200:
                        valid = _turn_is_structurally_valid(response.json())
                    with lock:
                        latencies_ms.append(elapsed_ms)
                        if response.status_code == 200:
                            accepted += 1
                            if not valid:
                                structurally_invalid += 1
                        elif response.status_code == 429:
                            rate_limited += 1
                        else:
                            failed += 1

                sampler.start()
                started_all = time.perf_counter()
                with ThreadPoolExecutor(max_workers=users) as executor:
                    futures = [executor.submit(worker, item) for item in prepared]
                    for future in as_completed(futures):
                        future.result()
                wall_seconds = time.perf_counter() - started_all
                sampler.stop()
                if check_isolation or delay_ms:
                    ownership_violations = _ownership_violations(client, prepared)
            provider_calls = int(calls["n"])
    finally:
        _restore_capacity_settings(snapshot)

    return _summarize(
        scenario=scenario,
        users=users,
        latencies_ms=latencies_ms,
        accepted=accepted,
        rate_limited=rate_limited,
        failed=failed,
        wall_seconds=wall_seconds,
        fake_provider_delay_ms=delay_ms,
        peak_threads=sampler.peak_threads,
        rss_peak_kb=sampler.rss_peak_kb,
        ownership_violations=ownership_violations if (check_isolation or delay_ms) else None,
        structurally_invalid=structurally_invalid,
        provider_calls=provider_calls,
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
    snapshot = _snapshot_capacity_settings()
    _force_mock_capacity()
    hold = threading.Event()
    started = threading.Barrier(2)
    original = CoachApplicationService._submit_once
    sampler = _ResourceSampler()

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

            sampler.start()
            wall_started = time.perf_counter()
            with ThreadPoolExecutor(max_workers=2) as executor:
                futures = [executor.submit(worker, first), executor.submit(worker, second)]
                for future in as_completed(futures):
                    future.result()
            wall_seconds = time.perf_counter() - wall_started
            sampler.stop()
    finally:
        CoachApplicationService._submit_once = original  # type: ignore[method-assign]
        _restore_capacity_settings(snapshot)

    accepted = sum(1 for status in statuses if status == 200)
    rate_limited = sum(1 for status in statuses if status == 429)
    failed = sum(1 for status in statuses if status not in {200, 429})
    return _summarize(
        scenario="two-notebooks",
        users=1,
        latencies_ms=latencies_ms,
        accepted=accepted,
        rate_limited=rate_limited,
        failed=failed,
        wall_seconds=wall_seconds,
        fake_provider_delay_ms=0,
        peak_threads=sampler.peak_threads,
        rss_peak_kb=sampler.rss_peak_kb,
    )


def run_same_notebook_probe() -> ProbeReport:
    """One owner, one notebook, two overlapping turns: only one may execute."""
    snapshot = _snapshot_capacity_settings()
    _force_mock_capacity()
    hold = threading.Event()
    started = threading.Event()
    original = CoachApplicationService._submit_once
    CoachApplicationService._submit_once = _gated_submit(hold, started)  # type: ignore[method-assign]
    statuses: list[int] = []
    latencies_ms: list[float] = []
    wall_seconds = 0.0
    sampler = _ResourceSampler()
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

            sampler.start()
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
            sampler.stop()
    finally:
        CoachApplicationService._submit_once = original  # type: ignore[method-assign]
        _restore_capacity_settings(snapshot)

    accepted = sum(1 for status in statuses if status == 200)
    rate_limited = sum(1 for status in statuses if status == 429)
    failed = sum(1 for status in statuses if status not in {200, 429})
    return _summarize(
        scenario="same-notebook",
        users=1,
        latencies_ms=latencies_ms,
        accepted=accepted,
        rate_limited=rate_limited,
        failed=failed,
        wall_seconds=wall_seconds,
        fake_provider_delay_ms=0,
        peak_threads=sampler.peak_threads,
        rss_peak_kb=sampler.rss_peak_kb,
    )


def run_slow_idempotency_probe(*, provider_delay_ms: int = 50) -> ProbeReport:
    """Replay the same idempotency key; the fake provider must run once."""
    snapshot = _snapshot_capacity_settings()
    _force_mock_capacity()
    delay_ms = max(0, int(provider_delay_ms))
    latencies_ms: list[float] = []
    sampler = _ResourceSampler()
    accepted = 0
    failed = 0
    provider_calls = 0
    try:
        with _fake_slow_provider(delay_ms) as calls:
            with TemporaryDirectory(prefix="co-design-load-") as tmp:
                client, store, _oidc = _build_client(Path(tmp))
                cookies = _seed_owner(store, sub=f"idem-{uuid4().hex[:8]}")
                thread_id = _create_notebook(client, cookies, label="idem")
                key = f"idem-{uuid4()}"
                sampler.start()
                started_all = time.perf_counter()
                first = client.post(
                    "/api/v1/coach/turn",
                    cookies=cookies,
                    json=_coach_payload(thread_id, key=key),
                )
                latencies_ms.append((time.perf_counter() - started_all) * 1000.0)
                replay_started = time.perf_counter()
                second = client.post(
                    "/api/v1/coach/turn",
                    cookies=cookies,
                    json=_coach_payload(thread_id, key=key),
                )
                latencies_ms.append((time.perf_counter() - replay_started) * 1000.0)
                wall_seconds = time.perf_counter() - started_all
                sampler.stop()
                accepted = int(first.status_code == 200) + int(second.status_code == 200)
                failed = int(first.status_code not in {200, 429}) + int(
                    second.status_code not in {200, 429}
                )
            provider_calls = int(calls["n"])
    finally:
        _restore_capacity_settings(snapshot)
    return _summarize(
        scenario="slow-idempotency",
        users=1,
        latencies_ms=latencies_ms,
        accepted=accepted,
        rate_limited=0,
        failed=failed,
        wall_seconds=wall_seconds,
        fake_provider_delay_ms=delay_ms,
        peak_threads=sampler.peak_threads,
        rss_peak_kb=sampler.rss_peak_kb,
        provider_calls=provider_calls,
    )


def run_failed_turn_no_partial_probe() -> ProbeReport:
    """A failed provider call must not persist an assistant turn."""
    snapshot = _snapshot_capacity_settings()
    _force_mock_capacity()
    sampler = _ResourceSampler()
    latencies_ms: list[float] = []
    assistant_turns = -1
    failed = 0
    accepted = 0
    try:
        with _failing_provider():
            with TemporaryDirectory(prefix="co-design-load-") as tmp:
                client, store, _oidc = _build_client(
                    Path(tmp), raise_server_exceptions=False
                )
                cookies = _seed_owner(store, sub=f"fail-{uuid4().hex[:8]}")
                thread_id = _create_notebook(client, cookies, label="fail")
                sampler.start()
                started = time.perf_counter()
                response = client.post(
                    "/api/v1/coach/turn",
                    cookies=cookies,
                    json=_coach_payload(thread_id, key=f"fail-{uuid4()}"),
                )
                latencies_ms.append((time.perf_counter() - started) * 1000.0)
                sampler.stop()
                if response.status_code == 200:
                    accepted = 1
                else:
                    failed = 1
                messages = client.get(
                    f"/api/v1/threads/{thread_id}/messages", cookies=cookies
                )
                assistant_turns = (
                    _count_assistant_messages(messages.json())
                    if messages.status_code == 200
                    else -1
                )
                wall_seconds = max(latencies_ms[0] / 1000.0, 0.001)
    finally:
        _restore_capacity_settings(snapshot)
    return _summarize(
        scenario="failed-no-partial",
        users=1,
        latencies_ms=latencies_ms,
        accepted=accepted,
        rate_limited=0,
        failed=failed,
        wall_seconds=wall_seconds,
        fake_provider_delay_ms=0,
        peak_threads=sampler.peak_threads,
        rss_peak_kb=sampler.rss_peak_kb,
        assistant_turns_after_failure=assistant_turns,
    )


def run_ownership_isolation_probe(*, users: int = 8) -> ProbeReport:
    """Concurrent distinct owners must not see one another's notebooks."""
    return run_distinct_owner_probe(
        users=users, provider_delay_ms=0, check_isolation=True
    )


def run_kb_pool_probe(
    *,
    workers: int,
    concurrency: int,
    delay_ms: int,
    timeout_seconds: float = 10.0,
    foreign_bucket: bool = False,
    scenario: str | None = None,
) -> ProbeReport:
    """Stress the real Retrieve pool with a fake client. Never calls AWS.

    Only ``client.retrieve`` is faked. Admission, timeout, selected-source
    validation, and fail-closed occupancy use production retriever code.
    """
    snapshot = _snapshot_capacity_settings()
    _force_mock_capacity()
    worker_count = max(1, min(int(workers), 16))
    concurrent = max(1, int(concurrency))
    delay = max(0, int(delay_ms))
    settings.knowledge_base_retrieve_executor_workers = worker_count
    reset_shared_retrieve_executor()
    client = _FakeSleepRetrieveClient(
        delay / 1000.0, foreign_bucket=foreign_bucket
    )
    retriever = BedrockKnowledgeBaseRetriever(
        "probe-kb-id",
        course_bucket=_COURSE_BUCKET,
        client=client,
        retrieve_timeout_seconds=timeout_seconds,
        metadata_filter_mode="required",
    )
    query = _course_query()
    latencies_ms: list[float] = []
    accepted = 0
    capacity_exhausted = 0
    failed = 0
    lock = threading.Lock()
    sampler = _ResourceSampler()
    name = scenario or "kb-pool"
    recovered = False
    unexpected_queueing = 0
    try:
        def worker() -> None:
            nonlocal accepted, capacity_exhausted, failed
            started = time.perf_counter()
            result = retriever.retrieve(query)
            elapsed_ms = (time.perf_counter() - started) * 1000.0
            with lock:
                latencies_ms.append(elapsed_ms)
            category = str(result.failure_category or "")
            if result.chunks:
                accepted += 1
            elif category == "capacity_exhausted":
                capacity_exhausted += 1
            elif category == "timeout":
                failed += 1
            elif result.course_retrieval_status not in {"empty", "unavailable"}:
                failed += 1

        sampler.start()
        started_all = time.perf_counter()
        with ThreadPoolExecutor(max_workers=concurrent) as executor:
            futures = [executor.submit(worker) for _ in range(concurrent)]
            for future in as_completed(futures):
                future.result()
        wall_seconds = time.perf_counter() - started_all
        recovered = _wait_pool_idle(
            timeout_seconds=max(1.0, float(timeout_seconds) + delay / 1000.0 + 1.0)
        )
        sampler.stop()
        unexpected_queueing = int(client.peak_in_flight > worker_count)
    finally:
        reset_shared_retrieve_executor()
        _restore_capacity_settings(snapshot)

    return _summarize(
        scenario=name,
        users=concurrent,
        latencies_ms=latencies_ms,
        accepted=accepted,
        rate_limited=0,
        failed=failed,
        wall_seconds=wall_seconds,
        requests=concurrent,
        fake_kb_delay_ms=delay,
        kb_workers=worker_count,
        capacity_exhausted=capacity_exhausted,
        peak_threads=sampler.peak_threads,
        peak_kb_admitted=sampler.peak_kb_admitted,
        peak_kb_worker_threads=sampler.peak_kb_worker_threads,
        rss_peak_kb=sampler.rss_peak_kb,
        unexpected_queueing=unexpected_queueing,
        pool_recovered=int(recovered),
    )


def run_kb_fail_closed_probe() -> ProbeReport:
    """Foreign-bucket fake hits must not become accepted evidence."""
    report = run_kb_pool_probe(
        workers=4,
        concurrency=4,
        delay_ms=20,
        timeout_seconds=2.0,
        foreign_bucket=True,
        scenario="kb-fail-closed",
    )
    return report


def run_kb_timeout_slot_probe(
    *, workers: int = 2, concurrency: int = 8, delay_ms: int = 400
) -> ProbeReport:
    """Timed-out fake Retrieves must keep occupying admission slots."""
    timeout_seconds = 0.05
    return run_kb_pool_probe(
        workers=workers,
        concurrency=concurrency,
        delay_ms=delay_ms,
        timeout_seconds=timeout_seconds,
        scenario="kb-timeout-slot",
    )


def run_phase(phase: str, *, slow_delay_ms: int = _DEFAULT_SLOW_DELAY_MS) -> list[ProbeReport]:
    """Run a named free local matrix and return comparable reports."""
    reports: list[ProbeReport] = []
    if phase in {"existing", "all"}:
        for users in _EXISTING_USER_COUNTS:
            reports.append(run_distinct_owner_probe(users=users))
        reports.append(run_two_notebooks_probe())
        reports.append(run_same_notebook_probe())
    if phase in {"slow", "all"}:
        delay = max(0, int(slow_delay_ms))
        for users in _SLOW_USER_COUNTS:
            reports.append(
                run_distinct_owner_probe(users=users, provider_delay_ms=delay)
            )
        if delay == _DEFAULT_SLOW_DELAY_MS:
            for extra_delay in _SLOW_DELAYS_MS:
                if extra_delay == delay:
                    continue
                reports.append(
                    run_distinct_owner_probe(users=90, provider_delay_ms=extra_delay)
                )
    if phase in {"kb", "all"}:
        for workers in _KB_WORKER_COUNTS:
            for delay_ms in _KB_DELAYS_MS:
                for concurrency in _KB_CONCURRENCY:
                    reports.append(
                        run_kb_pool_probe(
                            workers=workers,
                            concurrency=concurrency,
                            delay_ms=delay_ms,
                        )
                    )
        reports.append(run_kb_timeout_slot_probe())
        reports.append(run_kb_fail_closed_probe())
    if phase in {"correctness", "all"}:
        reports.append(run_ownership_isolation_probe(users=10))
        reports.append(run_slow_idempotency_probe(provider_delay_ms=50))
        reports.append(run_failed_turn_no_partial_probe())
        if phase == "correctness":
            reports.append(run_two_notebooks_probe())
            reports.append(run_same_notebook_probe())
            reports.append(run_kb_fail_closed_probe())
            reports.append(run_kb_timeout_slot_probe())
    if not reports:
        raise ValueError(f"unknown load-probe phase: {phase}")
    return reports


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--scenario",
        choices=(
            "sequential",
            "distinct-owners",
            "two-notebooks",
            "same-notebook",
            "slow-distinct-owners",
            "kb-pool",
            "kb-timeout-slot",
            "kb-fail-closed",
            "slow-idempotency",
            "failed-no-partial",
            "ownership-isolation",
        ),
        default="sequential",
    )
    parser.add_argument("--users", type=int, default=10)
    parser.add_argument("--requests-per-user", type=int, default=3)
    parser.add_argument("--provider-delay-ms", type=int, default=_DEFAULT_SLOW_DELAY_MS)
    parser.add_argument("--kb-delay-ms", type=int, default=500)
    parser.add_argument("--kb-workers", type=int, default=4)
    parser.add_argument("--kb-timeout-seconds", type=float, default=10.0)
    parser.add_argument(
        "--run-phase",
        choices=("existing", "slow", "kb", "correctness", "all"),
        default="",
        help="Run a named free local matrix and print one JSON object per line.",
    )
    return parser.parse_args()


def _print_report(report: ProbeReport) -> None:
    """Print one machine-readable JSON object. Never prints student content."""
    print(json.dumps(report.as_dict(), sort_keys=True))


def _quiet_logs() -> None:
    """Keep CLI output as JSON rows. Never logs student content."""
    logging.basicConfig(level=logging.ERROR)
    logging.getLogger().setLevel(logging.ERROR)
    for name in list(logging.root.manager.loggerDict):
        logging.getLogger(name).setLevel(logging.ERROR)


def main() -> None:
    """Run the selected mock-only concurrency probe and print aggregates."""
    _quiet_logs()
    args = _parse_args()
    if args.run_phase:
        for report in run_phase(str(args.run_phase), slow_delay_ms=int(args.provider_delay_ms)):
            _print_report(report)
        return
    users = max(1, min(int(args.users), 120))
    requests_per_user = max(1, min(int(args.requests_per_user), 20))
    delay_ms = max(0, min(int(args.provider_delay_ms), 60_000))
    kb_delay_ms = max(0, min(int(args.kb_delay_ms), 30_000))
    kb_workers = max(1, min(int(args.kb_workers), 16))
    if args.scenario == "sequential":
        report = run_sequential_probe(users=users, requests_per_user=requests_per_user)
    elif args.scenario == "distinct-owners":
        report = run_distinct_owner_probe(users=users)
    elif args.scenario == "slow-distinct-owners":
        report = run_distinct_owner_probe(users=users, provider_delay_ms=delay_ms)
    elif args.scenario == "two-notebooks":
        report = run_two_notebooks_probe()
    elif args.scenario == "same-notebook":
        report = run_same_notebook_probe()
    elif args.scenario == "kb-pool":
        report = run_kb_pool_probe(
            workers=kb_workers,
            concurrency=users,
            delay_ms=kb_delay_ms,
            timeout_seconds=float(args.kb_timeout_seconds),
        )
    elif args.scenario == "kb-timeout-slot":
        report = run_kb_timeout_slot_probe()
    elif args.scenario == "kb-fail-closed":
        report = run_kb_fail_closed_probe()
    elif args.scenario == "slow-idempotency":
        report = run_slow_idempotency_probe(provider_delay_ms=min(delay_ms, 500))
    elif args.scenario == "failed-no-partial":
        report = run_failed_turn_no_partial_probe()
    else:
        report = run_ownership_isolation_probe(users=users)
    _print_report(report)


if __name__ == "__main__":
    main()
