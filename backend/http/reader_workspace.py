"""Narrow student browser adapters over canonical workspace services."""
from collections.abc import Callable
from typing import Annotated, Any, Literal
from urllib.parse import quote

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.responses import Response, StreamingResponse
from pydantic import BaseModel, ConfigDict, Field, field_validator

from backend.domain import CoachTurn, require_supported_response_language
from backend.learning_signals import LearningSignal, LearningSignalSaved
from backend.models import DEFAULT_CHAT_MODEL_ID, MODEL_REGISTRY, get_model, validate_reasoning
from backend.learning.journey import normalize_journey
from backend.owner_context import OwnerServices
from backend.settings import settings
from backend.persistence.store.contracts import is_reader_notebook

_PARENT_NOTEBOOK_KEY = "reader_parent_notebook_id"


class ReaderCreate(BaseModel):
    """Create a named project notebook or an untitled standalone chat."""

    model_config = ConfigDict(extra="forbid")
    kind: Literal["notebook", "chat"] = "notebook"
    name: str | None = Field(default=None, min_length=1, max_length=120)
    parent_notebook_id: str | None = Field(default=None, min_length=1, max_length=128)


class ReaderSettingsPatch(BaseModel):
    """Allowlisted notebook controls without access to learning assessments or stage state."""

    model_config = ConfigDict(extra="forbid")
    name: str | None = Field(default=None, min_length=1, max_length=120)
    response_detail: Literal["short", "long"] | None = None
    pinned: bool | None = Field(default=None, strict=True)
    response_language: str | None = Field(default=None, min_length=1, max_length=50)
    _supported_language = field_validator("response_language")(require_supported_response_language)
    selected_model: str | None = Field(default=None, min_length=1, max_length=120)
    reasoning_effort: str | None = Field(default=None, min_length=1, max_length=30)
    assignment: dict[Annotated[str, Field(max_length=80)], Annotated[str, Field(max_length=4000)]] | None = Field(default=None, max_length=20)


class ReaderPreferences(BaseModel):
    """Presentation defaults scoped to the verified workspace owner."""

    owner_id: str
    appearance: Literal["System", "Light", "Dark"]
    display_name: str
    reduce_motion: bool
    default_mode: Literal["lecture", "project"]
    starter_prompts: bool


def reader_preferences(owner: OwnerServices) -> ReaderPreferences:
    """Project supported presentation defaults from one verified owner's preferences."""
    values = owner.workspace.get_preferences()
    theme = values.get("appearance")
    name = values.get("reader_display_name")
    return ReaderPreferences(
        owner_id=owner.user_id,
        appearance=theme if theme in ("System", "Light", "Dark") else "System",
        display_name=name if isinstance(name, str) else "",
        reduce_motion=values.get("reader_reduce_motion") is True,
        default_mode="project" if values.get("reader_default_mode") == "project" else "lecture",
        starter_prompts=values.get("reader_starter_prompts") is not False,
    )


class ReaderPreferencesPatch(BaseModel):
    """Allow only supported workspace preferences to be changed."""

    model_config = ConfigDict(extra="forbid")
    appearance: Literal["System", "Light", "Dark"] | None = None
    display_name: str | None = Field(default=None, max_length=80)
    reduce_motion: bool | None = None
    default_mode: Literal["lecture", "project"] | None = None
    starter_prompts: bool | None = None


class ReaderModel(BaseModel):
    """A configured model choice and supported reasoning settings."""

    id: str
    label: str
    reasoning_efforts: list[str]


class ReaderRemove(BaseModel):
    """Require affirmative confirmation before deleting owned notebook data."""

    model_config = ConfigDict(extra="forbid")
    confirmed: Literal[True]


class ReaderMoveChat(BaseModel):
    """Move an existing chat to an owned notebook, or to Chats with null."""

    model_config = ConfigDict(extra="forbid")
    parent_notebook_id: str | None = Field(min_length=1, max_length=128)


class ReaderNotebook(BaseModel):
    """Public workspace identity and classification for the sidebar."""

    id: str
    name: str
    kind: Literal["notebook", "chat"] = "notebook"
    parent_notebook_id: str | None = None
    pinned: bool = False


