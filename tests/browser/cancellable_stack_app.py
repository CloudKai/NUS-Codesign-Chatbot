"""Disposable cancellable-turn boundary for the Playwright CI slice (ticket 06).

Mirrors the paused-workflow technique of
``tests/http/test_reader_conversation.py::test_reader_stop_is_owner_scoped_and_prevents_saving``:
``CoachWorkflow.run`` pauses after emitting one unvalidated reply delta until the
fixture-only control route releases it. The real mock provider otherwise finishes
faster than a browser click can win the stop/save race, so this deterministic
pause lets the browser click the real Stop control and exercise real server-side
cancellation end to end: the worker hits a cancellation checkpoint, the stream
ends with the same terminal error the FastAPI seam proves (``reply_discard``
before a 409 ``cancelled`` error), and nothing is saved.

The control route exists only in this disposable fixture process; it is not part
of the application. Run with uvicorn on a disposable port; all workspace paths
must be explicit and temporary (validated before the application imports).
"""
from __future__ import annotations

import os
import tempfile
import threading
from pathlib import Path
from typing import Any


def _require_disposable_mock() -> None:
    """Refuse to run unless mock provider and disposable temp paths are selected."""
    root = Path(os.environ.get("APP_DATA_DIR", "/invalid")).resolve()
    temporary = (Path("/tmp").resolve(), Path(tempfile.gettempdir()).resolve())
    if os.environ.get("MODEL_PROVIDER") != "mock" or not any(root.is_relative_to(p) for p in temporary):
        raise RuntimeError("Cancellable fixture requires an explicit temporary mock workspace")
    for key in ("APP_DATABASE_PATH", "APP_FILES_DIR", "APP_WORKSPACES_DIR", "LECTURE_NOTES_DIR"):
        if not os.environ.get(key) or not Path(os.environ[key]).resolve().is_relative_to(root):
            raise RuntimeError("All fixture workspace paths must be explicit and temporary")


def _create_cancellable_app() -> Any:
    """Validate disposable paths, then build the app with the pausing workflow."""
    _require_disposable_mock()

    from backend.http.app import create_app
    from backend.settings import settings
    from backend.workflow import CoachWorkflow

    # The browser client always asks for reply deltas; enable the server side of
    # that opt-in for this fixture process only.
    settings.coach_stream_reply_deltas_enabled = True

    release = threading.Event()
    original_run = CoachWorkflow.run

    def paused_run(workflow: Any, model_request: Any) -> Any:
        """Emit one preview fragment, then hold the worker until released."""
        from backend.coaching.progress import emit_coach_reply_delta

        if not release.is_set():
            emit_coach_reply_delta("Unfinished preview ")
            release.wait(30)
        return original_run(workflow, model_request)

    CoachWorkflow.run = paused_run  # type: ignore[method-assign]
    app = create_app()

    @app.post("/__fixture__/release-coach-turn")
    def release_coach_turn() -> dict[str, bool]:
        """Release the paused mock workflow; fixture-only, never application surface."""
        release.set()
        return {"released": True}

    return app


app = _create_cancellable_app()
