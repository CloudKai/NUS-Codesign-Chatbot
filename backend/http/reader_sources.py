"""Typed source projections for the authenticated student browser companion."""

import asyncio
from collections.abc import Callable
from typing import Any, Literal
from urllib.parse import quote

from fastapi import Depends, FastAPI, File, HTTPException, Request, UploadFile
from fastapi.responses import Response
from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel, ConfigDict, Field

from backend.owner_context import OwnerServices
from backend.file_processing import checked_upload_mime
from backend.source_library import is_locked_course_source
from backend.settings import settings
from backend.upload_queue import PendingSourceUpload, SourceUploadCoordinator, SourceUploadFailed, UploadAdmissionError

_LIBRARY = "library"


class ReaderSource(BaseModel):
    """Source identity and selection without storage keys or extracted content."""

    id: str
    title: str
    selected: bool
    locked: bool
    kind: str
    size: int


class ReaderSources(BaseModel):
    """Owner/notebook fence around the available grounding sources."""

    owner_id: str
    thread_id: str
    sources: list[ReaderSource]
    max_files: int
    max_file_bytes: int


class ReaderSourceSelection(BaseModel):
    """Explicit desired selection; stale repeats cannot invert canonical selection."""

    model_config = ConfigDict(extra='forbid')
    selected: bool = Field(strict=True)


class ReaderLibraryDelete(BaseModel):
    """Require a deliberate permanent delete from the private Library."""

    model_config = ConfigDict(extra="forbid")
    confirmed: Literal[True]


class ReaderSourceDetail(BaseModel):
    """Bounded extracted text for safe plain-text inspection, never embedded HTML."""

    source: ReaderSource
    text: str
    truncated: bool


class ReaderUpload(BaseModel):
    """Payload-free receipt; queue and processing phases have no invented percentages."""

    id: str
    filenames: list[str]
    state: Literal['queued', 'processing', 'saved', 'failed']
    retryable: bool


class ReaderUploads(BaseModel):
    """Owner/notebook-fenced upload receipts, not durable upload history."""

    owner_id: str
    thread_id: str
    jobs: list[ReaderUpload]


def _upload(job: PendingSourceUpload) -> ReaderUpload:
    """Project a monotonic completion snapshot without consuming payloads or exceptions."""
    done = job.completed
    return ReaderUpload(id=job.upload_id, filenames=list(job.filenames),
                        state=('failed' if job.failed else 'saved') if done else ('processing' if job.processing else 'queued'),
                        retryable=job.retryable if done else False)


def _source(row: dict[str, Any]) -> ReaderSource:
    """Project only deliberate browser fields from an authorized workspace source."""
    return ReaderSource(
        id=row['id'], title=row['title'], selected=bool(row.get('selected')),
        locked=is_locked_course_source(row), kind=str(row.get('kind') or 'file'),
        size=max(0, int(row.get('size') or 0)),
    )


