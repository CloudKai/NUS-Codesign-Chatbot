"""Theme CSS injection and appearance overrides for the Streamlit UI.

Static layout and component styles live in ordered partials under
``ui/assets/styles/``. Appearance token overrides remain here so
Light/Dark/System can stay dynamic.
"""

from __future__ import annotations

from pathlib import Path

import streamlit as st

from ui.html_embed import wrap_component_html

_ASSETS_DIR = Path(__file__).resolve().parent / "assets"
_STYLES_DIR = _ASSETS_DIR / "styles"
# Fixed cascade order. Do not reorder without comparing the assembled CSS.
_STYLE_PARTIALS: tuple[str, ...] = (
    "00-foundations.css",
    "10-workspace.css",
    "15-nav.css",
    "20-studio.css",
    "30-chat.css",
    "40-sources.css",
    "50-dialogs-notebooks.css",
    "55-auth.css",
    "60-profile-topbar.css",
    "70-professor.css",
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


def inject_mobile_viewport_lock() -> None:
    """Keep phone browsers from zooming or shifting the app shell on focus.

    iOS Safari zooms pages when a focused control is under 16px, and it also
    scrolls the layout viewport to bring the composer into view. That scroll
    often sticks after the keyboard closes: a gap appears under the composer
    and the mobile top-bar icons sit under the status bar (unclickable).

    Combined with the mobile 16px input floor in ``90-responsive.css``, this
    locks ``maximum-scale=1`` and repeatedly pins ``scroll`` / visualViewport
    offsets back to the origin while editing.
    """
    import streamlit.components.v1 as components

    components.html(
        wrap_component_html(
            """
<script>
(() => {
  const doc = window.parent.document;
  const win = window.parent;
  const desired =
    "width=device-width, initial-scale=1, maximum-scale=1, viewport-fit=cover";
  let meta = doc.querySelector('meta[name="viewport"]');
  if (!meta) {
    meta = doc.createElement("meta");
    meta.setAttribute("name", "viewport");
    (doc.head || doc.documentElement).appendChild(meta);
  }
  if (meta.getAttribute("content") !== desired) {
    meta.setAttribute("content", desired);
  }

  const isNarrow = () => {
    try {
      return win.matchMedia("(max-width: 1050px)").matches;
    } catch (_) {
      return win.innerWidth <= 1050;
    }
  };

  const pinDocumentScroll = () => {
    if (!isNarrow()) {
      return;
    }
    try {
      if (win.scrollX || win.scrollY) {
        win.scrollTo(0, 0);
      }
      if (doc.documentElement && doc.documentElement.scrollTop) {
        doc.documentElement.scrollTop = 0;
      }
      if (doc.body && doc.body.scrollTop) {
        doc.body.scrollTop = 0;
      }
      const main = doc.querySelector(
        '[data-testid="stAppViewContainer"] > .main, section.main'
      );
      if (main && main.scrollTop) {
        main.scrollTop = 0;
      }
    } catch (_) {}
  };

  const schedulePin = () => {
    pinDocumentScroll();
    try {
      win.requestAnimationFrame(pinDocumentScroll);
    } catch (_) {}
    win.setTimeout(pinDocumentScroll, 50);
    win.setTimeout(pinDocumentScroll, 250);
  };

  if (!win.__cdViewportPinInstalled) {
    win.__cdViewportPinInstalled = true;
    win.addEventListener("scroll", pinDocumentScroll, { passive: true });
    doc.addEventListener(
      "focusin",
      (event) => {
        const target = event.target;
        if (!target || typeof target.matches !== "function") {
          return;
        }
        if (
          !target.matches(
            "input, textarea, [contenteditable='true'], [contenteditable='']"
          )
        ) {
          return;
        }
        schedulePin();
      },
      true
    );
    doc.addEventListener("focusout", schedulePin, true);
    if (win.visualViewport) {
      win.visualViewport.addEventListener("resize", schedulePin);
      win.visualViewport.addEventListener("scroll", schedulePin);
    }
  }
  pinDocumentScroll();
})();
</script>
            """
        ),
        height=0,
        width=0,
    )


def inject_template_css() -> None:
    """Inject the active template stylesheet into the Streamlit page."""
    st.markdown(_build_template_ui_css(), unsafe_allow_html=True)
    inject_mobile_viewport_lock()


def render_theme_css() -> None:
    light_tokens = """
        color-scheme:light;
        --cd-bg:#F7F9FC;--cd-surface:#FFFFFF;--cd-surface-muted:#F1F4F8;
        --cd-nav:#EEF2F6;--cd-text:#1F2933;--cd-muted:#66727F;
        --cd-border:#DDE3E9;--cd-panel:#F7F9FB;--cd-subtle:#E9EEF3;
        --cd-accent-soft:#DFF6F2;--cd-accent:#179E90;
        --cd-accent-hover:#11877B;--cd-success:#15803D;
        --cd-scrollbar:#C8D0D8;
        --cd-checkbox-bg:#FFFFFF;--cd-checkbox-border:#D5DCE3;
        --cd-shadow:0 10px 30px rgba(31,41,51,.09);
        --cd-placeholder-opacity:.48;
    """
    dark_tokens = """
        color-scheme:dark;
        --cd-bg:#0F1011;--cd-surface:#101112;--cd-surface-muted:#1D1F20;
        --cd-nav:#1D1F20;--cd-text:#E8EAED;--cd-muted:#9AA0A6;
        --cd-border:#2D3033;--cd-panel:#151718;--cd-subtle:#252729;
        --cd-accent-soft:#123A35;--cd-accent:#39CDBA;
        --cd-accent-hover:#63DECF;--cd-success:#4ADE80;
        --cd-scrollbar:#4B4F54;
        --cd-checkbox-bg:#202223;--cd-checkbox-border:#3A3D40;
        --cd-shadow:0 18px 50px rgba(0,0,0,.38);
        --cd-placeholder-opacity:.48;
    """
    mode = st.session_state.get("appearance", "System")
    tokens = dark_tokens if mode == "Dark" else light_tokens
    portal_background = "#1D1F20" if mode == "Dark" else "#FFFFFF"
    portal_text = "#E8EAED" if mode == "Dark" else "#1F2933"
    portal_muted = "#9AA0A6" if mode == "Dark" else "#66727F"
    system_portal_dark = (
        """
        @media (prefers-color-scheme:dark) {
            [data-testid="stPopoverBody"],
            [data-testid="stPopoverBody"] > div {
                background:#1D1F20 !important;
            }
            [data-testid="stPopoverBody"] p,
            [data-testid="stPopoverBody"] h3,
            [data-testid="stPopoverBody"] label {
                color:#E8EAED !important;
                -webkit-text-fill-color:#E8EAED !important;
            }
            [data-testid="stPopoverBody"] [data-testid="stTooltipHoverTarget"],
            [data-testid="stPopoverBody"] [data-testid="stTooltipHoverTarget"] [data-testid="stIconMaterial"],
            [data-testid="stPopoverBody"] [data-testid="stTooltipHoverTarget"] svg {
                opacity:1 !important;
                color:#9AA0A6 !important;
                -webkit-text-fill-color:#9AA0A6 !important;
                fill:currentColor !important;
            }
            [data-testid="stPopoverBody"] [data-testid="stCaptionContainer"],
            [data-testid="stPopoverBody"] [data-testid="stCaptionContainer"] p {
                color:#9AA0A6 !important;
                -webkit-text-fill-color:#9AA0A6 !important;
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
    light_inline_code = """
            [data-testid="stChatMessage"] [data-testid="stMarkdownContainer"] p code {
                color:#475467 !important;
                -webkit-text-fill-color:#475467 !important;
                background:#E8EDF2 !important;
                border:1px solid #D5DDE5 !important;
                border-radius:.35rem !important;
                padding:.08rem .3rem !important;
            }
    """
    system_light_inline_code = (
        f"@media (prefers-color-scheme:light) {{ {light_inline_code} }}"
        if mode == "System"
        else ""
    )
    active_light_inline_code = (
        light_inline_code if mode == "Light" else system_light_inline_code
    )
    st.markdown(
        f"""
        <style>
            :root {{{tokens}}}
            {system_dark}
            {active_light_inline_code}
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
            .st-key-profile_coaching_style [data-testid="stRadioOption"],
            .st-key-profile_coaching_style [role="radiogroup"] > [role="radio"] {{
                border-right:0 !important;
                min-height:0 !important;
                color:var(--cd-text) !important;
                background:var(--cd-surface) !important;
            }}
            .st-key-profile_coaching_style [data-testid="stRadioOption"][data-selected],
            .st-key-profile_coaching_style [data-testid="stRadioOption"][aria-checked="true"],
            .st-key-profile_coaching_style [data-testid="stRadioOption"][aria-pressed="true"],
            .st-key-profile_coaching_style [data-testid="stRadioOption"]:has(input:checked),
            .st-key-profile_coaching_style [role="radiogroup"] > label[data-selected],
            .st-key-profile_coaching_style [role="radiogroup"] > label:has(input:checked),
            .st-key-profile_coaching_style [role="radiogroup"]
            > [role="radio"][aria-checked="true"],
            .st-key-profile_coaching_style [role="radiogroup"]
            > [role="radio"][aria-pressed="true"] {{
                color:var(--cd-accent) !important;
                background:var(--cd-accent-soft) !important;
                border-color:var(--cd-accent) !important;
                font-weight:700 !important;
            }}
            .st-key-profile_coaching_style [data-testid="stRadioOption"][data-selected] p,
            .st-key-profile_coaching_style [data-testid="stRadioOption"][aria-checked="true"] p,
            .st-key-profile_coaching_style [data-testid="stRadioOption"][aria-pressed="true"] p,
            .st-key-profile_coaching_style [data-testid="stRadioOption"]:has(input:checked) p,
            .st-key-profile_coaching_style [role="radiogroup"] > label[data-selected] p,
            .st-key-profile_coaching_style [role="radiogroup"] > label:has(input:checked) p,
            .st-key-profile_coaching_style [role="radiogroup"]
            > [role="radio"][aria-checked="true"] p,
            .st-key-profile_coaching_style [role="radiogroup"]
            > [role="radio"][aria-pressed="true"] p {{
                color:var(--cd-accent) !important;
                -webkit-text-fill-color:var(--cd-accent) !important;
            }}
            .st-key-profile_coaching_style [data-testid="stRadioOption"][data-selected]
            [data-testid="stCaptionContainer"] p,
            .st-key-profile_coaching_style [data-testid="stRadioOption"]:has(input:checked)
            [data-testid="stCaptionContainer"] p {{
                color:var(--cd-text) !important;
                -webkit-text-fill-color:var(--cd-text) !important;
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
