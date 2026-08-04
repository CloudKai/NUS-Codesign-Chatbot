"""Compatibility shim — prefer ``ui.layout.composer_layout``."""

from __future__ import annotations

from ui.layout.composer_layout import sync_composer_layout

__all__ = ["sync_composer_layout"]
