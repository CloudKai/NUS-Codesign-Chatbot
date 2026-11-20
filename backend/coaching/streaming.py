"""Shared dispatch, preview, saved, and error events for both chat transports."""

from collections.abc import Callable, Iterator
import queue
import threading
from typing import Any

from backend.coaching.execution import CoachApplicationService
from backend.coaching.progress import PROGRESS_LABELS
from backend.coaching.stream_events import COACH_EVENT_ADAPTER
from backend.domain import CoachRequest
from backend.providers import ProviderUnavailableError, provider_error_category
from backend.rate_limit import RateLimitExceeded
from backend.student_store import (
    CoachIdempotencyConflictError,
    CoachRequestInProgressError,
    CoachRequestLeaseLostError,
    ConversationRevisionConflictError,
)


def _stream_error_payload(error: BaseException) -> dict[str, Any]:
    """Map worker failures to terminal events without leaking storage details."""
    if isinstance(error, RateLimitExceeded):
        return {"event": "error", "detail": error.detail, "status": 429,
                "category": error.category, "retry_after": max(1, int(error.retry_after_seconds))}
    if isinstance(error, (CoachIdempotencyConflictError, CoachRequestInProgressError,
                          CoachRequestLeaseLostError, ConversationRevisionConflictError)):
        return {"event": "error", "detail": str(error), "status": 409}
    if isinstance(error, ProviderUnavailableError):
        return {"event": "error", "detail": str(error), "status": 503,
                "category": provider_error_category(error)}
    if isinstance(error, ValueError):
        return {"event": "error", "detail": str(error), "status": 400}
    return {"event": "error", "detail": "The coach reply could not be saved. Please retry.",
            "status": 503, "category": "unavailable"}


def stream_error(error: BaseException) -> dict[str, Any]:
    """Validate and serialize the same safe terminal error for both transports."""
    return COACH_EVENT_ADAPTER.validate_python(_stream_error_payload(error)).model_dump(
        mode="json", exclude_none=True
    )


def coach_events(
    coach: CoachApplicationService,
    request: CoachRequest,
    *,
    before_submit: Callable[[], None] | None = None,
    reply_deltas: bool = False,
) -> Iterator[dict[str, Any] | BaseException]:
    """Dispatch once before acknowledging; finish saving even if a reader leaves.

    ``started`` acknowledges worker dispatch, not durable completion. Only
    ``done`` acknowledges a saved turn. Exceptions are returned to the transport
    for logging and conversion with ``stream_error``; previews remain ephemeral.

    ``reply_deltas`` adds ``reply_delta`` events (unvalidated partial reply
    text) and ``reply_discard``. Transports pass it only for clients that asked
    for deltas, so older clients still see the original event set. Whenever a
    turn ends in failure after text was previewed, ``reply_discard`` precedes
    the terminal error.
    """
    bus: queue.SimpleQueue[dict[str, Any] | BaseException | None] = queue.SimpleQueue()

    def progress(phase: str) -> None:
        bus.put({"event": "status", "phase": phase, "label": PROGRESS_LABELS.get(phase, "")})

    def reply(text: str) -> None:
        bus.put({"event": "reply_ready", "text": text})

    previewed = False

    def reply_delta(text: str | None) -> None:
        nonlocal previewed
        if text is None:
            if previewed:
                previewed = False
                bus.put({"event": "reply_discard"})
            return
        previewed = True
        bus.put({"event": "reply_delta", "text": text})

    def worker() -> None:
        try:
            if before_submit is not None:
                before_submit()
            turn = coach.submit(
                request,
                progress=progress,
                reply=reply,
                **({"reply_delta": reply_delta} if reply_deltas else {}),
            )
            bus.put({"event": "done", "turn": turn.model_dump(mode="json")})
        except BaseException as error:
            if reply_deltas and previewed:
                bus.put({"event": "reply_discard"})
            bus.put(error)
        finally:
            bus.put(None)

    threading.Thread(target=worker, name="coach-turn-stream", daemon=True).start()
    yield COACH_EVENT_ADAPTER.validate_python({
        "event": "started", "thread_id": request.thread_id,
        "stage": request.current_stage, "idempotency_key": request.idempotency_key,
    }).model_dump(mode="json")
    while (item := bus.get()) is not None:
        if isinstance(item, BaseException):
            yield item
        else:
            yield COACH_EVENT_ADAPTER.validate_python(item).model_dump(mode="json")
