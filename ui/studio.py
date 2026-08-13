"""Backward-compatible alias for :mod:`ui.panels.studio`."""

import sys

from ui.panels import studio as _implementation

sys.modules[__name__] = _implementation
