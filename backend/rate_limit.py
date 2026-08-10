"""In-process coach and auth-login rate limiting for a single EC2 instance.

This limiter is intentionally process-local. It is acceptable for the current
single-container production topology, but correctness must never depend on it:
durable coach idempotency remains DB-backed in ``StudentStore``. A future
Redis/distributed adapter can replace this module without changing API call
sites.

``LoginStartLimiter`` protects the public Cognito login-start route from
unauthenticated OAuth-state write amplification. It is also process-local.
"""

from __future__ import annotations

import threading
import time
from collections import defaultdict, deque
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Iterator


@dataclass(frozen=True)
class RateLimitExceeded(Exception):
    """Raised when a caller exceeds an active, burst, or global coach limit."""

    retry_after_seconds: int
    detail: str


class CoachRateLimiter:
    """Track per-user and global coach concurrency plus a short burst window."""

    def __init__(
        self,
        *,
        max_active_per_user: int = 1,
        requests_per_minute: int = 8,
        max_concurrent_model_calls: int = 20,
    ) -> None:
        """Create a limiter with the configured ceilings."""
        self.max_active_per_user = max(1, int(max_active_per_user))
        self.requests_per_minute = max(1, int(requests_per_minute))
        self.max_concurrent_model_calls = max(1, int(max_concurrent_model_calls))
        self._lock = threading.Lock()
        self._active_per_user: dict[str, int] = defaultdict(int)
        self._global_active = 0
        self._recent: dict[str, deque[float]] = defaultdict(deque)

    def _prune(self, user_id: str, now: float) -> None:
        """Drop burst timestamps older than one minute for *user_id*."""
        window = self._recent[user_id]
        while window and now - window[0] >= 60.0:
            window.popleft()

    def acquire(self, user_id: str) -> None:
        """Reserve one coach slot for the authenticated *user_id* or raise."""
        key = str(user_id or "").strip()
        if not key:
            raise RateLimitExceeded(1, "Authenticated user identity is required")
        now = time.monotonic()
        with self._lock:
            self._prune(key, now)
            if self._active_per_user[key] >= self.max_active_per_user:
                raise RateLimitExceeded(
                    1,
                    "Only one active coaching request is allowed at a time",
                )
            if len(self._recent[key]) >= self.requests_per_minute:
                oldest = self._recent[key][0]
                retry_after = max(1, int(60.0 - (now - oldest)) + 1)
                raise RateLimitExceeded(
                    retry_after,
                    "Coaching request rate limit exceeded; retry shortly",
                )
            if self._global_active >= self.max_concurrent_model_calls:
                raise RateLimitExceeded(
                    1,
                    "The service is at capacity; retry shortly",
                )
            self._active_per_user[key] += 1
            self._global_active += 1
            self._recent[key].append(now)

    def release(self, user_id: str) -> None:
        """Release one previously acquired coach slot for *user_id*."""
        key = str(user_id or "").strip()
        if not key:
            return
        with self._lock:
            active = self._active_per_user.get(key, 0)
            if active <= 1:
                self._active_per_user.pop(key, None)
            else:
                self._active_per_user[key] = active - 1
            if self._global_active > 0:
                self._global_active -= 1

    @contextmanager
    def limit(self, user_id: str) -> Iterator[None]:
        """Acquire on enter and always release on exit."""
        self.acquire(user_id)
        try:
            yield
        finally:
            self.release(user_id)


_LIMITER: CoachRateLimiter | None = None
_LIMITER_LOCK = threading.Lock()


def get_coach_rate_limiter() -> CoachRateLimiter:
    """Return the process-wide limiter configured from application settings."""
    global _LIMITER
    with _LIMITER_LOCK:
        if _LIMITER is None:
            from backend.settings import settings

            _LIMITER = CoachRateLimiter(
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
        self._recent_by_client: dict[str, deque[float]] = defaultdict(deque)
        self._recent_global: deque[float] = deque()

    def _prune(self, window: deque[float], now: float) -> None:
        """Drop timestamps older than one minute from *window*."""
        while window and now - window[0] >= 60.0:
            window.popleft()

    def acquire(self, client_key: str) -> None:
        """Reserve one login-start slot for *client_key* or raise."""
        key = str(client_key or "").strip() or "unknown"
        now = time.monotonic()
        with self._lock:
            client_window = self._recent_by_client[key]
            self._prune(client_window, now)
            self._prune(self._recent_global, now)
            if len(client_window) >= self.per_client_per_minute:
                oldest = client_window[0]
                retry_after = max(1, int(60.0 - (now - oldest)) + 1)
                raise RateLimitExceeded(
                    retry_after,
                    "Login start rate limit exceeded; retry shortly",
                )
            if len(self._recent_global) >= self.global_per_minute:
                oldest = self._recent_global[0]
                retry_after = max(1, int(60.0 - (now - oldest)) + 1)
                raise RateLimitExceeded(
                    retry_after,
                    "Login service is at capacity; retry shortly",
                )
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
