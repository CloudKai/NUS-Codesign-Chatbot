"""Hydrate selected student sources for retrieval without listing objects.

Callers must pass sources already authorized through an owner-scoped store
listing. This module never consults the chunk cache for authorization, never
discovers artifacts with ``list_prefix``, and never imports Streamlit.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from typing import Any

from backend.persistence.object_keys import (
    build_extracted_text_object_key,
    build_source_chunks_object_key,
)
from backend.persistence.ports import FileStorage
from backend.retrieval import (
    RetrievalSource,
    is_virtual_shared_course_record,
    retrieval_sources_from_notebook,
)
from backend.sources.chunk_artifacts import chunk_texts, parse_chunk_artifact
from backend.sources.chunk_cache import ChunkCacheKey, student_source_chunk_cache
from backend.turn_perf import (
    current_perf,
    elapsed_ms,
    record_count,
    record_field,
    record_student_source_chunk_cache_counters,
)

logger = logging.getLogger(__name__)


@dataclass
class _HydrateMetrics:
    """Privacy-safe counters accumulated while hydrating one selected set."""

    selected_count: int = 0
    precomputed_hit: int = 0
    precomputed_miss: int = 0
    dynamic_fallback: int = 0


def hydrate_selected_retrieval_sources(
    sources: Sequence[Mapping[str, Any]],
    *,
    owner_id: str,
    notebook_id: str,
    storage: FileStorage | None = None,
) -> tuple[RetrievalSource, ...]:
    """Attach precomputed chunks to already-authorized selected sources.

    Builds the same ``S1..Sn`` labeling as
    :func:`retrieval_sources_from_notebook`, then loads chunk artifacts only
    for selected student textual sources. Course/virtual rows and images are
    left unchanged. Cache lookups happen only after this owner-scoped list.

    Args:
        sources: Selected notebook source dictionaries from an authorized
            listing. Unselected rows must not be included.
        owner_id: Authenticated store owner id used to build object keys.
        notebook_id: Notebook that owns the sources.
        storage: Optional object storage. When omitted, the process FileStorage
            singleton is used.

    Returns:
        Frozen retrieval sources with ``chunks`` set on a successful
        precomputed path, or ``chunks=None`` after a dynamic extracted-text
        fallback. Never raises on a missing or invalid chunk artifact.

    Raises:
        None. Storage misses and corrupt artifacts fall back to extracted
        text. Other storage errors propagate from ``get_bytes``.
    """
    labeled = retrieval_sources_from_notebook(sources)
    hydrate_started = time.perf_counter()
    originals = {
        str(source.get("id") or "").strip(): source
        for source in sources
        if str(source.get("id") or "").strip()
    }
    if storage is None:
        from backend.persistence.factory import get_file_storage

        storage = get_file_storage()
    cache = student_source_chunk_cache()
    stats_before = cache.stats()
    metrics = _HydrateMetrics()
    hydrated: list[RetrievalSource] = []
    for item in labeled:
        original = originals.get(item.source_id, {})
        if _is_course_source(item, original) or _is_image_source(item, original):
            hydrated.append(item)
            continue
        metrics.selected_count += 1
        hydrated.append(
            _hydrate_student_textual_source(
                item,
                original,
                owner_id=owner_id,
                notebook_id=notebook_id,
                storage=storage,
                metrics=metrics,
            )
        )
    stats_after = cache.stats()
    record_field("hydrate_total_ms", elapsed_ms(hydrate_started))
    record_field("student_source_selected_count", metrics.selected_count)
    record_count("student_source_precomputed_hit", metrics.precomputed_hit)
    record_count("student_source_precomputed_miss", metrics.precomputed_miss)
    record_count("student_source_dynamic_fallback", metrics.dynamic_fallback)
    record_student_source_chunk_cache_counters(
        hits=stats_after.hits - stats_before.hits,
        misses=stats_after.misses - stats_before.misses,
        evictions=stats_after.evictions - stats_before.evictions,
    )
    return tuple(hydrated)


def _is_course_source(
    source: RetrievalSource, original: Mapping[str, Any]
) -> bool:
    """Return whether *source* is a shared/virtual course object."""
    if is_virtual_shared_course_record(source):
        return True
    return bool(original) and is_virtual_shared_course_record(original)


def _is_image_source(
    source: RetrievalSource, original: Mapping[str, Any]
) -> bool:
    """Return whether *source* is an image and must skip chunk artifacts."""
    kind = str(source.kind or original.get("kind") or "").strip().lower()
    mime = str(
        source.mime
        or original.get("mime")
        or original.get("content_type")
        or ""
    ).strip().lower()
    return kind == "image" or mime.startswith("image/")


def _hydrate_student_textual_source(
    source: RetrievalSource,
    original: Mapping[str, Any],
    *,
    owner_id: str,
    notebook_id: str,
    storage: FileStorage,
    metrics: _HydrateMetrics,
) -> RetrievalSource:
    """Load precomputed chunks or fall back to extracted text for one source.

    Args:
        source: Labeled retrieval source from the metadata pass.
        original: Authorized selected source dictionary.
        owner_id: Authenticated owner id for server-built object keys.
        notebook_id: Notebook that owns the source.
        storage: Object storage used for exact key reads.
        metrics: Mutable per-turn counters.

    Returns:
        *source* with ``chunks`` attached on the precomputed path, or with
        extracted text and ``chunks=None`` after a dynamic fallback.
    """
    metadata = original.get("metadata")
    metadata = metadata if isinstance(metadata, dict) else {}
    digest = str(metadata.get("extracted_text_sha256") or "").strip()
    if not digest:
        return _fallback_extracted(
            source,
            original,
            owner_id=owner_id,
            notebook_id=notebook_id,
            storage=storage,
            metrics=metrics,
        )
    artifact_key = build_source_chunks_object_key(
        user_id=owner_id,
        notebook_id=notebook_id,
        source_id=source.source_id,
    )
    cache = student_source_chunk_cache()
    cache_key = ChunkCacheKey.current(artifact_key, digest)
    cached = cache.get(cache_key)
    if cached is not None:
        metrics.precomputed_hit += 1
        return replace(source, chunks=chunk_texts(cached))
    load_started = time.perf_counter()
    try:
        raw = storage.get_bytes(artifact_key)
    except FileNotFoundError:
        _add_ms("student_source_chunk_artifact_load_ms", load_started)
        logger.info("student source hydrate category=missing_artifact size=0")
        metrics.precomputed_miss += 1
        return _fallback_extracted(
            source,
            original,
            owner_id=owner_id,
            notebook_id=notebook_id,
            storage=storage,
            metrics=metrics,
        )
    _add_ms("student_source_chunk_artifact_load_ms", load_started)
    parse_started = time.perf_counter()
    artifact = parse_chunk_artifact(
        raw,
        expected_source_id=source.source_id,
        expected_digest=digest,
    )
    _add_ms("student_source_chunk_parse_ms", parse_started)
    if artifact is None:
        logger.info(
            "student source hydrate category=invalid_artifact size=%s",
            len(raw),
        )
        metrics.precomputed_miss += 1
        return _fallback_extracted(
            source,
            original,
            owner_id=owner_id,
            notebook_id=notebook_id,
            storage=storage,
            metrics=metrics,
        )
    cache.put(cache_key, artifact)
    metrics.precomputed_hit += 1
    return replace(source, chunks=chunk_texts(artifact))


def _fallback_extracted(
    source: RetrievalSource,
    original: Mapping[str, Any],
    *,
    owner_id: str,
    notebook_id: str,
    storage: FileStorage,
    metrics: _HydrateMetrics,
) -> RetrievalSource:
    """Load extracted text and leave chunking to retrieval candidates.

    Args:
        source: Labeled retrieval source from the metadata pass.
        original: Authorized selected source dictionary.
        owner_id: Authenticated owner id for the fallback object key.
        notebook_id: Notebook that owns the source.
        storage: Object storage used for one exact extracted-text GET.
        metrics: Mutable per-turn counters.

    Returns:
        *source* with extracted text and ``chunks=None`` when bytes exist,
        otherwise the original placeholder labeling unchanged.
    """
    metrics.dynamic_fallback += 1
    key = str(original.get("extracted_text_key") or "").strip()
    if not key:
        key = build_extracted_text_object_key(
            user_id=owner_id,
            notebook_id=notebook_id,
            source_id=source.source_id,
        )
    try:
        raw = storage.get_bytes(key)
    except FileNotFoundError:
        logger.info("student source hydrate category=extracted_missing size=0")
        return source
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError:
        text = raw.decode("utf-8", errors="replace")
    logger.info(
        "student source hydrate category=dynamic_fallback size=%s",
        len(raw),
    )
    cleaned = text.strip()
    if not cleaned:
        return source
    return replace(source, text=cleaned, chunks=None)


def _add_ms(name: str, started: float) -> None:
    """Add elapsed milliseconds onto the current turn-perf accumulator."""
    perf = current_perf()
    if perf is not None:
        perf.add_ms(name, elapsed_ms(started))
