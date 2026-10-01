"""Quality-matrix CLI is dry-run only. No AWS."""

from __future__ import annotations

import importlib.util
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[2]


def _load():
    """Load the matrix CLI without requiring a scripts package."""
    path = _ROOT / "scripts" / "evals" / "fast_chat_quality_matrix.py"
    spec = importlib.util.spec_from_file_location(
        "co_design_fast_chat_quality_matrix", path
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_quality_matrix_cli_refuses_live_aws(capsys) -> None:
    module = _load()
    assert module.main(["--i-approve-live-aws"]) == 2
    err = capsys.readouterr().err
    assert "never calls AWS" in err


def test_quality_matrix_cli_dry_run_lists_required_cases(capsys) -> None:
    module = _load()
    assert module.main(["--dry-run"]) == 0
    out = capsys.readouterr().out
    assert "A_simple_greeting" in out
    assert "I_evidence_absent" in out
    assert "T_deep_review_while_chat" in out
    assert "mock" in out
    assert "live" in out
