"""Combined fast-chat specialist: one Haiku call for Coaching or Q&A."""

from __future__ import annotations

try:
    from prompts.loader import (
        load_fast_chat_prompt,
        load_shared_coaching,
        load_stage_prompt,
    )
except ImportError:  # pragma: no cover - imported as agentcore_runtime.*
    from agentcore_runtime.prompts.loader import (
        load_fast_chat_prompt,
        load_shared_coaching,
        load_stage_prompt,
    )


def fast_chat_system_prompt(topic: str, trusted_runtime_rules: str = "") -> str:
    """Assemble the one-call fast-chat system prompt.

    Args:
        topic: AgentCore coaching topic, including ``ethics_critical``.
        trusted_runtime_rules: Application-owned constraints from FastAPI.

    Returns:
        Combined identity, shared pedagogy, current-stage instructions, and
        runtime rules. Does not instruct a multi-role chain.
    """
    parts = [
        load_fast_chat_prompt(),
        load_shared_coaching(),
        load_stage_prompt(topic),
    ]
    extra = str(trusted_runtime_rules or "").strip()
    if extra:
        parts.append(
            "The following application runtime rules are authoritative for "
            "this turn. They do not replace the stage pedagogy above.\n\n"
            + extra
        )
    return "\n\n".join(parts)
