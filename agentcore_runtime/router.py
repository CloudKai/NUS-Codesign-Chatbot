"""Luna router helpers. Classification only; FastAPI owns authorization."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

try:
    from models import RouterOutput, parse_router_output
    from prompts.loader import load_router_prompt
    from structured_coach import last_user_text
except ImportError:  # pragma: no cover - imported as agentcore_runtime.router
    from agentcore_runtime.models import RouterOutput, parse_router_output
    from agentcore_runtime.prompts.loader import load_router_prompt
    from agentcore_runtime.structured_coach import last_user_text


def router_system_prompt() -> str:
    """Return the canonical router specialist prompt.

    Returns:
        Short classification instructions with no coaching curriculum.
    """
    return load_router_prompt()


def router_user_prompt(payload: Mapping[str, Any] | None) -> str:
    """Build a small router user prompt from the current message and stage.

    Args:
        payload: Companion router invoke JSON. Must not include full RAG.

    Returns:
        Compact classification input. Empty when the student message is missing.
    """
    message = last_user_text(payload)
    if not message.strip():
        return ""
    stage = ""
    surface = ""
    if isinstance(payload, Mapping):
        context = payload.get("runtime_context")
        if isinstance(context, Mapping):
            stage = str(context.get("current_stage") or "").strip()
            surface = str(context.get("surface") or "").strip()
    parts = [f"Student message:\n{message}"]
    if stage:
        parts.append(f"Current Thinking Path stage: {stage}")
    if surface:
        parts.append(f"Server-owned surface: {surface}")
    return "\n\n".join(parts)


def router_output_from_agent_result(result: Any) -> RouterOutput:
    """Validate structured router output from one AgentResult.

    Args:
        result: Strands AgentResult or a mapping test double.

    Returns:
        A validated :class:`RouterOutput`.

    Raises:
        ValidationError: When the object is not a supported specialist route.
    """
    try:
        from structured_coach import structured_from_agent_result
    except ImportError:  # pragma: no cover
        from agentcore_runtime.structured_coach import structured_from_agent_result
    return structured_from_agent_result(result, parse_router_output)


def router_output_text(output: RouterOutput) -> str:
    """Return compact router JSON for output-side guardrail evaluation."""
    return output.model_dump_json()
