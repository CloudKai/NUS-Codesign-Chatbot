"""Backward-compatible alias for :mod:`ui.panels.chat`."""

import sys

from ui.panels import chat as _implementation

sys.modules[__name__] = _implementation
