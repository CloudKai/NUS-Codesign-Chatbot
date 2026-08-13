from __future__ import annotations

import re
from typing import Any, Iterable

from backend.learning.stages import (
    DEFAULT_STAGE,
    STAGE_BY_ID,
    THINKING_STAGES,
    ThinkingStage,
)
RESPONSE_DETAILS = ("short", "long")
COACHING_PROFILES = ("quick", "strict")
STRICT_FACIONE_BASELINE_KEY = "strict_facione_baseline"
_STAGE_DECISION = re.compile(
    r"<!--\s*stage\s*:\s*(advance|stay)\s*-->",
    re.IGNORECASE,
)
_CONTRIBUTION_RESTATEMENT = re.compile(
    r"(?m)^(?:You(?:'|’)re exploring|I understand your current contribution as|"
    r"You(?:'|’)ve made this step clearer):.*"
    r"(?:\n\n|$)"
)
_READY_NEXT_PART = re.compile(
    r"(?m)^This is ready for the next part of the thinking path\.?\s*(?:\n\n|$)"
)
_SELECTED_LECTURE_BOILERPLATE = re.compile(
    r"(?m)^I(?:'|’)ll use the selected lecture material as evidence as we continue\.?\s*"
    r"(?:\n\n|$)"
)
_IMAGE_EVIDENCE_BOILERPLATE = re.compile(
    r"(?m)^I can see \d+ selected image source\(s\) and will treat them as notebook "
    r"evidence\.?\s*(?:\n\n|$)"
)
_STAGE_SIGNALS: dict[str, tuple[str, ...]] = {
    "focus": (
        "question",
        "problem",
        "claim",
        "focus",
        "understand",
        "evaluate",
        "compare",
        "whether",
    ),
    "evidence": (
        "evidence",
        "source",
        "data",
        "study",
        "result",
        "finding",
        "example",
        "reliable",
        "sample",
    ),
    "assumptions": (
        "assume",
        "assumption",
        "because",
        "depends",
        "implies",
        "premise",
        "believe",
        "uncertain",
    ),
    "perspectives": (
        "alternative",
        "counter",
        "however",
        "another",
        "perspective",
        "objection",
        "although",
        "whereas",
    ),
    "synthesis": (
        "overall",
        "therefore",
        "weigh",
        "balance",
        "combined",
        "considering",
        "stronger",
        "suggests",
    ),
    "conclusion": (
        "conclude",
        "conclusion",
        "confidence",
        "confident",
        "limitation",
        "remains",
        "qualified",
        "next step",
    ),
}
_STAGE_GUIDANCE: dict[str, tuple[str, str, str]] = {
    "focus": (
        "What exactly are you trying to understand, explain, or argue?",
        "Can you state the central question or claim in one clear sentence?",
        "What would a useful answer help you decide or do?",
    ),
    "evidence": (
        "Which evidence matters most, and how reliable is it?",
        "What does the strongest source directly support?",
        "What limitation could weaken that evidence?",
    ),
    "assumptions": (
        "What are you assuming, and which assumption is most uncertain?",
        "Which unstated premise connects your evidence to your claim?",
        "What changes if that premise is false?",
    ),
    "perspectives": (
        "What is the strongest alternative explanation or counterargument?",
        "Who might interpret the same evidence differently, and why?",
        "What would the strongest critic say about your reasoning?",
    ),
    "synthesis": (
        "How should your claim change after considering the evidence and alternatives?",
        "Which considerations deserve the most weight?",
        "Where do the competing perspectives agree or remain unresolved?",
    ),
    "conclusion": (
        "What can you conclude now, with what confidence, and what remains unresolved?",
        "Which limitation should qualify your conclusion?",
        "What is the most justified next step?",
    ),
}


def default_journey() -> dict[str, Any]:
    return {
        "current_stage": DEFAULT_STAGE,
        "completed_stages": [],
        "stage_notes": {},
        "working_conclusion": "",
        "critical_reflection": "",
        "response_detail": "short",
    }


def coaching_profile_for_response_detail(response_detail: str) -> str:
    """Map the stable public detail value to its internal coaching profile."""
    return "strict" if str(response_detail).lower() == "long" else "quick"


