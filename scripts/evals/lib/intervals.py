"""Wilson 95% intervals and small-sample marks shared by the eval commands.

Moved verbatim from ``evaluate_combined_gate`` so ``compare_routing_arms`` reuses the
same maths without importing another command. No backend imports, no I/O.
"""

from __future__ import annotations

import math
from collections.abc import Mapping
from statistics import NormalDist
from typing import Any

from scripts.evals.lib.metrics import rate_record

Z_95 = NormalDist().inv_cdf(0.975)
SMALL_N = 30
VERY_SMALL_N = 10


def wilson_interval(successes: int, total: int, z: float = Z_95) -> tuple[float, float] | None:
    """Wilson score interval for a proportion, or ``None`` when ``total`` is 0."""
    if total <= 0:
        return None
    if not 0 <= successes <= total:
        raise ValueError("successes must be between 0 and total")
    p = successes / total
    denominator = 1 + z * z / total
    centre = (p + z * z / (2 * total)) / denominator
    half = z * math.sqrt(p * (1 - p) / total + z * z / (4 * total * total)) / denominator
    return max(0.0, centre - half), min(1.0, centre + half)


def sample_mark(total: int) -> str:
    """``VS`` under 10 rows, ``S`` under 30 rows, else empty."""
    if total < VERY_SMALL_N:
        return "VS"
    if total < SMALL_N:
        return "S"
    return ""


def rate_ci(successes: int, total: int) -> dict[str, Any]:
    """A rate record with a Wilson 95% interval and a small-sample mark."""
    base = rate_record(successes, total)
    interval = wilson_interval(successes, total)
    return {
        **base,
        "wilson_low": None if interval is None else round(interval[0], 4),
        "wilson_high": None if interval is None else round(interval[1], 4),
        "small_sample": sample_mark(total),
    }


def format_ci(record: Mapping[str, Any]) -> str:
    """Render ``n/d = p% [lo, hi] mark`` or ``n/a (0/0)``."""
    if record["rate"] is None:
        return f"n/a ({record['numerator']}/{record['denominator']})"
    text = (
        f"{record['numerator']}/{record['denominator']} = {record['rate'] * 100:.1f}% "
        f"[{record['wilson_low'] * 100:.1f}, {record['wilson_high'] * 100:.1f}]"
    )
    return f"{text} {record['small_sample']}".rstrip()
