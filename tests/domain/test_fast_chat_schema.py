"""Lightweight FastChatTurnOutput contract tests. No AWS."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from agentcore_runtime.models import (
    FAST_CHAT_SCHEMA_ID,
    FastChatContractError,
    FastChatTurnOutput,
    adapt_fast_chat_turn_payload,
    parse_fast_chat_turn_output,
)
from backend.domain import EducationalAssessment, StageDecision


def test_coaching_schema_requires_stay_or_advance_and_omits_assessment() -> None:
    parsed = parse_fast_chat_turn_output(
        {
            "mode": "coaching",
            "response_text": "What specifically prevents noon booking?",
            "recommendation": "stay",
            "recommendation_rationale": "The booking mechanism is still unproven.",
            "citations": [],
            "needs_source_retrieval": False,
        }
    )
    dumped = parsed.model_dump(mode="json")
    assert "assessment" not in FastChatTurnOutput.model_fields
    assert "assessment" not in dumped
    assert "facione_scores" not in dumped
    assert "research_coding" not in dumped
    assert "review_strengths" not in dumped


def test_qa_schema_drops_recommendation() -> None:
    parsed = FastChatTurnOutput.model_validate(
        {
            "mode": "qa",
            "response_text": "Week 1 covers Innovation-driven economy [S1].",
            "recommendation": "stay",
            "recommendation_rationale": "ignore me",
            "citations": [{"label": "S1", "title": "Week 1"}],
        }
    )
    assert parsed.recommendation is None
    assert parsed.recommendation_rationale is None


def test_coaching_without_recommendation_fails() -> None:
    with pytest.raises(ValidationError):
        FastChatTurnOutput.model_validate(
            {"mode": "coaching", "response_text": "Hello"}
        )


def test_legacy_full_assessment_still_parses() -> None:
    assessment = EducationalAssessment.model_validate(
        {
            "current_stage": "problem_identification",
            "contribution_summary": "The student compared two constraints.",
            "stage_assessment": "Usable starting point.",
            "critical_understanding_level": "Developing",
            "confidence": 0.7,
            "recommendation": "STAY",
            "recommendation_rationale": "More evidence is needed.",
            "guidance_questions": ["What trade-off still needs evidence?"],
            "learning_summary": "The student is developing the problem.",
            "working_conclusion": "Evening rooms are scarce.",
            "review_strengths": ["Named a setting"],
            "review_improvements": ["Name who is affected"],
            "facione_scores": {"analysis": 2, "evaluation": 1},
            "research_coding": {"ignored": True},
        }
    )
    assert assessment.recommendation is StageDecision.STAY
    assert assessment.facione_scores.analysis == 2
    assert assessment.review_strengths == ["Named a setting"]


def test_fast_chat_persisted_mapping_omits_review_fields() -> None:
    slim = EducationalAssessment(
        current_stage="problem_identification",
        recommendation=StageDecision.STAY,
        recommendation_rationale="More evidence is needed.",
        response_mode="coaching",
    ).persisted_mapping()
    assert slim["response_mode"] == "coaching"
    assert slim["recommendation"] == "stay"
    assert "facione_scores" not in slim
    assert "review_strengths" not in slim
    assert "working_conclusion" not in slim
    assert "research_coding" not in slim


def _legacy_coach_turn(*, recommendation: str = "stay") -> dict:
    """Return the immediately-previous nested coach_turn wire shape."""
    return {
        "response_text": "What specifically prevents noon booking?",
        "assessment": {
            "current_stage": "problem_identification",
            "contribution_summary": "The student compared two constraints.",
            "stage_assessment": "Usable starting point.",
            "critical_understanding_level": "Developing",
            "confidence": 0.7,
            "recommendation": recommendation,
            "recommendation_rationale": "The booking mechanism is still unproven.",
            "guidance_questions": ["What trade-off still needs evidence?"],
            "learning_summary": "The student is developing the problem.",
            "citations": [],
            "facione_scores": {"analysis": 2, "evaluation": 1},
        },
        "research_coding": None,
    }


def test_adapt_slim_fast_chat_payload() -> None:
    parsed = adapt_fast_chat_turn_payload(
        {
            "mode": "coaching",
            "response_text": "What specifically prevents noon booking?",
            "recommendation": "stay",
            "schema_id": FAST_CHAT_SCHEMA_ID,
        }
    )
    assert parsed.mode == "coaching"
    assert parsed.recommendation == "stay"


def test_adapt_legacy_coach_turn_keeps_assessment_recommendation() -> None:
    parsed = adapt_fast_chat_turn_payload(_legacy_coach_turn(recommendation="advance"))
    assert parsed.mode == "coaching"
    assert parsed.recommendation == "advance"


def test_adapt_legacy_qa_turn_does_not_invent_recommendation() -> None:
    parsed = adapt_fast_chat_turn_payload(
        {
            "response_text": "Week 1 covers Innovation-driven economy [S1].",
            "citations": [{"label": "S1"}],
        }
    )
    assert parsed.mode == "qa"
    assert parsed.recommendation is None


def test_adapt_legacy_missing_recommendation_fails() -> None:
    payload = _legacy_coach_turn(recommendation="maybe")
    with pytest.raises(FastChatContractError) as raised:
        adapt_fast_chat_turn_payload(payload)
    assert raised.value.reason == "legacy_recommendation_missing"


def test_adapt_recommendation_without_mode_fails() -> None:
    with pytest.raises(FastChatContractError) as raised:
        adapt_fast_chat_turn_payload(
            {
                "response_text": "What specifically prevents noon booking?",
                "recommendation": "advance",
            }
        )
    assert raised.value.reason == "recommendation_without_mode"


def test_adapt_qa_mode_ignores_nested_assessment_advance() -> None:
    parsed = adapt_fast_chat_turn_payload(
        {
            "mode": "qa",
            "response_text": "The lecture names stakeholders.",
            "assessment": _legacy_coach_turn(recommendation="advance")["assessment"],
        }
    )
    assert parsed.mode == "qa"
    assert parsed.recommendation is None


def test_adapt_conflicting_recommendations_fail() -> None:
    payload = _legacy_coach_turn(recommendation="advance")
    payload["mode"] = "coaching"
    payload["recommendation"] = "stay"
    with pytest.raises(FastChatContractError) as raised:
        adapt_fast_chat_turn_payload(payload)
    assert raised.value.reason == "recommendation_conflict"


def test_adapt_malformed_payload_fails_closed() -> None:
    with pytest.raises(FastChatContractError) as raised:
        adapt_fast_chat_turn_payload({"foo": 1})
    assert raised.value.reason == "unrecognized"
    with pytest.raises(FastChatContractError) as raised_review:
        adapt_fast_chat_turn_payload(
            {
                "response_text": "Formative review.",
                "synthesis": "Progress is forming.",
                "strengths": ["Named a setting"],
            }
        )
    assert raised_review.value.reason == "wrong_contract"
