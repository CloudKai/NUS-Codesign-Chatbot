"""Markdown rendering of the ``compare_routing_arms`` result. No I/O, no backend import."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from scripts.evals.lib.arm_metrics import NO_LAYA, PAIRED_NOTE
from scripts.evals.lib.intervals import format_ci

ARM_NAMES = {
    "A": "A existing gate",
    "B": "B gate + Laya",
    "C": "C KB-score routing",
    "D": "D hybrid",
}
FAMILY_NAMES = {
    "retrieve_rows_m1": "retrieve rows (M1)",
    "skip_rows_m2": "skip rows (M2)",
    "all_rows_mistakes": "all rows (mistakes)",
}


def _table(header: Sequence[str], rows: Sequence[Sequence[str]]) -> list[str]:
    lines = ["| " + " | ".join(header) + " |", "|" + "|".join("---" for _ in header) + "|"]
    lines += ["| " + " | ".join(row) + " |" for row in rows]
    return lines


def _rate(block: Mapping[str, Any]) -> str:
    return f"{format_ci(block)} ({block['status']})"


def _p95(block: Mapping[str, Any]) -> str:
    wait = block["m4_added_wait_ms"]
    key = "combined" if wait["lower"]["combined"] is not None else "laya_only"
    low, high = wait["lower"][key]["p95"], wait["upper"][key]["p95"]
    scope = "" if key == "combined" else " Laya only, KB missing"
    text = f"{low}" if low == high else f"{low} to {high}"
    return f"{text} ({wait['status']}){scope}"


def _arm_rows(reading: Mapping[str, Any], pass_rule: Mapping[str, Any]) -> list[list[str]]:
    rows = []
    for arm, name in ARM_NAMES.items():
        block = reading["arms"][arm]
        state = pass_rule[arm]["state"]
        if not block["available"]:
            rows.append([name, f"{block['status']}: {block['reason']}", "", "", "", "", state])
            continue
        m3 = block["m3_searches_added_vs_a"]
        holdout = m3["holdout"]
        m5 = block["m5_cost_per_1000_turns"]
        memory = m5["laya_host_memory"]
        cost = f"${m5['kb_usd_per_1000_turns']} ({m5['kb_status']})"
        if memory is not None:
            cost += "; Laya memory " + (
                f"{memory['peak_rss_mib']} MiB peak RSS ({memory['status']})"
                if memory["status"] != "missing"
                else "missing"
            )
        rows.append(
            [
                name,
                _rate(block["m1_no_evidence_on_retrieve_rows"]),
                _rate(block["m2_evidence_on_skip_rows"]),
                f"KB {holdout['kb_added_per_100_turns']:+}, local {holdout['local_added_per_100_turns']:+} ({m3['status']})",
                _p95(block),
                cost,
                state,
            ]
        )
    return rows


ARM_HEADER = ["Arm", "M1 (retrieve rows, no evidence)", "M2 (skip rows, evidence)", "M3 searches added per 100 turns", "M4 added p95 wait ms", "M5 per 1,000 turns", "Pass rule"]


def _pair_rows(pairs: Mapping[str, Any]) -> list[list[str]]:
    rows = []
    for key, value in pairs.items():
        if key == "note":
            continue
        first, second = key.split("_vs_")
        if "reason" in value:
            rows.append([f"{first} vs {second}", f"{value['status']}: {value['reason']}", "", "", "", ""])
            continue
        for family, name in FAMILY_NAMES.items():
            cell = value[family]
            rows.append(
                [
                    f"{first} vs {second}",
                    name,
                    str(cell["rows"]),
                    f"{cell['first_bad_second_ok']} / {cell['first_ok_second_bad']}",
                    f"{cell['p_value']:.4f}",
                    value["status"],
                ]
            )
    return rows


def _category_rows(reading: Mapping[str, Any]) -> list[list[str]]:
    arms = [a for a in ARM_NAMES if reading["arms"][a]["available"]]
    categories = sorted({c for a in arms for c in reading["arms"][a]["by_category"]})
    rows = []
    for category in categories:
        row = [category]
        for arm in arms:
            cell = reading["arms"][arm]["by_category"].get(category)
            if cell is None:
                row.append("")
                continue
            parts = []
            if cell["m1"]["denominator"]:
                parts.append("M1 " + format_ci(cell["m1"]))
            if cell["m2"]["denominator"]:
                parts.append("M2 " + format_ci(cell["m2"]))
            row.append("; ".join(parts))
        rows.append(row)
    return [["Category", *[ARM_NAMES[a] for a in arms]], *rows]


def format_report(result: Mapping[str, Any]) -> str:
    """Markdown report: banners, split, T, then one section per Laya source and reading."""
    plan = result["prereg"]["plan"]
    kb = result["kb_file"]
    out = ["# Head-to-head routing comparison", ""]
    if kb.get("synthetic_test_fixture"):
        out += ["**SYNTHETIC TEST DATA. The KB-score file is a test fixture and this is not a result.**", ""]
    out += [
        f"Plan `{plan['path']}`, sha256 `{plan['sha256']}`, commit `{plan['commit']}`, "
        f"constants match code: {plan['constants_match_code']}.",
        "",
        "All figures are on the holdout half. Calibration rows only choose T. Labels: "
        "measured, bound, missing. No full comparison is claimed until a complete KB-score "
        "file and an all-rows Laya file exist.",
        "",
    ]
    split = result["split"]
    out += _table(
        ["Half", "Rows", "retrieve", "skip", "Laya eligible"],
        [[part, str(v["rows"]), str(v["retrieve"]), str(v["skip"]), str(v["laya_eligible"])] for part, v in split.items()],
    )
    out += [""]
    if not kb["present"]:
        out += ["KB-score file: missing. Arms C and D are `missing`; arms A and B use a search-only proxy (`bound`).", ""]
    else:
        state = "complete" if kb["complete"] else f"partial ({kb['rows_in_file']} of {kb['ids_expected']} ids), KB figures `missing`"
        out += [f"KB-score file: {state}; failed calls {kb['failed_calls']}, empty results {kb['empty_results']}.", ""]
    for name, value in result["calibration"].get("T_D", {}).items():
        out += [f"T_D for `{name}` (calibration rows): {_threshold_text(value)}", ""]
    if "T_C" in result["calibration"]:
        out += [f"T_C (calibration rows): {_threshold_text(result['calibration']['T_C'])}", ""]
    rules = result["skip_rules_arm_c"]
    out += [
        f"Arm C skip rules over all {rules['rows']} rows: {rules['skipped_by_c']} skipped "
        f"(first rule that fires: {rules['first_rule_that_fires']}).",
        "",
    ]
    for key, entry in result["sources"].items():
        title = "No Laya source (arms A and C)" if key == NO_LAYA else f"Laya source `{key}` ({entry['origin']})"
        out += [f"## {title}", ""]
        if key != NO_LAYA:
            cov = entry["coverage"]
            out += [
                f"{entry['description']}. Cutoffs {entry['cutoffs']}. Eligible rows {cov['eligible_rows']}, "
                f"with a decision {cov['eligible_rows_with_decision']}.",
                "",
            ]
        for mode, reading in entry["readings"].items():
            out += [f"### Reading `{mode}`: {reading['rows']['description']} ({reading['rows']['holdout_rows']} holdout rows)", ""]
            out += _table(ARM_HEADER, _arm_rows(reading, entry["pass_rule"])) + [""]
            if mode in ("floor", "all"):
                category = _category_rows(reading)
                out += ["Per category (holdout):", "", *_table(category[0], category[1:]), ""]
                out += [f"Exact McNemar tests (first-only bad / second-only bad). {PAIRED_NOTE}", ""]
                out += _table(["Pair", "Family", "Rows", "Discordant", "p", "Status"], _pair_rows(reading["pairs"])) + [""]
        selection = entry["selection"]
        out += [f"Selection: {selection['statement']}", ""]
    return "\n".join(out).rstrip() + "\n"


def _threshold_text(info: Mapping[str, Any]) -> str:
    if not info["feasible"]:
        return "no feasible T (the arm fails)"
    threshold = info["threshold"]
    value = "+inf (KB evidence never injected)" if threshold["infinite"] else str(threshold["value"])
    return f"{value}; calibration M1 {info['calibration_m1']}, M2 {info['calibration_m2']}"
