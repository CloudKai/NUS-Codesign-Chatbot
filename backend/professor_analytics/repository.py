"""Batch, read-only SQL access for professor analytics.

All aggregation is loaded in one query per endpoint snapshot.  The repository
never performs DDL or writes and never returns message bodies unless a selected
student detail needs its authorised transcript.
"""

from __future__ import annotations

from typing import Any

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

    @staticmethod
    def _row_dict(row: Any) -> dict[str, Any]:
        """Normalise SQLite rows and DSQL mapping/proxy rows into dictionaries."""
        if isinstance(row, dict):
            return dict(row)
        keys = getattr(row, "keys", None)
        if callable(keys):
            return {str(key): row[key] for key in keys()}
        return dict(row)
