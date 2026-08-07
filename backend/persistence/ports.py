"""Narrow storage ports used by application services.

These protocols keep business logic independent of SQLite and the local
filesystem so production can swap in Aurora DSQL and S3 without UI changes.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True)
class StoredObject:
    """Metadata for one persisted binary object (upload or derived file)."""

    key: str
    original_filename: str
    content_type: str
    size: int


class FileStorage(Protocol):
    """Byte-oriented object storage for user uploads and managed copies."""

    def put_bytes(
        self,
        *,
        key: str,
        data: bytes,
        content_type: str = "application/octet-stream",
    ) -> StoredObject:
        """Store *data* under *key* and return stored metadata."""

    def get_bytes(self, key: str) -> bytes:
        """Return object bytes for *key*.

        Raises:
            FileNotFoundError: when the object does not exist.
        """

    def delete(self, key: str) -> None:
        """Delete *key* when present; missing keys are ignored."""

    def exists(self, key: str) -> bool:
        """Return whether *key* is present."""

    def delete_prefix(self, prefix: str) -> int:
        """Delete every object whose key starts with *prefix*. Return count."""
