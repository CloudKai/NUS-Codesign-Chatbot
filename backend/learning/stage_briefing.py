"""Deterministic coach briefings after a Thinking Path stage move or revisit.

No model call. Copy uses stage definitions, working conclusion / prior notes,
personalized how-questions, and Review areas to improve when available.
"""

from __future__ import annotations

from typing import Any, Iterable, Mapping

from backend.learning.journey import (
    learning_review,
    normalize_journey,
    personalized_stage_questions,
    stage_guidance_questions,
)
from backend.learning.stages import STAGE_BY_ID
from backend.specialists.review_orchestration import (
    parse_journey_stage_reviews,
)

_TOPIC_SEED_LIMIT = 220
_IMPROVEMENT_LIMIT = 2
_COMMAND_LIMIT = 2


def stage_move_heading(stage_id: str) -> str:
    """Return the canonical ``Moved to Stage: …`` first line.

    Args:
        stage_id: Canonical Thinking Path stage id.

    Returns:
        Heading ending with a period.
    """
    stage = STAGE_BY_ID[stage_id]
    return f"Moved to Stage: {stage.label}."


def compose_stage_move_briefing(
    *,
    target_stage: str,
    journey: Mapping[str, Any] | None,
    messages: Iterable[Mapping[str, Any]] | None = None,
    deep_review_snapshot: Mapping[str, Any] | None = None,
    journey_stage_reviews: Mapping[str, Any] | None = None,
    already_selected: bool = False,
) -> str | None:
    """Build the coach bubble for a successful stage move or revisit.

    Args:
        target_stage: Destination Thinking Path stage id.
        journey: Raw or normalized learning-journey metadata **before** the
            focus change (``completed_stages`` decides enter vs revisit).
        messages: Notebook transcript for topic seed and Review merge.
        deep_review_snapshot: Optional durable Deep Review snapshot.
        journey_stage_reviews: Optional Haiku stage-checkpoint blob.
        already_selected: When True, return ``None`` (no bubble / no notice).

    Returns:
        Markdown for one assistant message, or ``None`` when the student is
        already on ``target_stage``.

    Raises:
        KeyError: When ``target_stage`` is not a known stage id.
    """
    if already_selected:
        return None
    cleaned = str(target_stage or "").strip()
    stage = STAGE_BY_ID[cleaned]
    normalized = normalize_journey(journey)
    completed = {
        str(item or "").strip()
        for item in (normalized.get("completed_stages") or [])
        if str(item or "").strip()
    }
    message_list = [dict(item) for item in (messages or [])]
    snapshot = (
        dict(deep_review_snapshot)
        if isinstance(deep_review_snapshot, Mapping)
        else None
    )
    checkpoint_blob = parse_journey_stage_reviews(journey_stage_reviews)
    if cleaned in completed:
        return _revisit_briefing(
            stage_id=cleaned,
            journey=normalized,
            messages=message_list,
            deep_review_snapshot=snapshot,
            journey_stage_reviews=checkpoint_blob,
        )
    return _enter_briefing(
        stage_id=cleaned,
        journey=normalized,
        messages=message_list,
        deep_review_snapshot=snapshot,
    )


def _enter_briefing(
    *,
    stage_id: str,
    journey: dict[str, Any],
    messages: list[dict[str, Any]],
    deep_review_snapshot: dict[str, Any] | None,
) -> str:
    """Compose first-time / forward-move commands for ``stage_id``."""
    stage = STAGE_BY_ID[stage_id]
    heading = stage_move_heading(stage_id)
    topic = _topic_seed(
        journey=journey,
        messages=messages,
        deep_review_snapshot=deep_review_snapshot,
    )
    questions = personalized_stage_questions(stage_id, topic)[:_COMMAND_LIMIT]
    if len(questions) < _COMMAND_LIMIT:
        for fallback in stage_guidance_questions(stage_id):
            if fallback not in questions:
                questions = (*questions, fallback)
            if len(questions) >= _COMMAND_LIMIT:
                break
    context = stage.description.rstrip(".")
    if topic:
        context = f'{context}. Building from your work so far: "{topic}"'
    else:
        context = f"{context}."
    lines = [
        heading,
        "",
        context,
        "",
        "What to work on next:",
        *[f"{index}. {item}" for index, item in enumerate(questions[:_COMMAND_LIMIT], start=1)],
    ]
    return "\n".join(lines).strip()


def _revisit_briefing(
    *,
    stage_id: str,
    journey: dict[str, Any],
    messages: list[dict[str, Any]],
    deep_review_snapshot: dict[str, Any] | None,
    journey_stage_reviews: dict[str, Any],
) -> str:
    """Compose revisit commands focused on what to improve and how."""
    stage = STAGE_BY_ID[stage_id]
    heading = stage_move_heading(stage_id)
    conclusion = _working_conclusion(
        journey=journey,
        messages=messages,
        deep_review_snapshot=deep_review_snapshot,
    )
    improvements = _areas_to_improve(
        stage_id=stage_id,
        messages=messages,
        deep_review_snapshot=deep_review_snapshot,
        journey_stage_reviews=journey_stage_reviews,
        journey=journey,
    )
    how = _revisit_how_commands(
        stage_id=stage_id,
        improvements=improvements,
        conclusion=conclusion,
    )
    parts: list[str] = [heading, ""]
    if conclusion:
        parts.append(f'Working conclusion to sharpen: "{conclusion}"')
        parts.append("")
    if improvements:
        parts.append("What to improve:")
        for item in improvements[:_IMPROVEMENT_LIMIT]:
            parts.append(f"- {item}")
        parts.append("")
    else:
        parts.append(
            f"Revisit {stage.label} to tighten your earlier reasoning before moving on."
        )
        parts.append("")
    parts.append("How to improve:")
    for index, item in enumerate(how[:_COMMAND_LIMIT], start=1):
        parts.append(f"{index}. {item}")
    return "\n".join(parts).strip()


