"""Typed synchronous client used by Streamlit once the local API is running."""

from __future__ import annotations

import httpx

from .domain import CoachRequest, CoachTurn, PendingPhaseTransition


class LocalApiClient:
    """Small typed client for the versioned local FastAPI contract."""

    def __init__(self, base_url: str, timeout_seconds: float = 120.0) -> None:
        self._base_url = base_url.rstrip("/")
        self._timeout_seconds = timeout_seconds

    def health(self) -> dict[str, str]:
        """Return the local API health response or raise an HTTP error."""
        response = httpx.get(f"{self._base_url}/api/v1/health", timeout=self._timeout_seconds)
        response.raise_for_status()
        return response.json()

    def coach_turn(self, request: CoachRequest) -> CoachTurn:
        """Submit one typed coaching turn to the local backend."""
        response = httpx.post(
            f"{self._base_url}/api/v1/coach/turn",
            json=request.model_dump(mode="json"),
            timeout=self._timeout_seconds,
        )
        response.raise_for_status()
        return CoachTurn.model_validate(response.json())

    def pending_transition(self, thread_id: str) -> PendingPhaseTransition | None:
        """Return the unresolved transition recommendation for one notebook."""
        response = httpx.get(
            f"{self._base_url}/api/v1/threads/{thread_id}/phase-transitions/pending",
            timeout=self._timeout_seconds,
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
        response = httpx.post(
            f"{self._base_url}/api/v1/threads/{thread_id}/phase-transitions/"
            f"{transition_id}/resolve",
            json={"accepted": accepted},
            timeout=self._timeout_seconds,
        )
        response.raise_for_status()
        return PendingPhaseTransition.model_validate(response.json())