def normalize_journey(value: Any) -> dict[str, Any]:
    raw = value if isinstance(value, dict) else {}
    journey = default_journey()
    current_stage = raw.get("current_stage")
    journey["current_stage"] = current_stage if current_stage in STAGE_BY_ID else DEFAULT_STAGE
    completed = raw.get("completed_stages")
    if isinstance(completed, list):
        journey["completed_stages"] = [
            stage.id for stage in THINKING_STAGES if stage.id in set(completed)
        ]
    # A completed stage may also be current when the student deliberately
    # revisits earlier work. Completion remains recorded while coaching is
    # temporarily focused on that stage again.
    notes = raw.get("stage_notes")
    if isinstance(notes, dict):
        journey["stage_notes"] = {
            stage.id: str(notes.get(stage.id, "")).strip()
            for stage in THINKING_STAGES
            if str(notes.get(stage.id, "")).strip()
        }
    journey["working_conclusion"] = str(raw.get("working_conclusion", "")).strip()
    journey["critical_reflection"] = str(raw.get("critical_reflection", "")).strip()
    detail = str(raw.get("response_detail", "short")).lower()
    journey["response_detail"] = detail if detail in RESPONSE_DETAILS else "short"
    if STRICT_FACIONE_BASELINE_KEY in raw:
        baseline = raw.get(STRICT_FACIONE_BASELINE_KEY)
        if isinstance(baseline, dict) and "scores" in baseline:
            boundary = baseline.get("captured_through")
            normalized_boundary = None
            if isinstance(boundary, dict):
                created_at = str(boundary.get("created_at") or "").strip()
                message_id = str(boundary.get("message_id") or "").strip()
                if created_at and message_id:
                    normalized_boundary = {
                        "created_at": created_at,
                        "message_id": message_id,
                    }
            journey[STRICT_FACIONE_BASELINE_KEY] = {
                "scores": _normalize_facione_scores(baseline.get("scores")),
                "captured_through": normalized_boundary,
            }
        else:
            # Flat score dicts were written briefly before capture provenance
            # existed. Preserve them as a fallback instead of losing progress.
            journey[STRICT_FACIONE_BASELINE_KEY] = _normalize_facione_scores(baseline)
    return journey


def current_stage(journey: dict[str, Any]) -> ThinkingStage:
    normalized = normalize_journey(journey)
    return STAGE_BY_ID[normalized["current_stage"]]


def stage_guidance_questions(stage_id: str) -> tuple[str, str, str]:
    return _STAGE_GUIDANCE.get(stage_id, _STAGE_GUIDANCE[DEFAULT_STAGE])


def personalized_stage_questions(
    stage_id: str,
    student_contribution: str,
    *,
    has_course_sources: bool = False,
) -> tuple[str, ...]:
    """Create concise next-step prompts tied to the student's current topic.

    This helper personalizes coaching language only; it never decides whether a
    stage is complete. Provider-generated questions remain preferred when they
    are available, while this deterministic fallback keeps mock and offline
    demonstrations useful.
    """
    normalized = " ".join(student_contribution.lower().split())
    older_adult_topic = any(
        phrase in normalized
        for phrase in (
            "elderly",
            "older adult",
            "older people",
            "older pedestrian",
            "senior",
            "aged",
        )
    )
    evidence_reference = (
        "the selected lecture notes or readings"
        if has_course_sources
        else "the course materials"
    )

    if stage_id == "evidence":
        population_question = (
            "Which group of older adults are you focusing on—for example, people "
            "with limited mobility, slower walking speeds, visual impairments, or "
            "cognitive difficulties?"
            if older_adult_topic
            else "Which specific people, setting, or situation within your topic should "
            "you focus on first?"
        )
        return (
            population_question,
            f"What evidence in {evidence_reference} supports that focus, and what are "
            "the limits of that evidence?",
        )
    if stage_id == "assumptions":
        subject = "older adults" if older_adult_topic else "the people in your chosen context"
        return (
            f"What are you assuming about {subject}, and which assumption is least certain?",
            f"Does {evidence_reference} support that assumption, challenge it, or leave it unresolved?",
        )
    if stage_id == "perspectives":
        subject = "older adults, caregivers, and road users" if older_adult_topic else "the affected groups"
        return (
            f"How might {subject} view the problem differently?",
            f"Which perspective is missing from {evidence_reference}, and why might it matter?",
        )
    if stage_id == "synthesis":
        return (
            "Which pieces of evidence should carry the most weight in your current reasoning?",
            f"How should your idea change after comparing the tensions or limits in {evidence_reference}?",
        )
    if stage_id == "conclusion":
        return (
            "What can you conclude now, and how confident are you in that conclusion?",
            f"Which limitation in {evidence_reference} should qualify your conclusion?",
        )
    return stage_guidance_questions(stage_id)[:2]


