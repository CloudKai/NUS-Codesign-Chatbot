"""Persistent design canvas operations: create, read, list and revision-guarded saves."""

from __future__ import annotations

import json
import math
import uuid
from typing import Any

from backend.persistence.store.contracts import StoreContext, utc_now
from backend.persistence.store.operations.references import (
    canonical_references,
    require_resolved,
)

CANVAS_SCHEMA_VERSION = 1
CANVAS_SNAPSHOT_MAX_BYTES = 262_144
CANVAS_MAX_NODES = 100
CANVAS_MAX_EDGES = 200
CANVAS_MAX_ACCEPTED_SUGGESTION_IDS = 1_000
# Course-aligned node categories: every Thinking Path stage plus evidence,
# stakeholders, needs, assumptions, constraints and general notes.
CANVAS_NODE_KINDS = ('note', 'problem', 'stakeholder', 'need', 'evidence', 'assumption',
                     'constraint', 'concept', 'specification', 'ethics', 'evaluation',
                     'reflection')
# Meaningful labeled relationships between nodes on one canvas.
CANVAS_RELATIONS = ('supports', 'addresses', 'depends_on', 'conflicts_with', 'requires',
                    'derived_from', 'alternative_to', 'evaluated_against', 'raises_concern')
# The persisted Thinking Path stage ids a node may optionally associate with.
CANVAS_STAGE_IDS = ('problem_identification', 'concept_generation', 'design_specification',
                    'ethics_critical_thinking', 'reflection')
_ID_MAX = 64
_TEXT_MAX = 2_000


class CanvasConflictError(ValueError):
    """Raised when a save carries a revision that no longer matches the stored canvas."""


class CanvasValidationError(ValueError):
    """Raised when a graph is not a bounded, canonical canvas snapshot."""


def _text(value: Any, label: str, required: bool, limit: int = _TEXT_MAX) -> str:
    if value is None:
        if required:
            raise CanvasValidationError(f'{label} is required')
        return ''
    if not isinstance(value, str):
        raise CanvasValidationError(f'{label} must be text')
    normalized = value if required else value.strip()
    if required and not normalized.strip():
        raise CanvasValidationError(f'{label} is required')
    if len(normalized) > limit:
        raise CanvasValidationError(f'{label} is too long')
    return normalized


def _identifier(value: Any, label: str) -> str:
    if not isinstance(value, str) or not value or len(value) > _ID_MAX:
        raise CanvasValidationError(f'{label} must be a bounded non-empty string')
    return value


def _position(value: Any) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise CanvasValidationError('Node positions must be finite numbers')
    return float(value)


def _accepted_suggestion_ids(value: Any) -> list[str]:
    """Validate optional acceptance provenance: bounded ids, duplicates collapsed."""
    if not isinstance(value, list):
        raise CanvasValidationError('Accepted suggestion ids must be a list')
    if len(value) > CANVAS_MAX_ACCEPTED_SUGGESTION_IDS:
        raise CanvasValidationError('Canvas has too many accepted suggestion ids')
    ids: list[str] = []
    seen: set[str] = set()
    for item in value:
        identifier = _identifier(item, 'Accepted suggestion id')
        if identifier not in seen:
            seen.add(identifier)
            ids.append(identifier)
    return ids


