from backend.models import (
    LOCKED_CHAT_MODEL_ID,
    LOCKED_REASONING_EFFORT,
    MODEL_REGISTRY,
    get_model,
    validate_reasoning,
)
from backend.domain import (
    CoachRequest,
    FacioneDimensionScores,
    ProviderCoachOutput,
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
    assert {model.id for model in MODEL_REGISTRY} == {LOCKED_CHAT_MODEL_ID}
    locked = get_model(LOCKED_CHAT_MODEL_ID)
    assert locked.label == "GPT-5.6 Luna"
    assert locked.reasoning_efforts == (LOCKED_REASONING_EFFORT,)
    assert locked.vision is True
    assert locked.web_search is True
    assert locked.file_search is True
    assert locked.function_calling is True
    # Unknown legacy IDs fall back to the locked model.
    assert get_model("gpt-5.5").id == LOCKED_CHAT_MODEL_ID


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
    assert "You’ve made this step clearer" not in response
    assert "ready for the next part" not in response.lower()


def test_reasoning_is_model_compatible():
    locked = get_model(LOCKED_CHAT_MODEL_ID)
    assert validate_reasoning(locked, "low") == "low"
    assert validate_reasoning(locked, "high") == "low"
    assert validate_reasoning(locked, "unsupported") == "low"


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
