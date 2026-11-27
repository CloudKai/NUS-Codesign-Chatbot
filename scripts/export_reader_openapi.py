"""Export an allowlisted browser contract offline without publishing API docs.

The CLI forces disposable mock storage before importing the application and
blocks network connections. No running backend, credentials or user data needed.
"""

from __future__ import annotations

import argparse
import json
import os
import socket
import sys
import tempfile
from pathlib import Path
from typing import Any

from fastapi import FastAPI
from fastapi.openapi.utils import get_openapi
from fastapi.routing import APIRoute

ROOT = Path(__file__).resolve().parents[1]
APPROVED_OPERATIONS = {
    ("/api/v1/reader/bootstrap", "GET"): "readerBootstrap",
    ("/api/v1/reader/session", "GET"): "readerSession",
    ("/api/v1/reader/threads", "GET"): "readerNotebooks",
    ("/api/v1/reader/threads/{thread_id}/messages/page", "GET"): "readerMessages",
    ("/api/v1/reader/threads/{thread_id}/workspace", "GET"): "readerThreadWorkspace",
    ("/api/v1/reader/preferences", "GET"): "readerPreferences",
    ("/api/v1/reader/preferences", "POST"): "readerPreferencesUpdate",
    ("/api/v1/reader/threads/{thread_id}/settings", "GET"): "readerNotebookSettings",
    ("/api/v1/reader/threads/{thread_id}/settings", "POST"): "readerNotebookSettingsUpdate",
    ("/api/v1/reader/threads", "POST"): "readerThreadsCreate",
    ("/api/v1/reader/threads/{thread_id}/move", "POST"): "readerThreadMove",
    ("/api/v1/reader/threads/{thread_id}/remove", "POST"): "readerThreadRemove",
    ("/api/v1/reader/threads/{thread_id}/sources", "GET"): "readerSources",
    ("/api/v1/reader/threads/{thread_id}/sources/{source_id}", "GET"): "readerSource",
    ("/api/v1/reader/threads/{thread_id}/sources/{source_id}/select", "POST"): "readerSourceSelect",
    ("/api/v1/reader/threads/{thread_id}/sources/{source_id}/link", "POST"): "readerSourceLink",
    ("/api/v1/reader/threads/{thread_id}/sources/{source_id}/remove", "POST"): "readerSourceRemove",
    ("/api/v1/reader/threads/{thread_id}/uploads", "GET"): "readerUploads",
    ("/api/v1/reader/threads/{thread_id}/uploads/{upload_id}/retry", "POST"): "readerUploadRetry",
    ("/api/v1/reader/threads/{thread_id}/uploads/{upload_id}/discard", "POST"): "readerUploadDiscard",
    ("/api/v1/reader/threads/{thread_id}/bookmarks", "GET"): "readerBookmarks",
    ("/api/v1/reader/threads/{thread_id}/messages/{message_id}/star", "POST"): "readerStar",
    ("/api/v1/reader/threads/{thread_id}/project", "GET"): "readerProject",
    ("/api/v1/reader/threads/{thread_id}/project/resolve/{transition_id}", "POST"): "readerProjectResolve",
    ("/api/v1/reader/threads/{thread_id}/project/select-stage", "POST"): "readerProjectSelect",
    ("/api/v1/reader/threads/{thread_id}/project/brief", "POST"): "readerProjectBrief",
    ("/api/v1/reader/threads/{thread_id}/deep-review", "GET"): "readerDeepReview",
    ("/api/v1/reader/threads/{thread_id}/deep-review", "POST"): "readerDeepReviewStart",
    ("/api/v1/reader/threads/{thread_id}/deep-review/cancel", "POST"): "readerDeepReviewCancel",
    ("/api/v1/reader/threads/{thread_id}/artifacts", "GET"): "readerArtifacts",
    ("/api/v1/reader/threads/{thread_id}/artifacts", "POST"): "readerArtifactCreate",
    ("/api/v1/reader/threads/{thread_id}/artifacts/{artifact_id}", "GET"): "readerArtifact",
    ("/api/v1/reader/threads/{thread_id}/artifacts/{artifact_id}", "PUT"): "readerArtifactUpdate",
    ("/api/v1/reader/threads/{thread_id}/artifacts/{artifact_id}/duplicate", "POST"): "readerArtifactDuplicate",
    ("/api/v1/reader/threads/{thread_id}/artifacts/{artifact_id}/delete", "POST"): "readerArtifactDelete",
    ("/api/v1/reader/threads/{thread_id}/artifacts/{artifact_id}/versions", "GET"): "readerArtifactVersions",
    ("/api/v1/reader/threads/{thread_id}/artifacts/{artifact_id}/versions/{revision}", "GET"): "readerArtifactVersion",
    ("/api/v1/reader/threads/{thread_id}/artifacts/{artifact_id}/versions/{revision}/restore", "POST"): "readerArtifactRestore",
    ("/api/v1/reader/threads/{thread_id}/canvases", "GET"): "readerCanvases",
    ("/api/v1/reader/threads/{thread_id}/canvases", "POST"): "readerCanvasCreate",
    ("/api/v1/reader/threads/{thread_id}/canvases/{canvas_id}", "GET"): "readerCanvas",
    ("/api/v1/reader/threads/{thread_id}/canvases/{canvas_id}", "PUT"): "readerCanvasUpdate",
    ("/api/v1/reader/threads/{thread_id}/canvases/{canvas_id}/delete", "POST"): "readerCanvasDelete",
    ("/api/v1/reader/threads/{thread_id}/canvases/{canvas_id}/versions", "GET"): "readerCanvasVersions",
    ("/api/v1/reader/threads/{thread_id}/canvases/{canvas_id}/versions/{revision}", "GET"): "readerCanvasVersion",
    ("/api/v1/reader/threads/{thread_id}/canvases/{canvas_id}/versions/{revision}/restore", "POST"): "readerCanvasRestore",
}
DEFAULT_OUTPUT = ROOT / "frontend" / "openapi" / "reader.json"


