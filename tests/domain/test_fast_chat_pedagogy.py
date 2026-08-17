"""Fast-chat must include the canonical shared coaching and stage prompts."""

from __future__ import annotations

from agentcore_runtime.prompts.loader import (
    COACHING_TOPICS,
    load_shared_coaching,
    load_stage_prompt,
)
from agentcore_runtime.specialists.fast_chat import (
    fast_chat_system_prompt,
    shared_coaching_for_fast_chat,
)
from backend.domain import FacioneDimensionScores

_COACHING_IDENTITY = (
    "You are the Coaching specialist in a Socratic design-thinking coach for CDE2300."
)


def _shared_coaching_body() -> str:
    """Return canonical shared coaching after the legacy specialist identity."""
    shared = load_shared_coaching()
    if shared.startswith(_COACHING_IDENTITY):
        return shared[len(_COACHING_IDENTITY) :]
    return shared


def test_fast_chat_includes_exact_shared_coaching_and_each_stage_prompt() -> None:
    shared_body = _shared_coaching_body()
    fast_shared = shared_coaching_for_fast_chat()
    assert shared_body
    assert fast_shared.startswith("This turn is Fast Chat")
    assert not fast_shared.startswith(_COACHING_IDENTITY)
    for topic in sorted(COACHING_TOPICS):
        stage = load_stage_prompt(topic)
        assembled = fast_chat_system_prompt(topic)
        assert fast_shared in assembled
        assert shared_body in assembled
        assert stage in assembled
        assert assembled.index(fast_shared) < assembled.index(stage)
        assert not assembled.lstrip().startswith(_COACHING_IDENTITY)


def test_fast_chat_wrapper_does_not_replace_canonical_coaching() -> None:
    assembled = fast_chat_system_prompt("problem_identification", "Guidance mode: Quick.")
    shared_body = _shared_coaching_body()
    assert "Socratic" in shared_body
    assert shared_body in assembled
    assert "Guidance mode: Quick." in assembled
    assert assembled.index(shared_body) < assembled.index("Guidance mode: Quick.")
    assert load_shared_coaching().startswith(_COACHING_IDENTITY)


def test_fast_chat_prompt_allows_framework_structured_output() -> None:
    from agentcore_runtime.structured_coach import specialist_system_prompt
    from pathlib import Path

    text = Path("agentcore_runtime/prompts/fast_chat.md").read_text(encoding="utf-8")
    normalized = " ".join(text.split())
    assert "Do not call tools." not in text
    assert "Return JSON only" not in text
    assert "Do not say the contribution is strong, weak, or ready" in text
    assert "You are not locked to the Coaching specialist" in normalized
    assembled = specialist_system_prompt(
        {
            "phase": "fast_chat",
            "topic": "problem_identification",
            "output_contract": "fast_chat_turn",
        }
    )
    assert assembled.count("framework-provided structured-output") == 1
    assert "FAST CHAT OUTPUT CONTRACT" in assembled
    assert "Do not emit an intermediate conversational answer first" in assembled
    assert "not a locked Coaching specialist" in assembled


def test_facione_schema_still_has_six_dimensions() -> None:
    fields = set(FacioneDimensionScores.model_fields)
    assert fields == {
        "analysis",
        "interpretation",
        "inference",
        "evaluation",
        "explanation",
        "self_regulation",
    }
