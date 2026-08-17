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

# Legacy Coaching still uses this identity. Fast Chat must not open as a
# locked Coaching specialist while it is deciding Coaching versus Q&A.
_COACHING_SPECIALIST_IDENTITY = (
    "You are the Coaching specialist in a Socratic design-thinking coach for CDE2300."
)
_FAST_CHAT_IDENTITY = (
    "This turn is Fast Chat in a Socratic design-thinking coach for CDE2300. "
    "Decide Coaching versus Q&A internally; you are not locked to the Coaching specialist."
)


def shared_coaching_for_fast_chat() -> str:
    """Return shared coaching pedagogy with Fast Chat identity, not specialist lock.

    Returns:
        Canonical ``shared_coaching.md`` with only the opening identity sentence
        replaced. Stage files and the rest of the Socratic baseline are unchanged.
    """
    text = load_shared_coaching()
    if text.startswith(_COACHING_SPECIALIST_IDENTITY):
        return _FAST_CHAT_IDENTITY + text[len(_COACHING_SPECIALIST_IDENTITY) :]
    return text


def fast_chat_static_prefix(topic: str) -> str:
    """Return the cacheable pedagogical prefix for one fast-chat topic.

    Args:
        topic: AgentCore coaching topic, including ``ethics_critical``.

    Returns:
        Shared coaching pedagogy with Fast Chat identity, the current stage
        prompt, and ``fast_chat.md``. Runtime rules, student text, and
        retrieved evidence are excluded.
    """
    return "\n\n".join(
        [
            shared_coaching_for_fast_chat(),
            load_stage_prompt(topic),
            load_fast_chat_prompt(),
        ]
    )


def fast_chat_system_prompt(topic: str, trusted_runtime_rules: str = "") -> str:
    """Assemble the one-call fast-chat system prompt.

    Args:
        topic: AgentCore coaching topic, including ``ethics_critical``.
        trusted_runtime_rules: Application-owned constraints from FastAPI.

    Returns:
        Combined shared pedagogy, current-stage instructions, Fast Chat
        coaching-versus-Q&A rules, and runtime constraints. Does not instruct
        a multi-role chain.
    """
    parts = [fast_chat_static_prefix(topic)]
    extra = str(trusted_runtime_rules or "").strip()
    if extra:
        parts.append(
            "The following application runtime rules are authoritative for "
            "this turn. They do not replace the stage pedagogy above.\n\n"
            + extra
        )
    return "\n\n".join(parts)