def reader_schema(app: FastAPI) -> dict[str, Any]:
    """Project only reviewed operations and their reachable Pydantic schemas.

    Missing, renamed or newly untyped operations fail closed. Other application
    routes cannot enter the generated client merely by being registered.
    """
    routes = []
    found: set[tuple[str, str]] = set()
    for route in app.routes:
        if not isinstance(route, APIRoute):
            continue
        for method in route.methods:
            key = (route.path, method)
            if key not in APPROVED_OPERATIONS:
                continue
            if route.response_model is None or route.operation_id != APPROVED_OPERATIONS[key]:
                raise ValueError(f"Browser contract requires a typed stable operation: {key}")
            if route.methods != {method}:
                raise ValueError("Browser contract requires single-method routes")
            found.add(key)
            routes.append(route)
    if found != APPROVED_OPERATIONS.keys():
        raise ValueError("Approved browser operation missing")
    return get_openapi(title="Co-design browser reader", version="1.0.0", routes=routes)


def export_offline() -> str:
    """Build deterministic JSON in a fresh mock workspace with sockets blocked.

    Run in a dedicated process: bootstrap changes process environment, and refuses
    an already imported settings module to avoid reusing production dependencies.
    """
    if "backend.settings" in sys.modules:
        raise RuntimeError("Export must run in a fresh process")
    with tempfile.TemporaryDirectory(prefix="codesign-openapi-") as directory:
        root = Path(directory)
        os.environ.update({
            "APP_ENV": "development", "MODEL_PROVIDER": "mock", "MOCK_OPENAI": "true",
            "DATABASE_PROVIDER": "sqlite", "FILE_STORAGE_PROVIDER": "local",
            "APP_DATA_DIR": str(root), "APP_DATABASE_PATH": str(root / "schema.sqlite3"),
            "APP_FILES_DIR": str(root / "files"), "APP_WORKSPACES_DIR": str(root / "workspaces"),
            "LECTURE_NOTES_DIR": str(root / "lectures"), "COURSE_MATERIAL_SYNC_ENABLED": "false",
            "OPENAI_API_KEY": "", "AGENTCORE_RUNTIME_ARN": "", "KNOWLEDGE_BASE_ID": "",
            "GENERATION_ADMISSION_POLICY": "", "LOCAL_COURSE_INTENT_CHECKPOINT": "",
            "LOCAL_COURSE_INTENT_LEARNER_BUNDLE": "", "AUTO_ADVANCE_STAGES": "false",
        })
        original_connect = socket.socket.connect
        original_connect_ex = socket.socket.connect_ex

        def no_network(*args: Any, **kwargs: Any) -> Any:
            """Fail closed if application composition tries to reach a service."""
            raise RuntimeError("Network access prohibited during OpenAPI export")

        socket.socket.connect = no_network
        socket.socket.connect_ex = no_network
        try:
            sys.path.insert(0, str(ROOT))
            from backend.http.app import app

            return json.dumps(reader_schema(app), indent=2, sort_keys=True) + "\n"
        finally:
            socket.socket.connect = original_connect
            socket.socket.connect_ex = original_connect_ex


def main(argv: list[str] | None = None) -> int:
    """Write the reviewed contract, or report drift without modifying files."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args(argv)
    content = export_offline()
    if args.check:
        if not args.output.is_file() or args.output.read_text(encoding="utf-8") != content:
            print("Reader contract drift: run scripts/export_reader_openapi.py", file=sys.stderr)
            return 1
        return 0
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(content, encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