def advanced_stage_response(
    response_text: str,
    current_stage_id: str,
    next_stage_id: str,
    questions: Iterable[str],
) -> str:
    """Present an automatic transition as the new stage plus useful questions."""
    current_stage_value = STAGE_BY_ID[current_stage_id]
    next_stage_value = STAGE_BY_ID[next_stage_id]
    response_body = concise_coach_response(response_text.strip())
    current_heading = f"**{current_stage_value.label}**"
    if response_body.startswith(current_heading):
        response_body = response_body[len(current_heading) :].strip()
    next_heading = f"**{next_stage_value.label}**"
    if response_body.startswith(next_heading):
        # Mock/provider already wrote the destination-stage reply.
        return response_body
    legacy_notice = (
        f"**Thinking Path:** I’ve moved you to {next_stage_value.short_label}."
    )
    response_body = response_body.replace(legacy_notice, "").strip()
    normalized_questions = [question.strip() for question in questions if question.strip()]
    question_list = "\n".join(f"- {question}" for question in normalized_questions)
    body = response_body
    if not body:
        body = next_stage_value.description
    return (
        f"**{next_stage_value.label}**\n\n"
        f"{body}\n\n"
        f"**Questions to explore**\n\n{question_list}"
    ).strip()


def concise_coach_response(response_text: str) -> str:
    """Hide legacy contribution restatements and readiness boilerplate."""
    cleaned = response_text
    cleaned = _CONTRIBUTION_RESTATEMENT.sub("", cleaned, count=1)
    cleaned = _READY_NEXT_PART.sub("", cleaned)
    cleaned = _SELECTED_LECTURE_BOILERPLATE.sub("", cleaned)
    cleaned = _IMAGE_EVIDENCE_BOILERPLATE.sub("", cleaned)
    return cleaned.strip()


def set_current_stage(journey: dict[str, Any], stage_id: str) -> dict[str, Any]:
    """Set the active Thinking Path stage without marking other stages complete."""
    normalized = normalize_journey(journey)
    if stage_id not in STAGE_BY_ID:
        raise ValueError(f"Unknown thinking stage: {stage_id}")
    normalized["current_stage"] = stage_id
    return normalized


def stage_selection_enabled() -> bool:
    """Return whether Journey stage picking is enabled for this process."""
    from backend.settings import settings

    return bool(settings.student_stage_selection)


def next_stage_id(stage_id: str) -> str | None:
    """Return the id of the stage after ``stage_id``, or None at Conclusion."""
    if stage_id not in STAGE_BY_ID:
        return None
    index = next(index for index, item in enumerate(THINKING_STAGES) if item.id == stage_id)
    if index >= len(THINKING_STAGES) - 1:
        return None
    return THINKING_STAGES[index + 1].id


def complete_and_advance(
    journey: dict[str, Any],
    *,
    note: str | None = None,
) -> dict[str, Any]:
    normalized = normalize_journey(journey)
    stage = current_stage(normalized)
    if note is not None and note.strip():
        normalized["stage_notes"][stage.id] = note.strip()
    if stage.id not in normalized["completed_stages"]:
        normalized["completed_stages"].append(stage.id)
    index = next(index for index, item in enumerate(THINKING_STAGES) if item.id == stage.id)
    if index < len(THINKING_STAGES) - 1:
        normalized["current_stage"] = THINKING_STAGES[index + 1].id
    return normalize_journey(normalized)


def contribution_supports_stage(content: str, stage_id: str) -> bool:
    """Fallback assessment when a model response omits its hidden stage decision."""
    normalized = " ".join(content.lower().split())
    words = re.findall(r"[a-z0-9']+", normalized)
    if stage_id not in STAGE_BY_ID or len(words) < 8:
        return False
    signals = _STAGE_SIGNALS[stage_id]
    signal_count = sum(1 for signal in signals if signal in normalized)
    if signal_count:
        return True
    return len(words) >= 24


