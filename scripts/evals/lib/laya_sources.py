"""Per-row Laya promotion decisions and the loaders for stored and full-run files.

``LayaSource`` and the two stored-file loaders moved verbatim from
``evaluate_combined_gate`` so ``compare_routing_arms`` shares them without importing
another command. This module also holds ``promotion`` (the one place a source and a
reading decide whether an eligible row is promoted), the Laya milliseconds that
``compare_routing_arms`` needs for added wait, and ``load_full_run``, the tolerant
loader for an all-rows run file. No model, no network, no backend import.

Full-run file (``load_full_run``). A JSON object with:

* ``rows`` (required): a list with one object per gate message. Each object needs
  ``id``. Other keys are optional and read when present: ``status`` (``scored``,
  ``busy``, ``error`` or ``not_eligible``), ``score`` (or ``course_score``, a float or
  null), ``ms`` (or ``classifier_ms``, a float or null) and ``first_turn`` (bool).
* ``memory`` (optional): ``peak_rss_mib``, ``load_delta_rss_mib`` and
  ``after_load.rss_mib`` as ``benchmark_course_intent`` writes them.
* ``host_note`` (optional): the operator's host notes. A file without it is read, but
  its figures are labelled ``bound``, not ``measured``.
* ``real_model`` (optional): ``false`` marks a stub run and the file is refused.

Every eligible gate row must appear, otherwise the file is refused as incomplete. A
row is promoted when it is eligible, has a score, and the score reaches the cutoff
(the continuing-turn cutoff, or the first-turn cutoff on a first turn). A busy or
failed call has no score, so the row is not promoted, as in production.
"""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from scripts.evals.lib.prepared_rows import PreparedRow

STORED_ORIGIN = "from stored results, not re-run"
RERUN_ORIGIN = "re-run in this process"
FULL_RUN_ORIGIN = "all-rows run file"

# How eligible rows with no stored Laya decision are treated.
MODES = {
    "floor": "unscored eligible rows are not promoted (the least Laya can do)",
    "ceiling": "unscored eligible rows are all promoted (the most Laya can do)",
    "scored_only": "unscored eligible rows are left out; every kept row has an exact decision",
}


class LayaFileError(ValueError):
    """A Laya results file is unreadable, stub-made, inconsistent or incomplete."""


@dataclass(frozen=True)
class LayaSource:
    """Per-row Laya promotion decisions and where they came from."""

    name: str
    origin: str
    description: str
    cutoffs: Mapping[str, Any]
    # id -> promoted. Holds every row the source has a decision for.
    decisions: Mapping[str, bool]
    file: str | None = None
    file_summary: Mapping[str, Any] | None = None
    consistency: Mapping[str, Any] = field(default_factory=dict)
    # id -> stored inference milliseconds (null when none was stored).
    ms: Mapping[str, float | None] = field(default_factory=dict)
    # True for an all-rows run file with host notes (a measurement, not a stored bound).
    host_noted: bool = False
    memory: Mapping[str, Any] = field(default_factory=dict)
    host_note: Mapping[str, Any] | None = None


def promotion(row: PreparedRow, source: LayaSource | None, mode: str) -> tuple[bool, bool]:
    """Return ``(promoted, unscored)`` for one row under one reading.

    A row is only ever promoted when it is eligible and a source exists. An eligible
    row with no decision is ``unscored``; the reading ``mode`` then decides: promoted
    under ``ceiling``, not under ``floor``. ``scored_only`` also reports it unscored
    and the caller leaves the row out.
    """
    if source is None or not row.eligible:
        return False, False
    if row.id in source.decisions:
        return bool(source.decisions[row.id]), False
    return mode == "ceiling", True


def _stored_consistency(
    prepared: Mapping[str, PreparedRow], rows: Sequence[Mapping[str, Any]], eligible_key: str
) -> dict[str, Any]:
    """Compare stored rows with the gate and eligibility computed at this commit."""
    missing = [str(r["id"]) for r in rows if str(r["id"]) not in prepared]
    known = [r for r in rows if str(r["id"]) in prepared]
    gate = [
        str(r["id"]) for r in known if prepared[str(r["id"])].gate_retrieve != r["baseline_retrieve"]
    ]
    eligibility = [
        str(r["id"]) for r in known if prepared[str(r["id"])].eligible != bool(r[eligible_key])
    ]
    return {
        "stored_rows": len(rows),
        "ids_not_in_gate_set": missing,
        "gate_mismatch_ids": gate,
        "eligibility_mismatch_ids": eligibility,
        "consistent": not (missing or gate or eligibility),
    }


def load_stored_multilingual(
    path: Path, name: str, prepared: Mapping[str, PreparedRow]
) -> LayaSource:
    """Read a phase3d per-row run (``rows`` with ``promoted``) at its stored cutoff."""
    data = json.loads(path.read_text(encoding="utf-8"))
    rows = data["rows"]
    return LayaSource(
        name=name,
        origin=STORED_ORIGIN,
        description=f"Laya checkpoint {Path(str(data['checkpoint'])).parts[-3].split('--')[-1]}, "
        f"serial, stored cutoff {data['threshold']}",
        cutoffs={"threshold": data["threshold"]},
        decisions={str(r["id"]): bool(r["promoted"]) for r in rows},
        file=str(path),
        file_summary={
            "wrong_skip": data["with_laya"]["wrong_skip"],
            "false_retrieve": data["with_laya"]["false_retrieve"],
        },
        # A stored row was eligible when the classifier ran (or was busy) on it.
        consistency=_stored_consistency(
            prepared,
            [{**r, "eligible": r["classifier_ms"] is not None} for r in rows],
            "eligible",
        ),
        ms={str(r["id"]): r.get("classifier_ms") for r in rows},
    )


