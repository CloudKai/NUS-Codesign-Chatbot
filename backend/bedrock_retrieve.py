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
import threading
import time
from collections.abc import Mapping
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as FutureTimeoutError
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
    contextual_course_query_text,
    course_material_id_from_object_key,
    expand_session_query_text,
    is_course_retrieval_source,
)
from .settings import settings

logger = logging.getLogger(__name__)

_DEFAULT_RESULTS = 4
_MAX_CONTEXT_CHARS = 16_000
_DEFAULT_RETRIEVE_TIMEOUT_SECONDS = 10.0
_RETRIEVE_CONNECT_TIMEOUT_SECONDS = 2.0
_SLOW_RETRIEVE_WARNING_MS = 3_000
_RETRIEVE_EXECUTOR_WORKERS = 4
_FILTER_MODES = frozenset({"required", "degraded_unfiltered", "disabled"})
_retrieve_executor: ThreadPoolExecutor | None = None
_retrieve_executor_lock = threading.Lock()
_retrieve_admission: threading.BoundedSemaphore | None = None
_retrieve_max_workers = 0
_retrieve_admitted = 0
_retrieve_occupancy_lock = threading.Lock()
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


class RetrieveCapacityError(RuntimeError):
    """Raised when the shared Retrieve pool rejects a call immediately.

    ThreadPoolExecutor's work queue is unbounded. Admission uses a semaphore
    sized to ``max_workers`` so excess calls fail closed instead of queueing
    ghost Retrieves that still run after the caller has timed out.
    """


def classify_retrieve_failure(error: BaseException) -> str:
    """Return a secret-safe category for one Knowledge Base Retrieve failure.

    Args:
        error: Exception raised by the SDK, admission control, or
            ``client.retrieve``.

    Returns:
        One of ``access_denied``, ``not_found``, ``validation_error``,
        ``throttled``, ``timeout``, ``capacity_exhausted``, or
        ``client_error``.
    """
    if isinstance(error, RetrieveCapacityError):
        return "capacity_exhausted"
    name = type(error).__name__
    if name == "RetrieveCapacityError":
        return "capacity_exhausted"
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
    if "capacity" in combined:
        return "capacity_exhausted"
    return "client_error"


def _configured_retrieve_workers() -> int:
    """Return the clamped shared-pool size from settings."""
    return max(
        1,
        int(
            getattr(
                settings,
                "knowledge_base_retrieve_executor_workers",
                _RETRIEVE_EXECUTOR_WORKERS,
            )
        ),
    )


def _mark_admitted(delta: int) -> None:
    """Adjust the admitted-call counter. Never logs query text."""
    global _retrieve_admitted
    with _retrieve_occupancy_lock:
        _retrieve_admitted = max(0, _retrieve_admitted + int(delta))


def retrieve_pool_stats() -> dict[str, int]:
    """Return secret-safe occupancy counters for the shared Retrieve pool.

    Returns:
        ``max_workers``, ``admitted`` (in-flight plus occupying timed-out
        calls that still hold a slot), and ``worker_threads`` currently
        alive with the ``kb-retrieve`` prefix.
    """
    with _retrieve_executor_lock:
        max_workers = int(_retrieve_max_workers)
    with _retrieve_occupancy_lock:
        admitted = int(_retrieve_admitted)
    worker_threads = sum(
        1
        for thread in threading.enumerate()
        if str(getattr(thread, "name", "")).startswith("kb-retrieve")
    )
    return {
        "max_workers": max_workers,
        "admitted": admitted,
        "worker_threads": worker_threads,
    }


def _shared_retrieve_executor() -> ThreadPoolExecutor:
    """Return the process-wide Retrieve worker pool.

    A Python future timeout does not cancel the boto HTTP call. Workers are
    reused so abandoned Retrieve calls cannot grow unbounded threads. A
    semaphore sized to ``max_workers`` is the admission bound: further
    ``submit`` calls are refused immediately so the executor queue cannot
    grow without limit while workers are stuck.
    """
    global _retrieve_executor, _retrieve_admission, _retrieve_max_workers
    workers = _configured_retrieve_workers()
    with _retrieve_executor_lock:
        if _retrieve_executor is None:
            _retrieve_max_workers = workers
            _retrieve_admission = threading.BoundedSemaphore(workers)
            _retrieve_executor = ThreadPoolExecutor(
                max_workers=workers,
                thread_name_prefix="kb-retrieve",
            )
        return _retrieve_executor


