"""Source ingestion, course-material synchronization, and compatibility re-exports.

Bounded coach context lives in :mod:`backend.sources.context`. Image and
storage projection live in :mod:`backend.sources.projection`.
"""

from __future__ import annotations

import ipaddress
import mimetypes
import re
import socket
import threading
import uuid
import zlib
from concurrent.futures import Future, ThreadPoolExecutor
from contextvars import ContextVar, Token
from dataclasses import dataclass
from html.parser import HTMLParser
from pathlib import Path
from typing import Any, Callable, Iterable
from urllib.error import HTTPError, URLError
from urllib.parse import urljoin, urlparse
from urllib.request import HTTPRedirectHandler, Request, build_opener

from ..file_processing import (
    IMAGE_SUFFIXES,
    SUPPORTED_SUFFIXES,
    extract_text,
    save_uploads,
)
from ..retrieval import course_material_id_from_object_key
from ..settings import settings
from ..student_store import StudentStore
from .context import selected_source_context as _selected_source_context
from .projection import (  # noqa: F401 - compatibility re-exports
    image_inputs_for_source_ids,
    read_source_bytes,
    safe_source_file_path,
    source_image_input,
)


MAX_SOURCE_TEXT = 120_000
MAX_COMBINED_CONTEXT = 160_000
MAX_WEB_BYTES = 5 * 1024 * 1024
WEB_TIMEOUT_SECONDS = 10
LECTURE_NOTES_README = "README.txt"
COURSE_MATERIAL_GROUPS = ("Lecture Notes", "Readings")
SHARED_COURSE_FOLDERS = ("lectureNotes", "readings")
_SHARED_CATALOG_UNAVAILABLE = (("__course_catalog_unavailable__", 0, 0),)
_COURSE_MATERIAL_SYNC_LOCK = threading.RLock()
_VIRTUAL_COURSE_NAMESPACE = uuid.UUID("6b1c9e20-4d8a-5f31-8c47-2e9a0b7d15c3")
_catalog_memo: ContextVar["_SharedCatalogMemo | None"] = ContextVar(
    "shared_course_catalog_memo", default=None
)


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


@dataclass(frozen=True)
class SharedCourseItem:
    """One shared course object referenced by locked notebook sources."""

    object_key: str
    relative_path: str
    filename: str
    size: int
    signature: str
    material_group: str
    fingerprint_token: int


@dataclass
class _SharedCatalogMemo:
    """Mutable request-local memo for one shared-catalog listing."""

    items: list[SharedCourseItem] | None = None
    error: BaseException | None = None
    loaded: bool = False
    load_count: int = 0


class shared_course_catalog_scope:
    """Memoize shared course-catalog listings for the current request.

    The memo does not outlive the ``with`` block and is not process-global.
    Listing failures are remembered for the same request only so a catalog
    outage is not retried once per source id.
    """

    def __init__(self) -> None:
        self._token: Token[_SharedCatalogMemo | None] | None = None

    def __enter__(self) -> "shared_course_catalog_scope":
        self._token = _catalog_memo.set(_SharedCatalogMemo())
        return self

    def __exit__(self, *_exc: object) -> bool:
        scope = _catalog_memo.get()
        # Reset before recording so a telemetry failure cannot strand the memo
        # on a pooled worker thread and leak it into the next request.
        if self._token is not None:
            _catalog_memo.reset(self._token)
            self._token = None
        if scope is not None:
            from backend.turn_perf import record_field

            record_field("source_catalog_load_count", int(scope.load_count))
        return False


def course_material_fingerprint() -> tuple[tuple[str, int, int], ...]:
    """Return the stable file signature used to coordinate background imports."""
    if settings.uses_shared_course_materials:
        return _shared_course_fingerprint()
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


def course_material_sync_disabled_result() -> LectureNotesSyncResult:
    """Return an immediate no-op result when course-material sync is disabled."""
    return LectureNotesSyncResult()


def _completed_sync_future(
    result: LectureNotesSyncResult | None = None,
) -> Future[LectureNotesSyncResult]:
    """Return an already-finished sync future (no worker thread)."""
    future: Future[LectureNotesSyncResult] = Future()
    future.set_result(result or course_material_sync_disabled_result())
    return future


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
        # Shared S3 catalogs are listed into the UI, not copied into ``sources``.
        if settings.uses_shared_course_materials:
            return fingerprint != _SHARED_CATALOG_UNAVAILABLE
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
        if not settings.course_material_sync_enabled:
            return _completed_sync_future()
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
                completed = _completed_sync_future(LectureNotesSyncResult())
                self._jobs[key] = (fingerprint, completed)
                return completed

            future = self._executor.submit(sync_lecture_notes_folder, store, thread_id)
            self._jobs[key] = (fingerprint, future)
            return future

    def request_api(
        self,
        channel: str,
        thread_id: str,
        worker: Callable[[], LectureNotesSyncResult],
    ) -> Future[LectureNotesSyncResult]:
        """Share one remote (HTTP) course-material sync per notebook snapshot.

        Used when Streamlit creates notebooks via FastAPI. Sync must hit the
        API so notebook ownership stays bound to the authenticated Cognito user
        (or local-student demo owner) rather than any in-process fallback store.
        """
        if not settings.course_material_sync_enabled:
            return _completed_sync_future()
        fingerprint = course_material_fingerprint()
        key = (str(channel), "__api__", str(thread_id))
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
                # Retry when the prior remote sync reported per-file errors.
                if result is not None and not result.errors:
                    return future

            future = self._executor.submit(worker)
            self._jobs[key] = (fingerprint, future)
            return future


