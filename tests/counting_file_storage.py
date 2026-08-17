"""Operation-counting in-memory storage for student-source retrieval tests.

Classifies keys by suffix/prefix so course-catalog ``list_prefix`` calls are
never counted as student chunk-discovery listings. Tests must reset the
operation log between turns with :meth:`CountingFileStorage.reset_counts`.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from backend.persistence.factory import reset_file_storage_cache
from backend.persistence.memory_files import MemoryFileStorage
from backend.persistence.ports import ListedObject, StoredObject
from backend.settings import settings

_EXTRACTED_SUFFIX = "/derived/extracted.txt"
_CHUNKS_SUFFIX = "/derived/chunks.v1.json"
_RAW_MARKER = "/raw/"
_COURSE_PREFIX = "course/"
_USERS_PREFIX = "users/"


@dataclass(frozen=True)
class StorageOperation:
    """One recorded FileStorage call with its object key or prefix."""

    op: str
    key: str


@dataclass
class OperationCounts:
    """Privacy-safe classified counts for one measurement window."""

    get_bytes: int = 0
    put_bytes: int = 0
    exists: int = 0
    delete: int = 0
    delete_prefix: int = 0
    list_prefix: int = 0
    extracted_gets: int = 0
    chunks_gets: int = 0
    raw_gets: int = 0
    student_content_gets: int = 0
    student_chunk_lists: int = 0
    course_lists: int = 0
    keys: list[str] = field(default_factory=list)


def classify_key(key: str) -> str:
    """Return a coarse key class used by operation-count assertions.

    Args:
        key: Object key or prefix passed to FileStorage.

    Returns:
        One of ``chunks``, ``extracted``, ``raw``, ``course``, ``student``,
        or ``other``. Never inspects object bytes.
    """
    value = str(key or "").replace("\\", "/")
    if value.endswith(_CHUNKS_SUFFIX) or value.endswith("derived/chunks.v1.json"):
        return "chunks"
    if value.endswith(_EXTRACTED_SUFFIX) or value.endswith("derived/extracted.txt"):
        return "extracted"
    if _RAW_MARKER in value:
        return "raw"
    if value.startswith(_COURSE_PREFIX) or value == "course":
        return "course"
    if value.startswith(_USERS_PREFIX):
        return "student"
    return "other"


class CountingFileStorage(MemoryFileStorage):
    """Memory FileStorage that records every mutating and lookup call.

    Course-catalog listings under ``course/`` are recorded separately from
    student-source listings. A student ``list_prefix`` of a source or derived
    prefix is the operation Track B forbids on the chunk-discovery hot path.
    """

    def __init__(self) -> None:
        super().__init__()
        self.operations: list[StorageOperation] = []

    def reset_counts(self) -> None:
        """Clear the operation log without deleting stored objects."""
        self.operations.clear()

    def _record(self, op: str, key: str) -> None:
        self.operations.append(StorageOperation(op=op, key=str(key)))

    def put_bytes(
        self,
        *,
        key: str,
        data: bytes,
        content_type: str = "application/octet-stream",
    ) -> StoredObject:
        """Record one PUT, then store the object in memory."""
        self._record("put_bytes", key)
        return super().put_bytes(key=key, data=data, content_type=content_type)

    def get_bytes(self, key: str) -> bytes:
        """Record one GET, including misses that raise ``FileNotFoundError``."""
        self._record("get_bytes", key)
        return super().get_bytes(key)

    def exists(self, key: str) -> bool:
        """Record one EXISTS check."""
        self._record("exists", key)
        return super().exists(key)

    def delete(self, key: str) -> None:
        """Record one DELETE."""
        self._record("delete", key)
        super().delete(key)

    def delete_prefix(self, prefix: str) -> int:
        """Record one prefix delete."""
        self._record("delete_prefix", prefix)
        return super().delete_prefix(prefix)

    def list_prefix(self, prefix: str) -> list[ListedObject]:
        """Record one prefix listing."""
        self._record("list_prefix", prefix)
        return super().list_prefix(prefix)

    def ops(self, op: str, *, kind: str | None = None) -> list[StorageOperation]:
        """Return recorded operations matching *op* and optional key class."""
        matched = [item for item in self.operations if item.op == op]
        if kind is None:
            return matched
        return [item for item in matched if classify_key(item.key) == kind]

    def gets(self, *, kind: str | None = None) -> list[StorageOperation]:
        """Return recorded ``get_bytes`` calls, optionally filtered by class."""
        return self.ops("get_bytes", kind=kind)

    def counts(self) -> OperationCounts:
        """Return classified counts for the current measurement window."""
        gets = self.ops("get_bytes")
        lists = self.ops("list_prefix")
        student_chunk_lists = [
            item
            for item in lists
            if classify_key(item.key) in {"chunks", "extracted", "raw", "student"}
        ]
        return OperationCounts(
            get_bytes=len(gets),
            put_bytes=len(self.ops("put_bytes")),
            exists=len(self.ops("exists")),
            delete=len(self.ops("delete")),
            delete_prefix=len(self.ops("delete_prefix")),
            list_prefix=len(lists),
            extracted_gets=len(self.gets(kind="extracted")),
            chunks_gets=len(self.gets(kind="chunks")),
            raw_gets=len(self.gets(kind="raw")),
            student_content_gets=len(
                [
                    item
                    for item in gets
                    if classify_key(item.key) in {"chunks", "extracted", "raw"}
                ]
            ),
            student_chunk_lists=len(student_chunk_lists),
            course_lists=len(self.ops("list_prefix", kind="course")),
            keys=[item.key for item in self.operations],
        )


def install_counting_storage(monkeypatch: object, storage: CountingFileStorage) -> None:
    """Point settings and the storage factory at *storage* for one test.

    Args:
        monkeypatch: Pytest monkeypatch fixture.
        storage: Shared counting store used as both student and course storage.
    """
    monkeypatch.setattr(settings, "file_storage_provider", "memory")
    reset_file_storage_cache()
    monkeypatch.setattr(
        "backend.persistence.factory.get_file_storage",
        lambda: storage,
    )
    monkeypatch.setattr(
        "backend.persistence.factory.get_course_file_storage",
        lambda: storage,
    )
