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
        "40-sources.css": ".cd-sources-add-face::after",
        "50-dialogs-notebooks.css": ".st-key-notebook_library_scroll",
        "55-auth.css": ".cd-auth-redirecting",
        "60-profile-topbar.css": ".st-key-profile_coaching_style",
        "70-professor.css": ".st-key-research_workspace",
        "90-responsive.css": "@media (max-width:1050px)",
    }
    for name, marker in markers.items():
        assert marker in Path(_STYLES_DIR / name).read_text(encoding="utf-8")
        assert marker in css

    profile_css = Path(_STYLES_DIR / "60-profile-topbar.css").read_text(encoding="utf-8")
    assert ".st-key-profile_menu_root" in profile_css
    assert ".st-key-profile_coaching_style" in profile_css
    assert "button[aria-checked=\"true\"]" in profile_css
    assert "background:var(--cd-accent)" in profile_css

    sources_css = Path(_STYLES_DIR / "40-sources.css").read_text(encoding="utf-8")
    assert "content:attr(data-tooltip)" in sources_css

    chat_css = Path(_STYLES_DIR / "30-chat.css").read_text(encoding="utf-8")
    assert ".cd-attach-tooltip" in chat_css
    assert "body[data-cd-attach-hover=\"1\"]" in chat_css
    assert "stChatInputStopButton" in chat_css
    assert "stExpanderIconSpinner" in chat_css
    assert "textarea:disabled" in chat_css

    dialogs_css = Path(_STYLES_DIR / "50-dialogs-notebooks.css").read_text(
        encoding="utf-8"
    )
    assert "max 10 MB per file" in dialogs_css

    auth_css = Path(_STYLES_DIR / "55-auth.css").read_text(encoding="utf-8")
    assert ".st-key-auth_login_card" in auth_css
    assert ".cd-auth-redirecting" in auth_css
    assert ".cd-auth-session-loading" in auth_css
    assert ".cd-auth-session-spinner" in auth_css
    assert ".cd-auth-gap-after-course-notice--spacer" in auth_css
    assert ".st-key-auth-config-error" in auth_css

    # Assembled text equals simple concatenation in manifest order.
    assembled = "".join(
        Path(_STYLES_DIR / name).read_text(encoding="utf-8") for name in _STYLE_PARTIALS
    )
    assert css == assembled
