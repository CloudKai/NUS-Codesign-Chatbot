"""Process-local background executor for Deep Review jobs.

Production runs one Uvicorn worker, so this in-process pool is the job
runtime. The job envelope itself is durable: queued/claimed work left behind
by a restart is recovered on the next owner read (``get_deep_review_job``)
within the bounded attempt budget, and stale claims past that budget fail
honestly with ``review_timeout``.
"""

from __future__ import annotations

import logging
import threading
from concurrent.futures import ThreadPoolExecutor
from typing import TYPE_CHECKING

from backend.settings import settings as runtime_settings

if TYPE_CHECKING:
    from backend.coaching.execution import CoachApplicationService

logger = logging.getLogger(__name__)

_LOCK = threading.Lock()
_EXECUTOR: ThreadPoolExecutor | None = None
_SUBMITTED: set[str] = set()


def get_deep_review_executor() -> ThreadPoolExecutor:
    """Return the process-wide Deep Review worker pool."""
    global _EXECUTOR
    with _LOCK:
        if _EXECUTOR is None:
            workers = max(1, int(runtime_settings.deep_review_max_concurrent))
            _EXECUTOR = ThreadPoolExecutor(
                max_workers=workers,
                thread_name_prefix="deep-review",
            )
        return _EXECUTOR


def submit_deep_review_job(
    service: CoachApplicationService,
    thread_id: str,
    review_id: str,
) -> bool:
    """Enqueue one Deep Review worker if *review_id* is not already submitted.

    Args:
        service: Owner-scoped coaching application service.
        thread_id: Owned notebook id.
        review_id: Persisted job id.

    Returns:
        ``True`` when a new worker was dispatched in this process, ``False``
        when the id is already submitted here or admission refused it. This
        lets read seams distinguish "recovery started a worker" from "a
        worker is already live" without exposing internals.

    Side effects:
        Starts a daemon worker that calls ``execute_deep_review_job``.
    """
    cleaned_id = str(review_id or "").strip()
    if not cleaned_id:
        return False
    with _LOCK:
        if cleaned_id in _SUBMITTED:
            return False
        _SUBMITTED.add(cleaned_id)

    def _run() -> None:
        try:
            service.execute_deep_review_job(thread_id, cleaned_id)
        except Exception:
            logger.exception("deep_review_worker_failed review_id=%s", cleaned_id)
        finally:
            with _LOCK:
                _SUBMITTED.discard(cleaned_id)

    from backend.coaching.background_admission import background_review_admission

    def reject(category: str) -> None:
        """Persist admission rejection and release the local duplicate guard."""
        try:
            service.reject_background_review(thread_id, cleaned_id, category)
        finally:
            with _LOCK:
                _SUBMITTED.discard(cleaned_id)

    accepted = background_review_admission().submit(
        get_deep_review_executor(), _run, reject
    )
    if not accepted:
        with _LOCK:
            _SUBMITTED.discard(cleaned_id)
    return accepted


def reset_deep_review_jobs_for_tests() -> None:
    """Drop the in-process executor so tests do not leak worker threads."""
    shutdown_deep_review_executor()


def shutdown_deep_review_executor() -> None:
    """Stop accepting new Deep Review work and drop the process-local pool.

    Clean-shutdown seam for the FastAPI lifespan: queued-but-unstarted
    dispatches are cancelled locally while their durable envelopes stay
    ``queued`` for the next owner read, and running workers are left to
    finish their current bounded phase (lease expiry plus bounded recovery
    covers a process that exits first). Never blocks on provider work.
    """
    global _EXECUTOR
    with _LOCK:
        executor = _EXECUTOR
        _EXECUTOR = None
        _SUBMITTED.clear()
    if executor is not None:
        executor.shutdown(wait=False, cancel_futures=True)
