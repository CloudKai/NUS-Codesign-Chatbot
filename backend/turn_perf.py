"""Privacy-safe per-request latency and context instrumentation.

This module records numeric timings and bounded counts for one coaching turn.
It never stores student text, prompts, retrieved excerpts, notebook identifiers,
auth tokens, cookies, or AWS credentials. Callers must only pass approved
field names from :data:`SAFE_PERF_FIELDS`. Emit writes JSON ``coach_turn_perf``
and grep-friendly ``TIMING`` lines in seconds.
"""

from __future__ import annotations

import hashlib
import logging
import time
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field
from typing import Any, Iterator, Mapping

from backend.operational_metrics import record_coach_turn_perf


logger = logging.getLogger("co_design.turn_perf")

SAFE_PERF_FIELDS = frozenset(
    {
        "request_total_ms",
        "request_id",
        "auth_context_ms",
        "submit_notebook_lookup_ms",
        "history_source_join_ms",
        "ui_stream_ms",
        "notebook_load_ms",
        "history_load_ms",
        "source_load_ms",
        "memory_load_ms",
        "student_state_ms",
        "context_build_ms",
        "agent_ms",
        "persistence_ms",
        "retrieval_gate_ms",
        "retrieval_required",
        "course_kb_retrieval_ms",
        "student_source_retrieval_ms",
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
        "retrieval_total_ms",
        "retrieved_chunk_count",
        "retrieved_context_chars",
        "context_planner_ms",
        "prompt_compose_ms",
        "estimated_input_tokens",
        "history_tokens",
        "evidence_tokens",
        "prompt_tokens",
        "original_message_count",
        "verbatim_message_count",
        "compressed_message_count",
        "compression_used",
        "input_over_soft_budget",
        "agentcore_invoke_ms",
        "agentcore_configured_timeout_seconds",
        "model_role",
        "model_id",
        "mode_returned",
        "mode_policy_intent",
        "mode_policy_enforced",
        "hmw_scaffold_ready_model",
        "hmw_scaffold_available",
        "idempotency_claim_ms",
        "persist_turn_ms",
        "idempotency_complete_ms",
        "db_total_ms",
        "success",
        "failure_category",
        "stage",
        "rag_used",
        "guardrail_configured",
        "context_policy",
        "fast_chat_needs_source_retrieval",
        "fast_chat_recent_message_count",
        "estimated_recent_history_tokens",
        "recent_history_budget_tokens",
        "largest_historical_message_tokens",
        "historical_messages_trimmed",
        "historical_message_tokens_trimmed",
        "estimated_memory_tokens",
        "estimated_rag_tokens",
        "estimated_current_message_tokens",
        "estimated_system_prompt_tokens",
        "estimated_dynamic_input_tokens",
        "estimated_total_model_input_tokens",
        "fast_chat_soft_input_tokens",
        "fast_chat_hard_input_tokens",
        "agentcore_call_count",
        "agentcore_structured_output_retry_attempted",
        "agentcore_structured_output_retry_skipped_budget",
        "agentcore_structured_output_retry_succeeded",
        "rag_fallback_used",
        "rag_fallback_model_calls",
        "rag_fallback_skipped_budget",
        "rag_fallback_retrieval_ms",
        "deep_review_invoked",
        "deep_review_model_role",
        "prompt_cache_enabled",
        "prompt_cache_hit",
        "cache_write_input_tokens",
        "cache_read_input_tokens",
        "kb_filter_mode",
        "kb_filtered",
        "kb_requested_material_count",
        "kb_raw_hit_count",
        "kb_validated_hit_count",
        "kb_timeout",
        "kb_failure_category",
        "kb_sdk_ms",
        "kb_validate_ms",
        "kb_drop_bucket_mismatch",
        "kb_drop_key_mismatch",
        "kb_drop_empty_text",
        "kb_session_narrowed",
        "kb_session_narrowed_count",
        "hydrate_total_ms",
        "qa_evidence_gap_authored",
        "course_catalog_retrieval",
        "course_catalog_source_count",
        "event_loop_cycle_count",
        "structured_output_recovery_used",
        "structured_output_failure_category",
        "first_cycle_stop_reason",
        "first_cycle_tool_choice_installed",
        "first_cycle_tool_choice_applied",
        "first_cycle_tool_choice_decision",
        "runtime_model_role",
        "runtime_model_provider",
        "runtime_model_id",
        "runtime_model_region",
        "runtime_strands_agents",
        "model_input_tokens",
        "model_output_tokens",
        "model_call_count",
        "agentcore_ttft_ms",
        "agentcore_model_duration_ms",
        "notebook_load_count",
        "source_catalog_load_count",
        "citation_source_resolution_count",
        "retrieval_count",
        "deep_review_context_mode",
        "deep_review_full_estimated_tokens",
        "deep_review_actual_context_estimated_tokens",
        "deep_review_checkpoint_revision",
        "deep_review_checkpoint_valid",
        "deep_review_checkpoint_fallback_reason",
        "deep_review_anchor_count",
        "deep_review_delta_message_count",
        "deep_review_reviewed_message_count",
        "deep_review_estimated_tokens_saved",
        "deep_review_estimated_savings_ratio",
    }
)

