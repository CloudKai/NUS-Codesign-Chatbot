"""Q&A specialist: grounded course answers over pre-retrieved evidence."""

from __future__ import annotations

try:
    from prompts.loader import load_qa_prompt
except ImportError:  # pragma: no cover - imported as agentcore_runtime.*
    from agentcore_runtime.prompts.loader import load_qa_prompt


def qa_system_prompt(trusted_runtime_rules: str = "") -> str:
    """Assemble the Q&A specialist system prompt.

    Args:
        trusted_runtime_rules: Application-owned constraints from FastAPI.

    Returns:
        Q&A identity plus optional runtime rules. No tools are attached.
    """
    body = load_qa_prompt()
    extra = str(trusted_runtime_rules or "").strip()
    if not extra:
        return body
    return (
        body
        + "\n\nThe following application runtime rules are authoritative for "
        "this turn.\n\n"
        + extra
    )
