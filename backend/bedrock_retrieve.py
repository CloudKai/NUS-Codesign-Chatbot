"""Bedrock Knowledge Base ``Retrieve`` adapter for selected course sources.

This adapter implements :class:`backend.retrieval.ContextRetriever`. It calls
``Retrieve`` only (never ``RetrieveAndGenerate``), maps S3 locations onto
selected locked Lecture Notes/Readings ``[S#]`` labels, and drops foreign
keys. Student uploads stay on :class:`LocalChunkRetriever`. Tests inject a
fake client so automated runs never contact AWS.
"""

from __future__ import annotations

import logging
import re
from collections.abc import Mapping
from typing import Any
from urllib.parse import ParseResult, unquote, urlparse

from .retrieval import (
    CompositeContextRetriever,
    ContextRetriever,
    LocalChunkRetriever,
    RetrievalQuery,
    RetrievalResult,
    RetrievalSource,
    RetrievedChunk,
    bounded_retrieval_result,
    course_material_id_from_object_key,
    expand_session_query_text,
    is_course_retrieval_source,
)
from .settings import settings

logger = logging.getLogger(__name__)

_DEFAULT_RESULTS = 8
_MAX_CONTEXT_CHARS = 16_000
_RETRIEVE_READ_TIMEOUT_SECONDS = 15.0
_RETRIEVE_CONNECT_TIMEOUT_SECONDS = 3.0
COURSE_MATERIAL_METADATA_KEY = "course_material_id"
_S3_VIRTUAL_HOST = re.compile(
    r"^(?P<bucket>.+)\.s3(?:[.-](?:dualstack\.)?(?:[a-z0-9-]+))?\.amazonaws\.com$",
    re.IGNORECASE,
)
_S3_PATH_HOST = re.compile(
    r"^s3(?:[.-](?:dualstack\.)?(?:[a-z0-9-]+))?\.amazonaws\.com$",
    re.IGNORECASE,
)

_TIMEOUT_EXCEPTION_NAMES = frozenset(
    {
        "ConnectTimeoutError",
        "ReadTimeoutError",
        "EndpointConnectionError",
        "ConnectionClosedError",
        "ConnectTimeout",
        "ReadTimeout",
        "TimeoutError",
    }
)


def classify_retrieve_failure(error: BaseException) -> str:
    """Return a secret-safe category for one Knowledge Base Retrieve failure.

    Args:
        error: Exception raised by the SDK or ``client.retrieve``.

    Returns:
        One of ``access_denied``, ``not_found``, ``validation_error``,
        ``throttled``, ``timeout``, or ``client_error``.
    """
    name = type(error).__name__
    code = ""
    response = getattr(error, "response", None)
    if isinstance(response, Mapping):
        payload = response.get("Error")
        if isinstance(payload, Mapping):
            code = str(payload.get("Code") or "").strip()
    combined = f"{code} {name}".casefold()
    if "accessdenied" in combined or "unauthorized" in combined:
        return "access_denied"
    if "resourcenotfound" in combined:
        return "not_found"
    if "validation" in combined:
        return "validation_error"
    if "throttl" in combined or "toomanyrequests" in combined:
        return "throttled"
    if name in _TIMEOUT_EXCEPTION_NAMES or "timeout" in combined:
        return "timeout"
    return "client_error"


def sanitized_s3_uri(uri: str) -> str:
    """Return ``s3://bucket/key`` without query strings or credentials.

    Args:
        uri: Retrieve location URI.

    Returns:
        Canonical bucket/key form, or an empty string when the URI is unusable.
    """
    bucket, key = _s3_uri_parts(uri)
    if bucket and key:
        return f"s3://{bucket}/{key}"
    return canonical_object_key(uri)


def sanitized_hit_s3_uri(item: Mapping[str, Any]) -> str:
    """Return the secret-safe S3 URI for one Retrieve hit.

    Args:
        item: One ``retrievalResults`` element.

    Returns:
        Canonical ``s3://bucket/key`` or an empty string.
    """
    return sanitized_s3_uri(_location_uri(item))


