"""Metrics M1 to M5, paired tests, pass rule and selection for the four routing arms.

Pure computation over rows already built by ``routing_arms``, the stored Laya
sources, and an optional KB-score file. Every rule is the one fixed in
``.agents/tasks/headtohead-prereg/plan.md`` and implemented once in ``prereg``.
No backend import, no network, no model.

Readings. A Laya source that misses decisions for some eligible rows is read three
ways (``floor``, ``ceiling``, ``scored_only``, see ``laya_sources.MODES``). With no Laya
source the single reading is ``all``. Only holdout rows feed a reported figure.
Calibration rows feed ``T`` and nothing else.

Status labels. Each figure says ``measured``, ``bound``, ``missing`` or, for a file
made for tests, ``synthetic_test_data`` (never a result).
"""

from __future__ import annotations

import math
from collections import defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from scripts.evals.lib import prereg
from scripts.evals.lib.intervals import rate_ci
from scripts.evals.lib.kb_scores import KbScores
from scripts.evals.lib.laya_sources import MODES, LayaSource, promotion
from scripts.evals.lib.paired_stats import paired_outcomes
from scripts.evals.lib.prepared_rows import PreparedRow
from scripts.evals.lib.routing_arms import ARMS, LAYA_ARMS, RowScopes, search_flags, skip_attribution

MEASURED = "measured"
BOUND = "bound"
MISSING = "missing"
SYNTHETIC = "synthetic_test_data"
NO_FEASIBLE_T = "no_feasible_threshold"

PAIRS = (("A", "B"), ("A", "C"), ("B", "C"), ("C", "D"))
FAMILIES = ("retrieve_rows_m1", "skip_rows_m2", "all_rows_mistakes")
PAIRED_NOTE = (
    "Arms B and D only add searches to arm A, so 'A is never better than B' on M1 is built "
    "in. For B this holds on the retrieve rows. For D it holds for searches only, because "
    "T can withhold evidence that arm A would inject. A significant B-over-A result on the "
    "retrieve rows follows from construction and is not evidence of Laya quality by itself. "
    "The skip-row (M2) and all-row families carry the information. No multiplicity "
    "correction; the p-values are descriptive."
)
NO_LAYA = "no_laya"


@dataclass(frozen=True)
class ScenarioRow:
    """One gate row inside one reading: its scopes and the Laya decision for it."""

    scopes: RowScopes
    promoted: bool
    unscored: bool


@dataclass
class ArmRun:
    """One arm over the rows of one reading: search flags and injection inputs."""

    arm: str
    rows: list[ScenarioRow]
    injection: dict[str, prereg.InjectionRow]
    kb_search: dict[str, bool]
    local_search: dict[str, bool]
    threshold: float

    def evidence(self, row_id: str) -> bool:
        return prereg.injected(self.injection[row_id], self.threshold)

    def bad(self, row_id: str) -> bool:
        """The mistake outcome: no evidence on a retrieve row, evidence on a skip row."""
        row = self.injection[row_id]
        return (not self.evidence(row_id)) if row.expected == "retrieve" else self.evidence(row_id)


# --------------------------------------------------------------------- small helpers


