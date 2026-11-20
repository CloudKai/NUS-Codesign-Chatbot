"""Train and evaluate local Laya Learn decision heads without application calls."""

from __future__ import annotations

import argparse
import os
import shutil
from collections.abc import Sequence
from pathlib import Path

from backend.course_intent import load_vega_reader
from scripts.evals.lib.fixtures import read_training
from scripts.evals.lib.offline import block_network
from scripts.evals.lib.output import save
from scripts.evals.lib.passage_scoring import run
from scripts.evals.lib.paths import DATASET_DIR as DATA  # noqa: F401  (re-exported name)
from scripts.evals.lib.route_scoring import evaluate, inputs, laya_predictor, training
from scripts.evals.lib.turn_state import (
    EVIDENCE_QUESTION,
    ROUTE_QUESTIONS,
    decide as decide,
    evidence_state,
    normalized as normalized,
    route_state as route_state,
    scope_name as scope_name,
)


def main(argv: Sequence[str] | None = None) -> int:
    """Fit or replay local Laya heads, reporting grouped routing and retrieved evidence."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--checkpoint", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--track", choices=("all", "routing", "evidence"), default="all")
    parser.add_argument("--saved-bundles", type=Path)
    args = parser.parse_args(argv)
    args.output_dir.mkdir(parents=True)
    os.environ.update(HF_HUB_OFFLINE="1", TOKENIZERS_PARALLELISM="false")
    block_network()
    from laya import Learner

    reader = load_vega_reader(args.checkpoint)
    report = {}
    for key, schema in (("routing", ROUTE_QUESTIONS), ("evidence", EVIDENCE_QUESTION)):
        if args.track not in ("all", key):
            continue
        dest = args.output_dir / f"{key}.zip"
        if args.saved_bundles:
            shutil.copyfile(args.saved_bundles / dest.name, dest)
        else:
            examples = (
                training()
                if key == "routing"
                else [
                    (evidence_state(question, excerpt), {"sufficiency": label})
                    for label, question, excerpt in read_training(
                        "laya_sufficiency_training.synthetic.tsv", 3
                    )
                ]
            )
            Learner(schema, examples=examples, reader=reader, auto=False, cache=0).save_bundle(dest)
        model = Learner(bundle=dest, reader=reader, auto=False, cache=0)
        if model.questions != schema:
            raise ValueError(f"Unexpected bundle schema for {key}")
        if key == "routing":
            report[key] = evaluate(laya_predictor(model), inputs())
        else:
            report[key] = run(judge=model)
    save(args.output_dir / "report.json", report)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
