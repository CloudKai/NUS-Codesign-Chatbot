"""Deterministic stub-model snapshots for the eval commands that need model weights.

``compare_turn_routes``, ``evaluate_passage_support``,
``evaluate_laya_turn_decisions`` and ``evaluate_course_intent_learn`` cannot run
here (no ``laya``, ``vegaml``, ``setfit`` or checkpoint). Their report-building
code does not need a fitted model, so this script feeds it stand-in predictors
whose answers come from a SHA-256 of the input text. The output is a pure
function of the checked-in datasets and the code, so a diff of the "before" and
"after" files shows any change in report building. Timing fields are removed.

    python .agents/tasks/refactor-baseline/stub_snapshots.py OUT_DIR LABEL

writes OUT_DIR/stub_snapshots.LABEL.json. Offline: no network, AWS or model call.
Only the imports and the function lookups below may change when code moves.
"""

from __future__ import annotations

import contextlib
import hashlib
import io
import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[3]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.evals import compare_turn_routes as routes  # noqa: E402
from scripts.evals import evaluate_course_intent_learn as learn  # noqa: E402
from scripts.evals import evaluate_laya_turn_decisions as base  # noqa: E402
from scripts.evals import evaluate_passage_support as passages  # noqa: E402
from scripts.evals import evaluate_retrieval as retrieval  # noqa: E402


def _weights(text: str, salt: str, labels: list[str]) -> dict[str, float]:
    """Return probabilities over ``labels`` derived from a hash of ``text``."""
    digest = hashlib.sha256(f"{salt}:{text}".encode()).digest()
    raw = [digest[i] + 1 for i in range(len(labels))]
    total = sum(raw)
    return {label: round(value / total, 6) for label, value in zip(labels, raw)}


def stub_predict(text: str) -> dict[str, dict[str, float]]:
    """Stand-in for a routing predictor (``Predict`` in compare_turn_routes)."""
    return {
        key: _weights(text, key, list(schema["criteria"]))
        for key, schema in base.ROUTE_QUESTIONS.items()
    }


class StubJudge:
    """Stand-in for a Laya model: ``decide(state)`` returns hash-derived answers."""

    def __init__(self, questions: dict[str, Any]) -> None:
        self.questions = questions

    def decide(self, state: str) -> dict[str, Any]:
        answers = {}
        for key, schema in self.questions.items():
            probs = _weights(state, key, list(schema["criteria"]))
            abstain = hashlib.sha256(f"abstain:{state}".encode()).digest()[0] % 5 == 0
            answers[key] = {"probs": probs, "abstain": abstain}
        return {"answers": answers}


def _sha(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def _drop(value: Any, keys: set[str]) -> Any:
    """Remove timing keys at every depth."""
    if isinstance(value, dict):
        return {k: _drop(v, keys) for k, v in value.items() if k not in keys}
    if isinstance(value, list):
        return [_drop(v, keys) for v in value]
    return value


TIMING = {"latency_ms", "latency", "ms", "added_ms"}


def route_snapshot() -> dict[str, Any]:
    splits = routes.inputs()
    with contextlib.redirect_stdout(io.StringIO()):
        report = routes.evaluate(stub_predict, splits)
    examples = routes.training()
    return {
        "split_sizes": {name: len(rows) for name, rows in splits.items()},
        "inputs_sha256": _sha(splits),
        "training_count": len(examples),
        "training_sha256": _sha(examples),
        "report_without_timing": _drop(report, TIMING),
    }


def passage_snapshot() -> dict[str, Any]:
    lexical = passages.run()
    orders: dict[str, list[str]] = {}
    for row in lexical["rankings"]:
        if row["method"] == "lexical":
            orders[row["id"]] = list(reversed(row["order"]))
    return {
        "lexical_only": _drop(lexical, TIMING),
        "stub_judge": _drop(passages.run(judge=StubJudge(base.EVIDENCE_QUESTION)), TIMING),
        "reversed_orders_and_stub_judge": _drop(
            passages.run(judge=StubJudge(base.EVIDENCE_QUESTION), orders=orders), TIMING
        ),
    }


def turn_decision_snapshot() -> dict[str, Any]:
    fresh = routes.scenarios("routing_fresh.synthetic.jsonl")
    states = [routes.state(row) for row in fresh]
    choices = []
    judge = StubJudge(base.ROUTE_QUESTIONS)
    for text in states:
        decided, _elapsed = base.decide(judge, text, base.ROUTE_QUESTIONS)
        choices.append(decided)
    routing = base.read_training("laya_routing_training.synthetic.tsv", 4)
    sufficiency = base.read_training("laya_sufficiency_training.synthetic.tsv", 3)
    return {
        "route_states_sha256": _sha(states),
        "first_state": states[0],
        "evidence_state": base.evidence_state("What is a job story?", "A job story is..."),
        "decisions_sha256": _sha(choices),
        "decisions": choices,
        "routing_training": {"rows": len(routing), "sha256": _sha(routing)},
        "sufficiency_training": {"rows": len(sufficiency), "sha256": _sha(sufficiency)},
        "scope_names": [base.scope_name(c, s) for c in (False, True) for s in (False, True)],
    }


def learn_snapshot() -> dict[str, Any]:
    materials = retrieval.load_materials(retrieval.MATERIALS_PATH)
    questions = retrieval.load_questions(retrieval.QUESTIONS_PATH, materials)
    messages = retrieval.load_messages(
        retrieval.MESSAGES_PATH, materials, [row["id"] for row in questions]
    )
    splits = learn.split_messages(messages)
    rows = []
    for row in messages:
        decision = retrieval.gate_decision(row)
        score = int.from_bytes(hashlib.sha256(row["id"].encode()).digest()[:2], "big") / 65535
        rows.append(
            {
                "expected": row["expected_decision"],
                "expected_scope": row["expected_scope"],
                "baseline_retrieve": decision.retrieve,
                "first_turn": not row["history"],
                "score": round(score, 6),
            }
        )
    general = learn.select_threshold(rows, "score")
    first = learn.select_threshold(rows, "score", continuing_cutoff=general)
    return {
        "split_ids": {name: [r["id"] for r in part] for name, part in splits.items()},
        "general_threshold": general,
        "first_turn_threshold": first,
        "routes_general": learn.evaluate_routes(rows, "score", general) if general is not None else None,
        "routes_first_turn": (
            learn.evaluate_routes(rows, "score", general, first_turn_threshold=first)
            if general is not None and first is not None
            else None
        ),
    }


def main(argv: list[str]) -> int:
    if len(argv) != 3:
        print(__doc__)
        return 2
    out_dir, label = Path(argv[1]), argv[2]
    out_dir.mkdir(parents=True, exist_ok=True)
    retrieval._block_network()
    snapshot = {
        "description": "Stub-model snapshots; timing fields removed. See stub_snapshots.py.",
        "compare_turn_routes": route_snapshot(),
        "evaluate_passage_support": passage_snapshot(),
        "evaluate_laya_turn_decisions": turn_decision_snapshot(),
        "evaluate_course_intent_learn": learn_snapshot(),
    }
    path = out_dir / f"stub_snapshots.{label}.json"
    path.write_text(json.dumps(snapshot, indent=2, sort_keys=True, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"wrote {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