_FORBIDDEN_KEYS = frozenset(
    {
        "student_message",
        "prompt",
        "excerpt",
        "source_text",
        "cookie",
        "authorization",
        "id_token",
        "refresh_token",
        "access_token",
        "dsql_token",
        "aws_secret",
        "aws_access",
        "password",
        "thread_id",
        "notebook_id",
    }
)
_CONTENT_HINTS = (
    "student_message",
    "bearer ",
    "cookie=",
    "authorization:",
)


_current: ContextVar["CoachTurnPerf | None"] = ContextVar(
    "coach_turn_perf", default=None
)


def _is_unsafe_key(name: str) -> bool:
    """Return whether a metric key is a forbidden content or secret name."""
    cleaned = str(name or "").strip().lower()
    if not cleaned:
        return True
    return cleaned in _FORBIDDEN_KEYS


def elapsed_ms(started: float) -> float:
    """Return milliseconds since a monotonic start marker."""
    return round(max(0.0, (time.perf_counter() - started) * 1000.0), 1)


def opaque_request_id(value: str | None) -> str:
    """Return a short non-reversible correlation id, or empty when unused."""
    cleaned = str(value or "").strip()
    if not cleaned:
        return ""
    digest = hashlib.sha256(cleaned.encode("utf-8")).hexdigest()
    return digest[:12]


@dataclass
class CoachTurnPerf:
    """Mutable timing accumulator for one coaching request."""

    started: float = field(default_factory=time.perf_counter)
    emitted: bool = False
    success: bool = False
    failure_category: str = ""
    fields: dict[str, Any] = field(default_factory=dict)

    def set(self, name: str, value: Any) -> None:
        """Record one approved numeric or categorical field."""
        key = str(name or "").strip()
        if key not in SAFE_PERF_FIELDS or _is_unsafe_key(key):
            logger.warning("turn_perf_rejected_field")
            return
        if isinstance(value, str):
            text = " ".join(value.split())[:80]
            if any(hint in text.lower() for hint in _CONTENT_HINTS):
                logger.warning("turn_perf_rejected_value")
                return
            self.fields[key] = text
            return
        if isinstance(value, bool):
            self.fields[key] = value
            return
        if isinstance(value, (int, float)):
            self.fields[key] = value
            return
        logger.warning("turn_perf_rejected_type")

    def add_ms(self, name: str, duration_ms: float) -> None:
        """Add milliseconds onto an existing timing field."""
        current = self.fields.get(name, 0.0)
        try:
            total = float(current) + float(duration_ms)
        except (TypeError, ValueError):
            total = float(duration_ms)
        self.set(name, round(max(0.0, total), 1))

    def snapshot(self) -> dict[str, Any]:
        """Return the safe fields plus total request duration."""
        payload = dict(self.fields)
        payload["request_total_ms"] = elapsed_ms(self.started)
        payload["success"] = bool(self.success)
        if self.failure_category:
            payload["failure_category"] = str(self.failure_category)[:64]
        elif not self.success:
            payload.setdefault("failure_category", "unavailable")
        else:
            payload.setdefault("failure_category", "ok")
        db_parts = (
            float(payload.get("notebook_load_ms") or 0.0),
            float(payload.get("history_load_ms") or 0.0),
            float(payload.get("source_load_ms") or 0.0),
            float(payload.get("idempotency_claim_ms") or 0.0),
            float(payload.get("persist_turn_ms") or 0.0),
            float(payload.get("idempotency_complete_ms") or 0.0),
        )
        payload["db_total_ms"] = round(sum(db_parts), 1)
        payload["student_state_ms"] = round(
            float(payload.get("notebook_load_ms") or 0.0)
            + float(payload.get("history_load_ms") or 0.0)
            + float(payload.get("source_load_ms") or 0.0),
            1,
        )
        payload["context_build_ms"] = round(
            float(payload.get("prompt_compose_ms") or 0.0)
            + float(payload.get("context_planner_ms") or 0.0),
            1,
        )
        payload["persistence_ms"] = round(
            float(payload.get("persist_turn_ms") or 0.0)
            + float(payload.get("idempotency_complete_ms") or 0.0),
            1,
        )
        if "agent_ms" not in payload and payload.get("agentcore_invoke_ms") is not None:
            payload["agent_ms"] = payload["agentcore_invoke_ms"]
        return {key: value for key, value in payload.items() if key in SAFE_PERF_FIELDS}