def _topic_seed(
    *,
    journey: dict[str, Any],
    messages: list[dict[str, Any]],
    deep_review_snapshot: dict[str, Any] | None,
) -> str:
    """Pick a short topic seed for personalizing enter-stage how-commands."""
    conclusion = _working_conclusion(
        journey=journey,
        messages=messages,
        deep_review_snapshot=deep_review_snapshot,
    )
    if conclusion:
        return conclusion
    notes = journey.get("stage_notes") if isinstance(journey.get("stage_notes"), dict) else {}
    # Prefer the most recent completed stage note, walking the path in reverse.
    from backend.learning.stages import THINKING_STAGES

    completed = {
        str(item or "").strip()
        for item in (journey.get("completed_stages") or [])
        if str(item or "").strip()
    }
    for stage in reversed(THINKING_STAGES):
        if stage.id not in completed:
            continue
        note = " ".join(str(notes.get(stage.id) or "").split()).strip()
        if note:
            return _truncate(note, _TOPIC_SEED_LIMIT)
    for message in reversed(messages):
        if message.get("role") != "user":
            continue
        content = " ".join(str(message.get("content") or "").split()).strip()
        if content:
            return _truncate(content, _TOPIC_SEED_LIMIT)
    return ""


def _working_conclusion(
    *,
    journey: dict[str, Any],
    messages: list[dict[str, Any]],
    deep_review_snapshot: dict[str, Any] | None,
) -> str:
    """Resolve working conclusion from Deep Review, latest assessment, or journey."""
    if isinstance(deep_review_snapshot, dict):
        snapshot_conclusion = " ".join(
            str(deep_review_snapshot.get("working_conclusion") or "").split()
        ).strip()
        if snapshot_conclusion:
            return _truncate(snapshot_conclusion, _TOPIC_SEED_LIMIT)
    review = learning_review(
        messages,
        journey,
        detail=journey.get("response_detail"),
        deep_review_snapshot=deep_review_snapshot,
    )
    conclusion = " ".join(str(review.get("conclusion") or "").split()).strip()
    if conclusion:
        return _truncate(conclusion, _TOPIC_SEED_LIMIT)
    return _truncate(
        " ".join(str(journey.get("working_conclusion") or "").split()).strip(),
        _TOPIC_SEED_LIMIT,
    )


def _areas_to_improve(
    *,
    stage_id: str,
    messages: list[dict[str, Any]],
    deep_review_snapshot: dict[str, Any] | None,
    journey_stage_reviews: dict[str, Any],
    journey: dict[str, Any],
) -> list[str]:
    """Merge checkpoint areas_to_revisit with Review improvement_sections."""
    items: list[str] = []
    seen: set[str] = set()

    def _add(raw: Any) -> None:
        cleaned = " ".join(str(raw or "").split()).strip()
        if not cleaned:
            return
        key = cleaned.casefold()
        if key in seen:
            return
        seen.add(key)
        items.append(cleaned)

    review_row = (journey_stage_reviews.get("reviews") or {}).get(stage_id) or {}
    if isinstance(review_row, dict):
        for item in review_row.get("areas_to_revisit") or []:
            _add(item)
    review = learning_review(
        messages,
        journey,
        detail=journey.get("response_detail"),
        deep_review_snapshot=deep_review_snapshot,
        journey_stage_reviews=journey_stage_reviews,
    )
    for section in review.get("improvement_sections") or []:
        if str(section.get("stage_id") or "") != stage_id:
            continue
        for item in section.get("items") or []:
            _add(item)
    return items[:_IMPROVEMENT_LIMIT]


def _revisit_how_commands(
    *,
    stage_id: str,
    improvements: list[str],
    conclusion: str,
) -> list[str]:
    """Turn improvement areas into two concrete revise commands."""
    commands: list[str] = []
    for item in improvements[:_COMMAND_LIMIT]:
        commands.append(f"Revise your work so that you address: {item}")
    if len(commands) < _COMMAND_LIMIT:
        seed = conclusion or " ".join(improvements)
        for question in personalized_stage_questions(stage_id, seed):
            if question not in commands:
                commands.append(question)
            if len(commands) >= _COMMAND_LIMIT:
                break
    if len(commands) < _COMMAND_LIMIT:
        for question in stage_guidance_questions(stage_id):
            if question not in commands:
                commands.append(question)
            if len(commands) >= _COMMAND_LIMIT:
                break
    return commands[:_COMMAND_LIMIT]


def _truncate(value: str, limit: int) -> str:
    """Collapse whitespace and truncate with an ellipsis when needed."""
    cleaned = " ".join(str(value or "").split()).strip()
    if len(cleaned) <= limit:
        return cleaned
    return cleaned[: max(0, limit - 1)].rstrip() + "…"
