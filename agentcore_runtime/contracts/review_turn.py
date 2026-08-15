"""Formative Review structured-output contract."""

from __future__ import annotations

try:
    from models import ReviewTurnOutput
except ImportError:  # pragma: no cover
    from agentcore_runtime.models import ReviewTurnOutput

__all__ = ["ReviewTurnOutput"]
