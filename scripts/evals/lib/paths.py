"""Repository root and the fixed dataset files every eval command reads."""

from __future__ import annotations

from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[3]

DATASET_DIR = PROJECT_ROOT / "scripts" / "evals" / "datasets"
QUESTIONS_PATH = DATASET_DIR / "retrieval_questions.jsonl"
MESSAGES_PATH = DATASET_DIR / "retrieval_gate_messages.synthetic.jsonl"
FOLLOWUPS_PATH = DATASET_DIR / "retrieval_gate_followups.synthetic.jsonl"
MATERIALS_PATH = DATASET_DIR / "course_materials.json"
