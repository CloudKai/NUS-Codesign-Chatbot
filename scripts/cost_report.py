"""Render an offline monthly SGD report from explicit inventory and usage JSONL.

Run from the repository root with ``python -m scripts.cost_report``. This CLI
reads only named operator files; it never opens the application DB or an account.
"""

from __future__ import annotations

import argparse
import json
import sys
from decimal import DecimalException
from pathlib import Path

from pydantic import ValidationError

from backend.cost_accounting import CostInventory, cost_report


def main(argv: list[str] | None = None) -> int:
    """Print a JSON report, or return 2 on invalid input without echoing content."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--inventory", type=Path, required=True)
    parser.add_argument("--events", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        inventory = CostInventory.model_validate_json(args.inventory.read_text())
        events = []
        for line in args.events.read_text().splitlines():
            if not line.strip():
                continue
            event = json.loads(line)
            events.append(event)
        report = cost_report(inventory, events)
    except (OSError, ValueError, ValidationError, TypeError, DecimalException):
        print("Invalid cost inventory or usage export; check the documented schema and evidence.", file=sys.stderr)
        return 2
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
