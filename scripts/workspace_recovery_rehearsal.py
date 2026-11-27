"""Rehearse complete-workspace backup and recovery on disposable mock data only.

Run ``python -m scripts.workspace_recovery_rehearsal``. The driver and the API
run in separate processes. Output is aggregate rehearsal evidence, never a
production-recovery verdict. No supplied database, provider, host or student
workspace can be selected, and the developer database is never opened.

The rehearsal seeds one synthetic owner's complete saved workspace through the
public HTTP surfaces only — chat turns, an uploaded source, an artifact with a
three-revision version history, a canvas with a three-revision version history,
a confirmed stage transition with its milestone recap, and a completed durable
Deep Review — then performs the documented stopped-server SQLite/file backup,
restores it into a fresh disposable location with the original stores removed,
and proves through public interfaces after restart that every resource reopens
byte-identically inside the same owner boundary. A second owner is refused
throughout.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import secrets
import shutil
import socket
import sqlite3
import subprocess
import sys
import tempfile
import time
from contextlib import closing, contextmanager
from pathlib import Path
from typing import Any, Iterator

import httpx

DATABASE_NAME = "workspace.sqlite3"
FILE_DIRS = ("files", "workspaces", "lectures")
INVENTORY_TABLES = (
    "notebooks", "messages", "sources", "student_artifacts",
    "student_artifact_versions", "student_canvases", "student_canvas_versions",
)

ADVANCE_MESSAGE = (
    "Older pedestrians near our school struggle to cross before the signal "
    "changes. They need to reach nearby shops safely and without stress."
)
SOURCE_BYTES = (
    b"Analogy transfers a relationship from a familiar setting to a new design "
    b"problem. Compare relationships rather than surface features."
)


def _document(paragraph: str) -> dict[str, Any]:
    """Return one small canonical Tiptap document."""
    return {"type": "doc", "content": [
        {"type": "paragraph", "content": [
            {"type": "text", "text": paragraph},
        ]},
    ]}


def _graph(node_count: int) -> dict[str, Any]:
    """Return one small valid canvas graph with ``node_count`` chained nodes."""
    nodes = [{
        "id": f"node-{index}", "kind": "problem" if index == 0 else "concept",
        "title": f"Rehearsal node {index}",
        "description": f"Synthetic reasoning step {index}.",
        "x": 40.0 * index, "y": 60.0,
    } for index in range(node_count)]
    edges = [{
        "id": f"edge-{index}", "source": f"node-{index}",
        "target": f"node-{index + 1}", "relation": "supports",
        "explanation": "Synthetic relationship.",
    } for index in range(node_count - 1)]
    return {"nodes": nodes, "edges": edges}


def _environment(root: Path, origin: str) -> dict[str, str]:
    """Pin all child adapters and writable paths before backend imports."""
    return {**os.environ, "APP_ENV": "development", "MODEL_PROVIDER": "mock",
        "MOCK_OPENAI": "true", "OPENAI_API_KEY": "", "DATABASE_PROVIDER": "sqlite",
        "FILE_STORAGE_PROVIDER": "local", "KNOWLEDGE_BASE_ID": "",
        "AGENTCORE_RUNTIME_ARN": "", "COURSE_MATERIALS_BUCKET": "",
        "COURSE_MATERIAL_SYNC_ENABLED": "false", "AWS_EC2_METADATA_DISABLED": "true",
        "APP_DATA_DIR": str(root), "APP_DATABASE_PATH": str(root / DATABASE_NAME),
        "APP_FILES_DIR": str(root / "files"), "APP_WORKSPACES_DIR": str(root / "workspaces"),
        "LECTURE_NOTES_DIR": str(root / "lectures"), "GUEST_ACCESS_ENABLED": "true",
        "AUTH_COOKIE_SECURE": "false", "CO_DESIGN_PUBLIC_API_URL": origin,
        "CO_DESIGN_UI_URL": origin, "COGNITO_USER_POOL_ID": "", "COGNITO_CLIENT_ID": "",
        "COGNITO_DOMAIN": "", "AUTO_ADVANCE_STAGES": "false",
        "STUDENT_STAGE_SELECTION": "true", "PYTHON_DOTENV_DISABLED": "1"}


def _serve(root: Path, port: int) -> None:
    """Run one isolated real API worker; only driver-marked roots may boot."""
    token = os.environ.get("WORKSPACE_RECOVERY_TOKEN", "")
    if (root.name not in {"active", "recovered"}
            or not root.parent.name.startswith("workspace-recovery-")
            or root.parent.parent.resolve() != Path(tempfile.gettempdir()).resolve()
            or not token or not (root / "rehearsal-disposable").is_file()
            or not secrets.compare_digest(
                (root / "rehearsal-disposable").read_text(), token)):
        raise ValueError("Only driver-created disposable child launches are allowed")
    os.environ.update(_environment(root, f"http://127.0.0.1:{port}"))
    import uvicorn
    import backend.owner_context as owners
    from backend.domain import StageDecision
    from backend.mock_provider import DeterministicCoachProvider
    from backend.student_store import StudentStore

    def provider_factory() -> DeterministicCoachProvider:
        """Serve the ADVANCE fixture while seeding, the plain mock afterwards."""
        control = json.loads((root / "control.json").read_text())
        if control.get("provider") == "advance":
            return DeterministicCoachProvider(StageDecision.ADVANCE)
        return DeterministicCoachProvider()

    owners.configured_coach_provider = provider_factory

    # Synthetic-fixture override, confined to this disposable child: Deep
    # Review eligibility requires a completed Thinking Path, and stage
    # completion has no public HTTP route because stage authority belongs to
    # confirmed coaching turns. The rehearsal must still persist and recover
    # review metadata, so only this eligibility gate is relaxed; enqueue, the
    # durable worker, snapshot persistence and owner fencing stay real.
    import backend.coaching.execution as execution
    execution.explicit_deep_review_available = lambda **kwargs: True

    from backend.api import create_app
    uvicorn.run(create_app(StudentStore(root / DATABASE_NAME)), host="127.0.0.1",
                port=port, log_level="warning", access_log=False)


@contextmanager
def _server(root: Path, port: int) -> Iterator[str]:
    """Start and always stop a fresh real loopback API process at one root."""
    origin = f"http://127.0.0.1:{port}"
    log_path = root.parent / "server-private.log"
    with log_path.open("ab") as log:
        process = subprocess.Popen(
            [sys.executable, "-m", "scripts.workspace_recovery_rehearsal",
             "--serve", str(root), "--port", str(port)],
            stdout=log, stderr=log,
            env={**_environment(root, origin),
                 "WORKSPACE_RECOVERY_TOKEN": (root / "rehearsal-disposable").read_text()})
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


def _client(origin: str) -> httpx.Client:
    """Open one keepalive browser-like client bound to the rehearsal origin."""
    return httpx.Client(base_url=origin, headers={"Origin": origin}, trust_env=False,
                        timeout=60, limits=httpx.Limits(max_connections=2,
                                                        max_keepalive_connections=2))


def _ok(client: httpx.Client, method: str, url: str, **kwargs: Any) -> Any:
    """Require HTTP success and decode the JSON body without printing it."""
    response = client.request(method, url, **kwargs)
    response.raise_for_status()
    return response.json()


def _stream_turn(client: httpx.Client, thread_id: str, message: str, key: str) -> None:
    """Submit one streamed coaching turn and require its truthful saved done."""
    terminal: dict[str, Any] = {}
    with client.stream("POST", f"/api/v1/reader/threads/{thread_id}/project/stream",
                       json={"student_message": message, "idempotency_key": key}) as response:
        response.raise_for_status()
        for line in response.iter_lines():
            event = json.loads(line)
            if event["event"] in {"done", "error"}:
                terminal = event
    if terminal.get("event") != "done":
        raise AssertionError(f"Seeding turn {key} did not save: {terminal.get('category')}")
    recovered = _ok(client, "GET", f"/api/v1/reader/threads/{thread_id}/coach-turn",
                    params={"idempotency_key": key})
    if recovered != terminal["turn"]:
        raise AssertionError("Saved-turn receipt did not match the stream terminal")


def _seed_owner(origin: str, *, with_work: bool) -> tuple[httpx.Client, dict[str, Any]]:
    """Create one real Guest and, for owner A, the complete synthetic workspace."""
    client = _client(origin)
    try:
        _ok(client, "POST", "/api/v1/auth/guest/start")
        thread_id = _ok(client, "POST", "/api/v1/reader/threads",
                        json={"name": "Recovery rehearsal"})["notebook"]["id"]
        evidence: dict[str, Any] = {"thread_id": thread_id}
        if not with_work:
            return client, evidence
        _ok(client, "POST", f"/api/v1/reader/threads/{thread_id}/project/select-stage",
            json={"stage_id": "problem_identification"})
        _stream_turn(client, thread_id, ADVANCE_MESSAGE, "seed-turn-1")
        project = _ok(client, "GET", f"/api/v1/reader/threads/{thread_id}/project")
        if project.get("pending") is None:
            raise AssertionError("ADVANCE fixture produced no pending transition")
        resolved = _ok(client, "POST",
                       f"/api/v1/reader/threads/{thread_id}/project/resolve/{project['pending']['id']}",
                       json={"accepted": True})
        if not resolved.get("recaps"):
            raise AssertionError("Confirmed transition produced no milestone recap")
        source = _ok(client, "POST", f"/api/v1/threads/{thread_id}/sources",
                     files={"files": ("analogy.txt", SOURCE_BYTES, "text/plain")})[0]
        artifact = _ok(client, "POST", f"/api/v1/reader/threads/{thread_id}/artifacts",
                       json={"title": "Rehearsal notes", "kind": "notes",
                             "document": _document("First saved draft.")})
        for revision, text in ((1, "Second saved draft."), (2, "Third saved draft.")):
            artifact = _ok(client, "PUT",
                           f"/api/v1/reader/threads/{thread_id}/artifacts/{artifact['id']}",
                           json={"document": _document(text), "revision": revision})
        canvas = _ok(client, "POST", f"/api/v1/reader/threads/{thread_id}/canvases",
                     json={"title": "Rehearsal map", "graph": _graph(2)})
        for revision, nodes in ((1, 3), (2, 4)):
            canvas = _ok(client, "PUT",
                         f"/api/v1/reader/threads/{thread_id}/canvases/{canvas['id']}",
                         json={"graph": _graph(nodes), "revision": revision})
        evidence.update({"source_id": source["id"], "artifact_id": artifact["id"],
                         "artifact_revision": artifact["revision"],
                         "canvas_id": canvas["id"], "canvas_revision": canvas["revision"],
                         "recaps": len(resolved["recaps"])})
        return client, evidence
    except BaseException:
        client.close()
        raise


def _complete_deep_review(client: httpx.Client, thread_id: str) -> dict[str, Any]:
    """Submit one durable Deep Review and wait for its terminal snapshot."""
    job = _ok(client, "POST", f"/api/v1/threads/{thread_id}/deep-review",
              json={"idempotency_key": "seed-review-1"})
    deadline = time.monotonic() + 60
    while time.monotonic() < deadline:
        job = _ok(client, "GET", f"/api/v1/threads/{thread_id}/deep-review")
        if job["status"] in {"completed", "failed"}:
            break
        time.sleep(0.1)
    if job["status"] != "completed":
        raise AssertionError(f"Deep Review did not complete: {job['status']}")
    return job


def _snapshot(client: httpx.Client, thread_id: str, ids: dict[str, Any]) -> dict[str, str]:
    """Hash every public read of one owner's saved workspace."""
    prefix = f"/api/v1/reader/threads/{thread_id}"
    reads: dict[str, Any] = {
        "project": _ok(client, "GET", f"{prefix}/project"),
        "messages_page": _ok(client, "GET", f"{prefix}/messages/page",
                             params={"limit": 100}),
        "settings": _ok(client, "GET", f"{prefix}/settings"),
        "learning_state": _ok(client, "GET",
                              f"/api/v1/threads/{thread_id}/learning-state"),
        "sources": _ok(client, "GET", f"/api/v1/threads/{thread_id}/sources"),
        "artifacts": _ok(client, "GET", f"{prefix}/artifacts"),
        "artifact": _ok(client, "GET", f"{prefix}/artifacts/{ids['artifact_id']}"),
        "artifact_versions": _ok(client, "GET",
                                 f"{prefix}/artifacts/{ids['artifact_id']}/versions"),
        "artifact_version_1": _ok(client, "GET",
                                  f"{prefix}/artifacts/{ids['artifact_id']}/versions/1"),
        "canvases": _ok(client, "GET", f"{prefix}/canvases"),
        "canvas": _ok(client, "GET", f"{prefix}/canvases/{ids['canvas_id']}"),
        "canvas_versions": _ok(client, "GET",
                               f"{prefix}/canvases/{ids['canvas_id']}/versions"),
        "canvas_version_1": _ok(client, "GET",
                                f"{prefix}/canvases/{ids['canvas_id']}/versions/1"),
        "deep_review": _ok(client, "GET", f"/api/v1/threads/{thread_id}/deep-review"),
    }
    digest = {"deep_review_status": str(reads["deep_review"]["status"]),
              "recap_count": str(len(reads["project"].get("recaps") or []))}
    for name, payload in reads.items():
        digest[name] = hashlib.sha256(
            json.dumps(payload, sort_keys=True).encode()).hexdigest()
    for name, url in (("source_content",
                       f"/api/v1/threads/{thread_id}/sources/{ids['source_id']}/content"),
                      ("transcript", f"/api/v1/threads/{thread_id}/transcript.txt")):
        response = client.get(url)
        response.raise_for_status()
        digest[name] = hashlib.sha256(response.content).hexdigest()
    return digest


