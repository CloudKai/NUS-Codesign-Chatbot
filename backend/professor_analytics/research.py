"""Application boundary for attributable professor research review.

The service depends on a narrow repository protocol and contains no SQL.  It
keeps role resolution and reviewer identity at the API boundary, audits every
identifiable read before loading records, and exposes only privacy-reviewed
research fields.
"""

from __future__ import annotations

import csv
import io
from collections import Counter
from collections.abc import Callable
from typing import Any, Literal, Protocol

from pydantic import BaseModel, Field

from backend.domain import ClearCode, EthicsConcept, FacioneBehavior
from backend.research.models import (
    ResearchAccessEvent,
    ResearchAccessEventCreate,
    ResearchAdjudication,
    ResearchAdjudicationCreate,
    ResearchObservation,
    ResearchReview,
    ResearchReviewCreate,
)


_CODING_STATUSES = frozenset({"coded", "partial", "uncoded"})


class ResearchRepository(Protocol):
    """Persistence operations required by the professor research slice."""

    def list_observations(
        self,
        *,
        notebook_id: str | None = None,
        active_only: bool = True,
        limit: int = 100,
        offset: int = 0,
    ) -> list[ResearchObservation]:
        """List immutable automated observations in stable order."""

    def get_observation(
        self, observation_id: str, *, active_only: bool = True
    ) -> ResearchObservation | None:
        """Return one observation or ``None``."""

    def append_review(self, value: ResearchReviewCreate) -> ResearchReview:
        """Append one human validation record."""

    def list_reviews(self, observation_id: str) -> list[ResearchReview]:
        """List reviews for an observation."""

    def append_adjudication(
        self, value: ResearchAdjudicationCreate
    ) -> ResearchAdjudication:
        """Append one adjudication record."""

    def list_adjudications(self, observation_id: str) -> list[ResearchAdjudication]:
        """List adjudications for an observation."""

    def record_access_event(
        self, value: ResearchAccessEventCreate
    ) -> ResearchAccessEvent:
        """Persist an attributable access audit or raise."""


class ResearchSummaryResponse(BaseModel):
    """Aggregate-only research coding summary."""

    total_observations: int = 0
    active_observations: int = 0
    coding_status: dict[str, int] = Field(default_factory=dict)
    phases: dict[str, int] = Field(default_factory=dict)
    mean_confidence: float | None = None


class ResearchQueueItem(BaseModel):
    """Privacy-bounded observation row for the human-validation queue."""

    observation_id: str
    notebook_id: str
    student_id: str
    student_name: str
    student_email: str | None = None
    phase: str
    coding_status: str
    confidence: float | None = None
    clear_strategy: str | None = None
    facione_count: int = 0
    ethics_count: int = 0
    created_at: str


class ResearchQueueResponse(BaseModel):
    """Safely paginated research-validation queue."""

    items: list[ResearchQueueItem] = Field(default_factory=list)
    total: int = 0
    limit: int
    offset: int


class ResearchNotebookDetailResponse(BaseModel):
    """One audited notebook transcript with automated and human coding."""

    notebook_id: str
    title: str
    student: dict[str, Any]
    transcript: list[dict[str, Any]] = Field(default_factory=list)
    observations: list[dict[str, Any]] = Field(default_factory=list)
    observation_limit: int = 100
    observation_offset: int = 0
    has_more_observations: bool = False


class ResearchReviewRequest(BaseModel):
    """Human validation input; reviewer identity is intentionally absent."""

    observation_id: str = Field(min_length=1, max_length=128)
    status: Literal["confirmed", "rejected", "amended"]
    coding_status: Literal["coded", "partial", "uncoded"] | None = None
    dominant_clear: ClearCode | None = None
    facione_behaviors: list[FacioneBehavior] | None = Field(default=None, max_length=2)
    ethics_concepts: list[EthicsConcept] | None = Field(default=None, max_length=5)
    evidence: list[dict[str, Any]] | None = Field(default=None, max_length=8)
    holistic_candidate: dict[str, Any] | None = None
    notes: str | None = Field(default=None, max_length=2_000)
    supersedes_review_id: str | None = Field(default=None, max_length=160)


