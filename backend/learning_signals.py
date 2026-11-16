"""Content-free student receipts and transparent active-branch funnel projections."""

from __future__ import annotations

import json
from typing import Any, Literal

from pydantic import AwareDatetime, BaseModel, ConfigDict, ValidationError

from backend.student_journey import STAGE_BY_ID


class LearningSignal(BaseModel):
    """One explicit rating or UI receipt; free text and client timestamps are forbidden."""

    model_config = ConfigDict(extra="forbid")
    kind: Literal["useful", "not_useful", "evidence_opened", "recommendation_displayed"]


class FunnelCount(BaseModel):
    """A numerator and its eligible population, never an inferred learning score."""

    numerator: int
    denominator: int
    unit: str


class AnswerRating(BaseModel):
    """Explicit usefulness judgement with its server-issued aware timestamp."""

    kind: Literal['useful', 'not_useful']
    at: AwareDatetime


class LearningReceipts(BaseModel):
    """Bounded persisted receipt namespace; absent fields mean unobserved."""

    rating: AnswerRating | None = None
    evidence_opened: AwareDatetime | None = None
    recommendation_displayed: AwareDatetime | None = None


class LearningSignalSaved(BaseModel):
    """Acknowledgement and canonical receipts after a successful commit."""

    saved: Literal[True] = True
    signals: LearningReceipts


def learning_receipts(value: Any) -> dict[str, Any]:
    """Normalize persisted/imported receipts; invalid fields remain unknown.

    This never invents timestamps or counts a partial imported rating. Answers
    remain readable even if the optional measurement namespace is malformed.
    """
    if not isinstance(value, dict):
        return {}
    receipts: dict[str, Any] = {}
    for field in LearningReceipts.model_fields:
        if field not in value:
            continue
        try:
            parsed = LearningReceipts.model_validate({field: value[field]})
        except ValidationError:
            continue
        receipts.update(parsed.model_dump(mode='json', exclude_none=True))
    return receipts


class LearningFunnel(BaseModel):
    """Aggregate lecture and project measures with identity and coverage limitations."""

    lecture_help: dict[str, FunnelCount]
    project_work: dict[str, FunnelCount]
    identities: dict[str, int]
    definitions: dict[str, str]
    human_reviewed_substantive_stage2_notebooks: int | None = None
    limitations: list[str]


