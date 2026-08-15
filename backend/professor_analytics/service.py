"""Pure, read-only learning analytics derived from persisted application data."""

from __future__ import annotations

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
    OverviewResponse,
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
        rows = [self._student_item(value) for value in self._build_students(self._repository.load_class_rows()).values()]
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
        """Return one authorised learner's journey and active transcript only."""
        class_students = self._build_students(self._repository.load_class_rows())
        value = class_students.get(student_id)
        if value is None:
            return None
        trend = [
            {"at": item["at"], "overall": item["overall"], "stage": _label(item["stage"])}
            for item in value["assessments"] if item["overall"] is not None
        ]
        notebooks = [
            {"id": notebook["id"], "title": notebook["title"], "stage": _label(notebook["stage"]),
             "messages": len(notebook["messages"]), "student_messages": sum(1 for message in notebook["messages"] if message["role"] == "user"),
             "last_active": notebook["last_activity"]}
            for notebook in value["notebooks"].values()
        ]
        notebooks.sort(key=lambda item: item["last_active"] or "", reverse=True)
        latest = value["latest_assessment"] or {}
        dimensions = {label: latest.get("dimensions", {}).get(key) for key, label in DIMENSIONS}
        return StudentDetailResponse(
            student=self._student_item(value),
            completed_stages=[_label(stage) or stage for stage in value["completed_stages"]],
            facione_profile=dimensions,
            class_facione_profile=self._dimension_profile(class_students.values()),
            class_median_facione=_score(
                student["overall"]
                for student in class_students.values()
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
            self._repository.load_class_rows(
                include_content=True,
                student_id=student_id,
                notebook_id=notebook_id,
            )
        )
        student = students.get(student_id)
        notebook = student["notebooks"].get(notebook_id) if student else None
        if notebook is None:
            return None
        return ConversationTranscriptResponse(
            notebook_id=notebook_id,
            title=notebook["title"],
            messages=[
                {
                    "role": message["role"],
                    "content": message["content"],
                    "created_at": message["created_at"],
                }
                for message in notebook["messages"]
            ],
        )

    def critical_thinking(self) -> CriticalThinkingResponse:
        """Return assessment aggregates that support teaching intervention."""
        students = self._build_students(self._repository.load_class_rows())
        values = list(students.values())
        scores = [student["overall"] for student in values if student["overall"] is not None]
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
            dimensions=self._dimension_profile(values), distribution=distribution,
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
            message = {
                "id": str(row["message_id"]),
                "role": str(row.get("message_role") or ""),
                "created_at": row.get("message_created_at"),
                "content": str(row.get("message_content") or ""),
                "is_error": bool(row.get("message_is_error")),
                "cited_source_ids": self._json_list(row.get("cited_source_ids_text")),
            }
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
        return StudentListItem(id=value["id"], name=value["name"], email=value["email"], current_stage=_label(value["stage"]), stage_progress=len(value["completed_stages"]), facione_overall=value["overall"], student_messages=value["student_messages"], active_days=len(value["active_days"]), last_active=value["last_activity"], needs_attention=self._attention(value))

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