def automatic_stage_update(
    journey: dict[str, Any],
    student_contribution: str,
    assistant_response: str,
    *,
    allow_advance: bool = True,
) -> tuple[dict[str, Any], str, str]:
    """Apply the coach's hidden decision and return clean assistant text."""
    normalized = normalize_journey(journey)
    stage = current_stage(normalized)
    decisions = _STAGE_DECISION.findall(assistant_response)
    clean_response = _STAGE_DECISION.sub("", assistant_response).strip()
    if not allow_advance:
        decision = "stay"
    elif decisions:
        decision = decisions[-1].lower()
    else:
        decision = (
            "advance"
            if contribution_supports_stage(student_contribution, stage.id)
            else "stay"
        )
    if decision == "advance":
        normalized = complete_and_advance(
            normalized,
            note=student_contribution,
        )
        if stage.id in {"synthesis", "conclusion"}:
            normalized["working_conclusion"] = student_contribution.strip()
        if stage.id != "focus":
            normalized["critical_reflection"] = (
                f"The discussion advanced from {stage.label.lower()} after the student "
                "made the reasoning for this stage explicit."
            )
    return normalize_journey(normalized), decision, clean_response


def journey_progress(journey: dict[str, Any]) -> int:
    normalized = normalize_journey(journey)
    return round(len(normalized["completed_stages"]) / len(THINKING_STAGES) * 100)


def understanding_level(journey: dict[str, Any]) -> tuple[str, str]:
    completed = len(normalize_journey(journey)["completed_stages"])
    if completed <= 1:
        return "Emerging", "You are clarifying the problem and beginning to identify relevant reasoning."
    if completed <= 3:
        return "Developing", "You are connecting evidence, assumptions, and alternative perspectives."
    if completed <= 5:
        return "Connected", "You are synthesizing competing considerations into a defensible position."
    return "Integrated", "You have worked through the full reasoning cycle and recorded a conclusion."


def _student_messages(messages: Iterable[dict[str, Any]]) -> list[str]:
    return [
        " ".join(str(message.get("content", "")).split())
        for message in messages
        if message.get("role") == "user" and str(message.get("content", "")).strip()
    ]


FACIONE_DIMENSIONS: tuple[tuple[str, str], ...] = (
    ("analysis", "Analysis"),
    ("interpretation", "Interpretation"),
    ("inference", "Inference"),
    ("evaluation", "Evaluation"),
    ("explanation", "Explanation"),
    ("self_regulation", "Self-Regulation"),
)

FACIONE_SCORE_LABELS: dict[int, str] = {
    0: "Not started",
    1: "Weak",
    2: "Unacceptable",
    3: "Acceptable",
    4: "Strong",
}

_EMPTY_REVIEW_SUMMARY = (
    "Your discussion will be summarized here after you start chatting."
)


def _normalize_facione_scores(raw: Any) -> dict[str, int]:
    """Clamp Facione scores to 0–4; missing legacy payloads become not-started."""
    source = raw if isinstance(raw, dict) else {}
    normalized: dict[str, int] = {}
    for key, _label in FACIONE_DIMENSIONS:
        try:
            value = int(source.get(key, 0))
        except (TypeError, ValueError):
            value = 0
        normalized[key] = max(0, min(4, value))
    return normalized


