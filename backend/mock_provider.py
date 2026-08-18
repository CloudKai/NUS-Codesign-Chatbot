"""Deterministic local provider for API-free tests and demonstrations."""

from __future__ import annotations

import re

from .domain import (
    ClearCode,
    CoachRequest,
    EducationalAssessment,
    FacioneBehavior,
    FacioneDimensionScores,
    HolisticCandidate,
    ProviderAssessmentResult,
    ProvisionalResearchCoding,
    ResearchCodingStatus,
    ResearchEvidence,
    StageDecision,
)
from .prompts import PreparedCoachPrompt, compose_coach_prompt
from .specialists.routing import (
    SPECIALIST_QA,
    SPECIALIST_REVIEW,
    select_specialist,
)
from .student_journey import (
    STAGE_BY_ID,
    THINKING_STAGES,
    next_stage_id,
    personalized_stage_questions,
    stage_guidance_questions,
)


_CITATION_LABEL = re.compile(r"S\d+")
_MAX_GROUNDED_EXCERPT_CHARS = 320
_CLEAR_BY_STAGE = {
    "problem_identification": ClearCode.CONCISE,
    "concept_generation": ClearCode.ADAPTIVE,
    "design_specification": ClearCode.EXPLICIT,
    "deep_analysis": ClearCode.LOGICAL,
    "reflection": ClearCode.REFLECTIVE,
}
_FACIONE_BEHAVIORS_BY_STAGE = {
    "problem_identification": [FacioneBehavior.ANALYSIS, FacioneBehavior.INTERPRETATION],
    "concept_generation": [FacioneBehavior.INFERENCE, FacioneBehavior.INTERPRETATION],
    "design_specification": [FacioneBehavior.EXPLANATION, FacioneBehavior.INFERENCE],
    "deep_analysis": [FacioneBehavior.ANALYSIS, FacioneBehavior.EVALUATION],
    "reflection": [FacioneBehavior.SELF_REGULATION, FacioneBehavior.EVALUATION],
}


def _prior_assessed_turns(request: CoachRequest) -> int:
    """Count prior assessments eligible for the active Quick/Strict profile.

    Profile-tagged Quick assessments do not satisfy Strict. Untagged legacy
    assessments remain eligible for both profiles so existing conversations do
    not lose progression after this internal metadata was introduced.
    """
    active_profile = "strict" if request.response_detail == "long" else "quick"
    count = 0
    for message in request.history:
        if message.get("role") != "assistant":
            continue
        metadata = message.get("metadata") or {}
        if not isinstance(metadata, dict) or not isinstance(
            metadata.get("assessment"), dict
        ):
            continue
        if str(metadata.get("thinking_stage") or "") != request.current_stage:
            continue
        profile = str(metadata.get("coaching_profile") or "").strip().lower()
        if not profile:
            research = metadata.get("research_coding")
            if isinstance(research, dict):
                profile = str(research.get("coaching_profile") or "").strip().lower()
        if not profile or profile == active_profile:
            count += 1
    return count


