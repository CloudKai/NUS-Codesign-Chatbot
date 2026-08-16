"""Safe-by-default fast-chat regression CLI tests. No live Claude."""

from __future__ import annotations

import importlib.util
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[2]
_CASES = _ROOT / "tests" / "fixtures" / "coaching_behavior_cases.json"


def _load():
    """Load the eval CLI without requiring a scripts package."""
    path = _ROOT / "scripts" / "evals" / "evaluate_fast_chat_regression.py"
    spec = importlib.util.spec_from_file_location(
        "co_design_evaluate_fast_chat_regression", path
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


_EVAL = _load()


def test_dataset_covers_required_stages_and_count() -> None:
    cases = _EVAL.load_cases(_CASES)
    assert len(cases) >= 40
    stages = {item["stage"] for item in cases}
    assert stages >= {
        "problem_identification",
        "concept_generation",
        "design_specification",
        "deep_analysis",
        "reflection",
    }
    ids = [item["id"] for item in cases]
    assert len(ids) == len(set(ids))
    assert "pi_hidden_assumption" in ids
    assert "prompt_injection" in ids
    assert "cg_complete_assignment" in ids


def test_refuse_without_dry_run_or_live_flag() -> None:
    args = _EVAL.parse_args([])
    assert _EVAL.refuse_reason(args)
    assert _EVAL.main([]) == 2


def test_dry_run_prints_plan_without_live_calls() -> None:
    args = _EVAL.parse_args(["--dry-run"])
    assert _EVAL.refuse_reason(args) is None
    assert _EVAL.main(["--dry-run"]) == 0
    report = _EVAL.dry_run_report(_EVAL.load_cases(_CASES), "")
    assert report["live_claude"] is False
    assert report["judge_model"] is False
    assert report["case_count"] >= 40
    assert "socratic_guidance" in _EVAL.EVALUATION_DIMENSIONS
    assert "does_not_complete_assignment" in _EVAL.EVALUATION_DIMENSIONS
