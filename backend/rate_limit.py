"""In-process coach and auth-login rate limiting for a single EC2 instance.

This limiter is intentionally process-local. It is acceptable for the current
single-container production topology, but correctness must never depend on it:
durable coach idempotency remains DB-backed in ``StudentStore``. A future
Redis/distributed adapter can replace this module without changing API call
sites.

``CoachRateLimiter`` tracks active provider-backed coaching *workflows* (one
claimed ``submit`` execution), not the internal Haiku/Sonnet invokes inside
one workflow. ``MAX_CONCURRENT_MODEL_CALLS`` keeps its historical name for
that global workflow ceiling.

``LoginStartLimiter`` protects the public Cognito login-start route from
unauthenticated OAuth-state write amplification. It is also process-local.
"""

from __future__ import annotations

import logging
import threading
import time
from collections import deque
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Iterator

logger = logging.getLogger(__name__)

NOTEBOOK_CONCURRENCY = "notebook_concurrency"
USER_CONCURRENCY = "user_concurrency"
USER_RPM = "user_rpm"
GLOBAL_CAPACITY = "global_capacity"
MISSING_IDENTITY = "missing_identity"


@dataclass(frozen=True)
class RateLimitExceeded(Exception):
    """Raised when a caller exceeds an active, burst, or global coach limit.

    ``category`` is a privacy-safe telemetry label. Student-facing HTTP mapping
    remains 429 / busy and must not include AWS or notebook identifiers.
    """

    retry_after_seconds: int
    detail: str
    category: str = "throttled"


class CoachRateLimiter:
    """Track per-notebook, per-user, and global coach concurrency plus RPM."""

    def __init__(
        self,
        *,
        max_active_per_notebook: int = 1,
        max_active_per_user: int = 2,
        requests_per_minute: int = 8,
        max_concurrent_model_calls: int = 20,
    ) -> None:
        """Create a limiter with the configured ceilings."""
        self.max_active_per_notebook = max(1, int(max_active_per_notebook))
        self.max_active_per_user = max(1, int(max_active_per_user))
        self.requests_per_minute = max(1, int(requests_per_minute))
        self.max_concurrent_model_calls = max(1, int(max_concurrent_model_calls))
        self._lock = threading.Lock()
        self._active_per_user: dict[str, int] = {}
        self._active_per_notebook: dict[tuple[str, str], int] = {}
        self._global_active = 0
        self._recent: dict[str, deque[float]] = {}

    def _notebook_key(self, user_id: str, thread_id: str) -> tuple[str, str]:
        """Return the owner-scoped notebook identity used for concurrency."""
        return (user_id, thread_id)

    def _prune(self, user_id: str, now: float) -> None:
        """Drop burst timestamps older than one minute for *user_id*."""
        window = self._recent.get(user_id)
        if window is None:
            return
        while window and now - window[0] >= 60.0:
            window.popleft()
        if not window:
            self._recent.pop(user_id, None)

    def _decrement_map(self, mapping: dict[object, int], key: object) -> None:
        """Decrement one counter and drop the key when it reaches zero."""
        current = mapping.get(key, 0)
        if current <= 1:
            mapping.pop(key, None)
        else:
            mapping[key] = current - 1

    def _reject(self, category: str, detail: str, retry_after_seconds: int) -> None:
        """Log a category-only rejection and raise ``RateLimitExceeded``."""
        logger.info(
            "coach_rate_limited category=%s retry_after=%s",
            category,
            retry_after_seconds,
        )
        raise RateLimitExceeded(
            retry_after_seconds,
            detail,
            category=category,
        )

    def acquire(self, user_id: str, thread_id: str) -> None:
        """Reserve one coach workflow slot for *user_id* / *thread_id* or raise.

        Checks and increments happen under one lock. This method must not sleep,
        call AWS, or perform DSQL/network I/O.
        """
        owner = str(user_id or "").strip()
        notebook = str(thread_id or "").strip()
        if not owner or not notebook:
            self._reject(
                MISSING_IDENTITY,
                "Authenticated user identity is required",
                1,
            )
        now = time.monotonic()
        notebook_key = self._notebook_key(owner, notebook)
        with self._lock:
            self._prune(owner, now)
            if (
                self._active_per_notebook.get(notebook_key, 0)
                >= self.max_active_per_notebook
            ):
                self._reject(
                    NOTEBOOK_CONCURRENCY,
                    "Only one active coaching request is allowed per notebook",
                    1,
                )
            if self._active_per_user.get(owner, 0) >= self.max_active_per_user:
                self._reject(
                    USER_CONCURRENCY,
                    "This account already has the maximum number of active coaching requests",
                    1,
                )
            recent = self._recent.get(owner)
            if recent is not None and len(recent) >= self.requests_per_minute:
                oldest = recent[0]
                retry_after = max(1, int(60.0 - (now - oldest)) + 1)
                self._reject(
                    USER_RPM,
                    "Coaching request rate limit exceeded; retry shortly",
                    retry_after,
                )
            if self._global_active >= self.max_concurrent_model_calls:
                self._reject(
                    GLOBAL_CAPACITY,
                    "The service is at capacity; retry shortly",
                    1,
                )
            self._active_per_notebook[notebook_key] = (
                self._active_per_notebook.get(notebook_key, 0) + 1
            )
            self._active_per_user[owner] = self._active_per_user.get(owner, 0) + 1
            self._global_active += 1
            if recent is None:
                recent = deque()
                self._recent[owner] = recent
            recent.append(now)

    def release(self, user_id: str, thread_id: str) -> None:
        """Release one previously acquired coach slot for *user_id* / *thread_id*.

        Missing or already-zero counters are ignored so a mismatched or double
        release cannot underflow. Zero-value map entries are removed.
        """
        owner = str(user_id or "").strip()
        notebook = str(thread_id or "").strip()
        if not owner or not notebook:
            return
        notebook_key = self._notebook_key(owner, notebook)
        with self._lock:
            self._decrement_map(self._active_per_notebook, notebook_key)
            self._decrement_map(self._active_per_user, owner)
            if self._global_active > 0:
                self._global_active -= 1

    @contextmanager
    def limit(self, user_id: str, thread_id: str) -> Iterator[None]:
        """Acquire on enter and always release on exit."""
        self.acquire(user_id, thread_id)
        try:
            yield
        finally:
            self.release(user_id, thread_id)


