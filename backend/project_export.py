"""Bounded, owner-checked selected project export assembly.

The export combines the saved conversation, the student-facing project
projections (summary and Thinking Path) and the student's selected artifacts
and canvases into one portable JSON envelope. It reuses the exact projections
the browser already reads — nothing is re-rendered, re-generated or fetched
from a model. Workspace identifiers, owner identity, operational fields,
internal prompts and hidden reasoning never enter the output; unavailable
references stay explicitly labeled instead of being substituted.
"""

from __future__ import annotations

import json
from typing import Any, Mapping

MAX_EXPORT_ARTIFACTS = 12
MAX_EXPORT_CANVASES = 12
MAX_EXPORT_MESSAGES = 200
MAX_EXPORT_BYTES = 1_048_576
EXPORT_SCHEMA_VERSION = 1
_ID_MAX = 128
_CHAT_TITLE_MAX = 120
_TRANSCRIPT_ROLES = {'user': 'Student', 'assistant': 'Coach'}


class ProjectExportError(ValueError):
    """Raised when a selection is malformed or the assembled export exceeds its bound."""


def selected_ids(raw: str, *, limit: int) -> list[str]:
    """Parse one bounded comma-separated identifier selection; duplicates collapse.

    Args:
        raw: The query-string selection, e.g. ``"id1,id2"``.
        limit: Maximum number of distinct identifiers accepted.

    Returns:
        Distinct bounded identifiers in first-seen order.

    Raises:
        ProjectExportError: When the selection exceeds the limit or any
            identifier is malformed.
    """
    identifiers: list[str] = []
    for piece in (raw or '').split(','):
        identifier = piece.strip()
        if not identifier:
            continue
        if len(identifier) > _ID_MAX or any(character in identifier for character in '/?&#'):
            raise ProjectExportError('Malformed selection identifier')
        if identifier not in identifiers:
            identifiers.append(identifier)
    if len(identifiers) > limit:
        raise ProjectExportError('Too many selected items')
    return identifiers


def _chat_title(message: Mapping[str, Any]) -> str | None:
    """Return one message's bounded, single-line chat title when supplied."""
    raw = message.get('chat_title')
    if raw is None:
        return None
    return ' '.join(str(raw).split())[:_CHAT_TITLE_MAX] or 'Untitled chat'


def _transcript(messages: list[Mapping[str, Any]]) -> dict[str, Any]:
    """Project at most the newest saved messages as the student-readable transcript.

    Mirrors the notebook transcript projection (visible roles only; no
    assessments, research coding or metadata) and labels truncation honestly.
    Messages assembled from a notebook family also carry their chat title, so
    work entered through a child chat stays attributable without exposing ids.
    """
    selected = messages[-MAX_EXPORT_MESSAGES:]
    lines: list[str] = []
    for message in selected:
        label = _TRANSCRIPT_ROLES.get(str(message.get('role') or '').strip().lower())
        content = str(message.get('content') or '').strip()
        if label is None or not content:
            continue
        title = _chat_title(message)
        lines.append(f'{title} — {label}:' if title else f'{label}:')
        lines.append(content)
        lines.append('')
    return {
        'transcript': '\n'.join(lines).rstrip() + '\n',
        'message_count': len(selected),
        'truncated': len(messages) > len(selected),
    }


def _brief(brief_result: Mapping[str, Any] | None) -> dict[str, Any] | None:
    """Return the saved project brief text when it is current; otherwise None."""
    if not brief_result or brief_result.get('status') != 'current':
        return None
    brief = brief_result.get('brief')
    if not isinstance(brief, Mapping):
        return None
    return {key: dict(point or {}) for key, point in brief.items()}


def _summary(review: Mapping[str, Any], recaps: list[Mapping[str, Any]]) -> dict[str, Any]:
    """Project the saved coach summary, feedback and confirmed recaps."""
    return {
        'saved_summary': str(review.get('summary') or ''),
        'strengths': [{'stage_id': entry['stage_id'], 'items': list(entry['items'])}
                      for entry in review.get('strengths') or []],
        'improvements': [{'stage_id': entry['stage_id'], 'items': list(entry['items'])}
                         for entry in review.get('improvements') or []],
        'facione_scores': [{'dimension': entry['dimension'], 'score': entry['score']}
                           for entry in review.get('facione_scores') or []],
        'project_brief': _brief(review.get('project_brief')),
        'recaps': [{
            'stage_label': recap.get('stage_label'), 'accomplishments': recap.get('accomplishments'),
            'changes': recap.get('changes'), 'gaps': list(recap.get('gaps') or []),
            'next_stage_label': recap.get('next_stage_label'), 'next_action': recap.get('next_action'),
        } for recap in recaps],
    }


