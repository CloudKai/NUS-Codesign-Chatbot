"""Persistent student artifact operations: create, read, list and revision-guarded saves."""

from __future__ import annotations

import hashlib
import json
import re
import uuid
from typing import Any

from backend.persistence.store.contracts import StoreContext, utc_now
from backend.persistence.store.operations.references import (
    canonical_references,
    require_resolved,
    resolve_references,
)

ARTIFACT_SCHEMA_VERSION = 1
ARTIFACT_DOCUMENT_MAX_BYTES = 262_144
ARTIFACT_DOCUMENT_MAX_DEPTH = 32
ARTIFACT_KINDS = ('notes', 'problem_identification', 'concept_generation',
                  'design_specification', 'ethics_critical_thinking', 'reflection')
ARTIFACT_ORIGINS = ('editor', 'coach_draft')
_REQUEST_ID_PATTERN = re.compile(r'^[A-Za-z0-9][A-Za-z0-9._:-]*$')


class ArtifactConflictError(ValueError):
    """Raised when a save carries a revision that no longer matches the stored artifact."""


class ArtifactValidationError(ValueError):
    """Raised when a document is not a canonical, bounded Tiptap document."""


def _depth(value: Any) -> int:
    if isinstance(value, dict):
        return 1 + max((_depth(item) for item in value.values()), default=0)
    if isinstance(value, list):
        return 1 + max((_depth(item) for item in value), default=0)
    return 0


def canonical_artifact_document(document: Any) -> str:
    """Validate and canonicalize one Tiptap document JSON payload.

    The canonical form is the stored source of truth: a bounded object whose
    root is ``{"type": "doc", "content": [...]}`` with finite depth. Unknown
    extra keys are preserved but the serialized form is always canonical JSON
    so stale-save comparisons stay exact.
    """
    if not isinstance(document, dict):
        raise ArtifactValidationError('Document must be a JSON object')
    if document.get('type') != 'doc':
        raise ArtifactValidationError('Document must start with a doc node')
    if not isinstance(document.get('content'), list):
        raise ArtifactValidationError('Document must contain content nodes')
    if _depth(document) > ARTIFACT_DOCUMENT_MAX_DEPTH:
        raise ArtifactValidationError('Document is too deeply nested')
    try:
        serialized = json.dumps(document, ensure_ascii=False, separators=(',', ':'), allow_nan=False)
    except (TypeError, ValueError) as error:
        raise ArtifactValidationError('Document contains unsupported values') from error
    if len(serialized.encode('utf-8')) > ARTIFACT_DOCUMENT_MAX_BYTES:
        raise ArtifactValidationError('Document is too large')
    return serialized


def _clean_title(title: Any) -> str:
    normalized = ' '.join(str(title or '').split())[:200] if title is not None else ''
    if not normalized:
        raise ArtifactValidationError('Document title is required')
    return normalized


def _clean_origin(origin: Any) -> str:
    """Normalize and allowlist the artifact provenance label; omitted stays editor."""
    value = 'editor' if origin is None else origin
    if value not in ARTIFACT_ORIGINS:
        raise ArtifactValidationError('Unsupported artifact origin')
    return value


def _clean_request_id(request_id: Any) -> str | None:
    """Bound the optional create idempotency key; ``None`` keeps creates distinct."""
    if request_id is None:
        return None
    if not isinstance(request_id, str) or not 1 <= len(request_id) <= 128 \
            or not _REQUEST_ID_PATTERN.fullmatch(request_id):
        raise ArtifactValidationError('request_id must be a bounded request key')
    return request_id


def _request_fingerprint(title: str, kind: str, document_text: str,
                         references_text: str, origin: str) -> str:
    """Exact retry fingerprint: a changed payload under one request id must refuse."""
    payload = json.dumps({'title': title, 'kind': kind, 'document_text': document_text,
                          'references_text': references_text, 'origin': origin},
                         ensure_ascii=False, separators=(',', ':'), sort_keys=True)
    return hashlib.sha256(payload.encode('utf-8')).hexdigest()


# SQLSTATE classes the DSQL OCC wrapper retries. The shared operations module
# stays provider-neutral, so serialization failures are recognised by their
# declared sqlstate (set by the DSQL adapters) rather than by exception type.
_RETRYABLE_SQLSTATES = ('40001', '40P01')


