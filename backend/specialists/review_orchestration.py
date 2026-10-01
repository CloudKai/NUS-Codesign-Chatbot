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

``resolve_deep_review_trigger`` and ``should_run_deep_review`` are not imported
by ``backend.coaching.execution``. Automatic Sonnet is off the live path.
Explicit Deep Review is ``POST /api/v1/threads/{thread_id}/deep-review``.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from backend.learning.stages import STAGE_BY_ID, THINKING_STAGES

DEFAULT_DEEP_REVIEW_INTERVAL_TURNS = 3
MIN_DEEP_REVIEW_INTERVAL_TURNS = 1
MAX_DEEP_REVIEW_INTERVAL_TURNS = 20

COUNTER_SETTINGS_KEY = "coaching_turns_since_deep_review"
DEEP_REVIEW_SNAPSHOT_KEY = "deep_review_snapshot"
DEEP_REVIEW_JOB_KEY = "deep_review_job"
DEEP_REVIEW_TURN_MESSAGE = "Start Deep Review"

DEEP_REVIEW_JOB_QUEUED = "queued"
DEEP_REVIEW_JOB_RUNNING = "running"
DEEP_REVIEW_JOB_COMPLETED = "completed"
DEEP_REVIEW_JOB_FAILED = "failed"
DEEP_REVIEW_JOB_ACTIVE_STATUSES = frozenset(
    {DEEP_REVIEW_JOB_QUEUED, DEEP_REVIEW_JOB_RUNNING}
)
DEEP_REVIEW_JOB_STATUSES = frozenset(
    {
        DEEP_REVIEW_JOB_QUEUED,
        DEEP_REVIEW_JOB_RUNNING,
        DEEP_REVIEW_JOB_COMPLETED,
        DEEP_REVIEW_JOB_FAILED,
    }
)
DEEP_REVIEW_ERROR_TIMEOUT = "review_timeout"
DEEP_REVIEW_ERROR_FAILED = "review_failed"

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