def _reference(reference: Mapping[str, Any]) -> dict[str, Any]:
    """One labeled evidence reference without internal identifiers.

    The reference keeps its course-facing title (when available), its
    availability label and — for artifact references — the originating
    revision, so an idea's development stays traceable.
    """
    entry: dict[str, Any] = {'kind': str(reference.get('kind')),
                             'available': bool(reference.get('available'))}
    if reference.get('title'):
        entry['title'] = str(reference['title'])
    if reference.get('revision') is not None:
        entry['revision'] = reference['revision']
    return entry


def _artifact(artifact: Mapping[str, Any]) -> dict[str, Any]:
    """One selected artifact with revision metadata, provenance and labeled references."""
    return {
        'title': artifact['title'], 'kind': artifact['kind'],
        'schema_version': artifact['schema_version'], 'revision': artifact['revision'],
        'origin': artifact['origin'], 'created_at': artifact['created_at'],
        'updated_at': artifact['updated_at'], 'document': artifact['document'],
        'references': [_reference(reference) for reference in artifact.get('references') or []],
    }


def _canvas(canvas: Mapping[str, Any]) -> dict[str, Any]:
    """One selected canvas with revision metadata, provenance and the canonical graph."""
    return {
        'title': canvas['title'], 'schema_version': canvas['schema_version'],
        'revision': canvas['revision'], 'origin': canvas['origin'],
        'created_at': canvas['created_at'], 'updated_at': canvas['updated_at'],
        'graph': canvas['graph'],
    }


def build_project_export(*, title: str, project: Mapping[str, Any],
                         messages: list[Mapping[str, Any]],
                         artifacts: list[Mapping[str, Any]],
                         canvases: list[Mapping[str, Any]]) -> dict[str, Any]:
    """Assemble the selected project envelope from saved projections only.

    Args:
        title: The owned notebook's name.
        project: The student-facing ``ReaderProject`` projection (owner and
            thread identifiers are never copied into the envelope).
        messages: Active saved conversation rows, oldest first.
        artifacts: Fully resolved owned artifact rows selected by the student.
        canvases: Owned canvas rows selected by the student.

    Returns:
        The export envelope; :meth:`serialize_project_export` bounds its size.
    """
    review = project.get('review') or {}
    source_references: dict[tuple[str, str], dict[str, Any]] = {}
    exported_artifacts = []
    for artifact in artifacts:
        exported_artifacts.append(_artifact(artifact))
        for reference in artifact.get('references') or []:
            if reference.get('kind') != 'source':
                continue
            available = bool(reference.get('available'))
            reference_title = str(reference.get('title') or '') if available else ''
            key = ('available', reference_title) if available else ('unavailable', '')
            source_references.setdefault(key, {'kind': 'source', **({'title': reference_title}
                                               if available else {}), 'available': available})
    return {
        'kind': 'project_export', 'schema_version': EXPORT_SCHEMA_VERSION,
        'title': title,
        'thinking_path': {
            'current_stage': project.get('current_stage'),
            'stages': [{
                'label': stage.get('label'), 'completed': stage.get('completed'),
                'coach_summary': stage.get('coach_summary'), 'next_action': stage.get('next_action'),
                'student_work': [work.get('text') for work in stage.get('student_work') or []],
            } for stage in project.get('stages') or []],
        },
        'summary': _summary(review, project.get('recaps') or []),
        'conversation': _transcript(messages),
        'artifacts': exported_artifacts,
        'canvases': [_canvas(canvas) for canvas in canvases],
        'source_references': list(source_references.values()),
    }


def serialize_project_export(envelope: Mapping[str, Any]) -> str:
    """Serialize the canonical envelope and fail closed when it exceeds the bound.

    Raises:
        ProjectExportError: When the serialized export exceeds
            ``MAX_EXPORT_BYTES`` — the student selects fewer items instead of
            the service growing the response without limit.
    """
    body = json.dumps(envelope, ensure_ascii=False, indent=2, sort_keys=True) + '\n'
    if len(body.encode('utf-8')) > MAX_EXPORT_BYTES:
        raise ProjectExportError('The selected export is too large; select fewer items')
    return body
