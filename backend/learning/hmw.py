"""Server-owned How Might We scaffold eligibility for Problem Identification.

Visibility is projected from the persisted Thinking Path stage plus active
validated Coaching assessments. The model may set ``hmw_scaffold_ready``;
FastAPI decides whether the UI may show the scaffold. This module never
calls a model and never mutates stage.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from backend.learning.stages import DEFAULT_STAGE


HMW_SCAFFOLD_STAGE_ID = "problem_identification"
HMW_SCAFFOLD_MINIMUM_COACHING_TURNS = 2
COACH_WELCOME_KIND = "coach_welcome"


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


def hmw_scaffold_available(
    current_stage: str | None,
    active_messages: Sequence[Mapping[str, Any]] | None,
    *,
    enabled: bool = True,
    minimum: int = HMW_SCAFFOLD_MINIMUM_COACHING_TURNS,
) -> bool:
    """Return whether the How Might We scaffold may be shown.

    Eligibility is server-derived:

    1. The HMW feature is enabled.
    2. The authoritative stage is Problem Identification.
    3. At least ``minimum`` active qualifying Coaching assessments exist
       for that stage (a guardrail against showing the card immediately).
    4. Any of those assessments recorded ``hmw_scaffold_ready=true``.

    Turn count alone never unlocks the scaffold. A later Coaching
    assessment that returns false does not hide an already-unlocked card
    while the notebook remains in Problem Identification. Leaving the
    stage hides it because the stage check fails.

    Args:
        current_stage: Authoritative Thinking Path stage id.
        active_messages: Active-branch persisted messages.
        enabled: Feature flag; false hides the scaffold.
        minimum: Qualifying Coaching-exchange guardrail. Defaults to 2.

    Returns:
        True when the UI may render the scaffold.
    """
    if not enabled:
        return False
    stage = str(current_stage or DEFAULT_STAGE).strip()
    if stage != HMW_SCAFFOLD_STAGE_ID:
        return False
    required = max(1, int(minimum))
    coaching = qualifying_pi_coaching_assessments(active_messages)
    if len(coaching) < required:
        return False
    return any(_hmw_ready(item) for item in coaching)


def hmw_scaffold_projection(
    current_stage: str | None,
    active_messages: Sequence[Mapping[str, Any]] | None,
    *,
    enabled: bool = True,
    minimum: int = HMW_SCAFFOLD_MINIMUM_COACHING_TURNS,
) -> dict[str, bool]:
    """Return the read-only UI contract for HMW scaffold visibility.

    Args:
        current_stage: Authoritative Thinking Path stage id.
        active_messages: Active-branch persisted messages.
        enabled: Feature flag; false hides the scaffold.
        minimum: Qualifying Coaching-exchange guardrail.

    Returns:
        ``{"available": bool}`` with no internal model rationale.
    """
    return {
        "available": hmw_scaffold_available(
            current_stage,
            active_messages,
            enabled=enabled,
            minimum=minimum,
        )
    }
