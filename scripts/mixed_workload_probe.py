"""Measure stepped mixed classroom workloads on disposable mock data only.

Run ``python -m scripts.mixed_workload_probe``. The driver and the single-worker
API run in separate processes. Output is aggregate local-mock characterization
evidence with recorded environment and sample-size limitations — never a live
capacity, provider, or cost verdict. No supplied database, provider, host or
student workspace can be selected, and the developer database is never opened.

At each level (default 1/10/20/40/60/80 persistent authenticated Guest HTTP
sessions) newly arriving students perform their startup (guest start, notebook
create, source upload) inside the barrier-released wave while every student —
new and existing — mixes navigation reads, one ordinary coaching turn, one
grounded turn with an explicit source attachment, one artifact autosave through
a deliberate two-tab same-revision OCC race, one canvas autosave and, for new
students, one durable Deep Review submission. Per operation the probe records
counts, errors, nearest-rank p50/p90/p95/p99/max milliseconds, queue
observations, OCC conflicts/retries, and per-level throughput; afterwards it
reconciles every transcript and revision count for confirmed turn/revision loss
and duplicates, records database growth (write-volume proxy), and polls all
Deep Review jobs to a bounded terminal deadline.
"""

from __future__ import annotations

import argparse
import json
import math
import os
import platform
import resource
import secrets
import socket
import sqlite3
import subprocess
import sys
import tempfile
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing, contextmanager
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator

import httpx

SOURCE = (b"Analogy transfers a relationship from a familiar setting to a new "
          b"design problem. Compare relationships rather than surface features.")
ORDINARY_MESSAGE = "What is analogy in design?"
GROUNDED_MESSAGE = "Use the attached analogy note to critique my crossing-problem framing."
LEVELS = (1, 10, 20, 40, 60, 80)


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
        "MAX_CONCURRENT_MODEL_CALLS": "120", "COACH_REQUESTS_PER_MINUTE": "120",
        "DEEP_REVIEW_MAX_CONCURRENT": "8"}


def _serve(root: Path, port: int) -> None:
    """Run one isolated API worker with delayed mock generation and a sampler."""
    # A hidden CLI argument alone must not opt an existing workspace into writes.
    # The driver passes a private launch capability for its newly allocated root.
    token = os.environ.get("MIXED_WORKLOAD_TOKEN", "")
    if (root.name != "active" or not root.parent.name.startswith("mixed-workload-")
            or root.parent.parent.resolve() != Path(tempfile.gettempdir()).resolve()
            or not token or not (root / "probe-disposable").is_file()
            or not secrets.compare_digest((root / "probe-disposable").read_text(), token)):
        raise ValueError("Only driver-created disposable child launches are allowed")
    os.environ.update(_environment(root, f"http://127.0.0.1:{port}"))
    import uvicorn
    import backend.owner_context as owners
    from backend.api import create_app
    from backend.domain import CoachRequest, ProviderAssessmentResult
    from backend.mock_provider import DeterministicCoachProvider
    from backend.student_store import StudentStore

    class DelayedProvider(DeterministicCoachProvider):
        """Expose a known artificial delay at the external provider seam."""

        usage_provider = "unknown"

        def assess(self, request: CoachRequest) -> ProviderAssessmentResult:
            control = json.loads((root / "control.json").read_text())
            time.sleep(control["delay_seconds"])
            return super().assess(request)

    owners.configured_coach_provider = DelayedProvider

    # Synthetic-fixture override, confined to this disposable child (see
    # scripts/workspace_recovery_rehearsal.py): Deep Review eligibility requires
    # a completed Thinking Path that has no public HTTP route. Enqueue, the
    # durable worker, admission, snapshot persistence and owner fencing stay
    # real — only this eligibility gate is relaxed for the measurement.
    import backend.coaching.execution as execution
    execution.explicit_deep_review_available = lambda **kwargs: True

    app = create_app(StudentStore(root / "students.sqlite3"))
    stopped = threading.Event()

    def sample() -> None:
        """Persist server-only high-water resource samples outside the HTTP API."""
        peak_threads = 0
        peak_running = peak_queued = 0
        while not stopped.wait(0.02):
            peak_threads = max(peak_threads, threading.active_count())
            with closing(sqlite3.connect(root / "generation.sqlite3", timeout=2)) as db:
                counts = dict(db.execute(
                    "SELECT state, count(*) FROM generation_calls GROUP BY state"))
            peak_running = max(peak_running, counts.get("running", 0))
            peak_queued = max(peak_queued, counts.get("queued", 0))
            usage = resource.getrusage(resource.RUSAGE_SELF)
            metrics = {"server_peak_threads": peak_threads,
                "server_process_max_rss_kib": round(
                    usage.ru_maxrss / (1024 if sys.platform == "darwin" else 1)),
                "server_cpu_seconds": round(usage.ru_utime + usage.ru_stime, 3),
                "sampled_peak_running": peak_running,
                "sampled_peak_queued": peak_queued}
            temporary = root / "metrics.tmp"
            temporary.write_text(json.dumps(metrics))
            temporary.replace(root / "metrics.json")

    sampler = threading.Thread(target=sample, daemon=True)
    sampler.start()
    try:
        uvicorn.run(app, host="127.0.0.1", port=port, log_level="warning",
                    access_log=False, timeout_keep_alive=120)
    finally:
        stopped.set()
        sampler.join(3)


