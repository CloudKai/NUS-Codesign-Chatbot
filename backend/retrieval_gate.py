"""Deterministic retrieval gate for latency-sensitive normal chat.

FastAPI decides whether selected-source / course Knowledge Base retrieval is
required BEFORE AgentCore. This module never calls a model. Security and
ownership checks remain in the retriever after this gate returns true.

Retrieval policy
================
There is no LLM router. False negatives (skipping Retrieve for a course or
source question) are worse than false positives (a bounded Retrieve that
returns nothing). A wasted Retrieve costs latency, not correctness, so a
project question that mentions a lecture, week, or source still retrieves.

Do not retrieve when the turn is clearly personal/project reasoning or
brainstorming with no factual grounding need. Idle acknowledgements also
skip. The gate must not degenerate into "always retrieve"; that would attach
Retrieve to every reflective coaching turn.

``looks_like_course_question`` in ``backend.specialists.routing`` stays
conservative because ``select_specialist`` uses it for mock/offline qa
routing. Broader recall lives only here.

Graded signal
=============
:func:`classify_retrieval_intent` returns :class:`RetrievalClassification`
with ``intent``:

- ``high_confidence_source`` — retrieve; later Q&A mode hints may use this
- ``high_confidence_personal`` — skip; later coaching mode hints may use this
- ``ambiguous`` — weak or mixed signal. ``retrieve`` is true only for a
  selected-source factual question that is not clearly personal. Idle text
  is ambiguous with ``retrieve`` false so a later hint can stay silent.

:func:`retrieval_required` keeps its existing signature and returns
``classification.retrieve``.
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Literal

from backend.specialists.routing import looks_like_course_question

RetrievalIntent = Literal[
    "high_confidence_source",
    "high_confidence_personal",
    "ambiguous",
]

INTENT_HIGH_CONFIDENCE_SOURCE: RetrievalIntent = "high_confidence_source"
INTENT_HIGH_CONFIDENCE_PERSONAL: RetrievalIntent = "high_confidence_personal"
INTENT_AMBIGUOUS: RetrievalIntent = "ambiguous"

# Week/lecture/reading plus a number or ordinal. "weekend" / "weekly" do not
# match because the token after week is not a session index.
_WEEK_OR_SESSION = re.compile(
    r"\b(?:week|weeks|lec|lecture|lectures|reading|readings)\s*#?\s*"
    r"(?:[1-9]\d?|one|two|three|four|five|six|seven|eight|nine|ten|"
    r"eleven|twelve)\b",
    re.IGNORECASE,
)

# Bare S1/S2 labels. Word-shaped so "as1", "ps1", "s1mple", and "US1" miss.
# S0 and S00 are rejected. Trailing alphanumerics block S100 and s1e.
_BARE_SOURCE_LABEL = re.compile(
    r"(?<![A-Za-z0-9])S(?:[1-9]|[1-9]\d)(?![A-Za-z0-9])",
    re.IGNORECASE,
)

_BRACKET_SOURCE_LABEL = re.compile(r"\[s\d+\]", re.IGNORECASE)

# "the course" / "this course", not "of course" or "course of action".
_COURSE_GROUNDING = re.compile(
    r"\b(?:the|this|our)\s+course\b"
    r"|\bcourse\s+(?:material|materials|pack|reading|readings|lecture|"
    r"lectures|notes|content|said|says|say|mention|mentions|cover|"
    r"covers|about)\b"
    r"|\b(?:in|from|about|according\s+to)\s+(?:the\s+)?course\b",
    re.IGNORECASE,
)

_SOURCE_CUES: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("week_or_session", _WEEK_OR_SESSION),
    ("bare_source_label", _BARE_SOURCE_LABEL),
    ("bracket_source_label", _BRACKET_SOURCE_LABEL),
    ("course_grounding", _COURSE_GROUNDING),
    (
        "material_noun",
        re.compile(
            r"\b(lecture|lectures|reading|readings|syllabus|pdf|handout|"
            r"slides?|handouts)\b",
            re.IGNORECASE,
        ),
    ),
    (
        "according_to_source",
        re.compile(
            r"\baccording to (the )?(lecture|reading|source|pdf|file|report|"
            r"notes|uploaded|brief|assignment|slides?|syllabus|week|document|"
            r"handout|excerpt|course)\b",
            re.IGNORECASE,
        ),
    ),
    (
        "what_source_says",
        re.compile(
            r"\bwhat (does|did|do) (the |this |my |those |these )?"
            r"(lecture|reading|source|sources|pdf|file|report|uploaded|brief|"
            r"week|notes|slides?|document|handout|excerpt|syllabus|course)\b",
            re.IGNORECASE,
        ),
    ),
    (
        "citation_request",
        re.compile(r"\b(cite|citation|citations)\b", re.IGNORECASE),
    ),
    (
        "evidence_request",
        re.compile(
            r"\b(give me|show|provide|use|need) (me )?(the )?(evidence|source|"
            r"sources|excerpt)\b",
            re.IGNORECASE,
        ),
    ),
    (
        "based_on_source",
        re.compile(
            r"\b(based on|from) (the )?(pdf|lecture|reading|source|uploaded|"
            r"file|report|notes|slides?|document|syllabus|handout)\b",
            re.IGNORECASE,
        ),
    ),
    (
        "compare_to_source",
        re.compile(
            r"\bcompare .{0,80}\b(lecture|reading|source|pdf|notes|slides?)\b",
            re.IGNORECASE,
        ),
    ),
    (
        "uploaded_document",
        re.compile(
            r"\b(uploaded (file|report|pdf|source|document|slides?|notes)|"
            r"my uploaded|attached (file|pdf|document|source))\b",
            re.IGNORECASE,
        ),
    ),
    (
        "selected_source_phrase",
        re.compile(
            r"\b(selected (lecture|reading|source|pdf|file)|this source|"
            r"the source|those sources)\b",
            re.IGNORECASE,
        ),
    ),
    ("evidence_word", re.compile(r"\bevidence\b", re.IGNORECASE)),
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
    r"\?|^\s*who\b|\b(what|why|how|when|where|which|explain|describe|according|"
    r"summar(?:y|ise|ize)|tell me)\b",
    re.IGNORECASE,
)

# A course-concept question carries no lecture/week/S# cue but is still a
# request for course knowledge rather than project reasoning ("what is the
# definition of a job story"). Only impersonal phrasings qualify, so
# "what assumption am I making here" stays project reasoning.
_DEFINITIONAL_MARKERS = (
    re.compile(r"\bdefinition of\b", re.IGNORECASE),
    re.compile(r"\bwhat (do|does) .{2,60} mean\b", re.IGNORECASE),
    re.compile(r"^\s*(define|explain|describe)\b", re.IGNORECASE),
    re.compile(r"\bdifference between\b", re.IGNORECASE),
)
# "what is a/the X" only counts as definitional once the noun phrase is
# substantial, so terse process questions ("what is the point") stay with
# the coach instead of becoming an evidence lookup.
_GENERIC_DEFINITIONAL_MARKER = re.compile(
    r"\bwhat (is|are)\s+(a|an|the)\b", re.IGNORECASE
)
_FIRST_OR_SECOND_PERSON = re.compile(
    r"\b(i|me|my|mine|we|us|our|ours|you|your|yours|let'?s)\b",
    re.IGNORECASE,
)
_MIN_DEFINITIONAL_WORDS = 5

_TITLE_TOKEN = re.compile(r"[a-z0-9][a-z0-9._-]{3,}", re.IGNORECASE)


@dataclass(frozen=True)
class RetrievalClassification:
    """Graded retrieval decision for one student turn.

    Attributes:
        intent: ``high_confidence_source``, ``high_confidence_personal``,
            or ``ambiguous``. Stable strings for a later Q&A/coaching hint.
        retrieve: Whether FastAPI should retrieve selected evidence.
        cues: Privacy-safe matcher names that fired. Never student text.
    """

    intent: RetrievalIntent
    retrieve: bool
    cues: tuple[str, ...] = ()


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
            for part in re.split(r"[-_.]+", token):
                if len(part) < 4 or part in seen:
                    continue
                seen.add(part)
                markers.append(part)
    return tuple(markers)


def _source_cues(
    text: str,
    *,
    selected_source_titles: Iterable[str],
    selected_source_filenames: Iterable[str],
) -> tuple[str, ...]:
    """Return privacy-safe names of source/course cues that matched."""
    found: list[str] = []
    if looks_like_course_question(text):
        found.append("conservative_course_question")
    for name, pattern in _SOURCE_CUES:
        if pattern.search(text):
            found.append(name)
    lowered = text.casefold()
    titles = tuple(selected_source_titles)
    filenames = tuple(selected_source_filenames)
    if any(marker in lowered for marker in _title_markers((*titles, *filenames))):
        found.append("selected_source_title")
    return tuple(found)


def _is_personal_reasoning(text: str) -> bool:
    """Return whether the turn is clearly the student's own project reasoning."""
    return any(pattern.search(text) for pattern in _PROJECT_REASONING)


