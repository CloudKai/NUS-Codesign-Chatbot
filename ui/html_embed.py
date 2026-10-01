"""Helpers for embedding browser scripts through Streamlit components."""

from __future__ import annotations


_COMPONENT_HTML_DOCUMENT_PREFIX = "<!doctype html><html><body>"


def wrap_component_html(payload: str) -> str:
    """Prefix a bare component payload with a stable HTML document shell.

    Streamlit appends its iframe auto-size script to ``components.html``
    payloads. Supplying an explicit document body ensures that suffix runs
    after a body exists, while leaving the document open for Streamlit to
    finish.

    Args:
        payload: Bare HTML or script content sent to ``components.html``.

    Returns:
        The payload prefixed with ``<!doctype html><html><body>``.
    """
    return f"{_COMPONENT_HTML_DOCUMENT_PREFIX}{payload}"


__all__ = ["wrap_component_html"]
