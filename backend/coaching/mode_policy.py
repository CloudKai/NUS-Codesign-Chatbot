"""Server-side Q&A vs Coaching mode policy for one Fast Chat turn.

There is no extra LLM router. Normal chat still makes exactly one AgentCore
``phase=fast_chat`` invoke. Haiku returns ``mode``, and this module constrains
what that label is allowed to *mean* downstream.

How confidence is derived
=========================
:func:`backend.retrieval_gate.classify_retrieval_intent` is recall-oriented:
any source cue wins, including a genuine project message that mentions
"lecture" or "week 2". That is correct for Retrieve (skipping evidence is
worse than a cheap empty Retrieve). It is too aggressive for mode
enforcement. Over-forcing a project-reasoning turn into Q&A would drop the
Socratic recommendation — a worse pedagogy failure than the bug this policy
fixes.

This overlay therefore uses a **conservative** threshold and a **generous**
ambiguous bucket:

- ``high_confidence_source`` **and no first-person project reasoning**
  → the server expects ``mode=qa``.
- ``high_confidence_personal`` (the retrieval classifier already found no
  source cues) → the server expects ``mode=coaching``.
- ``ambiguous``, idle text, weak questions, **or mixed** source+project
  language → Haiku chooses; the server does not constrain.

Mixed detection uses first-person project cues (``I think``, ``I interviewed``,
``my problem``, ``should I choose``, ``help me think``, …). A factual question
that merely contains ``lecture`` / ``week 2`` / ``S1`` stays source. A project
turn that merely mentions those tokens becomes ambiguous so coaching is not
flattened.

Enforcement (option A: coerce downstream to Q&A, keep the prose)
===============================================================
When the server expects Q&A and the model returns ``mode=coaching``:

- keep ``response_text`` (do not rewrite the student-facing prose)
- set ``response_mode=qa``, ``recommendation=None``,
  ``qualifying_coaching_turn=False``
- the workflow therefore cannot open a pending stage transition (it only
  opens one on ADVANCE) and no stay/advance is persisted

Coercing to Q&A (rather than keeping ``mode=coaching`` while stripping side
effects) preserves the existing invariant that coaching requires a
stay/advance recommendation.

When the server expects coaching, a returned coaching recommendation is
kept. The server never invents stay/advance if Haiku returned Q&A — that
would fabricate a stage recommendation. The runtime hint still asks for
coaching on high-confidence personal turns.

Clients never supply this policy. FastAPI stamps it from the authoritative
student message and selected-source metadata, then overwrites any
client-supplied values.
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any, Literal

from backend.retrieval import (
    COURSE_RETRIEVAL_EMPTY_CONTEXT,
    COURSE_RETRIEVAL_UNAVAILABLE_CONTEXT,
)
from backend.retrieval_gate import (
    INTENT_AMBIGUOUS,
    INTENT_HIGH_CONFIDENCE_PERSONAL,
    INTENT_HIGH_CONFIDENCE_SOURCE,
    RetrievalClassification,
    RetrievalIntent,
    classify_retrieval_intent,
)

ExpectedResponseMode = Literal["qa", "coaching"]

RUNTIME_HINT_QA = (
    "This turn is source Q&A: Q&A rules take precedence over Coaching. "
    "Answer from current retrieved excerpts only, or state the evidence gap. "
    "Do not ask a Socratic or project question. Do not connect the answer to "
    "the student's project unless they asked. Do not recommend stay or advance."
)
RUNTIME_HINT_COACHING = (
    "This turn is the student's own project reasoning: coach Socratically and "
    "include a stay or advance recommendation."
)

QA_EVIDENCE_GAP_RESPONSE = (
    "I couldn't retrieve a validated excerpt from the selected course material "
    "for this turn, so I can't reliably summarise it from the course sources "
    "right now."
)

# Project deliberation used only to *demote* source→ambiguous, so a turn is
# never forced into Q&A just because it mentions a lecture or a week. These
# are deliberately person-agnostic: students frame design work in the third
# person ("the core problem is that students skip the week 2 lecture") as
# often as the first. Over-matching here is safe — it only returns the turn
# to the model's own judgement — while under-matching silently strips a
# legitimate coaching recommendation.
_PROJECT_REASONING = (
    re.compile(
        r"^\s*i (think|thought|want|changed|chose|decided|will|am)\b",
        re.IGNORECASE,
    ),
    re.compile(r"^\s*i['’]m\b", re.IGNORECASE),
    re.compile(r"^\s*let'?s\b", re.IGNORECASE),
    re.compile(
        r"\b(my|our) (users?|idea|design|concept|stakeholders?)\b",
        re.IGNORECASE,
    ),
    re.compile(r"\bwould this (idea|design|concept|option)\b", re.IGNORECASE),
    re.compile(
        r"\b(does|would) this (idea|design|concept|option) solve\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(my|our) (problem|project|prototype|option|target users?)\b",
        re.IGNORECASE,
    ),
    re.compile(r"\b(i|we) interviewed\b", re.IGNORECASE),
    re.compile(r"\b(i|we) (spoke|talked) (to|with)\b", re.IGNORECASE),
    re.compile(r"\bhelp (me|us) (think|decide|choose|work through)\b", re.IGNORECASE),
    re.compile(
        r"\bshould (i|we) (choose|pick|go with|use|select|focus|prioriti[sz]e)\b",
        re.IGNORECASE,
    ),
    re.compile(r"\b(the|our|this) (core |real |main )?problem is\b", re.IGNORECASE),
    re.compile(r"\bproblem statement\b", re.IGNORECASE),
    re.compile(r"\btrade-?offs?\b", re.IGNORECASE),
    re.compile(r"\boption [ab1-9]\b", re.IGNORECASE),
    re.compile(r"\b(refine|narrow down|pivot|reframe) (the|our|my)\b", re.IGNORECASE),
    re.compile(r"\b(we|our team) (think|want|chose|decided|believe)\b", re.IGNORECASE),
)

# Forcing Q&A additionally requires the turn to actually ask for information.
# A declarative project statement that cites a lecture is reasoning, not a
# lookup, so it must keep its coaching semantics.
_INFORMATION_REQUEST = re.compile(
    r"\?|^\s*(what|why|how|when|where|which|who|explain|describe|define|list|"
    r"summar(?:y|ise|ize)|tell me|show me|give me|walk me through|"
    r"help me (?:understand|interpret|analy[sz]e))\b",
    re.IGNORECASE,
)

# A current-turn attachment is evidence for the student's request, not an
# implicit request to search the whole course catalogue.  Keep this matcher
# deliberately small and deterministic; the model still decides whether the
# attachment is in scope in the same Fast Chat call.
_ATTACHMENT_REFERENCE = re.compile(
    r"\b(attached|attachment|uploaded|upload|file|pdf|document|image|photo|"
    r"diagram|scan)\b",
    re.IGNORECASE,
)
_ATTACHMENT_ACTION = re.compile(
    r"\b(outline|extract|list|identify|review|analy[sz]e|summar(?:y|ise|ize))\b",
    re.IGNORECASE,
)
_ATTACHMENT_DIRECTIVE = re.compile(
    r"^\s*(?:(?:can|could|would)\s+(?:you\s+)?(?:please\s+)?|please\s+)?"
    r"(?:outline|extract|list|identify|review|analy[sz]e|summar(?:y|ise|ize))\b",
    re.IGNORECASE,
)
_COURSE_REFERENCE = re.compile(
    r"\b(lecture|lectures|week|weeks|course|cde2300|product\s+design|"
    r"design\s+thinking|jtbd|how\s+might\s+we|reading|readings|syllabus|"
    r"class\s+materials?)\b",
    re.IGNORECASE,
)

# Navigation is a command about the student's Thinking Path, not a request to
# explain a stage term.  Keep this intentionally narrow: stage names alone and
# factual questions ("what is concept generation?") must retain normal Q&A.
_STAGE_PROGRESSION_REQUEST = re.compile(
    r"^\s*(?:nothing else[.!]?\s*)?(?:can|could|may|should)\s+(?:we|i)\s+"
    r"move on\b|^\s*(?:can|could|may|should)\s+(?:we|i)\s+(?:proceed|advance)\s+"
    r"(?:to|onto)\s+(?:the\s+)?(?:next\s+(?:stage|phase)|problem\s+identification|"
    r"concept\s+generation|design\s+specification|ethics(?:\s*(?:&|and)\s*)?"
    r"(?:critical\s+thinking|ct)|reflection)\b|^\s*(?:are|am)\s+(?:we|i)\s+ready\s+"
    r"to\s+(?:move on|proceed|advance)\b|^\s*(?:let'?s|i(?:'m| am) ready to)\s+"
    r"(?:move on|proceed|advance)\b|\bgo\s+(?:to|onto)\s+(?:the\s+)?"
    r"(?:next\s+(?:stage|phase)|problem\s+identification|concept\s+generation|"
    r"design\s+specification|ethics(?:\s*(?:&|and)\s*)?(?:critical\s+thinking|ct)|"
    r"reflection)\b",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class ModePolicy:
    """Deterministic mode expectation for one student turn.

    Attributes:
        intent: Overlay intent used for the hint and enforcement. Mixed
            source+project turns are ``ambiguous``.
        expected_mode: ``qa``, ``coaching``, or ``None`` when unconstrained.
        retrieve: Retrieval-gate decision. Mixed project+source still
            retrieves; this overlay does not change Retrieve.
        retrieval_intent: Raw retrieval-gate intent before the overlay.
        mixed: True when source cues fired but the turn is project
            deliberation or is not an information request, so the model
            keeps authority over the mode.
    """

    intent: RetrievalIntent
    expected_mode: ExpectedResponseMode | None
    retrieve: bool
    retrieval_intent: RetrievalIntent
    mixed: bool = False


@dataclass(frozen=True)
class ModeEnforcement:
    """Downstream mode after applying :class:`ModePolicy` to the model label.

    Attributes:
        effective_mode: Mode the rest of the turn must use.
        overridden: True when the server coerced coaching→qa.
        qualifying_coaching_turn: Whether the Deep Review counter may increment.
    """

    effective_mode: ExpectedResponseMode
    overridden: bool
    qualifying_coaching_turn: bool


def _normalized_text(value: str) -> str:
    """Return compact text for intent matching."""
    return " ".join(str(value or "").split()).strip()


def looks_like_project_reasoning(student_message: str) -> bool:
    """Return whether the turn deliberates about the student's own project.

    Args:
        student_message: Current student contribution. Not logged.

    Returns:
        True when a person-agnostic project-deliberation matcher fires.
    """
    text = _normalized_text(student_message)
    if not text:
        return False
    return any(pattern.search(text) for pattern in _PROJECT_REASONING)


def looks_like_information_request(student_message: str) -> bool:
    """Return whether the turn asks for information rather than asserting.

    Args:
        student_message: Current student contribution. Not logged.

    Returns:
        True for questions and direct information requests. Declarative
        project statements return False even when they name a lecture.
    """
    text = _normalized_text(student_message)
    if not text:
        return False
    return bool(_INFORMATION_REQUEST.search(text))


def is_stage_progression_request(student_message: str) -> bool:
    """Return whether the student explicitly asks to navigate the Thinking Path.

    This matcher only controls routing.  It never changes a stage; the normal
    provider assessment, HMW guard, pending transition, and atomic confirmation
    path remain authoritative.
    """
    return bool(_STAGE_PROGRESSION_REQUEST.search(_normalized_text(student_message)))


def is_private_attachment_question(
    student_message: str,
    *,
    attachment_count: int = 0,
) -> bool:
    """Return whether this turn should retrieve only current attachments.

    This is a retrieval-scope hint, not a relevance classifier.  It applies
    only to a turn with private attachments, an information request, and no
    explicit course reference.  The existing Fast Chat result still owns the
    semantic out-of-scope decision, and explicit course comparisons continue
    through the normal combined attachment + course retrieval path.
    """
    if int(attachment_count or 0) <= 0:
        return False
    text = _normalized_text(student_message)
    asks_for_information = looks_like_information_request(text)
    # Attached-file verbs are commonly written as polite requests without a
    # question mark ("Could you outline…", "Please analyze…") or as direct
    # imperatives ("List the claims"). Keep this narrow and retain the
    # project-reasoning guard below so "analyze my idea" is not re-scoped.
    if not asks_for_information and not _ATTACHMENT_DIRECTIVE.search(text):
        return False
    if _COURSE_REFERENCE.search(text):
        return False
    if looks_like_project_reasoning(text):
        return False
    if _ATTACHMENT_REFERENCE.search(text) or _ATTACHMENT_ACTION.search(text):
        return True
    # Short questions such as "what themes do you notice?" implicitly refer
    # to the only newly supplied evidence. Project deliberation remains on the
    # normal path unless it explicitly names the attachment.
    return True


def overlay_mode_policy(
    classification: RetrievalClassification,
    student_message: str,
) -> ModePolicy:
    """Derive the mode overlay from one retrieval classification.

    Args:
        classification: Result of :func:`classify_retrieval_intent`.
        student_message: Same student text, used only for mixed detection.

    Returns:
        A :class:`ModePolicy`. Mixed source+project turns are unconstrained.
    """
    project = looks_like_project_reasoning(student_message)
    asks_for_information = looks_like_information_request(student_message)
    mixed = classification.intent == INTENT_HIGH_CONFIDENCE_SOURCE and (
        project or not asks_for_information
    )
    if mixed:
        return ModePolicy(
            intent=INTENT_AMBIGUOUS,
            expected_mode=None,
            retrieve=classification.retrieve,
            retrieval_intent=classification.intent,
            mixed=True,
        )
    if classification.intent == INTENT_HIGH_CONFIDENCE_SOURCE:
        return ModePolicy(
            intent=INTENT_HIGH_CONFIDENCE_SOURCE,
            expected_mode="qa",
            retrieve=classification.retrieve,
            retrieval_intent=classification.intent,
        )
    if classification.intent == INTENT_HIGH_CONFIDENCE_PERSONAL:
        return ModePolicy(
            intent=INTENT_HIGH_CONFIDENCE_PERSONAL,
            expected_mode="coaching",
            retrieve=classification.retrieve,
            retrieval_intent=classification.intent,
        )
    return ModePolicy(
        intent=INTENT_AMBIGUOUS,
        expected_mode=None,
        retrieve=classification.retrieve,
        retrieval_intent=classification.intent,
    )


def resolve_mode_policy(
    student_message: str,
    *,
    selected_source_titles: Iterable[str] = (),
    selected_source_filenames: Iterable[str] = (),
    has_selected_sources: bool | None = None,
) -> ModePolicy:
    """Classify retrieval and overlay the conservative mode policy.

    Args:
        student_message: Authoritative current student contribution.
        selected_source_titles: Server-owned selected source titles.
        selected_source_filenames: Server-owned selected source filenames.
        has_selected_sources: When True, selected-source questions retrieve.

    Returns:
        One :class:`ModePolicy`. Cue names never include student text.
    """
    classification = classify_retrieval_intent(
        student_message,
        selected_source_titles=selected_source_titles,
        selected_source_filenames=selected_source_filenames,
        has_selected_sources=has_selected_sources,
    )
    return overlay_mode_policy(classification, student_message)


def runtime_mode_hint(expected_mode: str | None) -> str:
    """Return the one-sentence runtime hint, or empty when unconstrained.

    Args:
        expected_mode: ``qa``, ``coaching``, or ``None``.

    Returns:
        A single sentence, or ``""`` when the model should choose.
    """
    cleaned = str(expected_mode or "").strip().lower()
    if cleaned == "qa":
        return RUNTIME_HINT_QA
    if cleaned == "coaching":
        return RUNTIME_HINT_COACHING
    return ""


def enforce_model_mode(
    expected_mode: str | None,
    model_mode: str,
) -> ModeEnforcement:
    """Apply the server policy to the model's returned ``mode``.

    Args:
        expected_mode: Server expectation, or ``None`` when unconstrained.
        model_mode: ``qa`` or ``coaching`` from FastChatTurnOutput.

    Returns:
        Downstream mode, override flag, and counter eligibility.

    Raises:
        ValueError: When ``model_mode`` is not ``qa`` or ``coaching``.
    """
    returned = str(model_mode or "").strip().lower()
    if returned not in {"qa", "coaching"}:
        raise ValueError("model_mode must be qa or coaching")
    expected = str(expected_mode or "").strip().lower()
    if expected not in {"qa", "coaching"}:
        expected = ""
    if expected == "qa" and returned == "coaching":
        return ModeEnforcement(
            effective_mode="qa",
            overridden=True,
            qualifying_coaching_turn=False,
        )
    if returned == "qa":
        return ModeEnforcement(
            effective_mode="qa",
            overridden=False,
            qualifying_coaching_turn=False,
        )
    return ModeEnforcement(
        effective_mode="coaching",
        overridden=False,
        qualifying_coaching_turn=True,
    )


def policy_from_request(request: object) -> ModePolicy:
    """Return the stamped policy, or classify from the student message.

    Args:
        request: A :class:`backend.domain.CoachRequest`-shaped object.

    Returns:
        The server-stamped overlay when ``mode_policy_intent`` is set;
        otherwise a message-only classification (no selected-source titles).
    """
    intent_raw = str(getattr(request, "mode_policy_intent", "") or "").strip().lower()
    expected_raw = str(
        getattr(request, "expected_response_mode", "") or ""
    ).strip().lower()
    expected_mode: ExpectedResponseMode | None = None
    if expected_raw == "qa":
        expected_mode = "qa"
    elif expected_raw == "coaching":
        expected_mode = "coaching"
    stamped: RetrievalIntent | None = None
    if intent_raw == INTENT_HIGH_CONFIDENCE_SOURCE:
        stamped = INTENT_HIGH_CONFIDENCE_SOURCE
    elif intent_raw == INTENT_HIGH_CONFIDENCE_PERSONAL:
        stamped = INTENT_HIGH_CONFIDENCE_PERSONAL
    elif intent_raw == INTENT_AMBIGUOUS:
        stamped = INTENT_AMBIGUOUS
    if stamped is None:
        return resolve_mode_policy(
            str(getattr(request, "student_message", "") or "")
        )
    return ModePolicy(
        intent=stamped,
        expected_mode=expected_mode,
        retrieve=bool(getattr(request, "retrieval_required", False)),
        retrieval_intent=stamped,
    )


def should_author_qa_evidence_gap(request: object) -> bool:
    """Return whether FastAPI should author a Q&A evidence-gap reply.

    High-confidence source Q&A with selected sources and no validated chunks
    must not invoke the model, so prior assistant text cannot become course
    facts. Mixed/unconstrained turns still go to the provider.

    Args:
        request: Prepared :class:`~backend.domain.CoachRequest`.

    Returns:
        True when the server should persist ``QA_EVIDENCE_GAP_RESPONSE``
        without an AgentCore invoke.
    """
    if str(getattr(request, "expected_response_mode", "") or "").strip().lower() != "qa":
        return False
    if bool(getattr(request, "allow_model_knowledge", False)):
        return False
    if getattr(request, "retrieved_chunks", None):
        return False
    source_ids = getattr(request, "source_ids", None) or []
    if not source_ids:
        return False
    retrieved_context = str(getattr(request, "retrieved_course_context", "") or "")
    gap_note = (
        COURSE_RETRIEVAL_UNAVAILABLE_CONTEXT in retrieved_context
        or COURSE_RETRIEVAL_EMPTY_CONTEXT in retrieved_context
    )
    if gap_note:
        return True
    # Image-only Q&A has selected sources but no textual retrieve. The model
    # still needs the vision turn; do not author a course-material gap. A
    # mixed image + textual-source turn remains grounded: its course claims
    # still require a validated textual chunk.
    image_inputs = getattr(request, "image_inputs", None) or []
    image_ids = {
        str(item.get("source_id") or "")
        if isinstance(item, dict)
        else str(getattr(item, "source_id", "") or "")
        for item in image_inputs
    }
    source_ids = {str(source_id) for source_id in source_ids}
    image_only = bool(image_inputs) and source_ids and source_ids <= image_ids
    if image_only and not retrieved_context.strip():
        return False
    return True


def qa_evidence_gap_turn(request: object) -> Any:
    """Return a Q&A CoachTurn that states the current evidence gap.

    Args:
        request: Prepared request whose stage is copied onto the assessment.

    Returns:
        A ``CoachTurn`` with ``response_mode=qa``, no recommendation, and no
        citations. Does not invoke a model.
    """
    from backend.domain import CoachTurn, EducationalAssessment

    stage = str(getattr(request, "current_stage", "") or "problem_identification")
    return CoachTurn(
        response_text=QA_EVIDENCE_GAP_RESPONSE,
        assessment=EducationalAssessment(
            current_stage=stage,
            response_mode="qa",
        ),
    )