def reader_notebook(row: dict[str, Any]) -> ReaderNotebook:
    """Treat unmarked legacy conversations as chats without rewriting their stored data."""
    metadata = row.get("metadata") or {}
    quick_chat = not is_reader_notebook(metadata)
    parent = metadata.get(_PARENT_NOTEBOOK_KEY)
    name = row["name"]
    if quick_chat and name == "New assignment chat":
        name = "New Chat"
    return ReaderNotebook(
        id=row["id"], name=name, kind="chat" if quick_chat else "notebook",
        parent_notebook_id=parent if quick_chat and isinstance(parent, str) else None,
        pinned=quick_chat and metadata.get("reader_pinned") is True,
    )


def reader_notebook_for_owner(row: dict[str, Any], owner: OwnerServices) -> ReaderNotebook:
    """Resolve a chat whose target was removed back to the owner's Chats list."""
    entry = reader_notebook(row)
    if entry.parent_notebook_id:
        target = owner.workspace.get_thread(entry.parent_notebook_id)
        if target is None or reader_notebook(target).kind != "notebook":
            entry.parent_notebook_id = None
    return entry


class ReaderNotebookSettings(BaseModel):
    """Owner-fenced notebook identity for workspace actions."""

    owner_id: str
    notebook: ReaderNotebook
    response_detail: Literal["short", "long"]
    response_language: str
    selected_model: str
    reasoning_effort: str | None
    assignment: dict[str, str]
    models: list[ReaderModel]
    chat_model_label: str


class ReaderRevision(BaseModel):
    """Student-authored replacement with a stable identity for ambiguous retries."""

    model_config = ConfigDict(extra="forbid")
    content: str = Field(min_length=1, max_length=12_000)
    idempotency_key: str = Field(min_length=1, max_length=128, pattern=r"^[A-Za-z0-9][A-Za-z0-9._:-]*$")


def reader_chat_model_label(saved_model_label: str) -> str:
    """Label the actual coaching runtime rather than its legacy chat preference."""
    if settings.model_provider == "mock":
        return "Mock coach"
    if settings.model_provider == "openai":
        return saved_model_label
    model_id = (settings.coaching_model_id or settings.agentcore_model_id
                if settings.model_provider == "agentcore" else settings.bedrock_model_id)
    if "claude-haiku-4-5" in model_id:
        return "Claude Haiku 4.5"
    return "Course coach"


