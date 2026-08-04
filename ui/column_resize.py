"""Compatibility shim — prefer ``ui.layout.column_resize``."""

from __future__ import annotations

from ui.layout.column_resize import (
    DEFAULT_WORKSPACE_WIDTHS,
    effective_column_widths,
    get_workspace_widths,
    set_side_panel_collapsed,
    side_panel_collapsed,
    sync_workspace_column_resize,
)

__all__ = [
    "DEFAULT_WORKSPACE_WIDTHS",
    "effective_column_widths",
    "get_workspace_widths",
    "set_side_panel_collapsed",
    "side_panel_collapsed",
    "sync_workspace_column_resize",
]
