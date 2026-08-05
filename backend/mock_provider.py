"""Deterministic local provider for API-free tests and demonstrations."""

from __future__ import annotations

from .domain import CoachRequest, EducationalAssessment, FacioneDimensionScores, StageDecision
from .student_journey import (
    STAGE_BY_ID,
    THINKING_STAGES,
    next_stage_id,
    personalized_stage_questions,
    stage_guidance_questions,
)


def _mock_facione_scores(stage_id: str, *, is_advancing: bool) -> FacioneDimensionScores:
    """Return deterministic Facione scores that rise with journey progress.

    Early stages light up Analysis/Interpretation; later stages unlock the rest.
    Advancing nudges active dimensions up by one (capped at 4).
    """
    stage_index = next(
        (index for index, stage in enumerate(THINKING_STAGES) if stage.id == stage_id),
        0,
    )
    baselines = {
        "analysis": 1 if stage_index >= 0 else 0,
        "interpretation": 1 if stage_index >= 0 else 0,
        "inference": 1 if stage_index >= 2 else 0,
        "evaluation": 1 if stage_index >= 1 else 0,
        "explanation": 1 if stage_index >= 3 else 0,
        "self_regulation": 1 if stage_index >= 4 else 0,
    }
    bump = 1 if is_advancing else 0
    if stage_index <= 1:
        baselines["analysis"] = min(4, baselines["analysis"] + 1 + bump)
        baselines["interpretation"] = min(4, baselines["interpretation"] + bump)
        baselines["evaluation"] = min(4, baselines["evaluation"] + bump)
    elif stage_index <= 3:
        baselines["inference"] = min(4, baselines["inference"] + 1 + bump)
        baselines["evaluation"] = min(4, baselines["evaluation"] + 1 + bump)
        baselines["explanation"] = min(4, baselines["explanation"] + bump)
    else:
        baselines["explanation"] = min(4, baselines["explanation"] + 1 + bump)
        baselines["self_regulation"] = min(4, baselines["self_regulation"] + 1 + bump)
        baselines["inference"] = min(4, baselines["inference"] + bump)
    return FacioneDimensionScores(**baselines)


def _mock_review_feedback(
    stage_id: str,
    *,
    is_advancing: bool,
    has_contribution: bool,
) -> tuple[list[str], list[str]]:
    """Return supportive stage feedback for the mock assessment."""
    if not has_contribution:
        return [], []
    if stage_id == "focus":
        strengths = [
            "You named a concrete design challenge worth examining.",
        ]
        improvements = (
            []
            if is_advancing
            else [
                "Name who is affected and what successful change would look like.",
            ]
        )
        return strengths, improvements
    if stage_id == "evidence":
        strengths = ["You are starting to look for concrete support for the idea."]
        improvements = (
            []
            if is_advancing
            else ["Point to one source finding and one limit of that evidence."]
        )
        return strengths, improvements
    strengths = [
        f"You are making the {STAGE_BY_ID[stage_id].short_label.lower()} step more explicit."
    ]
    improvements = (
        []
        if is_advancing
        else [stage_guidance_questions(stage_id)[0].rstrip("?")]
    )
    return strengths, improvements


class DeterministicCoachProvider:
    """Return predictable structured coaching output without contacting a model."""

    def __init__(self, recommendation: StageDecision | None = None):
        self.recommendation = recommendation

    def assess(self, request: CoachRequest) -> tuple[str, EducationalAssessment]:
        """Build a repeatable coaching turn with visible, guided progression.

        An explicit recommendation keeps unit tests fully controllable. In the
        normal local demonstration, Quick guidance recommends advance after one
        follow-up contribution at the stage; Complex waits for a second follow-up
        so progression is a little stricter. This is turn-based demo behavior, not
        a claim that the mock provider semantically evaluated the writing.
        """
        stage = STAGE_BY_ID[request.current_stage]
        prior_stage_contributions = sum(
            1
            for message in request.history
            if message.get("role") == "user"
            and (message.get("metadata") or {}).get("thinking_stage") == stage.id
        )
        advance_after = 2 if request.response_detail == "long" else 1
        guided_recommendation = (
            StageDecision.ADVANCE
            if prior_stage_contributions >= advance_after and stage.id != "conclusion"
            else StageDecision.STAY
        )
        recommendation = self.recommendation or guided_recommendation
        questions = stage_guidance_questions(stage.id)
        question = questions[min(prior_stage_contributions + 1, len(questions) - 1)]
        summary = " ".join(request.student_message.split())[:500]
        is_advancing = recommendation is StageDecision.ADVANCE
        upcoming_id = next_stage_id(stage.id) if is_advancing else None
        upcoming = STAGE_BY_ID[upcoming_id] if upcoming_id else None
        next_questions = (
            list(
                personalized_stage_questions(
                    upcoming.id,
                    request.student_message,
                    has_course_sources=bool(request.source_ids or request.source_context),
                )
            )
            if upcoming
            else []
        )
        strengths, improvements = _mock_review_feedback(
            stage.id,
            is_advancing=is_advancing,
            has_contribution=bool(summary),
        )
        assessment = EducationalAssessment(
            current_stage=stage.id,
            contribution_summary=summary or "Student shared an initial contribution.",
            stage_assessment=(
                f"The contribution is clear enough to move into {upcoming.short_label}."
                if is_advancing and upcoming
                else f"The contribution begins the {stage.short_label} stage and needs one "
                "more precise element."
            ),
            missing_reasoning_elements=[] if is_advancing else [question],
            critical_understanding_level="Developing" if is_advancing else "Emerging",
            confidence=0.7 if is_advancing else 0.5,
            recommendation=recommendation,
            recommendation_rationale=(
                f"Move into {upcoming.short_label} and deepen the reasoning there."
                if is_advancing and upcoming
                else "Add one more specific detail before moving to the next step."
            ),
            guidance_questions=next_questions[:2] if is_advancing else [question],
            learning_summary=(
                f"The student clarified the {stage.short_label.lower()} step and is ready "
                f"to examine {upcoming.short_label.lower()}."
                if is_advancing and upcoming
                else f"The student began clarifying the {stage.short_label.lower()} step."
            ),
            facione_scores=_mock_facione_scores(stage.id, is_advancing=is_advancing),
            review_strengths=strengths,
            review_improvements=improvements,
        )
        if is_advancing and upcoming:
            follow_up = next_questions[0] if next_questions else upcoming.reflection_prompt
            response = (
                f"**{upcoming.label}**\n\n"
                f"That's a solid start—now let's look more carefully at "
                f"{upcoming.short_label.lower()}. {upcoming.description}\n\n"
                f"{follow_up}"
            )
        else:
            response = (
                f"**{stage.label}**\n\n"
                "That's an interesting direction. Let's make this step a little more "
                f"precise.\n\n{question}"
            )
        return response, assessment