def course_material_group(relative_path: str) -> str:
    """Classify a course file by its folder or filename without moving it."""
    lowered_parts = [part.lower() for part in Path(relative_path).parts]
    if any("reading" in part for part in lowered_parts):
        return "Readings"
    return "Lecture Notes"


def _list_shared_course_items_from_storage() -> list[SharedCourseItem]:
    """List shared Lecture Notes and Readings objects without request memoisation.

    Raises:
        Exception: Listing failures propagate so callers can avoid treating an
            outage as an empty catalog (which would delete locked sources).
    """
    from backend.persistence.factory import get_course_file_storage

    prefix = settings.normalized_course_materials_prefix
    storage = get_course_file_storage()
    items: list[SharedCourseItem] = []
    max_bytes = settings.max_course_material_size_mb * 1024 * 1024
    for folder in SHARED_COURSE_FOLDERS:
        for obj in storage.list_prefix(f"{prefix}{folder}/"):
            if "/derived/" in obj.key or obj.key.endswith("/"):
                continue
            relative = obj.key[len(prefix) :] if obj.key.startswith(prefix) else obj.key
            filename = Path(relative).name
            if filename == LECTURE_NOTES_README or filename.startswith("."):
                continue
            if Path(filename).suffix.lower() not in SUPPORTED_SUFFIXES:
                continue
            if obj.size > max_bytes:
                continue
            signature = f"{obj.size}:{obj.etag or obj.size}"
            items.append(
                SharedCourseItem(
                    object_key=obj.key,
                    relative_path=relative,
                    filename=filename,
                    size=obj.size,
                    signature=signature,
                    material_group=course_material_group(relative),
                    fingerprint_token=zlib.crc32(signature.encode("utf-8")) & 0x7FFFFFFF,
                )
            )
            if len(items) >= settings.max_lecture_notes:
                return items
    return items


def _iter_shared_course_items() -> list[SharedCourseItem]:
    """List shared Lecture Notes and Readings objects for locked source sync.

    When a :class:`shared_course_catalog_scope` is active, the listing result
    or failure is reused for the rest of the request.

    Raises:
        Exception: Listing failures propagate so callers can avoid treating an
            outage as an empty catalog (which would delete locked sources).
    """
    scope = _catalog_memo.get()
    if scope is not None and scope.loaded:
        if scope.error is not None:
            raise scope.error
        return list(scope.items or [])
    try:
        items = _list_shared_course_items_from_storage()
    except Exception as error:
        if scope is not None:
            scope.loaded = True
            scope.error = error
            scope.load_count += 1
        raise
    if scope is not None:
        scope.loaded = True
        scope.items = list(items)
        scope.load_count += 1
    else:
        from backend.turn_perf import record_count

        record_count("source_catalog_load_count")
    return items


def _shared_course_fingerprint() -> tuple[tuple[str, int, int], ...]:
    """Return the shared-catalog fingerprint, or a sentinel when listing fails."""
    try:
        items = _iter_shared_course_items()
    except Exception:
        return _SHARED_CATALOG_UNAVAILABLE
    return tuple(
        (item.relative_path, item.size, item.fingerprint_token) for item in items
    )


def is_locked_course_source(source: dict[str, Any]) -> bool:
    """Return whether a synchronized course source is read-only in the UI."""
    metadata = source.get("metadata") or {}
    return bool(metadata.get("locked_source")) and (
        metadata.get("origin") == "lecture_notes_folder"
    )


def virtual_course_source_id(object_key: str) -> str:
    """Return a stable source id for a shared course object that is not in DSQL."""
    return str(uuid.uuid5(_VIRTUAL_COURSE_NAMESPACE, object_key))


