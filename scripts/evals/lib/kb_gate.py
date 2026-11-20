"""Live Knowledge Base gate run: one Retrieve per gate message through the production adapter.

Importing this module starts no call and loads no AWS library. The functions
here take an already built client, so the command (``evaluate_retrieval
--live-kb-gate``) stays the only owner of the real client. The Retrieve call,
the course-material filter, the candidate count and the hit validation all
come from ``backend.bedrock_retrieve.BedrockKnowledgeBaseRetriever``; nothing
is re-implemented here. A record holds ids, scores, counts and timings only,
never message or history text.
"""

from __future__ import annotations

import time
from collections import Counter
from collections.abc import Mapping, Sequence
from typing import Any

from scripts.evals.lib.live import (
    LiveCallLimitExceeded,
    exception_label,
    is_auth_or_access_error,
)
from scripts.evals.lib.metrics import evenly_spaced_indices, p95_ms

# One Retrieve per gate message, and the gate set has 295 messages.
LIVE_KB_GATE_CAP = 295

# Retrieve statuses that mean the Knowledge Base answered (with or without hits).
_ANSWERED = frozenset({"ok", "empty"})


class RecordingRetrieveClient:
    """Wrap a ``bedrock-agent-runtime`` client: count calls, enforce a cap, remember errors.

    The production adapter swallows every exception and reports only a
    ``failure_category``; ``NoCredentialsError`` for example maps to
    ``client_error``, not ``access_denied``. This wrapper keeps the raised
    exception per call so the run can stop on an auth or access error.
    """

    def __init__(self, client: Any, limit: int) -> None:
        self._client = client
        self._limit = limit
        self.calls = 0
        self.errors: dict[int, BaseException] = {}
        self.raw_hit_counts: dict[int, int] = {}

    def retrieve(self, **kwargs: Any) -> Any:
        if self.calls >= self._limit:
            raise LiveCallLimitExceeded(f"call limit {self._limit} reached")
        self.calls += 1
        number = self.calls
        try:
            response = self._client.retrieve(**kwargs)
        except BaseException as error:
            self.errors[number] = error
            raise
        results = response.get("retrievalResults") if isinstance(response, Mapping) else None
        self.raw_hit_counts[number] = len(results) if isinstance(results, list) else 0
        return response


def course_sources(materials: Sequence[Mapping[str, Any]]) -> tuple[Any, ...]:
    """Return the course catalogue as retrieval sources, as ``run_live`` builds it."""
    from backend.retrieval import RetrievalSource

    return tuple(
        RetrievalSource(
            source_id=entry["source_id"],
            label=f"S{index}",
            title=entry["filename"],
            text="",
            mime="application/pdf",
            group=entry["group"],
            object_key=entry["object_key"],
            course_material_id=entry["material_id"],
            virtual_course_source=True,
        )
        for index, entry in enumerate(materials, start=1)
    )


def kb_region() -> str:
    """Return the Knowledge Base region the way ``configured_context_retriever`` picks it."""
    from backend.settings import settings

    return (
        str(getattr(settings, "knowledge_base_region", "") or "").strip()
        or str(settings.aws_region or "").strip()
        or "us-west-2"
    )


def build_retriever(client: Any) -> Any:
    """Build the production Knowledge Base adapter with production settings.

    The arguments are those of ``configured_context_retriever``. The filter
    mode and page-citation switch are left to the adapter, so they follow
    settings exactly as in production.
    """
    from backend.bedrock_retrieve import (
        _DEFAULT_CANDIDATES,
        _DEFAULT_RESULTS,
        _DEFAULT_RETRIEVE_TIMEOUT_SECONDS,
        BedrockKnowledgeBaseRetriever,
    )
    from backend.settings import settings

    return BedrockKnowledgeBaseRetriever(
        str(settings.knowledge_base_id),
        region=kb_region(),
        course_bucket=str(settings.course_materials_bucket or "").strip(),
        client=client,
        knowledge_base_type=str(getattr(settings, "normalized_knowledge_base_type", "vector")),
        number_of_results=int(
            getattr(settings, "knowledge_base_retrieve_candidates", _DEFAULT_CANDIDATES)
        ),
        max_results=int(getattr(settings, "fast_chat_retrieval_max_chunks", _DEFAULT_RESULTS)),
        retrieve_timeout_seconds=float(
            getattr(
                settings,
                "knowledge_base_retrieve_timeout_seconds",
                _DEFAULT_RETRIEVE_TIMEOUT_SECONDS,
            )
        ),
    )


def kb_settings_record() -> dict[str, Any]:
    """Return the Knowledge Base settings a run used. No id, bucket or account."""
    from backend.settings import settings

    max_results = max(1, int(settings.fast_chat_retrieval_max_chunks))
    return {
        "candidates": max(1, int(settings.knowledge_base_retrieve_candidates), max_results),
        "max_results": max_results,
        "filter_mode": str(settings.normalized_knowledge_base_metadata_filter_mode),
        "knowledge_base_type": str(settings.normalized_knowledge_base_type),
        "timeout_seconds": float(settings.knowledge_base_retrieve_timeout_seconds),
        "region": kb_region(),
    }