def _parse_job_timestamp(value: Any) -> datetime | None:
    """Parse one ISO-8601 job timestamp as aware UTC, or return ``None``."""
    try:
        parsed = datetime.fromisoformat(str(value or "").strip().replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def parse_deep_review_job(value: Any) -> dict[str, Any] | None:
    """Return a normalized Deep Review job mapping, or ``None`` when absent.

    Args:
        value: Notebook ``settings_text`` job blob.

    Returns:
        A dictionary with the durable job fields, or ``None``.
    """
    if not isinstance(value, dict):
        return None
    review_id = str(value.get("review_id") or "").strip()
    status = str(value.get("status") or "").strip().lower()
    if not review_id or status not in DEEP_REVIEW_JOB_STATUSES:
        return None
    try:
        reviewed_revision = int(value.get("reviewed_revision") or 0)
    except (TypeError, ValueError):
        reviewed_revision = 0
    source_ids = [
        str(item).strip()
        for item in (value.get("source_ids") or [])
        if str(item).strip()
    ]
    message_ids = [
        str(item).strip()
        for item in (value.get("message_ids") or [])
        if str(item).strip()
    ]
    try:
        base_checkpoint_revision = int(value.get("base_checkpoint_revision"))
        if base_checkpoint_revision < 0:
            base_checkpoint_revision = None
    except (TypeError, ValueError):
        base_checkpoint_revision = None
    try:
        base_checkpoint_version = int(value.get("base_checkpoint_version"))
        if base_checkpoint_version < 1:
            base_checkpoint_version = None
    except (TypeError, ValueError):
        base_checkpoint_version = None
    return {
        "review_id": review_id,
        "status": status,
        "reviewed_revision": max(0, reviewed_revision),
        "stage_at_start": str(value.get("stage_at_start") or "").strip() or None,
        "source_ids": source_ids,
        "message_ids": message_ids,
        "base_checkpoint_revision": base_checkpoint_revision,
        "base_checkpoint_version": base_checkpoint_version,
        "started_at": str(value.get("started_at") or "").strip() or None,
        "updated_at": str(value.get("updated_at") or "").strip() or None,
        "error_code": str(value.get("error_code") or "").strip() or None,
    }


def deep_review_job_is_active(job: dict[str, Any] | None) -> bool:
    """Return whether *job* is still queued or running."""
    if not isinstance(job, dict):
        return False
    return str(job.get("status") or "").strip().lower() in DEEP_REVIEW_JOB_ACTIVE_STATUSES


def deep_review_job_is_stale(
    job: dict[str, Any] | None,
    timeout_seconds: int,
    *,
    now: datetime | None = None,
) -> bool:
    """Return whether an in-flight job has exceeded the operator timeout.

    Missing timestamps fail closed so a crashed worker cannot spin forever.

    Args:
        job: Parsed job mapping.
        timeout_seconds: ``DEEP_REVIEW_JOB_TIMEOUT_SECONDS``.
        now: Optional clock for tests.

    Returns:
        ``True`` when the job should be marked ``failed`` / ``review_timeout``.
    """
    if not deep_review_job_is_active(job):
        return False
    started = _parse_job_timestamp((job or {}).get("started_at")) or _parse_job_timestamp(
        (job or {}).get("updated_at")
    )
    if started is None:
        return True
    current = now or datetime.now(timezone.utc)
    return (current - started).total_seconds() > max(1, int(timeout_seconds))


def new_deep_review_job(
    *,
    review_id: str,
    reviewed_revision: int,
    stage_at_start: str,
    source_ids: list[str],
    message_ids: list[str],
    started_at: str,
    base_checkpoint_revision: int | None = None,
    base_checkpoint_version: int | None = None,
) -> dict[str, Any]:
    """Return a queued Deep Review job payload for notebook settings.

    Args:
        review_id: New job id.
        reviewed_revision: Conversation revision frozen at enqueue.
        stage_at_start: Thinking Path stage at enqueue.
        source_ids: Selected source ids frozen at enqueue.
        message_ids: Active message ids frozen at enqueue.
        started_at: UTC timestamp when the job was first persisted.
        base_checkpoint_revision: Prior checkpoint revision frozen at
            enqueue, when a checkpoint-capable snapshot exists.
        base_checkpoint_version: Prior checkpoint version frozen at enqueue.

    Returns:
        JSON-serialisable job dictionary.
    """
    payload: dict[str, Any] = {
        "review_id": str(review_id).strip(),
        "status": DEEP_REVIEW_JOB_QUEUED,
        "reviewed_revision": max(0, int(reviewed_revision)),
        "stage_at_start": str(stage_at_start or "").strip(),
        "source_ids": [str(item).strip() for item in source_ids if str(item).strip()],
        "message_ids": [str(item).strip() for item in message_ids if str(item).strip()],
        "started_at": str(started_at or "").strip(),
        "updated_at": str(started_at or "").strip(),
        "error_code": None,
        "base_checkpoint_revision": None,
        "base_checkpoint_version": None,
    }
    try:
        if base_checkpoint_revision is not None:
            payload["base_checkpoint_revision"] = max(0, int(base_checkpoint_revision))
    except (TypeError, ValueError):
        payload["base_checkpoint_revision"] = None
    try:
        if base_checkpoint_version is not None:
            payload["base_checkpoint_version"] = max(1, int(base_checkpoint_version))
    except (TypeError, ValueError):
        payload["base_checkpoint_version"] = None
    return payload


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
    completed_stages: list[str] | tuple[str, ...] | None = None,
    coaching_turns_since_deep_review: int | None = None,
    interval: int | None = None,
) -> bool:
    """Return whether the Thinking Path unlocks one explicit Deep Review.

    Unlock requires every required Thinking Path stage, including Reflection,
    to appear in ``completed_stages``. The legacy coaching-turn counter is
    ignored when ``completed_stages`` is supplied (the live gate). The
    counter/interval form remains only for older callers and tests.

    Args:
        completed_stages: Persisted completed stage ids.
        coaching_turns_since_deep_review: Legacy notebook counter (unused when
            ``completed_stages`` is provided).
        interval: Legacy ``DEEP_REVIEW_INTERVAL_TURNS`` (unused when
            ``completed_stages`` is provided).

    Returns:
        ``True`` when Deep Review may be enqueued.
    """
    if completed_stages is not None:
        done = {
            str(stage_id or "").strip()
            for stage_id in completed_stages
            if str(stage_id or "").strip()
        }
        required = {stage.id for stage in THINKING_STAGES}
        return required.issubset(done)
    current = parse_coaching_turns_since_deep_review(coaching_turns_since_deep_review)
    return current >= bound_deep_review_interval(interval)