class ResearchAdjudicationRequest(BaseModel):
    """Consensus decision input; adjudicator identity is server-derived."""

    observation_id: str = Field(min_length=1, max_length=128)
    referenced_review_ids: list[str] = Field(min_length=1, max_length=20)
    decision: Literal["confirmed", "rejected", "amended"]
    coding_status: Literal["coded", "partial", "uncoded"] | None = None
    dominant_clear: ClearCode | None = None
    facione_behaviors: list[FacioneBehavior] | None = Field(default=None, max_length=2)
    ethics_concepts: list[EthicsConcept] | None = Field(default=None, max_length=5)
    evidence: list[dict[str, Any]] | None = Field(default=None, max_length=8)
    holistic_candidate: dict[str, Any] | None = None
    notes: str | None = Field(default=None, max_length=2_000)
    supersedes_adjudication_id: str | None = Field(default=None, max_length=160)


def _record_dict(value: Any) -> dict[str, Any]:
    """Convert a typed persistence record to a plain API-safe dictionary."""
    if isinstance(value, BaseModel):
        return value.model_dump(mode="json")
    if isinstance(value, dict):
        return dict(value)
    model_dump = getattr(value, "model_dump", None)
    if callable(model_dump):
        return dict(model_dump(mode="json"))
    return dict(vars(value))


def _field(data: dict[str, Any], *names: str, default: Any = None) -> Any:
    """Return the first present compatibility field from one record."""
    for name in names:
        if name in data and data[name] is not None:
            return data[name]
    return default


def _codes(data: dict[str, Any], *names: str) -> list[Any]:
    """Normalize one persisted code collection without interpreting it."""
    value = _field(data, *names, default=[])
    return list(value) if isinstance(value, (list, tuple)) else []


def _safe_csv_cell(value: Any) -> str:
    """Prevent spreadsheet formula execution while preserving exported text."""
    text = "" if value is None else str(value)
    if text.lstrip().startswith(("=", "+", "-", "@")):
        return "'" + text
    return text


