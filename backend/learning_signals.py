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
    """Aggregate activity and feedback by mode with identity and coverage limitations."""

    lecture_help: dict[str, FunnelCount]
    improve_design: dict[str, FunnelCount] = {}
    project_work: dict[str, FunnelCount]
    engagement: dict[str, FunnelCount] = {}
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

    feedback_answers: dict[str, list[dict[str, Any]]] = {'lecture_help': [], 'improve_design': []}
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
    notebooks_with_turns: set[str] = set()
    notebooks_with_errors: set[str] = set()
    notebook_stage_indexes: dict[str, set[int]] = {}
    artifact_notebooks: set[str] = set()
    canvas_notebooks: set[str] = set()
    review_notebooks: set[str] = set()
    artifact_saves_by_notebook: dict[str, int] = {}
    canvas_saves_by_notebook: dict[str, int] = {}
    turns_by_intent = {'project_coaching': 0, 'lecture_help': 0, 'improve_design': 0}
    unknown = 0
    for row in rows:
        owner, notebook = str(row['user_id']), str(row['notebook_id'])
        owners.add(owner)
        notebooks.add(notebook)
        # Notebook-level activity attributes ride on every row of that
        # notebook; they are counts only, never titles, documents or review
        # identifiers. Save counts are keyed per notebook because every
        # message row repeats them.
        if int(row.get('artifact_count') or 0):
            artifact_notebooks.add(notebook)
        artifact_saves_by_notebook[notebook] = int(row.get('artifact_revision_saves') or 0)
        if int(row.get('canvas_count') or 0):
            canvas_notebooks.add(notebook)
        canvas_saves_by_notebook[notebook] = int(row.get('canvas_revision_saves') or 0)
        review_job = decoded(row.get('notebook_settings_text')).get('deep_review_job')
        if isinstance(review_job, dict) and review_job.get('status'):
            review_notebooks.add(notebook)
        if str(row.get('identifier') or '').startswith('guest:') and not row.get('cognito_sub'):
            guests.add(owner)
        if not row.get('message_id') or row.get('message_is_error'):
            if row.get('message_id') and row.get('message_is_error'):
                notebooks_with_errors.add(notebook)
            continue
        meta = decoded(row.get('message_metadata'))
        stamp = str(row.get('message_created_at') or '')
        intent = meta.get('interaction_intent')
        is_user = row.get('message_role') == 'user'
        if is_user:
            user_days.setdefault(owner, set()).add(stamp[:10])
            notebooks_with_turns.add(notebook)
        if not isinstance(intent, str) or intent not in turns_by_intent:
            unknown += 1
            continue
        if is_user:
            turns_by_intent[intent] += 1
        if intent in feedback_answers:
            if row.get('message_role') == 'assistant' and not meta.get('kind'):
                feedback_answers[intent].append({
                    'owner': owner,
                    'signals': learning_receipts(meta.get('learning_signals')),
                    'cited': has_citations(row.get('cited_source_ids_text')),
                })
            continue
        if row.get('message_role') == 'user':
            if meta.get('thinking_stage') in STAGE_BY_ID:
                project.add(notebook)
                notebook_stage_indexes.setdefault(notebook, set()).add(
                    list(STAGE_BY_ID).index(meta['thinking_stage'])
                )
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
    subsequent = {n for n, at in stage2 if n in confirmed and at > confirmed[n]}
    active_owners = set(user_days)
    returning_students = {o for o, days in user_days.items() if len(days) >= 2}
    progressing = {
        n for n, indexes in notebook_stage_indexes.items()
        if indexes and max(indexes) > min(indexes)
    }

    def count(n: int, d: int, unit: str) -> FunnelCount:
        return FunnelCount(numerator=n, denominator=d, unit=unit)

    def summarize_answers(answers: list[dict[str, Any]]) -> dict[str, FunnelCount]:
        """Count answer receipts and later-day returns for one mode."""
        rated = [a for a in answers if (a['signals'].get('rating') or {}).get('kind') in {'useful', 'not_useful'}]
        useful = [a for a in rated if a['signals']['rating']['kind'] == 'useful']
        useful_owners = {a['owner'] for a in useful}
        returned = {
            a['owner']
            for a in useful
            if any(day > a['signals']['rating']['at'][:10] for day in user_days.get(a['owner'], set()))
        }
        cited = [a for a in answers if a['cited']]
        return {
            'rated_answers': count(len(rated), len(answers), 'answers'),
            'useful_answers': count(len(useful), len(rated), 'answers'),
            'cited_answers': count(len(cited), len(answers), 'answers'),
            'evidence_opened': count(sum(bool(a['signals'].get('evidence_opened')) for a in cited), len(cited), 'answers'),
            'returned_after_useful': count(len(returned), len(useful_owners), 'owner identities'),
        }

    classified_turns = sum(turns_by_intent.values())
    engagement = {
        'returning_students': count(len(returning_students), len(active_owners), 'owner identities'),
        'stage_progression': count(len(progressing), len(project), 'notebooks'),
        'artifacts_authored': count(len(artifact_notebooks), len(notebooks), 'notebooks'),
        'artifact_revisions_saved': count(sum(artifact_saves_by_notebook.values()), len(artifact_notebooks), 'saved revisions'),
        'canvases_explored': count(len(canvas_notebooks), len(notebooks), 'notebooks'),
        'canvas_revisions_saved': count(sum(canvas_saves_by_notebook.values()), len(canvas_notebooks), 'saved revisions'),
        'coaching_turns': count(turns_by_intent['project_coaching'], classified_turns, 'student turns'),
        'lecture_help_turns': count(turns_by_intent['lecture_help'], classified_turns, 'student turns'),
        'improve_design_turns': count(turns_by_intent['improve_design'], classified_turns, 'student turns'),
        'deep_reviews': count(len(review_notebooks), len(notebooks), 'notebooks'),
        'notebooks_without_saved_turns': count(len(notebooks - notebooks_with_turns), len(notebooks), 'notebooks'),
        'notebooks_with_saved_errors': count(len(notebooks_with_errors), len(notebooks), 'notebooks'),
    }
    engagement_definitions = {
        'returning_students': 'Owners with saved student turns on two or more distinct UTC days / owners with at least one saved student turn. Return activity, not retention or learning gain.',
        'stage_progression': 'Notebooks whose stage-tagged student turns span a forward stage move / notebooks with a stage-tagged project student contribution. Stage movement is recorded activity, never assessed quality.',
        'artifacts_authored': 'Notebooks with at least one saved artifact / all notebooks. Authorship activity only; artifact content is never exposed.',
        'artifact_revisions_saved': 'Saved artifact revision saves beyond initial creation / notebooks with at least one artifact. Save volume is not quality.',
        'canvases_explored': 'Notebooks with at least one saved canvas / all notebooks. Exploration activity only; canvas content is never exposed.',
        'canvas_revisions_saved': 'Saved canvas revision saves beyond initial creation / notebooks with at least one canvas. Save volume is not quality.',
        'coaching_turns': 'Saved project-coaching student turns / classified saved student turns.',
        'lecture_help_turns': 'Saved historical Lecture help student turns / classified saved student turns.',
        'improve_design_turns': 'Saved Improve my design student turns / classified saved student turns.',
        'deep_reviews': 'Notebooks with a recorded Deep Review job in any state / all notebooks. A requested review is activity; the review judgement itself stays in authorized Research.',
        'notebooks_without_saved_turns': 'Notebooks without a saved non-error student turn / all notebooks. Silence is unknown, not disengagement.',
        'notebooks_with_saved_errors': 'Notebooks with a saved error message / all notebooks. Errors are recorded activity signals, not fault attribution.',
    }

    return LearningFunnel(
        lecture_help=summarize_answers(feedback_answers['lecture_help']),
        improve_design=summarize_answers(feedback_answers['improve_design']),
        project_work={
            'framing_recognized': count(len(framed & project), len(project), 'notebooks'),
            'recommendation_displayed': count(len(displayed & recommendations), len(recommendations), 'notebooks'),
            'confirmed': count(len(confirmed), len(recommendations), 'notebooks'),
            'subsequent_stage2_contribution': count(len(subsequent), len(confirmed), 'notebooks'),
            'stage2_saved_turn_participation': count(len({n for n, _ in stage2} & project), len(project), 'notebooks'),
        },
        engagement=engagement,
        identities={'owners': len(owners), 'guest_owners': len(guests), 'registered_owners': len(owners - guests), 'notebooks': len(notebooks), 'unclassified_messages': unknown},
        definitions={
            'rated_answers': 'Rated answers / all classified saved answers in this mode.',
            'useful_answers': 'Currently useful answers / rated answers in this mode.',
            'cited_answers': 'Cited answers / all classified saved answers in this mode.',
            'evidence_opened': 'Cited answers with a citation-action receipt / cited answers in this mode.',
            'returned_after_useful': 'Owners with a saved student turn on a later UTC day after a current useful rating / owners with a currently useful answer in this mode.',
            'framing_recognized': 'Project starter notebooks with a model recommendation to Concept generation / notebooks with a stage-tagged project student contribution.',
            'recommendation_displayed': 'Notebooks with explicitly opened Concept-generation recommendation details / notebooks with a saved Concept-generation recommendation.',
            'confirmed': 'Notebooks with an explicit confirmation (excluding automatic moves) / notebooks with a saved Concept-generation recommendation.',
            'subsequent_stage2_contribution': 'Notebooks with a saved Concept-generation student turn after confirmation (unreviewed proxy) / explicitly confirmed notebooks.',
            'stage2_saved_turn_participation': 'Project starter notebooks with a saved Concept-generation student turn (unreviewed proxy) / all project starter notebooks.',
            'human_reviewed_substantive_stage2_notebooks': 'Unknown: this snapshot does not assess substance. Use authorized Research review; saved turns, rubric codes and stage moves cannot substitute for this judgement.',
            **engagement_definitions,
        },
        limitations=[
            'All-time active conversation branch only; revised-away or deleted work is excluded. Historical UI receipts are unknown, not zero exposure.',
            'Guest cookies and multiple notebooks can duplicate people. Owners are not distinct students; identities are never silently linked.',
            'Return means a saved student turn on a later UTC day after a useful rating; it is not a visit, retention or learning gain.',
            'Framing is a model recommendation to Concept generation. Saved stage-tagged contributions are not proof of substantive reasoning; use authorized research review.',
            'Displayed means explicitly opened recommendation details (a client receipt), not attention. Evidence opened means citation action, not reading or comprehension. Missing ratings remain unknown.',
            'Engagement counts are activity signals, not evidence of educational quality: artifacts, revisions, canvases, reviews and errors are recorded work events, never assessed substance, and artifact/canvas/review content never leaves the aggregate.',
            '5–8-student formative study pending external participants; no statistical learning or retention claim.',
        ],
    )
