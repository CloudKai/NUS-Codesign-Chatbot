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


def test_behavior_cases_exist_for_every_stage() -> None:
    import json

    payload = json.loads(_CASES.read_text(encoding="utf-8"))
    stages = {item["stage"] for item in payload["cases"]}
    assert {stage.id for stage in THINKING_STAGES} <= stages
