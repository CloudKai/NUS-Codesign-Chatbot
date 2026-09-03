"""Process-local executor for durable Journey stage-review jobs.

The database owns queue state and the job id is the execution fence. The
process-local set only suppresses duplicate submissions in one worker; queued
rows are resubmitted from the existing Journey read seam after restart.
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
    *,
    job_id: str | None = None,
) -> None:
    """Submit one durable stage-review job when not already in-flight.

    Args:
        service: Application service that owns ``execute_stage_review_job``.
        thread_id: Owned notebook id.
        stage_id: Completed Thinking Path stage id.
        job_id: Optional durable job id. When omitted, resolve the current
            stage job for compatibility with older callers.
    """
    cleaned_thread = str(thread_id or "").strip()
    cleaned_stage = str(stage_id or "").strip()
    if not cleaned_thread or not cleaned_stage:
        return
    cleaned_job_id = str(job_id or "").strip()
    if not cleaned_job_id:
        try:
            thread = service._store.get_thread(cleaned_thread)  # type: ignore[attr-defined]
            blob = (
                (thread or {}).get("metadata", {}).get("journey_stage_reviews")
                if isinstance((thread or {}).get("metadata"), dict)
                else None
            )
            from backend.specialists.review_orchestration import (
                parse_journey_stage_reviews,
            )

            parsed = parse_journey_stage_reviews(blob)
            job = dict((parsed.get("jobs") or {}).get(cleaned_stage) or {})
            cleaned_job_id = str(
                job.get("job_id") or job.get("review_id") or ""
            ).strip()
        except Exception:
            logger.exception(
                "stage_review_job_lookup_failed thread_id=%s stage_id=%s",
                cleaned_thread,
                cleaned_stage,
            )
    key = cleaned_job_id or f"{cleaned_thread}:{cleaned_stage}"
    with _LOCK:
        if key in _SUBMITTED:
            return
        _SUBMITTED.add(key)

    def _run() -> None:
        try:
            service.execute_stage_review_job(
                cleaned_thread,
                cleaned_stage,
                cleaned_job_id or None,
            )
        except Exception:
            logger.exception(
                "stage_review_job_failed thread_id=%s stage_id=%s",
                cleaned_thread,
                cleaned_stage,
            )
        finally:
            # The durable row, rather than this process-local set, owns the
            # lifecycle.  Release the submission key when this worker exits so
            # a lease-reclaimed job with the same job id can be submitted
            # again, while concurrent callers remain deduplicated during the
            # active execution window.
            with _LOCK:
                _SUBMITTED.discard(key)
            try:
                # A stale worker can finish after another process reclaimed
                # its lease.  Reconcile queued durable work now that this
                # process-local guard has been released.
                reconcile = getattr(
                    service, "resubmit_queued_stage_review_jobs", None
                )
                if callable(reconcile):
                    reconcile(cleaned_thread)
            except Exception:
                logger.exception(
                    "stage_review_job_recovery_after_exit_failed thread_id=%s",
                    cleaned_thread,
                )
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
