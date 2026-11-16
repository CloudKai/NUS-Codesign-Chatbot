"""Authenticated browser projection over existing owner-scoped workspace services."""

from collections.abc import Callable
from pathlib import Path
from typing import Any, Literal
from urllib.parse import quote

from fastapi import Depends, FastAPI, HTTPException, Query, Request
from pydantic import BaseModel, ConfigDict, Field
from fastapi.responses import FileResponse, StreamingResponse, Response

from backend.domain import CitationReference, CoachRequest, CoachTurn
from backend.learning.journey import normalize_journey
from backend.owner_context import OwnerServices
from backend.settings import settings


class ReaderSession(BaseModel):
    """Nonsecret identity used to fence in-memory browser state."""

    owner_id: str
    display_name: str
    kind: Literal["guest", "registered"]


class ReaderNotebook(BaseModel):
    """Notebook list entry without educational, research, or storage metadata."""

    id: str
    name: str


class ReaderNotebooks(BaseModel):
    """Owner-fenced notebook list for the read-only pilot."""

    owner_id: str
    notebooks: list[ReaderNotebook]


class ReaderMessage(BaseModel):
    """Visible saved message without private assessment or storage metadata."""

    id: str
    role: Literal["user", "assistant"]
    content: str
    citations: list[CitationReference] = Field(default_factory=list)


class ReaderPage(BaseModel):
    """Chronological transcript page fenced to owner, notebook, and revision."""

    owner_id: str
    notebook: ReaderNotebook
    messages: list[ReaderMessage]
    next_cursor: str | None
    total_count: int
    conversation_revision: int


class LectureRequest(BaseModel):
    """Bounded lecture input; source, stage and model authority remain on the server."""

    model_config = ConfigDict(extra="forbid")
    student_message: str = Field(min_length=1, max_length=12_000)
    idempotency_key: str = Field(min_length=1, max_length=128, pattern=r"^[A-Za-z0-9][A-Za-z0-9._:-]*$")


def _message(row: dict[str, Any]) -> ReaderMessage:
    """Project saved citations only, keeping research and storage fields private."""
    metadata = row.get("metadata")
    assessment = metadata.get("assessment") if isinstance(metadata, dict) else None
    values = assessment.get("citations") if isinstance(assessment, dict) else None
    citations = []
    for value in values if isinstance(values, list) and row["role"] == "assistant" else []:
        try:
            citations.append(CitationReference.model_validate(value))
        except ValueError:
            continue
    return ReaderMessage(id=row["id"], role=row["role"], content=row["content"], citations=citations)


def _notebook(row: dict[str, Any]) -> ReaderNotebook:
    return ReaderNotebook(id=row["id"], name=row["name"])


