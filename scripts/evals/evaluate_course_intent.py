"""Benchmark the optional Laya course classifier on synthetic messages."""

from __future__ import annotations

import argparse
import json
import os
import sys
from collections.abc import Mapping, Sequence
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from time import perf_counter
from typing import Any

_PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

_COMPARE_CATEGORIES = (
    "course_content",
    "course_logistics",
    "informal_or_multilingual",
    "upload_question",
    "follow_up",
)


def _p95_ms(values: list[float]) -> float | None:
    return round(sorted(values)[(95 * len(values) - 1) // 100], 2) if values else None


def main(argv: Sequence[str] | None = None) -> int:
    """Run the Phase 3c subset with local weights and write a JSON report."""
    from backend.coaching.evidence_scope import local_course_intent_candidate
    from backend.course_intent import LayaCourseIntentClassifier
    from scripts.evals import evaluate_retrieval as retrieval

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--checkpoint", type=Path, required=True)
    parser.add_argument("--threshold", type=float, default=0.8)
    parser.add_argument("--concurrency", type=int, default=1)
    parser.add_argument("--json-output", type=Path, required=True)
    args = parser.parse_args(argv)
    if not 0 <= args.threshold <= 1 or args.concurrency < 1:
        parser.error("threshold must be in [0, 1] and concurrency must be positive")

    os.environ["HF_HUB_OFFLINE"] = "1"
    retrieval._block_network()
    materials = retrieval.load_materials(retrieval.MATERIALS_PATH)
    questions = retrieval.load_questions(retrieval.QUESTIONS_PATH, materials)
    messages = retrieval.load_messages(
        retrieval.MESSAGES_PATH, materials, [row["id"] for row in questions]
    )
    selected = retrieval.select_live_rows(
        messages, categories=_COMPARE_CATEGORIES, expected_decision="retrieve", skip_sample=60
    )
    titles = retrieval.eval_course_titles(materials)
    started = perf_counter()
    classifier = LayaCourseIntentClassifier(args.checkpoint)
    load_ms = (perf_counter() - started) * 1000

    def evaluate(row: Mapping[str, Any]) -> dict[str, Any]:
        decision = retrieval.gate_decision(row)
        eligible = local_course_intent_candidate(
            row["message"],
            intent=decision.intent,
            evidence_scoped=bool(
                decision.scope_cleared or row["attachments"] or row["selected_sources"]
            ),
            searched=decision.retrieve,
        )
        elapsed = None
        score = None
        if eligible:
            inference_started = perf_counter()
            score = classifier.score(row["message"], row["history"], titles)
            elapsed = (perf_counter() - inference_started) * 1000
        promoted = score is not None and score >= args.threshold
        return {
            "id": row["id"],
            "category": row["category"],
            "expected": row["expected_decision"],
            "expected_scope": row["expected_scope"],
            "baseline_retrieve": decision.retrieve,
            "course_score": score,
            "classifier_ms": elapsed,
            "promoted": promoted,
        }

    started = perf_counter()
    with ThreadPoolExecutor(max_workers=args.concurrency) as pool:
        rows = list(pool.map(evaluate, selected))
    wall_seconds = perf_counter() - started
    baseline = [(row["expected"], row["baseline_retrieve"]) for row in rows]
    candidate = [
        (row["expected"], row["baseline_retrieve"] or row["promoted"])
        for row in rows
    ]
    report = {
        "checkpoint": str(args.checkpoint),
        "rows_evaluated": len(rows),
        "threshold": args.threshold,
        "concurrency": args.concurrency,
        "load_ms": round(load_ms, 2),
        "wall_seconds": round(wall_seconds, 2),
        "inferences": sum(row["course_score"] is not None for row in rows),
        "busy_abstentions": sum(
            row["classifier_ms"] is not None and row["course_score"] is None for row in rows
        ),
        "inference_p95_ms": _p95_ms(
            [row["classifier_ms"] for row in rows if row["course_score"] is not None]
        ),
        "baseline": {
            "wrong_skip": retrieval.wrong_skip_rate(baseline),
            "false_retrieve": retrieval.false_retrieve_rate(baseline),
        },
        "with_laya": {
            "wrong_skip": retrieval.wrong_skip_rate(candidate),
            "false_retrieve": retrieval.false_retrieve_rate(candidate),
            "promoted_outside_course_scope": sum(
                row["promoted"] and row["expected_scope"] not in {"course", "both"}
                for row in rows
            ),
        },
    }
    args.json_output.write_text(json.dumps({**report, "rows": rows}, indent=2) + "\n")
    print(json.dumps(report, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
