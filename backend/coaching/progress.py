"""Request-scoped coaching progress events for FastAPI NDJSON streaming.

Application code emits phase names only. FastAPI maps them to student-visible
labels. Streamlit is never imported here.
"""

from __future__ import annotations

from collections.abc import Callable
from contextvars import ContextVar, Token

PROGRESS_RETRIEVING = "retrieving"
PROGRESS_THINKING = "thinking"
PROGRESS_SAVING = "saving"

PROGRESS_LABELS = {
    PROGRESS_RETRIEVING: "Searching course materials…",
    PROGRESS_THINKING: "Coach is thinking…",
    PROGRESS_SAVING: "Saving response…",
}

CoachProgressCallback = Callable[[str], None]

_progress_callback: ContextVar[CoachProgressCallback | None] = ContextVar(
    "coach_progress_callback", default=None
)


class coach_progress:
    """Bind a progress callback for the current turn.

    Implemented as a class-based context manager so frozen exception types
    such as ``RateLimitExceeded`` can propagate. ``@contextmanager`` would
    try to assign ``__traceback__`` on those instances.
    """

    def __init__(self, callback: CoachProgressCallback | None) -> None:
        self._callback = callback
        self._token: Token[CoachProgressCallback | None] | None = None

    def __enter__(self) -> coach_progress:
        self._token = _progress_callback.set(self._callback)
        return self

    def __exit__(self, *_exc: object) -> bool:
        if self._token is not None:
            _progress_callback.reset(self._token)
            self._token = None
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
