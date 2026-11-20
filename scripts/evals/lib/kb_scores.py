"""Loader and validator for the live Knowledge Base gate file (``--live-kb-gate``).

Reads the JSON that ``evaluate_retrieval --live-kb-gate`` writes: ``mode`` is
``"live_kb_gate"`` and ``rows`` holds one record per gate message with ``id``,
``top_score`` (float or null), ``result_count``, ``status`` (``ok``, ``empty`` or
``unavailable``), ``failure_category`` and ``elapsed_ms``. A file made for tests may
carry ``synthetic_test_fixture: true``; the loader passes the marker on so a report
can never present such a file as a result. No message text is read or kept. No AWS.
"""

from __future__ import annotations

import json
from collections.abc import Collection, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

STATUSES = frozenset({"ok", "empty", "unavailable"})


class KbFileError(ValueError):
    """The KB-score file is unreadable, has the wrong shape, or names unknown ids."""


@dataclass(frozen=True)
class KbRow:
    """One Retrieve outcome for one gate message."""

    id: str
    top_score: float | None
    result_count: int
    status: str
    elapsed_ms: float

    @property
    def ok(self) -> bool:
        """The call was answered with at least one validated result."""
        return self.status != "unavailable" and self.result_count >= 1 and self.top_score is not None


@dataclass(frozen=True)
class KbScores:
    """The rows of one KB-score file and what they cover."""

    path: str
    rows: Mapping[str, KbRow]
    complete: bool
    stopped_on_auth_error: bool
    synthetic_test_fixture: bool
    git_sha: str | None
    kb_settings: Mapping[str, Any]

    def describe(self, expected_ids: Collection[str]) -> dict[str, Any]:
        """JSON-ready coverage and counts (no scores, no text)."""
        failed = sum(1 for row in self.rows.values() if row.status == "unavailable")
        return {
            "path": self.path,
            "rows_in_file": len(self.rows),
            "ids_expected": len(expected_ids),
            "ids_missing": len(set(expected_ids) - set(self.rows)),
            "complete": self.complete,
            "stopped_on_auth_error": self.stopped_on_auth_error,
            "failed_calls": failed,
            "empty_results": sum(1 for row in self.rows.values() if row.status == "empty"),
            "synthetic_test_fixture": self.synthetic_test_fixture,
            "git_sha": self.git_sha,
            "kb_settings": dict(self.kb_settings),
        }


def _row(raw: Any) -> KbRow:
    if not isinstance(raw, dict) or "id" not in raw:
        raise KbFileError("every KB row needs an 'id'")
    row_id = str(raw["id"])
    status = raw.get("status")
    if status not in STATUSES:
        raise KbFileError(f"{row_id}: status must be one of {', '.join(sorted(STATUSES))}")
    count = raw.get("result_count")
    if isinstance(count, bool) or not isinstance(count, int) or count < 0:
        raise KbFileError(f"{row_id}: result_count must be a non-negative integer")
    score = raw.get("top_score")
    if score is not None and (isinstance(score, bool) or not isinstance(score, (int, float))):
        raise KbFileError(f"{row_id}: top_score must be a number or null")
    elapsed = raw.get("elapsed_ms")
    if isinstance(elapsed, bool) or not isinstance(elapsed, (int, float)) or elapsed < 0:
        raise KbFileError(f"{row_id}: elapsed_ms must be a non-negative number")
    if count > 0 and score is None:
        raise KbFileError(f"{row_id}: result_count above 0 needs a top_score")
    return KbRow(
        id=row_id,
        top_score=None if score is None else float(score),
        result_count=count,
        status=str(status),
        elapsed_ms=float(elapsed),
    )


def load_kb_scores(path: Path, expected_ids: Collection[str]) -> KbScores:
    """Read and validate a KB-score file against the gate ids.

    Raises ``KbFileError`` for an unreadable file, a wrong ``mode``, a malformed or
    repeated row, or an id outside ``expected_ids``. A file that covers only some
    expected ids loads with ``complete`` False; the caller reports KB figures as
    missing then.
    """
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as error:
        raise KbFileError(f"{path}: cannot read as JSON ({type(error).__name__})") from None
    if not isinstance(data, dict) or data.get("mode") != "live_kb_gate":
        raise KbFileError(f"{path}: not a live_kb_gate file (mode must be 'live_kb_gate')")
    raw_rows = data.get("rows")
    if not isinstance(raw_rows, list):
        raise KbFileError(f"{path}: 'rows' must be a list")
    rows: dict[str, KbRow] = {}
    for raw in raw_rows:
        row = _row(raw)
        if row.id in rows:
            raise KbFileError(f"{path}: repeated id {row.id}")
        rows[row.id] = row
    unknown = sorted(set(rows) - set(expected_ids))
    if unknown:
        raise KbFileError(f"{path}: ids not in the gate set: {', '.join(unknown[:5])}")
    summary = data.get("summary") if isinstance(data.get("summary"), dict) else {}
    run = data.get("run") if isinstance(data.get("run"), dict) else {}
    settings = data.get("kb_settings") if isinstance(data.get("kb_settings"), dict) else {}
    return KbScores(
        path=str(path),
        rows=rows,
        complete=set(rows) == set(expected_ids),
        stopped_on_auth_error=bool(summary.get("stopped_on_auth_error")),
        synthetic_test_fixture=data.get("synthetic_test_fixture") is True,
        git_sha=run.get("git_sha") if isinstance(run.get("git_sha"), str) else None,
        kb_settings=settings,
    )
