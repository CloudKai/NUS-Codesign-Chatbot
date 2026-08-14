"""Owned source metadata operations shared by SQLite and DSQL stores."""

from __future__ import annotations

import uuid
from pathlib import Path
from typing import Any, Callable

from backend.persistence.store.contracts import StoreContext, dump_json, load_json, utc_now
from backend.settings import settings


class SourceOperations:
    """Read and mutate source metadata through a bound store context."""

    def __init__(self, store: StoreContext):
        self._store = store

    def load_extracted_text(self, extracted_text_key: str | None) -> str:
        """Load UTF-8 extracted text from configured object storage."""
        if not extracted_text_key:
            return ""
        from backend.persistence.factory import get_file_storage

        try:
            data = get_file_storage().get_bytes(str(extracted_text_key))
        except FileNotFoundError:
            return ""
        try:
            return data.decode("utf-8")
        except UnicodeDecodeError:
            return data.decode("utf-8", errors="replace")

    def add(
        self,
        thread_id: str,
        *,
        kind: str,
        title: str,
        mime: str = "text/plain",
        path: str | None = None,
        source_url: str | None = None,
        extracted_text_key: str | None = None,
        size: int = 0,
        selected: bool = True,
        metadata: dict[str, Any] | None = None,
        source_id: str | None = None,
        serialize: Callable[[Any], str] = dump_json,
    ) -> str:
        """Add source metadata after its content has been persisted."""
        if kind not in {"file", "image", "text", "url"}:
            raise ValueError("Unsupported source type")
        normalized_title = " ".join(title.strip().split())[:180]
        if not normalized_title:
            raise ValueError("Source title is required")
        metadata_dict = dict(metadata or {})
        object_key = metadata_dict.get("object_key") or None
        storage_provider = str(metadata_dict.get("storage_provider") or "local")
        if path:
            if storage_provider in {"s3", "memory"} or object_key:
                object_key = str(object_key or path)
                path = None
            else:
                resolved_path = Path(path).resolve()
                allowed_root = (settings.files_dir / "threads" / thread_id).resolve()
                if allowed_root not in resolved_path.parents:
                    raise ValueError("Unsafe source path")
                metadata_dict["local_path"] = str(resolved_path)
                path = None
        source_id = source_id or str(uuid.uuid4())
        stored_text_key = str(extracted_text_key or "").strip() or None
        now = utc_now()
        with self._store._lock, self._store._connect() as connection:
            owned = connection.execute(
                "SELECT id FROM notebooks WHERE id=? AND user_id=?",
                (thread_id, self._store.owner_id),
            ).fetchone()
            if not owned:
                raise ValueError("Notebook not found")
            connection.execute(
                """
                INSERT INTO sources
                  (id, notebook_id, kind, title, content_type, byte_size,
                   object_key, extracted_text_key, source_url, selected,
                   metadata_text, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    source_id,
                    thread_id,
                    kind,
                    normalized_title,
                    mime or "application/octet-stream",
                    max(0, int(size)),
                    object_key,
                    stored_text_key,
                    source_url,
                    int(selected),
                    serialize(metadata_dict),
                    now,
                    now,
                ),
            )
            connection.execute(
                "UPDATE notebooks SET updated_at=? WHERE id=? AND user_id=?",
                (now, thread_id, self._store.owner_id),
            )
        return source_id

    def list(
        self,
        thread_id: str,
        *,
        selected_only: bool = False,
        normalize: Callable[[Any], dict[str, Any]] | None = None,
    ) -> list[dict[str, Any]]:
        """List owned sources for one notebook."""
        if not self._store.get_thread(thread_id):
            return []
        selected_clause = " AND selected=1" if selected_only else ""
        with self._store._connect() as connection:
            rows = connection.execute(
                f"""
                SELECT s.* FROM sources s
                JOIN notebooks n ON n.id=s.notebook_id
                WHERE s.notebook_id=? AND n.user_id=?{selected_clause}
                ORDER BY s.created_at ASC, s.id ASC
                """,
                (thread_id, self._store.owner_id),
            ).fetchall()
        mapper = normalize or self.as_dict
        return [mapper(row) for row in rows]

    def get(
        self,
        thread_id: str,
        source_id: str,
        *,
        normalize: Callable[[Any], dict[str, Any]] | None = None,
    ) -> dict[str, Any] | None:
        """Return one owned source or ``None``."""
        with self._store._connect() as connection:
            row = connection.execute(
                """
                SELECT s.* FROM sources s
                JOIN notebooks n ON n.id=s.notebook_id
                WHERE s.id=? AND s.notebook_id=? AND n.user_id=?
                """,
                (source_id, thread_id, self._store.owner_id),
            ).fetchone()
        return (normalize or self.as_dict)(row) if row else None

    def find_by_path(
        self,
        thread_id: str,
        path: str,
        *,
        normalize: Callable[[Any], dict[str, Any]] | None = None,
    ) -> dict[str, Any] | None:
        """Find a source by object key or a legacy managed local path."""
        with self._store._connect() as connection:
            row = connection.execute(
                """
                SELECT s.* FROM sources s
                JOIN notebooks n ON n.id=s.notebook_id
                WHERE s.notebook_id=? AND n.user_id=?
                  AND (s.object_key=? OR s.metadata_text LIKE ?)
                """,
                (thread_id, self._store.owner_id, path, f"%{path}%"),
            ).fetchone()
        if not row:
            return None
        source = (normalize or self.as_dict)(row)
        if source.get("path") == path or source.get("object_key") == path:
            return source
        if (source.get("metadata") or {}).get("local_path") == path:
            return source
        return None

    def as_dict(
        self,
        row: Any,
        *,
        deserialize: Callable[[str | None, Any], Any] = load_json,
        load_extracted: Callable[[str | None], str] | None = None,
    ) -> dict[str, Any]:
        """Normalize one source row while preserving legacy response keys."""
        metadata = deserialize(row["metadata_text"], {})
        if not isinstance(metadata, dict):
            metadata = {}
        legacy_extracted = str(metadata.pop("_legacy_extracted_text", "") or "")
        object_key = row["object_key"]
        local_path = metadata.get("local_path")
        extracted = (load_extracted or self.load_extracted_text)(
            row["extracted_text_key"]
        )
        if not extracted:
            extracted = legacy_extracted
        path_value = object_key or local_path
        if object_key and metadata.get("storage_provider") not in {"s3", "memory"}:
            if settings.file_storage_provider != "local":
                metadata.setdefault("storage_provider", settings.file_storage_provider)
                metadata.setdefault("object_key", object_key)
        return {
            "id": str(row["id"]),
            "threadId": str(row["notebook_id"]),
            "notebook_id": str(row["notebook_id"]),
            "ownerId": self._store.owner_id,
            "kind": row["kind"],
            "title": row["title"],
            "mime": row["content_type"] or "application/octet-stream",
            "content_type": row["content_type"],
            "path": path_value,
            "object_key": object_key,
            "extracted_text_key": row["extracted_text_key"],
            "sourceUrl": row["source_url"],
            "extractedText": extracted,
            "size": int(row["byte_size"] or 0),
            "byte_size": int(row["byte_size"] or 0),
            "selected": bool(row["selected"]),
            "metadata": metadata,
            "createdAt": row["created_at"],
            "updatedAt": row["updated_at"],
        }

    def set_selected(
        self,
        thread_id: str,
        source_id: str,
        selected: bool,
        *,
        source: dict[str, Any] | None = None,
    ) -> None:
        """Toggle one personal source selection flag."""
        from backend.source_library import is_locked_course_source

        source = source if source is not None else self.get(thread_id, source_id)
        if not source:
            raise ValueError("Source not found")
        if is_locked_course_source(source):
            if not selected:
                raise ValueError("Course materials stay selected and cannot be unselected.")
            if source.get("selected"):
                return
        with self._store._lock, self._store._connect() as connection:
            changed = connection.execute(
                """
                UPDATE sources SET selected=?, updated_at=?
                WHERE id=? AND notebook_id=? AND notebook_id IN (
                  SELECT id FROM notebooks WHERE id=? AND user_id=?
                )
                """,
                (
                    int(selected),
                    utc_now(),
                    source_id,
                    thread_id,
                    thread_id,
                    self._store.owner_id,
                ),
            ).rowcount
        if not changed:
            raise ValueError("Source not found")

    def set_all_selected(
        self,
        thread_id: str,
        selected: bool,
        *,
        deserialize: Callable[[str | None, Any], Any] = load_json,
    ) -> None:
        """Select or deselect personal sources while retaining course materials."""
        from backend.source_library import is_locked_course_source

        if not self._store.get_thread(thread_id):
            raise ValueError("Notebook not found")
        now = utc_now()
        with self._store._lock, self._store._connect() as connection:
            rows = connection.execute(
                "SELECT id, selected, metadata_text FROM sources WHERE notebook_id=?",
                (thread_id,),
            ).fetchall()
            for row in rows:
                metadata = deserialize(row["metadata_text"], {})
                if not isinstance(metadata, dict):
                    metadata = {}
                locked = is_locked_course_source(
                    {"metadata": metadata, "selected": bool(row["selected"])}
                )
                if locked:
                    if not bool(row["selected"]):
                        connection.execute(
                            """
                            UPDATE sources SET selected=1, updated_at=?
                            WHERE id=? AND notebook_id=?
                            """,
                            (now, row["id"], thread_id),
                        )
                    continue
                connection.execute(
                    """
                    UPDATE sources SET selected=?, updated_at=?
                    WHERE id=? AND notebook_id=?
                    """,
                    (int(selected), now, row["id"], thread_id),
                )

    def rename(
        self,
        thread_id: str,
        source_id: str,
        title: str,
        *,
        source: dict[str, Any] | None = None,
    ) -> None:
        """Rename a personal source while keeping course resources immutable."""
        source = source if source is not None else self.get(thread_id, source_id)
        if not source:
            raise ValueError("Source not found")
        if (source.get("metadata") or {}).get("locked_source"):
            raise ValueError("Course materials cannot be renamed.")
        normalized_title = " ".join(title.strip().split())[:180]
        if not normalized_title:
            raise ValueError("Source title is required")
        with self._store._lock, self._store._connect() as connection:
            connection.execute(
                """
                UPDATE sources SET title=?, updated_at=?
                WHERE id=? AND notebook_id=?
                """,
                (normalized_title, utc_now(), source_id, thread_id),
            )

    def delete(
        self,
        thread_id: str,
        source_id: str,
        *,
        force: bool = False,
        source: dict[str, Any] | None = None,
        cleanup_local: Callable[..., None] | None = None,
        cleanup_prefix: Callable[[str, str], None] | None = None,
    ) -> None:
        """Delete source metadata then clean its managed content."""
        source = source if source is not None else self.get(thread_id, source_id)
        if source:
            metadata = source.get("metadata") or {}
            if metadata.get("locked_source") and not force:
                raise ValueError("Course materials cannot be removed from the app.")
            with self._store._lock, self._store._connect() as connection:
                connection.execute(
                    """
                    DELETE FROM sources
                    WHERE id=? AND notebook_id=?
                      AND notebook_id IN (
                        SELECT id FROM notebooks WHERE id=? AND user_id=?
                      )
                    """,
                    (source_id, thread_id, thread_id, self._store.owner_id),
                )
            (cleanup_local or self.cleanup_local_file)(source, thread_id=thread_id)
        (cleanup_prefix or self.cleanup_object_prefix)(thread_id, source_id)

    def cleanup_object_prefix(self, thread_id: str, source_id: str) -> None:
        """Delete keys derived only from the authenticated owner's source prefix."""
        from backend.persistence.factory import get_file_storage
        from backend.persistence.object_keys import source_prefix

        get_file_storage().delete_prefix(
            source_prefix(
                user_id=self._store.owner_id,
                notebook_id=thread_id,
                source_id=source_id,
            )
        )

    def cleanup_local_file(
        self,
        source: dict[str, Any],
        *,
        thread_id: str,
    ) -> None:
        """Remove a managed legacy file only from its owned notebook root."""
        metadata = source.get("metadata") or {}
        local_path = metadata.get("local_path")
        if not (local_path and metadata.get("managed_file")):
            return
        path = Path(str(local_path)).resolve()
        allowed_root = (settings.files_dir / "threads" / thread_id).resolve()
        if path.is_file() and allowed_root in path.parents:
            path.unlink(missing_ok=True)