def _is_definitional_question(text: str) -> bool:
    """Return whether the turn is an impersonal course-concept question.

    Args:
        text: Normalised student contribution.

    Returns:
        True for phrasings such as "what is the definition of a job story"
        that ask for course knowledge without naming a lecture, week, or
        source label. Any first- or second-person pronoun disqualifies the
        turn so project reflection is never misread as a factual lookup.
    """
    if _FIRST_OR_SECOND_PERSON.search(text):
        return False
    if any(pattern.search(text) for pattern in _DEFINITIONAL_MARKERS):
        return True
    if len(text.split()) < _MIN_DEFINITIONAL_WORDS:
        return False
    return bool(_GENERIC_DEFINITIONAL_MARKER.search(text))


def classify_retrieval_intent(
    student_message: str,
    *,
    selected_source_titles: Iterable[str] = (),
    selected_source_filenames: Iterable[str] = (),
    has_selected_sources: bool | None = None,
) -> RetrievalClassification:
    """Classify whether this student turn needs selected-source retrieval.

    Args:
        student_message: Current student contribution. Not logged by callers.
        selected_source_titles: Authoritative selected source titles.
        selected_source_filenames: Authoritative selected source filenames.
        has_selected_sources: When True, factual questions about selected
            material also retrieve. Inferred from titles/filenames when omitted.

    Returns:
        A :class:`RetrievalClassification`. Strong source/course cues win
        over personal-reasoning cues. Project-only turns skip retrieval.
    """
    text = _normalized_text(student_message)
    titles = tuple(selected_source_titles)
    filenames = tuple(selected_source_filenames)
    if not text:
        return RetrievalClassification(
            intent=INTENT_AMBIGUOUS, retrieve=False, cues=()
        )
    cues = _source_cues(
        text,
        selected_source_titles=titles,
        selected_source_filenames=filenames,
    )
    if cues:
        return RetrievalClassification(
            intent=INTENT_HIGH_CONFIDENCE_SOURCE,
            retrieve=True,
            cues=cues,
        )
    if _is_definitional_question(text):
        return RetrievalClassification(
            intent=INTENT_HIGH_CONFIDENCE_SOURCE,
            retrieve=True,
            cues=("definitional_question",),
        )
    if _is_personal_reasoning(text):
        return RetrievalClassification(
            intent=INTENT_HIGH_CONFIDENCE_PERSONAL,
            retrieve=False,
            cues=("personal_reasoning",),
        )
    selected = bool(has_selected_sources)
    if has_selected_sources is None:
        selected = any(_normalized_text(value) for value in (*titles, *filenames))
    if selected and _QUESTION_SHAPE.search(text):
        return RetrievalClassification(
            intent=INTENT_AMBIGUOUS,
            retrieve=True,
            cues=("selected_source_question",),
        )
    return RetrievalClassification(
        intent=INTENT_AMBIGUOUS, retrieve=False, cues=()
    )


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
    return classify_retrieval_intent(
        student_message,
        selected_source_titles=selected_source_titles,
        selected_source_filenames=selected_source_filenames,
        has_selected_sources=has_selected_sources,
    ).retrieve