def canonical_canvas_graph(graph: Any) -> str:
    """Validate and canonicalize one canvas snapshot.

    The canonical form is the stored source of truth: ``{"nodes": [...],
    "edges": [...]}`` with unique bounded node/edge ids, allowlisted kinds and
    relations, edges that join existing nodes on the same canvas, and finite
    positions. Optional ``accepted_suggestion_ids`` records accepted coach
    proposals as a deduplicated bounded list. The serialized form is always
    canonical JSON so stale-save comparisons stay exact.
    """
    if not isinstance(graph, dict):
        raise CanvasValidationError('Graph must be a JSON object')
    if set(graph) - {'nodes', 'edges', 'accepted_suggestion_ids'}:
        raise CanvasValidationError('Graph contains unsupported keys')
    nodes = graph.get('nodes')
    edges = graph.get('edges')
    if not isinstance(nodes, list) or not isinstance(edges, list):
        raise CanvasValidationError('Graph must contain node and edge lists')
    try:
        raw_size = len(json.dumps(graph, ensure_ascii=False, separators=(',', ':'),
                                  allow_nan=False).encode('utf-8'))
    except (TypeError, ValueError) as error:
        raise CanvasValidationError('Graph contains unsupported values') from error
    if raw_size > CANVAS_SNAPSHOT_MAX_BYTES:
        raise CanvasValidationError('Graph is too large')
    if len(nodes) > CANVAS_MAX_NODES:
        raise CanvasValidationError('Graph has too many nodes')
    if len(edges) > CANVAS_MAX_EDGES:
        raise CanvasValidationError('Graph has too many relationships')
    canonical_nodes: list[dict[str, Any]] = []
    seen_nodes: set[str] = set()
    for node in nodes:
        if not isinstance(node, dict):
            raise CanvasValidationError('Each node must be a JSON object')
        node_id = _identifier(node.get('id'), 'Node id')
        if node_id in seen_nodes:
            raise CanvasValidationError(f'Duplicate node id {node_id}')
        seen_nodes.add(node_id)
        kind = node.get('kind', 'note')
        if kind not in CANVAS_NODE_KINDS:
            raise CanvasValidationError('Unsupported node type')
        canonical: dict[str, Any] = {
            'id': node_id,
            'kind': kind,
            'title': _text(node.get('title'), 'Node title', required=True, limit=200),
            'description': _text(node.get('description'), 'Node description', required=False),
            'x': _position(node.get('x', 0)),
            'y': _position(node.get('y', 0)),
        }
        stage = node.get('stage')
        if stage is not None:
            if stage not in CANVAS_STAGE_IDS:
                raise CanvasValidationError('Unknown Thinking Path stage')
            # The association stays absent when unset so legacy snapshots compare exactly.
            canonical['stage'] = stage
        references = canonical_references(node.get('references'))
        if references:
            # The stored form stays absent when unset so legacy snapshots compare exactly.
            canonical['references'] = references
        canonical_nodes.append(canonical)
    canonical_edges: list[dict[str, Any]] = []
    seen_edges: set[str] = set()
    for edge in edges:
        if not isinstance(edge, dict):
            raise CanvasValidationError('Each relationship must be a JSON object')
        edge_id = _identifier(edge.get('id'), 'Relationship id')
        if edge_id in seen_edges:
            raise CanvasValidationError(f'Duplicate relationship id {edge_id}')
        seen_edges.add(edge_id)
        source = _identifier(edge.get('source'), 'Relationship source')
        target = _identifier(edge.get('target'), 'Relationship target')
        relation = edge.get('relation')
        if relation not in CANVAS_RELATIONS:
            raise CanvasValidationError('Unsupported relationship type')
        if source not in seen_nodes or target not in seen_nodes:
            raise CanvasValidationError(f'Relationship {edge_id} joins an unknown node')
        if source == target:
            raise CanvasValidationError(f'Relationship {edge_id} joins a node to itself')
        canonical_edges.append({
            'id': edge_id,
            'source': source,
            'target': target,
            'relation': relation,
            'explanation': _text(edge.get('explanation'), 'Relationship explanation', required=False),
        })
    canonical: dict[str, Any] = {'nodes': canonical_nodes, 'edges': canonical_edges}
    if 'accepted_suggestion_ids' in graph:
        canonical['accepted_suggestion_ids'] = _accepted_suggestion_ids(
            graph['accepted_suggestion_ids'])
    try:
        serialized = json.dumps(canonical, ensure_ascii=False,
                                separators=(',', ':'), allow_nan=False)
    except (TypeError, ValueError) as error:
        raise CanvasValidationError('Graph contains unsupported values') from error
    if len(serialized.encode('utf-8')) > CANVAS_SNAPSHOT_MAX_BYTES:
        raise CanvasValidationError('Graph is too large')
    return serialized


def _clean_title(title: Any) -> str:
    normalized = ' '.join(str(title or '').split())[:200] if title is not None else ''
    if not normalized:
        raise CanvasValidationError('Canvas title is required')
    return normalized


