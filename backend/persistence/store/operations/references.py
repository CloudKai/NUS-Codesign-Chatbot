"""Evidence reference validation and owner-scoped resolution for artifacts and canvas nodes.

References point at authorized evidence inside the same notebook: notebook
sources, active conversation messages, sibling artifacts and canvas nodes.
Structural validation is pure; resolution runs owner-scoped queries and marks
every unresolvable reference unavailable without substituting content.
"""

from __future__ import annotations

import json
from typing import Any

from backend.persistence.store.contracts import StoreContext

REFERENCE_KINDS = ('source', 'message', 'artifact', 'canvas_node')
MAX_REFERENCES = 20
_ID_MAX = 128
_MESSAGE_PREVIEW_MAX = 160


class ReferenceError(ValueError):
    """Raised when a reference list is malformed or evidence cannot be resolved."""


def canonical_references(references: Any) -> list[dict[str, Any]]:
    """Validate and canonicalize one bounded reference list; duplicates collapse.

    A duplicate keeps the newest supplied revision stamp so a node linked at a
    later revision is not silently downgraded, and stays unchanged when the
    duplicate carries no revision.
    """
    if references is None:
        return []
    if not isinstance(references, list):
        raise ReferenceError('References must be a list')
    if len(references) > MAX_REFERENCES:
        raise ReferenceError('Too many references')
    canonical: list[dict[str, Any]] = []
    position: dict[tuple[str, str, str], int] = {}
    for reference in references:
        if not isinstance(reference, dict):
            raise ReferenceError('Each reference must be a JSON object')
        kind = reference.get('kind')
        if kind not in REFERENCE_KINDS:
            raise ReferenceError('Unsupported reference kind')
        identifier = reference.get('id')
        if not isinstance(identifier, str) or not identifier or len(identifier) > _ID_MAX:
            raise ReferenceError('Reference id must be a bounded non-empty string')
        entry: dict[str, Any] = {'kind': kind, 'id': identifier}
        if kind == 'canvas_node':
            canvas_id = reference.get('canvas_id')
            if not isinstance(canvas_id, str) or not canvas_id or len(canvas_id) > _ID_MAX:
                raise ReferenceError('A canvas_node reference needs a canvas id')
            entry['canvas_id'] = canvas_id
        # The optional revision records which saved revision the linked content
        # came from (an artifact version or a canvas snapshot). It stays absent
        # when unsupplied so legacy snapshots compare exactly.
        revision = reference.get('revision')
        if revision is not None:
            if kind not in ('artifact', 'canvas_node'):
                raise ReferenceError(
                    'Only artifact and canvas_node references carry a revision')
            if isinstance(revision, bool) or not isinstance(revision, int) \
                    or not 1 <= revision <= 1_000_000:
                raise ReferenceError('A reference revision must be a positive integer')
            entry['revision'] = revision
        key = (str(kind), identifier, str(entry.get('canvas_id') or ''))
        existing = position.get(key)
        if existing is not None:
            # Keep the newest stamp: a lower or absent duplicate revision never
            # rewrites the earlier entry, preserving legacy collapse-to-first.
            revision = entry.get('revision')
            if revision is not None and revision > canonical[existing].get('revision', 0):
                canonical[existing]['revision'] = revision
            continue
        position[key] = len(canonical)
        canonical.append(entry)
    return canonical


def _owned_canvas_node_title(store: StoreContext, thread_id: str, canvas_id: str,
                             node_id: str) -> str | None:
    """Return one node's title when it exists in an owned same-notebook canvas."""
    with store._connect() as connection:
        row = connection.execute(
            "SELECT graph_text FROM student_canvases WHERE id = ? AND notebook_id = ? AND user_id = ?",
            (canvas_id, thread_id, store.owner_id),
        ).fetchone()
    if row is None:
        return None
    try:
        graph = json.loads(row['graph_text'])
    except (TypeError, ValueError):
        return None
    for node in graph.get('nodes') or []:
        if str(node.get('id')) == node_id:
            return str(node.get('title')) or None
    return None


