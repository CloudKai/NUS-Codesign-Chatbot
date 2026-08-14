"""In-memory FileStorage used by deterministic automated tests."""

from __future__ import annotations

from .ports import ListedObject, StoredObject


class MemoryFileStorage:
    """Dict-backed object store that never touches disk or AWS."""

    def __init__(self) -> None:
        self._objects: dict[str, tuple[bytes, str]] = {}

    def ping(self) -> None:
        """Memory storage is always ready after construction."""

    def put_bytes(
        self,
        *,
        key: str,
        data: bytes,
        content_type: str = "application/octet-stream",
    ) -> StoredObject:
        """Store *data* in memory under *key*."""
        self._objects[key] = (bytes(data), content_type)
        return StoredObject(
            key=key,
            original_filename=key.rsplit("/", 1)[-1],
            content_type=content_type,
            size=len(data),
        )

    def get_bytes(self, key: str) -> bytes:
        """Return in-memory bytes for *key*."""
        try:
            return self._objects[key][0]
        except KeyError as error:
            raise FileNotFoundError(key) from error

    def delete(self, key: str) -> None:
        """Remove one in-memory object when present."""
        self._objects.pop(key, None)

    def exists(self, key: str) -> bool:
        """Return whether *key* is present in memory."""
        return key in self._objects

    def delete_prefix(self, prefix: str) -> int:
        """Delete every in-memory object under *prefix*."""
        keys = [key for key in self._objects if key.startswith(prefix)]
        for key in keys:
            del self._objects[key]
        return len(keys)

    def list_prefix(self, prefix: str) -> list[ListedObject]:
        """List in-memory objects whose keys start with *prefix*."""
        listed: list[ListedObject] = []
        for key, (data, _content_type) in sorted(self._objects.items()):
            if not key.startswith(prefix) or key.endswith("/"):
                continue
            listed.append(ListedObject(key=key, size=len(data), etag=str(len(data))))
        return listed
