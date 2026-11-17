"""Rehearse classroom load and recovery on disposable loopback mock data only.

Run ``python -m scripts.classroom_probe``. The driver and single-worker API run
in separate processes. Output is aggregate evidence, never a readiness verdict.
No supplied database, provider, host or student workspace can be selected.
"""

from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing, contextmanager
from dataclasses import dataclass
import hashlib
import json
import math
import os
from pathlib import Path
import resource
import secrets
import shutil
import socket
import sqlite3
import subprocess
import sys
import tempfile
import threading
import time
from typing import Any, Iterator

import httpx


SOURCE = b"Analogy transfers a relationship from a familiar setting to a new design problem. Compare relationships rather than surface features."


def _environment(root: Path, origin: str) -> dict[str, str]:
    """Pin all child adapters and writable paths before backend imports."""
    return {**os.environ, "APP_ENV": "development", "MODEL_PROVIDER": "mock",
        "MOCK_OPENAI": "true", "OPENAI_API_KEY": "", "DATABASE_PROVIDER": "sqlite",
        "FILE_STORAGE_PROVIDER": "local", "KNOWLEDGE_BASE_ID": "",
        "AGENTCORE_RUNTIME_ARN": "", "COURSE_MATERIALS_BUCKET": "",
        "COURSE_MATERIAL_SYNC_ENABLED": "false", "AWS_EC2_METADATA_DISABLED": "true",
        "APP_DATA_DIR": str(root), "APP_DATABASE_PATH": str(root / "students.sqlite3"),
        "APP_FILES_DIR": str(root / "files"), "APP_WORKSPACES_DIR": str(root / "workspaces"),
        "LECTURE_NOTES_DIR": str(root / "lectures"), "GUEST_ACCESS_ENABLED": "true",
        "AUTH_COOKIE_SECURE": "false", "CO_DESIGN_PUBLIC_API_URL": origin,
        "COGNITO_USER_POOL_ID": "", "COGNITO_CLIENT_ID": "", "COGNITO_DOMAIN": "",
        "GENERATION_ADMISSION_POLICY": str(root / "policy.json"),
        "AUTO_ADVANCE_STAGES": "false", "SYNC_THREADPOOL_TOKENS": "120",
        "MAX_CONCURRENT_MODEL_CALLS": "120", "COACH_REQUESTS_PER_MINUTE": "10000"}


def _serve(root: Path, port: int) -> None:
    """Run one isolated API worker with delayed mock generation and sampling."""
    # A hidden CLI argument alone must not opt an existing workspace into writes.
    # The driver passes a private launch capability for its newly allocated root.
    token = os.environ.get("CLASSROOM_REHEARSAL_TOKEN", "")
    if (root.name != "active" or not root.parent.name.startswith("classroom-rehearsal-")
            or root.parent.parent.resolve() != Path(tempfile.gettempdir()).resolve()
            or not token or not (root / "classroom-disposable").is_file()
            or not secrets.compare_digest((root / "classroom-disposable").read_text(), token)):
        raise ValueError("Only driver-created disposable child launches are allowed")
    os.environ.update(_environment(root, f"http://127.0.0.1:{port}"))
    import uvicorn
    import backend.owner_context as owners
    from backend.api import create_app
    from backend.domain import CoachRequest, ProviderAssessmentResult
    from backend.mock_provider import DeterministicCoachProvider
    from backend.providers import ProviderUnavailableError
    from backend.student_store import StudentStore

    class DelayedProvider(DeterministicCoachProvider):
        """Expose a known artificial delay, retaining conservative mock charges."""

        usage_provider = "unknown"

        def assess(self, request: CoachRequest) -> ProviderAssessmentResult:
            """Delay at the external provider seam, optionally fail one fixture."""
            control = json.loads((root / "control.json").read_text())
            time.sleep(control["delay_seconds"])
            if request.student_message == "fixture-provider-failure":
                raise ProviderUnavailableError("Deterministic classroom fixture")
            return super().assess(request)

    owners.configured_coach_provider = DelayedProvider
    app = create_app(StudentStore(root / "students.sqlite3"))
    stopped = threading.Event()

    def sample() -> None:
        """Persist server-only high-water resource samples outside the HTTP API."""
        peak_threads = 0
        peak_running = peak_queued = 0
        while not stopped.wait(0.02):
            peak_threads = max(peak_threads, threading.active_count())
            with closing(sqlite3.connect(root / "generation.sqlite3", timeout=2)) as db:
                counts = dict(db.execute("SELECT state, count(*) FROM generation_calls GROUP BY state"))
            peak_running = max(peak_running, counts.get("running", 0))
            peak_queued = max(peak_queued, counts.get("queued", 0))
            usage = resource.getrusage(resource.RUSAGE_SELF)
            metrics = {"server_peak_threads": peak_threads,
                "server_process_max_rss_kib": round(usage.ru_maxrss / (1024 if sys.platform == "darwin" else 1)),
                "server_cpu_seconds": round(usage.ru_utime + usage.ru_stime, 3),
                "sampled_peak_running": peak_running, "sampled_peak_queued": peak_queued}
            temporary = root / "metrics.tmp"
            temporary.write_text(json.dumps(metrics))
            temporary.replace(root / "metrics.json")

    sampler = threading.Thread(target=sample, daemon=True)
    sampler.start()
    try:
        uvicorn.run(app, host="127.0.0.1", port=port, log_level="warning", access_log=False,
                    timeout_keep_alive=120)
    finally:
        stopped.set()
        sampler.join(3)


