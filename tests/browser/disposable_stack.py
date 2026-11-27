"""Disposable, mock-only FastAPI stack for the Playwright Test CI slice (ticket 05).

This boots the same production-built CDE2300 reader frontend and real same-origin
FastAPI + SQLite application that the manual browser scripts exercise, but as a
finite, self-cleaning process controlled by the Playwright slice
(`frontend/tests/browser/stack.ts`), which can also restart it in place. It never
uses a personal database, live Cognito, AWS credentials, or a paid provider.

All workspace paths are created under a temporary directory and every mutable
setting is pinned to mock/SQLite/local so the stack is reproducible and
non-billable. Run it once; it prints READY after /api/v1/ready answers and then
blocks until Playwright terminates it.
"""
from __future__ import annotations

import os
import signal
import subprocess
import sys
import tempfile
import time
import urllib.request
from pathlib import Path

ROOT = Path.cwd()
FRONTEND_DIST = ROOT / "frontend" / "dist" / "index.html"

REQUIRED_DATA_KEYS = (
    "APP_DATABASE_PATH",
    "APP_FILES_DIR",
    "APP_WORKSPACES_DIR",
    "LECTURE_NOTES_DIR",
)


def _require_disposable_environment(env: dict[str, str]) -> None:
    """Refuse to run unless mock provider and disposable temp paths are selected.

    This mirrors the guards on the other browser fixtures so the Playwright slice
    can never point at a developer's real data or a live provider. It validates the
    resolved workspace rather than the caller's ambient environment.
    """
    if env.get("MODEL_PROVIDER") != "mock":
        sys.exit("disposable_stack: MODEL_PROVIDER must be 'mock'")
    if env.get("MOCK_OPENAI") != "true":
        sys.exit("disposable_stack: MOCK_OPENAI must be 'true'")
    if env.get("OPENAI_API_KEY") != "":
        sys.exit("disposable_stack: OPENAI_API_KEY must be empty")
    temp_roots = (Path("/tmp").resolve(), Path(tempfile.gettempdir()).resolve())
    root = Path(env.get("APP_DATA_DIR", "/invalid")).resolve()
    if not any(root.is_relative_to(candidate) for candidate in temp_roots):
        sys.exit("disposable_stack: APP_DATA_DIR must live under the temporary directory")
    for key in REQUIRED_DATA_KEYS:
        value = env.get(key)
        if not value or not Path(value).resolve().is_relative_to(root):
            sys.exit(f"disposable_stack: {key} must live under APP_DATA_DIR")


def _build_environment() -> dict[str, str]:
    """Create a dedicated disposable workspace tree and a mock-only environment.

    When CO_DESIGN_STACK_DIR is set the tree is reused so a later process can reopen
    the same saved output; otherwise a fresh private directory is created.
    """
    env = dict(os.environ)
    env["MODEL_PROVIDER"] = "mock"
    env["MOCK_OPENAI"] = "true"
    env["OPENAI_API_KEY"] = ""
    env["DATABASE_PROVIDER"] = "sqlite"
    env["FILE_STORAGE_PROVIDER"] = "local"
    env["GUEST_ACCESS_ENABLED"] = "true"
    env["AUTO_ADVANCE_STAGES"] = "false"
    env["STUDENT_STAGE_SELECTION"] = "false"
    env["COACH_REQUESTS_PER_MINUTE"] = "120"
    env["COURSE_MATERIAL_SYNC_ENABLED"] = "false"
    env["APP_ENV"] = "development"
    env.setdefault("PYTHON_DOTENV_DISABLED", "1")

    # The public/UI base URL must match the origin the browser actually loads, or
    # the guest-start same-origin check rejects the request (see app.py).
    host = os.environ.get("PW_STACK_HOST", "127.0.0.1")
    port = os.environ.get("PW_STACK_PORT", "8123")
    origin = f"http://{host}:{port}"
    env["CO_DESIGN_PUBLIC_API_URL"] = origin
    env["CO_DESIGN_UI_URL"] = origin

    existing = os.environ.get("CO_DESIGN_STACK_DIR")
    root = Path(existing).resolve() if existing else Path(tempfile.mkdtemp(prefix="codesign-pw-stack-"))
    root.mkdir(parents=True, exist_ok=True)
    (root / "lecture_notes").mkdir(exist_ok=True)

    env["APP_DATA_DIR"] = str(root)
    env["APP_DATABASE_PATH"] = str(root / "workspace.sqlite3")
    env["APP_FILES_DIR"] = str(root / "files")
    env["APP_WORKSPACES_DIR"] = str(root / "workspaces")
    env["LECTURE_NOTES_DIR"] = str(root / "lecture_notes")
    return env