def register_reader_workspace(
    app: FastAPI, reader_owner: Callable[[Request], OwnerServices],
    revise: Callable[[str, str, str, str, Request, OwnerServices], CoachTurn],
    revise_stream: Callable[[str, str, str, str, Request, OwnerServices], StreamingResponse],
) -> None:
    """Register authenticated CRUD/export adapters, preserving the shared service behavior."""

    def notebook(thread_id: str, owner: OwnerServices) -> ReaderNotebookSettings:
        row = owner.workspace.get_thread(thread_id)
        if row is None:
            raise HTTPException(status_code=404, detail="Notebook not found")
        meta = row.get('metadata') or {}
        model = get_model(str(meta.get('selected_model') or DEFAULT_CHAT_MODEL_ID))
        return ReaderNotebookSettings(
            owner_id=owner.user_id, notebook=reader_notebook_for_owner(row, owner),
            response_detail=normalize_journey(meta.get('learning_journey'))['response_detail'],
            response_language=str(meta.get('response_language') or 'English'),
            selected_model=model.id, reasoning_effort=validate_reasoning(model, meta.get('reasoning_effort')),
            assignment=meta.get('assignment') or {},
            chat_model_label=reader_chat_model_label(model.label),
            models=[ReaderModel(id=item.id, label=item.label, reasoning_efforts=list(item.reasoning_efforts)) for item in MODEL_REGISTRY],
        )

    @app.post('/api/v1/reader/threads', response_model=ReaderNotebookSettings)
    def create(payload: ReaderCreate, owner: OwnerServices = Depends(reader_owner)) -> ReaderNotebookSettings:
        """Create an owned entry using the canonical workspace defaults."""
        quick_chat = payload.kind == "chat"
        name = (payload.name or "").strip()
        if quick_chat and payload.name is not None:
            raise HTTPException(status_code=422, detail="Quick chats start without a name")
        if not quick_chat and not name:
            raise HTTPException(status_code=422, detail="Enter a notebook name")
        if payload.parent_notebook_id is not None:
            if not quick_chat:
                raise HTTPException(status_code=422, detail="Only chats can be created within a notebook")
            target = owner.workspace.get_thread(payload.parent_notebook_id)
            if target is None or reader_notebook(target).kind != "notebook":
                raise HTTPException(status_code=404, detail="Destination notebook not found")
        row = owner.workspace.create_thread(
            name="New assignment chat" if quick_chat else name,
            model_id=DEFAULT_CHAT_MODEL_ID,
            support_mode="critical-thinking",
            quick_chat=quick_chat,
            reader_notebook=not quick_chat,
            parent_notebook_id=payload.parent_notebook_id,
        )
        return notebook(row['id'], owner)

    @app.get('/api/v1/reader/threads/{thread_id}/settings', response_model=ReaderNotebookSettings)
    def read(thread_id: str, owner: OwnerServices = Depends(reader_owner)) -> ReaderNotebookSettings:
        """Read the canonical notebook action projection without private metadata."""
        return notebook(thread_id, owner)

    @app.post('/api/v1/reader/threads/{thread_id}/settings', response_model=ReaderNotebookSettings)
    def rename(thread_id: str, payload: ReaderSettingsPatch, owner: OwnerServices = Depends(reader_owner)) -> ReaderNotebookSettings:
        """Rename only an owned notebook, preserving all transcript and learning state."""
        current = notebook(thread_id, owner)
        if payload.name is not None and not payload.name.strip():
            raise HTTPException(status_code=422, detail="Enter a notebook name")
        patch = payload.model_dump(exclude_none=True, exclude={'name', 'pinned'})
        if payload.pinned is not None:
            if current.notebook.kind != "chat":
                raise HTTPException(status_code=422, detail="Only chats can be pinned")
            patch["reader_pinned"] = payload.pinned
        if payload.selected_model is not None and payload.selected_model not in {item.id for item in MODEL_REGISTRY}:
            raise HTTPException(status_code=422, detail="Model unavailable")
        if payload.reasoning_effort is not None:
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

    @app.post('/api/v1/reader/threads/{thread_id}/move', response_model=ReaderNotebookSettings)
    def move(thread_id: str, payload: ReaderMoveChat, owner: OwnerServices = Depends(reader_owner)) -> ReaderNotebookSettings:
        """Save an owner-validated chat location without moving any conversation data."""
        row = owner.workspace.get_thread(thread_id)
        if row is None:
            raise HTTPException(status_code=404, detail="Chat not found")
        chat = reader_notebook(row)
        if chat.kind != "chat":
            raise HTTPException(status_code=422, detail="Only chats can be moved")
        target_id = payload.parent_notebook_id
        if target_id is not None:
            target = owner.workspace.get_thread(target_id)
            if target is None or reader_notebook(target).kind != "notebook":
                raise HTTPException(status_code=404, detail="Destination notebook not found")
        if chat.parent_notebook_id != target_id:
            try:
                owner.workspace.update_thread(thread_id, metadata={_PARENT_NOTEBOOK_KEY: target_id})
            except ValueError as error:
                raise HTTPException(status_code=404, detail="Chat not found") from error
        return notebook(thread_id, owner)

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
        """Read supported presentation values without exposing unrelated settings."""
        return reader_preferences(owner)

    @app.post('/api/v1/reader/preferences', response_model=ReaderPreferences)
    def appearance(payload: ReaderPreferencesPatch, owner: OwnerServices = Depends(reader_owner)) -> ReaderPreferences:
        """Merge only supplied keys with the owner's existing preferences."""
        patch = payload.model_dump(exclude_none=True)
        if not patch:
            raise HTTPException(status_code=422, detail="Choose a preference to update")
        if "display_name" in patch:
            patch["display_name"] = patch["display_name"].strip()
        owner.workspace.update_preferences({
            key if key == "appearance" else f"reader_{key}": value
            for key, value in patch.items()
        })
        return preferences(owner)

    @app.post('/api/v1/reader/threads/{thread_id}/messages/{message_id}/revise', response_model=CoachTurn)
    def reader_revise(
        thread_id: str, message_id: str, payload: ReaderRevision, request: Request,
        owner: OwnerServices = Depends(reader_owner),
    ) -> CoachTurn:
        """Delegate append-only editing and all recovery/error semantics to the shared route."""
        return revise(thread_id, message_id, payload.content, payload.idempotency_key, request, owner)

    @app.post('/api/v1/reader/threads/{thread_id}/messages/{message_id}/revise/stream')
    def reader_revise_stream(
        thread_id: str, message_id: str, payload: ReaderRevision, request: Request,
        owner: OwnerServices = Depends(reader_owner),
    ) -> StreamingResponse:
        """Stream a credential-guarded revision through the canonical lifecycle."""
        return revise_stream(thread_id, message_id, payload.content, payload.idempotency_key, request, owner)

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
