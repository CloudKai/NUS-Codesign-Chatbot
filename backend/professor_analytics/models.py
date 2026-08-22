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


class ProfessorNotebookSummary(BaseModel):
    """Notebook header metadata for a lecturer workspace."""

    id: str
    title: str
    current_stage: str | None = None
    last_active: str | None = None
    student_messages: int = 0
    coach_messages: int = 0
    assistant_messages: int = 0
    completed_stage_count: int = 0


class ProfessorMessageAttachment(BaseModel):
    """Allow-listed attachment descriptor on one transcript message."""

    id: str
    title: str
    mime: str
    kind: str
    size: int = 0


class ProfessorMessageCitation(BaseModel):
    """Allow-listed citation descriptor on one transcript message."""

    id: str
    label: str | None = None
    title: str | None = None


class ProfessorTranscriptMessage(BaseModel):
    """One active-branch transcript row for lecturer pagination."""

    id: str
    role: str
    content: str
    created_at: str | None = None
    attachments: list[ProfessorMessageAttachment] = Field(default_factory=list)
    citations: list[ProfessorMessageCitation] = Field(default_factory=list)


class ProfessorMessagePage(BaseModel):
    """One paginated active-branch transcript page for lecturers."""

    notebook: ProfessorNotebookSummary
    messages: list[ProfessorTranscriptMessage] = Field(default_factory=list)
    next_cursor: str | None = None


class ProfessorSourcesResponse(BaseModel):
    """Grouped library sources for one authorised notebook."""

    notebook: ProfessorNotebookSummary
    sources: list[ProfessorSourceSummary] = Field(default_factory=list)


class ProfessorJourneyStage(BaseModel):
    """One thinking-path stage with persisted completion state."""

    id: str
    label: str
    state: str


class ProfessorJourneyProjection(BaseModel):
    """Read-only journey projection without transcript bodies."""

    notebook: ProfessorNotebookSummary
    current_stage: str | None = None
    completed_stages: list[str] = Field(default_factory=list)
    stages: list[ProfessorJourneyStage] = Field(default_factory=list)
    hmw_scaffold: dict[str, Any] = Field(default_factory=dict)


class ProfessorReviewProjection(BaseModel):
    """Persisted Deep Review / learning review fields for lecturer display."""

    notebook: ProfessorNotebookSummary
    summary: str = ""
    facione_scores: dict[str, Any] = Field(default_factory=dict)
    strength_sections: list[dict[str, Any]] = Field(default_factory=list)
    improvement_sections: list[dict[str, Any]] = Field(default_factory=list)
    conclusion: str = ""


class ProfessorWorkspaceTranscript(BaseModel):
    """Active-branch transcript messages without duplicated notebook metadata."""

    messages: list[dict[str, Any]] = Field(default_factory=list)


class ProfessorSourceSummary(BaseModel):
    """Allow-listed source metadata for lecturer workspace lists."""

    id: str
    title: str
    kind: str | None = None
    mime: str | None = None
    size: int = 0
    group: str | None = None
    selected: bool = False
    origin: str | None = None
    locked: bool = False
    has_file: bool = False


class ProfessorLearningState(BaseModel):
    """Read-only journey, HMW, and Review projections for one notebook."""

    journey: dict[str, Any] = Field(default_factory=dict)
    hmw_scaffold: dict[str, Any] = Field(default_factory=dict)
    review: dict[str, Any] = Field(default_factory=dict)


class NotebookWorkspaceResponse(BaseModel):
    """Read-only student notebook workspace for lecturer review."""

    notebook: ProfessorNotebookSummary
    transcript: ProfessorWorkspaceTranscript
    sources: list[ProfessorSourceSummary] = Field(default_factory=list)
    learning: ProfessorLearningState = Field(default_factory=ProfessorLearningState)


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
