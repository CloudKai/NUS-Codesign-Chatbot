"""Byte-bounded student-source chunk cache tests. No object storage or AWS."""

from __future__ import annotations

import threading
from concurrent.futures import ThreadPoolExecutor, wait
from dataclasses import dataclass

from backend.sources.chunk_cache import (
    CHUNK_ARTIFACT_SCHEMA_VERSION,
    CHUNKER_VERSION,
    ChunkCacheKey,
    StudentSourceChunkCache,
    invalidate_cached_chunks_for_prefix,
    reset_student_source_chunk_cache,
    student_source_chunk_cache,
)
from backend.turn_perf import (
    SAFE_PERF_FIELDS,
    assert_payload_is_safe,
    begin_coach_turn_perf,
    record_count,
    record_student_source_chunk_cache_counters,
    reset_coach_turn_perf,
)


@dataclass(frozen=True)
class _FakeChunk:
    """Stand-in chunk with the ``text`` attribute the cache costs against."""

    text: str


@dataclass(frozen=True)
class _FakeArtifact:
    """Stand-in parsed artifact; independent of ``chunk_artifacts``."""

    chunks: tuple[_FakeChunk, ...]


def _artifact(*texts: str) -> _FakeArtifact:
    """Return a fake artifact whose chunks use the given texts."""
    return _FakeArtifact(chunks=tuple(_FakeChunk(text=text) for text in texts))


def _object_key(*, owner: str, notebook: str = "nb", source: str = "src") -> str:
    """Return a server-shaped derived-chunk object key for *owner*."""
    return (
        f"users/{owner}/notebooks/{notebook}/sources/{source}/derived/chunks.v1.json"
    )


def _key(
    object_key: str,
    digest: str = "a" * 64,
    *,
    chunker_version: str | None = None,
    schema_version: int | None = None,
) -> ChunkCacheKey:
    """Build a cache key, defaulting to the running chunker and schema."""
    if chunker_version is None and schema_version is None:
        return ChunkCacheKey.current(object_key, digest)
    return ChunkCacheKey(
        artifact_object_key=object_key,
        content_digest=digest,
        chunker_version=chunker_version or CHUNKER_VERSION,
        schema_version=(
            CHUNK_ARTIFACT_SCHEMA_VERSION if schema_version is None else schema_version
        ),
    )


def _measure_entry_bytes(artifact: _FakeArtifact) -> int:
    """Return the cache's approximate cost of one *artifact*."""
    probe = StudentSourceChunkCache(max_bytes=10_000_000)
    probe.put(_key(_object_key(owner="probe")), artifact)
    return probe.stats().total_bytes


def test_hit_after_put_and_miss_for_unknown_key() -> None:
    cache = StudentSourceChunkCache(max_bytes=10_000)
    stored = _artifact("hello")
    key = _key(_object_key(owner="alice"))
    cache.put(key, stored)
    assert cache.get(key) is stored
    unknown = _key(_object_key(owner="alice", source="other"))
    assert cache.get(unknown) is None
    stats = cache.stats()
    assert stats.hits == 1
    assert stats.misses == 1
    assert stats.entries == 1


def test_different_content_digest_is_miss() -> None:
    cache = StudentSourceChunkCache(max_bytes=10_000)
    object_key = _object_key(owner="alice")
    cache.put(_key(object_key, "digest-one"), _artifact("hello"))
    assert cache.get(_key(object_key, "digest-two")) is None
    assert cache.get(_key(object_key, "digest-one")) is not None
    assert cache.stats().misses == 1


def test_different_chunker_or_schema_version_is_miss() -> None:
    cache = StudentSourceChunkCache(max_bytes=10_000)
    object_key = _object_key(owner="alice")
    digest = "b" * 64
    cache.put(_key(object_key, digest), _artifact("hello"))
    assert (
        cache.get(_key(object_key, digest, chunker_version="local_lexical_v2")) is None
    )
    assert cache.get(_key(object_key, digest, schema_version=2)) is None
    assert cache.get(_key(object_key, digest)) is not None


