"""Review Agent orchestration: incremental Haiku vs deep Sonnet.

The Review Agent has two depths.

Incremental Review uses Haiku 4.5 after normal Coaching turns to keep the
student-facing Review projection current at low cost.

Deep Review uses Sonnet at periodic or event-driven checkpoints to perform
the more expensive pedagogical synthesis and stage-readiness assessment.

Periodic means every configured N successful new Coaching turns since the
last successfully persisted Deep Review. It does not mean elapsed time.
Opening the Review UI, Q&A, failed turns, or idempotent replays do not count.

FastAPI and DSQL remain authoritative. Review assessments never mutate the
Thinking Path stage directly. Research coding is observational and must not
influence routing, the periodic counter, Deep Review eligibility, or
advancement.
"""

from __future__ import annotations

from typing import Any

DEFAULT_DEEP_REVIEW_INTERVAL_TURNS = 3
MIN_DEEP_REVIEW_INTERVAL_TURNS = 1
MAX_DEEP_REVIEW_INTERVAL_TURNS = 20

COUNTER_SETTINGS_KEY = "coaching_turns_since_deep_review"
DEEP_REVIEW_SNAPSHOT_KEY = "deep_review_snapshot"
DEEP_REVIEW_TURN_MESSAGE = "Start Deep Review"

REVIEW_DEPTH_INCREMENTAL = "incremental"
REVIEW_DEPTH_DEEP = "deep"
REVIEW_DEPTHS = frozenset({REVIEW_DEPTH_INCREMENTAL, REVIEW_DEPTH_DEEP})

REVIEW_TRIGGER_INCREMENTAL = "incremental"
REVIEW_TRIGGER_PERIODIC = "periodic"
REVIEW_TRIGGER_EXPLICIT = "explicit"
REVIEW_TRIGGER_READINESS_CANDIDATE = "readiness_candidate"
REVIEW_TRIGGER_STAGE_CHECKPOINT = "stage_checkpoint"
REVIEW_TRIGGER_REFLECTION_CHECKPOINT = "reflection_checkpoint"
DEEP_REVIEW_TRIGGERS = frozenset(
    {
        REVIEW_TRIGGER_PERIODIC,
        REVIEW_TRIGGER_EXPLICIT,
        REVIEW_TRIGGER_READINESS_CANDIDATE,
        REVIEW_TRIGGER_STAGE_CHECKPOINT,
        REVIEW_TRIGGER_REFLECTION_CHECKPOINT,
    }
)


def bound_deep_review_interval(value: Any) -> int:
    """Clamp ``DEEP_REVIEW_INTERVAL_TURNS`` to a safe production range.

    Args:
        value: Configured interval. Invalid values become ``3``.

    Returns:
        An integer in ``[1, 20]``.
    """
    try:
        interval = int(value)
    except (TypeError, ValueError):
        return DEFAULT_DEEP_REVIEW_INTERVAL_TURNS
    if interval < MIN_DEEP_REVIEW_INTERVAL_TURNS:
        return DEFAULT_DEEP_REVIEW_INTERVAL_TURNS
    return min(MAX_DEEP_REVIEW_INTERVAL_TURNS, interval)


def parse_coaching_turns_since_deep_review(value: Any) -> int:
    """Return a non-negative persisted periodic counter.

    Args:
        value: Notebook settings value. Invalid input becomes ``0``.

    Returns:
        ``max(0, int(value))``.
    """
    try:
        count = int(value)
    except (TypeError, ValueError):
        return 0
    return max(0, count)


def next_persisted_counter(
    *,
    current: int,
    qualifying_coaching_turn: bool,
    deep_review_succeeded: bool,
) -> int:
    """Return the counter to persist after one coach turn.

    Reset to ``0`` only after a Deep Review result is validated and accepted
    for persistence. Failed Deep Review keeps the due count so the next
    eligible turn can retry. Q&A, explicit Review, and failed coaching do
    not increment.

    Args:
        current: Counter loaded from notebook settings before this turn.
        qualifying_coaching_turn: Whether this turn is a newly persisted
            Coaching interaction.
        deep_review_succeeded: Whether Sonnet Deep Review was validated.

    Returns:
        The next durable counter value.
    """
    if deep_review_succeeded:
        return 0
    if qualifying_coaching_turn:
        return parse_coaching_turns_since_deep_review(current) + 1
    return parse_coaching_turns_since_deep_review(current)


