"""Canonical AgentCore specialist prompts and contracts (no AWS)."""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from agentcore_runtime.models import (
    DeepReviewTurnOutput,
    FastChatTurnOutput,
    QATurnOutput,
    ReviewTurnOutput,
    parse_review_turn_output,
)
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


def test_deep_review_schema_requires_stage_reviews_array() -> None:
    schema = DeepReviewTurnOutput.model_json_schema()
    for field in (
        "strengths",
        "areas_to_develop",
        "readiness_evidence",
        "missing_requirements",
        "stage_reviews",
    ):
        assert field in schema["required"]
        node = schema["properties"][field]
        assert node.get("type") == "array"
        assert "null" not in str(node.get("type"))
        assert "anyOf" not in node
    incremental = ReviewTurnOutput.model_json_schema()
    assert "stage_reviews" not in incremental.get("properties", {})
    defs = schema.get("$defs") or schema.get("definitions") or {}
    feedback = defs.get("DeepReviewStageFeedback") or {}
    refs = (feedback.get("properties") or {}).get("supporting_message_refs") or {}
    assert (feedback.get("required") or []) and "supporting_message_refs" in feedback["required"]
    assert refs.get("type") == "array"
    assert "anyOf" not in refs
    fast = FastChatTurnOutput.model_json_schema()
    assert "supporting_message_refs" not in fast.get("properties", {})
    assert "stage_reviews" not in fast.get("properties", {})


def test_parse_review_turn_output_keeps_stage_reviews() -> None:
    parsed = parse_review_turn_output(
        {
            "response_text": "Formative deep review.",
            "strengths": ["Holistic strength"],
            "areas_to_develop": ["Holistic area"],
            "synthesis": "Progress is formative.",
            "readiness_evidence": [],
            "missing_requirements": [],
            "review_depth": "deep",
            "current_stage": "concept_generation",
            "recommendation": "stay",
            "rationale_summary": "Stay.",
            "stage_reviews": [
                {
                    "stage_id": "problem_identification",
                    "strengths": ["Constructed a How Might We question"],
                    "areas_to_develop": [],
                    "supporting_message_refs": [],
                },
                {
                    "stage_id": "not_a_stage",
                    "strengths": ["Dropped"],
                    "areas_to_develop": [],
                },
                {
                    "stage_id": "concept_generation",
                    "strengths": [],
                    "areas_to_develop": [],
                    "supporting_message_refs": [],
                },
            ],
        }
    )
    assert isinstance(parsed, DeepReviewTurnOutput)
    assert [item.stage_id for item in parsed.stage_reviews] == [
        "problem_identification"
    ]
    assert parsed.stage_reviews[0].strengths == [
        "Constructed a How Might We question"
    ]
    assert parsed.stage_reviews[0].supporting_message_refs == []


def test_deep_review_legacy_shape_still_defaults_stage_reviews_to_empty() -> None:
    """Old deep payloads remain parseable while new schema requires arrays."""
    parsed = parse_review_turn_output(
        {
            "response_text": "Legacy formative review.",
            "strengths": ["Named a setting"],
            "areas_to_develop": ["Name affected users"],
            "synthesis": "Legacy synthesis.",
            "review_depth": "deep",
            "current_stage": "problem_identification",
            "recommendation": "stay",
            "rationale_summary": "More evidence is needed.",
        },
        allow_legacy=True,
    )
    assert isinstance(parsed, ReviewTurnOutput)
    assert not isinstance(parsed, DeepReviewTurnOutput)


@pytest.mark.parametrize(
    "bad_value",
    [None, "not-an-array", {"stage_id": "problem_identification"}],
)
def test_deep_review_stage_reviews_rejects_non_arrays(bad_value: Any) -> None:
    """New Deep Review validation must not normalize malformed arrays."""
    with pytest.raises(Exception):
        DeepReviewTurnOutput.model_validate(
            {
                "response_text": "Deep review.",
                "synthesis": "Synthesis.",
                "review_depth": "deep",
                "stage_reviews": bad_value,
            }
        )


