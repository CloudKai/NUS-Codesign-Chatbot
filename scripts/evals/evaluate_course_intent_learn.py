"""Fit and evaluate a fixed Laya Learn bundle on synthetic course messages."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from collections.abc import Mapping, Sequence
from pathlib import Path
from time import perf_counter
from typing import Any

from backend.course_intent import (
    course_intent_questions,
    course_intent_state,
    is_first_student_turn,
    learner_course_score,
    load_vega_reader,
)
from scripts.evals.lib.fixtures import (
    eval_course_titles,
    load_materials,
    load_messages,
    load_questions,
)
from scripts.evals.lib.gate import GateDecision, gate_decision
from scripts.evals.lib.metrics import false_retrieve_rate, p95_ms as _p95_ms, wrong_skip_rate
from scripts.evals.lib.offline import block_network
from scripts.evals.lib.paths import MATERIALS_PATH, MESSAGES_PATH, QUESTIONS_PATH


def split_messages(
    messages: Sequence[Mapping[str, Any]],
) -> dict[str, list[Mapping[str, Any]]]:
    """Keep messages linked to a question, and exact duplicates, in one split."""
    splits: dict[str, list[Mapping[str, Any]]] = {
        "train": [], "calibration": [], "holdout": []
    }
    linked = {
        " ".join(row["message"].casefold().split()): row["question_id"]
        for row in messages if row["question_id"]
    }
    for row in messages:
        message = " ".join(row["message"].casefold().split())
        group = linked.get(message) or row["question_id"] or message
        digest = hashlib.sha256(f"course-intent-learn-v1:{group}".encode()).digest()
        bucket = int.from_bytes(digest[:4], "big") % 100
        split = "train" if bucket < 50 else "calibration" if bucket < 75 else "holdout"
        splits[split].append(row)
    return splits


def evaluate_routes(
    rows: Sequence[Mapping[str, Any]], score_key: str, threshold: float,
    *, first_turn_threshold: float | None = None,
) -> dict[str, Any]:
    """Score the complete gate, including rows that never reach the learner."""
    def promoted(row: Mapping[str, Any]) -> bool:
        cutoff = (first_turn_threshold if first_turn_threshold is not None and row["first_turn"]
                  else threshold)
        return row[score_key] is not None and row[score_key] >= cutoff

    decisions = [
        (row["expected"], row["baseline_retrieve"] or promoted(row))
        for row in rows
    ]
    return {
        "wrong_skip": wrong_skip_rate(decisions),
        "false_retrieve": false_retrieve_rate(decisions),
        "promoted_outside_course_scope": sum(
            promoted(row) and row["expected_scope"] not in {"course", "both"}
            for row in rows
        ),
    }


def select_threshold(
    rows: Sequence[Mapping[str, Any]], score_key: str, *, continuing_cutoff: float | None = None
) -> float | None:
    """Minimize calibration misses subject to false retrieves below 10%."""
    candidates = {0.0, 1.0, *(r[score_key] for r in rows if r[score_key] is not None)}
    ranked = []
    for threshold in candidates:
        if continuing_cutoff is None:
            metrics = evaluate_routes(rows, score_key, threshold)
        else:
            if threshold > continuing_cutoff:
                continue
            metrics = evaluate_routes(rows, score_key, continuing_cutoff, first_turn_threshold=threshold)
        wrong_skip = metrics["wrong_skip"]["rate"]
        false_retrieve = metrics["false_retrieve"]["rate"]
        if wrong_skip is not None and false_retrieve is not None and false_retrieve < 0.10:
            ranked.append((wrong_skip, false_retrieve, -threshold))
    return -min(ranked)[2] if ranked else None


def main(argv: Sequence[str] | None = None) -> int:
    """Fit local synthetic data and report one untouched holdout evaluation."""
    from backend.coaching.evidence_scope import local_course_intent_candidate

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--checkpoint", type=Path, required=True)
    parser.add_argument("--bundle-output", type=Path, required=True)
    parser.add_argument("--json-output", type=Path, required=True)
    args = parser.parse_args(argv)
    if args.bundle_output.resolve() == args.json_output.resolve():
        parser.error("bundle and JSON outputs must be different files")
    if args.bundle_output.exists() or args.json_output.exists():
        parser.error("use fresh output paths")
    os.environ["HF_HUB_OFFLINE"] = "1"
    block_network()
    from laya import Learner

    materials = load_materials(MATERIALS_PATH)
    questions = load_questions(QUESTIONS_PATH, materials)
    messages = load_messages(
        MESSAGES_PATH, materials, [row["id"] for row in questions]
    )
    if not all(row.get("synthetic") is True for row in messages):
        parser.error("use synthetic labels only")
    splits = split_messages(messages)
    titles = eval_course_titles(materials)
    decision_question = course_intent_questions()

    def candidate(row: Mapping[str, Any], decision: GateDecision) -> bool:
        return local_course_intent_candidate(
            row["message"],
            intent=decision.intent,
            evidence_scoped=bool(
                decision.scope_cleared or row["attachments"] or row["selected_sources"]
            ),
            searched=decision.retrieve,
        )

    def state(row: Mapping[str, Any]) -> str:
        return course_intent_state(row["message"], row["history"], titles)

    training = [
        (
            state(row),
            {"retrieval": "course_evidence" if row["expected_scope"] in {"course", "both"}
             else "no_course_evidence"},
        )
        for row in splits["train"]
        if candidate(row, gate_decision(row))
    ]
    print(f"Fitting Vega on {len(training)} eligible synthetic turns.", flush=True)
    started = perf_counter()
    reader = load_vega_reader(args.checkpoint)
    base = Learner(decision_question, reader=reader, auto=False, cache=0)
    fitted = Learner(decision_question, examples=training, reader=reader, auto=False, cache=0)
    fit_seconds = perf_counter() - started
    fitted.save_bundle(args.bundle_output)
    # Evaluate from the same frozen artifact the app loads.
    restored = Learner(bundle=args.bundle_output, reader=reader, auto=False, cache=0)

    def score_split(name: str) -> list[dict[str, Any]]:
        print(f"Scoring {len(splits[name])} {name} turns.", flush=True)
        results = []
        for row in splits[name]:
            decision = gate_decision(row)
            result = {
                "id": row["id"],
                "expected": row["expected_decision"],
                "expected_scope": row["expected_scope"],
                "baseline_retrieve": decision.retrieve,
                "baseline_only": None,
                "first_turn": is_first_student_turn(row["history"]),
                "eligible": candidate(row, decision),
            }
            for key, classifier in (("vega", base), ("learn", restored)):
                score = readout = elapsed_ms = None
                if result["eligible"]:
                    began = perf_counter()
                    score, readout = learner_course_score(classifier.decide(state(row)))
                    elapsed_ms = round((perf_counter() - began) * 1000, 2)
                result[key] = score
                result[f"{key}_readout"] = readout
                result[f"{key}_ms"] = elapsed_ms
            results.append(result)
        return results

    calibration = score_split("calibration")
    thresholds = {key: select_threshold(calibration, key) for key in ("vega", "learn")}
    continuing = thresholds["learn"]
    first = (select_threshold(calibration, "learn", continuing_cutoff=continuing)
             if continuing is not None else None)
    holdout = score_split("holdout")
    report = {
        "split_counts": {name: len(rows) for name, rows in splits.items()},
        "split_ids": {name: [row["id"] for row in rows] for name, rows in splits.items()},
        "trained_examples": len(training),
        "fit_and_load_seconds": round(fit_seconds, 2),
        "training_report": fitted.report,
        "thresholds_from_calibration": {**thresholds, "learn_first_turn": first},
        "holdout": {
            "learn_by_turn": evaluate_routes(holdout, "learn", continuing, first_turn_threshold=first)
            if continuing is not None and first is not None else None,
            "baseline": evaluate_routes(holdout, "baseline_only", 1.0),
            **{
                key: {
                    "metrics": evaluate_routes(holdout, key, threshold)
                    if threshold is not None else None,
                    "inference_p95_ms": _p95_ms(
                        [row[f"{key}_ms"] for row in holdout if row[f"{key}_ms"] is not None]
                    ),
                    "head_predictions": sum(row[f"{key}_readout"] == "head" for row in holdout),
                }
                for key, threshold in thresholds.items()
            },
        },
    }
    args.json_output.write_text(
        json.dumps({**report, "calibration_rows": calibration, "holdout_rows": holdout}, indent=2)
        + "\n",
        encoding="utf-8",
    )
    print(json.dumps({key: value for key, value in report.items() if key != "split_ids"}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