def load_stored_learn(path: Path, name: str, prepared: Mapping[str, PreparedRow]) -> LayaSource:
    """Read the Laya Learn holdout rows and apply the stored per-turn cutoffs.

    Only ``holdout_rows`` are used. The cutoffs were selected on the calibration
    rows, and the training rows were fitted on, so neither is a fair test.
    """
    data = json.loads(path.read_text(encoding="utf-8"))
    cutoffs = data["thresholds_from_calibration"]
    continuing, first = cutoffs["learn"], cutoffs.get("learn_first_turn")
    decisions: dict[str, bool] = {}
    for row in data["holdout_rows"]:
        cutoff = first if first is not None and row["first_turn"] else continuing
        score = row["learn"]
        decisions[str(row["id"])] = bool(
            row["eligible"] and score is not None and cutoff is not None and score >= cutoff
        )
    return LayaSource(
        name=name,
        origin=STORED_ORIGIN,
        description="Laya Learn, per-turn cutoffs, 84 holdout rows",
        cutoffs={"learn": continuing, "learn_first_turn": first},
        decisions=decisions,
        file=str(path),
        file_summary={
            "wrong_skip": data["holdout"]["learn_by_turn"]["wrong_skip"],
            "false_retrieve": data["holdout"]["learn_by_turn"]["false_retrieve"],
        },
        consistency=_stored_consistency(
            prepared, data["holdout_rows"], "eligible"
        ),
        ms={str(r["id"]): r.get("learn_ms") for r in data["holdout_rows"]},
    )


def _number(value: Any) -> float | None:
    """Return a float for a real number, else ``None`` (booleans are not numbers)."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value)


def load_full_run(
    path: Path,
    name: str,
    prepared: Mapping[str, PreparedRow],
    *,
    cutoff: float,
    first_turn_cutoff: float | None = None,
) -> LayaSource:
    """Read an all-rows Laya run file and apply the given, unchanged cutoffs.

    Raises ``LayaFileError`` for a stub run, an unknown or repeated id, or any
    eligible gate row missing from the file. See the module docstring for the schema.
    """
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as error:
        raise LayaFileError(f"{path}: cannot read as JSON ({type(error).__name__})") from None
    if not isinstance(data, dict) or not isinstance(data.get("rows"), list):
        raise LayaFileError(f"{path}: expected an object with a 'rows' list")
    if data.get("real_model") is False:
        raise LayaFileError(f"{path}: a stub run (real_model false) is not a Laya result")
    decisions: dict[str, bool] = {}
    ms: dict[str, float | None] = {}
    unknown: list[str] = []
    mismatched: list[str] = []
    for item in data["rows"]:
        if not isinstance(item, dict) or "id" not in item:
            raise LayaFileError(f"{path}: every row needs an 'id'")
        row_id = str(item["id"])
        if row_id in decisions:
            raise LayaFileError(f"{path}: repeated id {row_id}")
        row = prepared.get(row_id)
        if row is None:
            unknown.append(row_id)
            continue
        score = _number(item.get("score", item.get("course_score")))
        millis = _number(item.get("ms", item.get("classifier_ms")))
        status = item.get("status")
        in_file_eligible = (
            status != "not_eligible" if status is not None else (score is not None or millis is not None)
        )
        if in_file_eligible != row.eligible:
            mismatched.append(row_id)
        first = item.get("first_turn")
        first_turn = row.first_turn if not isinstance(first, bool) else first
        use = first_turn_cutoff if first_turn_cutoff is not None and first_turn else cutoff
        decisions[row_id] = bool(row.eligible and score is not None and score >= use)
        ms[row_id] = millis
    if unknown:
        raise LayaFileError(f"{path}: ids not in the gate set: {', '.join(sorted(unknown)[:5])}")
    missing = sorted(r.id for r in prepared.values() if r.eligible and r.id not in decisions)
    if missing:
        raise LayaFileError(
            f"{path}: incomplete, {len(missing)} eligible rows missing (first: {', '.join(missing[:5])})"
        )
    for row_id, row in prepared.items():
        if row_id not in decisions:
            decisions[row_id] = False
    memory = data.get("memory") if isinstance(data.get("memory"), dict) else {}
    after_load = memory.get("after_load") if isinstance(memory.get("after_load"), dict) else {}
    host = data.get("host_note") if isinstance(data.get("host_note"), dict) else None
    return LayaSource(
        name=name,
        origin=FULL_RUN_ORIGIN,
        description="all-rows Laya run, cutoffs unchanged",
        cutoffs={"threshold": cutoff, "first_turn_threshold": first_turn_cutoff},
        decisions=decisions,
        file=str(path),
        consistency={
            "stored_rows": len(data["rows"]),
            "ids_not_in_gate_set": [],
            "gate_mismatch_ids": [],
            "eligibility_mismatch_ids": sorted(mismatched),
            "consistent": not mismatched,
        },
        ms=ms,
        host_noted=host is not None,
        memory={
            "peak_rss_mib": _number(memory.get("peak_rss_mib")),
            "load_delta_rss_mib": _number(memory.get("load_delta_rss_mib")),
            "after_load_rss_mib": _number(after_load.get("rss_mib")),
        },
        host_note=host,
    )
