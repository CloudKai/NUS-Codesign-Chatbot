"""Check the local learner interface and holdout logic without model weights."""

from __future__ import annotations

import sys
from pathlib import Path
from types import ModuleType
from typing import Any

from backend import course_intent
from scripts.evals import evaluate_retrieval as retrieval
from scripts.evals.evaluate_course_intent_learn import evaluate_routes, select_threshold, split_messages


def test_split_keeps_question_ids_and_duplicate_messages_together() -> None:
    materials = retrieval.load_materials(retrieval.MATERIALS_PATH)
    questions = retrieval.load_questions(retrieval.QUESTIONS_PATH, materials)
    messages = retrieval.load_messages(
        retrieval.MESSAGES_PATH, materials, [row["id"] for row in questions]
    )
    splits = split_messages(messages)
    assert splits == split_messages(messages)
    assert sum(map(len, splits.values())) == len(messages)
    question_split: dict[str, str] = {}
    message_split: dict[str, str] = {}
    for name, rows in splits.items():
        assert {row["expected_decision"] for row in rows} == {"retrieve", "skip"}
        for row in rows:
            if row["question_id"]:
                assert question_split.setdefault(row["question_id"], name) == name
            text = " ".join(row["message"].casefold().split())
            assert message_split.setdefault(text, name) == name


def test_threshold_meets_calibration_false_retrieve_limit() -> None:
    rows = [
        {"expected": "retrieve", "expected_scope": "course", "baseline_retrieve": False,
         "score": 0.9},
        {"expected": "retrieve", "expected_scope": "course", "baseline_retrieve": False,
         "score": 0.5},
        *([
            {"expected": "skip", "expected_scope": "none", "baseline_retrieve": False,
             "score": 0.5}
        ] * 10),
    ]
    assert select_threshold(rows, "score") == 0.9
    metrics = evaluate_routes(rows, "score", 0.9)
    assert metrics["wrong_skip"]["numerator"] == 1
    assert metrics["false_retrieve"]["numerator"] == 0


def test_first_turn_calibration_preserves_continuing_cutoff_and_false_retrieve_budget() -> None:
    opening = {"expected": "retrieve", "expected_scope": "course", "baseline_retrieve": False,
               "first_turn": True, "score": 0.6}
    followup = {**opening, "first_turn": False, "expected": "skip", "expected_scope": "none"}
    rows = [opening, followup, {**opening, "score": 0.9}]
    general = select_threshold(rows, "score")
    assert general == 0.9
    first = select_threshold(rows, "score", continuing_cutoff=general)
    assert first == 0.6
    metrics = evaluate_routes(rows, "score", general, first_turn_threshold=first)
    assert metrics["wrong_skip"]["numerator"] == metrics["false_retrieve"]["numerator"] == 0


def test_learner_adapter_loads_fixed_bundle_and_honors_abstention(tmp_path, monkeypatch) -> None:
    class StubLearner:
        questions = course_intent.course_intent_questions()

        def __init__(self, *, bundle: Path, reader: Any, auto: bool, cache: int) -> None:
            assert bundle.name == "bundle.zip"
            assert reader == "local-reader"
            assert not auto and cache == 0

        def decide(self, state: str) -> dict[str, Any]:
            assert "Course materials: Week 2 JTBD" in state
            return {"answers": {"retrieval": {
                "probs": {"course_evidence": 0.92},
                "readout": "head",
                "abstain": state.endswith("unclear"),
            }}}

    laya = ModuleType("laya")
    laya.Learner = StubLearner
    monkeypatch.setitem(sys.modules, "laya", laya)
    monkeypatch.setattr(course_intent, "load_vega_reader", lambda _: "local-reader")
    bundle = tmp_path / "bundle.zip"
    bundle.touch()
    classifier = course_intent.LayaLearnCourseIntentClassifier(tmp_path, bundle)
    history = [{"role": "assistant", "text": "Last turn"}]
    assert classifier.score("What is a job story?", history, ["Week 2 JTBD"]) == 0.92
    assert classifier.score("unclear", history, ["Week 2 JTBD"]) is None