def _refuse_foreign(owner_a: httpx.Client, owner_b: httpx.Client,
                    thread: str, ids: dict[str, Any]) -> dict[str, int]:
    """Require that neither owner can read the other's saved workspace."""
    foreign = {f"b_reads_{name}": owner_b.get(url).status_code for name, url in {
        "project": f"/api/v1/reader/threads/{thread}/project",
        "messages": f"/api/v1/reader/threads/{thread}/messages/page",
        "settings": f"/api/v1/reader/threads/{thread}/settings",
        "artifact": f"/api/v1/reader/threads/{thread}/artifacts/{ids['artifact_id']}",
        "canvas": f"/api/v1/reader/threads/{thread}/canvases/{ids['canvas_id']}",
        "deep_review": f"/api/v1/threads/{thread}/deep-review",
        "source_content": f"/api/v1/threads/{thread}/sources/{ids['source_id']}/content",
    }.items()}
    b_thread = _ok(owner_b, "GET", "/api/v1/reader/threads")["notebooks"][0]["id"]
    foreign["a_reads_b_project"] = owner_a.get(
        f"/api/v1/reader/threads/{b_thread}/project").status_code
    if any(status == 200 for status in foreign.values()):
        raise AssertionError(f"Owner boundary leaked: {foreign}")
    return foreign


