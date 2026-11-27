"""Validated artifact feedback: one bounded before/after proposal per turn.

The model may propose revised text for the student's artifact as data.
Proposals are never executable mutations: they cannot save documents, change
stages or touch saved work. Only the student's explicit acceptance — the
ordinary authorized revision-guarded artifact update — writes anything, and
the client revalidates against the current revision at accept time.

Server-owned identity and bounds live here so every provider path (mock and
live) produces the same public contract.
"""

from __future__ import annotations

import hashlib
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

# One before/after proposal per turn: a single focused edit the student can
# inspect as a pair.
MAX_ARTIFACT_FEEDBACK = 1

_ID_PATTERN = r"^af-[A-Za-z0-9][A-Za-z0-9._:-]{3,63}$"


class ArtifactFeedback(BaseModel):
    """One validated before/after proposal for the student's artifact.

    ``original_text`` is the server-resolved saved passage (or the whole
    bounded document text when ``paragraph`` is None). ``base_artifact_id``
    and ``base_artifact_revision`` are server-stamped from the snapshot the
    coaching context was resolved from; the model never supplies them.
    """

    model_config = ConfigDict(extra="ignore")

    id: str = Field(min_length=4, max_length=64, pattern=_ID_PATTERN)
    kind: Literal["revise_text"]
    proposed_text: str = Field(min_length=1, max_length=8_000)
    rationale: str = Field(min_length=1, max_length=500)
    base_artifact_id: str | None = Field(default=None, max_length=64)
    base_artifact_revision: int | None = Field(default=None, ge=1)
    paragraph: int | None = Field(default=None, ge=0)
    original_text: str = Field(default="", max_length=4_000)


def bounded_artifact_feedback(
    items: Any, *, origin_artifact_id: str | None = None,
    origin_revision: int | None = None, origin_paragraph: int | None = None,
    origin_original_text: str = "",
) -> list[ArtifactFeedback]:
    """Validate provider proposals into at most one public before/after pair.

    Hostile or malformed entries are dropped silently — a bad proposal must
    never fail the coaching turn. Without a resolved artifact origin nothing
    survives at all.
    """
    if not isinstance(items, list) or origin_artifact_id is None:
        return []
    for raw in items:
        if isinstance(raw, dict) and raw.get("id") is None:
            # A live-model proposal carries no stable identity or kind: the
            # server synthesizes both so duplicate acceptance is detectable.
            # An invalid *supplied* id is hostile and stays dropped.
            raw = dict(raw)
            digest = hashlib.sha1(
                str(raw.get("proposed_text") or "").encode("utf-8")
            ).hexdigest()[:12]
            raw["id"] = f"af-srv-{digest}"
            raw.setdefault("kind", "revise_text")
        try:
            candidate = ArtifactFeedback.model_validate(raw)
        except (TypeError, ValueError):
            continue
        return [candidate.model_copy(update={
            "base_artifact_id": origin_artifact_id,
            "base_artifact_revision": origin_revision,
            "paragraph": origin_paragraph,
            "original_text": origin_original_text[:4_000],
        })]
    return []