def _admission_semaphore() -> threading.BoundedSemaphore:
    """Return the pool admission semaphore, creating the pool if needed."""
    _shared_retrieve_executor()
    with _retrieve_executor_lock:
        admission = _retrieve_admission
    if admission is None:
        raise RetrieveCapacityError("knowledge_base_retrieve_capacity_exhausted")
    return admission


def reset_shared_retrieve_executor() -> None:
    """Shut down the process-wide Retrieve pool.

    Production does not call this. Tests may reset the pool after injecting a
    hung client so abandoned workers are not reused by later cases. Shutdown
    does not cancel in-flight boto calls; those finish or hit the SDK timeout.
    In-flight workers release the semaphore instance they captured, not the
    replacement created after reset.
    """
    global _retrieve_executor, _retrieve_admission, _retrieve_max_workers
    global _retrieve_admitted
    with _retrieve_executor_lock:
        executor = _retrieve_executor
        _retrieve_executor = None
        _retrieve_admission = None
        _retrieve_max_workers = 0
    with _retrieve_occupancy_lock:
        _retrieve_admitted = 0
    if executor is not None:
        executor.shutdown(wait=False)


def _record_kb_perf(**fields: Any) -> None:
    """Copy secret-safe Knowledge Base counters onto coach_turn_perf."""
    from backend.turn_perf import current_perf

    perf = current_perf()
    if perf is None:
        return
    for key, value in fields.items():
        if value is not None:
            perf.set(key, value)


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
    """Split ``s3://bucket/key`` or an HTTPS S3 URL into ``(bucket, key)``.

    ``s3:///key`` has an empty netloc. Callers must treat a missing bucket as
    unconfirmed and drop the hit; they must not skip the bucket check.
    """
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


def _hit_drop_reason(
    item: Mapping[str, Any],
    sources: tuple[RetrievalSource, ...],
    *,
    course_bucket: str,
) -> str:
    """Return a secret-safe reason when a Retrieve hit cannot be validated.

    Args:
        item: One ``retrievalResults`` element.
        sources: Selected course sources for this turn.
        course_bucket: Configured ``COURSE_MATERIALS_BUCKET``.

    Returns:
        ``bucket_mismatch``, ``key_mismatch``, or ``empty_text``. Empty when
        the hit maps onto a selected source and has excerpt text.
    """
    uri = _location_uri(item)
    bucket, key = _s3_uri_parts(uri)
    expected_bucket = str(course_bucket or "").strip()
    actual_bucket = str(bucket or "").strip()
    if not expected_bucket or not actual_bucket or actual_bucket != expected_bucket:
        return "bucket_mismatch"
    if not key:
        return "key_mismatch"
    if not any(_keys_match(key, _source_keys(source)) for source in sources):
        return "key_mismatch"
    if not _excerpt_text(item):
        return "empty_text"
    return ""


