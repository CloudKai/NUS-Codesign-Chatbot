"""Backward-compatible FastAPI façade.

Application composition lives in :mod:`backend.http.app`; the original import
path and its intentionally patched test seams remain available here.
"""

from backend.cognito_config import validate_cognito_readiness
from backend.http.app import (
    MessageReviseRequest,
    StageSelectionRequest,
    TransitionResolution,
    app,
    create_app,
)
from backend.research.repository import StudentStoreResearchRepository

__all__ = [
    "MessageReviseRequest",
    "StageSelectionRequest",
    "StudentStoreResearchRepository",
    "TransitionResolution",
    "app",
    "create_app",
    "validate_cognito_readiness",
]
