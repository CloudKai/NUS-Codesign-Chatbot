"""Deterministic local provider for API-free tests and demonstrations."""

from __future__ import annotations

from .domain import CoachRequest, EducationalAssessment, StageDecision
from .student_journey import STAGE_BY_ID, stage_guidance_questions


class DeterministicCoachProvider:
    """Return predictable structured coaching output without contacting a model."""

    def __init__(self, recommendation: StageDecision | None = None):
        self.recommendation = recommendation

    def assess(self, request: CoachRequest) -> tuple[str, EducationalAssessment]:
        """Build a repeatable coaching turn with visible, guided progression.

        An explicit recommendation keeps unit tests fully controllable. In the
        normal local demonstration, the first contribution at a stage receives
        focused guidance and a follow-up contribution creates an advance
        recommendation. This is turn-based demo behavior, not a claim that the
        mock provider semantically evaluated the student's writing.
        """
        stage = STAGE_BY_ID[request.current_stage]
        prior_stage_contributions = sum(
            1
            for message in request.history
            if message.get("role") == "user"
            and (message.get("metadata") or {}).get("thinking_stage") == stage.id
        )
        guided_recommendation = (
            StageDecision.ADVANCE
            if prior_stage_contributions >= 1 and stage.id != "conclusion"
            else StageDecision.STAY
        )
        recommendation = self.recommendation or guided_recommendation
        questions = stage_guidance_questions(stage.id)
        question = questions[min(prior_stage_contributions + 1, len(questions) - 1)]
        summary = " ".join(request.student_message.split())[:500]
        is_advancing = recommendation is StageDecision.ADVANCE
        assessment = EducationalAssessment(
            current_stage=stage.id,
            contribution_summary=summary or "Student shared an initial contribution.",
            stage_assessment=(
                f"The follow-up contribution is ready for a student-confirmed move beyond "
                f"{stage.short_label}."
                if is_advancing
                else f"The contribution begins the {stage.short_label} stage and needs one "
                "more precise element."
            ),
            missing_reasoning_elements=[] if is_advancing else [question],
            critical_understanding_level="Developing" if is_advancing else "Emerging",
            confidence=0.7 if is_advancing else 0.5,
            recommendation=recommendation,
            recommendation_rationale=(
                "Your follow-up has made this step clear enough to begin the next part of "
                "the thinking path."
                if is_advancing
                else "Add one more specific detail before moving to the next step."
            ),
            guidance_questions=[] if is_advancing else [question],
            learning_summary=(
                f"The student developed and clarified the {stage.short_label.lower()} step."
                if is_advancing
                else f"The student began clarifying the {stage.short_label.lower()} step."
            ),
        )
        if is_advancing:
            response = (
                f"**{stage.label}**\n\n"
                f"You’ve made this step clearer: {assessment.contribution_summary}\n\n"
                "This is ready for the next part of the thinking path."
            )
        else:
            response = (
                f"**{stage.label}**\n\n"
                "Before moving on, make this step more precise with one concrete detail.\n\n"
                f"**Next:** {question}"
            )
        if request.source_context:
            response += "\n\nI’ll use the selected lecture material as evidence as we continue."
        return response, assessment
