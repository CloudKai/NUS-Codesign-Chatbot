"""Gated live AgentCore coaching smoke (never used by pytest).

Automated tests must not call this script with approval flags. A live invoke
requires ``--i-approve-live-agentcore``, a positive ``--cost-cap``, and
``--max-requests 1``. Default is refuse.
"""

from __future__ import annotations

import argparse
import json
import sys
from typing import Sequence


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    """Parse the live-smoke CLI, defaulting to a refused dry check."""
    parser = argparse.ArgumentParser(
        description="One-request AgentCore coaching smoke with an explicit cost cap."
    )
    parser.add_argument(
        "--i-approve-live-agentcore",
        action="store_true",
        help="Required acknowledgement that this call is paid and live.",
    )
    parser.add_argument(
        "--cost-cap",
        type=float,
        default=0.0,
        help="USD ceiling the operator accepts for this single request.",
    )
    parser.add_argument(
        "--max-requests",
        type=int,
        default=1,
        help="Must remain 1 so this script cannot fan out.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Validate flags and print the payload without invoking AWS.",
    )
    return parser.parse_args(list(argv) if argv is not None else None)


def refuse_reason(args: argparse.Namespace) -> str | None:
    """Return a refusal message when the live smoke must not run."""
    if not args.i_approve_live_agentcore:
        return "live AgentCore smoke requires --i-approve-live-agentcore"
    if args.cost_cap <= 0:
        return "live AgentCore smoke requires a positive --cost-cap"
    if args.max_requests != 1:
        return "live AgentCore smoke allows --max-requests 1 only"
    return None


def main(argv: Sequence[str] | None = None) -> int:
    """Refuse by default; invoke AgentCore only after explicit approval flags."""
    args = parse_args(argv)
    reason = refuse_reason(args)
    if reason:
        print(f"refusing: {reason}", file=sys.stderr)
        return 2
    from backend.agentcore_provider import AgentCoreCoachProvider
    from backend.domain import CoachRequest
    from backend.settings import settings

    if not settings.resolved_agentcore_runtime_arn:
        print("refusing: AGENTCORE_RUNTIME_ARN is not configured", file=sys.stderr)
        return 2
    request = CoachRequest(
        thread_id="agentcore-smoke",
        student_message="Name one trade-off that still needs evidence.",
        current_stage="problem_identification",
        response_detail="short",
    )
    provider = AgentCoreCoachProvider(
        settings.resolved_agentcore_runtime_arn,
        region=settings.aws_region,
        qualifier=settings.agentcore_qualifier,
        timeout_seconds=min(settings.agentcore_timeout_seconds, 30.0),
        max_retries=0,
    )
    payload = provider._invoke_payload(request, "coaching")
    if args.dry_run:
        print(json.dumps({"dry_run": True, "phase": payload.get("phase")}, indent=2))
        return 0
    result = provider.assess(request)
    print(
        json.dumps(
            {
                "ok": True,
                "stage": result.assessment.current_stage,
                "recommendation": result.assessment.recommendation.value,
            }
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
