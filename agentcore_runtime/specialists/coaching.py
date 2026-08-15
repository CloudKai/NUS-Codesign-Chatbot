"""Coaching specialist: Socratic Thinking Path pedagogy."""

from __future__ import annotations

try:
    from prompts.loader import load_shared_coaching, load_stage_prompt
except ImportError:  # pragma: no cover - imported as agentcore_runtime.*
    from agentcore_runtime.prompts.loader import load_shared_coaching, load_stage_prompt


def coaching_system_prompt(topic: str, trusted_runtime_rules: str = "") -> str:
    """Assemble the coaching specialist system prompt for one topic.

    Args:
        topic: AgentCore coaching topic, including ``ethics_critical``.
        trusted_runtime_rules: Application-owned constraints from FastAPI.

    Returns:
        Specialist identity, shared pedagogy, stage meaning, and runtime rules.
    """
    parts = [load_shared_coaching(), load_stage_prompt(topic)]
    extra = str(trusted_runtime_rules or "").strip()
    if extra:
        parts.append(
            "The following application runtime rules are authoritative for "
            "this turn. They do not replace the stage pedagogy above.\n\n"
            + extra
        )
    return "\n\n".join(parts)
