"""Disposable derived chunk artifacts for selected-source retrieval.

``derived/extracted.txt`` remains the authoritative source text. The sibling
``derived/chunks.v1.json`` object is an optimisation so chat turns can skip
re-chunking. Any missing, oversize, or invalid artifact means callers must
fall back to chunking extracted text at query time.

This module never imports Streamlit or ``backend.sources.chunk_cache``.
"""

from __future__ import annotations

import hashlib
import json
import logging
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from backend.persistence.object_keys import build_source_chunks_object_key
from backend.persistence.ports import FileStorage
from backend.retrieval import canonical_chunk_text

logger = logging.getLogger(__name__)

CHUNK_ARTIFACT_SCHEMA_VERSION = 1
CHUNKER_VERSION = "local_lexical_v1"
DEFAULT_CHUNK_CHARS = 1_800
DEFAULT_OVERLAP_CHARS = 220
MAX_ARTIFACT_CHUNKS = 512
MAX_ARTIFACT_CHUNK_CHARS = 8_000
MAX_ARTIFACT_BYTES = 1_048_576


class SourceChunkRecord(BaseModel):
    """One ordered chunk inside a derived source artifact."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    chunk_index: int = Field(ge=1)
    text: str = Field(min_length=1, max_length=MAX_ARTIFACT_CHUNK_CHARS)


class SourceChunkArtifact(BaseModel):
    """Versioned, content-addressed chunk list for one source."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    schema_version: int
    chunker_version: str
    source_id: str
    content_digest: str
    chunk_chars: int
    overlap_chars: int
    chunks: tuple[SourceChunkRecord, ...] = Field(max_length=MAX_ARTIFACT_CHUNKS)

    @model_validator(mode="after")
    def chunk_indexes_are_sequential(self) -> SourceChunkArtifact:
        """Require ``chunk_index`` values to be exactly ``1..len(chunks)`` in order."""
        expected = tuple(range(1, len(self.chunks) + 1))
        actual = tuple(record.chunk_index for record in self.chunks)
        if actual != expected:
            raise ValueError("chunk_index values must be 1..len(chunks) in order")
        return self


def extracted_text_digest(text: str) -> str:
    """Return the SHA-256 hex digest of UTF-8 extracted text.

    Args:
        text: Authoritative extracted source text.

    Returns:
        Hex-encoded SHA-256 digest used as the content version identifier.
    """
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def build_chunk_artifact(*, source_id: str, text: str) -> SourceChunkArtifact | None:
    """Build a disposable chunk artifact from extracted source text.

    Args:
        source_id: Persisted source identifier.
        text: Authoritative extracted text.

    Returns:
        A validated artifact, or ``None`` when the text yields no chunks or
        more than ``MAX_ARTIFACT_CHUNKS``. Never raises on ordinary content.
    """
    try:
        pieces = canonical_chunk_text(
            text,
            chunk_chars=DEFAULT_CHUNK_CHARS,
            overlap_chars=DEFAULT_OVERLAP_CHARS,
        )
        if not pieces or len(pieces) > MAX_ARTIFACT_CHUNKS:
            return None
        records = tuple(
            SourceChunkRecord(chunk_index=index, text=piece)
            for index, piece in enumerate(pieces, start=1)
        )
        return SourceChunkArtifact(
            schema_version=CHUNK_ARTIFACT_SCHEMA_VERSION,
            chunker_version=CHUNKER_VERSION,
            source_id=source_id,
            content_digest=extracted_text_digest(text),
            chunk_chars=DEFAULT_CHUNK_CHARS,
            overlap_chars=DEFAULT_OVERLAP_CHARS,
            chunks=records,
        )
    except Exception:  # noqa: BLE001 - ordinary content must not raise
        return None