def _normalize_key(value: str) -> str:
    """Return a comparable object-key form without a leading slash."""
    cleaned = unquote(str(value or "").strip().replace("\\", "/")).lstrip("/")
    return "/".join(part for part in cleaned.split("/") if part)


def canonical_object_key(value: str) -> str:
    """Return the canonical S3 object key after URI extraction and slash normalize.

    Exact key equality is required. Suffix matching is intentionally absent so
    ``course/readings/week1.pdf`` cannot match ``archive/week1.pdf`` or
    ``myweek1.pdf``.
    """
    cleaned = str(value or "").strip()
    lowered = cleaned.lower()
    if lowered.startswith(("s3://", "http://", "https://")):
        _bucket, key = _s3_uri_parts(cleaned)
        return key
    return _normalize_key(cleaned)


def _https_s3_parts(parsed: ParseResult) -> tuple[str, str]:
    """Split a virtual-hosted or path-style HTTPS S3 URL into bucket and key.

    Args:
        parsed: ``urlparse`` result for an ``http(s)`` URI.

    Returns:
        ``(bucket, key)`` when the host is Amazon S3; otherwise empty strings.
        Exact key matching still applies after this split.
    """
    host = (parsed.netloc or "").split("@")[-1].split(":")[0].strip().lower()
    path_key = _normalize_key(unquote(parsed.path or ""))
    if not host or not path_key:
        return "", ""
    virtual = _S3_VIRTUAL_HOST.match(host)
    if virtual:
        bucket = str(virtual.group("bucket") or "").strip()
        if bucket and bucket != "s3":
            return bucket, path_key
    if _S3_PATH_HOST.match(host):
        bucket, sep, remainder = path_key.partition("/")
        if sep and bucket and remainder:
            return bucket, remainder
    return "", ""


def _s3_uri_parts(uri: str) -> tuple[str, str]:
    """Split ``s3://bucket/key`` or an HTTPS S3 URL into ``(bucket, key)``."""
    cleaned = str(uri or "").strip()
    if not cleaned:
        return "", ""
    parsed = urlparse(cleaned)
    scheme = parsed.scheme.lower()
    if scheme == "s3":
        return str(parsed.netloc or "").strip(), _normalize_key(
            unquote(parsed.path or "")
        )
    if scheme in {"http", "https"}:
        return _https_s3_parts(parsed)
    return "", ""


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
    web_location = location.get("webLocation")
    if isinstance(web_location, Mapping):
        url = str(web_location.get("url") or "").strip()
        if url:
            return url
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
    """Return whether a Retrieve object key equals a selected canonical key."""
    candidate = canonical_object_key(result_key)
    if not candidate:
        return False
    canonical_sources = {
        canonical_object_key(source_key) for source_key in source_keys if source_key
    }
    return candidate in canonical_sources


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


def _course_material_ids(sources: tuple[RetrievalSource, ...]) -> list[str]:
    """Return unique selected course_material_id values for a KB metadata filter."""
    ordered: list[str] = []
    seen: set[str] = set()
    for source in sources:
        value = str(source.course_material_id or "").strip()
        if not value:
            value = course_material_id_from_object_key(str(source.object_key or ""))
        if value and value not in seen:
            seen.add(value)
            ordered.append(value)
    return ordered


def _retrieval_results(response: Any) -> list[Any]:
    """Return the Retrieve ``retrievalResults`` list, or an empty list."""
    if not isinstance(response, Mapping):
        return []
    raw = response.get("retrievalResults")
    return list(raw) if isinstance(raw, list) else []


