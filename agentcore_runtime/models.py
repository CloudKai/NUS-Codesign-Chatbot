"""Focused coach_turn wire schema for the AgentCore harness.

This schema matches the companion application's production contract without
importing ``backend.domain``. Live-model variants already accepted by the
application (uppercase ``stay``/``advance``, object-shaped
``stage_assessment``) are coerced here so the harness can validate before
returning JSON. Invalid optional research coding is dropped; invalid
coaching assessment fails closed.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator, model_validator


def _stage_assessment_as_text(value: Any) -> Any:
    """Flatten live-model stage_assessment objects or lists into one string."""
    if isinstance(value, str) or value is None:
        return value
    if isinstance(value, list):
        return " ".join(str(item).strip() for item in value if str(item).strip())
    if not isinstance(value, Mapping):
        return value
    for key in ("text", "summary", "assessment", "stage_assessment"):
        item = value.get(key)
        if isinstance(item, str) and item.strip():
            return item.strip()
    parts: list[str] = []
    for key in ("strengths", "improvements", "gaps", "notes"):
        item = value.get(key)
        if isinstance(item, list):
            joined = "; ".join(
                str(entry).strip() for entry in item if str(entry).strip()
            )
            if joined:
                parts.append(f"{key}: {joined}")
        elif isinstance(item, str) and item.strip():
            parts.append(item.strip())
    return " ".join(parts).strip()


class FacioneScoresOutput(BaseModel):
    """Six Facione dimensions using 0=not started through 4=Strong."""

    model_config = ConfigDict(extra="ignore")

    analysis: int = Field(ge=0, le=4, default=0)
    interpretation: int = Field(ge=0, le=4, default=0)
    inference: int = Field(ge=0, le=4, default=0)
    evaluation: int = Field(ge=0, le=4, default=0)
    explanation: int = Field(ge=0, le=4, default=0)
    self_regulation: int = Field(ge=0, le=4, default=0)


class CitationOutput(BaseModel):
    """One [S#] citation over a selected notebook source."""

    model_config = ConfigDict(extra="ignore")

    source_id: str = ""
    label: str
    title: str = ""
    excerpt: str = ""


class AssessmentOutput(BaseModel):
    """Required educational assessment fields for one coach_turn."""

    model_config = ConfigDict(extra="ignore")

    current_stage: str
    contribution_summary: str = Field(min_length=1, max_length=2_000)
    stage_assessment: str = Field(min_length=1, max_length=4_000)
    critical_understanding_level: str = Field(min_length=1, max_length=120)
    confidence: float = Field(ge=0.0, le=1.0)
    recommendation: str
    recommendation_rationale: str = Field(min_length=1, max_length=4_000)
    guidance_questions: list[str] = Field(default_factory=list, max_length=3)
    learning_summary: str = Field(min_length=1, max_length=4_000)
    citations: list[CitationOutput] = Field(default_factory=list)
    facione_scores: FacioneScoresOutput = Field(default_factory=FacioneScoresOutput)
    evidence_identified: list[str] = Field(default_factory=list)
    assumptions_identified: list[str] = Field(default_factory=list)
    missing_reasoning_elements: list[str] = Field(default_factory=list)
    working_conclusion: str = Field(default="", max_length=4_000)
    understanding_change: str = Field(default="", max_length=4_000)
    review_strengths: list[str] = Field(default_factory=list, max_length=4)
    review_improvements: list[str] = Field(default_factory=list, max_length=4)

    @model_validator(mode="before")
    @classmethod
    def coerce_live_provider_shapes(cls, value: Any) -> Any:
        """Accept uppercase stay/advance and object-shaped stage_assessment."""
        if not isinstance(value, dict):
            return value
        data = dict(value)
        stage = data.get("stage_assessment")
        if isinstance(stage, Mapping):
            if not data.get("review_strengths") and isinstance(
                stage.get("strengths"), list
            ):
                data["review_strengths"] = stage.get("strengths")
            if not data.get("review_improvements") and isinstance(
                stage.get("improvements"), list
            ):
                data["review_improvements"] = stage.get("improvements")
            data["stage_assessment"] = _stage_assessment_as_text(stage)
        elif isinstance(stage, list):
            data["stage_assessment"] = _stage_assessment_as_text(stage)
        recommendation = data.get("recommendation")
        if isinstance(recommendation, str):
            data["recommendation"] = recommendation.strip().lower()
        return data

    @field_validator("recommendation")
    @classmethod
    def recommendation_must_be_stay_or_advance(cls, value: str) -> str:
        """Reject recommendations outside the two-value production contract."""
        cleaned = str(value or "").strip().lower()
        if cleaned not in {"stay", "advance"}:
            raise ValueError("recommendation must be stay or advance")
        return cleaned

    @field_validator("guidance_questions")
    @classmethod
    def guidance_questions_are_questions(cls, values: list[str]) -> list[str]:
        """Normalize non-empty guidance prompts while preserving model wording."""
        cleaned = [value.strip() for value in values if value and value.strip()]
        if any(not value.endswith("?") for value in cleaned):
            raise ValueError("Guidance questions must end with a question mark")
        return cleaned


class CoachTurnOutput(BaseModel):
    """Validated coach_turn object returned by the production harness."""

    model_config = ConfigDict(extra="ignore")

    response_text: str = Field(min_length=1)
    assessment: AssessmentOutput
    research_coding: dict[str, Any] | None = None

    @field_validator("research_coding", mode="before")
    @classmethod
    def invalid_research_coding_becomes_absent(cls, value: Any) -> Any:
        """Drop invalid optional research data without losing valid coaching."""
        if value is None:
            return None
        if not isinstance(value, dict):
            return None
        if "coding_status" not in value and "dominant_clear" not in value:
            return None
        return value


class QATurnOutput(BaseModel):
    """Grounded course Q&A result. Never advances the Thinking Path."""

    model_config = ConfigDict(extra="ignore")

    response_text: str = Field(min_length=1)
    citations: list[CitationOutput] = Field(default_factory=list)


class ReviewTurnOutput(BaseModel):
    """Formative review result. Never a grade and never a stage transition."""

    model_config = ConfigDict(extra="ignore")

    response_text: str = Field(min_length=1)
    strengths: list[str] = Field(default_factory=list, max_length=4)
    areas_to_develop: list[str] = Field(default_factory=list, max_length=4)
    synthesis: str = Field(min_length=1)
    citations: list[CitationOutput] = Field(default_factory=list)
    facione_profile: FacioneScoresOutput | None = None


def parse_coach_turn_output(value: Any) -> CoachTurnOutput:
    """Validate one coach_turn payload or raise ``ValidationError``.

    Args:
        value: A Pydantic model, mapping, or JSON-compatible object.

    Returns:
        A validated :class:`CoachTurnOutput`.

    Raises:
        ValidationError: When coaching fields are missing or invalid.
    """
    if isinstance(value, CoachTurnOutput):
        return value
    if hasattr(value, "model_dump") and callable(value.model_dump):
        try:
            return CoachTurnOutput.model_validate(value.model_dump(mode="json"))
        except (TypeError, ValidationError):
            return CoachTurnOutput.model_validate(value)
    return CoachTurnOutput.model_validate(value)


def parse_qa_turn_output(value: Any) -> QATurnOutput:
    """Validate one Q&A payload or raise ``ValidationError``."""
    if isinstance(value, QATurnOutput):
        return value
    if hasattr(value, "model_dump") and callable(value.model_dump):
        try:
            return QATurnOutput.model_validate(value.model_dump(mode="json"))
        except (TypeError, ValidationError):
            return QATurnOutput.model_validate(value)
    return QATurnOutput.model_validate(value)


def parse_review_turn_output(value: Any) -> ReviewTurnOutput:
    """Validate one Review payload or raise ``ValidationError``."""
    if isinstance(value, ReviewTurnOutput):
        return value
    if hasattr(value, "model_dump") and callable(value.model_dump):
        try:
            return ReviewTurnOutput.model_validate(value.model_dump(mode="json"))
        except (TypeError, ValidationError):
            return ReviewTurnOutput.model_validate(value)
    return ReviewTurnOutput.model_validate(value)