def test_byte_bound_evicts_lru_and_stays_within_budget() -> None:
    small = _artifact("x")
    entry_bytes = _measure_entry_bytes(small)
    cache = StudentSourceChunkCache(max_bytes=entry_bytes * 2)
    first = _key(_object_key(owner="alice", source="s1"))
    second = _key(_object_key(owner="alice", source="s2"))
    third = _key(_object_key(owner="alice", source="s3"))
    cache.put(first, small)
    cache.put(second, small)
    assert cache.get(first) is small
    cache.put(third, small)
    stats = cache.stats()
    assert stats.total_bytes <= cache.max_bytes
    assert stats.entries == 2
    assert stats.evictions == 1
    assert cache.get(second) is None
    assert cache.get(first) is small
    assert cache.get(third) is small


def test_many_unique_keys_stay_bounded() -> None:
    small = _artifact("x")
    entry_bytes = _measure_entry_bytes(small)
    budget = entry_bytes * 8
    cache = StudentSourceChunkCache(max_bytes=budget)
    for index in range(3_000):
        cache.put(
            _key(_object_key(owner="alice", source=f"s{index}")),
            small,
        )
    stats = cache.stats()
    assert stats.total_bytes <= budget
    assert stats.entries <= 8
    assert stats.evictions >= 3_000 - 8


def test_oversized_entry_is_not_cached_and_does_not_evict() -> None:
    small = _artifact("x")
    entry_bytes = _measure_entry_bytes(small)
    cache = StudentSourceChunkCache(max_bytes=entry_bytes * 2)
    first = _key(_object_key(owner="alice", source="s1"))
    second = _key(_object_key(owner="alice", source="s2"))
    cache.put(first, small)
    cache.put(second, small)
    huge = _artifact("y" * (entry_bytes * 8))
    oversized = _key(_object_key(owner="alice", source="huge"))
    cache.put(oversized, huge)
    stats = cache.stats()
    assert stats.entries == 2
    assert stats.evictions == 0
    assert stats.total_bytes <= cache.max_bytes
    assert cache.get(first) is small
    assert cache.get(second) is small
    assert cache.get(oversized) is None


def test_zero_budget_disables_cache() -> None:
    cache = StudentSourceChunkCache(max_bytes=0)
    key = _key(_object_key(owner="alice"))
    cache.put(key, _artifact("hello"))
    assert cache.get(key) is None
    stats = cache.stats()
    assert stats.total_bytes == 0
    assert stats.entries == 0
    assert stats.hits == 0
    assert stats.misses == 1
    assert stats.evictions == 0
    cache.put(key, _artifact("y" * 100_000))
    assert cache.stats().total_bytes == 0


def test_invalidate_prefix_removes_only_matching_entries() -> None:
    cache = StudentSourceChunkCache(max_bytes=50_000)
    artifact = _artifact("hello")
    alice_one = _key(_object_key(owner="alice", notebook="n1", source="s1"))
    alice_two = _key(_object_key(owner="alice", notebook="n1", source="s2"))
    alice_other_nb = _key(_object_key(owner="alice", notebook="n2", source="s1"))
    bob = _key(_object_key(owner="bob", notebook="n1", source="s1"))
    cache.put(alice_one, artifact)
    cache.put(alice_two, artifact)
    cache.put(alice_other_nb, artifact)
    cache.put(bob, artifact)
    removed = cache.invalidate_prefix("users/alice/notebooks/n1/")
    assert removed == 2
    assert cache.get(alice_one) is None
    assert cache.get(alice_two) is None
    assert cache.get(alice_other_nb) is artifact
    assert cache.get(bob) is artifact
    assert cache.invalidate_prefix("") == 0
    assert cache.stats().entries == 2