@contextmanager
def _server(root: Path, port: int) -> Iterator[str]:
    """Start and always stop a fresh real loopback API process at the same store."""
    origin = f"http://127.0.0.1:{port}"
    with (root.parent / "server-private.log").open("ab") as log:
        process = subprocess.Popen([sys.executable, "-m", "scripts.classroom_probe",
            "--serve", str(root), "--port", str(port)], stdout=log, stderr=log,
            env={**_environment(root, origin),
                 "CLASSROOM_REHEARSAL_TOKEN": (root / "classroom-disposable").read_text()})
        try:
            deadline = time.monotonic() + 20
            with httpx.Client(base_url=origin, trust_env=False) as client:
                while True:
                    if process.poll() is not None:
                        raise RuntimeError("Mock API exited; inspect private server log")
                    try:
                        if client.get("/api/v1/ready").status_code == 200:
                            break
                    except httpx.TransportError:
                        pass
                    if time.monotonic() > deadline:
                        raise TimeoutError("Mock API startup timed out")
                    time.sleep(0.05)
            yield origin
        finally:
            process.terminate()
            try:
                process.wait(10)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(5)


@dataclass
class Session:
    """Private persistent HTTP client and its synthetic notebook receipt."""

    client: httpx.Client
    thread: str
    source: str
    expected: int = 0

    @property
    def path(self) -> str:
        """Return the owned public reader notebook prefix."""
        return f"/api/v1/reader/threads/{self.thread}"


def _ok(response: httpx.Response) -> Any:
    """Require HTTP success and decode fixture JSON without printing bodies."""
    response.raise_for_status()
    return response.json()


def _arrive(origin: str) -> Session:
    """Create a real Guest, notebook and selected source through HTTP only."""
    client = httpx.Client(base_url=origin, headers={"Origin": origin}, trust_env=False,
                         timeout=60, limits=httpx.Limits(max_connections=2, max_keepalive_connections=2))
    try:
        _ok(client.post("/api/v1/auth/guest/start"))
        thread = _ok(client.post("/api/v1/reader/threads", json={"name": "Synthetic lecture"}))["notebook"]["id"]
        source = _ok(client.post(f"/api/v1/threads/{thread}/sources",
            files={"files": ("analogy.txt", SOURCE, "text/plain")}))[0]["id"]
        return Session(client, thread, source)
    except BaseException:
        client.close()
        raise


