"""Typed synchronous client used by Streamlit once the local API is running."""

from __future__ import annotations

import json
from typing import Any, Iterator, Protocol

import httpx

from .domain import (
    CoachRequest,
    CoachTurn,
    MessageCreateRequest,
    NotebookCreateRequest,
    NotebookUpdateRequest,
    PendingPhaseTransition,
    PreferencePatch,
    SourceSelectAllRequest,
    SourceUpdateRequest,
)
from .workspace_service import SourceContent


class _HttpSession(Protocol):
    """Minimal sync HTTP surface used by ``LocalApiClient``."""

    def get(self, url: str, **kwargs: Any) -> Any:
        """Send a GET request."""

    def post(self, url: str, **kwargs: Any) -> Any:
        """Send a POST request."""

    def patch(self, url: str, **kwargs: Any) -> Any:
        """Send a PATCH request."""

    def delete(self, url: str, **kwargs: Any) -> Any:
        """Send a DELETE request."""

    def stream(self, method: str, url: str, **kwargs: Any) -> Any:
        """Open a streaming HTTP response context manager."""


class LocalApiClient:
    """Small typed client for the versioned local FastAPI contract.

    Production uses ``httpx.Client``. Tests may inject a Starlette/FastAPI
    ``TestClient`` (or compatible session) to exercise the same methods
    in-process without a network socket.
    """

    def __init__(
        self,
        base_url: str,
        timeout_seconds: float = 120.0,
        *,
        session: _HttpSession | None = None,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._owns_session = session is None
        self._http: _HttpSession = session or httpx.Client(
            base_url=self._base_url,
            timeout=timeout_seconds,
        )

    def close(self) -> None:
        """Close an owned httpx client; injected test sessions are left alone."""
        if not self._owns_session:
            return
        close = getattr(self._http, "close", None)
        if callable(close):
            close()

    def health(self) -> dict[str, str]:
        """Return the local API health response or raise an HTTP error."""
        response = self._http.get(f"{self._base_url}/api/v1/health")
        response.raise_for_status()
        return response.json()

    def ready(self) -> dict[str, str]:
        """Return readiness once the API can serve coaching and CRUD."""
        response = self._http.get(f"{self._base_url}/api/v1/ready")
        response.raise_for_status()
        return response.json()

    def auth_me(self, session_token: str) -> dict[str, Any] | None:
        """Return the authenticated user for an opaque session cookie, or ``None``.

        Uses the internal FastAPI base URL. A 401 means unauthenticated.
        """
        token = str(session_token or "").strip()
        if not token:
            return None
        from backend.settings import settings

        cookie_name = settings.app_session_cookie_name
        response = self._http.get(
            f"{self._base_url}/api/v1/auth/me",
            cookies={cookie_name: token},
        )
        if response.status_code == 401:
            return None
        response.raise_for_status()
        payload = response.json()
        if not isinstance(payload, dict) or not payload.get("authenticated"):
            return None
        user = payload.get("user")
        return user if isinstance(user, dict) else None

    def graph_state(self, thread_id: str) -> dict[str, Any]:
        """Return the latest inspectable coach-graph summary."""
        response = self._http.get(f"{self._base_url}/api/v1/threads/{thread_id}/graph")
        response.raise_for_status()
        return response.json()

    def get_preferences(self) -> dict[str, Any]:
        """Return local user preferences."""
        response = self._http.get(f"{self._base_url}/api/v1/preferences")
        response.raise_for_status()
        return response.json()

    def update_preferences(self, patch: dict[str, Any]) -> dict[str, Any]:
        """Merge preference keys."""
        body = PreferencePatch.model_validate(patch).model_dump(exclude_none=True)
        response = self._http.patch(
            f"{self._base_url}/api/v1/preferences", json=body
        )
        response.raise_for_status()
        return response.json()

    def list_threads(self, search: str = "") -> list[dict[str, Any]]:
        """List notebooks."""
        response = self._http.get(
            f"{self._base_url}/api/v1/threads", params={"search": search}
        )
        response.raise_for_status()
        return response.json()

    def get_thread(self, thread_id: str) -> dict[str, Any] | None:
        """Return one notebook or ``None`` when missing."""
        response = self._http.get(f"{self._base_url}/api/v1/threads/{thread_id}")
        if response.status_code == 404:
            return None
        response.raise_for_status()
        return response.json()

    def create_thread(self, request: NotebookCreateRequest) -> dict[str, Any]:
        """Create a notebook."""
        response = self._http.post(
            f"{self._base_url}/api/v1/threads",
            json=request.model_dump(mode="json"),
        )
        response.raise_for_status()
        return response.json()

    def update_thread(
        self, thread_id: str, request: NotebookUpdateRequest
    ) -> dict[str, Any]:
        """Rename a notebook and/or merge metadata."""
        response = self._http.patch(
            f"{self._base_url}/api/v1/threads/{thread_id}",
            json=request.model_dump(mode="json", exclude_none=True),
        )
        response.raise_for_status()
        return response.json()

    def delete_thread(self, thread_id: str) -> None:
        """Delete a notebook."""
        response = self._http.delete(f"{self._base_url}/api/v1/threads/{thread_id}")
        response.raise_for_status()

    def get_messages(self, thread_id: str) -> list[dict[str, Any]]:
        """Return chat history."""
        response = self._http.get(
            f"{self._base_url}/api/v1/threads/{thread_id}/messages"
        )
        response.raise_for_status()
        return response.json()

    def add_message(self, thread_id: str, request: MessageCreateRequest) -> str:
        """Persist one message and return its id."""
        response = self._http.post(
            f"{self._base_url}/api/v1/threads/{thread_id}/messages",
            json=request.model_dump(mode="json"),
        )
        response.raise_for_status()
        return str(response.json()["id"])

    def list_sources(
        self, thread_id: str, *, selected_only: bool = False
    ) -> list[dict[str, Any]]:
        """List notebook sources."""
        response = self._http.get(
            f"{self._base_url}/api/v1/threads/{thread_id}/sources",
            params={"selected_only": selected_only},
        )
        response.raise_for_status()
        return response.json()

    def get_source(self, thread_id: str, source_id: str) -> dict[str, Any] | None:
        """Return one source or ``None``."""
        response = self._http.get(
            f"{self._base_url}/api/v1/threads/{thread_id}/sources/{source_id}"
        )
        if response.status_code == 404:
            return None
        response.raise_for_status()
        return response.json()

    def upload_sources(
        self,
        thread_id: str,
        uploads: list[tuple[str, bytes, str | None]],
    ) -> list[dict[str, Any]]:
        """Upload files into the source library."""
        files = [
            ("files", (name, data, mime or "application/octet-stream"))
            for name, data, mime in uploads
        ]
        response = self._http.post(
            f"{self._base_url}/api/v1/threads/{thread_id}/sources",
            files=files,
        )
        response.raise_for_status()
        return response.json()

    def update_source(
        self, thread_id: str, source_id: str, request: SourceUpdateRequest
    ) -> dict[str, Any]:
        """Rename and/or change selection for one source."""
        response = self._http.patch(
            f"{self._base_url}/api/v1/threads/{thread_id}/sources/{source_id}",
            json=request.model_dump(mode="json", exclude_none=True),
        )
        response.raise_for_status()
        return response.json()

    def select_all_sources(self, thread_id: str, selected: bool) -> list[dict[str, Any]]:
        """Select or deselect every source."""
        body = SourceSelectAllRequest(selected=selected).model_dump(mode="json")
        response = self._http.post(
            f"{self._base_url}/api/v1/threads/{thread_id}/sources/select-all",
            json=body,
        )
        response.raise_for_status()
        return response.json()

    def delete_source(self, thread_id: str, source_id: str) -> None:
        """Delete a source."""
        response = self._http.delete(
            f"{self._base_url}/api/v1/threads/{thread_id}/sources/{source_id}"
        )
        response.raise_for_status()

    def get_source_content(self, thread_id: str, source_id: str) -> SourceContent:
        """Download source file bytes for preview."""
        response = self._http.get(
            f"{self._base_url}/api/v1/threads/{thread_id}/sources/{source_id}/content"
        )
        response.raise_for_status()
        mime = response.headers.get("content-type", "application/octet-stream")
        filename = "source.bin"
        disposition = response.headers.get("content-disposition") or ""
        if "filename*=" in disposition:
            filename = disposition.split("filename*=UTF-8''", 1)[-1].strip()
        return SourceContent(data=response.content, mime=mime, filename=filename)

    def backfill_legacy_sources(self, thread_id: str) -> int:
        """Import legacy attachments."""
        response = self._http.post(
            f"{self._base_url}/api/v1/threads/{thread_id}/sources/backfill-legacy"
        )
        response.raise_for_status()
        return int(response.json().get("created") or 0)

    def sync_course_materials(self, thread_id: str) -> dict[str, Any]:
        """Synchronize course materials into the notebook."""
        response = self._http.post(
            f"{self._base_url}/api/v1/threads/{thread_id}/sources/sync-course-materials"
        )
        response.raise_for_status()
        return response.json()

    def learning_state(self, thread_id: str) -> dict:
        """Return persisted learning metadata for one notebook."""
        response = self._http.get(
            f"{self._base_url}/api/v1/threads/{thread_id}/learning-state"
        )
        response.raise_for_status()
        payload = response.json()
        return payload if isinstance(payload, dict) else {}

    def coach_turn(self, request: CoachRequest) -> CoachTurn:
        """Submit one typed coaching turn to the local backend."""
        response = self._http.post(
            f"{self._base_url}/api/v1/coach/turn",
            json=request.model_dump(mode="json"),
        )
        response.raise_for_status()
        return CoachTurn.model_validate(response.json())

    def stream_coach_turn(self, request: CoachRequest) -> Iterator[dict[str, Any]]:
        """Yield NDJSON events from the streaming coaching endpoint."""
        with self._http.stream(
            "POST",
            f"{self._base_url}/api/v1/coach/turn/stream",
            json=request.model_dump(mode="json"),
        ) as response:
            response.raise_for_status()
            for line in response.iter_lines():
                if not line:
                    continue
                payload = json.loads(line)
                if isinstance(payload, dict):
                    yield payload

    def pending_transition(self, thread_id: str) -> PendingPhaseTransition | None:
        """Return the unresolved transition recommendation for one notebook."""
        response = self._http.get(
            f"{self._base_url}/api/v1/threads/{thread_id}/phase-transitions/pending"
        )
        response.raise_for_status()
        payload = response.json()
        return PendingPhaseTransition.model_validate(payload) if payload else None

    def resolve_transition(
        self,
        thread_id: str,
        transition_id: str,
        accepted: bool,
    ) -> PendingPhaseTransition:
        """Send the student's explicit decision for a pending transition."""
        response = self._http.post(
            f"{self._base_url}/api/v1/threads/{thread_id}/phase-transitions/"
            f"{transition_id}/resolve",
            json={"accepted": accepted},
        )
        response.raise_for_status()
        return PendingPhaseTransition.model_validate(response.json())
