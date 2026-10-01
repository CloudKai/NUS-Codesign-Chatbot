"""Contracts for the document shell used by Streamlit HTML components."""

from __future__ import annotations

from pathlib import Path

import pytest

from ui.html_embed import wrap_component_html


def test_wrap_component_html_leaves_streamlit_suffix_inside_open_body() -> None:
    """Bare scripts receive an open document without closing Streamlit tags."""
    payload = "\n<script>window.parent.document.body;</script>\n"

    wrapped = wrap_component_html(payload)

    assert wrapped == "<!doctype html><html><body>" + payload
    assert wrapped.endswith(payload)
    assert "</body>" not in wrapped
    assert "</html>" not in wrapped


@pytest.mark.parametrize(
    "module_path",
    (
        "ui/layout/column_resize.py",
        "ui/layout/studio_scroll.py",
        "ui/layout/sources_scroll.py",
        "ui/layout/chat_scroll.py",
        "ui/layout/composer_layout.py",
        "ui/theme.py",
        "ui/profile.py",
        "ui/notebooks.py",
        "ui/rename.py",
        "ui/panels/sources.py",
        "ui/toasts.py",
    ),
)
def test_bare_component_sites_use_the_shared_wrapper(module_path: str) -> None:
    """Every bare-script component site stays protected across UI modules."""
    source = Path(module_path).read_text(encoding="utf-8")

    assert "from ui.html_embed import wrap_component_html" in source
    assert "wrap_component_html(" in source
