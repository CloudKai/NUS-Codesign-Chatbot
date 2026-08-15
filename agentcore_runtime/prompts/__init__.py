"""Canonical AgentCore pedagogical prompts. This package does not import backend."""

from __future__ import annotations

from .loader import (
    PromptLoadError,
    load_qa_prompt,
    load_review_prompt,
    load_shared_coaching,
    load_stage_prompt,
    normalize_coaching_topic,
)

__all__ = [
    "PromptLoadError",
    "load_qa_prompt",
    "load_review_prompt",
    "load_shared_coaching",
    "load_stage_prompt",
    "normalize_coaching_topic",
]