def resolve_deep_review_trigger(
    *,
    specialist: str,
    current_stage: str,
    readiness_candidate: bool,
    coaching_turns_since_deep_review: int,
    interval: int,
    qualifying_coaching_turn: bool,
) -> str | None:
    """Return the Deep Review trigger for this turn, or ``None``.

    A periodic Deep Review is triggered after N qualifying Coaching turns
    since the previous successful Deep Review.

    A qualifying turn is a newly executed and successfully persisted
    Coaching interaction. Q&A, explicit Review, UI navigation, failed turns,
    safety blocks, timeouts, malformed outputs, and idempotent replays do not
    advance this counter.

    This is intentionally turn-based rather than time-based: the purpose is
    to review new learning evidence, not elapsed wall-clock time.

    Event triggers (explicit Review, readiness candidate, Reflection
    checkpoint) take priority over the periodic count.

    Args:
        specialist: Server-owned ``qa``, ``coaching``, or ``review``.
        current_stage: Persisted Thinking Path stage id.
        readiness_candidate: Coaching or Incremental Review flag.
        coaching_turns_since_deep_review: Counter before this turn.
        interval: Configured N (``DEEP_REVIEW_INTERVAL_TURNS``).
        qualifying_coaching_turn: Whether this turn will count if persisted.

    Returns:
        A ``review_trigger`` member of :data:`DEEP_REVIEW_TRIGGERS`, or
        ``None`` when Deep Review must not run.
    """
    cleaned = str(specialist or "").strip().lower()
    if cleaned == "review":
        return REVIEW_TRIGGER_EXPLICIT
    if not qualifying_coaching_turn:
        return None
    if str(current_stage or "").strip().lower() == "reflection":
        return REVIEW_TRIGGER_REFLECTION_CHECKPOINT
    if readiness_candidate:
        return REVIEW_TRIGGER_READINESS_CANDIDATE
    bounded_interval = bound_deep_review_interval(interval)
    current = parse_coaching_turns_since_deep_review(coaching_turns_since_deep_review)
    if current + 1 >= bounded_interval:
        return REVIEW_TRIGGER_PERIODIC
    return None


def should_run_deep_review(trigger: str | None) -> bool:
    """Return whether Sonnet Deep Review should run for ``trigger``."""
    return str(trigger or "").strip().lower() in DEEP_REVIEW_TRIGGERS


def explicit_deep_review_available(
    *,
    coaching_turns_since_deep_review: int,
    interval: int,
) -> bool:
    """Return whether persisted Coaching turns unlock one explicit Deep Review.

    Reaching 4, 5, or 6 unused qualifying turns still yields one entitlement.
    The counter is not a bank of stacked reviews.

    Args:
        coaching_turns_since_deep_review: Durable notebook counter.
        interval: Configured ``DEEP_REVIEW_INTERVAL_TURNS``.

    Returns:
        ``True`` when ``counter >= interval``.
    """
    current = parse_coaching_turns_since_deep_review(coaching_turns_since_deep_review)
    return current >= bound_deep_review_interval(interval)


def deep_review_snapshot_payload(
    *,
    conversation_revision: int,
    created_at: str,
    synthesis: str,
    summary: str,
    strengths: list[str],
    areas_to_develop: list[str],
    facione_scores: dict[str, Any],
    working_conclusion: str,
    readiness_candidate: bool,
    readiness_evidence: list[str],
    missing_requirements: list[str],
    model_id: str,
) -> dict[str, Any]:
    """Return the durable Deep Review snapshot stored in notebook settings.

    Hidden prompts are never included. Normal Coaching persist must omit this
    key so a later Haiku turn cannot overwrite the snapshot.

    Args:
        conversation_revision: Revision reviewed through.
        created_at: UTC timestamp of the successful review.
        synthesis: Formative synthesis text.
        summary: Student-facing summary.
        strengths: Named strengths.
        areas_to_develop: Named development areas.
        facione_scores: Facione profile mapping.
        working_conclusion: Working conclusion at review time.
        readiness_candidate: Whether Sonnet marked stage readiness.
        readiness_evidence: Evidence strings supporting readiness.
        missing_requirements: Remaining requirements.
        model_id: Review model identifier (Sonnet 4.6).

    Returns:
        JSON-serialisable snapshot dictionary.
    """
    return {
        "reviewed_through_revision": max(0, int(conversation_revision)),
        "created_at": str(created_at or "").strip(),
        "synthesis": " ".join(str(synthesis or "").split()).strip()[:4_000],
        "summary": " ".join(str(summary or "").split()).strip()[:4_000],
        "strengths": [str(item).strip() for item in strengths if str(item).strip()][:8],
        "areas_to_develop": [
            str(item).strip() for item in areas_to_develop if str(item).strip()
        ][:8],
        "facione_scores": dict(facione_scores or {}),
        "working_conclusion": " ".join(str(working_conclusion or "").split()).strip()[
            :4_000
        ],
        "readiness_candidate": bool(readiness_candidate),
        "readiness_evidence": [
            str(item).strip() for item in readiness_evidence if str(item).strip()
        ][:12],
        "missing_requirements": [
            str(item).strip() for item in missing_requirements if str(item).strip()
        ][:12],
        "model_id": str(model_id or "").strip()[:128],
        "review_depth": REVIEW_DEPTH_DEEP,
        "review_trigger": REVIEW_TRIGGER_EXPLICIT,
    }