def register_notebook_reader(
    app: FastAPI, resolve_owner: Callable[[Request], OwnerServices],
    stream_turn: Callable[[CoachRequest, Request, OwnerServices], StreamingResponse],
) -> None:
    """Register bounded student conversation routes; never use the anonymous local demo owner."""

    def reader_owner(request: Request) -> OwnerServices:
        """Require credentials and delegate verification to the existing resolver."""
        credential = str(request.cookies.get(settings.cognito_id_token_cookie_name) or "").strip()
        guest = settings.guest_access_enabled and str(request.cookies.get(settings.guest_session_cookie_name) or "").strip()
        if not credential and not guest:
            raise HTTPException(status_code=401, detail="Not authenticated")
        if request.headers.get("sec-fetch-site") == "cross-site":
            raise HTTPException(status_code=403, detail="Same-origin request required")
        origin = request.headers.get("origin")
        if origin and origin.rstrip("/") != settings.public_api_base_url.rstrip("/"):
            raise HTTPException(status_code=403, detail="Same-origin request required")
        if request.method == "POST" and not origin:
            raise HTTPException(status_code=403, detail="Same-origin request required")
        owner = resolve_owner(request)
        profile = owner.store.get_user_by_id(owner.user_id) or {}
        if profile.get("role", "student") != "student":
            raise HTTPException(status_code=403, detail="Open the lecturer workspace in Streamlit")
        return owner

    @app.get("/api/v1/reader/session", response_model=ReaderSession)
    def session(owner: OwnerServices = Depends(reader_owner)) -> ReaderSession:
        """Return the verified owner without tokens or private profile fields."""
        profile = owner.store.get_user_by_id(owner.user_id) or {}
        return ReaderSession(
            owner_id=owner.user_id,
            display_name=str(profile.get("display_name") or "Student"),
            kind="guest" if owner.identifier.startswith("guest:") else "registered",
        )

    @app.get("/api/v1/reader/threads", response_model=ReaderNotebooks)
    def notebooks(owner: OwnerServices = Depends(reader_owner)) -> ReaderNotebooks:
        """List owned notebooks without changing or migrating their data."""
        return ReaderNotebooks(owner_id=owner.user_id, notebooks=[
            _notebook(row)
            for row in owner.workspace.list_threads()
        ])

    @app.get("/api/v1/reader/threads/{thread_id}/messages/page", response_model=ReaderPage)
    def messages(
        thread_id: str,
        limit: int = Query(20, ge=1, le=100),
        cursor: str | None = Query(None, max_length=2048),
        owner: OwnerServices = Depends(reader_owner),
    ) -> ReaderPage:
        """Read active saved history using existing revision-bound pagination."""
        notebook = owner.workspace.get_thread(thread_id)
        if notebook is None:
            raise HTTPException(status_code=404, detail="Notebook not found")
        try:
            page = owner.workspace.get_message_page(thread_id, limit=limit, cursor=cursor)
        except ValueError as error:
            status = int(getattr(error, "status_code", 400))
            raise HTTPException(status_code=status, detail="History changed. Reopen the notebook.") from error
        return ReaderPage(
            owner_id=owner.user_id, notebook=_notebook(notebook),
            messages=[_message(row) for row in page["messages"]],
            next_cursor=page["next_cursor"], total_count=page["total_count"],
            conversation_revision=page["conversation_revision"],
        )

    @app.post("/api/v1/reader/threads/{thread_id}/lecture/stream")
    def lecture_stream(
        thread_id: str, payload: LectureRequest, request: Request,
        owner: OwnerServices = Depends(reader_owner),
    ) -> StreamingResponse:
        """Reuse the shared dispatch/preview/save lifecycle with server-owned lecture intent."""
        thread = owner.workspace.get_thread(thread_id)
        if thread is None:
            raise HTTPException(status_code=404, detail="Notebook not found")
        journey = normalize_journey((thread.get("metadata") or {}).get("learning_journey"))
        coach_request = CoachRequest(
            thread_id=thread_id, student_message=payload.student_message,
            idempotency_key=payload.idempotency_key, interaction_intent="lecture_help",
            current_stage=journey["current_stage"], response_detail=journey["response_detail"],
        )
        return stream_turn(coach_request, request, owner)

    @app.get("/api/v1/reader/threads/{thread_id}/coach-turn", response_model=CoachTurn | None)
    def saved_turn(
        thread_id: str, idempotency_key: str = Query(min_length=1, max_length=128),
        owner: OwnerServices = Depends(reader_owner),
    ) -> CoachTurn | None:
        """Reconcile by the exact saved identity without starting or replaying generation."""
        if owner.workspace.get_thread(thread_id) is None:
            raise HTTPException(status_code=404, detail="Notebook not found")
        return owner.coach.completed_turn(thread_id, idempotency_key)

    @app.get("/api/v1/reader/threads/{thread_id}/messages/{message_id}/citations/{source_id}/content")
    def cited_content(
        thread_id: str, message_id: str, source_id: str,
        owner: OwnerServices = Depends(reader_owner),
    ) -> Response:
        """Download only evidence mapped to an active saved answer in this notebook."""
        if owner.workspace.get_thread(thread_id) is None:
            raise HTTPException(status_code=404, detail="Notebook not found")
        row = owner.workspace.get_active_message(thread_id, message_id)
        if row is not None and row["role"] != "assistant":
            row = None
        if row is None or not any(citation.source_id == source_id for citation in _message(row).citations):
            raise HTTPException(status_code=404, detail="Saved citation not found")
        try:
            content = owner.workspace.read_source_content(thread_id, source_id)
        except ValueError as error:
            raise HTTPException(status_code=404, detail="Source no longer available") from error
        return Response(content.data, media_type="application/octet-stream", headers={
            "Content-Disposition": "attachment; filename*=UTF-8''" + quote(content.filename, safe=""),
            "X-Content-Type-Options": "nosniff",
        })

    @app.get("/pilot/{asset_path:path}", include_in_schema=False)
    def pilot_asset(asset_path: str) -> FileResponse:
        """Serve built public assets only; missing builds never break Streamlit startup."""
        root = Path(__file__).resolve().parents[2] / "frontend" / "dist"
        relative = asset_path or "index.html"
        path = (root / relative).resolve()
        if not path.is_relative_to(root.resolve()) or path.suffix not in {".html", ".js", ".css", ".svg", ".ico", ".ttf", ".txt"}:
            raise HTTPException(status_code=404, detail="Not found")
        if not path.is_file():
            raise HTTPException(status_code=404, detail="Not found")
        return FileResponse(path, headers={
            "Cache-Control": "no-store",
            "X-Content-Type-Options": "nosniff",
            "Content-Security-Policy": "default-src 'self'; script-src 'self'; style-src 'self'; connect-src 'self'; img-src 'self' data:; object-src 'none'; base-uri 'none'; frame-ancestors 'none'",
        })
