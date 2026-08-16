"""Server-owned specialist routing for Q&A, Coaching, and Formative Review.

The browser cannot pick a privileged specialist. FastAPI overwrites any client
``specialist`` hint. Ambiguous messages default to coaching.
"""

from __future__ import annotations

from .review_orchestration import (
    COUNTER_SETTINGS_KEY,
    DEFAULT_DEEP_REVIEW_INTERVAL_TURNS,
    bound_deep_review_interval,
    next_persisted_counter,
    parse_coaching_turns_since_deep_review,
    resolve_deep_review_trigger,
    should_run_deep_review,
)
from .routing import (
    ALLOWED_SPECIALISTS,
    SPECIALIST_COACHING,
    SPECIALIST_QA,
    SPECIALIST_REVIEW,
    apply_semantic_route,
    looks_like_course_question,
    looks_like_review_request,
    select_specialist,
)

__all__ = [
    "ALLOWED_SPECIALISTS",
    "COUNTER_SETTINGS_KEY",
    "DEFAULT_DEEP_REVIEW_INTERVAL_TURNS",
    "SPECIALIST_COACHING",
    "SPECIALIST_QA",
    "SPECIALIST_REVIEW",
    "apply_semantic_route",
    "bound_deep_review_interval",
    "looks_like_course_question",
    "looks_like_review_request",
    "next_persisted_counter",
    "parse_coaching_turns_since_deep_review",
    "resolve_deep_review_trigger",
    "select_specialist",
    "should_run_deep_review",
]
