"""Validated structured canvas suggestions: bounded untrusted proposals.

The model may propose canvas nodes or relationships as data. Suggestions are
never executable mutations: they cannot run database operations, change stages
or touch saved work. Only the student's explicit acceptance — the ordinary
authorized revision-guarded canvas save — writes anything, and the client
revalidates against the current revision at accept time.

Server-owned identity and bounds live here so every provider path (mock and
live) produces the same public contract.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from backend.persistence.store.operations.canvases import (
    CANVAS_NODE_KINDS,
    CANVAS_RELATIONS,
)

# At most five proposals per turn: bounded context, bounded cards.
MAX_CANVAS_SUGGESTIONS = 5

_ID_PATTERN = r"^sg-[A-Za-z0-9][A-Za-z0-9._:-]{3,63}$"


class CanvasSuggestion(BaseModel):
    """One validated proposal for the student's Design Canvas.

    ``base_canvas_revision`` is server-stamped from the canvas snapshot the
    coaching context was resolved from; the model never supplies it. Target
    node ids for ``new_edge`` proposals are untrusted text — they are checked
    against the real graph only at acceptance, by the ordinary canvas save.
    """

    model_config = ConfigDict(extra="ignore")

    id: str = Field(min_length=4, max_length=64, pattern=_ID_PATTERN)
    kind: Literal["new_node", "new_edge"]
    node_kind: str | None = Field(default=None, max_length=32)
    title: str = Field(default="", max_length=200)
    description: str = Field(default="", max_length=2_000)
    relation: str | None = Field(default=None, max_length=32)
    source_node_id: str | None = Field(default=None, max_length=64)
    target_node_id: str | None = Field(default=None, max_length=64)
    explanation: str = Field(default="", max_length=500)
    rationale: str = Field(min_length=1, max_length=500)
    # Server-stamped snapshot identity; the model never supplies either value.
    base_canvas_id: str | None = Field(default=None, max_length=64)
    base_canvas_revision: int | None = Field(default=None, ge=1)


def _valid(item: CanvasSuggestion) -> bool:
    """Apply kind-specific allowlists beyond the schema-level bounds."""
    if item.kind == "new_node":
        return item.node_kind in CANVAS_NODE_KINDS and bool(item.title.strip())
    return (
        item.relation in CANVAS_RELATIONS
        and bool(item.source_node_id)
        and bool(item.target_node_id)
    )


def bounded_canvas_suggestions(
    items: Any, *, origin_canvas_id: str | None = None,
    origin_revision: int | None = None,
) -> list[CanvasSuggestion]:
    """Validate provider proposals into at most five public suggestions.

    Hostile or malformed entries are dropped silently — a bad proposal must
    never fail the coaching turn. Duplicate ids collapse to the first entry so
    one stable identity cannot apply twice. ``origin_revision`` is the
    authoritative server-resolved base revision and overwrites anything a
    model claimed.
    """
    if not isinstance(items, list):
        return []
    suggestions: list[CanvasSuggestion] = []
    seen: set[str] = set()
    for raw in items:
        if len(suggestions) >= MAX_CANVAS_SUGGESTIONS:
            break
        try:
            candidate = CanvasSuggestion.model_validate(raw)
        except (TypeError, ValueError):
            continue
        if not _valid(candidate) or candidate.id in seen:
            continue
        seen.add(candidate.id)
        suggestions.append(
            candidate.model_copy(
                update={
                    "base_canvas_revision": origin_revision,
                    "base_canvas_id": origin_canvas_id,
                }
            )
        )
    return suggestions