JOURNEY_STAGE_REVIEWS_KEY = "journey_stage_reviews"
STAGE_REVIEW_QUEUED = "queued"
STAGE_REVIEW_RUNNING = "running"
STAGE_REVIEW_COMPLETE = "complete"
STAGE_REVIEW_FAILED = "failed"
STAGE_REVIEW_ACTIVE = frozenset({STAGE_REVIEW_QUEUED, STAGE_REVIEW_RUNNING})
STAGE_REVIEW_STATUSES = frozenset(
    {
        STAGE_REVIEW_QUEUED,
        STAGE_REVIEW_RUNNING,
        STAGE_REVIEW_COMPLETE,
        STAGE_REVIEW_FAILED,
    }
)

# These values are persisted as additive metadata on the existing
# ``journey_stage_reviews`` settings blob.  ``completion`` is the one-shot
# checkpoint written when a stage first completes.  ``revisit_exit`` is a
# coalesced refresh for substantive work made while the stage was already
# complete and then left.
STAGE_REVIEW_REASON_COMPLETION = "completion"
STAGE_REVIEW_REASON_REVISIT_EXIT = "revisit_exit"
STAGE_REVIEW_SCOPE_VERSION = 1


def stage_review_job_is_stale(
    job: dict[str, Any] | None,
    timeout_seconds: int,
    *,
    now: datetime | None = None,
) -> bool:
    """Return whether a running Journey review has exceeded its lease.

    Queued jobs are intentionally never considered stale: they are safe to
    resubmit after a process restart.  Running jobs carry an explicit lease
    expiry when created by the current implementation; older jobs fall back to
    their ``started_at``/``updated_at`` watermark for compatibility.

    Args:
        job: Parsed Journey stage-review job mapping.
        timeout_seconds: Maximum worker lease duration.
        now: Optional UTC clock for deterministic tests.

    Returns:
        ``True`` only for an expired running job (or a malformed running job
        with no usable timestamp).
    """
    if not isinstance(job, dict):
        return False
    if str(job.get("status") or "").strip().lower() != STAGE_REVIEW_RUNNING:
        return False
    current = now or datetime.now(timezone.utc)
    lease_expires = _parse_job_timestamp(job.get("lease_expires_at"))
    if lease_expires is not None:
        return current >= lease_expires
    started = _parse_job_timestamp(job.get("started_at")) or _parse_job_timestamp(
        job.get("updated_at")
    )
    if started is None:
        return True
    return (current - started).total_seconds() > max(1, int(timeout_seconds))


def empty_journey_stage_reviews() -> dict[str, Any]:
    """Return an empty durable Journey stage-review blob."""
    return {"jobs": {}, "reviews": {}, "unread": False, "revisit_dirty": {}}


def stage_reviews_need_attention(blob: dict[str, Any] | None) -> bool:
    """Return whether Journey/Review should show the unread stop badge.

    True when a checkpoint is unread, or a stage Haiku job is still queued or
    running (so the badge appears as soon as a stage completes, not only after
    the background checkpoint finishes).
    """
    parsed = parse_journey_stage_reviews(blob)
    if parsed.get("unread"):
        return True
    for job in (parsed.get("jobs") or {}).values():
        if not isinstance(job, dict):
            continue
        if str(job.get("status") or "") in STAGE_REVIEW_ACTIVE:
            return True
    return False


