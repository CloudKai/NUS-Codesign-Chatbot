"""Safe-by-default fast-chat regression CLI tests. No live Claude."""

from __future__ import annotations

import importlib.util
import json
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


def test_live_without_arn_is_refused(monkeypatch) -> None:
    monkeypatch.delenv("AGENTCORE_RUNTIME_ARN", raising=False)
    args = _EVAL.parse_args(["--i-approve-live-claude", "--max-calls", "1"])
    assert _EVAL.refuse_reason(args)
    assert _EVAL.main(["--i-approve-live-claude", "--max-calls", "1"]) == 2


def test_baseline_missing_is_unavailable(tmp_path) -> None:
    report = _EVAL.compare_baseline({"results": []}, str(tmp_path / "missing.json"))
    assert report["baseline_comparison"] == "unavailable"
    assert "unavailable" in report["note"]


def test_live_candidate_artifact_with_mocked_invoke(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("AGENTCORE_RUNTIME_ARN", "arn:aws:bedrock-agentcore:us-west-2:1:runtime/x")

    def fake_run(cases, **kwargs):
        del kwargs
        return [
            {
                "id": cases[0]["id"],
                "expected": cases[0].get("expected"),
                "status": "ok",
                "specialist": "coaching",
                "recommendation": "stay",
                "response_text": "What assumption is carrying that claim?",
                "dimensions": list(_EVAL.EVALUATION_DIMENSIONS),
            }
        ]

    monkeypatch.setattr(_EVAL, "run_live_candidates", fake_run)
    output = tmp_path / "candidate.json"
    assert (
        _EVAL.main(
            [
                "--i-approve-live-claude",
                "--max-calls",
                "1",
                "--output",
                str(output),
            ]
        )
        == 0
    )
    payload = json.loads(output.read_text(encoding="utf-8"))
    assert payload["live_claude"] is True
    assert payload["judge_model"] is False
    assert payload["agentcore_publish"] is False
    assert payload["baseline_comparison"] == "unavailable"
    assert payload["results"][0]["status"] == "ok"
