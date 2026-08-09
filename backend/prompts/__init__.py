"""Framework-neutral local stage-prompt package for coaching turns.

Prompt markdown files define educational BEHAVIOUR. Selected-source context
(and later Knowledge Base chunks) supply KNOWLEDGE via the composer. Providers
invoke models; they do not own stage educational wording.
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
