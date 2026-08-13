"""Regression coverage for the deterministic mock load-probe CLI."""

from __future__ import annotations

import ast
import subprocess
import sys
from pathlib import Path


def test_load_probe_runs_as_documented_with_distinct_virtual_users():
    """Direct execution is import-safe and avoids false per-owner throttling."""
    root = Path(__file__).resolve().parents[1]
    completed = subprocess.run(
        [
            sys.executable,
            str(root / "scripts" / "load_probe.py"),
            "--users",
            "5",
            "--requests-per-user",
            "1",
        ],
        cwd=root,
        check=True,
        capture_output=True,
        text=True,
        timeout=30,
    )
    result = ast.literal_eval(completed.stdout.strip().splitlines()[-1])

    assert result["users"] == 5
    assert result["requests"] == 5
    assert result["errors"] == 0
    assert result["http_429"] == 0
