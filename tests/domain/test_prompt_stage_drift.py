"""Drift check for stage prompt files that exist in both prompt copies.

``agentcore_runtime/prompts/stages/`` (deployed AgentCore runtime) and
``backend/prompts/stages/`` (mock, OpenAI, Bedrock Converse) are kept as two
copies on purpose; see ``docs/PROMPT_ARCHITECTURE.md``. The stage files with the
same name must not drift apart silently.

What is pinned:

* The set of same-named stage files is exactly ``SHARED_STAGES``.
* ``problem_identification.md`` is byte-identical in both copies.
* For the other shared files, the file text is compared paragraph by paragraph
  (blank-line separated, whitespace collapsed). Every paragraph in the backend
  copy must also exist in the runtime copy. The only paragraphs allowed to exist
  in the runtime copy alone are the ones listed in ``KNOWN_RUNTIME_ONLY``
  (the CORE FOCUS and READINESS SIGNALS blocks), pinned by SHA-256.
* The shared paragraphs must appear in the same order, except where
  ``KNOWN_REORDERED`` records a known difference (the Facione paragraph in
  ``reflection.md``).

Editing a shared paragraph in only one copy, editing a pinned runtime-only
paragraph, or adding a new divergence fails the test. Editing a shared
paragraph in both copies identically passes. To accept an intended divergence,
update the pinned values below in the same change.
"""

from __future__ import annotations

import hashlib
import re
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[2]
_RUNTIME_STAGES = _REPO_ROOT / "agentcore_runtime" / "prompts" / "stages"
_BACKEND_STAGES = _REPO_ROOT / "backend" / "prompts" / "stages"

SHARED_STAGES = frozenset(
    {
        "concept_generation.md",
        "design_specification.md",
        "problem_identification.md",
        "reflection.md",
    }
)
IDENTICAL_STAGES = frozenset({"problem_identification.md"})

# Runtime-only paragraphs: file -> {first words: first 16 hex chars of SHA-256
# of the whitespace-normalised paragraph}.
KNOWN_RUNTIME_ONLY: dict[str, dict[str, str]] = {
    "concept_generation.md": {
        "CORE FOCUS": "5b26b91f9949f80e",
        "READINESS SIGNALS": "b2db1f9b0187936b",
    },
    "design_specification.md": {
        "CORE FOCUS": "0b446d04c5aa4a59",
        "READINESS SIGNALS": "9bbea1a4ca1b6312",
    },
    "reflection.md": {
        "CORE FOCUS": "ebc7bbece89dc5a0",
        "READINESS SIGNALS": "09a0cb2df91f861d",
    },
}
# Files where shared paragraphs sit in a different order in the two copies.
# reflection.md: the runtime copy places the optional holistic Facione paragraph
# before CORE FOCUS; the backend copy places it at the end of the file.
KNOWN_REORDERED = frozenset({"reflection.md"})


def _paragraphs(path: Path) -> list[str]:
    text = path.read_text(encoding="utf-8")
    blocks = re.split(r"\n\s*\n", text.strip())
    return [" ".join(block.split()) for block in blocks if block.strip()]


def _digest(paragraph: str) -> str:
    return hashlib.sha256(paragraph.encode("utf-8")).hexdigest()[:16]


def test_same_named_stage_files_are_the_known_set() -> None:
    runtime = {p.name for p in _RUNTIME_STAGES.glob("*.md")}
    backend = {p.name for p in _BACKEND_STAGES.glob("*.md")}
    assert runtime & backend == SHARED_STAGES, (
        "The set of stage files present in both prompt copies changed. "
        "Add the new file to SHARED_STAGES (and KNOWN_RUNTIME_ONLY if it differs)."
    )


@pytest.mark.parametrize("name", sorted(IDENTICAL_STAGES))
def test_identical_stage_files_stay_byte_identical(name: str) -> None:
    runtime = (_RUNTIME_STAGES / name).read_bytes()
    backend = (_BACKEND_STAGES / name).read_bytes()
    assert runtime == backend, f"{name} differs between the two prompt copies"


@pytest.mark.parametrize("name", sorted(SHARED_STAGES - IDENTICAL_STAGES))
def test_diverging_stage_files_match_pinned_differences(name: str) -> None:
    runtime = _paragraphs(_RUNTIME_STAGES / name)
    backend = _paragraphs(_BACKEND_STAGES / name)

    backend_only = [p for p in backend if p not in runtime]
    assert backend_only == [], f"{name}: backend paragraphs missing from runtime copy"

    runtime_only = {
        " ".join(p.split()[:2]): _digest(p) for p in runtime if p not in backend
    }
    assert runtime_only == KNOWN_RUNTIME_ONLY[name], (
        f"{name}: runtime-only paragraphs changed. If intended, update "
        "KNOWN_RUNTIME_ONLY in this test."
    )

    common_runtime = [p for p in runtime if p in backend]
    common_backend = [p for p in backend if p in runtime]
    assert sorted(common_runtime) == sorted(common_backend)
    if name in KNOWN_REORDERED:
        assert common_runtime != common_backend, (
            f"{name}: paragraph order now matches; remove it from KNOWN_REORDERED."
        )
    else:
        assert common_runtime == common_backend, f"{name}: shared paragraph order differs"