def _turn(session: Session, key: str, barrier: threading.Barrier | None = None,
          *, fail: bool = False) -> dict[str, Any]:
    """Observe actual stream waits and terminal status, then verify saved authority."""
    if barrier:
        barrier.wait(20)
    start = time.monotonic()
    queued_at: float | None = None
    thinking_at: float | None = None
    terminal: dict[str, Any] = {}
    dispatched = False
    with session.client.stream("POST", f"{session.path}/lecture/stream", json={
        "student_message": "fixture-provider-failure" if fail else "What is analogy in design?",
        "idempotency_key": key,
    }) as response:
        response.raise_for_status()
        for line in response.iter_lines():
            event = json.loads(line)
            now = time.monotonic()
            dispatched |= event["event"] == "started"
            if event.get("phase") == "queued" and queued_at is None:
                queued_at = now
            if event.get("phase") == "thinking" and thinking_at is None:
                thinking_at = now
            if event["event"] in {"done", "error"}:
                terminal = event
    elapsed = (time.monotonic() - start) * 1000
    assert terminal, "Stream ended without a truthful terminal outcome"
    recovered = _ok(session.client.get(f"{session.path}/coach-turn", params={"idempotency_key": key}))
    if terminal["event"] == "done":
        assert recovered == terminal["turn"]
        citations = recovered["assessment"]["citations"]
        assert citations and citations[0]["source_id"] == session.source
        session.expected += 2
    else:
        assert recovered is None, "Rejected/failed work must not appear saved"
    return {"dispatched": dispatched, "saved": terminal["event"] == "done",
        "admitted": thinking_at is not None, "queued": queued_at is not None,
        "category": terminal.get("category"), "status": terminal.get("status", 200),
        "completion_ms": elapsed,
        "dispatch_to_thinking_ms": (thinking_at - start) * 1000 if thinking_at else None,
        "observed_queue_ms": ((thinking_at or time.monotonic()) - queued_at) * 1000 if queued_at else None}


def _percentiles(values: list[float]) -> dict[str, float | None]:
    """Return nearest-rank p50/p95/max in milliseconds, null for no observations."""
    ordered = sorted(values)
    return {label: round(ordered[max(0, math.ceil(len(ordered) * p) - 1)], 2) if ordered else None
            for label, p in (("p50", .5), ("p95", .95), ("max", 1))}


def _wave(sessions: list[Session], key: str, root: Path) -> dict[str, Any]:
    """Release all submissions together and reconcile every notebook and retry."""
    barrier = threading.Barrier(len(sessions))
    with ThreadPoolExecutor(max_workers=len(sessions)) as pool:
        futures = [pool.submit(_turn, session, key, barrier) for session in sessions]
        results = [future.result() for future in futures]
    ledger_before_replays = _ledger_summary(root)
    assert all(r["admitted"] == r["saved"] for r in results), "An admitted normal turn did not save"
    for session, result in zip(sessions, results):
        page = _ok(session.client.get(f"{session.path}/messages/page", params={"limit": 100}))
        assert page["total_count"] == session.expected, "Lost or duplicated saved turn"
        if result["saved"]:
            before = _ok(session.client.get(f"{session.path}/coach-turn", params={"idempotency_key": key}))
            # Explicit same-key replay must not append transcript rows or spend again.
            replay = _turn(session, key)
            session.expected -= 2
            assert replay["saved"]
            assert _ok(session.client.get(f"{session.path}/coach-turn", params={"idempotency_key": key})) == before
            assert _ok(session.client.get(f"{session.path}/messages/page"))["total_count"] == session.expected
    assert _ledger_summary(root) == ledger_before_replays, "Replays changed generation allowance"
    categories: dict[str, int] = {}
    for result in results:
        if result["category"]:
            categories[result["category"]] = categories.get(result["category"], 0) + 1
    return {"scenario": key, "sessions": len(sessions), "submitted": len(results),
        "dispatch_acknowledged": sum(r["dispatched"] for r in results),
        "admitted_thinking": sum(r["admitted"] for r in results),
        "queued": sum(r["queued"] for r in results), "completed_saved": sum(r["saved"] for r in results),
        "terminal_errors": categories, "unclassified_errors": sum(not r["saved"] and not r["category"] for r in results),
        "completion_ms_all_outcomes": _percentiles([r["completion_ms"] for r in results]),
        "completion_ms_saved": _percentiles([r["completion_ms"] for r in results if r["saved"]]),
        "dispatch_to_thinking_ms": _percentiles([r["dispatch_to_thinking_ms"] for r in results if r["admitted"]]),
        "observed_queue_ms": _percentiles([r["observed_queue_ms"] for r in results if r["queued"]]),
        "transcript_recovery_replay_assertions_passed": True,
        "same_key_replays_verified": sum(r["saved"] for r in results),
        "ledger_unchanged_by_replays": True,
        **json.loads((root / "metrics.json").read_text())}


