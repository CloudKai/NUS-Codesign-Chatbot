"""Backward-compatible alias for :mod:`ui.panels.sources`."""

import sys

from ui.panels import sources as _implementation

sys.modules[__name__] = _implementation
