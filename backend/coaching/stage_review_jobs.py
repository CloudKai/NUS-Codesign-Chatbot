"""Process-local background executor for Journey stage-completion reviews.

Same pattern as Deep Review: one Uvicorn worker, in-process pool, fail-open.
Queued/running jobs are lost on restart and may be retried on the next
completion attempt when status is missing or ``failed``.
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


def get_stage_review_executor() -> ThreadPoolExecutor:
    """Return the process-wide Journey stage-review worker pool."""
    global _EXECUTOR
    with _LOCK:
        if _EXECUTOR is None:
            workers = max(1, int(runtime_settings.deep_review_max_concurrent))
            _EXECUTOR = ThreadPoolExecutor(
                max_workers=workers,
                thread_name_prefix="stage-review",
            )
        return _EXECUTOR


def submit_stage_review_job(
    service: CoachApplicationService,
    thread_id: str,
    stage_id: str,
) -> None:
    """Submit one stage-completion Haiku review when not already in-flight.

    Args:
        service: Application service that owns ``execute_stage_review_job``.
        thread_id: Owned notebook id.
        stage_id: Completed Thinking Path stage id.
    """
    cleaned_thread = str(thread_id or "").strip()
    cleaned_stage = str(stage_id or "").strip()
    if not cleaned_thread or not cleaned_stage:
        return
    key = f"{cleaned_thread}:{cleaned_stage}"
    with _LOCK:
        if key in _SUBMITTED:
            return
        _SUBMITTED.add(key)

    def _run() -> None:
        try:
            service.execute_stage_review_job(cleaned_thread, cleaned_stage)
        except Exception:
            logger.exception(
                "stage_review_job_failed thread_id=%s stage_id=%s",
                cleaned_thread,
                cleaned_stage,
            )
        finally:
            with _LOCK:
                _SUBMITTED.discard(key)

    get_stage_review_executor().submit(_run)


def reset_stage_review_jobs_for_tests() -> None:
    """Drop the in-process executor so tests do not leak worker threads."""
    global _EXECUTOR
    with _LOCK:
        executor = _EXECUTOR
        _EXECUTOR = None
        _SUBMITTED.clear()
    if executor is not None:
        executor.shutdown(wait=False, cancel_futures=True)
