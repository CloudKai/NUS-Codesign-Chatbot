"""Formative Review specialist: synthesis, not a grade."""

from __future__ import annotations

try:
    from prompts.loader import load_review_prompt
except ImportError:  # pragma: no cover - imported as agentcore_runtime.*
    from agentcore_runtime.prompts.loader import load_review_prompt


def review_system_prompt(trusted_runtime_rules: str = "") -> str:
    """Assemble the Formative Review specialist system prompt.

    Args:
        trusted_runtime_rules: Application-owned constraints from FastAPI.

    Returns:
        Review identity plus optional runtime rules. No tools are attached.
    """
    body = load_review_prompt()
    extra = str(trusted_runtime_rules or "").strip()
    if not extra:
        return body
    return (
        body
        + "\n\nThe following application runtime rules are authoritative for "
        "this turn.\n\n"
        + extra
    )
