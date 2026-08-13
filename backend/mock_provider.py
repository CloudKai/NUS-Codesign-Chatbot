"""Deterministic local provider for API-free tests and demonstrations."""

from __future__ import annotations

import re

from .domain import CoachRequest, EducationalAssessment, FacioneDimensionScores, StageDecision
from .prompts import PreparedCoachPrompt, compose_coach_prompt
from .student_journey import (
    STAGE_BY_ID,
    coaching_profile_for_response_detail,
    next_stage_id,
    personalized_stage_questions,
    stage_guidance_questions,
)


_CITATION_LABEL = re.compile(r"S\d+")
_MAX_GROUNDED_EXCERPT_CHARS = 320
_FACIONE_DIMENSIONS_BY_STAGE = {
    "focus": ("analysis", "interpretation"),
    "evidence": ("interpretation", "evaluation"),
    "assumptions": ("analysis", "self_regulation"),
    "perspectives": ("interpretation", "evaluation", "self_regulation"),
    "synthesis": ("inference", "evaluation", "explanation"),
    "conclusion": ("inference", "explanation", "self_regulation"),
}


def _mock_grounded_evidence(request: CoachRequest) -> tuple[str, str] | None:
    """Return one bounded, validated retrieved excerpt for the visible mock reply.

    The application supplies ``retrieved_chunks`` only after notebook-scope and
    label validation.  Keeping the mock on that structured contract (rather
    than parsing provider prompt text) preserves the same retrieval boundary
    that a future Bedrock adapter will use.  No source context means no quote
    or citation, so ordinary offline coaching stays unchanged.
    """
    if not request.source_context.strip():
        return None
    for chunk in request.retrieved_chunks:
        label = str(chunk.label or "").strip()
        excerpt = " ".join(str(chunk.excerpt or "").split()).strip()
        if not _CITATION_LABEL.fullmatch(label) or not excerpt:
            continue
        if len(excerpt) > _MAX_GROUNDED_EXCERPT_CHARS:
            excerpt = excerpt[: _MAX_GROUNDED_EXCERPT_CHARS - 1].rstrip() + "…"
        return excerpt, label
    return None


def _mock_facione_scores(stage_id: str, *, is_advancing: bool) -> FacioneDimensionScores:
    """Return stage-specific deterministic scores without simulating mastery.

    Relevant dimensions receive ``1`` for STAY or ``2`` for ADVANCE. Every
    other dimension stays at ``0``; the offline mock never emits ``3`` or ``4``.
    """
    relevant_dimensions = _FACIONE_DIMENSIONS_BY_STAGE.get(stage_id, ())
    relevant_score = 2 if is_advancing else 1
    scores = {
        dimension: (relevant_score if dimension in relevant_dimensions else 0)
        for dimension in FacioneDimensionScores.model_fields
    }
    return FacioneDimensionScores(**scores)


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
    """Return predictable structured coaching output without contacting a model.

    Composes the same stage prompt path as live providers so tests can assert
    which authoritative stage prompt was selected. Raw prompt text is kept only
    on this instance for tests and is never returned through normal APIs.
    """

    def __init__(self, recommendation: StageDecision | None = None):
        self.recommendation = recommendation
        self.last_prepared_prompt: PreparedCoachPrompt | None = None
        self.last_stage_id: str | None = None

    def assess(self, request: CoachRequest) -> tuple[str, EducationalAssessment]:
        """Build a repeatable coaching turn with visible, guided progression.

        An explicit recommendation keeps unit tests fully controllable. In the
        normal local demonstration, Quick guidance recommends advance after one
        follow-up contribution at the stage; Strict waits for a second follow-up
        so progression is a little stricter. This is turn-based demo behavior, not
        a claim that the mock provider semantically evaluated the writing.
        """
        prepared = compose_coach_prompt(request)
        self.last_prepared_prompt = prepared
        self.last_stage_id = request.current_stage
        stage = STAGE_BY_ID[request.current_stage]
        coaching_profile = coaching_profile_for_response_detail(
            request.response_detail
        )
        prior_stage_contributions = sum(
            1
            for message in request.history
            if message.get("role") == "assistant"
            and isinstance((message.get("metadata") or {}).get("assessment"), dict)
            and (message.get("metadata") or {})["assessment"].get("current_stage")
            == stage.id
            and str(
                (message.get("metadata") or {}).get("coaching_profile") or ""
            ).strip().lower()
            in {"", coaching_profile}
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
        grounded_evidence = _mock_grounded_evidence(request)
        evidence_note = (
            f'One retrieved finding is: “{grounded_evidence[0]}” '
            f'[{grounded_evidence[1]}].'
            if grounded_evidence
            else ""
        )
        evidence_block = f"{evidence_note}\n\n" if evidence_note else ""
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
                f"{evidence_block}"
                f"{follow_up}"
            )
        else:
            response = (
                f"**{stage.label}**\n\n"
                "That's an interesting direction. Let's make this step a little more "
                f"precise.\n\n{evidence_block}{question}"
            )
        return response, assessment