def _ledger_summary(root: Path) -> dict[str, int]:
    """Read aggregate diagnostic accounting without identities or request content."""
    with closing(sqlite3.connect(root / "generation.sqlite3")) as db:
        rows, amount = db.execute("SELECT count(*), coalesce(sum(amount),0) FROM generation_calls").fetchone()
        unsettled = db.execute("SELECT count(*) FROM generation_calls WHERE state != 'settled'").fetchone()[0]
    return {"reservations": rows, "charged_micro_sgd": amount, "unsettled": unsettled}


def _snapshot(sessions: list[Session]) -> str:
    """Hash canonical pages, project state, source bytes and transcript exports."""
    digest = hashlib.sha256()
    for session in sessions:
        for suffix in ("/messages/page?limit=100", "/project", "/sources", "/settings"):
            data = _ok(session.client.get(session.path + suffix))
            digest.update(json.dumps(data, sort_keys=True).encode())
        for url in (f"{session.path}/sources/{session.source}/content",
                    f"/api/v1/threads/{session.thread}/transcript.txt"):
            response = session.client.get(url)
            response.raise_for_status()
            digest.update(response.content)
    return digest.hexdigest()


def _backup(root: Path, backup: Path) -> None:
    """Copy stopped disposable SQLite stores with the backup API and file bytes."""
    backup.mkdir()
    for name in ("students.sqlite3", "generation.sqlite3"):
        with closing(sqlite3.connect(root / name)) as source, closing(sqlite3.connect(backup / name)) as target:
            source.backup(target)
            assert target.execute("PRAGMA integrity_check").fetchone() == ("ok",)
    for name in ("files", "workspaces", "lectures"):
        if (root / name).exists():
            shutil.copytree(root / name, backup / name)
    for name in ("policy.json", "control.json", "classroom-disposable"):
        shutil.copy2(root / name, backup / name)


