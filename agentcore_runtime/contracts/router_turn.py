"""Router structured-output contract."""

from __future__ import annotations

try:
    from models import RouterOutput
except ImportError:  # pragma: no cover
    from agentcore_runtime.models import RouterOutput

__all__ = ["RouterOutput"]