def project_shared_course_item(item: SharedCourseItem) -> dict[str, Any]:
    """Project one shared catalog object into a locked source dict.

    The dict is UI/retrieval shaped. It is not a ``sources`` row.
    """
    mime = mimetypes.guess_type(item.filename)[0] or "application/octet-stream"
    kind = (
        "image"
        if Path(item.filename).suffix.lower() in IMAGE_SUFFIXES
        else "file"
    )
    return {
        "id": virtual_course_source_id(item.object_key),
        "kind": kind,
        "title": item.filename,
        "mime": mime,
        "size": item.size,
        "selected": True,
        "path": item.object_key,
        "object_key": item.object_key,
        "extractedText": "",
        "metadata": {
            "origin": "lecture_notes_folder",
            "lecture_note_relative_path": item.relative_path,
            "lecture_note_signature": item.signature,
            "course_material_group": item.material_group,
            "locked_source": True,
            "managed_file": True,
            "supported": True,
            "storage_provider": settings.file_storage_provider,
            "object_key": item.object_key,
            "shared_course_object": True,
            "virtual_course_source": True,
            "course_material_id": course_material_id_from_object_key(item.object_key),
        },
    }


def _shared_catalog_source_dicts() -> list[dict[str, Any]]:
    """List locked course sources from the shared catalog, or empty on outage."""
    if not settings.course_material_sync_enabled:
        return []
    if not settings.uses_shared_course_materials:
        return []
    try:
        items = _iter_shared_course_items()
    except Exception:
        return []
    return [project_shared_course_item(item) for item in items]


def list_visible_sources(
    store: StudentStore,
    thread_id: str,
    *,
    selected_only: bool = False,
) -> list[dict[str, Any]]:
    """List personal notebook sources plus the shared Lecture Notes catalog.

    Shared ``course/`` objects are not inserted per notebook. Notebooks that
    already persisted locked course rows keep those rows and skip duplicates.
    """
    persisted = store.list_sources(thread_id, selected_only=False)
    persisted_course_paths = {
        str((source.get("metadata") or {}).get("lecture_note_relative_path") or "")
        for source in persisted
        if is_locked_course_source(source)
    }
    catalog = [
        source
        for source in _shared_catalog_source_dicts()
        if str((source.get("metadata") or {}).get("lecture_note_relative_path") or "")
        not in persisted_course_paths
    ]
    merged = persisted + catalog
    if selected_only:
        return [source for source in merged if source.get("selected")]
    return merged


def get_visible_source(
    store: StudentStore,
    thread_id: str,
    source_id: str,
) -> dict[str, Any] | None:
    """Return a persisted source or a shared-catalog course source."""
    found = store.get_source(thread_id, source_id)
    if found:
        return found
    wanted = str(source_id or "").strip()
    if not wanted:
        return None
    for source in _shared_catalog_source_dicts():
        if str(source.get("id") or "") == wanted:
            return source
    return None


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


def _object_storage_key(value: str | None) -> str | None:
    """Return *value* when it looks like a student-upload object key."""
    key = str(value or "").strip()
    if key.startswith("users/"):
        return key
    return None


def _cleanup_object_keys(*keys: str | None) -> None:
    """Best-effort delete of object-storage keys outside any DB OCC retry."""
    to_delete = [_object_storage_key(key) for key in keys]
    cleaned = [key for key in to_delete if key]
    if not cleaned:
        return
    from backend.persistence.factory import get_file_storage

    storage = get_file_storage()
    errors: list[Exception] = []
    for key in cleaned:
        try:
            storage.delete(key)
        except Exception as error:  # noqa: BLE001 - surface after all deletes
            errors.append(error)
    if errors:
        raise errors[0]


def _add_source_with_extracted_text(
    store: StudentStore,
    notebook_id: str,
    *,
    extracted_text: str = "",
    **source_values: Any,
) -> str:
    """Store extracted text before the retryable source-metadata DB write.

    Object storage is deliberately outside ``StudentStore.add_source`` so an
    Aurora DSQL OCC retry never repeats S3 writes. On metadata failure, both the
    raw upload key and extracted-text key are cleaned up.
    """
    source_id = str(source_values.pop("source_id", "") or uuid.uuid4())
    cleaned = (extracted_text or "")[:MAX_SOURCE_TEXT]
    metadata = source_values.get("metadata")
    metadata_dict = dict(metadata) if isinstance(metadata, dict) else {}
    raw_object_key = _object_storage_key(
        metadata_dict.get("object_key") or source_values.get("path")
    )
    extracted_text_key: str | None = None
    storage = None
    if cleaned:
        from backend.persistence.factory import get_file_storage
        from backend.persistence.object_keys import build_extracted_text_object_key

        storage = get_file_storage()
        extracted_text_key = build_extracted_text_object_key(
            user_id=store.owner_id,
            notebook_id=notebook_id,
            source_id=source_id,
        )
        storage.put_bytes(
            key=extracted_text_key,
            data=cleaned.encode("utf-8"),
            content_type="text/plain; charset=utf-8",
        )
    try:
        return store.add_source(
            notebook_id,
            source_id=source_id,
            extracted_text_key=extracted_text_key,
            **source_values,
        )
    except Exception as database_error:
        try:
            _cleanup_object_keys(extracted_text_key, raw_object_key)
        except Exception as cleanup_error:
            raise cleanup_error from database_error
        raise


