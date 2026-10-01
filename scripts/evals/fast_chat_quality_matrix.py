"""Print the Fast Chat quality matrix. Safe by default. No AWS.

This is an evaluation plan, not a measured scorecard. Live execution is
refused unless the caller later adds an explicit approval flag to a
different entry point.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Sequence

_PROJECT_ROOT = Path(__file__).resolve().parents[2]
_MATRIX = _PROJECT_ROOT / "tests" / "fixtures" / "fast_chat_quality_matrix.json"


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    """Parse the dry-run CLI."""
    parser = argparse.ArgumentParser(
        description="List Fast Chat quality-matrix cases without scoring."
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print case ids and mock/live requirements.",
    )
    parser.add_argument(
        "--i-approve-live-aws",
        action="store_true",
        help="Refused. This script never calls AWS.",
    )
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    """Print the matrix or refuse a live request."""
    args = parse_args(argv)
    if args.i_approve_live_aws:
        print("this entry point never calls AWS", file=sys.stderr)
        return 2
    payload = json.loads(_MATRIX.read_text(encoding="utf-8"))
    if not args.dry_run:
        print("pass --dry-run to list cases; live scores are not invented")
        return 0
    for item in payload["cases"]:
        kind = "live" if item.get("live_required") else "mock"
        print(f"{item['id']}\t{kind}\t{item.get('kind')}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
