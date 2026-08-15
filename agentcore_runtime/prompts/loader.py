"""UTF-8 loader for canonical AgentCore specialist and stage prompts.

This module must not import the companion ``backend`` package. Stage files
use AgentCore topic keys, including ``ethics_critical`` for the persisted
application stage ``deep_analysis``.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

COACHING_TOPICS = frozenset(
    {
        "problem_identification",
        "concept_generation",
        "design_specification",
        "ethics_critical",
        "reflection",
    }
)
DEFAULT_COACHING_TOPIC = "problem_identification"

_PROMPTS_ROOT = Path(__file__).resolve().parent
_SHARED_PATH = _PROMPTS_ROOT / "shared_coaching.md"
_QA_PATH = _PROMPTS_ROOT / "qa.md"
_REVIEW_PATH = _PROMPTS_ROOT / "review.md"
_STAGES_DIR = _PROMPTS_ROOT / "stages"


class PromptLoadError(ValueError):
    """Raised when a runtime prompt file is missing or invalid."""


def _read_utf8(path: Path) -> str:
    """Load one prompt file as UTF-8 text.

    Args:
        path: Absolute prompt file path.

    Returns:
        File contents with surrounding whitespace stripped.

    Raises:
        PromptLoadError: When the file is missing, empty, or not UTF-8.
    """
    try:
        text = path.read_text(encoding="utf-8").strip()
    except FileNotFoundError as error:
        raise PromptLoadError(f"Prompt file not found: {path}") from error
    except UnicodeDecodeError as error:
        raise PromptLoadError(f"Prompt file is not valid UTF-8: {path}") from error
    if not text:
        raise PromptLoadError(f"Prompt file is empty: {path}")
    return text


def normalize_coaching_topic(topic: str | None) -> str:
    """Return a known coaching topic, defaulting closed to Problem Identification.

    Args:
        topic: AgentCore topic key from the invoke payload.

    Returns:
        A member of ``COACHING_TOPICS``.
    """
    cleaned = str(topic or "").strip().lower()
    if cleaned in COACHING_TOPICS:
        return cleaned
    return DEFAULT_COACHING_TOPIC


@lru_cache(maxsize=1)
def load_shared_coaching() -> str:
    """Return the canonical shared coaching specialist prompt."""
    return _read_utf8(_SHARED_PATH)


@lru_cache(maxsize=1)
def load_qa_prompt() -> str:
    """Return the canonical Q&A specialist prompt."""
    return _read_utf8(_QA_PATH)


@lru_cache(maxsize=1)
def load_review_prompt() -> str:
    """Return the canonical Formative Review specialist prompt."""
    return _read_utf8(_REVIEW_PATH)


@lru_cache(maxsize=8)
def load_stage_prompt(topic: str) -> str:
    """Return the stage pedagogical prompt for one AgentCore topic.

    Args:
        topic: Coaching topic key, including ``ethics_critical``.

    Returns:
        Stage instruction text for that topic.
    """
    normalized = normalize_coaching_topic(topic)
    return _read_utf8(_STAGES_DIR / f"{normalized}.md")
