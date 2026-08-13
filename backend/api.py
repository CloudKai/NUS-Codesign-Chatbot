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
    register_workspace_routes,
)

__all__ = [
    "MessageReviseRequest",
    "StageSelectionRequest",
    "TransitionResolution",
    "app",
    "create_app",
    "register_workspace_routes",
    "validate_cognito_readiness",
]
