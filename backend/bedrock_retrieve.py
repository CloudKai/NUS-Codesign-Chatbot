"""Bedrock Knowledge Base ``Retrieve`` adapter for selected course sources.

This adapter implements :class:`backend.retrieval.ContextRetriever`. It calls
``Retrieve`` only (never ``RetrieveAndGenerate``), maps S3 locations onto
selected locked Lecture Notes/Readings ``[S#]`` labels, and drops foreign
keys. Student uploads stay on :class:`LocalChunkRetriever`. Tests inject a
fake client so automated runs never contact AWS.
"""

from __future__ import annotations

import logging
from collections.abc import Mapping
from typing import Any
from urllib.parse import unquote, urlparse

from .retrieval import (
    CompositeContextRetriever,
    ContextRetriever,
    LocalChunkRetriever,
    RetrievalQuery,
    RetrievalResult,
    RetrievalSource,
    RetrievedChunk,
    bounded_retrieval_result,
    is_course_retrieval_source,
)
from .settings import settings

logger = logging.getLogger(__name__)

_DEFAULT_RESULTS = 8
_MAX_CONTEXT_CHARS = 16_000


def _normalize_key(value: str) -> str:
    """Return a comparable object-key form without a leading slash."""
    return unquote(str(value or "").strip()).lstrip("/")


def _s3_uri_parts(uri: str) -> tuple[str, str]:
    """Split ``s3://bucket/key`` into ``(bucket, key)``. Empty on failure."""
    cleaned = str(uri or "").strip()
    if not cleaned:
        return "", ""
    parsed = urlparse(cleaned)
    if parsed.scheme.lower() != "s3":
        return "", _normalize_key(cleaned)
    return str(parsed.netloc or "").strip(), _normalize_key(parsed.path)


def _location_uri(item: Mapping[str, Any]) -> str:
    """Return the S3 URI from one Retrieve result, if present."""
    location = item.get("location")
    if not isinstance(location, Mapping):
        return ""
    s3_location = location.get("s3Location")
    if isinstance(s3_location, Mapping):
        uri = str(s3_location.get("uri") or "").strip()
        if uri:
            return uri
    return str(location.get("uri") or "").strip()


def _source_keys(source: RetrievalSource) -> set[str]:
    """Return comparable object keys for one selected notebook source."""
    keys: set[str] = set()
    for raw in (source.object_key, source.url):
        cleaned = _normalize_key(str(raw or ""))
        if not cleaned:
            continue
        keys.add(cleaned)
        if cleaned.lower().startswith("s3://"):
            _bucket, key = _s3_uri_parts(cleaned)
            if key:
                keys.add(key)
    return keys


def _keys_match(result_key: str, source_keys: set[str]) -> bool:
    """Return whether a Retrieve object key belongs to a selected source."""
    candidate = _normalize_key(result_key)
    if not candidate:
        return False
    for source_key in source_keys:
        if not source_key:
            continue
        if candidate == source_key:
            return True
        if candidate.endswith(source_key) or source_key.endswith(candidate):
            return True
    return False


def _match_selected_source(
    item: Mapping[str, Any],
    sources: tuple[RetrievalSource, ...],
    *,
    course_bucket: str,
) -> RetrievalSource | None:
    """Map one Retrieve hit onto a selected course source, or drop it."""
    uri = _location_uri(item)
    bucket, key = _s3_uri_parts(uri)
    expected_bucket = str(course_bucket or "").strip()
    if expected_bucket and bucket and bucket != expected_bucket:
        return None
    if not key:
        return None
    for source in sources:
        if _keys_match(key, _source_keys(source)):
            return source
    return None


def _excerpt_text(item: Mapping[str, Any]) -> str:
    """Return the Retrieve content text without opaque adapter envelopes."""
    content = item.get("content")
    if isinstance(content, Mapping):
        text = str(content.get("text") or "").strip()
        if text:
            return text
    return str(item.get("content") or "").strip() if isinstance(item.get("content"), str) else ""


def _result_score(item: Mapping[str, Any]) -> float:
    """Return a finite Retrieve score, defaulting to 0.0."""
    try:
        return float(item.get("score") or 0.0)
    except (TypeError, ValueError):
        return 0.0