def current_perf() -> CoachTurnPerf | None:
    """Return the request-local timing accumulator, if any."""
    return _current.get()


def begin_coach_turn_perf() -> CoachTurnPerf:
    """Start a request-local timing accumulator, replacing any leftover value."""
    perf = CoachTurnPerf()
    _current.set(perf)
    return perf


def bind_coach_turn_perf(perf: CoachTurnPerf) -> None:
    """Attach an existing accumulator to this task/thread."""
    _current.set(perf)


def reset_coach_turn_perf() -> None:
    """Clear the request-local accumulator after emit or failure handling."""
    _current.set(None)


@contextmanager
def record_span(name: str) -> Iterator[None]:
    """Time a block and store milliseconds on the current accumulator."""
    perf = current_perf()
    started = time.perf_counter()
    try:
        yield
    finally:
        if perf is not None:
            perf.set(name, elapsed_ms(started))


def record_field(name: str, value: Any) -> None:
    """Set one field on the current accumulator when present."""
    perf = current_perf()
    if perf is not None:
        perf.set(name, value)


def record_count(name: str, delta: int = 1) -> None:
    """Add *delta* onto an existing integer count field.

    Args:
        name: Allowlisted count field.
        delta: Amount to add. Negative values are ignored.

    Returns:
        None. No-op when no request accumulator is bound.
    """
    perf = current_perf()
    if perf is None:
        return
    amount = int(delta)
    if amount <= 0:
        return
    current = perf.fields.get(name, 0)
    try:
        total = int(current) + amount
    except (TypeError, ValueError):
        total = amount
    perf.set(name, total)


def record_student_source_chunk_cache_counters(
    *,
    hits: int = 0,
    misses: int = 0,
    evictions: int = 0,
) -> None:
    """Add per-turn student-source chunk-cache counters.

    Args:
        hits: Cache hits observed during this turn.
        misses: Cache misses observed during this turn.
        evictions: LRU evictions observed during this turn.

    Returns:
        None. No-op when no request accumulator is bound. Non-positive
        deltas are ignored by :func:`record_count`.
    """
    record_count("student_source_chunk_cache_hit", hits)
    record_count("student_source_chunk_cache_miss", misses)
    record_count("student_source_chunk_cache_eviction", evictions)


def record_failure(category: str) -> None:
    """Stamp a category-only failure on the current accumulator."""
    perf = current_perf()
    if perf is None:
        return
    perf.success = False
    perf.failure_category = str(category or "unavailable")[:64]


def record_success() -> None:
    """Mark the current accumulator as a successful turn."""
    perf = current_perf()
    if perf is None:
        return
    perf.success = True
    if not perf.failure_category:
        perf.failure_category = "ok"


def emit_coach_turn_perf(perf: CoachTurnPerf | None = None) -> dict[str, Any]:
    """Write ``coach_turn_perf`` once and detach the accumulator.

    Args:
        perf: Optional accumulator. Defaults to the request-local value.

    Returns:
        The emitted safe field mapping. Empty when nothing was recorded.
    """
    target = perf if perf is not None else current_perf()
    if target is None or target.emitted:
        return {}
    payload = target.snapshot()
    target.emitted = True
    record_coach_turn_perf(payload)
    _log_service_timings(payload)
    reset_coach_turn_perf()
    return payload


def _ms_to_seconds(value: Any) -> float:
    """Convert a millisecond timing field to non-negative seconds."""
    try:
        return max(0.0, float(value or 0.0) / 1000.0)
    except (TypeError, ValueError):
        return 0.0


