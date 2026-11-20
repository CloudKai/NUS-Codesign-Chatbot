"""Pure metric helpers shared by the eval commands: rates, intervals, percentiles.

No backend imports, no I/O.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Any


def rate(numerator: int, denominator: int) -> float | None:
    """Return numerator/denominator, or ``None`` when the denominator is 0."""
    if denominator <= 0:
        return None
    return numerator / denominator


def rate_record(numerator: int, denominator: int) -> dict[str, Any]:
    """Return a JSON-ready ``{numerator, denominator, rate}`` record."""
    value = rate(numerator, denominator)
    return {
        "numerator": numerator,
        "denominator": denominator,
        "rate": None if value is None else round(value, 4),
    }


def format_rate(record: Mapping[str, Any]) -> str:
    """Render a rate record as ``n/d (p%)`` or ``n/a``."""
    value = record.get("rate")
    if value is None:
        return f"n/a ({record['numerator']}/{record['denominator']})"
    return f"{record['numerator']}/{record['denominator']} ({value * 100:.1f}%)"


def wrong_skip_rate(decisions: Iterable[tuple[str, bool]]) -> dict[str, Any]:
    """Share of 'should retrieve' messages the gate skipped.

    Args:
        decisions: ``(expected_decision, gate_retrieved)`` per message.
    """
    expected_retrieve = [
        retrieved for expected, retrieved in decisions if expected == "retrieve"
    ]
    skipped = sum(1 for retrieved in expected_retrieve if not retrieved)
    return rate_record(skipped, len(expected_retrieve))


def false_retrieve_rate(decisions: Iterable[tuple[str, bool]]) -> dict[str, Any]:
    """Share of 'should skip' messages the gate searched for (reported extra)."""
    expected_skip = [
        retrieved for expected, retrieved in decisions if expected == "skip"
    ]
    searched = sum(1 for retrieved in expected_skip if retrieved)
    return rate_record(searched, len(expected_skip))


def empty_result_rate(result_counts: Iterable[int]) -> dict[str, Any]:
    """Share of completed attempts that returned zero results.

    Args:
        result_counts: Number of results per completed attempt.
    """
    counts = list(result_counts)
    empty = sum(1 for count in counts if count == 0)
    return rate_record(empty, len(counts))


def evenly_spaced_indices(total: int, limit: int) -> list[int]:
    """Pick ``min(limit, total)`` deterministic, evenly spread indices."""
    if total <= 0 or limit <= 0:
        return []
    if limit >= total:
        return list(range(total))
    return [index * total // limit for index in range(limit)]
