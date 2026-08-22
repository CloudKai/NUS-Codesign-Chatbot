"""Typed public contracts for the professor analytics API.

The models deliberately expose learning aggregates, not authentication claims,
storage keys, or source contents.  Individual conversation text is available
only from the authorised student-detail endpoint.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class AttentionSignal(BaseModel):
    """One transparent, deterministic reason to invite staff follow-up."""

    code: str
    reason: str


class StageDistributionItem(BaseModel):
    """Class count and share at one authoritative thinking stage."""

    stage: str
    count: int
    percentage: float


class ScoreValue(BaseModel):
    """A score value that remains nullable when no valid assessment exists."""

    value: float | None = None
    sample_size: int = 0


class StudentListItem(BaseModel):
    """Privacy-minimised class roster row for a professor."""

    id: str
    name: str
    email: str | None = None
    current_stage: str | None = None
    stage_progress: int = 0
    facione_overall: float | None = None
    student_messages: int = 0
    active_days: int = 0
    last_active: str | None = None
    needs_attention: list[AttentionSignal] = Field(default_factory=list)


class OverviewResponse(BaseModel):
    """Compact class-level snapshot used by the Overview dashboard."""

    generated_at: str
    students: int
    active_students_week: int
    total_conversations: int
    median_facione: ScoreValue
    median_stage: str | None = None
    median_active_days: float | None = None
    stage_distribution: list[StageDistributionItem] = Field(default_factory=list)
    facione_profile: dict[str, ScoreValue] = Field(default_factory=dict)
    weekly_activity: list[dict[str, Any]] = Field(default_factory=list)
    attention_students: list[StudentListItem] = Field(default_factory=list)
    attention_students_count: int = 0
    summary: str


class StudentsResponse(BaseModel):
    """Filterable roster response; filtering remains server-side and read-only."""

    students: list[StudentListItem] = Field(default_factory=list)
    total: int = 0


class StudentDetailResponse(BaseModel):
    """One student learning journey, including only authorised transcript data."""

    student: StudentListItem
    completed_stages: list[str] = Field(default_factory=list)
    facione_profile: dict[str, float | None] = Field(default_factory=dict)
    class_facione_profile: dict[str, ScoreValue] = Field(default_factory=dict)
    class_median_facione: ScoreValue = Field(default_factory=ScoreValue)
    facione_trend: list[dict[str, Any]] = Field(default_factory=list)
    engagement: dict[str, Any] = Field(default_factory=dict)
    notebooks: list[dict[str, Any]] = Field(default_factory=list)
    conversations: list[dict[str, Any]] = Field(default_factory=list)


class ConversationTranscriptResponse(BaseModel):
    """One selected active-branch transcript for an authorised professor."""

    notebook_id: str
    title: str
    stage: str | None = None
    last_active: str | None = None
    messages: list[dict[str, Any]] = Field(default_factory=list)


class CriticalThinkingResponse(BaseModel):
    """Teaching-focused assessment aggregates, not a claim of causal impact."""

    dimensions: dict[str, ScoreValue] = Field(default_factory=dict)
    stage_distribution: list[StageDistributionItem] = Field(default_factory=list)
    distribution: list[dict[str, Any]] = Field(default_factory=list)
    stage_comparison: list[dict[str, Any]] = Field(default_factory=list)
    trend: list[dict[str, Any]] = Field(default_factory=list)


class EngagementResponse(BaseModel):
    """Usage measures kept distinct from critical-thinking performance."""

    weekly_active_students: list[dict[str, Any]] = Field(default_factory=list)
    weekly_messages: list[dict[str, Any]] = Field(default_factory=list)
    active_day_distribution: list[dict[str, Any]] = Field(default_factory=list)
    estimated_active_time_distribution: list[dict[str, Any]] = Field(default_factory=list)
    assessed_coach_responses: int = 0
    source_grounded_responses: int = 0
    source_grounded_percentage: float | None = None
    inactive_students: list[StudentListItem] = Field(default_factory=list)
    definition: str
