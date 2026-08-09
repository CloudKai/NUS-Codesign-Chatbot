"""Safe object-key helpers for local and S3 file storage."""

from __future__ import annotations

import re
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
    source_id: str,
    filename: str,
) -> str:
    """Build a generated object key that never trusts the raw user filename path.

    Example:
        ``users/<user-id>/notebooks/<notebook-id>/sources/<source-id>/raw/<safe-filename>``
    """
    safe_user = sanitize_filename(user_id) or "user"
    safe_notebook = sanitize_filename(notebook_id) or "notebook"
    safe_source = sanitize_filename(source_id) or "source"
    return (
        f"users/{safe_user}/notebooks/{safe_notebook}/sources/{safe_source}/raw/"
        f"{sanitize_filename(filename)}"
    )


def notebook_prefix(*, user_id: str, notebook_id: str) -> str:
    """Return the key prefix for every object belonging to one notebook."""
    safe_user = sanitize_filename(user_id) or "user"
    safe_notebook = sanitize_filename(notebook_id) or "notebook"
    return f"users/{safe_user}/notebooks/{safe_notebook}/"


def source_prefix(*, user_id: str, notebook_id: str, source_id: str) -> str:
    """Return the key prefix for every object belonging to one source.

    Example:
        ``users/<user-id>/notebooks/<notebook-id>/sources/<source-id>/``

    Uses the same sanitization and owner/notebook/source components as
    ``build_upload_object_key`` / ``build_extracted_text_object_key``. Callers
    must pass the authenticated owner id — never a metadata-supplied user.
    """
    safe_user = sanitize_filename(user_id) or "user"
    safe_notebook = sanitize_filename(notebook_id) or "notebook"
    safe_source = sanitize_filename(source_id) or "source"
    return f"users/{safe_user}/notebooks/{safe_notebook}/sources/{safe_source}/"


def build_extracted_text_object_key(
    *,
    user_id: str,
    notebook_id: str,
    source_id: str,
) -> str:
    """Build a deterministic object key for derived extracted text.

    Example:
        ``users/<user-id>/notebooks/<notebook-id>/sources/<source-id>/derived/extracted.txt``
    """
    safe_user = sanitize_filename(user_id) or "user"
    safe_notebook = sanitize_filename(notebook_id) or "notebook"
    safe_source = sanitize_filename(source_id) or "source"
    return (
        f"users/{safe_user}/notebooks/{safe_notebook}/sources/{safe_source}/"
        "derived/extracted.txt"
    )
