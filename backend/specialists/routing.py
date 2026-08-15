"""Deterministic specialist selection. There is no LLM router.

Course-information questions may route to Q&A. Explicit formative-review
requests may route to Review. Everything else, including ambiguous messages,
routes to Coaching. Client-supplied specialist names are ignored unless the
application service already validated them.
"""

from __future__ import annotations

import re

SPECIALIST_QA = "qa"
SPECIALIST_COACHING = "coaching"
SPECIALIST_REVIEW = "review"
ALLOWED_SPECIALISTS = frozenset(
    {SPECIALIST_QA, SPECIALIST_COACHING, SPECIALIST_REVIEW}
)

_QA_PATTERNS = (
    re.compile(r"\bwhat is week\s*\d+\b", re.IGNORECASE),
    re.compile(r"\bwhat (is|are) week\s*\d+\s+about\b", re.IGNORECASE),
    re.compile(
        r"\bwhat does (the )?(week|reading|lecture|assignment|brief|syllabus|jtbd)\b",
        re.IGNORECASE,
    ),
    re.compile(r"\bwhen is (the )?(assignment|deadline|due date|due)\b", re.IGNORECASE),
    re.compile(r"\bwhat does reading\s*\d+\b", re.IGNORECASE),
    re.compile(r"\bassignment (brief|due|deadline|require)", re.IGNORECASE),
    re.compile(r"\bsyllabus\b", re.IGNORECASE),
)

_REVIEW_PATTERNS = (
    re.compile(
        r"\breview (my|our) (progress|work|reasoning|thinking|journey)\b",
        re.IGNORECASE,
    ),
    re.compile(r"\bformative review\b", re.IGNORECASE),
    re.compile(r"\bhow (am i|are we) doing so far\b", re.IGNORECASE),
)


def looks_like_course_question(student_message: str) -> bool:
    """Return whether the message is a conservative course-information question.

    Args:
        student_message: The current student contribution.

    Returns:
        True only for clearly course-catalog questions such as week or reading
        lookups. Project reasoning never matches.
    """
    text = " ".join(str(student_message or "").lower().split())
    if not text:
        return False
    return any(pattern.search(text) for pattern in _QA_PATTERNS)


def looks_like_review_request(student_message: str) -> bool:
    """Return whether the message explicitly asks for formative review.

    Args:
        student_message: The current student contribution.

    Returns:
        True only for explicit progress-review requests.
    """
    text = " ".join(str(student_message or "").lower().split())
    if not text:
        return False
    return any(pattern.search(text) for pattern in _REVIEW_PATTERNS)


def select_specialist(
    student_message: str,
    *,
    requested: str | None = None,
    surface: str | None = None,
) -> str:
    """Choose ``qa``, ``coaching``, or ``review`` for one student turn.

    Args:
        student_message: Untrusted student text used only for conservative
            course-Q&A and review-intent detection.
        requested: Optional already-validated specialist from application
            code. HTTP handlers must pass ``None`` so the browser cannot
            select a privileged specialist.
        surface: Optional server-owned UI surface such as ``review``.

    Returns:
        A member of ``ALLOWED_SPECIALISTS``. Ambiguous messages return
        ``coaching``.
    """
    cleaned_requested = str(requested or "").strip().lower()
    if cleaned_requested in ALLOWED_SPECIALISTS:
        return cleaned_requested
    if str(surface or "").strip().lower() == SPECIALIST_REVIEW:
        return SPECIALIST_REVIEW
    if looks_like_course_question(student_message):
        return SPECIALIST_QA
    if looks_like_review_request(student_message):
        return SPECIALIST_REVIEW
    return SPECIALIST_COACHING
