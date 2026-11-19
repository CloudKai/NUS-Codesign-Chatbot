"""Check the combined gate evaluation: interval maths, arm composition, loaders."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from scripts.evals import evaluate_combined_gate as combined
from scripts.evals import evaluate_retrieval as retrieval

COST = combined.CostModel(rule_chars=100, titles_chars=50, excerpt_cap_chars=1000)


def _row(
    row_id: str,
    expected: str,
    *,
    category: str = "course_content",
    gate: bool = False,
    second_chance: bool = True,
    eligible: bool = True,
    message: str = "What is a stakeholder map?",
    first_turn: bool = False,
) -> combined.PreparedRow:
    return combined.PreparedRow(
        id=row_id,
        category=category,
        expected=expected,
        message=message,
        history=(),
        gate_retrieve=gate,
        second_chance=second_chance,
        eligible=eligible,
        first_turn=first_turn,
    )


def _source(decisions: dict[str, bool]) -> combined.LayaSource:
    return combined.LayaSource(
        name="stub",
        origin=combined.STORED_ORIGIN,
        description="stub",
        cutoffs={},
        decisions=decisions,
    )


# --- interval maths ---------------------------------------------------------


@pytest.mark.parametrize(
    ("successes", "total", "low", "high"),
    [
        (0, 10, 0.0, 0.2775),
        (5, 10, 0.2366, 0.7634),
        (10, 10, 0.7225, 1.0),
        (62, 109, 0.475, 0.658),
        (73, 109, 0.577, 0.751),
        (2, 60, 0.009, 0.114),
        (1, 9, 0.020, 0.435),
        (0, 3, 0.0, 0.561),
    ],
)
def test_wilson_interval_matches_reference_values(
    successes: int, total: int, low: float, high: float
) -> None:
    interval = combined.wilson_interval(successes, total)
    assert interval is not None
    assert interval[0] == pytest.approx(low, abs=0.001)
    assert interval[1] == pytest.approx(high, abs=0.001)


def test_wilson_interval_edges() -> None:
    assert combined.wilson_interval(0, 0) is None
    with pytest.raises(ValueError):
        combined.wilson_interval(5, 4)
    low, high = combined.wilson_interval(7, 20)  # type: ignore[misc]
    assert 0 <= low < 7 / 20 < high <= 1


def test_rate_ci_marks_small_samples_and_formats() -> None:
    assert combined.rate_ci(1, 9)["small_sample"] == "VS"
    assert combined.rate_ci(1, 29)["small_sample"] == "S"
    assert combined.rate_ci(1, 30)["small_sample"] == ""
    assert combined.format_ci(combined.rate_ci(2, 60)) == "2/60 = 3.3% [0.9, 11.4]"
    assert combined.format_ci(combined.rate_ci(1, 9)).endswith(" VS")
    empty = combined.rate_ci(0, 0)
    assert empty["rate"] is None and empty["wilson_low"] is None
    assert combined.format_ci(empty) == "n/a (0/0)"


# --- arm composition ----------------------------------------------------------


def test_laya_only_promotes_eligible_rows_the_gate_skipped() -> None:
    rows = [
        _row("r1", "retrieve"),
        _row("r2", "skip"),
        _row("r3", "retrieve", gate=True, second_chance=False, eligible=False),
        _row("r4", "retrieve", eligible=False),
    ]
    outcomes = combined.compose(rows, _source({"r1": True, "r2": True, "r3": True, "r4": True}), "floor")
    by_id = {o.id: o for o in outcomes}
    assert by_id["r1"].with_laya and by_id["r2"].with_laya
    assert by_id["r3"].with_laya and not by_id["r3"].laya_promoted  # gate already searched
    assert not by_id["r4"].with_laya  # not eligible, so Laya never runs
    summary = combined.summarize(outcomes, COST)
    assert summary["arm_a_gate"]["overall"]["wrong_skip"]["numerator"] == 2
    assert summary["arm_b_gate_laya"]["overall"]["wrong_skip"]["numerator"] == 1
    assert summary["arm_b_gate_laya"]["overall"]["false_retrieve"]["numerator"] == 1
    assert summary["arm_b_gate_laya"]["overall"]["extra_retrieval_searches"] == 2


def test_wording_arm_flags_only_stamped_rows_and_counts_extra_calls() -> None:
    rows = [
        _row("promoted", "retrieve"),
        _row("missed", "retrieve"),
        _row("fp", "skip"),
        _row("cleared", "retrieve", second_chance=False, eligible=False),
    ]
    outcomes = combined.compose(rows, _source({"promoted": True, "missed": False, "fp": False}), "floor")
    by_id = {o.id: o for o in outcomes}
    assert by_id["promoted"].stamped is False  # Laya searched, no second chance
    assert by_id["cleared"].stamped is False  # gate override fixed the scope
    assert by_id["missed"].stamped and by_id["fp"].stamped
    block = combined.summarize(outcomes, COST)["arm_c_gate_laya_wording_STUB_BOUND"]
    oracle = block["oracle"]["overall"]
    assert oracle["wrong_skip"]["numerator"] == 1  # only the unstamped 'cleared' row stays skipped
    assert oracle["false_retrieve"]["numerator"] == 0
    assert oracle["extra_model_calls"] == 1
    flag_all = block["flag_all"]["overall"]
    assert flag_all["false_retrieve"]["numerator"] == 1
    assert flag_all["extra_model_calls"] == 2
    assert flag_all["stamped_turns"] == 2
    assert flag_all["wording_prompt_chars"] == 2 * (100 + 50)
    assert flag_all["excerpt_chars_upper_bound"] == 3 * 1000  # promoted + 2 flagged
    assert flag_all["second_call_input_tokens"] == 2 * 7100
    assert flag_all["second_call_output_tokens"] == 2 * 300


def test_modes_bracket_unscored_eligible_rows() -> None:
    rows = [_row("scored", "retrieve"), _row("unscored", "retrieve"), _row("other", "skip", eligible=False)]
    source = _source({"scored": True})
    floor = combined.compose(rows, source, "floor")
    ceiling = combined.compose(rows, source, "ceiling")
    only = combined.compose(rows, source, "scored_only")
    assert [o.with_laya for o in floor] == [True, False, False]
    assert [o.with_laya for o in ceiling] == [True, True, False]
    assert [o.id for o in only] == ["scored", "other"]
    assert sum(o.laya_unscored for o in floor) == 1
    assert combined.summarize(floor, COST)["laya_unscored_eligible_rows"] == 1
    with pytest.raises(ValueError):
        combined.compose(rows, source, "nonsense")


def test_without_a_source_arm_b_equals_arm_a() -> None:
    rows = [_row("r1", "retrieve"), _row("r2", "skip", gate=True, second_chance=False)]
    summary = combined.summarize(combined.compose(rows, None, "floor"), COST)
    assert summary["arm_a_gate"] == summary["arm_b_gate_laya"]


def test_by_category_cells_sum_to_overall() -> None:
    rows = [
        _row("r1", "retrieve", category="x"),
        _row("r2", "retrieve", category="y"),
        _row("r3", "skip", category="y"),
    ]
    block = combined.summarize(combined.compose(rows, _source({"r1": True}), "floor"), COST)[
        "arm_b_gate_laya"
    ]
    assert set(block["by_category"]) == {"x", "y"}
    assert block["by_category"]["x"]["wrong_skip"]["numerator"] == 0
    assert block["by_category"]["y"]["wrong_skip"]["numerator"] == 1
    assert block["by_category"]["x"]["false_retrieve"]["denominator"] == 0
    assert sum(c["rows"] for c in block["by_category"].values()) == block["overall"]["rows"]


def test_arms_match_the_existing_offline_gate_and_needs_sources_stubs() -> None:
    """With no Laya, arm (a) and arm (c) must equal the numbers evaluate_retrieval reports."""
    materials = retrieval.load_materials(retrieval.MATERIALS_PATH)
    questions = retrieval.load_questions(retrieval.QUESTIONS_PATH, materials)
    messages = retrieval.load_messages(
        retrieval.MESSAGES_PATH, materials, [row["id"] for row in questions]
    )
    gate = retrieval.evaluate_gate(messages, None)
    stubs = gate["needs_sources_stubs"]["stubs"]
    summary = combined.summarize(combined.compose(combined.prepare_rows(messages), None, "floor"), COST)
    assert len(messages) == 295
    a = summary["arm_a_gate"]["overall"]
    assert (a["wrong_skip"]["numerator"], a["wrong_skip"]["denominator"]) == (
        gate["wrong_skip_rate"]["numerator"],
        gate["wrong_skip_rate"]["denominator"],
    )
    assert a["false_retrieve"]["numerator"] == gate["false_retrieve_rate"]["numerator"]
    for name in combined.STUB_NAMES:
        c = summary["arm_c_gate_laya_wording_STUB_BOUND"][name]["overall"]
        assert c["wrong_skip"]["numerator"] == stubs[name]["wrong_skip_rate"]["numerator"]
        assert c["false_retrieve"]["numerator"] == stubs[name]["false_retrieve_rate"]["numerator"]
        assert c["extra_model_calls"] == stubs[name]["second_model_calls"]


# --- stored results and re-run ---------------------------------------------------


def _prepared_map(rows: list[combined.PreparedRow]) -> dict[str, combined.PreparedRow]:
    return {row.id: row for row in rows}


def test_load_stored_multilingual_uses_row_decisions_and_checks_consistency(tmp_path: Path) -> None:
    prepared = _prepared_map([_row("a", "retrieve"), _row("b", "skip", eligible=False)])
    data: dict[str, Any] = {
        "checkpoint": "/x/models--org--laya-multilingual/snapshots/abc",
        "threshold": 0.8,
        "with_laya": {
            "wrong_skip": {"numerator": 0, "denominator": 1, "rate": 0.0},
            "false_retrieve": {"numerator": 0, "denominator": 1, "rate": 0.0},
        },
        "rows": [
            {"id": "a", "baseline_retrieve": False, "classifier_ms": 5.0, "promoted": True},
            {"id": "b", "baseline_retrieve": True, "classifier_ms": None, "promoted": False},
        ],
    }
    path = tmp_path / "m.json"
    path.write_text(json.dumps(data))
    source = combined.load_stored_multilingual(path, "m", prepared)
    assert source.decisions == {"a": True, "b": False}
    assert source.origin == combined.STORED_ORIGIN
    # Row b's stored gate decision (True) differs from the gate now (False).
    assert source.consistency["gate_mismatch_ids"] == ["b"]
    assert source.consistency["consistent"] is False


def test_load_stored_learn_applies_per_turn_cutoffs_to_holdout_only(tmp_path: Path) -> None:
    prepared = _prepared_map(
        [_row("first", "retrieve"), _row("later", "retrieve"), _row("off", "skip", eligible=False)]
    )

    def row(row_id: str, score: float | None, first_turn: bool, eligible: bool = True) -> dict[str, Any]:
        return {
            "id": row_id,
            "baseline_retrieve": False,
            "eligible": eligible,
            "first_turn": first_turn,
            "learn": score,
        }

    data = {
        "thresholds_from_calibration": {"learn": 0.86, "learn_first_turn": 0.65},
        "holdout": {
            "learn_by_turn": {
                "wrong_skip": {"numerator": 1, "denominator": 2},
                "false_retrieve": {"numerator": 0, "denominator": 1},
            }
        },
        "holdout_rows": [
            row("first", 0.7, True),  # above the first-turn cutoff only
            row("later", 0.7, False),  # below the continuing cutoff
            row("off", None, False, eligible=False),
        ],
        "calibration_rows": [row("calibration-only", 0.99, False)],
    }
    path = tmp_path / "learn.json"
    path.write_text(json.dumps(data))
    source = combined.load_stored_learn(path, "learn", prepared)
    assert source.decisions == {"first": True, "later": False, "off": False}
    assert "calibration-only" not in source.decisions
    assert source.cutoffs == {"learn": 0.86, "learn_first_turn": 0.65}
    result = combined.evaluate_source(list(prepared.values()), source, COST)
    assert result["reproduces_file_summary"]["match"] is True
    assert result["coverage"]["eligible_rows_without_decision"] == 0


class _StubClassifier:
    def __init__(self, scores: dict[str, float | None], fail: set[str] = frozenset()) -> None:  # type: ignore[assignment]
        self.scores = scores
        self.fail = fail
        self.seen: list[str] = []

    def score(self, message: str, history: Any, titles: Any) -> float | None:
        self.seen.append(message)
        if message in self.fail:
            raise RuntimeError("boom")
        return self.scores.get(message)


def test_rerun_source_scores_eligible_rows_only_and_survives_errors() -> None:
    rows = [
        _row("hi", "retrieve", message="hi", first_turn=True),
        _row("lo", "retrieve", message="lo"),
        _row("bad", "retrieve", message="bad"),
        _row("busy", "retrieve", message="busy"),
        _row("skipped", "skip", message="skipped", eligible=False),
    ]
    classifier = _StubClassifier({"hi": 0.7, "lo": 0.5}, fail={"bad"})
    source = combined.rerun_source(
        classifier, rows, ["Title"], name="rerun", threshold=0.8, first_turn_threshold=0.6
    )
    assert source.origin == combined.RERUN_ORIGIN
    assert source.decisions == {
        "hi": True, "lo": False, "bad": False, "busy": False, "skipped": False
    }
    assert "skipped" not in classifier.seen
    assert source.cutoffs == {"threshold": 0.8, "first_turn_threshold": 0.6}


def test_probe_reports_why_laya_cannot_run(tmp_path: Path) -> None:
    probe = combined.probe_laya_runtime(None)
    assert probe["can_rerun"] is False
    assert "no --checkpoint was given" in probe["reason_if_not"]
    missing = combined.probe_laya_runtime(tmp_path)
    assert "model.safetensors" in missing["reason_if_not"]


def test_main_runs_offline_and_writes_json_with_run_block(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    output = tmp_path / "out.json"
    code = combined.main(["--results-dir", str(tmp_path / "none"), "--json-output", str(output)])
    assert code == 0
    data = json.loads(output.read_text())
    assert data["rows"] == 295
    assert data["sources"] == {}
    assert {item["name"] for item in data["sources_unavailable"]} == {
        "laya_multilingual_0.8",
        "laya_typed_decisions_0.8",
        "laya_learn_per_turn_holdout",
    }
    assert "git_sha" in data["run"] and data["run"]["generated_at_utc"].endswith("Z")
    assert "not tuned" in data["cutoff_note"]
    assert "STUB MODEL BOUND" in data["bound_note"]
    printed = capsys.readouterr().out
    assert "Wilson 95%" in printed and "49.4%" in printed
