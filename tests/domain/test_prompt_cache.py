"""Pinned Strands 1.52.0 fast-chat prefix cache helpers. No AWS."""

from __future__ import annotations

from types import SimpleNamespace

from agentcore_runtime.prompt_cache import (
    HAIKU_MIN_CACHE_TOKENS,
    cache_usage_from_agent_result,
    estimate_prefix_tokens,
    prefix_meets_haiku_cache_minimum,
    prompt_cache_enabled_from_environ,
    system_prompt_with_optional_cache_point,
)
from agentcore_runtime.specialists.fast_chat import fast_chat_static_prefix
from agentcore_runtime.structured_coach import (
    agent_system_prompt,
    specialist_system_prompt,
)
from agentcore_runtime.model import bedrock_model_kwargs, runtime_model_config_from_mapping
from agentcore_runtime.model import HAIKU_4_5_MODEL_ID, SONNET_4_6_MODEL_ID


def test_cache_disabled_returns_identical_string() -> None:
    prefix = "STATIC PEDAGOGY"
    suffix = "\n\nDYNAMIC RULES"
    result = system_prompt_with_optional_cache_point(
        static_prefix=prefix,
        dynamic_suffix=suffix,
        enabled=False,
    )
    assert result == prefix + suffix
    assert isinstance(result, str)


def test_prefix_below_minimum_does_not_insert_cache_point_or_padding() -> None:
    prefix = "short prefix"
    suffix = "\n\nruntime"
    assert estimate_prefix_tokens(prefix) < HAIKU_MIN_CACHE_TOKENS
    result = system_prompt_with_optional_cache_point(
        static_prefix=prefix,
        dynamic_suffix=suffix,
        enabled=True,
    )
    assert result == prefix + suffix
    assert "pad" not in str(result).lower()
    assert isinstance(result, str)


def test_eligible_prefix_uses_system_content_block_not_cache_config() -> None:
    prefix = "P" * (HAIKU_MIN_CACHE_TOKENS * 4)
    suffix = "\n\nDYNAMIC"
    result = system_prompt_with_optional_cache_point(
        static_prefix=prefix,
        dynamic_suffix=suffix,
        enabled=True,
    )
    assert isinstance(result, list)
    assert result[0] == {"text": prefix}
    assert result[1] == {"cachePoint": {"type": "default"}}
    assert result[2] == {"text": suffix}
    assert "student" not in prefix.lower()


def test_static_prefix_excludes_runtime_and_student_content() -> None:
    prefix = fast_chat_static_prefix("problem_identification")
    lowered = prefix.lower()
    assert "conversation_revision" not in lowered
    assert "allowed_citations" not in lowered
    assert "guidance mode: quick." not in lowered
    payload = {
        "phase": "fast_chat",
        "topic": "problem_identification",
        "output_contract": "fast_chat_turn",
        "trusted_instructions": "Guidance mode: Quick.",
        "runtime_context": {
            "current_stage": "problem_identification",
            "allowed_citations": ["S1"],
            "conversation_revision": 9,
        },
    }
    assembled = specialist_system_prompt(payload)
    assert prefix in assembled
    assert assembled.index(prefix) == 0
    assert "Guidance mode: Quick." in assembled
    assert "conversation_revision" in assembled
    assert assembled.index(prefix) + len(prefix) <= assembled.index("conversation_revision")


def test_agent_system_prompt_defaults_to_identical_string(monkeypatch) -> None:
    monkeypatch.delenv("FAST_CHAT_PROMPT_CACHE_ENABLED", raising=False)
    payload = {
        "phase": "fast_chat",
        "topic": "concept_generation",
        "output_contract": "fast_chat_turn",
    }
    assert agent_system_prompt(payload) == specialist_system_prompt(payload)
    assert prompt_cache_enabled_from_environ({}) is False


def test_cache_usage_is_not_fabricated() -> None:
    assert cache_usage_from_agent_result(None) == {}
    empty = SimpleNamespace(metrics=SimpleNamespace(accumulated_usage={}))
    assert cache_usage_from_agent_result(empty) == {}
    metrics = SimpleNamespace(
        accumulated_usage={
            "inputTokens": 10,
            "outputTokens": 4,
            "totalTokens": 14,
            "cacheReadInputTokens": 12,
            "cacheWriteInputTokens": 80,
        }
    )
    result = SimpleNamespace(metrics=metrics)
    assert cache_usage_from_agent_result(result) == {
        "cache_read_input_tokens": 12,
        "cache_write_input_tokens": 80,
    }


def test_bedrock_kwargs_do_not_enable_message_caching() -> None:
    config = runtime_model_config_from_mapping(
        {
            "AGENTCORE_MODEL_PROVIDER": "bedrock",
            "AGENTCORE_MODEL_ID": HAIKU_4_5_MODEL_ID,
            "AGENTCORE_MODEL_REGION": "us-west-2",
            "GUARDRAIL_ID": "gr-test",
            "GUARDRAIL_VERSION": "3",
        }
    )
    kwargs = bedrock_model_kwargs(config)
    assert "cache_config" not in kwargs
    assert "cache_prompt" not in kwargs


def test_fast_chat_and_deep_review_model_ids_are_not_substituted() -> None:
    assert HAIKU_4_5_MODEL_ID == "global.anthropic.claude-haiku-4-5-20251001-v1:0"
    assert SONNET_4_6_MODEL_ID == "global.anthropic.claude-sonnet-4-6"
    assert prefix_meets_haiku_cache_minimum("x") is False
