"""Application-layer coaching orchestration and deterministic projections."""

from __future__ import annotations

from typing import Any

__all__ = ["CoachApplicationService"]


def __getattr__(name: str) -> Any:
    """Lazy-load execution exports to avoid a workflow ↔ coaching import cycle."""
    if name == "CoachApplicationService":
        from backend.coaching.execution import CoachApplicationService

        return CoachApplicationService
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
