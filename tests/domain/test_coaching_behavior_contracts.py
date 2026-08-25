"""Deterministic coaching-contract checks for all five Thinking Path stages."""

from __future__ import annotations

from pathlib import Path

from agentcore_runtime.prompts.loader import load_shared_coaching, load_stage_prompt
from backend.agentcore_provider import agentcore_topic_for_stage
from backend.student_journey import THINKING_STAGES

_CASES = Path("tests/fixtures/coaching_behavior_cases.json")


def test_each_stage_prompt_encodes_the_coaching_contract() -> None:
    shared = load_shared_coaching()
    assert "one meaningful question" in shared
    assert "Do not use generic praise" in shared
    assert "RESEARCH CODING MUST NOT CONTROL COACHING" in shared
    assert "PROGRESS OVER INTERROGATION" in shared
    assert "Imperfect but usable work should normally progress" in shared
    assert "substantive blocker" in shared
    assert "does not need a Socratic question when it advances" in shared
    expected = {
        "problem_identification": ("assumption", "stakeholder"),
        "concept_generation": ("alternative", "compar"),
        "design_specification": ("requirement", "constraint"),
        "deep_analysis": ("trade", "ethic"),
        "reflection": ("limit", "self"),
    }
    for stage in THINKING_STAGES:
        text = load_stage_prompt(agentcore_topic_for_stage(stage.id)).lower()
        for needle in expected[stage.id]:
            assert needle in text, f"{stage.id} missing {needle}"
    pi = load_stage_prompt("problem_identification").lower()
    assert "good enough to progress" in pi
    assert "when a workable hmw is present" in pi
    assert "explicit progression requests" in pi
    assert "repeated hmw rule" in pi
    assert "what evidence do you have?" in pi


def test_behavior_cases_exist_for_every_stage() -> None:
    import json

    payload = json.loads(_CASES.read_text(encoding="utf-8"))
    stages = {item["stage"] for item in payload["cases"]}
    assert {stage.id for stage in THINKING_STAGES} <= stages


def test_progress_over_interrogation_regression_cases_are_explicit() -> None:
    """Keep the deterministic pedagogy matrix honest about necessary blockers."""
    import json

    payload = json.loads(_CASES.read_text(encoding="utf-8"))
    cases = {item["id"]: item for item in payload["cases"]}
    expected = {
        "pi_hmw_two_of_three_scaffold_stay": ("stay", "problem_identification"),
        "pi_rough_hmw_advance": ("advance_allowed", "concept_generation"),
        "pi_solution_locked_hmw_stay": ("stay", "problem_identification"),
        "pi_filler_stay": ("stay", "problem_identification"),
        "pi_misconception_stay": ("stay", "problem_identification"),
        "cg_adequate_imperfect_advance": (
            "advance_allowed",
            "design_specification",
        ),
        "cg_optional_refinement_advance": (
            "advance_allowed",
            "design_specification",
        ),
        "qa_isolation": ("qa", "concept_generation"),
    }
    assert set(expected) <= cases.keys()
    for case_id, (decision, next_stage) in expected.items():
        case_expected = cases[case_id]["expected"]
        if decision == "qa":
            assert case_expected["mode"] == "qa"
            assert case_expected["must_remain_socratic"] is False
            assert case_expected["must_not_recommend_stage_change"] is True
        else:
            assert case_expected["stay_or_advance"] == decision
        stage_key = (
            "stage_should_become"
            if decision == "advance_allowed"
            else "stage_should_remain"
        )
        assert case_expected[stage_key] == next_stage
