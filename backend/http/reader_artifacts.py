"""Typed persistent student artifact routes over the existing owner-scoped notebook anchor."""

from collections.abc import Callable
from typing import Any

from urllib.parse import quote

from fastapi import Depends, FastAPI, HTTPException, Query, Request, Response
from pydantic import BaseModel, ConfigDict, Field

from backend.artifact_export import render_artifact_export
from backend.http.reader_workspace import ReaderError
from backend.owner_context import OwnerServices
from backend.persistence.store.operations.artifacts import (
    ARTIFACT_KINDS,
    ArtifactConflictError,
    ArtifactValidationError,
)
from backend.persistence.store.operations.references import ReferenceError


class ReaderArtifact(BaseModel):
    """One owner-authorized persistent artifact with its canonical document and resolved references."""

    owner_id: str
    thread_id: str
    id: str
    title: str
    kind: str
    document: dict[str, Any]
    schema_version: int
    revision: int
    origin: str
    created_at: str
    updated_at: str
    references: list[dict[str, Any]]


class ReaderArtifactSummary(BaseModel):
    """Bounded artifact identity without the document body."""

    id: str
    thread_id: str
    title: str
    kind: str
    schema_version: int
    revision: int
    origin: str
    created_at: str
    updated_at: str


class ReaderArtifacts(BaseModel):
    """Owner/notebook-fenced artifact list, newest first."""

    owner_id: str
    thread_id: str
    artifacts: list[ReaderArtifactSummary]
    kinds: list[str]


class ReaderArtifactCreate(BaseModel):
    """Explicit create payload; the document and references are validated server-side."""

    model_config = ConfigDict(extra='forbid')
    title: str = Field(min_length=1, max_length=200)
    kind: str = Field(min_length=1, max_length=40)
    document: dict[str, Any]
    references: list[dict[str, Any]] | None = None
    origin: str | None = Field(default=None, pattern='^(editor|coach_draft)$')
    request_id: str | None = Field(
        default=None, min_length=1, max_length=128,
        pattern=r'^[A-Za-z0-9][A-Za-z0-9._:-]*$')


class ReaderArtifactUpdate(BaseModel):
    """Explicit save payload; the seen revision guards against stale writes.

    Omitted references keep the saved list; an explicit list replaces it.
    """

    model_config = ConfigDict(extra='forbid')
    title: str | None = Field(default=None, min_length=1, max_length=200)
    document: dict[str, Any]
    revision: int = Field(strict=True, ge=1)
    references: list[dict[str, Any]] | None = None


class ReaderArtifactDelete(BaseModel):
    """Require an explicit confirmation before deleting owned work."""

    model_config = ConfigDict(extra='forbid')
    confirmed: bool = Field(strict=True)


class ReaderArtifactRestore(BaseModel):
    """Restore guard: the caller must have seen the current revision."""

    model_config = ConfigDict(extra='forbid')
    revision: int = Field(strict=True, ge=1)


class ReaderArtifactVersionSummary(BaseModel):
    """Bounded version checkpoint metadata without the document body."""

    revision: int
    title: str
    kind: str
    origin: str
    restored_from: int | None
    created_at: str


class ReaderArtifactVersions(BaseModel):
    """Owner-fenced bounded version history, newest first."""

    owner_id: str
    thread_id: str
    artifact_id: str
    versions: list[ReaderArtifactVersionSummary]


class ReaderArtifactVersion(BaseModel):
    """One readable version preview with its canonical document."""

    owner_id: str
    thread_id: str
    artifact_id: str
    revision: int
    title: str
    kind: str
    document: dict[str, Any]
    origin: str
    restored_from: int | None
    created_at: str


def _artifact(owner: OwnerServices, row: dict[str, Any]) -> ReaderArtifact:
    return ReaderArtifact(owner_id=owner.user_id, **row)


def _summary(owner: OwnerServices, thread_id: str, entry: dict[str, Any]) -> ReaderArtifactSummary:
    return ReaderArtifactSummary(owner_id=owner.user_id, thread_id=thread_id, **{
        key: entry[key] for key in ('id', 'title', 'kind', 'schema_version', 'revision',
                                    'origin', 'created_at', 'updated_at')})


