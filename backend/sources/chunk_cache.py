"""Byte-bounded in-process LRU for parsed student-source chunk artifacts.

This cache never authorizes access. Callers must already have validated
owner, notebook, and source identity through the owner-scoped store before
reading or writing here. A cache hit is unreachable with an unvalidated
source id because the key includes a server-built artifact object key
derived from ``store.owner_id``, never from client input, filenames,
titles, or any student-supplied label.

Do not log chunk text, object keys, owner ids, or notebook ids.
"""

from __future__ import annotations

import threading
from collections import OrderedDict
from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from backend.sources.chunk_artifacts import SourceChunkArtifact

# Must stay aligned with ``backend.sources.chunk_artifacts`` without importing it.
CHUNKER_VERSION = "local_lexical_v1"
CHUNK_ARTIFACT_SCHEMA_VERSION = 1

_PER_CHUNK_OVERHEAD_BYTES = 64
_PER_ENTRY_OVERHEAD_BYTES = 256


@dataclass(frozen=True)
class ChunkCacheKey:
    """Identity for one parsed chunk artifact.

    The object key already namespaces owner, notebook, and source and must be
    built server-side. Chunker and schema versions prevent a code upgrade from
    serving a stale parse of the same content digest.
    """

    artifact_object_key: str
    content_digest: str
    chunker_version: str
    schema_version: int

    @classmethod
    def current(cls, artifact_object_key: str, content_digest: str) -> ChunkCacheKey:
        """Build a key from a server object key and content digest.

        Args:
            artifact_object_key: Server-built derived-chunk object key.
            content_digest: SHA-256 hex digest of authoritative extracted text.

        Returns:
            A frozen key using the running chunker and schema versions.
            Does not authorize the source.
        """
        return cls(
            artifact_object_key=str(artifact_object_key),
            content_digest=str(content_digest),
            chunker_version=CHUNKER_VERSION,
            schema_version=CHUNK_ARTIFACT_SCHEMA_VERSION,
        )


@dataclass(frozen=True)
class ChunkCacheStats:
    """Snapshot of cache occupancy and cumulative process counters."""

    hits: int
    misses: int
    evictions: int
    entries: int
    total_bytes: int


@dataclass(frozen=True)
class _CachedEntry:
    """One stored artifact plus the byte cost used for eviction."""

    artifact: object
    cost_bytes: int


def _entry_cost_bytes(artifact: object) -> int:
    """Return the approximate byte cost of caching *artifact*.

    Args:
        artifact: Parsed chunk artifact exposing ``chunks`` with ``text``.

    Returns:
        UTF-8 text bytes plus 64 bytes per chunk and 256 bytes per entry.
    """
    chunks = getattr(artifact, "chunks", ()) or ()
    total = _PER_ENTRY_OVERHEAD_BYTES
    for chunk in chunks:
        text = getattr(chunk, "text", "") or ""
        total += len(str(text).encode("utf-8")) + _PER_CHUNK_OVERHEAD_BYTES
    return total


