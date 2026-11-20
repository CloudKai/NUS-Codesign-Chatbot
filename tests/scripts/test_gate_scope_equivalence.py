"""The offline gate and production share one first-pass scope decision. No network.

``scripts/evals/evaluate_retrieval.py::gate_decision`` is an adapter over
``backend.coaching.evidence_scope.decide_first_pass_scope``. These tests pin
that the module's decision for every gate message (295) and follow-up case (12,
plus the standalone question of each retrieve case) equals the per-message
decisions saved before the refactor in
``.agents/tasks/refactor-baseline/gate-decisions-before.json``, and that the
eval's Laya-eligibility approximation agrees with the module on the gate set.
"""

from __future__ import annotations

import dataclasses
import hashlib
import importlib.util
import json
import sys
from pathlib import Path
from typing import Any

import pytest

from backend.coaching.evidence_scope import (
    decide_first_pass_scope,
    local_course_intent_candidate,
    scope_label,
)

_ROOT = Path(__file__).resolve().parents[2]
_BEFORE = _ROOT / ".agents" / "tasks" / "refactor-baseline" / "gate-decisions-before.json"


def _load_eval():
    path = _ROOT / "scripts" / "evals" / "evaluate_retrieval.py"
    spec = importlib.util.spec_from_file_location("co_design_evaluate_retrieval_scope", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module  # dataclasses resolve their module by name
    spec.loader.exec_module(module)
    return module


_EVAL = _load_eval()


@pytest.fixture(scope="module")
def before() -> dict[str, Any]:
    assert _BEFORE.is_file(), "the saved pre-refactor decisions must stay in the repository"
    return json.loads(_BEFORE.read_text(encoding="utf-8"))


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _module_decision(row: dict[str, Any]) -> dict[str, Any]:
    """The module's answer, in the saved file's shape (no ``GateDecision``)."""
    scope = decide_first_pass_scope(_EVAL.scope_inputs_for_row(row))
    return {
        "effective_scope": scope_label(scope),
        "mode": scope.expected_mode,
        "retrieve": bool(scope.include_course_catalog or scope.searches_personal_files),
    }


def _saved(entry: dict[str, Any]) -> dict[str, Any]:
    return {key: entry[key] for key in ("effective_scope", "mode", "retrieve")}


def _followup_rows() -> list[tuple[dict[str, Any], dict[str, Any] | None]]:
    materials = _EVAL.load_materials(_EVAL.MATERIALS_PATH)
    questions = _EVAL.load_questions(_EVAL.QUESTIONS_PATH, materials)
    question_text = {item["id"]: item["question"] for item in questions}
    rows = _EVAL.load_followups(
        _EVAL.FOLLOWUPS_PATH, materials, [item["id"] for item in questions]
    )
    pairs = []
    for row in rows:
        standalone = None
        if row["expected_decision"] == "retrieve":
            # The row ``evaluate_followups`` builds for the standalone question.
            standalone = {
                "message": str(question_text[row["question_id"]]),
                "stage": "problem_identification",
                "selected_sources": [],
                "attachments": [],
            }
        pairs.append((row, standalone))
    return pairs


def test_saved_decisions_belong_to_the_current_datasets(before: dict[str, Any]) -> None:
    assert before["gate_messages_sha256"] == _sha256(_EVAL.MESSAGES_PATH)
    assert before["followup_cases_sha256"] == _sha256(_EVAL.FOLLOWUPS_PATH)
    assert len(before["gate_messages"]) == 295
    assert len(before["followup_cases"]) == 12


def test_module_decision_equals_the_saved_decision_for_all_295_gate_messages(
    before: dict[str, Any],
) -> None:
    rows = _EVAL.load_messages()
    assert len(rows) == 295
    mismatches = [
        row["id"]
        for row in rows
        if _module_decision(row) != _saved(before["gate_messages"][row["id"]])
    ]
    assert mismatches == []


def test_module_decision_equals_the_saved_decision_for_the_follow_up_cases(
    before: dict[str, Any],
) -> None:
    pairs = _followup_rows()
    assert len(pairs) == 12
    for row, standalone in pairs:
        saved = before["followup_cases"][row["id"]]
        assert _module_decision(row) == _saved(saved), row["id"]
        if standalone is not None:
            assert _module_decision(standalone) == _saved(saved["standalone"]), row["id"]
        else:
            assert "standalone" not in saved


def test_adapter_returns_the_full_saved_gate_decision(before: dict[str, Any]) -> None:
    for row in _EVAL.load_messages():
        saved = before["gate_messages"][row["id"]]
        assert dataclasses.asdict(_EVAL.gate_decision(row)) == saved["decision"], row["id"]
    for row, standalone in _followup_rows():
        saved = before["followup_cases"][row["id"]]
        assert dataclasses.asdict(_EVAL.gate_decision(row)) == saved["decision"], row["id"]
        if standalone is not None:
            assert (
                dataclasses.asdict(_EVAL.gate_decision(standalone))
                == saved["standalone"]["decision"]
            )


def test_gate_decision_holds_the_values_the_eval_cannot_supply() -> None:
    inputs = _EVAL.scope_inputs_for_row(
        {
            "message": "what does the survey say",
            "stage": "problem_identification",
            "selected_sources": [{"title": "Sketch", "filename": "Sketch.png"}],
            "attachments": [{"title": "Notes", "filename": "Notes.pdf"}],
            "explicit_mode": "lecture_help",
        }
    )
    assert inputs.force_retrieval is False and inputs.frozen_history is False
    assert inputs.upload_retrieval_enabled is False
    assert all(
        source.image_bytes_resolved and not source.is_course_library for source in inputs.sources
    )
    assert [(s.source_id, s.is_attachment, s.is_image) for s in inputs.sources] == [
        ("eval-source-1", False, True),
        ("eval-attachment-1", True, False),
    ]
    assert inputs.attachment_count == 1 and inputs.interaction_intent == "lecture_help"


def test_eval_laya_eligibility_matches_the_module_on_all_gate_messages() -> None:
    """The three Laya eval scripts' ``evidence_scoped`` and ``searched`` agree.

    They approximate production's eligibility from the gate decision and the
    row's sources. On the gate set that approximation equals the module's
    ``course_intent_eligible``.
    """
    eligible = 0
    for row in _EVAL.load_messages():
        decision = _EVAL.gate_decision(row)
        approximation = local_course_intent_candidate(
            row["message"],
            intent=decision.intent,
            evidence_scoped=bool(
                decision.scope_cleared or row["attachments"] or row["selected_sources"]
            ),
            searched=decision.retrieve,
        )
        module = decide_first_pass_scope(_EVAL.scope_inputs_for_row(row)).course_intent_eligible
        assert approximation is module, row["id"]
        eligible += int(module)
    assert eligible == 147
