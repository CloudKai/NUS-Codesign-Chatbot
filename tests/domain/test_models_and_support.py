"""Provider model registry and support-mode helper tests."""

from backend.models import (
    DEFAULT_CHAT_MODEL_ID,
    DEFAULT_REASONING_EFFORT,
    LOCKED_CHAT_MODEL_ID,
    MODEL_REGISTRY,
    get_model,
    validate_reasoning,
)
from backend.domain import (
    CoachRequest,
    FacioneDimensionScores,
    ProviderCoachOutput,
    StageDecision,
    openai_strict_schema,
)
from backend.mock_provider import DeterministicCoachProvider
from backend.student_support import (
    DEFAULT_SUPPORT_MODE,
    SUPPORT_MODES,
    build_student_instructions,
    critical_thinking_scaffold,
    get_support_mode,
)


def test_curated_model_registry_and_capabilities():
    assert {model.id for model in MODEL_REGISTRY} == {DEFAULT_CHAT_MODEL_ID}
    locked = get_model(LOCKED_CHAT_MODEL_ID)
    assert locked.label == "GPT-5.6 Luna"
    assert DEFAULT_REASONING_EFFORT in locked.reasoning_efforts
    assert locked.vision is True
    assert locked.web_search is True
    assert locked.file_search is True
    assert locked.function_calling is True
    # Unknown legacy IDs fall back to the default model.
    assert get_model("gpt-5.4").id == DEFAULT_CHAT_MODEL_ID
    assert get_model("gpt-5.5").id == DEFAULT_CHAT_MODEL_ID


def test_openai_strict_schema_marks_objects_closed():
    schema = openai_strict_schema(ProviderCoachOutput)
    assert schema["additionalProperties"] is False
    assert "response_text" in schema["required"]
    assessment = schema["$defs"]["EducationalAssessment"]
    assert assessment["additionalProperties"] is False
    assert "facione_scores" in assessment["properties"]
    assert "facione_scores" in assessment["required"]
    assert "review_strengths" in assessment["required"]
    assert "review_improvements" in assessment["required"]
    facione = schema["$defs"]["FacioneDimensionScores"]
    assert facione["additionalProperties"] is False
    for key in (
        "analysis",
        "interpretation",
        "inference",
        "evaluation",
        "explanation",
        "self_regulation",
    ):
        assert key in facione["required"]


def test_facione_dimension_scores_default_to_not_started():
    scores = FacioneDimensionScores()
    assert scores.model_dump() == {
        "analysis": 0,
        "interpretation": 0,
        "inference": 0,
        "evaluation": 0,
        "explanation": 0,
        "self_regulation": 0,
    }


def test_mock_provider_includes_facione_scores():
    response, assessment = DeterministicCoachProvider().assess(
        CoachRequest(
            thread_id="t1",
            student_message="I want to study safer crossings for older adults near schools.",
            current_stage="focus",
            response_detail="short",
        )
    )
    assert response
    assert assessment.facione_scores.analysis >= 1
    assert 0 <= assessment.facione_scores.self_regulation <= 4
    assert assessment.review_strengths
    assert "That's an interesting direction" in response
    assert "One retrieved finding is:" not in response
    assert "[S" not in response
    assert "You’ve made this step clearer" not in response
    assert "ready for the next part" not in response.lower()


def test_mock_facione_scores_use_exact_stage_mapping_and_never_claim_mastery():
    dimensions_by_stage = {
        "focus": {"analysis", "interpretation"},
        "evidence": {"interpretation", "evaluation"},
        "assumptions": {"analysis", "self_regulation"},
        "perspectives": {"interpretation", "evaluation", "self_regulation"},
        "synthesis": {"inference", "evaluation", "explanation"},
        "conclusion": {"inference", "explanation", "self_regulation"},
    }
    all_dimensions = set(FacioneDimensionScores.model_fields)

    for stage_id, relevant_dimensions in dimensions_by_stage.items():
        for decision, relevant_score in (
            (StageDecision.STAY, 1),
            (StageDecision.ADVANCE, 2),
        ):
            _, assessment = DeterministicCoachProvider(decision).assess(
                CoachRequest(
                    thread_id=f"{stage_id}-{decision}",
                    student_message="A deterministic mock contribution.",
                    current_stage=stage_id,
                    response_detail="short",
                )
            )
            scores = assessment.facione_scores.model_dump()
            assert {
                dimension
                for dimension, score in scores.items()
                if score == relevant_score
            } == relevant_dimensions
            assert all(
                scores[dimension] == 0
                for dimension in all_dimensions - relevant_dimensions
            )
            assert max(scores.values()) <= 2


