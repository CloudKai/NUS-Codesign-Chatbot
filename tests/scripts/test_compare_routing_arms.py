"""Check the head-to-head comparison: split, T selection, statistics, arms, statuses.

Every KB-score file here is SYNTHETIC TEST DATA built by ``synthetic_kb``. It carries
``synthetic_test_fixture: true`` so a report never presents it as a result. Laya
decisions in the full-run tests are stub values. No AWS, no weights, no model.
"""

from __future__ import annotations

import hashlib
import json
import math
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

from scripts.evals import compare_routing_arms as command
from scripts.evals import evaluate_combined_gate as combined
from scripts.evals.lib import arm_metrics, prereg
from scripts.evals.lib.fixtures import load_materials, load_messages, load_questions
from scripts.evals.lib.intervals import rate_ci, sample_mark, wilson_interval
from scripts.evals.lib.kb_scores import KbFileError, load_kb_scores
from scripts.evals.lib.laya_sources import (
    LayaFileError,
    LayaSource,
    load_full_run,
    promotion,
)
from scripts.evals.lib.paired_stats import exact_mcnemar_p, paired_outcomes
from scripts.evals.lib.paths import MATERIALS_PATH, MESSAGES_PATH, QUESTIONS_PATH
from scripts.evals.lib.prepared_rows import prepare_rows
from scripts.evals.lib.routing_arms import (
    SKIP_GREETING,
    SKIP_NAVIGATION,
    SKIP_PERSONAL,
    build_row_scopes,
    search_flags,
    skip_attribution,
)

ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture(scope="module")
def messages() -> list[dict[str, Any]]:
    materials = load_materials(MATERIALS_PATH)
    questions = load_questions(QUESTIONS_PATH, materials)
    return load_messages(MESSAGES_PATH, materials, [q["id"] for q in questions])


@pytest.fixture(scope="module")
def prepared(messages):
    return {row.id: row for row in prepare_rows(messages)}


@pytest.fixture(scope="module")
def scopes(messages, prepared):
    return build_row_scopes(messages, prepared)


def synthetic_kb(
    scopes_: list[Any],
    *,
    mutate: dict[str, dict[str, Any]] | None = None,
    drop: set[str] = frozenset(),
) -> dict[str, Any]:
    """SYNTHETIC TEST DATA: a deterministic fake KB-score file, never a result.

    Retrieve-labelled rows get higher scores than skip rows with an overlap, so a
    threshold exists. ``mutate`` overrides fields per id, ``drop`` removes ids.
    """
    rows = []
    for row in scopes_:
        if row.id in drop:
            continue
        unit = int(hashlib.sha256(f"fixture-{row.id}".encode()).hexdigest()[:8], 16) / 0xFFFFFFFF
        base = 0.55 if row.expected == "retrieve" else 0.25
        score = round(base + 0.4 * unit, 6)
        record = {
            "id": row.id,
            "category": row.category,
            "top_score": score,
            "result_count": 1 + int(unit * 4) % 4,
            "status": "ok",
            "failure_category": None,
            "elapsed_ms": round(100 + 400 * unit, 1),
            "raw_hit_count": 5,
            "exception_class": None,
        }
        record.update((mutate or {}).get(row.id, {}))
        rows.append(record)
    return {
        "mode": "live_kb_gate",
        "synthetic_test_fixture": True,
        "rows": rows,
        "summary": {"stopped_on_auth_error": False},
        "run": {"git_sha": "0" * 40, "git_dirty": False, "generated_at_utc": "2000-01-01T00:00:00Z"},
    }


def write_kb(path: Path, data: dict[str, Any]) -> Path:
    path.write_text(json.dumps(data), encoding="utf-8")
    return path


def kb_from(path: Path, data: dict[str, Any], scopes_: list[Any]):
    return load_kb_scores(write_kb(path, data), {row.id for row in scopes_})


