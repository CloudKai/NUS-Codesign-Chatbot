"""Read-only project resumption from canonical saved work; never invokes a model."""
from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any, Literal

from pydantic import BaseModel, Field

from backend.student_journey import THINKING_STAGES, normalize_journey
from backend.learning.requirements import stage_criteria


class SavedContribution(BaseModel):
    """Exact active transcript text with its original message identifier."""

    message_id: str
    text: str


class StageResume(BaseModel):
    """Authored work, separately attributed feedback, and a deterministic action."""

    stage_id: str
    artifact_label: str
    completed: bool
    student_work: list[SavedContribution] = Field(default_factory=list)
    feedback: list[SavedContribution] = Field(default_factory=list)
    coach_summary: str = ''
    decision: Literal['', 'pending', 'confirmed', 'rejected'] = ''
    next_action: str
    criteria: list[str] = Field(default_factory=list)


class ProjectResume(BaseModel):
    """Notebook resume projection; legacy unclassified text stays in the transcript."""

    current_stage: str
    stages: list[StageResume]


_STAGE_WORK = {
    'problem_identification': ('Working problem statement', 'Describe the affected people, their context, and the outcome they need.'),
    'concept_generation': ('Alternatives and reasons', 'Describe two different concepts and compare how each addresses the need.'),
    'design_specification': ('Requirements and tests', 'Choose one requirement, explain its rationale, and describe how you would test it.'),
    'deep_analysis': ('Stakeholders and trade-offs', 'Identify one possible harm, who could be affected, and a mitigation to examine.'),
    'reflection': ('Changes in your reasoning', 'Explain one change in your thinking, the evidence behind it, and what remains uncertain.'),
}


def project_resume(
    metadata: Mapping[str, Any], messages: Sequence[Mapping[str, Any]],
) -> ProjectResume:
    """Project exact stage-tagged contributions and saved decisions without writes.

    Inputs must be the owned notebook and its active conversation revision.
    Untagged legacy rows are not guessed into a stage. Lecture help is excluded;
    the complete historical conversation and Review remain available unchanged.
    """
    raw_journey = metadata.get('learning_journey')
    if not isinstance(raw_journey, dict):
        raw_journey = {'current_stage': metadata.get('thinking_stage')}
    journey = normalize_journey(raw_journey)
    stages = []
    for stage in THINKING_STAGES:
        label, action = _STAGE_WORK[stage.id]
        view = StageResume(
            stage_id=stage.id, artifact_label=label,
            completed=stage.id in journey['completed_stages'],
            coach_summary=str(journey['stage_notes'].get(stage.id) or ''),
            next_action=action, criteria=list(stage_criteria(stage.id)),
        )
        for row in messages:
            meta = row.get('metadata') or {}
            if not isinstance(meta, Mapping) or meta.get('thinking_stage') != stage.id:
                continue
            if meta.get('interaction_intent') in {'lecture_help', 'improve_design'}:
                continue
            text = str(row.get('content') or '')
            if not text.strip():
                continue
            item = SavedContribution(message_id=str(row.get('id') or ''), text=text)
            if row.get('role') == 'user':
                view.student_work.append(item)
            elif row.get('role') == 'assistant' and not meta.get('kind'):
                assessment = meta.get('assessment') or {}
                if isinstance(assessment, Mapping) and assessment.get('response_mode') == 'qa':
                    continue
                view.feedback.append(item)
                status = str(meta.get('decision_status') or '')
                if status == 'pending':
                    view.decision = 'pending'
                elif status == 'confirmed':
                    view.decision = 'confirmed'
                elif status == 'rejected':
                    view.decision = 'rejected'
        if view.decision == 'pending':
            view.next_action = 'Review the saved recommendation, then choose Confirm next stage or Stay here.'
        elif view.completed:
            view.next_action = f'Refine your {label.lower()} using new evidence, or return to an unlocked stage.'
        stages.append(view)
    return ProjectResume(current_stage=journey['current_stage'], stages=stages)
