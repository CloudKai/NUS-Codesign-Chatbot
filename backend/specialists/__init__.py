"""Server-owned specialist routing for Q&A, Coaching, and Formative Review.

The browser cannot pick a privileged specialist. FastAPI overwrites any client
``specialist`` hint. Ambiguous messages default to coaching.
"""

from __future__ import annotations

from .review_orchestration import (
    COUNTER_SETTINGS_KEY,
    DEEP_REVIEW_JOB_KEY,
    DEEP_REVIEW_SNAPSHOT_KEY,
    DEEP_REVIEW_TURN_MESSAGE,
    DEFAULT_DEEP_REVIEW_INTERVAL_TURNS,
    JOURNEY_STAGE_REVIEWS_KEY,
    STAGE_REVIEW_REASON_COMPLETION,
    STAGE_REVIEW_REASON_REVISIT_EXIT,
    STAGE_REVIEW_SCOPE_VERSION,
    bound_deep_review_interval,
    deep_review_job_is_active,
    deep_review_snapshot_payload,
    explicit_deep_review_available,
    next_persisted_counter,
    parse_coaching_turns_since_deep_review,
    parse_deep_review_job,
    parse_journey_stage_reviews,
    public_journey_stage_reviews,
    stage_review_job_is_stale,
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
    "DEEP_REVIEW_JOB_KEY",
    "DEEP_REVIEW_SNAPSHOT_KEY",
    "DEEP_REVIEW_TURN_MESSAGE",
    "DEFAULT_DEEP_REVIEW_INTERVAL_TURNS",
    "SPECIALIST_COACHING",
    "SPECIALIST_QA",
    "SPECIALIST_REVIEW",
    "apply_semantic_route",
    "bound_deep_review_interval",
    "deep_review_job_is_active",
    "deep_review_snapshot_payload",
    "explicit_deep_review_available",
    "looks_like_course_question",
    "looks_like_review_request",
    "next_persisted_counter",
    "parse_coaching_turns_since_deep_review",
    "parse_deep_review_job",
    "parse_journey_stage_reviews",
    "JOURNEY_STAGE_REVIEWS_KEY",
    "STAGE_REVIEW_REASON_COMPLETION",
    "STAGE_REVIEW_REASON_REVISIT_EXIT",
    "STAGE_REVIEW_SCOPE_VERSION",
    "public_journey_stage_reviews",
    "resolve_deep_review_trigger",
    "select_specialist",
    "stage_review_job_is_stale",
    "should_run_deep_review",
]
