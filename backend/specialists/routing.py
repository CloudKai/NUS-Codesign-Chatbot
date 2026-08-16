"""Server-owned specialist selection.

Production AgentCore uses a Claude Haiku 4.5 semantic router for free-text turns.
This module still owns:

1. Explicit validated server-owned specialist/surface (never from the browser)
2. Deterministic mock/offline fallback (conservative regex)
3. Fail-closed coaching when a semantic route is missing or low-confidence

Client-supplied specialist names are ignored unless application code already
validated them. The router never decides stage advancement, source ownership,
or database changes.
"""

from __future__ import annotations

import re

SPECIALIST_QA = "qa"
SPECIALIST_COACHING = "coaching"
SPECIALIST_REVIEW = "review"
ALLOWED_SPECIALISTS = frozenset(
    {SPECIALIST_QA, SPECIALIST_COACHING, SPECIALIST_REVIEW}
)
DEFAULT_ROUTER_MIN_CONFIDENCE = 0.60

_QA_PATTERNS = (
    re.compile(r"\bwhat is week\s*\d+\b", re.IGNORECASE),
    re.compile(r"\bwhat (is|are) (the )?week\s*\d+\b", re.IGNORECASE),
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


def bound_router_min_confidence(value: float | None) -> float:
    """Clamp a router confidence threshold to ``[0.0, 1.0]``.

    Args:
        value: Configured minimum confidence.

    Returns:
        A finite threshold in range. Invalid values become ``0.60``.
    """
    try:
        score = float(value)
    except (TypeError, ValueError):
        return DEFAULT_ROUTER_MIN_CONFIDENCE
    if score != score:  # NaN
        return DEFAULT_ROUTER_MIN_CONFIDENCE
    return min(1.0, max(0.0, score))


def apply_semantic_route(
    specialist: str | None,
    confidence: float | None,
    *,
    min_confidence: float = DEFAULT_ROUTER_MIN_CONFIDENCE,
) -> str:
    """Map a Haiku router result onto a specialist, or fall closed to coaching.

    Args:
        specialist: Claimed specialist from structured router output.
        confidence: Claimed confidence in ``[0.0, 1.0]``.
        min_confidence: Inclusive threshold; lower values become coaching.

    Returns:
        ``qa``, ``coaching``, or ``review``. Unsupported values, missing
        confidence, or low confidence return ``coaching``.
    """
    cleaned = str(specialist or "").strip().lower()
    if cleaned not in ALLOWED_SPECIALISTS:
        return SPECIALIST_COACHING
    try:
        score = float(confidence)
    except (TypeError, ValueError):
        return SPECIALIST_COACHING
    if score != score or score < 0.0 or score > 1.0:
        return SPECIALIST_COACHING
    if score < bound_router_min_confidence(min_confidence):
        return SPECIALIST_COACHING
    return cleaned


def select_specialist(
    student_message: str,
    *,
    requested: str | None = None,
    surface: str | None = None,
    semantic_specialist: str | None = None,
    semantic_confidence: float | None = None,
    min_confidence: float = DEFAULT_ROUTER_MIN_CONFIDENCE,
    use_semantic: bool = False,
) -> str:
    """Choose ``qa``, ``coaching``, or ``review`` for one student turn.

    Priority:

    1. Explicit validated ``requested`` specialist
    2. Server-owned ``surface`` such as ``review``
    3. Semantic router result when ``use_semantic`` is true
    4. Conservative regex fallback for mock/offline providers
    5. Coaching

    Args:
        student_message: Untrusted student text used only for the mock
            fallback. The production Haiku router reads this separately.
        requested: Optional already-validated specialist from application
            code. HTTP handlers must pass ``None`` so the browser cannot
            select a privileged specialist.
        surface: Optional server-owned UI surface such as ``review``.
        semantic_specialist: Optional Haiku router specialist.
        semantic_confidence: Optional Haiku router confidence.
        min_confidence: Inclusive confidence floor for semantic routes.
        use_semantic: When true, skip regex and use the semantic result
            or coaching.

    Returns:
        A member of ``ALLOWED_SPECIALISTS``. Ambiguous messages return
        ``coaching``.
    """
    cleaned_requested = str(requested or "").strip().lower()
    if cleaned_requested in ALLOWED_SPECIALISTS:
        return cleaned_requested
    if str(surface or "").strip().lower() == SPECIALIST_REVIEW:
        return SPECIALIST_REVIEW
    if use_semantic:
        return apply_semantic_route(
            semantic_specialist,
            semantic_confidence,
            min_confidence=min_confidence,
        )
    if looks_like_course_question(student_message):
        return SPECIALIST_QA
    if looks_like_review_request(student_message):
        return SPECIALIST_REVIEW
    return SPECIALIST_COACHING
