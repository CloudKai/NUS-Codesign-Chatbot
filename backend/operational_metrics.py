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


def record_stage_transition(*, outcome: str) -> None:
    """Record an anonymous accepted/rejected stage-decision outcome."""
    _emit("stage_transition", outcome=outcome)