class StudentSourceChunkCache:
    """Thread-safe, byte-bounded LRU of parsed source chunk artifacts.

    FastAPI runs sync routes in a threadpool, so every mutation and LRU
    reorder is taken under a lock. A budget of ``0`` disables caching:
    ``get`` always misses and ``put`` is a no-op.
    """

    def __init__(self, *, max_bytes: int) -> None:
        """Create an empty cache with a byte budget.

        Args:
            max_bytes: Maximum approximate occupancy. ``0`` disables the
                cache. Negative values are treated as ``0``.
        """
        self._max_bytes = max(0, int(max_bytes))
        self._lock = threading.Lock()
        self._entries: OrderedDict[ChunkCacheKey, _CachedEntry] = OrderedDict()
        self._total_bytes = 0
        self._hits = 0
        self._misses = 0
        self._evictions = 0

    @property
    def max_bytes(self) -> int:
        """Return the configured byte budget. Zero disables caching."""
        return self._max_bytes

    def get(self, key: ChunkCacheKey) -> "SourceChunkArtifact | None":
        """Return a cached artifact or ``None`` on miss.

        Args:
            key: Server-built cache identity. Callers must already have
                authorized the underlying source.

        Returns:
            The parsed artifact when present and caching is enabled,
            otherwise ``None``.
        """
        with self._lock:
            if self._max_bytes <= 0:
                self._misses += 1
                return None
            entry = self._entries.get(key)
            if entry is None:
                self._misses += 1
                return None
            self._entries.move_to_end(key)
            self._hits += 1
            return entry.artifact  # type: ignore[return-value]

    def put(self, key: ChunkCacheKey, artifact: "SourceChunkArtifact") -> None:
        """Insert *artifact* under *key*, evicting least-recently-used entries.

        A single entry larger than the whole budget is not stored and does
        not evict existing entries. A budget of ``0`` makes this a no-op.

        Args:
            key: Server-built cache identity.
            artifact: Parsed chunk artifact. Treated as immutable by the cache.

        Returns:
            None.
        """
        if self._max_bytes <= 0:
            return
        cost = _entry_cost_bytes(artifact)
        if cost > self._max_bytes:
            return
        with self._lock:
            if self._max_bytes <= 0:
                return
            existing = self._entries.pop(key, None)
            if existing is not None:
                self._total_bytes = max(0, self._total_bytes - existing.cost_bytes)
            while self._entries and self._total_bytes + cost > self._max_bytes:
                _evicted_key, evicted = self._entries.popitem(last=False)
                self._total_bytes = max(0, self._total_bytes - evicted.cost_bytes)
                self._evictions += 1
            if self._total_bytes + cost > self._max_bytes:
                return
            self._entries[key] = _CachedEntry(artifact=artifact, cost_bytes=cost)
            self._total_bytes += cost

    def invalidate_prefix(self, object_key_prefix: str) -> int:
        """Drop entries whose object key starts with *object_key_prefix*.

        Args:
            object_key_prefix: Server-built object-key prefix, typically a
                source or notebook key. Empty prefixes match nothing.

        Returns:
            Number of entries removed.
        """
        prefix = str(object_key_prefix or "")
        if not prefix:
            return 0
        with self._lock:
            to_drop = [
                key
                for key in self._entries
                if key.artifact_object_key.startswith(prefix)
            ]
            for key in to_drop:
                entry = self._entries.pop(key)
                self._total_bytes = max(0, self._total_bytes - entry.cost_bytes)
            return len(to_drop)

    def clear(self) -> None:
        """Drop every cached artifact. Process counters are kept."""
        with self._lock:
            self._entries.clear()
            self._total_bytes = 0

    def stats(self) -> ChunkCacheStats:
        """Return occupancy and cumulative hit, miss, and eviction counters.

        Returns:
            A frozen snapshot. Counters are process-lifetime totals for this
            instance and are not reset by :meth:`clear`.
        """
        with self._lock:
            return ChunkCacheStats(
                hits=self._hits,
                misses=self._misses,
                evictions=self._evictions,
                entries=len(self._entries),
                total_bytes=self._total_bytes,
            )


_CACHE: StudentSourceChunkCache | None = None
_CACHE_LOCK = threading.Lock()


def student_source_chunk_cache() -> StudentSourceChunkCache:
    """Return the process-wide cache sized from application settings.

    Returns:
        The lazily created singleton. Creation is serialized with a lock.
    """
    global _CACHE
    with _CACHE_LOCK:
        if _CACHE is None:
            from backend.settings import settings

            _CACHE = StudentSourceChunkCache(
                max_bytes=settings.student_source_chunk_cache_max_bytes
            )
        return _CACHE


def reset_student_source_chunk_cache() -> None:
    """Drop the process singleton so tests can start from an empty cache."""
    global _CACHE
    with _CACHE_LOCK:
        _CACHE = None
