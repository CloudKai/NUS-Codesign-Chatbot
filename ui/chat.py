"""Backward-compatible alias for :mod:`ui.panels.chat`.

Streamlit watches this shim file; keep it so panel edits remount. Chat
scroll policy lives in ``ui.layout.chat_scroll`` and ``ui.panels.chat``.
"""

import sys

from ui.panels import chat as _implementation

sys.modules[__name__] = _implementation