def canvas_row(row: dict[str, Any]) -> dict[str, Any]:
    """Project one stored canvas row with its parsed canonical graph."""
    return {
        'id': row['id'], 'thread_id': row['notebook_id'], 'title': row['title'],
        'graph': json.loads(row['graph_text']), 'schema_version': int(row['schema_version']),
        'revision': int(row['revision']), 'origin': row['origin'],
        'created_at': row['created_at'], 'updated_at': row['updated_at'],
    }


class CanvasOperations:
    """Persistent, owner-scoped design canvases over the existing notebook anchor."""

    def __init__(self, store: StoreContext):
        self._store = store

    def _require_node_evidence(
        self, thread_id: str, serialized: str, previous: str | None = None,
    ) -> None:
        """Resolve new links while retaining previously saved evidence provenance."""
        graph = json.loads(serialized)
        existing = {
            node['id']: node.get('references') or []
            for node in json.loads(previous or '{}').get('nodes') or []
        }
        references = [dict(reference) for node in graph.get('nodes') or []
                      for reference in node.get('references') or []
                      if reference not in existing.get(node['id'], ())]
        if references:
            require_resolved(self._store, thread_id, references)

    def create(self, thread_id: str, title: str, graph: Any) -> dict[str, Any]:
        """Create one owned canvas anchored to an existing owned notebook."""
        serialized = canonical_canvas_graph(graph)
        clean_title = _clean_title(title)
        canvas_id = str(uuid.uuid4())
        now = utc_now()
        self._require_node_evidence(thread_id, serialized)
        with self._store._lock, self._store._connect() as connection:
            owned = connection.execute(
                "SELECT id FROM notebooks WHERE id=? AND user_id=?",
                (thread_id, self._store.owner_id),
            ).fetchone()
            if not owned:
                raise LookupError('Notebook not found')
            connection.execute(
                """
                INSERT INTO student_canvases
                  (id, notebook_id, user_id, title, graph_text, schema_version,
                   revision, origin, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, 1, 'editor', ?, ?)
                """,
                (canvas_id, thread_id, self._store.owner_id, clean_title,
                 serialized, CANVAS_SCHEMA_VERSION, now, now),
            )
            connection.execute(
                """
                INSERT INTO student_canvas_versions
                  (id, canvas_id, notebook_id, user_id, revision, title,
                   graph_text, origin, restored_from, created_at)
                VALUES (?, ?, ?, ?, 1, ?, ?, 'editor', NULL, ?)
                """,
                (str(uuid.uuid4()), canvas_id, thread_id, self._store.owner_id,
                 clean_title, serialized, now),
            )
            connection.commit()
        stored = self.get(canvas_id)
        assert stored is not None
        return stored

    def get(self, canvas_id: str) -> dict[str, Any] | None:
        """Return one owned canvas with its parsed graph, or None."""
        with self._store._connect() as connection:
            row = connection.execute(
                "SELECT * FROM student_canvases WHERE id = ? AND user_id = ?",
                (canvas_id, self._store.owner_id),
            ).fetchone()
        return canvas_row(dict(row)) if row is not None else None

    def list(self, thread_id: str) -> list[dict[str, Any]]:
        """List one owned notebook's canvases, newest first, without graph bodies."""
        with self._store._connect() as connection:
            rows = connection.execute(
                """
                SELECT id, notebook_id, title, schema_version, revision, origin,
                       created_at, updated_at
                FROM student_canvases WHERE notebook_id = ? AND user_id = ?
                ORDER BY updated_at DESC, id
                """,
                (thread_id, self._store.owner_id),
            ).fetchall()
        return [{
            'id': row['id'], 'thread_id': row['notebook_id'], 'title': row['title'],
            'schema_version': int(row['schema_version']), 'revision': int(row['revision']),
            'origin': row['origin'], 'created_at': row['created_at'], 'updated_at': row['updated_at'],
        } for row in rows]

    def update(self, canvas_id: str, graph: Any, revision: int,
               title: str | None = None, restored_from: int | None = None) -> dict[str, Any]:
        """Apply one explicit save guarded by the seen revision; stale saves fail."""
        serialized = canonical_canvas_graph(graph)
        clean_title = _clean_title(title) if title is not None else None
        now = utc_now()
        origin = 'restore' if restored_from is not None else 'editor'
        with self._store._lock, self._store._connect() as connection:
            row = connection.execute(
                "SELECT revision, title, notebook_id, graph_text "
                "FROM student_canvases WHERE id = ? AND user_id = ?",
                (canvas_id, self._store.owner_id),
            ).fetchone()
            if row is None:
                raise LookupError('Canvas not found')
            new_revision = int(row['revision']) + 1
            final_title = clean_title if clean_title is not None else str(row['title'])
            if restored_from is None:
                self._require_node_evidence(str(row['notebook_id']), serialized, row['graph_text'])
            # The version checkpoint lands first; a lost OCC race rolls it back.
            connection.execute(
                """
                INSERT INTO student_canvas_versions
                  (id, canvas_id, notebook_id, user_id, revision, title,
                   graph_text, origin, restored_from, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (str(uuid.uuid4()), canvas_id, row['notebook_id'], self._store.owner_id,
                 new_revision, final_title, serialized, origin, restored_from, now),
            )
            cursor = connection.execute(
                """
                UPDATE student_canvases
                SET graph_text = ?, revision = ?, updated_at = ?, title = ?, origin = ?
                WHERE id = ? AND user_id = ? AND revision = ?
                """,
                (serialized, new_revision, now, final_title, origin,
                 canvas_id, self._store.owner_id, int(revision)),
            )
            if cursor.rowcount != 1:
                connection.rollback()
                raise CanvasConflictError('Canvas changed. Reopen it before saving.')
            connection.commit()
        stored = self.get(canvas_id)
        assert stored is not None
        return stored

    def delete(self, canvas_id: str, revision: int, confirmed: bool) -> None:
        """Delete the confirmed canvas revision and its checkpoints atomically."""
        if not confirmed:
            raise CanvasValidationError('Confirm the deletion first')
        owner_id = self._store.owner_id
        with self._store._lock, self._store._connect() as connection:
            connection.execute(
                "DELETE FROM student_canvas_versions WHERE canvas_id = ? AND user_id = ?",
                (canvas_id, owner_id),
            )
            cursor = connection.execute(
                "DELETE FROM student_canvases WHERE id = ? AND user_id = ? AND revision = ?",
                (canvas_id, owner_id, revision),
            )
            if cursor.rowcount != 1:
                raise CanvasConflictError('Canvas changed. Reopen it before deleting.')
            # Other work retains its original references. Resolution now marks
            # those links unavailable, without rewriting another document.
            connection.commit()

    def list_versions(self, canvas_id: str, limit: int = 50) -> list[dict[str, Any]]:
        """List one owned canvas's bounded version metadata, newest first."""
        with self._store._connect() as connection:
            rows = connection.execute(
                """
                SELECT revision, title, origin, restored_from, created_at
                FROM student_canvas_versions
                WHERE canvas_id = ? AND user_id = ?
                ORDER BY revision DESC LIMIT ?
                """,
                (canvas_id, self._store.owner_id, max(1, min(200, limit))),
            ).fetchall()
        return [{
            'revision': int(row['revision']), 'title': row['title'],
            'origin': row['origin'],
            'restored_from': int(row['restored_from']) if row['restored_from'] is not None else None,
            'created_at': row['created_at'],
        } for row in rows]

    def get_version(self, canvas_id: str, revision: int) -> dict[str, Any] | None:
        """Return one owned version's readable preview, or None."""
        with self._store._connect() as connection:
            row = connection.execute(
                """
                SELECT revision, title, graph_text, origin, restored_from, created_at
                FROM student_canvas_versions
                WHERE canvas_id = ? AND user_id = ? AND revision = ?
                """,
                (canvas_id, self._store.owner_id, int(revision)),
            ).fetchone()
        if row is None:
            return None
        return {
            'revision': int(row['revision']), 'title': row['title'],
            'graph': json.loads(row['graph_text']), 'origin': row['origin'],
            'restored_from': int(row['restored_from']) if row['restored_from'] is not None else None,
            'created_at': row['created_at'],
        }

    def restore(self, canvas_id: str, version_revision: int, seen_revision: int) -> dict[str, Any]:
        """Restore an older version as a new revision guarded by the current one."""
        version = self.get_version(canvas_id, version_revision)
        if version is None:
            raise LookupError('Canvas version not found')
        return self.update(canvas_id, version['graph'], seen_revision,
                           version['title'], restored_from=version_revision)
