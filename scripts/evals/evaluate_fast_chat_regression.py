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
import sys
from pathlib import Path
from typing import Any, Sequence

_PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

_CASES_PATH = _PROJECT_ROOT / "tests" / "fixtures" / "coaching_behavior_cases.json"
_HARD_CALL_CAP = 80

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
    print(
        "Live Claude evaluation is implemented as an explicit future step. "
        "This process will not call AWS, Claude, or AgentCore without a "
        "separate authorized runtime path. Re-run with --dry-run.",
        file=sys.stderr,
    )
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
