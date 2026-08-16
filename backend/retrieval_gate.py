"""Deterministic retrieval gate for latency-sensitive normal chat.

FastAPI decides whether selected-source / course Knowledge Base retrieval is
required BEFORE AgentCore. This module never calls a model. Security and
ownership checks remain in the retriever after this gate returns true.
"""

from __future__ import annotations

import re
from collections.abc import Iterable

from backend.specialists.routing import looks_like_course_question

# Compact intent signals. Tests cover capitalization, punctuation, and
# selected-source titles rather than an exhaustive phrase list.
_SOURCE_INTENT = (
    re.compile(
        r"\b(lecture|lectures|reading|readings|syllabus|pdf|handout|slides?)\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"\baccording to (the )?(lecture|reading|source|pdf|file|report|notes|"
        r"uploaded|brief|assignment)\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"\bwhat does (the |this |my )?(lecture|reading|source|pdf|file|report|"
        r"uploaded|brief|week)\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(cite|citation|citations)\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(give me|show|provide|use|need) (me )?(the )?(evidence|source|"
        r"sources|excerpt)\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(based on|from) (the )?(pdf|lecture|reading|source|uploaded|file|"
        r"report|notes)\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"\bcompare .{0,80}\b(lecture|reading|source|pdf)\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(uploaded (file|report|pdf|source)|my uploaded)\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"\bselected (lecture|reading|source|pdf|file)\b",
        re.IGNORECASE,
    ),
    re.compile(r"\[s\d+\]", re.IGNORECASE),
    re.compile(r"\bevidence\b", re.IGNORECASE),
)

_PROJECT_REASONING = (
    re.compile(
        r"^\s*i (think|thought|want|changed|chose|decided|will|am)\b",
        re.IGNORECASE,
    ),
    re.compile(r"\bmy (users?|idea|design|concept|stakeholders?)\b", re.IGNORECASE),
    re.compile(r"\bwould this (idea|design|concept|option)\b", re.IGNORECASE),
    re.compile(
        r"\b(does|would) this (idea|design|concept|option) solve\b",
        re.IGNORECASE,
    ),
)
_QUESTION_SHAPE = re.compile(
    r"\?|\b(what|why|how|when|where|which|who|explain|describe|according)\b",
    re.IGNORECASE,
)

_TITLE_TOKEN = re.compile(r"[a-z0-9][a-z0-9._-]{3,}", re.IGNORECASE)


def _normalized_text(value: str) -> str:
    """Return compact lowercase text for intent matching."""
    return " ".join(str(value or "").split()).strip()


def _title_markers(values: Iterable[str]) -> tuple[str, ...]:
    """Return distinctive title/filename tokens that can trigger retrieval."""
    markers: list[str] = []
    seen: set[str] = set()
    for raw in values:
        text = _normalized_text(raw)
        if not text:
            continue
        lowered = text.casefold()
        if len(lowered) >= 4 and lowered not in seen:
            seen.add(lowered)
            markers.append(lowered)
        for match in _TITLE_TOKEN.findall(text):
            token = match.casefold()
            if token in seen or len(token) < 4:
                continue
            if token in {"lecture", "reading", "notes", "week", "file", "pdf"}:
                continue
            seen.add(token)
            markers.append(token)
    return tuple(markers)


def retrieval_required(
    student_message: str,
    *,
    selected_source_titles: Iterable[str] = (),
    selected_source_filenames: Iterable[str] = (),
    has_selected_sources: bool | None = None,
) -> bool:
    """Return whether this student turn should retrieve selected evidence.

    Args:
        student_message: Current student contribution. Not logged by callers.
        selected_source_titles: Authoritative selected source titles.
        selected_source_filenames: Authoritative selected source filenames.
        has_selected_sources: When True, factual questions about selected
            material also retrieve. Inferred from titles/filenames when omitted.

    Returns:
        True when the message has strong source/course-evidence intent, names
        a selected source, or (with selected sources) asks a non-project
        question that needs grounding. Project-reasoning turns return False.
    """
    text = _normalized_text(student_message)
    if not text:
        return False
    if looks_like_course_question(text):
        return True
    if any(pattern.search(text) for pattern in _SOURCE_INTENT):
        return True
    titles = tuple(selected_source_titles)
    filenames = tuple(selected_source_filenames)
    lowered = text.casefold()
    for marker in _title_markers((*titles, *filenames)):
        if marker in lowered:
            return True
    selected = bool(has_selected_sources)
    if has_selected_sources is None:
        selected = any(_normalized_text(value) for value in (*titles, *filenames))
    if (
        selected
        and _QUESTION_SHAPE.search(text)
        and not any(pattern.search(text) for pattern in _PROJECT_REASONING)
    ):
        return True
    return False
