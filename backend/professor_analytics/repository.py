"""Batch, read-only SQL access for professor analytics.

All aggregation is loaded in one query per endpoint snapshot.  The repository
never performs DDL or writes and never returns message bodies unless a selected
student detail needs its authorised transcript.
"""

from __future__ import annotations

import json
from typing import Any

from backend.source_library import CHAT_ATTACHMENT_ORIGIN
from backend.student_store import StudentStore


class ProfessorAnalyticsUnavailable(RuntimeError):
    """Raised when the read-only analytics snapshot cannot be loaded safely."""


class ProfessorAnalyticsRepository:
    """Read active notebook/message rows without an N+1 roster query pattern."""

    def __init__(self, store: StudentStore) -> None:
        self._store = store

    def load_class_rows(
        self,
        *,
        include_content: bool = False,
        student_id: str | None = None,
        notebook_id: str | None = None,
    ) -> list[dict[str, Any]]:
        """Return active-branch learning rows for every persisted student.

        ``conversation_revision`` and ``superseded_at_revision`` are evaluated
        in SQL so a revised-away turn cannot appear in current analytics.
        Internal idempotency marker rows are excluded at source.
        """
        content = "m.content AS message_content," if include_content else ""
        message_metadata = "m.metadata_text AS message_metadata," if include_content else ""
        student_clause = "AND u.id = ?" if student_id else ""
        notebook_clause = "AND n.id = ?" if notebook_id else ""
        params = tuple(
            value
            for value, enabled in (
                (student_id, bool(student_id)),
                (notebook_id, bool(notebook_id)),
            )
            if enabled
        )
        query = f"""
            SELECT
                u.id AS user_id, u.display_name, u.email, u.role,
                u.created_at AS user_created_at,
                n.id AS notebook_id, n.title, n.current_stage, n.progress_text,
                n.created_at AS notebook_created_at, n.updated_at AS notebook_updated_at,
                {content}
                m.id AS message_id, m.role AS message_role,
                m.is_error AS message_is_error, m.assessment_text,
                {message_metadata}
                m.cited_source_ids_text,
                m.created_at AS message_created_at
            FROM users u
            LEFT JOIN notebooks n ON n.user_id = u.id
            LEFT JOIN messages m ON m.notebook_id = n.id
                AND COALESCE(m.conversation_revision, 0) <= COALESCE(n.conversation_revision, 0)
                AND (m.superseded_at_revision IS NULL
                     OR m.superseded_at_revision > COALESCE(n.conversation_revision, 0))
                AND COALESCE(m.metadata_text, '') NOT LIKE
                    '%"_internal_type": "coach_idempotency"%'
            WHERE COALESCE(u.role, 'student') NOT IN ('lecturer', 'admin')
              AND (u.identifier <> 'local-student' OR u.cognito_sub IS NOT NULL)
              {student_clause}
              {notebook_clause}
            ORDER BY u.display_name, u.id, n.updated_at DESC, m.created_at ASC, m.id ASC
        """
        try:
            with self._store._connect() as connection:  # noqa: SLF001 - repository boundary
                rows = connection.execute(query, params).fetchall()
        except Exception as error:
            # Keep SQL/driver details out of professor responses; request-level
            # logging records only the route, status, latency, and request ID.
            raise ProfessorAnalyticsUnavailable(
                "Professor analytics data is temporarily unavailable"
            ) from error
        return [self._row_dict(row) for row in rows]

    def load_student_rows(
        self,
        student_id: str,
        *,
        include_content: bool = False,
        notebook_id: str | None = None,
    ) -> list[dict[str, Any]]:
        """Load only one student's active-branch rows.

        This explicit boundary keeps selected-student detail and transcript
        requests from materialising detailed rows for the rest of the class.
        The notebook predicate is additionally checked by the service before
        any transcript content is returned.
        """
        return self.load_class_rows(
            include_content=include_content,
            student_id=student_id,
            notebook_id=notebook_id,
        )

    def load_class_benchmark_rows(self) -> list[dict[str, Any]]:
        """Return compact class assessment rows without message bodies.

        The selected-student endpoint uses this narrow projection only for
        optional class comparison values; it never loads class notebook titles,
        message text, or attachment metadata.
        """
        query = """
            SELECT
                u.id AS user_id, u.display_name, u.email,
                m.id AS message_id, m.role AS message_role,
                m.is_error AS message_is_error, m.assessment_text,
                m.created_at AS message_created_at
            FROM users u
            JOIN notebooks n ON n.user_id = u.id
            JOIN messages m ON m.notebook_id = n.id
                AND COALESCE(m.conversation_revision, 0) <= COALESCE(n.conversation_revision, 0)
                AND (m.superseded_at_revision IS NULL
                     OR m.superseded_at_revision > COALESCE(n.conversation_revision, 0))
                AND COALESCE(m.metadata_text, '') NOT LIKE
                    '%"_internal_type": "coach_idempotency"%'
            WHERE COALESCE(u.role, 'student') NOT IN ('lecturer', 'admin')
              AND (u.identifier <> 'local-student' OR u.cognito_sub IS NOT NULL)
            ORDER BY u.id, m.created_at ASC, m.id ASC
        """
        try:
            with self._store._connect() as connection:  # noqa: SLF001 - repository boundary
                rows = connection.execute(query).fetchall()
        except Exception as error:
            raise ProfessorAnalyticsUnavailable(
                "Professor analytics data is temporarily unavailable"
            ) from error
        return [self._row_dict(row) for row in rows]

    def read_attachment(
        self, student_id: str, notebook_id: str, attachment_id: str
    ) -> dict[str, Any] | None:
        """Return one message-associated attachment after ownership checks.

        The source is eligible only when the notebook belongs to ``student_id``
        and an active message in that notebook explicitly references it.  The
        returned source remains an internal storage projection for the HTTP
        response and is never serialised directly.
        """
        query = """
            SELECT s.*,
                   m.metadata_text AS attachment_message_metadata
            FROM sources s
            JOIN notebooks n ON n.id = s.notebook_id
            JOIN messages m ON m.notebook_id = n.id
                AND COALESCE(m.conversation_revision, 0) <= COALESCE(n.conversation_revision, 0)
                AND (m.superseded_at_revision IS NULL
                     OR m.superseded_at_revision > COALESCE(n.conversation_revision, 0))
            JOIN users u ON u.id = n.user_id
            WHERE u.id=? AND n.id=? AND s.id=?
              AND COALESCE(s.metadata_text, '') LIKE '%chat_attachment%'
        """
        try:
            with self._store._connect() as connection:  # noqa: SLF001
                rows = connection.execute(query, (student_id, notebook_id, attachment_id)).fetchall()
        except Exception as error:
            raise ProfessorAnalyticsUnavailable(
                "Professor analytics data is temporarily unavailable"
            ) from error
        associated = False
        for row in rows:
            metadata = row["attachment_message_metadata"]
            try:
                message_metadata = json.loads(str(metadata or "{}"))
            except (TypeError, ValueError):
                message_metadata = {}
            attachment_ids = {
                str(item.get("id") or "")
                for item in (message_metadata.get("attachments") or [])
                if isinstance(item, dict)
            }
            if attachment_id in attachment_ids:
                associated = True
                break
        if not associated:
            return None
        # Reuse the store's source projection so local and object-storage
        # adapters receive normalized metadata without exposing storage keys.
        source = self._store._source_dict(  # noqa: SLF001 - repository projection boundary
            row, include_extracted_text=False
        )
        metadata = source.get("metadata") or {}
        if str(metadata.get("origin") or "").strip() != CHAT_ATTACHMENT_ORIGIN:
            return None
        return source

    def authorized_citation_ids(
        self, notebook_id: str, source_ids: list[str]
    ) -> set[str]:
        """Return citation ids persisted on the selected notebook only."""
        ids = [str(item).strip() for item in source_ids if str(item).strip()]
        if not ids:
            return set()
        placeholders = ",".join("?" for _ in ids)
        query = f"SELECT id FROM sources WHERE notebook_id=? AND id IN ({placeholders})"
        try:
            with self._store._connect() as connection:  # noqa: SLF001
                rows = connection.execute(query, (notebook_id, *ids)).fetchall()
        except Exception as error:
            raise ProfessorAnalyticsUnavailable(
                "Professor analytics data is temporarily unavailable"
            ) from error
        return {str(row["id"]) for row in rows}

    @staticmethod
    def _row_dict(row: Any) -> dict[str, Any]:
        """Normalise SQLite rows and DSQL mapping/proxy rows into dictionaries."""
        if isinstance(row, dict):
            return dict(row)
        keys = getattr(row, "keys", None)
        if callable(keys):
            return {str(key): row[key] for key in keys()}
        return dict(row)
