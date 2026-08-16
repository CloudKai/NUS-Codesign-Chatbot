"""Typed domain objects for the critical-thinking coach.

These models intentionally contain no Streamlit, database, provider, or graph
dependencies. They define the durable contract between the user interface,
application services, and infrastructure adapters.
"""

from __future__ import annotations

from collections.abc import Mapping
from enum import StrEnum
from typing import Any, Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    ValidationError,
    field_validator,
    model_validator,
)


RESEARCH_CODING_VERSION = "clear-facione-ethics-v1"


class StageDecision(StrEnum):
    """A model recommendation for the student's current learning stage."""

    STAY = "stay"
    ADVANCE = "advance"


class ResearchCodingStatus(StrEnum):
    """Soft-validation status for provisional research coding."""

    CODED = "coded"
    PARTIAL = "partial"
    UNCODED = "uncoded"


class ClearCode(StrEnum):
    """Dominant CLEAR behavior demonstrated in one student contribution."""

    CONCISE = "concise"
    LOGICAL = "logical"
    EXPLICIT = "explicit"
    ADAPTIVE = "adaptive"
    REFLECTIVE = "reflective"


class FacioneBehavior(StrEnum):
    """Observable Facione behavior tag; this is not a holistic score."""

    ANALYSIS = "analysis"
    INTERPRETATION = "interpretation"
    INFERENCE = "inference"
    EVALUATION = "evaluation"
    EXPLANATION = "explanation"
    SELF_REGULATION = "self_regulation"


class EthicsConcept(StrEnum):
    """Ethics concepts that may be explicitly evidenced in a contribution."""

    FAIRNESS = "fairness"
    PRIVACY = "privacy"
    TRANSPARENCY = "transparency"
    NON_MALEFICENCE = "non_maleficence"
    RESPONSIBILITY = "responsibility"


class ResearchEvidence(BaseModel):
    """Quoted evidence and provisional rationale for one research code."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    quote: str = Field(min_length=1, max_length=2_000)
    rationale: str = Field(min_length=1, max_length=1_000)
    confidence: float = Field(ge=0.0, le=1.0)


class HolisticCandidate(BaseModel):
    """Conversation-based provisional Facione candidate, never a grade."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    score: int = Field(ge=1, le=4)
    rationale: str = Field(min_length=1, max_length=1_000)
    evidence_quotes: list[str] = Field(default_factory=list, max_length=3)

    @field_validator("evidence_quotes")
    @classmethod
    def normalize_evidence_quotes(cls, values: list[str]) -> list[str]:
        """Keep at most three non-empty, bounded evidence quotations."""
        return [" ".join(str(value).split())[:2_000] for value in values if str(value).strip()][:3]


