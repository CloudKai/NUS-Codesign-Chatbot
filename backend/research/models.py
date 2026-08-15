"""Typed internal records for research coding, review, and access auditing."""

from __future__ import annotations

import json
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from backend.domain import ClearCode, EthicsConcept, FacioneBehavior


CodingStatus = Literal["coded", "partial", "uncoded"]
_MAX_METADATA_JSON_BYTES = 8_192
_FORBIDDEN_TRANSCRIPT_KEYS = frozenset(
    {"quote", "quotes", "evidence_quote", "evidence_quotes", "transcript"}
)


def _bounded_json(value: Any, *, label: str) -> None:
    """Reject oversized internal JSON before it reaches a TEXT column."""
    encoded = json.dumps(value, ensure_ascii=False, separators=(",", ":"))
    if len(encoded.encode("utf-8")) > _MAX_METADATA_JSON_BYTES:
        raise ValueError(f"{label} exceeds {_MAX_METADATA_JSON_BYTES} bytes")


def _contains_transcript_copy(value: Any) -> bool:
    """Detect fields that could duplicate private transcript text."""
    if isinstance(value, dict):
        return any(
            str(key).casefold() in _FORBIDDEN_TRANSCRIPT_KEYS
            or _contains_transcript_copy(item)
            for key, item in value.items()
        )
    if isinstance(value, list):
        return any(_contains_transcript_copy(item) for item in value)
    return False


class ResearchEvidenceSpan(BaseModel):
    """Evidence location without duplicating a private student transcript."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    start_offset: int = Field(ge=0)
    end_offset: int = Field(gt=0)
    rationale: str = Field(min_length=1, max_length=500)
    confidence: float = Field(ge=0.0, le=1.0)

    @model_validator(mode="after")
    def end_follows_start(self) -> "ResearchEvidenceSpan":
        """Require a non-empty half-open span."""
        if self.end_offset <= self.start_offset:
            raise ValueError("research evidence end_offset must follow start_offset")
        return self


class ResearchOffsetSpan(BaseModel):
    """A half-open transcript location used by holistic Reflection evidence."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    start_offset: int = Field(ge=0)
    end_offset: int = Field(gt=0)

    @model_validator(mode="after")
    def end_follows_start(self) -> "ResearchOffsetSpan":
        """Require a non-empty half-open span."""
        if self.end_offset <= self.start_offset:
            raise ValueError("research evidence end_offset must follow start_offset")
        return self


class ResearchHolisticCandidate(BaseModel):
    """Offset-only provisional Reflection candidate, never a student grade."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    score: int = Field(ge=1, le=4)
    rationale: str = Field(min_length=1, max_length=1_000)
    evidence_spans: list[ResearchOffsetSpan] = Field(default_factory=list, max_length=3)

    @model_validator(mode="before")
    @classmethod
    def reject_transcript_fields(cls, value: Any) -> Any:
        """Fail clearly when provider quote fields cross persistence boundary."""
        if _contains_transcript_copy(value):
            raise ValueError("Holistic research coding must use offsets, not quotes")
        return value


class ResearchCodingFields(BaseModel):
    """Normalized provisional codes shared by observations and human decisions."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    coding_status: CodingStatus
    dominant_clear: ClearCode | None = None
    facione_behaviors: list[FacioneBehavior] = Field(default_factory=list, max_length=2)
    ethics_concepts: list[EthicsConcept] = Field(default_factory=list, max_length=5)
    evidence: list[ResearchEvidenceSpan] = Field(default_factory=list, max_length=8)
    holistic_candidate: ResearchHolisticCandidate | None = None

    @model_validator(mode="after")
    def codes_are_unique(self) -> "ResearchCodingFields":
        """Reject ambiguous duplicate occurrence codes."""
        if self.coding_status == "coded" and self.dominant_clear is None:
            raise ValueError("coded research output requires one dominant CLEAR code")
        if self.coding_status != "coded" and self.dominant_clear is not None:
            raise ValueError("partial or uncoded research output cannot assign CLEAR")
        if len(set(self.facione_behaviors)) != len(self.facione_behaviors):
            raise ValueError("Facione behavior codes must be unique")
        if len(set(self.ethics_concepts)) != len(self.ethics_concepts):
            raise ValueError("Ethics concept codes must be unique")
        _bounded_json(
            self.holistic_candidate.model_dump(mode="json")
            if self.holistic_candidate
            else None,
            label="holistic_candidate",
        )
        return self


class ResearchObservationCreate(ResearchCodingFields):
    """Research observation supplied to atomic coach-turn persistence."""

    coding_version: str = Field(min_length=1, max_length=80)
    prompt_version: str = Field(min_length=1, max_length=120)
    provider: str = Field(min_length=1, max_length=80)
    model_id: str = Field(min_length=1, max_length=160)
    coaching_profile: str = Field(min_length=1, max_length=80)
    phase_id: str = Field(min_length=1, max_length=80)
    metadata: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def metadata_is_bounded(self) -> "ResearchObservationCreate":
        """Keep internal observation metadata bounded and transcript-free."""
        _bounded_json(self.metadata, label="research observation metadata")
        if _contains_transcript_copy(self.metadata):
            raise ValueError("Research metadata must not duplicate transcript text")
        return self

    def message_metadata(self) -> dict[str, Any]:
        """Return normalized offset-only coding safe for assistant metadata."""
        return self.model_dump(mode="json")


