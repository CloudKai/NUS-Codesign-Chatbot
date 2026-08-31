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

try:
    from ..module_profile import load_module_profile
except ImportError:  # pragma: no cover - deployed with main.py at zip root
    from module_profile import load_module_profile

# Legacy Coaching still uses this identity. Fast Chat must not open as a
# locked Coaching specialist while it is deciding Coaching versus Q&A.
def _identities() -> tuple[str, str]:
    """Return module-specific identities while keeping curriculum static."""
    code = load_module_profile().module_code
    return (
        f"You are the Coaching specialist in a Socratic design-thinking coach for {code}.",
        f"This turn is Fast Chat in a Socratic design-thinking coach for {code}. "
        "Decide Coaching versus Q&A internally; you are not locked to the Coaching specialist.",
    )


def shared_coaching_for_fast_chat() -> str:
    """Return shared coaching pedagogy with Fast Chat identity, not specialist lock.

    Returns:
        Canonical ``shared_coaching.md`` with only the opening identity sentence
        replaced. Stage files and the rest of the Socratic baseline are unchanged.
    """
    text = load_shared_coaching()
    coaching_identity, fast_identity = _identities()
    if text.startswith(coaching_identity):
        return fast_identity + text[len(coaching_identity) :]
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
            "this turn. When they specify source Q&A or expected_response_mode=qa, "
            "they take precedence over Coaching and stage-progression pedagogy "
            "above. Otherwise they constrain Coaching without replacing stage "
            "pedagogy.\n\n"
            "Prior assistant messages are not course evidence. If retrieved "
            "evidence is missing and broader model knowledge is not permitted, "
            "state the evidence gap; do not continue with course facts from "
            "history.\n\n"
            + extra
        )
    return "\n\n".join(parts)