@contextmanager
def _server(root: Path, port: int) -> Iterator[str]:
    """Start and always stop a fresh real loopback API process at the same store."""
    origin = f"http://127.0.0.1:{port}"
    log_path = root.parent / "server-private.log"
    with log_path.open("ab") as log:
        process = subprocess.Popen(
            [sys.executable, "-m", "scripts.mixed_workload_probe",
             "--serve", str(root), "--port", str(port)], stdout=log, stderr=log,
            env={**_environment(root, origin),
                 "MIXED_WORKLOAD_TOKEN": (root / "probe-disposable").read_text()})
        try:
            deadline = time.monotonic() + 30
            with httpx.Client(base_url=origin, trust_env=False) as client:
                while True:
                    if process.poll() is not None:
                        try:
                            with open(log_path, encoding="utf-8", errors="replace") as done_log:
                                tail = done_log.read()[-2000:]
                        except OSError:
                            tail = ""
                        raise RuntimeError(f"Mock API exited; server log tail:\n{tail}")
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
    """One synthetic student: private client, saved ids and expected counts."""

    client: httpx.Client
    ready: bool = False
    thread: str = ""
    source: str = ""
    attachment: str = ""
    artifact: str = ""
    artifact_revision: int = 0
    canvas: str = ""
    canvas_revision: int = 0
    expected_messages: int = 0
    review_ids: list[str] = field(default_factory=list)
    review_submitted_at: float | None = None

    @property
    def path(self) -> str:
        """Return the owned public reader notebook prefix."""
        return f"/api/v1/reader/threads/{self.thread}"


@dataclass
class Observation:
    """One timed operation observation."""

    category: str
    ok: bool
    ms: float
    saved: bool = False
    queued: bool = False
    conflict: bool = False
    retried: bool = False
    detail: str = ""


def percentiles(values: list[float]) -> dict[str, float | None]:
    """Return nearest-rank p50/p90/p95/p99/max in milliseconds, null when empty."""
    ordered = sorted(values)
    return {label: round(ordered[max(0, math.ceil(len(ordered) * p) - 1)], 2)
            if ordered else None
            for label, p in (("p50", .5), ("p90", .9), ("p95", .95), ("p99", .99),
                             ("max", 1.0))}


