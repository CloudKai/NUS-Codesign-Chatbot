"""Theme CSS injection and appearance overrides for the Streamlit UI.

Static layout and component styles live in ordered partials under
``ui/assets/styles/``. Appearance token overrides remain here so
Light/Dark/System can stay dynamic.
"""

from __future__ import annotations

from pathlib import Path

import streamlit as st

from ui.constants import DEFAULT_APPEARANCE

_ASSETS_DIR = Path(__file__).resolve().parent / "assets"
_STYLES_DIR = _ASSETS_DIR / "styles"
# Fixed cascade order. Do not reorder without comparing the assembled CSS.
_STYLE_PARTIALS: tuple[str, ...] = (
    "00-foundations.css",
    "10-workspace.css",
    "20-studio.css",
    "30-chat.css",
    "40-sources.css",
    "50-dialogs-notebooks.css",
    "55-auth.css",
    "60-profile-topbar.css",
    "90-responsive.css",
)
_template_css_cache: tuple[tuple[tuple[str, int, int], ...], str] | None = None


def style_partial_paths() -> list[Path]:
    """Return the ordered stylesheet partial paths used by the UI."""
    return [_STYLES_DIR / name for name in _STYLE_PARTIALS]


def _stylesheet_signature(paths: list[Path]) -> tuple[tuple[str, int, int], ...]:
    """Build a cache key from each partial's name, mtime, and size."""
    return tuple(
        (path.name, path.stat().st_mtime_ns, path.stat().st_size) for path in paths
    )


def _template_stylesheet() -> str:
    """Load and concatenate static stylesheets, refreshing when any change."""
    global _template_css_cache
    paths = style_partial_paths()
    missing = [path.name for path in paths if not path.is_file()]
    if missing:
        raise FileNotFoundError(
            "Missing stylesheet partial(s) in "
            f"{_STYLES_DIR}: {', '.join(missing)}"
        )
    signature = _stylesheet_signature(paths)
    if _template_css_cache is None or _template_css_cache[0] != signature:
        assembled = "".join(path.read_text(encoding="utf-8") for path in paths)
        _template_css_cache = (signature, assembled)
    return _template_css_cache[1]


def _build_template_ui_css() -> str:
    """Return the full HTML style block injected once per page."""
    return f"<style>\n{_template_stylesheet()}</style>"


def __getattr__(name: str):
    """Expose ``TEMPLATE_UI_CSS`` as a live stylesheet for docs/tests."""
    if name == "TEMPLATE_UI_CSS":
        return _build_template_ui_css()
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


def inject_template_css() -> None:
    """Inject the active template stylesheet into the Streamlit page."""
    st.markdown(_build_template_ui_css(), unsafe_allow_html=True)


