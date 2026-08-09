"""Local filesystem FileStorage adapter for development and tests."""

from __future__ import annotations

from pathlib import Path

from .ports import StoredObject


class LocalFileStorage:
    """Persist upload bytes under a configured root directory."""

    def __init__(self, root: Path):
        """Create storage rooted at *root* (created on demand)."""
        self.root = Path(root).resolve()
        self.root.mkdir(parents=True, exist_ok=True)

    def _resolve(self, key: str) -> Path:
        """Map an object key to a path under ``root`` with traversal checks."""
        relative = Path(str(key).replace("\\", "/").lstrip("/"))
        if relative.is_absolute() or ".." in relative.parts:
            raise ValueError("Unsafe storage key")
        path = (self.root / relative).resolve()
        if self.root not in path.parents and path != self.root:
            raise ValueError("Unsafe storage key")
        return path

    def ping(self) -> None:
        """Verify that the configured local storage root exists."""
        if not self.root.is_dir():
            raise FileNotFoundError(self.root)

    def put_bytes(
        self,
        *,
        key: str,
        data: bytes,
        content_type: str = "application/octet-stream",
    ) -> StoredObject:
        """Write *data* to the local path for *key*."""
        path = self._resolve(key)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        return StoredObject(
            key=key,
            original_filename=path.name,
            content_type=content_type,
            size=len(data),
        )

    def get_bytes(self, key: str) -> bytes:
        """Read local bytes for *key*."""
        path = self._resolve(key)
        if not path.is_file():
            raise FileNotFoundError(key)
        return path.read_bytes()

    def delete(self, key: str) -> None:
        """Remove one local object when present."""
        path = self._resolve(key)
        if path.is_file():
            path.unlink(missing_ok=True)

    def exists(self, key: str) -> bool:
        """Return whether the local object exists."""
        return self._resolve(key).is_file()

    def delete_prefix(self, prefix: str) -> int:
        """Delete files under a key prefix. Return number removed."""
        normalized = str(prefix).replace("\\", "/").lstrip("/")
        base = self._resolve(normalized.rstrip("/") or ".")
        if not base.exists():
            # Prefix may point at a virtual directory that only exists as files.
            parent = self.root
            removed = 0
            for path in parent.rglob("*"):
                if not path.is_file():
                    continue
                rel = path.relative_to(self.root).as_posix()
                if rel.startswith(normalized):
                    path.unlink(missing_ok=True)
                    removed += 1
            return removed
        removed = 0
        if base.is_file():
            base.unlink(missing_ok=True)
            return 1
        for path in sorted(base.rglob("*"), reverse=True):
            if path.is_file():
                path.unlink(missing_ok=True)
                removed += 1
        return removed
