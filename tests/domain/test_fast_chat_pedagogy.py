"""Fast-chat must include the canonical shared coaching and stage prompts."""

from __future__ import annotations

from agentcore_runtime.prompts.loader import (
    COACHING_TOPICS,
    load_shared_coaching,
    load_stage_prompt,
)
from agentcore_runtime.specialists.fast_chat import fast_chat_system_prompt
from backend.domain import FacioneDimensionScores


def test_fast_chat_includes_exact_shared_coaching_and_each_stage_prompt() -> None:
    shared = load_shared_coaching()
    assert shared
    for topic in sorted(COACHING_TOPICS):
        stage = load_stage_prompt(topic)
        assembled = fast_chat_system_prompt(topic)
        assert shared in assembled
        assert stage in assembled
        assert assembled.index(shared) < assembled.index(stage)


def test_fast_chat_wrapper_does_not_replace_canonical_coaching() -> None:
    assembled = fast_chat_system_prompt("problem_identification", "Guidance mode: Quick.")
    shared = load_shared_coaching()
    assert "Socratic" in shared
    assert shared in assembled
    assert "Guidance mode: Quick." in assembled
    assert assembled.index(shared) < assembled.index("Guidance mode: Quick.")


def test_fast_chat_prompt_allows_framework_structured_output() -> None:
    from agentcore_runtime.structured_coach import specialist_system_prompt
    from pathlib import Path

    text = Path("agentcore_runtime/prompts/fast_chat.md").read_text(encoding="utf-8")
    assert "Do not call tools." not in text
    assert "Return JSON only" not in text
    assert "Do not say the contribution is strong, weak, or ready" in text
    assembled = specialist_system_prompt(
        {
            "phase": "fast_chat",
            "topic": "problem_identification",
            "output_contract": "fast_chat_turn",
        }
    )
    assert assembled.count("framework-provided structured-output") == 1
    assert "FAST CHAT OUTPUT CONTRACT" in assembled


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
