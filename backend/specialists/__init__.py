"""Server-owned specialist routing for Q&A, Coaching, and Formative Review.

The browser cannot pick a privileged specialist. FastAPI overwrites any client
``specialist`` hint. Ambiguous messages default to coaching.
"""

from __future__ import annotations

from .routing import (
    ALLOWED_SPECIALISTS,
    SPECIALIST_COACHING,
    SPECIALIST_QA,
    SPECIALIST_REVIEW,
    looks_like_course_question,
    looks_like_review_request,
    select_specialist,
)

__all__ = [
    "ALLOWED_SPECIALISTS",
    "SPECIALIST_COACHING",
    "SPECIALIST_QA",
    "SPECIALIST_REVIEW",
    "looks_like_course_question",
    "looks_like_review_request",
    "select_specialist",
]
