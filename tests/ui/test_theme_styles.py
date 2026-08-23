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


def _css_rule_body(css: str, marker: str) -> str:
    """Return the first declaration block that follows ``marker``."""
    start = css.index(marker)
    open_brace = css.index("{", start)
    close_brace = css.index("}", open_brace)
    return css[open_brace + 1 : close_brace]


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
    assert "[data-testid=\"stRadio\"]" in profile_css
    assert "[data-testid=\"stRadioGroup\"]" in profile_css
    assert "[data-testid=\"stRadioOption\"]" in profile_css
    assert "border-bottom:1px solid var(--cd-border)" in profile_css
    assert "[data-selected]" in profile_css
    assert ":has(input:checked)" in profile_css
    assert "clip:rect(0,0,0,0)" in profile_css
    assert "white-space:pre-line" in profile_css
    assert "overflow-wrap:anywhere" in profile_css
    assert "p::first-line" in profile_css
    assert "background:var(--cd-accent)" in profile_css

    sources_css = Path(_STYLES_DIR / "40-sources.css").read_text(encoding="utf-8")
    assert "content:attr(data-tooltip)" in sources_css

    workspace_css = Path(_STYLES_DIR / "10-workspace.css").read_text(encoding="utf-8")
    assert ".st-key-chat_inflight" in workspace_css
    assert ".st-key-chat_transcript" in workspace_css
    panel_scroll = _css_rule_body(workspace_css, ".st-key-chat_panel {")
    assert "overflow-y:hidden" in panel_scroll
    transcript_flex = _css_rule_body(
        workspace_css,
        ".st-key-chat_transcript,\n    [data-testid=\"stElementContainer\"].st-key-chat_transcript",
    )
    assert "flex:1 1 auto" in transcript_flex
    assert "overflow:visible" in transcript_flex
    assert "overflow-y:auto" not in transcript_flex
    log_flex = _css_rule_body(
        workspace_css,
        ".st-key-chat_log,\n    [data-testid=\"stElementContainer\"].st-key-chat_log",
    )
    assert "flex:1 1 0%" in log_flex
    assert "overflow-y:auto" in log_flex
    assert "justify-content:flex-start" in log_flex
    assert "justify-content:flex-end" not in log_flex
    studio_scroll = _css_rule_body(workspace_css, ".st-key-studio_scroll {")
    assert "height:100%" in studio_scroll
    assert "margin-top:auto" not in _css_rule_body(
        workspace_css, ":has(> .st-key-chat_composer)"
    )
    composer_pin = _css_rule_body(
        workspace_css,
        ".st-key-chat_panel > [data-testid=\"stLayoutWrapper\"]:has(.st-key-chat_composer):not(:has(.st-key-chat_log))",
    )
    assert "flex:0 0 auto" in composer_pin
    assert "margin-top:0" in composer_pin
    assert "overflow:visible" in composer_pin
    composer_column = _css_rule_body(
        workspace_css,
        ".st-key-chat_transcript [data-testid=\"stVerticalBlock\"]:has(.st-key-chat_composer)",
    )
    assert "flex:0 0 auto" in composer_column
    assert "flex-grow:0" in composer_column
    assert "height:auto" in composer_column
    log_wrap = _css_rule_body(
        workspace_css,
        ".st-key-chat_panel [data-testid=\"stLayoutWrapper\"]:has(> .st-key-chat_log):not(:has(> .st-key-chat_inflight))",
    )
    assert "height:auto" in log_wrap
    assert "height:100%" not in log_wrap
    inflight_size = _css_rule_body(
        workspace_css,
        ".st-key-chat_inflight,\n    [data-testid=\"stElementContainer\"].st-key-chat_inflight",
    )
    assert "flex:0 0 auto" in inflight_size
    assert "flex-shrink:0" in inflight_size
    assert "overflow:visible" in inflight_size
    assert "background:transparent" in inflight_size
    inflight_occupied = _css_rule_body(
        workspace_css, ".st-key-chat_inflight:has(.cd-user-bubble-text)"
    )
    assert "min-height:0" in inflight_occupied
    assert "overflow:visible" in inflight_occupied
    inflight_collapse = _css_rule_body(
        workspace_css, ".st-key-chat_inflight:not(:has("
    )
    assert "max-height:0" in inflight_collapse
    assert "overflow:hidden" in inflight_collapse
    assert ":not(:has(.cd-user-bubble-text))" in workspace_css
    assert ":not(:has(.st-key-inflight_user_message_row))" in workspace_css
    log_children = _css_rule_body(
        workspace_css,
        ".st-key-chat_log > [data-testid=\"stVerticalBlock\"] > [data-testid=\"stLayoutWrapper\"]",
    )
    assert "flex:0 0 auto" in log_children
    assert "height:auto" in log_children
    assert "flex-grow" not in log_children
    assert "margin-top:auto" not in log_children
    log_direct = _css_rule_body(
        workspace_css,
        ".st-key-chat_log > [data-testid=\"stVerticalBlock\"],\n    .st-key-chat_log > [data-testid=\"stLayoutWrapper\"] {",
    )
    assert "flex:0 0 auto" in log_direct
    assert "margin-top:auto" in log_direct
    assert "flex-grow" not in log_direct

    chat_css = Path(_STYLES_DIR / "30-chat.css").read_text(encoding="utf-8")
    assert ".st-key-chat_inflight" in chat_css
    assert ".st-key-inflight_user_message_row" in chat_css
    assert ".cd-inflight-error" in chat_css
    composer_card = _css_rule_body(chat_css, ".st-key-chat_composer {")
    assert "flex:0 0 auto" in composer_card
    assert "margin-top:auto" not in composer_card
    transcript_composer = _css_rule_body(
        chat_css, ".st-key-chat_panel .st-key-chat_composer"
    )
    assert "position:relative" in transcript_composer
    assert "margin-top:0" in transcript_composer
    assert "flex:0 0 auto" in transcript_composer
    assert (
        '.st-key-chat_inflight [data-testid="stChatMessage"]:last-of-type'
        in chat_css
    )
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
