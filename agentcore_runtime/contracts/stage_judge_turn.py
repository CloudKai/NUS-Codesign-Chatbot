"""Stage Judge structured-output contract."""

from __future__ import annotations

try:
    from models import StageJudgeOutput
except ImportError:  # pragma: no cover
    from agentcore_runtime.models import StageJudgeOutput

__all__ = ["StageJudgeOutput"]
