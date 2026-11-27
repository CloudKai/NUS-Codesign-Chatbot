"""Rehearse the coordinated release configuration on disposable local resources.

Run ``python -m scripts.release_rehearsal``. Output is one aggregate JSON
rehearsal report on stdout; exit 0 means every stage passed, exit 2 means the
candidate configuration produced findings. This driver never deploys, never
touches live infrastructure, and has no flag that can select a real database,
host or student workspace: the coordinated-startup stage boots the real API
only inside a driver-created temporary tree with deterministic mock adapters,
so a passing rehearsal is ordering and configuration evidence — never a
production-safety or live-environment verdict. Live publication, migrations
and capped live checks stay gated behind the release checklist.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import secrets
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[1]
DATABASE_NAME = "release-rehearsal.sqlite3"
READER_CONTRACT = ROOT / "frontend" / "openapi" / "reader.json"
DIRECT_LINK_PATHS = ("/chats/*", "/notebooks/*", "/notebooks/*/artifacts/*",
                     "/library", "/search", "/settings")
LIVE_GATES = (
    "Publish/verify the AgentCore runtime version, endpoint qualifier and DEFAULT "
    "state against the selected release tuple (gated, capped live approval).",
    "Run the coordinated additive DSQL migration plan by an administrator against "
    "the live cluster; never app-startup DDL.",
    "Verify runtime publication, fresh sessions, allowed and blocked Mantle output "
    "and saved-data checks through the real edge within the approved cap.",
    "Fill the manifest's actually_verified_live section only from checks performed "
    "against the exact released tuple; nulls block the corresponding gate.",
)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _compose_value(text: str, key: str) -> str | None:
    match = re.search(rf'^[ \t]*{key}: "?([^"\n#]+)"?', text, re.MULTILINE)
    return match.group(1).strip() if match else None


def _edge_patterns(caddyfile: Path) -> dict[str, str]:
    """Extract the public reader/writer/lecture matchers from one edge file."""
    text = caddyfile.read_text(encoding="utf-8")
    patterns = {}
    for name in ("reader", "writer", "lecture"):
        match = re.search(rf"path_regexp {name} (\S+)", text)
        if match:
            patterns[name] = match.group(1)
    return patterns


def _stage_configuration(config_dir: Path) -> tuple[dict[str, object], list[str]]:
    """Check the candidate compose/edge files against the coordinated contract."""
    checks: dict[str, object] = {}
    findings: list[str] = []
    compose_path = config_dir / "compose.prod.yaml"
    if not compose_path.is_file():
        return {"status": "fail"}, [f"missing {compose_path.name}"]
    compose = compose_path.read_text(encoding="utf-8")
    expected = {
        "STUDENT_STAGE_SELECTION": "true",
        "AUTO_ADVANCE_STAGES": "false",
        "GUARDRAIL_VERSION": "4",
        "MODEL_PROVIDER": "agentcore",
        "DATABASE_PROVIDER": "dsql",
        "FILE_STORAGE_PROVIDER": "s3",
    }
    for key, value in expected.items():
        actual = _compose_value(compose, key)
        checks[key.lower()] = actual
        if actual != value:
            findings.append(f"compose {key}={actual!r}, expected {value!r}")
    app_image = _compose_value(compose, "image") or ""
    checks["app_image_immutable"] = "APP_IMAGE" in app_image and ":latest" not in app_image
    if not checks["app_image_immutable"]:
        findings.append(f"APP_IMAGE is not an immutable placeholder: {app_image!r}")
    generation = _compose_value(compose, "AGENTCORE_SESSION_GENERATION")
    checks["session_generation_recorded"] = bool(generation)
    if not generation:
        findings.append("AGENTCORE_SESSION_GENERATION is not set")

    caddyfile = config_dir / "Caddyfile"
    local = config_dir / "Caddyfile.local"
    if not caddyfile.is_file() or not local.is_file():
        findings.append("missing Caddyfile or Caddyfile.local")
        return {"status": "fail", "checks": checks}, findings
    production_patterns = _edge_patterns(caddyfile)
    caddy_text = caddyfile.read_text(encoding="utf-8")
    checks["ready_not_public"] = "ready" not in production_patterns.get("reader", "") + \
        production_patterns.get("lecture", "") + production_patterns.get("writer", "")
    if not checks["ready_not_public"]:
        findings.append("host-local /api/v1/ready must stay private at the edge")
    checks["api_wildcard_blocked"] = "handle /api/*" in caddy_text and \
        'respond "Not Found" 404' in caddy_text
    if not checks["api_wildcard_blocked"]:
        findings.append("edge lacks the bounded /api/* 404 fallthrough")
    checks["direct_link_paths_allowlisted"] = sum(
        1 for path in DIRECT_LINK_PATHS if path in caddy_text)
    if checks["direct_link_paths_allowlisted"] < len(DIRECT_LINK_PATHS):
        findings.append("recognized student deep-link paths are not all allowlisted")

    if READER_CONTRACT.is_file() and production_patterns:
        contract = json.loads(READER_CONTRACT.read_text(encoding="utf-8"))
        parity_failures = []
        for path, ops in contract["paths"].items():
            for method in ("get", "post", "put"):
                if method not in ops:
                    continue
                name = {"get": "reader", "post": "lecture", "put": "writer"}[method]
                pattern = production_patterns.get(name)
                if not pattern or not re.fullmatch(pattern, path):
                    parity_failures.append(f"{method.upper()} {path}")
        checks["reader_contract_edge_parity"] = not parity_failures
        if parity_failures:
            findings.append(
                "production edge does not allow built-contract routes: "
                + ", ".join(parity_failures[:5]))
    else:
        checks["reader_contract_edge_parity"] = False
        findings.append("reader contract or edge matchers unavailable for parity check")
    return {"status": "pass" if not findings else "fail", "checks": checks}, findings


def _stage_contracts_and_builds() -> tuple[dict[str, object], list[str]]:
    """Verify the generated contract and the production frontend build exist."""
    findings: list[str] = []
    details: dict[str, object] = {"status": "pass"}
    if not READER_CONTRACT.is_file():
        findings.append("generated reader contract is missing")
    else:
        contract = json.loads(READER_CONTRACT.read_text(encoding="utf-8"))
        details["reader_contract_paths"] = len(contract.get("paths", {}))
        details["generated_contract_sha256"] = _sha256(READER_CONTRACT)
    index = ROOT / "frontend" / "dist" / "index.html"
    if not index.is_file():
        findings.append("frontend/dist/index.html missing; run npm run build --prefix frontend")
    else:
        details["frontend_dist_index_sha256"] = _sha256(index)
        details["frontend_dist_assets"] = len(list((ROOT / "frontend" / "dist").rglob("*")))
    details["status"] = "pass" if not findings else "fail"
    return details, findings


def _stage_coordinated_startup(root: Path) -> tuple[dict[str, object], list[str]]:
    """Boot the real API once on disposable data and probe health/readiness.

    The production fail-closed gate is exercised as a negative check: the same
    mock adapter tuple must be refused under APP_ENV=production, so a rehearsal
    adapter can never be mistaken for a production release configuration.
    """
    findings: list[str] = []
    details: dict[str, object] = {"status": "pass"}
    root.mkdir(parents=True, exist_ok=True)
    port = _free_port()
    token_path = root / "rehearsal-disposable"
    token_path.write_text(token_path.parent.name)
    process = subprocess.Popen(
        [sys.executable, "-m", "scripts.release_rehearsal", "--serve",
         str(root), "--port", str(port)],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        env={**_child_environment(root, port),
             "RELEASE_REHEARSAL_TOKEN": token_path.read_text()})
    try:
        deadline = time.monotonic() + 60
        ready_status = None
        health_status = None
        health_mode = None
        with httpx.Client(base_url=f"http://127.0.0.1:{port}", trust_env=False) as client:
            while time.monotonic() < deadline:
                try:
                    probe = client.get("/api/v1/ready")
                    if probe.status_code == 200:
                        ready_status = probe.status_code
                        health = client.get("/api/v1/health")
                        health_status = health.status_code
                        health_mode = health.json().get("mode")
                        break
                except httpx.TransportError:
                    if process.poll() is not None:
                        break
                time.sleep(0.1)
        details["ready_status"] = ready_status
        details["health_status"] = health_status
        details["health_mode"] = health_mode
        if ready_status != 200 or health_status != 200:
            findings.append("disposable coordinated startup failed health/readiness")
        # Negative check: the mock rehearsal tuple must fail production validation.
        rejected = subprocess.run(
            [sys.executable, "-c",
             "from backend.settings import validate_production_configuration; "
             "validate_production_configuration()"],
            capture_output=True, text=True, timeout=120,
            env={**_child_environment(root, port), "APP_ENV": "production"})
        details["mock_tuple_rejected_for_production"] = rejected.returncode != 0
        if rejected.returncode == 0:
            findings.append("production fail-closed validation accepted a mock tuple")
    finally:
        process.terminate()
        try:
            process.wait(10)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(5)
    details["status"] = "pass" if not findings else "fail"
    return details, findings


def _stage_backup_restore() -> tuple[dict[str, object], list[str]]:
    """Run the saved-workspace backup/restore rehearsal on its disposable data."""
    started = time.monotonic()
    result = subprocess.run(
        [sys.executable, "-m", "scripts.workspace_recovery_rehearsal"],
        capture_output=True, text=True, timeout=1200, cwd=ROOT)
    duration = round(time.monotonic() - started, 1)
    details: dict[str, object] = {
        "driver": "scripts.workspace_recovery_rehearsal",
        "exit_code": result.returncode,
        "duration_seconds": duration,
    }
    findings: list[str] = []
    if result.returncode != 0:
        findings.append("saved-workspace backup/restore rehearsal failed")
        details["stderr_tail"] = result.stderr[-800:]
    details["status"] = "pass" if result.returncode == 0 else "fail"
    return details, findings


def _free_port() -> int:
    import socket
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def _child_environment(root: Path, port: int) -> dict[str, str]:
    """Pin every child adapter to the disposable tree and deterministic mocks."""
    return {**os.environ, "APP_ENV": "development", "MODEL_PROVIDER": "mock",
            "MOCK_OPENAI": "true", "OPENAI_API_KEY": "",
            "DATABASE_PROVIDER": "sqlite", "FILE_STORAGE_PROVIDER": "local",
            "KNOWLEDGE_BASE_ID": "", "AGENTCORE_RUNTIME_ARN": "",
            "COURSE_MATERIALS_BUCKET": "", "COURSE_MATERIAL_SYNC_ENABLED": "false",
            "AWS_EC2_METADATA_DISABLED": "true", "APP_DATA_DIR": str(root),
            "APP_DATABASE_PATH": str(root / DATABASE_NAME),
            "APP_FILES_DIR": str(root / "files"),
            "APP_WORKSPACES_DIR": str(root / "workspaces"),
            "LECTURE_NOTES_DIR": str(root / "lectures"),
            "GUEST_ACCESS_ENABLED": "false", "AUTH_COOKIE_SECURE": "false",
            "CO_DESIGN_PUBLIC_API_URL": f"http://127.0.0.1:{port}",
            "CO_DESIGN_UI_URL": f"http://127.0.0.1:{port}",
            "COGNITO_USER_POOL_ID": "", "COGNITO_CLIENT_ID": "",
            "COGNITO_DOMAIN": "", "AUTO_ADVANCE_STAGES": "false",
            "STUDENT_STAGE_SELECTION": "true", "PYTHON_DOTENV_DISABLED": "1"}


def _serve(root: Path, port: int) -> None:
    """Run one isolated real API worker; only driver-marked roots may boot."""
    token = os.environ.get("RELEASE_REHEARSAL_TOKEN", "")
    if (root.name != "startup"
            or not root.parent.name.startswith("release-rehearsal-")
            or root.parent.parent.resolve() != Path(tempfile.gettempdir()).resolve()
            or not token or not (root / "rehearsal-disposable").is_file()
            or not secrets.compare_digest(
                (root / "rehearsal-disposable").read_text(), token)):
        raise ValueError("Only driver-created disposable child launches are allowed")
    os.environ.update(_child_environment(root, port))
    import uvicorn
    from backend.api import create_app
    from backend.student_store import StudentStore

    uvicorn.run(create_app(StudentStore(root / DATABASE_NAME)), host="127.0.0.1",
                port=port, log_level="warning", access_log=False)


def main() -> None:
    """Aggregate the rehearsal stages; findings fail the run without deploying."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config-dir", type=Path, default=ROOT,
                        help="candidate deployment-file directory (default: repository)")
    parser.add_argument("--skip-recovery", action="store_true",
                        help="skip the slower backup/restore rehearsal stage")
    parser.add_argument("--serve", type=Path, help=argparse.SUPPRESS)
    parser.add_argument("--port", type=int, help=argparse.SUPPRESS)
    arguments = parser.parse_args()
    if arguments.serve is not None:
        _serve(arguments.serve, arguments.port or 0)
        return

    config_dir = arguments.config_dir.resolve()
    stages: dict[str, object] = {}
    findings: list[str] = []

    configuration, configuration_findings = _stage_configuration(config_dir)
    stages["configuration"] = configuration
    findings.extend(configuration_findings)

    builds, build_findings = _stage_contracts_and_builds()
    stages["contracts_and_builds"] = builds
    findings.extend(build_findings)

    with tempfile.TemporaryDirectory(prefix="release-rehearsal-") as temporary:
        startup, startup_findings = _stage_coordinated_startup(Path(temporary) / "startup")
    stages["coordinated_startup"] = startup
    findings.extend(startup_findings)

    if arguments.skip_recovery:
        stages["backup_restore"] = {"status": "skipped"}
    else:
        recovery, recovery_findings = _stage_backup_restore()
        stages["backup_restore"] = recovery
        findings.extend(recovery_findings)

    report = {
        "rehearsal": "release-rehearsal",
        "recorded_at_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "disposable": True,
        "config_dir": str(config_dir),
        "stages": stages,
        "findings": findings,
        "live_gates": list(LIVE_GATES),
        "live_steps_executed": False,
    }
    print(json.dumps(report, indent=2))
    raise SystemExit(0 if not findings else 2)


if __name__ == "__main__":
    main()