class BedrockKnowledgeBaseRetriever:
    """Call Bedrock Agent Runtime ``Retrieve`` for selected course sources."""

    def __init__(
        self,
        knowledge_base_id: str,
        *,
        region: str = "us-west-2",
        number_of_results: int = _DEFAULT_RESULTS,
        max_context_chars: int = _MAX_CONTEXT_CHARS,
        course_bucket: str = "",
        client: Any | None = None,
    ) -> None:
        """Create the adapter with an injected or lazily constructed client.

        Args:
            knowledge_base_id: Bedrock Knowledge Base id (non-secret).
            region: AWS region for the data-plane client.
            number_of_results: ``vectorSearchConfiguration.numberOfResults``.
            max_context_chars: Prompt budget after selected-source filtering.
            course_bucket: When set, Retrieve hits from other buckets are dropped.
            client: Optional injected ``bedrock-agent-runtime`` client for tests.
        """
        self._knowledge_base_id = str(knowledge_base_id or "").strip()
        self._region = str(region or "").strip() or "us-west-2"
        self._number_of_results = max(1, int(number_of_results))
        self._max_context_chars = max(1, int(max_context_chars))
        self._course_bucket = str(course_bucket or "").strip()
        self._client = client

    def _runtime_client(self) -> Any:
        """Return the injected client or construct a bedrock-agent-runtime client."""
        if self._client is not None:
            return self._client
        try:
            import boto3
            from botocore.config import Config
        except ImportError:
            logger.warning("Knowledge Base client libraries are unavailable")
            return None
        config = Config(
            retries={"max_attempts": 1, "mode": "standard"},
            read_timeout=30.0,
            connect_timeout=10.0,
        )
        self._client = boto3.client(
            "bedrock-agent-runtime",
            region_name=self._region,
            config=config,
        )
        return self._client

    def retrieve(self, query: RetrievalQuery) -> RetrievalResult:
        """Return selected-source chunks from Knowledge Base Retrieve.

        Foreign S3 keys and non-course sources are dropped. AWS and SDK
        failures return an empty result so the composer can apply evidence-gap
        rules instead of inventing sources.
        """
        if not self._knowledge_base_id:
            return RetrievalResult(context="", chunks=())
        course_sources = tuple(
            source for source in query.sources if is_course_retrieval_source(source)
        )
        if not course_sources:
            return RetrievalResult(context="", chunks=())
        client = self._runtime_client()
        if client is None:
            return RetrievalResult(context="", chunks=())
        query_text = " ".join(str(query.current_message or "").split()).strip()
        if not query_text:
            return RetrievalResult(context="", chunks=())
        try:
            response = client.retrieve(
                knowledgeBaseId=self._knowledge_base_id,
                retrievalQuery={"text": query_text},
                retrievalConfiguration={
                    "vectorSearchConfiguration": {
                        "numberOfResults": self._number_of_results,
                    }
                },
            )
        except Exception:
            logger.warning("Knowledge Base Retrieve failed", exc_info=False)
            return RetrievalResult(context="", chunks=())
        if not isinstance(response, Mapping):
            return RetrievalResult(context="", chunks=())
        raw_hits = response.get("retrievalResults")
        if not isinstance(raw_hits, list):
            return RetrievalResult(context="", chunks=())
        chunks: list[RetrievedChunk] = []
        per_source: dict[str, int] = {}
        for item in raw_hits:
            if not isinstance(item, Mapping):
                continue
            source = _match_selected_source(
                item,
                course_sources,
                course_bucket=self._course_bucket,
            )
            if source is None:
                continue
            text = _excerpt_text(item)
            if not text:
                continue
            count = per_source.get(source.source_id, 0) + 1
            per_source[source.source_id] = count
            source_index = next(
                (
                    index
                    for index, candidate in enumerate(query.sources, start=1)
                    if candidate.source_id == source.source_id
                ),
                1,
            )
            chunks.append(
                RetrievedChunk(
                    source_id=source.source_id,
                    label=source.label,
                    title=source.title,
                    chunk_id=f"{source.label}-KB{count}",
                    text=text,
                    score=round(_result_score(item), 6),
                    source_index=source_index,
                    chunk_index=count,
                    url=source.url,
                    group=source.group,
                )
            )
        return bounded_retrieval_result(
            chunks, max_context_chars=self._max_context_chars
        )


def configured_context_retriever(
    *,
    client: Any | None = None,
) -> ContextRetriever:
    """Return local retrieval, or a KB+local composite when configured.

    Mock-mode and an empty ``KNOWLEDGE_BASE_ID`` keep
    :class:`LocalChunkRetriever` so pytest never calls AWS. Production sets
    the Knowledge Base id and injects this composite into
    :class:`CoachApplicationService`.
    """
    knowledge_base_id = str(getattr(settings, "knowledge_base_id", "") or "").strip()
    if (
        not knowledge_base_id
        or settings.model_provider == "mock"
        or settings.mock_openai
    ):
        return LocalChunkRetriever()
    region = (
        str(getattr(settings, "knowledge_base_region", "") or "").strip()
        or str(settings.aws_region or "").strip()
        or "us-west-2"
    )
    knowledge_base = BedrockKnowledgeBaseRetriever(
        knowledge_base_id,
        region=region,
        course_bucket=str(settings.course_materials_bucket or "").strip(),
        client=client,
    )
    return CompositeContextRetriever(
        knowledge_base=knowledge_base,
        local=LocalChunkRetriever(),
        max_context_chars=_MAX_CONTEXT_CHARS,
    )
