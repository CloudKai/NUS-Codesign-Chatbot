"""Pure, read-only learning analytics derived from persisted application data."""

from __future__ import annotations

import base64
import json
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from statistics import median
from typing import Any, Iterable

from .models import (
    AttentionSignal,
    ConversationTranscriptResponse,
    CriticalThinkingResponse,
    EngagementResponse,
    NotebookWorkspaceResponse,
    OverviewResponse,
    ProfessorJourneyProjection,
    ProfessorJourneyStage,
    ProfessorLearningState,
    ProfessorMessagePage,
    ProfessorNotebookSummary,
    ProfessorReviewProjection,
    ProfessorSourcesResponse,
    ProfessorSourceSummary,
    ProfessorTranscriptMessage,
    ProfessorWorkspaceTranscript,
    ScoreValue,
    StageDistributionItem,
    StudentDetailResponse,
    StudentListItem,
    StudentsResponse,
)
from .repository import ProfessorAnalyticsRepository

STAGES = (
    "problem_identification",
    "concept_generation",
    "design_specification",
    "deep_analysis",
    "reflection",
)
DIMENSIONS = (
    ("analysis", "Analysis"),
    ("interpretation", "Interpretation"),
    ("inference", "Inference"),
    ("evaluation", "Evaluation"),
    ("explanation", "Explanation"),
    ("self_regulation", "Self-Regulation"),
)


@dataclass(frozen=True)
class AttentionRules:
    """Central, reviewable thresholds used for neutral follow-up signals."""

    inactive_days: int = 7
    focus_turns: int = 8
    limited_progress_turns: int = 12
    limited_progress_completed_stages: int = 1
    low_score: float = 2.0
    minimum_scored_dimensions: int = 3
    session_gap_minutes: int = 30
    minimum_session_minutes: int = 5


def _parse_time(value: Any) -> datetime | None:
    """Parse persisted ISO timestamps defensively without changing stored data."""
    raw = str(value or "").strip()
    if not raw:
        return None
    try:
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def _label(stage: str | None) -> str | None:
    """Render an authoritative stage id as the student-facing label."""
    if not stage:
        return None
    from backend.learning.stages import STAGE_BY_ID

    spec = STAGE_BY_ID.get(str(stage))
    if spec is not None:
        return spec.label
    return str(stage).replace("_", " ").title()


def _stage_id_from_label(label: str | None) -> str | None:
    """Resolve a student-facing stage label back to its authoritative id."""
    if not label:
        return None
    normalized = str(label).strip().casefold()
    from backend.learning.stages import STAGE_BY_ID

    for stage_id, spec in STAGE_BY_ID.items():
        if spec.label.casefold() == normalized or stage_id == normalized:
            return stage_id
    return normalized.replace(" ", "_")


def _encode_message_cursor(created_at: str, message_id: str) -> str:
    """Encode a keyset cursor for lecturer transcript pagination."""
    payload = json.dumps({"t": created_at, "i": message_id}, separators=(",", ":"))
    return base64.urlsafe_b64encode(payload.encode("utf-8")).decode("ascii")


def _decode_message_cursor(cursor: str) -> tuple[str, str]:
    """Decode one lecturer transcript cursor or raise ``ValueError``."""
    try:
        decoded = base64.urlsafe_b64decode(cursor.encode("ascii"))
        payload = json.loads(decoded.decode("utf-8"))
        created_at = str(payload["t"])
        message_id = str(payload["i"])
    except (KeyError, TypeError, ValueError, json.JSONDecodeError) as error:
        raise ValueError("Invalid cursor") from error
    if not created_at or not message_id:
        raise ValueError("Invalid cursor")
    return created_at, message_id


def _completed_stage_count(progress_text: Any) -> int:
    """Return the number of persisted completed stages from notebook metadata."""
    if not isinstance(progress_text, dict):
        try:
            progress_text = json.loads(str(progress_text or "{}"))
        except (TypeError, ValueError):
            return 0
    completed = progress_text.get("completed_stages") if isinstance(progress_text, dict) else []
    if not isinstance(completed, list):
        return 0
    return len(
        [
            str(item).lower()
            for item in completed
            if str(item).lower() in STAGES
        ]
    )


def _score(values: Iterable[float]) -> ScoreValue:
    """Return median score and sample count while preserving missingness."""
    valid = [float(value) for value in values]
    return ScoreValue(value=round(float(median(valid)), 2) if valid else None, sample_size=len(valid))


