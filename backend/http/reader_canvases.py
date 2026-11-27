"""Typed persistent design canvas routes over the existing owner-scoped notebook anchor."""

from collections.abc import Callable
from typing import Any

from urllib.parse import quote

from fastapi import Depends, FastAPI, HTTPException, Query, Request, Response
from pydantic import BaseModel, ConfigDict, Field

from backend.canvas_export import render_canvas_export
from backend.http.reader_workspace import ReaderError
from backend.owner_context import OwnerServices
from backend.persistence.store.operations.canvases import (
    CANVAS_NODE_KINDS,
    CANVAS_RELATIONS,
    CANVAS_STAGE_IDS,
    CanvasConflictError,
    CanvasValidationError,
)
from backend.persistence.store.operations.references import ReferenceError


class ReaderCanvas(BaseModel):
    """One owner-authorized persistent canvas with its canonical graph."""

    owner_id: str
    thread_id: str
    id: str
    title: str
    graph: dict[str, Any]
    schema_version: int
    revision: int
    origin: str
    created_at: str
    updated_at: str


class ReaderCanvasSummary(BaseModel):
    """Bounded canvas identity without the graph body."""

    id: str
    thread_id: str
    title: str
    schema_version: int
    revision: int
    origin: str
    created_at: str
    updated_at: str


class ReaderCanvases(BaseModel):
    """Owner/notebook-fenced canvas list, newest first."""

    owner_id: str
    thread_id: str
    canvases: list[ReaderCanvasSummary]
    node_kinds: list[str]
    relations: list[str]
    stages: list[str]


class ReaderCanvasCreate(BaseModel):
    """Explicit create payload; the graph is validated canonically server-side."""

    model_config = ConfigDict(extra='forbid')
    title: str = Field(min_length=1, max_length=200)
    graph: dict[str, Any]


class ReaderCanvasUpdate(BaseModel):
    """Explicit save payload; the seen revision guards against stale writes."""

    model_config = ConfigDict(extra='forbid')
    title: str | None = Field(default=None, min_length=1, max_length=200)
    graph: dict[str, Any]
    revision: int = Field(strict=True, ge=1)


class ReaderCanvasRestore(BaseModel):
    """Restore guard: the caller must have seen the current revision."""

    model_config = ConfigDict(extra='forbid')
    revision: int = Field(strict=True, ge=1)


class ReaderCanvasDelete(BaseModel):
    """Explicit deletion confirmation for the canvas revision shown to the student."""

    model_config = ConfigDict(extra='forbid')
    confirmed: bool = Field(strict=True)
    revision: int = Field(strict=True, ge=1)


class ReaderCanvasVersionSummary(BaseModel):
    """Bounded version checkpoint metadata without the graph body."""

    revision: int
    title: str
    origin: str
    restored_from: int | None
    created_at: str


class ReaderCanvasVersions(BaseModel):
    """Owner-fenced bounded version history, newest first."""

    owner_id: str
    thread_id: str
    canvas_id: str
    versions: list[ReaderCanvasVersionSummary]


class ReaderCanvasVersion(BaseModel):
    """One readable version preview with its canonical graph."""

    owner_id: str
    thread_id: str
    canvas_id: str
    revision: int
    title: str
    graph: dict[str, Any]
    origin: str
    restored_from: int | None
    created_at: str


def _canvas(owner: OwnerServices, row: dict[str, Any]) -> ReaderCanvas:
    return ReaderCanvas(owner_id=owner.user_id, **row)


