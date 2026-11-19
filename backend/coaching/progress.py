"""Request-scoped coaching status and validated reply preview events.

Application code emits phase names and the final reply before persistence.
FastAPI maps phases to student-visible labels. Streamlit is never imported here.
"""

from __future__ import annotations

from collections.abc import Callable
from contextvars import ContextVar, Token

PROGRESS_RETRIEVING = "retrieving"
PROGRESS_THINKING = "thinking"
PROGRESS_SAVING = "saving"

PROGRESS_LABELS = {
    "queued": "Waiting for a generation slot (up to 30 seconds)…",
    PROGRESS_RETRIEVING: "Searching course materials…",
    PROGRESS_THINKING: "Coach is thinking…",
    PROGRESS_SAVING: "Saving response…",
}

CoachProgressCallback = Callable[[str], None]
CoachReplyCallback = Callable[[str], None]
# A string is an unvalidated partial reply fragment; ``None`` withdraws every
# fragment sent so far (the attempt will be redone or has failed).
CoachReplyDeltaCallback = Callable[[str | None], None]

_progress_callback: ContextVar[CoachProgressCallback | None] = ContextVar(
    "coach_progress_callback", default=None
)
_reply_callback: ContextVar[CoachReplyCallback | None] = ContextVar(
    "coach_reply_callback", default=None
)
_reply_delta_callback: ContextVar[CoachReplyDeltaCallback | None] = ContextVar(
    "coach_reply_delta_callback", default=None
)


class coach_progress:
    """Bind a progress callback for the current turn.

    Implemented as a class-based context manager so frozen exception types
    such as ``RateLimitExceeded`` can propagate. ``@contextmanager`` would
    try to assign ``__traceback__`` on those instances.
    """

    def __init__(
        self,
        callback: CoachProgressCallback | None,
        reply: CoachReplyCallback | None = None,
        reply_delta: CoachReplyDeltaCallback | None = None,
    ) -> None:
        self._callback = callback
        self._reply = reply
        self._reply_delta = reply_delta
        self._token: Token[CoachProgressCallback | None] | None = None
        self._reply_token: Token[CoachReplyCallback | None] | None = None
        self._delta_token: Token[CoachReplyDeltaCallback | None] | None = None

    def __enter__(self) -> coach_progress:
        self._token = _progress_callback.set(self._callback)
        self._reply_token = _reply_callback.set(self._reply)
        self._delta_token = _reply_delta_callback.set(self._reply_delta)
        return self

    def __exit__(self, *_exc: object) -> bool:
        if self._token is not None:
            _progress_callback.reset(self._token)
            self._token = None
        if self._reply_token is not None:
            _reply_callback.reset(self._reply_token)
            self._reply_token = None
        if self._delta_token is not None:
            _reply_delta_callback.reset(self._delta_token)
            self._delta_token = None
        return False


def emit_coach_progress(phase: str) -> None:
    """Notify the bound callback of one execution-boundary phase.

    Args:
        phase: One of the ``PROGRESS_*`` constants. Unknown values are ignored.
    """
    cleaned = str(phase or "").strip().casefold()
    if cleaned not in PROGRESS_LABELS:
        return
    callback = _progress_callback.get()
    if callback is None:
        return
    callback(cleaned)


def emit_coach_reply_ready(response_text: str) -> None:
    """Send a validated final reply to this request's preview before persistence.

    The preview is ephemeral. The saved ``CoachTurn`` remains authoritative and
    callers must clear the preview if persistence fails.
    """
    callback = _reply_callback.get()
    if callback is not None and response_text.strip():
        callback(response_text)


def reply_delta_sink_bound() -> bool:
    """Report whether this request wants partial reply text from its provider."""
    return _reply_delta_callback.get() is not None


def emit_coach_reply_delta(text: str) -> None:
    """Send one unvalidated partial reply fragment to this request's preview.

    Providers call this only with text the model produced for the final reply.
    It is ephemeral: the validated ``reply_ready`` text and the saved turn stay
    authoritative, and no caller may persist a fragment. A no-op when no
    callback is bound or the fragment is empty.
    """
    callback = _reply_delta_callback.get()
    if callback is not None and text:
        callback(text)


def emit_coach_reply_discard() -> None:
    """Withdraw every fragment sent so far, before another attempt is made."""
    callback = _reply_delta_callback.get()
    if callback is not None:
        callback(None)