def parse_journey_stage_reviews(value: Any) -> dict[str, Any]:
    """Normalize the ``journey_stage_reviews`` settings blob.

    Args:
        value: Raw notebook settings value.

    Returns:
        ``{jobs, reviews, unread, revisit_dirty}`` with known stage ids only.
        Job metadata includes the durable id, reason, target token, frozen
        conversation/message scope, and optional worker lease fields.
    """
    base = empty_journey_stage_reviews()
    if not isinstance(value, dict):
        return base
    jobs_raw = value.get("jobs") if isinstance(value.get("jobs"), dict) else {}
    reviews_raw = value.get("reviews") if isinstance(value.get("reviews"), dict) else {}
    dirty_raw = (
        value.get("revisit_dirty")
        if isinstance(value.get("revisit_dirty"), dict)
        else {}
    )
    jobs: dict[str, Any] = {}
    reviews: dict[str, Any] = {}
    revisit_dirty: dict[str, Any] = {}
    for stage_id in STAGE_BY_ID:
        job = jobs_raw.get(stage_id)
        if isinstance(job, dict):
            status = str(job.get("status") or "").strip().lower()
            if status in STAGE_REVIEW_STATUSES:
                raw_job_id = str(
                    job.get("job_id") or job.get("review_id") or ""
                ).strip()
                try:
                    conversation_revision = int(
                        job.get("conversation_revision") or 0
                    )
                except (TypeError, ValueError):
                    conversation_revision = 0
                message_ids = [
                    str(item).strip()
                    for item in (job.get("message_ids") or [])
                    if str(item).strip()
                ][:256]
                try:
                    scope_version = int(job.get("scope_version") or 0)
                except (TypeError, ValueError):
                    scope_version = 0
                jobs[stage_id] = {
                    "status": status,
                    "job_id": raw_job_id or None,
                    # ``review_id`` is retained as a compatibility alias for
                    # callers that modelled Deep Review jobs similarly.
                    "review_id": raw_job_id or None,
                    "reason": (
                        str(job.get("reason") or "").strip()
                        or STAGE_REVIEW_REASON_COMPLETION
                    ),
                    "target_token": str(job.get("target_token") or "").strip()
                    or None,
                    "conversation_revision": max(0, conversation_revision),
                    "message_ids": message_ids,
                    "scope_frozen": job.get("scope_frozen") is True,
                    "scope_version": max(0, scope_version),
                    "updated_at": str(job.get("updated_at") or "").strip() or None,
                    "started_at": str(job.get("started_at") or "").strip() or None,
                    "lease_token": str(job.get("lease_token") or "").strip() or None,
                    "lease_expires_at": str(
                        job.get("lease_expires_at") or ""
                    ).strip()
                    or None,
                    "error_code": str(job.get("error_code") or "").strip() or None,
                }
        review = reviews_raw.get(stage_id)
        if isinstance(review, dict):
            cleaned = normalize_stage_checkpoint(review, stage_id=stage_id)
            if cleaned is not None:
                reviews[stage_id] = cleaned
        dirty = dirty_raw.get(stage_id)
        if isinstance(dirty, str):
            # Accept a compact token-only legacy shape and normalize it to the
            # richer additive marker used by current writers.
            token = dirty.strip()
            dirty_revision = 0
            dirty_updated_at = None
        elif isinstance(dirty, dict):
            token = str(dirty.get("token") or "").strip()
            if token:
                try:
                    dirty_revision = int(dirty.get("conversation_revision") or 0)
                except (TypeError, ValueError):
                    dirty_revision = 0
                dirty_updated_at = (
                    str(dirty.get("updated_at") or "").strip() or None
                )
            else:
                dirty_revision = 0
                dirty_updated_at = None
        else:
            token = ""
            dirty_revision = 0
            dirty_updated_at = None
        if token:
            revisit_dirty[stage_id] = {
                "token": token,
                "conversation_revision": max(0, dirty_revision),
                "updated_at": dirty_updated_at,
            }
    return {
        "jobs": jobs,
        "reviews": reviews,
        "unread": bool(value.get("unread")),
        "revisit_dirty": revisit_dirty,
    }


_FACIONE_CHECKPOINT_KEYS = (
    "analysis",
    "interpretation",
    "inference",
    "evaluation",
    "explanation",
    "self_regulation",
)


def _normalize_checkpoint_facione_scores(raw: Any) -> dict[str, int]:
    """Clamp optional Haiku Facione scores to the 0–4 Review contract."""
    source = raw if isinstance(raw, dict) else {}
    normalized: dict[str, int] = {}
    for key in _FACIONE_CHECKPOINT_KEYS:
        try:
            value = int(source.get(key, 0))
        except (TypeError, ValueError):
            value = 0
        normalized[key] = max(0, min(4, value))
    return normalized


