"""Compatibility entrypoint for the admin-only Aurora DSQL bootstrap.

The implementation lives in :mod:`scripts.dsql.cli`.  This module keeps the
historical direct CLI path and import surface used by operators and tests.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts.dsql import cli as _implementation  # noqa: E402

# Preserve the complete historical module surface, including private helpers
# used by deterministic adapter tests. Assigning the implementation objects
# directly also keeps signatures and monkeypatch targets stable.
for _name in dir(_implementation):
    if not _name.startswith("__"):
        globals()[_name] = getattr(_implementation, _name)

__all__ = list(getattr(_implementation, "__all__", ())) or [
    name for name in dir(_implementation) if not name.startswith("_")
]


if __name__ == "__main__":
    raise SystemExit(_implementation.main())
