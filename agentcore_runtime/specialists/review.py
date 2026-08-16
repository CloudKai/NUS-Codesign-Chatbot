"""Formative Review specialist: incremental Luna or deep Sonnet."""

from __future__ import annotations

try:
    from prompts.loader import (
        load_review_deep_prompt,
        load_review_incremental_prompt,
        load_review_prompt,
    )
    from specialists.routing import REVIEW_MODE_INCREMENTAL
except ImportError:  # pragma: no cover - imported as agentcore_runtime.*
    from agentcore_runtime.prompts.loader import (
        load_review_deep_prompt,
        load_review_incremental_prompt,
        load_review_prompt,
    )
    from agentcore_runtime.specialists.routing import REVIEW_MODE_INCREMENTAL


def review_system_prompt(
    trusted_runtime_rules: str = "",
    *,
    review_mode: str = "deep",
) -> str:
    """Assemble the Formative Review specialist system prompt.

    Args:
        trusted_runtime_rules: Application-owned constraints from FastAPI.
        review_mode: ``incremental`` (Luna) or ``deep`` (Sonnet).

    Returns:
        Review identity plus optional runtime rules. No tools are attached.
    """
    if str(review_mode or "").strip().lower() == REVIEW_MODE_INCREMENTAL:
        body = load_review_incremental_prompt()
    else:
        body = load_review_deep_prompt()
    extra = str(trusted_runtime_rules or "").strip()
    if not extra:
        return body
    return (
        body
        + "\n\nThe following application runtime rules are authoritative for "
        "this turn.\n\n"
        + extra
    )


def shared_review_prompt() -> str:
    """Return the shared Review identity used by documentation tests."""
    return load_review_prompt()