def normalize_stage_checkpoint(
    value: Any, *, stage_id: str
) -> dict[str, Any] | None:
    """Return one compact Journey stage checkpoint, or ``None`` when empty.

    Optional ``facione_scores`` and ``conversation_revision`` are preserved so
    Review can project Critical Thinking and revisit refresh can compare
    notebook watermarks.
    """
    if not isinstance(value, dict):
        return None
    cleaned_stage = str(stage_id or value.get("stage") or "").strip()
    if cleaned_stage not in STAGE_BY_ID:
        return None
    strengths = _compact_stage_review_items(value.get("strengths"), limit=4)
    areas = _compact_stage_review_items(
        value.get("areas_to_revisit") or value.get("areas_to_develop"),
        limit=4,
    )
    summary = " ".join(str(value.get("summary") or "").split()).strip()[:600]
    reasoning = " ".join(
        str(value.get("reasoning_progress") or "").split()
    ).strip()[:400]
    message_ids = [
        str(item).strip()
        for item in (value.get("important_message_ids") or [])
        if str(item).strip()
    ][:16]
    artifacts_raw = value.get("important_artifacts")
    artifacts: dict[str, str] = {}
    if isinstance(artifacts_raw, dict):
        for key, item in artifacts_raw.items():
            cleaned_key = str(key or "").strip()[:64]
            cleaned_item = " ".join(str(item or "").split()).strip()[:400]
            if cleaned_key and cleaned_item:
                artifacts[cleaned_key] = cleaned_item
            if len(artifacts) >= 8:
                break
    facione_scores = _normalize_checkpoint_facione_scores(
        value.get("facione_scores") or value.get("facione_profile")
    )
    try:
        conversation_revision = int(value.get("conversation_revision") or 0)
    except (TypeError, ValueError):
        conversation_revision = 0
    conversation_revision = max(0, conversation_revision)
    if not (summary or strengths or areas or reasoning or artifacts):
        return None
    return {
        "stage": cleaned_stage,
        "summary": summary,
        "strengths": strengths,
        "areas_to_revisit": areas,
        "reasoning_progress": reasoning,
        "important_message_ids": message_ids,
        "important_artifacts": artifacts,
        "facione_scores": facione_scores,
        "conversation_revision": conversation_revision,
    }


def public_journey_stage_reviews(value: Any) -> dict[str, Any]:
    """Project durable Journey review metadata for the student-facing API.

    Internal queue records carry fencing ids, dirty tokens, frozen transcript
    ids, and worker lease timestamps.  Those implementation details must not
    become part of the existing student API contract.  This projection keeps
    the historical top-level shape and the prior job status timestamps/error
    fields while retaining normalized checkpoint content.

    Args:
        value: Raw or normalized ``journey_stage_reviews`` metadata.

    Returns:
        A public ``{jobs, reviews, unread}`` mapping with no queue internals.
    """
    parsed = parse_journey_stage_reviews(value)
    jobs: dict[str, dict[str, Any]] = {}
    for stage_id, job in (parsed.get("jobs") or {}).items():
        if not isinstance(job, dict):
            continue
        jobs[stage_id] = {
            "status": job.get("status"),
            "updated_at": job.get("updated_at"),
            "error_code": job.get("error_code"),
        }
    # ``important_message_ids`` is useful to internal stage-history tooling,
    # but it is still transcript metadata and must not cross the student API
    # boundary.  Keep the public review shape and all pedagogical fields while
    # omitting that internal linkage field.
    reviews: dict[str, dict[str, Any]] = {}
    for stage_id, review in (parsed.get("reviews") or {}).items():
        if not isinstance(review, dict):
            continue
        public_review = dict(review)
        public_review.pop("important_message_ids", None)
        reviews[stage_id] = public_review
    return {
        "jobs": jobs,
        "reviews": reviews,
        "unread": bool(parsed.get("unread")),
    }


def stage_review_should_enqueue(
    blob: dict[str, Any] | None,
    *,
    stage_id: str,
    notebook_revision: int | None = None,
) -> bool:
    """Return whether one stage still needs a Journey Haiku review queued.

    Queued/running jobs stay exclusive. A completed checkpoint may re-queue
    when ``notebook_revision`` is strictly newer than the checkpoint watermark
    (student revisited an already-completed stage after a later coach turn).
    """
    cleaned = str(stage_id or "").strip()
    if cleaned not in STAGE_BY_ID:
        return False
    parsed = parse_journey_stage_reviews(blob)
    status = str((parsed["jobs"].get(cleaned) or {}).get("status") or "")
    if status in STAGE_REVIEW_ACTIVE:
        return False
    if status == STAGE_REVIEW_COMPLETE:
        if notebook_revision is None:
            return False
        try:
            revision = int(notebook_revision)
        except (TypeError, ValueError):
            return False
        review = parsed["reviews"].get(cleaned) or {}
        try:
            watermark = int(review.get("conversation_revision") or 0)
        except (TypeError, ValueError):
            watermark = 0
        return revision > max(0, watermark)
    return True