def _is_serialization_failure(error: BaseException) -> bool:
    """True when *error* (or its cause) is an OCC-retryable serialization failure."""
    for candidate in (error, getattr(error, '__cause__', None)):
        if candidate is not None and getattr(candidate, 'sqlstate', None) in _RETRYABLE_SQLSTATES:
            return True
    return False


def artifact_row(store: StoreContext, row: dict[str, Any]) -> dict[str, Any]:
    """Project one stored artifact row with its parsed document and resolved references."""
    references = json.loads(row.get('references_text') or '[]')
    return {
        'id': row['id'], 'thread_id': row['notebook_id'], 'title': row['title'],
        'kind': row['kind'] if 'kind' in row else 'notes',
        'document': json.loads(row['document_text']), 'schema_version': int(row['schema_version']),        'revision': int(row['revision']), 'origin': row['origin'],
        'created_at': row['created_at'], 'updated_at': row['updated_at'],
        'references': resolve_references(store, row['notebook_id'], references),
    }


class ArtifactOperations:
    """Persistent, owner-scoped student documents over the existing notebook anchor.

    Creates carrying a ``request_id`` are idempotent even when two requests race:
    the request-key lookup handles the common retry, and a loser of the race
    between that lookup and the INSERT replays the winner through the same
    fingerprint check instead of surfacing the uniqueness error.
    """

    def __init__(self, store: StoreContext):
        self._store = store

    def create(self, thread_id: str, title: str, document: Any, kind: str = 'notes',
               references: list[dict[str, Any]] | None = None, *,
               origin: str | None = None,
               request_id: str | None = None) -> dict[str, Any]:
        """Create one owned artifact anchored to an existing owned notebook.

        A supplied ``request_id`` makes the call idempotent for the notebook: an
        existing row with that key is replayed unchanged (same revision, no new
        checkpoint), so a lost acknowledgement can be retried safely. If a
        concurrent create wins the race after our lookup, the uniqueness failure
        on INSERT also replays the winner (or refuses a changed retry).
        """
        if kind not in ARTIFACT_KINDS:
            raise ArtifactValidationError('Unsupported artifact type')
        clean_origin = _clean_origin(origin)
        clean_request_id = _clean_request_id(request_id)
        serialized = canonical_artifact_document(document)
        clean_references = canonical_references(references)
        serialized_references = json.dumps(clean_references, ensure_ascii=False,
                                           separators=(',', ':'))
        clean_title = _clean_title(title)
        # A retry must be the same request: identical title, kind, document,
        # references and origin. Changed retries refuse instead of replaying
        # someone else's content under this identity.
        fingerprint = _request_fingerprint(clean_title, kind, serialized,
                                           serialized_references, clean_origin)
        if clean_request_id is not None:
            with self._store._lock, self._store._connect() as connection:
                self._require_owned_notebook(connection, thread_id)
                existing = self._request_row(connection, thread_id, clean_request_id)
            if existing is not None:
                return self._replay(existing, fingerprint)
        if clean_references:
            require_resolved(self._store, thread_id, clean_references)
        artifact_id = str(uuid.uuid4())
        now = utc_now()
        try:
            with self._store._lock, self._store._connect() as connection:
                self._require_owned_notebook(connection, thread_id)
                connection.execute(
                    """
                    INSERT INTO student_artifacts
                      (id, notebook_id, user_id, title, kind, document_text, references_text,
                       schema_version, revision, origin, request_id, request_fingerprint,
                       created_at, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, 1, ?, ?, ?, ?, ?)
                    """,
                    (artifact_id, thread_id, self._store.owner_id, clean_title, kind,
                     serialized, serialized_references, ARTIFACT_SCHEMA_VERSION, clean_origin,
                     clean_request_id, fingerprint, now, now),
                )
                connection.execute(
                    """
                    INSERT INTO student_artifact_versions
                      (id, artifact_id, notebook_id, user_id, revision, title, kind,
                       document_text, references_text, origin, restored_from, created_at)
                    VALUES (?, ?, ?, ?, 1, ?, ?, ?, ?, ?, NULL, ?)
                    """,
                    (str(uuid.uuid4()), artifact_id, thread_id, self._store.owner_id,
                     clean_title, kind, serialized, serialized_references, clean_origin, now),
                )
                connection.commit()
        except Exception as error:
            # Only a request-key collision is replayable. Serialization-class
            # failures must propagate unchanged so the DSQL OCC wrapper can
            # retry the whole unit (the recovery re-read cannot run on an
            # aborted transaction). Anything else, or a collision with no
            # visible winner, re-raises unchanged.
            if clean_request_id is None or _is_serialization_failure(error):
                raise
            with self._store._connect() as connection:
                winner = self._request_row(connection, thread_id, clean_request_id)
            if winner is None:
                raise
            return self._replay(winner, fingerprint)
        stored = self.get(artifact_id)
        assert stored is not None
        return stored

    def _request_row(self, connection: Any, thread_id: str,
                     request_id: str) -> Any | None:
        """Return the owner+notebook-scoped row for one create key, if any."""
        return connection.execute(
            "SELECT * FROM student_artifacts "
            "WHERE notebook_id=? AND user_id=? AND request_id=?",
            (thread_id, self._store.owner_id, request_id),
        ).fetchone()

    def _replay(self, existing: Any, fingerprint: str) -> dict[str, Any]:
        """Replay one existing request row, or refuse a retry that changed the payload."""
        stored_fingerprint = (existing['request_fingerprint']
                              if 'request_fingerprint' in existing.keys() else None)
        if stored_fingerprint not in (None, fingerprint):
            raise ArtifactValidationError(
                'Retried creation changed the original operation. Start a new artifact instead.')
        return artifact_row(self._store, dict(existing))

    def _require_owned_notebook(self, connection: Any, thread_id: str) -> None:
        """Fail closed unless this owner's notebook anchor exists."""
        owned = connection.execute(
            "SELECT id FROM notebooks WHERE id=? AND user_id=?",
            (thread_id, self._store.owner_id),
        ).fetchone()
        if not owned:
            raise LookupError('Notebook not found')

    def get(self, artifact_id: str) -> dict[str, Any] | None:
        """Return one owned artifact with its parsed document, or None."""
        with self._store._connect() as connection:
            row = connection.execute(
                "SELECT * FROM student_artifacts WHERE id = ? AND user_id = ?",
                (artifact_id, self._store.owner_id),
            ).fetchone()
        return artifact_row(self._store, dict(row)) if row is not None else None

    def list(self, thread_id: str) -> list[dict[str, Any]]:
        """List one owned notebook's artifacts, newest first, without document bodies."""
        with self._store._connect() as connection:
            rows = connection.execute(
                """
                SELECT id, notebook_id, title, kind, schema_version, revision, origin,
                       created_at, updated_at
                FROM student_artifacts WHERE notebook_id = ? AND user_id = ?
                ORDER BY updated_at DESC, id
                """,
                (thread_id, self._store.owner_id),
            ).fetchall()
        return [{
            'id': row['id'], 'thread_id': row['notebook_id'], 'title': row['title'],
            'kind': row['kind'], 'schema_version': int(row['schema_version']),
            'revision': int(row['revision']),
            'origin': row['origin'], 'created_at': row['created_at'], 'updated_at': row['updated_at'],
        } for row in rows]

    def update(self, artifact_id: str, document: Any, revision: int,
               title: str | None = None, restored_from: int | None = None,
               references: list[dict[str, Any]] | None = None) -> dict[str, Any]:
        """Apply one explicit save guarded by the seen revision; stale saves fail.

        Omitted references keep the saved list; an explicit list (including an
        empty one) replaces it after every entry resolves inside the notebook.
        """
        serialized = canonical_artifact_document(document)
        clean_title = _clean_title(title) if title is not None else None
        now = utc_now()
        origin = 'restore' if restored_from is not None else 'editor'
        with self._store._lock, self._store._connect() as connection:
            row = connection.execute(
                "SELECT revision, kind, title, notebook_id, references_text FROM student_artifacts WHERE id = ? AND user_id = ?",
                (artifact_id, self._store.owner_id),
            ).fetchone()
            if row is None:
                raise LookupError('Artifact not found')
            new_revision = int(row['revision']) + 1
            final_title = clean_title if clean_title is not None else str(row['title'])
            if references is None:
                final_references = str(row['references_text'] or '[]')
            else:
                clean_references = canonical_references(references)
                require_resolved(self._store, str(row['notebook_id']), clean_references)
                final_references = json.dumps(clean_references, ensure_ascii=False,
                                              separators=(',', ':'))
            connection.execute(
                """
                INSERT INTO student_artifact_versions
                  (id, artifact_id, notebook_id, user_id, revision, title, kind,
                   document_text, references_text, origin, restored_from, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (str(uuid.uuid4()), artifact_id, row['notebook_id'], self._store.owner_id,
                 new_revision, final_title, str(row['kind']), serialized, final_references,
                 origin, restored_from, now),
            )
            cursor = connection.execute(
                """
                UPDATE student_artifacts
                SET document_text = ?, revision = ?, updated_at = ?,
                    title = ?, origin = ?, references_text = ?
                WHERE id = ? AND user_id = ? AND revision = ?
                """,
                (serialized, new_revision, now, final_title, origin, final_references,
                 artifact_id, self._store.owner_id, int(revision)),
            )
            if cursor.rowcount != 1:
                raise ArtifactConflictError('Artifact changed. Reopen it before saving.')
            connection.commit()
        stored = self.get(artifact_id)
        assert stored is not None
        return stored

    def list_versions(self, artifact_id: str, limit: int = 50) -> list[dict[str, Any]]:
        """List one owned artifact's bounded version metadata, newest first."""
        with self._store._connect() as connection:
            rows = connection.execute(
                """
                SELECT revision, title, kind, origin, restored_from, created_at
                FROM student_artifact_versions
                WHERE artifact_id = ? AND user_id = ?
                ORDER BY revision DESC LIMIT ?
                """,
                (artifact_id, self._store.owner_id, max(1, min(200, limit))),
            ).fetchall()
        return [{
            'revision': int(row['revision']), 'title': row['title'], 'kind': row['kind'],
            'origin': row['origin'], 'restored_from':
                int(row['restored_from']) if row['restored_from'] is not None else None,
            'created_at': row['created_at'],
        } for row in rows]

    def get_version(self, artifact_id: str, revision: int) -> dict[str, Any] | None:
        """Return one owned version's readable preview, or None."""
        with self._store._connect() as connection:
            row = connection.execute(
                """
                SELECT revision, title, kind, document_text, references_text, origin,
                       restored_from, created_at
                FROM student_artifact_versions
                WHERE artifact_id = ? AND user_id = ? AND revision = ?
                """,
                (artifact_id, self._store.owner_id, int(revision)),
            ).fetchone()
        if row is None:
            return None
        return {
            'revision': int(row['revision']), 'title': row['title'], 'kind': row['kind'],
            'document': json.loads(row['document_text']),
            'references': json.loads(row['references_text'] or '[]'),
            'origin': row['origin'],
            'restored_from': int(row['restored_from']) if row['restored_from'] is not None else None,
            'created_at': row['created_at'],
        }

    def restore(self, artifact_id: str, version_revision: int, seen_revision: int) -> dict[str, Any]:
        """Restore an older version as a new revision guarded by the current one."""
        version = self.get_version(artifact_id, version_revision)
        if version is None:
            raise LookupError('Artifact version not found')
        return self.update(artifact_id, version['document'], seen_revision,
                           version['title'], restored_from=version_revision,
                           references=version['references'])

    def duplicate(self, artifact_id: str) -> dict[str, Any]:
        """Copy one owned artifact's kind, title and canonical document to a new identity."""
        stored = self.get(artifact_id)
        if stored is None:
            raise LookupError('Artifact not found')
        copied = self.create(stored['thread_id'], f"{stored['title']} (copy)",
                             stored['document'], stored['kind'],
                             [dict(entry) for entry in stored['references']])
        return copied

    def delete(self, artifact_id: str, confirmed: bool) -> None:
        """Delete one owned artifact and its version history only after an explicit confirmation."""
        if not confirmed:
            raise ArtifactValidationError('Confirm the deletion first')
        with self._store._lock, self._store._connect() as connection:
            connection.execute(
                "DELETE FROM student_artifact_versions WHERE artifact_id = ? AND user_id = ?",
                (artifact_id, self._store.owner_id),
            )
            cursor = connection.execute(
                "DELETE FROM student_artifacts WHERE id = ? AND user_id = ?",
                (artifact_id, self._store.owner_id),
            )
            if cursor.rowcount != 1:
                raise LookupError('Artifact not found')
            connection.commit()
