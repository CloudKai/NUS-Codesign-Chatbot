"""Pre-registered rules of the head-to-head routing evaluation, written once.

Everything here is fixed by ``.agents/tasks/headtohead-prereg/plan.md`` (committed
before any evaluation code). The split function, the pass thresholds, the threshold
``T`` selection, the pass rule and the tie-break live in this module and nowhere else.
``PREREG_CONSTANTS`` is compared with the machine-readable block in the plan by a test
and by ``compare_routing_arms`` before it computes anything. No model, no network.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
import subprocess
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from fractions import Fraction
from pathlib import Path
from typing import Any

from scripts.evals.lib.paths import PROJECT_ROOT

PLAN_PATH = PROJECT_ROOT / ".agents" / "tasks" / "headtohead-prereg" / "plan.md"

M1_MAX = 0.15
M2_MAX = 0.10
ADDED_P95_WAIT_MS_MAX = 1000
CALIBRATION_M2_TARGET = 0.10
MCNEMAR_ALPHA = 0.05
SMALL_N = 30
VERY_SMALL_N = 10
COMPLEXITY_ORDER = ("A", "C", "B", "D")
LAYA_CUTOFFS = {
    "multilingual": 0.8,
    "learn_continuing": 0.8563768,
    "learn_first_turn": 0.6455846,
}
KB_CANDIDATES = 12
KB_MAX_RESULTS = 4
KB_PRICE_USD_PER_1000_SEARCHES = 1.0
GATE_MESSAGE_COUNT = 295

CALIBRATION = "calibration"
HOLDOUT = "holdout"

PASS = "pass"
FAIL = "fail"
UNDETERMINED = "cannot be determined yet"

# The same values as the ```json prereg-constants block in plan.md.
PREREG_CONSTANTS: dict[str, Any] = {
    "split": {
        "hash": "sha256",
        "input": "row id, utf-8",
        "calibration_if": "int(hexdigest, 16) % 2 == 0",
        "holdout_otherwise": True,
    },
    "m1_max": M1_MAX,
    "m2_max": M2_MAX,
    "added_p95_wait_ms_max": ADDED_P95_WAIT_MS_MAX,
    "calibration_m2_target": CALIBRATION_M2_TARGET,
    "mcnemar_alpha": MCNEMAR_ALPHA,
    "small_n": SMALL_N,
    "very_small_n": VERY_SMALL_N,
    "complexity_order": list(COMPLEXITY_ORDER),
    "laya_cutoffs": dict(LAYA_CUTOFFS),
    "kb": {
        "candidates": KB_CANDIDATES,
        "max_results": KB_MAX_RESULTS,
        "price_usd_per_1000_searches": KB_PRICE_USD_PER_1000_SEARCHES,
    },
    "gate_message_count": GATE_MESSAGE_COUNT,
}

_BLOCK = re.compile(r"```json prereg-constants\s*\n(.*?)\n```", re.DOTALL)


def split_of(row_id: str) -> str:
    """Return ``"calibration"`` or ``"holdout"`` for a row id (the one split rule).

    ``int(sha256(id utf-8).hexdigest(), 16) % 2 == 0`` is calibration, otherwise
    holdout. No salt, no re-roll, no stratification.
    """
    digest = int(hashlib.sha256(str(row_id).encode("utf-8")).hexdigest(), 16)
    return CALIBRATION if digest % 2 == 0 else HOLDOUT


def parse_constants_block(plan_text: str) -> dict[str, Any]:
    """Return the JSON object in the plan's ``prereg-constants`` block.

    Raises ``ValueError`` when the block is missing or is not valid JSON.
    """
    found = _BLOCK.search(plan_text)
    if found is None:
        raise ValueError("plan has no prereg-constants block")
    return json.loads(found.group(1))


def plan_record(path: Path = PLAN_PATH) -> dict[str, Any]:
    """Return the plan's sha256, last commit and whether its constants match the code.

    Raises ``FileNotFoundError`` when the plan is missing and ``ValueError`` when its
    constants block is absent. The commit is ``None`` when git cannot say (local
    subprocess only, never raises).
    """
    data = path.read_bytes()
    constants = parse_constants_block(data.decode("utf-8"))
    commit: str | None
    try:
        done = subprocess.run(
            ["git", "log", "-1", "--format=%H", "--", str(path)],
            cwd=PROJECT_ROOT,
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
        commit = done.stdout.strip() or None if done.returncode == 0 else None
    except (OSError, subprocess.SubprocessError):
        commit = None
    return {
        "path": str(path.relative_to(PROJECT_ROOT)) if path.is_relative_to(PROJECT_ROOT) else str(path),
        "sha256": hashlib.sha256(data).hexdigest(),
        "commit": commit,
        "constants_match_code": constants == PREREG_CONSTANTS,
    }


# ------------------------------------------------------------------ evidence injected


@dataclass(frozen=True)
class InjectionRow:
    """What one arm did on one row, in the terms ``T`` selection needs.

    ``kb_ok`` is True when the Knowledge Base call was answered with at least one
    validated result. ``top_score`` is the top validated score (``None`` when none).
    ``kb_ok`` with no ``top_score`` is the search-only proxy used when no KB file
    exists: it counts as a hit only at ``threshold == -inf``.
    """

    expected: str
    local: bool
    kb_search: bool
    kb_ok: bool
    top_score: float | None


def injected(row: InjectionRow, threshold: float) -> bool:
    """Whether the student receives evidence: a local search, or a KB hit at ``threshold``."""
    if row.local:
        return True
    if not (row.kb_search and row.kb_ok):
        return False
    if threshold == -math.inf:
        return True
    return row.top_score is not None and row.top_score >= threshold


def _counts(rows: Sequence[InjectionRow], threshold: float) -> tuple[int, int, int, int]:
    """Return (retrieve rows without evidence, retrieve rows, skip rows with evidence, skip rows)."""
    retrieve = [r for r in rows if r.expected == "retrieve"]
    skip = [r for r in rows if r.expected == "skip"]
    return (
        sum(1 for r in retrieve if not injected(r, threshold)),
        len(retrieve),
        sum(1 for r in skip if injected(r, threshold)),
        len(skip),
    )


def _within(numerator: int, denominator: int, limit: float) -> bool:
    """Exact ``numerator / denominator <= limit`` (an empty denominator counts as 0)."""
    if denominator == 0:
        return True
    return Fraction(numerator, denominator) <= Fraction(str(limit))


def choose_threshold(rows: Sequence[InjectionRow]) -> dict[str, Any]:
    """Choose ``T`` on calibration rows by the pre-registered rule.

    ``rows`` must be calibration rows only (the caller filters with ``split_of``).
    Candidates are the distinct top scores of rows where the arm searched the KB and
    got at least one validated result, plus ``+inf``. Among candidates whose
    calibration M2 point estimate is at most ``CALIBRATION_M2_TARGET``, take the lowest
    M1; ties go to the lower M2, then the higher ``T``. When none qualifies the result
    has ``feasible`` False and ``threshold`` None (the arm fails).
    """
    scores = {
        float(r.top_score)
        for r in rows
        if r.kb_search and r.kb_ok and r.top_score is not None
    }
    candidates = sorted(scores) + [math.inf]
    best: tuple[Fraction, Fraction, float] | None = None
    chosen: dict[str, Any] | None = None
    for threshold in candidates:
        m1_n, m1_d, m2_n, m2_d = _counts(rows, threshold)
        if not _within(m2_n, m2_d, CALIBRATION_M2_TARGET):
            continue
        key = (
            Fraction(m1_n, m1_d) if m1_d else Fraction(0),
            Fraction(m2_n, m2_d) if m2_d else Fraction(0),
            -threshold,
        )
        if best is None or key < best:
            best = key
            chosen = {
                "feasible": True,
                "threshold": threshold,
                "calibration_m1": [m1_n, m1_d],
                "calibration_m2": [m2_n, m2_d],
            }
    base = {"candidates": len(candidates), "calibration_rows": len(rows)}
    if chosen is None:
        return {**base, "feasible": False, "threshold": None, "calibration_m1": None, "calibration_m2": None}
    return {**base, **chosen}


def threshold_for_json(value: float | None) -> dict[str, Any]:
    """JSON-safe form of a threshold: ``+inf`` has no JSON number, so it is flagged."""
    if value is None:
        return {"value": None, "infinite": False}
    if math.isinf(value):
        return {"value": None, "infinite": True}
    return {"value": value, "infinite": False}


# ------------------------------------------------------------------------- pass rule


def criteria(
    m1: tuple[int, int] | None, m2: tuple[int, int] | None, p95_wait_ms: float | None
) -> dict[str, bool | None]:
    """Check the three pass criteria. ``None`` means the input is unknown."""
    return {
        "m1": None if m1 is None else _within(m1[0], m1[1], M1_MAX),
        "m2": None if m2 is None else _within(m2[0], m2[1], M2_MAX),
        "added_p95_wait": None if p95_wait_ms is None else p95_wait_ms <= ADDED_P95_WAIT_MS_MAX,
    }


def pass_state(
    *,
    pessimistic: Mapping[str, Any] | None,
    optimistic: Mapping[str, Any] | None,
    no_feasible_threshold: bool = False,
    data_complete: bool = True,
) -> dict[str, Any]:
    """Return ``{"state", "failed_criteria", "criteria_pessimistic", "criteria_optimistic"}``.

    ``pessimistic`` and ``optimistic`` are dicts with ``m1`` and ``m2`` as
    ``(numerator, denominator)`` and ``p95_wait_ms`` (a number or ``None``). Pessimistic
    is the worst reading of every unknown (M1 at the floor, M2 at the ceiling, wait at
    the upper imputation), optimistic the best. ``None`` for a whole reading means the
    data to form it is missing.

    * ``fail``: no feasible ``T``, or a criterion fails even under the optimistic reading.
    * ``pass``: ``data_complete`` and every criterion holds under the pessimistic reading.
    * ``cannot be determined yet``: everything else, including any missing data.
    """

    def check(reading: Mapping[str, Any] | None) -> dict[str, bool | None] | None:
        if reading is None:
            return None
        return criteria(reading.get("m1"), reading.get("m2"), reading.get("p95_wait_ms"))

    pessimistic_checks = check(pessimistic)
    optimistic_checks = check(optimistic)
    failed = (
        sorted(name for name, ok in optimistic_checks.items() if ok is False)
        if optimistic_checks
        else []
    )
    if no_feasible_threshold:
        state = FAIL
        failed = sorted({*failed, "no_feasible_threshold"})
    elif failed:
        state = FAIL
    elif (
        data_complete
        and pessimistic_checks is not None
        and all(ok is True for ok in pessimistic_checks.values())
    ):
        state = PASS
    else:
        state = UNDETERMINED
    return {
        "state": state,
        "failed_criteria": failed,
        "criteria_pessimistic": pessimistic_checks,
        "criteria_optimistic": optimistic_checks,
    }


def select_champion(
    passing: Sequence[str],
    m1_rate: Mapping[str, float],
    p_value: Callable[[str, str], float],
) -> tuple[str | None, list[dict[str, Any]]]:
    """Walk the passing arms in ``COMPLEXITY_ORDER`` and return ``(champion, trail)``.

    The first passing arm is the champion. A later passing arm replaces the champion
    only when its holdout M1 is lower and ``p_value(champion, challenger)`` (the exact
    McNemar test on the retrieve rows) is below ``MCNEMAR_ALPHA``. ``trail`` records
    each comparison. No passing arm gives ``(None, [])``.
    """
    ordered = [arm for arm in COMPLEXITY_ORDER if arm in set(passing)]
    if not ordered:
        return None, []
    champion = ordered[0]
    trail: list[dict[str, Any]] = []
    for challenger in ordered[1:]:
        lower = m1_rate[challenger] < m1_rate[champion]
        p = p_value(champion, challenger)
        replaces = lower and p < MCNEMAR_ALPHA
        trail.append(
            {
                "champion": champion,
                "challenger": challenger,
                "challenger_m1_lower": lower,
                "p_value": p,
                "replaces": replaces,
            }
        )
        if replaces:
            champion = challenger
    return champion, trail