@pytest.mark.parametrize(
    ("field", "bad_value"),
    [
        (field, bad_value)
        for field in (
            "strengths",
            "areas_to_develop",
            "readiness_evidence",
            "missing_requirements",
        )
        for bad_value in (None, "not-an-array", {"item": "not-an-array"})
    ],
)
def test_deep_review_top_level_arrays_reject_null_and_flattened_shapes(
    field: str, bad_value: Any
) -> None:
    """New Deep Review top-level arrays reject null and flattened values."""
    base = {
        "response_text": "Deep review.",
        "synthesis": "Synthesis.",
        "review_depth": "deep",
        "strengths": [],
        "areas_to_develop": [],
        "readiness_evidence": [],
        "missing_requirements": [],
        "stage_reviews": [],
    }
    with pytest.raises(Exception):
        DeepReviewTurnOutput.model_validate({**base, field: bad_value})

    missing = dict(base)
    del missing[field]
    with pytest.raises(Exception):
        DeepReviewTurnOutput.model_validate(missing)


def test_deep_review_top_level_arrays_accept_explicit_empty_arrays() -> None:
    """An explicit [] is valid for every new Deep Review collection field."""
    parsed = DeepReviewTurnOutput.model_validate(
        {
            "response_text": "Deep review.",
            "synthesis": "Synthesis.",
            "review_depth": "deep",
            "strengths": [],
            "areas_to_develop": [],
            "readiness_evidence": [],
            "missing_requirements": [],
            "stage_reviews": [],
        }
    )
    assert parsed.strengths == []
    assert parsed.areas_to_develop == []
    assert parsed.readiness_evidence == []
    assert parsed.missing_requirements == []


def test_deep_review_stage_feedback_requires_explicit_child_arrays() -> None:
    """Child arrays reject omission/null/wrong shapes while [] remains valid."""
    base = {
        "response_text": "Deep review.",
        "synthesis": "Synthesis.",
        "review_depth": "deep",
        "strengths": [],
        "areas_to_develop": [],
        "readiness_evidence": [],
        "missing_requirements": [],
        "stage_reviews": [],
    }
    assert DeepReviewTurnOutput.model_validate(base).stage_reviews == []
    with pytest.raises(Exception):
        DeepReviewTurnOutput.model_validate(
            {
                **base,
                "stage_reviews": [
                    {
                        "stage_id": "problem_identification",
                        "strengths": None,
                        "areas_to_develop": [],
                        "supporting_message_refs": [],
                    }
                ],
            }
        )
    with pytest.raises(Exception):
        DeepReviewTurnOutput.model_validate(
            {
                **base,
                "stage_reviews": [
                    {
                        "stage_id": "problem_identification",
                        "strengths": [],
                        "areas_to_develop": "missing-array",
                        "supporting_message_refs": [],
                    }
                ],
            }
        )
    with pytest.raises(Exception):
        DeepReviewTurnOutput.model_validate(
            {
                **base,
                "stage_reviews": [
                    {
                        "stage_id": "problem_identification",
                        "strengths": [],
                        "areas_to_develop": [],
                        "supporting_message_refs": {"ref": "M1"},
                    }
                ],
            }
        )


def test_review_turn_output_ignores_stage_reviews_field() -> None:
    parsed = ReviewTurnOutput.model_validate(
        {
            "response_text": "Incremental review.",
            "strengths": ["Setting"],
            "areas_to_develop": ["Users"],
            "synthesis": "Formative.",
            "stage_reviews": [
                {
                    "stage_id": "problem_identification",
                    "strengths": ["Should be ignored"],
                    "areas_to_develop": [],
                }
            ],
        }
    )
    assert not isinstance(parsed, DeepReviewTurnOutput)
    assert not hasattr(parsed, "stage_reviews")


def test_agentcore_payload_uses_fast_chat_for_week_question() -> None:
    client = FakeAgentCoreRuntime(
        payload={
            "mode": "qa",
            "response_text": "Week 1 covers the course introduction [S1].",
            "citations": [],
            "hmw_scaffold_ready": False,
            "needs_source_retrieval": False,
            "out_of_scope": False,
        }
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
    assert payload["phase"] == "fast_chat"
    assert payload["output_contract"] == "fast_chat_turn"
    assert result.assessment.recommendation is None
    assert "Week 1" in result.response_text
    assert "Socratic" not in result.response_text


def test_agentcore_free_text_review_stays_on_fast_chat() -> None:
    client = FakeAgentCoreRuntime(
        payload={
            "mode": "coaching",
            "response_text": "What trade-off still needs evidence?",
            "recommendation": "stay",
            "recommendation_rationale": "Stay and name who is affected.",
            "citations": [],
            "hmw_scaffold_ready": False,
            "needs_source_retrieval": False,
            "out_of_scope": False,
        }
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
    assert payload["phase"] == "fast_chat"
    assert payload["output_contract"] == "fast_chat_turn"
    assert result.assessment.recommendation is StageDecision.STAY


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