def test_mock_provider_applies_quick_and_strict_advancement_thresholds():
    def assessed_history(*profiles: str) -> list[dict]:
        return [
            {
                "role": "assistant",
                "content": "Earlier assessment.",
                "metadata": {
                    "coaching_profile": profile,
                    "assessment": {
                        "current_stage": "focus",
                        "recommendation": "stay",
                    },
                },
            }
            for profile in profiles
        ]

    quick_response, quick = DeterministicCoachProvider().assess(
        CoachRequest(
            thread_id="quick-profile",
            student_message="A workable focus question.",
            current_stage="focus",
            response_detail="short",
            history=assessed_history("quick"),
        )
    )
    strict_response, strict = DeterministicCoachProvider().assess(
        CoachRequest(
            thread_id="strict-profile",
            student_message="A workable focus question.",
            current_stage="focus",
            response_detail="long",
            history=assessed_history("strict"),
        )
    )
    _, strict_after_quick = DeterministicCoachProvider().assess(
        CoachRequest(
            thread_id="strict-after-quick",
            student_message="A first contribution under Strict.",
            current_stage="focus",
            response_detail="long",
            history=assessed_history("quick", "quick"),
        )
    )
    _, strict_after_two_strict = DeterministicCoachProvider().assess(
        CoachRequest(
            thread_id="strict-after-two-strict",
            student_message="A third contribution under Strict.",
            current_stage="focus",
            response_detail="long",
            history=assessed_history("strict", "strict"),
        )
    )

    assert quick.recommendation is StageDecision.ADVANCE
    assert "Examine evidence" in quick_response
    assert strict.recommendation is StageDecision.STAY
    assert "Define the focus" in strict_response
    assert strict_after_quick.recommendation is StageDecision.STAY
    assert strict_after_two_strict.recommendation is StageDecision.ADVANCE


def test_reasoning_is_model_compatible():
    locked = get_model(LOCKED_CHAT_MODEL_ID)
    assert locked.reasoning_efforts == (DEFAULT_REASONING_EFFORT, "medium")
    assert validate_reasoning(locked, "low") == "low"
    assert validate_reasoning(locked, "medium") == "medium"
    assert validate_reasoning(locked, "high") == DEFAULT_REASONING_EFFORT
    assert validate_reasoning(locked, "unsupported") == DEFAULT_REASONING_EFFORT
    assert validate_reasoning(locked, "xhigh") == DEFAULT_REASONING_EFFORT


def test_student_modes_cover_assignment_workflows():
    assert DEFAULT_SUPPORT_MODE == "critical-thinking"
    assert {mode.id for mode in SUPPORT_MODES} == {
        "critical-thinking",
        "assignment-planner",
        "evidence-review",
        "argument-builder",
        "writing-feedback",
        "general-tutor",
    }
    assert get_support_mode("missing").id == DEFAULT_SUPPORT_MODE


def test_prompt_preserves_student_authorship_and_context():
    prompt = build_student_instructions(
        "evidence-review",
        assignment_title="Policy brief",
        assignment_brief="Assess the proposal.",
        rubric="Use credible primary evidence.",
        course_context="Public policy",
        thinking_stage_id="assumptions",
        response_detail="long",
        response_language="中文",
    )
    lowered = prompt.lower()
    assert "student authorship" in lowered
    assert "never fabricate" in lowered
    assert "policy brief" in lowered
    assert "credible primary evidence" in prompt
    assert "Evidence Reviewer" in prompt
    assert "Surface assumptions" in prompt
    assert "Response detail: Long" in prompt
    assert "Respond in 中文" in prompt


def test_critical_thinking_scaffold_is_actionable():
    scaffold = critical_thinking_scaffold()
    assert len(scaffold) >= 6
    assert any("evidence" in question.lower() for question in scaffold)
    assert any("assumption" in question.lower() for question in scaffold)
    assert any("alternative" in question.lower() for question in scaffold)


def test_apply_selected_model_accepts_explicit_effort(monkeypatch):
    """Composer helpers apply and clamp reasoning effort for the chosen model."""
    import streamlit as st

    from ui.settings import apply_selected_model

    class _Session(dict):
        def __getattr__(self, key):  # noqa: D105
            try:
                return self[key]
            except KeyError as exc:
                raise AttributeError(key) from exc

        def __setattr__(self, key, value):  # noqa: D105
            self[key] = value

    state = _Session(
        selected_model=DEFAULT_CHAT_MODEL_ID,
        reasoning_effort="low",
    )
    monkeypatch.setattr(st, "session_state", state)

    apply_selected_model(DEFAULT_CHAT_MODEL_ID, effort="medium")
    assert state["selected_model"] == DEFAULT_CHAT_MODEL_ID
    assert state["reasoning_effort"] == "medium"

    apply_selected_model(DEFAULT_CHAT_MODEL_ID, effort="not-allowed")
    assert state["reasoning_effort"] == DEFAULT_REASONING_EFFORT