def _match_selected_source(
    item: Mapping[str, Any],
    sources: tuple[RetrievalSource, ...],
    *,
    course_bucket: str,
) -> RetrievalSource | None:
    """Map one Retrieve hit onto a selected course source, or drop it.

    Fail closed: the hit bucket must be present and equal the configured
    course bucket. An empty configured bucket, an empty URI bucket (for
    example ``s3:///course/lectureNotes/week1.pdf``), or a mismatch drops
    the hit. Key matching still requires exact canonical equality.
    """
    uri = _location_uri(item)
    bucket, key = _s3_uri_parts(uri)
    expected_bucket = str(course_bucket or "").strip()
    actual_bucket = str(bucket or "").strip()
    if not expected_bucket or not actual_bucket:
        return None
    if actual_bucket != expected_bucket:
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
        number_of_results: int | None = None,
        max_context_chars: int = _MAX_CONTEXT_CHARS,
        course_bucket: str = "",
        client: Any | None = None,
        strict_metadata_filter: bool | None = None,
        knowledge_base_type: str | None = None,
        retrieve_timeout_seconds: float | None = None,
        metadata_filter_mode: str | None = None,
    ) -> None:
        """Create the adapter with an injected or lazily constructed client.

        Args:
            knowledge_base_id: Bedrock Knowledge Base id (non-secret).
            region: AWS region for the data-plane client.
            number_of_results: Retrieve ``numberOfResults``. Defaults to the
                Fast Chat chunk budget so MANAGED search does not fetch unused
                hits.
            max_context_chars: Prompt budget after selected-source filtering.
            course_bucket: Required to accept a hit. Empty drops every hit
                because the bucket cannot be positively confirmed.
            client: Optional injected ``bedrock-agent-runtime`` client for tests.
            strict_metadata_filter: Deprecated alias for filter mode. True maps
                to ``required``; False maps to ``degraded_unfiltered`` when
                ``metadata_filter_mode`` is omitted. Production defaults to
                ``required`` from settings.
            knowledge_base_type: ``vector`` or ``managed``. MANAGED Knowledge
                Bases require ``managedSearchConfiguration``.
            retrieve_timeout_seconds: Wall-clock and SDK read timeout. Optional
                evidence gathering fails closed after this budget. Tests may
                pass a sub-second value; production uses settings.
            metadata_filter_mode: ``required``, ``degraded_unfiltered``, or
                ``disabled``. Default follows settings (production target
                ``required``).
        """
        self._knowledge_base_id = str(knowledge_base_id or "").strip()
        self._region = str(region or "").strip() or "us-west-2"
        if number_of_results is None:
            self._number_of_results = max(
                1,
                int(
                    getattr(
                        settings,
                        "fast_chat_retrieval_max_chunks",
                        _DEFAULT_RESULTS,
                    )
                ),
            )
        else:
            self._number_of_results = max(1, int(number_of_results))
        self._max_context_chars = max(1, int(max_context_chars))
        self._course_bucket = str(course_bucket or "").strip()
        self._client = client
        if retrieve_timeout_seconds is None:
            self._retrieve_timeout_seconds = float(
                getattr(
                    settings,
                    "knowledge_base_retrieve_timeout_seconds",
                    _DEFAULT_RETRIEVE_TIMEOUT_SECONDS,
                )
            )
        else:
            self._retrieve_timeout_seconds = max(0.05, float(retrieve_timeout_seconds))
        if metadata_filter_mode is not None:
            cleaned_mode = str(metadata_filter_mode or "").strip().casefold()
            self._metadata_filter_mode = (
                cleaned_mode if cleaned_mode in _FILTER_MODES else "required"
            )
        elif strict_metadata_filter is not None:
            self._metadata_filter_mode = (
                "required" if strict_metadata_filter else "degraded_unfiltered"
            )
        else:
            self._metadata_filter_mode = str(
                getattr(
                    settings,
                    "normalized_knowledge_base_metadata_filter_mode",
                    "required",
                )
            )
            if self._metadata_filter_mode not in _FILTER_MODES:
                self._metadata_filter_mode = "required"
        self._strict_metadata_filter = self._metadata_filter_mode == "required"
        if knowledge_base_type is None:
            self._knowledge_base_type = str(
                getattr(settings, "normalized_knowledge_base_type", "vector")
            )
        else:
            cleaned = str(knowledge_base_type or "").strip().casefold()
            self._knowledge_base_type = (
                "managed" if cleaned == "managed" else "vector"
            )

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
        read_timeout = self._retrieve_timeout_seconds
        connect_timeout = min(_RETRIEVE_CONNECT_TIMEOUT_SECONDS, read_timeout)
        config = Config(
            # Retrieve is optional evidence gathering, not the model call. Do
            # not let SDK retries consume the UI client's 120-second timeout.
            retries={"total_max_attempts": 1, "mode": "standard"},
            read_timeout=read_timeout,
            connect_timeout=connect_timeout,
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

        Raises:
            TimeoutError: When the wall-clock budget expires. Botocore
                ``read_timeout`` is a per-read idle timeout and is not a
                reliable total-request cap on a slow MANAGED Retrieve.
            RetrieveCapacityError: When every shared worker is already
                occupied. The caller is not queued.
        """
        timeout = self._retrieve_timeout_seconds
        admission = _admission_semaphore()
        if not admission.acquire(blocking=False):
            raise RetrieveCapacityError("knowledge_base_retrieve_capacity_exhausted")
        _mark_admitted(1)
        released = False

        def _release_slot() -> None:
            nonlocal released
            if released:
                return
            released = True
            admission.release()
            _mark_admitted(-1)

        def _invoke() -> Any:
            try:
                return client.retrieve(
                    knowledgeBaseId=self._knowledge_base_id,
                    retrievalQuery={"text": query_text},
                    retrievalConfiguration=self._retrieval_configuration(
                        material_ids
                    ),
                )
            finally:
                _release_slot()

        # A future timeout does not cancel boto. Admission equals worker
        # count so abandoned calls occupy a slot until the SDK returns
        # instead of queueing unbounded ghost Retrieves.
        executor = _shared_retrieve_executor()
        try:
            future = executor.submit(_invoke)
        except Exception:
            _release_slot()
            raise
        sdk_started = time.perf_counter()
        try:
            response = future.result(timeout=timeout)
        except FutureTimeoutError as exc:
            _record_kb_perf(
                kb_sdk_ms=round(max(0.0, (time.perf_counter() - sdk_started) * 1000.0), 1)
            )
            raise TimeoutError("knowledge_base_retrieve_timeout") from exc
        _record_kb_perf(
            kb_sdk_ms=round(max(0.0, (time.perf_counter() - sdk_started) * 1000.0), 1)
        )
        return response

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

    def _log_retrieve_elapsed(
        self, started: float, result: RetrievalResult
    ) -> None:
        """Log secret-safe Retrieve duration. Slow or failed calls use WARNING.

        Args:
            started: ``time.perf_counter()`` mark from ``retrieve``.
            result: Adapter result after filtering. Query text is never logged.
        """
        elapsed_ms = int((time.perf_counter() - started) * 1000)
        status = str(result.course_retrieval_status or "ok")
        category = str(result.failure_category or "-")
        payload = (
            "course_retrieval_elapsed_ms=%s status=%s category=%s "
            "timeout_s=%s kb_type=%s"
            % (
                elapsed_ms,
                status,
                category,
                self._retrieve_timeout_seconds,
                self._knowledge_base_type,
            )
        )
        if elapsed_ms >= _SLOW_RETRIEVE_WARNING_MS or status == "unavailable":
            logger.warning(payload)
            return
        logger.info(payload)

    def retrieve(self, query: RetrievalQuery) -> RetrievalResult:
        """Return selected-source chunks from Knowledge Base Retrieve.

        Foreign S3 keys and non-course sources are dropped. AWS and SDK
        failures return an empty result so the composer can apply evidence-gap
        rules instead of inventing sources.         VECTOR metadata-filter ``ValidationException`` is an evidence gap in
        ``required`` mode. Exact bucket/key validation applies to every
        result. A wall-clock timeout fails closed as ``unavailable`` /
        ``timeout``. Pool admission rejection fails closed as
        ``unavailable`` / ``capacity_exhausted``. ``degraded_unfiltered``
        skips the metadata filter on purpose. ``disabled`` does not call
        Retrieve.

        Args:
            query: Selected-source retrieval query from FastAPI.

        Returns:
            Validated Knowledge Base chunks, or an empty evidence-gap result.
        """
        started = time.perf_counter()
        result = self._retrieve_once(query)
        self._log_retrieve_elapsed(started, result)
        return result

    def _retrieve_once(self, query: RetrievalQuery) -> RetrievalResult:
        """Run one Retrieve attempt. Never retry unfiltered after a failure.

        Args:
            query: Selected-source retrieval query from FastAPI.

        Returns:
            Validated chunks or an evidence-gap result. Does not log query text.
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
        contextual_query = contextual_course_query_text(
            query,
            max_chars=int(settings.fast_chat_project_context_chars),
        )
        query_text = expand_session_query_text(contextual_query)
        if contextual_query != original_query:
            query_text = query_text[: int(settings.fast_chat_project_context_chars)].rstrip()
        if not query_text:
            return RetrievalResult(context="", chunks=())
        material_ids = _course_material_ids(course_sources)
        if (
            self._metadata_filter_mode == "required"
            and course_sources
            and not material_ids
        ):
            logger.warning(
                "course_retrieval_missing_material_ids region=%s "
                "selected_course_count=%s",
                self._region,
                len(course_sources),
            )
            _record_kb_perf(
                kb_filter_mode="required",
                kb_filtered=False,
                kb_requested_material_count=0,
                kb_raw_hit_count=0,
                kb_validated_hit_count=0,
                kb_timeout=False,
                kb_failure_category="missing_material_id",
            )
            return RetrievalResult(
                context="",
                chunks=(),
                course_retrieval_status="unavailable",
                failure_category="missing_material_id",
            )
        if self._metadata_filter_mode == "disabled":
            logger.warning(
                "course_retrieval_disabled region=%s selected_course_count=%s",
                self._region,
                len(course_sources),
            )
            _record_kb_perf(
                kb_filter_mode="disabled",
                kb_filtered=False,
                kb_requested_material_count=len(material_ids),
                kb_raw_hit_count=0,
                kb_validated_hit_count=0,
                kb_timeout=False,
                kb_failure_category="disabled",
            )
            return RetrievalResult(
                context="",
                chunks=(),
                course_retrieval_status="unavailable",
                failure_category="disabled",
            )
        request_material_ids = (
            ()
            if self._metadata_filter_mode == "degraded_unfiltered"
            else material_ids
        )
        used_filter = bool(request_material_ids)
        _record_kb_perf(
            kb_filter_mode=self._metadata_filter_mode,
            kb_filtered=used_filter,
            kb_requested_material_count=len(material_ids),
        )
        logger.info(
            "course_retrieval_query kb_configured=1 region=%s "
            "kb_type=%s selected_course_count=%s material_id_count=%s "
            "filter_mode=%s filter=%s session_expanded=%s",
            self._region,
            self._knowledge_base_type,
            len(course_sources),
            len(material_ids),
            self._metadata_filter_mode,
            int(used_filter),
            int(query_text != original_query),
        )
        try:
            response = self._call_retrieve(client, query_text, request_material_ids)
        except Exception as exc:
            category = classify_retrieve_failure(exc)
            _record_kb_perf(
                kb_timeout=category == "timeout",
                kb_failure_category=category,
                kb_raw_hit_count=0,
                kb_validated_hit_count=0,
            )
            return self._unavailable_result(category, exc)
        raw_hits = _retrieval_results(response)
        if not raw_hits:
            logger.info(
                "course_retrieval_empty raw_hits=0 validated_count=0 "
                "filter=%s filter_mode=%s",
                int(used_filter),
                self._metadata_filter_mode,
            )
            _record_kb_perf(kb_raw_hit_count=0, kb_validated_hit_count=0)
            return RetrievalResult(
                context="", chunks=(), course_retrieval_status="empty"
            )
        chunks: list[RetrievedChunk] = []
        per_source: dict[str, int] = {}
        drop_bucket = 0
        drop_key = 0
        drop_empty = 0
        validate_started = time.perf_counter()
        for item in raw_hits:
            if not isinstance(item, Mapping):
                continue
            source = _match_selected_source(
                item,
                course_sources,
                course_bucket=self._course_bucket,
            )
            if source is None:
                reason = _hit_drop_reason(
                    item,
                    course_sources,
                    course_bucket=self._course_bucket,
                )
                if reason == "bucket_mismatch":
                    drop_bucket += 1
                elif reason == "empty_text":
                    drop_empty += 1
                else:
                    drop_key += 1
                continue
            text = _excerpt_text(item)
            if not text:
                drop_empty += 1
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
        _record_kb_perf(
            kb_validate_ms=round(
                max(0.0, (time.perf_counter() - validate_started) * 1000.0), 1
            ),
            kb_raw_hit_count=len(raw_hits),
            kb_validated_hit_count=len(chunks),
            kb_drop_bucket_mismatch=drop_bucket,
            kb_drop_key_mismatch=drop_key,
            kb_drop_empty_text=drop_empty,
        )
        logger.info(
            "course_retrieval_hit_count raw_hits=%s validated_count=%s "
            "filter=%s filter_mode=%s drop_bucket=%s drop_key=%s drop_empty=%s",
            len(raw_hits),
            len(chunks),
            int(used_filter),
            self._metadata_filter_mode,
            drop_bucket,
            drop_key,
            drop_empty,
        )
        if settings.co_design_rag_debug:
            titles = [str(source.title or "")[:80] for source in course_sources[:8]]
            scores = [
                round(_result_score(item), 4)
                for item in raw_hits[:8]
                if isinstance(item, Mapping)
            ]
            logger.info(
                "rag_debug query_chars=%s selected_count=%s titles=%s "
                "top_scores=%s raw=%s validated=%s",
                len(query_text),
                len(course_sources),
                titles,
                scores,
                len(raw_hits),
                len(chunks),
            )
        formatted = bounded_retrieval_result(
            chunks, max_context_chars=self._max_context_chars
        )
        if not formatted.chunks:
            logger.info(
                "course_retrieval_empty raw_hits=%s validated_count=0 "
                "filter=%s filter_mode=%s",
                len(raw_hits),
                int(used_filter),
                self._metadata_filter_mode,
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
        number_of_results=int(
            getattr(settings, "fast_chat_retrieval_max_chunks", _DEFAULT_RESULTS)
        ),
        retrieve_timeout_seconds=float(
            getattr(
                settings,
                "knowledge_base_retrieve_timeout_seconds",
                _DEFAULT_RETRIEVE_TIMEOUT_SECONDS,
            )
        ),
    )
    return CompositeContextRetriever(
        knowledge_base=knowledge_base,
        local=local,
        max_context_chars=_MAX_CONTEXT_CHARS,
    )