def _cumulative_facione_scores(
    messages: Iterable[dict[str, Any]],
    *,
    coaching_profile: str,
    baseline: Any = None,
) -> dict[str, int]:
    """Return strongest active scores for one internal coaching profile.

    Untagged assessments predate profile-aware scoring and seed both profiles.
    Tagged Quick and Strict assessments otherwise remain separate. Strict may
    additionally start from the immutable baseline captured on first switch so
    existing progress is retained without letting later Quick evidence raise a
    Strict score. Callers provide the active message branch; superseded history
    is excluded by the repository before this presentation helper runs.
    """
    selected_profile = (
        coaching_profile if coaching_profile in COACHING_PROFILES else "quick"
    )
    baseline_scores: Any = None
    boundary: tuple[str, str] | None = None
    if selected_profile == "strict" and isinstance(baseline, dict):
        if "scores" in baseline:
            baseline_scores = baseline.get("scores")
            captured_through = baseline.get("captured_through")
            if isinstance(captured_through, dict):
                created_at = str(captured_through.get("created_at") or "").strip()
                message_id = str(captured_through.get("message_id") or "").strip()
                if created_at and message_id:
                    boundary = (created_at, message_id)
        else:
            baseline_scores = baseline
    cumulative = _normalize_facione_scores(
        baseline_scores if selected_profile == "strict" and boundary is None else None
    )
    for message in messages:
        if message.get("role") != "assistant":
            continue
        metadata = message.get("metadata") or {}
        if not isinstance(metadata, dict):
            continue
        profile = str(metadata.get("coaching_profile") or "").strip().lower()
        if selected_profile == "strict" and boundary is not None:
            message_position = (
                str(message.get("createdAt") or message.get("created_at") or ""),
                str(message.get("id") or ""),
            )
            is_baseline_evidence = profile in {"", "quick"}
            if is_baseline_evidence and message_position > boundary:
                continue
        if profile and profile != selected_profile:
            # Strict recomputes the baseline from active legacy/Quick messages
            # at or before its capture boundary. Other cross-profile evidence
            # remains isolated.
            if not (
                selected_profile == "strict"
                and boundary is not None
                and profile == "quick"
                and message_position <= boundary
            ):
                continue
        assessment = metadata.get("assessment")
        if not isinstance(assessment, dict) or not assessment.get("recommendation"):
            continue
        scores = _normalize_facione_scores(assessment.get("facione_scores"))
        for key, _label in FACIONE_DIMENSIONS:
            cumulative[key] = max(cumulative[key], scores[key])
    return cumulative


def _review_summary(assessment: dict[str, Any] | None) -> str:
    """Prefer the model-written learning_summary; never paste student prompts."""
    if not assessment:
        return _EMPTY_REVIEW_SUMMARY
    summary = " ".join(str(assessment.get("learning_summary") or "").split()).strip()
    return summary or _EMPTY_REVIEW_SUMMARY


def _clean_feedback_items(values: Iterable[Any]) -> list[str]:
    """Normalize and dedupe short review feedback strings."""
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
        cleaned.append(item)
    return cleaned


