"""Narrow student browser adapters over canonical workspace services."""
from collections.abc import Callable
from typing import Annotated, Literal
from urllib.parse import quote

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.responses import Response
from pydantic import BaseModel, ConfigDict, Field

from backend.domain import CoachTurn
from backend.learning_signals import LearningSignal, LearningSignalSaved
from backend.models import DEFAULT_CHAT_MODEL_ID, MODEL_REGISTRY, get_model, validate_reasoning
from backend.learning.journey import normalize_journey
from backend.owner_context import OwnerServices


class ReaderCreate(BaseModel):
    """A new notebook name; default educational settings remain server-owned."""

    model_config = ConfigDict(extra="forbid")
    name: str = Field(min_length=1, max_length=120)


class ReaderSettingsPatch(BaseModel):
    """Allowlisted notebook controls without access to learning assessments or stage state."""

    model_config = ConfigDict(extra="forbid")
    name: str | None = Field(default=None, min_length=1, max_length=120)
    response_detail: Literal["short", "long"] | None = None
    response_language: str | None = Field(default=None, min_length=1, max_length=50)
    selected_model: str | None = Field(default=None, min_length=1, max_length=120)
    reasoning_effort: str | None = Field(default=None, min_length=1, max_length=30)
    assignment: dict[Annotated[str, Field(max_length=80)], Annotated[str, Field(max_length=4000)]] | None = Field(default=None, max_length=20)


class ReaderPreferences(BaseModel):
    """Allowlisted global appearance, scoped to the verified student."""

    owner_id: str
    appearance: Literal["System", "Light", "Dark"]


class ReaderAppearance(BaseModel):
    """Only the existing appearance preference is writable through this adapter."""

    model_config = ConfigDict(extra="forbid")
    appearance: Literal["System", "Light", "Dark"]


class ReaderModel(BaseModel):
    """A configured model choice and supported reasoning settings."""

    id: str
    label: str
    reasoning_efforts: list[str]


class ReaderRemove(BaseModel):
    """Require affirmative confirmation before deleting owned notebook data."""

    model_config = ConfigDict(extra="forbid")
    confirmed: Literal[True]


class ReaderNotebookSettings(BaseModel):
    """Owner-fenced notebook identity for workspace actions."""

    owner_id: str
    notebook: dict[str, str]
    response_detail: Literal["short", "long"]
    response_language: str
    selected_model: str
    reasoning_effort: str | None
    assignment: dict[str, str]
    models: list[ReaderModel]


class ReaderRevision(BaseModel):
    """Student-authored replacement with a stable identity for ambiguous retries."""

    model_config = ConfigDict(extra="forbid")
    content: str = Field(min_length=1, max_length=12_000)
    idempotency_key: str = Field(min_length=1, max_length=128, pattern=r"^[A-Za-z0-9][A-Za-z0-9._:-]*$")