_LIMITER: CoachRateLimiter | None = None
_LIMITER_LOCK = threading.Lock()


def get_coach_rate_limiter() -> CoachRateLimiter:
    """Return the process-wide limiter configured from application settings."""
    global _LIMITER
    with _LIMITER_LOCK:
        if _LIMITER is None:
            from backend.settings import settings

            _LIMITER = CoachRateLimiter(
                max_active_per_notebook=settings.max_active_coach_requests_per_notebook,
                max_active_per_user=settings.max_active_coach_requests_per_user,
                requests_per_minute=settings.coach_requests_per_minute,
                max_concurrent_model_calls=settings.max_concurrent_model_calls,
            )
        return _LIMITER


def reset_coach_rate_limiter_for_tests() -> None:
    """Drop the cached limiter so tests can inject fresh ceilings."""
    global _LIMITER
    with _LIMITER_LOCK:
        _LIMITER = None


class LoginStartLimiter:
    """Throttle unauthenticated Cognito login starts (OAuth-state writes).

    Limits both per-client and global starts per rolling minute so a flood
    cannot create unbounded durable OAuth-state rows on a single EC2 process.
    """

    def __init__(
        self,
        *,
        per_client_per_minute: int = 10,
        global_per_minute: int = 60,
    ) -> None:
        """Create a login-start limiter with the configured ceilings."""
        self.per_client_per_minute = max(1, int(per_client_per_minute))
        self.global_per_minute = max(1, int(global_per_minute))
        self._lock = threading.Lock()
        self._recent_by_client: dict[str, deque[float]] = {}
        self._recent_global: deque[float] = deque()

    def _prune(self, window: deque[float], now: float) -> None:
        """Drop timestamps older than one minute from *window*."""
        while window and now - window[0] >= 60.0:
            window.popleft()

    def _prune_clients(self, now: float) -> None:
        """Remove inactive client keys so attacker-controlled identities stay bounded."""
        expired: list[str] = []
        for key, window in self._recent_by_client.items():
            self._prune(window, now)
            if not window:
                expired.append(key)
        for key in expired:
            self._recent_by_client.pop(key, None)

    def acquire(self, client_key: str) -> None:
        """Reserve one login-start slot for *client_key* or raise."""
        key = str(client_key or "").strip() or "unknown"
        now = time.monotonic()
        with self._lock:
            self._prune_clients(now)
            self._prune(self._recent_global, now)
            client_window = self._recent_by_client.get(key)
            if client_window and len(client_window) >= self.per_client_per_minute:
                oldest = client_window[0]
                retry_after = max(1, int(60.0 - (now - oldest)) + 1)
                raise RateLimitExceeded(
                    retry_after,
                    "Login start rate limit exceeded; retry shortly",
                    category="login",
                )
            if len(self._recent_global) >= self.global_per_minute:
                oldest = self._recent_global[0]
                retry_after = max(1, int(60.0 - (now - oldest)) + 1)
                raise RateLimitExceeded(
                    retry_after,
                    "Login service is at capacity; retry shortly",
                    category="login",
                )
            if client_window is None:
                client_window = deque()
                self._recent_by_client[key] = client_window
            client_window.append(now)
            self._recent_global.append(now)


_LOGIN_LIMITER: LoginStartLimiter | None = None
_LOGIN_LIMITER_LOCK = threading.Lock()


def get_login_start_limiter() -> LoginStartLimiter:
    """Return the process-wide login-start limiter from application settings."""
    global _LOGIN_LIMITER
    with _LOGIN_LIMITER_LOCK:
        if _LOGIN_LIMITER is None:
            from backend.settings import settings

            _LOGIN_LIMITER = LoginStartLimiter(
                per_client_per_minute=settings.auth_login_requests_per_minute_per_ip,
                global_per_minute=settings.auth_login_requests_per_minute_global,
            )
        return _LOGIN_LIMITER


def reset_login_start_limiter_for_tests() -> None:
    """Drop the cached login-start limiter so tests can inject fresh ceilings."""
    global _LOGIN_LIMITER
    with _LOGIN_LIMITER_LOCK:
        _LOGIN_LIMITER = None