def render_theme_css() -> None:
    light_tokens = """
        color-scheme:light;
        --cd-bg:#F4F6F7;--cd-surface:#FFFFFF;--cd-surface-muted:#F7F8F9;
        --cd-text:#15202B;--cd-muted:#5B6875;--cd-border:#D7DDE2;
        --cd-panel:#F1F3F4;--cd-subtle:#E9EDEF;--cd-accent-soft:#E8F3F1;
        --cd-accent:#0F766E;--cd-accent-hover:#0D9488;--cd-success:#15803D;
        --cd-scrollbar:#C6CDD3;
        --cd-checkbox-bg:#FFFFFF;--cd-checkbox-border:#D7DDE2;
        --cd-shadow:0 10px 28px rgba(21,32,43,.09);
        --cd-placeholder-opacity:.48;
    """
    dark_tokens = """
        color-scheme:dark;
        --cd-bg:#111416;--cd-surface:#171B1E;--cd-surface-muted:#1C2124;
        --cd-text:#EEF2F3;--cd-muted:#A4ADB3;--cd-border:#30373C;
        --cd-panel:#15191C;--cd-subtle:#20262A;--cd-accent-soft:#19312E;
        --cd-accent:#2BA89A;--cd-accent-hover:#38B6A7;--cd-success:#4FB37A;
        --cd-scrollbar:#4A5359;
        --cd-checkbox-bg:#1C2124;--cd-checkbox-border:#30373C;
        --cd-shadow:0 14px 36px rgba(0,0,0,.28);
        --cd-placeholder-opacity:.48;
    """
    mode = st.session_state.get("appearance", DEFAULT_APPEARANCE)
    tokens = dark_tokens if mode == "Dark" else light_tokens
    portal_background = "#171B1E" if mode == "Dark" else "#FFFFFF"
    portal_text = "#EEF2F3" if mode == "Dark" else "#15202B"
    portal_muted = "#A4ADB3" if mode == "Dark" else "#5B6875"
    system_portal_dark = (
        """
        @media (prefers-color-scheme:dark) {
            [data-testid="stPopoverBody"],
            [data-testid="stPopoverBody"] > div {
                background:#171B1E !important;
            }
            [data-testid="stPopoverBody"] p,
            [data-testid="stPopoverBody"] h3,
            [data-testid="stPopoverBody"] label {
                color:#EEF2F3 !important;
                -webkit-text-fill-color:#EEF2F3 !important;
            }
            [data-testid="stPopoverBody"] [data-testid="stTooltipHoverTarget"],
            [data-testid="stPopoverBody"] [data-testid="stTooltipHoverTarget"] [data-testid="stIconMaterial"],
            [data-testid="stPopoverBody"] [data-testid="stTooltipHoverTarget"] svg {
                opacity:1 !important;
                color:#A4ADB3 !important;
                -webkit-text-fill-color:#A4ADB3 !important;
                fill:currentColor !important;
            }
            [data-testid="stPopoverBody"] [data-testid="stCaptionContainer"],
            [data-testid="stPopoverBody"] [data-testid="stCaptionContainer"] p {
                color:#A4ADB3 !important;
                -webkit-text-fill-color:#A4ADB3 !important;
            }
        }
        """
        if mode == "System"
        else ""
    )
    system_dark = (
        f"@media (prefers-color-scheme:dark) {{ :root {{{dark_tokens}}} }}"
        if mode == "System"
        else ""
    )
    st.markdown(
        f"""
        <style>
            :root {{{tokens}}}
            {system_dark}
            [data-testid="stAppViewContainer"],
            [data-testid="stAppViewContainer"] > .main {{
                color:var(--cd-text);
                background:var(--cd-bg);
            }}
            [data-testid="stPopoverBody"],
            [data-testid="stPopoverBody"] > div {{
                color:{portal_text} !important;
                background:{portal_background} !important;
            }}
            [data-testid="stPopoverBody"] p,
            [data-testid="stPopoverBody"] h3,
            [data-testid="stPopoverBody"] label {{
                opacity:1 !important;
                color:{portal_text} !important;
                -webkit-text-fill-color:{portal_text} !important;
            }}
            [data-testid="stPopoverBody"] [data-testid="stTooltipHoverTarget"],
            [data-testid="stPopoverBody"] [data-testid="stTooltipHoverTarget"] [data-testid="stIconMaterial"],
            [data-testid="stPopoverBody"] [data-testid="stTooltipHoverTarget"] svg {{
                opacity:1 !important;
                color:{portal_muted} !important;
                -webkit-text-fill-color:{portal_muted} !important;
                fill:currentColor !important;
            }}
            [data-testid="stPopoverBody"] [data-testid="stCaptionContainer"],
            [data-testid="stPopoverBody"] [data-testid="stCaptionContainer"] p {{
                color:{portal_muted} !important;
                -webkit-text-fill-color:{portal_muted} !important;
            }}
            [role="dialog"] [data-testid="stMarkdownContainer"],
            [role="dialog"] [data-testid="stMarkdownContainer"] p,
            [role="dialog"] [data-testid="stMarkdownContainer"] li {{
                opacity:1 !important;
                color:var(--cd-text) !important;
                -webkit-text-fill-color:var(--cd-text) !important;
            }}
            [role="dialog"] [data-testid="stCaptionContainer"],
            [role="dialog"] [data-testid="stCaptionContainer"] p {{
                color:var(--cd-muted) !important;
                -webkit-text-fill-color:var(--cd-muted) !important;
            }}
            [role="dialog"] [role="tab"] {{
                flex:1 1 0;
                justify-content:center;
                opacity:1 !important;
                color:var(--cd-muted) !important;
            }}
            [role="dialog"] [role="tab"][aria-selected="true"] {{
                color:var(--cd-accent) !important;
            }}
            [role="dialog"] [role="tab"] p {{
                color:inherit !important;
                -webkit-text-fill-color:currentColor !important;
            }}
            {system_portal_dark}
            [data-testid="stAppViewContainer"] [data-testid="stMarkdownContainer"],
            [data-testid="stAppViewContainer"] [data-testid="stMarkdownContainer"] p,
            [data-testid="stAppViewContainer"] [data-testid="stMarkdownContainer"] li,
            [data-testid="stAppViewContainer"] [data-testid="stMarkdownContainer"] strong,
            [data-testid="stAppViewContainer"] label,
            [data-testid="stAppViewContainer"] h1,
            [data-testid="stAppViewContainer"] h2,
            [data-testid="stAppViewContainer"] h3,
            [data-testid="stAppViewContainer"] h4 {{
                opacity:1 !important;
                color:var(--cd-text) !important;
                -webkit-text-fill-color:var(--cd-text) !important;
            }}
            [data-baseweb="select"],
            [data-baseweb="select"] > div,
            [data-baseweb="select"] > div > div,
            [data-baseweb="input"],
            [data-baseweb="input"] > div,
            [data-testid="stTextInputRootElement"],
            [data-baseweb="textarea"],
            [data-baseweb="textarea"] > div {{
                color:var(--cd-text) !important;
                border-color:var(--cd-border) !important;
                background:var(--cd-surface) !important;
            }}
            div[role="group"]:has(> input[role="combobox"]) {{
                overflow:hidden;
                border:1px solid var(--cd-border) !important;
                border-radius:.6rem !important;
                color:var(--cd-text) !important;
                background:var(--cd-surface) !important;
            }}
            div[role="group"] > input[role="combobox"],
            div[role="group"]:has(> input[role="combobox"]) > button {{
                opacity:1 !important;
                color:var(--cd-text) !important;
                -webkit-text-fill-color:var(--cd-text) !important;
                border:0 !important;
                background:transparent !important;
            }}
            [role="radiogroup"] {{
                overflow:hidden;
                border:1px solid var(--cd-border) !important;
                border-radius:.62rem !important;
                background:var(--cd-surface) !important;
            }}
            [role="radiogroup"] > [role="radio"] {{
                min-height:2.55rem;
                opacity:1 !important;
                border:0 !important;
                border-right:1px solid var(--cd-border) !important;
                color:var(--cd-muted) !important;
                background:var(--cd-surface) !important;
            }}
            [role="radiogroup"] > [role="radio"]:last-child {{
                border-right:0 !important;
            }}
            [role="radiogroup"] > [role="radio"][aria-checked="true"] {{
                color:var(--cd-accent) !important;
                background:var(--cd-accent-soft) !important;
            }}
            [role="radiogroup"] > [role="radio"] p {{
                opacity:1 !important;
                color:inherit !important;
                -webkit-text-fill-color:currentColor !important;
            }}
            [data-baseweb="select"] *,
            [data-baseweb="input"] input,
            [data-baseweb="textarea"] textarea,
            [data-testid="stTextInputRootElement"] input,
            [data-testid="stChatInput"] textarea {{
                color:var(--cd-text) !important;
                -webkit-text-fill-color:var(--cd-text) !important;
            }}
            [data-testid="stTextInputRootElement"],
            [data-testid="stTextInputRootElement"] > div {{
                color:var(--cd-text) !important;
                border-color:var(--cd-border) !important;
                background:var(--cd-surface) !important;
            }}
            [data-testid="stDownloadButton"] button {{
                opacity:1 !important;
                border:1px solid var(--cd-border) !important;
                color:var(--cd-text) !important;
                -webkit-text-fill-color:var(--cd-text) !important;
                background:var(--cd-surface) !important;
            }}
            [data-testid="stDownloadButton"] button * {{
                color:var(--cd-text) !important;
                -webkit-text-fill-color:var(--cd-text) !important;
            }}
            [data-testid="stCheckbox"] label > div:nth-child(2),
            [data-testid="stCheckbox"] label > div:has(> svg),
            [data-baseweb="checkbox"] > div:first-child {{
                border:1px solid var(--cd-checkbox-border) !important;
                background:var(--cd-checkbox-bg) !important;
                box-shadow:none !important;
            }}
            [data-testid="stCheckbox"] label:has(input:checked) > div:nth-child(2),
            [data-testid="stCheckbox"] label:has(input:checked) > div:has(> svg),
            [data-baseweb="checkbox"][data-checked="true"] > div:first-child {{
                border-color:var(--cd-accent) !important;
                background:var(--cd-accent) !important;
            }}
            [data-testid="stCheckbox"] label:has(input:checked) > div:nth-child(2) svg,
            [data-testid="stCheckbox"] label:has(input:checked) > div:has(> svg) svg,
            [data-baseweb="checkbox"][data-checked="true"] svg {{
                fill:#fff !important;
                stroke:#fff !important;
                color:#fff !important;
            }}
            [data-testid="stChatInput"] {{
                color:var(--cd-text) !important;
                border-color:var(--cd-border) !important;
                background:var(--cd-surface) !important;
            }}
            [data-testid="stChatInput"] > div {{
                color:var(--cd-text) !important;
                border:0 !important;
                background:transparent !important;
                box-shadow:none !important;
            }}
            [data-testid="stChatInput"] textarea::placeholder,
            input::placeholder,
            textarea::placeholder {{
                color:var(--cd-muted) !important;
                -webkit-text-fill-color:var(--cd-muted) !important;
                opacity:var(--cd-placeholder-opacity, .48) !important;
            }}
            [data-testid="stChatMessage"],
            [data-testid="stChatMessage"] [data-testid="stMarkdownContainer"],
            [data-testid="stChatMessage"] [data-testid="stMarkdownContainer"] p,
            [data-testid="stChatMessage"] [data-testid="stMarkdownContainer"] li,
            [data-testid="stChatMessage"] [data-testid="stMarkdownContainer"] strong {{
                color:var(--cd-text) !important;
            }}
            div[data-testid="stButton"] button,
            [data-testid="stPopover"] > button {{
                color:var(--cd-text) !important;
                border-color:var(--cd-border) !important;
                background:var(--cd-surface) !important;
            }}
            div[data-testid="stButton"] button *,
            [data-testid="stPopover"] > button * {{
                color:var(--cd-text) !important;
                -webkit-text-fill-color:var(--cd-text) !important;
            }}
            section[role="dialog"]:has(.st-key-notebook-search)
            [data-testid="stPopover"] button {{
                color:var(--cd-accent) !important;
                border-color:transparent !important;
                background:transparent !important;
            }}
            section[role="dialog"]:has(.st-key-notebook-search)
            [data-testid="stPopover"] button * {{
                color:var(--cd-accent) !important;
                -webkit-text-fill-color:var(--cd-accent) !important;
            }}
            div[data-testid="stButton"] button[kind="primary"],
            [data-testid="stBaseButton-primary"] {{
                color:#fff !important;
                border-color:var(--cd-accent) !important;
                background:var(--cd-accent) !important;
            }}
            div[data-testid="stButton"] button[kind="primary"] *,
            [data-testid="stBaseButton-primary"] * {{
                color:#fff !important;
                -webkit-text-fill-color:#fff !important;
            }}
            div[data-testid="stButton"] button[kind="primary"]:hover,
            [data-testid="stBaseButton-primary"]:hover {{
                background:var(--cd-accent-hover) !important;
            }}
            div[data-testid="stButton"] button[kind="primary"]:disabled,
            [data-testid="stBaseButton-primary"]:disabled {{
                opacity:.72 !important;
                color:var(--cd-muted) !important;
                border-color:var(--cd-border) !important;
                background:var(--cd-subtle) !important;
            }}
            div[data-testid="stButton"] button[kind="primary"]:disabled *,
            [data-testid="stBaseButton-primary"]:disabled * {{
                color:var(--cd-muted) !important;
                -webkit-text-fill-color:var(--cd-muted) !important;
            }}
            [data-testid="stChatInputSubmitButton"] {{
                display:inline-flex !important;
                align-items:center !important;
                justify-content:center !important;
                padding:0 !important;
                color:#fff !important;
                background:var(--cd-accent) !important;
            }}
            [data-testid="stChatInputFileUploadButton"] button {{
                color:var(--cd-muted) !important;
                background:transparent !important;
            }}
            [data-testid="stChatInputFileUploadButton"] button svg {{
                display:none !important;
            }}
            [data-testid="stChatInputFileUploadButton"] button::before {{
                content:"attach_file";
                font-family:"Material Symbols Rounded";
                font-size:1.35rem;
                font-variation-settings:"FILL" 0,"wght" 400,"GRAD" 0,"opsz" 20;
                line-height:1;
            }}
            [data-testid="stChatInputMicButton"] {{
                display:none !important;
            }}
            [data-testid="stHeaderActionElements"] {{
                display:none !important;
            }}
            [data-testid="stChatInputSubmitButton"] svg,
            [data-testid="stChatInputSubmitButton"] [data-testid="stIconMaterial"] {{
                display:none !important;
            }}
            [data-testid="stChatInputSubmitButton"]::before {{
                content:"arrow_upward";
                display:block !important;
                width:1.15rem;
                height:1.15rem;
                font-family:"Material Symbols Rounded";
                font-size:1.15rem;
                font-variation-settings:"FILL" 0,"wght" 500,"GRAD" 0,"opsz" 20;
                line-height:1.15rem;
                text-align:center;
                color:#fff !important;
                -webkit-text-fill-color:#fff !important;
            }}
            [data-testid="stChatInputSubmitButton"]:disabled {{
                color:var(--cd-muted) !important;
                background:var(--cd-subtle) !important;
            }}
            [data-testid="stChatInputSubmitButton"]:disabled::before {{
                color:var(--cd-muted) !important;
                -webkit-text-fill-color:var(--cd-muted) !important;
            }}
            [data-testid="stCaptionContainer"],
            [data-testid="stCaptionContainer"] p {{
                color:var(--cd-muted) !important;
                -webkit-text-fill-color:var(--cd-muted) !important;
            }}
            [data-testid="stExpander"] details,
            [data-testid="stExpander"] details summary {{
                color:var(--cd-text) !important;
                border-color:var(--cd-border) !important;
                background:var(--cd-surface) !important;
            }}
            [data-testid="stExpander"] details summary * {{
                color:var(--cd-text) !important;
                -webkit-text-fill-color:var(--cd-text) !important;
            }}
            [data-baseweb="popover"],
            [data-baseweb="popover"] > div,
            [data-baseweb="menu"],
            [role="listbox"],
            [data-testid="stDialog"] > div {{
                color:var(--cd-text) !important;
                border-color:var(--cd-border) !important;
                background:var(--cd-surface) !important;
            }}
            [data-baseweb="popover"] [role="listbox"],
            [data-baseweb="menu"] [role="listbox"] {{
                overflow:hidden;
                border:1px solid var(--cd-border) !important;
                border-radius:.72rem !important;
                background:var(--cd-surface) !important;
                box-shadow:var(--cd-shadow) !important;
            }}
            [data-baseweb="popover"] [role="option"],
            [data-baseweb="menu"] [role="option"],
            [role="listbox"] [role="option"] {{
                opacity:1 !important;
                color:var(--cd-text) !important;
                -webkit-text-fill-color:var(--cd-text) !important;
                background:var(--cd-surface) !important;
            }}
            [data-baseweb="popover"] [role="option"] *,
            [data-baseweb="menu"] [role="option"] *,
            [role="listbox"] [role="option"] * {{
                opacity:1 !important;
                color:inherit !important;
                -webkit-text-fill-color:currentColor !important;
            }}
            [role="listbox"] [role="option"][aria-selected="true"] {{
                color:var(--cd-text) !important;
                background:var(--cd-surface) !important;
                font-weight:650 !important;
            }}
            [role="listbox"] [role="option"]:hover,
            [role="listbox"] [role="option"]:focus {{
                color:var(--cd-text) !important;
                background:var(--cd-subtle) !important;
            }}
        </style>
        """,
        unsafe_allow_html=True,
    )
