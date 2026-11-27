"""Validated canvas-to-artifact draft proposals: one reviewable synthesis per turn.

The model may synthesize the student's selected saved nodes into draft text as
data. Proposals are never executable mutations: they cannot create artifacts,
change stages or touch saved work. Only the student's explicit confirmation —
the ordinary authorized artifact create, which always makes a new artifact —
writes anything.
"""

from __future__ import annotations

import hashlib
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

# Node ids, the canvas snapshot and provenance are server-stamped; the model
# supplies only the title, draft text and rationale.
_DRAFT_TITLE_MAX = 200
_DRAFT_TEXT_MAX = 8_000


class CanvasDraftProposal(BaseModel):
    """One reviewable synthesized draft from the student's selected canvas nodes."""

    model_config = ConfigDict(extra="ignore")

    id: str = Field(min_length=4, max_length=64)
    title: str = Field(min_length=1, max_length=_DRAFT_TITLE_MAX)
    draft_text: str = Field(min_length=1, max_length=_DRAFT_TEXT_MAX)
    rationale: str = Field(default="", max_length=500)
    # Server-stamped origin. The student confirms against the current canvas.
    base_canvas_id: str | None = Field(default=None, max_length=64)
    base_canvas_revision: int | None = Field(default=None, ge=1)
    node_ids: list[str] = Field(default_factory=list, max_length=5)
    provenance: Literal["coach"] = "coach"


def bounded_canvas_draft(
    raw: Any, *, canvas_id: str | None = None, revision: int | None = None,
    node_ids: list[str] | None = None,
) -> CanvasDraftProposal | None:
    """Validate one provider draft against the server-resolved canvas origin.

    Malformed or hostile proposals are dropped silently — a bad draft must
    never fail the coaching turn. Without a resolved canvas origin (or with no
    contributing nodes) nothing survives at all, and any model-supplied node
    list is ignored in favor of the server-resolved selection.
    """
    if not isinstance(raw, dict) or canvas_id is None or not node_ids:
        return None
    payload = dict(raw)
    payload.pop("node_ids", None)  # the server-resolved selection decides
    payload.pop("base_canvas_id", None)
    payload.pop("base_canvas_revision", None)
    payload.pop("provenance", None)
    if not isinstance(payload.get("id"), str) or not payload["id"].strip():
        # A live-model proposal carries no stable identity: synthesize one
        # from the proposed content so duplicate confirmation is detectable.
        digest = hashlib.sha1(
            f"{payload.get('title') or ''}\n{payload.get('draft_text') or ''}".encode("utf-8")
        ).hexdigest()[:12]
        payload["id"] = f"cd-srv-{digest}"
    try:
        candidate = CanvasDraftProposal.model_validate(payload)
    except (TypeError, ValueError):
        return None
    return candidate.model_copy(update={
        "base_canvas_id": canvas_id,
        "base_canvas_revision": revision,
        "node_ids": list(node_ids)[:5],
        "provenance": "coach",
    })
