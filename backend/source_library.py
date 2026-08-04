from __future__ import annotations

import base64
import ipaddress
import mimetypes
import re
import socket
import threading
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import dataclass
from html.parser import HTMLParser
from pathlib import Path
from typing import Any, Iterable
from urllib.error import HTTPError, URLError
from urllib.parse import urljoin, urlparse
from urllib.request import HTTPRedirectHandler, Request, build_opener

from .file_processing import (
    IMAGE_SUFFIXES,
    SUPPORTED_SUFFIXES,
    extract_text,
    save_uploads,
)
from .settings import settings
from .student_store import StudentStore


MAX_SOURCE_TEXT = 120_000
MAX_COMBINED_CONTEXT = 160_000
MAX_WEB_BYTES = 5 * 1024 * 1024
WEB_TIMEOUT_SECONDS = 10
LECTURE_NOTES_README = "README.txt"
COURSE_MATERIAL_GROUPS = ("Lecture Notes", "Readings")
_COURSE_MATERIAL_SYNC_LOCK = threading.RLock()


class SourceImportError(ValueError):
    """A source could not be imported safely or usefully."""


@dataclass(frozen=True)
class LectureNotesSyncResult:
    """Summary of one notebook's safe lecture-notes folder synchronization."""

    added: int = 0
    updated: int = 0
    removed: int = 0
    unchanged: int = 0
    skipped: int = 0
    errors: tuple[str, ...] = ()


def course_material_fingerprint() -> tuple[tuple[str, int, int], ...]:
    """Return the stable file signature used to coordinate background imports."""
    root = settings.lecture_notes_dir.resolve()
    root.mkdir(parents=True, exist_ok=True)
    fingerprint: list[tuple[str, int, int]] = []
    for path in sorted(root.rglob("*")):
        if not path.is_file() or path.is_symlink():
            continue
        relative = path.relative_to(root)
        if path.name == LECTURE_NOTES_README or any(
            part.startswith(".") for part in relative.parts
        ):
            continue
        if path.suffix.lower() not in SUPPORTED_SUFFIXES:
            continue
        try:
            stat = path.stat()
        except OSError:
            continue
        if stat.st_size > settings.max_course_material_size_mb * 1024 * 1024:
            continue
        fingerprint.append((relative.as_posix(), stat.st_size, stat.st_mtime_ns))
        if len(fingerprint) >= settings.max_lecture_notes:
            break
    return tuple(fingerprint)


class CourseMaterialSyncCoordinator:
    """Run one course-material import per notebook and file-system snapshot.

    Repeated Streamlit refreshes share the same future, so a second render
    cannot import the same files while the first import is still in progress.
    """

    def __init__(self) -> None:
        self._executor = ThreadPoolExecutor(
            max_workers=1,
            thread_name_prefix="course-material-sync",
        )
        self._lock = threading.RLock()
        self._jobs: dict[
            tuple[str, str, str],
            tuple[tuple[tuple[str, int, int], ...], Future[LectureNotesSyncResult]],
        ] = {}

    @staticmethod
    def _key(store: StudentStore, thread_id: str) -> tuple[str, str, str]:
        return str(store.path), store.identifier, thread_id

    @staticmethod
    def _matches_snapshot(
        store: StudentStore,
        thread_id: str,
        fingerprint: tuple[tuple[str, int, int], ...],
    ) -> bool:
        expected_paths = {item[0] for item in fingerprint}
        actual_paths = [
            str((source.get("metadata") or {}).get("lecture_note_relative_path"))
            for source in store.list_sources(thread_id)
            if (source.get("metadata") or {}).get("origin") == "lecture_notes_folder"
        ]
        return len(actual_paths) == len(expected_paths) and set(actual_paths) == expected_paths

    def request(
        self,
        store: StudentStore,
        thread_id: str,
    ) -> Future[LectureNotesSyncResult]:
        """Return the shared import future for the notebook's current file snapshot."""
        fingerprint = course_material_fingerprint()
        key = self._key(store, thread_id)
        with self._lock:
            existing = self._jobs.get(key)
            if existing and existing[0] == fingerprint:
                future = existing[1]
                if not future.done():
                    return future
                try:
                    result = future.result()
                except Exception:
                    result = None
                if result and (
                    result.errors
                    or self._matches_snapshot(store, thread_id, fingerprint)
                ):
                    return future

            if not fingerprint and self._matches_snapshot(store, thread_id, fingerprint):
                completed: Future[LectureNotesSyncResult] = Future()
                completed.set_result(LectureNotesSyncResult())
                self._jobs[key] = (fingerprint, completed)
                return completed

            future = self._executor.submit(sync_lecture_notes_folder, store, thread_id)
            self._jobs[key] = (fingerprint, future)
            return future


