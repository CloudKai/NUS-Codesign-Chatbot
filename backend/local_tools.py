from __future__ import annotations

import asyncio
import json
import os
import resource
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

from .settings import settings


PYTHON_TOOL = {
    "type": "function",
    "name": "execute_python",
    "description": (
        "Run Python for data analysis or artifact creation in this chat's persistent "
        "workspace. This tool is available only when the server owner explicitly enables it."
    ),
    "strict": True,
    "parameters": {
        "type": "object",
        "properties": {
            "code": {"type": "string", "description": "Complete Python code to execute."}
        },
        "required": ["code"],
        "additionalProperties": False,
    },
}


def workspace_for(thread_id: str) -> Path:
    safe_id = "".join(ch for ch in thread_id if ch.isalnum() or ch in {"-", "_"})
    workspace = (settings.workspaces_dir / safe_id).resolve()
    if settings.workspaces_dir not in workspace.parents:
        raise ValueError("Unsafe workspace identifier")
    workspace.mkdir(parents=True, exist_ok=True)
    return workspace


def _limit_process() -> None:
    resource.setrlimit(resource.RLIMIT_CPU, (settings.python_timeout_seconds, settings.python_timeout_seconds + 1))
    resource.setrlimit(resource.RLIMIT_AS, (768 * 1024 * 1024, 768 * 1024 * 1024))
    resource.setrlimit(resource.RLIMIT_FSIZE, (50 * 1024 * 1024, 50 * 1024 * 1024))
    resource.setrlimit(resource.RLIMIT_NOFILE, (64, 64))


def _execute_python_sync(thread_id: str, code: str) -> dict[str, Any]:
    workspace = workspace_for(thread_id)
    before = {path.name for path in workspace.iterdir() if path.is_file()}
    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".py", dir=workspace, delete=False, encoding="utf-8"
    ) as script:
        script.write(
            "import os\n"
            f"os.chdir({str(workspace)!r})\n"
            "try:\n"
            "    import matplotlib\n"
            "    matplotlib.use('Agg')\n"
            "except Exception:\n"
            "    pass\n\n"
        )
        script.write(code)
        script_path = Path(script.name)
    try:
        result = subprocess.run(
            [sys.executable, "-I", str(script_path)],
            cwd=workspace,
            capture_output=True,
            text=True,
            timeout=settings.python_timeout_seconds,
            preexec_fn=_limit_process if os.name == "posix" else None,
            env={"PATH": os.environ.get("PATH", ""), "MPLBACKEND": "Agg"},
        )
        after = {path.name for path in workspace.iterdir() if path.is_file()}
        generated = []
        for name in sorted(after - before - {script_path.name}):
            path = (workspace / name).resolve()
            if workspace in path.parents and path.is_file() and path.stat().st_size <= 50 * 1024 * 1024:
                generated.append(str(path))
        return {
            "success": result.returncode == 0,
            "return_code": result.returncode,
            "stdout": result.stdout[-12000:],
            "stderr": result.stderr[-12000:],
            "generated_files": generated,
        }
    except subprocess.TimeoutExpired:
        return {
            "success": False,
            "return_code": -1,
            "stdout": "",
            "stderr": f"Execution exceeded {settings.python_timeout_seconds} seconds.",
            "generated_files": [],
        }
    finally:
        script_path.unlink(missing_ok=True)


async def execute_python(thread_id: str, code: str) -> dict[str, Any]:
    if not settings.enable_local_code_execution:
        return {
            "success": False,
            "error": "Local Python is disabled. Set ENABLE_LOCAL_CODE_EXECUTION=true for trusted local use.",
        }
    return await asyncio.to_thread(_execute_python_sync, thread_id, code)


async def call_local_tool(thread_id: str, name: str, arguments: str) -> str:
    try:
        payload = json.loads(arguments or "{}")
    except json.JSONDecodeError as exc:
        return json.dumps({"success": False, "error": f"Invalid tool arguments: {exc}"})
    if name == "execute_python":
        result = await execute_python(thread_id, str(payload.get("code", "")))
        return json.dumps(result, ensure_ascii=False)
    return json.dumps({"success": False, "error": f"Unknown local tool: {name}"})
