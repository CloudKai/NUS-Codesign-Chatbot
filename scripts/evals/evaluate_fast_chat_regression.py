"""Safe-by-default fast-chat coaching behaviour regression entry point.

This is not ``evaluate_live_coach.py``. That script is an isolated Luna
evaluation. This entry point compares candidate fast-chat behaviour against
an explicit baseline artifact using the versioned case dataset.

Default: refuse live model calls. ``--dry-run`` inspects cases only.
Live Claude requires ``--i-approve-live-claude`` and is not invoked by pytest.
This script never publishes AgentCore.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Sequence

_PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

_CASES_PATH = _PROJECT_ROOT / "tests" / "fixtures" / "coaching_behavior_cases.json"
_HARD_CALL_CAP = 80
_DEFAULT_OUTPUT = (
    _PROJECT_ROOT / "scripts" / "evals" / "artifacts" / "fast_chat_regression_candidate.json"
)

EVALUATION_DIMENSIONS = (
    "socratic_guidance",
    "student_agency",
    "stage_alignment",
    "reasoning_gap_identification",
    "assumption_challenge",
    "vv_quality",
    "question_focus",
    "does_not_complete_assignment",
    "non_grading",
    "conversation_continuity",
    "stay_advance_consistency",
    "source_grounding",
    "citation_validity",
    "hallucination_avoidance",
    "response_relevance",
    "correctness",
    "faithfulness",
    "citation_precision",
    "citation_coverage",
)

CRITICAL_REGRESSIONS = (
    "begins directly completing assignments",
    "stops asking Socratic questions",
    "repeatedly asks already-answered questions",
    "ignores current stage",
    "makes decisions for the student",
    "invents citations",
    "introduces unsupported course claims",
    "starts grading",
    "lets CLEAR/research coding control Coaching",
    "materially worsens STAY/ADVANCE judgement",
)


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    """Parse the regression CLI, defaulting to a refused dry check."""
    parser = argparse.ArgumentParser(
        description="Fast-chat coaching behaviour regression (safe by default)."
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Load cases and print the evaluation plan without model calls.",
    )
    parser.add_argument(
        "--i-approve-live-claude",
        action="store_true",
        help="Required acknowledgement that live Claude calls are paid.",
    )
    parser.add_argument(
        "--cases",
        default=str(_CASES_PATH),
        help="Path to the behaviour-case JSON dataset.",
    )
    parser.add_argument(
        "--baseline-artifact",
        default="",
        help="Optional previously generated ratings JSON. Never invented.",
    )
    parser.add_argument(
        "--max-calls",
        type=int,
        default=8,
        help="Maximum live model calls for this process (hard cap 80).",
    )
    parser.add_argument(
        "--output",
        default=str(_DEFAULT_OUTPUT),
        help="Versioned JSON artifact path for live candidate results.",
    )
    return parser.parse_args(list(argv) if argv is not None else None)


def refuse_reason(args: argparse.Namespace) -> str | None:
    """Return a refusal message when the evaluation must not run live."""
    if not args.dry_run and not args.i_approve_live_claude:
        return (
            "fast-chat regression requires --dry-run or --i-approve-live-claude"
        )
    if int(args.max_calls) < 1:
        return "--max-calls must be at least 1"
    if int(args.max_calls) > _HARD_CALL_CAP:
        return f"--max-calls cannot exceed {_HARD_CALL_CAP}"
    if args.i_approve_live_claude and not args.dry_run:
        if not str(os.environ.get("AGENTCORE_RUNTIME_ARN") or "").strip():
            return (
                "AGENTCORE_RUNTIME_ARN is not configured; live candidate "
                "execution refused"
            )
    return None


def load_cases(path: Path) -> list[dict[str, Any]]:
    """Load version-controlled behavioural cases. No network."""
    payload = json.loads(path.read_text(encoding="utf-8"))
    cases = payload.get("cases") if isinstance(payload, dict) else payload
    if not isinstance(cases, list) or not cases:
        raise ValueError("behaviour case dataset is empty")
    return [item for item in cases if isinstance(item, dict)]


def dry_run_report(cases: list[dict[str, Any]], baseline_artifact: str) -> dict[str, Any]:
    """Return a JSON-serialisable dry-run summary with no model output."""
    stages = sorted({str(item.get("stage") or "") for item in cases})
    return {
        "event": "fast_chat_regression_dry_run",
        "case_count": len(cases),
        "stages": stages,
        "dimensions": list(EVALUATION_DIMENSIONS),
        "critical_regressions": list(CRITICAL_REGRESSIONS),
        "baseline_artifact": baseline_artifact or None,
        "live_claude": False,
        "judge_model": False,
        "agentcore_publish": False,
        "note": (
            "Mock tests do not prove live model quality. Baseline ratings must "
            "be an explicit artifact; this dry run does not invent them."
        ),
    }


def compare_baseline(
    candidate: dict[str, Any], baseline_artifact: str
) -> dict[str, Any]:
    """Compare candidate results to an explicit baseline file, or say unavailable.

    Args:
        candidate: Live or recorded candidate artifact.
        baseline_artifact: Path to a previously saved JSON file.

    Returns:
        Comparison metadata. Never invents historical responses.
    """
    path = Path(str(baseline_artifact or "").strip())
    if not str(baseline_artifact or "").strip() or not path.is_file():
        return {
            "baseline_comparison": "unavailable",
            "note": "baseline comparison unavailable",
        }
    try:
        baseline = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {
            "baseline_comparison": "unavailable",
            "note": "baseline comparison unavailable",
        }
    if not isinstance(baseline, dict):
        return {
            "baseline_comparison": "unavailable",
            "note": "baseline comparison unavailable",
        }
    candidate_ids = [item.get("id") for item in candidate.get("results") or [] if isinstance(item, dict)]
    baseline_ids = [item.get("id") for item in baseline.get("results") or [] if isinstance(item, dict)]
    return {
        "baseline_comparison": "present",
        "baseline_path": str(path),
        "candidate_case_count": len(candidate_ids),
        "baseline_case_count": len(baseline_ids),
        "shared_case_count": len(set(candidate_ids) & set(baseline_ids)),
        "note": (
            "Baseline file loaded. This helper does not score or judge quality."
        ),
    }


def run_live_candidates(
    cases: list[dict[str, Any]],
    *,
    max_calls: int,
    runtime_arn: str,
    region: str,
    qualifier: str,
) -> list[dict[str, Any]]:
    """Invoke the already-configured AgentCore runtime for fixture cases.

    Does not persist student data, publish AgentCore, or call a judge model.

    Args:
        cases: Versioned evaluation fixtures.
        max_calls: Inclusive call cap for this process.
        runtime_arn: Existing AgentCore runtime ARN.
        region: AgentCore AWS region.
        qualifier: Runtime qualifier, typically ``DEFAULT``.

    Returns:
        One result dict per attempted case.
    """
    from backend.agentcore_provider import AgentCoreCoachProvider
    from backend.domain import CoachRequest

    provider = AgentCoreCoachProvider(
        runtime_arn,
        region=region,
        qualifier=qualifier,
        timeout_seconds=110.0,
        max_retries=0,
    )
    results: list[dict[str, Any]] = []
    for case in cases[: max(0, int(max_calls))]:
        case_id = str(case.get("id") or "unknown")
        request = CoachRequest(
            thread_id=f"eval-{case_id}",
            student_message=str(case.get("student_message") or "Hello."),
            current_stage=str(case.get("stage") or "problem_identification"),
            response_detail="short",
        )
        try:
            result = provider.assess(request)
            results.append(
                {
                    "id": case_id,
                    "expected": case.get("expected"),
                    "status": "ok",
                    "specialist": result.specialist,
                    "recommendation": result.assessment.recommendation.value,
                    "response_text": result.response_text,
                    "dimensions": list(EVALUATION_DIMENSIONS),
                }
            )
        except Exception as error:
            results.append(
                {
                    "id": case_id,
                    "expected": case.get("expected"),
                    "status": "error",
                    "category": str(
                        getattr(error, "category", "") or type(error).__name__
                    ),
                    "dimensions": list(EVALUATION_DIMENSIONS),
                }
            )
    return results


def write_candidate_artifact(
    path: Path,
    *,
    cases: list[dict[str, Any]],
    results: list[dict[str, Any]],
    baseline_artifact: str,
    max_calls: int,
) -> dict[str, Any]:
    """Write a versioned candidate JSON artifact and return it."""
    artifact = {
        "event": "fast_chat_regression_candidate",
        "version": "fast-chat-regression-v1",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "case_count": len(cases),
        "attempted_calls": len(results),
        "max_calls": int(max_calls),
        "dimensions": list(EVALUATION_DIMENSIONS),
        "critical_regressions": list(CRITICAL_REGRESSIONS),
        "judge_model": False,
        "agentcore_publish": False,
        "live_claude": True,
        "results": results,
    }
    artifact.update(compare_baseline(artifact, baseline_artifact))
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(artifact, indent=2) + "\n", encoding="utf-8")
    return artifact


def main(argv: Sequence[str] | None = None) -> int:
    """Run the safe default CLI. Live Claude is refused without the flag."""
    args = parse_args(argv)
    refused = refuse_reason(args)
    if refused:
        print(refused, file=sys.stderr)
        return 2
    cases = load_cases(Path(args.cases))
    if args.dry_run:
        print(json.dumps(dry_run_report(cases, args.baseline_artifact), indent=2))
        return 0
    from backend.settings import settings

    results = run_live_candidates(
        cases,
        max_calls=int(args.max_calls),
        runtime_arn=str(os.environ.get("AGENTCORE_RUNTIME_ARN") or "").strip(),
        region=str(settings.aws_region or "us-west-2"),
        qualifier=str(settings.agentcore_qualifier or "DEFAULT"),
    )
    artifact = write_candidate_artifact(
        Path(args.output),
        cases=cases,
        results=results,
        baseline_artifact=args.baseline_artifact,
        max_calls=int(args.max_calls),
    )
    print(json.dumps(artifact, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
