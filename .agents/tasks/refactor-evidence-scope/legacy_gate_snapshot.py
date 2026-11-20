"""Record ``evaluate_retrieval.gate_decision`` over a synthetic cross product.

Read-only and offline. Run it on the code under test, write the JSON, and diff
two outputs (before and after the refactor) to list every row whose
``GateDecision`` changed. Rows: every gate message and follow-up message, plus
a few hand-written compound messages, crossed with explicit interaction mode
(none, lecture_help, project_coaching), attachments (0 or 1) and selected
sources (none, a PDF, an image).

Usage (repo root, mock env vars set):

    python .agents/tasks/refactor-evidence-scope/legacy_gate_snapshot.py OUTPUT.json
"""

from __future__ import annotations

import dataclasses
import itertools
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.evals import evaluate_retrieval as retrieval  # noqa: E402

COMPOUND_MESSAGES = [
    "what stage am I in and let's move on to the next stage",
    "what stage am I on and what should I do next",
    "let's move on and also review this file",
    "I am done with this stage, what does the survey say?",
    "what does the survey say about week 3 and move to ideation",
    "can you review this persona",
    "what is dot voting in the lecture notes",
]

MODES = [None, "lecture_help", "project_coaching"]
ATTACHMENTS = [[], [{"title": "Persona", "filename": "Persona.pdf"}]]
SELECTED = [
    [],
    [{"title": "Survey results", "filename": "Survey results.pdf"}],
    [{"title": "Sketch", "filename": "Sketch.png"}],
]


def build() -> dict:
    materials = retrieval.load_materials(retrieval.MATERIALS_PATH)
    questions = retrieval.load_questions(retrieval.QUESTIONS_PATH, materials)
    ids = [q["id"] for q in questions]
    rows = retrieval.load_messages(retrieval.MESSAGES_PATH, materials, ids)
    rows += retrieval.load_followups(retrieval.FOLLOWUPS_PATH, materials, ids)
    base = [(row["id"], str(row["message"]), str(row["stage"])) for row in rows]
    base += [(f"compound-{i}", text, "problem_identification") for i, text in enumerate(COMPOUND_MESSAGES)]
    out: dict[str, dict] = {}
    for (row_id, message, stage), mode, attachments, selected in itertools.product(
        base, MODES, range(len(ATTACHMENTS)), range(len(SELECTED))
    ):
        row = {
            "message": message,
            "stage": stage,
            "selected_sources": SELECTED[selected],
            "attachments": ATTACHMENTS[attachments],
        }
        if mode is not None:
            row["explicit_mode"] = mode
        key = f"{row_id}|mode={mode}|att={attachments}|sel={selected}"
        out[key] = dataclasses.asdict(retrieval.gate_decision(row))
    return out


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print(__doc__)
        return 2
    data = build()
    Path(argv[1]).write_text(json.dumps(data, sort_keys=True, separators=(",", ":")) + "\n", encoding="utf-8")
    print(f"wrote {argv[1]}: {len(data)} rows")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
