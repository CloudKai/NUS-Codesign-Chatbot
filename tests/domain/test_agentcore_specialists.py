"""Canonical AgentCore specialist prompts and contracts (no AWS)."""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from agentcore_runtime.models import QATurnOutput, ReviewTurnOutput
from agentcore_runtime.prompts.loader import (
    COACHING_TOPICS,
    load_qa_prompt,
    load_review_prompt,
    load_shared_coaching,
    load_stage_prompt,
)
from agentcore_runtime.structured_coach import (
    CoachTurnExtractionError,
    coach_turn_from_agent_result,
    qa_turn_from_agent_result,
    review_turn_from_agent_result,
    specialist_system_prompt,
)
from backend.agentcore_provider import AgentCoreCoachProvider, agentcore_topic_for_stage
from backend.domain import CoachRequest, StageDecision
from fake_agentcore_runtime import FakeAgentCoreRuntime


_RUNTIME_ARN = (
    "arn:aws:bedrock-agentcore:us-west-2:123456789012:runtime/test-harness"
)
_RUNTIME_PROMPTS = Path("agentcore_runtime/prompts")


def _specialist_payload(client: FakeAgentCoreRuntime) -> dict[str, Any]:
    """Return the first non-router AgentCore payload."""
    for call in client.calls:
        payload = json.loads(call["payload"].decode("utf-8"))
        if (
            payload.get("phase") not in {"router"}
            and str(payload.get("review_mode") or "") != "incremental"
        ):
            return payload
    raise AssertionError("no specialist invoke recorded")


def _provider(client: FakeAgentCoreRuntime) -> AgentCoreCoachProvider:
    return AgentCoreCoachProvider(
        _RUNTIME_ARN,
        region="us-west-2",
        qualifier="DEFAULT",
        timeout_seconds=110.0,
        max_retries=0,
        client=client,
    )


def test_runtime_owns_five_coaching_topics_and_not_a_sixth_stage() -> None:
    assert COACHING_TOPICS == {
        "problem_identification",
        "concept_generation",
        "design_specification",
        "ethics_critical",
        "reflection",
    }
    assert agentcore_topic_for_stage("deep_analysis") == "ethics_critical"
    names = {path.name for path in (_RUNTIME_PROMPTS / "stages").glob("*.md")}
    assert names == {f"{topic}.md" for topic in COACHING_TOPICS}


def test_coaching_prompt_preserves_socratic_vv_and_assumption_check() -> None:
    shared = load_shared_coaching()
    assert "Socratic" in shared
    assert "ASSUMPTION CHECK" in shared
    assert "VERIFICATION AND VALIDATION" in shared
    assert "one meaningful question" in shared
    assert "RESEARCH CODING MUST NOT CONTROL COACHING" in shared
    stage = load_stage_prompt("problem_identification")
    assert "STAGE: PROBLEM IDENTIFICATION" in stage
    ethics = load_stage_prompt("ethics_critical")
    assert "ETHICS & CRITICAL THINKING" in ethics
    assert "AT-EAI" in ethics


def test_qa_and_review_prompts_are_not_socratic_coaching() -> None:
    qa = load_qa_prompt()
    assert "Q&A specialist" in qa
    assert "Do not switch into Socratic Thinking Path coaching." in qa
    assert "no tools" in qa.lower() or "You have no tools" in qa
    review = load_review_prompt()
    assert "Formative Review specialist" in review
    assert "not a grade" in review.lower()
    assert "Do not assign a numeric grade" in review


def test_specialist_system_prompt_does_not_need_application_stage_files() -> None:
    system = specialist_system_prompt(
        {
            "phase": "coaching",
            "topic": "concept_generation",
            "trusted_instructions": "Guidance mode: Quick.",
        }
    )
    assert "STAGE: CONCEPT GENERATION" in system
    assert "Guidance mode: Quick." in system
    assert "<shared_coaching>" not in system


def test_qa_and_review_contracts_fail_closed_without_text() -> None:
    with pytest.raises(Exception):
        QATurnOutput.model_validate({"citations": []})
    with pytest.raises(Exception):
        ReviewTurnOutput.model_validate({"response_text": "ok"})


def test_qa_turn_from_structured_output() -> None:
    output = QATurnOutput(response_text="Week 1 introduces design thinking.", citations=[])
    parsed = qa_turn_from_agent_result(
        SimpleNamespace(stop_reason="end_turn", structured_output=output, message=None)
    )
    assert "Week 1" in parsed.response_text


def test_review_turn_from_structured_output() -> None:

    output = ReviewTurnOutput(
        response_text="You named a concrete crossing context.",
        strengths=["Specific setting"],
        areas_to_develop=["Name who is affected"],
        synthesis="Progress is formative, not a grade.",
    )
    parsed = review_turn_from_agent_result(
        SimpleNamespace(stop_reason="end_turn", structured_output=output, message=None)
    )
    assert parsed.areas_to_develop
    assert "grade" in parsed.synthesis


def test_agentcore_payload_routes_week_question_to_qa() -> None:
    client = FakeAgentCoreRuntime(
        payload={
            "response_text": "Week 1 covers the course introduction [S1].",
            "citations": [],
        },
        router_payload={
            "specialist": "qa",
            "confidence": 0.95,
            "rationale_category": "course_information",
        },
    )
    result = _provider(client).assess(
        CoachRequest(
            thread_id="thread-demo",
            student_message="What is Week 1 about?",
            current_stage="problem_identification",
            response_detail="short",
        )
    )
    payload = _specialist_payload(client)
    assert payload["phase"] == "qa"
    assert payload["output_contract"] == "qa_turn"
    assert "STAGE: PROBLEM IDENTIFICATION" not in payload["trusted_instructions"]
    assert result.assessment.recommendation is StageDecision.STAY
    assert "Week 1" in result.response_text
    assert "Socratic" not in result.response_text


def test_agentcore_payload_routes_review_request() -> None:
    client = FakeAgentCoreRuntime(
        payload={
            "response_text": "You located a real street context.",
            "strengths": ["Concrete setting"],
            "areas_to_develop": ["Name who is affected"],
            "synthesis": "Formative progress, not a grade.",
        },
        router_payload={
            "specialist": "review",
            "confidence": 0.92,
            "rationale_category": "formative_review",
        },
    )
    result = _provider(client).assess(
        CoachRequest(
            thread_id="thread-demo",
            student_message="Review my progress so far.",
            current_stage="problem_identification",
            response_detail="short",
        )
    )
    payload = _specialist_payload(client)
    assert payload["phase"] == "review"
    assert payload["output_contract"] == "review_turn"
    assert result.assessment.recommendation is StageDecision.STAY
    assert "grade" in result.response_text.lower() or "grade" in result.assessment.stage_assessment.lower()
    assert result.assessment.review_strengths


def test_coaching_structured_output_still_required() -> None:
    with pytest.raises(CoachTurnExtractionError):
        coach_turn_from_agent_result(
            type(
                "Result",
                (),
                {
                    "stop_reason": "end_turn",
                    "structured_output": None,
                    "message": {"role": "assistant", "content": []},
                },
            )()
        )