class ResearchObservation(ResearchObservationCreate):
    """Persisted automated observation with owner attribution through notebook."""

    id: str
    notebook_id: str
    student_user_id: str
    student_display_name: str | None = None
    student_email: str | None = None
    user_message_id: str
    assistant_message_id: str
    conversation_revision: int = Field(ge=0)
    created_at: str


class ResearchReviewCreate(BaseModel):
    """Append-only human review; replacement code fields are independent."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    observation_id: str = Field(min_length=1, max_length=160)
    reviewer_user_id: str = Field(min_length=1, max_length=160)
    status: str = Field(min_length=1, max_length=80)
    coding_status: CodingStatus | None = None
    dominant_clear: ClearCode | None = None
    facione_behaviors: list[FacioneBehavior] | None = Field(default=None, max_length=2)
    ethics_concepts: list[EthicsConcept] | None = Field(default=None, max_length=5)
    evidence: list[ResearchEvidenceSpan] | None = Field(default=None, max_length=8)
    holistic_candidate: ResearchHolisticCandidate | None = None
    notes: str | None = Field(default=None, max_length=2_000)
    supersedes_review_id: str | None = Field(default=None, max_length=160)
    metadata: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def internal_json_is_safe(self) -> "ResearchReviewCreate":
        """Keep review JSON bounded and prevent transcript duplication."""
        if self.coding_status == "coded" and self.dominant_clear is None:
            raise ValueError("a coded review requires one dominant CLEAR code")
        if self.coding_status in {"partial", "uncoded"} and self.dominant_clear is not None:
            raise ValueError("a partial or uncoded review cannot assign CLEAR")
        for label, value in (
            ("review metadata", self.metadata),
            (
                "review holistic_candidate",
                self.holistic_candidate.model_dump(mode="json")
                if self.holistic_candidate
                else None,
            ),
        ):
            _bounded_json(value, label=label)
            if _contains_transcript_copy(value):
                raise ValueError("Research reviews must use offsets, not quotes")
        return self


class ResearchReview(ResearchReviewCreate):
    """Persisted append-only human review."""

    id: str
    created_at: str


class ResearchAdjudicationCreate(BaseModel):
    """Append-only adjudication over one observation and referenced reviews."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    observation_id: str = Field(min_length=1, max_length=160)
    adjudicator_user_id: str = Field(min_length=1, max_length=160)
    decision: str = Field(min_length=1, max_length=80)
    coding_status: CodingStatus | None = None
    dominant_clear: ClearCode | None = None
    facione_behaviors: list[FacioneBehavior] | None = Field(default=None, max_length=2)
    ethics_concepts: list[EthicsConcept] | None = Field(default=None, max_length=5)
    evidence: list[ResearchEvidenceSpan] | None = Field(default=None, max_length=8)
    holistic_candidate: ResearchHolisticCandidate | None = None
    notes: str | None = Field(default=None, max_length=2_000)
    supersedes_adjudication_id: str | None = Field(default=None, max_length=160)
    referenced_review_ids: list[str] = Field(default_factory=list, max_length=20)
    metadata: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def internal_json_is_safe(self) -> "ResearchAdjudicationCreate":
        """Keep adjudication JSON bounded and prevent transcript duplication."""
        if self.coding_status == "coded" and self.dominant_clear is None:
            raise ValueError("a coded adjudication requires one dominant CLEAR code")
        if self.coding_status in {"partial", "uncoded"} and self.dominant_clear is not None:
            raise ValueError("a partial or uncoded adjudication cannot assign CLEAR")
        for label, value in (
            ("adjudication metadata", self.metadata),
            (
                "adjudication holistic_candidate",
                self.holistic_candidate.model_dump(mode="json")
                if self.holistic_candidate
                else None,
            ),
        ):
            _bounded_json(value, label=label)
            if _contains_transcript_copy(value):
                raise ValueError("Research adjudications must use offsets, not quotes")
        return self


class ResearchAdjudication(ResearchAdjudicationCreate):
    """Persisted append-only adjudication."""

    id: str
    created_at: str


class ResearchAccessEventCreate(BaseModel):
    """Fail-closed audit input for an identifiable research read or export."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    actor_user_id: str = Field(min_length=1, max_length=160)
    action: str = Field(min_length=1, max_length=80)
    scope: str = Field(min_length=1, max_length=120)
    request_id: str = Field(min_length=1, max_length=128)
    target_user_id: str | None = Field(default=None, max_length=160)
    target_count: int | None = Field(default=None, ge=0)
    notebook_id: str | None = Field(default=None, max_length=160)
    observation_id: str | None = Field(default=None, max_length=160)
    filters: dict[str, Any] = Field(default_factory=dict)
    metadata: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def audit_json_is_bounded(self) -> "ResearchAccessEventCreate":
        """Bound audit filters and metadata to predictable row sizes."""
        _bounded_json(self.filters, label="research access filters")
        _bounded_json(self.metadata, label="research access metadata")
        return self


class ResearchAccessEvent(ResearchAccessEventCreate):
    """Persisted research access audit event."""

    id: str
    created_at: str
