"""Q&A structured-output contract."""

from __future__ import annotations

try:
    from models import QATurnOutput
except ImportError:  # pragma: no cover
    from agentcore_runtime.models import QATurnOutput

__all__ = ["QATurnOutput"]
