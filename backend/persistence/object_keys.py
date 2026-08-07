"""Safe object-key helpers for local and S3 file storage."""

from __future__ import annotations

import re
import uuid
from pathlib import Path


_UNSAFE = re.compile(r"[^A-Za-z0-9._-]+")


def sanitize_filename(name: str) -> str:
    """Return a path-safe basename limited to 180 characters."""
    base = Path(str(name or "")).name.replace("\x00", "").strip()
    cleaned = _UNSAFE.sub("_", base).strip("._") or "upload"
    return cleaned[:180]


def build_upload_object_key(
    *,
    user_id: str,
    thread_id: str,
    filename: str,
    object_id: str | None = None,
) -> str:
    """Build a generated object key that never trusts the raw user filename path.

    Example:
        ``users/<user-id>/<thread-id>/<uuid>/<sanitized-filename>``
    """
    safe_user = sanitize_filename(user_id) or "user"
    safe_thread = sanitize_filename(thread_id) or "thread"
    oid = object_id or str(uuid.uuid4())
    return f"users/{safe_user}/{safe_thread}/{oid}/{sanitize_filename(filename)}"


def thread_prefix(*, user_id: str, thread_id: str) -> str:
    """Return the key prefix for every object belonging to one notebook."""
    safe_user = sanitize_filename(user_id) or "user"
    safe_thread = sanitize_filename(thread_id) or "thread"
    return f"users/{safe_user}/{safe_thread}/"
