"""Process-local background executor for Deep Review jobs.

Production runs one Uvicorn worker, so this in-process pool is the job
runtime. Jobs persisted as ``queued``/``running`` are lost on restart; the
next GET marks them ``failed`` / ``review_timeout``.
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
) -> None:
    """Enqueue one Deep Review worker if *review_id* is not already submitted.

    Args:
        service: Owner-scoped coaching application service.
        thread_id: Owned notebook id.
        review_id: Persisted job id.

    Side effects:
        Starts a daemon worker that calls ``execute_deep_review_job``.
    """
    cleaned_id = str(review_id or "").strip()
    if not cleaned_id:
        return
    with _LOCK:
        if cleaned_id in _SUBMITTED:
            return
        _SUBMITTED.add(cleaned_id)

    def _run() -> None:
        try:
            service.execute_deep_review_job(thread_id, cleaned_id)
        except Exception:
            logger.exception("deep_review_worker_failed review_id=%s", cleaned_id)
        finally:
            with _LOCK:
                _SUBMITTED.discard(cleaned_id)

    get_deep_review_executor().submit(_run)


def reset_deep_review_jobs_for_tests() -> None:
    """Drop the in-process executor so tests do not leak worker threads."""
    global _EXECUTOR
    with _LOCK:
        executor = _EXECUTOR
        _EXECUTOR = None
        _SUBMITTED.clear()
    if executor is not None:
        executor.shutdown(wait=False, cancel_futures=True)