def serialize_chunk_artifact(artifact: SourceChunkArtifact) -> bytes:
    """Encode *artifact* as deterministic UTF-8 JSON.

    Args:
        artifact: Validated chunk artifact.

    Returns:
        JSON bytes, or ``b""`` when the payload exceeds ``MAX_ARTIFACT_BYTES``.
    """
    payload: dict[str, Any] = artifact.model_dump(mode="json")
    encoded = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")
    if len(encoded) > MAX_ARTIFACT_BYTES:
        return b""
    return encoded


def parse_chunk_artifact(
    raw: bytes,
    *,
    expected_source_id: str,
    expected_digest: str,
) -> SourceChunkArtifact | None:
    """Parse and validate a stored chunk artifact.

    Returns ``None`` (never raises) when the payload is unusable. Logs one
    privacy-safe warning with a category label and numeric size only — never
    chunk text, extracted text, object keys, owner ids, or notebook ids.

    Args:
        raw: Stored artifact bytes.
        expected_source_id: Source id that must match the payload.
        expected_digest: SHA-256 digest of the current extracted text.

    Returns:
        The validated artifact, or ``None`` on any validation failure.
    """
    size = len(raw)
    if size > MAX_ARTIFACT_BYTES:
        _reject("oversize", size)
        return None
    try:
        decoded = raw.decode("utf-8")
    except UnicodeDecodeError:
        _reject("decode", size)
        return None
    try:
        payload = json.loads(decoded)
    except json.JSONDecodeError:
        _reject("json", size)
        return None
    try:
        artifact = SourceChunkArtifact.model_validate(payload)
    except ValidationError:
        _reject("schema", size)
        return None
    if artifact.schema_version != CHUNK_ARTIFACT_SCHEMA_VERSION:
        _reject("schema_version", size)
        return None
    if artifact.chunker_version != CHUNKER_VERSION:
        _reject("chunker_version", size)
        return None
    if artifact.source_id != expected_source_id:
        _reject("source_mismatch", size)
        return None
    if artifact.content_digest != expected_digest:
        _reject("digest_mismatch", size)
        return None
    return artifact


def chunk_texts(artifact: SourceChunkArtifact) -> tuple[str, ...]:
    """Return chunk strings in artifact order.

    Args:
        artifact: Parsed chunk artifact.

    Returns:
        Ordered chunk texts ready for retrieval candidates.
    """
    return tuple(record.text for record in artifact.chunks)


def write_chunk_artifact_best_effort(
    *,
    storage: FileStorage,
    user_id: str,
    notebook_id: str,
    source_id: str,
    text: str,
    digest: str,
) -> bool:
    """Write a chunk artifact without failing the caller on errors.

    Precomputation is an optimisation. Failures are logged without object keys,
    owner ids, notebook ids, or source text, and never raised.

    Args:
        storage: Object storage adapter already used for ``extracted.txt``.
        user_id: Authenticated owner id used in the object key.
        notebook_id: Notebook that owns the source.
        source_id: Persisted source identifier.
        text: Authoritative extracted text.
        digest: SHA-256 digest previously computed from *text*.

    Returns:
        ``True`` when a payload was stored; ``False`` on skip or failure.
    """
    try:
        artifact = build_chunk_artifact(source_id=source_id, text=text)
        if artifact is None:
            return False
        if artifact.content_digest != digest:
            logger.warning(
                "chunk artifact write skipped category=digest_mismatch size=%s",
                len(digest),
            )
            return False
        payload = serialize_chunk_artifact(artifact)
        if not payload:
            logger.warning("chunk artifact write skipped category=oversize size=%s", 0)
            return False
        key = build_source_chunks_object_key(
            user_id=user_id,
            notebook_id=notebook_id,
            source_id=source_id,
        )
        storage.put_bytes(
            key=key,
            data=payload,
            content_type="application/json; charset=utf-8",
        )
        return True
    except Exception:  # noqa: BLE001 - uploads must succeed without the artifact
        logger.warning(
            "chunk artifact write failed category=optimisation size=%s",
            len(text),
        )
        return False


def _reject(category: str, size: int) -> None:
    """Log one privacy-safe rejection with a category and byte size."""
    logger.warning("chunk artifact rejected category=%s size=%s", category, size)
