"""Combined offline gate evaluation: gate, gate + Laya, gate + Laya + title wording.

Offline only: no network, no AWS, no model call. It composes three arms over
all gate messages and reports wrong-skip, false-retrieve and extra-call/token
counts per category, each rate with a Wilson 95% interval.

Arms:

* (a) the existing rules-based gate (``evaluate_retrieval.gate_decision``).
* (b) gate + Laya: an ambiguous turn the gate skipped is promoted to course
  retrieval when the local course-intent classifier scores at or above its
  cutoff (``backend.coaching.execution`` rule). The cutoffs are the existing
  ones. They are read from the stored results or the setting; this script never
  fits or searches a cutoff, and nothing here is tuned on the gate rows.
* (c) gate + Laya + course-title wording: arm (b) plus the SOURCE CHECK rule
  with course titles. The wording effect is a STUB MODEL BOUND, not a
  measurement: ``oracle`` (best case), ``mock_rule`` and ``flag_all`` (worst case
  for false retrieves and extra calls). Only a live run measures wording.

Laya decisions come from one of two places, and each source says which:

* ``re-run``: ``--checkpoint`` loads the local weights and scores every eligible
  row in this process (needs the ``laya`` package and the weights).
* ``from stored results, not re-run``: per-row decisions stored by earlier runs
  (``.agents/tasks/phase3d-work/*.json``). Those files cover only some rows, so
  the unscored eligible rows are bracketed (see ``MODES``).
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import sys
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

_PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from scripts.evals.lib.fixtures import (  # noqa: E402
    eval_course_titles,
    load_materials,
    load_messages,
    load_questions,
)
from scripts.evals.lib.offline import block_network  # noqa: E402
from scripts.evals.lib.output import write_json_output  # noqa: E402
from scripts.evals.lib.paths import MATERIALS_PATH, MESSAGES_PATH, QUESTIONS_PATH  # noqa: E402

# Moved to scripts/evals/lib/prepared_rows.py so benchmark_course_intent can use them
# without importing this command; re-exported for existing callers.
from scripts.evals.lib.prepared_rows import PreparedRow as PreparedRow  # noqa: E402
from scripts.evals.lib.prepared_rows import prepare_rows as prepare_rows  # noqa: E402

# Moved to scripts/evals/lib so compare_routing_arms shares the interval maths and the
# stored Laya loaders without importing this command; re-exported for existing callers.
from scripts.evals.lib.intervals import SMALL_N as SMALL_N  # noqa: E402
from scripts.evals.lib.intervals import VERY_SMALL_N as VERY_SMALL_N  # noqa: E402
from scripts.evals.lib.intervals import Z_95 as Z_95  # noqa: E402
from scripts.evals.lib.intervals import format_ci as format_ci  # noqa: E402
from scripts.evals.lib.intervals import rate_ci as rate_ci  # noqa: E402
from scripts.evals.lib.intervals import sample_mark as sample_mark  # noqa: E402
from scripts.evals.lib.intervals import wilson_interval as wilson_interval  # noqa: E402
from scripts.evals.lib.laya_sources import MODES as MODES  # noqa: E402
from scripts.evals.lib.laya_sources import RERUN_ORIGIN as RERUN_ORIGIN  # noqa: E402
from scripts.evals.lib.laya_sources import STORED_ORIGIN as STORED_ORIGIN  # noqa: E402
from scripts.evals.lib.laya_sources import LayaSource as LayaSource  # noqa: E402
from scripts.evals.lib.laya_sources import (  # noqa: E402
    _stored_consistency as _stored_consistency,
)
from scripts.evals.lib.laya_sources import (  # noqa: E402
    load_stored_learn as load_stored_learn,
)
from scripts.evals.lib.laya_sources import (  # noqa: E402
    load_stored_multilingual as load_stored_multilingual,
)
from scripts.evals.lib.laya_sources import promotion  # noqa: E402

PHASE3D_DIR = _PROJECT_ROOT / ".agents" / "tasks" / "phase3d-work"
STUB_NAMES = ("oracle", "mock_rule", "flag_all")
BOUND_NOTE = (
    "Arm (c) wording is a STUB MODEL BOUND, not a measurement: oracle flags exactly the "
    "rows labelled retrieve, mock_rule is the repo's keyword rule, flag_all flags every "
    "stamped turn. Only a live run measures whether the titles change a real model's flags."
)
CUTOFF_NOTE = (
    "The existing cutoffs were used and not tuned on these rows: the 0.8 default "
    "(settings.local_course_intent_threshold) and, for Laya Learn, the two cutoffs "
    "selected earlier on the calibration split. This script reads them and never "
    "fits or searches a cutoff."
)


# ------------------------------------------------------------------- Laya sources


def probe_laya_runtime(checkpoint: Path | None) -> dict[str, Any]:
    """Say whether the Laya runtime can run here, without importing it."""
    laya = importlib.util.find_spec("laya") is not None
    vegaml = importlib.util.find_spec("vegaml") is not None
    weights = bool(checkpoint and (checkpoint / "model.safetensors").is_file())
    reasons = []
    if not laya:
        reasons.append("the 'laya' package is not installed")
    if checkpoint is None:
        reasons.append("no --checkpoint was given")
    elif not weights:
        reasons.append(f"{checkpoint} has no model.safetensors")
    return {
        "laya_installed": laya,
        "vegaml_installed": vegaml,
        "checkpoint": None if checkpoint is None else str(checkpoint),
        "weights_found": weights,
        "can_rerun": bool(laya and weights),
        "reason_if_not": "; ".join(reasons),
    }


def rerun_source(
    classifier: Any,
    prepared: Sequence[PreparedRow],
    titles: Sequence[str],
    *,
    name: str,
    threshold: float,
    first_turn_threshold: float | None = None,
) -> LayaSource:
    """Score every eligible row with a loaded classifier at the given cutoffs.

    A classifier exception or a busy abstention is "no score", as in
    production, so the row is not promoted.
    """
    decisions: dict[str, bool] = {}
    for row in prepared:
        promoted = False
        if row.eligible:
            try:
                score = classifier.score(row.message, list(row.history), titles)
            except Exception:  # noqa: BLE001 - production treats any failure as no score
                score = None
            cutoff = (
                first_turn_threshold
                if first_turn_threshold is not None and row.first_turn
                else threshold
            )
            promoted = score is not None and score >= cutoff
        decisions[row.id] = promoted
    return LayaSource(
        name=name,
        origin=RERUN_ORIGIN,
        description="local classifier scored every eligible row",
        cutoffs={"threshold": threshold, "first_turn_threshold": first_turn_threshold},
        decisions=decisions,
    )


# ------------------------------------------------------------------ arm composition


def _flag_oracle(row: PreparedRow) -> bool:
    return row.expected == "retrieve"


def _flag_mock_rule(row: PreparedRow) -> bool:
    from backend.mock_provider import mock_flags_needs_sources

    return mock_flags_needs_sources(row.message)


def _flag_all(row: PreparedRow) -> bool:
    return True


STUB_MODELS: Mapping[str, Callable[[PreparedRow], bool]] = {
    "oracle": _flag_oracle,
    "mock_rule": _flag_mock_rule,
    "flag_all": _flag_all,
}


@dataclass(frozen=True)
class Outcome:
    """One row through all arms."""

    id: str
    category: str
    expected: str
    gate: bool
    laya_promoted: bool
    laya_eligible: bool
    laya_unscored: bool
    stamped: bool
    flagged: Mapping[str, bool]

    @property
    def with_laya(self) -> bool:
        return self.gate or self.laya_promoted

    def with_wording(self, stub: str) -> bool:
        return self.with_laya or self.flagged[stub]


def compose(
    prepared: Sequence[PreparedRow], source: LayaSource | None, mode: str
) -> list[Outcome]:
    """Run every row through the three arms.

    Args:
        prepared: Gate rows with decisions.
        source: Laya decisions, or ``None`` for no Laya at all.
        mode: One of ``MODES``; sets how eligible rows with no decision are treated.

    A row is "stamped" (sent the SOURCE CHECK rule) when the gate left it a
    second chance and Laya did not promote it. A stub flag on a stamped row
    is the extra model call.
    """
    if mode not in MODES:
        raise ValueError(f"mode must be one of {', '.join(MODES)}")
    outcomes = []
    for row in prepared:
        promoted, unscored = promotion(row, source, mode)
        if unscored and mode == "scored_only":
            continue
        stamped = row.second_chance and not promoted and not row.gate_retrieve
        outcomes.append(
            Outcome(
                id=row.id,
                category=row.category,
                expected=row.expected,
                gate=row.gate_retrieve,
                laya_promoted=promoted and not row.gate_retrieve,
                laya_eligible=row.eligible and source is not None,
                laya_unscored=unscored,
                stamped=stamped,
                flagged={name: stamped and fn(row) for name, fn in STUB_MODELS.items()},
            )
        )
    return outcomes


@dataclass(frozen=True)
class CostModel:
    """Sizes used to turn counts into token estimates (all estimates)."""

    rule_chars: int
    titles_chars: int
    excerpt_cap_chars: int
    second_call_input_tokens: int = 7100
    second_call_output_tokens: int = 300


def default_cost_model(materials: Sequence[Mapping[str, Any]]) -> CostModel:
    """Sizes from the production prompt text and settings."""
    from backend.prompts.composer import _SOURCE_NEED_INSTRUCTION, source_check_titles_block
    from backend.settings import settings

    titles = eval_course_titles(materials)
    return CostModel(
        rule_chars=len(_SOURCE_NEED_INSTRUCTION) + 1,
        titles_chars=len(source_check_titles_block(titles)) + 1,
        excerpt_cap_chars=int(settings.fast_chat_retrieval_max_chars),
    )


def _cell(
    outcomes: Sequence[Outcome],
    retrieved: Callable[[Outcome], bool],
    cost: CostModel,
    *,
    wording_stub: str | None = None,
) -> dict[str, Any]:
    """Metrics for one arm over a set of rows."""
    expected_retrieve = [o for o in outcomes if o.expected == "retrieve"]
    expected_skip = [o for o in outcomes if o.expected == "skip"]
    extra_searches = sum(1 for o in outcomes if retrieved(o) and not o.gate)
    if wording_stub is None:
        stamped = flagged = 0
    else:
        stamped = sum(1 for o in outcomes if o.stamped)
        flagged = sum(1 for o in outcomes if o.flagged[wording_stub])
    wording_chars = stamped * (cost.rule_chars + cost.titles_chars)
    excerpt_chars = extra_searches * cost.excerpt_cap_chars
    return {
        "rows": len(outcomes),
        "retrieve_rows": len(expected_retrieve),
        "skip_rows": len(expected_skip),
        "wrong_skip": rate_ci(sum(1 for o in expected_retrieve if not retrieved(o)), len(expected_retrieve)),
        "false_retrieve": rate_ci(sum(1 for o in expected_skip if retrieved(o)), len(expected_skip)),
        "laya_eligible_rows": sum(1 for o in outcomes if o.laya_eligible),
        "extra_retrieval_searches": extra_searches,
        "extra_model_calls": flagged,
        "stamped_turns": stamped,
        "wording_prompt_chars": wording_chars,
        "wording_prompt_tokens_4cpt": round(wording_chars / 4),
        "wording_prompt_tokens_3cpt": round(wording_chars / 3),
        "excerpt_chars_upper_bound": excerpt_chars,
        "excerpt_tokens_upper_bound_4cpt": round(excerpt_chars / 4),
        "excerpt_tokens_upper_bound_3cpt": round(excerpt_chars / 3),
        "second_call_input_tokens": flagged * cost.second_call_input_tokens,
        "second_call_output_tokens": flagged * cost.second_call_output_tokens,
    }


def _arm_block(
    outcomes: Sequence[Outcome],
    retrieved: Callable[[Outcome], bool],
    cost: CostModel,
    wording_stub: str | None = None,
) -> dict[str, Any]:
    by_category: dict[str, list[Outcome]] = defaultdict(list)
    for outcome in outcomes:
        by_category[outcome.category].append(outcome)
    return {
        "overall": _cell(outcomes, retrieved, cost, wording_stub=wording_stub),
        "by_category": {
            category: _cell(rows, retrieved, cost, wording_stub=wording_stub)
            for category, rows in sorted(by_category.items())
        },
    }


def summarize(outcomes: Sequence[Outcome], cost: CostModel) -> dict[str, Any]:
    """All three arms over one set of composed rows."""
    return {
        "rows": len(outcomes),
        "laya_eligible_rows": sum(1 for o in outcomes if o.laya_eligible),
        "laya_unscored_eligible_rows": sum(1 for o in outcomes if o.laya_unscored),
        "arm_a_gate": _arm_block(outcomes, lambda o: o.gate, cost),
        "arm_b_gate_laya": _arm_block(outcomes, lambda o: o.with_laya, cost),
        "arm_c_gate_laya_wording_STUB_BOUND": {
            stub: _arm_block(outcomes, lambda o, s=stub: o.with_wording(s), cost, wording_stub=stub)
            for stub in STUB_NAMES
        },
    }


def evaluate_source(
    prepared: Sequence[PreparedRow], source: LayaSource, cost: CostModel
) -> dict[str, Any]:
    """Coverage, stored-summary reproduction and the three modes for one source."""
    by_id = {row.id: row for row in prepared}
    eligible = [row for row in prepared if row.eligible]
    scored = [row for row in eligible if row.id in source.decisions]
    covered = [by_id[i] for i in source.decisions if i in by_id]
    reproduction = None
    if source.file_summary is not None:
        recomputed = summarize(compose(covered, source, "floor"), cost)["arm_b_gate_laya"]["overall"]
        expected = source.file_summary
        reproduction = {
            "file": {k: [expected[k]["numerator"], expected[k]["denominator"]] for k in expected},
            "recomputed": {
                k: [recomputed[k]["numerator"], recomputed[k]["denominator"]] for k in expected
            },
        }
        reproduction["match"] = reproduction["file"] == reproduction["recomputed"]
    return {
        "description": source.description,
        "origin": source.origin,
        "file": source.file,
        "cutoffs": dict(source.cutoffs),
        "coverage": {
            "gate_rows": len(prepared),
            "rows_with_stored_decision": len(covered),
            "eligible_rows": len(eligible),
            "eligible_rows_with_decision": len(scored),
            "eligible_rows_without_decision": len(eligible) - len(scored),
            "not_eligible_rows": len(prepared) - len(eligible),
        },
        "consistency_with_gate_at_this_commit": dict(source.consistency),
        "reproduces_file_summary": reproduction,
        "modes": {mode: summarize(compose(prepared, source, mode), cost) for mode in MODES},
    }


def build_result(
    messages: Sequence[Mapping[str, Any]],
    sources: Sequence[LayaSource],
    cost: CostModel,
    *,
    probe: Mapping[str, Any],
    unavailable: Sequence[Mapping[str, str]] = (),
) -> dict[str, Any]:
    """The full result: arm (a) on all rows plus each Laya source."""
    prepared = prepare_rows(messages)
    return {
        "definition": __doc__,
        "cutoff_note": CUTOFF_NOTE,
        "bound_note": BOUND_NOTE,
        "modes": dict(MODES),
        "small_sample_rule": f"S = fewer than {SMALL_N} rows, VS = fewer than {VERY_SMALL_N}",
        "cost_model": {
            "rule_chars": cost.rule_chars,
            "titles_chars": cost.titles_chars,
            "excerpt_cap_chars": cost.excerpt_cap_chars,
            "second_call_input_tokens": cost.second_call_input_tokens,
            "second_call_output_tokens": cost.second_call_output_tokens,
            "second_call_tokens_origin": "user-reported per-call mean from the Phase 3b live run",
            "excerpt_tokens_origin": "upper bound: every newly searched turn fills the excerpt cap",
        },
        "rows": len(prepared),
        "laya_runtime": dict(probe),
        "sources_unavailable": [dict(item) for item in unavailable],
        "all_rows_arm_a": summarize(compose(prepared, None, "floor"), cost),
        "sources": {s.name: evaluate_source(prepared, s, cost) for s in sources},
    }


# ----------------------------------------------------------------------- reporting


def _mode_set(result_source: Mapping[str, Any], mode: str) -> Mapping[str, Any]:
    return result_source["modes"][mode]


def _arm_rows(summary: Mapping[str, Any]) -> list[tuple[str, Mapping[str, Any]]]:
    arms: list[tuple[str, Mapping[str, Any]]] = [
        ("(a) gate", summary["arm_a_gate"]),
        ("(b) gate + Laya", summary["arm_b_gate_laya"]),
    ]
    for stub, block in summary["arm_c_gate_laya_wording_STUB_BOUND"].items():
        arms.append((f"(c) + wording, stub bound `{stub}`", block))
    return arms


def _md_table(header: Sequence[str], rows: Sequence[Sequence[str]]) -> list[str]:
    lines = ["| " + " | ".join(header) + " |", "|" + "|".join("---" for _ in header) + "|"]
    lines += ["| " + " | ".join(row) + " |" for row in rows]
    return lines


def _extras(cell: Mapping[str, Any]) -> list[str]:
    return [
        str(cell["extra_retrieval_searches"]),
        str(cell["extra_model_calls"]),
        str(cell["stamped_turns"]),
        f"{cell['wording_prompt_tokens_4cpt']:,} to {cell['wording_prompt_tokens_3cpt']:,}",
        f"{cell['excerpt_tokens_upper_bound_4cpt']:,} to {cell['excerpt_tokens_upper_bound_3cpt']:,}",
        f"{cell['second_call_input_tokens']:,} / {cell['second_call_output_tokens']:,}",
    ]


EXTRA_HEADER = [
    "Extra searches",
    "Extra model calls (stub)",
    "Rule stamped on turns",
    "Rule + titles prompt tokens (4 to 3 chars/token, estimate)",
    "Excerpt tokens, upper bound (4 to 3 chars/token)",
    "Second-call tokens in/out (estimate)",
]


def _overall_table(summary: Mapping[str, Any]) -> list[str]:
    rows = []
    for label, block in _arm_rows(summary):
        cell = block["overall"]
        rows.append([label, format_ci(cell["wrong_skip"]), format_ci(cell["false_retrieve"]), *_extras(cell)])
    return _md_table(["Arm", "Wrong skip", "False retrieve", *EXTRA_HEADER], rows)


def _category_tables(summary: Mapping[str, Any], *, only_gate: bool = False) -> list[str]:
    arms = _arm_rows(summary)[:1] if only_gate else _arm_rows(summary)
    categories = sorted(summary["arm_a_gate"]["by_category"])
    cell = lambda block, category: block["by_category"][category]  # noqa: E731
    lines: list[str] = []
    for title, key in (("Wrong skip", "wrong_skip"), ("False retrieve", "false_retrieve")):
        lines += [f"**{title} by category**", ""]
        rows = []
        for category in categories:
            first = cell(arms[0][1], category)
            count = first["retrieve_rows"] if key == "wrong_skip" else first["skip_rows"]
            rows.append([category, str(count), *[format_ci(cell(block, category)[key]) for _, block in arms]])
        lines += _md_table(["Category", "Rows", *[label for label, _ in arms]], rows) + [""]
    if only_gate:
        return lines
    lines += ["**Extra calls and tokens by category** (per cell: extra searches / extra model calls / rule stamped on turns / rule + titles tokens 4 to 3 cpt / excerpt tokens upper bound 4 to 3 cpt)", ""]
    rows = []
    for category in categories:
        row = [category]
        for label, block in arms[1:]:
            c = cell(block, category)
            row.append(
                f"{c['extra_retrieval_searches']} / {c['extra_model_calls']} / {c['stamped_turns']} / "
                f"{c['wording_prompt_tokens_4cpt']:,} to {c['wording_prompt_tokens_3cpt']:,} / "
                f"{c['excerpt_tokens_upper_bound_4cpt']:,} to {c['excerpt_tokens_upper_bound_3cpt']:,}"
            )
        rows.append(row)
    lines += _md_table(["Category", *[label for label, _ in arms[1:]]], rows) + [""]
    return lines


def format_report(result: Mapping[str, Any], per_category_modes: Sequence[str] = ("floor",)) -> str:
    """Markdown report of the combined evaluation."""
    out = [
        "# Combined offline gate evaluation",
        "",
        f"Rows: {result['rows']}. {result['cutoff_note']}",
        "",
        result["bound_note"],
        "",
        f"Intervals are Wilson 95%. Marks: {result['small_sample_rule']}.",
        "",
        "Laya runtime here: "
        + (
            "can re-run."
            if result["laya_runtime"]["can_rerun"]
            else f"cannot re-run ({result['laya_runtime']['reason_if_not']})."
        ),
        "",
        "## Arm (a), all rows",
        "",
        *_overall_table(result["all_rows_arm_a"])[:3],
        "",
    ]
    out += [
        "### Arm (a) by category, all rows",
        "",
        *_category_tables(result["all_rows_arm_a"], only_gate=True),
    ]
    for item in result["sources_unavailable"]:
        out += [f"Source `{item['name']}` unavailable: {item['reason']}", ""]
    for name, source in result["sources"].items():
        cov = source["coverage"]
        out += [
            f"## Laya source `{name}` ({source['origin']})",
            "",
            f"{source['description']}. Cutoffs: {json.dumps(source['cutoffs'])}. File: {source['file']}.",
            "",
            f"Eligible rows {cov['eligible_rows']} of {cov['gate_rows']}; with a decision "
            f"{cov['eligible_rows_with_decision']}; without {cov['eligible_rows_without_decision']}.",
            "",
        ]
        reproduction = source["reproduces_file_summary"]
        if reproduction is not None:
            out += [f"Reproduces the stored summary: {reproduction['match']} ({json.dumps(reproduction)}).", ""]
        out += [f"Consistency with the gate at this commit: {json.dumps(source['consistency_with_gate_at_this_commit'])}", ""]
        for mode in MODES:
            summary = _mode_set(source, mode)
            out += [
                f"### Mode `{mode}`: {MODES[mode]} ({summary['rows']} rows)",
                "",
                *_overall_table(summary),
                "",
            ]
            if mode in per_category_modes:
                out += _category_tables(summary)
    return "\n".join(out).rstrip() + "\n"


# ----------------------------------------------------------------------------- CLI


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    parser.add_argument("--results-dir", type=Path, default=PHASE3D_DIR, help="folder with the stored phase3d JSON files")
    parser.add_argument("--multilingual", default="multilingual.json")
    parser.add_argument("--typed-decisions", default="typed-decisions.json")
    parser.add_argument("--learn", default="course-intent-by-turn.json")
    parser.add_argument("--checkpoint", type=Path, default=None, help="re-run Laya from local weights (needs the laya package)")
    parser.add_argument("--bundle", type=Path, default=None, help="Laya Learn bundle; with --checkpoint loads the Learn classifier")
    parser.add_argument("--threshold", type=float, default=None, help="re-run cutoff (default: the setting)")
    parser.add_argument("--first-turn-threshold", type=float, default=None)
    parser.add_argument("--per-category-modes", default="floor", help="comma list of floor, ceiling, scored_only")
    parser.add_argument("--json-output", type=Path, default=None)
    return parser


def _load_sources(
    args: argparse.Namespace, prepared: Sequence[PreparedRow], materials: Sequence[Mapping[str, Any]]
) -> tuple[list[LayaSource], list[dict[str, str]]]:
    by_id = {row.id: row for row in prepared}
    sources: list[LayaSource] = []
    unavailable: list[dict[str, str]] = []
    stored = (
        ("laya_multilingual_0.8", args.multilingual, load_stored_multilingual),
        ("laya_typed_decisions_0.8", args.typed_decisions, load_stored_multilingual),
        ("laya_learn_per_turn_holdout", args.learn, load_stored_learn),
    )
    for name, filename, loader in stored:
        path = args.results_dir / filename
        if path.is_file():
            sources.append(loader(path, name, by_id))
        else:
            unavailable.append({"name": name, "reason": f"{path} not found"})
    if args.checkpoint is not None:
        from backend.settings import settings

        if args.bundle is not None:
            from backend.course_intent import LayaLearnCourseIntentClassifier

            classifier: Any = LayaLearnCourseIntentClassifier(args.checkpoint, args.bundle)
        else:
            from backend.course_intent import LayaCourseIntentClassifier

            classifier = LayaCourseIntentClassifier(args.checkpoint)
        threshold = args.threshold if args.threshold is not None else settings.local_course_intent_threshold
        sources.append(
            rerun_source(
                classifier,
                prepared,
                eval_course_titles(materials),
                name="laya_rerun",
                threshold=threshold,
                first_turn_threshold=args.first_turn_threshold,
            )
        )
    return sources, unavailable


def main(argv: Sequence[str] | None = None) -> int:
    """Run the combined evaluation offline and print a markdown report."""
    args = build_parser().parse_args(argv)
    modes = [m for m in args.per_category_modes.split(",") if m]
    if any(m not in MODES for m in modes):
        build_parser().error(f"--per-category-modes must be from: {', '.join(MODES)}")
    block_network()
    materials = load_materials(MATERIALS_PATH)
    questions = load_questions(QUESTIONS_PATH, materials)
    messages = load_messages(
        MESSAGES_PATH, materials, [row["id"] for row in questions]
    )
    prepared = prepare_rows(messages)
    sources, unavailable = _load_sources(args, prepared, materials)
    result = build_result(
        messages,
        sources,
        default_cost_model(materials),
        probe=probe_laya_runtime(args.checkpoint),
        unavailable=unavailable,
    )
    if args.json_output is not None:
        write_json_output(args.json_output, result)
    print(format_report(result, modes))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