def _search_configuration(
    *,
    number_of_results: int,
    material_ids: list[str] | tuple[str, ...] = (),
) -> dict[str, Any]:
    """Build Retrieve search configuration, optionally metadata-filtered."""
    config: dict[str, Any] = {"numberOfResults": number_of_results}
    cleaned = [str(item).strip() for item in material_ids if str(item).strip()]
    if not cleaned:
        return config
    if len(cleaned) == 1:
        config["filter"] = {
            "equals": {"key": COURSE_MATERIAL_METADATA_KEY, "value": cleaned[0]}
        }
    else:
        config["filter"] = {
            "in": {"key": COURSE_MATERIAL_METADATA_KEY, "value": cleaned}
        }
    return config


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
        strict_metadata_filter: bool | None = None,
        knowledge_base_type: str | None = None,
    ) -> None:
        """Create the adapter with an injected or lazily constructed client.

        Args:
            knowledge_base_id: Bedrock Knowledge Base id (non-secret).
            region: AWS region for the data-plane client.
            number_of_results: Retrieve ``numberOfResults``.
            max_context_chars: Prompt budget after selected-source filtering.
            course_bucket: When set, Retrieve hits from other buckets are dropped.
            client: Optional injected ``bedrock-agent-runtime`` client for tests.
            strict_metadata_filter: When true, an empty filtered Retrieve is an
                evidence gap (no unfiltered retry). Default follows settings and
                remains false until live KB metadata is verified. A MANAGED
                Knowledge Base skips its unverified optional filter while this
                setting is false and relies on exact bucket/key post-validation.
            knowledge_base_type: ``vector`` or ``managed``. MANAGED Knowledge
                Bases require ``managedSearchConfiguration``.
        """
        self._knowledge_base_id = str(knowledge_base_id or "").strip()
        self._region = str(region or "").strip() or "us-west-2"
        self._number_of_results = max(1, int(number_of_results))
        self._max_context_chars = max(1, int(max_context_chars))
        self._course_bucket = str(course_bucket or "").strip()
        self._client = client
        if knowledge_base_type is None:
            self._knowledge_base_type = str(
                getattr(settings, "normalized_knowledge_base_type", "vector")
            )
        else:
            cleaned = str(knowledge_base_type or "").strip().casefold()
            self._knowledge_base_type = (
                "managed" if cleaned == "managed" else "vector"
            )
        if strict_metadata_filter is None:
            self._strict_metadata_filter = bool(
                getattr(settings, "knowledge_base_strict_metadata_filter", False)
            )
        else:
            self._strict_metadata_filter = bool(strict_metadata_filter)

    def _runtime_client(self) -> Any:
        """Return the injected client or construct a bedrock-agent-runtime client."""
        if self._client is not None:
            return self._client
        try:
            import boto3
            from botocore.config import Config
        except ImportError:
            logger.warning(
                "course_retrieval_client_error exception=ImportError region=%s",
                self._region,
            )
            return None
        config = Config(
            # Retrieve is optional evidence gathering, not the model call. Do
            # not let SDK retries consume the UI client's 120-second timeout.
            retries={"total_max_attempts": 1, "mode": "standard"},
            read_timeout=_RETRIEVE_READ_TIMEOUT_SECONDS,
            connect_timeout=_RETRIEVE_CONNECT_TIMEOUT_SECONDS,
        )
        try:
            self._client = boto3.client(
                "bedrock-agent-runtime",
                region_name=self._region,
                config=config,
            )
        except Exception as exc:
            logger.warning(
                "course_retrieval_%s exception=%s region=%s",
                classify_retrieve_failure(exc),
                type(exc).__name__,
                self._region,
            )
            return None
        return self._client

    def _retrieval_configuration(
        self,
        material_ids: list[str] | tuple[str, ...] = (),
    ) -> dict[str, Any]:
        """Return Retrieve configuration for VECTOR or MANAGED Knowledge Bases."""
        search = _search_configuration(
            number_of_results=self._number_of_results,
            material_ids=material_ids,
        )
        if self._knowledge_base_type == "managed":
            return {"managedSearchConfiguration": search}
        return {"vectorSearchConfiguration": search}

    def _call_retrieve(
        self,
        client: Any,
        query_text: str,
        material_ids: list[str] | tuple[str, ...] = (),
    ) -> Any:
        """Invoke Retrieve once. Never RetrieveAndGenerate.

        Args:
            client: Injected or constructed ``bedrock-agent-runtime`` client.
            query_text: Expanded Retrieve query text (never logged).
            material_ids: Optional ``course_material_id`` filter values.

        Returns:
            The raw ``client.retrieve`` response.
        """
        return client.retrieve(
            knowledgeBaseId=self._knowledge_base_id,
            retrievalQuery={"text": query_text},
            retrievalConfiguration=self._retrieval_configuration(material_ids),
        )

    def _unavailable_result(
        self, category: str, error: BaseException
    ) -> RetrievalResult:
        """Log a secret-safe failure category and return an evidence gap."""
        logger.warning(
            "course_retrieval_%s exception=%s region=%s",
            category,
            type(error).__name__,
            self._region,
        )
        return RetrievalResult(
            context="",
            chunks=(),
            course_retrieval_status="unavailable",
            failure_category=category,
        )

    def retrieve(self, query: RetrievalQuery) -> RetrievalResult:
        """Return selected-source chunks from Knowledge Base Retrieve.

        Foreign S3 keys and non-course sources are dropped. AWS and SDK
        failures return an empty result so the composer can apply evidence-gap
        rules instead of inventing sources. VECTOR metadata-filter
        ``ValidationException`` retries unfiltered Retrieve when strict
        metadata mode is off. MANAGED retrieval skips its optional filter until
        strict metadata mode confirms the indexed attribute is usable. Exact
        bucket/key validation applies to every result.

        Args:
            query: Selected-source retrieval query from FastAPI.

        Returns:
            Validated Knowledge Base chunks, or an empty evidence-gap result.
        """
        if not self._knowledge_base_id:
            logger.warning(
                "course_retrieval_config_missing kb_configured=0 region=%s",
                self._region,
            )
            return RetrievalResult(
                context="",
                chunks=(),
                course_retrieval_status="unavailable",
                failure_category="config_missing",
            )
        course_sources = tuple(
            source for source in query.sources if is_course_retrieval_source(source)
        )
        if not course_sources:
            return RetrievalResult(context="", chunks=())
        client = self._runtime_client()
        if client is None:
            return RetrievalResult(
                context="",
                chunks=(),
                course_retrieval_status="unavailable",
                failure_category="client_error",
            )
        original_query = " ".join(str(query.current_message or "").split()).strip()
        query_text = expand_session_query_text(query.current_message)
        if not query_text:
            return RetrievalResult(context="", chunks=())
        material_ids = _course_material_ids(course_sources)
        # The production MANAGED KB currently rejects its course_material_id
        # filter because that optional attribute has not been verified in the
        # index. While strict mode is off, retrieve once without that filter
        # and retain the mandatory exact bucket/key validation below. Strict
        # mode opts back into the supported filter after metadata verification.
        request_material_ids = (
            ()
            if self._knowledge_base_type == "managed"
            and not self._strict_metadata_filter
            else material_ids
        )
        used_filter = bool(request_material_ids)
        fallback = False
        logger.info(
            "course_retrieval_query kb_configured=1 region=%s "
            "kb_type=%s selected_course_count=%s material_id_count=%s "
            "strict_filter=%s session_expanded=%s",
            self._region,
            self._knowledge_base_type,
            len(course_sources),
            len(material_ids),
            int(self._strict_metadata_filter),
            int(query_text != original_query),
        )
        try:
            response = self._call_retrieve(client, query_text, request_material_ids)
        except Exception as exc:
            category = classify_retrieve_failure(exc)
            if self._can_retry_unfiltered(category, request_material_ids):
                logger.warning(
                    "course_retrieval_validation_error exception=%s region=%s "
                    "retrying_unfiltered=1",
                    type(exc).__name__,
                    self._region,
                )
                fallback = True
                used_filter = False
                try:
                    response = self._call_retrieve(client, query_text, ())
                except Exception as retry_exc:
                    return self._unavailable_result(
                        classify_retrieve_failure(retry_exc), retry_exc
                    )
            else:
                return self._unavailable_result(category, exc)
        else:
            raw_hits = _retrieval_results(response)
            if (
                request_material_ids
                and not self._strict_metadata_filter
                and not raw_hits
            ):
                logger.info(
                    "Knowledge Base metadata filter returned no hits; "
                    "retrying without filter"
                )
                fallback = True
                used_filter = False
                try:
                    response = self._call_retrieve(client, query_text, ())
                except Exception as retry_exc:
                    return self._unavailable_result(
                        classify_retrieve_failure(retry_exc), retry_exc
                    )
            elif (
                request_material_ids
                and self._strict_metadata_filter
                and not raw_hits
            ):
                logger.info(
                    "Knowledge Base metadata filter returned no hits; "
                    "strict filter treats this as an evidence gap"
                )
        raw_hits = _retrieval_results(response)
        if not raw_hits:
            logger.info(
                "course_retrieval_empty raw_hits=0 validated_count=0 "
                "filter=%s fallback=%s",
                int(used_filter),
                int(fallback),
            )
            return RetrievalResult(
                context="", chunks=(), course_retrieval_status="empty"
            )
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
                    retrieval_origin="knowledge_base",
                )
            )
        logger.info(
            "course_retrieval_hit_count raw_hits=%s validated_count=%s "
            "filter=%s fallback=%s",
            len(raw_hits),
            len(chunks),
            int(used_filter),
            int(fallback),
        )
        formatted = bounded_retrieval_result(
            chunks, max_context_chars=self._max_context_chars
        )
        if not formatted.chunks:
            logger.info(
                "course_retrieval_empty raw_hits=%s validated_count=0 "
                "filter=%s fallback=%s",
                len(raw_hits),
                int(used_filter),
                int(fallback),
            )
            return RetrievalResult(
                context="",
                chunks=(),
                course_retrieval_status="empty",
            )
        logger.info("course_retrieval_status=ok")
        return RetrievalResult(
            context=formatted.context,
            chunks=formatted.chunks,
            course_retrieval_status="ok",
        )

    def _can_retry_unfiltered(
        self,
        category: str,
        material_ids: list[str] | tuple[str, ...],
    ) -> bool:
        """Return whether a failed filtered Retrieve may retry unfiltered."""
        return (
            category == "validation_error"
            and bool(material_ids)
            and not self._strict_metadata_filter
        )


def configured_context_retriever(
    *,
    client: Any | None = None,
) -> ContextRetriever:
    """Return a composite retriever that never dumps virtual course sources locally.

    Mock-mode and an empty ``KNOWLEDGE_BASE_ID`` still return
    :class:`CompositeContextRetriever` with ``knowledge_base=None`` so pytest
    never calls AWS and shared course sources become an evidence gap instead
    of placeholder chunks. Live providers with a Knowledge Base id inject
    :class:`BedrockKnowledgeBaseRetriever`.
    """
    local = LocalChunkRetriever()
    knowledge_base_id = str(getattr(settings, "knowledge_base_id", "") or "").strip()
    if (
        not knowledge_base_id
        or settings.model_provider == "mock"
        or settings.mock_openai
    ):
        return CompositeContextRetriever(
            knowledge_base=None,
            local=local,
            max_context_chars=_MAX_CONTEXT_CHARS,
        )
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
        knowledge_base_type=str(
            getattr(settings, "normalized_knowledge_base_type", "vector")
        ),
    )
    return CompositeContextRetriever(
        knowledge_base=knowledge_base,
        local=local,
        max_context_chars=_MAX_CONTEXT_CHARS,
    )
