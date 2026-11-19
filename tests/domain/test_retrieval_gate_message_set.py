"""Validate the synthetic retrieval-gate message set under ``scripts/evals/datasets``.

Offline only. Checks the schema, label vocabulary, and links to the retrieval
question file and the materials manifest. It does not run the gate.
"""

from __future__ import annotations

import json
from collections import Counter
from pathlib import Path

from backend.domain import VALID_STAGE_IDS

ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = ROOT / "scripts" / "evals" / "datasets"
MESSAGES_PATH = DATA_DIR / "retrieval_gate_messages.synthetic.jsonl"
QUESTIONS_PATH = DATA_DIR / "retrieval_questions.jsonl"
MATERIALS_PATH = DATA_DIR / "course_materials.json"

ROW_KEYS = {
    "id",
    "message",
    "stage",
    "selected_sources",
    "attachments",
    "history",
    "expected_decision",
    "expected_scope",
    "category",
    "certainty",
    "follow_up",
    "question_id",
    "expected_material",
    "rationale",
    "synthetic",
}
DECISIONS = {"retrieve", "skip"}
SCOPES = {"course", "student_upload", "both", "none"}
CERTAINTY = {"clear", "borderline"}
CATEGORIES = {
    "course_content",
    "course_logistics",
    "named_material",
    "informal_or_multilingual",
    "mixed_project_and_course",
    "upload_question",
    "attachment_question",
    "upload_and_course",
    "course_with_unrelated_upload",
    "greeting_thanks_chitchat",
    "procedural_ui",
    "stage_navigation",
    "stage_meta_guidance",
    "project_reasoning",
    "project_mentions_course",
    "follow_up",
    "ambiguous_generic",
    "out_of_scope",
    "not_in_course_material",
}


def _rows() -> list[dict]:
    lines = MESSAGES_PATH.read_text(encoding="utf-8").splitlines()
    return [json.loads(line) for line in lines if line.strip()]


def _questions() -> dict[str, dict]:
    lines = QUESTIONS_PATH.read_text(encoding="utf-8").splitlines()
    return {row["id"]: row for row in map(json.loads, filter(str.strip, lines))}


def test_file_is_marked_synthetic_and_large_enough() -> None:
    rows = _rows()
    assert len(rows) >= 200
    assert "synthetic" in MESSAGES_PATH.name
    assert all(row["synthetic"] is True for row in rows)


def test_schema_and_label_vocabulary() -> None:
    rows = _rows()
    ids = [row["id"] for row in rows]
    assert ids == [f"gm{i:03d}" for i in range(1, len(rows) + 1)]
    contexts = set()
    for row in rows:
        assert set(row) == ROW_KEYS, row["id"]
        assert 1 <= len(row["message"]) <= 12_000
        assert row["stage"] in VALID_STAGE_IDS
        assert row["expected_decision"] in DECISIONS
        assert row["expected_scope"] in SCOPES
        assert row["certainty"] in CERTAINTY
        assert row["category"] in CATEGORIES
        assert isinstance(row["follow_up"], bool)
        assert row["rationale"].strip()
        for item in [*row["selected_sources"], *row["attachments"]]:
            assert set(item) == {"title", "filename"}
            assert item["title"].strip() and item["filename"].strip()
        assert len(row["attachments"]) <= 5
        for turn in row["history"]:
            assert set(turn) == {"role", "text"}
            assert turn["role"] in {"user", "assistant"}
            assert turn["text"].strip()
        context = json.dumps(
            [
                row["message"].casefold(),
                row["stage"],
                row["selected_sources"],
                row["attachments"],
                row["history"],
            ],
            sort_keys=True,
        )
        assert context not in contexts, f"duplicate message and context: {row['id']}"
        contexts.add(context)


def test_decision_scope_and_context_agree() -> None:
    for row in _rows():
        has_upload = bool(row["selected_sources"] or row["attachments"])
        if row["expected_decision"] == "skip":
            assert row["expected_scope"] == "none", row["id"]
            assert row["question_id"] is None and row["expected_material"] is None
        else:
            assert row["expected_scope"] != "none", row["id"]
        if row["expected_scope"] in {"student_upload", "both"}:
            assert has_upload, f"{row['id']}: upload scope without an upload"
        if row["category"] == "follow_up":
            assert row["follow_up"] and row["history"], row["id"]
        if row["follow_up"]:
            assert row["history"], row["id"]


def test_links_to_question_set_and_manifest() -> None:
    questions = _questions()
    materials = {
        item["material_id"] for item in json.loads(MATERIALS_PATH.read_text("utf-8"))
    }
    for row in _rows():
        if row["question_id"] is not None:
            assert row["question_id"] in questions, row["id"]
            assert (
                row["expected_material"] == questions[row["question_id"]]["expected_material"]
            ), row["id"]
        if row["expected_material"] is not None:
            assert row["expected_material"] in materials, row["id"]
            assert row["expected_scope"] in {"course", "both"}, row["id"]


def test_coverage() -> None:
    rows = _rows()
    decisions = Counter(row["expected_decision"] for row in rows)
    assert decisions["retrieve"] >= 80 and decisions["skip"] >= 80
    assert {row["stage"] for row in rows} == set(VALID_STAGE_IDS)
    assert {row["expected_scope"] for row in rows} == SCOPES
    assert {row["category"] for row in rows} == CATEGORIES
    assert sum(1 for row in rows if row["certainty"] == "borderline") >= 20
    assert sum(1 for row in rows if row["attachments"]) >= 10
    assert sum(1 for row in rows if row["history"]) >= 10
