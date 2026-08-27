"""Deterministic Thinking Path workflow-intent recognition.

Natural-language understanding is tolerant for **matching only**. This module
never mutates journey state, never authorizes a stage change, and never calls a
model. Authorization stays in ``StudentStore.validate_learning_stage_selection``
/ ``_selected_learning_stage_metadata`` and the Phase 1 readiness path.

Stored student messages are not rewritten; callers pass the raw message and
receive match results derived from a private normalized view.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Literal

from backend.learning.stages import THINKING_STAGES

WorkflowIntentKind = Literal[
    "move_stage",
    "move_next",
    "readiness",
    "status",
    "confirm",
    "none",
]


@dataclass(frozen=True)
class WorkflowIntent:
    """Bounded result of one deterministic workflow parse.

    Attributes:
        kind: Recognized workflow class, or ``none``.
        target_stage_id: Canonical stage id when a named destination resolved.
        confidence: ``high`` only when the match is safe to act on for routing.
    """

    kind: WorkflowIntentKind
    target_stage_id: str | None = None
    confidence: Literal["high", "low"] = "high"


_TRAILING_PUNCT = re.compile(r"[.?!…]+$")
_MULTI_SPACE = re.compile(r"\s+")

# Leading chit-chat stripped only for matching. Do not include "please" — existing
# contracts keep "Please move me to …" from becoming an exact stage command.
_LEADING_PREFIXES = (
    re.compile(r"^(?:hi|hello|hey)[,!]?\s+", re.IGNORECASE),
    re.compile(r"^(?:ok|okay|alright|so)[,!]?\s+", re.IGNORECASE),
    re.compile(r"^(?:thanks|thank you)[,!]?\s+", re.IGNORECASE),
    re.compile(r"^(?:i think|i feel like)\s+", re.IGNORECASE),
)

_TRAILING_FILLER = re.compile(
    r"(?:\s|,)+(?:now|already|anot|lah|please)\s*$",
    re.IGNORECASE,
)

# Definition / course lookup about a stage — never navigation, even with typos.
_STAGE_DEFINITION_OR_COURSE_QA = re.compile(
    r"^\s*(?:"
    r"what\s+is\b|"
    r"what\s+does\b|"
    r"what\s+should\s+i\s+do\b|"
    r"how\s+does\b|"
    r"how\s+do\s+i\b|"
    r"can\s+you\s+explain\b|"
    r"could\s+you\s+explain\b|"
    r"explain\b|"
    r"define\b|"
    r"which\s+(?:lecture|lectures|reading|readings|week|source|sources)\b|"
    r"what\s+does\s+the\s+(?:lecture|reading|course)\b|"
    r"where\s+in\s+the\s+(?:lecture|reading|course)\b"
    r")",
    re.IGNORECASE,
)

_EXACT_MOVE_ME_TO = re.compile(
    r"^move\s+me\s+to\s+(.+)$",
    re.IGNORECASE,
)

# Selection-mode chat CTA: whole-message ``Move to <stage>`` (no ``me``).
# Rejects discussion such as ``Move this idea to concept generation``.
_EXACT_MOVE_TO = re.compile(
    r"^move\s+to\s+(.+)$",
    re.IGNORECASE,
)

# Strong navigation / readiness language. Matched anywhere so a project
# paragraph can end with a move request.
_NAVIGATION_CLAUSE = re.compile(
    r"(?:"
    r"(?:can|could|may|should)\s+(?:we|i)\s+"
    r"(?:move(?:\s+on)?\s+(?:to|into|onto)|go(?:\s+ahead)?\s+to|go\s+onto|"
    r"proceed\s+to|advance\s+to|switch\s+to|start|continue\s+to)\s+"
    r"(?:the\s+)?(?P<target>.+?)"
    r"|"
    r"(?:can|could|may|should)\s+move(?:\s+on)?\s+(?:to|into|onto)\s+"
    r"(?:the\s+)?(?P<target_bare>.+?)"
    r"|"
    r"(?:let'?s)\s+(?:move(?:\s+on)?\s+(?:to|into)|go\s+to|proceed\s+to|"
    r"advance\s+to|start)\s+(?:the\s+)?(?P<target_lets>.+?)"
    r"|"
    r"(?:i(?:'m| am)\s+ready\s+to)\s+(?:move(?:\s+on)?\s+(?:to|into)|go\s+to|"
    r"proceed\s+to|advance\s+to|start)\s+(?:the\s+)?(?P<target_ready>.+?)"
    r")$",
    re.IGNORECASE,
)

_MOVE_NEXT = re.compile(
    r"(?:"
    r"(?:can|could|may|should)\s+(?:we|i)\s+move\s+on(?:\s+already)?"
    r"|"
    r"(?:can|could|may|should)\s+move\s+on(?:\s+already)?"
    r"|"
    r"(?:can|could|may|should)\s+(?:we|i)\s+"
    r"(?:proceed|advance|continue|go\s+ahead)\s+to\s+(?:the\s+)?"
    r"(?:next\s+)?(?:stage|phase)"
    r"|"
    r"(?:let'?s|i(?:'m| am)\s+ready\s+to)\s+"
    r"(?:move\s+on|proceed|advance)"
    r"(?:\s+to\s+(?:the\s+)?(?:next\s+)?(?:stage|phase))?"
    r")$",
    re.IGNORECASE,
)

_READINESS = re.compile(
    r"(?:"
    r"(?:am|are)\s+(?:i|we)\s+(?:ready|good)\s+to\s+"
    r"(?:move\s+on|proceed|advance|move\s+forward)"
    r"|"
    r"(?:is|am)\s+(?:this|it)\s+enough\s+"
    r"(?:to\s+(?:move\s+on|proceed|advance)|for\s+(?:the\s+)?(?:next\s+)?"
    r"(?:stage|phase))"
    r"|"
    r"(?:i\s+think\s+)?(?:i(?:'m| am)\s+)?done\s+here"
    r"|"
    r"(?:i\s+think\s+)?(?:this\s+is\s+)?enough(?:\s*,?\s*can\s+(?:i|we)\s+"
    r"(?:move\s+on|proceed|advance))?"
    r")$",
    re.IGNORECASE,
)

_EMBEDDED_READINESS_OR_NEXT = re.compile(
    r"\b(?:"
    r"(?:am|are)\s+(?:i|we)\s+(?:ready|good)\s+to\s+"
    r"(?:move\s+on|proceed|advance|move\s+forward)"
    r"|"
    r"(?:is|am)\s+(?:this|it)\s+enough\s+"
    r"(?:to\s+(?:move\s+on|proceed|advance)|for\s+(?:the\s+)?(?:next\s+)?"
    r"(?:stage|phase))"
    r"|"
    r"(?:can|could|may|should)\s+(?:we|i)\s+move\s+on(?:\s+already)?"
    r"|"
    r"(?:can|could|may|should)\s+move\s+on(?:\s+already)?"
    r"|"
    r"(?:can|could|may|should)\s+(?:we|i)\s+"
    r"(?:proceed|advance|continue|go\s+ahead)\s+to\s+(?:the\s+)?"
    r"(?:next\s+)?(?:stage|phase)"
    r")\b",
    re.IGNORECASE,
)

_EMBEDDED_NAMED_MOVE = re.compile(
    r"\b(?:can|could|may|should)\s+(?:we|i)\s+"
    r"(?:move(?:\s+on)?\s+(?:to|into|onto)|go(?:\s+ahead)?\s+to|go\s+onto|"
    r"proceed\s+to|advance\s+to|switch\s+to|start|continue\s+to)\s+"
    r"(?:the\s+)?(?P<target>.+?)(?:\s*[?.!]*)?$"
    r"|"
    r"\b(?:can|could|may|should)\s+move(?:\s+on)?\s+(?:to|into|onto)\s+"
    r"(?:the\s+)?(?P<target_bare>.+?)(?:\s*[?.!]*)?$",
    re.IGNORECASE | re.DOTALL,
)

_PATH_COMPLETION = re.compile(
    r"\b(?:finish|complete)\s+(?:the\s+)?thinking\s+path\b|"
    r"\b(?:is|am|are|can|could|may|should)\b[^?!.]{0,80}\b(?:thinking\s+path|"
    r"reflection)\b[^?!.]{0,80}\b(?:complete|completed|finished|done)\b|"
    r"\b(?:finish|complete)\s+(?:my\s+)?reflection\b",
    re.IGNORECASE,
)

_GENERIC_TERMINAL_COMPLETION = re.compile(
    r"^\s*(?:(?:am|are)\s+(?:i|we)|(?:can|could|may|should)\s+(?:i|we)|"
    r"is\s+(?:this|my\s+reflection))\s+(?:done|finished|complete)\b|"
    r"^\s*(?:can|could|may|should)\s+(?:i|we)\s+(?:finish|complete)\b",
    re.IGNORECASE,
)

_STATUS = re.compile(
    r"^\s*(?:"
    r"(?:(?:can|could|would)\s+you\s+(?:please\s+)?(?:tell|show)\s+me\s+)?"
    r"(?:what|which)\s+(?:(?:my|the)\s+)?(?:journey\s+|thinking\s+path\s+)?"
    r"(?:stage|phase)\s+(?:am\s+i|are\s+we)\s+(?:in|on|at)(?:\s+now)?"
    r"|"
    r"what\s+is\s+(?:my|the)\s+current\s+(?:journey\s+|thinking\s+path\s+)?"
    r"(?:stage|phase)(?:\s+(?:right\s+now|now))?"
    r"|"
    r"where\s+(?:am\s+i|are\s+we)(?:\s+now)?(?:\s+in\s+(?:the\s+)?"
    r"(?:thinking\s+path|journey))?"
    r"|"
    r"where\s+am\s+i\s+in\s+(?:the\s+)?thinking\s+path"
    r"|"
    r"which\s+phase\s+am\s+i\s+currently\s+working\s+on"
    r")\s*$",
    re.IGNORECASE,
)

_CONFIRM = re.compile(r"^confirm$", re.IGNORECASE)

_NEXT_STAGE_PHRASE = re.compile(
    r"^(?:the\s+)?(?:next\s+)?(?:stage|phase)$",
    re.IGNORECASE,
)


def _manual_stage_key(value: str) -> str:
    """Return the strict comparison key for a stage name or alias."""
    compact = " ".join(str(value or "").split()).strip().casefold()
    compact = re.sub(r"\s*&\s*", " and ", compact)
    compact = compact.replace("_", " ")
    return " ".join(compact.split())


def _stage_aliases() -> dict[str, str]:
    """Return approved alias → canonical stage id mappings."""
    aliases: dict[str, str] = {}
    for stage in THINKING_STAGES:
        for raw in (stage.id, stage.label, stage.short_label):
            aliases[_manual_stage_key(raw)] = stage.id
    extras = {
        "problem identification": "problem_identification",
        "problem stage": "problem_identification",
        "concept generation": "concept_generation",
        "concept stage": "concept_generation",
        "idea generation": "concept_generation",
        "design specification": "design_specification",
        "design spec": "design_specification",
        "specification": "design_specification",
        "ethics and critical thinking": "deep_analysis",
        "ethics & critical thinking": "deep_analysis",
        "ethics and ct": "deep_analysis",
        "ethics & ct": "deep_analysis",
        "ethics": "deep_analysis",
        "critical thinking": "deep_analysis",
        "reflection": "reflection",
        "reflection stage": "reflection",
    }
    for alias, stage_id in extras.items():
        aliases[_manual_stage_key(alias)] = stage_id
    return aliases


_STAGE_ALIASES = _stage_aliases()
_ALIAS_KEYS = tuple(_STAGE_ALIASES.keys())


def normalize_workflow_text(message: str) -> str:
    """Return a matching-only normalized view of one student message.

    Args:
        message: Raw student text. Not logged and not mutated in storage.

    Returns:
        Lower-noise text with collapsed whitespace, stripped conversational
        prefixes, trailing punctuation removed, and trailing fillers dropped.
    """
    text = " ".join(str(message or "").split()).strip()
    if not text:
        return ""
    changed = True
    while changed:
        changed = False
        for pattern in _LEADING_PREFIXES:
            updated = pattern.sub("", text, count=1)
            if updated != text:
                text = updated.lstrip(" ,")
                changed = True
    text = _TRAILING_PUNCT.sub("", text).strip()
    text = _TRAILING_FILLER.sub("", text).strip()
    text = _TRAILING_PUNCT.sub("", text).strip()
    return _MULTI_SPACE.sub(" ", text).strip()


def _edit_distance(left: str, right: str) -> int:
    """Return Levenshtein distance for short stage phrases only."""
    if left == right:
        return 0
    if not left:
        return len(right)
    if not right:
        return len(left)
    previous = list(range(len(right) + 1))
    for i, left_ch in enumerate(left, start=1):
        current = [i]
        for j, right_ch in enumerate(right, start=1):
            insert_cost = current[j - 1] + 1
            delete_cost = previous[j] + 1
            replace_cost = previous[j - 1] + (left_ch != right_ch)
            current.append(min(insert_cost, delete_cost, replace_cost))
        previous = current
    return previous[-1]


def resolve_stage_phrase(phrase: str, *, allow_typos: bool = False) -> str | None:
    """Resolve one stage phrase to a canonical id using aliases and optional typos.

    Args:
        phrase: Candidate destination text already extracted from a navigation
            clause.
        allow_typos: When True, allow a very small edit distance against the
            approved alias set only. Callers must set this only after strong
            navigation intent is established.

    Returns:
        Canonical stage id, or ``None`` when the phrase is empty, means "next
        stage", or remains ambiguous.
    """
    key = _manual_stage_key(phrase)
    if not key or _NEXT_STAGE_PHRASE.fullmatch(key):
        return None
    exact = _STAGE_ALIASES.get(key)
    if exact is not None:
        return exact
    if not allow_typos:
        return None
    # Bound typo search: short phrases get distance 1; longer get distance 2.
    max_distance = 1 if len(key) < 10 else 2
    matches: list[str] = []
    for alias in _ALIAS_KEYS:
        if abs(len(alias) - len(key)) > max_distance:
            continue
        if _edit_distance(key, alias) <= max_distance:
            stage_id = _STAGE_ALIASES[alias]
            if stage_id not in matches:
                matches.append(stage_id)
    if len(matches) == 1:
        return matches[0]
    return None


def _strip_target_noise(raw: str) -> str:
    """Trim trailing punctuation/fillers from an extracted target phrase."""
    text = " ".join(str(raw or "").split()).strip()
    text = _TRAILING_PUNCT.sub("", text).strip()
    text = _TRAILING_FILLER.sub("", text).strip()
    text = _TRAILING_PUNCT.sub("", text).strip()
    # Drop a trailing "now" that survived filler stripping mid-clause.
    text = re.sub(r"\s+\bnow\b$", "", text, flags=re.IGNORECASE).strip()
    return text


def _looks_like_stage_definition_qa(normalized: str) -> bool:
    """Return whether the turn asks what a stage means or where course material covers it."""
    return bool(_STAGE_DEFINITION_OR_COURSE_QA.search(normalized))


def is_exact_confirm_command(message: str) -> bool:
    """Return whether the message is an explicit ``confirm`` command.

    Harmless casing and trailing punctuation are accepted. Vague
    acknowledgements such as ``yes`` / ``okay`` are not.
    """
    text = normalize_workflow_text(message)
    return bool(_CONFIRM.fullmatch(text))


def is_current_stage_status_request(message: str) -> bool:
    """Return whether the turn asks only for the persisted current stage."""
    text = normalize_workflow_text(message)
    if not text:
        return False
    # Status forms often begin with "what is … stage"; check them before the
    # broader stage-definition Q&A negative filter.
    return bool(_STATUS.fullmatch(text))


def _target_from_named_move(normalized: str) -> str | None:
    """Extract and resolve a named stage from a navigation clause."""
    match = _NAVIGATION_CLAUSE.search(normalized)
    if match is None:
        match = _EMBEDDED_NAMED_MOVE.search(normalized)
    if match is None:
        return None
    raw = (
        match.groupdict().get("target")
        or match.groupdict().get("target_bare")
        or match.groupdict().get("target_lets")
        or match.groupdict().get("target_ready")
        or ""
    )
    phrase = _strip_target_noise(raw)
    if not phrase:
        return None
    return resolve_stage_phrase(phrase, allow_typos=True)


def classify_workflow_intent(message: str) -> WorkflowIntent:
    """Classify one student message for Thinking Path workflow routing.

    Args:
        message: Raw student contribution.

    Returns:
        A :class:`WorkflowIntent`. ``kind=none`` means normal coaching / Q&A
        routing should proceed unchanged.
    """
    text = normalize_workflow_text(message)
    if not text:
        return WorkflowIntent(kind="none", confidence="low")

    if is_exact_confirm_command(message):
        return WorkflowIntent(kind="confirm")

    if is_current_stage_status_request(message):
        return WorkflowIntent(kind="status")

    if _looks_like_stage_definition_qa(text):
        return WorkflowIntent(kind="none")

    # Exact Phase-2 style command first.
    move_me = _EXACT_MOVE_ME_TO.fullmatch(text)
    if move_me is not None:
        target = resolve_stage_phrase(move_me.group(1), allow_typos=True)
        if target is not None:
            return WorkflowIntent(kind="move_stage", target_stage_id=target)
        return WorkflowIntent(kind="none", confidence="low")

    move_to = _EXACT_MOVE_TO.fullmatch(text)
    if move_to is not None:
        target = resolve_stage_phrase(move_to.group(1), allow_typos=True)
        if target is not None:
            return WorkflowIntent(kind="move_stage", target_stage_id=target)
        return WorkflowIntent(kind="none", confidence="low")

    named = _target_from_named_move(text)
    if named is not None:
        return WorkflowIntent(kind="move_stage", target_stage_id=named)

    # Whole-message next/readiness forms after prefix stripping.
    if _MOVE_NEXT.fullmatch(text) or _READINESS.fullmatch(text):
        return WorkflowIntent(kind="move_next")

    # Embedded readiness / next after a reasoning paragraph.
    if _EMBEDDED_READINESS_OR_NEXT.search(text):
        return WorkflowIntent(kind="readiness")

    if _PATH_COMPLETION.search(text):
        return WorkflowIntent(kind="readiness")

    return WorkflowIntent(kind="none")


def is_stage_progression_request(student_message: str) -> bool:
    """Return whether the student explicitly asks to navigate the Thinking Path.

    Routing only. Never changes a stage.
    """
    intent = classify_workflow_intent(student_message)
    return intent.kind in {"move_stage", "move_next", "readiness"}


def manual_stage_selection_target(student_message: str) -> str | None:
    """Return the canonical target of an explicit stage-move command.

    Accepts ``move me to <stage>``, whole-message ``move to <stage>``, and
    natural ``can I move to <stage>`` forms once intent and destination
    resolve. Does not authorize the move; Phase 2 selection and store
    validation remain authoritative. Ambiguous phrases such as
    ``Concept generation now?`` return ``None``.
    """
    intent = classify_workflow_intent(student_message)
    if intent.kind == "move_stage":
        return intent.target_stage_id
    return None


def is_terminal_completion_request(student_message: str, *, current_stage: str) -> bool:
    """Return whether a Reflection turn asks to complete the Thinking Path."""
    if str(current_stage or "").strip().lower() != "reflection":
        return False
    text = normalize_workflow_text(student_message)
    return bool(
        _PATH_COMPLETION.search(text) or _GENERIC_TERMINAL_COMPLETION.search(text)
    )
