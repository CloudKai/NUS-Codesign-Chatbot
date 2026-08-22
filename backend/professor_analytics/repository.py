"""Batch, read-only SQL access for professor analytics.

All aggregation is loaded in one query per endpoint snapshot.  The repository
never performs DDL or writes and never returns message bodies unless a selected
student detail needs its authorised transcript.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from backend.persistence.factory import create_student_store
from backend.source_library import CHAT_ATTACHMENT_ORIGIN, get_visible_source, is_chat_attachment_source
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

    def load_student_roster(self) -> list[dict[str, Any]]:
        """Return one compact aggregate row per student for the roster endpoint.

        Unlike ``load_class_rows``, this projection never materialises one Python
        row per active message.  It still evaluates active-branch predicates in
        SQL so superseded turns cannot affect roster signals.
        """
        query = """
            WITH eligible_users AS (
                SELECT id, display_name, email, created_at
                FROM users
                WHERE COALESCE(role, 'student') NOT IN ('lecturer', 'admin')
                  AND (identifier <> 'local-student' OR cognito_sub IS NOT NULL)
            ),
            active_messages AS (
                SELECT
                    n.user_id,
                    n.id AS notebook_id,
                    n.current_stage,
                    n.progress_text,
                    n.updated_at AS notebook_updated_at,
                    m.id AS message_id,
                    m.role AS message_role,
                    m.is_error AS message_is_error,
                    m.assessment_text,
                    m.created_at AS message_created_at
                FROM notebooks n
                JOIN eligible_users u ON u.id = n.user_id
                LEFT JOIN messages m ON m.notebook_id = n.id
                    AND COALESCE(m.conversation_revision, 0) <=
                        COALESCE(n.conversation_revision, 0)
                    AND (
                        m.superseded_at_revision IS NULL
                        OR m.superseded_at_revision >
                           COALESCE(n.conversation_revision, 0)
                    )
                    AND COALESCE(m.metadata_text, '') NOT LIKE
                        '%"_internal_type": "coach_idempotency"%'
            ),
            notebook_stats AS (
                SELECT
                    user_id,
                    notebook_id,
                    current_stage,
                    progress_text,
                    notebook_updated_at,
                    MAX(
                        CASE
                            WHEN message_role = 'user' AND NOT message_is_error
                            THEN message_created_at
                        END
                    ) AS last_user_at,
                    SUM(
                        CASE
                            WHEN message_role = 'user' AND NOT message_is_error
                            THEN 1 ELSE 0
                        END
                    ) AS notebook_student_messages
                FROM active_messages
                GROUP BY user_id, notebook_id, current_stage, progress_text,
                         notebook_updated_at
            ),
            ranked_notebooks AS (
                SELECT
                    ns.*,
                    ROW_NUMBER() OVER (
                        PARTITION BY user_id
                        ORDER BY
                            COALESCE(last_user_at, notebook_updated_at, '') DESC,
                            notebook_id DESC
                    ) AS notebook_rank
                FROM notebook_stats ns
            ),
            current_notebook AS (
                SELECT * FROM ranked_notebooks WHERE notebook_rank = 1
            ),
            latest_assessment AS (
                SELECT
                    am.user_id,
                    am.notebook_id,
                    am.assessment_text,
                    ROW_NUMBER() OVER (
                        PARTITION BY am.user_id, am.notebook_id
                        ORDER BY am.message_created_at DESC, am.message_id DESC
                    ) AS assessment_rank
                FROM active_messages am
                WHERE am.message_role = 'assistant'
                  AND NOT am.message_is_error
                  AND COALESCE(am.assessment_text, '') <> ''
            ),
            student_totals AS (
                SELECT
                    user_id,
                    SUM(
                        CASE
                            WHEN message_role = 'user' AND NOT message_is_error
                            THEN 1 ELSE 0
                        END
                    ) AS student_messages,
                    COUNT(
                        DISTINCT CASE
                            WHEN message_role = 'user' AND NOT message_is_error
                            THEN substr(message_created_at, 1, 10)
                        END
                    ) AS active_days,
                    MAX(
                        CASE
                            WHEN message_role = 'user' AND NOT message_is_error
                            THEN message_created_at
                        END
                    ) AS last_activity
                FROM active_messages
                GROUP BY user_id
            )
            SELECT
                u.id AS user_id,
                u.display_name,
                u.email,
                u.created_at AS user_created_at,
                cn.notebook_id AS current_notebook_id,
                cn.current_stage,
                cn.progress_text,
                COALESCE(cn.notebook_student_messages, 0) AS primary_student_messages,
                COALESCE(st.student_messages, 0) AS student_messages,
                COALESCE(st.active_days, 0) AS active_days,
                st.last_activity,
                la.assessment_text AS latest_assessment_text
            FROM eligible_users u
            LEFT JOIN current_notebook cn ON cn.user_id = u.id
            LEFT JOIN student_totals st ON st.user_id = u.id
            LEFT JOIN latest_assessment la
                ON la.user_id = u.id
               AND la.notebook_id = cn.notebook_id
               AND la.assessment_rank = 1
            ORDER BY u.display_name, u.id
        """
        try:
            with self._store._connect() as connection:  # noqa: SLF001 - repository boundary
                rows = connection.execute(query).fetchall()
        except Exception as error:
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

    def student_store(self, student_id: str) -> StudentStore | None:
        """Return an owner-scoped store for one authorised student.

        Preserves the configured database provider: SQLite when the analytics
        store has a path, DSQL when ``path`` is ``None``.
        """
        user = self._store.get_user_by_id(student_id)
        if not user:
            return None
        identifier = str(user.get("identifier") or "").strip()
        if not identifier:
            return None
        store_path = getattr(self._store, "path", None)
        if isinstance(store_path, Path) and store_path is not None:
            store = create_student_store(
                path=store_path,
                identifier=identifier,
                ensure_owner=False,
            )
        else:
            store = create_student_store(
                identifier=identifier,
                ensure_owner=False,
            )
        store.owner_id = str(user.get("id") or student_id)
        return store

    def notebook_owned(self, student_id: str, notebook_id: str) -> bool:
        """Return whether ``notebook_id`` belongs to ``student_id``."""
        query = "SELECT 1 FROM notebooks WHERE id=? AND user_id=? LIMIT 1"
        try:
            with self._store._connect() as connection:  # noqa: SLF001
                row = connection.execute(query, (notebook_id, student_id)).fetchone()
        except Exception as error:
            raise ProfessorAnalyticsUnavailable(
                "Professor analytics data is temporarily unavailable"
            ) from error
        return row is not None

    def read_library_source(
        self, student_id: str, notebook_id: str, source_id: str
    ) -> dict[str, Any] | None:
        """Return one library source after notebook ownership checks.

        Chat-attachment origins stay excluded because they require a message
        association and are served from the attachment route instead.
        """
        if not self.notebook_owned(student_id, notebook_id):
            return None
        store = self.student_store(student_id)
        if store is None:
            return None
        source = get_visible_source(
            store,
            notebook_id,
            source_id,
            include_extracted_text=False,
        )
        if source is None or is_chat_attachment_source(source):
            return None
        return source

    def authorized_citation_ids(
        self, student_id: str, notebook_id: str, source_ids: list[str]
    ) -> set[str]:
        """Return citation ids visible to the selected notebook.

        Personal library sources and shared/virtual course catalog sources are
        both resolved through the same ``list_visible_sources`` universe used
        by the workspace Sources tab.
        """
        ids = {str(item).strip() for item in source_ids if str(item).strip()}
        if not ids or not self.notebook_owned(student_id, notebook_id):
            return set()
        store = self.student_store(student_id)
        if store is None:
            return set()
        from backend.sources.library import list_visible_sources

        visible_ids = {
            str(source.get("id") or "")
            for source in list_visible_sources(
                store,
                notebook_id,
                include_extracted_text=False,
            )
            if str(source.get("id") or "").strip()
        }
        return ids & visible_ids

    @staticmethod
    def _row_dict(row: Any) -> dict[str, Any]:
        """Normalise SQLite rows and DSQL mapping/proxy rows into dictionaries."""
        if isinstance(row, dict):
            return dict(row)
        keys = getattr(row, "keys", None)
        if callable(keys):
            return {str(key): row[key] for key in keys()}
        return dict(row)