def test_invalidate_cached_chunks_for_prefix_never_raises(monkeypatch) -> None:
    """Best-effort invalidation must not raise to storage-cleanup callers."""
    reset_student_source_chunk_cache()
    cache = student_source_chunk_cache()

    def _boom(_prefix: str) -> int:
        raise RuntimeError("cache boom")

    monkeypatch.setattr(cache, "invalidate_prefix", _boom)
    invalidate_cached_chunks_for_prefix("users/alice/notebooks/n1/")
    reset_student_source_chunk_cache()


def test_different_owners_do_not_collide() -> None:
    cache = StudentSourceChunkCache(max_bytes=50_000)
    alice_key = _key(_object_key(owner="owner-a"), "shared-digest")
    bob_key = _key(_object_key(owner="owner-b"), "shared-digest")
    alice_artifact = _artifact("from-alice")
    bob_artifact = _artifact("from-bob")
    cache.put(alice_key, alice_artifact)
    cache.put(bob_key, bob_artifact)
    assert cache.get(alice_key) is alice_artifact
    assert cache.get(bob_key) is bob_artifact
    assert alice_key != bob_key


def test_thread_safety_smoke_stays_bounded() -> None:
    small = _artifact("hello world")
    entry_bytes = _measure_entry_bytes(small)
    budget = entry_bytes * 16
    cache = StudentSourceChunkCache(max_bytes=budget)
    errors: list[BaseException] = []
    error_lock = threading.Lock()

    def worker(owner_index: int) -> None:
        try:
            for index in range(200):
                key = _key(
                    _object_key(owner=f"o{owner_index}", source=f"s{index % 40}"),
                    f"{index % 12:064d}",
                )
                cache.put(key, small)
                cache.get(key)
        except BaseException as exc:
            with error_lock:
                errors.append(exc)

    with ThreadPoolExecutor(max_workers=8) as pool:
        futures = [pool.submit(worker, index) for index in range(8)]
        wait(futures)
    assert errors == []
    stats = cache.stats()
    assert stats.total_bytes <= budget
    assert stats.entries <= 16


def test_module_singleton_reset_creates_fresh_cache() -> None:
    from backend.settings import settings

    reset_student_source_chunk_cache()
    first = student_source_chunk_cache()
    second = student_source_chunk_cache()
    assert first is second
    assert first.max_bytes == settings.student_source_chunk_cache_max_bytes
    assert 0 <= first.max_bytes <= 268_435_456
    reset_student_source_chunk_cache()
    third = student_source_chunk_cache()
    assert third is not first
    reset_student_source_chunk_cache()


def test_chunk_cache_perf_fields_are_safe_counts() -> None:
    expected = {
        "student_source_selected_count",
        "student_source_precomputed_hit",
        "student_source_precomputed_miss",
        "student_source_dynamic_fallback",
        "student_source_chunk_cache_hit",
        "student_source_chunk_cache_miss",
        "student_source_chunk_cache_eviction",
        "student_source_chunk_artifact_load_ms",
        "student_source_chunk_parse_ms",
        "student_source_chunk_build_ms",
        "student_source_chunk_rank_ms",
        "student_source_candidate_chunk_count",
        "student_source_returned_chunk_count",
    }
    assert expected <= SAFE_PERF_FIELDS
    perf = begin_coach_turn_perf()
    try:
        record_count("student_source_chunk_cache_hit", 2)
        record_count("student_source_precomputed_miss")
        record_student_source_chunk_cache_counters(misses=3, evictions=1)
        snapshot = perf.snapshot()
        assert snapshot["student_source_chunk_cache_hit"] == 2
        assert snapshot["student_source_precomputed_miss"] == 1
        assert snapshot["student_source_chunk_cache_miss"] == 3
        assert snapshot["student_source_chunk_cache_eviction"] == 1
        assert_payload_is_safe(snapshot)
    finally:
        reset_coach_turn_perf()
