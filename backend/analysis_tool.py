from __future__ import annotations

import json
from pathlib import Path

from .local_tools import execute_python, workspace_for


PYTHON_TOOL = {
    "type": "function",
    "name": "execute_python",
    "description": (
        "Run Python for a student's data analysis in this chat's persistent workspace. "
        "Returns success, stdout, stderr, and generated file paths. The function can fail "
        "when local execution is disabled, code is invalid, limits are exceeded, or time expires."
    ),
    "strict": True,
    "parameters": {
        "type": "object",
        "properties": {
            "code": {
                "type": "string",
                "description": "Complete Python code to execute for the requested analysis.",
            }
        },
        "required": ["code"],
        "additionalProperties": False,
    },
}


async def run_analysis_tool(
    thread_id: str, name: str, arguments: str
) -> tuple[str, list[Path]]:
    if name != "execute_python":
        return json.dumps({"success": False, "error": f"Unknown tool: {name}"}), []
    try:
        payload = json.loads(arguments or "{}")
    except json.JSONDecodeError as exc:
        return json.dumps({"success": False, "error": f"Invalid JSON: {exc}"}), []
    result = await execute_python(thread_id, str(payload.get("code") or ""))
    workspace = workspace_for(thread_id)
    artifacts = []
    for raw_path in result.get("generated_files", []):
        path = Path(raw_path).resolve()
        if path.is_file() and workspace in path.parents:
            artifacts.append(path)
    return json.dumps(result, ensure_ascii=False), artifacts