def summarize(observations: list[Observation]) -> dict[str, Any]:
    """Aggregate one operation category: counts, errors, timing percentiles."""
    saved = [o for o in observations if o.ok and o.saved]
    error_details: dict[str, int] = {}
    for observation in observations:
        if not observation.ok and observation.detail:
            error_details[observation.detail] = \
                error_details.get(observation.detail, 0) + 1
    return {"operations": len(observations), "succeeded": sum(o.ok for o in observations),
        "errors": sum(not o.ok for o in observations),
        "error_details": error_details,
        "queue_observations": sum(o.queued for o in observations),
        "occ_conflicts": sum(o.conflict for o in observations),
        "occ_retries": sum(o.retried for o in observations),
        "latency_ms_all_outcomes": percentiles([o.ms for o in observations]),
        "latency_ms_saved": percentiles([o.ms for o in saved])}


def _ok(client: httpx.Client, method: str, url: str, **kwargs: Any) -> Any:
    """Require HTTP success and decode fixture JSON without printing bodies."""
    response = client.request(method, url, **kwargs)
    response.raise_for_status()
    return response.json()


def _turn(session: Session, key: str, barrier: threading.Barrier | None = None,
          *, grounded: bool = False) -> Observation:
    """Observe one streamed coaching turn's queue wait and truthful save."""
    if barrier:
        barrier.wait(60)
    payload: dict[str, Any] = {"student_message": GROUNDED_MESSAGE if grounded
                               else ORDINARY_MESSAGE, "idempotency_key": key}
    if grounded:
        payload["attachment_source_ids"] = [session.attachment]
    start = time.monotonic()
    queued_at: float | None = None
    thinking_at: float | None = None
    terminal: dict[str, Any] = {}
    with session.client.stream("POST", f"{session.path}/lecture/stream",
                               json=payload) as response:
        response.raise_for_status()
        for line in response.iter_lines():
            event = json.loads(line)
            now = time.monotonic()
            if event.get("phase") == "queued" and queued_at is None:
                queued_at = now
            if event.get("phase") == "thinking" and thinking_at is None:
                thinking_at = now
            if event["event"] in {"done", "error"}:
                terminal = event
    ms = (time.monotonic() - start) * 1000
    saved = terminal.get("event") == "done"
    detail = str(terminal.get("category") or terminal.get("detail") or "")[:120] \
        if not saved else ""
    if saved:
        recovered = _ok(session.client, "GET", f"{session.path}/coach-turn",
                        params={"idempotency_key": key})
        citations = (recovered.get("assessment") or {}).get("citations") or []
        if grounded and not citations:
            raise AssertionError(f"Grounded turn {key} saved without citations")
        session.expected_messages += 2
    else:
        recovered = _ok(session.client, "GET", f"{session.path}/coach-turn",
                        params={"idempotency_key": key})
        if recovered is not None:
            raise AssertionError(f"Rejected turn {key} appeared saved")
    return Observation("grounded_turn" if grounded else "ordinary_turn",
                       saved, ms, saved=saved, queued=queued_at is not None,
                       detail=detail)


def _navigation(session: Session, barrier: threading.Barrier | None) -> Observation:
    """Observe one open/switch navigation: list, project and transcript page."""
    if barrier:
        barrier.wait(60)
    start = time.monotonic()
    _ok(session.client, "GET", "/api/v1/reader/threads")
    project = _ok(session.client, "GET", f"{session.path}/project")
    page = _ok(session.client, "GET", f"{session.path}/messages/page",
               params={"limit": 100})
    if page["total_count"] != session.expected_messages:
        raise AssertionError("Navigation read a lost or duplicated transcript")
    if project.get("thread_id") not in ("", session.thread):
        raise AssertionError("Navigation projected a foreign notebook")
    return Observation("navigation", True, (time.monotonic() - start) * 1000)