def _backup(root: Path, backup: Path, token: str) -> dict[str, Any]:
    """Copy stopped disposable stores with the backup API plus file bytes."""
    backup.mkdir()
    inventory: dict[str, Any] = {"databases": [], "files": {}}
    for database in sorted(root.glob("*.sqlite3")):
        with closing(sqlite3.connect(database)) as source, \
                closing(sqlite3.connect(backup / database.name)) as target:
            source.backup(target)
            if target.execute("PRAGMA integrity_check").fetchone() != ("ok",):
                raise AssertionError(f"Backup of {database.name} failed integrity check")
        with closing(sqlite3.connect(backup / database.name)) as check:
            inventory["databases"].append({
                "name": database.name,
                "tables": {table: check.execute(
                    f"SELECT count(*) FROM {table}").fetchone()[0]
                    for table in INVENTORY_TABLES
                    if check.execute(
                        "SELECT count(*) FROM sqlite_master WHERE name=?",
                        (table,)).fetchone()[0]},
                "integrity_check": "ok"})
    for name in FILE_DIRS:
        if (root / name).exists():
            shutil.copytree(root / name, backup / name)
            inventory["files"][name] = sum(
                len(files) for _, _, files in os.walk(backup / name))
    shutil.copy2(root / "control.json", backup / "control.json")
    (backup / "rehearsal-disposable").write_text(token)
    return inventory


