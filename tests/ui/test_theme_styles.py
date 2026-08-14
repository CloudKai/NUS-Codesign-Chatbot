"""Loader contracts for ordered static stylesheet partials."""

from __future__ import annotations

from pathlib import Path

from ui.theme import (
    _STYLE_PARTIALS,
    _STYLES_DIR,
    _build_template_ui_css,
    _template_stylesheet,
    style_partial_paths,
)


def test_style_partials_exist_in_fixed_manifest_order() -> None:
    """Every declared partial must exist and stay in cascade order."""
    paths = style_partial_paths()
    assert [path.name for path in paths] == list(_STYLE_PARTIALS)
    assert paths == [_STYLES_DIR / name for name in _STYLE_PARTIALS]
    for path in paths:
        assert path.is_file(), f"missing stylesheet partial: {path}"


def test_assembled_stylesheet_wraps_all_component_markers() -> None:
    """Concatenation keeps one injection block and markers from each partial."""
    css = _template_stylesheet()
    wrapped = _build_template_ui_css()

    assert wrapped.startswith("<style>\n")
    assert wrapped.endswith("</style>")
    assert wrapped.count("<style>") == 1
    assert css in wrapped

    markers = {
        "00-foundations.css": "--cd-header-height",
        "10-workspace.css": ".st-key-notebook_topbar",
        "20-studio.css": ".st-key-journey_track",
        "30-chat.css": ".chat-context-line",
        "40-sources.css": ".st-key-sources_panel",
        "50-dialogs-notebooks.css": ".st-key-notebook_library_scroll",
        "55-auth.css": ".cd-auth-redirecting",
        "60-profile-topbar.css": ".st-key-profile_menu_root",
        "70-professor.css": ".st-key-research_workspace",
        "90-responsive.css": "@media (max-width:1050px)",
    }
    for name, marker in markers.items():
        assert marker in Path(_STYLES_DIR / name).read_text(encoding="utf-8")
        assert marker in css

    auth_css = Path(_STYLES_DIR / "55-auth.css").read_text(encoding="utf-8")
    assert ".st-key-auth_login_card" in auth_css
    assert ".cd-auth-redirecting" in auth_css
    assert ".cd-auth-gap-after-course-notice--spacer" in auth_css
    assert ".st-key-auth-config-error" in auth_css

    # Assembled text equals simple concatenation in manifest order.
    assembled = "".join(
        Path(_STYLES_DIR / name).read_text(encoding="utf-8") for name in _STYLE_PARTIALS
    )
    assert css == assembled