def _startup(session: Session, barrier: threading.Barrier) -> list[Observation]:
    """Observe one student's arrival: guest start, notebook create, upload."""
    barrier.wait(60)
    observations: list[Observation] = []
    start = time.monotonic()
    _ok(session.client, "POST", "/api/v1/auth/guest/start")
    observations.append(Observation("startup", True, (time.monotonic() - start) * 1000))
    start = time.monotonic()
    session.thread = _ok(session.client, "POST", "/api/v1/reader/threads",
                         json={"name": "Mixed workload student"})["notebook"]["id"]
    observations.append(Observation("startup", True, (time.monotonic() - start) * 1000))
    start = time.monotonic()
    source = _ok(session.client, "POST", f"/api/v1/threads/{session.thread}/sources",
                 files={"files": ("analogy.txt", SOURCE, "text/plain")})[0]
    session.source = source["id"]
    observations.append(Observation("source_upload", True,
                                    (time.monotonic() - start) * 1000))
    # Private current-turn attachments back the grounded turn (the documented
    # attachment contract: selected only inside that one request).
    start = time.monotonic()
    attachment = _ok(session.client, "POST",
                     f"/api/v1/threads/{session.thread}/attachments",
                     files={"files": ("private-note.txt",
                                      b"Grounding note for one turn.", "text/plain")})[0]
    session.attachment = attachment["id"]
    observations.append(Observation("source_upload", True,
                                    (time.monotonic() - start) * 1000))
    start = time.monotonic()
    artifact = _ok(session.client, "POST", f"{session.path}/artifacts",
                   json={"title": "Autosave notes", "kind": "notes",
                         "document": {"type": "doc", "content": [
                             {"type": "paragraph", "content": [
                                 {"type": "text", "text": "First draft."}]}]}})
    session.artifact = artifact["id"]
    session.artifact_revision = artifact["revision"]
    canvas = _ok(session.client, "POST", f"{session.path}/canvases",
                 json={"title": "Autosave map",
                       "graph": _graph(2)})
    session.canvas = canvas["id"]
    session.canvas_revision = canvas["revision"]
    observations.append(Observation("startup", True, (time.monotonic() - start) * 1000))
    session.ready = True
    return observations


def _graph(nodes: int) -> dict[str, Any]:
    """Return one small valid canvas graph with ``nodes`` chained nodes."""
    return {"nodes": [{
            "id": f"node-{index}", "kind": "problem" if index == 0 else "concept",
            "title": f"Node {index}", "description": "Synthetic step.",
            "x": 40.0 * index, "y": 60.0} for index in range(nodes)],
        "edges": [{"id": f"edge-{index}", "source": f"node-{index}",
                   "target": f"node-{index + 1}", "relation": "supports",
                   "explanation": "Synthetic."} for index in range(nodes - 1)]}


def _document(text: str) -> dict[str, Any]:
    """Return one small canonical Tiptap document."""
    return {"type": "doc", "content": [
        {"type": "paragraph", "content": [{"type": "text", "text": text}]}]}


def _artifact_occ_autosave(session: Session, key: str,
                           barrier: threading.Barrier | None) -> list[Observation]:
    """Race two same-owner tabs on one revision; the loser refetches and retries.

    This is the documented OCC behavior: one save wins, the other receives the
    canonical 409, rereads the saved revision and retries with the fresh base.
    Both saves must commit; the saved revision advances by exactly two.
    """
    if barrier:
        barrier.wait(60)
    base = session.artifact_revision
    tab_b = _tab_client(session)

    def put(client: httpx.Client, text: str) -> tuple[bool, float, bool]:
        start = time.monotonic()
        response = client.put(f"{session.path}/artifacts/{session.artifact}",
                              json={"document": _document(text), "revision": base})
        return response.status_code == 200, (time.monotonic() - start) * 1000, \
            response.status_code == 409

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(
            lambda pair: put(pair[0], pair[1]),
            ((session.client, "Tab A draft."), (tab_b, "Tab B draft."))))
    committed = [result for result in results if result[0]]
    conflicts = [result for result in results if result[2]]
    if len(committed) != 1 or len(conflicts) != 1:
        raise AssertionError(
            f"Expected one committed save and one 409 conflict; got {results}")
    saved_ms = committed[0][1]
    conflict_ms = conflicts[0][1]
    start = time.monotonic()
    current = _ok(tab_b, "GET", f"{session.path}/artifacts/{session.artifact}")
    retried = tab_b.put(f"{session.path}/artifacts/{session.artifact}",
                        json={"document": _document("Tab B redraft."),
                              "revision": current["revision"]})
    retried.raise_for_status()
    retry_ms = (time.monotonic() - start) * 1000
    final = _ok(session.client, "GET", f"{session.path}/artifacts/{session.artifact}")
    session.artifact_revision = final["revision"]
    if session.artifact_revision != base + 2:
        raise AssertionError("OCC autosave lost or duplicated a revision")
    return [Observation("artifact_autosave", True, saved_ms, saved=True),
        Observation("artifact_autosave", False, conflict_ms, conflict=True),
        Observation("artifact_autosave", True, retry_ms, saved=True, retried=True)]


