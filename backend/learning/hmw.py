"""Server-owned How Might We scaffold eligibility for Problem Identification.

Visibility is projected from the persisted Thinking Path stage plus the latest
meaningful active Coaching assessment. The model may set
``hmw_scaffold_ready``; FastAPI decides whether the UI may show the scaffold
and whether a Problem Identification ADVANCE may proceed. This module never
calls a model and never mutates stage.
"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from typing import Any

from backend.learning.stages import DEFAULT_STAGE


HMW_SCAFFOLD_STAGE_ID = "problem_identification"
COACH_WELCOME_KIND = "coach_welcome"

_HMW_MARKER = "how might we"
_MIN_HMW_CONTENT_WORDS = 6
_HMW_META_RE = re.compile(
    r"|".join(
        (
            r"what does how might we",
            r"what is (?:a |an )?how might we",
            r"what are how might we",
            r"what do how might we",
            r"(?:can|could) you (?:explain|define) how might we",
            r"explain how might we",
            r"meaning of how might we",
            r"should i use (?:a |an )?how might we",
            r"how might we (?:questions?|statements?|formula|scaffold)",
            r"(?:lecture|week \d+|course material).{0,80}how might we",
            r"the lecture says how might we",
        )
    )
)
_HMW_LEADING_META_RE = re.compile(
    r"^(?:what|why|when|where|who|how do|how does|can you|could you|"
    r"should i|do i|does)\b"
)
_HMW_CONSTRUCTION_META_RE = re.compile(
    r"(?:\b(?:here is|this is|use|using|follow|fill in|complete|write|"
    r"create|generate|phrase|formulate|make|draft|give me|help me)\b"
    r"[^.?!]{0,100}\b(?:example|template|formula|scaffold|card|prompt|"
    r"instruction)\b[^.?!]{0,100}\bhow might we\b|\b(?:write|create|"
    r"generate|phrase|formulate|make|draft|give me|help me)\b[^.?!]{0,100}"
    r"\bhow might we\b|\bhow might we\b[^.?!]{0,100}\b(?:as an example|"
    r"as a template|using this formula|is a scaffold|is a prompt|is an "
    r"instruction|assignment|question|statement)\b)",
    re.IGNORECASE,
)


def _as_mapping(value: Any) -> Mapping[str, Any] | None:
    """Return a mapping or ``None`` when ``value`` is not a JSON object."""
    return value if isinstance(value, Mapping) else None


def _assistant_assessment(message: Mapping[str, Any]) -> Mapping[str, Any] | None:
    """Return the persisted assessment for one active assistant turn.

    Welcome rows, non-assistant rows, and messages without a mapping
    assessment are skipped. Callers must pass the active conversation
    branch; this helper does not inspect superseded rows.

    Args:
        message: One persisted message object from ``get_messages``.

    Returns:
        The assessment mapping, or ``None`` when the row is not a qualifying
        assessment carrier.
    """
    if str(message.get("role") or "").strip().lower() != "assistant":
        return None
    metadata = _as_mapping(message.get("metadata"))
    if metadata is None:
        return None
    if str(metadata.get("kind") or "").strip() == COACH_WELCOME_KIND:
        return None
    return _as_mapping(metadata.get("assessment"))


def _is_deep_review_assessment(assessment: Mapping[str, Any]) -> bool:
    """Return whether this persisted assessment is a Deep Review row."""
    mode = str(assessment.get("response_mode") or "").strip().lower()
    if mode == "review":
        return True
    for key in ("review_depth", "review_trigger", "review_model"):
        if str(assessment.get(key) or "").strip():
            return True
    return False


def _is_qualifying_pi_coaching(assessment: Mapping[str, Any]) -> bool:
    """Return whether one assessment is active Problem Identification Coaching.

    Q&A, Deep Review, and other specialists never count. Fast Chat Coaching
    rows carry ``response_mode=coaching``. Mock coaching rows may omit that
    field; those still count when they persist a stay/advance recommendation
    and are not Q&A or review.

    Args:
        assessment: Persisted assessment mapping from an active assistant turn.

    Returns:
        True when the row is a qualifying Problem Identification Coaching
        assessment.
    """
    mode = str(assessment.get("response_mode") or "").strip().lower()
    if mode == "qa":
        return False
    if _is_deep_review_assessment(assessment):
        return False
    stage = str(assessment.get("current_stage") or "").strip()
    if stage != HMW_SCAFFOLD_STAGE_ID:
        return False
    if mode == "coaching":
        return True
    if mode:
        return False
    recommendation = str(assessment.get("recommendation") or "").strip().lower()
    return recommendation in {"stay", "advance"}


def _hmw_ready(assessment: Mapping[str, Any]) -> bool:
    """Return whether one persisted assessment recorded HMW readiness.

    Missing, null, and malformed values fail closed to false so historical
    notebooks remain valid.

    Args:
        assessment: Persisted assessment mapping.

    Returns:
        True only when the stored value is JSON/Python true.
    """
    return assessment.get("hmw_scaffold_ready") is True


def _recommendation_stay(assessment: Mapping[str, Any]) -> bool:
    """Return whether one persisted assessment recommended stay."""
    return str(assessment.get("recommendation") or "").strip().lower() == "stay"


def _scaffold_is_useful(assessment: Mapping[str, Any]) -> bool:
    """Return whether one assessment says the construction scaffold is useful.

    ``hmw_scaffold_ready`` means the card is pedagogically useful now. A valid
    student HMW uses ``ready=false`` with ``recommendation=advance``, so the
    scaffold must hide. The application-owned ``hmw_scaffold_guarded`` marker
    is the exception for a current server-rejected PI ADVANCE: it keeps the
    active branch's scaffold visible without changing the assessment's model
    readiness or completion candidate.

    Args:
        assessment: Persisted Problem Identification Coaching assessment.

    Returns:
        True when the assessment is a PI STAY with model readiness or an
        application-owned rejected-advance scaffold marker.
    """
    return _recommendation_stay(assessment) and (
        _hmw_ready(assessment)
        or assessment.get("hmw_scaffold_guarded") is True
    )


def student_hmw_candidate_present(text: str | None) -> bool:
    """Return whether active user text looks like a student-authored HMW attempt.

    This is a deterministic provenance/structure check, not a semantic quality
    judge. Haiku still decides whether an attempt is a valid working HMW.
    Meta-questions, lecture commentary, and empty "How might we?" fragments
    are not candidates.

    Args:
        text: The current active student contribution for this Coaching turn.

    Returns:
        True when the text contains a substantive ``how might we`` framing
        attempt.
    """
    cleaned = " ".join(str(text or "").split()).strip()
    if not cleaned:
        return False
    lower = cleaned.lower()
    if _HMW_MARKER not in lower:
        return False
    if _HMW_META_RE.search(lower):
        return False
    if _HMW_CONSTRUCTION_META_RE.search(lower):
        return False
    if _HMW_LEADING_META_RE.match(lower):
        return False
    after = cleaned[lower.find(_HMW_MARKER) + len(_HMW_MARKER) :].strip(" :,-")
    words = [token for token in re.split(r"\W+", after) if token]
    return len(words) >= _MIN_HMW_CONTENT_WORDS


def student_workable_hmw_present(text: str | None) -> bool:
    """Return whether active user text is a structural How Might We completion.

    This is a lenient application-owned check for Problem Identification
    advancement. It reuses the student-authored candidate guard and additionally
    requires the preferred ``for`` and ``so that`` clauses after the How Might
    We marker. It does not judge evidence, root cause, or wording quality.

    Args:
        text: The current active student contribution for this Coaching turn.

    Returns:
        True when the text is a candidate HMW with both structural clauses.
    """
    if not student_hmw_candidate_present(text):
        return False
    lower = " ".join(str(text or "").split()).lower()
    marker_index = lower.find(_HMW_MARKER)
    if marker_index < 0:
        return False
    after = lower[marker_index + len(_HMW_MARKER) :]
    return re.search(r"\bfor\b", after) is not None and re.search(
        r"\bso that\b", after
    ) is not None


def qualifying_pi_coaching_assessments(
    active_messages: Sequence[Mapping[str, Any]] | None,
) -> list[Mapping[str, Any]]:
    """Return active Problem Identification Coaching assessments.

    Args:
        active_messages: Active-branch messages from ``get_messages``.
            Superseded rows must already be excluded.

    Returns:
        Qualifying Coaching assessments in conversation order.
    """
    found: list[Mapping[str, Any]] = []
    for message in active_messages or ():
        mapping = _as_mapping(message)
        if mapping is None:
            continue
        assessment = _assistant_assessment(mapping)
        if assessment is None:
            continue
        if _is_qualifying_pi_coaching(assessment):
            found.append(assessment)
    return found


def _is_empty_assistant(message: Mapping[str, Any]) -> bool:
    """Return whether an assistant row has no visible transcript content."""
    return (
        str(message.get("role") or "").strip().lower() == "assistant"
        and not str(message.get("content") or "").strip()
    )


def hmw_scaffold_anchor_message(
    active_messages: Sequence[Mapping[str, Any]] | None,
) -> Mapping[str, Any] | None:
    """Return the visible Coaching row after which the HMW card should render.

    The card belongs to the first qualifying Problem Identification Coaching
    response at which the scaffold became useful (``hmw_scaffold_ready=true``
    with ``recommendation=stay``). Later stay/ready turns do not move the
    anchor. Q&A, Deep Review, and welcome rows are never anchors. Callers
    still hide the card when ``hmw_scaffold_available`` is false, including
    after a later valid HMW ADVANCE.

    If usefulness trips on a skipped empty assistant, fall back to the latest
    visible qualifying Coaching row.

    Args:
        active_messages: Active-branch messages from ``get_messages``.

    Returns:
        The visible assistant message to follow with the scaffold, or
        ``None`` when no visible Coaching anchor exists.
    """
    unlock: Mapping[str, Any] | None = None
    last_visible_qualifying: Mapping[str, Any] | None = None
    for message in active_messages or ():
        mapping = _as_mapping(message)
        if mapping is None:
            continue
        assessment = _assistant_assessment(mapping)
        if assessment is None or not _is_qualifying_pi_coaching(assessment):
            continue
        visible = not _is_empty_assistant(mapping)
        if visible:
            last_visible_qualifying = mapping
        if unlock is not None:
            continue
        if not _scaffold_is_useful(assessment):
            continue
        unlock = mapping if visible else last_visible_qualifying
    return unlock


def hmw_scaffold_available(
    current_stage: str | None,
    active_messages: Sequence[Mapping[str, Any]] | None,
    *,
    enabled: bool = True,
) -> bool:
    """Return whether the How Might We scaffold may be shown.

    Eligibility is server-derived from the latest meaningful HMW state:

    1. The HMW feature is enabled.
    2. The authoritative stage is Problem Identification.
    3. The latest active qualifying PI Coaching assessment has
       ``hmw_scaffold_ready=true`` and ``recommendation=stay``.

    There is no minimum Coaching-turn count. A later valid HMW with
    ``ready=false`` and ``recommendation=advance`` hides the card. Q&A and
    Deep Review never govern visibility. Leaving the stage hides it because
    the stage check fails.

    Args:
        current_stage: Authoritative Thinking Path stage id.
        active_messages: Active-branch persisted messages.
        enabled: Feature flag; false hides the scaffold.

    Returns:
        True when the UI may render the scaffold.
    """
    if not enabled:
        return False
    stage = str(current_stage or DEFAULT_STAGE).strip()
    if stage != HMW_SCAFFOLD_STAGE_ID:
        return False
    coaching = qualifying_pi_coaching_assessments(active_messages)
    if not coaching:
        return False
    return _scaffold_is_useful(coaching[-1])


def hmw_scaffold_projection(
    current_stage: str | None,
    active_messages: Sequence[Mapping[str, Any]] | None,
    *,
    enabled: bool = True,
) -> dict[str, bool]:
    """Return the read-only UI contract for HMW scaffold visibility.

    Args:
        current_stage: Authoritative Thinking Path stage id.
        active_messages: Active-branch persisted messages.
        enabled: Feature flag; false hides the scaffold.

    Returns:
        ``{"available": bool}`` with no internal model rationale.
    """
    return {
        "available": hmw_scaffold_available(
            current_stage,
            active_messages,
            enabled=enabled,
        )
    }