def newly_completed_stage_ids(
    before: list[str] | tuple[str, ...] | None,
    after: list[str] | tuple[str, ...] | None,
) -> list[str]:
    """Return newly completed stage ids in Thinking Path order."""
    before_set = {str(item).strip() for item in (before or []) if str(item).strip()}
    after_list = [str(item).strip() for item in (after or []) if str(item).strip()]
    added = [stage_id for stage_id in after_list if stage_id not in before_set]
    order = {stage.id: index for index, stage in enumerate(THINKING_STAGES)}
    return sorted(
        (stage_id for stage_id in added if stage_id in order),
        key=lambda stage_id: order[stage_id],
    )


def _compact_stage_review_items(values: Any, *, limit: int = 8) -> list[str]:
    """Normalize one Deep Review bullet list without empty or duplicate items."""
    if not isinstance(values, list):
        return []
    cleaned: list[str] = []
    seen: set[str] = set()
    for value in values:
        item = " ".join(str(value or "").split()).strip()[:400]
        if not item:
            continue
        key = item.lower()
        if key in seen:
            continue
        seen.add(key)
        cleaned.append(item)
        if len(cleaned) >= limit:
            break
    return cleaned


def represented_thinking_path_stages(
    messages: list[dict[str, Any]] | None,
    *,
    fallback_stage: str = "",
) -> frozenset[str]:
    """Return Thinking Path stages evidenced in a frozen conversation.

    Uses persisted ``thinking_stage`` / ``assessment.current_stage`` metadata
    plus the enqueue-time fallback stage. Future stages with no messages are
    not included.

    Args:
        messages: Frozen active-branch messages at Deep Review enqueue.
        fallback_stage: Stage id frozen when Deep Review started.

    Returns:
        Canonical stage ids that appear in the frozen snapshot.
    """
    found: set[str] = set()
    fallback = str(fallback_stage or "").strip()
    if fallback in STAGE_BY_ID:
        found.add(fallback)
    for message in messages or []:
        if not isinstance(message, dict):
            continue
        metadata = message.get("metadata")
        if not isinstance(metadata, dict):
            continue
        for key in ("thinking_stage", "current_stage"):
            stage_id = str(metadata.get(key) or "").strip()
            if stage_id in STAGE_BY_ID:
                found.add(stage_id)
        assessment = metadata.get("assessment")
        if isinstance(assessment, dict):
            stage_id = str(assessment.get("current_stage") or "").strip()
            if stage_id in STAGE_BY_ID:
                found.add(stage_id)
    return frozenset(found)


def normalize_deep_review_stage_reviews(
    raw: Any,
    *,
    allowed_stage_ids: frozenset[str] | set[str] | None = None,
) -> list[dict[str, Any]]:
    """Validate Deep Review ``stage_reviews`` for persistence and projection.

    Unknown stage identifiers are dropped. Duplicate stage ids are merged.
    Entries with both lists empty are omitted. When ``allowed_stage_ids`` is
    provided, stages without conversation evidence are dropped.

    Args:
        raw: Model or snapshot ``stage_reviews`` value.
        allowed_stage_ids: Optional set of stages represented in the frozen
            transcript. ``None`` disables that filter.

    Returns:
        Ordered list of ``{stage_id, strengths, areas_to_develop}`` dicts.
    """
    if not isinstance(raw, list):
        return []
    merged: dict[str, dict[str, list[str]]] = {}
    for item in raw:
        if not isinstance(item, dict):
            continue
        stage_id = str(item.get("stage_id") or "").strip()
        if stage_id not in STAGE_BY_ID:
            continue
        if allowed_stage_ids is not None and stage_id not in allowed_stage_ids:
            continue
        strengths = _compact_stage_review_items(item.get("strengths"))
        areas = _compact_stage_review_items(item.get("areas_to_develop"))
        supporting_ids: list[str] = []
        seen_ids: set[str] = set()
        for message_id in item.get("supporting_message_ids") or []:
            cleaned = str(message_id or "").strip()
            if not cleaned or cleaned in seen_ids:
                continue
            seen_ids.add(cleaned)
            supporting_ids.append(cleaned)
            if len(supporting_ids) >= 3:
                break
        existing = merged.get(stage_id)
        if existing is None:
            merged[stage_id] = {
                "strengths": strengths,
                "areas_to_develop": areas,
                "supporting_message_ids": supporting_ids,
            }
            continue
        existing["strengths"] = _compact_stage_review_items(
            [*existing["strengths"], *strengths]
        )
        existing["areas_to_develop"] = _compact_stage_review_items(
            [*existing["areas_to_develop"], *areas]
        )
        merged_ids = list(existing.get("supporting_message_ids") or [])
        for message_id in supporting_ids:
            if message_id not in merged_ids:
                merged_ids.append(message_id)
            if len(merged_ids) >= 3:
                break
        existing["supporting_message_ids"] = merged_ids
    payload: list[dict[str, Any]] = []
    for stage in THINKING_STAGES:
        row = merged.get(stage.id)
        if row is None:
            continue
        if not row["strengths"] and not row["areas_to_develop"]:
            continue
        payload.append(
            {
                "stage_id": stage.id,
                "strengths": list(row["strengths"]),
                "areas_to_develop": list(row["areas_to_develop"]),
                "supporting_message_ids": list(row.get("supporting_message_ids") or []),
            }
        )
    return payload


