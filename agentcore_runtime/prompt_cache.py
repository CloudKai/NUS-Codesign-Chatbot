"""Fast-chat pedagogical prefix cache helpers for pinned Strands 1.52.0.

Claude Haiku 4.5 supports Bedrock prompt caching but requires at least 4,096
tokens before a cache checkpoint. ``CacheConfig(strategy="auto")`` injects a
cache point on the last user message and would cache student text, so this
module never uses it.

The supported mechanism is a Strands ``SystemContentBlock`` ``cachePoint``
after the static pedagogical prefix (fast_chat + shared coaching + current
stage). Dynamic runtime rules stay after that point.

Default behaviour is cache-disabled and string-identical to the uncached
prompt. This module never pads prompts to force eligibility.
"""

from __future__ import annotations

import logging
import math
import os
from typing import Any, Mapping

logger = logging.getLogger("agentcore_runtime.prompt_cache")

HAIKU_MIN_CACHE_TOKENS = 4096
# Conservative eligibility: under-count tokens so a cache point is not sent
# when the prefix may be below Bedrock's minimum.
CACHE_ELIGIBILITY_CHARS_PER_TOKEN = 4.0
CACHE_POINT_TYPE = "default"


def prompt_cache_enabled_from_environ(values: Mapping[str, Any] | None = None) -> bool:
    """Return whether the AgentCore process opted into fast-chat prefix cache.

    Args:
        values: Optional environment mapping. Defaults to ``os.environ``.

    Returns:
        True only for explicit true-like values. Local/test default is false.
    """
    data = values if values is not None else os.environ
    raw = str(data.get("FAST_CHAT_PROMPT_CACHE_ENABLED") or "").strip().lower()
    return raw in {"1", "true", "yes", "on"}


def estimate_prefix_tokens(text: str) -> int:
    """Return a conservative token estimate for cache eligibility.

    Args:
        text: Static pedagogical prefix. Must not include student text.

    Returns:
        Estimated token count using a high chars-per-token ratio.
    """
    cleaned = str(text or "")
    if not cleaned:
        return 0
    return int(math.ceil(len(cleaned) / CACHE_ELIGIBILITY_CHARS_PER_TOKEN))


def prefix_meets_haiku_cache_minimum(text: str) -> bool:
    """Return whether ``text`` is estimated at or above the Haiku cache floor."""
    return estimate_prefix_tokens(text) >= HAIKU_MIN_CACHE_TOKENS


def log_prompt_cache_decision(
    *,
    enabled: bool,
    eligible: bool,
    reason: str,
    estimated_tokens: int = 0,
) -> None:
    """Log category-only cache eligibility. Never logs prompt text."""
    logger.info(
        "prompt_cache_enabled=%s prompt_cache_eligible=%s reason=%s "
        "estimated_prefix_tokens=%s haiku_min_cache_tokens=%s",
        "true" if enabled else "false",
        "true" if eligible else "false",
        str(reason or "unspecified")[:80],
        int(estimated_tokens),
        HAIKU_MIN_CACHE_TOKENS,
    )


def cache_usage_from_agent_result(result: Any) -> dict[str, int]:
    """Extract cache token counts from AgentResult metrics when present.

    Args:
        result: Optional Strands AgentResult. Duck-typed so pytest can run
            without Strands.

    Returns:
        Mapping that may include ``cache_read_input_tokens`` and
        ``cache_write_input_tokens``. Absent keys are omitted; zeros are
        recorded only when the runtime supplied the field.
    """
    metrics = getattr(result, "metrics", None)
    usage = getattr(metrics, "accumulated_usage", None)
    if not isinstance(usage, Mapping):
        return {}
    extracted: dict[str, int] = {}
    mapping = (
        ("cacheReadInputTokens", "cache_read_input_tokens"),
        ("cacheWriteInputTokens", "cache_write_input_tokens"),
    )
    for source, dest in mapping:
        if source not in usage:
            continue
        raw = usage[source]
        if isinstance(raw, bool) or not isinstance(raw, (int, float)):
            continue
        extracted[dest] = int(raw)
    return extracted


def system_prompt_with_optional_cache_point(
    *,
    static_prefix: str,
    dynamic_suffix: str,
    enabled: bool,
) -> str | list[dict[str, Any]]:
    """Return a string prompt or SystemContentBlock list for one Agent invoke.

    Args:
        static_prefix: Cacheable pedagogical prefix. No student/RAG content.
        dynamic_suffix: Runtime rules and JSON contract, including the
            original ``\\n\\n`` separator so concatenation matches the
            uncached string prompt.
        enabled: Process feature flag.

    Returns:
        The concatenated string when cache is disabled or the prefix is
        below the Haiku minimum. Otherwise a three-block list with a
        ``cachePoint`` between prefix and suffix.
    """
    prefix = str(static_prefix or "")
    suffix = str(dynamic_suffix or "")
    combined = f"{prefix}{suffix}"
    estimated = estimate_prefix_tokens(prefix)
    if not enabled:
        log_prompt_cache_decision(
            enabled=False,
            eligible=False,
            reason="disabled",
            estimated_tokens=estimated,
        )
        return combined
    if not prefix.strip() or not suffix:
        log_prompt_cache_decision(
            enabled=True,
            eligible=False,
            reason="prefix_or_suffix_empty",
            estimated_tokens=estimated,
        )
        return combined
    if estimated < HAIKU_MIN_CACHE_TOKENS:
        log_prompt_cache_decision(
            enabled=True,
            eligible=False,
            reason="prefix_below_minimum",
            estimated_tokens=estimated,
        )
        return combined
    log_prompt_cache_decision(
        enabled=True,
        eligible=True,
        reason="static_prefix_cache_point",
        estimated_tokens=estimated,
    )
    return [
        {"text": prefix},
        {"cachePoint": {"type": CACHE_POINT_TYPE}},
        {"text": suffix},
    ]
