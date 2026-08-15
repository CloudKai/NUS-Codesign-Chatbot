"""Application composer for mock/OpenAI/Bedrock Converse.

Canonical AgentCore specialist and stage pedagogy lives in
``agentcore_runtime/prompts/``. This package still composes the ordered brief
used by non-AgentCore providers and for AgentCore token budgeting.
"""

from __future__ import annotations

from .composer import (
    EMPTY_RETRIEVED_COURSE_CONTEXT,
    PreparedCoachPrompt,
    PromptComposer,
    PromptContext,
    compose_coach_prompt,
    prompt_context_from_request,
)
from .loader import (
    PromptLoadError,
    clear_prompt_cache,
    load_shared_prompt,
    load_stage_prompt,
    validate_stage_prompt_files,
)

__all__ = [
    "EMPTY_RETRIEVED_COURSE_CONTEXT",
    "PreparedCoachPrompt",
    "PromptComposer",
    "PromptContext",
    "PromptLoadError",
    "clear_prompt_cache",
    "compose_coach_prompt",
    "load_shared_prompt",
    "load_stage_prompt",
    "prompt_context_from_request",
    "validate_stage_prompt_files",
]
