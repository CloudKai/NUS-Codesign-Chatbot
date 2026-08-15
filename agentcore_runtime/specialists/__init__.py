"""Deterministic specialist prompt builders for one AgentCore runtime."""

from __future__ import annotations

from .coaching import coaching_system_prompt
from .qa import qa_system_prompt
from .review import review_system_prompt
from .routing import (
    PHASE_COACHING,
    PHASE_QA,
    PHASE_REVIEW,
    normalize_phase,
)

__all__ = [
    "PHASE_COACHING",
    "PHASE_QA",
    "PHASE_REVIEW",
    "coaching_system_prompt",
    "normalize_phase",
    "qa_system_prompt",
    "review_system_prompt",
]
