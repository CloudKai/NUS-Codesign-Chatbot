"""Application service for notebook, history, source, and preference CRUD.

Keeps Streamlit and FastAPI on one persistence path while ``StudentStore``
(or ``DsqlStudentStore``) remains the persistence adapter. Source file bytes
are read here via ``read_source_bytes`` so the UI never touches storage paths
directly.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

from .learning.deep_analysis_pdf import (
    DeepAnalysisPdfExport,
    build_deep_analysis_pdf,
)
from .persistence.object_keys import sanitize_filename
from .source_library import (
    CourseMaterialSyncCoordinator,
    LectureNotesSyncResult,
    add_file_sources,
    backfill_legacy_sources,
    CHAT_ATTACHMENT_ORIGIN,
    get_visible_source,
    is_locked_course_source,
    list_visible_sources,
    read_source_bytes,
)
from .specialists.review_orchestration import (
    DEEP_REVIEW_SNAPSHOT_KEY,
    JOURNEY_STAGE_REVIEWS_KEY,
    explicit_deep_review_available,
    public_journey_stage_reviews,
)
from .student_journey import normalize_journey
from .student_store import StudentStore
from .learning_signals import LearningReceipts
from .sources.library import private_library_sources

_TRANSCRIPT_ROLES = {"user": "Student", "assistant": "Coach"}
MESSAGE_PAGE_SIZE = 6


@dataclass(frozen=True)
class SourceContent:
    """Binary payload for source preview or download."""

    data: bytes
    mime: str
    filename: str


@dataclass(frozen=True)
class TranscriptExport:
    """UTF-8 chat transcript projected from persisted notebook messages."""

    data: bytes
    filename: str
    mime: str = "text/plain; charset=utf-8"


def public_attachment(source: dict[str, Any]) -> dict[str, Any]:
    """Return the small safe descriptor stored on a chat message."""
    return {
        "id": str(source.get("id") or ""),
        "title": str(source.get("title") or "Attachment"),
        "mime": str(source.get("mime") or "application/octet-stream"),
        "kind": str(source.get("kind") or "file"),
        "size": max(0, int(source.get("size") or 0)),
    }


def format_notebook_transcript(
    *,
    title: str,
    messages: Iterable[dict[str, Any]],
) -> str:
    """Render visible chat turns as a student-readable ``.txt`` transcript.

    The text is a projection of ``get_messages`` only. It omits assessments,
    research coding, and other metadata so the download is not a second
    message store.

    Args:
        title: Notebook title shown at the top of the file.
        messages: Active-branch message dicts from the student store.

    Returns:
        UTF-8 transcript text ending in a newline.
    """
    heading = str(title or "").strip() or "Untitled notebook"
    lines = [heading, ""]
    for message in messages:
        role = str(message.get("role") or "").strip().lower()
        content = str(message.get("content") or "").strip()
        label = _TRANSCRIPT_ROLES.get(role)
        if label is None or not content:
            continue
        lines.append(f"{label}:")
        lines.append(content)
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def transcript_filename(title: str) -> str:
    """Return a path-safe ``.txt`` basename derived from the notebook title.

    Args:
        title: Notebook title, which may contain spaces or unsafe characters.

    Returns:
        A sanitized filename ending in ``-transcript.txt``.
    """
    stem = str(title or "").strip() or "Untitled notebook"
    return sanitize_filename(f"{stem}-transcript.txt")


def public_source(source: dict[str, Any]) -> dict[str, Any]:
    """Return a source record safe for API/UI consumers (no filesystem path)."""
    payload = {
        key: value
        for key, value in source.items()
        if key not in {"path", "object_key", "extracted_text_key", "local_path"}
    }
    # Keep extracted text for grounding/UI; strip storage keys only.
    meta = dict(payload.get("metadata") or {})
    meta.pop("object_key", None)
    meta.pop("local_path", None)
    payload["metadata"] = meta
    payload["has_file"] = bool(
        source.get("path") or source.get("object_key") or meta.get("local_path")
    )
    return payload


def professor_public_source(source: dict[str, Any]) -> dict[str, Any]:
    """Return a source record safe for lecturer read-only workspace views.

    Lecturer APIs must not expose extracted text, storage keys, or filesystem
    paths. File bytes are served only from the dedicated source endpoint.
    """
    payload = public_source(source)
    payload.pop("extracted_text", None)
    return payload


def public_notebook_metadata(metadata: Any) -> dict[str, Any]:
    """Return notebook metadata without internal Journey worker state.

    Queue ids, dirty tokens, frozen transcript ids, and lease fields are
    persistence/worker details. All notebook-facing API routes share this
    projection so a broader thread or learning-state response cannot bypass
    the dedicated Journey review projection.
    """
    payload = dict(metadata) if isinstance(metadata, dict) else {}
    if JOURNEY_STAGE_REVIEWS_KEY in payload:
        payload[JOURNEY_STAGE_REVIEWS_KEY] = public_journey_stage_reviews(
            payload.get(JOURNEY_STAGE_REVIEWS_KEY)
        )
    return payload


def public_thread(thread: dict[str, Any]) -> dict[str, Any]:
    """Return a notebook record for API/UI consumers."""
    payload = dict(thread)
    payload["metadata"] = public_notebook_metadata(payload.get("metadata"))
    return payload


class WorkspaceService:
    """Coordinate notebook workspace CRUD over the local SQLite store."""

    def __init__(
        self,
        store: StudentStore,
        course_sync: CourseMaterialSyncCoordinator | None = None,
    ) -> None:
        self._store = store
        self._course_sync = course_sync or CourseMaterialSyncCoordinator()

    @property
    def store(self) -> StudentStore:
        """Expose the underlying store for legacy engine wiring only."""
        return self._store

    def get_preferences(self) -> dict[str, Any]:
        """Return the local user preference blob."""
        return self._store.get_user_preferences() or {}

    def update_preferences(self, patch: dict[str, Any]) -> dict[str, Any]:
        """Merge preference keys and return the updated blob."""
        self._store.update_user_preferences(patch)
        return self.get_preferences()

    def list_threads(self, search: str = "") -> list[dict[str, Any]]:
        """List notebooks for the local student, newest activity first."""
        return [public_thread(thread) for thread in self._store.list_threads(search, None)]

    def get_thread(self, thread_id: str) -> dict[str, Any] | None:
        """Return one owned notebook or ``None``."""
        thread = self._store.get_thread(thread_id)
        return public_thread(thread) if thread and not (thread.get("metadata") or {}).get("reader_library") else None

    def get_artifact(self, thread_id: str, artifact_id: str) -> dict[str, Any]:
        """Return an artifact only from the requested owned notebook, or raise LookupError."""
        artifact = self._store.get_artifact(artifact_id)
        if artifact is None or artifact["thread_id"] != thread_id:
            raise LookupError("Artifact not found")
        return artifact

    def deep_review_available(self, thread_id: str) -> bool:
        """Return persisted Thinking Path eligibility or raise for a missing notebook."""
        thread = self.get_thread(thread_id)
        if thread is None:
            raise LookupError("Notebook not found")
        journey = normalize_journey(thread["metadata"].get("learning_journey"))
        return explicit_deep_review_available(completed_stages=journey.get("completed_stages") or [])

    def save_artifact(
        self, thread_id: str, artifact_id: str, document: dict[str, Any], revision: int,
        title: str | None, references: list[dict[str, Any]] | None,
    ) -> dict[str, Any]:
        """Save the seen artifact revision in its owned notebook or propagate a conflict."""
        self.get_artifact(thread_id, artifact_id)
        return self._store.update_artifact(artifact_id, document, revision, title, references=references)

    def get_canvas(self, thread_id: str, canvas_id: str) -> dict[str, Any]:
        """Return a canvas only from the requested owned notebook, or raise LookupError."""
        canvas = self._store.get_canvas(canvas_id)
        if canvas is None or canvas["thread_id"] != thread_id:
            raise LookupError("Canvas not found")
        return canvas

    def save_canvas(
        self, thread_id: str, canvas_id: str, graph: dict[str, Any], revision: int, title: str | None,
    ) -> dict[str, Any]:
        """Save the seen canvas revision in its owned notebook or propagate a conflict."""
        self.get_canvas(thread_id, canvas_id)
        return self._store.update_canvas(canvas_id, graph, revision, title)

    def delete_canvas(
        self, thread_id: str, canvas_id: str, revision: int, confirmed: bool,
    ) -> dict[str, Any]:
        """Delete a confirmed canvas revision and return its previous projection for the caller."""
        canvas = self.get_canvas(thread_id, canvas_id)
        self._store.delete_canvas(canvas_id, revision, confirmed)
        return canvas

    def create_thread(
        self,
        *,
        name: str,
        model_id: str,
        support_mode: str,
        assignment: dict[str, str] | None = None,
        metadata: dict[str, Any] | None = None,
        quick_chat: bool = False,
        reader_notebook: bool = False,
        parent_notebook_id: str | None = None,
    ) -> dict[str, Any]:
        """Create an owned notebook or quick chat and optionally merge initial metadata."""
        thread_id = self._store.create_thread(
            name=name,
            model_id=model_id,
            support_mode=support_mode,
            assignment=assignment,
            quick_chat=quick_chat,
            reader_notebook=reader_notebook,
            parent_notebook_id=parent_notebook_id,
        )
        if metadata:
            self._store.update_thread(thread_id, metadata=metadata)
        thread = self.get_thread(thread_id)
        if not thread:
            raise ValueError("Notebook not found")
        return thread

    def update_thread(
        self,
        thread_id: str,
        *,
        name: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Rename a notebook and/or merge metadata."""
        if not self._store.get_thread(thread_id):
            raise ValueError("Notebook not found")
        self._store.update_thread(thread_id, name=name, metadata=metadata)
        thread = self.get_thread(thread_id)
        if not thread:
            raise ValueError("Notebook not found")
        return thread

    def delete_thread(self, thread_id: str) -> None:
        """Idempotently delete a notebook and retry its owned-file cleanup.

        The store derives cleanup prefixes from its authenticated owner context.
        Calling through when the row is already absent lets a repeated API
        DELETE retry object-storage cleanup that failed after the DB commit.
        The public API still reports an absent/foreign notebook as not found
        after that safe owner-scoped cleanup attempt.
        """
        existing = self._store.get_thread(thread_id)
        if (existing or {}).get("metadata", {}).get("reader_library"):
            raise ValueError("Notebook not found")
        existed = existing is not None
        self._store.delete_thread(thread_id)
        if not existed:
            raise ValueError("Notebook not found")

    def get_active_message(self, thread_id: str, message_id: str) -> dict[str, Any] | None:
        """Return one active owned message for saved-evidence authorization."""
        return self._store.get_active_message(thread_id, message_id)

    def get_messages(self, thread_id: str) -> list[dict[str, Any]]:
        """Return canonical chat history for a notebook."""
        if not self._store.get_thread(thread_id):
            raise ValueError("Notebook not found")
        return self._store.get_messages(thread_id)

    def get_message_bookmarks(self, thread_id: str) -> tuple[int, list[dict[str, Any]]]:
        """Return active owned bookmarks and revision independently of transcript paging."""
        return self._store.get_message_bookmarks(thread_id)

    def set_message_star(self, thread_id: str, message_id: str, starred: bool) -> bool:
        """Persist the owner's desired star state on an active saved message."""
        return self._store.set_message_star(thread_id, message_id, starred)

    def record_learning_signal(self, thread_id: str, message_id: str, kind: str) -> LearningReceipts:
        """Persist one validated explicit rating or UI receipt on an owned answer."""
        return LearningReceipts.model_validate(self._store.record_learning_signal(thread_id, message_id, kind))

    def has_messages(self, thread_id: str) -> bool:
        """Return whether an owned notebook has any visible chat rows."""
        return self._store.has_messages(thread_id)

    def get_message_page(
        self,
        thread_id: str,
        *,
        limit: int = MESSAGE_PAGE_SIZE,
        cursor: str | None = None,
    ) -> dict[str, Any]:
        """Return one bounded, revision-bound page of notebook history."""
        return self._store.get_message_page(
            thread_id,
            limit=limit,
            cursor=cursor,
        )

    def get_messages_page(
        self,
        thread_id: str,
        *,
        limit: int = MESSAGE_PAGE_SIZE,
        cursor: str | None = None,
    ) -> dict[str, Any]:
        """Compatibility alias for :meth:`get_message_page`."""
        return self.get_message_page(thread_id, limit=limit, cursor=cursor)

    def get_message_metadata(self, thread_id: str) -> list[dict[str, Any]]:
        """Return active message metadata without transcript bodies."""
        return self._store.get_message_metadata(thread_id)

    def get_oldest_user_messages(
        self, thread_id: str, *, limit: int = 2
    ) -> list[str]:
        """Return at most two oldest active user prompts for title migration."""
        return self._store.get_oldest_user_messages(thread_id, limit=limit)

    def export_transcript(self, thread_id: str) -> TranscriptExport:
        """Return a ``.txt`` transcript projected from persisted messages.

        Args:
            thread_id: Owned notebook id.

        Returns:
            Filename and UTF-8 bytes built from the active ``messages`` rows.

        Raises:
            ValueError: When the notebook is missing or not owned.
        """
        thread = self._store.get_thread(thread_id)
        if not thread:
            raise ValueError("Notebook not found")
        title = str(thread.get("name") or "").strip() or "Untitled notebook"
        text = format_notebook_transcript(
            title=title,
            messages=self._store.get_messages(thread_id),
        )
        return TranscriptExport(
            data=text.encode("utf-8"),
            filename=transcript_filename(title),
        )

    def export_deep_analysis_pdf(self, thread_id: str) -> DeepAnalysisPdfExport:
        """Return a PDF built from the notebook's Sonnet Deep Review snapshot.

        Args:
            thread_id: Owned notebook id.

        Returns:
            PDF bytes and download filename.

        Raises:
            ValueError: When the notebook is missing/not owned, or no usable
                Deep Review snapshot has been persisted yet.
        """
        thread = self._store.get_thread(thread_id)
        if not thread:
            raise ValueError("Notebook not found")
        metadata = dict(thread.get("metadata") or {})
        snapshot = metadata.get(DEEP_REVIEW_SNAPSHOT_KEY)
        if not isinstance(snapshot, dict) or not snapshot:
            raise ValueError("Deep Analysis PDF is not ready yet")
        title = str(thread.get("name") or "").strip() or "Untitled notebook"
        journey = normalize_journey(metadata.get("learning_journey"))
        return build_deep_analysis_pdf(
            title=title,
            snapshot=snapshot,
            journey=journey,
        )

    def get_messages_at_revision(
        self, thread_id: str, revision: int
    ) -> list[dict[str, Any]]:
        """Return chat history active at a conversation revision snapshot."""
        return self._store.get_messages_at_revision(thread_id, revision)

    def add_message(
        self,
        thread_id: str,
        role: str,
        content: str,
        *,
        metadata: dict[str, Any] | None = None,
    ) -> str:
        """Persist one chat message (used for coach welcome seeding)."""
        return self._store.add_message(
            thread_id, role, content, metadata=metadata
        )

    def list_sources(
        self, thread_id: str, *, selected_only: bool = False, include_extracted_text: bool = True
    ) -> list[dict[str, Any]]:
        """List notebook sources without exposing filesystem paths.

        Shared Lecture Notes/Readings are projected from the course catalog
        and are not inserted as per-notebook ``sources`` rows.
        """
        thread = self._store.get_thread(thread_id)
        if not thread:
            raise ValueError("Notebook not found")
        return [
            public_source(source)
            for source in list_visible_sources(
                self._store, thread_id, selected_only=selected_only, include_extracted_text=include_extracted_text,
                thread_metadata=thread.get("metadata") or {},
            )
        ]

    def get_source(self, thread_id: str, source_id: str) -> dict[str, Any] | None:
        """Return one source without a filesystem path."""
        source = get_visible_source(self._store, thread_id, source_id)
        return public_source(source) if source else None

    def upload_sources(
        self,
        thread_id: str,
        uploads: Iterable[tuple[str, bytes, str | None]],
        *,
        origin: str = "source_panel",
    ) -> list[dict[str, Any]]:
        """Store uploaded files as notebook sources."""
        if not self._store.get_thread(thread_id):
            raise ValueError("Notebook not found")
        created = add_file_sources(
            self._store, thread_id, uploads, origin=origin
        )
        if created:
            # Complete the existing Library grounding switch even if the tab
            # closes before its next progress poll.
            self._store.update_thread(thread_id, metadata={"allow_model_knowledge": False})
        return [public_source(source) for source in created]

    def upload_attachments(
        self,
        thread_id: str,
        uploads: Iterable[tuple[str, bytes, str | None]],
    ) -> list[dict[str, Any]]:
        """Store private current-turn attachments outside the Sources library."""
        if not self._store.get_thread(thread_id):
            raise ValueError("Notebook not found")
        created = add_file_sources(
            self._store,
            thread_id,
            uploads,
            origin=CHAT_ATTACHMENT_ORIGIN,
            selected=False,
            extra_metadata={"hidden_from_sources": True},
        )
        return [public_attachment(source) for source in created]

    def library_sources(self, source_ids: list[str] | None = None, *,
                        include_extracted_text: bool = False) -> list[dict[str, Any]]:
        """List this owner's library, optionally retrieving exact source IDs and text."""
        return private_library_sources(self._store, source_ids, include_extracted_text=include_extracted_text)

    def upload_library_files(self, uploads: Iterable[tuple[str, bytes, str | None]], *,
                             thread_id: str | None = None, attachment: bool = False) -> list[dict[str, Any]]:
        """Save a single original per upload and optionally link it to notebook Sources."""
        if thread_id is not None and self.get_thread(thread_id) is None:
            raise ValueError("Notebook not found")
        if attachment and thread_id is None:
            raise ValueError("Chat not found")
        created = add_file_sources(
            self._store, self._store.ensure_library_thread(), uploads,
            origin=CHAT_ATTACHMENT_ORIGIN if attachment else "source_panel",
            selected=False,
            compress=False,
            extra_metadata={
                "reader_checked_upload": True,
                **({"reader_attachment_thread": thread_id} if attachment else {}),
            },
        )
        if thread_id is not None and not attachment:
            for source in created:
                self._store.set_reader_source_link(thread_id, source["id"], True)
        return [public_attachment(source) for source in created]

    def set_library_link(self, thread_id: str, source_id: str, selected: bool | None, *,
                         require_link: bool = False) -> None:
        """Attach, enable, disable or detach an owned source without deleting its bytes."""
        matches = self.library_sources([source_id])
        if not matches or (require_link and not any(
            row["id"] == source_id for row in self.list_sources(thread_id, include_extracted_text=False)
        )):
            raise ValueError("Source not found")
        self._store.set_reader_source_link(thread_id, source_id, selected)

    def delete_library_source(self, source_id: str) -> None:
        """Permanently delete one owned original; linked projections will no longer resolve."""
        matches = self.library_sources([source_id])
        if not matches:
            raise ValueError("Source not found")
        self._store.delete_source(matches[0]["threadId"], source_id)

    def read_library_source(self, source_id: str) -> SourceContent:
        """Read an owned original independently of current notebook membership."""
        matches = self.library_sources([source_id], include_extracted_text=True)
        return self._source_content(matches[0] if matches else None)

    def set_source_selected(
        self, thread_id: str, source_id: str, selected: bool
    ) -> dict[str, Any]:
        """Toggle one source selection flag."""
        self._store.set_source_selected(thread_id, source_id, selected)
        source = self.get_source(thread_id, source_id)
        if not source:
            raise ValueError("Source not found")
        return source

    def set_all_sources_selected(self, thread_id: str, selected: bool) -> list[dict[str, Any]]:
        """Select or deselect personal sources; locked course materials stay on."""
        self._store.set_all_sources_selected(thread_id, selected)
        return self.list_sources(thread_id)

    def rename_source(self, thread_id: str, source_id: str, title: str) -> dict[str, Any]:
        """Rename a non-locked source."""
        self._store.rename_source(thread_id, source_id, title)
        source = self.get_source(thread_id, source_id)
        if not source:
            raise ValueError("Source not found")
        return source

    def delete_source(self, thread_id: str, source_id: str) -> None:
        """Idempotently delete a source and retry owner-scoped prefix cleanup.

        Existing source metadata still enforces ownership and locked-course
        rules in the store. An absent row is treated as a cleanup retry, then
        reported as not found so cross-user deletes keep their existing API
        semantics.
        """
        existed = self._store.get_source(thread_id, source_id) is not None
        if not existed:
            virtual = get_visible_source(self._store, thread_id, source_id)
            if virtual and is_locked_course_source(virtual):
                raise ValueError("Course materials cannot be removed")
        self._store.delete_source(thread_id, source_id)
        if not existed:
            raise ValueError("Source not found")

    def read_source_content(self, thread_id: str, source_id: str) -> SourceContent:
        """Read source file bytes for preview/download via local or object storage."""
        return self._source_content(get_visible_source(self._store, thread_id, source_id))

    @staticmethod
    def _source_content(source: dict[str, Any] | None) -> SourceContent:
        """Build a safe download from an already authorized source row."""
        if not source:
            raise ValueError("Source not found")
        data = read_source_bytes(source)
        if data is None and source.get("kind") == "text":
            # Pasted notes have extracted text, but no original uploaded object.
            data = str(source.get("extractedText") or "").encode("utf-8")
        if data is None:
            raise ValueError("Source file is not available")
        mime = str(source.get("mime") or "application/octet-stream")
        filename = Path(str(source.get("title") or "download")).name or "download"
        return SourceContent(data=data, mime=mime, filename=filename)

    def backfill_legacy_sources(self, thread_id: str) -> int:
        """Import legacy message attachments into the source library."""
        if not self._store.get_thread(thread_id):
            raise ValueError("Notebook not found")
        return backfill_legacy_sources(self._store, thread_id)

    def sync_course_materials(self, thread_id: str) -> LectureNotesSyncResult:
        """Run (or join) course-material synchronization for one notebook."""
        if not self._store.get_thread(thread_id):
            raise ValueError("Notebook not found")
        future = self._course_sync.request(self._store, thread_id)
        return future.result()