def _wait_until_ready(
    port: int,
    process: subprocess.Popen,
    log_path: Path,
    timeout_seconds: float = 60.0,
) -> None:
    """Poll readiness until it answers, the timeout elapses, or the server dies.

    If the served uvicorn process exits first, its captured log is printed so the
    failure is diagnosable instead of burning the whole readiness timeout.
    """
    deadline = time.monotonic() + timeout_seconds
    last_error = "readiness URL never answered"
    while time.monotonic() < deadline:
        if process.poll() is not None:
            tail = ""
            try:
                tail = log_path.read_text(errors="replace")[-2000:]
            except OSError:
                pass
            sys.exit(
                f"disposable_stack: server exited with code {process.returncode} "
                f"before readiness.\n--- server log tail ---\n{tail}"
            )
        try:
            with urllib.request.urlopen(f"http://127.0.0.1:{port}/api/v1/ready", timeout=2) as response:
                if response.status == 200:
                    return
        except Exception as error:  # noqa: BLE001 - readiness probe tolerates errors
            last_error = str(error)
        time.sleep(0.25)
    sys.exit(f"disposable_stack: readiness probe failed after {timeout_seconds}s: {last_error}")


def main() -> None:
    """Build a disposable workspace, validate it, and serve the stack."""
    if not FRONTEND_DIST.exists():
        sys.exit("disposable_stack: frontend not built; run 'npm run build --prefix frontend' first")

    # Build the workspace first, then validate the resolved disposable paths so the
    # guard checks the real (temporary) tree instead of the caller's environment.
    env = _build_environment()
    _require_disposable_environment(env)

    port = int(os.environ.get("PW_STACK_PORT", "8123"))
    host = os.environ.get("PW_STACK_HOST", "127.0.0.1")

    print(f"disposable_stack: workspace {env['APP_DATA_DIR']}", flush=True)
    print(f"disposable_stack: serving http://{host}:{port}", flush=True)

    # Capture the served process output in the disposable workspace so a startup
    # failure is diagnosable (a PIPE nobody drains would risk blocking the child).
    server_log = Path(env["APP_DATA_DIR"]) / "server.log"
    # PW_REGISTERED_IDENTITY=1 serves the synthetic registered-identity boundary
    # (tests/browser/registered_stack_app.py) instead of the plain mock app.
    # PW_STACK_APP=<module> serves another tests/browser fixture app (e.g.
    # cancellable_stack_app) the same way. The modes are mutually exclusive.
    if os.environ.get("PW_REGISTERED_IDENTITY") == "1":
        if os.environ.get("PW_STACK_APP"):
            sys.exit("disposable_stack: PW_REGISTERED_IDENTITY and PW_STACK_APP are mutually exclusive")
        uvicorn_target = "registered_stack_app:app"
        uvicorn_dir = str(ROOT / "tests" / "browser")
    elif os.environ.get("PW_STACK_APP"):
        module = os.environ["PW_STACK_APP"]
        if not (ROOT / "tests" / "browser" / f"{module}.py").is_file():
            sys.exit(f"disposable_stack: unknown PW_STACK_APP fixture module {module!r}")
        uvicorn_target = f"{module}:app"
        uvicorn_dir = str(ROOT / "tests" / "browser")
    else:
        uvicorn_target = "backend.http.app:app"
        uvicorn_dir = str(ROOT)
    process = subprocess.Popen(
        [
            os.environ.get("PW_PYTHON", sys.executable),
            "-m",
            "uvicorn",
            uvicorn_target,
            "--app-dir",
            uvicorn_dir,
            "--host",
            host,
            "--port",
            str(port),
        ],
        cwd=str(ROOT),
        env=env,
        stdout=server_log.open("w"),
        stderr=subprocess.STDOUT,
    )

    # Terminate the served uvicorn process on SIGTERM so a restart rebinds cleanly
    # instead of leaking the port to an orphaned child.
    def _terminate(signum, frame):  # noqa: ARG001
        if process.poll() is None:
            process.terminate()

    signal.signal(signal.SIGTERM, _terminate)

    try:
        _wait_until_ready(port, process, server_log)
        print("disposable_stack: READY", flush=True)
        process.wait()
    except KeyboardInterrupt:
        process.terminate()


if __name__ == "__main__":
    main()
