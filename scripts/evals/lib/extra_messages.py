"""Loader and validator for the optional ``--extra-messages`` file.

The file holds anonymised, human-labelled messages the operator wants to check next to
the 295 synthetic gate messages. One JSON object per line (JSONL), UTF-8:

* required: ``id``, ``message``, ``label`` (``retrieve`` or ``skip``) and ``synthetic``
  (a JSON boolean);
* optional: ``history_summary`` (a short text, becomes one earlier user turn),
  ``selected_source`` and ``attachment`` (booleans, default false; a flag adds one source
  with no title or filename), ``stage`` (default ``problem_identification``) and
  ``category`` (one of the gate categories, default ``uncategorised``).

A row whose ``synthetic`` is not ``true`` is refused. ``allow_non_synthetic=True``
(command flag ``--allow-non-synthetic``) accepts ``synthetic: false`` and marks the
result ``real_messages``. The marker itself must always be a boolean.

Privacy. Errors name a line number, a field name and, when the id is a safe token, the
id. They never repeat a message, a history summary or any other field value. Rows go
into the gate row format in memory only; the commands write ids, categories, labels,
scores and counts, never message or history text. No network, no model.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from scripts.evals.lib.fixtures import MESSAGE_CATEGORIES

DECISION_LABELS = frozenset({"retrieve", "skip"})
REQUIRED_FIELDS = frozenset({"id", "message", "label", "synthetic"})
OPTIONAL_FIELDS = frozenset({"history_summary", "selected_source", "attachment", "stage", "category"})
DEFAULT_STAGE = "problem_identification"
DEFAULT_CATEGORY = "uncategorised"
MAX_ROWS = 295
MAX_MESSAGE_CHARS = 4000
MAX_HISTORY_CHARS = 2000
MAX_ERRORS = 20
ALLOW_FLAG = "--allow-non-synthetic"

_ID = re.compile(r"[A-Za-z][A-Za-z0-9_-]{0,39}")
_GATE_ID = re.compile(r"gm\d{3}")
_FIELD_NAME = re.compile(r"[a-z_]{1,32}")


class ExtraMessagesError(ValueError):
    """The extra-messages file does not match its documented format (no row text inside)."""


@dataclass(frozen=True)
class ExtraMessages:
    """Validated extra rows in the gate row format, and how they were accepted."""

    rows: tuple[dict[str, Any], ...]
    real_messages: bool
    allow_non_synthetic: bool

    @property
    def ids(self) -> list[str]:
        return [str(row["id"]) for row in self.rows]

    def describe(self) -> dict[str, Any]:
        """JSON-ready counts (no text)."""
        return {
            "rows": len(self.rows),
            "retrieve": sum(1 for r in self.rows if r["expected_decision"] == "retrieve"),
            "skip": sum(1 for r in self.rows if r["expected_decision"] == "skip"),
            "real_messages": self.real_messages,
            "allow_non_synthetic": self.allow_non_synthetic,
        }


def _name(value: Any) -> str:
    """A field name that is safe to print; anything else is shown as ``<invalid name>``."""
    return value if isinstance(value, str) and _FIELD_NAME.fullmatch(value) else "<invalid name>"


def _row_errors(raw: Any, allow_non_synthetic: bool) -> tuple[str | None, list[str]]:
    """Return the id (when it is a safe token) and the problems of one parsed row."""
    if not isinstance(raw, dict):
        return None, ["row is not a JSON object"]
    errors: list[str] = []
    row_id = raw.get("id")
    safe_id = row_id if isinstance(row_id, str) and _ID.fullmatch(row_id) else None
    missing = sorted(REQUIRED_FIELDS - set(raw))
    if missing:
        errors.append(f"missing field(s): {', '.join(missing)}")
    unknown = sorted(_name(key) for key in set(raw) - REQUIRED_FIELDS - OPTIONAL_FIELDS)
    if unknown:
        errors.append(f"unexpected field(s): {', '.join(unknown)}")
    if "id" in raw:
        if safe_id is None:
            errors.append("field 'id' must be a short token (letters, digits, '_' or '-', starting with a letter)")
        elif _GATE_ID.fullmatch(safe_id):
            errors.append("field 'id' must not look like a gate message id (gm###)")
    if "message" in raw:
        text = raw["message"]
        if not isinstance(text, str) or not text.strip():
            errors.append("field 'message' must be a non-empty string")
        elif len(text) > MAX_MESSAGE_CHARS:
            errors.append(f"field 'message' is longer than {MAX_MESSAGE_CHARS} characters")
    summary = raw.get("history_summary")
    if summary is not None and (not isinstance(summary, str) or len(summary) > MAX_HISTORY_CHARS):
        errors.append(f"field 'history_summary' must be a string of at most {MAX_HISTORY_CHARS} characters")
    for flag in ("selected_source", "attachment"):
        if flag in raw and not isinstance(raw[flag], bool):
            errors.append(f"field '{flag}' must be true or false")
    if "label" in raw and raw["label"] not in DECISION_LABELS:
        errors.append("field 'label' must be 'retrieve' or 'skip'")
    if "category" in raw and raw["category"] not in MESSAGE_CATEGORIES:
        errors.append("field 'category' is not one of the gate categories")
    if "stage" in raw:
        from backend.domain import VALID_STAGE_IDS

        if raw["stage"] not in VALID_STAGE_IDS:
            errors.append("field 'stage' is not a known stage id")
    if "synthetic" in raw:
        marker = raw["synthetic"]
        if not isinstance(marker, bool):
            errors.append("field 'synthetic' must be true or false")
        elif marker is not True and not allow_non_synthetic:
            errors.append(f"synthetic marker is not true (refused; {ALLOW_FLAG} accepts real messages)")
    return safe_id, errors


def _gate_row(raw: dict[str, Any]) -> dict[str, Any]:
    """Project a validated extra row into the gate row format."""
    blank = {"title": "", "filename": ""}
    summary = str(raw.get("history_summary") or "").strip()
    return {
        "id": raw["id"],
        "message": raw["message"],
        "stage": raw.get("stage", DEFAULT_STAGE),
        "selected_sources": [dict(blank)] if raw.get("selected_source") else [],
        "attachments": [dict(blank)] if raw.get("attachment") else [],
        "history": [{"role": "user", "text": summary}] if summary else [],
        "expected_decision": raw["label"],
        "category": raw.get("category", DEFAULT_CATEGORY),
        "synthetic": raw["synthetic"],
    }


def load_extra_messages(path: Path, *, allow_non_synthetic: bool = False) -> ExtraMessages:
    """Read and validate an extra-messages JSONL file.

    Raises:
        ExtraMessagesError: For an unreadable file, an empty file, more than ``MAX_ROWS``
            rows, a blank line, invalid JSON, a duplicate id, or any row that breaks the
            format (including ``synthetic`` not true while ``allow_non_synthetic`` is
            False). The message lists line numbers, ids and field names, never values.
    """
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except (OSError, UnicodeError) as error:
        raise ExtraMessagesError(f"cannot read the extra-messages file ({type(error).__name__})") from None
    if not lines:
        raise ExtraMessagesError("the extra-messages file is empty")
    if len(lines) > MAX_ROWS:
        raise ExtraMessagesError(f"the extra-messages file has more than {MAX_ROWS} rows")
    problems: list[str] = []
    rows: list[dict[str, Any]] = []
    seen: set[str] = set()
    for number, line in enumerate(lines, start=1):
        if not line.strip():
            problems.append(f"line {number}: blank line")
            continue
        try:
            raw = json.loads(line)
        except ValueError:
            problems.append(f"line {number}: not valid JSON")
            continue
        safe_id, errors = _row_errors(raw, allow_non_synthetic)
        if safe_id is not None and safe_id in seen:
            errors.append("duplicate id")
        if safe_id is not None:
            seen.add(safe_id)
        where = f"line {number}" + (f" (id {safe_id})" if safe_id else "")
        problems += [f"{where}: {error}" for error in errors]
        if not errors:
            rows.append(_gate_row(raw))
    if problems:
        shown = problems[:MAX_ERRORS]
        more = len(problems) - len(shown)
        raise ExtraMessagesError("; ".join(shown) + (f"; and {more} more" if more else ""))
    return ExtraMessages(
        rows=tuple(rows),
        real_messages=any(row["synthetic"] is not True for row in rows),
        allow_non_synthetic=allow_non_synthetic,
    )
