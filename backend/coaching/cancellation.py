"""Explicit cancellation for streamed turns on the single-worker app."""

from collections.abc import Callable, Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from threading import Lock


class TurnCancelled(Exception):
    """A student stopped generation before reply persistence began."""

    category = "cancelled"


class TurnCancellation:
    """Decide the race between Stop and saving, and release active streams."""

    def __init__(self) -> None:
        self._lock = Lock()
        self._cancelled = False
        self._saving = False
        self._close: Callable[[], None] | None = None

    def stop(self) -> bool:
        """Cancel before saving starts and close the current provider stream."""
        with self._lock:
            if self._saving:
                return False
            self._cancelled = True
            close, self._close = self._close, None
        if close is not None:
            _close_stream(close)
        return True

    def check(self, *, saving: bool = False) -> None:
        """Raise if stopped, or declare that the turn has reached saving."""
        with self._lock:
            if self._cancelled:
                raise TurnCancelled()
            if saving:
                self._saving = True

    def set_close(self, close: Callable[[], None] | None) -> None:
        """Attach a provider stream closer or release it after reading."""
        with self._lock:
            if not self._cancelled or close is None:
                self._close = close
                return
        _close_stream(close)
        raise TurnCancelled()


def _close_stream(close: Callable[[], None]) -> None:
    try:
        close()
    except Exception:
        # A racing provider read can already have closed the transport.
        pass


_active: ContextVar[TurnCancellation | None] = ContextVar("turn_cancellation", default=None)


@contextmanager
def bind_turn_cancellation(value: TurnCancellation | None) -> Iterator[None]:
    """Bind one worker's cancellation signal for cooperative checkpoints."""
    token = _active.set(value)
    try:
        yield
    finally:
        _active.reset(token)


def check_turn_cancelled(*, saving: bool = False) -> None:
    """Check the current streamed turn, if any."""
    if current := _active.get():
        current.check(saving=saving)


def register_stream_closer(close: Callable[[], None] | None) -> None:
    """Connect a provider stream to the current turn's stop control."""
    if current := _active.get():
        current.set_close(close)