def learning_funnel(rows: list[dict[str, Any]]) -> LearningFunnel:
    """Aggregate metadata-only active messages; unclassified legacy work stays unknown.

    Receipts deduplicate per answer. Returns require a later UTC calendar day
    after the explicit useful rating, within the same owner identity. Project
    contributions are saved stage-tagged student turns, not assessed quality.
    """
    def decoded(value: Any) -> dict[str, Any]:
        try:
            parsed = json.loads(value or "{}") if isinstance(value, str) else value
        except (ValueError, TypeError):
            return {}
        return parsed if isinstance(parsed, dict) else {}

    def has_citations(value: Any) -> bool:
        try:
            parsed = json.loads(value or '[]') if isinstance(value, str) else value
        except (ValueError, TypeError):
            return False
        return isinstance(parsed, list) and bool(parsed)

    lecture: list[dict[str, Any]] = []
    project: set[str] = set()
    framed: set[str] = set()
    recommendations: set[str] = set()
    displayed: set[str] = set()
    confirmed: dict[str, str] = {}
    stage2: list[tuple[str, str]] = []
    user_days: dict[str, set[str]] = {}
    guests: set[str] = set()
    owners: set[str] = set()
    notebooks: set[str] = set()
    unknown = 0
    for row in rows:
        owner, notebook = str(row['user_id']), str(row['notebook_id'])
        owners.add(owner)
        notebooks.add(notebook)
        if str(row.get('identifier') or '').startswith('guest:') and not row.get('cognito_sub'):
            guests.add(owner)
        if not row.get('message_id') or row.get('message_is_error'):
            continue
        meta = decoded(row.get('message_metadata'))
        stamp = str(row.get('message_created_at') or '')
        if row.get('message_role') == 'user':
            user_days.setdefault(owner, set()).add(stamp[:10])
        intent = meta.get('interaction_intent')
        if intent not in {'lecture_help', 'project_coaching'}:
            unknown += 1
            continue
        if intent == 'lecture_help':
            if row.get('message_role') == 'assistant' and not meta.get('kind'):
                lecture.append({'owner': owner, 'signals': learning_receipts(meta.get('learning_signals')),
                                'cited': has_citations(row.get('cited_source_ids_text'))})
            continue
        if row.get('message_role') == 'user':
            if meta.get('thinking_stage') in STAGE_BY_ID:
                project.add(notebook)
            if meta.get('thinking_stage') == 'concept_generation':
                stage2.append((notebook, stamp))
        if row.get('message_role') != 'assistant':
            continue
        signals = learning_receipts(meta.get('learning_signals'))
        if row.get('proposed_stage') == 'concept_generation':
            recommendations.add(notebook)
            # Recognition is a model proposal, never an independent judgement.
            framed.add(notebook)
            if signals.get('recommendation_displayed'):
                displayed.add(notebook)
            if row.get('decision_status') == 'confirmed' and not meta.get('auto_advanced_to'):
                confirmed[notebook] = min(confirmed.get(notebook, '9999'), str(row.get('decision_at') or stamp))
    rated = [a for a in lecture if (a['signals'].get('rating') or {}).get('kind') in {'useful', 'not_useful'}]
    useful = [a for a in rated if a['signals']['rating']['kind'] == 'useful']
    useful_owners = {a['owner'] for a in useful}
    returned = {a['owner'] for a in useful if any(day > a['signals']['rating']['at'][:10] for day in user_days.get(a['owner'], set()))}
    subsequent = {n for n, at in stage2 if n in confirmed and at > confirmed[n]}

    def count(n: int, d: int, unit: str) -> FunnelCount:
        return FunnelCount(numerator=n, denominator=d, unit=unit)

    return LearningFunnel(
        lecture_help={
            'rated_answers': count(len(rated), len(lecture), 'answers'),
            'useful_answers': count(len(useful), len(rated), 'answers'),
            'cited_answers': count(sum(a['cited'] for a in lecture), len(lecture), 'answers'),
            'evidence_opened': count(sum(bool(a['signals'].get('evidence_opened')) for a in lecture if a['cited']), sum(a['cited'] for a in lecture), 'answers'),
            'returned_after_useful': count(len(returned), len(useful_owners), 'owner identities'),
        },
        project_work={
            'framing_recognized': count(len(framed & project), len(project), 'notebooks'),
            'recommendation_displayed': count(len(displayed & recommendations), len(recommendations), 'notebooks'),
            'confirmed': count(len(confirmed), len(recommendations), 'notebooks'),
            'subsequent_stage2_contribution': count(len(subsequent), len(confirmed), 'notebooks'),
            'stage2_saved_turn_participation': count(len({n for n, _ in stage2} & project), len(project), 'notebooks'),
        },
        identities={'owners': len(owners), 'guest_owners': len(guests), 'registered_owners': len(owners - guests), 'notebooks': len(notebooks), 'unclassified_messages': unknown},
        definitions={
            'rated_answers': 'Rated lecture answers / all classified saved lecture answers.',
            'useful_answers': 'Currently useful lecture answers / rated lecture answers.',
            'cited_answers': 'Cited lecture answers / all classified saved lecture answers.',
            'evidence_opened': 'Cited lecture answers with a citation-action receipt / cited lecture answers.',
            'returned_after_useful': 'Owners with a saved student turn on a later UTC day after a current useful rating / owners with a currently useful lecture answer.',
            'framing_recognized': 'Project starter notebooks with a model recommendation to Concept generation / notebooks with a stage-tagged project student contribution.',
            'recommendation_displayed': 'Notebooks with explicitly opened Concept-generation recommendation details / notebooks with a saved Concept-generation recommendation.',
            'confirmed': 'Notebooks with an explicit confirmation (excluding automatic moves) / notebooks with a saved Concept-generation recommendation.',
            'subsequent_stage2_contribution': 'Notebooks with a saved Concept-generation student turn after confirmation (unreviewed proxy) / explicitly confirmed notebooks.',
            'stage2_saved_turn_participation': 'Project starter notebooks with a saved Concept-generation student turn (unreviewed proxy) / all project starter notebooks.',
            'human_reviewed_substantive_stage2_notebooks': 'Unknown: this snapshot does not assess substance. Use authorized Research review; saved turns, rubric codes and stage moves cannot substitute for this judgement.',
        },
        limitations=[
            'All-time active conversation branch only; revised-away or deleted work is excluded. Historical UI receipts are unknown, not zero exposure.',
            'Guest cookies and multiple notebooks can duplicate people. Owners are not distinct students; identities are never silently linked.',
            'Return means a saved student turn on a later UTC day after a useful rating; it is not a visit, retention or learning gain.',
            'Framing is a model recommendation to Concept generation. Saved stage-tagged contributions are not proof of substantive reasoning; use authorized research review.',
            'Displayed means explicitly opened recommendation details (a client receipt), not attention. Evidence opened means citation action, not reading or comprehension. Missing ratings remain unknown.',
            '5–8-student formative study pending external participants; no statistical learning or retention claim.',
        ],
    )
