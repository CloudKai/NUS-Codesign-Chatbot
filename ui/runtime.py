"""Backward-compatible alias for :mod:`ui.services.runtime`.

Using the implementation module object preserves monkeypatch/cache seams whose
function globals must observe attributes patched through ``ui.runtime``.
"""

import sys

from ui.services import runtime as _implementation

sys.modules[__name__] = _implementation
