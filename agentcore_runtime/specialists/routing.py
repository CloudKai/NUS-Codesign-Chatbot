"""Deterministic specialist phase selection inside the AgentCore runtime.

Unknown phases fall closed to coaching with no tools. They must never fall
through to Q&A, which historically attached Knowledge Base tools in the POC.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

PHASE_QA = "qa"
PHASE_COACHING = "coaching"
PHASE_REVIEW = "review"
ALLOWED_PHASES = frozenset({PHASE_QA, PHASE_COACHING, PHASE_REVIEW})


def normalize_phase(value: Any) -> str:
    """Return a known specialist phase.

    Args:
        value: Payload ``phase`` or equivalent.

    Returns:
        ``qa``, ``coaching``, or ``review``. ``scoring`` maps to ``review``.
        Any other value becomes ``coaching``.
    """
    cleaned = str(value or "").strip().lower()
    if cleaned == "scoring":
        return PHASE_REVIEW
    if cleaned in ALLOWED_PHASES:
        return cleaned
    return PHASE_COACHING


def payload_phase(payload: Mapping[str, Any] | None) -> str:
    """Return the specialist phase from one invoke payload."""
    if not isinstance(payload, Mapping):
        return PHASE_COACHING
    return normalize_phase(payload.get("phase"))
