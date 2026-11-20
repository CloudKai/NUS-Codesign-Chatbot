"""Compare lexical and cross-encoder ranks and judge actual retrieved evidence offline."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from time import perf_counter
from typing import Any

from backend.course_intent import load_vega_reader
from scripts.evals.lib.fixtures import load_materials, load_questions
from scripts.evals.lib.metrics import interval
from scripts.evals.lib.offline import (
    OfflineCourseSearch,
    RankedHit,
    accepted_targets,
    block_network,
    rank_hits,
)
from scripts.evals.lib.output import save
from scripts.evals.lib.paths import QUESTIONS_PATH

# The scoring half (candidates, fact coverage, run) lives in
# scripts/evals/lib/passage_scoring.py so evaluate_laya_turn_decisions can use it
# without importing this command. The names are re-exported for existing callers.
from scripts.evals.lib.passage_scoring import candidates as candidates, coverage as coverage, run


def benchmark_pages(encoder: Any) -> dict[str, Any]:
    """Compare top-four page hits on the full course benchmark within identical top-eight pools."""
    materials = load_materials()
    search = OfflineCourseSearch(materials)
    questions = load_questions(QUESTIONS_PATH, materials)
    details = []
    for row in questions:
        hits = rank_hits(search.search(row["question"]))[:8]
        accepted = accepted_targets(
            row["expected_material"], row["expected_pages"], row["alt_expected"]
        )
        start = perf_counter()
        scores = encoder.predict([(row["question"], h.text[:1800]) for h in hits]) if hits else []
        elapsed = (perf_counter() - start) * 1000
        reordered = [
            h for _, h in sorted(zip(scores, hits, strict=True), key=lambda pair: -pair[0])
        ]

        def page_hit(order: list[RankedHit]) -> bool:
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
    block_network()
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
            bundle=args.bundle, reader=load_vega_reader(args.checkpoint), auto=False, cache=0
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
