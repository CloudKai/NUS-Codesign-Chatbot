"""Bound retained background review work and expire waits without browser polling."""

from __future__ import annotations

import threading
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from functools import lru_cache

from backend.settings import settings


class BackgroundReviewAdmission:
    """Share one finite process-local count across Deep Review and checkpoints."""

    def __init__(self) -> None:
        """Create the lock and retained running/queued submission counter."""
        self._lock = threading.Lock()
        self._active = 0

    def submit(
        self, executor: ThreadPoolExecutor, work: Callable[[], None],
        reject: Callable[[str], None],
    ) -> bool:
        """Submit within capacity; expire queued work independently.

        Running jobs retain their slot until completion. The timer cannot kill
        running provider work; the shared durable generation ledger bounds that
        work separately. Rejected callbacks persist safe terminal job status.

        Returns:
            ``True`` when the work was dispatched to the executor. A ``False``
            return means ``reject`` already persisted the refusal; a ``True``
            return means dispatch happened, while the bounded wait timer may
            still expire the wait later (existing honest semantics).
        """
        with self._lock:
            accepted = self._active < settings.generation_background_jobs
            if accepted:
                self._active += 1
        if not accepted:
            reject("generation_capacity")
            return False
        started = threading.Event()
        gate = threading.Lock()
        expired = False

        def run() -> None:
            nonlocal expired
            with gate:
                if expired:
                    return
                started.set()
            work()

        try:
            future = executor.submit(run)
        except RuntimeError:
            with self._lock:
                self._active -= 1
            reject("generation_unavailable")
            return False

        def expire() -> None:
            nonlocal expired
            with gate:
                if started.is_set():
                    return
                expired = True
            # Mark expired before cancelling: even if dispatch wins the race,
            # the wrapper refuses to invoke the application work.
            reject("generation_wait")
            # Keep the retained-work slot until the executor consumes the wrapper.
            # Cancelling releases Future callbacks but leaves its work item queued,
            # allowing repeated expired submissions to accumulate without bound.

        timer = threading.Timer(settings.generation_background_wait_seconds, expire)
        timer.daemon = True

        def done(_future: object) -> None:
            timer.cancel()
            with self._lock:
                self._active -= 1

        future.add_done_callback(done)
        if not future.done():
            timer.start()
        return True


@lru_cache(maxsize=1)
def background_review_admission() -> BackgroundReviewAdmission:
    """Return the shared process-local review admission service."""
    return BackgroundReviewAdmission()
