"""Write a JSON result file with its ``run`` block (git SHA, dirty flag, UTC time)."""

from __future__ import annotations

import json
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from scripts.evals.lib.paths import PROJECT_ROOT as _PROJECT_ROOT


def _git_run_metadata() -> dict[str, Any]:
    """Return the checkout's commit and a UTC timestamp for a JSON output file.

    ``git_dirty`` is true when tracked files have uncommitted changes
    (untracked files are ignored). Both git fields are ``None`` when git is
    unavailable. Local subprocess only; never raises.
    """
    import subprocess
    from datetime import datetime, timezone

    def _git(*command: str) -> str | None:
        try:
            done = subprocess.run(
                ["git", *command],
                cwd=_PROJECT_ROOT,
                capture_output=True,
                text=True,
                timeout=5,
                check=False,
            )
        except (OSError, subprocess.SubprocessError):
            return None
        return done.stdout if done.returncode == 0 else None

    sha = _git("rev-parse", "HEAD")
    status = _git("status", "--porcelain", "--untracked-files=no")
    return {
        "git_sha": (sha.strip() or None) if sha is not None else None,
        "git_dirty": bool(status.strip()) if status is not None else None,
        "generated_at_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    }


def _write_json_output(
    path: Path, result: Mapping[str, Any], run: Mapping[str, Any] | None = None
) -> None:
    """Write ``result`` as JSON with a ``run`` block (git SHA, UTC timestamp).

    Shared by the offline, ``--live-kb`` and ``--live-model`` modes. ``run`` is
    added only to the file, so the printed report is unchanged. ``run`` defaults
    to ``_git_run_metadata()``; a caller may pass its own block.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    data = {**result, "run": _git_run_metadata() if run is None else run}
    path.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8")
