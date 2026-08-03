"""Typed domain objects for the critical-thinking coach.

These models intentionally contain no Streamlit, database, provider, or graph
dependencies. They define the durable contract between the user interface,
application services, and infrastructure adapters.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator


class StageDecision(StrEnum):
    """A model recommendation for the student's current learning stage."""

    STAY = "stay"
    ADVANCE = "advance"


class TransitionStatus(StrEnum):
    """The lifecycle state of a persisted stage-transition recommendation."""

    PENDING = "pending"
    CONFIRMED = "confirmed"
    REJECTED = "rejected"


class CitationReference(BaseModel):
    """A stable source citation that can be resolved in the notebook source viewer."""

    model_config = ConfigDict(frozen=True)

    source_id: str
    label: str
    title: str
    excerpt: str = ""


class EducationalAssessment(BaseModel):
    """Validated coaching assessment produced for one student contribution."""

    current_stage: str
    contribution_summary: str = Field(min_length=1, max_length=2_000)
    stage_assessment: str = Field(min_length=1, max_length=4_000)
    evidence_identified: list[str] = Field(default_factory=list)
    assumptions_identified: list[str] = Field(default_factory=list)
    missing_reasoning_elements: list[str] = Field(default_factory=list)
    critical_understanding_level: str = Field(min_length=1, max_length=120)
    confidence: float = Field(ge=0.0, le=1.0)
    recommendation: StageDecision
    recommendation_rationale: str = Field(min_length=1, max_length=4_000)
    guidance_questions: list[str] = Field(default_factory=list, max_length=3)
    learning_summary: str = Field(min_length=1, max_length=4_000)
    working_conclusion: str = Field(default="", max_length=4_000)
    understanding_change: str = Field(default="", max_length=4_000)
    citations: list[CitationReference] = Field(default_factory=list)

    @field_validator("guidance_questions")
    @classmethod
    def guidance_questions_are_questions(cls, values: list[str]) -> list[str]:
        """Normalize non-empty guidance prompts while preserving model wording."""
        cleaned = [value.strip() for value in values if value and value.strip()]
        if any(not value.endswith("?") for value in cleaned):
            raise ValueError("Guidance questions must end with a question mark")
        return cleaned


class PendingPhaseTransition(BaseModel):
    """A student-visible stage transition that awaits an explicit decision."""

    id: str
    thread_id: str
    from_stage: str
    to_stage: str
    assessment: EducationalAssessment
    status: TransitionStatus = TransitionStatus.PENDING
    created_at: str
    resolved_at: str | None = None


class CoachRequest(BaseModel):
    """Input required to run one local critical-thinking workflow turn."""

    thread_id: str
    student_message: str = Field(min_length=1, max_length=50_000)
    current_stage: str
    response_detail: str = Field(pattern="^(short|long)$")
    source_ids: list[str] = Field(default_factory=list)
    source_context: str = ""
    allow_model_knowledge: bool = False
    history: list[dict[str, Any]] = Field(default_factory=list)


class CoachTurn(BaseModel):
    """Stable result of one coaching workflow turn for API and UI consumers."""

    response_text: str = Field(min_length=1)
    assessment: EducationalAssessment
    pending_transition: PendingPhaseTransition | None = None
    auto_advanced_to: str | None = None
