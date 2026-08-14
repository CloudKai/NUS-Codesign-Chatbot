"""Compatibility alias for the source-library implementation.

Source ingestion, course-material synchronization and context projection live
in :mod:`backend.sources`.  Replacing this module object preserves historical
imports and monkeypatch seams while new code can use the focused package.
"""

from __future__ import annotations

import sys

from backend.sources import library as _implementation

sys.modules[__name__] = _implementation
