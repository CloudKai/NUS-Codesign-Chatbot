"""Deterministic confirmed-milestone recaps: bounded, deduplicated, stage-bound.

Recaps are persisted data bound to the confirmed transition. They never award
completion or advance a stage — only the confirmation flow does — and
rebuilding or reloading can never duplicate one.
"""

from backend.domain import (
    EducationalAssessment,
    PendingPhaseTransition,
    StageDecision,
)
from backend.learning.recaps import (
    MilestoneRecap,
    build_milestone_recap,
    merge_milestone_recaps,
)


def _pending(**assessment_overrides) -> PendingPhaseTransition:
    assessment = EducationalAssessment(
        current_stage='problem_identification',
        contribution_summary='Named the unsafe peak-hour crossing and the affected residents.',
        understanding_change='Moved from a vague complaint to a specific safety need.',
        missing_reasoning_elements=['Who else is affected?', 'What does safer mean?', 'Cost?', 'Time?'],
        recommendation=StageDecision.ADVANCE,
        recommendation_rationale='The problem statement is concrete enough to design against.',
        **assessment_overrides,
    )
    return PendingPhaseTransition(
        id='tr-1', thread_id='nb1', from_stage='problem_identification',
        to_stage='concept_generation', assessment=assessment, created_at='2026-11-25T00:00:00Z',
    )


def _messages() -> list[dict]:
    return [
        {'id': 'm1', 'role': 'user', 'content': 'Students cross the road unsafely at peak hours.',
         'metadata': {'thinking_stage': 'problem_identification',
                      'interaction_intent': 'project_coaching'}},
        {'id': 'm2', 'role': 'user', 'content': 'What is an analogy?',
         'metadata': {'thinking_stage': 'problem_identification',
                      'interaction_intent': 'lecture_help'}},
        {'id': 'm3', 'role': 'assistant', 'content': 'Coaching reply',
         'metadata': {'thinking_stage': 'problem_identification'}},
    ]


def test_recap_is_built_deterministically_from_the_saved_confirmation() -> None:
    """One confirmed milestone yields exactly one bounded recap from saved data."""
    first = build_milestone_recap(_pending(), messages=_messages(), confirmed_at='2026-11-25T01:00:00Z')
    second = build_milestone_recap(_pending(), messages=_messages(), confirmed_at='2026-11-25T01:00:00Z')
    assert first == second  # deterministic: no model call, no timestamps beyond the passed one
    assert first is not None
    assert first.stage_id == 'problem_identification'
    assert first.stage_label == 'Problem identification'
    assert first.transition_id == 'tr-1'
    assert first.next_stage_id == 'concept_generation'
    assert first.next_action == ('Describe two different concepts and compare how each '
                                 'addresses the need.')
    assert first.accomplishments.startswith('Named the unsafe peak-hour crossing')
    assert first.changes.startswith('Moved from a vague complaint')
    # Gaps reuse the saved assessment; the list is bounded and ordered.
    assert first.gaps == ['Who else is affected?', 'What does safer mean?', 'Cost?']
    # Relevant work is the student's own saved stage work; lecture help is excluded.
    assert [(work.message_id, work.preview) for work in first.relevant_work] == [
        ('m1', 'Students cross the road unsafely at peak hours.')]


def test_recaps_deduplicate_by_stage_and_stay_bounded() -> None:
    """Reconfirming a stage replaces its recap; reloads and repeats never duplicate."""
    recap = build_milestone_recap(_pending(), messages=[], confirmed_at='2026-11-25T01:00:00Z')
    assert recap is not None
    merged = merge_milestone_recaps([], recap)
    assert merged == [recap]
    again = build_milestone_recap(_pending(), messages=[], confirmed_at='2026-11-25T02:00:00Z')
    assert again is not None
    replaced = merge_milestone_recaps(merged, again)
    assert [entry.stage_id for entry in replaced] == ['problem_identification']
    assert replaced[0].confirmed_at == '2026-11-25T02:00:00Z'
    # A different stage's recap is kept, and the list never grows unbounded.
    other = build_milestone_recap(
        _pending().model_copy(update={'id': 'tr-2', 'from_stage': 'concept_generation',
                                      'to_stage': 'design_specification'}),
        messages=[], confirmed_at='2026-11-25T03:00:00Z')
    assert other is not None
    both = merge_milestone_recaps(replaced, other)
    assert [entry.stage_id for entry in both] == ['concept_generation', 'problem_identification']
    # Distinct confirmed stages accumulate; a bounded history caps the list.
    for count in range(15):
        extra = MilestoneRecap(
            id=f'recap-extra-{count}', stage_id=f'stage-{count}', stage_label='Stage',
            transition_id=f'tr-extra-{count}', next_stage_id='reflection',
            next_stage_label='Reflection', next_action='Reflect on your work.',
            confirmed_at='2026-11-25T04:00:00Z')
        both = merge_milestone_recaps(both, extra)
    assert len(both) == 10
    # Hostile or malformed saved entries are dropped, never raised.
    assert [entry.stage_id for entry in merge_milestone_recaps(
        [{'stage_id': 'nonsense'}], recap)] == ['problem_identification']


def test_no_recap_is_built_without_a_real_confirmed_advance() -> None:
    """Recaps bind to real confirmations only; a same-stage target builds nothing."""
    from backend.learning.recaps import MAX_STAGE_RECAPS
    assert MAX_STAGE_RECAPS == 10
    stale = _pending().model_copy(update={'to_stage': 'problem_identification'})
    assert build_milestone_recap(stale, messages=[], confirmed_at='2026-11-25T01:00:00Z') is None