def _log_service_timings(payload: Mapping[str, Any]) -> None:
    """Write grep-friendly service-latency lines with no student content.

    Seconds match operator timing snippets. Milliseconds remain on the JSON
    ``coach_turn_perf`` event. Values are numeric only. ``request_id`` is the
    FastAPI ``X-Request-ID`` (UUID), never a notebook or student identifier.
    """
    request_id = str(payload.get("request_id") or "-").strip() or "-"
    spans = (
        ("auth", payload.get("auth_context_ms")),
        ("submit_notebook", payload.get("submit_notebook_lookup_ms")),
        ("student_state", payload.get("student_state_ms")),
        ("notebook_load", payload.get("notebook_load_ms")),
        ("history_load", payload.get("history_load_ms")),
        ("source_load", payload.get("source_load_ms")),
        ("history_source_join", payload.get("history_source_join_ms")),
        ("memory", payload.get("memory_load_ms")),
        ("retrieval", payload.get("retrieval_total_ms")),
        ("kb_sdk", payload.get("kb_sdk_ms")),
        ("kb_validate", payload.get("kb_validate_ms")),
        ("context_build", payload.get("context_build_ms")),
        ("agent", payload.get("agent_ms") or payload.get("agentcore_invoke_ms")),
        ("persistence", payload.get("persistence_ms")),
        ("TOTAL", payload.get("request_total_ms")),
    )
    for name, raw_ms in spans:
        logger.info(
            "TIMING %s %.3fs request_id=%s",
            name,
            _ms_to_seconds(raw_ms),
            request_id,
        )
    logger.info(
        "TIMING_MS request_id=%s auth_ms=%.1f submit_notebook_ms=%.1f "
        "notebook_load_ms=%.1f history_load_ms=%.1f source_load_ms=%.1f "
        "history_source_join_ms=%.1f memory_ms=%.1f retrieval_gate_ms=%.1f "
        "retrieval_ms=%.1f kb_sdk_ms=%.1f kb_validate_ms=%.1f "
        "context_build_ms=%.1f agentcore_ms=%.1f persistence_ms=%.1f "
        "notebook_load_count=%s agentcore_call_count=%s "
        "event_loop_cycle_count=%s structured_output_recovery_used=%s "
        "first_cycle_stop_reason=%s first_cycle_tool_choice_installed=%s "
        "first_cycle_tool_choice_applied=%s first_cycle_tool_choice_decision=%s "
        "total_backend_ms=%.1f total_server_ms=%.1f",
        request_id,
        float(payload.get("auth_context_ms") or 0.0),
        float(payload.get("submit_notebook_lookup_ms") or 0.0),
        float(payload.get("notebook_load_ms") or 0.0),
        float(payload.get("history_load_ms") or 0.0),
        float(payload.get("source_load_ms") or 0.0),
        float(payload.get("history_source_join_ms") or 0.0),
        float(payload.get("memory_load_ms") or 0.0),
        float(payload.get("retrieval_gate_ms") or 0.0),
        float(payload.get("retrieval_total_ms") or 0.0),
        float(payload.get("kb_sdk_ms") or 0.0),
        float(payload.get("kb_validate_ms") or 0.0),
        float(payload.get("context_build_ms") or 0.0),
        float(payload.get("agent_ms") or payload.get("agentcore_invoke_ms") or 0.0),
        float(payload.get("persistence_ms") or 0.0),
        payload.get("notebook_load_count", "-"),
        payload.get("agentcore_call_count", "-"),
        payload.get("event_loop_cycle_count", "-"),
        payload.get("structured_output_recovery_used", "-"),
        payload.get("first_cycle_stop_reason", "-"),
        payload.get("first_cycle_tool_choice_installed", "-"),
        payload.get("first_cycle_tool_choice_applied", "-"),
        payload.get("first_cycle_tool_choice_decision", "-"),
        float(payload.get("request_total_ms") or 0.0),
        float(payload.get("request_total_ms") or 0.0),
    )


def assert_payload_is_safe(payload: Mapping[str, Any]) -> None:
    """Raise ``AssertionError`` when a perf payload includes forbidden keys."""
    for key in payload:
        if str(key) not in SAFE_PERF_FIELDS or _is_unsafe_key(str(key)):
            raise AssertionError("unsafe performance field")
        value = payload[key]
        if isinstance(value, str) and any(
            hint in value.lower() for hint in _CONTENT_HINTS
        ):
            raise AssertionError("unsafe performance value")