def register_reader_workspace(
    app: FastAPI, reader_owner: Callable[[Request], OwnerServices],
    revise: Callable[[str, str, str, str, Request, OwnerServices], CoachTurn],
) -> None:
    """Register authenticated CRUD/export adapters, preserving the shared service behavior."""

    def notebook(thread_id: str, owner: OwnerServices) -> ReaderNotebookSettings:
        row = owner.workspace.get_thread(thread_id)
        if row is None:
            raise HTTPException(status_code=404, detail="Notebook not found")
        meta = row.get('metadata') or {}
        model = get_model(str(meta.get('selected_model') or DEFAULT_CHAT_MODEL_ID))
        return ReaderNotebookSettings(
            owner_id=owner.user_id, notebook={"id": row['id'], "name": row['name']},
            response_detail=normalize_journey(meta.get('learning_journey'))['response_detail'],
            response_language=str(meta.get('response_language') or 'English'),
            selected_model=model.id, reasoning_effort=validate_reasoning(model, meta.get('reasoning_effort')),
            assignment=meta.get('assignment') or {},
            models=[ReaderModel(id=item.id, label=item.label, reasoning_efforts=list(item.reasoning_efforts)) for item in MODEL_REGISTRY],
        )

    @app.post('/api/v1/reader/threads', response_model=ReaderNotebookSettings)
    def create(payload: ReaderCreate, owner: OwnerServices = Depends(reader_owner)) -> ReaderNotebookSettings:
        """Create an owned notebook using the same defaults as the existing workspace."""
        if not payload.name.strip():
            raise HTTPException(status_code=422, detail="Enter a notebook name")
        row = owner.workspace.create_thread(name=payload.name.strip(), model_id=DEFAULT_CHAT_MODEL_ID, support_mode='critical-thinking')
        return notebook(row['id'], owner)

    @app.get('/api/v1/reader/threads/{thread_id}/settings', response_model=ReaderNotebookSettings)
    def read(thread_id: str, owner: OwnerServices = Depends(reader_owner)) -> ReaderNotebookSettings:
        """Read the canonical notebook action projection without private metadata."""
        return notebook(thread_id, owner)

    @app.post('/api/v1/reader/threads/{thread_id}/settings', response_model=ReaderNotebookSettings)
    def rename(thread_id: str, payload: ReaderSettingsPatch, owner: OwnerServices = Depends(reader_owner)) -> ReaderNotebookSettings:
        """Rename only an owned notebook, preserving all transcript and learning state."""
        notebook(thread_id, owner)
        if payload.name is not None and not payload.name.strip():
            raise HTTPException(status_code=422, detail="Enter a notebook name")
        patch = payload.model_dump(exclude_none=True, exclude={'name'})
        if payload.selected_model is not None and payload.selected_model not in {item.id for item in MODEL_REGISTRY}:
            raise HTTPException(status_code=422, detail="Model unavailable")
        if payload.reasoning_effort is not None:
            current = notebook(thread_id, owner)
            model = get_model(payload.selected_model or current.selected_model)
            if payload.reasoning_effort not in model.reasoning_efforts:
                raise HTTPException(status_code=422, detail="Reasoning setting unavailable")
        owner.workspace.update_thread(thread_id, name=payload.name.strip() if payload.name is not None else None, metadata=patch or None)
        return notebook(thread_id, owner)

    @app.post('/api/v1/reader/threads/{thread_id}/remove')
    def remove(thread_id: str, payload: ReaderRemove, owner: OwnerServices = Depends(reader_owner)) -> dict[str, str]:
        """Delete confirmed owned data through the existing cleanup-aware service."""
        notebook(thread_id, owner)
        owner.workspace.delete_thread(thread_id)
        return {'owner_id': owner.user_id, 'status': 'deleted'}

    @app.get('/api/v1/reader/threads/{thread_id}/transcript.txt')
    def export(thread_id: str, owner: OwnerServices = Depends(reader_owner)) -> Response:
        """Download the full active saved transcript, independent of the loaded browser window."""
        notebook(thread_id, owner)
        transcript = owner.workspace.export_transcript(thread_id)
        return Response(transcript.data, media_type=transcript.mime, headers={
            'Content-Disposition': "attachment; filename*=UTF-8''" + quote(transcript.filename, safe=''),
            'X-Content-Type-Options': 'nosniff',
        })

    @app.get('/api/v1/reader/preferences', response_model=ReaderPreferences)
    def preferences(owner: OwnerServices = Depends(reader_owner)) -> ReaderPreferences:
        """Read existing theme only, preserving private and unrelated preference keys."""
        value = owner.workspace.get_preferences().get('appearance')
        return ReaderPreferences(owner_id=owner.user_id, appearance=value if value in {'System', 'Light', 'Dark'} else 'System')

    @app.post('/api/v1/reader/preferences', response_model=ReaderPreferences)
    def appearance(payload: ReaderAppearance, owner: OwnerServices = Depends(reader_owner)) -> ReaderPreferences:
        """Merge the canonical appearance preference without overwriting other keys."""
        owner.workspace.update_preferences({'appearance': payload.appearance})
        return preferences(owner)

    @app.post('/api/v1/reader/threads/{thread_id}/messages/{message_id}/revise', response_model=CoachTurn)
    def reader_revise(
        thread_id: str, message_id: str, payload: ReaderRevision, request: Request,
        owner: OwnerServices = Depends(reader_owner),
    ) -> CoachTurn:
        """Delegate append-only editing and all recovery/error semantics to the shared route."""
        return revise(thread_id, message_id, payload.content, payload.idempotency_key, request, owner)

    @app.post('/api/v1/reader/threads/{thread_id}/messages/{message_id}/learning-signal', response_model=LearningSignalSaved)
    def reader_signal(
        thread_id: str, message_id: str, payload: LearningSignal,
        owner: OwnerServices = Depends(reader_owner),
    ) -> LearningSignalSaved:
        """Persist canonical bounded receipts without accepting private or educational metadata."""
        try:
            receipts = owner.workspace.record_learning_signal(thread_id, message_id, payload.kind)
        except ValueError as error:
            raise HTTPException(status_code=404, detail='Answer not found') from error
        return LearningSignalSaved(signals=receipts)
