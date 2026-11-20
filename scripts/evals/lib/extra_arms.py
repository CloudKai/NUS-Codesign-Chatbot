"""The ``extra_messages`` section of the routing comparison: arms A and C on extra rows.

Extra rows (``lib/extra_messages.py``) are a separate, descriptive section. They are not
in the 295, not in the calibration or holdout half, not used to choose ``T``, and never
enter M1, M2, a paired test or a pass rule. Arm C uses the ``T_C`` frozen on the
calibration half of the 295 as it is. Arms B and D need Laya decisions, and none exist
for extra rows, so they are ``missing``.

Search decisions come from the same existing scope code as the main comparison
(``build_row_scopes`` and ``search_flags``). Evidence needs a live KB file made for the
extra rows (``evaluate_retrieval --live-kb-gate --extra-messages``); without one, the
evidence columns are ``missing``. Rows are reported by id, category and label. No message
text is read into the output. No network, no model.
"""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from typing import Any

from scripts.evals.lib import prereg
from scripts.evals.lib.arm_metrics import MEASURED, MISSING, SYNTHETIC
from scripts.evals.lib.extra_messages import ExtraMessages
from scripts.evals.lib.intervals import format_ci, rate_ci
from scripts.evals.lib.kb_scores import KbScores
from scripts.evals.lib.prepared_rows import prepare_rows
from scripts.evals.lib.routing_arms import build_row_scopes, search_flags

SECTION_NOTE = (
    "Descriptive only. These rows are not part of the 295 gate messages, the split, the "
    "choice of T, M1, M2, the paired tests or the pass rule. Arm C uses the T_C frozen on "
    "the calibration half of the 295. Arms B and D have no Laya decisions for these rows."
)


def frozen_threshold(calibration: Mapping[str, Any]) -> float | None:
    """``T_C`` as a float (``inf`` when KB evidence is never injected), else ``None``."""
    info = calibration.get("T_C")
    if not info or not info.get("feasible"):
        return None
    threshold = info["threshold"]
    return math.inf if threshold["infinite"] else float(threshold["value"])


def _arm_record(
    arm: str, scopes: Any, label: str, hit: Any, threshold: float | None, status: str
) -> dict[str, Any]:
    kb_search, local_search = search_flags(arm, scopes, False)
    record: dict[str, Any] = {"kb_search": kb_search, "local_search": local_search}
    if arm == "C":
        record["skip_rule"] = scopes.skip_rule
    if hit is None or threshold is None:
        record.update({"evidence": None, "mistake": None, "status": MISSING})
        return record
    injection = prereg.InjectionRow(
        expected=label, local=local_search, kb_search=kb_search, kb_ok=hit.ok, top_score=hit.top_score
    )
    evidence = prereg.injected(injection, threshold)
    mistake = (not evidence) if label == "retrieve" else evidence
    record.update({"evidence": evidence, "mistake": mistake, "status": status})
    return record


def _summary(rows: Sequence[Mapping[str, Any]], arm: str) -> dict[str, Any]:
    records = [(row["label"], row[arm]) for row in rows]
    if any(rec["evidence"] is None for _, rec in records):
        return {"status": MISSING}
    retrieve = [rec for label, rec in records if label == "retrieve"]
    skip = [rec for label, rec in records if label == "skip"]
    return {
        "status": records[0][1]["status"] if records else MISSING,
        "retrieve_rows_without_evidence": rate_ci(sum(1 for r in retrieve if not r["evidence"]), len(retrieve)),
        "skip_rows_with_evidence": rate_ci(sum(1 for r in skip if r["evidence"]), len(skip)),
        "kb_searches": sum(1 for _, rec in records if rec["kb_search"]),
        "rows": len(records),
    }


