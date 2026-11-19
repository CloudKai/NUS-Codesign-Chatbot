"""Bound process-local source work and release payloads independently of the UI.

The coordinator owns payloads, executor admission and retry lifetimes. Callers
supply an owner-bound upload operation accepting a batch, never a closure over
that batch. No Streamlit, storage or provider dependency is needed here.
"""

from __future__ import annotations

import logging
import threading
import time
import uuid
from collections.abc import Callable
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import dataclass
from typing import Any

UploadBatch = list[tuple[str, bytes, str | None]]
UploadOperation = Callable[[UploadBatch], list[dict[str, Any]]]
_logger = logging.getLogger(__name__)


class UploadAdmissionError(ValueError):
    """A batch cannot fit the current process or owner upload allowance."""


class SourceUploadFailed(RuntimeError):
    """Sanitized terminal failure without a retained upload traceback."""


@dataclass(frozen=True)
class PendingSourceUpload:
    """Payload-free progress snapshot for one owner's notebook upload."""

    upload_id: str
    owner_id: str
    thread_id: str
    filenames: tuple[str, ...]
    future: Future[list[dict[str, Any]]]
    failed: bool
    retryable: bool
    completed: bool
    processing: bool


@dataclass
class _UploadJob:
    """Private payload lease and bounded completion receipt."""

    owner_id: str
    thread_id: str
    filenames: tuple[str, ...]
    uploads: UploadBatch
    operation: UploadOperation | None
    future: Future[list[dict[str, Any]]]
    size: int
    retained: bool = True
    processing: bool = False
    attempts: int = 1
    failed: bool = False
    expires_at: float | None = None