def _tab_client(session: Session) -> httpx.Client:
    """Open a second same-owner tab sharing the session's Guest cookie."""
    client = session.client
    tab = httpx.Client(base_url=client.base_url,
                       headers={"Origin": client.headers.get("Origin")},
                       trust_env=False, timeout=120,
                       limits=httpx.Limits(max_connections=2,
                                           max_keepalive_connections=2))
    tab.cookies.update(client.cookies)
    return tab


def _canvas_autosave(session: Session, key: str,
                     barrier: threading.Barrier | None) -> Observation:
    """Observe one revision-guarded canvas autosave that adds one node."""
    if barrier:
        barrier.wait(60)
    saved = _ok(session.client, "GET", f"{session.path}/canvases/{session.canvas}")
    start = time.monotonic()
    response = session.client.put(f"{session.path}/canvases/{session.canvas}",
                                  json={"graph": _graph(len(saved["graph"]["nodes"]) + 1),
                                        "revision": saved["revision"]},
                                  headers={"Idempotency-Key": key})
    response.raise_for_status()
    canvas = response.json()
    session.canvas_revision = canvas["revision"]
    if canvas["revision"] != saved["revision"] + 1:
        raise AssertionError("Canvas autosave lost or duplicated a revision")
    return Observation("canvas_autosave", True, (time.monotonic() - start) * 1000,
                       saved=True)


def _deep_review_submit(session: Session, key: str,
                        barrier: threading.Barrier | None) -> Observation:
    """Observe one durable Deep Review submission's immediate feedback."""
    if barrier:
        barrier.wait(60)
    start = time.monotonic()
    job = _ok(session.client, "POST", f"/api/v1/threads/{session.thread}/deep-review",
              json={"idempotency_key": key})
    ms = (time.monotonic() - start) * 1000
    session.review_ids.append(job["review_id"])
    session.review_submitted_at = start
    return Observation("deep_review_submit", True, ms)


def _student_level(session: Session, level: int, index: int,
                   barrier: threading.Barrier) -> list[Observation]:
    """Run one student's full mixed step for one level, sequentially inside."""
    observations: list[Observation] = []
    if not session.ready:
        observations.extend(_startup(session, barrier))
    else:
        barrier.wait(60)
    unique = f"{level}-{index}"
    observations.append(_navigation(session, None))
    observations.append(_turn(session, f"{unique}-ordinary"))
    observations.append(_turn(session, f"{unique}-grounded", grounded=True))
    observations.extend(_artifact_occ_autosave(session, f"{unique}-occ", None))
    observations.append(_canvas_autosave(session, f"{unique}-canvas", None))
    # One durable Deep Review per student per session, submitted on arrival:
    # resubmitting completed reviews would multiply review jobs without adding
    # a new measurement dimension.
    if not session.review_ids:
        observations.append(_deep_review_submit(session, f"{unique}-review", None))
    return observations


