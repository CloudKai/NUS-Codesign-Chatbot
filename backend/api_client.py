"""Typed synchronous client used by Streamlit once the local API is running."""

from __future__ import annotations

import json
from typing import Any, Callable, Iterator, Mapping, Protocol
from urllib.parse import quote, unquote

import httpx

from .domain import (
    CoachRequest,
    CoachTurn,
    DeepReviewJob,
    MessageCreateRequest,
    NotebookCreateRequest,
    NotebookUpdateRequest,
    PendingPhaseTransition,
    PreferencePatch,
    SourceSelectAllRequest,
    SourceUpdateRequest,
)
from .workspace_service import SourceContent, TranscriptExport


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

    When Streamlit holds a Cognito ID-token cookie, ``cookie_provider`` forwards
    only that short-lived cookie so FastAPI can resolve the owner. The refresh
    token never reaches this client.
    """

    def __init__(
        self,
        base_url: str,
        timeout_seconds: float = 120.0,
        *,
        session: _HttpSession | None = None,
        cookie_provider: Callable[[], Mapping[str, str]] | None = None,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._owns_session = session is None
        self._cookie_provider = cookie_provider
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

    def _auth_cookies(self, extra: Mapping[str, str] | None = None) -> dict[str, str]:
        """Merge dynamic Cognito ID cookies with any call-site extras."""
        cookies: dict[str, str] = {}
        if self._cookie_provider is not None:
            provided = self._cookie_provider() or {}
            for key, value in provided.items():
                cleaned = str(value or "").strip()
                if cleaned:
                    cookies[str(key)] = cleaned
        if extra:
            for key, value in extra.items():
                cleaned = str(value or "").strip()
                if cleaned:
                    cookies[str(key)] = cleaned
        return cookies

    def auth_cookies_snapshot(self) -> dict[str, str]:
        """Capture the current request's ID-cookie for a background upload."""
        return self._auth_cookies()

    def _request_kwargs(self, **kwargs: Any) -> dict[str, Any]:
        """Attach auth cookies without dropping caller-supplied cookie maps."""
        merged = self._auth_cookies(kwargs.pop("cookies", None))
        if merged:
            kwargs["cookies"] = merged
        return kwargs

    def auth_cookie_snapshot(self) -> dict[str, str]:
        """Capture the current short-lived auth cookie for a worker request.

        Streamlit's cookie context is bound to its script thread. Background
        course-material synchronization must therefore take this snapshot on
        the render thread instead of invoking ``cookie_provider`` later from a
        worker where the browser context is unavailable.
        """
        return self._auth_cookies()

    def health(self) -> dict[str, str]:
        """Return the local API health response or raise an HTTP error."""
        response = self._http.get(
            f"{self._base_url}/api/v1/health", **self._request_kwargs()
        )
        response.raise_for_status()
        return response.json()

    def ready(self) -> dict[str, str]:
        """Return readiness once the API can serve coaching and CRUD."""
        response = self._http.get(
            f"{self._base_url}/api/v1/ready", **self._request_kwargs()
        )
        response.raise_for_status()
        return response.json()

    def auth_me(
        self,
        id_token: str | None = None,
    ) -> dict[str, Any] | None:
        """Return the authenticated user for Cognito auth cookies, or ``None``.

        Uses the internal FastAPI base URL. A 401 means unauthenticated.
        Only the short-lived ID-token cookie is forwarded. The refresh token is
        scoped to the browser-facing auth path and never reaches Streamlit.
        """
        from backend.settings import settings

        id_value = str(id_token or "").strip()
        cookies: dict[str, str] = {}
        if id_value:
            cookies[settings.cognito_id_token_cookie_name] = id_value
        response = self._http.get(
            f"{self._base_url}/api/v1/auth/me",
            **self._request_kwargs(cookies=cookies or None),
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
        response = self._http.get(
            f"{self._base_url}/api/v1/threads/{thread_id}/graph",
            **self._request_kwargs(),
        )
        response.raise_for_status()
        return response.json()

    def professor_overview(self) -> dict[str, Any]:
        """Return professor-authorised class overview analytics."""
        response = self._http.get(
            f"{self._base_url}/api/v1/professor/overview", **self._request_kwargs()
        )
        response.raise_for_status()
        return response.json()

    def professor_students(self, **filters: Any) -> dict[str, Any]:
        """Return professor-authorised roster data with server-side filters."""
        response = self._http.get(
            f"{self._base_url}/api/v1/professor/students",
            params={key: value for key, value in filters.items() if value not in (None, "")},
            **self._request_kwargs(),
        )
        response.raise_for_status()
        return response.json()

    def professor_student_detail(self, student_id: str) -> dict[str, Any]:
        """Return one professor-authorised student's learning journey."""
        response = self._http.get(
            f"{self._base_url}/api/v1/professor/students/{student_id}",
            **self._request_kwargs(),
        )
        response.raise_for_status()
        return response.json()

    def professor_conversation_transcript(
        self, student_id: str, notebook_id: str
    ) -> dict[str, Any]:
        """Return one selected active-branch transcript for teaching review."""
        response = self._http.get(
            f"{self._base_url}/api/v1/professor/students/{student_id}/conversations/{notebook_id}",
            **self._request_kwargs(),
        )
        response.raise_for_status()
        return response.json()

    def professor_conversation_attachment(
        self, student_id: str, notebook_id: str, attachment_id: str
    ) -> SourceContent:
        """Fetch one authorized transcript attachment on explicit user action."""
        response = self._http.get(
            f"{self._base_url}/api/v1/professor/students/{student_id}"
            f"/conversations/{notebook_id}/attachments/{attachment_id}",
            **self._request_kwargs(),
        )
        response.raise_for_status()
        mime = response.headers.get("content-type", "application/octet-stream")
        filename = "attachment.bin"
        disposition = response.headers.get("content-disposition") or ""
        if "filename*=" in disposition:
            filename = unquote(
                disposition.split("filename*=UTF-8''", 1)[-1].strip()
            )
        return SourceContent(data=response.content, mime=mime, filename=filename)

    def professor_notebook_workspace(
        self, student_id: str, notebook_id: str
    ) -> dict[str, Any]:
        """Return one authorised read-only notebook workspace for lecturers."""
        response = self._http.get(
            f"{self._base_url}/api/v1/professor/students/{student_id}"
            f"/conversations/{notebook_id}/workspace",
            **self._request_kwargs(),
        )
        response.raise_for_status()
        return response.json()

    def professor_notebook_source(
        self, student_id: str, notebook_id: str, source_id: str
    ) -> SourceContent:
        """Fetch one authorised library source on explicit lecturer action."""
        response = self._http.get(
            f"{self._base_url}/api/v1/professor/students/{student_id}"
            f"/conversations/{notebook_id}/sources/{source_id}",
            **self._request_kwargs(),
        )
        response.raise_for_status()
        mime = response.headers.get("content-type", "application/octet-stream")
        filename = "source.bin"
        disposition = response.headers.get("content-disposition") or ""
        if "filename*=" in disposition:
            filename = unquote(
                disposition.split("filename*=UTF-8''", 1)[-1].strip()
            )
        return SourceContent(data=response.content, mime=mime, filename=filename)

    def professor_critical_thinking(self) -> dict[str, Any]:
        """Return professor-authorised Facione analytics."""
        response = self._http.get(
            f"{self._base_url}/api/v1/professor/critical-thinking", **self._request_kwargs()
        )
        response.raise_for_status()
        return response.json()

    def professor_engagement(self) -> dict[str, Any]:
        """Return professor-authorised engagement analytics."""
        response = self._http.get(
            f"{self._base_url}/api/v1/professor/engagement", **self._request_kwargs()
        )
        response.raise_for_status()
        return response.json()

    def professor_research_summary(self) -> dict[str, Any]:
        """Return aggregate automated research-coding status."""
        response = self._http.get(
            f"{self._base_url}/api/v1/professor/research/summary",
            **self._request_kwargs(),
        )
        response.raise_for_status()
        return response.json()

    def professor_research_queue(self, **filters: Any) -> dict[str, Any]:
        """Return an audited page of identifiable research observations."""
        response = self._http.get(
            f"{self._base_url}/api/v1/professor/research/queue",
            params={
                key: value
                for key, value in filters.items()
                if value not in (None, "")
            },
            **self._request_kwargs(),
        )
        response.raise_for_status()
        return response.json()

    def professor_research_notebook(
        self,
        notebook_id: str,
        *,
        observation_limit: int = 100,
        observation_offset: int = 0,
    ) -> dict[str, Any]:
        """Return one audited research notebook detail."""
        response = self._http.get(
            f"{self._base_url}/api/v1/professor/research/notebooks/"
            f"{quote(notebook_id, safe='')}",
            params={
                "observation_limit": observation_limit,
                "observation_offset": observation_offset,
            },
            **self._request_kwargs(),
        )
        response.raise_for_status()
        return response.json()

    def professor_submit_research_review(
        self, payload: Mapping[str, Any]
    ) -> dict[str, Any]:
        """Append one human validation; reviewer identity stays server-side."""
        response = self._http.post(
            f"{self._base_url}/api/v1/professor/research/reviews",
            json=dict(payload),
            **self._request_kwargs(),
        )
        response.raise_for_status()
        return response.json()

    def professor_submit_research_adjudication(
        self, payload: Mapping[str, Any]
    ) -> dict[str, Any]:
        """Append one adjudication; actor identity stays server-side."""
        response = self._http.post(
            f"{self._base_url}/api/v1/professor/research/adjudications",
            json=dict(payload),
            **self._request_kwargs(),
        )
        response.raise_for_status()
        return response.json()

    def professor_research_export(self, **filters: Any) -> bytes:
        """Return an audited formula-safe research CSV export."""
        response = self._http.get(
            f"{self._base_url}/api/v1/professor/research/export.csv",
            params={
                key: value
                for key, value in filters.items()
                if value not in (None, "")
            },
            **self._request_kwargs(),
        )
        response.raise_for_status()
        return bytes(response.content)

    def get_preferences(self) -> dict[str, Any]:
        """Return local user preferences."""
        response = self._http.get(
            f"{self._base_url}/api/v1/preferences", **self._request_kwargs()
        )
        response.raise_for_status()
        return response.json()

    def update_preferences(self, patch: dict[str, Any]) -> dict[str, Any]:
        """Merge preference keys."""
        body = PreferencePatch.model_validate(patch).model_dump(exclude_none=True)
        response = self._http.patch(
            f"{self._base_url}/api/v1/preferences",
            json=body,
            **self._request_kwargs(),
        )
        response.raise_for_status()
        return response.json()

    def list_threads(self, search: str = "") -> list[dict[str, Any]]:
        """List notebooks."""
        response = self._http.get(
            f"{self._base_url}/api/v1/threads",
            params={"search": search},
            **self._request_kwargs(),
        )
        response.raise_for_status()
        return response.json()

    def get_thread(self, thread_id: str) -> dict[str, Any] | None:
        """Return one notebook or ``None`` when missing."""
        response = self._http.get(
            f"{self._base_url}/api/v1/threads/{thread_id}",
            **self._request_kwargs(),
        )
        if response.status_code == 404:
            return None
        response.raise_for_status()
        return response.json()

    def create_thread(self, request: NotebookCreateRequest) -> dict[str, Any]:
        """Create a notebook."""
        response = self._http.post(
            f"{self._base_url}/api/v1/threads",
            json=request.model_dump(mode="json"),
            **self._request_kwargs(),
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
            **self._request_kwargs(),
        )
        response.raise_for_status()
        return response.json()

    def delete_thread(self, thread_id: str) -> None:
        """Delete a notebook."""
        response = self._http.delete(
            f"{self._base_url}/api/v1/threads/{thread_id}",
            **self._request_kwargs(),
        )
        response.raise_for_status()

    def get_messages(self, thread_id: str) -> list[dict[str, Any]]:
        """Return chat history."""
        response = self._http.get(
            f"{self._base_url}/api/v1/threads/{thread_id}/messages",
            **self._request_kwargs(),
        )
        response.raise_for_status()
        return response.json()

    def download_transcript(self, thread_id: str) -> TranscriptExport:
        """Download the persisted notebook transcript as UTF-8 ``.txt``."""
        response = self._http.get(
            f"{self._base_url}/api/v1/threads/{thread_id}/transcript.txt",
            **self._request_kwargs(),
        )
        response.raise_for_status()
        mime = response.headers.get("content-type", "text/plain; charset=utf-8")
        filename = "transcript.txt"
        disposition = response.headers.get("content-disposition") or ""
        if "filename*=" in disposition:
            filename = disposition.split("filename*=UTF-8''", 1)[-1].strip()
        return TranscriptExport(
            data=bytes(response.content),
            filename=filename,
            mime=mime,
        )

    def add_message(self, thread_id: str, request: MessageCreateRequest) -> str:
        """Persist one message and return its id."""
        response = self._http.post(
            f"{self._base_url}/api/v1/threads/{thread_id}/messages",
            json=request.model_dump(mode="json"),
            **self._request_kwargs(),
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
            **self._request_kwargs(),
        )
        response.raise_for_status()
        return response.json()

    def get_source(self, thread_id: str, source_id: str) -> dict[str, Any] | None:
        """Return one source or ``None``."""
        response = self._http.get(
            f"{self._base_url}/api/v1/threads/{thread_id}/sources/{source_id}",
            **self._request_kwargs(),
        )
        if response.status_code == 404:
            return None
        response.raise_for_status()
        return response.json()

    def upload_sources(
        self,
        thread_id: str,
        uploads: list[tuple[str, bytes, str | None]],
        *,
        auth_cookies: Mapping[str, str] | None = None,
    ) -> list[dict[str, Any]]:
        """Upload files into the source library."""
        files = [
            ("files", (name, data, mime or "application/octet-stream"))
            for name, data, mime in uploads
        ]
        response = self._http.post(
            f"{self._base_url}/api/v1/threads/{thread_id}/sources",
            files=files,
            **(
                self._request_kwargs()
                if auth_cookies is None
                else {"cookies": self._auth_cookies(auth_cookies)}
            ),
        )
        response.raise_for_status()
        return response.json()

    def upload_attachments(
        self,
        thread_id: str,
        uploads: list[tuple[str, bytes, str | None]],
    ) -> list[dict[str, Any]]:
        """Upload private attachments for exactly one coaching turn."""
        files = [
            ("files", (name, data, mime or "application/octet-stream"))
            for name, data, mime in uploads
        ]
        response = self._http.post(
            f"{self._base_url}/api/v1/threads/{thread_id}/attachments",
            files=files,
            **self._request_kwargs(),
        )
        response.raise_for_status()
        payload = response.json()
        return payload if isinstance(payload, list) else []

    def update_source(
        self, thread_id: str, source_id: str, request: SourceUpdateRequest
    ) -> dict[str, Any]:
        """Rename and/or change selection for one source."""
        response = self._http.patch(
            f"{self._base_url}/api/v1/threads/{thread_id}/sources/{source_id}",
            json=request.model_dump(mode="json", exclude_none=True),
            **self._request_kwargs(),
        )
        response.raise_for_status()
        return response.json()

    def select_all_sources(self, thread_id: str, selected: bool) -> list[dict[str, Any]]:
        """Select or deselect every source."""
        body = SourceSelectAllRequest(selected=selected).model_dump(mode="json")
        response = self._http.post(
            f"{self._base_url}/api/v1/threads/{thread_id}/sources/select-all",
            json=body,
            **self._request_kwargs(),
        )
        response.raise_for_status()
        return response.json()

    def delete_source(self, thread_id: str, source_id: str) -> None:
        """Delete a source."""
        response = self._http.delete(
            f"{self._base_url}/api/v1/threads/{thread_id}/sources/{source_id}",
            **self._request_kwargs(),
        )
        response.raise_for_status()

    def get_source_content(self, thread_id: str, source_id: str) -> SourceContent:
        """Download source file bytes for preview."""
        response = self._http.get(
            f"{self._base_url}/api/v1/threads/{thread_id}/sources/{source_id}/content",
            **self._request_kwargs(),
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
            f"{self._base_url}/api/v1/threads/{thread_id}/sources/backfill-legacy",
            **self._request_kwargs(),
        )
        response.raise_for_status()
        return int(response.json().get("created") or 0)

    def sync_course_materials(
        self,
        thread_id: str,
        *,
        auth_cookies: Mapping[str, str] | None = None,
    ) -> dict[str, Any]:
        """Synchronize course materials using an optional cookie snapshot."""
        request_kwargs = (
            self._request_kwargs()
            if auth_cookies is None
            else {
                "cookies": {
                    str(key): str(value).strip()
                    for key, value in auth_cookies.items()
                    if str(value or "").strip()
                }
            }
        )
        response = self._http.post(
            f"{self._base_url}/api/v1/threads/{thread_id}/sources/sync-course-materials",
            **request_kwargs,
        )
        response.raise_for_status()
        return response.json()

    def learning_state(self, thread_id: str) -> dict:
        """Return persisted learning metadata for one notebook."""
        response = self._http.get(
            f"{self._base_url}/api/v1/threads/{thread_id}/learning-state",
            **self._request_kwargs(),
        )
        response.raise_for_status()
        payload = response.json()
        return payload if isinstance(payload, dict) else {}

    def select_stage(self, thread_id: str, stage_id: str) -> dict:
        """Move the notebook to a student-chosen Thinking Path stage."""
        response = self._http.post(
            f"{self._base_url}/api/v1/threads/{thread_id}/learning-state/select-stage",
            json={"stage_id": stage_id},
            **self._request_kwargs(),
        )
        response.raise_for_status()
        payload = response.json()
        return payload if isinstance(payload, dict) else {}

    def revise_message(
        self,
        thread_id: str,
        message_id: str,
        content: str,
        *,
        idempotency_key: str,
        model_id: str | None = None,
        reasoning_effort: str | None = None,
        response_detail: str | None = None,
        response_language: str | None = None,
    ) -> CoachTurn:
        """Revise a user message via append-only supersede and regenerate the coach."""
        body: dict[str, Any] = {
            "content": content,
            "idempotency_key": idempotency_key,
        }
        if model_id is not None:
            body["model_id"] = model_id
        if reasoning_effort is not None:
            body["reasoning_effort"] = reasoning_effort
        if response_detail is not None:
            body["response_detail"] = response_detail
        if response_language is not None:
            body["response_language"] = response_language
        response = self._http.post(
            f"{self._base_url}/api/v1/threads/{thread_id}/messages/{message_id}/revise",
            json=body,
            **self._request_kwargs(),
        )
        response.raise_for_status()
        return CoachTurn.model_validate(response.json())

    def pending_transition(self, thread_id: str) -> PendingPhaseTransition | None:
        """Return the unresolved transition recommendation for one notebook."""
        response = self._http.get(
            f"{self._base_url}/api/v1/threads/{thread_id}/phase-transitions/pending",
            **self._request_kwargs(),
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
            **self._request_kwargs(),
        )
        response.raise_for_status()
        return PendingPhaseTransition.model_validate(response.json())

    def _idempotency_request_kwargs(
        self,
        request: CoachRequest,
        extra_headers: Mapping[str, str] | None = None,
    ) -> dict[str, Any]:
        """Attach auth cookies and optional Idempotency-Key / correlation headers."""
        headers: dict[str, str] = {}
        if request.idempotency_key:
            headers["Idempotency-Key"] = request.idempotency_key
        if extra_headers:
            for key, value in extra_headers.items():
                cleaned = str(value or "").strip()
                if cleaned:
                    headers[str(key)] = cleaned
        return self._request_kwargs(**({"headers": headers} if headers else {}))

    def coach_turn(self, request: CoachRequest) -> CoachTurn:
        """Submit one typed coaching turn to the local backend."""
        response = self._http.post(
            f"{self._base_url}/api/v1/coach/turn",
            json=request.model_dump(mode="json"),
            **self._idempotency_request_kwargs(request),
        )
        response.raise_for_status()
        return CoachTurn.model_validate(response.json())

    def start_deep_review(
        self,
        thread_id: str,
        *,
        idempotency_key: str | None = None,
    ) -> DeepReviewJob:
        """Enqueue a server-owned explicit Deep Review for one owned notebook."""
        payload: dict[str, Any] = {}
        if idempotency_key:
            payload["idempotency_key"] = idempotency_key
        headers = {"Idempotency-Key": idempotency_key} if idempotency_key else None
        kwargs = self._request_kwargs(**({"headers": headers} if headers else {}))
        response = self._http.post(
            f"{self._base_url}/api/v1/threads/{quote(thread_id, safe='')}/deep-review",
            json=payload,
            **kwargs,
        )
        response.raise_for_status()
        return DeepReviewJob.model_validate(response.json())

    def get_deep_review(self, thread_id: str) -> DeepReviewJob:
        """Return the owner-scoped Deep Review job for one notebook."""
        response = self._http.get(
            f"{self._base_url}/api/v1/threads/{quote(thread_id, safe='')}/deep-review",
            **self._request_kwargs(),
        )
        response.raise_for_status()
        return DeepReviewJob.model_validate(response.json())

    @staticmethod
    def coaching_error_category(payload: Mapping[str, Any] | None) -> str:
        """Return the structured coaching error category from an API payload.

        Stream error events carry ``category`` at the top level. JSON 503
        bodies nest it under ``detail``. Missing or malformed payloads return
        an empty string rather than guessing from message text.

        Args:
            payload: A stream event dict or a decoded HTTP JSON body.

        Returns:
            The category token, or ``""`` when none is present.
        """
        if not isinstance(payload, Mapping):
            return ""
        category = str(payload.get("category") or "").strip()
        if category:
            return category
        detail = payload.get("detail")
        if isinstance(detail, Mapping):
            return str(detail.get("category") or "").strip()
        return ""

    def stream_coach_turn(
        self,
        request: CoachRequest,
        *,
        request_id: str | None = None,
    ) -> Iterator[dict[str, Any]]:
        """Yield NDJSON events from the streaming coaching endpoint."""
        extra: dict[str, str] = {}
        cleaned_id = str(request_id or "").strip()
        if cleaned_id:
            extra["X-Request-ID"] = cleaned_id
        with self._http.stream(
            "POST",
            f"{self._base_url}/api/v1/coach/turn/stream",
            json=request.model_dump(mode="json"),
            **self._idempotency_request_kwargs(request, extra or None),
        ) as response:
            response.raise_for_status()
            for line in response.iter_lines():
                if not line:
                    continue
                payload = json.loads(line)
                if isinstance(payload, dict):
                    yield payload
