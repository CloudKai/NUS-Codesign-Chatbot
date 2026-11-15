"""Bound anonymous workspace creation in the single-worker API process.

Admission is global rather than per IP so a shared classroom network can
arrive together. Counters reset on process restart; multiple workers require
a shared admission adapter before relying on the same deployment-wide bounds.
"""

from collections import deque
import math
import threading
import time
from collections.abc import Callable

from backend.rate_limit import RateLimitExceeded


class GuestAdmissionLimiter:
    """Atomically reserve bounded new-Guest starts without retaining identities."""

    def __init__(
        self, *, per_minute: int = 120, per_hour: int = 480,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        """Set a positive creation ceiling and injectable monotonic clock."""
        self._per_minute = max(1, per_minute)
        self._per_hour = max(1, per_hour)
        self._clock = clock
        self._recent: deque[float] = deque()
        self._lock = threading.Lock()

    def admit(self) -> None:
        """Reserve before any owner/session insert, or raise with a retry delay.

        Failed creations retain their reservation conservatively. Rejected
        attempts never grow the bounded timestamp queue.
        """
        with self._lock:
            now = self._clock()
            while self._recent and now - self._recent[0] >= 3600:
                self._recent.popleft()
            waits: list[float] = []
            if len(self._recent) >= self._per_hour:
                waits.append(3600 - (now - self._recent[0]))
            if len(self._recent) >= self._per_minute:
                waits.append(60 - (now - self._recent[-self._per_minute]))
            retry_after = max(waits, default=0)
            if retry_after > 0:
                raise RateLimitExceeded(
                    max(1, math.ceil(retry_after)),
                    "Guest entry is busy. Please retry after the indicated wait; "
                    "if it continues, ask your lecturer for help.",
                    category="guest_admission",
                )
            self._recent.append(now)