def run_rehearsal(*, delay_seconds: float = .25, users: int = 80) -> dict[str, Any]:
    """Run stepped load, overload, failure, restart and independent local restore.

    All stores are newly created and removed on exit. Raises on incomplete streams,
    persistence/citation/isolation violations, or changed recovery snapshots.
    """
    if not 1 <= users <= 80 or not math.isfinite(delay_seconds) or not .05 <= delay_seconds <= 2:
        raise ValueError("Use 1..80 sessions and a finite .05..2 second mock delay")
    with tempfile.TemporaryDirectory(prefix="classroom-rehearsal-") as temporary:
        base = Path(temporary)
        root = base / "active"
        root.mkdir()
        (root / "classroom-disposable").write_text(secrets.token_urlsafe(32))
        policy: dict[str, Any] = {"ledger_path": str(root / "generation.sqlite3"),
            "monthly_micro_sgd": 1000000, "headroom_micro_sgd": 100000,
            "call_reserve_micro_sgd": 100, "max_running": 4, "max_queued": 80,
            "max_wait_seconds": 30, "lease_seconds": 600,
            "ceiling_evidence": "Synthetic rehearsal only; not a price or funding decision"}
        (root / "policy.json").write_text(json.dumps(policy))
        (root / "control.json").write_text(json.dumps({"delay_seconds": delay_seconds}))
        with socket.socket() as reservation:
            reservation.bind(("127.0.0.1", 0))
            port = reservation.getsockname()[1]
        sessions: list[Session] = []
        reports: list[dict[str, Any]] = []
        try:
            with _server(root, port) as origin:
                # Keep each client's authenticated keepalive connection open as the
                # class grows. These are HTTP sessions, not Streamlit WebSockets.
                for target in sorted({min(n, users) for n in (10, 20, 40, 80)}):
                    with ThreadPoolExecutor(max_workers=target - len(sessions)) as pool:
                        sessions.extend(pool.map(lambda _: _arrive(origin), range(target - len(sessions))))
                    reports.append(_wave(sessions, f"step-{target}", root))
                idle_before = _ledger_summary(root)
                idle_started = time.monotonic()
                time.sleep(2)
                with ThreadPoolExecutor(max_workers=users) as pool:
                    pages = list(pool.map(lambda session: _ok(session.client.get(session.path + "/messages/page")), sessions))
                assert all(page["total_count"] == session.expected for page, session in zip(pages, sessions))
                assert _ledger_summary(root) == idle_before
                open_sessions = {"authenticated_http_sessions": users, "idle_hold_seconds": 2,
                    "hold_and_concurrent_read_seconds": round(time.monotonic() - idle_started, 3),
                    "read_completions": len(pages), "generation_reservations_added": 0,
                    **json.loads((root / "metrics.json").read_text())}
                reports.append(_wave(sessions, "repeat-burst", root))
                # Read each owner's list and reject access to the next owner's work.
                for i, session in enumerate(sessions):
                    listed = _ok(session.client.get("/api/v1/reader/threads"))["notebooks"]
                    assert [row["id"] for row in listed] == [session.thread]
                    if users > 1:
                        assert session.client.get(sessions[(i + 1) % users].path + "/messages/page").status_code == 404
                initial = _snapshot(sessions)
                initial_ledger = _ledger_summary(root)
            with _server(root, port):
                assert _snapshot(sessions) == initial
                assert _ledger_summary(root) == initial_ledger
                restart = {"same_store_snapshot_sha256": initial, "matched": True}
            # Backup exists independently. Remove active data from its original
            # location before restoration; do not use original bytes for recovery.
            _backup(root, base / "backup")
            root.rename(base / "unavailable-original")
            shutil.copytree(base / "backup", root)
            with _server(root, port):
                assert _snapshot(sessions) == initial
                assert _ledger_summary(root) == initial_ledger
                restored = {"independent_backup_snapshot_sha256": initial, "matched": True,
                    "original_store_unavailable": True, "physical_off_host_backup_tested": False}
                reports.append(_wave(sessions, "restored-burst", root))
            policy.update(max_queued=2)
            (root / "policy.json").write_text(json.dumps(policy))
            (root / "control.json").write_text(json.dumps({"delay_seconds": 1}))
            with _server(root, port):
                reports.append(_wave(sessions, "overload-burst", root))
            policy.update(max_queued=80, max_wait_seconds=.05)
            (root / "policy.json").write_text(json.dumps(policy))
            with _server(root, port):
                reports.append(_wave(sessions, "wait-expiry-burst", root))
                failure = _turn(sessions[0], "provider-failure", fail=True)
                assert not failure["saved"]
                assert failure["admitted"] and failure["status"] == 503 and failure["category"] == "unavailable"
                assert _ok(sessions[0].client.get(sessions[0].path + "/messages/page"))["total_count"] == sessions[0].expected
                final_ledger = _ledger_summary(root)
                assert final_ledger["unsettled"] == 0
            return {"evidence": "local_mock_characterization_only", "users": users,
                "fake_provider_delay_seconds": delay_seconds, "max_running": 4,
                "initial_max_queued": 80, "initial_queue_deadline_seconds": 30,
                "server_workers": 1, "open_sessions": open_sessions,
                "steps": reports, "restart": restart, "restore": restored,
                "restored_ledger": initial_ledger, "final_ledger": final_ledger,
                "provider_failure": failure, "owner_isolation_violations": 0,
                "live_ready": False, "unresolved_gates": ["agreed_maximum_classroom_wait",
                    "real_provider_capacity", "complete_cash_funded_SGD30_inventory_and_headroom",
                    "off_host_backup_operations", "external_formative_study_and_two_week_pilot"]}
        finally:
            for session in sessions:
                session.client.close()


def main() -> None:
    """Print aggregate rehearsal JSON, or serve only a marked disposable child."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--serve", type=Path, help=argparse.SUPPRESS)
    parser.add_argument("--port", type=int, default=0, help=argparse.SUPPRESS)
    parser.add_argument("--delay-seconds", type=float, default=.25)
    args = parser.parse_args()
    if args.serve:
        _serve(args.serve, args.port)
    else:
        if not math.isfinite(args.delay_seconds) or not .05 <= args.delay_seconds <= 2:
            parser.error("delay must be between .05 and 2 seconds")
        print(json.dumps(run_rehearsal(delay_seconds=args.delay_seconds), indent=2))


if __name__ == "__main__":
    main()