def _mock_research_coding(
    request: CoachRequest,
) -> ProvisionalResearchCoding:
    """Return explicit stage-based research coding without text heuristics."""
    quote = request.student_message.strip()[:2_000]
    holistic = (
        HolisticCandidate(
            score=2,
            rationale=(
                "The contribution shows some reflective reasoning, with important "
                "opportunities to deepen evaluation across the conversation."
            ),
            evidence_quotes=[quote],
        )
        if request.current_stage == "reflection"
        else None
    )
    return ProvisionalResearchCoding(
        coding_status=ResearchCodingStatus.CODED,
        dominant_clear=_CLEAR_BY_STAGE[request.current_stage],
        facione_behaviors=_FACIONE_BEHAVIORS_BY_STAGE[request.current_stage],
        ethics_concepts=[],
        evidence=[
            ResearchEvidence(
                quote=quote,
                rationale="The quoted contribution is the direct evidence used for this provisional coding.",
                confidence=0.7,
            )
        ],
        holistic_candidate=holistic,
    )


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
    if stage_id == "problem_identification":
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
    if stage_id == "concept_generation":
        strengths = ["You are starting to connect a concept to the identified need."]
        improvements = (
            []
            if is_advancing
            else ["Compare this concept with one meaningfully different alternative."]
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

    provider_id = "mock"

    def __init__(self, recommendation: StageDecision | None = None):
        self.recommendation = recommendation
        self.last_prepared_prompt: PreparedCoachPrompt | None = None
        self.last_stage_id: str | None = None

    def model_id_for(self, request: CoachRequest) -> str:
        """Return the deterministic implementation version used for this turn."""
        return "deterministic-v1"

    def assess(self, request: CoachRequest) -> ProviderAssessmentResult:
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
        requested = str(request.specialist or "").strip().lower()
        specialist = select_specialist(
            request.student_message, requested=request.specialist
        )
        if specialist == SPECIALIST_QA:
            return self._qa_result(request)
        if requested == SPECIALIST_REVIEW:
            return self._review_result(request)
        stage = STAGE_BY_ID[request.current_stage]
        prior_stage_contributions = _prior_assessed_turns(request)
        advance_after = 2 if request.response_detail == "long" else 1
        guided_recommendation = (
            StageDecision.ADVANCE
            if prior_stage_contributions >= advance_after and stage.id != "reflection"
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
        return ProviderAssessmentResult(
            response_text=response,
            assessment=assessment,
            research_coding=_mock_research_coding(request),
        )

    def _qa_result(self, request: CoachRequest) -> ProviderAssessmentResult:
        """Return a grounded course answer that does not coach or advance."""
        evidence = _mock_grounded_evidence(request)
        if evidence:
            excerpt, label = evidence
            response = (
                f"Week 1 introduces the course framing using the selected materials. "
                f"One retrieved excerpt is: “{excerpt}” [{label}]."
            )
        else:
            response = (
                "I couldn't find a validated excerpt from the selected course "
                "material for that question."
            )
        summary = " ".join(request.student_message.split())[:500]
        assessment = EducationalAssessment(
            current_stage=request.current_stage,
            contribution_summary=summary or "Student asked a course question.",
            stage_assessment="Course-information question; Thinking Path stage unchanged.",
            critical_understanding_level="Not assessed",
            confidence=0.5,
            recommendation=StageDecision.STAY,
            recommendation_rationale="Q&A specialist does not recommend Thinking Path changes.",
            guidance_questions=[],
            learning_summary="The student asked a course-information question.",
        )
        return ProviderAssessmentResult(
            response_text=response,
            assessment=assessment,
            research_coding=None,
            specialist="qa",
            qualifying_coaching_turn=False,
        )

    def _review_result(self, request: CoachRequest) -> ProviderAssessmentResult:
        """Return formative synthesis that is not a grade and does not advance."""
        summary = " ".join(request.student_message.split())[:500]
        response = (
            "You have started to locate the problem in a real context. "
            "Next, make the affected people and intended outcome more specific. "
            "This is formative feedback, not a grade."
        )
        assessment = EducationalAssessment(
            current_stage=request.current_stage,
            contribution_summary=summary or "Student asked for a formative review.",
            stage_assessment="Formative review of progress so far.",
            critical_understanding_level="Not assessed",
            confidence=0.5,
            recommendation=StageDecision.STAY,
            recommendation_rationale="Formative Review does not recommend Thinking Path changes.",
            guidance_questions=[],
            learning_summary="Formative review of the student's reasoning.",
            review_strengths=["You located the work in a concrete setting."],
            review_improvements=["Name who is affected and what success would look like."],
            review_depth="deep",
            review_model="global.anthropic.claude-sonnet-4-6",
            review_trigger="explicit",
        )
        return ProviderAssessmentResult(
            response_text=response,
            assessment=assessment,
            research_coding=None,
            specialist="review",
            qualifying_coaching_turn=False,
            deep_review_succeeded=True,
            review_trigger="explicit",
        )
