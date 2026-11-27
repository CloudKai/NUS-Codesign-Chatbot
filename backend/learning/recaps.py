"""Deterministic confirmed-milestone recaps bound to real confirmations.

A recap is persisted data describing what the student accomplished when a
stage confirmation was accepted. It reuses validated saved assessment fields
and the student's own saved stage work; there is no model call and no new
stage authority — recaps never complete or advance a stage. One recap exists
per confirmed Thinking Path stage, so repeated confirmations of the same
stage replace it and reloads can never duplicate it.
"""

from __future__ import annotations

import hashlib
from collections.abc import Mapping, Sequence
from typing import Any

from pydantic import BaseModel, Field

from backend.domain import PendingPhaseTransition
from backend.learning.stages import THINKING_STAGES

# One recap per confirmed stage, newest first, bounded history.
MAX_STAGE_RECAPS = 10
_TEXT_MAX = 600
_PREVIEW_MAX = 200

_STAGE_LABELS = {stage.id: stage.label for stage in THINKING_STAGES}


def next_stage_action(stage_id: str) -> str:
    """The deterministic authored prompt for one Thinking Path stage."""
    from backend.learning.resume import _STAGE_WORK

    return _STAGE_WORK.get(stage_id, ('', ''))[1]


class RecapWork(BaseModel):
    """One bounded pointer at the student's own saved stage contribution."""

    message_id: str = Field(min_length=1, max_length=128)
    preview: str = Field(min_length=1, max_length=_PREVIEW_MAX)


class MilestoneRecap(BaseModel):
    """One persisted recap of a confirmed educational milestone.

    Every field is derived server-side from the confirmed transition, the
    saved assessment and saved student work. ``id`` is content-derived from
    the transition so duplicate confirmation is detectable.
    """

    id: str = Field(min_length=4, max_length=64)
    stage_id: str = Field(min_length=1, max_length=64)
    stage_label: str = Field(min_length=1, max_length=200)
    transition_id: str = Field(min_length=1, max_length=128)
    next_stage_id: str = Field(min_length=1, max_length=64)
    next_stage_label: str = Field(min_length=1, max_length=200)
    next_action: str = Field(min_length=1, max_length=_TEXT_MAX)
    accomplishments: str = Field(default='', max_length=_TEXT_MAX)
    changes: str = Field(default='', max_length=_TEXT_MAX)
    gaps: list[str] = Field(default_factory=list, max_length=3)
    relevant_work: list[RecapWork] = Field(default_factory=list, max_length=2)
    confirmed_at: str = Field(min_length=1, max_length=64)


def build_milestone_recap(pending: PendingPhaseTransition, *, messages: Sequence[Mapping[str, Any]],
                          confirmed_at: str) -> MilestoneRecap | None:
    """Build one recap from a confirmed transition and saved data, or None.

    Only a real advance to a different stage is a milestone: a same-stage
    target builds nothing. Gaps reuse the saved assessment's missing
    reasoning elements; relevant work is the student's own saved stage-tagged
    contributions (lecture help excluded), most recent first.
    """
    stage_id = pending.from_stage
    next_stage_id = pending.to_stage
    if next_stage_id == stage_id or next_stage_id not in _STAGE_LABELS \
            or stage_id not in _STAGE_LABELS:
        return None
    assessment = pending.assessment
    gaps = [str(item).strip()[:_PREVIEW_MAX] for item in assessment.missing_reasoning_elements[:3]
            if str(item).strip()]
    relevant_work: list[RecapWork] = []
    for row in reversed(list(messages)):
        meta = row.get('metadata') or {}
        if not isinstance(meta, Mapping) or meta.get('thinking_stage') != stage_id:
            continue
        if meta.get('interaction_intent') in {'lecture_help', 'improve_design'} or row.get('role') != 'user':
            continue
        preview = ' '.join(str(row.get('content') or '').split())[:_PREVIEW_MAX]
        if not preview:
            continue
        relevant_work.append(RecapWork(message_id=str(row.get('id') or '')[:128], preview=preview))
        if len(relevant_work) == 2:
            break
    changes = (assessment.understanding_change or assessment.working_conclusion or '').strip()
    return MilestoneRecap(
        id='recap-' + hashlib.sha1(pending.id.encode('utf-8')).hexdigest()[:16],
        stage_id=stage_id,
        stage_label=_STAGE_LABELS[stage_id],
        transition_id=pending.id,
        next_stage_id=next_stage_id,
        next_stage_label=_STAGE_LABELS[next_stage_id],
        next_action=next_stage_action(next_stage_id)[:_TEXT_MAX],
        accomplishments=assessment.contribution_summary.strip()[:_TEXT_MAX],
        changes=changes[:_TEXT_MAX],
        gaps=gaps,
        relevant_work=relevant_work,
        confirmed_at=confirmed_at[:64],
    )


def merge_milestone_recaps(existing: Any, recap: MilestoneRecap) -> list[MilestoneRecap]:
    """Merge one new recap into the saved list: one per stage, newest first.

    Malformed or hostile saved entries are dropped silently; an entry for the
    recap's stage is replaced, so repeated confirmations and reloads never
    duplicate a recap.
    """
    validated: list[MilestoneRecap] = []
    if isinstance(existing, list):
        for raw in existing:
            try:
                validated.append(MilestoneRecap.model_validate(raw))
            except (TypeError, ValueError):
                continue
    kept = [entry for entry in validated if entry.stage_id != recap.stage_id]
    return [recap, *kept][:MAX_STAGE_RECAPS]