def _assessments(messages: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    """Return persisted assessments in chronological order."""
    found: list[dict[str, Any]] = []
    for message in messages:
        if message.get("role") != "assistant":
            continue
        assessment = (message.get("metadata") or {}).get("assessment")
        if isinstance(assessment, dict) and assessment.get("recommendation"):
            found.append(assessment)
    return found


def _latest_assessment(messages: Iterable[dict[str, Any]]) -> dict[str, Any] | None:
    """Return the newest assistant assessment payload, if one was persisted."""
    assessments = _assessments(messages)
    return assessments[-1] if assessments else None


def _legacy_strengths(assessment: dict[str, Any]) -> list[str]:
    """Map older assessment fields into supportive strengths."""
    stage_assessment = " ".join(
        str(assessment.get("stage_assessment") or "").split()
    ).strip()
    if not stage_assessment:
        return []
    # Avoid echoing contribution paste patterns from older personalization.
    if "your latest contribution centered on:" in stage_assessment.lower():
        stage_assessment = stage_assessment.split("Your latest contribution centered on:")[0].strip()
    return _clean_feedback_items([stage_assessment])


def _legacy_improvements(assessment: dict[str, Any]) -> list[str]:
    """Map older assessment fields into improvement actions."""
    missing = [
        " ".join(str(item).split()).strip()
        for item in (assessment.get("missing_reasoning_elements") or [])
        if str(item).strip()
    ]
    return _clean_feedback_items(missing)


def _stage_feedback_history(
    messages: Iterable[dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Aggregate strengths and improvements by Thinking Path stage.

    Stages without evidence stay empty. Feedback from each assessment is kept
    under that assessment's ``current_stage`` and deduplicated across turns.
    """
    strengths_by_stage: dict[str, list[str]] = {stage.id: [] for stage in THINKING_STAGES}
    improvements_by_stage: dict[str, list[str]] = {
        stage.id: [] for stage in THINKING_STAGES
    }
    for assessment in _assessments(messages):
        stage_id = str(assessment.get("current_stage") or "").strip()
        if stage_id not in STAGE_BY_ID:
            continue
        raw_strengths = assessment.get("review_strengths")
        if isinstance(raw_strengths, list):
            strengths = _clean_feedback_items(raw_strengths)
        else:
            strengths = _legacy_strengths(assessment)
        raw_improvements = assessment.get("review_improvements")
        if isinstance(raw_improvements, list):
            improvements = _clean_feedback_items(raw_improvements)
        else:
            improvements = _legacy_improvements(assessment)
        for item in strengths:
            if item.lower() not in {
                existing.lower() for existing in strengths_by_stage[stage_id]
            }:
                strengths_by_stage[stage_id].append(item)
        for item in improvements:
            if item.lower() not in {
                existing.lower() for existing in improvements_by_stage[stage_id]
            }:
                improvements_by_stage[stage_id].append(item)

    strength_sections = [
        {
            "stage_id": stage.id,
            "stage": stage.label,
            "items": strengths_by_stage[stage.id],
        }
        for stage in THINKING_STAGES
    ]
    improvement_sections = [
        {
            "stage_id": stage.id,
            "stage": stage.label,
            "items": improvements_by_stage[stage.id],
        }
        for stage in THINKING_STAGES
    ]
    return strength_sections, improvement_sections


def learning_review(
    messages: Iterable[dict[str, Any]],
    journey: dict[str, Any],
    *,
    detail: str | None = None,
) -> dict[str, Any]:
    """Build the Review-tab payload for the current notebook.

    Summary comes from the newest assessment. Facione scores retain the
    strongest demonstrated level per dimension across active assessments, and
    strengths and areas for improvement are aggregated by Thinking Path stage.
    Empty notebooks stay empty instead of showing generic filler.

    Returns:
        A dict consumed by ``ui.studio.render_learning_review``, including
        ``summary``, ``facione_scores``, ``strength_sections``,
        ``improvement_sections``, and ``has_personalized_assessment``.
    """
    message_list = list(messages)
    normalized = normalize_journey(journey)
    stage = current_stage(normalized)
    student_messages = _student_messages(message_list)
    selected_detail = detail if detail in RESPONSE_DETAILS else normalized["response_detail"]
    contribution_limit = 3 if selected_detail == "short" else 8
    contributions = student_messages[-contribution_limit:]
    level, level_description = understanding_level(normalized)
    assessment = _latest_assessment(message_list)
    if assessment:
        assessed_level = str(
            assessment.get("critical_understanding_level") or ""
        ).strip()
        if assessed_level:
            level = assessed_level
            level_description = (
                " ".join(str(assessment.get("stage_assessment") or "").split()).strip()
                or level_description
            )
    strength_sections, improvement_sections = _stage_feedback_history(message_list)
    current_strengths = next(
        (
            section["items"]
            for section in strength_sections
            if section["stage_id"] == stage.id
        ),
        [],
    )
    current_improvements = next(
        (
            section["items"]
            for section in improvement_sections
            if section["stage_id"] == stage.id
        ),
        [],
    )
    coaching_profile = coaching_profile_for_response_detail(selected_detail)
    facione_scores = _cumulative_facione_scores(
        message_list,
        coaching_profile=coaching_profile,
        baseline=journey.get(STRICT_FACIONE_BASELINE_KEY),
    )
    summary = _review_summary(assessment)
    completed_labels = [
        STAGE_BY_ID[stage_id].label for stage_id in normalized["completed_stages"]
    ]
    notes = [
        {
            "stage": STAGE_BY_ID[stage_id].label,
            "note": normalized["stage_notes"].get(stage_id, ""),
        }
        for stage_id in normalized["completed_stages"]
        if normalized["stage_notes"].get(stage_id)
    ]
    conclusion = (
        (
            " ".join(str(assessment.get("working_conclusion") or "").split()).strip()
            if assessment
            else ""
        )
        or normalized["working_conclusion"]
        or ""
    )
    critical_reflection = (
        (
            " ".join(str(assessment.get("understanding_change") or "").split()).strip()
            if assessment
            else ""
        )
        or normalized["critical_reflection"]
        or ""
    )
    return {
        "detail": selected_detail,
        "current_stage": stage.label,
        "progress": journey_progress(normalized),
        "understanding_level": level,
        "understanding_description": level_description,
        "completed_stages": completed_labels,
        "contributions": contributions,
        "summary": summary,
        "facione_scores": facione_scores,
        "stage_notes": notes,
        "conclusion": conclusion,
        "critical_reflection": critical_reflection,
        "strength_sections": strength_sections,
        "improvement_sections": improvement_sections,
        "strengths": " ".join(current_strengths),
        "improvement_areas": list(current_improvements),
        "next_question": stage.reflection_prompt,
        "turn_count": len(student_messages),
        "has_personalized_assessment": assessment is not None,
    }
