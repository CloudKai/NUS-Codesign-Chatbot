"""Score retrieved passages against hand-annotated facts, with no model loaded here.

``run`` takes an optional cross-encoder (``encoder``), a Laya judge (``judge``) or saved
candidate orders. Loading those models stays in ``evaluate_passage_support``.
"""

from __future__ import annotations

import hashlib
import json
from time import perf_counter
from typing import Any, Sequence

from scripts.evals.lib.fixtures import load_materials
from scripts.evals.lib.metrics import interval
from scripts.evals.lib.offline import OfflineCourseSearch, rank_hits
from scripts.evals.lib.paths import DATASET_DIR
from scripts.evals.lib.turn_state import EVIDENCE_QUESTION, decide, evidence_state

def candidates(search: OfflineCourseSearch, case: dict[str, Any]) -> list[dict[str, Any]]:
    """Retrieve the reviewed candidates, refusing changed passages or stale annotations."""
    rows = []
    for h in rank_hits(search.search(case["question"]))[:8]:
        key = f"{h.material_id}/{h.page}"
        label = case["passages"][key]
        text = h.text[:1800]
        if hashlib.sha256(text.encode()).hexdigest() != label["sha256"]:
            raise ValueError(f"Passage changed: {key}")
        if not set(label["facts"]) <= set(range(len(case["facts"]))):
            raise ValueError(f"Unknown fact in {key}")
        rows.append(dict(key=key, text=text, facts=label["facts"]))
    if {r["key"] for r in rows} != set(case["passages"]):
        raise ValueError("Re-review the changed candidate set")
    return rows


def coverage(rows: Sequence[dict[str, Any]], facts: list[str]) -> str:
    """Return answer sufficiency from the union of independently annotated facts."""
    supported = {fact for row in rows for fact in row["facts"]}
    return (
        "sufficient" if len(supported) == len(facts) else "partial" if supported else "insufficient"
    )


def run(
    encoder: Any = None, judge: Any = None, orders: dict[str, Any] | None = None
) -> dict[str, Any]:
    """Score the same returned texts using page relevance and fact-level sufficiency."""
    cases = json.loads((DATASET_DIR / "passage_fact_labels.json").read_text())
    search = OfflineCourseSearch(load_materials())
    rankings = []
    judgments = []
    for case in cases:
        passages = candidates(search, case)
        pools = {"lexical": passages}
        elapsed = None
        if encoder is not None:
            start = perf_counter()
            scores = encoder.predict([(case["question"], p["text"]) for p in passages])
            elapsed = (perf_counter() - start) * 1000
            pools["reranked"] = [
                p for _, p in sorted(zip(scores, passages, strict=True), key=lambda pair: -pair[0])
            ]
        elif orders:
            by_id = {p["key"]: p for p in passages}
            order = orders[case["id"]]
            if sorted(order) != sorted(by_id):
                raise ValueError("Reranker candidates differ from reviewed pool")
            pools["reranked"] = [by_id[key] for key in order]
        for method, ordered in pools.items():
            top = ordered[:4]
            rankings.append(
                dict(
                    id=case["id"],
                    method=method,
                    order=[p["key"] for p in ordered],
                    relevant_at_four=sum(bool(p["facts"]) for p in top),
                    expected_page_hit=any(p["facts"] for p in top),
                    support=coverage(top, case["facts"]),
                    added_ms=elapsed if method == "reranked" else 0,
                )
            )
        if judge:
            contexts = {p["key"]: [p] for p in passages}
            contexts.update({k: v[:4] for k, v in pools.items()})
            for name, context in contexts.items():
                text = evidence_state(case["question"], "\n".join(p["text"] for p in context))
                prediction, ms = decide(judge, text, EVIDENCE_QUESTION)
                judgments.append(
                    dict(
                        id=case["id"],
                        context=name,
                        passages=[p["key"] for p in context],
                        gold=coverage(context, case["facts"]),
                        prediction=prediction["sufficiency"],
                        ms=ms,
                    )
                )
    metrics = {}
    for method in {r["method"] for r in rankings}:
        group = [r for r in rankings if r["method"] == method]
        metrics[method] = dict(
            page_recall_at_four=interval(sum(r["expected_page_hit"] for r in group), len(group)),
            all_facts_at_four=interval(
                sum(r["support"] == "sufficient" for r in group), len(group)
            ),
            relevant_passages_at_four=interval(
                sum(r["relevant_at_four"] for r in group), 4 * len(group)
            ),
        )
    incomplete = [r for r in judgments if r["gold"] != "sufficient"]
    false = sum(r["prediction"] == "sufficient" for r in incomplete)
    return dict(
        rankings=rankings,
        metrics=metrics,
        judgments=judgments,
        decision_coverage=interval(
            sum(r["prediction"] is not None for r in judgments), len(judgments)
        ),
        false_sufficient_per_incomplete=interval(false, len(incomplete)),
        false_sufficient_per_decided_incomplete=interval(
            false, sum(r["prediction"] is not None for r in incomplete)
        ),
    )