def add_file_sources(
    store: StudentStore,
    thread_id: str,
    uploads: Iterable[tuple[str, bytes, str | None]],
    *,
    origin: str = "source_panel",
    extra_metadata: dict[str, Any] | None = None,
    max_file_size_mb: int | None = None,
    preserve_display_names: bool = False,
    compress: bool = True,
) -> list[dict[str, Any]]:
    upload_items = list(uploads)
    # Generate source ids server-side before object storage so keys include them.
    source_ids = [str(uuid.uuid4()) for _ in upload_items]
    stored_uploads = save_uploads(
        thread_id,
        upload_items,
        max_file_size_mb=max_file_size_mb,
        compress=compress,
        owner_id=getattr(store, "owner_id", "local-student"),
        source_ids=source_ids,
    )
    created: list[dict[str, Any]] = []
    pending_raw_keys: list[str] = []
    for upload in stored_uploads:
        raw_key = _object_storage_key(upload.storage_key)
        if raw_key:
            pending_raw_keys.append(raw_key)
    try:
        for index, upload in enumerate(stored_uploads):
            kind = "image" if upload.is_image else "file"
            display_title = (
                Path(upload_items[index][0]).name
                if preserve_display_names
                else upload.name
            )
            source_id = _add_source_with_extracted_text(
                store,
                thread_id,
                kind=kind,
                title=display_title,
                mime=upload.mime,
                path=upload.storage_key or str(upload.path),
                extracted_text=upload.extracted_text,
                size=upload.size,
                selected=True,
                source_id=upload.source_id or source_ids[index],
                metadata={
                    **(extra_metadata or {}),
                    "managed_file": True,
                    "supported": upload.supported,
                    "origin": origin,
                    "storage_provider": upload.storage_provider,
                    **(
                        {"object_key": upload.storage_key}
                        if upload.storage_key
                        else {}
                    ),
                },
            )
            raw_key = _object_storage_key(upload.storage_key)
            if raw_key and raw_key in pending_raw_keys:
                pending_raw_keys.remove(raw_key)
            source = store.get_source(thread_id, source_id)
            if source:
                created.append(source)
    except Exception:
        _cleanup_object_keys(*pending_raw_keys)
        raise
    return created


def sync_lecture_notes_folder(
    store: StudentStore,
    thread_id: str,
) -> LectureNotesSyncResult:
    """Synchronize course files once, repairing duplicates from older races."""
    if not settings.course_material_sync_enabled:
        return course_material_sync_disabled_result()
    with _COURSE_MATERIAL_SYNC_LOCK:
        return _sync_lecture_notes_folder(store, thread_id)


def _sync_shared_course_materials(
    store: StudentStore,
    thread_id: str,
) -> LectureNotesSyncResult:
    """Confirm the shared course catalog without writing notebook ``sources``.

    PDFs stay under the shared prefix. New notebooks must not receive one
    ``sources`` row per Week/Reading file. A catalog listing failure is
    reported so the UI can keep any older persisted locked rows.

    Args:
        store: Unused; kept so the coordinator signature stays notebook-scoped.
        thread_id: Unused; catalog listing is shared across notebooks.
    """
    del store, thread_id
    try:
        catalog = _iter_shared_course_items()
    except Exception:
        return LectureNotesSyncResult(errors=("course catalog is unavailable",))
    return LectureNotesSyncResult(unchanged=len(catalog))


def _sync_lecture_notes_folder(
    store: StudentStore,
    thread_id: str,
) -> LectureNotesSyncResult:
    """Copy local lecture-note files into one notebook, or list the shared catalog.

    The shared folder is treated as read-only input. Local development copies
    files into notebook-owned storage. Production S3 lists shared ``course/``
    object keys into the UI and never writes those files into ``sources``.
    """
    if settings.uses_shared_course_materials:
        return _sync_shared_course_materials(store, thread_id)
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
            and current_metadata.get("course_material_id")
            == course_material_id_from_object_key(f"course/{relative_text}")
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
                    "course_material_id": course_material_id_from_object_key(
                        f"course/{relative_text}"
                    ),
                },
                max_file_size_mb=settings.max_course_material_size_mb,
                preserve_display_names=True,
                # Shared lecture files are prepared offline; skip MuPDF/Pillow
                # rewrite so new-notebook sync stays a fast copy + extract.
                compress=False,
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
    source_id = _add_source_with_extracted_text(
        store,
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
    source_id = _add_source_with_extracted_text(
        store,
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
            _add_source_with_extracted_text(
                store,
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
    """Return bounded labeled context using the historical default limit."""
    return _selected_source_context(sources, limit=limit)