def run_rehearsal() -> dict[str, Any]:
    """Seed, restart, back up, restore into a fresh location and re-verify.

    All stores are newly created and removed on exit. Raises on any lost
    resource, version, recap, review envelope or owner-boundary leak.
    """
    with tempfile.TemporaryDirectory(prefix="workspace-recovery-") as temporary:
        base = Path(temporary)
        active = base / "active"
        active.mkdir()
        token = secrets.token_urlsafe(32)
        (active / "rehearsal-disposable").write_text(token)
        (active / "control.json").write_text(json.dumps({"provider": "advance"}))
        with socket.socket() as reservation:
            reservation.bind(("127.0.0.1", 0))
            port = reservation.getsockname()[1]
        owner_a: httpx.Client | None = None
        owner_b: httpx.Client | None = None
        try:
            with _server(active, port) as origin:
                owner_a, ids = _seed_owner(origin, with_work=True)
                thread = ids["thread_id"]
                job = _complete_deep_review(owner_a, thread)
                (active / "control.json").write_text(json.dumps({"provider": "default"}))
                owner_b, _ = _seed_owner(origin, with_work=False)
                boundary_before = _refuse_foreign(owner_a, owner_b, thread, ids)
                snapshot = _snapshot(owner_a, thread, ids)
            with _server(active, port) as origin:
                if _snapshot(owner_a, thread, ids) != snapshot:
                    raise AssertionError("Saved workspace changed across restart")
            inventory = _backup(active, base / "backup", token)
            # The original stores become unavailable; recovery uses only the
            # independent backup copied into a fresh disposable location.
            active.rename(base / "unavailable-original")
            recovered = base / "recovered"
            recovered.mkdir()
            shutil.copytree(base / "backup", recovered, dirs_exist_ok=True)
            with _server(recovered, port) as origin:
                if _snapshot(owner_a, thread, ids) != snapshot:
                    raise AssertionError("Restored workspace differs from the backup")
                boundary_after = _refuse_foreign(owner_a, owner_b, thread, ids)
                restored_job = _ok(owner_a, "GET",
                                   f"/api/v1/threads/{thread}/deep-review")
                if restored_job["status"] != "completed":
                    raise AssertionError("Deep Review job did not survive restore")
                listed = _ok(owner_a, "GET", "/api/v1/reader/threads")["notebooks"]
                if [row["id"] for row in listed] != [thread]:
                    raise AssertionError("Restored notebook list is not owner-fenced")
            with _server(recovered, port) as origin:
                if _snapshot(owner_a, thread, ids) != snapshot:
                    raise AssertionError("Restored workspace changed across a second restart")
            return {
                "evidence": "local_mock_rehearsal_only",
                "seeded": ids,
                "deep_review_status": job["status"],
                "backup_inventory": inventory,
                "owner_boundary_before_restore": boundary_before,
                "owner_boundary_after_restore": boundary_after,
                "workspace_snapshot_sha256": hashlib.sha256(
                    json.dumps(snapshot, sort_keys=True).encode()).hexdigest(),
                "restart_matches": True,
                "restore_into_fresh_location": True,
                "original_store_unavailable": True,
                "second_restart_matches": True,
                "dsql_recovery_tested": False,
                "live_recovery_claimed": False,
            }
        finally:
            if owner_a is not None:
                owner_a.close()
            if owner_b is not None:
                owner_b.close()


def main() -> None:
    """Print aggregate rehearsal JSON, or serve only a marked disposable child."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--serve", type=Path, help=argparse.SUPPRESS)
    parser.add_argument("--port", type=int, default=0, help=argparse.SUPPRESS)
    args = parser.parse_args()
    if args.serve:
        _serve(args.serve, args.port)
    else:
        print(json.dumps(run_rehearsal(), indent=2))


if __name__ == "__main__":
    main()
