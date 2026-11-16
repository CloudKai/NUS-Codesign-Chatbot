"""Read-only browser projection over existing owner-scoped workspace services."""

from collections.abc import Callable
from pathlib import Path
from typing import Any, Literal

from fastapi import Depends, FastAPI, HTTPException, Query, Request
from pydantic import BaseModel
from fastapi.responses import FileResponse

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


class ReaderPage(BaseModel):
    """Chronological transcript page fenced to owner, notebook, and revision."""

    owner_id: str
    notebook: ReaderNotebook
    messages: list[ReaderMessage]
    next_cursor: str | None
    total_count: int
    conversation_revision: int


def _notebook(row: dict[str, Any]) -> ReaderNotebook:
    return ReaderNotebook(id=row["id"], name=row["name"])


def register_notebook_reader(
    app: FastAPI, resolve_owner: Callable[[Request], OwnerServices]
) -> None:
    """Register authenticated reads; never use the anonymous local demo owner."""

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
            messages=[ReaderMessage.model_validate(row) for row in page["messages"]],
            next_cursor=page["next_cursor"], total_count=page["total_count"],
            conversation_revision=page["conversation_revision"],
        )

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