class ProfessorResearchService:
    """Coordinate research reads, validation writes, audit, and CSV export."""

    def __init__(self, repository: ResearchRepository) -> None:
        self._repository = repository

    def summary(self) -> ResearchSummaryResponse:
        """Return aggregate observation counts without exposing identities."""
        observations = self._all_observations(active_only=False)
        rows = [_record_dict(item) for item in observations]
        active = [
            _record_dict(item)
            for item in self._all_observations(active_only=True)
        ]
        statuses = Counter(
            str(_field(row, "coding_status", "status", default="uncoded"))
            for row in active
        )
        phases = Counter(
            str(_field(row, "phase_id", "phase", "stage", default="Unknown"))
            for row in active
        )
        confidence = [
            float(value)
            for row in active
            if (value := self._observation_confidence(row)) is not None
        ]
        return ResearchSummaryResponse(
            total_observations=len(rows),
            active_observations=len(active),
            coding_status={key: statuses.get(key, 0) for key in sorted(_CODING_STATUSES)},
            phases=dict(sorted(phases.items())),
            mean_confidence=(
                round(sum(confidence) / len(confidence), 3) if confidence else None
            ),
        )

    def queue(
        self,
        *,
        actor_user_id: str,
        actor_role: str,
        request_id: str,
        coding_status: str | None,
        phase: str | None,
        search: str,
        limit: int,
        offset: int,
    ) -> ResearchQueueResponse:
        """Audit, then return a filtered and bounded identifiable queue."""
        safe_limit = max(1, min(int(limit), 100))
        safe_offset = max(0, min(int(offset), 10_000))
        selected_status = str(coding_status or "").strip().lower()
        if selected_status and selected_status not in _CODING_STATUSES:
            raise ValueError("Invalid research coding status")
        selected_phase = str(phase or "").strip().lower()
        needle = str(search or "").strip().lower()[:120]
        metadata = {
            "coding_status": selected_status or None,
            "phase": selected_phase or None,
            "search_applied": bool(needle),
            "limit": safe_limit,
            "offset": safe_offset,
            "request_id": request_id,
        }
        self._audit(
            actor_user_id=actor_user_id,
            actor_role=actor_role,
            action="research.queue",
            scope="identifiable_queue",
            metadata=metadata,
        )
        # Fetch a bounded working set so filtering cannot become an unbounded
        # in-memory scan even when the repository only supports base paging.
        observations = self._all_observations(active_only=True)
        items = [self._queue_item(item) for item in observations]
        filtered = [
            item
            for item in items
            if (not selected_status or item.coding_status.lower() == selected_status)
            and (not selected_phase or item.phase.lower() == selected_phase)
            and (
                not needle
                or needle in item.student_name.lower()
                or needle in (item.student_email or "").lower()
                or needle in item.notebook_id.lower()
            )
        ]
        return ResearchQueueResponse(
            items=filtered[safe_offset : safe_offset + safe_limit],
            total=len(filtered),
            limit=safe_limit,
            offset=safe_offset,
        )

    def notebook_detail(
        self,
        notebook_id: str,
        *,
        actor_user_id: str,
        actor_role: str,
        request_id: str,
        transcript_loader: Callable[[str, str], Any],
        observation_limit: int = 100,
        observation_offset: int = 0,
    ) -> ResearchNotebookDetailResponse | None:
        """Audit before loading one identifiable notebook research record."""
        clean_id = str(notebook_id or "").strip()
        safe_limit = max(1, min(int(observation_limit), 100))
        safe_offset = max(0, min(int(observation_offset), 10_000))
        self._audit(
            actor_user_id=actor_user_id,
            actor_role=actor_role,
            action="research.detail",
            scope="notebook",
            notebook_id=clean_id,
            metadata={
                "request_id": request_id,
                "limit": safe_limit,
                "offset": safe_offset,
            },
        )
        observations = self._repository.list_observations(
            notebook_id=clean_id,
            active_only=True,
            limit=safe_limit + 1,
            offset=safe_offset,
        )
        # A page beyond the final observation still identifies a valid
        # notebook. Resolve attribution from the first record after auditing,
        # then return an empty page rather than a misleading 404.
        anchor = observations[0] if observations else None
        if anchor is None and safe_offset:
            first_page = self._repository.list_observations(
                notebook_id=clean_id,
                active_only=True,
                limit=1,
                offset=0,
            )
            anchor = first_page[0] if first_page else None
        if anchor is None:
            return None
        has_more = len(observations) > safe_limit
        observations = observations[:safe_limit]
        first = _record_dict(anchor)
        student_id = str(
            _field(first, "student_user_id", "student_id", "user_id", default="")
        )
        transcript = transcript_loader(student_id, clean_id)
        if transcript is None:
            return None
        transcript_data = _record_dict(transcript)
        enriched: list[dict[str, Any]] = []
        for observation in observations:
            row = _record_dict(observation)
            observation_id = str(_field(row, "id", "observation_id", default=""))
            row["reviews"] = [
                _record_dict(value)
                for value in self._repository.list_reviews(observation_id)
            ]
            row["adjudications"] = [
                _record_dict(value)
                for value in self._repository.list_adjudications(observation_id)
            ]
            enriched.append(row)
        return ResearchNotebookDetailResponse(
            notebook_id=clean_id,
            title=str(transcript_data.get("title") or "Research notebook"),
            student={
                "id": student_id,
                "name": str(
                    _field(
                        first,
                        "student_display_name",
                        "student_name",
                        "display_name",
                        default="Student",
                    )
                ),
                "email": _field(first, "student_email", "email"),
            },
            transcript=list(transcript_data.get("messages") or []),
            observations=enriched,
            observation_limit=safe_limit,
            observation_offset=safe_offset,
            has_more_observations=has_more,
        )

    def submit_review(
        self, request: ResearchReviewRequest, *, reviewer_user_id: str
    ) -> ResearchReview:
        """Append a validation under the authenticated server-side reviewer."""
        if self._repository.get_observation(request.observation_id) is None:
            raise ValueError("Research observation not found")
        payload = request.model_dump()
        payload["reviewer_user_id"] = reviewer_user_id
        return self._repository.append_review(ResearchReviewCreate(**payload))

    def submit_adjudication(
        self, request: ResearchAdjudicationRequest, *, adjudicator_user_id: str
    ) -> ResearchAdjudication:
        """Append an adjudication under the authenticated server-side actor."""
        if self._repository.get_observation(request.observation_id) is None:
            raise ValueError("Research observation not found")
        payload = request.model_dump()
        payload["adjudicator_user_id"] = adjudicator_user_id
        return self._repository.append_adjudication(
            ResearchAdjudicationCreate(**payload)
        )

    def export_csv(
        self,
        *,
        actor_user_id: str,
        actor_role: str,
        request_id: str,
        coding_status: str | None,
        phase: str | None,
    ) -> str:
        """Audit, then return formula-safe attributable observation CSV."""
        selected_status = str(coding_status or "").strip().lower()
        if selected_status and selected_status not in _CODING_STATUSES:
            raise ValueError("Invalid research coding status")
        selected_phase = str(phase or "").strip().lower()
        self._audit(
            actor_user_id=actor_user_id,
            actor_role=actor_role,
            action="research.export",
            scope="identifiable_csv",
            metadata={
                "coding_status": selected_status or None,
                "phase": selected_phase or None,
                "request_id": request_id,
            },
        )
        rows = [
            self._queue_item(item)
            for item in self._all_observations(active_only=True)
        ]
        rows = [
            item for item in rows
            if (not selected_status or item.coding_status.lower() == selected_status)
            and (not selected_phase or item.phase.lower() == selected_phase)
        ]
        output = io.StringIO(newline="")
        writer = csv.writer(output, lineterminator="\n")
        writer.writerow(
            [
                "observation_id", "notebook_id", "student_id", "student_name",
                "student_email", "phase", "coding_status", "confidence",
                "clear_strategy", "facione_count", "ethics_count", "created_at",
            ]
        )
        for item in rows:
            writer.writerow(
                [
                    _safe_csv_cell(item.observation_id),
                    _safe_csv_cell(item.notebook_id),
                    _safe_csv_cell(item.student_id),
                    _safe_csv_cell(item.student_name),
                    _safe_csv_cell(item.student_email),
                    _safe_csv_cell(item.phase),
                    _safe_csv_cell(item.coding_status),
                    _safe_csv_cell(item.confidence),
                    _safe_csv_cell(item.clear_strategy),
                    item.facione_count,
                    item.ethics_count,
                    _safe_csv_cell(item.created_at),
                ]
            )
        return output.getvalue()

    def _queue_item(self, observation: ResearchObservation) -> ResearchQueueItem:
        """Project one persistence record onto the minimal queue contract."""
        row = _record_dict(observation)
        return ResearchQueueItem(
            observation_id=str(_field(row, "id", "observation_id", default="")),
            notebook_id=str(row.get("notebook_id") or ""),
            student_id=str(
                _field(row, "student_user_id", "student_id", "user_id", default="")
            ),
            student_name=str(
                _field(
                    row,
                    "student_display_name",
                    "student_name",
                    "display_name",
                    default="Student",
                )
            ),
            student_email=_field(row, "student_email", "email"),
            phase=str(_field(row, "phase_id", "phase", "stage", default="Unknown")),
            coding_status=str(
                _field(row, "coding_status", "status", default="uncoded")
            ),
            confidence=(
                float(value)
                if (value := self._observation_confidence(row)) is not None
                else None
            ),
            clear_strategy=_field(row, "dominant_clear", "clear_strategy"),
            facione_count=len(_codes(row, "facione_behaviors", "facione_codes")),
            ethics_count=len(_codes(row, "ethics_concepts", "ethics_codes")),
            created_at=str(row.get("created_at") or ""),
        )

    def _all_observations(
        self,
        *,
        active_only: bool,
        notebook_id: str | None = None,
    ) -> list[ResearchObservation]:
        """Read bounded repository pages without relying on adapter max limits."""
        rows: list[ResearchObservation] = []
        page_size = 500
        for offset in range(0, 10_000, page_size):
            page = self._repository.list_observations(
                notebook_id=notebook_id,
                active_only=active_only,
                limit=page_size,
                offset=offset,
            )
            rows.extend(page)
            if len(page) < page_size:
                break
        return rows

    def _audit(
        self,
        *,
        actor_user_id: str,
        actor_role: str,
        action: str,
        scope: str,
        notebook_id: str | None = None,
        observation_id: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        """Persist access audit before any identifiable repository read."""
        self._repository.record_access_event(
            ResearchAccessEventCreate(
                actor_user_id=actor_user_id,
                action=action,
                scope=scope,
                request_id=str((metadata or {}).get("request_id") or "unknown"),
                notebook_id=notebook_id,
                observation_id=observation_id,
                filters={
                    key: value
                    for key, value in (metadata or {}).items()
                    if key != "request_id"
                },
                metadata={"actor_role": actor_role},
            )
        )

    @staticmethod
    def _observation_confidence(row: dict[str, Any]) -> float | None:
        """Return mean persisted evidence confidence for one observation."""
        evidence = row.get("evidence")
        if not isinstance(evidence, list):
            return None
        values = [
            float(item["confidence"])
            for item in evidence
            if isinstance(item, dict) and item.get("confidence") is not None
        ]
        return round(sum(values) / len(values), 3) if values else None
