"""Exact McNemar test for paired binary outcomes. Pure maths, no I/O."""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from typing import Any


def exact_mcnemar_p(b: int, c: int) -> float:
    """Exact two-sided McNemar p-value from the discordant counts ``b`` and ``c``.

    ``n = b + c`` and ``p = min(1, 2 * P(X <= min(b, c)))`` with ``X ~ Binomial(n, 0.5)``.
    ``n = 0`` gives 1. The sum uses integers, so ``(10, 2)`` is exactly 158/4096.
    """
    if b < 0 or c < 0:
        raise ValueError("discordant counts cannot be negative")
    n = b + c
    if n == 0:
        return 1.0
    tail = sum(math.comb(n, k) for k in range(min(b, c) + 1))
    return min(1.0, 2 * tail / 2**n)


def paired_outcomes(
    first: Mapping[str, bool], second: Mapping[str, bool], ids: Sequence[str]
) -> dict[str, Any]:
    """Count discordant pairs over ``ids`` for two outcome maps (True means a bad outcome).

    ``first_bad_second_ok`` is the rows where only the first arm has the bad outcome and
    ``first_ok_second_bad`` where only the second does. Rows bad for both or neither are
    concordant and do not enter the test.
    """
    b = sum(1 for i in ids if first[i] and not second[i])
    c = sum(1 for i in ids if second[i] and not first[i])
    return {
        "rows": len(ids),
        "first_bad_second_ok": b,
        "first_ok_second_bad": c,
        "both_bad": sum(1 for i in ids if first[i] and second[i]),
        "both_ok": sum(1 for i in ids if not first[i] and not second[i]),
        "p_value": exact_mcnemar_p(b, c),
    }
