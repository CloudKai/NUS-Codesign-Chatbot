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


class FacioneDimensionScores(BaseModel):
    """Facione critical-thinking scores for one coaching assessment.

    Each dimension uses the Holistic Critical Thinking Scoring Rubric plus a
    not-started state: ``0`` not started, ``1`` Weak, ``2`` Unacceptable,
    ``3`` Acceptable, ``4`` Strong.
    """

    analysis: int = Field(ge=0, le=4, default=0)
    interpretation: int = Field(ge=0, le=4, default=0)
    inference: int = Field(ge=0, le=4, default=0)
    evaluation: int = Field(ge=0, le=4, default=0)
    explanation: int = Field(ge=0, le=4, default=0)
    self_regulation: int = Field(ge=0, le=4, default=0)


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
    facione_scores: FacioneDimensionScores = Field(
        default_factory=FacioneDimensionScores
    )
    review_strengths: list[str] = Field(default_factory=list, max_length=4)
    review_improvements: list[str] = Field(default_factory=list, max_length=4)

    @field_validator("guidance_questions")
    @classmethod
    def guidance_questions_are_questions(cls, values: list[str]) -> list[str]:
        """Normalize non-empty guidance prompts while preserving model wording."""
        cleaned = [value.strip() for value in values if value and value.strip()]
        if any(not value.endswith("?") for value in cleaned):
            raise ValueError("Guidance questions must end with a question mark")
        return cleaned

    @field_validator("review_strengths", "review_improvements")
    @classmethod
    def normalize_review_feedback(cls, values: list[str]) -> list[str]:
        """Keep short supportive feedback items and drop blanks."""
        cleaned: list[str] = []
        seen: set[str] = set()
        for value in values:
            item = " ".join(str(value).split()).strip()
            if not item:
                continue
            key = item.lower()
            if key in seen:
                continue
            seen.add(key)
            cleaned.append(item[:400])
        return cleaned[:4]

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


class CoachImageInput(BaseModel):
    """A selected notebook image resolved for a coaching turn.

    Local adapters may use a data URL. Future AWS adapters can resolve the same
    ``source_id`` from object storage without changing the coach workflow.
    """

    model_config = ConfigDict(frozen=True)

    source_id: str
    mime: str = "image/png"
    data_url: str = Field(min_length=1, max_length=12_000_000)


VALID_STAGE_IDS = frozenset(
    {
        "focus",
        "evidence",
        "assumptions",
        "perspectives",
        "synthesis",
        "conclusion",
    }
)


class CoachRequest(BaseModel):
    """Input required to run one local critical-thinking workflow turn.

    Clients may hint stage, history, and sources, but the application service
    reloads those values from the notebook store and rejects mismatches.
    ``student_project_context`` and ``conversation_summary`` are also filled
    server-side for prompt composition; clients cannot inject prompt files or
    stage instructions through this contract.
    """

    thread_id: str
    student_message: str = Field(min_length=1, max_length=50_000)
    current_stage: str
    response_detail: str = Field(pattern="^(short|long)$")
    source_ids: list[str] = Field(default_factory=list)
    source_context: str = ""
    student_project_context: str = ""
    conversation_summary: str = ""
    image_inputs: list[CoachImageInput] = Field(default_factory=list)
    allow_model_knowledge: bool = False
    history: list[dict[str, Any]] = Field(default_factory=list)
    model_id: str | None = None
    reasoning_effort: str | None = None

    @field_validator("current_stage")
    @classmethod
    def current_stage_must_be_known(cls, value: str) -> str:
        """Reject unknown Thinking Path stage identifiers before the workflow runs."""
        stage = str(value or "").strip().lower()
        if stage not in VALID_STAGE_IDS:
            raise ValueError(
                "current_stage must be one of: " + ", ".join(sorted(VALID_STAGE_IDS))
            )
        return stage

    @field_validator("source_ids")
    @classmethod
    def source_ids_must_be_unique(cls, values: list[str]) -> list[str]:
        """Normalize and reject duplicate source identifiers in one request."""
        cleaned = [str(value).strip() for value in values if str(value).strip()]
        if len(cleaned) != len(set(cleaned)):
            raise ValueError("source_ids must be unique")
        return cleaned


class CoachTurn(BaseModel):
    """Stable result of one coaching workflow turn for API and UI consumers."""

    response_text: str = Field(min_length=1)
    assessment: EducationalAssessment
    pending_transition: PendingPhaseTransition | None = None
    auto_advanced_to: str | None = None


class ProviderCoachOutput(BaseModel):
    """Structured provider payload before workflow-side transition handling."""

    response_text: str = Field(min_length=1)
    assessment: EducationalAssessment


def openai_strict_schema(model: type[BaseModel]) -> dict[str, Any]:
    """Adapt a Pydantic JSON schema for OpenAI strict structured outputs."""

    def harden(node: Any) -> Any:
        if isinstance(node, list):
            return [harden(item) for item in node]
        if not isinstance(node, dict):
            return node
        hardened = {key: harden(value) for key, value in node.items()}
        if hardened.get("type") == "object" or "properties" in hardened:
            properties = hardened.setdefault("properties", {})
            hardened["additionalProperties"] = False
            hardened["required"] = list(properties.keys())
        return hardened

    schema = model.model_json_schema()
    return harden(schema)


class PreferencePatch(BaseModel):
    """Partial update for local user preferences."""

    model_config = ConfigDict(extra="allow")

    appearance: str | None = None
    active_thread_id: str | None = None
    sources_expander_state: dict[str, Any] | None = None


class NotebookCreateRequest(BaseModel):
    """Payload for creating a notebook through the typed API."""

    name: str = Field(default="Untitled notebook", min_length=1, max_length=120)
    model_id: str = Field(min_length=1, max_length=120)
    support_mode: str = Field(min_length=1, max_length=120)
    assignment: dict[str, str] = Field(default_factory=dict)
    metadata: dict[str, Any] = Field(default_factory=dict)


class NotebookUpdateRequest(BaseModel):
    """Partial notebook rename / metadata merge."""

    name: str | None = Field(default=None, min_length=1, max_length=120)
    metadata: dict[str, Any] | None = None


class MessageCreateRequest(BaseModel):
    """Persist one chat message outside the coaching workflow (e.g. welcome)."""

    role: str = Field(pattern="^(user|assistant|system)$")
    content: str = Field(min_length=1, max_length=100_000)
    metadata: dict[str, Any] = Field(default_factory=dict)


class SourceUpdateRequest(BaseModel):
    """Rename and/or change selection for one notebook source."""

    title: str | None = Field(default=None, min_length=1, max_length=180)
    selected: bool | None = None


class SourceSelectAllRequest(BaseModel):
    """Select or deselect every source in a notebook."""

    selected: bool