def _transcript_reconciliation(sessions: list[Session], root: Path) -> dict[str, Any]:
    """Verify every saved transcript and revision count against expectations."""
    for session in sessions:
        page = _ok(session.client, "GET", f"{session.path}/messages/page",
                   params={"limit": 100})
        if page["total_count"] != session.expected_messages:
            raise AssertionError(
                f"Confirmed turn loss/duplicate: {page['total_count']} != "
                f"{session.expected_messages}")
        artifact = _ok(session.client, "GET",
                       f"{session.path}/artifacts/{session.artifact}")
        if artifact["revision"] != session.artifact_revision:
            raise AssertionError("Artifact revision drifted from the observed saves")
        canvas = _ok(session.client, "GET", f"{session.path}/canvases/{session.canvas}")
        if canvas["revision"] != session.canvas_revision:
            raise AssertionError("Canvas revision drifted from the observed saves")
    with closing(sqlite3.connect(root / "students.sqlite3")) as db:
        rows = {table: db.execute(f"SELECT count(*) FROM {table}").fetchone()[0]
                for table in ("notebooks", "messages", "sources", "student_artifacts",
                              "student_artifact_versions", "student_canvases",
                              "student_canvas_versions")}
        database_bytes = (root / "students.sqlite3").stat().st_size
    return {"verified_sessions": len(sessions), "confirmed_losses": 0,
        "confirmed_duplicates": 0, "row_counts": rows,
        "database_bytes": database_bytes}


def _ledger_summary(root: Path) -> dict[str, Any]:
    """Read aggregate diagnostic accounting without identities or content."""
    with closing(sqlite3.connect(root / "generation.sqlite3")) as db:
        rows, amount = db.execute(
            "SELECT count(*), coalesce(sum(amount),0) FROM generation_calls").fetchone()
        unsettled = db.execute(
            "SELECT count(*) FROM generation_calls WHERE state != 'settled'").fetchone()[0]
    return {"reservations": rows, "charged_micro_sgd_fake": amount,
        "unsettled": unsettled}


def _deep_review_completion(sessions: list[Session],
                            deadline_seconds: float) -> dict[str, Any]:
    """Poll every submitted Deep Review to a bounded terminal deadline."""
    pending = {session.review_ids[0]: session for session in sessions
               if session.review_ids}
    completed: list[float] = []
    statuses: dict[str, int] = {}
    deadline = time.monotonic() + deadline_seconds
    while pending and time.monotonic() < deadline:
        for review_id, session in list(pending.items()):
            job = _ok(session.client, "GET",
                      f"/api/v1/threads/{session.thread}/deep-review")
            if job["status"] in {"completed", "failed", "cancelled"}:
                statuses[job["status"]] = statuses.get(job["status"], 0) + 1
                if job["status"] == "completed" and session.review_submitted_at:
                    completed.append((time.monotonic() - session.review_submitted_at)
                                     * 1000)
                del pending[review_id]
        if pending:
            time.sleep(0.5)
    return {"submitted": sum(statuses.values()) + len(pending),
        "statuses": statuses, "still_unfinished_at_deadline": len(pending),
        "deadline_seconds": deadline_seconds,
        "completion_ms_from_submission": percentiles(completed) if completed else None}


