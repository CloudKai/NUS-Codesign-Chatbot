"""Deterministic pedagogical fixtures for every Thinking Path stage."""

from __future__ import annotations

import pytest

from agentcore_runtime.prompts.loader import load_shared_coaching, load_stage_prompt
from backend.agentcore_provider import agentcore_topic_for_stage
from backend.domain import CoachRequest, StageDecision
from backend.mock_provider import DeterministicCoachProvider
from backend.student_journey import STAGE_BY_ID, THINKING_STAGES

_SHARED = load_shared_coaching()
_STAGE_FILES = {
    stage.id: load_stage_prompt(agentcore_topic_for_stage(stage.id))
    for stage in THINKING_STAGES
}

_SCENARIOS = (
    "weak contribution",
    "reasonable contribution",
    "strong contribution",
    "hidden assumption",
    "unsupported factual claim",
    "insufficient evidence",
    "stage-ready reasoning",
)


def test_every_stage_prompt_has_purpose_readiness_and_no_assignment_completion() -> None:
    for stage in THINKING_STAGES:
        text = _STAGE_FILES[stage.id]
        assert "STAGE:" in text
        assert "PURPOSE:" in text
        assert "ADVANCE" in text or stage.id == "reflection"
        assert "STAY" in text
        assert "Never" in text or "never" in text
        assert "CORE FOCUS" in text


def test_shared_runtime_prompt_has_vv_assumption_and_one_question() -> None:
    assert "Assumption / V&V check" in _SHARED or "ASSUMPTION CHECK" in _SHARED
    assert "Verification" in _SHARED
    assert "Validation" in _SHARED
    assert "one meaningful question" in _SHARED
    assert "Do not use generic praise" in _SHARED
    assert "finished assignment" in _SHARED


@pytest.mark.parametrize("stage", THINKING_STAGES, ids=lambda item: item.id)
@pytest.mark.parametrize("scenario", _SCENARIOS)
def test_mock_provider_keeps_stage_identity_and_does_not_complete_assignment(
    stage, scenario: str
) -> None:
    """Provider-fixture coverage: stage identity, stay/advance, no assignment dump."""
    messages = {
        "weak contribution": "A street.",
        "reasonable contribution": (
            f"In {stage.short_label}, older pedestrians wait too long at a residential crossing."
        ),
        "strong contribution": (
            "Older pedestrians at night on Holland Road need a longer crossing interval "
            "because the current signal leaves them stranded mid-block."
        ),
        "hidden assumption": "Everyone will love this design so it must work.",
        "unsupported factual claim": "Studies prove this is the safest option.",
        "insufficient evidence": "I think it is probably fine.",
        "stage-ready reasoning": (
            "Affected people are older pedestrians at night; the need is a safer crossing "
            "interval; the context is a residential arterial; success is reaching the far "
            "kerb before the signal changes."
        ),
    }
    provider = DeterministicCoachProvider(
        StageDecision.ADVANCE
        if scenario == "stage-ready reasoning" and stage.id != "reflection"
        else StageDecision.STAY
    )
    result = provider.assess(
        CoachRequest(
            thread_id="thread-demo",
            student_message=messages[scenario],
            current_stage=stage.id,
            response_detail="long",
            specialist="coaching",
        )
    )
    assert result.assessment.current_stage == stage.id
    assert result.response_text.count("?") >= 1
    lowered = result.response_text.lower()
    assert "here is your completed assignment" not in lowered
    assert "clear code" not in lowered
    assert "facione" not in lowered
    if scenario == "stage-ready reasoning" and stage.id != "reflection":
        assert result.assessment.recommendation is StageDecision.ADVANCE
    else:
        assert result.assessment.recommendation is StageDecision.STAY
        assert (
            stage.label.split()[0] in result.response_text
            or stage.short_label in result.response_text
        )
    if stage.id == "reflection":
        assert result.assessment.recommendation is StageDecision.STAY


def test_hidden_assumption_and_vv_live_in_runtime_not_student_headings() -> None:
    assert "Do not render these headings" in _SHARED or "silently" in _SHARED.lower()
    assert STAGE_BY_ID["deep_analysis"].label == "Ethics & Critical Thinking"
