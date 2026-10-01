"""Provider-neutral constants and token helpers for persistent guest sessions."""

from __future__ import annotations

import hashlib
import secrets
import uuid
from datetime import datetime, timedelta, timezone

GUEST_SESSION_TTL = timedelta(days=400)


def new_guest_owner_identifier() -> str:
    """Return a server-generated opaque identifier for one guest owner."""
    return f"guest:{uuid.uuid4()}"


def new_guest_secret() -> str:
    """Return a URL-safe bearer secret containing 256 random bits."""
    return secrets.token_urlsafe(32)


def guest_secret_digest(secret: str) -> str:
    """Return the SHA-256 digest used to look up a guest bearer secret."""
    return hashlib.sha256(secret.encode("utf-8")).hexdigest()


def normalize_guest_time(value: datetime | None = None) -> datetime:
    """Return a UTC-aware time suitable for deterministic guest-session work."""
    moment = value or datetime.now(timezone.utc)
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    return moment.astimezone(timezone.utc)


def guest_time_text(value: datetime) -> str:
    """Serialize guest-session timestamps in a stable lexically sortable form."""
    return normalize_guest_time(value).isoformat(timespec="microseconds")
