"""Dump the offline gate's per-message decisions as deterministic JSON.

Read-only: it calls ``scripts.evals.evaluate_retrieval.gate_decision`` on every
gate message (295) and every follow-up case (12) and writes the result sorted
by id, so two runs can be compared byte for byte. It changes no production or
eval code and makes no network, AWS or model call.

Usage (repo root, mock env vars set):

    python .agents/tasks/refactor-baseline/dump_gate_decisions.py OUTPUT.json

Rows from ``evaluate_followups`` also run the standalone question through the
gate (the same row shape ``evaluate_followups`` builds), recorded under
``standalone`` for the retrieve cases.
"""

from __future__ import annotations

import dataclasses
import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.evals import evaluate_retrieval as retrieval  # noqa: E402


def _scope(course: bool, student: bool) -> str:
    """Name the effective evidence scope with the dataset's scope labels."""
    if course and student:
        return "both"
    if course:
        return "course"
    if student:
        return "student_upload"
    return "none"


def _record(row: dict) -> dict:
    decision = retrieval.gate_decision(row)
    return {
        "effective_scope": _scope(decision.course, decision.student),
        "mode": decision.expected_mode,
        "retrieve": decision.retrieve,
        "decision": dataclasses.asdict(decision),
    }


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def build() -> dict:
    materials = retrieval.load_materials(retrieval.MATERIALS_PATH)
    questions = retrieval.load_questions(retrieval.QUESTIONS_PATH, materials)
    question_ids = [q["id"] for q in questions]
    question_text = {q["id"]: q["question"] for q in questions}
    messages = retrieval.load_messages(retrieval.MESSAGES_PATH, materials, question_ids)
    followups = retrieval.load_followups(retrieval.FOLLOWUPS_PATH, materials, question_ids)

    gate = {}
    for row in messages:
        gate[row["id"]] = {
            "expected_decision": row["expected_decision"],
            "category": row["category"],
            **_record(row),
        }
    follow = {}
    for row in followups:
        entry = {
            "expected_decision": row["expected_decision"],
            "category": row["category"],
            **_record(row),
        }
        if row["expected_decision"] == "retrieve":
            standalone_row = {
                "message": str(question_text[row["question_id"]]),
                "stage": "problem_identification",
                "selected_sources": [],
                "attachments": [],
            }
            entry["standalone"] = _record(standalone_row)
        follow[row["id"]] = entry
    return {
        "description": (
            "Per-message output of scripts.evals.evaluate_retrieval.gate_decision, sorted by id. "
            "effective_scope: course|student_upload|both|none; mode: GateDecision.expected_mode; "
            "retrieve: course or student searched."
        ),
        "gate_messages_sha256": _sha256(retrieval.MESSAGES_PATH),
        "followup_cases_sha256": _sha256(retrieval.FOLLOWUPS_PATH),
        "gate_messages": {key: gate[key] for key in sorted(gate)},
        "followup_cases": {key: follow[key] for key in sorted(follow)},
    }


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print(__doc__)
        return 2
    out = Path(argv[1])
    out.parent.mkdir(parents=True, exist_ok=True)
    data = build()
    out.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(f"wrote {out}: {len(data['gate_messages'])} gate messages, {len(data['followup_cases'])} follow-ups")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
