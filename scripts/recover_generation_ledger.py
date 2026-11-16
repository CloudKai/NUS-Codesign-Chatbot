"""Back up and release local generation slots after all API/UI workers stop."""

from __future__ import annotations

import argparse
from contextlib import closing
from pathlib import Path
import sqlite3
import sys

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backend.generation_admission import GenerationPolicy, SQLiteGenerationAdmission


def main() -> int:
    """Require explicit shutdown confirmation and a new backup before recovery."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--policy", required=True, type=Path)
    parser.add_argument("--backup", required=True, type=Path)
    parser.add_argument("--confirm-all-workers-stopped", action="store_true")
    args = parser.parse_args()
    if not args.confirm_all_workers_stopped:
        parser.error("Stop every API/UI worker and explicitly confirm before recovering")
    try:
        policy = GenerationPolicy.model_validate_json(args.policy.read_text())
        if not policy.ledger_path.is_file() or args.backup.exists():
            raise ValueError("Existing ledger and new backup path required")
        # Exclusive creation prevents overwriting an existing backup or student DB.
        with args.backup.open("xb"):
            pass
        with closing(sqlite3.connect(f"file:{policy.ledger_path}?mode=ro", uri=True)) as source:
            with closing(sqlite3.connect(args.backup)) as destination:
                source.backup(destination)
        ledger = SQLiteGenerationAdmission(policy)
        count = ledger.recover_stopped_workers()
    except (OSError, ValueError, sqlite3.Error):
        print("Recovery failed; inspect configuration and preserve the ledger/backup.", file=sys.stderr)
        return 2
    print(f"Released {count} orphan slots; invoked charges retained. Backup saved.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