def run_probe(*, levels: tuple[int, ...] = LEVELS,
              delay_seconds: float = .25, users: int | None = None,
              review_deadline_seconds: float = 90.0) -> dict[str, Any]:
    """Run the stepped mixed workloads and return the aggregate report."""
    if not math.isfinite(delay_seconds) or not .05 <= delay_seconds <= 2:
        raise ValueError("Use a finite mock delay between .05 and 2 seconds")
    if not all(a < b for a, b in zip(levels, levels[1:])) or not levels:
        raise ValueError("Use strictly increasing positive levels")
    if users is not None:
        levels = tuple(level for level in levels if level <= users)
        if not levels:
            levels = (min(1, users or 1),)
    with tempfile.TemporaryDirectory(prefix="mixed-workload-") as temporary:
        base = Path(temporary)
        root = base / "active"
        root.mkdir()
        (root / "probe-disposable").write_text(secrets.token_urlsafe(32))
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
                for level in levels:
                    new_clients = [_client(origin) for _ in range(level - len(sessions))]
                    new_sessions = [Session(client) for client in new_clients]
                    wave_sessions = sessions + new_sessions
                    barrier = threading.Barrier(len(wave_sessions))
                    start = time.monotonic()
                    with ThreadPoolExecutor(max_workers=len(wave_sessions)) as pool:
                        futures = [
                            pool.submit(_student_level, session, level, index, barrier)
                            for index, session in enumerate(wave_sessions)]
                        results = [future.result() for future in futures]
                    wave_seconds = time.monotonic() - start
                    flat = [observation
                            for result in results for observation in result]
                    sessions = wave_sessions
                    categories = sorted({o.category for o in flat})
                    reports.append({
                        "students": level, "new_students": len(new_sessions),
                        "wave_seconds": round(wave_seconds, 3),
                        "operations_total": len(flat),
                        "throughput_operations_per_second":
                            round(len(flat) / wave_seconds, 3) if wave_seconds else None,
                        "operations": {category: summarize(
                            [o for o in flat if o.category == category])
                            for category in categories},
                        "reconciliation": _transcript_reconciliation(sessions, root),
                        "ledger": _ledger_summary(root)})
                review_report = _deep_review_completion(sessions, review_deadline_seconds)
                server_metrics = json.loads((root / "metrics.json").read_text())
            return {"evidence": "local_mock_characterization_only",
                "levels_run": list(levels),
                "environment": {
                    "mock_provider_delay_seconds": delay_seconds,
                    "generation_admission": {"max_running": 4, "max_queued": 80,
                        "max_wait_seconds": 30},
                    "deep_review_max_concurrent": 8,
                    "server_workers": 1,
                    "python": sys.version.split()[0],
                    "platform": platform.platform(),
                    "machine": platform.machine(),
                    "recorded_at": datetime.now(timezone.utc).isoformat(timespec="seconds")},
                "limitations": [
                    "Deterministic mock provider with an injected delay; latencies "
                    "include no real model, guardrail, AgentCore, Cognito or AWS time.",
                    "Sessions are authenticated keepalive HTTP clients, not 80 "
                    "browser tabs, rendered React clients or Streamlit WebSockets.",
                    "One run per level (sample sizes equal the operation counts "
                    "reported per level); no repetition or confidence intervals.",
                    "The synthetic admission policy (4 running / 80 queued slots, "
                    "30 s deadline) and its fake accounting are fixtures, never a "
                    "funding or classroom configuration decision.",
                    "Database bytes and row counts are a write-volume proxy, not a "
                    "measured WAL/write-amplification factor.",
                    "Live provider capacity, live application latency and any "
                    "monthly cost claim remain separate, unapproved measurements."],
                "levels": reports,
                "deep_review_completion": review_report,
                "server": server_metrics,
                "live_ready": False,
                "unresolved_gates": ["agreed_maximum_classroom_wait",
                    "real_provider_capacity", "approved_live_procedure_with_cost_caps"]}
        finally:
            for session in sessions:
                session.client.close()


def _client(origin: str) -> httpx.Client:
    """Open one keepalive browser-like client bound to the probe origin."""
    return httpx.Client(base_url=origin, headers={"Origin": origin}, trust_env=False,
                        timeout=120, limits=httpx.Limits(max_connections=2,
                                                         max_keepalive_connections=2))


def main() -> None:
    """Print the aggregate report JSON, or serve only a marked disposable child."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--serve", type=Path, help=argparse.SUPPRESS)
    parser.add_argument("--port", type=int, default=0, help=argparse.SUPPRESS)
    parser.add_argument("--levels", type=int, nargs="*", default=list(LEVELS))
    parser.add_argument("--users", type=int, default=None,
                        help="Cap the levels at this many students")
    parser.add_argument("--delay-seconds", type=float, default=.25)
    args = parser.parse_args()
    if args.serve:
        _serve(args.serve, args.port)
    else:
        print(json.dumps(run_probe(levels=tuple(sorted(set(args.levels))),
                                   delay_seconds=args.delay_seconds,
                                   users=args.users), indent=2))


if __name__ == "__main__":
    main()
