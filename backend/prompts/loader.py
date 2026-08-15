"""UTF-8 prompt-file loader with an in-process immutable cache.

Stage IDs come from ``backend.student_journey.STAGE_BY_ID`` so the prompt
package cannot drift from the five Thinking Path stages. Unknown stages raise;
there is no silent fallback to another stage file.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from backend.student_journey import STAGE_BY_ID

_PROMPTS_ROOT = Path(__file__).resolve().parent
_SHARED_PATH = _PROMPTS_ROOT / "shared" / "coaching.md"
_STAGES_DIR = _PROMPTS_ROOT / "stages"


class PromptLoadError(ValueError):
    """Raised when a prompt file is missing, unexpected, or invalid."""


def _read_utf8(path: Path) -> str:
    """Load a prompt file as UTF-8 text.

    Raises:
        PromptLoadError: When the file is missing or not valid UTF-8.
    """
    try:
        return path.read_text(encoding="utf-8")
    except FileNotFoundError as error:
        raise PromptLoadError(f"Prompt file not found: {path}") from error
    except UnicodeDecodeError as error:
        raise PromptLoadError(f"Prompt file is not valid UTF-8: {path}") from error


def validate_stage_prompt_files(*, stages_dir: Path | None = None) -> None:
    """Require an exact one-to-one map of stage IDs to ``*.md`` files.

    Every ``STAGE_BY_ID`` key must have ``{stage_id}.md``. Extra typo files in
    the stages directory are rejected so they cannot be silently selected.

    Raises:
        PromptLoadError: When the on-disk set does not match stage IDs exactly.
    """
    directory = stages_dir or _STAGES_DIR
    if not directory.is_dir():
        raise PromptLoadError(f"Stage prompt directory missing: {directory}")
    expected = {f"{stage_id}.md" for stage_id in STAGE_BY_ID}
    actual = {path.name for path in directory.glob("*.md")}
    missing = sorted(expected - actual)
    extra = sorted(actual - expected)
    if missing or extra:
        parts: list[str] = []
        if missing:
            parts.append(f"missing stage prompt files: {', '.join(missing)}")
        if extra:
            parts.append(f"unexpected stage prompt files: {', '.join(extra)}")
        raise PromptLoadError("; ".join(parts))


@lru_cache(maxsize=1)
def load_shared_prompt() -> str:
    """Return the shared coaching instructions (cached, immutable string).

    Returns:
        Shared coach behaviour text from ``shared/coaching.md``.
    """
    text = _read_utf8(_SHARED_PATH).strip()
    if not text:
        raise PromptLoadError(f"Shared coaching prompt is empty: {_SHARED_PATH}")
    return text


@lru_cache(maxsize=16)
def load_stage_prompt(stage_id: str) -> str:
    """Return stage-specific coaching instructions for a known stage ID.

    Args:
        stage_id: Thinking Path stage identifier from ``STAGE_BY_ID``.

    Returns:
        Stage instruction text for that stage only.

    Raises:
        PromptLoadError: When the stage ID is unknown or the file is invalid.
    """
    normalized = str(stage_id or "").strip().lower()
    if normalized not in STAGE_BY_ID:
        known = ", ".join(sorted(STAGE_BY_ID))
        raise PromptLoadError(
            f"Unknown Thinking Path stage for prompts: {stage_id!r}. "
            f"Expected one of: {known}"
        )
    validate_stage_prompt_files()
    path = _STAGES_DIR / f"{normalized}.md"
    text = _read_utf8(path).strip()
    if not text:
        raise PromptLoadError(f"Stage prompt is empty: {path}")
    return text


def clear_prompt_cache() -> None:
    """Clear the in-process prompt cache (tests and hot-reload helpers only)."""
    load_shared_prompt.cache_clear()
    load_stage_prompt.cache_clear()