def nearest_rank(values: Sequence[float], percent: int) -> float | None:
    """Nearest-rank percentile rounded to two places, or ``None`` when empty."""
    if not values:
        return None
    ordered = sorted(values)
    rank = max(1, (percent * len(ordered) + 99) // 100)
    return round(ordered[rank - 1], 2)


def summary_ms(values: Sequence[float]) -> dict[str, Any]:
    """``{n, p50, p95}`` of a list of milliseconds (nearest rank)."""
    return {"n": len(values), "p50": nearest_rank(values, 50), "p95": nearest_rank(values, 95)}


def counts(record: Mapping[str, Any]) -> tuple[int, int]:
    """``(numerator, denominator)`` of a rate record."""
    return int(record["numerator"]), int(record["denominator"])


def make_scenario(
    scopes: Sequence[RowScopes],
    prepared: Mapping[str, PreparedRow],
    source: LayaSource | None,
    mode: str,
) -> list[ScenarioRow]:
    """Rows of one reading. ``scored_only`` leaves out eligible rows with no decision."""
    rows = []
    for row in scopes:
        promoted, unscored = promotion(prepared[row.id], source, mode)
        if unscored and mode == "scored_only":
            continue
        rows.append(ScenarioRow(row, promoted, unscored))
    return rows


def build_run(
    arm: str,
    rows: Sequence[ScenarioRow],
    kb: KbScores | None,
    *,
    threshold: float,
    proxy: str = "always",
) -> ArmRun:
    """Build an arm's run. Without ``kb`` the Knowledge Base is a proxy.

    ``proxy`` is ``always`` (every KB search yields evidence) or ``never`` (none does).
    The proxy only bounds M1 and M2; it is never a measurement.
    """
    injection: dict[str, prereg.InjectionRow] = {}
    kb_search: dict[str, bool] = {}
    local_search: dict[str, bool] = {}
    for item in rows:
        row_id = item.scopes.id
        kb_flag, local_flag = search_flags(arm, item.scopes, item.promoted)
        if kb is not None:
            hit = kb.rows[row_id]
            kb_ok, top = hit.ok, hit.top_score
        else:
            kb_ok, top = proxy == "always", None
        injection[row_id] = prereg.InjectionRow(
            expected=item.scopes.expected,
            local=local_flag,
            kb_search=kb_flag,
            kb_ok=kb_ok,
            top_score=top,
        )
        kb_search[row_id] = kb_flag
        local_search[row_id] = local_flag
    return ArmRun(arm, list(rows), injection, kb_search, local_search, threshold)


def subset(run: ArmRun, ids: set[str]) -> list[str]:
    """Row ids of ``run`` that are in ``ids``, in row order."""
    return [item.scopes.id for item in run.rows if item.scopes.id in ids]


def m1_m2(run: ArmRun, ids: Sequence[str]) -> tuple[dict[str, Any], dict[str, Any]]:
    """M1 and M2 as Wilson-interval records over ``ids``."""
    retrieve = [i for i in ids if run.injection[i].expected == "retrieve"]
    skip = [i for i in ids if run.injection[i].expected == "skip"]
    return (
        rate_ci(sum(1 for i in retrieve if not run.evidence(i)), len(retrieve)),
        rate_ci(sum(1 for i in skip if run.evidence(i)), len(skip)),
    )


def by_category(run: ArmRun, ids: Sequence[str], categories: Mapping[str, str]) -> dict[str, Any]:
    """M1 and M2 per category over ``ids`` (a category with no such rows shows n/a)."""
    grouped: dict[str, list[str]] = defaultdict(list)
    for row_id in ids:
        grouped[categories[row_id]].append(row_id)
    table = {}
    for category in sorted(grouped):
        m1, m2 = m1_m2(run, grouped[category])
        table[category] = {"rows": len(grouped[category]), "m1": m1, "m2": m2}
    return table


# ---------------------------------------------------------------------- M3, M4, M5


def searches_added(run: ArmRun, base: ArmRun, ids: Sequence[str]) -> dict[str, Any]:
    """M3 over ``ids``: searches added per 100 turns versus arm A, KB and local apart."""
    turns = len(ids)
    kb_arm = sum(1 for i in ids if run.kb_search[i])
    kb_base = sum(1 for i in ids if base.kb_search[i])
    local_arm = sum(1 for i in ids if run.local_search[i])
    local_base = sum(1 for i in ids if base.local_search[i])

    def per_100(added: int) -> float | None:
        return round(100 * added / turns, 2) if turns else None

    return {
        "turns": turns,
        "kb_searches": kb_arm,
        "kb_searches_arm_a": kb_base,
        "kb_added_per_100_turns": per_100(kb_arm - kb_base),
        "local_searches": local_arm,
        "local_searches_arm_a": local_base,
        "local_added_per_100_turns": per_100(local_arm - local_base),
    }


def laya_ms_for(row: ScenarioRow, source: LayaSource | None, imputation: str, ceiling_ms: float) -> float:
    """Laya inference ms for one row of arm B or D: stored, else the imputation."""
    if source is None or not row.scopes.eligible:
        return 0.0
    stored = source.ms.get(row.scopes.id)
    if stored is not None:
        return float(stored)
    return ceiling_ms if imputation == "upper" else 0.0


def source_ms_values(source: LayaSource | None, rows: Sequence[RowScopes]) -> list[float]:
    """Stored Laya ms for the eligible rows that have one."""
    if source is None:
        return []
    return [
        float(source.ms[r.id]) for r in rows if r.eligible and source.ms.get(r.id) is not None
    ]


def added_wait(
    run: ArmRun,
    base: ArmRun,
    ids: Sequence[str],
    *,
    source: LayaSource | None,
    kb: KbScores | None,
    imputation: str,
    include_kb: bool,
) -> list[float]:
    """Added wait per turn versus arm A, one value per row of ``ids`` (ms, signed).

    ``laya_ms + kb_ms(arm) - kb_ms(A)``. Laya ms count on eligible rows of B and D only.
    ``include_kb`` False leaves the Knowledge Base out (used with no KB file).
    """
    by_id = {item.scopes.id: item for item in run.rows}
    ceiling = max((float(v) for v in (source.ms.values() if source else []) if v is not None), default=0.0)
    values = []
    for row_id in ids:
        wait = 0.0
        if run.arm in LAYA_ARMS:
            wait += laya_ms_for(by_id[row_id], source, imputation, ceiling)
        if include_kb and kb is not None:
            elapsed = kb.rows[row_id].elapsed_ms
            wait += (elapsed if run.kb_search[row_id] else 0.0) - (elapsed if base.kb_search[row_id] else 0.0)
        values.append(wait)
    return values


def laya_memory(source: LayaSource | None) -> dict[str, Any]:
    """Host memory for Laya (not dollars). ``missing`` unless an all-rows file has it."""
    if source is None:
        return {"status": MISSING, "note": "no Laya source"}
    peak = source.memory.get("peak_rss_mib") if source.memory else None
    if peak is None:
        return {"status": MISSING, "note": "no memory figure in the stored decisions"}
    return {
        "status": MEASURED if source.host_noted else BOUND,
        "peak_rss_mib": peak,
        "load_delta_rss_mib": source.memory.get("load_delta_rss_mib"),
        "after_load_rss_mib": source.memory.get("after_load_rss_mib"),
        "host_note": dict(source.host_note) if source.host_note else None,
    }


# ------------------------------------------------------------------------- statuses


def kb_figure_status(
    arm: str,
    *,
    kb: KbScores | None,
    source: LayaSource | None,
    laya_exact: bool,
) -> str:
    """Status of a KB-dependent figure (M1, M2, pairs) for one arm."""
    if arm in LAYA_ARMS and source is None:
        return MISSING
    if kb is None:
        return MISSING if arm in ("C", "D") else BOUND
    if kb_synthetic(kb):
        return SYNTHETIC
    if arm in LAYA_ARMS and not laya_exact:
        return BOUND
    return MEASURED


def kb_synthetic(kb: KbScores) -> bool:
    return kb.synthetic_test_fixture


def worst_status(*statuses: str) -> str:
    """Combine labels: synthetic beats missing beats bound beats measured."""
    for label in (SYNTHETIC, MISSING, BOUND):
        if label in statuses:
            return label
    return MEASURED


# --------------------------------------------------------------------- T selection


def injection_rows_for_calibration(
    arm: str, rows: Sequence[ScenarioRow], kb: KbScores, calibration_ids: set[str]
) -> list[prereg.InjectionRow]:
    """Arm inputs for ``choose_threshold``: calibration rows only."""
    run = build_run(arm, [r for r in rows if r.scopes.id in calibration_ids], kb, threshold=-math.inf)
    return [run.injection[item.scopes.id] for item in run.rows]


def calibration_report(
    arm: str, rows: Sequence[ScenarioRow], kb: KbScores, calibration_ids: set[str]
) -> dict[str, Any]:
    """Choose ``T`` for arm C or D on calibration rows and describe the choice."""
    chosen = prereg.choose_threshold(injection_rows_for_calibration(arm, rows, kb, calibration_ids))
    return {
        "arm": arm,
        "chosen_on": "calibration rows only",
        "feasible": chosen["feasible"],
        "threshold": prereg.threshold_for_json(chosen["threshold"]),
        "candidates": chosen["candidates"],
        "calibration_rows": chosen["calibration_rows"],
        "calibration_m1": chosen["calibration_m1"],
        "calibration_m2": chosen["calibration_m2"],
        "_python_threshold": chosen["threshold"],
    }


# ---------------------------------------------------------------- reading evaluation


@dataclass
class Reading:
    """One reading of one source: arm runs, serialisable blocks and pass inputs."""

    name: str
    rows: list[ScenarioRow]
    holdout_ids: list[str]
    runs: dict[str, ArmRun]
    block: dict[str, Any]
    wait_p95: dict[str, dict[str, float | None]]


def _arm_block(
    arm: str,
    run: ArmRun,
    base: ArmRun,
    *,
    holdout: list[str],
    all_ids: list[str],
    categories: Mapping[str, str],
    source: LayaSource | None,
    kb: KbScores | None,
    laya_exact: bool,
    threshold_info: Mapping[str, Any] | None,
) -> tuple[dict[str, Any], dict[str, float | None]]:
    """The metric block for one arm in one reading, and its lower/upper p95 wait."""
    status = kb_figure_status(arm, kb=kb, source=source, laya_exact=laya_exact)
    m1, m2 = m1_m2(run, holdout)
    search_status = MEASURED if arm in ("A", "C") or (source is not None and laya_exact) else BOUND
    if arm in LAYA_ARMS and source is None:
        search_status = MISSING
    synthetic = kb is not None and kb_synthetic(kb)
    wait: dict[str, Any] = {}
    p95: dict[str, float | None] = {}
    for imputation in ("lower", "upper"):
        laya_only = added_wait(run, base, holdout, source=source, kb=None, imputation=imputation, include_kb=False)
        combined = (
            added_wait(run, base, holdout, source=source, kb=kb, imputation=imputation, include_kb=True)
            if kb is not None
            else None
        )
        wait[imputation] = {
            "laya_only": summary_ms(laya_only),
            "combined": summary_ms(combined) if combined is not None else None,
        }
        used = combined if combined is not None else laya_only
        p95[imputation] = nearest_rank(used, 95)
    laya_status = MEASURED if arm not in LAYA_ARMS else (
        MISSING if source is None else (MEASURED if source.host_noted else BOUND)
    )
    if arm == "A":
        wait_status = MEASURED
    elif arm in LAYA_ARMS and source is None:
        wait_status = MISSING
    elif kb is None:
        wait_status = MISSING
    else:
        wait_status = worst_status(laya_status, SYNTHETIC if synthetic else MEASURED)
    kb_searches = sum(1 for i in holdout if run.kb_search[i])
    per_1000 = round(1000 * kb_searches / len(holdout), 2) if holdout else None
    block = {
        "available": True,
        "threshold": None if threshold_info is None else threshold_info["threshold"],
        "m1_no_evidence_on_retrieve_rows": {"status": status, **m1},
        "m2_evidence_on_skip_rows": {"status": status, **m2},
        "m3_searches_added_vs_a": {
            "status": search_status,
            "holdout": searches_added(run, base, holdout),
            "all_rows_descriptive": searches_added(run, base, all_ids),
        },
        "m4_added_wait_ms": {
            "status": wait_status,
            "local_search_time": MISSING,
            "imputation": "lower = 0 ms and upper = the source's largest stored Laya ms, for eligible rows with no stored ms",
            "lower": wait["lower"],
            "upper": wait["upper"],
        },
        "m5_cost_per_1000_turns": {
            "kb_status": search_status,
            "kb_searches_per_1000_turns": per_1000,
            "kb_usd_per_1000_turns": (
                None if per_1000 is None else round(per_1000 * prereg.KB_PRICE_USD_PER_1000_SEARCHES / 1000, 4)
            ),
            "kb_price_usd_per_1000_searches": prereg.KB_PRICE_USD_PER_1000_SEARCHES,
            "price_note": "user-supplied price, not checked against an AWS page; other costs excluded",
            "laya_host_memory": laya_memory(source) if arm in LAYA_ARMS else None,
        },
        "by_category": {
            name: {
                "rows": cell["rows"],
                "m1": {"status": status, **cell["m1"]},
                "m2": {"status": status, **cell["m2"]},
            }
            for name, cell in by_category(run, holdout, categories).items()
        },
    }
    return block, p95


def _unavailable(reason: str, status: str = MISSING) -> dict[str, Any]:
    return {"available": False, "status": status, "reason": reason}


def evaluate_reading(
    name: str,
    rows: list[ScenarioRow],
    *,
    source: LayaSource | None,
    kb: KbScores | None,
    kb_file_present: bool,
    thresholds: Mapping[str, Mapping[str, Any]],
    split: Mapping[str, str],
    categories: Mapping[str, str],
    laya_exact: bool,
) -> Reading:
    """Run all four arms over the holdout rows of one reading.

    ``thresholds`` maps ``C`` and ``D`` to their frozen ``T`` records (from
    ``calibration_report``), or is empty when there is no complete KB file.
    """
    holdout_ids = [r.scopes.id for r in rows if split[r.scopes.id] == prereg.HOLDOUT]
    all_ids = [r.scopes.id for r in rows]
    runs: dict[str, ArmRun] = {}
    blocks: dict[str, Any] = {}
    wait_p95: dict[str, dict[str, float | None]] = {}
    base = build_run("A", rows, kb, threshold=-math.inf)
    for arm in ARMS:
        if arm in LAYA_ARMS and source is None:
            blocks[arm] = _unavailable("no Laya source")
            continue
        info = thresholds.get(arm)
        if arm in ("C", "D"):
            if kb is None:
                reason = (
                    "KB-score file is partial, so no T can be chosen" if kb_file_present
                    else "no KB-score file"
                )
                blocks[arm] = _unavailable(reason)
                continue
            if info is None or not info["feasible"]:
                blocks[arm] = _unavailable("no feasible T on the calibration rows", NO_FEASIBLE_T)
                continue
            threshold = float(info["_python_threshold"])
        else:
            threshold = -math.inf
        run = base if arm == "A" else build_run(arm, rows, kb, threshold=threshold)
        runs[arm] = run
        blocks[arm], wait_p95[arm] = _arm_block(
            arm, run, base,
            holdout=holdout_ids, all_ids=all_ids, categories=categories,
            source=source, kb=kb, laya_exact=laya_exact,
            threshold_info=info if arm in ("C", "D") else None,
        )
    return Reading(name, rows, holdout_ids, runs, {"arms": blocks}, wait_p95)


def pair_blocks(reading: Reading, kb: KbScores | None, source: LayaSource | None, laya_exact: bool) -> dict[str, Any]:
    """Exact McNemar tests on the holdout rows for A-B, A-C, B-C and C-D."""
    out: dict[str, Any] = {}
    by_id = {item.scopes.id: item for item in reading.rows}
    for first, second in PAIRS:
        key = f"{first}_vs_{second}"
        run_a, run_b = reading.runs.get(first), reading.runs.get(second)
        if run_a is None or run_b is None:
            missing = [arm for arm, run in ((first, run_a), (second, run_b)) if run is None]
            out[key] = {"status": MISSING, "reason": f"no data for arm {', '.join(missing)}"}
            continue
        status = worst_status(
            *[
                kb_figure_status(arm, kb=kb, source=source, laya_exact=laya_exact)
                for arm in (first, second)
            ]
        )
        families = {}
        ids = reading.holdout_ids
        selectors = {
            "retrieve_rows_m1": [i for i in ids if by_id[i].scopes.expected == "retrieve"],
            "skip_rows_m2": [i for i in ids if by_id[i].scopes.expected == "skip"],
            "all_rows_mistakes": list(ids),
        }
        first_bad = {i: run_a.bad(i) for i in ids}
        second_bad = {i: run_b.bad(i) for i in ids}
        for family, family_ids in selectors.items():
            families[family] = paired_outcomes(first_bad, second_bad, family_ids)
        out[key] = {"status": status, "outcome": "bad = the mistake outcome of each family", **families}
    out["note"] = PAIRED_NOTE
    return out


# ------------------------------------------------------------------- pass and select


def _reading_counts(reading: Reading, arm: str) -> tuple[tuple[int, int], tuple[int, int]] | None:
    run = reading.runs.get(arm)
    if run is None:
        return None
    m1, m2 = m1_m2(run, reading.holdout_ids)
    return counts(m1), counts(m2)


def proxy_counts(
    arm: str, rows: Sequence[ScenarioRow], split: Mapping[str, str], proxy: str
) -> tuple[tuple[int, int], tuple[int, int]]:
    """M1 and M2 counts with no KB file: ``always`` bounds M1, ``never`` bounds M2."""
    holdout = [r for r in rows if split[r.scopes.id] == prereg.HOLDOUT]
    run = build_run(arm, holdout, None, threshold=-math.inf, proxy=proxy)
    m1, m2 = m1_m2(run, [r.scopes.id for r in holdout])
    return counts(m1), counts(m2)


def pass_rule_for_source(
    *,
    readings: Mapping[str, Reading],
    source: LayaSource | None,
    kb: KbScores | None,
    thresholds: Mapping[str, Mapping[str, Any]],
    split: Mapping[str, str],
    laya_complete: bool,
) -> dict[str, Any]:
    """Tri-state pass result per arm for one source.

    Pessimistic reading: M1 at the floor, M2 at the ceiling, wait at the upper
    imputation. Optimistic: M1 at the ceiling, M2 at the floor, wait at the lower one.
    Without a complete KB file no pessimistic reading exists, and the optimistic M1
    assumes every KB search yields evidence while the optimistic M2 assumes none does.
    """
    floor = readings["floor" if "floor" in readings else "all"]
    ceiling = readings["ceiling" if "ceiling" in readings else "all"]
    result: dict[str, Any] = {}
    for arm in ARMS:
        if arm in LAYA_ARMS and source is None:
            result[arm] = {
                "state": prereg.UNDETERMINED,
                "failed_criteria": [],
                "reason": "no Laya source",
            }
            continue
        info = thresholds.get(arm)
        if arm in ("C", "D") and kb is not None and (info is None or not info["feasible"]):
            result[arm] = {**prereg.pass_state(pessimistic=None, optimistic=None, no_feasible_threshold=True),
                           "reason": "no feasible T on the calibration rows"}
            continue
        if kb is not None:
            f, c = _reading_counts(floor, arm), _reading_counts(ceiling, arm)
            if f is None or c is None:
                result[arm] = {"state": prereg.UNDETERMINED, "failed_criteria": [], "reason": "no arm data"}
                continue
            pess_wait = [floor.wait_p95[arm]["upper"], ceiling.wait_p95[arm]["upper"]]
            opt_wait = [floor.wait_p95[arm]["lower"], ceiling.wait_p95[arm]["lower"]]
            pessimistic = {
                "m1": f[0], "m2": c[1],
                "p95_wait_ms": None if None in pess_wait else max(pess_wait),
            }
            optimistic = {
                "m1": c[0], "m2": f[1],
                "p95_wait_ms": None if None in opt_wait else min(opt_wait),
            }
            complete = laya_complete if arm in LAYA_ARMS else True
        else:
            rows = ceiling.rows
            optimistic = {
                "m1": proxy_counts(arm, rows, split, "always")[0],
                "m2": proxy_counts(arm, rows, split, "never")[1],
                "p95_wait_ms": (
                    floor.wait_p95[arm]["lower"] if arm in floor.wait_p95 else None
                ),
            }
            pessimistic, complete = None, False
        verdict = prereg.pass_state(pessimistic=pessimistic, optimistic=optimistic, data_complete=complete)
        verdict["pessimistic"] = pessimistic
        verdict["optimistic"] = optimistic
        if kb is None:
            verdict["reason"] = "no complete KB-score file: only a bound can be checked"
        elif arm in LAYA_ARMS and not laya_complete:
            verdict["reason"] = "stored Laya decisions miss eligible rows, so pass is not reachable"
        result[arm] = verdict
    return result


def selection_for_source(
    pass_rule: Mapping[str, Any], reading: Reading
) -> dict[str, Any]:
    """Apply the tie-break to the passing arms and say what is undetermined."""
    passing = [arm for arm in prereg.COMPLEXITY_ORDER if pass_rule[arm]["state"] == prereg.PASS]
    undetermined = [arm for arm in prereg.COMPLEXITY_ORDER if pass_rule[arm]["state"] == prereg.UNDETERMINED]
    failing = {
        arm: pass_rule[arm]["failed_criteria"]
        for arm in prereg.COMPLEXITY_ORDER
        if pass_rule[arm]["state"] == prereg.FAIL
    }
    m1_rate = {}
    for arm in passing:
        m1, _ = m1_m2(reading.runs[arm], reading.holdout_ids)
        m1_rate[arm] = m1["rate"] if m1["rate"] is not None else 0.0

    def p_value(champion: str, challenger: str) -> float:
        by_id = {item.scopes.id: item for item in reading.rows}
        ids = [i for i in reading.holdout_ids if by_id[i].scopes.expected == "retrieve"]
        first = {i: reading.runs[champion].bad(i) for i in ids}
        second = {i: reading.runs[challenger].bad(i) for i in ids}
        return paired_outcomes(first, second, ids)["p_value"]

    champion, trail = prereg.select_champion(passing, m1_rate, p_value)
    provisional = bool(undetermined)
    if champion is None and not undetermined:
        statement = "No arm passes."
    elif champion is None:
        statement = "No arm has passed yet; the undetermined arms could still pass."
    elif provisional:
        statement = f"Provisional champion {champion}; arms not yet determined: {', '.join(undetermined)}."
    else:
        statement = f"Champion {champion}."
    return {
        "champion": champion,
        "passing": passing,
        "failing": failing,
        "undetermined": undetermined,
        "provisional": provisional,
        "trail": trail,
        "statement": statement,
        "full_comparison_claimed": False,
    }


# ----------------------------------------------------------------------- top level


def split_counts(scopes: Sequence[RowScopes], split: Mapping[str, str]) -> dict[str, Any]:
    """Calibration and holdout sizes by label."""
    out: dict[str, Any] = {}
    for part in (prereg.CALIBRATION, prereg.HOLDOUT):
        members = [r for r in scopes if split[r.id] == part]
        out[part] = {
            "rows": len(members),
            "retrieve": sum(1 for r in members if r.expected == "retrieve"),
            "skip": sum(1 for r in members if r.expected == "skip"),
            "laya_eligible": sum(1 for r in members if r.eligible),
        }
    return out


def coverage(source: LayaSource, scopes: Sequence[RowScopes]) -> dict[str, Any]:
    """How many eligible rows the source has a decision for."""
    eligible = [r for r in scopes if r.eligible]
    scored = [r for r in eligible if r.id in source.decisions]
    values = source_ms_values(source, scopes)
    return {
        "eligible_rows": len(eligible),
        "eligible_rows_with_decision": len(scored),
        "eligible_rows_without_decision": len(eligible) - len(scored),
        "complete": len(scored) == len(eligible),
        "laya_ms": summary_ms(values),
        "laya_ms_max": round(max(values), 2) if values else None,
    }


def kb_ms_summary(kb: KbScores | None) -> dict[str, Any] | None:
    """KB elapsed ms over the rows the live run answered (p50 and p95)."""
    if kb is None:
        return None
    answered = [r.elapsed_ms for r in kb.rows.values() if r.status != "unavailable"]
    everything = [r.elapsed_ms for r in kb.rows.values()]
    return {"answered_calls": summary_ms(answered), "all_attempts": summary_ms(everything)}


def compare(
    scopes: Sequence[RowScopes],
    prepared: Mapping[str, PreparedRow],
    sources: Sequence[LayaSource],
    kb_file: KbScores | None,
) -> dict[str, Any]:
    """Evaluate every arm on every Laya source and reading.

    ``kb_file`` is used for KB-dependent figures only when it covers every gate id;
    a partial file leaves them ``missing``. Returns the JSON-ready result (the
    command adds the plan record, the run block and the report).
    """
    split = {r.id: prereg.split_of(r.id) for r in scopes}
    categories = {r.id: r.category for r in scopes}
    calibration_ids = {i for i, part in split.items() if part == prereg.CALIBRATION}
    kb = kb_file if kb_file is not None and kb_file.complete else None
    expected_ids = [r.id for r in scopes]
    result: dict[str, Any] = {
        "rows": len(scopes),
        "split": split_counts(scopes, split),
        "skip_rules_arm_c": skip_attribution(scopes),
        "kb_file": (
            {"present": False}
            if kb_file is None
            else {"present": True, **kb_file.describe(expected_ids), "used": kb is not None}
        ),
        "kb_ms": kb_ms_summary(kb),
        "calibration": {},
        "sources": {},
    }
    base_rows = make_scenario(scopes, prepared, None, "floor")
    c_info = calibration_report("C", base_rows, kb, calibration_ids) if kb is not None else None
    if c_info is not None:
        result["calibration"]["T_C"] = {k: v for k, v in c_info.items() if k != "_python_threshold"}
    for source in [None, *sources]:
        key = NO_LAYA if source is None else source.name
        modes = ["all"] if source is None else list(MODES)
        scenarios = {
            m: make_scenario(scopes, prepared, source, "floor" if m == "all" else m) for m in modes
        }
        floor_rows = scenarios["all" if source is None else "floor"]
        laya_complete = source is None or not any(r.unscored for r in floor_rows)
        thresholds: dict[str, Mapping[str, Any]] = {}
        if c_info is not None:
            thresholds["C"] = c_info
        if kb is not None and source is not None:
            d_info = calibration_report("D", floor_rows, kb, calibration_ids)
            thresholds["D"] = d_info
            result["calibration"].setdefault("T_D", {})[key] = {
                k: v for k, v in d_info.items() if k != "_python_threshold"
            }
        readings: dict[str, Reading] = {}
        blocks: dict[str, Any] = {}
        for mode, rows in scenarios.items():
            exact = laya_complete or mode == "scored_only"
            reading = evaluate_reading(
                mode, rows, source=source, kb=kb, kb_file_present=kb_file is not None,
                thresholds=thresholds, split=split, categories=categories, laya_exact=exact,
            )
            reading.block["pairs"] = pair_blocks(reading, kb, source, exact)
            reading.block["rows"] = {
                "reading_rows": len(rows),
                "holdout_rows": len(reading.holdout_ids),
                "description": "all gate rows" if source is None else MODES[mode],
            }
            readings[mode] = reading
            blocks[mode] = reading.block
        rule = pass_rule_for_source(
            readings=readings, source=source, kb=kb, thresholds=thresholds,
            split=split, laya_complete=laya_complete,
        )
        entry: dict[str, Any] = {
            "readings": blocks,
            "pass_rule": rule,
            "selection": selection_for_source(rule, readings["all" if source is None else "floor"]),
        }
        if source is None:
            entry["description"] = "no Laya source: arms A and C only; B and D are missing"
        else:
            entry.update(
                {
                    "description": source.description,
                    "origin": source.origin,
                    "file": source.file,
                    "cutoffs": dict(source.cutoffs),
                    "host_noted": source.host_noted,
                    "coverage": coverage(source, scopes),
                    "consistency_with_gate_at_this_commit": dict(source.consistency),
                }
            )
        result["sources"][key] = entry
    return result
