"""Compare lexical and cross-encoder ranks and judge actual retrieved evidence offline."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
from time import perf_counter
from typing import Any, Sequence

from scripts.evals import evaluate_laya_turn_decisions as base
from scripts.evals import evaluate_retrieval as retrieval
from scripts.evals.compare_turn_routes import interval, save


def candidates(search: retrieval.OfflineCourseSearch, case: dict[str, Any]) -> list[dict[str, Any]]:
    """Retrieve the reviewed candidates, refusing changed passages or stale annotations."""
    rows = []
    for h in retrieval.rank_hits(search.search(case["question"]))[:8]:
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
    cases = json.loads((base.DATA / "passage_fact_labels.json").read_text())
    search = retrieval.OfflineCourseSearch(retrieval.load_materials())
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
                text = base.evidence_state(case["question"], "\n".join(p["text"] for p in context))
                prediction, ms = base.decide(judge, text, base.EVIDENCE_QUESTION)
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


def benchmark_pages(encoder: Any) -> dict[str, Any]:
    """Compare top-four page hits on the full course benchmark within identical top-eight pools."""
    materials = retrieval.load_materials()
    search = retrieval.OfflineCourseSearch(materials)
    questions = retrieval.load_questions(retrieval.QUESTIONS_PATH, materials)
    details = []
    for row in questions:
        hits = retrieval.rank_hits(search.search(row["question"]))[:8]
        accepted = retrieval.accepted_targets(
            row["expected_material"], row["expected_pages"], row["alt_expected"]
        )
        start = perf_counter()
        scores = encoder.predict([(row["question"], h.text[:1800]) for h in hits]) if hits else []
        elapsed = (perf_counter() - start) * 1000
        reordered = [
            h for _, h in sorted(zip(scores, hits, strict=True), key=lambda pair: -pair[0])
        ]

        def page_hit(order: list[retrieval.RankedHit]) -> bool:
            return any(h.page in accepted.get(h.material_id, ()) for h in order[:4])

        details.append(
            dict(
                id=row["id"],
                lexical=page_hit(hits),
                reranked=page_hit(reordered),
                candidates=[f"{h.material_id}/{h.page}" for h in hits],
                reranked_order=[f"{h.material_id}/{h.page}" for h in reordered],
                added_ms=elapsed,
            )
        )
    return {
        "rows": details,
        "page_recall_at_four": {
            name: interval(sum(r[name] for r in details), len(details))
            for name in ("lexical", "reranked")
        },
    }


def main() -> None:
    """Run the reranker or replay its saved candidate order with a local Laya bundle."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("track", choices=("rank", "judge"))
    parser.add_argument("--checkpoint", type=Path, required=True)
    parser.add_argument("--bundle", type=Path)
    parser.add_argument("--rank-report", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        raise FileExistsError(args.output)
    os.environ["HF_HUB_OFFLINE"] = "1"
    retrieval._block_network()
    if args.track == "rank":
        from sentence_transformers import CrossEncoder
        import torch

        torch.set_num_threads(2)
        encoder = CrossEncoder(str(args.checkpoint), device="cpu")
        report = run(encoder=encoder)
        report["historical_pages"] = benchmark_pages(encoder)
    else:
        from laya import Learner

        if not args.bundle or not args.rank_report:
            parser.error("judge requires --bundle and --rank-report")
        judge = Learner(
            bundle=args.bundle, reader=base.load_vega_reader(args.checkpoint), auto=False, cache=0
        )
        orders = {
            r["id"]: r["order"]
            for r in json.loads(args.rank_report.read_text())["rankings"]
            if r["method"] == "reranked"
        }
        report = run(judge=judge, orders=orders)
    save(args.output, report)


if __name__ == "__main__":
    main()