def notebook_family_ids(connection: Any, thread_id: str, owner_id: str) -> list[str]:
    """The notebook family for one thread: the whole project it belongs to.

    The parent relationship lives in the notebooks' settings JSON; the family
    is bounded by one owner's notebook count, so a single read is enough. A
    child chat's family is its parent plus every one of the parent's children,
    so exports and evidence opened from any chat see the same full set.
    """
    rows = connection.execute(
        "SELECT id, settings_text FROM notebooks WHERE user_id = ?", (owner_id,)).fetchall()
    parents: dict[str, str | None] = {}
    for row in rows:
        try:
            settings = json.loads(row['settings_text'] or '{}')
        except (TypeError, ValueError):
            settings = {}
        parents[str(row['id'])] = str(settings['reader_parent_notebook_id']) \
            if settings.get('reader_parent_notebook_id') else None
    if thread_id not in parents:
        return [thread_id]
    family = {thread_id}
    parent = parents[thread_id]
    if parent and parent in parents:
        family.add(parent)
        family.update(identifier for identifier, parent_id in parents.items()
                      if parent_id == parent)
    family.update(identifier for identifier, parent_id in parents.items()
                  if parent_id == thread_id)
    return sorted(family)


def _family_linked_source_ids(connection: Any, family: list[str]) -> set[str]:
    """Source ids explicitly linked into one notebook family's notebooks.

    Reader sources live in the owner's Library and link into notebooks through
    each notebook's settings metadata, so evidence resolution must consult
    those links as well as in-notebook rows.
    """
    marks = ','.join('?' for _ in family)
    linked: set[str] = set()
    for row in connection.execute(
            f"SELECT settings_text FROM notebooks WHERE id IN ({marks})", family).fetchall():
        try:
            metadata = json.loads(row['settings_text'] or '{}')
        except (TypeError, ValueError):
            continue
        links = metadata.get('reader_source_links')
        if isinstance(links, dict):
            linked.update(str(identifier) for identifier, selected in links.items() if selected)
    return linked


def resolve_references(store: StoreContext, thread_id: str,
                       references: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Resolve every reference under the owner/project boundary; unavailable stays explicit.

    The project boundary is the notebook family: the whole project the given
    notebook belongs to (its parent and every sibling chat when it is a child).
    Sources and messages resolve anywhere in the family
    (sources are shared across a notebook's chats); artifacts and canvases must
    be anchored to the given notebook. Nothing is substituted for missing evidence.
    """
    resolutions: list[dict[str, Any]] = []
    family_linked: set[str] | None = None
    with store._connect() as connection:
        family = notebook_family_ids(connection, thread_id, store.owner_id)
        family_marks = ','.join('?' for _ in family)
        for reference in references:
            kind = str(reference['kind'])
            identifier = str(reference['id'])
            available = False
            title: str | None = None
            if kind == 'source':
                linked = family_linked or _family_linked_source_ids(connection, family)
                family_linked = linked
                row = connection.execute(
                    "SELECT s.title FROM sources s JOIN notebooks n ON n.id = s.notebook_id "
                    f"WHERE s.id = ? AND n.user_id = ? AND s.notebook_id IN ({family_marks})",
                    (identifier, store.owner_id, *family),
                ).fetchone()
                if row is None and identifier in linked:
                    # Linked Library sources belong to the owner but sit outside the
                    # notebook family; ownership is still enforced by the join.
                    row = connection.execute(
                        "SELECT s.title FROM sources s JOIN notebooks n ON n.id = s.notebook_id "
                        "WHERE s.id = ? AND n.user_id = ?",
                        (identifier, store.owner_id),
                    ).fetchone()
                if row is not None:
                    available, title = True, str(row['title'])
            elif kind == 'message':
                row = connection.execute(
                    "SELECT m.content FROM messages m JOIN notebooks n ON n.id = m.notebook_id "
                    f"WHERE m.id = ? AND n.user_id = ? AND m.superseded_at_revision IS NULL "
                    f"AND m.notebook_id IN ({family_marks})",
                    (identifier, store.owner_id, *family),
                ).fetchone()
                if row is not None:
                    available = True
                    title = ' '.join(str(row['content']).split())[:_MESSAGE_PREVIEW_MAX]
            elif kind == 'artifact':
                row = connection.execute(
                    "SELECT title FROM student_artifacts "
                    "WHERE id = ? AND notebook_id = ? AND user_id = ?",
                    (identifier, thread_id, store.owner_id),
                ).fetchone()
                if row is not None:
                    available, title = True, str(row['title'])
            elif kind == 'canvas_node':
                canvas_id = str(reference['canvas_id'])
                title = _owned_canvas_node_title(store, thread_id, canvas_id, identifier)
                available = title is not None
            resolutions.append({
                **reference, 'available': available, 'title': title if available else None,
            })
    return resolutions


def require_resolved(store: StoreContext, thread_id: str,
                     references: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Fail closed unless every reference resolves to available same-project evidence."""
    resolved = resolve_references(store, thread_id, references)
    for entry in resolved:
        if not entry['available']:
            raise ReferenceError('Unresolved reference')
    return resolved
