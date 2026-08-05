"""Explicit SQLite initialization for local Co-design Chatbot data.

Refuses to touch an existing database unless ``--force`` is passed, so casual
runs cannot mutate a developer's live student data. Prefer a dedicated
``--database`` path when creating a fresh file.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backend.settings import settings
from backend.student_store import StudentStore


def resolve_database_path(explicit: Path | None, *, force: bool) -> Path:
    """Return the database path to initialize, or exit if an existing file is unprotected.

    Args:
        explicit: Optional absolute/relative database path from ``--database``.
        force: When True, allow opening an existing database to ensure schema.

    Returns:
        Resolved filesystem path for ``StudentStore``.
    """
    path = (explicit if explicit is not None else settings.database_path).expanduser()
    path = path if path.is_absolute() else (settings.project_root / path)
    path = path.resolve()
    if path.exists() and not force:
        raise SystemExit(
            f"Refusing to initialize existing database at {path}.\n"
            "Pass --force to ensure schema on that file, or --database PATH "
            "for a new location."
        )
    return path


def main(argv: list[str] | None = None) -> int:
    """Parse CLI flags and initialize the requested SQLite database."""
    parser = argparse.ArgumentParser(
        description=(
            "Initialize the Co-design SQLite schema. "
            "Does not run unless a path is safe (new file) or --force is set."
        )
    )
    parser.add_argument(
        "--database",
        type=Path,
        default=None,
        help="Database file to create or open (default: settings.database_path).",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Allow ensuring schema on an existing database file.",
    )
    args = parser.parse_args(argv)
    path = resolve_database_path(args.database, force=args.force)
    store = StudentStore(path=path)
    print(f"Initialized Co-design student database at {store.path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
