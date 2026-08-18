"""Privacy-safe structured operational metrics for the API boundary.

Metrics are written to the normal application log rather than exposed through
an HTTP endpoint.  They intentionally contain neither request bodies, source
text, notebook identifiers, tokens, email addresses, nor provider responses.
This keeps the production telemetry useful for EC2 health investigation without
turning it into a second store of student data.
"""

from __future__ import annotations

import json
import logging
from time import perf_counter
from typing import Any


logger = logging.getLogger("co_design.operational")

_OPERATIONAL_LOGGERS = (
    "backend.api",
    "backend.agentcore_provider",
    "backend.bedrock_retrieve",
    "backend.retrieval",
    "co_design.operational",
    "co_design.turn_perf",
    "co_design.ui_perf",
)

_HANDLER_FLAG = "_co_design_operational_stream"


def configure_operational_loggers() -> None:
    """Enable INFO operational logs that remain visible under uvicorn.

    Production uvicorn leaves the root logger at WARNING and often has no
    root handler, so INFO ``coach_turn_perf`` / ``TIMING`` lines never
    reached ``docker logs``. Each operational logger gets its own INFO
    stream handler. Records still propagate so pytest ``caplog`` works.
    These loggers must not emit student text, prompts, or notebook ids.
    """
    handler = logging.StreamHandler()
    handler.setLevel(logging.INFO)
    handler.setFormatter(logging.Formatter("%(levelname)s:%(name)s:%(message)s"))
    setattr(handler, _HANDLER_FLAG, True)
    for name in _OPERATIONAL_LOGGERS:
        log = logging.getLogger(name)
        log.setLevel(logging.INFO)
        if any(getattr(existing, _HANDLER_FLAG, False) for existing in log.handlers):
            continue
        log.addHandler(handler)


def _emit(event: str, **fields: Any) -> None:
    """Write one compact JSON metric event with only caller-approved fields."""
    payload = {"event": event, **fields}
    logger.info("%s", json.dumps(payload, separators=(",", ":"), sort_keys=True))


def started_at() -> float:
    """Return a monotonic start marker for a request or operation."""
    return perf_counter()


def record_http_request(
    *,
    method: str,
    route: str,
    status_code: int,
    started: float,
) -> None:
    """Record one API request latency and final status without client content."""
    _emit(
        "http_request",
        duration_ms=round((perf_counter() - started) * 1000, 1),
        method=method.upper(),
        route=route,
        status_code=int(status_code),
    )


def record_coach_turn(
    *,
    provider: str,
    outcome: str,
    selected_source_count: int,
    citation_count: int = 0,
    recommendation: str = "unknown",
    transition_outcome: str = "none",
) -> None:
    """Record aggregate coaching/retrieval outcomes without turn identifiers.

    ``selected_source_count`` and ``citation_count`` are bounded aggregate
    counts. They describe whether grounded retrieval reached the response but
    cannot identify a notebook, source, or student.
    """
    _emit(
        "coach_turn",
        citation_count=max(0, int(citation_count)),
        citation_outcome=("cited" if citation_count else "not_cited"),
        outcome=outcome,
        provider=provider,
        recommendation=recommendation,
        retrieval_outcome=(
            "not_requested"
            if selected_source_count == 0
            else ("cited" if citation_count else "no_citation")
        ),
        selected_source_count=max(0, int(selected_source_count)),
        transition_outcome=transition_outcome,
    )


def record_coach_rate_limit(*, category: str) -> None:
    """Record one privacy-safe coach concurrency rejection.

    ``category`` is one of ``notebook_concurrency``, ``user_concurrency``,
    ``user_rpm``, ``global_capacity``, or ``missing_identity``. No user,
    notebook, or message identifiers are included.
    """
    label = str(category or "throttled").strip() or "throttled"
    _emit("coach_rate_limited", category=label)


def record_stage_transition(*, outcome: str) -> None:
    """Record an anonymous accepted/rejected stage-decision outcome."""
    _emit("stage_transition", outcome=outcome)


def record_coach_turn_perf(fields: dict[str, Any]) -> None:
    """Record one privacy-safe coaching latency/context breakdown.

    Callers must already strip student text, prompts, excerpts, tokens, and
    identifiers. This helper only emits the supplied numeric/categorical
    fields under a stable event name.
    """
    cleaned = {
        key: value
        for key, value in dict(fields or {}).items()
        if str(key).strip() and value is not None
    }
    _emit("coach_turn_perf", **cleaned)