class ProvisionalResearchCoding(BaseModel):
    """Optional research coding produced alongside, but isolated from, coaching."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    coding_status: ResearchCodingStatus
    dominant_clear: ClearCode | None = None
    facione_behaviors: list[FacioneBehavior] = Field(default_factory=list, max_length=2)
    ethics_concepts: list[EthicsConcept] = Field(default_factory=list, max_length=5)
    evidence: list[ResearchEvidence] = Field(default_factory=list, max_length=8)
    holistic_candidate: HolisticCandidate | None = None

    @model_validator(mode="after")
    def dominant_clear_matches_status(self) -> "ProvisionalResearchCoding":
        """Require one CLEAR code only when the result is fully coded."""
        if self.coding_status is ResearchCodingStatus.CODED and self.dominant_clear is None:
            raise ValueError("coded research output requires one dominant CLEAR code")
        if self.coding_status is not ResearchCodingStatus.CODED and self.dominant_clear is not None:
            raise ValueError("partial or uncoded research output cannot assign CLEAR")
        if len(set(self.facione_behaviors)) != len(self.facione_behaviors):
            raise ValueError("Facione behavior codes must be unique")
        if len(set(self.ethics_concepts)) != len(self.ethics_concepts):
            raise ValueError("Ethics concept codes must be unique")
        return self


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


class RetrievalChunkReference(BaseModel):
    """Auditable metadata for one source chunk supplied to a coaching turn."""

    model_config = ConfigDict(frozen=True)

    source_id: str
    label: str
    title: str
    chunk_id: str
    excerpt: str = Field(default="", max_length=600)
    score: float = 0.0
    retrieval_origin: str = ""


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
            joined = "; ".join(str(entry).strip() for entry in item if str(entry).strip())
            if joined:
                parts.append(f"{key}: {joined}")
        elif isinstance(item, str) and item.strip():
            parts.append(item.strip())
    for key, item in value.items():
        if key in {
            "strengths",
            "improvements",
            "gaps",
            "notes",
            "text",
            "summary",
            "assessment",
            "stage_assessment",
        }:
            continue
        if isinstance(item, str) and item.strip():
            parts.append(item.strip())
    return " ".join(parts).strip()


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
    readiness_candidate: bool = False
    review_depth: str | None = Field(default=None, max_length=32)
    review_model: str | None = Field(default=None, max_length=128)
    review_trigger: str | None = Field(default=None, max_length=64)

    @model_validator(mode="before")
    @classmethod
    def coerce_live_provider_shapes(cls, value: Any) -> Any:
        """Accept common live-model variants without changing the stored contract.

        AgentCore JSON sometimes emits ``recommendation`` as ``STAY``/``ADVANCE``
        and ``stage_assessment`` as an object with strengths/improvements.
        """
        if not isinstance(value, dict):
            return value
        data = dict(value)
        stage = data.get("stage_assessment")
        if isinstance(stage, Mapping):
            if not data.get("review_strengths") and isinstance(stage.get("strengths"), list):
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
        "problem_identification",
        "concept_generation",
        "design_specification",
        "deep_analysis",
        "reflection",
    }
)


class CoachRequest(BaseModel):
    """Input required to run one local critical-thinking workflow turn.

    Clients may hint stage, history, and sources, but the application service
    reloads those values from the notebook store and rejects mismatches.
    ``student_project_context`` and ``conversation_summary`` are also filled
    server-side for prompt composition; clients cannot inject prompt files,
    stage instructions, or a privileged specialist through this contract.
    """

    thread_id: str
    student_message: str = Field(min_length=1, max_length=12_000)
    current_stage: str
    response_detail: str = Field(pattern="^(short|long)$")
    # Server-filled owner identifier for AgentCore harness compatibility.
    # Never a notebook id; clients cannot make this authoritative.
    student_id: str | None = Field(default=None, max_length=128)
    source_ids: list[str] = Field(default_factory=list)
    source_context: str = ""
    student_project_context: str = ""
    conversation_summary: str = ""
    conversation_memory: dict[str, Any] | None = None
    retrieved_chunks: list[RetrievalChunkReference] = Field(default_factory=list)
    image_inputs: list[CoachImageInput] = Field(default_factory=list, max_length=5)
    allow_model_knowledge: bool = False
    response_language: str = Field(default="English", min_length=1, max_length=50)
    history: list[dict[str, Any]] = Field(default_factory=list)
    model_id: str | None = None
    reasoning_effort: str | None = None
    # Server-filled notebook CAS token; clients must not treat this as authoritative.
    # Normal submit stamps this current revision on new rows and does not bump it.
    conversation_revision: int | None = None
    # Replacement user-message id from an append-only revision. The assistant
    # attaches to this already-persisted row; it is excluded from provider history.
    revise_user_message_id: str | None = Field(default=None, max_length=64)
    idempotency_key: str | None = Field(
        default=None,
        min_length=1,
        max_length=128,
        pattern=r"^[A-Za-z0-9][A-Za-z0-9._:-]*$",
    )
    # Server-filled specialist. Clients cannot make this authoritative.
    specialist: str | None = Field(default=None, max_length=32)
    # Server-filled periodic Deep Review counter. Clients cannot make this
    # authoritative. Persisted on notebook settings_text.
    coaching_turns_since_deep_review: int = Field(default=0, ge=0)
    deep_review_interval_turns: int = Field(default=3, ge=1, le=50)
    # Server-filled retrieval decision. Clients cannot make this authoritative.
    retrieval_required: bool = False

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

    @field_validator("specialist")
    @classmethod
    def specialist_must_be_known_or_empty(cls, value: str | None) -> str | None:
        """Drop unknown specialist names. The application service overwrites this."""
        cleaned = str(value or "").strip().lower()
        if cleaned in {"qa", "coaching", "review"}:
            return cleaned
        return None


class CoachTurn(BaseModel):
    """Stable result of one coaching workflow turn for API and UI consumers."""

    response_text: str = Field(min_length=1)
    assessment: EducationalAssessment
    pending_transition: PendingPhaseTransition | None = None
    auto_advanced_to: str | None = None


class ProviderCoachOutput(BaseModel):
    """One-call provider envelope with soft provisional research validation."""

    response_text: str = Field(min_length=1)
    assessment: EducationalAssessment
    research_coding: ProvisionalResearchCoding | None = None

    @field_validator("research_coding", mode="before")
    @classmethod
    def invalid_research_coding_becomes_absent(cls, value: Any) -> Any:
        """Drop invalid optional research data without losing valid coaching."""
        if value is None or isinstance(value, ProvisionalResearchCoding):
            return value
        try:
            return ProvisionalResearchCoding.model_validate(value)
        except (ValidationError, TypeError, ValueError):
            return None

    @model_validator(mode="after")
    def holistic_candidate_is_reflection_only(self) -> "ProviderCoachOutput":
        """Force non-Reflection holistic candidates to absent."""
        coding = self.research_coding
        if (
            coding is not None
            and coding.holistic_candidate is not None
            and self.assessment.current_stage != "reflection"
        ):
            object.__setattr__(
                self,
                "research_coding",
                coding.model_copy(update={"holistic_candidate": None}),
            )
        return self


class ProviderAssessmentResult(BaseModel):
    """Internal provider result; iteration preserves the legacy two-item seam."""

    model_config = ConfigDict(frozen=True)

    response_text: str = Field(min_length=1)
    assessment: EducationalAssessment
    research_coding: ProvisionalResearchCoding | None = None
    conversation_memory: dict[str, Any] | None = None
    specialist: str = "coaching"
    qualifying_coaching_turn: bool = False
    deep_review_succeeded: bool = False
    review_trigger: str | None = None

    @model_validator(mode="after")
    def holistic_candidate_is_reflection_only(self) -> "ProviderAssessmentResult":
        """Apply the authoritative assessment stage to the holistic candidate."""
        coding = self.research_coding
        if (
            coding is not None
            and coding.holistic_candidate is not None
            and self.assessment.current_stage != "reflection"
        ):
            object.__setattr__(
                self,
                "research_coding",
                coding.model_copy(update={"holistic_candidate": None}),
            )
        return self

    def __iter__(self):
        """Yield coaching text and assessment for existing provider consumers."""
        yield self.response_text
        yield self.assessment


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


class NotebookMetadataPatch(BaseModel):
    """Student-editable notebook settings accepted at the public API boundary.

    Learning-stage, progress-summary, assessment, and transition fields are
    deliberately absent. Those values are written only by trusted application
    services after a validated coaching turn or transition decision.
    """

    model_config = ConfigDict(extra="forbid")

    response_detail: Literal["short", "long"] | None = None
    response_language: str | None = Field(default=None, min_length=1, max_length=50)
    selected_model: str | None = Field(default=None, min_length=1, max_length=120)
    reasoning_effort: str | None = Field(default=None, min_length=1, max_length=30)
    support_mode: str | None = Field(default=None, min_length=1, max_length=120)
    assignment: dict[str, str] | None = None
    allow_model_knowledge: bool | None = None
    display_name: str | None = Field(default=None, min_length=1, max_length=80)
    tags: list[str] | None = Field(default=None, max_length=50)


class NotebookCreateRequest(BaseModel):
    """Payload for creating a notebook through the typed API."""

    name: str = Field(default="Untitled notebook", min_length=1, max_length=120)
    model_id: str = Field(min_length=1, max_length=120)
    support_mode: str = Field(min_length=1, max_length=120)
    assignment: dict[str, str] = Field(default_factory=dict)
    metadata: NotebookMetadataPatch = Field(default_factory=NotebookMetadataPatch)


class NotebookUpdateRequest(BaseModel):
    """Partial notebook rename / metadata merge."""

    name: str | None = Field(default=None, min_length=1, max_length=120)
    metadata: NotebookMetadataPatch | None = None


class WelcomeMessageMetadata(BaseModel):
    """Fixed metadata accepted for the public welcome-message seed command."""

    model_config = ConfigDict(extra="forbid")

    kind: Literal["coach_welcome"] = "coach_welcome"
    workflow: Literal["welcome"] = "welcome"


class MessageCreateRequest(BaseModel):
    """Seed the fixed assistant welcome outside the coaching workflow.

    General message creation is intentionally not exposed: user turns,
    assistant assessments, and stage decisions belong to the coaching service.
    """

    role: Literal["assistant"] = "assistant"
    content: str = Field(min_length=1, max_length=100_000)
    metadata: WelcomeMessageMetadata = Field(default_factory=WelcomeMessageMetadata)


class SourceUpdateRequest(BaseModel):
    """Rename and/or change selection for one notebook source."""

    title: str | None = Field(default=None, min_length=1, max_length=180)
    selected: bool | None = None


class SourceSelectAllRequest(BaseModel):
    """Select or deselect every source in a notebook."""

    selected: bool