def stub_source(prepared_, *, decisions=None, ms=None, name="stub") -> LayaSource:
    """A stub Laya source: promotes every eligible row it has a decision for."""
    eligible = [i for i, row in prepared_.items() if row.eligible]
    decisions = decisions if decisions is not None else {i: True for i in eligible[: len(eligible) // 2]}
    return LayaSource(
        name=name, origin="stub", description="stub", cutoffs={}, decisions=decisions,
        ms=ms if ms is not None else {i: 100.0 for i in decisions},
    )


# ------------------------------------------------------------------------ the split


def test_split_is_the_sha256_parity_rule_and_deterministic(scopes) -> None:
    for row in scopes:
        digest = int(hashlib.sha256(row.id.encode("utf-8")).hexdigest(), 16)
        expected = prereg.CALIBRATION if digest % 2 == 0 else prereg.HOLDOUT
        assert prereg.split_of(row.id) == expected
        assert prereg.split_of(row.id) == prereg.split_of(row.id)
    halves = {prereg.split_of(row.id) for row in scopes}
    assert halves == {prereg.CALIBRATION, prereg.HOLDOUT}
    assert len(scopes) == prereg.GATE_MESSAGE_COUNT


def test_the_code_constants_equal_the_plan_block() -> None:
    plan = prereg.plan_record(prereg.PLAN_PATH)
    assert plan["constants_match_code"] is True
    text = prereg.PLAN_PATH.read_text(encoding="utf-8")
    assert prereg.parse_constants_block(text) == prereg.PREREG_CONSTANTS
    assert len(plan["sha256"]) == 64
    with pytest.raises(ValueError):
        prereg.parse_constants_block("no block here")


def test_the_laya_cutoffs_in_code_are_the_ones_in_the_stored_learn_file() -> None:
    stored = json.loads(
        (command.PHASE3D_DIR / "course-intent-by-turn.json").read_text(encoding="utf-8")
    )["thresholds_from_calibration"]
    assert round(stored["learn"], 7) == prereg.LAYA_CUTOFFS["learn_continuing"]
    assert round(stored["learn_first_turn"], 7) == prereg.LAYA_CUTOFFS["learn_first_turn"]


# ------------------------------------------------------------------- exact McNemar


@pytest.mark.parametrize(
    ("b", "c", "expected"),
    [(0, 0, 1.0), (5, 0, 0.0625), (0, 5, 0.0625), (10, 2, 158 / 4096), (3, 3, 1.0), (1, 0, 1.0)],
)
def test_exact_mcnemar_vectors(b: int, c: int, expected: float) -> None:
    assert exact_mcnemar_p(b, c) == pytest.approx(expected, abs=1e-15)


def test_mcnemar_rejects_negative_counts_and_counts_discordant_pairs() -> None:
    with pytest.raises(ValueError):
        exact_mcnemar_p(-1, 2)
    first = {"a": True, "b": True, "c": False, "d": False, "e": True}
    second = {"a": False, "b": True, "c": True, "d": False, "e": False}
    result = paired_outcomes(first, second, ["a", "b", "c", "d", "e"])
    assert (result["first_bad_second_ok"], result["first_ok_second_bad"]) == (2, 1)
    assert (result["both_bad"], result["both_ok"], result["rows"]) == (1, 1, 5)
    assert result["p_value"] == exact_mcnemar_p(2, 1)


# ------------------------------------------------------------------------- Wilson


def test_wilson_marks_and_known_interval() -> None:
    low, high = wilson_interval(62, 109)
    assert (round(low, 3), round(high, 3)) == (0.475, 0.658)
    assert wilson_interval(0, 0) is None
    assert [sample_mark(n) for n in (0, 9, 10, 29, 30)] == ["VS", "VS", "S", "S", ""]
    record = rate_ci(3, 20)
    assert record["small_sample"] == "S" and record["rate"] == 0.15
    assert rate_ci(1, 40)["small_sample"] == ""


# --------------------------------------------------------------- T selection (maths)


def _inj(expected: str, top: float | None, *, local: bool = False, ok: bool = True, search: bool = True):
    return prereg.InjectionRow(expected, local, search, ok and top is not None, top)


def test_choose_threshold_picks_the_lowest_m1_among_feasible_candidates() -> None:
    rows = [_inj("retrieve", s) for s in (0.9, 0.8, 0.7, 0.4)] + [
        _inj("skip", s) for s in (0.75, 0.45, 0.2, 0.1, 0.05, 0.04, 0.03, 0.02, 0.01, 0.005)
    ]
    chosen = prereg.choose_threshold(rows)
    # Ten skip rows allow one with evidence. T = 0.45 would admit two (0.75, 0.45), so it
    # is infeasible. T = 0.7 admits one and keeps three retrieve rows, the lowest M1 left.
    assert chosen["feasible"] and chosen["threshold"] == 0.7
    assert chosen["calibration_m2"] == [1, 10] and chosen["calibration_m1"] == [1, 4]
    relaxed = [_inj("retrieve", s) for s in (0.9, 0.8, 0.7, 0.4)] + [_inj("skip", s) for s in (0.75, 0.2, 0.1, 0.05, 0.04, 0.03, 0.02, 0.01, 0.005, 0.001)]
    assert prereg.choose_threshold(relaxed)["threshold"] == 0.4


def test_choose_threshold_infeasible_when_local_searches_break_m2() -> None:
    rows = [_inj("retrieve", 0.9)] + [_inj("skip", None, local=True, search=False) for _ in range(3)]
    chosen = prereg.choose_threshold(rows)
    assert chosen["feasible"] is False and chosen["threshold"] is None


def test_choose_threshold_can_choose_plus_infinity_and_breaks_ties_to_the_higher_t() -> None:
    rows = [_inj("retrieve", None, ok=False, search=True), _inj("skip", 0.9), _inj("skip", 0.8)]
    chosen = prereg.choose_threshold(rows)
    assert chosen["threshold"] == math.inf
    assert prereg.threshold_for_json(chosen["threshold"]) == {"value": None, "infinite": True}
    # Equal M1 and M2 at both candidates: the higher T wins.
    flat = [_inj("retrieve", 0.5), _inj("retrieve", 0.5)]
    assert prereg.choose_threshold(flat)["threshold"] == 0.5


def test_injected_follows_local_search_failed_calls_and_threshold() -> None:
    assert prereg.injected(_inj("skip", None, local=True, search=False), math.inf)
    assert not prereg.injected(_inj("retrieve", None, ok=False), -math.inf)
    assert prereg.injected(_inj("retrieve", 0.6), 0.6)
    assert not prereg.injected(_inj("retrieve", 0.59), 0.6)
    assert not prereg.injected(_inj("retrieve", 0.9, search=False), 0.0)


# ------------------------------------------------------- pass rule and tie-break


def _reading(m1=(1, 10), m2=(0, 10), p95=500.0) -> dict[str, Any]:
    return {"m1": m1, "m2": m2, "p95_wait_ms": p95}


def test_pass_rule_is_tri_state() -> None:
    good = _reading()
    assert prereg.pass_state(pessimistic=good, optimistic=good)["state"] == prereg.PASS
    # Exactly at the limits still passes.
    edge = _reading(m1=(15, 100), m2=(1, 10), p95=1000.0)
    assert prereg.pass_state(pessimistic=edge, optimistic=edge)["state"] == prereg.PASS
    over = _reading(m1=(16, 100))
    failing = prereg.pass_state(pessimistic=over, optimistic=over)
    assert failing["state"] == prereg.FAIL and failing["failed_criteria"] == ["m1"]
    slow = _reading(p95=1000.5)
    assert prereg.pass_state(pessimistic=slow, optimistic=slow)["failed_criteria"] == ["added_p95_wait"]
    # Pessimistic breaks a limit but optimistic does not: undetermined.
    mixed = prereg.pass_state(pessimistic=over, optimistic=good)
    assert mixed["state"] == prereg.UNDETERMINED
    # Missing data never passes.
    assert prereg.pass_state(pessimistic=None, optimistic=good)["state"] == prereg.UNDETERMINED
    assert prereg.pass_state(pessimistic=good, optimistic=good, data_complete=False)["state"] == prereg.UNDETERMINED
    unknown_wait = _reading(p95=None)
    assert prereg.pass_state(pessimistic=unknown_wait, optimistic=unknown_wait)["state"] == prereg.UNDETERMINED
    # No feasible T fails regardless.
    result = prereg.pass_state(pessimistic=good, optimistic=good, no_feasible_threshold=True)
    assert result["state"] == prereg.FAIL and "no_feasible_threshold" in result["failed_criteria"]


def test_tie_break_walks_in_complexity_order_and_needs_lower_m1_and_significance() -> None:
    m1 = {"A": 0.10, "C": 0.08, "B": 0.05, "D": 0.01}
    significant = {("A", "C"): 0.5, ("A", "B"): 0.01, ("B", "D"): 0.2, ("A", "D"): 0.001}

    def p(champion: str, challenger: str) -> float:
        return significant[(champion, challenger)]

    champion, trail = prereg.select_champion(["D", "B", "A", "C"], m1, p)
    # C is lower but not significant, B replaces A (p 0.01), D is not significant over B.
    assert champion == "B"
    assert [(t["champion"], t["challenger"], t["replaces"]) for t in trail] == [
        ("A", "C", False), ("A", "B", True), ("B", "D", False),
    ]
    assert prereg.select_champion([], m1, p) == (None, [])
    # A challenger with a higher M1 never replaces, however small p is.
    assert prereg.select_champion(["A", "C"], {"A": 0.05, "C": 0.09}, lambda *_: 0.0)[0] == "A"


# ------------------------------------------------------ skip rules and arm flags


def test_arm_c_skip_is_the_or_of_the_three_existing_outputs(messages, scopes) -> None:
    from backend.coaching.evidence_scope import is_chit_chat
    from scripts.evals.lib.gate import gate_decision

    for row, scope in zip(messages, scopes):
        gate = gate_decision(row)
        expected = (
            is_chit_chat(row["message"])
            or gate.scope_cleared
            or gate.intent == "high_confidence_personal"
        )
        assert scope.skipped_by_c is expected
        assert (scope.skip_rule is not None) is expected
    counts = skip_attribution(scopes)
    assert sum(counts["first_rule_that_fires"].values()) == counts["skipped_by_c"]
    assert set(counts["first_rule_that_fires"]) == {SKIP_GREETING, SKIP_NAVIGATION, SKIP_PERSONAL}


def test_skip_rule_attribution_order_is_greeting_navigation_personal(scopes) -> None:
    template = scopes[0]
    both = type(template)(**{**template.__dict__, "chit_chat": True, "scope_cleared": True, "personal": True})
    assert both.skip_rule == SKIP_GREETING
    nav = type(template)(**{**both.__dict__, "chit_chat": False})
    assert nav.skip_rule == SKIP_NAVIGATION
    personal = type(template)(**{**nav.__dict__, "scope_cleared": False})
    assert personal.skip_rule == SKIP_PERSONAL


def test_arm_flags_match_the_gate_and_promotion(messages, scopes) -> None:
    from scripts.evals.lib.gate import gate_decision

    promoted_extra = 0
    for row, scope in zip(messages, scopes):
        gate = gate_decision(row)
        assert search_flags("A", scope, False) == (gate.course, gate.student)
        assert search_flags("B", scope, False) == (gate.course, gate.student)
        assert search_flags("D", scope, False) == (gate.course, gate.student)
        assert search_flags("C", scope, False) == (not scope.skipped_by_c, gate.student)
        if not scope.eligible:
            assert search_flags("B", scope, True) == (gate.course, gate.student)
        elif search_flags("B", scope, True)[0] and not gate.course:
            promoted_extra += 1
    assert promoted_extra > 0
    with pytest.raises(ValueError):
        search_flags("X", scopes[0], False)


def test_promotion_readings(prepared) -> None:
    eligible = next(r for r in prepared.values() if r.eligible)
    other = next(r for r in prepared.values() if not r.eligible)
    source = stub_source(prepared, decisions={eligible.id: True})
    assert promotion(eligible, source, "floor") == (True, False)
    assert promotion(other, source, "ceiling") == (False, False)
    assert promotion(eligible, None, "ceiling") == (False, False)
    bare = stub_source(prepared, decisions={})
    assert promotion(eligible, bare, "floor") == (False, True)
    assert promotion(eligible, bare, "ceiling") == (True, True)
    assert promotion(eligible, bare, "scored_only") == (False, True)


def test_the_shared_helpers_are_the_ones_the_combined_gate_re_exports() -> None:
    from scripts.evals.lib import intervals, laya_sources

    assert combined.wilson_interval is intervals.wilson_interval
    assert combined.rate_ci is intervals.rate_ci
    assert combined.LayaSource is laya_sources.LayaSource
    assert combined.load_stored_learn is laya_sources.load_stored_learn
    assert combined.MODES is laya_sources.MODES


def test_arms_a_and_b_reproduce_the_combined_gate_counts_on_all_rows(messages, prepared, scopes) -> None:
    source = combined.load_stored_multilingual(command.PHASE3D_DIR / "multilingual.json", "m", prepared)
    summary = combined.summarize(combined.compose(list(prepare_rows(messages)), source, "floor"), combined.CostModel(1, 1, 1))
    rows = arm_metrics.make_scenario(scopes, prepared, source, "floor")
    ids = [r.scopes.id for r in rows]
    for arm, key in (("A", "arm_a_gate"), ("B", "arm_b_gate_laya")):
        run = arm_metrics.build_run(arm, rows, None, threshold=-math.inf)
        m1, m2 = arm_metrics.m1_m2(run, ids)
        assert (m1["numerator"], m1["denominator"]) == (
            summary[key]["overall"]["wrong_skip"]["numerator"],
            summary[key]["overall"]["wrong_skip"]["denominator"],
        )
        assert m2["numerator"] == summary[key]["overall"]["false_retrieve"]["numerator"]


# --------------------------------------------------------------- KB-score loader


def test_kb_loader_validates_and_passes_the_synthetic_marker(tmp_path: Path, scopes) -> None:
    ids = {row.id for row in scopes}
    data = synthetic_kb(scopes)
    kb = kb_from(tmp_path / "kb.json", data, scopes)
    assert kb.complete and kb.synthetic_test_fixture and len(kb.rows) == 295
    assert kb.describe(ids)["ids_missing"] == 0
    partial = kb_from(tmp_path / "p.json", synthetic_kb(scopes, drop={"gm001"}), scopes)
    assert not partial.complete and partial.describe(ids)["ids_missing"] == 1
    bad_cases = {
        "mode": {**data, "mode": "other"},
        "status": {**data, "rows": [{**data["rows"][0], "status": "weird"}]},
        "elapsed": {**data, "rows": [{**data["rows"][0], "elapsed_ms": -1}]},
        "count": {**data, "rows": [{**data["rows"][0], "result_count": 2, "top_score": None}]},
        "duplicate": {**data, "rows": [data["rows"][0], data["rows"][0]]},
        "unknown": {**data, "rows": [{**data["rows"][0], "id": "zzz"}]},
        "rows": {**data, "rows": "nope"},
    }
    for name, bad in bad_cases.items():
        with pytest.raises(KbFileError):
            load_kb_scores(write_kb(tmp_path / f"{name}.json", bad), ids)
    (tmp_path / "junk.json").write_text("{", encoding="utf-8")
    with pytest.raises(KbFileError):
        load_kb_scores(tmp_path / "junk.json", ids)


# ----------------------------------------------------------- Laya full-run loader


def _full_run_file(path: Path, prepared_, *, status="scored", score=0.9, drop=(), extra=None) -> Path:
    rows = []
    for row_id, row in prepared_.items():
        if row_id in drop:
            continue
        if row.eligible:
            rows.append({"id": row_id, "status": status, "score": score, "ms": 120.0})
        else:
            rows.append({"id": row_id, "status": "not_eligible", "score": None, "ms": None})
    data = {
        "rows": rows,
        "memory": {"peak_rss_mib": 2048.0, "load_delta_rss_mib": 1500.0, "after_load": {"rss_mib": 1800.0}},
        "host_note": {"instance_type": "<TYPE>"},
        **(extra or {}),
    }
    path.write_text(json.dumps(data), encoding="utf-8")
    return path


def test_full_run_loader_applies_unchanged_cutoffs(tmp_path: Path, prepared) -> None:
    path = _full_run_file(tmp_path / "f.json", prepared, score=0.85)
    source = load_full_run(path, "full", prepared, cutoff=0.8)
    eligible = [i for i, r in prepared.items() if r.eligible]
    assert all(source.decisions[i] for i in eligible)
    assert not any(v for i, v in source.decisions.items() if i not in eligible)
    assert set(source.decisions) == set(prepared) and source.host_noted
    assert source.memory["peak_rss_mib"] == 2048.0 and source.consistency["consistent"]
    strict = load_full_run(path, "full", prepared, cutoff=0.9)
    assert not any(strict.decisions.values())
    first = next(i for i in eligible if prepared[i].first_turn)
    split_cutoff = load_full_run(path, "full", prepared, cutoff=0.9, first_turn_cutoff=0.5)
    assert split_cutoff.decisions[first] is True
    busy = load_full_run(_full_run_file(tmp_path / "b.json", prepared, status="busy", score=None), "b", prepared, cutoff=0.8)
    assert not any(busy.decisions.values())


def test_full_run_loader_is_tolerant_and_strict_where_it_matters(tmp_path: Path, prepared) -> None:
    minimal = tmp_path / "m.json"
    eligible = [i for i, r in prepared.items() if r.eligible]
    minimal.write_text(json.dumps({"rows": [{"id": i, "course_score": 0.95} for i in eligible]}), encoding="utf-8")
    source = load_full_run(minimal, "m", prepared, cutoff=0.8)
    assert all(source.decisions[i] for i in eligible) and not source.host_noted
    with pytest.raises(LayaFileError, match="incomplete"):
        load_full_run(_full_run_file(tmp_path / "i.json", prepared, drop={eligible[0]}), "i", prepared, cutoff=0.8)
    with pytest.raises(LayaFileError, match="stub"):
        load_full_run(_full_run_file(tmp_path / "s.json", prepared, extra={"real_model": False}), "s", prepared, cutoff=0.8)
    unknown = tmp_path / "u.json"
    unknown.write_text(json.dumps({"rows": [{"id": "nope"}]}), encoding="utf-8")
    with pytest.raises(LayaFileError, match="not in the gate set"):
        load_full_run(unknown, "u", prepared, cutoff=0.8)
    repeated = tmp_path / "r.json"
    repeated.write_text(json.dumps({"rows": [{"id": eligible[0]}, {"id": eligible[0]}]}), encoding="utf-8")
    with pytest.raises(LayaFileError, match="repeated"):
        load_full_run(repeated, "r", prepared, cutoff=0.8)
    with pytest.raises(LayaFileError):
        load_full_run(tmp_path / "absent.json", "x", prepared, cutoff=0.8)


# -------------------------------------------------------------- comparison, no KB


def test_without_a_kb_file_arms_c_and_d_are_missing_and_never_pass(tmp_path: Path, prepared, scopes) -> None:
    result = arm_metrics.compare(scopes, prepared, [stub_source(prepared)], None)
    assert result["kb_file"] == {"present": False}
    for key, entry in result["sources"].items():
        for reading in entry["readings"].values():
            arms = reading["arms"]
            assert arms["C"]["available"] is False and arms["C"]["status"] == "missing"
            assert arms["D"]["available"] is False and arms["D"]["status"] == "missing"
            assert arms["A"]["m1_no_evidence_on_retrieve_rows"]["status"] == "bound"
            for pair in ("A_vs_C", "B_vs_C", "C_vs_D"):
                assert reading["pairs"][pair]["status"] == "missing"
        states = {arm: v["state"] for arm, v in entry["pass_rule"].items()}
        assert prereg.PASS not in states.values()
        assert states["C"] == prereg.UNDETERMINED
        assert entry["selection"]["full_comparison_claimed"] is False
    assert result["sources"][arm_metrics.NO_LAYA]["pass_rule"]["B"]["state"] == prereg.UNDETERMINED
    assert result["calibration"] == {}


def test_arm_a_fails_on_its_known_bound_without_any_kb_data(prepared, scopes) -> None:
    result = arm_metrics.compare(scopes, prepared, [], None)
    rule = result["sources"][arm_metrics.NO_LAYA]["pass_rule"]["A"]
    assert rule["state"] == prereg.FAIL and "m1" in rule["failed_criteria"]


def test_only_holdout_rows_feed_reported_figures_and_categories_sum(prepared, scopes) -> None:
    result = arm_metrics.compare(scopes, prepared, [], None)
    holdout = result["split"][prereg.HOLDOUT]["rows"]
    reading = result["sources"][arm_metrics.NO_LAYA]["readings"]["all"]
    assert reading["rows"]["holdout_rows"] == holdout
    a = reading["arms"]["A"]
    assert a["m1_no_evidence_on_retrieve_rows"]["denominator"] == result["split"][prereg.HOLDOUT]["retrieve"]
    assert a["m2_evidence_on_skip_rows"]["denominator"] == result["split"][prereg.HOLDOUT]["skip"]
    categories = a["by_category"]
    assert sum(c["rows"] for c in categories.values()) == holdout
    assert sum(c["m1"]["denominator"] for c in categories.values()) == a["m1_no_evidence_on_retrieve_rows"]["denominator"]
    assert sum(c["m2"]["denominator"] for c in categories.values()) == a["m2_evidence_on_skip_rows"]["denominator"]
    assert result["split"][prereg.CALIBRATION]["rows"] + holdout == 295


def test_laya_readings_bracket_and_scored_only_drops_rows(prepared, scopes) -> None:
    source = stub_source(prepared)
    entry = arm_metrics.compare(scopes, prepared, [source], None)["sources"]["stub"]
    floor, ceiling, scored = (entry["readings"][m]["arms"]["B"] for m in ("floor", "ceiling", "scored_only"))
    assert floor["m3_searches_added_vs_a"]["holdout"]["kb_searches"] <= ceiling["m3_searches_added_vs_a"]["holdout"]["kb_searches"]
    assert entry["readings"]["scored_only"]["rows"]["reading_rows"] < 295
    assert entry["coverage"]["complete"] is False
    assert floor["m1_no_evidence_on_retrieve_rows"]["status"] == "bound"
    assert scored["m3_searches_added_vs_a"]["status"] == "measured"
    # Stored-dev-laptop Laya time is a bound, and the unknown KB time is missing.
    assert floor["m4_added_wait_ms"]["status"] == "missing"
    assert floor["m5_cost_per_1000_turns"]["laya_host_memory"]["status"] == "missing"


# ------------------------------------------------------------ comparison, synthetic KB


def test_synthetic_kb_run_chooses_t_on_calibration_rows_only(tmp_path: Path, prepared, scopes) -> None:
    kb = kb_from(tmp_path / "kb.json", synthetic_kb(scopes), scopes)
    source = stub_source(prepared)
    result = arm_metrics.compare(scopes, prepared, [source], kb)
    t_c = result["calibration"]["T_C"]
    assert t_c["feasible"] and t_c["chosen_on"] == "calibration rows only"
    assert t_c["calibration_rows"] == result["split"][prereg.CALIBRATION]["rows"]
    # An independent brute force over the calibration rows agrees.
    cal = [r for r in scopes if prereg.split_of(r.id) == prereg.CALIBRATION]
    best = None
    scores = sorted({kb.rows[r.id].top_score for r in cal if not r.skipped_by_c and kb.rows[r.id].ok})
    for threshold in [*scores, math.inf]:
        def evid(r):
            hit = (not r.skipped_by_c) and kb.rows[r.id].ok and kb.rows[r.id].top_score >= threshold
            return r.local_a or hit
        retrieve = [r for r in cal if r.expected == "retrieve"]
        skip = [r for r in cal if r.expected == "skip"]
        m1 = sum(1 for r in retrieve if not evid(r)) / len(retrieve)
        m2 = sum(1 for r in skip if evid(r)) / len(skip)
        if m2 <= 0.10 and (best is None or (m1, m2, -threshold) < best[:3]):
            best = (m1, m2, -threshold)
    assert best is not None
    assert (t_c["threshold"]["infinite"], t_c["threshold"]["value"]) == (
        (True, None) if best[2] == -math.inf else (False, -best[2])
    )
    reading = result["sources"]["stub"]["readings"]["floor"]["arms"]
    assert reading["C"]["threshold"] == t_c["threshold"]
    for arm in "ABCD":
        for key in ("m1_no_evidence_on_retrieve_rows", "m2_evidence_on_skip_rows"):
            assert reading[arm][key]["status"] in {"synthetic_test_data", "bound"}
    assert reading["A"]["m1_no_evidence_on_retrieve_rows"]["status"] == "synthetic_test_data"
    assert "T_D" in result["calibration"] and "stub" in result["calibration"]["T_D"]
    json.dumps(result, allow_nan=False)


def test_t_ignores_holdout_scores_and_follows_calibration_scores(tmp_path: Path, prepared, scopes) -> None:
    base = kb_from(tmp_path / "a.json", synthetic_kb(scopes), scopes)
    holdout = {r.id: {"top_score": 0.01, "elapsed_ms": 5.0} for r in scopes if prereg.split_of(r.id) == prereg.HOLDOUT}
    calib = {r.id: {"top_score": 0.99} for r in scopes if prereg.split_of(r.id) == prereg.CALIBRATION}
    changed_holdout = kb_from(tmp_path / "b.json", synthetic_kb(scopes, mutate=holdout), scopes)
    changed_calibration = kb_from(tmp_path / "c.json", synthetic_kb(scopes, mutate=calib), scopes)
    t = lambda kb: arm_metrics.compare(scopes, prepared, [], kb)["calibration"]["T_C"]["threshold"]  # noqa: E731
    assert t(base) == t(changed_holdout)
    assert t(base) != t(changed_calibration)
    # And the holdout figures do move when holdout scores move (T frozen, applied unchanged).
    def holdout_m1(kb):
        arms = arm_metrics.compare(scopes, prepared, [], kb)["sources"]["no_laya"]["readings"]["all"]["arms"]
        return arms["C"]["m1_no_evidence_on_retrieve_rows"]["numerator"]
    assert holdout_m1(changed_holdout) > holdout_m1(base)


def test_failed_kb_calls_count_as_no_evidence(tmp_path: Path, prepared, scopes) -> None:
    searched = [r for r in scopes if not r.skipped_by_c and prereg.split_of(r.id) == prereg.HOLDOUT and r.expected == "retrieve"]
    failing = {r.id: {"status": "unavailable", "result_count": 0, "top_score": None, "failure_category": "timeout"} for r in searched}
    healthy = kb_from(tmp_path / "h.json", synthetic_kb(scopes), scopes)
    broken = kb_from(tmp_path / "x.json", synthetic_kb(scopes, mutate=failing), scopes)
    assert broken.describe({r.id for r in scopes})["failed_calls"] == len(searched)
    def m1(kb):
        reading = arm_metrics.compare(scopes, prepared, [], kb)["sources"]["no_laya"]["readings"]["all"]["arms"]
        return reading["A"]["m1_no_evidence_on_retrieve_rows"]["numerator"]
    assert m1(broken) >= m1(healthy)


def test_a_partial_kb_file_leaves_kb_figures_missing(tmp_path: Path, prepared, scopes) -> None:
    partial = kb_from(tmp_path / "p.json", synthetic_kb(scopes, drop={"gm001"}), scopes)
    result = arm_metrics.compare(scopes, prepared, [], partial)
    assert result["kb_file"]["present"] and result["kb_file"]["used"] is False
    arms = result["sources"]["no_laya"]["readings"]["all"]["arms"]
    assert arms["C"]["available"] is False and "partial" in arms["C"]["reason"]
    assert arms["A"]["m1_no_evidence_on_retrieve_rows"]["status"] == "bound"
    assert result["calibration"] == {} and result["kb_ms"] is None


def test_pairs_report_discordant_counts_and_the_construction_note(tmp_path: Path, prepared, scopes) -> None:
    kb = kb_from(tmp_path / "kb.json", synthetic_kb(scopes), scopes)
    result = arm_metrics.compare(scopes, prepared, [stub_source(prepared)], kb)
    pairs = result["sources"]["stub"]["readings"]["floor"]["pairs"]
    assert "A is never better than B" in pairs["note"]
    ab = pairs["A_vs_B"]["retrieve_rows_m1"]
    assert ab["first_ok_second_bad"] == 0, "B only adds searches to A, so A is never better on retrieve rows"
    for key in ("A_vs_B", "A_vs_C", "B_vs_C", "C_vs_D"):
        for family in arm_metrics.FAMILIES:
            cell = pairs[key][family]
            assert cell["p_value"] == exact_mcnemar_p(cell["first_bad_second_ok"], cell["first_ok_second_bad"])
            assert cell["first_bad_second_ok"] + cell["first_ok_second_bad"] + cell["both_bad"] + cell["both_ok"] == cell["rows"]


# --------------------------------------------------------------------- M3 / M4 / M5


def test_searches_added_wait_and_nearest_rank_on_crafted_runs(scopes) -> None:
    rows = [arm_metrics.ScenarioRow(s, False, False) for s in scopes[:4]]
    base = arm_metrics.build_run("A", rows, None, threshold=-math.inf)
    run = arm_metrics.build_run("A", rows, None, threshold=-math.inf)
    ids = [r.scopes.id for r in rows]
    # Craft: arm searches the KB on two rows A does not, and one local search more.
    run.kb_search.update({ids[0]: True, ids[1]: True, ids[2]: False, ids[3]: False})
    base.kb_search.update({i: False for i in ids})
    base.local_search.update({i: False for i in ids})
    run.local_search.update({ids[0]: False, ids[1]: False, ids[2]: True, ids[3]: False})
    added = arm_metrics.searches_added(run, base, ids)
    assert (added["kb_added_per_100_turns"], added["local_added_per_100_turns"]) == (50.0, 25.0)
    assert (added["kb_searches"], added["local_searches"]) == (2, 1)

    class Kb:
        rows = {i: type("R", (), {"elapsed_ms": 100.0 * (n + 1)})() for n, i in enumerate(ids)}

    waits = arm_metrics.added_wait(run, base, ids, source=None, kb=Kb, imputation="lower", include_kb=True)
    assert waits == [100.0, 200.0, 0.0, 0.0]
    run.arm = "B"
    source = stub_source({}, decisions={}, ms={ids[0]: 50.0})
    eligible_row = arm_metrics.ScenarioRow(
        type(scopes[0])(**{**scopes[0].__dict__, "eligible": True}), False, True
    )
    run.rows[0] = eligible_row
    upper = arm_metrics.added_wait(run, base, ids[:1], source=source, kb=None, imputation="upper", include_kb=False)
    assert upper == [50.0]
    assert arm_metrics.nearest_rank([], 95) is None
    assert arm_metrics.nearest_rank(list(range(1, 21)), 95) == 19
    assert arm_metrics.nearest_rank(list(range(1, 21)), 50) == 10
    assert arm_metrics.nearest_rank([5.0], 95) == 5.0


def test_cost_uses_the_price_and_laya_memory_comes_from_the_full_run_file(tmp_path: Path, prepared, scopes) -> None:
    kb = kb_from(tmp_path / "kb.json", synthetic_kb(scopes), scopes)
    full = load_full_run(_full_run_file(tmp_path / "f.json", prepared, score=0.5), "full", prepared, cutoff=0.8)
    result = arm_metrics.compare(scopes, prepared, [full], kb)
    reading = result["sources"]["full"]["readings"]["floor"]["arms"]
    a_cost = reading["A"]["m5_cost_per_1000_turns"]
    holdout = result["sources"]["full"]["readings"]["floor"]["rows"]["holdout_rows"]
    searches = reading["A"]["m3_searches_added_vs_a"]["holdout"]["kb_searches"]
    assert a_cost["kb_searches_per_1000_turns"] == round(1000 * searches / holdout, 2)
    assert a_cost["kb_usd_per_1000_turns"] == round(a_cost["kb_searches_per_1000_turns"] / 1000, 4)
    assert a_cost["laya_host_memory"] is None
    memory = reading["B"]["m5_cost_per_1000_turns"]["laya_host_memory"]
    assert memory["status"] == "measured" and memory["peak_rss_mib"] == 2048.0
    assert result["sources"]["full"]["coverage"]["complete"] is True
    # With full coverage the three readings coincide and B is exact.
    assert reading["B"]["m1_no_evidence_on_retrieve_rows"]["status"] == "synthetic_test_data"
    floor = result["sources"]["full"]["readings"]["floor"]["arms"]["B"]["m1_no_evidence_on_retrieve_rows"]
    ceiling = result["sources"]["full"]["readings"]["ceiling"]["arms"]["B"]["m1_no_evidence_on_retrieve_rows"]
    assert (floor["numerator"], floor["denominator"]) == (ceiling["numerator"], ceiling["denominator"])


# ------------------------------------------------------------------------- the command


def _run(args: list[str], capsys) -> tuple[int, str, str]:
    code = command.main(args)
    out = capsys.readouterr()
    return code, out.out, out.err


def test_command_runs_offline_without_a_kb_file(tmp_path: Path, capsys, messages) -> None:
    json_path, md_path = tmp_path / "out.json", tmp_path / "out.md"
    code, out, err = _run(["--json-output", str(json_path), "--markdown-output", str(md_path)], capsys)
    assert code == 0 and err == ""
    data = json.loads(json_path.read_text(encoding="utf-8"))
    json.dumps(data, allow_nan=False)
    assert data["kb_file"] == {"present": False}
    assert data["prereg"]["plan"]["constants_match_code"] is True
    assert {"git_sha", "git_dirty", "generated_at_utc"} <= set(data["run"])
    assert {"no_laya", "laya_multilingual_0.8"} <= set(data["sources"])
    assert data["source_roles"]["laya_multilingual_0.8"].startswith("primary")
    assert out == md_path.read_text(encoding="utf-8") + "\n"
    assert "missing" in out and "SYNTHETIC" not in out
    blob = json_path.read_text(encoding="utf-8") + out
    for row in messages[:60]:
        assert str(row["message"]) not in blob


def test_command_with_a_synthetic_kb_file_marks_it_not_a_result(tmp_path: Path, capsys, scopes) -> None:
    kb = write_kb(tmp_path / "kb.json", synthetic_kb(scopes))
    code, out, _ = _run(["--kb-gate", str(kb), "--json-output", str(tmp_path / "o.json")], capsys)
    assert code == 0
    assert "SYNTHETIC TEST DATA" in out
    data = json.loads((tmp_path / "o.json").read_text(encoding="utf-8"))
    assert data["kb_file"]["synthetic_test_fixture"] is True and data["kb_file"]["used"] is True
    assert "T_C" in data["calibration"]


def test_command_with_a_full_laya_run_adds_a_source(tmp_path: Path, capsys, prepared) -> None:
    full = _full_run_file(tmp_path / "full.json", prepared, score=0.9)
    code, _, _ = _run(["--laya-full", str(full), "--json-output", str(tmp_path / "o.json")], capsys)
    assert code == 0
    data = json.loads((tmp_path / "o.json").read_text(encoding="utf-8"))
    entry = data["sources"]["laya_full_multilingual"]
    assert entry["coverage"]["complete"] and entry["host_noted"] is True
    learn_code, _, _ = _run(["--laya-full", str(full), "--laya-full-kind", "learn", "--json-output", str(tmp_path / "l.json")], capsys)
    assert learn_code == 0
    learn = json.loads((tmp_path / "l.json").read_text(encoding="utf-8"))["sources"]["laya_full_learn"]
    assert learn["cutoffs"] == {"threshold": 0.8563768, "first_turn_threshold": 0.6455846}


def test_command_refuses_bad_inputs_with_exit_2(tmp_path: Path, capsys, scopes, prepared) -> None:
    unknown = synthetic_kb(scopes)
    unknown["rows"][0]["id"] = "zzz999"
    code, _, err = _run(["--kb-gate", str(write_kb(tmp_path / "u.json", unknown))], capsys)
    assert code == 2 and "refused" in err
    code, _, err = _run(["--kb-gate", str(tmp_path / "absent.json")], capsys)
    assert code == 2 and "refused" in err
    stub = _full_run_file(tmp_path / "s.json", prepared, extra={"real_model": False})
    code, _, err = _run(["--laya-full", str(stub)], capsys)
    assert code == 2 and "stub" in err
    plan = tmp_path / "plan.md"
    plan.write_text("# plan\n\n```json prereg-constants\n{\"m1_max\": 0.5}\n```\n", encoding="utf-8")
    code, _, err = _run(["--plan", str(plan)], capsys)
    assert code == 2 and "differs" in err
    code, _, err = _run(["--plan", str(tmp_path / "none.md")], capsys)
    assert code == 2 and "plan" in err
    with pytest.raises(SystemExit) as exit_info:
        command.main(["--laya-full-kind", "other"])
    assert exit_info.value.code == 2


def test_new_modules_load_no_aws_or_model_package_and_no_other_command() -> None:
    code = (
        "import sys\n"
        "import scripts.evals.compare_routing_arms\n"
        "import scripts.evals.lib.arm_metrics, scripts.evals.lib.arm_report, scripts.evals.lib.prereg\n"
        "import scripts.evals.lib.kb_scores, scripts.evals.lib.paired_stats, scripts.evals.lib.laya_sources\n"
        "import scripts.evals.lib.intervals, scripts.evals.lib.routing_arms\n"
        "heavy = {'laya', 'vegaml', 'setfit', 'torch', 'onnxruntime', 'boto3', 'botocore'}\n"
        "others = [m for m in sys.modules if m.startswith('scripts.evals.') and not m.startswith('scripts.evals.lib')\n"
        "          and m != 'scripts.evals.compare_routing_arms']\n"
        "print(sorted(heavy & set(sys.modules)), others)\n"
    )
    done = subprocess.run([sys.executable, "-c", code], cwd=ROOT, capture_output=True, text=True, check=True)
    assert done.stdout.strip() == "[] []"


def test_the_boundary_walk_covers_the_new_command() -> None:
    evals = ROOT / "scripts" / "evals"
    assert (evals / "compare_routing_arms.py").is_file()
    commands = sorted(p.stem for p in evals.glob("*.py") if p.name != "__init__.py")
    assert "compare_routing_arms" in commands
    for name in ("arm_metrics", "arm_report", "prereg", "kb_scores", "paired_stats", "routing_arms", "intervals", "laya_sources"):
        assert (evals / "lib" / f"{name}.py").is_file()