def query_for_row(row: Mapping[str, Any], sources: Sequence[Any]) -> Any:
    """Build the ``RetrievalQuery`` production would send for one gate message.

    Sources are narrowed by ``prefer_session_matching_sources``, which the
    composite retriever applies before the adapter; the history becomes
    ``recent_messages``, as in ``captured_kb_query``.
    """
    from backend.retrieval import RetrievalQuery, prefer_session_matching_sources

    message = str(row["message"])
    return RetrievalQuery(
        current_message=message,
        current_stage=str(row["stage"]),
        sources=prefer_session_matching_sources(tuple(sources), message),
        recent_messages=tuple(
            {"role": turn["role"], "content": turn["text"]} for turn in row["history"]
        ),
    )


def _row_record(
    row: Mapping[str, Any],
    result: Any,
    elapsed_ms: float,
    client: RecordingRetrieveClient,
    before: int,
) -> tuple[dict[str, Any], BaseException | None]:
    """Return the JSON record for one row and the exception its call raised (if any)."""
    number = before + 1 if client.calls > before else None
    error = client.errors.get(number) if number is not None else None
    scores = [float(chunk.score) for chunk in result.chunks]
    record = {
        "id": str(row["id"]),
        "category": str(row["category"]),
        "top_score": max(scores) if scores else None,
        "result_count": len(scores),
        "status": str(result.course_retrieval_status or "ok"),
        "failure_category": str(result.failure_category or "") or None,
        "elapsed_ms": round(elapsed_ms, 1),
        "raw_hit_count": client.raw_hit_counts.get(number) if number is not None else None,
        "exception_class": type(error).__name__ if error is not None else None,
    }
    return record, error


def _percentile(values: list[float], percent: int) -> float | None:
    """Nearest-rank percentile rounded to one place, or ``None`` when empty."""
    if not values:
        return None
    ordered = sorted(values)
    return round(ordered[max(0, (percent * len(ordered) + 99) // 100 - 1)], 1)


def summarize_rows(rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """Count statuses and failure categories and give the latency percentiles."""
    answered = [float(row["elapsed_ms"]) for row in rows if row["status"] in _ANSWERED]
    every = [float(row["elapsed_ms"]) for row in rows]
    return {
        "rows_recorded": len(rows),
        "status_counts": dict(sorted(Counter(str(row["status"]) for row in rows).items())),
        "failure_categories": dict(
            sorted(Counter(str(row["failure_category"]) for row in rows if row["failure_category"]).items())
        ),
        "rows_with_validated_hit": sum(1 for row in rows if row["result_count"] > 0),
        "elapsed_ms_answered": {
            "n": len(answered),
            "p50": _percentile(answered, 50),
            "p95": p95_ms(answered),
        },
        "elapsed_ms_all_attempts": {
            "n": len(every),
            "p50": _percentile(every, 50),
            "p95": p95_ms(every),
        },
    }


def run_gate_calls(
    rows: Sequence[Mapping[str, Any]],
    *,
    retriever: Any,
    client: RecordingRetrieveClient,
    sources: Sequence[Any],
    limit: int,
) -> dict[str, Any]:
    """Send one Retrieve per row (at most ``limit``) and record the outcome.

    Rows are taken in file order, or evenly spaced when ``limit`` is below the
    row count. The run stops after the first auth or access error. Returns
    ``rows``, ``summary``, ``stopped_on_auth_error`` and ``first_auth_error``
    (row id and exception label), plus ``rows_requested``. No message text is
    stored or printed.
    """
    chosen = [rows[index] for index in evenly_spaced_indices(len(rows), limit)]
    records: list[dict[str, Any]] = []
    stopped: dict[str, str] | None = None
    for row in chosen:
        before = client.calls
        started = time.perf_counter()
        result = retriever.retrieve(query_for_row(row, sources))
        elapsed_ms = (time.perf_counter() - started) * 1000.0
        record, error = _row_record(row, result, elapsed_ms, client, before)
        records.append(record)
        if error is not None and is_auth_or_access_error(error):
            stopped = {"id": record["id"], "exception": exception_label(error)}
            break
    summary = summarize_rows(records)
    summary["rows_requested"] = len(chosen)
    summary["stopped_on_auth_error"] = stopped is not None
    return {
        "rows": records,
        "summary": summary,
        "first_auth_error": stopped,
    }


def kb_gate_exit_code(result: Mapping[str, Any]) -> int:
    """Return 3 after an auth stop, 1 when no call was answered, else 0."""
    if result["first_auth_error"] is not None:
        return 3
    if not any(row["status"] in _ANSWERED for row in result["rows"]):
        return 1
    return 0