def deep_review_stage_reviews_for_snapshot(
    raw: Any,
    *,
    history: list[dict[str, Any]] | None = None,
    fallback_stage: str = "",
) -> list[dict[str, Any]]:
    """Filter model ``stage_reviews`` to stages in the frozen conversation.

    Args:
        raw: Provider ``review_stage_feedback`` or model ``stage_reviews``.
        history: Frozen active messages reconstructed for this job.
        fallback_stage: Stage id frozen at enqueue.

    Returns:
        Snapshot-ready ``stage_reviews`` list. Empty when none are valid.
    """
    allowed = represented_thinking_path_stages(
        history, fallback_stage=fallback_stage
    )
    return normalize_deep_review_stage_reviews(
        raw, allowed_stage_ids=allowed
    )


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
    reviewed_stage_id: str = "",
    stage_reviews: list[dict[str, Any]] | None = None,
    reviewed_message_ids: list[str] | None = None,
    source_ids: list[str] | None = None,
    checkpoint_version: int | None = None,
) -> dict[str, Any]:
    """Return the durable Deep Review snapshot stored in notebook settings.

    Hidden prompts are never included. Normal Coaching persist must omit this
    key so a later Haiku turn cannot overwrite the snapshot. ``reviewed_stage_id``
    is the Thinking Path stage frozen at enqueue, not the stage at completion.
    ``stage_reviews`` is the authoritative per-stage Strengths / Areas
    projection when non-empty. Older snapshots omit that key.
    Checkpoint-capable snapshots also persist ``checkpoint_version``,
    ``reviewed_message_ids``, and ``source_ids`` without duplicating message
    content.

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
        reviewed_stage_id: Stage id frozen when Deep Review started.
        stage_reviews: Optional per-stage strengths, areas, and supporting ids.
        reviewed_message_ids: Frozen active message ids reviewed, ids only.
        source_ids: Frozen selected-source ids used for this review.
        checkpoint_version: Internal marker distinguishing compact-capable
            snapshots. Omit for legacy callers; successful new reviews pass 1.

    Returns:
        JSON-serialisable snapshot dictionary.
    """
    normalized_reviews = normalize_deep_review_stage_reviews(stage_reviews or [])
    payload: dict[str, Any] = {
        "reviewed_through_revision": max(0, int(conversation_revision)),
        "reviewed_stage_id": str(reviewed_stage_id or "").strip(),
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
    # A supplied list is the new stage-aware contract, including an explicit
    # empty list.  Omitting the argument preserves the legacy v24 snapshot
    # shape, so projection can distinguish "no field" from "intentionally []".
    if stage_reviews is not None:
        payload["stage_reviews"] = normalized_reviews
        payload["stage_reviews_contract"] = "v1"
    if checkpoint_version is not None:
        try:
            payload["checkpoint_version"] = max(1, int(checkpoint_version))
        except (TypeError, ValueError):
            pass
    if reviewed_message_ids is not None:
        seen: set[str] = set()
        ids: list[str] = []
        for item in reviewed_message_ids:
            cleaned = str(item or "").strip()
            if not cleaned or cleaned in seen:
                continue
            seen.add(cleaned)
            ids.append(cleaned)
        payload["reviewed_message_ids"] = ids
    if source_ids is not None:
        payload["source_ids"] = [
            str(item).strip() for item in source_ids if str(item).strip()
        ]
    return payload