def register_reader_canvases(
    app: FastAPI, reader_owner: Callable[[Request], OwnerServices],
) -> None:
    """Expose persistent canvas CRUD through the reader's credential and origin guard."""

    def _fail(error: Exception) -> HTTPException:
        if isinstance(error, CanvasConflictError):
            return HTTPException(status_code=409, detail='Canvas changed. Reopen it before saving.')
        if isinstance(error, (CanvasValidationError, ReferenceError)):
            return HTTPException(status_code=422, detail=str(error))
        if isinstance(error, LookupError):
            return HTTPException(status_code=404, detail='Canvas not found')
        raise error

    @app.get('/api/v1/reader/threads/{thread_id}/canvases', response_model=ReaderCanvases,
             operation_id="readerCanvases",
             responses={401: {"model": ReaderError}, 403: {"model": ReaderError}, 404: {"model": ReaderError}})
    def canvases(thread_id: str, owner: OwnerServices = Depends(reader_owner)) -> ReaderCanvases:
        """List one owned notebook's canvases without their graph bodies."""
        if owner.workspace.get_thread(thread_id) is None:
            raise HTTPException(status_code=404, detail='Notebook not found')
        entries = owner.store.list_canvases(thread_id)
        return ReaderCanvases(owner_id=owner.user_id, thread_id=thread_id,
                              node_kinds=list(CANVAS_NODE_KINDS), relations=list(CANVAS_RELATIONS),
                              stages=list(CANVAS_STAGE_IDS),
                              canvases=[{
            'id': entry['id'], 'thread_id': entry['thread_id'], 'title': entry['title'],
            'schema_version': entry['schema_version'], 'revision': entry['revision'],
            'origin': entry['origin'], 'created_at': entry['created_at'], 'updated_at': entry['updated_at'],
        } for entry in entries])

    @app.post('/api/v1/reader/threads/{thread_id}/canvases', response_model=ReaderCanvas,
              status_code=201, operation_id="readerCanvasCreate",
              responses={401: {"model": ReaderError}, 403: {"model": ReaderError}, 404: {"model": ReaderError}})
    def create(thread_id: str, payload: ReaderCanvasCreate,
               owner: OwnerServices = Depends(reader_owner)) -> ReaderCanvas:
        """Create one owned persistent canvas anchored to this notebook."""
        try:
            row = owner.store.create_canvas(thread_id, payload.title, payload.graph)
        except (CanvasConflictError, CanvasValidationError, LookupError, ReferenceError) as error:
            raise _fail(error) from error
        return _canvas(owner, row)

    @app.get('/api/v1/reader/threads/{thread_id}/canvases/{canvas_id}', response_model=ReaderCanvas,
             operation_id="readerCanvas",
             responses={401: {"model": ReaderError}, 403: {"model": ReaderError}, 404: {"model": ReaderError}})
    def canvas(thread_id: str, canvas_id: str,
               owner: OwnerServices = Depends(reader_owner)) -> ReaderCanvas:
        """Read one owned canvas with its canonical graph."""
        row = owner.store.get_canvas(canvas_id)
        if row is None or row['thread_id'] != thread_id:
            raise HTTPException(status_code=404, detail='Canvas not found')
        return _canvas(owner, row)

    @app.put('/api/v1/reader/threads/{thread_id}/canvases/{canvas_id}', response_model=ReaderCanvas,
             operation_id="readerCanvasUpdate",
             responses={401: {"model": ReaderError}, 403: {"model": ReaderError}, 404: {"model": ReaderError},
                        409: {"model": ReaderError}})
    def update(thread_id: str, canvas_id: str, payload: ReaderCanvasUpdate,
               owner: OwnerServices = Depends(reader_owner)) -> ReaderCanvas:
        """Apply one explicit revision-guarded save for an owned canvas."""
        try:
            row = owner.workspace.save_canvas(thread_id, canvas_id, payload.graph,
                                              payload.revision, payload.title)
        except (CanvasConflictError, CanvasValidationError, LookupError, ReferenceError) as error:
            raise _fail(error) from error
        return _canvas(owner, row)

    @app.post('/api/v1/reader/threads/{thread_id}/canvases/{canvas_id}/delete',
              response_model=ReaderCanvasSummary, operation_id="readerCanvasDelete",
              responses={401: {"model": ReaderError}, 403: {"model": ReaderError},
                         404: {"model": ReaderError}, 409: {"model": ReaderError}})
    def delete(thread_id: str, canvas_id: str, payload: ReaderCanvasDelete,
               owner: OwnerServices = Depends(reader_owner)) -> ReaderCanvasSummary:
        """Delete the confirmed canvas revision and return its former summary."""
        try:
            row = owner.workspace.delete_canvas(thread_id, canvas_id, payload.revision, payload.confirmed)
        except (CanvasConflictError, CanvasValidationError, LookupError) as error:
            raise _fail(error) from error
        return ReaderCanvasSummary(**row)

    def _owned_canvas(thread_id: str, canvas_id: str, owner: OwnerServices) -> None:
        """Fail 404 unless the owned canvas exists in this notebook."""
        existing = owner.store.get_canvas(canvas_id)
        if existing is None or existing['thread_id'] != thread_id:
            raise HTTPException(status_code=404, detail='Canvas not found')

    @app.get('/api/v1/reader/threads/{thread_id}/canvases/{canvas_id}/versions',
             response_model=ReaderCanvasVersions, operation_id="readerCanvasVersions",
             responses={401: {"model": ReaderError}, 403: {"model": ReaderError}, 404: {"model": ReaderError}})
    def versions(thread_id: str, canvas_id: str,
                 owner: OwnerServices = Depends(reader_owner)) -> ReaderCanvasVersions:
        """List one owned canvas's bounded version checkpoints, newest first."""
        _owned_canvas(thread_id, canvas_id, owner)
        return ReaderCanvasVersions(owner_id=owner.user_id, thread_id=thread_id,
                                    canvas_id=canvas_id, versions=[
            ReaderCanvasVersionSummary(**entry) for entry in owner.store.list_canvas_versions(canvas_id)])

    @app.get('/api/v1/reader/threads/{thread_id}/canvases/{canvas_id}/versions/{revision}',
             response_model=ReaderCanvasVersion, operation_id="readerCanvasVersion",
             responses={401: {"model": ReaderError}, 403: {"model": ReaderError}, 404: {"model": ReaderError}})
    def version(thread_id: str, canvas_id: str, revision: int,
                owner: OwnerServices = Depends(reader_owner)) -> ReaderCanvasVersion:
        """Read one owned version's readable preview."""
        _owned_canvas(thread_id, canvas_id, owner)
        entry = owner.store.get_canvas_version(canvas_id, revision)
        if entry is None:
            raise HTTPException(status_code=404, detail='Canvas version not found')
        return ReaderCanvasVersion(owner_id=owner.user_id, thread_id=thread_id,
                                   canvas_id=canvas_id, **entry)

    @app.post('/api/v1/reader/threads/{thread_id}/canvases/{canvas_id}/versions/{revision}/restore',
              response_model=ReaderCanvas, operation_id="readerCanvasRestore",
              responses={401: {"model": ReaderError}, 403: {"model": ReaderError}, 404: {"model": ReaderError},
                         409: {"model": ReaderError}})
    def restore(thread_id: str, canvas_id: str, revision: int, payload: ReaderCanvasRestore,
                owner: OwnerServices = Depends(reader_owner)) -> ReaderCanvas:
        """Restore an older version as a new revision guarded by the current one."""
        _owned_canvas(thread_id, canvas_id, owner)
        try:
            row = owner.store.restore_canvas(canvas_id, revision, payload.revision)
        except (CanvasConflictError, CanvasValidationError, LookupError, ReferenceError) as error:
            raise _fail(error) from error
        return _canvas(owner, row)

    @app.get('/api/v1/reader/threads/{thread_id}/canvases/{canvas_id}/export', include_in_schema=False)
    def export_canvas(thread_id: str, canvas_id: str,
                      format: str = Query('json', pattern='^(json|outline|svg)$'),
                      owner: OwnerServices = Depends(reader_owner)) -> Response:
        """Download one owned canvas as structured JSON, an outline or a legible SVG.

        Like the artifact export, this stays a documented download outside the
        JSON browser contract: same-origin enforced, nosniff attachment with a
        sanitized filename, and an envelope carrying provenance and the whole
        graph — never workspace identifiers or operational fields. The SVG
        spans the whole graph including off-screen nodes and escapes content.
        """

        existing = owner.store.get_canvas(canvas_id)
        if existing is None or existing['thread_id'] != thread_id:
            raise HTTPException(status_code=404, detail='Canvas not found')
        try:
            body, media_type, suffix = render_canvas_export(existing, format)
        except ValueError as error:
            raise HTTPException(status_code=422, detail=str(error)) from error
        safe_title = ''.join(character for character in existing['title'] if character.isalnum()
                             or character in (' ', '-', '_')).strip() or 'canvas'
        return Response(body, media_type=media_type, headers={
            'Content-Disposition': f"attachment; filename*=UTF-8''{quote(f'{safe_title}.{suffix}', safe='')}",
            'X-Content-Type-Options': 'nosniff',
            'Cache-Control': 'no-store',
        })