class ProfessorAnalyticsService:
    """Calculate transparent class analytics from one active-branch data snapshot."""

    def __init__(
        self,
        repository: ProfessorAnalyticsRepository,
        *,
        now: datetime | None = None,
        rules: AttentionRules = AttentionRules(),
    ) -> None:
        self._repository = repository
        self._now = now or datetime.now(timezone.utc)
        self._rules = rules

    def overview(self) -> OverviewResponse:
        """Return the concise class snapshot used to orient a professor."""
        students = self._build_students(self._repository.load_class_rows())
        roster = [self._student_item(value) for value in students.values()]
        assessed = [value["overall"] for value in students.values() if value["overall"] is not None]
        active = [value for value in students.values() if self._is_active_week(value)]
        stages = Counter(value["stage"] for value in students.values() if value["stage"])
        total = len(students)
        distribution = [
            StageDistributionItem(
                stage=_label(stage) or stage,
                count=stages[stage],
                percentage=round((stages[stage] / total * 100) if total else 0, 1),
            )
            for stage in STAGES
        ]
        not_started = total - sum(stages.values())
        distribution.append(
            StageDistributionItem(
                stage="Not started",
                count=not_started,
                percentage=round((not_started / total * 100) if total else 0, 1),
            )
        )
        profile = self._dimension_profile(students.values())
        active_days = [len(value["active_days"]) for value in students.values() if value["active_days"]]
        attention = [row for row in roster if row.needs_attention]
        return OverviewResponse(
            generated_at=self._now.isoformat(),
            students=total,
            active_students_week=len(active),
            total_conversations=sum(value["started_conversations"] for value in students.values()),
            median_facione=_score(assessed),
            median_stage=self._median_stage(students.values()),
            median_active_days=round(float(median(active_days)), 1) if active_days else None,
            stage_distribution=distribution,
            facione_profile=profile,
            weekly_activity=self._weekly_activity(students.values()),
            attention_students=attention[:8],
            attention_students_count=len(attention),
            summary=self._summary(students.values(), profile, attention),
        )

    def students(
        self,
        *,
        search: str = "",
        stage: str | None = None,
        attention_only: bool = False,
        min_score: float | None = None,
        max_score: float | None = None,
    ) -> StudentsResponse:
        """Return a searchable/filterable roster without message contents."""
        rows = [
            self._student_item(value)
            for value in self._build_students_from_roster(
                self._repository.load_student_roster()
            ).values()
        ]
        needle = search.strip().lower()
        selected_stage = stage.strip().lower() if stage else ""
        filtered = [
            row for row in rows
            if (not needle or needle in row.name.lower() or needle in (row.email or "").lower())
            and (not selected_stage or (row.current_stage or "").lower() == selected_stage)
            and (not attention_only or row.needs_attention)
            and (min_score is None or (row.facione_overall is not None and row.facione_overall >= min_score))
            and (max_score is None or (row.facione_overall is not None and row.facione_overall <= max_score))
        ]
        filtered.sort(key=lambda row: (not bool(row.needs_attention), row.name.lower()))
        return StudentsResponse(students=filtered, total=len(filtered))

    def student_detail(self, student_id: str) -> StudentDetailResponse | None:
        """Return one authorised learner snapshot without transcript bodies."""
        profile = self._repository.load_student_roster_row(student_id)
        if profile is None:
            return None
        notebook_rows = self._repository.load_student_notebook_summaries(student_id)
        activity_rows = self._repository.load_student_activity_rows(student_id)
        value = self._build_student_from_bounded_rows(profile, notebook_rows, activity_rows)
        benchmark = self._build_benchmark_students(
            self._repository.load_class_benchmark_rows()
        )
        trend = [
            {"at": item["at"], "overall": item["overall"], "stage": _label(item["stage"])}
            for item in value["assessments"] if item["overall"] is not None
        ]
        notebooks = [
            self._notebook_summary_item(row)
            for row in notebook_rows
        ]
        latest = value["latest_assessment"] or {}
        dimensions = {label: latest.get("dimensions", {}).get(key) for key, label in DIMENSIONS}
        return StudentDetailResponse(
            student=self._student_item(value),
            completed_stages=[_label(stage) or stage for stage in value["completed_stages"]],
            facione_profile=dimensions,
            class_facione_profile=self._dimension_profile(benchmark.values()),
            class_median_facione=_score(
                student["overall"]
                for student in benchmark.values()
                if student["overall"] is not None
            ),
            facione_trend=trend,
            engagement={
                "active_days": len(value["active_days"]), "sessions": value["sessions"],
                "student_messages": value["student_messages"], "assistant_messages": value["assistant_messages"],
                "first_activity": value["first_activity"], "last_activity": value["last_activity"],
                "estimated_active_minutes": value["estimated_active_minutes"],
                "definition": "Messages separated by more than 30 minutes start a new session; each session contributes at least five minutes.",
            },
            notebooks=notebooks,
            conversations=notebooks,
        )

    def conversation_transcript(
        self, student_id: str, notebook_id: str
    ) -> ConversationTranscriptResponse | None:
        """Return one selected active transcript without loading other students' text."""
        students = self._build_students(
            self._repository.load_student_rows(
                include_content=True,
                student_id=student_id,
                notebook_id=notebook_id,
            )
        )
        student = students.get(student_id)
        notebook = student["notebooks"].get(notebook_id) if student else None
        if notebook is None:
            return None
        citation_ids = [
            str(source_id)
            for message in notebook["messages"]
            for source_id in message.get("cited_source_ids", [])
        ]
        authorized_citations = self._repository.authorized_citation_ids(
            student_id, notebook_id, citation_ids
        )
        return ConversationTranscriptResponse(
            notebook_id=notebook_id,
            title=notebook["title"],
            stage=_label(notebook.get("stage")),
            last_active=notebook.get("last_activity"),
            messages=[
                {
                    "id": message["id"],
                    "role": message["role"],
                    "content": message["content"],
                    "created_at": message["created_at"],
                    "attachments": message.get("attachments", []),
                    "citations": [
                        citation
                        for citation in message.get("citations", [])
                        if str(citation.get("id")) in authorized_citations
                    ],
                }
                for message in notebook["messages"]
            ],
        )

    def notebook_messages(
        self,
        student_id: str,
        notebook_id: str,
        *,
        limit: int = 30,
        cursor: str | None = None,
    ) -> ProfessorMessagePage | None:
        """Return one paginated active-branch transcript page for lecturers."""
        header_row = self._repository.load_notebook_header(student_id, notebook_id)
        if header_row is None:
            return None
        clamped_limit = max(1, min(int(limit), 50))
        cursor_created_at: str | None = None
        cursor_id: str | None = None
        if cursor:
            try:
                cursor_created_at, cursor_id = _decode_message_cursor(cursor)
            except ValueError:
                raise
        rows = self._repository.load_notebook_message_page(
            student_id,
            notebook_id,
            limit=clamped_limit + 1,
            cursor_created_at=cursor_created_at,
            cursor_id=cursor_id,
        )
        has_more = len(rows) > clamped_limit
        page_rows_desc = rows[:clamped_limit]
        page_rows = list(reversed(page_rows_desc))
        citation_ids = [
            str(source_id)
            for row in page_rows
            for source_id in self._row_citation_ids(row)
        ]
        authorized_citations = self._repository.authorized_citation_ids(
            student_id, notebook_id, citation_ids
        )
        messages = [
            self._project_message_row(row, authorized_citations)
            for row in page_rows
        ]
        next_cursor = None
        if has_more and page_rows_desc:
            oldest = page_rows_desc[-1]
            next_cursor = _encode_message_cursor(
                str(oldest.get("message_created_at") or ""),
                str(oldest.get("message_id") or ""),
            )
        return ProfessorMessagePage(
            notebook=self._notebook_summary_from_row(header_row),
            messages=messages,
            next_cursor=next_cursor,
        )

    def notebook_sources(
        self, student_id: str, notebook_id: str
    ) -> ProfessorSourcesResponse | None:
        """Return allow-listed library sources for one owned notebook."""
        header_row = self._repository.load_notebook_header(student_id, notebook_id)
        if header_row is None:
            return None
        store = self._repository.student_store(student_id)
        if store is None:
            return None
        from backend.sources.library import list_visible_sources

        sources = [
            self._professor_source_summary(source)
            for source in list_visible_sources(
                store,
                notebook_id,
                include_extracted_text=False,
            )
        ]
        return ProfessorSourcesResponse(
            notebook=self._notebook_summary_from_row(header_row),
            sources=sources,
        )

    def notebook_journey(
        self, student_id: str, notebook_id: str
    ) -> ProfessorJourneyProjection | None:
        """Return persisted journey state without transcript bodies."""
        header_row = self._repository.load_notebook_header(student_id, notebook_id)
        if header_row is None:
            return None
        store = self._repository.student_store(student_id)
        if store is None:
            return None
        thread = store.get_thread(notebook_id)
        if thread is None:
            return None
        from backend.learning.hmw import hmw_scaffold_projection
        from backend.settings import settings
        from backend.student_journey import DEFAULT_STAGE, normalize_journey

        metadata = dict(thread.get("metadata") or {})
        journey = normalize_journey(metadata.get("learning_journey"))
        messages = store.get_messages(notebook_id)
        current_stage = str(journey.get("current_stage") or DEFAULT_STAGE)
        completed = [
            str(item).lower()
            for item in (journey.get("completed_stages") or [])
            if str(item).lower() in STAGES
        ]
        stages = []
        for stage in STAGES:
            if stage in completed and stage != current_stage:
                state = "completed"
            elif stage == current_stage:
                state = "current"
            elif stage in completed:
                state = "completed"
            else:
                state = "not_completed"
            stages.append(
                ProfessorJourneyStage(
                    id=stage,
                    label=_label(stage) or stage,
                    state=state,
                )
            )
        return ProfessorJourneyProjection(
            notebook=self._notebook_summary_from_row(header_row),
            current_stage=_label(current_stage),
            completed_stages=[_label(stage) or stage for stage in completed],
            stages=stages,
            hmw_scaffold=hmw_scaffold_projection(
                current_stage,
                messages,
                enabled=settings.hmw_scaffold_enabled,
                response_detail=str(journey.get("response_detail") or ""),
            ),
        )

    def notebook_review(
        self, student_id: str, notebook_id: str
    ) -> ProfessorReviewProjection | None:
        """Return persisted review projection without regeneration."""
        header_row = self._repository.load_notebook_header(student_id, notebook_id)
        if header_row is None:
            return None
        store = self._repository.student_store(student_id)
        if store is None:
            return None
        thread = store.get_thread(notebook_id)
        if thread is None:
            return None
        from backend.learning.journey import learning_review
        from backend.specialists.review_orchestration import DEEP_REVIEW_SNAPSHOT_KEY
        from backend.student_journey import normalize_journey

        metadata = dict(thread.get("metadata") or {})
        journey = normalize_journey(metadata.get("learning_journey"))
        snapshot = metadata.get(DEEP_REVIEW_SNAPSHOT_KEY)
        messages = store.get_messages(notebook_id)
        review = learning_review(
            messages,
            journey,
            detail=journey.get("response_detail"),
            deep_review_snapshot=snapshot if isinstance(snapshot, dict) else None,
        )
        return ProfessorReviewProjection(
            notebook=self._notebook_summary_from_row(header_row),
            summary=str(review.get("summary") or ""),
            facione_scores=dict(review.get("facione_scores") or {}),
            strength_sections=list(review.get("strength_sections") or []),
            improvement_sections=list(review.get("improvement_sections") or []),
            conclusion=str(review.get("conclusion") or ""),
        )

    def notebook_workspace(
        self, student_id: str, notebook_id: str
    ) -> NotebookWorkspaceResponse | None:
        """Return one authorised read-only notebook workspace for lecturers."""
        if not self._repository.notebook_owned(student_id, notebook_id):
            return None
        store = self._repository.student_store(student_id)
        if store is None:
            return None
        thread = store.get_thread(notebook_id)
        if thread is None:
            return None

        from backend.learning.hmw import hmw_scaffold_projection
        from backend.learning.journey import learning_review
        from backend.settings import settings
        from backend.sources.library import list_visible_sources
        from backend.specialists.review_orchestration import DEEP_REVIEW_SNAPSHOT_KEY
        from backend.student_journey import DEFAULT_STAGE, normalize_journey

        messages = store.get_messages(notebook_id)
        transcript_messages = self._project_transcript_messages(
            student_id, notebook_id, messages
        )
        metadata = dict(thread.get("metadata") or {})
        journey = normalize_journey(metadata.get("learning_journey"))
        snapshot = metadata.get(DEEP_REVIEW_SNAPSHOT_KEY)
        last_active = None
        for message in reversed(messages):
            if str(message.get("role") or "") == "user" and not message.get("is_error"):
                last_active = message.get("created_at")
                break
        sources = [
            self._professor_source_summary(source)
            for source in list_visible_sources(
                store,
                notebook_id,
                include_extracted_text=False,
            )
        ]
        title = str(thread.get("title") or "Untitled notebook")
        stage = _label(str(thread.get("current_stage") or ""))
        return NotebookWorkspaceResponse(
            notebook=ProfessorNotebookSummary(
                id=notebook_id,
                title=title,
                current_stage=stage,
                last_active=last_active,
            ),
            transcript=ProfessorWorkspaceTranscript(messages=transcript_messages),
            sources=sources,
            learning=ProfessorLearningState(
                journey=journey,
                hmw_scaffold=hmw_scaffold_projection(
                    str(journey.get("current_stage") or DEFAULT_STAGE),
                    messages,
                    enabled=settings.hmw_scaffold_enabled,
                    response_detail=str(journey.get("response_detail") or ""),
                ),
                review=learning_review(
                    messages,
                    journey,
                    detail=journey.get("response_detail"),
                    deep_review_snapshot=snapshot
                    if isinstance(snapshot, dict)
                    else None,
                ),
            ),
        )

    @staticmethod
    def _professor_source_summary(source: dict[str, Any]) -> ProfessorSourceSummary:
        """Project one visible source into the lecturer allow-listed summary."""
        from backend.source_library import is_locked_course_source

        metadata = source.get("metadata") or {}
        group = str(metadata.get("course_material_group") or "").strip() or None
        if group is None and not is_locked_course_source(source):
            group = "My Sources"
        has_file = bool(
            source.get("path")
            or source.get("object_key")
            or metadata.get("local_path")
            or metadata.get("shared_course_object")
        )
        return ProfessorSourceSummary(
            id=str(source.get("id") or ""),
            title=str(source.get("title") or "Source"),
            kind=str(source.get("kind") or "file") or None,
            mime=str(source.get("mime") or source.get("content_type") or "") or None,
            size=max(0, int(source.get("size") or source.get("byte_size") or 0)),
            group=group,
            selected=bool(source.get("selected")),
            origin=str(metadata.get("origin") or "").strip() or None,
            locked=is_locked_course_source(source),
            has_file=has_file,
        )

    def _project_transcript_messages(
        self, student_id: str, notebook_id: str, messages: list[dict[str, Any]]
    ) -> list[dict[str, Any]]:
        """Build professor-safe transcript rows from one active message list."""
        citation_ids = [
            str(source_id)
            for message in messages
            for source_id in self._message_citation_ids(message)
        ]
        authorized_citations = self._repository.authorized_citation_ids(
            student_id, notebook_id, citation_ids
        )
        projected: list[dict[str, Any]] = []
        for message in messages:
            metadata = message.get("metadata") or {}
            attachments = [
                {
                    "id": str(item.get("id") or ""),
                    "title": str(item.get("title") or "Attachment"),
                    "mime": str(item.get("mime") or "application/octet-stream"),
                    "kind": str(item.get("kind") or "file"),
                    "size": max(0, int(item.get("size") or 0)),
                }
                for item in metadata.get("attachments", [])
                if isinstance(item, dict) and str(item.get("id") or "").strip()
            ]
            citations = [
                citation
                for citation in self._message_citations(message)
                if str(citation.get("id")) in authorized_citations
            ]
            projected.append(
                {
                    "id": str(message.get("id") or ""),
                    "role": str(message.get("role") or ""),
                    "content": str(message.get("content") or ""),
                    "created_at": message.get("created_at"),
                    "attachments": attachments,
                    "citations": citations,
                }
            )
        return projected

    @staticmethod
    def _message_citation_ids(message: dict[str, Any]) -> list[str]:
        """Return citation ids from one persisted message metadata blob."""
        metadata = message.get("metadata") or {}
        raw_refs = metadata.get("source_refs") or metadata.get("cited_source_ids") or []
        ids: list[str] = []
        if not isinstance(raw_refs, list):
            return ids
        for raw_citation in raw_refs:
            if isinstance(raw_citation, dict):
                citation_id = str(
                    raw_citation.get("id")
                    or raw_citation.get("source_id")
                    or raw_citation.get("sourceId")
                    or ""
                ).strip()
            else:
                citation_id = str(raw_citation or "").strip()
            if citation_id:
                ids.append(citation_id)
        return ids

    @staticmethod
    def _message_citations(message: dict[str, Any]) -> list[dict[str, str]]:
        """Return citation descriptors from one persisted message metadata blob."""
        metadata = message.get("metadata") or {}
        raw_refs = metadata.get("source_refs") or metadata.get("cited_source_ids") or []
        citations: list[dict[str, str]] = []
        if not isinstance(raw_refs, list):
            return citations
        for raw_citation in raw_refs:
            if isinstance(raw_citation, dict):
                citation_id = str(
                    raw_citation.get("id")
                    or raw_citation.get("source_id")
                    or raw_citation.get("sourceId")
                    or ""
                ).strip()
                label = str(raw_citation.get("label") or "").strip()
                title = str(
                    raw_citation.get("title")
                    or raw_citation.get("source_title")
                    or raw_citation.get("sourceTitle")
                    or ""
                ).strip()
            else:
                citation_id = str(raw_citation or "").strip()
                label = ""
                title = ""
            if not citation_id:
                continue
            citations.append(
                {
                    "id": citation_id,
                    **({"label": label} if label else {}),
                    **({"title": title} if title else {}),
                }
            )
        return citations

    @staticmethod
    def _notebook_summary_item(row: dict[str, Any]) -> dict[str, Any]:
        """Project one notebook aggregate row into the student-detail shape."""
        coach_messages = int(row.get("coach_messages") or 0)
        student_messages = int(row.get("student_messages") or 0)
        progress = ProfessorAnalyticsService._json(row.get("progress_text"))
        return {
            "id": str(row.get("notebook_id") or ""),
            "title": str(row.get("title") or "Untitled notebook"),
            "stage": _label(str(row.get("current_stage") or "")),
            "current_stage": _label(str(row.get("current_stage") or "")),
            "student_messages": student_messages,
            "coach_messages": coach_messages,
            "assistant_messages": coach_messages,
            "messages": student_messages + coach_messages,
            "last_active": row.get("last_active"),
            "completed_stage_count": _completed_stage_count(progress),
        }

    def _notebook_summary_from_row(self, row: dict[str, Any]) -> ProfessorNotebookSummary:
        """Project one notebook aggregate row into the API summary model."""
        coach_messages = int(row.get("coach_messages") or 0)
        return ProfessorNotebookSummary(
            id=str(row.get("notebook_id") or ""),
            title=str(row.get("title") or "Untitled notebook"),
            current_stage=_label(str(row.get("current_stage") or "")),
            last_active=row.get("last_active"),
            student_messages=int(row.get("student_messages") or 0),
            coach_messages=coach_messages,
            assistant_messages=coach_messages,
            completed_stage_count=_completed_stage_count(row.get("progress_text")),
        )

    def _build_student_from_bounded_rows(
        self,
        profile: dict[str, Any],
        notebook_rows: list[dict[str, Any]],
        activity_rows: list[dict[str, Any]],
    ) -> dict[str, Any]:
        """Build one student aggregate from compact roster and activity rows."""
        value = self._build_students_from_roster([profile])[str(profile["user_id"])]
        assessments: list[dict[str, Any]] = []
        cited_assessment_ids: set[str] = set()
        user_timestamps: list[datetime] = []
        session_timestamps: list[datetime] = []
        for row in activity_rows:
            role = str(row.get("message_role") or "")
            if row.get("message_is_error"):
                continue
            timestamp = _parse_time(row.get("message_created_at"))
            if role == "user" and timestamp is not None:
                user_timestamps.append(timestamp)
                session_timestamps.append(timestamp)
            if role != "assistant":
                continue
            assessment = self._json(row.get("assessment_text"))
            if not assessment:
                continue
            raw_scores = assessment.get("facione_scores")
            dimensions = {
                key: self._dimension_score(raw_scores, key) for key, _ in DIMENSIONS
            }
            valid = [score for score in dimensions.values() if score > 0]
            assessments.append(
                {
                    "id": str(row.get("message_id") or ""),
                    "at": row.get("message_created_at"),
                    "dimensions": dimensions,
                    "overall": round(sum(valid) / len(valid), 2) if valid else None,
                    "stage": assessment.get("current_stage"),
                }
            )
            cited_assessment_ids.add(str(row.get("message_id") or ""))
        assessments.sort(key=lambda item: (str(item["at"] or ""), item["id"]))
        value["assessments"] = assessments
        value["latest_assessment"] = assessments[-1] if assessments else value.get("latest_assessment")
        value["overall"] = value["latest_assessment"]["overall"] if value["latest_assessment"] else None
        value["assistant_messages"] = sum(
            1
            for row in activity_rows
            if str(row.get("message_role") or "") == "assistant"
            and not row.get("message_is_error")
        )
        value["student_messages"] = int(profile.get("student_messages") or 0)
        value["active_days"] = {
            item.date().isoformat() for item in sorted(user_timestamps)
        }
        value["active_days_count"] = int(profile.get("active_days") or len(value["active_days"]))
        timestamps = sorted(user_timestamps)
        value["first_activity"] = timestamps[0].isoformat() if timestamps else None
        value["last_activity"] = timestamps[-1].isoformat() if timestamps else profile.get("last_activity")
        sessions, minutes = self._sessions(sorted(session_timestamps))
        value["sessions"] = sessions
        value["estimated_active_minutes"] = minutes
        value["started_conversations"] = sum(
            1 for row in notebook_rows if int(row.get("student_messages") or 0) > 0
        )
        value["assessed_responses"] = len(cited_assessment_ids)
        value["source_grounded_responses"] = sum(
            1
            for row in activity_rows
            if str(row.get("message_role") or "") == "assistant"
            and not row.get("message_is_error")
            and str(row.get("message_id") or "") in cited_assessment_ids
            and bool(self._json_list(row.get("cited_source_ids_text")))
        )
        value["notebooks"] = {
            str(row.get("notebook_id") or ""): {
                "id": str(row.get("notebook_id") or ""),
                "messages": [],
            }
            for row in notebook_rows
        }
        return value

    def _row_citation_ids(self, row: dict[str, Any]) -> list[str]:
        """Return citation ids from one compact message row."""
        citations: list[str] = []
        for raw_citation in self._json_list(row.get("cited_source_ids_text")):
            if isinstance(raw_citation, dict):
                citation_id = str(
                    raw_citation.get("id")
                    or raw_citation.get("source_id")
                    or raw_citation.get("sourceId")
                    or ""
                ).strip()
            else:
                citation_id = str(raw_citation or "").strip()
            if citation_id:
                citations.append(citation_id)
        return citations

    def _project_message_row(
        self,
        row: dict[str, Any],
        authorized_citations: set[str],
    ) -> ProfessorTranscriptMessage:
        """Project one SQL message row into the lecturer transcript model."""
        metadata = self._json(row.get("message_metadata"))
        attachments = [
            {
                "id": str(item.get("id") or ""),
                "title": str(item.get("title") or "Attachment"),
                "mime": str(item.get("mime") or "application/octet-stream"),
                "kind": str(item.get("kind") or "file"),
                "size": max(0, int(item.get("size") or 0)),
            }
            for item in metadata.get("attachments", [])
            if isinstance(item, dict) and str(item.get("id") or "").strip()
        ]
        message = {
            "id": str(row.get("message_id") or ""),
            "role": str(row.get("message_role") or ""),
            "content": str(row.get("message_content") or ""),
            "created_at": row.get("message_created_at"),
            "metadata": metadata,
        }
        citations = [
            citation
            for citation in self._message_citations(message)
            if str(citation.get("id")) in authorized_citations
        ]
        return ProfessorTranscriptMessage(
            id=str(row.get("message_id") or ""),
            role=str(row.get("message_role") or ""),
            content=str(row.get("message_content") or ""),
            created_at=row.get("message_created_at"),
            attachments=attachments,
            citations=citations,
        )

    def _build_students_from_roster(
        self, rows: list[dict[str, Any]]
    ) -> dict[str, dict[str, Any]]:
        """Convert compact roster rows into the internal student aggregate shape."""
        students: dict[str, dict[str, Any]] = {}
        for row in rows:
            user_id = str(row["user_id"])
            progress = self._json(row.get("progress_text"))
            completed = progress.get("completed_stages") if isinstance(progress, dict) else []
            if not isinstance(completed, list):
                completed = []
            stage = str(row.get("current_stage") or "").lower() or None
            assessment = self._json(row.get("latest_assessment_text"))
            dimensions: dict[str, float] = {}
            overall: float | None = None
            if assessment:
                raw_scores = assessment.get("facione_scores")
                dimensions = {
                    key: self._dimension_score(raw_scores, key) for key, _ in DIMENSIONS
                }
                valid = [score for score in dimensions.values() if score > 0]
                overall = round(sum(valid) / len(valid), 2) if valid else None
            last_activity = row.get("last_activity")
            active_days_count = int(row.get("active_days") or 0)
            students[user_id] = {
                "id": user_id,
                "name": str(row.get("display_name") or "Student"),
                "email": row.get("email"),
                "created_at": row.get("user_created_at"),
                "stage": stage,
                "completed_stages": [
                    str(item).lower() for item in completed if str(item).lower() in STAGES
                ],
                "primary_student_messages": int(row.get("primary_student_messages") or 0),
                "student_messages": int(row.get("student_messages") or 0),
                "active_days_count": active_days_count,
                "active_days": set(),
                "last_activity": last_activity,
                "latest_assessment": (
                    {"dimensions": dimensions, "overall": overall} if assessment else None
                ),
                "overall": overall,
                "notebooks": {},
                "assessments": [],
            }
        return students

    def _build_benchmark_students(
        self, rows: list[dict[str, Any]]
    ) -> dict[str, dict[str, Any]]:
        """Build latest assessment summaries from compact benchmark rows."""
        values: dict[str, dict[str, Any]] = {}
        for row in rows:
            if str(row.get("message_role") or "") != "assistant" or row.get("message_is_error"):
                continue
            assessment = self._json(row.get("assessment_text"))
            if not assessment:
                continue
            user_id = str(row.get("user_id") or "")
            if not user_id:
                continue
            raw_scores = assessment.get("facione_scores")
            dimensions = {
                key: self._dimension_score(raw_scores, key) for key, _ in DIMENSIONS
            }
            valid = [score for score in dimensions.values() if score > 0]
            value = values.setdefault(
                user_id,
                {
                    "id": user_id,
                    "name": str(row.get("display_name") or "Student"),
                    "email": row.get("email"),
                    "assessments": [],
                    "latest_assessment": None,
                    "overall": None,
                    "notebooks": {},
                },
            )
            value["assessments"].append(
                {
                    "id": str(row.get("message_id") or ""),
                    "at": row.get("message_created_at"),
                    "dimensions": dimensions,
                    "overall": round(sum(valid) / len(valid), 2) if valid else None,
                    "stage": assessment.get("current_stage"),
                }
            )
        for value in values.values():
            value["assessments"].sort(
                key=lambda item: (str(item["at"] or ""), item["id"])
            )
            value["latest_assessment"] = value["assessments"][-1]
            value["overall"] = value["latest_assessment"]["overall"]
        return values

    def critical_thinking(self) -> CriticalThinkingResponse:
        """Return assessment aggregates that support teaching intervention."""
        students = self._build_students(self._repository.load_class_rows())
        values = list(students.values())
        scores = [student["overall"] for student in values if student["overall"] is not None]
        stage_counts = Counter(student["stage"] for student in values if student["stage"])
        total_students = len(values)
        stage_distribution = [
            StageDistributionItem(
                stage=_label(stage) or stage,
                count=stage_counts[stage],
                percentage=round(stage_counts[stage] / total_students * 100, 1)
                if total_students
                else 0,
            )
            for stage in STAGES
        ]
        stage_distribution.append(
            StageDistributionItem(
                stage="Not started",
                count=total_students - sum(stage_counts.values()),
                percentage=round(
                    (total_students - sum(stage_counts.values())) / total_students * 100,
                    1,
                )
                if total_students
                else 0,
            )
        )
        bands = [(1.0, 1.5), (1.5, 2.0), (2.0, 2.5), (2.5, 3.0), (3.0, 3.5), (3.5, 4.01)]
        distribution = [{"band": f"{low:.1f}–{high if high < 4 else 4.0:.1f}", "count": sum(low <= score < high for score in scores)} for low, high in bands]
        comparisons = []
        for stage in STAGES:
            grouped = [student["overall"] for student in values if student["stage"] == stage and student["overall"] is not None]
            if len(grouped) >= 3:
                comparisons.append({"stage": _label(stage), "median": round(float(median(grouped)), 2), "sample_size": len(grouped)})
        trend_groups: dict[str, list[float]] = defaultdict(list)
        for student in values:
            latest_by_week: dict[str, dict[str, Any]] = {}
            for assessment in student["assessments"]:
                timestamp = _parse_time(assessment["at"])
                if timestamp is None or assessment["overall"] is None:
                    continue
                week = (timestamp - timedelta(days=timestamp.weekday())).date().isoformat()
                latest_by_week[week] = assessment
            for week, assessment in latest_by_week.items():
                trend_groups[week].append(assessment["overall"])
        return CriticalThinkingResponse(
            dimensions=self._dimension_profile(values),
            stage_distribution=stage_distribution,
            distribution=distribution,
            stage_comparison=comparisons,
            trend=[{"date": date, "median": round(float(median(group)), 2), "sample_size": len(group)} for date, group in sorted(trend_groups.items())],
        )

    def engagement(self) -> EngagementResponse:
        """Return engagement signals without equating use volume to learning quality."""
        students = self._build_students(self._repository.load_class_rows())
        values = list(students.values())
        weekly = self._weekly_activity(values)
        active_hist = Counter(len(value["active_days"]) for value in values)
        time_hist = Counter(self._time_band(value["estimated_active_minutes"]) for value in values)
        inactive = [self._student_item(value) for value in values if any(signal.code == "inactive" for signal in self._attention(value))]
        assessed_responses = sum(value["assessed_responses"] for value in values)
        grounded_responses = sum(value["source_grounded_responses"] for value in values)
        return EngagementResponse(
            weekly_active_students=[{"week": item["week"], "active_students": item["active_students"]} for item in weekly],
            weekly_messages=[{"week": item["week"], "student_messages": item["student_messages"]} for item in weekly],
            active_day_distribution=[{"days": days, "students": count} for days, count in sorted(active_hist.items())],
            estimated_active_time_distribution=[{"band": band, "students": count} for band, count in sorted(time_hist.items())],
            assessed_coach_responses=assessed_responses,
            source_grounded_responses=grounded_responses,
            source_grounded_percentage=(
                round(grounded_responses / assessed_responses * 100, 1)
                if assessed_responses else None
            ),
            inactive_students=inactive,
            definition="Estimated active time groups student messages within each notebook into sessions when gaps are 30 minutes or less. Each session contributes its message span, with a five-minute minimum; it is not recorded time spent. Source grounding counts assessed coach responses that cite at least one persisted source; it does not prove that a student read the source.",
        )

    def _build_students(self, rows: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
        """Group a batch snapshot into stable per-student aggregates in memory."""
        students: dict[str, dict[str, Any]] = {}
        for row in rows:
            user_id = str(row["user_id"])
            value = students.setdefault(
                user_id,
                {
                    "id": user_id,
                    "name": str(row.get("display_name") or "Student"),
                    "email": row.get("email"),
                    "created_at": row.get("user_created_at"),
                    "notebooks": {},
                    "assessments": [],
                },
            )
            notebook_id = row.get("notebook_id")
            if not notebook_id:
                continue
            notebook = value["notebooks"].setdefault(str(notebook_id), {
                "id": str(notebook_id), "title": str(row.get("title") or "Untitled notebook"), "stage": str(row.get("current_stage") or "problem_identification").lower(),
                "progress": self._json(row.get("progress_text")), "updated_at": row.get("notebook_updated_at"),
                "messages": [], "assessments": [], "last_activity": None,
            })
            if not row.get("message_id"):
                continue
            raw_citations = self._json_list(row.get("cited_source_ids_text"))
            citations: list[dict[str, str]] = []
            citation_ids: list[str] = []
            for raw_citation in raw_citations:
                if isinstance(raw_citation, dict):
                    citation_id = str(
                        raw_citation.get("id")
                        or raw_citation.get("source_id")
                        or raw_citation.get("sourceId")
                        or ""
                    ).strip()
                    label = str(raw_citation.get("label") or "").strip()
                    title = str(
                        raw_citation.get("title")
                        or raw_citation.get("source_title")
                        or raw_citation.get("sourceTitle")
                        or ""
                    ).strip()
                else:
                    citation_id = str(raw_citation or "").strip()
                    label = ""
                    title = ""
                if not citation_id:
                    continue
                citation_ids.append(citation_id)
                citations.append(
                    {
                        "id": citation_id,
                        **({"label": label} if label else {}),
                        **({"title": title} if title else {}),
                    }
                )
            message = {
                "id": str(row["message_id"]),
                "role": str(row.get("message_role") or ""),
                "created_at": row.get("message_created_at"),
                "content": str(row.get("message_content") or ""),
                "is_error": bool(row.get("message_is_error")),
                "cited_source_ids": citation_ids,
                "citations": citations,
            }
            metadata = self._json(row.get("message_metadata"))
            message["attachments"] = [
                {
                    "id": str(item.get("id") or ""),
                    "title": str(item.get("title") or "Attachment"),
                    "mime": str(item.get("mime") or "application/octet-stream"),
                    "kind": str(item.get("kind") or "file"),
                    "size": max(0, int(item.get("size") or 0)),
                }
                for item in metadata.get("attachments", [])
                if isinstance(item, dict) and str(item.get("id") or "").strip()
            ]
            notebook["messages"].append(message)
            if not message["is_error"] and (
                not notebook["last_activity"]
                or str(message["created_at"] or "") > str(notebook["last_activity"])
            ):
                notebook["last_activity"] = message["created_at"]
            if message["role"] == "assistant" and not message["is_error"]:
                assessment = self._json(row.get("assessment_text"))
                if assessment:
                    raw_scores = assessment.get("facione_scores")
                    dimensions = {
                        key: self._dimension_score(raw_scores, key)
                        for key, _ in DIMENSIONS
                    }
                    valid = [score for score in dimensions.values() if score > 0]
                    notebook["assessments"].append(
                        {
                            "id": message["id"],
                            "at": message["created_at"],
                            "dimensions": dimensions,
                            "overall": round(sum(valid) / len(valid), 2) if valid else None,
                            "stage": assessment.get("current_stage"),
                        }
                    )
        for value in students.values():
            notebooks = list(value["notebooks"].values())
            notebooks.sort(key=lambda notebook: (str(notebook["last_activity"] or notebook["updated_at"] or ""), notebook["id"]), reverse=True)
            current = notebooks[0] if notebooks else None
            value["stage"] = current["stage"] if current else None
            progress = current.get("progress") if current else {}
            completed = progress.get("completed_stages") if isinstance(progress, dict) else []
            if not isinstance(completed, list):
                completed = []
            value["completed_stages"] = [str(stage).lower() for stage in completed if str(stage).lower() in STAGES]
            value["primary_student_messages"] = sum(
                message["role"] == "user" and not message["is_error"]
                for message in (current["messages"] if current else [])
            )
            messages = [message for notebook in notebooks for message in notebook["messages"]]
            messages.sort(key=lambda message: (str(message["created_at"] or ""), message["id"]))
            student_messages = [
                message for message in messages
                if message["role"] == "user" and not message["is_error"]
            ]
            value["student_messages"] = len(student_messages)
            value["assistant_messages"] = sum(
                message["role"] == "assistant" and not message["is_error"]
                for message in messages
            )
            assessment_ids = {
                assessment["id"]
                for notebook in notebooks
                for assessment in notebook["assessments"]
            }
            assessed_messages = [
                message
                for notebook in notebooks
                for message in notebook["messages"]
                if message["role"] == "assistant"
                and not message["is_error"]
                and message["id"] in assessment_ids
            ]
            value["assessed_responses"] = len(assessed_messages)
            value["source_grounded_responses"] = sum(
                bool(message["cited_source_ids"]) for message in assessed_messages
            )
            value["started_conversations"] = sum(
                any(
                    message["role"] == "user" and not message["is_error"]
                    for message in notebook["messages"]
                )
                for notebook in notebooks
            )
            dates = [_parse_time(message["created_at"]) for message in student_messages]
            timestamps = sorted(item for item in dates if item is not None)
            value["active_days"] = {item.date().isoformat() for item in timestamps}
            value["first_activity"] = timestamps[0].isoformat() if timestamps else None
            value["last_activity"] = timestamps[-1].isoformat() if timestamps else None
            session_results = []
            for notebook in notebooks:
                notebook_timestamps = sorted(
                    timestamp
                    for timestamp in (
                        _parse_time(message["created_at"])
                        for message in notebook["messages"]
                        if message["role"] == "user" and not message["is_error"]
                    )
                    if timestamp is not None
                )
                session_results.append(self._sessions(notebook_timestamps))
            value["sessions"] = sum(result[0] for result in session_results)
            value["estimated_active_minutes"] = sum(result[1] for result in session_results)
            value["assessments"] = list(current["assessments"]) if current else []
            value["assessments"].sort(
                key=lambda item: (str(item["at"] or ""), item["id"])
            )
            value["latest_assessment"] = value["assessments"][-1] if value["assessments"] else None
            value["overall"] = value["latest_assessment"]["overall"] if value["latest_assessment"] else None
        return students

    @staticmethod
    def _dimension_score(raw_scores: Any, key: str) -> float:
        """Return one valid persisted 0–4 dimension, or the not-started value."""
        if not isinstance(raw_scores, dict):
            return 0.0
        try:
            score = float(raw_scores.get(key, 0))
        except (TypeError, ValueError):
            return 0.0
        return score if 0 <= score <= 4 else 0.0

    @staticmethod
    def _json(value: Any) -> dict[str, Any]:
        try:
            parsed = json.loads(str(value or "{}"))
        except (TypeError, ValueError):
            return {}
        return parsed if isinstance(parsed, dict) else {}

    @staticmethod
    def _json_list(value: Any) -> list[Any]:
        """Parse a persisted JSON list defensively for citation-presence checks."""
        try:
            parsed = json.loads(str(value or "[]"))
        except (TypeError, ValueError):
            return []
        return parsed if isinstance(parsed, list) else []

    def _sessions(self, timestamps: list[datetime]) -> tuple[int, int]:
        """Estimate active time from student-message sessions, never wall-clock span."""
        if not timestamps:
            return 0, 0
        groups: list[list[datetime]] = [[timestamps[0]]]
        gap = timedelta(minutes=self._rules.session_gap_minutes)
        for timestamp in timestamps[1:]:
            if timestamp - groups[-1][-1] <= gap:
                groups[-1].append(timestamp)
            else:
                groups.append([timestamp])
        minutes = sum(max(self._rules.minimum_session_minutes, round((group[-1] - group[0]).total_seconds() / 60)) for group in groups)
        return len(groups), minutes

    def _attention(self, value: dict[str, Any]) -> list[AttentionSignal]:
        signals: list[AttentionSignal] = []
        last = _parse_time(value["last_activity"])
        created = _parse_time(value.get("created_at"))
        inactive_for = self._now - last if last is not None else None
        account_age = self._now - created if created is not None else None
        should_flag_inactive = bool(
            (inactive_for is not None and inactive_for >= timedelta(days=self._rules.inactive_days))
            or (
                last is None
                and account_age is not None
                and account_age >= timedelta(days=self._rules.inactive_days)
            )
        )
        if should_flag_inactive:
            wording = "No student activity recorded" if last is None else f"No activity for {inactive_for.days} days"
            signals.append(AttentionSignal(code="inactive", reason=wording))
        primary_turns = value["primary_student_messages"]
        if (
            value["stage"] == "problem_identification"
            and primary_turns >= self._rules.focus_turns
        ):
            signals.append(
                AttentionSignal(
                    code="problem_identification_after_activity",
                    reason=(
                        "Currently at Problem Identification after "
                        f"{primary_turns} student turns in the current notebook"
                    ),
                )
            )
        if primary_turns >= self._rules.limited_progress_turns and len(value["completed_stages"]) <= self._rules.limited_progress_completed_stages:
            signals.append(AttentionSignal(code="limited_progress", reason=f"{primary_turns} student turns in the current notebook with {len(value['completed_stages'])} completed stage(s)"))
        latest = value.get("latest_assessment") or {}
        dimensions = [score for score in latest.get("dimensions", {}).values() if score > 0]
        if value["overall"] is not None and len(dimensions) >= self._rules.minimum_scored_dimensions and value["overall"] < self._rules.low_score:
            signals.append(AttentionSignal(code="assessment_follow_up", reason=f"Latest critical-thinking profile is {value['overall']:.1f}/4 across {len(dimensions)} assessed dimensions"))
        return signals

    def _student_item(self, value: dict[str, Any]) -> StudentListItem:
        active_days = value.get("active_days_count")
        if active_days is None:
            active_days = len(value.get("active_days") or [])
        return StudentListItem(
            id=value["id"],
            name=value["name"],
            email=value["email"],
            current_stage=_label(value["stage"]),
            stage_progress=len(value["completed_stages"]),
            facione_overall=value["overall"],
            student_messages=value["student_messages"],
            active_days=int(active_days),
            last_active=value["last_activity"],
            needs_attention=self._attention(value),
        )

    def _dimension_profile(self, values: Iterable[dict[str, Any]]) -> dict[str, ScoreValue]:
        result: dict[str, list[float]] = {label: [] for _, label in DIMENSIONS}
        for value in values:
            latest = value.get("latest_assessment") or {}
            for key, label in DIMENSIONS:
                score = latest.get("dimensions", {}).get(key, 0)
                if score and score > 0:
                    result[label].append(float(score))
        return {label: _score(scores) for label, scores in result.items()}

    def _median_stage(self, values: Iterable[dict[str, Any]]) -> str | None:
        positions = sorted(STAGES.index(value["stage"]) for value in values if value["stage"] in STAGES)
        return _label(STAGES[positions[len(positions) // 2]]) if positions else None

    def _is_active_week(self, value: dict[str, Any]) -> bool:
        last = _parse_time(value["last_activity"])
        if last is None:
            return False
        elapsed = self._now - last
        return timedelta(0) <= elapsed < timedelta(days=7)

    def _weekly_activity(self, values: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
        weeks: dict[str, dict[str, Any]] = {}
        for value in values:
            seen: set[str] = set()
            for notebook in value["notebooks"].values():
                for message in notebook["messages"]:
                    if message["role"] != "user" or message["is_error"]:
                        continue
                    timestamp = _parse_time(message["created_at"])
                    if not timestamp:
                        continue
                    start = (timestamp - timedelta(days=timestamp.weekday())).date().isoformat()
                    entry = weeks.setdefault(start, {"week": start, "student_messages": 0, "students": set()})
                    entry["student_messages"] += 1
                    if start not in seen:
                        entry["students"].add(value["id"])
                        seen.add(start)
        return [{"week": key, "student_messages": item["student_messages"], "active_students": len(item["students"])} for key, item in sorted(weeks.items())]

    @staticmethod
    def _time_band(minutes: int) -> str:
        if minutes == 0:
            return "No activity"
        if minutes <= 15:
            return "1–15 min"
        if minutes <= 45:
            return "16–45 min"
        return "46+ min"

    def _summary(self, values: Iterable[dict[str, Any]], profile: dict[str, ScoreValue], attention: list[StudentListItem]) -> str:
        values = list(values)
        counts = Counter(value["stage"] for value in values if value["stage"])
        first = "No student discussions have been recorded yet."
        started = sum(counts.values())
        if started:
            adjacent = max(
                ((STAGES[index], STAGES[index + 1]) for index in range(len(STAGES) - 1)),
                key=lambda pair: counts[pair[0]] + counts[pair[1]],
            )
            adjacent_count = counts[adjacent[0]] + counts[adjacent[1]]
            if adjacent_count / started >= 0.5:
                first = (
                    f"{adjacent_count} of {started} students with a current discussion are "
                    f"working between {_label(adjacent[0])} and {_label(adjacent[1])}."
                )
            else:
                stage, count = max(counts.items(), key=lambda item: (item[1], -STAGES.index(item[0])))
                first = (
                    f"The largest group is at {_label(stage)} "
                    f"({count} of {started} students with a current discussion)."
                )
        scored = [
            (label, item.value, item.sample_size)
            for label, item in profile.items()
            if item.value is not None and item.sample_size >= 3
        ]
        lowest = min(scored, key=lambda item: item[1]) if scored else None
        parts = [first]
        if lowest:
            parts.append(
                f"{lowest[0]} has the lowest class median ({lowest[1]:.1f}/4; n={lowest[2]})."
            )
        inactive = sum(
            any(signal.code == "inactive" for signal in row.needs_attention)
            for row in attention
        )
        if inactive:
            parts.append(
                f"{inactive} student{'s' if inactive != 1 else ''} "
                f"{'have' if inactive != 1 else 'has'} no activity in the past seven days."
            )
        return " ".join(parts)