def register_reader_artifacts(
    app: FastAPI, reader_owner: Callable[[Request], OwnerServices],
) -> None:
    """Expose persistent artifact CRUD through the reader's credential and origin guard."""

    def _fail(error: Exception) -> HTTPException:
        if isinstance(error, ArtifactConflictError):
            return HTTPException(status_code=409, detail='Artifact changed. Reopen it before saving.')
        if isinstance(error, (ArtifactValidationError, ReferenceError)):
            return HTTPException(status_code=422, detail=str(error))
        if isinstance(error, LookupError):
            return HTTPException(status_code=404, detail='Artifact not found')
        raise error

    @app.get('/api/v1/reader/threads/{thread_id}/artifacts', response_model=ReaderArtifacts,
             operation_id="readerArtifacts",
             responses={401: {"model": ReaderError}, 403: {"model": ReaderError}, 404: {"model": ReaderError}})
    def artifacts(thread_id: str, owner: OwnerServices = Depends(reader_owner)) -> ReaderArtifacts:
        """List one owned notebook's artifacts without their document bodies."""
        if owner.workspace.get_thread(thread_id) is None:
            raise HTTPException(status_code=404, detail='Notebook not found')
        entries = owner.store.list_artifacts(thread_id)
        return ReaderArtifacts(owner_id=owner.user_id, thread_id=thread_id,
                               kinds=list(ARTIFACT_KINDS), artifacts=[{
            'id': entry['id'], 'thread_id': entry['thread_id'], 'title': entry['title'],
            'kind': entry['kind'], 'schema_version': entry['schema_version'],
            'revision': entry['revision'],
            'origin': entry['origin'], 'created_at': entry['created_at'], 'updated_at': entry['updated_at'],
        } for entry in entries])

    @app.post('/api/v1/reader/threads/{thread_id}/artifacts', response_model=ReaderArtifact,
              status_code=201, operation_id="readerArtifactCreate",
              responses={401: {"model": ReaderError}, 403: {"model": ReaderError}, 404: {"model": ReaderError}})
    def create(thread_id: str, payload: ReaderArtifactCreate,
               owner: OwnerServices = Depends(reader_owner)) -> ReaderArtifact:
        """Create one owned persistent artifact anchored to this notebook."""
        try:
            row = owner.store.create_artifact(
                thread_id, payload.title, payload.document, payload.kind,
                payload.references, origin=payload.origin, request_id=payload.request_id)
        except (ArtifactConflictError, ArtifactValidationError, LookupError, ReferenceError) as error:
            raise _fail(error) from error
        return _artifact(owner, row)

    @app.get('/api/v1/reader/threads/{thread_id}/artifacts/{artifact_id}', response_model=ReaderArtifact,
             operation_id="readerArtifact",
             responses={401: {"model": ReaderError}, 403: {"model": ReaderError}, 404: {"model": ReaderError}})
    def artifact(thread_id: str, artifact_id: str,
                 owner: OwnerServices = Depends(reader_owner)) -> ReaderArtifact:
        """Read one owned artifact with its canonical document."""
        row = owner.store.get_artifact(artifact_id)
        if row is None or row['thread_id'] != thread_id:
            raise HTTPException(status_code=404, detail='Artifact not found')
        return _artifact(owner, row)

    @app.put('/api/v1/reader/threads/{thread_id}/artifacts/{artifact_id}', response_model=ReaderArtifact,
             operation_id="readerArtifactUpdate",
             responses={401: {"model": ReaderError}, 403: {"model": ReaderError}, 404: {"model": ReaderError},
                        409: {"model": ReaderError}})
    def update(thread_id: str, artifact_id: str, payload: ReaderArtifactUpdate,
               owner: OwnerServices = Depends(reader_owner)) -> ReaderArtifact:
        """Apply one explicit revision-guarded save for an owned artifact."""
        try:
            row = owner.workspace.save_artifact(thread_id, artifact_id, payload.document,
                                                payload.revision, payload.title, payload.references)
        except (ArtifactConflictError, ArtifactValidationError, LookupError, ReferenceError) as error:
            raise _fail(error) from error
        return _artifact(owner, row)

    @app.post('/api/v1/reader/threads/{thread_id}/artifacts/{artifact_id}/duplicate',
              response_model=ReaderArtifact, status_code=201, operation_id="readerArtifactDuplicate",
              responses={401: {"model": ReaderError}, 403: {"model": ReaderError}, 404: {"model": ReaderError}})
    def duplicate(thread_id: str, artifact_id: str,
                  owner: OwnerServices = Depends(reader_owner)) -> ReaderArtifact:
        """Copy one owned artifact with its kind, title and canonical document."""
        existing = owner.store.get_artifact(artifact_id)
        if existing is None or existing['thread_id'] != thread_id:
            raise HTTPException(status_code=404, detail='Artifact not found')
        try:
            row = owner.store.duplicate_artifact(artifact_id)
        except (ArtifactConflictError, ArtifactValidationError, LookupError) as error:
            raise _fail(error) from error
        return _artifact(owner, row)

    @app.post('/api/v1/reader/threads/{thread_id}/artifacts/{artifact_id}/delete',
              response_model=ReaderArtifactSummary, operation_id="readerArtifactDelete",
              responses={401: {"model": ReaderError}, 403: {"model": ReaderError}, 404: {"model": ReaderError}})
    def delete(thread_id: str, artifact_id: str, payload: ReaderArtifactDelete,
               owner: OwnerServices = Depends(reader_owner)) -> ReaderArtifactSummary:
        """Delete one owned artifact only after an explicit confirmation."""
        existing = owner.store.get_artifact(artifact_id)
        if existing is None or existing['thread_id'] != thread_id:
            raise HTTPException(status_code=404, detail='Artifact not found')
        try:
            owner.store.delete_artifact(artifact_id, payload.confirmed)
        except (ArtifactValidationError, LookupError) as error:
            raise _fail(error) from error
        return _summary(owner, thread_id, existing)

    def _owned_artifact(thread_id: str, artifact_id: str, owner: OwnerServices) -> None:
        """Fail 404 unless the owned artifact exists in this notebook."""
        existing = owner.store.get_artifact(artifact_id)
        if existing is None or existing['thread_id'] != thread_id:
            raise HTTPException(status_code=404, detail='Artifact not found')

    @app.get('/api/v1/reader/threads/{thread_id}/artifacts/{artifact_id}/versions',
             response_model=ReaderArtifactVersions, operation_id="readerArtifactVersions",
             responses={401: {"model": ReaderError}, 403: {"model": ReaderError}, 404: {"model": ReaderError}})
    def versions(thread_id: str, artifact_id: str,
                 owner: OwnerServices = Depends(reader_owner)) -> ReaderArtifactVersions:
        """List one owned artifact's bounded version checkpoints, newest first."""
        _owned_artifact(thread_id, artifact_id, owner)
        return ReaderArtifactVersions(owner_id=owner.user_id, thread_id=thread_id,
                                      artifact_id=artifact_id, versions=[
            ReaderArtifactVersionSummary(**entry) for entry in owner.store.list_artifact_versions(artifact_id)])

    @app.get('/api/v1/reader/threads/{thread_id}/artifacts/{artifact_id}/versions/{revision}',
             response_model=ReaderArtifactVersion, operation_id="readerArtifactVersion",
             responses={401: {"model": ReaderError}, 403: {"model": ReaderError}, 404: {"model": ReaderError}})
    def version(thread_id: str, artifact_id: str, revision: int,
                owner: OwnerServices = Depends(reader_owner)) -> ReaderArtifactVersion:
        """Read one owned version's readable preview."""
        _owned_artifact(thread_id, artifact_id, owner)
        entry = owner.store.get_artifact_version(artifact_id, revision)
        if entry is None:
            raise HTTPException(status_code=404, detail='Artifact version not found')
        return ReaderArtifactVersion(owner_id=owner.user_id, thread_id=thread_id,
                                     artifact_id=artifact_id, **entry)

    @app.post('/api/v1/reader/threads/{thread_id}/artifacts/{artifact_id}/versions/{revision}/restore',
              response_model=ReaderArtifact, operation_id="readerArtifactRestore",
              responses={401: {"model": ReaderError}, 403: {"model": ReaderError}, 404: {"model": ReaderError},
                         409: {"model": ReaderError}})
    def restore(thread_id: str, artifact_id: str, revision: int, payload: ReaderArtifactRestore,
                owner: OwnerServices = Depends(reader_owner)) -> ReaderArtifact:
        """Restore an older version as a new revision guarded by the current one."""
        _owned_artifact(thread_id, artifact_id, owner)
        try:
            row = owner.store.restore_artifact(artifact_id, revision, payload.revision)
        except (ArtifactConflictError, ArtifactValidationError, LookupError) as error:
            raise _fail(error) from error
        return _artifact(owner, row)

    @app.get('/api/v1/reader/threads/{thread_id}/artifacts/{artifact_id}/export', include_in_schema=False)
    def export_artifact(thread_id: str, artifact_id: str,
                        format: str = Query('markdown', pattern='^(markdown|text|json)$'),
                        owner: OwnerServices = Depends(reader_owner)) -> Response:
        """Download one owned artifact as Markdown, plaintext or canonical JSON.

        Like the transcript export, this stays a documented text download outside
        the JSON browser contract: same-origin enforced, nosniff attachment with
        a sanitized filename, and an envelope carrying provenance only.
        """

        existing = owner.store.get_artifact(artifact_id)
        if existing is None or existing['thread_id'] != thread_id:
            raise HTTPException(status_code=404, detail='Artifact not found')
        try:
            body, media_type, suffix = render_artifact_export(existing, format)
        except ValueError as error:
            raise HTTPException(status_code=422, detail=str(error)) from error
        safe_title = ''.join(character for character in existing['title'] if character.isalnum()
                             or character in (' ', '-', '_')).strip() or 'artifact'
        return Response(body, media_type=media_type, headers={
            'Content-Disposition': f"attachment; filename*=UTF-8''{quote(f'{safe_title}.{suffix}', safe='')}",
            'X-Content-Type-Options': 'nosniff',
            'Cache-Control': 'no-store',
        })