def register_reader_sources(
    app: FastAPI, reader_owner: Callable[[Request], OwnerServices],
) -> None:
    """Expose source inspection through the reader's credential, role and origin guard."""

    def require_thread(thread_id: str, owner: OwnerServices) -> None:
        """Reject missing or foreign notebooks before any source operation."""
        if thread_id != _LIBRARY and owner.workspace.get_thread(thread_id) is None:
            raise HTTPException(status_code=404, detail='Notebook not found')

    def queue(request: Request) -> SourceUploadCoordinator:
        """Use the API process's bounded coordinator, created and drained by its lifespan."""
        return request.app.state.reader_uploads

    async def upload_batch(files: list[UploadFile], limit: int) -> list[tuple[str, bytes, str | None]]:
        """Check a finite multipart batch and validate images before admission."""
        try:
            if not files or len(files) > limit:
                raise HTTPException(status_code=400, detail="Choose fewer files.")
            maximum = max(1, int(settings.max_file_size_mb)) * 1024 * 1024
            batch = []
            for file in files:
                data = await file.read(maximum + 1)
                if len(data) > maximum:
                    raise HTTPException(status_code=413, detail="File exceeds upload limit.")
                name = file.filename or "upload.bin"
                try:
                    mime = await run_in_threadpool(checked_upload_mime, name, data, file.content_type)
                except ValueError as error:
                    raise HTTPException(status_code=422, detail=str(error)) from error
                batch.append((name, data, mime))
            return batch
        finally:
            for file in files:
                await file.close()

    def submit_batch(request: Request, owner: OwnerServices, scope: str,
                     batch: list[tuple[str, bytes, str | None]], *, attachment: bool = False) -> PendingSourceUpload:
        """Admit bounded upload work under the existing owner-scoped queue."""
        coordinator = queue(request)
        try:
            key = coordinator.submit(
                owner_id=owner.user_id, thread_id=scope, uploads=batch,
                upload=lambda files: owner.workspace.upload_library_files(
                    files, thread_id=None if scope == _LIBRARY else scope, attachment=attachment
                ),
            )
        except UploadAdmissionError as error:
            raise HTTPException(status_code=429, detail=str(error), headers={"Retry-After": "5"}) from error
        return next(job for job in coordinator.jobs_for(owner.user_id, scope) if job.upload_id == key)

    @app.get('/api/v1/reader/threads/{thread_id}/uploads', response_model=ReaderUploads)
    def reader_uploads(thread_id: str, request: Request, owner: OwnerServices = Depends(reader_owner)) -> ReaderUploads:
        """Read ephemeral owned progress after reload; never restart missing work automatically."""
        require_thread(thread_id, owner)
        return ReaderUploads(owner_id=owner.user_id, thread_id=thread_id,
                             jobs=[_upload(job) for job in queue(request).jobs_for(owner.user_id, thread_id)])

    @app.post('/api/v1/reader/threads/{thread_id}/uploads', response_model=ReaderUpload, status_code=202)
    async def reader_upload_submit(
        thread_id: str, request: Request, files: list[UploadFile] = File(...),
        owner: OwnerServices = Depends(reader_owner),
    ) -> ReaderUpload:
        """Read finite per-file payloads, then atomically admit bounded retained work.

        Multipart/parser buffering precedes this boundary and is not covered by
        coordinator limits. Source persistence and successful payload release do
        not require a browser revisit. Failed attempts retain no credentials.
        """
        require_thread(thread_id, owner)
        return _upload(submit_batch(request, owner, thread_id, await upload_batch(files, settings.max_files)))

    @app.post('/api/v1/reader/threads/{thread_id}/attachments')
    async def reader_attachments(
        thread_id: str, request: Request, files: list[UploadFile] = File(...),
        owner: OwnerServices = Depends(reader_owner),
    ) -> list[dict[str, str]]:
        """Save composer uploads and return only IDs and titles for the next turn."""
        if thread_id == _LIBRARY:
            raise HTTPException(status_code=404, detail="Chat not found")
        require_thread(thread_id, owner)
        scope = f"attachment:{thread_id}"
        batch = await upload_batch(files, min(settings.max_files, 5))
        coordinator = queue(request)
        try:
            key = coordinator.submit(
                owner_id=owner.user_id, thread_id=scope, uploads=batch,
                upload=lambda items: owner.workspace.upload_library_files(items, thread_id=thread_id, attachment=True),
            )
            job = next(job for job in coordinator.jobs_for(owner.user_id, scope) if job.upload_id == key)
            return await asyncio.shield(asyncio.wrap_future(job.future))
        except UploadAdmissionError as error:
            raise HTTPException(status_code=429, detail="Uploads are busy. Try again.", headers={"Retry-After": "5"}) from error
        except SourceUploadFailed as error:
            raise HTTPException(status_code=422, detail="File processing failed. Check the Library before retrying.") from error
        finally:
            if "key" in locals():
                coordinator.discard(key, owner.user_id)

    @app.post('/api/v1/reader/threads/{thread_id}/uploads/{upload_id}/retry', status_code=202)
    def reader_upload_retry(thread_id: str, upload_id: str, request: Request, owner: OwnerServices = Depends(reader_owner)) -> dict[str, bool]:
        """Retry only an owned retained failure with freshly authenticated owner services."""
        require_thread(thread_id, owner)
        if not queue(request).retry(upload_id, owner.user_id, thread_id,
                                    lambda batch: owner.workspace.upload_library_files(
                                        batch, thread_id=None if thread_id == _LIBRARY else thread_id
                                    )):
            raise HTTPException(status_code=409, detail='Upload changed or retry expired. Refresh sources.')
        return {'accepted': True}

    @app.post('/api/v1/reader/threads/{thread_id}/uploads/{upload_id}/discard')
    def reader_upload_discard(thread_id: str, upload_id: str, request: Request, owner: OwnerServices = Depends(reader_owner)) -> dict[str, bool]:
        """Release a terminal receipt/failure only after checking both notebook and owner."""
        require_thread(thread_id, owner)
        coordinator = queue(request)
        owned = any(job.upload_id == upload_id for job in coordinator.jobs_for(owner.user_id, thread_id))
        if not owned or not coordinator.discard(upload_id, owner.user_id):
            raise HTTPException(status_code=409, detail='Upload still running or no longer available.')
        return {'discarded': True}

    @app.get('/api/v1/reader/threads/{thread_id}/sources', response_model=ReaderSources)
    def reader_sources(thread_id: str, owner: OwnerServices = Depends(reader_owner)) -> ReaderSources:
        """List current canonical selection without returning private storage metadata."""
        require_thread(thread_id, owner)
        return ReaderSources(owner_id=owner.user_id, thread_id=thread_id,
                             max_files=settings.max_files, max_file_bytes=settings.max_file_size_mb * 1024 * 1024,
                             sources=[_source(row) for row in (
                                 owner.workspace.library_sources() if thread_id == _LIBRARY else
                                 owner.workspace.list_sources(thread_id, include_extracted_text=False)
                             )])

    @app.post('/api/v1/reader/threads/{thread_id}/sources/{source_id}/select', response_model=ReaderSources)
    def reader_source_select(
        thread_id: str, source_id: str, payload: ReaderSourceSelection,
        owner: OwnerServices = Depends(reader_owner),
    ) -> ReaderSources:
        """Set explicit selection through the shared store; locked sources remain authoritative."""
        if thread_id == _LIBRARY:
            raise HTTPException(status_code=404, detail="Notebook not found")
        require_thread(thread_id, owner)
        try:
            owner.workspace.set_library_link(thread_id, source_id, payload.selected, require_link=True)
        except ValueError as error:
            raise HTTPException(status_code=409, detail='Source changed or is locked. Refresh sources.') from error
        return reader_sources(thread_id, owner)

    @app.post('/api/v1/reader/threads/{thread_id}/sources/{source_id}/link', response_model=ReaderSources)
    def reader_source_link(thread_id: str, source_id: str, owner: OwnerServices = Depends(reader_owner)) -> ReaderSources:
        """Add an owned Library source to the target notebook and enable it."""
        if thread_id == _LIBRARY:
            raise HTTPException(status_code=404, detail="Notebook not found")
        require_thread(thread_id, owner)
        try:
            owner.workspace.set_library_link(thread_id, source_id, True)
        except ValueError as error:
            raise HTTPException(status_code=404, detail="Library source not found") from error
        return reader_sources(thread_id, owner)

    @app.post('/api/v1/reader/threads/{thread_id}/sources/{source_id}/remove', response_model=ReaderSources)
    def reader_source_remove(thread_id: str, source_id: str, payload: ReaderLibraryDelete | None = None,
                             owner: OwnerServices = Depends(reader_owner)) -> ReaderSources:
        """Detach a notebook source or permanently delete an explicitly confirmed Library original."""
        require_thread(thread_id, owner)
        if thread_id == _LIBRARY and payload is None:
            raise HTTPException(status_code=422, detail="Confirm permanent deletion")
        try:
            if thread_id == _LIBRARY:
                owner.workspace.delete_library_source(source_id)
            else:
                owner.workspace.set_library_link(thread_id, source_id, None, require_link=True)
        except ValueError as error:
            raise HTTPException(status_code=409, detail='Source changed or is locked. Refresh sources.') from error
        return reader_sources(thread_id, owner)

    @app.get('/api/v1/reader/threads/{thread_id}/sources/{source_id}', response_model=ReaderSourceDetail)
    def reader_source(thread_id: str, source_id: str, owner: OwnerServices = Depends(reader_owner)) -> ReaderSourceDetail:
        """Inspect up to 24,000 characters of owned extracted text without executing it."""
        require_thread(thread_id, owner)
        if thread_id == _LIBRARY:
            row = next(iter(owner.workspace.library_sources([source_id], include_extracted_text=True)), None)
        else:
            row = owner.workspace.get_source(thread_id, source_id)
        if row is None:
            raise HTTPException(status_code=404, detail='Source not found')
        text = str(row.get('extractedText') or '')
        return ReaderSourceDetail(source=_source(row), text=text[:24_000], truncated=len(text) > 24_000)

    @app.get('/api/v1/reader/threads/{thread_id}/sources/{source_id}/content')
    def reader_source_content(thread_id: str, source_id: str, owner: OwnerServices = Depends(reader_owner)) -> Response:
        """Download an owned original as an attachment; never render untrusted active content."""
        require_thread(thread_id, owner)
        try:
            content = (owner.workspace.read_library_source(source_id) if thread_id == _LIBRARY
                       else owner.workspace.read_source_content(thread_id, source_id))
        except ValueError as error:
            raise HTTPException(status_code=404, detail='Source unavailable') from error
        return Response(content.data, media_type='application/octet-stream', headers={
            'Content-Disposition': "attachment; filename*=UTF-8''" + quote(content.filename, safe=''),
            'X-Content-Type-Options': 'nosniff',
        })
