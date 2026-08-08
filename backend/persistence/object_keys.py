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
    notebook_id: str,
    filename: str,
    object_id: str | None = None,
) -> str:
    """Build a generated object key that never trusts the raw user filename path.

    Example:
        ``users/<user-id>/<notebook-id>/<uuid>/<sanitized-filename>``
    """
    safe_user = sanitize_filename(user_id) or "user"
    safe_notebook = sanitize_filename(notebook_id) or "notebook"
    safe_object = sanitize_filename(object_id or str(uuid.uuid4())) or "object"
    return (
        f"users/{safe_user}/{safe_notebook}/{safe_object}/"
        f"{sanitize_filename(filename)}"
    )


def notebook_prefix(*, user_id: str, notebook_id: str) -> str:
    """Return the key prefix for every object belonging to one notebook."""
    safe_user = sanitize_filename(user_id) or "user"
    safe_notebook = sanitize_filename(notebook_id) or "notebook"
    return f"users/{safe_user}/{safe_notebook}/"


def build_extracted_text_object_key(
    *,
    user_id: str,
    notebook_id: str,
    source_id: str,
) -> str:
    """Build a deterministic object key for derived extracted text.

    Example:
        ``users/<user-id>/<notebook-id>/<source-id>/extracted.txt``
    """
    safe_user = sanitize_filename(user_id) or "user"
    safe_notebook = sanitize_filename(notebook_id) or "notebook"
    safe_source = sanitize_filename(source_id) or "source"
    return f"users/{safe_user}/{safe_notebook}/{safe_source}/extracted.txt"
