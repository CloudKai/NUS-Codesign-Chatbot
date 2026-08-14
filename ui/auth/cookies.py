"""Read browser cookies without coupling authentication to runtime services."""

from __future__ import annotations

import streamlit as st


def cookie_value(name: str) -> str | None:
    """Return one non-empty cookie value from the current Streamlit request.

    Cookie access is best-effort because older Streamlit runtimes and test
    harnesses may not expose ``st.context.cookies``. Authentication authority
    remains with FastAPI; this helper only forwards a browser-supplied value.
    """
    try:
        context = getattr(st, "context", None)
        cookie_map = getattr(context, "cookies", None) if context is not None else None
        if cookie_map is None:
            return None
        cleaned = str(cookie_map.get(name) or "").strip()
        return cleaned or None
    except Exception:
        return None
