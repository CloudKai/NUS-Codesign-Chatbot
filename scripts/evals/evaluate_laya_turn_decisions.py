"""Train and evaluate local Laya Learn decision heads without application calls."""

from __future__ import annotations

import argparse
import csv
import os
import shutil
from collections.abc import Mapping, Sequence
from pathlib import Path
from time import perf_counter
from typing import Any

from backend.course_intent import load_vega_reader
from scripts.evals import evaluate_retrieval as retrieval

DATA = Path(__file__).with_name("datasets")
ROUTE_QUESTIONS = {
    "scope": {
        "type": "choice",
        "instructions": "Which evidence does the current turn need?",
        "criteria": {
            "course": "Official course material only, even if an unrelated file is selected.",
            "student_upload": "The selected notebook files only.",
            "both": "Official course material and selected files are both necessary.",
            "none": "The existing conversation or student's own reasoning is enough.",
        },
    },
    "mode": {
        "type": "choice",
        "instructions": "What kind of help is the student asking for?",
        "criteria": {
            "lecture_help": "A direct explanation, lookup, comparison, or factual answer.",
            "project_coaching": "Guidance developing, applying, or testing their design reasoning.",
        },
    },
}
EVIDENCE_QUESTION = {
    "sufficiency": {
        "type": "choice",
        "instructions": "Can the excerpts support an answer to the question?",
        "criteria": {
            "sufficient": "The excerpts support all material parts of the question.",
            "partial": "The excerpts support one part but leave another material part unanswered.",
            "insufficient": "The excerpts do not support an answer to any material part.",
        },
    },
}


def read_training(name: str, width: int) -> list[list[str]]:
    """Read source-controlled, synthetic Sol examples and validate field counts."""
    with (DATA / name).open(encoding="utf-8", newline="") as file:
        rows = list(csv.reader(file, delimiter="\t"))
    if not rows or any(len(row) != width or not all(row) for row in rows):
        raise ValueError(f"Invalid synthetic training rows in {name}")
    return rows


def normalized(text: str) -> str:
    """Normalize a message for the exact-overlap check."""
    return " ".join(text.strip(" ?.!").casefold().split())


def route_state(
    message: str,
    history: Sequence[Mapping[str, Any]],
    titles: Sequence[str],
    files: Sequence[Mapping[str, Any]],
) -> str:
    """Format bounded titles, history, and current question without source contents."""
    selected = ", ".join(str(item["title"]) for item in files)[:500]
    recent = [
        f"{turn['role']}: {str(turn.get('text', turn.get('content', '')))[:220]}"
        for turn in history[-4:]
        if turn.get("role") in {"user", "assistant"}
    ]
    return "\n".join(
        [f"Student: {message[:1200]}", f"Selected files: {selected or 'none'}", *recent]
    )


def evidence_state(question: str, excerpts: str) -> str:
    """Format the sufficiency check using only the supplied excerpts."""
    return f"Question: {question[:1200]}\nRetrieved excerpts:\n{excerpts[:8000]}"


def decide(
    model: Any,
    state: str,
    questions: Mapping[str, Any],
) -> tuple[dict[str, str | None], float]:
    """Return validated choice labels or explicit abstentions and elapsed time."""
    started = perf_counter()
    result = model.decide(state)
    elapsed = (perf_counter() - started) * 1000
    choices = {}
    for key, question in questions.items():
        answer = result["answers"][key]
        probabilities = answer["probs"]
        if probabilities.keys() != question["criteria"].keys():
            raise ValueError(f"Unexpected probability labels for {key}")
        choices[key] = None if answer.get("abstain") else max(probabilities, key=probabilities.get)
    return choices, elapsed


def scope_name(course: bool, student: bool) -> str:
    """Translate the existing gate's two search decisions into an evidence scope."""
    if course and student:
        return "both"
    if course:
        return "course"
    return "student_upload" if student else "none"


def main(argv: Sequence[str] | None = None) -> int:
    """Fit or replay local Laya heads, reporting grouped routing and retrieved evidence."""
    from scripts.evals import compare_turn_routes as routes
    from scripts.evals.evaluate_passage_support import run

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--checkpoint", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--track", choices=("all", "routing", "evidence"), default="all")
    parser.add_argument("--saved-bundles", type=Path)
    args = parser.parse_args(argv)
    args.output_dir.mkdir(parents=True)
    os.environ.update(HF_HUB_OFFLINE="1", TOKENIZERS_PARALLELISM="false")
    retrieval._block_network()
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
                routes.training()
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
            report[key] = routes.evaluate(routes.laya_predictor(model), routes.inputs())
        else:
            report[key] = run(judge=model)
    routes.save(args.output_dir / "report.json", report)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
