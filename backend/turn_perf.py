"""Privacy-safe per-request latency and context instrumentation.

This module records numeric timings and bounded counts for one coaching turn.
It never stores student text, prompts, retrieved excerpts, notebook identifiers,
auth tokens, cookies, or AWS credentials. Callers must only pass approved
field names from :data:`SAFE_PERF_FIELDS`.
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
        "auth_context_ms",
        "notebook_load_ms",
        "history_load_ms",
        "source_load_ms",
        "retrieval_gate_ms",
        "retrieval_required",
        "course_kb_retrieval_ms",
        "student_source_retrieval_ms",
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
        "model_role",
        "model_id",
        "mode_returned",
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
        "rag_fallback_used",
        "rag_fallback_model_calls",
        "rag_fallback_retrieval_ms",
        "deep_review_invoked",
        "deep_review_model_role",
        "prompt_cache_enabled",
        "prompt_cache_hit",
        "cache_write_input_tokens",
        "cache_read_input_tokens",
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
    reset_coach_turn_perf()
    return payload


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