def extra_section(
    extras: ExtraMessages,
    kb: KbScores | None,
    calibration: Mapping[str, Any],
    *,
    main_kb_synthetic: bool,
) -> dict[str, Any]:
    """Build the separate JSON section for the extra rows.

    ``kb`` is the extra-rows KB file (``None`` when absent or partial). ``calibration`` is
    the main result's ``calibration`` block, read for the frozen ``T_C`` and never changed.
    """
    rows = list(extras.rows)
    prepared = {p.id: p for p in prepare_rows(rows)}
    scopes = {s.id: s for s in build_row_scopes(rows, prepared)}
    kb_usable = kb if kb is not None and kb.complete else None
    t_c = frozen_threshold(calibration)
    synthetic_kb = kb_usable is not None and kb_usable.synthetic_test_fixture
    status_a = SYNTHETIC if synthetic_kb else MEASURED
    status_c = SYNTHETIC if synthetic_kb or main_kb_synthetic else MEASURED
    records = []
    for row in rows:
        row_id, label = str(row["id"]), str(row["expected_decision"])
        hit = kb_usable.rows[row_id] if kb_usable is not None else None
        records.append(
            {
                "id": row_id,
                "category": str(row["category"]),
                "label": label,
                "laya_eligible": bool(prepared[row_id].eligible),
                "A": _arm_record("A", scopes[row_id], label, hit, -math.inf, status_a),
                "C": _arm_record("C", scopes[row_id], label, hit, t_c, status_c),
            }
        )
    missing_reason = (
        "no KB file for the extra rows" if kb is None
        else "the extra-rows KB file does not cover every extra id"
    )
    return {
        "note": SECTION_NOTE,
        "real_messages": extras.real_messages,
        "allow_non_synthetic": extras.allow_non_synthetic,
        "counts": extras.describe(),
        "kb_file": (
            {"present": False}
            if kb is None
            else {"present": True, **kb.describe(extras.ids), "used": kb_usable is not None}
        ),
        "evidence_unavailable_reason": None if kb_usable is not None else missing_reason,
        "t_c_frozen": (
            None if t_c is None else {"value": None if math.isinf(t_c) else t_c, "infinite": math.isinf(t_c)}
        ),
        "arms_not_evaluated": {
            "B": f"{MISSING}: no Laya decisions exist for extra rows",
            "D": f"{MISSING}: no Laya decisions exist for extra rows",
        },
        "summary": {"A": _summary(records, "A"), "C": _summary(records, "C")},
        "rows": records,
    }


def format_extra_section(section: Mapping[str, Any]) -> str:
    """Markdown for the extra section. Ids, labels, flags and counts only."""
    counts = section["counts"]
    out = ["", "## Extra messages (separate from M1 and M2)", ""]
    if section["real_messages"]:
        out += ["**real_messages: the file holds rows marked synthetic: false.**", ""]
    out += [
        section["note"],
        "",
        f"Rows {counts['rows']} (retrieve {counts['retrieve']}, skip {counts['skip']}).",
        "",
    ]
    if section["evidence_unavailable_reason"]:
        out += [f"Evidence columns are `missing`: {section['evidence_unavailable_reason']}.", ""]
    if section["t_c_frozen"] is None:
        out += ["Arm C evidence is `missing`: no frozen T_C (needs a complete KB file for the 295 and a feasible T).", ""]
    for arm in ("A", "C"):
        summary = section["summary"][arm]
        if summary["status"] == MISSING:
            out += [f"Arm {arm}: missing."]
            continue
        out += [
            f"Arm {arm} ({summary['status']}): retrieve rows without evidence "
            f"{format_ci(summary['retrieve_rows_without_evidence'])}; skip rows with evidence "
            f"{format_ci(summary['skip_rows_with_evidence'])}; KB searches {summary['kb_searches']} of {summary['rows']}."
        ]
    out += ["", "Arms B and D: missing (no Laya decisions for extra rows).", ""]
    header = ["id", "category", "label", "A kb/local", "A evidence", "C skip rule", "C kb/local", "C evidence"]
    lines = ["| " + " | ".join(header) + " |", "|" + "|".join("---" for _ in header) + "|"]
    for row in section["rows"]:
        a, c = row["A"], row["C"]
        lines.append(
            "| "
            + " | ".join(
                [
                    row["id"],
                    row["category"],
                    row["label"],
                    f"{int(a['kb_search'])}/{int(a['local_search'])}",
                    _flag(a["evidence"]),
                    str(c["skip_rule"] or "none"),
                    f"{int(c['kb_search'])}/{int(c['local_search'])}",
                    _flag(c["evidence"]),
                ]
            )
            + " |"
        )
    return "\n".join(out + lines) + "\n"


def _flag(value: bool | None) -> str:
    return "missing" if value is None else ("yes" if value else "no")
