"""Streamlit layout helpers that inject browser-side DOM/CSS adjustments.

These modules exist because Streamlit does not expose first-class APIs for
column drag-resize, sources/studio/chat scroll sizing, or composer footer
placement. Keep them small, side-effect free at import time, and call their
``sync_*`` / render helpers explicitly from panel code.
"""

from __future__ import annotations

from ui.layout.column_resize import (
    DEFAULT_WORKSPACE_WIDTHS,
    effective_column_widths,
    get_workspace_widths,
    nav_collapsed,
    set_nav_collapsed,
    set_side_panel_collapsed,
    side_panel_collapsed,
    sync_workspace_column_resize,
)
from ui.layout.chat_scroll import sync_chat_scroll
from ui.layout.composer_layout import sync_composer_layout
from ui.layout.sources_scroll import sync_sources_scroll
from ui.layout.studio_scroll import sync_studio_scroll

__all__ = [
    "DEFAULT_WORKSPACE_WIDTHS",
    "effective_column_widths",
    "get_workspace_widths",
    "nav_collapsed",
    "set_nav_collapsed",
    "set_side_panel_collapsed",
    "side_panel_collapsed",
    "sync_chat_scroll",
    "sync_composer_layout",
    "sync_sources_scroll",
    "sync_studio_scroll",
    "sync_workspace_column_resize",
]