class SourceUploadCoordinator:
    """Admit bounded running/queued/retry work and expire terminal jobs.

    Counts and bytes include failed batches while retryable. Success releases
    its batch before resolving the public future; small receipts last at most
    ``retention_seconds`` and are count-bounded separately. A daemon reaper
    expires abandoned failures even when no browser polls. Active jobs retain
    their allowance until the worker finishes; a hung worker cannot free a slot
    and admit unbounded additional work.
    """

    def __init__(
        self, *, global_jobs: int = 32, owner_jobs: int = 4,
        global_bytes: int = 209_715_200, owner_bytes: int = 52_428_800,
        retention_seconds: float = 300, max_attempts: int = 3,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        """Create a two-worker queue with positive ceilings and an injected clock."""
        if min(global_jobs, owner_jobs, global_bytes, owner_bytes,
               retention_seconds, max_attempts) <= 0:
            raise ValueError("Upload limits must be positive")
        self._global_jobs, self._owner_jobs = global_jobs, owner_jobs
        self._global_bytes, self._owner_bytes = global_bytes, owner_bytes
        self._retention_seconds, self._max_attempts = retention_seconds, max_attempts
        self._clock = clock
        self._jobs: dict[str, _UploadJob] = {}
        self._lock = threading.RLock()
        self._executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix="source-upload")
        self._stopped = threading.Event()
        self._reaper = threading.Thread(target=self._reap, daemon=True, name="upload-cleanup")
        self._reaper.start()

    def submit(
        self, *, owner_id: str, thread_id: str, uploads: UploadBatch,
        upload: UploadOperation,
    ) -> str:
        """Atomically admit a batch or raise actionable ``UploadAdmissionError``.

        Retains only an immutable copy of the supplied tuple list. Rejected work
        never reaches the executor. Per-file/count validation stays at the API
        and file-storage boundaries.
        """
        size = sum(len(data) for _, data, _ in uploads)
        if not uploads:
            raise UploadAdmissionError("Choose at least one file to upload.")
        with self._lock:
            self._expire_locked()
            if self._stopped.is_set():
                raise UploadAdmissionError("Uploads are restarting. Choose your files again shortly.")
            retained = [job for job in self._jobs.values() if job.retained]
            owned = [job for job in retained if job.owner_id == owner_id]
            if (len(owned) >= self._owner_jobs
                    or sum(job.size for job in owned) + size > self._owner_bytes):
                raise UploadAdmissionError(
                    "Your upload allowance is full. Wait for uploads to finish or remove failed "
                    "uploads, then choose fewer or smaller files again."
                )
            if (len(retained) >= self._global_jobs
                    or sum(job.size for job in retained) + size > self._global_bytes):
                raise UploadAdmissionError(
                    "Uploads are busy. Wait for uploads to finish, then choose your files again."
                )
            upload_id = str(uuid.uuid4())
            self._jobs[upload_id] = _UploadJob(
                owner_id, thread_id, tuple(name[:180] for name, _, _ in uploads),
                list(uploads), upload, Future(), size,
            )
            try:
                self._executor.submit(self._run, upload_id)
            except RuntimeError:
                self._jobs.pop(upload_id)
                raise UploadAdmissionError("Uploads are restarting. Choose your files again shortly.") from None
            return upload_id

    def jobs_for(self, owner_id: str, thread_id: str) -> list[PendingSourceUpload]:
        """Return payload-free, owner/notebook-scoped progress, newest first."""
        with self._lock:
            self._expire_locked()
            return [PendingSourceUpload(
                key, job.owner_id, job.thread_id, job.filenames, job.future, job.failed,
                job.failed and job.retained, job.future.done(), job.processing,
            ) for key, job in reversed(self._jobs.items())
                if job.owner_id == owner_id and job.thread_id == thread_id]

    def retry(
        self, upload_id: str, owner_id: str, thread_id: str, upload: UploadOperation,
    ) -> bool:
        """Retry an owned terminal failure within its original TTL/attempt limit.

        The caller supplies freshly captured credentials; retained credentials
        are released on every failure. Retrying never extends the first failure
        deadline and needs no new admission because its payload is still charged.
        """
        with self._lock:
            self._expire_locked()
            job = self._jobs.get(upload_id)
            if (job is None or job.owner_id != owner_id or job.thread_id != thread_id
                    or not job.future.done() or not job.failed or not job.retained
                    or self._stopped.is_set()):
                return False
            job.operation = upload
            job.future = Future()
            job.failed = False
            job.processing = False
            job.attempts += 1
            self._executor.submit(self._run, upload_id)
            return True

    def mark_failed(self, upload_id: str, owner_id: str) -> None:
        """Compatibility no-op: workers now mark failure without a UI revisit."""
        # Failure is already authoritative before the future resolves. Never
        # let a stale browser observation change a replacement retry's state.
        del upload_id, owner_id

    def discard(self, upload_id: str, owner_id: str) -> bool:
        """Remove an owned terminal receipt/failure; active leases cannot vanish."""
        with self._lock:
            job = self._jobs.get(upload_id)
            if job is None or job.owner_id != owner_id or not job.future.done():
                return False
            self._release(job)
            del self._jobs[upload_id]
            return True

    def close(self) -> None:
        """Stop cleanup and drain workers, then release all process-local leases."""
        self._stopped.set()
        self._executor.shutdown(wait=True)
        self._reaper.join(timeout=2)
        with self._lock:
            for job in self._jobs.values():
                self._release(job)
            self._jobs.clear()

    def _run(self, upload_id: str) -> None:
        with self._lock:
            job = self._jobs[upload_id]
            job.processing = True
            batch, operation = job.uploads, job.operation
        failed = False
        receipts: list[dict[str, Any]] = []
        try:
            assert operation is not None
            receipts = [{key: row[key] for key in ("id", "title") if key in row} for row in operation(batch)]
        except Exception as error:
            failed = True
            # Do not keep exception tracebacks (which reference the batch) in
            # futures, or log filenames, payloads, credentials or raw errors.
            _logger.warning("source_upload_failed upload_id=%s thread_id=%s category=%s",
                            upload_id, job.thread_id, type(error).__name__)
        finally:
            del batch, operation
        with self._lock:
            job.failed = failed
            job.operation = None
            if job.expires_at is None:
                job.expires_at = self._clock() + self._retention_seconds
            if not failed or job.attempts >= self._max_attempts or self._clock() >= job.expires_at:
                self._release(job)
            if failed:
                job.future.set_exception(SourceUploadFailed("The file could not be added."))
            else:
                # Only safe identity is retained; never paths, text or bytes.
                job.future.set_result(receipts)
            self._trim_receipts_locked(job.owner_id)

    @staticmethod
    def _release(job: _UploadJob) -> None:
        job.retained = False
        job.uploads = []
        job.operation = None
        job.size = 0

    def _expire_locked(self) -> None:
        for key, job in list(self._jobs.items()):
            if job.future.done() and job.expires_at is not None and self._clock() >= job.expires_at:
                self._release(job)
                del self._jobs[key]

    def _trim_receipts_locked(self, owner_id: str) -> None:
        receipts = [key for key, job in self._jobs.items() if not job.retained]
        owned = [key for key in receipts if self._jobs[key].owner_id == owner_id]
        # Payload-free receipts are separately bounded so finished uploads
        # neither consume admission nor accumulate metadata in abandoned tabs.
        remove = set(owned[:-8]) | set(receipts[:-128])
        for key in remove:
            del self._jobs[key]

    def _reap(self) -> None:
        while not self._stopped.wait(min(1.0, self._retention_seconds)):
            with self._lock:
                self._expire_locked()
