from backend.models import MODEL_REGISTRY, get_model, validate_reasoning
from backend.student_support import (
    DEFAULT_SUPPORT_MODE,
    SUPPORT_MODES,
    build_student_instructions,
    critical_thinking_scaffold,
    get_support_mode,
)


EXPECTED_MODELS = {
    "gpt-5.5",
    "gpt-5.4",
    "gpt-5.4-mini",
    "gpt-5.4-nano",
    "gpt-5.3-chat-latest",
    "gpt-5.2",
    "gpt-5.1",
    "gpt-5",
    "gpt-5-mini",
    "gpt-5-nano",
    "gpt-4.1",
    "gpt-4.1-mini",
}


def test_curated_model_registry_and_capabilities():
    assert {model.id for model in MODEL_REGISTRY} == EXPECTED_MODELS
    assert get_model("gpt-5.3-chat-latest").deprecated is True
    for model in MODEL_REGISTRY:
        assert model.vision is True
        assert model.web_search is True
        assert model.file_search is True
        assert model.function_calling is True


def test_reasoning_is_model_compatible():
    assert validate_reasoning(get_model("gpt-5.4"), "high") == "high"
    assert validate_reasoning(get_model("gpt-5.4"), "unsupported") == "medium"
    assert validate_reasoning(get_model("gpt-4.1"), "high") is None


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