def course_material_group(relative_path: str) -> str:
    """Classify a course file by its folder or filename without moving it."""
    lowered_parts = [part.lower() for part in Path(relative_path).parts]
    if any("reading" in part for part in lowered_parts):
        return "Readings"
    return "Lecture Notes"


def is_locked_course_source(source: dict[str, Any]) -> bool:
    """Return whether a synchronized course source is read-only in the UI."""
    metadata = source.get("metadata") or {}
    return bool(metadata.get("locked_source")) and (
        metadata.get("origin") == "lecture_notes_folder"
    )


class _ReadableHTML(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.title = ""
        self._in_title = False
        self._ignored_depth = 0
        self._parts: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        lowered = tag.lower()
        if lowered == "title":
            self._in_title = True
        if lowered in {"script", "style", "svg", "noscript", "template"}:
            self._ignored_depth += 1
        if lowered in {"p", "br", "li", "h1", "h2", "h3", "h4", "blockquote", "tr"}:
            self._parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        lowered = tag.lower()
        if lowered == "title":
            self._in_title = False
        if lowered in {"script", "style", "svg", "noscript", "template"}:
            self._ignored_depth = max(0, self._ignored_depth - 1)
        if lowered in {"p", "li", "h1", "h2", "h3", "h4", "blockquote", "tr"}:
            self._parts.append("\n")

    def handle_data(self, data: str) -> None:
        if self._ignored_depth:
            return
        if self._in_title:
            self.title += data
        self._parts.append(data)

    def text(self) -> str:
        value = "".join(self._parts)
        value = re.sub(r"[ \t\f\v]+", " ", value)
        value = re.sub(r"\n\s*\n\s*\n+", "\n\n", value)
        return value.strip()


def validate_public_url(
    url: str,
    *,
    resolver: Any = socket.getaddrinfo,
) -> str:
    normalized = url.strip()
    parsed = urlparse(normalized)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise SourceImportError("Enter a public http or https webpage URL.")
    if parsed.username or parsed.password:
        raise SourceImportError("URLs containing credentials are not allowed.")
    try:
        default_port = 443 if parsed.scheme == "https" else 80
        records = resolver(
            parsed.hostname,
            parsed.port or default_port,
            type=socket.SOCK_STREAM,
        )
    except OSError as exc:
        raise SourceImportError("The webpage address could not be resolved.") from exc
    if not records:
        raise SourceImportError("The webpage address could not be resolved.")
    for record in records:
        address = ipaddress.ip_address(record[4][0])
        if (
            address.is_private
            or address.is_loopback
            or address.is_link_local
            or address.is_multicast
            or address.is_reserved
            or address.is_unspecified
        ):
            raise SourceImportError("Private or local network URLs are not allowed.")
    return normalized


class _SafeRedirectHandler(HTTPRedirectHandler):
    def redirect_request(
        self,
        req: Request,
        fp: Any,
        code: int,
        msg: str,
        headers: Any,
        newurl: str,
    ) -> Request | None:
        safe_url = validate_public_url(urljoin(req.full_url, newurl))
        return super().redirect_request(req, fp, code, msg, headers, safe_url)


def fetch_public_webpage(
    url: str,
    *,
    opener: Any | None = None,
) -> tuple[str, str, str, int]:
    safe_url = validate_public_url(url)
    request = Request(
        safe_url,
        headers={
            "User-Agent": "Co-design-Source-Importer/1.0",
            "Accept": "text/html,text/plain;q=0.9",
        },
    )
    client = opener or build_opener(_SafeRedirectHandler())
    try:
        with client.open(request, timeout=WEB_TIMEOUT_SECONDS) as response:
            final_url = validate_public_url(response.geturl())
            content_type = (
                response.headers.get_content_type()
                if hasattr(response.headers, "get_content_type")
                else str(response.headers.get("Content-Type", "")).split(";")[0]
            )
            if content_type not in {"text/html", "text/plain"}:
                raise SourceImportError("Only public HTML or plain-text webpages can be imported.")
            declared = response.headers.get("Content-Length")
            if declared and int(declared) > MAX_WEB_BYTES:
                raise SourceImportError("The webpage exceeds the 5 MB import limit.")
            payload = response.read(MAX_WEB_BYTES + 1)
            if len(payload) > MAX_WEB_BYTES:
                raise SourceImportError("The webpage exceeds the 5 MB import limit.")
            charset = (
                response.headers.get_content_charset()
                if hasattr(response.headers, "get_content_charset")
                else None
            ) or "utf-8"
    except SourceImportError:
        raise
    except (HTTPError, URLError, TimeoutError, OSError) as exc:
        raise SourceImportError("The webpage could not be imported.") from exc

    decoded = payload.decode(charset, errors="replace")
    if content_type == "text/html":
        parser = _ReadableHTML()
        parser.feed(decoded)
        title = " ".join(parser.title.split())
        extracted = parser.text()
    else:
        title = ""
        extracted = decoded.strip()
    if not extracted:
        raise SourceImportError("No readable text was found on this webpage.")
    fallback_title = urlparse(final_url).hostname or "Web source"
    return title[:180] or fallback_title, extracted[:MAX_SOURCE_TEXT], final_url, len(payload)


def add_file_sources(
    store: StudentStore,
    thread_id: str,
    uploads: Iterable[tuple[str, bytes, str | None]],
    *,
    origin: str = "source_panel",
    extra_metadata: dict[str, Any] | None = None,
    max_file_size_mb: int | None = None,
    preserve_display_names: bool = False,
) -> list[dict[str, Any]]:
    upload_items = list(uploads)
    stored_uploads = save_uploads(
        thread_id,
        upload_items,
        max_file_size_mb=max_file_size_mb,
    )
    created: list[dict[str, Any]] = []
    for index, upload in enumerate(stored_uploads):
        kind = "image" if upload.is_image else "file"
        display_title = (
            Path(upload_items[index][0]).name
            if preserve_display_names
            else upload.name
        )
        source_id = store.add_source(
            thread_id,
            kind=kind,
            title=display_title,
            mime=upload.mime,
            path=str(upload.path),
            extracted_text=upload.extracted_text,
            size=upload.size,
            selected=True,
            metadata={
                **(extra_metadata or {}),
                "managed_file": True,
                "supported": upload.supported,
                "origin": origin,
            },
        )
        source = store.get_source(thread_id, source_id)
        if source:
            created.append(source)
    return created


def sync_lecture_notes_folder(
    store: StudentStore,
    thread_id: str,
) -> LectureNotesSyncResult:
    """Synchronize course files once, repairing duplicates from older races."""
    with _COURSE_MATERIAL_SYNC_LOCK:
        return _sync_lecture_notes_folder(store, thread_id)


def _sync_lecture_notes_folder(
    store: StudentStore,
    thread_id: str,
) -> LectureNotesSyncResult:
    """Copy lecture-note files into one notebook and select them for grounding.

    The shared folder is treated as read-only input. Files are validated through
    the existing upload path, copied into notebook-owned storage, and keyed by a
    relative path plus size/mtime signature. Deleted or replaced folder files
    update only sources previously created by this synchronizer.
    """
    root = settings.lecture_notes_dir.resolve()
    root.mkdir(parents=True, exist_ok=True)
    managed_by_path: dict[str, list[dict[str, Any]]] = {}
    for source in store.list_sources(thread_id):
        metadata = source.get("metadata") or {}
        relative_path = metadata.get("lecture_note_relative_path")
        if metadata.get("origin") != "lecture_notes_folder" or not relative_path:
            continue
        managed_by_path.setdefault(str(relative_path), []).append(source)

    seen: set[str] = set()
    added = updated = removed = unchanged = skipped = 0
    errors: list[str] = []
    processed = 0

    existing: dict[str, dict[str, Any]] = {}
    for relative_path, candidates in managed_by_path.items():
        ordered = sorted(
            candidates,
            key=lambda source: (str(source.get("createdAt") or ""), source["id"]),
        )
        existing[relative_path] = ordered[0]
        for duplicate in ordered[1:]:
            store.delete_source(thread_id, duplicate["id"], force=True)
            removed += 1

    for path in sorted(root.rglob("*")):
        if not path.is_file() or path.is_symlink():
            continue
        relative = path.relative_to(root)
        relative_text = relative.as_posix()
        if path.name == LECTURE_NOTES_README or any(part.startswith(".") for part in relative.parts):
            continue
        if path.suffix.lower() not in SUPPORTED_SUFFIXES:
            skipped += 1
            continue
        if processed >= settings.max_lecture_notes:
            skipped += 1
            continue
        try:
            stat = path.stat()
        except OSError:
            errors.append(f"{relative_text}: could not read file details")
            continue
        if stat.st_size > settings.max_course_material_size_mb * 1024 * 1024:
            skipped += 1
            continue
        seen.add(relative_text)
        signature = f"{stat.st_size}:{stat.st_mtime_ns}"
        material_group = course_material_group(relative_text)
        current = existing.get(relative_text)
        current_metadata = (current or {}).get("metadata") or {}
        if (
            current_metadata.get("lecture_note_signature") == signature
            and current_metadata.get("course_material_group") == material_group
            and current_metadata.get("locked_source") is True
            and current.get("title") == path.name
        ):
            unchanged += 1
            processed += 1
            continue
        try:
            created = add_file_sources(
                store,
                thread_id,
                [(path.name, path.read_bytes(), mimetypes.guess_type(path.name)[0])],
                origin="lecture_notes_folder",
                extra_metadata={
                    "lecture_note_relative_path": relative_text,
                    "lecture_note_signature": signature,
                    "course_material_group": material_group,
                    "locked_source": True,
                },
                max_file_size_mb=settings.max_course_material_size_mb,
                preserve_display_names=True,
            )
        except (OSError, ValueError) as exc:
            errors.append(f"{relative_text}: {exc}")
            continue
        if not created:
            errors.append(f"{relative_text}: source was not created")
            continue
        if current:
            store.delete_source(thread_id, current["id"], force=True)
            updated += 1
        else:
            added += 1
        processed += 1

    for relative_text, source in existing.items():
        if relative_text not in seen:
            store.delete_source(thread_id, source["id"], force=True)
            removed += 1

    return LectureNotesSyncResult(
        added=added,
        updated=updated,
        removed=removed,
        unchanged=unchanged,
        skipped=skipped,
        errors=tuple(errors),
    )


def add_text_source(
    store: StudentStore,
    thread_id: str,
    title: str,
    text: str,
) -> dict[str, Any]:
    cleaned = text.strip()
    if not cleaned:
        raise SourceImportError("Paste some source text first.")
    source_id = store.add_source(
        thread_id,
        kind="text",
        title=title or "Pasted text",
        mime="text/plain",
        extracted_text=cleaned[:MAX_SOURCE_TEXT],
        size=len(cleaned.encode("utf-8")),
        selected=True,
        metadata={"origin": "pasted_text"},
    )
    return store.get_source(thread_id, source_id) or {}


def add_url_source(
    store: StudentStore,
    thread_id: str,
    url: str,
    *,
    opener: Any | None = None,
) -> dict[str, Any]:
    title, text, final_url, size = fetch_public_webpage(url, opener=opener)
    source_id = store.add_source(
        thread_id,
        kind="url",
        title=title,
        mime="text/html",
        source_url=final_url,
        extracted_text=text,
        size=size,
        selected=True,
        metadata={"origin": "public_webpage"},
    )
    return store.get_source(thread_id, source_id) or {}


def backfill_legacy_sources(store: StudentStore, thread_id: str) -> int:
    created = 0
    files_root = settings.files_dir.resolve()
    for message in store.get_messages(thread_id):
        for upload in (message.get("metadata") or {}).get("uploads") or []:
            path_value = str(upload.get("path") or "")
            if not path_value:
                continue
            path = Path(path_value).resolve()
            if not path.is_file() or files_root not in path.parents:
                continue
            if store.find_source_by_path(thread_id, str(path)):
                continue
            suffix = path.suffix.lower()
            supported = bool(upload.get("supported", suffix in SUPPORTED_SUFFIXES))
            extracted = ""
            if supported and suffix not in IMAGE_SUFFIXES:
                try:
                    extracted = extract_text(path)[:MAX_SOURCE_TEXT]
                except Exception:
                    extracted = ""
            store.add_source(
                thread_id,
                kind="image" if suffix in IMAGE_SUFFIXES else "file",
                title=str(upload.get("name") or path.name),
                mime=str(
                    upload.get("mime")
                    or mimetypes.guess_type(path.name)[0]
                    or "application/octet-stream"
                ),
                path=str(path),
                extracted_text=extracted,
                size=int(upload.get("size") or path.stat().st_size),
                selected=True,
                metadata={
                    "managed_file": False,
                    "legacy_attachment": True,
                    "supported": supported,
                },
            )
            created += 1
    return created


def selected_source_context(
    sources: Iterable[dict[str, Any]],
    *,
    limit: int = MAX_COMBINED_CONTEXT,
) -> tuple[str, list[dict[str, Any]]]:
    sections: list[str] = []
    references: list[dict[str, Any]] = []
    remaining = max(0, limit)
    for index, source in enumerate(sources, start=1):
        label = f"S{index}"
        title = str(source.get("title") or "Untitled source")
        text = str(source.get("extractedText") or "").strip()
        if not text and source.get("kind") == "image":
            text = "[Image source. Inspect the accompanying image input.]"
        elif not text:
            text = "[This source is stored but has no analyzable text.]"
        header = f"--- [{label}] {title} ---"
        if source.get("sourceUrl"):
            header += f"\nURL: {source['sourceUrl']}"
        separator_size = 2 if sections else 0
        available = max(0, remaining - separator_size - len(header) - 1)
        body = text[:available]
        section = f"{header}\n{body}".strip()
        if section and remaining:
            sections.append(section)
            remaining -= len(section) + separator_size
        references.append(
            {
                "id": source["id"],
                "label": label,
                "title": title,
                "kind": source.get("kind", "file"),
                "mime": source.get("mime", "application/octet-stream"),
                "url": source.get("sourceUrl"),
            }
        )
        if remaining <= 0:
            break
    return "\n\n".join(sections), references


def source_image_input(source: dict[str, Any]) -> dict[str, str] | None:
    """Build an OpenAI-style ``input_image`` part for a notebook image source.

    Returns None when the source is not an image, the path is missing, or the
    file is outside the configured files directory (path-traversal guard).
    """
    path_value = source.get("path")
    if source.get("kind") != "image" or not path_value:
        return None
    path = Path(str(path_value)).resolve()
    files_root = settings.files_dir.resolve()
    if not path.is_file() or files_root not in path.parents:
        return None
    mime = str(source.get("mime") or mimetypes.guess_type(path.name)[0] or "image/png")
    encoded = base64.b64encode(path.read_bytes()).decode("ascii")
    return {
        "type": "input_image",
        "image_url": f"data:{mime};base64,{encoded}",
        "detail": "auto",
    }


def image_inputs_for_source_ids(
    store: StudentStore,
    thread_id: str,
    source_ids: Iterable[str],
) -> list[dict[str, str]]:
    """Resolve selected notebook images into coach-ready image payloads.

    Resolution stays in the source/infrastructure layer so providers and future
    AWS adapters can swap storage backends without changing the workflow.
    """
    resolved: list[dict[str, str]] = []
    for source_id in source_ids:
        source = store.get_source(thread_id, str(source_id))
        if not source:
            continue
        image_part = source_image_input(source)
        if not image_part:
            continue
        resolved.append(
            {
                "source_id": str(source["id"]),
                "mime": str(source.get("mime") or "image/png"),
                "data_url": image_part["image_url"],
            }
        )
    return resolved
