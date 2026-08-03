"""Theme CSS injection and appearance overrides for the Streamlit UI."""

from __future__ import annotations

import streamlit as st


TEMPLATE_UI_CSS = """
<style>
    :root {
        --cd-bg:#F3F5F7;
        --cd-surface:#FFFFFF;
        --cd-surface-muted:#F7F9FA;
        --cd-text:#15202B;
        --cd-muted:#5B6B7C;
        --cd-border:#D5DCE3;
        --cd-accent:#0F766E;
        --cd-accent-hover:#0D9488;
        --cd-accent-soft:#E6F5F3;
        --cd-success:#15803D;
        --cd-danger:#B42318;
        --cd-panel:#EEF1F4;
        --cd-subtle:#E8ECF0;
        --cd-shadow:0 8px 24px rgba(21,32,43,.08);
        --cd-header-height:5.4rem;
        --cd-radius:.75rem;
    }

    @import url("https://fonts.googleapis.com/css2?family=IBM+Plex+Sans:wght@400;500;600;700&family=Material+Symbols+Rounded:opsz,wght,FILL,GRAD@20..48,400,0..1,0&family=Source+Serif+4:opsz,wght@8..60,600;8..60,700&display=swap");

    :root {
        --cd-warning-dot:#E11D48;
        --cd-radius-dialog:1rem;
        --cd-transition:150ms ease;
    }

    @media (prefers-reduced-motion: reduce) {
        *, *::before, *::after {
            transition-duration:0.01ms !important;
            animation-duration:0.01ms !important;
        }
    }

    .brand-name {
        font-family:"Source Serif 4",Georgia,"Times New Roman",serif !important;
        font-weight:700 !important;
        letter-spacing:-0.01em;
    }
    .brand-mark {
        background:var(--cd-accent) !important;
        border-radius:.7rem !important;
    }

    .cd-nav-dot {
        display:inline-block;
        width:.42rem;
        height:.42rem;
        margin-left:.28rem;
        border-radius:999px;
        background:var(--cd-warning-dot);
        vertical-align:middle;
    }

    .cd-progress {
        display:grid;
        gap:0;
        margin:0 0 .55rem;
    }
    .cd-progress-heading {
        margin:0 0 .35rem;
        color:var(--cd-text);
        font-size:.92rem;
        font-weight:680;
        line-height:1;
    }
    .cd-progress-meta {
        display:flex;
        justify-content:flex-end;
        align-items:baseline;
        gap:.5rem;
        margin:0 0 5px;
        color:var(--cd-muted);
        font-size:.72rem;
        font-weight:600;
        line-height:1;
    }
    .cd-progress-track {
        height:.42rem;
        border-radius:999px;
        background:color-mix(in srgb, var(--cd-text) 22%, var(--cd-border));
        overflow:hidden;
    }
    .cd-progress-fill {
        height:100%;
        border-radius:999px;
        background:var(--cd-accent);
        transition:width var(--cd-transition);
    }

    .cd-roadmap {
        position:relative;
        display:grid;
        gap:.55rem;
        padding-left:.15rem;
    }
    .cd-roadmap::before {
        content:"";
        position:absolute;
        left:1.05rem;
        top:.6rem;
        bottom:.6rem;
        width:2px;
        background:var(--cd-border);
    }
    .cd-roadmap-step {
        position:relative;
        z-index:1;
        display:grid;
        grid-template-columns:2.1rem 1fr;
        gap:.55rem;
        padding:.55rem .6rem .55rem .1rem;
        border-radius:var(--cd-radius);
        transition:background var(--cd-transition);
    }
    .cd-roadmap-step.current {
        background:var(--cd-accent-soft);
    }
    .cd-roadmap-node {
        width:2.1rem;
        height:2.1rem;
        display:grid;
        place-items:center;
        border-radius:999px;
        border:2px solid var(--cd-border);
        background:var(--cd-surface);
        color:var(--cd-muted);
        font-size:.78rem;
        font-weight:700;
    }
    .cd-roadmap-node .material-symbols-rounded {
        font-family:"Material Symbols Rounded";
        font-size:1.1rem;
        font-variation-settings:"FILL" 0,"wght" 400,"GRAD" 0,"opsz" 20;
        line-height:1;
    }
    .cd-roadmap-step.completed .cd-roadmap-node {
        border-color:var(--cd-accent);
        background:var(--cd-accent);
        color:#fff;
    }
    .cd-roadmap-step.current .cd-roadmap-node {
        border-color:var(--cd-accent);
        color:var(--cd-accent);
        box-shadow:0 0 0 4px color-mix(in srgb, var(--cd-accent) 16%, transparent);
    }

    .cd-card {
        border:1px solid var(--cd-border);
        border-radius:var(--cd-radius);
        background:var(--cd-surface);
        padding:.85rem .9rem;
        margin:0 0 .7rem;
    }
    .cd-card-label {
        color:var(--cd-muted);
        font-size:.72rem;
        font-weight:700;
        letter-spacing:.02em;
        margin-bottom:.35rem;
    }
    .cd-card-body {
        color:var(--cd-text);
        font-size:.9rem;
        line-height:1.45;
    }
    .cd-card ul {
        margin:.2rem 0 0;
        padding-left:1.1rem;
    }

    .cd-empty-state {
        display:grid;
        gap:.45rem;
        place-items:start;
        padding:1.1rem .2rem 1.2rem;
        color:var(--cd-muted);
    }
    .cd-empty-state strong {
        color:var(--cd-text);
        font-size:.95rem;
    }

    .cd-profile-menu { display:grid; gap:.75rem; }
    .cd-profile-avatar {
        width:2.2rem; height:2.2rem; border-radius:999px; display:grid; place-items:center;
        background:var(--cd-accent-soft); color:var(--cd-accent); font-weight:700;
        border:1px solid color-mix(in srgb, var(--cd-accent) 25%, var(--cd-border));
    }
    .cd-notebook-card.is-active {
        border:1px solid color-mix(in srgb, var(--cd-accent) 40%, var(--cd-border));
        background:var(--cd-accent-soft);
        border-radius:var(--cd-radius);
        padding:.55rem .6rem;
    }
    .cd-notebook-list {
        max-height:min(62vh, 34rem);
        overflow-y:auto;
        padding-right:.2rem;
    }

    .st-key-topbar_navigation div[data-testid="stButton"] button {
        min-height:2.35rem !important;
        padding:0 .7rem !important;
        border:1px solid var(--cd-border) !important;
        border-radius:.75rem !important;
        background:var(--cd-surface) !important;
        color:var(--cd-text) !important;
        box-shadow:none !important;
        transition:background 150ms ease, color 150ms ease, border-color 150ms ease;
    }
    .st-key-topbar_navigation div[data-testid="stButton"] button:hover {
        color:var(--cd-text) !important;
        background:var(--cd-surface-muted) !important;
        border-color:var(--cd-border) !important;
    }
    .st-key-topbar_profile div[data-testid="stButton"] button {
        width:auto !important;
        min-width:2.35rem !important;
        min-height:2.35rem !important;
        padding:0 .42rem !important;
        border-radius:.75rem !important;
        border:1px solid var(--cd-border) !important;
        background:var(--cd-surface) !important;
        color:var(--cd-text) !important;
        font-size:.78rem !important;
        font-weight:700 !important;
        letter-spacing:.02em;
        line-height:1 !important;
    }
    .st-key-topbar_profile {
        display:flex;
        justify-content:flex-end;
        align-items:center;
    }
    .st-key-topbar_profile div[data-testid="stButton"] button:hover {
        border-color:var(--cd-border) !important;
        background:var(--cd-surface-muted) !important;
    }

    button:focus-visible,
    input:focus-visible,
    textarea:focus-visible {
        outline:2px solid color-mix(in srgb, var(--cd-accent) 55%, transparent) !important;
        outline-offset:2px !important;
    }

    [data-baseweb="select"] > div:focus-within {
        outline:2px solid color-mix(in srgb, var(--cd-accent) 55%, transparent) !important;
        outline-offset:2px !important;
    }

    .st-key-topbar_mode [data-baseweb="select"] > div:focus-within {
        outline:none !important;
        outline-offset:0 !important;
    }

    [data-testid="stChatMessage"]:has([aria-label="Chat message from user"]) {
        background:var(--cd-accent-soft) !important;
        border-radius:var(--cd-radius);
        padding:.2rem .45rem;
    }


    html,
    body,
    [data-testid="stAppViewContainer"],
    button,
    input,
    textarea,
    [data-baseweb="select"] {
        font-family:"IBM Plex Sans",ui-sans-serif,-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif;
    }

    html,
    body,
    [data-testid="stAppViewContainer"],
    [data-testid="stAppViewContainer"] > .main {
        width:100%;
        height:100vh;
        min-height:100vh;
        overflow:hidden;
        color:var(--cd-text);
        background:var(--cd-bg);
    }

    [data-testid="stHeader"],
    [data-testid="stSidebar"],
    [data-testid="stSidebarCollapsedControl"] {
        display:none !important;
    }

    .block-container {
        width:100%;
        max-width:none;
        height:100vh;
        min-height:0;
        display:flex;
        flex-direction:column;
        overflow:hidden;
        padding:0;
    }

    .block-container > [data-testid="stVerticalBlock"] {
        height:100%;
        min-height:0;
        gap:0;
        overflow:hidden;
    }

    .block-container > [data-testid="stVerticalBlock"]
    > [data-testid="stLayoutWrapper"]:has(.st-key-notebook_workspace) {
        height:0;
        min-height:0;
        flex:1 1 auto;
        overflow:hidden;
    }

    /* Header */
    .st-key-notebook_topbar {
        position:relative;
        height:var(--cd-header-height);
        min-height:var(--cd-header-height);
        flex:0 0 var(--cd-header-height);
        box-sizing:border-box;
        padding:0 1.45rem;
        border-bottom:1px solid var(--cd-border);
        background:var(--cd-surface);
    }

    .st-key-notebook_topbar > [data-testid="stLayoutWrapper"],
    .st-key-notebook_topbar > [data-testid="stLayoutWrapper"]
    > [data-testid="stHorizontalBlock"] {
        height:100%;
    }

    .st-key-notebook_topbar [data-testid="stHorizontalBlock"] {
        align-items:center !important;
        gap:.7rem;
    }

    .st-key-notebook_topbar [data-testid="stColumn"] {
        min-width:0;
        display:flex !important;
        align-items:center !important;
        align-self:center !important;
    }

    .st-key-notebook_topbar [data-testid="stColumn"] > [data-testid="stVerticalBlock"] {
        width:100%;
        justify-content:center;
    }

    .brand-lockup {
        display:flex;
        align-items:center;
        gap:.85rem;
        height:100%;
        margin:0;
        padding:0;
    }

    .st-key-notebook_topbar [data-testid="stColumn"]:first-child,
    .st-key-notebook_topbar [data-testid="stColumn"]:first-child
    > [data-testid="stVerticalBlock"],
    .st-key-notebook_topbar [data-testid="stColumn"]:first-child
    [data-testid="stMarkdownContainer"] {
        display:flex;
        align-items:center;
        height:100%;
        margin:0;
        padding:0;
    }

    .st-key-notebook_topbar [data-testid="stColumn"]:first-child
    [data-testid="stMarkdownContainer"] > div {
        width:100%;
    }

    .brand-mark {
        width:2.9rem;
        height:2.9rem;
        flex:none;
        display:grid;
        place-items:center;
        border-radius:.75rem;
        color:#fff;
        background:var(--cd-accent);
        font-size:1.28rem;
        font-weight:760;
        line-height:1;
        box-shadow:0 5px 14px color-mix(in srgb,var(--cd-accent) 22%,transparent);
    }

    .brand-name {
        color:var(--cd-text);
        font-size:1.16rem;
        font-weight:760;
        letter-spacing:-.025em;
        line-height:1.15;
    }

    .brand-caption {
        color:var(--cd-text);
        font-size:1.18rem;
        font-weight:700;
        line-height:1.2;
        letter-spacing:-.02em;
        white-space:nowrap;
    }

    .st-key-current_notebook_identity {
        position:absolute;
        z-index:2;
        top:50%;
        left:50%;
        width:max-content;
        max-width:min(34rem,34vw);
        min-height:3rem;
        display:flex;
        align-items:center;
        justify-content:center;
        padding:0;
        border-left:0;
        transform:translate(-50%,-50%);
    }

    .st-key-notebook_topbar > [data-testid="stLayoutWrapper"],
    .st-key-notebook_topbar > [data-testid="stLayoutWrapper"]
    > [data-testid="stHorizontalBlock"],
    .st-key-notebook_topbar [data-testid="stColumn"]:has(
        .st-key-current_notebook_identity
    ),
    .st-key-notebook_topbar [data-testid="stVerticalBlock"]:has(
        .st-key-current_notebook_identity
    ),
    .st-key-notebook_topbar [data-testid="stLayoutWrapper"]:has(
        .st-key-current_notebook_identity
    ) {
        position:static !important;
    }

    .st-key-current_notebook_identity > [data-testid="stLayoutWrapper"],
    .st-key-current_notebook_identity > [data-testid="stLayoutWrapper"]
    > [data-testid="stHorizontalBlock"] {
        width:auto;
        max-width:100%;
    }

    .st-key-current_notebook_identity > [data-testid="stLayoutWrapper"]
    > [data-testid="stHorizontalBlock"] {
        display:grid;
        grid-template-columns:minmax(0,max-content) 2rem;
        align-items:center;
        justify-content:start;
        gap:.32rem;
    }

    .st-key-current_notebook_identity [data-testid="stColumn"] {
        width:auto !important;
        min-width:0 !important;
        flex:none !important;
    }

    .st-key-current_notebook_identity h1 {
        margin:0;
        padding:0;
        max-width:100%;
        overflow:hidden;
        color:var(--cd-text);
        font-size:1.08rem;
        font-weight:760;
        letter-spacing:-.026em;
        line-height:1.25;
        text-overflow:ellipsis;
        white-space:nowrap;
    }

    .st-key-current_notebook_identity
    [data-testid="stHeaderActionElements"] {
        margin-left:.2rem;
        color:var(--cd-muted);
    }

    .st-key-current_notebook_identity
    [data-testid="stHeaderActionElements"]:hover {
        color:var(--cd-accent);
    }

    .st-key-current_notebook_identity div[data-testid="stButton"] button {
        width:2rem;
        min-width:2rem;
        height:2rem;
        min-height:2rem;
        display:flex !important;
        align-items:center !important;
        justify-content:center !important;
        padding:0;
        border:1px solid transparent !important;
        border-radius:.48rem !important;
        color:var(--cd-muted) !important;
        background:transparent !important;
    }

    .st-key-current_notebook_identity div[data-testid="stButton"] button:hover {
        border-color:var(--cd-border) !important;
        color:var(--cd-accent) !important;
        background:var(--cd-accent-soft) !important;
    }

    .st-key-current_notebook_identity div[data-testid="stButton"] button p {
        display:none;
    }

    .st-key-current_notebook_identity div[data-testid="stButton"] button
    span[data-has-shortcut] {
        width:100%;
        height:100%;
        display:flex !important;
        align-items:center !important;
        justify-content:center !important;
        gap:0 !important;
    }

    .st-key-current_notebook_identity div[data-testid="stButton"] button
    [data-testid="stIconMaterial"] {
        width:1.15rem;
        height:1.15rem;
        display:grid !important;
        place-items:center;
        margin:0 !important;
        padding:0 !important;
        font-size:1.1rem !important;
        line-height:1 !important;
        transform:translateY(.62rem) !important;
    }

    .st-key-topbar_navigation,
    .st-key-topbar_navigation > [data-testid="stLayoutWrapper"],
    .st-key-topbar_navigation > [data-testid="stLayoutWrapper"]
    > [data-testid="stHorizontalBlock"] {
        width:100%;
    }

    .st-key-topbar_navigation > [data-testid="stLayoutWrapper"]
    > [data-testid="stHorizontalBlock"] {
        align-items:center;
        gap:.3rem;
    }

    .st-key-notebook_topbar div[data-testid="stButton"] button,
    .st-key-notebook_topbar div[data-testid="stPopover"] button {
        min-height:2.35rem;
        border:1px solid transparent !important;
        border-radius:.62rem;
        color:var(--cd-text) !important;
        background:transparent !important;
        box-shadow:none !important;
    }

    .st-key-notebook_topbar .st-key-topbar_mode div[data-testid="stPopover"] button,
    .st-key-notebook_topbar .st-key-topbar_mode [data-testid="stPopover"] button {
        min-height:2.35rem !important;
        height:2.35rem !important;
        padding:0 .7rem !important;
        border:1px solid var(--cd-border) !important;
        border-radius:.75rem !important;
        color:var(--cd-text) !important;
        background:var(--cd-surface) !important;
        box-shadow:none !important;
    }

    .st-key-notebook_topbar div[data-testid="stButton"] button:hover,
    .st-key-notebook_topbar div[data-testid="stPopover"] button:hover {
        border-color:var(--cd-border) !important;
        background:var(--cd-surface-muted) !important;
    }

    .st-key-notebook_topbar .st-key-topbar_mode div[data-testid="stPopover"] button:hover,
    .st-key-notebook_topbar .st-key-topbar_mode [data-testid="stPopover"] button:hover,
    .st-key-notebook_topbar .st-key-topbar_mode div[data-testid="stPopover"] button:focus,
    .st-key-notebook_topbar .st-key-topbar_mode [data-testid="stPopover"] button:focus {
        border:1px solid var(--cd-border) !important;
        background:var(--cd-surface-muted) !important;
    }

    /* Responsive panel selector */
    .st-key-mobile_panel {
        display:none;
        flex:0 0 auto;
    }

    /* Three-column workspace */
    .st-key-notebook_workspace {
        height:100%;
        min-height:0;
        flex:1 1 auto;
        overflow:hidden;
        margin:0;
        border:0;
        border-radius:0;
        background:var(--cd-surface);
    }

    .st-key-notebook_workspace > [data-testid="stLayoutWrapper"],
    .st-key-notebook_workspace > [data-testid="stLayoutWrapper"]
    > [data-testid="stHorizontalBlock"] {
        height:100%;
        min-height:0;
    }

    .st-key-notebook_workspace > [data-testid="stLayoutWrapper"]
    > [data-testid="stHorizontalBlock"] {
        position:relative;
        align-items:stretch;
        gap:0;
    }

    .st-key-notebook_workspace > [data-testid="stLayoutWrapper"]
    > [data-testid="stHorizontalBlock"] > [data-testid="stColumn"] {
        position:relative;
        height:100%;
        min-width:0;
        min-height:0;
    }

    /* Collapsed rails are sized by JS (cd-col-rail); keep CSS as a fallback only. */
    .st-key-notebook_workspace > [data-testid="stLayoutWrapper"]
    > [data-testid="stHorizontalBlock"] > [data-testid="stColumn"].cd-col-rail,
    .st-key-notebook_workspace > [data-testid="stLayoutWrapper"]
    > [data-testid="stHorizontalBlock"] > [data-testid="stColumn"]:has(.st-key-studio_rail),
    .st-key-notebook_workspace > [data-testid="stLayoutWrapper"]
    > [data-testid="stHorizontalBlock"] > [data-testid="stColumn"]:has(.st-key-sources_rail) {
        flex:0 0 2.625rem !important;
        width:2.625rem !important;
        min-width:2.625rem !important;
        max-width:2.625rem !important;
        overflow:visible;
    }

    /* Let side-panel arrow boxes sit on the divider without being clipped. */
    .st-key-notebook_workspace > [data-testid="stLayoutWrapper"]
    > [data-testid="stHorizontalBlock"] > [data-testid="stColumn"]:has(.st-key-studio_panel),
    .st-key-notebook_workspace > [data-testid="stLayoutWrapper"]
    > [data-testid="stHorizontalBlock"] > [data-testid="stColumn"]:has(.st-key-sources_panel),
    .st-key-notebook_workspace > [data-testid="stLayoutWrapper"]
    > [data-testid="stHorizontalBlock"] > [data-testid="stColumn"]:has(.st-key-studio_rail),
    .st-key-notebook_workspace > [data-testid="stLayoutWrapper"]
    > [data-testid="stHorizontalBlock"] > [data-testid="stColumn"]:has(.st-key-sources_rail),
    .st-key-notebook_workspace > [data-testid="stLayoutWrapper"]
    > [data-testid="stHorizontalBlock"] > [data-testid="stColumn"]:has(.st-key-studio_panel)
    > [data-testid="stVerticalBlock"],
    .st-key-notebook_workspace > [data-testid="stLayoutWrapper"]
    > [data-testid="stHorizontalBlock"] > [data-testid="stColumn"]:has(.st-key-sources_panel)
    > [data-testid="stVerticalBlock"],
    .st-key-notebook_workspace > [data-testid="stLayoutWrapper"]
    > [data-testid="stHorizontalBlock"] > [data-testid="stColumn"]:has(.st-key-studio_rail)
    > [data-testid="stVerticalBlock"],
    .st-key-notebook_workspace > [data-testid="stLayoutWrapper"]
    > [data-testid="stHorizontalBlock"] > [data-testid="stColumn"]:has(.st-key-sources_rail)
    > [data-testid="stVerticalBlock"],
    .st-key-notebook_workspace > [data-testid="stLayoutWrapper"]
    > [data-testid="stHorizontalBlock"] > [data-testid="stColumn"]:has(.st-key-studio_panel)
    > [data-testid="stVerticalBlock"] > [data-testid="stLayoutWrapper"],
    .st-key-notebook_workspace > [data-testid="stLayoutWrapper"]
    > [data-testid="stHorizontalBlock"] > [data-testid="stColumn"]:has(.st-key-sources_panel)
    > [data-testid="stVerticalBlock"] > [data-testid="stLayoutWrapper"],
    .st-key-notebook_workspace > [data-testid="stLayoutWrapper"]
    > [data-testid="stHorizontalBlock"] > [data-testid="stColumn"]:has(.st-key-studio_rail)
    > [data-testid="stVerticalBlock"] > [data-testid="stLayoutWrapper"],
    .st-key-notebook_workspace > [data-testid="stLayoutWrapper"]
    > [data-testid="stHorizontalBlock"] > [data-testid="stColumn"]:has(.st-key-sources_rail)
    > [data-testid="stVerticalBlock"] > [data-testid="stLayoutWrapper"] {
        overflow:visible;
    }

    .st-key-notebook_workspace > [data-testid="stLayoutWrapper"]
    > [data-testid="stHorizontalBlock"] > [data-testid="stColumn"]
    > [data-testid="stVerticalBlock"],
    .st-key-notebook_workspace > [data-testid="stLayoutWrapper"]
    > [data-testid="stHorizontalBlock"] > [data-testid="stColumn"]
    > [data-testid="stVerticalBlock"] > [data-testid="stLayoutWrapper"] {
        height:100%;
        min-height:0;
        overflow:hidden;
    }

    /* Drag the divider between columns (no header strip). */
    .cd-col-resize-handle {
        position:absolute;
        top:0;
        right:-3px;
        z-index:40;
        width:6px;
        height:100%;
        cursor:col-resize;
        background:transparent;
    }

    .cd-col-resize-handle:hover,
    .cd-col-resize-handle:focus-visible,
    body.cd-col-resizing .cd-col-resize-handle {
        background:color-mix(in srgb,var(--cd-accent) 42%,transparent);
    }

    body.cd-col-resizing,
    body.cd-col-resizing * {
        cursor:col-resize !important;
        user-select:none !important;
    }

    /* Keep the zero-height resize bridge iframe out of layout. */
    .st-key-notebook_workspace
    [data-testid="stElementContainer"]:has(iframe[height="0"]),
    .st-key-notebook_workspace
    [data-testid="stElementContainer"]:has(iframe[style*="height: 0"]) {
        position:absolute !important;
        width:0 !important;
        height:0 !important;
        min-height:0 !important;
        margin:0 !important;
        padding:0 !important;
        overflow:hidden !important;
        opacity:0 !important;
        pointer-events:none !important;
    }

    /* Side-panel arrows sit centered on the divider line. */
    .st-key-studio_panel,
    .st-key-sources_panel,
    .st-key-studio_rail,
    .st-key-sources_rail {
        position:relative;
        overflow:visible;
    }

    .st-key-notebook_workspace > [data-testid="stLayoutWrapper"]
    > [data-testid="stHorizontalBlock"] > [data-testid="stColumn"]:has(.st-key-sources_panel) {
        position:relative;
        z-index:3;
    }

    [class*="st-key-collapse-studio"],
    [class*="st-key-collapse-sources"],
    [class*="st-key-expand-studio"],
    [class*="st-key-expand-sources"] {
        position:absolute !important;
        z-index:120 !important;
        top:50% !important;
        width:1.35rem !important;
        margin:0 !important;
        pointer-events:auto !important;
    }

    /* Thinking Path controls sit on the right divider. */
    [class*="st-key-collapse-studio"],
    [class*="st-key-expand-studio"] {
        right:0 !important;
        left:auto !important;
        transform:translate(50%, -50%) !important;
    }

    /* Sources controls sit on the left divider. */
    [class*="st-key-collapse-sources"],
    [class*="st-key-expand-sources"] {
        left:0 !important;
        right:auto !important;
        transform:translate(-50%, -50%) !important;
    }

    [class*="st-key-collapse-studio"] div[data-testid="stButton"] button,
    [class*="st-key-collapse-sources"] div[data-testid="stButton"] button,
    [class*="st-key-expand-studio"] div[data-testid="stButton"] button,
    [class*="st-key-expand-sources"] div[data-testid="stButton"] button {
        width:1.35rem !important;
        min-width:1.35rem !important;
        min-height:2.4rem !important;
        padding:0 !important;
        border:1px solid var(--cd-border) !important;
        border-radius:.55rem !important;
        color:var(--cd-muted) !important;
        background:var(--cd-surface) !important;
        box-shadow:var(--cd-shadow);
        font-size:1.05rem !important;
        font-weight:600 !important;
        line-height:1 !important;
    }

    [class*="st-key-collapse-studio"] div[data-testid="stButton"] button:hover,
    [class*="st-key-collapse-sources"] div[data-testid="stButton"] button:hover,
    [class*="st-key-expand-studio"] div[data-testid="stButton"] button:hover,
    [class*="st-key-expand-sources"] div[data-testid="stButton"] button:hover {
        color:var(--cd-accent) !important;
        border-color:color-mix(in srgb,var(--cd-accent) 40%,var(--cd-border)) !important;
    }

    .st-key-studio_rail,
    .st-key-sources_rail {
        height:100%;
        min-height:0;
        width:100%;
        display:flex;
        flex-direction:column;
        align-items:center;
        justify-content:center;
        padding:0;
        box-sizing:border-box;
        background:var(--cd-panel);
    }

    .st-key-studio_rail {
        border-right:1px solid var(--cd-border);
    }

    .st-key-sources_rail {
        border-left:1px solid var(--cd-border);
    }

    .st-key-studio_rail > [data-testid="stLayoutWrapper"],
    .st-key-sources_rail > [data-testid="stLayoutWrapper"],
    .st-key-studio_rail [data-testid="stVerticalBlock"],
    .st-key-sources_rail [data-testid="stVerticalBlock"] {
        height:100%;
        min-height:0;
        width:100%;
        overflow:visible;
    }

    .st-key-studio_panel,
    .st-key-chat_panel,
    .st-key-sources_panel {
        height:100%;
        min-height:0;
        display:flex;
        flex-direction:column;
        box-sizing:border-box;
        border:0;
        border-radius:0;
        color:var(--cd-text);
        background:var(--cd-surface);
        box-shadow:none;
    }

    .st-key-studio_panel {
        padding:1.1rem 1rem .8rem;
        border-right:1px solid var(--cd-border);
        background:var(--cd-panel);
        overflow:visible;
    }

    .st-key-studio_panel .pane-heading {
        min-height:2rem;
    }

    .st-key-chat_panel {
        padding:1.55rem 2rem 1.25rem;
        background:var(--cd-surface);
        overflow:hidden;
    }

    .st-key-notebook_workspace > [data-testid="stLayoutWrapper"]
    > [data-testid="stHorizontalBlock"] > [data-testid="stColumn"]:has(.st-key-sources_panel)
    > [data-testid="stVerticalBlock"],
    .st-key-notebook_workspace > [data-testid="stLayoutWrapper"]
    > [data-testid="stHorizontalBlock"] > [data-testid="stColumn"]:has(.st-key-sources_panel)
    > [data-testid="stVerticalBlock"] > [data-testid="stElementContainer"].st-key-sources_panel {
        display:flex !important;
        flex-direction:column !important;
        height:100% !important;
        min-height:0 !important;
    }

    [data-testid="stElementContainer"].st-key-sources_panel,
    .st-key-sources_panel > [data-testid="stVerticalBlock"] {
        display:flex !important;
        flex-direction:column !important;
        height:100% !important;
        min-height:0 !important;
        flex:1 1 auto !important;
    }

    .st-key-sources_panel {
        padding:1.55rem 1.6rem 1.2rem;
        border-left:1px solid var(--cd-border);
        background:var(--cd-panel);
        overflow:visible;
        box-sizing:border-box;
    }

    .st-key-sources_panel > [data-testid="stVerticalBlock"] {
        display:flex !important;
        flex-direction:column !important;
        height:100% !important;
        min-height:0 !important;
    }

    .st-key-sources_panel > [data-testid="stVerticalBlock"] > [data-testid="stLayoutWrapper"] {
        flex:0 0 auto;
        min-height:0;
    }

    .st-key-sources_panel > [data-testid="stLayoutWrapper"]:has(.st-key-sources_header),
    .st-key-sources_panel > [data-testid="stVerticalBlock"] > [data-testid="stLayoutWrapper"]:has(.st-key-sources_header) {
        flex:0 0 auto !important;
        padding-bottom:.35rem;
        border-bottom:1px solid var(--cd-border);
    }

    .st-key-sources_panel > [data-testid="stLayoutWrapper"]:has(.st-key-sources_scroll),
    .st-key-sources_panel > [data-testid="stVerticalBlock"] > [data-testid="stLayoutWrapper"]:has(.st-key-sources_scroll) {
        flex:1 1 auto !important;
        min-height:0 !important;
        max-height:100% !important;
        overflow:hidden !important;
        display:flex !important;
        flex-direction:column !important;
    }

    .st-key-sources_panel > [data-testid="stLayoutWrapper"]:has(.st-key-sources_scroll)
    [data-testid="stVerticalBlockBorderWrapper"],
    .st-key-sources_panel > [data-testid="stVerticalBlock"] > [data-testid="stLayoutWrapper"]:has(.st-key-sources_scroll)
    [data-testid="stVerticalBlockBorderWrapper"] {
        flex:1 1 auto !important;
        min-height:0 !important;
        max-height:100% !important;
        overflow-y:auto !important;
        overflow-x:hidden !important;
        overscroll-behavior:contain;
    }

    .st-key-sources_panel > [data-testid="stLayoutWrapper"]:has(iframe[height="0"]),
    .st-key-sources_panel > [data-testid="stVerticalBlock"] > [data-testid="stLayoutWrapper"]:has(iframe[height="0"]) {
        flex:0 0 auto !important;
        min-height:0 !important;
        max-height:0 !important;
        overflow:hidden !important;
    }

    .st-key-sources_panel > [data-testid="stLayoutWrapper"]:has(.st-key-sources_scroll),
    .st-key-studio_panel > [data-testid="stLayoutWrapper"]:has(.st-key-studio_scroll),
    .st-key-chat_panel > [data-testid="stLayoutWrapper"]:has(.st-key-chat_log) {
        min-height:0;
        flex:1 1 auto;
        overflow:hidden;
    }

    .st-key-sources_scroll,
    .st-key-studio_scroll,
    .st-key-chat_log {
        min-height:0;
        overflow-y:auto !important;
        overflow-x:hidden;
        overscroll-behavior:contain;
        scrollbar-width:thin;
        scrollbar-color:var(--cd-text) transparent;
    }

    .st-key-studio_scroll,
    .st-key-chat_log {
        height:100%;
    }

    .st-key-sources_scroll::-webkit-scrollbar,
    .st-key-studio_scroll::-webkit-scrollbar,
    .st-key-chat_log::-webkit-scrollbar {
        width:6px;
    }

    .st-key-sources_scroll::-webkit-scrollbar-track,
    .st-key-studio_scroll::-webkit-scrollbar-track,
    .st-key-chat_log::-webkit-scrollbar-track {
        background:transparent;
    }

    .st-key-sources_scroll::-webkit-scrollbar-thumb,
    .st-key-studio_scroll::-webkit-scrollbar-thumb,
    .st-key-chat_log::-webkit-scrollbar-thumb {
        background:var(--cd-text);
        border-radius:999px;
    }

    .st-key-sources_scroll > [data-testid="stVerticalBlock"],
    .st-key-sources_scroll > [data-testid="stLayoutWrapper"] {
        height:auto !important;
        max-height:none !important;
        min-height:0 !important;
        flex:0 0 auto !important;
        overflow:visible !important;
    }

    .st-key-sources_scroll [data-testid="stLayoutWrapper"],
    .st-key-sources_scroll [data-testid="stElementContainer"],
    .st-key-sources_scroll [data-testid="stExpander"],
    .st-key-sources_scroll [data-testid="stVerticalBlock"]:not(.st-key-sources_scroll) {
        height:auto !important;
        max-height:none !important;
        min-height:0 !important;
        flex:0 0 auto !important;
        overflow:visible !important;
    }

    /* Panel headings and tabs */
    .pane-heading {
        min-height:2.5rem;
        display:flex;
        align-items:center;
        justify-content:space-between;
        gap:.75rem;
    }

    .pane-title {
        color:var(--cd-text);
        font-size:1.13rem;
        font-weight:740;
        letter-spacing:-.025em;
    }

    .pane-count {
        color:var(--cd-muted);
        font-size:.76rem;
        font-variant-numeric:tabular-nums;
    }

    .st-key-studio_scroll [role="tablist"] {
        width:100%;
        height:2.55rem;
        display:grid !important;
        grid-template-columns:1fr 1fr;
        gap:0 !important;
        overflow:hidden;
        margin:.35rem 0 .4rem;
        padding:0 !important;
        border:1px solid var(--cd-border);
        border-radius:.62rem;
        background:var(--cd-surface);
    }

    .st-key-studio_scroll [role="tab"] {
        min-height:2.45rem;
        display:flex;
        justify-content:center;
        margin:0 !important;
        padding:.45rem .7rem !important;
        border:0 !important;
        color:var(--cd-muted) !important;
        background:transparent !important;
    }

    .st-key-studio_scroll [role="tab"]:first-child {
        border-right:1px solid var(--cd-border) !important;
    }

    .st-key-studio_scroll [role="tab"][aria-selected="true"] {
        color:var(--cd-accent) !important;
        background:var(--cd-accent-soft) !important;
        box-shadow:inset 0 -2px 0 var(--cd-accent);
    }

    .st-key-studio_scroll [data-testid="stCaptionContainer"] {
        margin:0 !important;
        padding:0 !important;
    }

    .st-key-studio_scroll [data-testid="stCaptionContainer"] p {
        color:var(--cd-text) !important;
        -webkit-text-fill-color:var(--cd-text) !important;
        font-weight:650 !important;
    }

    .st-key-studio_scroll [data-testid="stElementContainer"]:has(.cd-progress) {
        margin-bottom:.34rem;
    }

    .st-key-studio_scroll [role="tab"] .react-aria-SelectionIndicator {
        display:none !important;
    }

    /* Journey */
    .st-key-journey_track {
        position:relative;
        display:flex;
        flex-direction:column;
        gap:.05rem;
        padding:0 0 .15rem;
    }

    .st-key-journey_track [data-testid="stElementContainer"]:has(
        .journey-a11y
    ) {
        position:absolute;
        width:1px;
        height:1px;
        overflow:hidden;
        clip-path:inset(50%);
    }

    [class*="st-key-journey_stage_"] {
        position:relative;
        min-height:0;
        margin:0 0 .22rem;
        padding:.38rem .55rem .34rem;
        border-radius:.7rem;
        border:1px solid transparent;
        background:transparent;
        text-align:left;
    }

    div[data-testid="stElementContainer"]:has(.journey-state) {
        position:absolute !important;
        width:1px !important;
        height:1px !important;
        overflow:hidden !important;
        clip-path:inset(50%);
    }

    [class*="st-key-journey_stage_"] [data-testid="stVerticalBlock"] {
        gap:.2rem;
    }

    [class*="st-key-journey_stage_"]:not(:last-child)::after {
        content:"";
        position:absolute;
        z-index:0;
        top:2.15rem;
        bottom:-.65rem;
        left:1.24rem;
        width:1px;
        background:var(--cd-border);
    }

    [class*="st-key-journey_stage_"]:has(.journey-state.current) {
        margin:.1rem 0 .48rem;
        padding:.95rem .88rem .9rem;
        border:1px solid color-mix(in srgb,var(--cd-accent) 22%,transparent);
        background:var(--cd-accent-soft);
    }

    [class*="st-key-journey_stage_"]:has(.journey-state.upcoming) {
        opacity:.78;
    }

    [class*="st-key-journey-toggle-"] {
        width:100%;
        min-width:0;
        display:flex;
        justify-content:flex-end;
    }

    [class*="st-key-journey-toggle-"] div[data-testid="stButton"],
    [class*="st-key-journey-toggle-"] [data-testid="stBaseButton-tertiary"] {
        width:auto !important;
        min-width:1.5rem;
        margin-left:auto;
    }

    [class*="st-key-journey-toggle-"] div[data-testid="stButton"] button,
    [class*="st-key-journey-toggle-"] [data-testid="stBaseButton-tertiary"] {
        width:1.5rem !important;
        min-width:1.5rem !important;
        min-height:1.4rem !important;
        justify-content:center !important;
        margin:0 0 0 auto !important;
        padding:0 !important;
        border:0 !important;
        border-radius:0 !important;
        color:var(--cd-muted) !important;
        background:transparent !important;
        box-shadow:none !important;
        font-size:.92rem !important;
        font-weight:500 !important;
        line-height:1 !important;
    }

    [class*="st-key-journey-toggle-"] div[data-testid="stButton"] button:hover,
    [class*="st-key-journey-toggle-"] [data-testid="stBaseButton-tertiary"]:hover {
        color:var(--cd-accent) !important;
        background:transparent !important;
    }

    [class*="st-key-journey-toggle-"] div[data-testid="stButton"] button p,
    [class*="st-key-journey-toggle-"] [data-testid="stBaseButton-tertiary"] p {
        margin:0;
        text-align:center;
        color:inherit !important;
        -webkit-text-fill-color:currentColor !important;
        font-size:inherit !important;
        font-weight:inherit !important;
    }

    [class*="st-key-journey_stage_"] [data-testid="stColumn"] {
        min-width:0;
        align-self:flex-start;
        text-align:left;
    }

    [class*="st-key-journey_stage_"] [data-testid="stColumn"]
    > [data-testid="stVerticalBlock"] {
        justify-content:flex-start;
        align-items:stretch;
    }

    [class*="st-key-journey_stage_"] [data-testid="stMarkdownContainer"] {
        margin:0;
        text-align:left;
    }

    [class*="st-key-journey_stage_"] [data-testid="stElementContainer"] {
        margin-bottom:0;
    }

    [class*="st-key-journey_stage_"] > [data-testid="stLayoutWrapper"]
    > [data-testid="stHorizontalBlock"] {
        position:relative;
        z-index:1;
        align-items:flex-start;
        justify-content:flex-start;
        gap:.42rem;
    }

    [class*="st-key-journey_stage_"] .cd-roadmap-step {
        display:flex;
        align-items:flex-start;
        justify-content:flex-start;
        padding:0;
    }

    [class*="st-key-journey_stage_"] [data-testid="stColumn"]:first-child {
        display:flex;
        align-items:flex-start;
        justify-content:flex-start;
    }

    .journey-state {
        display:none;
    }

    .journey-icon {
        position:relative;
        z-index:1;
        width:2rem;
        height:2rem;
        display:grid;
        place-items:center;
        border:1px solid var(--cd-border);
        border-radius:50%;
        color:var(--cd-muted);
        background:var(--cd-surface);
    }

    .journey-icon .material-symbols-rounded {
        font-family:"Material Symbols Rounded";
        font-size:1.08rem;
        font-variation-settings:"FILL" 0,"wght" 400,"GRAD" 0,"opsz" 20;
        line-height:1;
    }

    [class*="st-key-journey_stage_"]:has(.journey-state.current) .journey-icon {
        border-color:var(--cd-accent);
        color:#fff;
        background:var(--cd-accent);
    }

    [class*="st-key-journey_stage_"]:has(.journey-state.completed) .journey-icon {
        border-color:color-mix(in srgb,var(--cd-accent) 38%,var(--cd-border));
        color:var(--cd-accent);
    }

    .journey-stage-heading {
        display:flex;
        align-items:center;
        gap:.5rem;
        color:var(--cd-text);
    }

    .journey-copy-stack {
        min-width:0;
        display:flex;
        flex-direction:column;
        justify-content:flex-start;
    }

    .journey-short-label {
        min-width:0;
        overflow:hidden;
        font-size:1rem;
        font-weight:720;
        line-height:1.2;
        text-overflow:ellipsis;
        white-space:nowrap;
    }

    .journey-stage-detail {
        box-sizing:border-box;
        margin:.32rem 0 0;
        padding-left:0;
    }

    .journey-stage-detail strong {
        display:block;
        margin-bottom:.18rem;
        color:var(--cd-text);
        font-size:.86rem;
        font-weight:700;
        line-height:1.25;
    }

    .journey-stage-detail span {
        display:block;
        color:var(--cd-muted);
        font-size:.74rem;
        line-height:1.48;
    }

    [class*="st-key-journey-suggestions-"] {
        box-sizing:border-box;
        width:100%;
        margin:.42rem 0 0;
        padding:.12rem;
        border:1px solid color-mix(in srgb,var(--cd-accent) 34%,var(--cd-border));
        border-radius:.6rem;
        background:var(--cd-surface);
    }

    [class*="st-key-journey-suggestions-"]
    [data-testid="stPopover"] > button {
        width:100%;
        min-height:2.4rem;
        display:flex !important;
        align-items:center !important;
        justify-content:flex-start !important;
        gap:.5rem !important;
        margin-top:0;
        padding:.42rem .62rem !important;
        border:0 !important;
        border-radius:.48rem !important;
        color:var(--cd-accent) !important;
        background:transparent !important;
        font-size:.76rem;
        font-weight:650;
    }

    [class*="st-key-journey-suggestions-"]
    [data-testid="stPopover"] > button
    span[data-has-shortcut] {
        width:100%;
        display:flex;
        align-items:center;
        justify-content:flex-start !important;
        gap:.48rem;
    }

    [class*="st-key-journey-suggestions-"]
    [data-testid="stPopover"] > button
    span[data-has-shortcut] p {
        flex:1;
        margin:0;
        text-align:left;
    }

    [class*="st-key-journey-suggestions-"]
    [data-testid="stPopover"] > button
    span[data-has-shortcut] > span:has([data-testid="stIconMaterial"]) {
        order:0;
    }

    [data-testid="stPopoverBody"]:has(.journey-question-list) {
        width:min(28rem,calc(100vw - 1.5rem));
    }

    .journey-question-list {
        display:grid;
        gap:.45rem;
        margin-top:.35rem;
    }

    .journey-question-row {
        display:flex;
        align-items:flex-start;
        gap:.55rem;
        padding:.62rem .7rem;
        border:1px solid var(--cd-border);
        border-radius:.55rem;
        color:var(--cd-text);
        background:var(--cd-surface);
        font-size:.8rem;
        line-height:1.45;
    }

    .journey-question-row .material-symbols-rounded {
        flex:none;
        margin-top:.08rem;
        color:var(--cd-accent);
        font-family:"Material Symbols Rounded";
        font-size:1rem;
        line-height:1;
    }

    [class*="st-key-advance-journey-"] {
        margin-top:.35rem;
    }

    [class*="st-key-advance-journey-"] div[data-testid="stButton"] button {
        min-height:2.45rem;
        border:1px solid var(--cd-border) !important;
        color:var(--cd-text) !important;
        background:var(--cd-surface) !important;
    }

    /* Review */
    .review-section {
        padding:1rem 0;
        border-bottom:1px solid var(--cd-border);
    }

    .review-section:first-child {
        padding-top:.1rem;
    }

    .review-section:last-of-type {
        border-bottom:0;
    }

    .review-label {
        margin-bottom:.46rem;
        color:var(--cd-text);
        font-size:.88rem;
        font-weight:710;
    }

    .review-value {
        color:var(--cd-muted);
        font-size:.79rem;
        line-height:1.58;
    }

    .review-understanding .review-value strong {
        display:block;
        margin-bottom:.42rem;
        color:var(--cd-text);
        font-size:1rem;
        font-weight:730;
    }

    .review-understanding {
        display:grid;
        grid-template-columns:2.7rem minmax(0,1fr);
        gap:.8rem;
        align-items:start;
    }

    .review-understanding .review-icon {
        width:2.5rem;
        height:2.5rem;
        display:grid;
        place-items:center;
        border:1px solid var(--cd-border);
        border-radius:50%;
        color:var(--cd-muted);
        background:var(--cd-surface);
    }

    .review-understanding .review-icon .material-symbols-rounded {
        font-family:"Material Symbols Rounded";
        font-size:1.22rem;
        font-variation-settings:"FILL" 0,"wght" 400,"GRAD" 0,"opsz" 20;
        line-height:1;
    }

    .review-understanding .review-value span {
        display:block;
    }

    .review-actions {
        margin:.1rem 0 0;
        padding-left:1.15rem;
        color:var(--cd-muted);
        font-size:.79rem;
        line-height:1.55;
    }

    .review-actions li + li {
        margin-top:.42rem;
    }

    /* Discussion */
    .chat-context-line {
        min-height:3.2rem;
        display:flex;
        align-items:center;
        gap:.48rem;
        padding:.45rem 0 .7rem;
        border-bottom:1px solid var(--cd-border);
        color:var(--cd-muted);
        font-size:.78rem;
    }

    .context-dot {
        width:.54rem;
        height:.54rem;
        flex:none;
        border-radius:50%;
        background:var(--cd-success);
    }

    .st-key-chat_log {
        padding:.65rem .25rem .7rem 0;
    }

    [data-testid="stChatMessage"] {
        margin-bottom:.72rem;
        padding:.8rem .2rem;
        border:0;
        border-radius:0;
        color:var(--cd-text);
        background:transparent;
    }

    [data-testid="stChatMessage"]:has([aria-label="Chat message from user"]) {
        width:fit-content;
        max-width:72%;
        margin-left:auto;
        padding:.95rem 1.02rem;
        border-radius:.85rem;
        background:var(--cd-accent-soft);
    }

    [data-testid="stChatMessageAvatarCustom"] {
        width:2.9rem !important;
        height:2.9rem !important;
        min-width:2.9rem;
        border-radius:50% !important;
        color:#fff !important;
        background:var(--cd-accent) !important;
    }

    [data-testid="stChatMessage"]:has([aria-label="Chat message from user"])
    [data-testid="stChatMessageAvatarCustom"] {
        display:none !important;
    }

    [data-testid="stChatMessage"] [data-testid="stMarkdownContainer"] {
        color:var(--cd-text);
        font-size:.94rem;
        line-height:1.65;
    }

    [data-testid="stChatMessage"] [data-testid="stMarkdownContainer"] p,
    [data-testid="stChatMessage"] [data-testid="stMarkdownContainer"] li,
    [data-testid="stChatMessage"] [data-testid="stMarkdownContainer"] strong {
        color:var(--cd-text) !important;
        -webkit-text-fill-color:var(--cd-text) !important;
    }

    [data-testid="stChatMessage"] [data-testid="stMarkdownContainer"] li + li {
        margin-top:.55rem;
    }

    .message-meta {
        margin:.05rem 0 .45rem;
        color:var(--cd-text);
        font-size:.88rem;
        font-weight:720;
    }

    [class*="st-key-user_message_row_"] {
        position:relative;
        min-height:2rem;
        padding-right:2rem;
    }

    [class*="st-key-user_message_row_"] div[data-testid="stPopover"] {
        position:absolute;
        top:-.05rem;
        right:-.1rem;
        width:1.8rem !important;
        opacity:.5;
    }

    [class*="st-key-user_message_row_"] div[data-testid="stPopover"] button {
        width:1.8rem;
        min-width:1.8rem;
        min-height:1.8rem;
        padding:0;
        border:0 !important;
        background:transparent !important;
    }

    [class*="st-key-user_message_row_"] div[data-testid="stPopover"] button p {
        display:block !important;
        margin:0 !important;
        font-size:1.18rem !important;
        line-height:1;
    }

    [class*="st-key-user_message_row_"] div[data-testid="stPopover"] button
    [data-testid="stIconMaterial"],
    [class*="st-key-user_message_row_"] div[data-testid="stPopover"] button svg {
        display:none !important;
    }

    .st-key-chat_composer {
        position:relative;
        flex:0 0 auto;
        padding-top:.35rem;
        overflow:visible;
    }

    /* Model chip: overlay the composer so bottom/left pin to the footer. */
    .st-key-chat_composer > [data-testid="stLayoutWrapper"]:has(.st-key-composer_model_slot),
    .st-key-chat_composer [data-testid="stElementContainer"]:has(.st-key-composer_model_slot) {
        position:absolute !important;
        inset:0 !important;
        width:auto !important;
        height:auto !important;
        min-height:0 !important;
        margin:0 !important;
        padding:0 !important;
        overflow:visible !important;
        pointer-events:none !important;
    }

    .st-key-composer_model_slot {
        position:static !important;
        width:100% !important;
        height:100% !important;
        min-height:0 !important;
        margin:0 !important;
        padding:0 !important;
        overflow:visible !important;
        pointer-events:none;
    }

    .st-key-composer_model_slot > [data-testid="stLayoutWrapper"],
    .st-key-composer_model_slot [data-testid="stVerticalBlock"],
    .st-key-composer_model_slot [data-testid="stElementContainer"] {
        position:static !important;
        width:100% !important;
        height:100% !important;
        min-width:0 !important;
        min-height:0 !important;
        margin:0 !important;
        padding:0 !important;
        overflow:visible !important;
    }

    .st-key-composer_model_slot [data-testid="stPopover"] {
        position:absolute !important;
        z-index:45 !important;
        inset:auto !important;
        left:0 !important;
        top:0 !important;
        right:auto !important;
        bottom:auto !important;
        width:max-content !important;
        max-width:10.5rem !important;
        min-width:max-content !important;
        margin:0 !important;
        pointer-events:auto !important;
        white-space:nowrap !important;
        transform:none !important;
        opacity:0;
    }

    .st-key-composer_model_slot [data-testid="stPopover"].cd-model-placed {
        opacity:1 !important;
        visibility:visible !important;
    }

    .st-key-composer_model_slot [data-testid="stPopover"] > button,
    .st-key-composer_model_slot [data-testid="stPopover"] [data-testid="stBaseButton-tertiary"] {
        display:inline-flex !important;
        align-items:center !important;
        justify-content:center !important;
        flex-direction:row !important;
        flex-wrap:nowrap !important;
        width:max-content !important;
        min-width:max-content !important;
        max-width:10.5rem !important;
        min-height:1.5rem !important;
        height:1.5rem !important;
        padding:0 .4rem !important;
        border:0 !important;
        border-radius:.45rem !important;
        color:var(--cd-muted) !important;
        background:transparent !important;
        box-shadow:none !important;
        font-size:.78rem !important;
        font-weight:600 !important;
        line-height:1 !important;
        gap:.12rem !important;
        white-space:nowrap !important;
        writing-mode:horizontal-tb !important;
        overflow:hidden !important;
    }

    .st-key-composer_model_slot [data-testid="stPopover"] > button:hover,
    .st-key-composer_model_slot [data-testid="stPopover"] > button:focus,
    .st-key-composer_model_slot [data-testid="stPopover"] > button:focus-visible,
    .st-key-composer_model_slot [data-testid="stPopover"] [data-testid="stBaseButton-tertiary"]:hover,
    .st-key-composer_model_slot [data-testid="stPopover"] [data-testid="stBaseButton-tertiary"]:focus,
    .st-key-composer_model_slot [data-testid="stPopover"] [data-testid="stBaseButton-tertiary"]:focus-visible {
        color:var(--cd-text) !important;
        background:var(--cd-surface-muted) !important;
        outline:none !important;
        box-shadow:none !important;
    }

    .st-key-composer_model_slot [data-testid="stPopover"] > button *,
    .st-key-composer_model_slot [data-testid="stPopover"] [data-testid="stBaseButton-tertiary"] * {
        color:inherit !important;
        -webkit-text-fill-color:currentColor !important;
        white-space:nowrap !important;
        writing-mode:horizontal-tb !important;
    }

    .st-key-composer_model_slot [data-testid="stPopover"] > button
    span[data-has-shortcut],
    .st-key-composer_model_slot [data-testid="stPopover"] [data-testid="stBaseButton-tertiary"]
    span[data-has-shortcut] {
        display:inline-flex !important;
        align-items:center !important;
        flex-direction:row !important;
        flex-wrap:nowrap !important;
        width:max-content !important;
        max-width:100%;
        gap:.12rem !important;
    }

    .st-key-composer_model_slot [data-testid="stPopover"] > button p,
    .st-key-composer_model_slot [data-testid="stPopover"] [data-testid="stBaseButton-tertiary"] p {
        display:inline !important;
        margin:0 !important;
        font-size:.78rem !important;
        font-weight:600 !important;
        white-space:nowrap !important;
        overflow:hidden;
        text-overflow:ellipsis;
    }

    .st-key-composer_model_slot [data-testid="stPopover"] > button
    [data-testid="stIconMaterial"]:last-child {
        display:inline-flex !important;
        flex:none !important;
        font-size:.88rem !important;
        opacity:.75;
    }

    [data-testid="stPopoverBody"]:has([class*="st-key-composer-model-"]) {
        min-width:14rem;
        max-width:min(20rem,calc(100vw - 2rem));
    }

    /*
     * Cursor-style card for Streamlit 1.60+ chat input.
     * Empty state is a single flex row by default; force text on top and a
     * footer row (attach + model | mic + send) underneath.
     */
    .st-key-chat_composer [data-testid="stChatInput"] {
        position:relative !important;
        display:block !important;
        width:100% !important;
        box-sizing:border-box !important;
        min-height:4.5rem !important;
        max-height:11rem !important;
        height:auto !important;
        overflow:visible !important;
        border:1px solid var(--cd-border) !important;
        border-radius:1.05rem !important;
        color:var(--cd-text);
        background:var(--cd-surface) !important;
        box-shadow:none !important;
    }

    .st-key-chat_composer [data-testid="stChatInput"]:focus-within {
        border-color:color-mix(in srgb,var(--cd-accent) 55%,var(--cd-border)) !important;
        box-shadow:0 0 0 3px color-mix(in srgb,var(--cd-accent) 12%,transparent) !important;
    }

    .st-key-chat_composer [data-testid="stChatInput"] > div {
        width:100% !important;
        min-height:4.5rem !important;
        height:auto !important;
        box-sizing:border-box !important;
        border:0 !important;
        outline:none !important;
        box-shadow:none !important;
        background:transparent !important;
    }

    /* Main content row (Ae): always card grid — text full-width, footer below. */
    .st-key-chat_composer [data-testid="stChatInput"] > div > div:has([data-testid="stChatInputTextArea"]) {
        display:grid !important;
        grid-template-columns:minmax(0,1fr) auto !important;
        grid-template-rows:auto auto !important;
        align-items:stretch !important;
        justify-content:stretch !important;
        width:100% !important;
        column-gap:.35rem !important;
        row-gap:.15rem !important;
        flex:1 1 auto !important;
    }

    .st-key-chat_composer [data-testid="stChatInput"] div:has(> [data-testid="stChatInputTextArea"]) {
        grid-column:1 / -1 !important;
        grid-row:1 !important;
        width:100% !important;
        max-width:100% !important;
        min-width:0 !important;
        min-height:0 !important;
        flex:1 1 auto !important;
        order:-1 !important;
        align-items:stretch !important;
        margin:0 !important;
        padding:0 !important;
        border:0 !important;
        background:transparent !important;
        box-shadow:none !important;
        overflow:visible !important;
    }

    /* Expanded Streamlit footer already holds attach + actions. */
    .st-key-chat_composer [data-testid="stChatInput"]
    div:has([data-testid="stChatInputFileUploadButton"]):has([data-testid="stChatInputMicButton"]):not(:has([data-testid="stChatInputTextArea"])),
    .st-key-chat_composer [data-testid="stChatInput"]
    div:has([data-testid="stChatInputFileUploadButton"]):has([data-testid="stChatInputSubmitButton"]):not(:has([data-testid="stChatInputTextArea"])) {
        grid-column:1 / -1 !important;
        grid-row:2 !important;
        display:flex !important;
        align-items:center !important;
        justify-content:space-between !important;
        width:100% !important;
        gap:.35rem !important;
    }

    /* Compact mode: attach group left, action group right on footer row. */
    .st-key-chat_composer [data-testid="stChatInput"]
    div:has([data-testid="stChatInputFileUploadButton"]):not(:has([data-testid="stChatInputMicButton"])):not(:has([data-testid="stChatInputSubmitButton"])):not(:has([data-testid="stChatInputTextArea"])) {
        grid-column:1 !important;
        grid-row:2 !important;
        display:flex !important;
        flex-direction:row !important;
        align-items:center !important;
        justify-content:flex-start !important;
        gap:.2rem !important;
        width:auto !important;
        min-width:0 !important;
        order:0 !important;
    }

    .st-key-chat_composer [data-testid="stChatInput"]
    div:has([data-testid="stChatInputMicButton"]):not(:has([data-testid="stChatInputFileUploadButton"])):not(:has([data-testid="stChatInputTextArea"])),
    .st-key-chat_composer [data-testid="stChatInput"]
    div:has([data-testid="stChatInputSubmitButton"]):not(:has([data-testid="stChatInputFileUploadButton"])):not(:has([data-testid="stChatInputTextArea"])) {
        grid-column:2 !important;
        grid-row:2 !important;
        display:flex !important;
        flex-direction:row !important;
        align-items:center !important;
        justify-content:flex-end !important;
        gap:.15rem !important;
        width:auto !important;
        margin-left:auto !important;
        order:0 !important;
    }

    .st-key-chat_composer [data-testid="stChatInput"] [data-baseweb="textarea"],
    .st-key-chat_composer [data-testid="stChatInput"] [data-baseweb="textarea"] > div {
        width:100% !important;
        max-width:100% !important;
        margin:0 !important;
        padding:0 !important;
        border:0 !important;
        background:transparent !important;
        box-shadow:none !important;
        overflow:visible !important;
    }

    .st-key-chat_composer [data-testid="stChatInput"] textarea,
    .st-key-chat_composer [data-testid="stChatInputTextArea"] {
        width:100% !important;
        box-sizing:border-box !important;
        /* Let Streamlit auto-grow height; cap at 3 lines then scroll. */
        min-height:calc(1em * 1.45) !important;
        max-height:calc(1em * 1.45 * 3) !important;
        overflow-y:auto !important;
        overflow-x:hidden !important;
        resize:none !important;
        padding:.1rem 0 !important;
        margin:0 !important;
        text-align:left !important;
        text-indent:0 !important;
        white-space:pre-wrap !important;
        word-break:break-word !important;
        border:0 !important;
        outline:none !important;
        box-shadow:none !important;
        background:transparent !important;
        color:var(--cd-text) !important;
        font-size:.95rem !important;
        line-height:1.45 !important;
        scrollbar-width:thin;
        scrollbar-color:var(--cd-text) transparent;
    }

    .st-key-chat_composer [data-testid="stChatInput"] textarea::-webkit-scrollbar,
    .st-key-chat_composer [data-testid="stChatInputTextArea"]::-webkit-scrollbar {
        width:6px;
    }

    .st-key-chat_composer [data-testid="stChatInput"] textarea::-webkit-scrollbar-track,
    .st-key-chat_composer [data-testid="stChatInputTextArea"]::-webkit-scrollbar-track {
        background:transparent;
    }

    .st-key-chat_composer [data-testid="stChatInput"] textarea::-webkit-scrollbar-thumb,
    .st-key-chat_composer [data-testid="stChatInputTextArea"]::-webkit-scrollbar-thumb {
        background:var(--cd-text);
        border-radius:999px;
    }

    .st-key-chat_composer [data-testid="stChatInput"] textarea:focus,
    .st-key-chat_composer [data-testid="stChatInput"] textarea:focus-visible,
    .st-key-chat_composer [data-testid="stChatInputTextArea"]:focus,
    .st-key-chat_composer [data-testid="stChatInputTextArea"]:focus-visible {
        border:0 !important;
        outline:none !important;
        box-shadow:none !important;
    }

    .st-key-chat_composer [data-testid="stChatInput"] textarea::placeholder,
    .st-key-chat_composer [data-testid="stChatInputTextArea"]::placeholder {
        color:var(--cd-muted) !important;
        opacity:1;
    }

    /* Streamlit 1.60 controls are flex children — do not absolute-position them. */
    .st-key-chat_composer [data-testid="stChatInputFileUploadButton"],
    .st-key-chat_composer [data-testid="stChatInputFileUploadButton"] button,
    .st-key-chat_composer [data-testid="stChatInputSubmitButton"],
    .st-key-chat_composer [data-testid="stChatInputCancelButton"],
    .st-key-chat_composer [data-testid="stChatInputApproveButton"] {
        position:relative !important;
        inset:auto !important;
        top:auto !important;
        right:auto !important;
        bottom:auto !important;
        left:auto !important;
        transform:none !important;
    }

    /* Microphone input is disabled — hide any leftover mic UI. */
    .st-key-chat_composer [data-testid="stChatInputMicButton"],
    .st-key-chat_composer [data-testid="stChatInputMicButton"] * {
        display:none !important;
    }

    .st-key-chat_composer [data-testid="stChatInputSubmitButton"] {
        display:inline-flex !important;
        align-items:center !important;
        justify-content:center !important;
        width:2.1rem !important;
        height:2.1rem !important;
        min-width:2.1rem !important;
        min-height:2.1rem !important;
        padding:0 !important;
        margin:0 !important;
        border-radius:999px !important;
        color:#fff !important;
        background:var(--cd-accent) !important;
        border:0 !important;
        line-height:0 !important;
    }

    .st-key-chat_composer [data-testid="stChatInputSubmitButton"] svg,
    .st-key-chat_composer [data-testid="stChatInputSubmitButton"] [data-testid="stIconMaterial"] {
        display:none !important;
    }

    .st-key-chat_composer [data-testid="stChatInputSubmitButton"]::before {
        content:"arrow_upward";
        display:flex !important;
        align-items:center !important;
        justify-content:center !important;
        width:1.15rem !important;
        height:1.15rem !important;
        margin:0 !important;
        font-family:"Material Symbols Rounded" !important;
        font-size:1.15rem !important;
        font-variation-settings:"FILL" 0,"wght" 500,"GRAD" 0,"opsz" 20;
        line-height:1 !important;
        text-align:center !important;
        color:#fff !important;
        -webkit-text-fill-color:#fff !important;
        transform:translateY(0.5px);
    }

    .st-key-chat_composer [data-testid="stChatInputSubmitButton"]:disabled {
        color:var(--cd-muted) !important;
        background:var(--cd-surface-muted) !important;
    }

    .st-key-chat_composer [data-testid="stChatInputSubmitButton"]:disabled::before {
        color:var(--cd-muted) !important;
        -webkit-text-fill-color:var(--cd-muted) !important;
    }

    /* Keep the zero-height composer layout bridge iframe out of layout. */
    .st-key-chat_composer
    [data-testid="stElementContainer"]:has(iframe[height="0"]),
    .st-key-chat_composer
    [data-testid="stElementContainer"]:has(iframe[style*="height: 0"]) {
        position:absolute !important;
        width:0 !important;
        height:0 !important;
        min-height:0 !important;
        margin:0 !important;
        padding:0 !important;
        overflow:hidden !important;
        opacity:0 !important;
        pointer-events:none !important;
    }

    .chat-empty {
        min-height:26rem;
        display:flex;
        flex-direction:column;
        align-items:center;
        justify-content:center;
        padding:2rem;
        text-align:center;
    }

    .chat-empty-mark,
    .source-empty-mark {
        display:grid;
        place-items:center;
        color:var(--cd-accent);
        background:var(--cd-accent-soft);
    }

    .chat-empty-mark {
        width:3.1rem;
        height:3.1rem;
        margin-bottom:.9rem;
        border-radius:.8rem;
    }

    .chat-empty-mark .material-symbols-rounded,
    .source-empty-mark .material-symbols-rounded {
        font-family:"Material Symbols Rounded";
        font-size:1.35rem;
        font-variation-settings:"FILL" 0,"wght" 400,"GRAD" 0,"opsz" 20;
        line-height:1;
    }

    .chat-empty h2 {
        margin:0;
        color:var(--cd-text);
        font-size:1.3rem;
    }

    .chat-empty p {
        max-width:30rem;
        margin:.55rem 0 0;
        color:var(--cd-muted);
        font-size:.88rem;
        line-height:1.55;
    }

    /* Sources */
    .st-key-sources_panel [data-testid="stHorizontalBlock"] {
        align-items:center;
    }

    .st-key-sources_header > [data-testid="stVerticalBlock"]
    > [data-testid="stLayoutWrapper"]:first-child [data-testid="stHorizontalBlock"] {
        display:grid !important;
        grid-template-columns:minmax(0, 1fr) 5.25rem !important;
        gap:.35rem !important;
        align-items:start !important;
    }

    .st-key-sources_header > [data-testid="stVerticalBlock"]
    > [data-testid="stLayoutWrapper"]:first-child [data-testid="stColumn"] {
        width:auto !important;
        min-width:0 !important;
    }

    .st-key-sources_filters [data-testid="stHorizontalBlock"] {
        display:flex !important;
        gap:.45rem !important;
        align-items:end !important;
    }

    .st-key-sources_filters [data-testid="stColumn"] {
        flex:1 1 0 !important;
        width:auto !important;
        min-width:0 !important;
    }

    .st-key-sources_header [data-testid="stWidgetLabel"] p {
        margin-bottom:.15rem !important;
        font-size:.78rem !important;
        line-height:1.2 !important;
    }

    .st-key-sources_header [data-testid="stCheckbox"] {
        margin-top:.15rem !important;
        margin-bottom:.15rem !important;
    }

    .st-key-sources_header > [data-testid="stVerticalBlock"] {
        gap:.45rem !important;
    }

    .st-key-sources_panel > [data-testid="stLayoutWrapper"]:first-child {
        padding-bottom:0;
        border-bottom:0;
    }

    .st-key-sources_panel .pane-heading {
        min-height:2.8rem;
    }

    .source-pane-heading {
        align-items:flex-start;
        justify-content:flex-start;
    }

    .source-heading-group {
        display:flex;
        flex-direction:column;
        align-items:flex-start;
        gap:.1rem;
    }

    .source-title-row {
        display:flex;
        align-items:center;
        gap:.38rem;
    }

    .source-heading-group .pane-count {
        display:block;
    }

    .st-key-sources_panel [class*="st-key-add-sources"] div[data-testid="stButton"] button {
        min-height:2.55rem;
        justify-content:flex-end;
        padding:.3rem .25rem !important;
        border:0 !important;
        color:var(--cd-accent) !important;
        background:transparent !important;
        font-size:.92rem;
    }

    .st-key-sources_scroll {
        padding-top:.2rem;
    }

    .st-key-sources_header [data-testid="stTextInput"] input,
    .st-key-sources_header [data-testid="stTextInputRootElement"] input,
    .st-key-sources_scroll [data-testid="stTextInput"] input,
    .st-key-sources_scroll [data-testid="stTextInputRootElement"] input {
        color:var(--cd-text) !important;
        -webkit-text-fill-color:var(--cd-text) !important;
    }

    .st-key-sources_header [data-testid="stTextInput"] input::placeholder,
    .st-key-sources_header [data-testid="stTextInputRootElement"] input::placeholder,
    .st-key-sources_scroll [data-testid="stTextInput"] input::placeholder,
    .st-key-sources_scroll [data-testid="stTextInputRootElement"] input::placeholder {
        color:var(--cd-muted) !important;
        opacity:1;
    }

    .source-empty {
        min-height:6rem;
        display:flex;
        flex-direction:column;
        align-items:center;
        justify-content:center;
        padding:1rem .5rem;
        color:var(--cd-muted);
        text-align:center;
    }

    .source-empty-mark {
        width:2.8rem;
        height:2.8rem;
        margin-bottom:.85rem;
        border-radius:.72rem;
    }

    .source-empty strong {
        color:var(--cd-text);
        font-size:.96rem;
    }

    .st-key-sources_panel [class*="st-key-source_card_"] {
        margin:0;
        padding:1rem .15rem 1.05rem 0;
        border:0;
        border-bottom:1px solid var(--cd-border);
        border-radius:0;
        background:transparent;
    }

    [class*="st-key-source_card_"] [data-testid="stHorizontalBlock"] {
        display:grid;
        grid-template-columns:1.6rem minmax(0,1fr) 2rem;
        gap:.45rem;
    }

    [class*="st-key-source_card_"] [data-testid="stColumn"] {
        width:auto !important;
        min-width:0 !important;
        flex:none !important;
    }

    [class*="st-key-source_card_"] [data-testid="stColumn"]:nth-child(2) div[data-testid="stButton"],
    [class*="st-key-source_card_"] [data-testid="stColumn"]:nth-child(2) [data-testid="stBaseButton-tertiary"] {
        width:100% !important;
        max-width:100% !important;
    }

    [class*="st-key-source_card_"] [data-testid="stColumn"]:nth-child(2) [data-testid="stBaseButton-tertiary"] > div {
        display:block !important;
        width:100% !important;
        max-width:100% !important;
        justify-content:flex-start !important;
        align-items:flex-start !important;
        text-align:left !important;
    }

    [class*="st-key-source_card_"] [data-testid="stColumn"]:nth-child(2) div[data-testid="stButton"] button,
    [class*="st-key-source_card_"] [data-testid="stColumn"]:nth-child(2) [data-testid="stBaseButton-tertiary"] {
        width:100% !important;
        max-width:100% !important;
        display:block !important;
        align-items:flex-start !important;
        justify-content:flex-start !important;
        text-align:left !important;
        min-height:2rem;
        padding:.1rem 0 !important;
        border:0 !important;
        color:var(--cd-text) !important;
        background:transparent !important;
        font-size:.84rem;
        font-weight:680;
        line-height:1.4;
    }

    [class*="st-key-source_card_"] [data-testid="stColumn"]:nth-child(2) div[data-testid="stButton"] button p,
    [class*="st-key-source_card_"] [data-testid="stColumn"]:nth-child(2) [data-testid="stBaseButton-tertiary"] p {
        display:block !important;
        width:100% !important;
        min-width:100% !important;
        max-width:100% !important;
        flex:none !important;
        overflow:hidden;
        text-align:left !important;
        text-overflow:ellipsis;
        white-space:normal;
    }

    [class*="st-key-source_card_"] [data-testid="stColumn"]:nth-child(3) div[data-testid="stButton"] button,
    [class*="st-key-source_card_"] [data-testid="stColumn"]:nth-child(3) [data-testid="stBaseButton-tertiary"] {
        width:2rem !important;
        min-width:2rem !important;
        max-width:2rem !important;
        padding:0 !important;
        border:0 !important;
        background:transparent !important;
    }

    [class*="st-key-source_card_"] [data-testid="stColumn"]:nth-child(3) div[data-testid="stPopover"] button {
        width:2rem;
        min-width:2rem;
        min-height:2rem;
        padding:0;
        border:0 !important;
        background:transparent !important;
    }

    .source-meta {
        margin:.1rem 0 0 2.05rem;
        color:var(--cd-muted);
        font-size:.72rem;
        line-height:1.45;
    }

    .source-lock {
        min-height:2rem;
        display:grid;
        place-items:center;
        color:var(--cd-muted);
    }

    .source-lock .material-symbols-rounded {
        font-size:1rem;
    }

    .source-lock svg {
        width:.92rem;
        height:.92rem;
        stroke:currentColor;
    }

    .st-key-sources_scroll [data-testid="stExpander"] {
        margin:.45rem 0;
        border:1px solid var(--cd-border);
        border-radius:.75rem;
        background:var(--cd-surface);
        overflow:visible !important;
        flex:0 0 auto !important;
        height:auto !important;
        max-height:none !important;
    }

    .st-key-sources_scroll [data-testid="stExpander"] [data-testid="stVerticalBlock"],
    .st-key-sources_scroll [data-testid="stExpander"] [data-testid="stLayoutWrapper"],
    .st-key-sources_scroll [class*="st-key-source_card_"],
    .st-key-sources_scroll [class*="st-key-source_card_"] [data-testid="stVerticalBlock"],
    .st-key-sources_scroll [class*="st-key-source_card_"] [data-testid="stLayoutWrapper"] {
        height:auto !important;
        max-height:none !important;
        overflow:visible !important;
        flex:0 0 auto !important;
        min-height:0 !important;
    }

    .st-key-sources_scroll [data-testid="stExpander"] summary {
        min-height:2.7rem;
        color:var(--cd-text);
        font-size:.78rem;
        font-weight:700;
    }

    /* Buttons and form controls */
    div[data-testid="stButton"] button,
    div[data-testid="stPopover"] button,
    [data-baseweb="select"] > div,
    [data-baseweb="input"],
    [data-baseweb="textarea"] {
        border-radius:.6rem;
    }

    div[data-testid="stButton"] button[kind="primary"],
    [data-testid="stBaseButton-primary"] {
        border-color:var(--cd-accent) !important;
        color:#fff !important;
        background:var(--cd-accent) !important;
    }

    div[data-testid="stButton"] button[kind="primary"] *,
    [data-testid="stBaseButton-primary"] * {
        color:#fff !important;
        -webkit-text-fill-color:#fff !important;
    }

    div[data-testid="stButton"] button[kind="primary"]:hover,
    [data-testid="stBaseButton-primary"]:hover {
        background:var(--cd-accent-hover) !important;
    }

    div[data-testid="stButton"] button[kind="primary"]:disabled,
    [data-testid="stBaseButton-primary"]:disabled {
        opacity:1 !important;
        border-color:var(--cd-border) !important;
        color:var(--cd-muted) !important;
        background:var(--cd-surface-muted) !important;
    }

    /* Dialogs and popovers */
    [data-testid="stDialog"] {
        padding:1.5rem !important;
        align-items:center !important;
        justify-content:center !important;
    }

    [role="dialog"] {
        max-height:calc(100vh - 3rem);
        overflow:auto;
        border:1px solid var(--cd-border) !important;
        border-radius:1rem !important;
        color:var(--cd-text) !important;
        background:var(--cd-surface) !important;
        box-shadow:var(--cd-shadow) !important;
    }

    [role="dialog"]:has(.st-key-notebook-search) {
        width:min(54rem,calc(100vw - 3rem)) !important;
        max-width:min(54rem,calc(100vw - 3rem)) !important;
        min-height:35rem;
    }

    [data-testid="stDialog"] > div:has(> [role="dialog"] .st-key-notebook-search) {
        width:min(54rem,calc(100vw - 3rem)) !important;
    }

    [role="dialog"]:has([data-testid="stFileUploader"]) {
        width:min(42rem,calc(100vw - 3rem)) !important;
        max-width:min(42rem,calc(100vw - 3rem)) !important;
    }

    [data-testid="stDialog"] > div:has(> [role="dialog"] [data-testid="stFileUploader"]) {
        width:min(42rem,calc(100vw - 3rem)) !important;
    }

    [role="dialog"]:has(.stage-confirm-row) {
        width:min(35rem,calc(100vw - 3rem)) !important;
        max-width:min(35rem,calc(100vw - 3rem)) !important;
    }

    [data-testid="stDialog"] > div:has(> [role="dialog"] .stage-confirm-row) {
        width:min(35rem,calc(100vw - 3rem)) !important;
    }

    [role="dialog"]:has(.notebook-actions-context) {
        width:min(31rem,calc(100vw - 3rem)) !important;
        max-width:min(31rem,calc(100vw - 3rem)) !important;
    }

    [data-testid="stDialog"] > div:has(
        > [role="dialog"] .notebook-actions-context
    ) {
        width:min(31rem,calc(100vw - 3rem)) !important;
    }

    .notebook-actions-context {
        margin:.1rem 0 .65rem;
        padding:.8rem .9rem;
        border:1px solid var(--cd-border);
        border-radius:.68rem;
        color:var(--cd-muted);
        background:var(--cd-surface-muted);
        font-size:.8rem;
        line-height:1.5;
    }

    .notebook-actions-context strong {
        color:var(--cd-text);
    }

    .st-key-notebook_action_danger {
        margin-top:.3rem;
        padding:.7rem .8rem .8rem;
        border:1px solid color-mix(in srgb,var(--cd-danger) 22%,var(--cd-border));
        border-radius:.68rem;
        background:color-mix(in srgb,var(--cd-danger) 5%,var(--cd-surface));
    }

    .st-key-notebook_action_danger
    div[data-testid="stButton"] button:not(:disabled) {
        border-color:var(--cd-danger) !important;
        color:#fff !important;
        background:var(--cd-danger) !important;
    }

    .st-key-notebook_action_danger
    div[data-testid="stButton"] button:not(:disabled) * {
        color:#fff !important;
        -webkit-text-fill-color:#fff !important;
    }

    [role="dialog"]:has(.stage-confirm-row) > h2[slot="title"] {
        position:absolute !important;
        width:1px !important;
        height:1px !important;
        overflow:hidden !important;
        clip:rect(0,0,0,0) !important;
        white-space:nowrap !important;
    }

    [role="dialog"] h2,
    [role="dialog"] h3,
    [role="dialog"] h4 {
        color:var(--cd-text) !important;
        letter-spacing:-.025em;
    }

    [role="dialog"] [data-baseweb="input"],
    [role="dialog"] [data-baseweb="select"] > div,
    [role="dialog"] [data-baseweb="textarea"] {
        border-color:var(--cd-border) !important;
        color:var(--cd-text) !important;
        background:var(--cd-surface) !important;
    }

    [role="dialog"]:has(.st-key-notebook-search)
    > [data-testid="stVerticalBlock"] {
        gap:.65rem;
    }

    [class*="st-key-notebook_card_"] {
        margin:0;
        padding:.9rem .75rem 1rem;
        border:0;
        border-bottom:1px solid var(--cd-border);
        border-radius:0;
        background:transparent;
    }

    [class*="st-key-notebook_card_"]:hover {
        background:var(--cd-surface-muted);
    }

    [class*="st-key-notebook_card_"] [data-testid="stHorizontalBlock"] {
        display:grid;
        grid-template-columns:minmax(0,1fr) 4rem 2rem;
        gap:.35rem;
    }

    [class*="st-key-notebook_card_"] [data-testid="stColumn"] {
        width:auto !important;
        min-width:0 !important;
        flex:none !important;
    }

    [class*="st-key-notebook_card_"] div[data-testid="stButton"] button {
        min-height:2rem;
        justify-content:flex-start;
        padding:.1rem 0;
        border:0 !important;
        color:var(--cd-text) !important;
        background:transparent !important;
    }

    [class*="st-key-notebook_card_"] div[data-testid="stButton"] button p {
        overflow:hidden;
        text-align:left;
        text-overflow:ellipsis;
        white-space:nowrap;
        font-size:.88rem;
        font-weight:700;
    }

    .notebook-card-title {
        min-height:2rem;
        display:flex;
        align-items:center;
        overflow:hidden;
        color:var(--cd-text);
        font-size:.86rem;
        font-weight:720;
        line-height:1.35;
        text-overflow:ellipsis;
        white-space:nowrap;
    }

    .notebook-folder-active {
        margin:.35rem 0 .5rem;
        padding:.55rem .7rem;
        border-radius:.48rem;
        color:var(--cd-accent);
        background:var(--cd-accent-soft);
        font-size:.78rem;
        font-weight:650;
    }

    .notebook-card-folder {
        margin:.05rem 0 0;
        color:var(--cd-muted);
        font-size:.7rem;
    }

    .notebook-card-meta {
        margin:.32rem 0 0;
        color:var(--cd-accent);
        font-size:.72rem;
        font-weight:620;
    }

    .notebook-card-summary {
        margin:.28rem 0 0;
        overflow:hidden;
        color:var(--cd-muted);
        font-size:.76rem;
        line-height:1.45;
        text-overflow:ellipsis;
        white-space:nowrap;
    }

    [data-testid="stFileUploaderDropzone"] {
        min-height:12rem;
        display:flex !important;
        flex-direction:column !important;
        align-items:center !important;
        justify-content:center !important;
        gap:.42rem !important;
        border:1px dashed color-mix(in srgb,var(--cd-accent) 42%,var(--cd-border)) !important;
        border-radius:.72rem;
        color:var(--cd-text) !important;
        background:var(--cd-surface-muted) !important;
        text-align:center;
    }

    [data-testid="stFileUploaderDropzone"]::before {
        content:"upload_file";
        order:1;
        color:var(--cd-muted);
        font-family:"Material Symbols Rounded";
        font-size:2.25rem;
        font-variation-settings:"FILL" 0,"wght" 350,"GRAD" 0,"opsz" 32;
        line-height:1;
    }

    [data-testid="stFileUploaderDropzone"]::after {
        content:"Drop files here or browse";
        order:2;
        color:var(--cd-text);
        font-size:.96rem;
        font-weight:700;
    }

    [data-testid="stFileUploaderDropzone"] > [data-testid="stFileUploaderDropzoneInstructions"] {
        order:3;
    }

    [data-testid="stFileUploaderDropzone"] > span {
        order:4;
    }

    [data-testid="stFileUploaderDropzone"] > span button {
        min-height:2.35rem;
        padding:.35rem 1.1rem !important;
        border-color:var(--cd-accent) !important;
        color:var(--cd-accent) !important;
        background:var(--cd-surface) !important;
    }

    [data-testid="stFileUploaderDropzone"] > span button p {
        font-size:0 !important;
    }

    [data-testid="stFileUploaderDropzone"] > span button p::after {
        content:"Choose files";
        font-size:.82rem;
    }

    [data-testid="stFileUploaderDropzone"] *,
    [data-testid="stFileUploaderDropzone"] button * {
        color:var(--cd-text) !important;
        -webkit-text-fill-color:var(--cd-text) !important;
    }

    [data-testid="stPopoverBody"] {
        max-width:23rem;
        overflow:hidden;
        border:1px solid var(--cd-border) !important;
        border-radius:.9rem !important;
        color:var(--cd-text) !important;
        background:var(--cd-surface) !important;
        box-shadow:var(--cd-shadow) !important;
    }

    [data-testid="stPopoverBody"] > div {
        color:var(--cd-text) !important;
        background:var(--cd-surface) !important;
    }

    .preference-hint {
        opacity:1 !important;
        margin:.15rem 0 .35rem;
        color:var(--cd-muted) !important;
        -webkit-text-fill-color:var(--cd-muted) !important;
        font-size:.74rem;
        line-height:1.45;
    }

    [data-testid="stPopoverBody"][aria-label="Setting"] {
        width:min(21rem,calc(100vw - 1.5rem));
        max-width:min(21rem,calc(100vw - 1.5rem));
    }

    [data-testid="stPopoverBody"][aria-label="Setting"]
    > [data-testid="stVerticalBlock"] {
        gap:.82rem;
    }

    [data-testid="stPopoverBody"][aria-label="Setting"] h3 {
        margin:0 0 .08rem;
        line-height:1.2;
    }

    [data-testid="stPopoverBody"][aria-label="Setting"]
    [data-testid="stWidgetLabel"] {
        margin-bottom:.34rem;
    }

    [data-testid="stPopoverBody"][aria-label="Setting"]
    [data-testid="stWidgetLabel"] p {
        line-height:1.3;
    }

    [data-testid="stPopoverBody"][aria-label="Setting"] hr {
        margin:.2rem 0 .05rem;
    }

    .response-mode-guide {
        display:grid;
        gap:.45rem;
        margin:.08rem 0 .48rem;
        padding:.72rem .78rem;
        border:1px solid var(--cd-border);
        border-radius:.62rem;
        background:var(--cd-surface-muted);
    }

    .response-mode-row {
        display:grid;
        grid-template-columns:3.35rem minmax(0,1fr);
        align-items:start;
        gap:.55rem;
        color:var(--cd-muted);
        font-size:.72rem;
        line-height:1.4;
    }

    .response-mode-row strong {
        color:var(--cd-text);
        font-size:.75rem;
    }

    .stage-confirm-row {
        display:grid;
        grid-template-columns:1fr auto 1fr;
        align-items:center;
        gap:.75rem;
        margin:1rem 0;
        padding:1rem;
        border:1px solid var(--cd-border);
        border-radius:.72rem;
        background:var(--cd-surface-muted);
        text-align:center;
    }

    .stage-confirm-row .material-symbols-rounded {
        font-family:"Material Symbols Rounded";
        font-size:1.1rem;
        font-variation-settings:"FILL" 0,"wght" 400,"GRAD" 0,"opsz" 20;
        line-height:1;
    }

    .stage-confirm-item {
        min-width:0;
        display:flex;
        align-items:center;
        justify-content:center;
        gap:.48rem;
    }

    .stage-confirm-icon,
    .stage-confirm-number {
        width:1.9rem;
        height:1.9rem;
        flex:none;
        display:grid;
        place-items:center;
        border:1px solid var(--cd-border);
        border-radius:50%;
        color:var(--cd-muted);
        background:var(--cd-surface);
    }

    .stage-confirm-item.is-current .stage-confirm-icon,
    .stage-confirm-item.is-current .stage-confirm-number {
        border-color:var(--cd-accent);
        color:#fff;
        background:var(--cd-accent);
    }

    .stage-confirm-number {
        font-size:.72rem;
        font-weight:700;
    }

    .stage-confirm-item strong {
        overflow:hidden;
        color:var(--cd-text);
        font-size:.86rem;
        text-overflow:ellipsis;
        white-space:nowrap;
    }

    .stage-confirm-arrow {
        color:var(--cd-muted);
        font-size:1.35rem !important;
    }

    /* Simplified editable notebook header */
    .st-key-current_notebook_identity {
        width:min(31rem,34vw);
    }

    .st-key-current_notebook_identity > [data-testid="stLayoutWrapper"],
    .st-key-current_notebook_identity [data-testid="stTextInput"] {
        width:100%;
    }

    .st-key-current_notebook_identity [data-baseweb="input"],
    .st-key-current_notebook_identity [data-testid="stTextInputRootElement"] {
        min-height:2.45rem;
        border:0 !important;
        border-radius:.55rem;
        background:transparent !important;
        box-shadow:none !important;
    }

    .st-key-current_notebook_identity [data-baseweb="input"]:hover,
    .st-key-current_notebook_identity [data-testid="stTextInputRootElement"]:hover {
        border:1px solid var(--cd-border) !important;
        background:var(--cd-surface-muted) !important;
        box-shadow:none !important;
    }

    .st-key-current_notebook_identity [data-baseweb="input"]:focus-within,
    .st-key-current_notebook_identity [data-testid="stTextInputRootElement"]:focus-within {
        border:1px solid color-mix(in srgb, var(--cd-accent) 45%, var(--cd-border)) !important;
        background:var(--cd-surface) !important;
        box-shadow:0 0 0 3px color-mix(in srgb, var(--cd-accent) 14%, transparent) !important;
    }

    .st-key-current_notebook_identity input {
        overflow:hidden;
        color:var(--cd-text) !important;
        -webkit-text-fill-color:var(--cd-text) !important;
        background:transparent;
        font-size:1.05rem;
        font-weight:760;
        letter-spacing:-.025em;
        text-align:center;
        text-overflow:ellipsis;
        white-space:nowrap;
    }

    .st-key-current_notebook_identity [data-testid="InputInstructions"] {
        display:none !important;
    }

    .st-key-topbar_navigation div[data-testid="stButton"] {
        display:flex;
        justify-content:center;
    }

    .st-key-notebook_topbar .st-key-topbar_navigation div[data-testid="stButton"] button {
        width:auto !important;
        min-width:0;
        min-height:2.35rem !important;
        height:2.35rem !important;
        padding:0 .7rem !important;
        border:1px solid var(--cd-border) !important;
        border-radius:.75rem !important;
        background:var(--cd-surface) !important;
        outline:0 !important;
        box-shadow:none !important;
    }

    .st-key-notebook_topbar .st-key-topbar_navigation div[data-testid="stButton"] button:hover,
    .st-key-notebook_topbar .st-key-topbar_navigation div[data-testid="stButton"] button:focus,
    .st-key-notebook_topbar .st-key-topbar_navigation div[data-testid="stButton"] button:focus-visible {
        color:var(--cd-text) !important;
        border-color:var(--cd-border) !important;
        background:var(--cd-surface-muted) !important;
        outline:0 !important;
        box-shadow:none !important;
    }

    .st-key-topbar_navigation div[data-testid="stButton"] button p {
        position:static;
        width:auto;
        height:auto;
        overflow:visible;
        clip:auto;
        color:var(--cd-text);
        font-size:.95rem;
        font-weight:700;
        white-space:nowrap;
    }

    .st-key-notebook_topbar .st-key-topbar_mode [data-testid="stPopover"] button,
    .st-key-notebook_topbar .st-key-topbar_mode div[data-testid="stPopover"] > button,
    .st-key-topbar_mode [data-testid="stPopover"] button {
        width:auto !important;
        min-width:4.6rem !important;
        max-width:5.4rem !important;
        min-height:2.35rem !important;
        height:2.35rem !important;
        padding:0 .7rem !important;
        border:1px solid var(--cd-border) !important;
        border-radius:.75rem !important;
        color:var(--cd-text) !important;
        background:var(--cd-surface) !important;
        box-shadow:none !important;
        outline:none !important;
        font-size:.9rem !important;
        font-weight:650 !important;
    }

    .st-key-notebook_topbar .st-key-topbar_mode [data-testid="stPopover"] button:hover,
    .st-key-notebook_topbar .st-key-topbar_mode [data-testid="stPopover"] button:focus,
    .st-key-notebook_topbar .st-key-topbar_mode [data-testid="stPopover"] button:focus-visible,
    .st-key-notebook_topbar .st-key-topbar_mode [data-testid="stPopover"] button:active,
    .st-key-topbar_mode [data-testid="stPopover"] button:hover,
    .st-key-topbar_mode [data-testid="stPopover"] button:focus,
    .st-key-topbar_mode [data-testid="stPopover"] button:focus-visible,
    .st-key-topbar_mode [data-testid="stPopover"] button:active {
        border:1px solid var(--cd-border) !important;
        background:var(--cd-surface-muted) !important;
        box-shadow:none !important;
        outline:none !important;
    }

    .st-key-topbar_mode [data-testid="stPopover"] button p {
        display:inline !important;
        margin:0 !important;
        font-size:.9rem !important;
        font-weight:650 !important;
        color:var(--cd-text) !important;
    }

    .st-key-topbar_mode [data-testid="stPopover"] button
    [data-testid="stIconMaterial"]:last-child {
        display:inline-flex !important;
        margin-left:.15rem;
        font-size:1rem !important;
        color:var(--cd-muted) !important;
    }

    .st-key-notebook_topbar .st-key-topbar_profile div[data-testid="stButton"] button {
        width:auto !important;
        min-width:2.35rem !important;
        min-height:2.35rem !important;
        height:2.35rem !important;
        padding:0 .5rem !important;
        border:1px solid var(--cd-border) !important;
        border-radius:.75rem !important;
        background:var(--cd-surface) !important;
        color:var(--cd-text) !important;
        box-shadow:none !important;
    }

    .st-key-open-settings div[data-testid="stButton"] button {
        width:2.4rem;
        min-width:2.4rem;
        min-height:2.4rem;
        padding:0 !important;
        border:0 !important;
        background:transparent !important;
        outline:0 !important;
        box-shadow:none !important;
    }

    .st-key-open-settings div[data-testid="stButton"] button:hover,
    .st-key-open-settings div[data-testid="stButton"] button:focus,
    .st-key-open-settings div[data-testid="stButton"] button:focus-visible {
        color:var(--cd-accent) !important;
        background:transparent !important;
        outline:0 !important;
        box-shadow:none !important;
    }

    .st-key-open-settings div[data-testid="stButton"] button p {
        position:absolute;
        width:1px;
        height:1px;
        padding:0;
        overflow:hidden;
        clip:rect(0,0,0,0);
        white-space:nowrap;
        border:0;
    }

    .topbar-guidance-label {
        margin:0 !important;
        padding:0 !important;
        color:var(--cd-text);
        font-size:.95rem;
        font-weight:700;
        line-height:1 !important;
        white-space:nowrap;
    }

    .st-key-topbar_actions > [data-testid="stLayoutWrapper"]
    > [data-testid="stHorizontalBlock"] > [data-testid="stColumn"]:nth-child(2)
    [data-testid="stMarkdownContainer"],
    .st-key-topbar_actions > [data-testid="stLayoutWrapper"]
    > [data-testid="stHorizontalBlock"] > [data-testid="stColumn"]:nth-child(2)
    [data-testid="stMarkdownContainer"] > div,
    .st-key-topbar_actions > [data-testid="stLayoutWrapper"]
    > [data-testid="stHorizontalBlock"] > [data-testid="stColumn"]:nth-child(2)
    [data-testid="stVerticalBlock"] {
        display:flex !important;
        align-items:center !important;
        height:100% !important;
        margin:0 !important;
        padding:0 !important;
    }

    .st-key-topbar_mode > [data-testid="stLayoutWrapper"]
    > [data-testid="stHorizontalBlock"] {
        align-items:center !important;
        gap:.35rem !important;
        width:max-content !important;
    }

    .st-key-topbar_mode [data-testid="stColumn"] {
        width:auto !important;
        flex:0 0 auto !important;
        min-width:0 !important;
    }

    /* Guidance menu: no heavy outline, soft hover only. */
    [data-testid="stPopoverBody"]:has([class*="st-key-topbar-guidance-"]) {
        border:0 !important;
        outline:none !important;
        box-shadow:var(--cd-shadow) !important;
        background:var(--cd-surface) !important;
        border-radius:.72rem !important;
        padding:.2rem !important;
        min-width:6.5rem !important;
    }

    [data-testid="stPopoverBody"]:has([class*="st-key-topbar-guidance-"])
    > div,
    [data-testid="stPopoverBody"]:has([class*="st-key-topbar-guidance-"])
    [data-testid="stVerticalBlock"],
    [data-testid="stPopoverBody"]:has([class*="st-key-topbar-guidance-"])
    [data-testid="stLayoutWrapper"] {
        gap:0 !important;
        row-gap:0 !important;
    }

    [data-testid="stPopoverBody"] [class*="st-key-topbar-guidance-"] {
        margin:0 !important;
        padding:0 !important;
    }

    [data-testid="stPopoverBody"] [class*="st-key-topbar-guidance-"]
    div[data-testid="stButton"] {
        margin:0 !important;
        padding:0 !important;
    }

    [data-testid="stPopoverBody"] [class*="st-key-topbar-guidance-"]
    div[data-testid="stButton"] button {
        min-height:1.85rem !important;
        height:1.85rem !important;
        margin:0 !important;
        padding:0 .55rem !important;
        border:0 !important;
        border-radius:.45rem !important;
        color:var(--cd-text) !important;
        background:transparent !important;
        box-shadow:none !important;
        justify-content:flex-start !important;
    }

    [data-testid="stPopoverBody"] [class*="st-key-topbar-guidance-"]
    div[data-testid="stButton"] button:hover {
        background:var(--cd-subtle) !important;
    }

    /* Neutral listbox options for any remaining selects. */
    [data-baseweb="popover"] [role="listbox"] [role="option"],
    [data-baseweb="menu"] [role="option"],
    [role="listbox"] [role="option"] {
        color:var(--cd-text) !important;
        background:var(--cd-surface) !important;
    }

    [data-baseweb="popover"] [role="listbox"] [role="option"][aria-selected="true"],
    [data-baseweb="menu"] [role="option"][aria-selected="true"],
    [role="listbox"] [role="option"][aria-selected="true"] {
        color:var(--cd-text) !important;
        background:var(--cd-surface) !important;
        font-weight:650 !important;
    }

    [data-baseweb="popover"] [role="listbox"] [role="option"]:hover,
    [data-baseweb="menu"] [role="option"]:hover,
    [role="listbox"] [role="option"]:hover,
    [data-baseweb="popover"] [role="listbox"] [role="option"]:focus,
    [role="listbox"] [role="option"]:focus {
        color:var(--cd-text) !important;
        background:var(--cd-subtle) !important;
    }

    .st-key-topbar_actions > [data-testid="stLayoutWrapper"],
    .st-key-topbar_actions > [data-testid="stLayoutWrapper"]
    > [data-testid="stHorizontalBlock"] {
        width:100% !important;
        align-items:center !important;
    }

    .st-key-topbar_actions > [data-testid="stLayoutWrapper"]
    > [data-testid="stHorizontalBlock"] {
        gap:0 !important;
    }

    /* Only the top-level action columns — not nested widgets. */
    .st-key-topbar_actions > [data-testid="stLayoutWrapper"]
    > [data-testid="stHorizontalBlock"] > [data-testid="stColumn"]:nth-child(1) {
        flex:0 0 auto !important;
        width:auto !important;
        padding-right:30px !important;
        transform:translateX(-50px);
    }

    .st-key-topbar_actions > [data-testid="stLayoutWrapper"]
    > [data-testid="stHorizontalBlock"] > [data-testid="stColumn"]:nth-child(2) {
        flex:0 0 auto !important;
        width:auto !important;
        transform:translateX(-50px);
    }

    .st-key-topbar_actions > [data-testid="stLayoutWrapper"]
    > [data-testid="stHorizontalBlock"] > [data-testid="stColumn"]:nth-child(3) {
        flex:0 0 auto !important;
        width:max-content !important;
        max-width:max-content !important;
        transform:translateX(-50px);
        padding-left:.35rem !important;
    }

    .st-key-topbar_actions > [data-testid="stLayoutWrapper"]
    > [data-testid="stHorizontalBlock"] > [data-testid="stColumn"]:nth-child(4) {
        flex:1 1 auto !important;
        width:auto !important;
        display:flex !important;
        justify-content:flex-end !important;
    }

    .st-key-topbar_navigation,
    .st-key-topbar_mode,
    .st-key-topbar_profile_slot,
    .st-key-topbar_navigation > [data-testid="stLayoutWrapper"],
    .st-key-topbar_mode > [data-testid="stLayoutWrapper"],
    .st-key-topbar_profile_slot > [data-testid="stLayoutWrapper"] {
        display:flex !important;
        align-items:center !important;
        height:auto !important;
        margin:0 !important;
        padding:0 !important;
    }

    .st-key-notebook_topbar > [data-testid="stLayoutWrapper"]
    > [data-testid="stHorizontalBlock"] > [data-testid="stColumn"]:last-child
    .st-key-topbar_profile_slot div[data-testid="stPopover"] button {
        width:2.65rem;
        min-width:2.65rem;
        padding:0;
        border-color:transparent !important;
        background:transparent !important;
    }

    .st-key-open-settings div[data-testid="stButton"] button {
        width:2.65rem;
        min-width:2.65rem;
        padding:0;
        border:0 !important;
        background:transparent !important;
        box-shadow:none !important;
    }

    .st-key-open-settings div[data-testid="stButton"] button p {
        position:absolute;
        width:1px;
        height:1px;
        padding:0;
        overflow:hidden;
        clip:rect(0,0,0,0);
        white-space:nowrap;
        border:0;
    }

    .st-key-sources-help div[data-testid="stButton"] button {
        width:2.1rem;
        min-width:2.1rem;
        min-height:2.1rem;
        padding:0;
        border:0 !important;
        color:var(--cd-muted) !important;
        background:transparent !important;
    }

    .st-key-sources-help div[data-testid="stButton"] button p,
    [class*="st-key-locked-source-"] div[data-testid="stButton"] button p {
        display:none;
    }

    [class*="st-key-locked-source-"] div[data-testid="stButton"] button {
        width:2rem;
        min-width:2rem;
        min-height:2rem;
        padding:0;
        border:0 !important;
        color:var(--cd-muted) !important;
        background:transparent !important;
        opacity:1 !important;
    }

    #MainMenu,
    footer {
        display:none !important;
    }

    /* Brand left, title centered, actions right. */
    .st-key-notebook_topbar > [data-testid="stLayoutWrapper"]
    > [data-testid="stHorizontalBlock"] {
        display:grid !important;
        grid-template-columns:minmax(12rem,16rem) minmax(10rem,1fr) minmax(17rem,max-content);
        column-gap:.72rem !important;
        align-items:center !important;
    }

    .st-key-topbar_actions,
    .st-key-topbar_actions > [data-testid="stLayoutWrapper"],
    .st-key-topbar_actions > [data-testid="stLayoutWrapper"]
    > [data-testid="stHorizontalBlock"] {
        align-items:center !important;
    }

    .st-key-notebook_topbar > [data-testid="stLayoutWrapper"]
    > [data-testid="stHorizontalBlock"] > [data-testid="stColumn"] {
        width:auto !important;
        min-width:0 !important;
        flex:none !important;
    }

    .st-key-topbar_navigation,
    .st-key-topbar_navigation > [data-testid="stLayoutWrapper"],
    .st-key-topbar_navigation > [data-testid="stLayoutWrapper"]
    > [data-testid="stHorizontalBlock"],
    .st-key-topbar_mode {
        width:max-content !important;
    }

    @media (max-width:1050px) {
        .block-container {
            padding:0 .7rem .7rem;
            background:var(--cd-bg);
        }

        .st-key-notebook_topbar {
            height:4.6rem;
            min-height:4.6rem;
            flex-basis:4.6rem;
            margin:0 -.7rem;
            padding:0 .7rem;
        }

        .st-key-notebook_topbar > [data-testid="stLayoutWrapper"]
        > [data-testid="stHorizontalBlock"] {
            display:grid;
            grid-template-columns:2.8rem minmax(0,1fr) max-content;
            justify-content:stretch;
            gap:.65rem;
        }

        .st-key-notebook_topbar > [data-testid="stLayoutWrapper"]
        > [data-testid="stHorizontalBlock"] > [data-testid="stColumn"] {
            width:auto !important;
            min-width:0 !important;
            flex:none !important;
        }

        .brand-lockup > div:last-child {
            display:none;
        }

        .brand-mark {
            width:2.5rem;
            height:2.5rem;
            border-radius:.62rem;
            font-size:1.05rem;
        }

        .st-key-topbar_navigation div[data-testid="stButton"] button p {
            font-size:.86rem;
        }

        .st-key-notebook_topbar [data-baseweb="select"] > div {
            width:100%;
            min-width:0;
        }

        .st-key-topbar_mode [data-testid="stPopover"] button {
            min-width:4.4rem !important;
            max-width:5.2rem !important;
            border:1px solid var(--cd-border) !important;
            border-radius:.75rem !important;
        }

        .st-key-mobile_panel {
            display:block;
            width:100%;
            flex:0 0 auto;
            margin:.65rem 0 .7rem;
        }

        .st-key-mobile_panel [data-testid="stRadio"] {
            width:100%;
        }

        .st-key-mobile_panel [data-testid="stRadio"] > div {
            width:100%;
            display:grid;
            grid-template-columns:repeat(3,1fr);
            gap:.2rem;
            padding:.25rem;
            border:1px solid var(--cd-border);
            border-radius:.75rem;
            background:var(--cd-surface-muted);
        }

        .st-key-mobile_panel [role="radiogroup"] {
            width:100%;
            display:grid;
            grid-template-columns:repeat(3,minmax(0,1fr));
            gap:.2rem;
            padding:.24rem;
        }

        .st-key-mobile_panel label[data-testid="stRadioOption"] {
            min-height:2.55rem;
            display:flex;
            align-items:center;
            justify-content:center;
            margin:0 !important;
            padding:.35rem .25rem;
            border-radius:.55rem;
            color:var(--cd-muted);
            background:transparent;
        }

        .st-key-mobile_panel label[data-testid="stRadioOption"][data-selected="true"] {
            color:var(--cd-accent);
            background:var(--cd-accent-soft);
        }

        .st-key-mobile_panel label[data-testid="stRadioOption"]
        > div > div > div:first-child {
            display:none !important;
        }

        .st-key-mobile_panel label[data-testid="stRadioOption"] p {
            color:inherit !important;
            -webkit-text-fill-color:currentColor !important;
        }

        .st-key-notebook_workspace {
            border:1px solid var(--cd-border);
            border-radius:.85rem;
        }

        .st-key-notebook_workspace > [data-testid="stLayoutWrapper"]
        > [data-testid="stHorizontalBlock"] {
            display:block;
        }

        .st-key-notebook_workspace > [data-testid="stLayoutWrapper"]
        > [data-testid="stHorizontalBlock"] > [data-testid="stColumn"] {
            width:100% !important;
            height:100%;
            min-width:0 !important;
            flex:none !important;
        }

        .st-key-notebook_workspace > [data-testid="stLayoutWrapper"]
        > [data-testid="stHorizontalBlock"] > [data-testid="stColumn"]:has(.st-key-sources_panel),
        .st-key-notebook_workspace > [data-testid="stLayoutWrapper"]
        > [data-testid="stHorizontalBlock"] > [data-testid="stColumn"]:has(.st-key-chat_panel),
        .st-key-notebook_workspace > [data-testid="stLayoutWrapper"]
        > [data-testid="stHorizontalBlock"] > [data-testid="stColumn"]:has(.st-key-studio_panel) {
            display:none;
        }

        body:has(.st-key-mobile_panel label:nth-child(1) input:checked)
        .st-key-notebook_workspace > [data-testid="stLayoutWrapper"]
        > [data-testid="stHorizontalBlock"] > [data-testid="stColumn"]:has(.st-key-sources_panel) {
            display:block;
        }

        body:has(.st-key-mobile_panel label:nth-child(2) input:checked)
        .st-key-notebook_workspace > [data-testid="stLayoutWrapper"]
        > [data-testid="stHorizontalBlock"] > [data-testid="stColumn"]:has(.st-key-chat_panel) {
            display:block;
        }

        body:has(.st-key-mobile_panel label:nth-child(3) input:checked)
        .st-key-notebook_workspace > [data-testid="stLayoutWrapper"]
        > [data-testid="stHorizontalBlock"] > [data-testid="stColumn"]:has(.st-key-studio_panel) {
            display:block;
        }

        .cd-col-resize-handle,
        [class*="st-key-collapse-studio"],
        [class*="st-key-collapse-sources"],
        [class*="st-key-expand-studio"],
        [class*="st-key-expand-sources"],
        .st-key-studio_rail,
        .st-key-sources_rail {
            display:none !important;
        }

        .st-key-studio_panel,
        .st-key-chat_panel,
        .st-key-sources_panel {
            height:100%;
            padding:1.2rem 1rem 1rem;
            border:0;
        }

        [data-testid="stChatMessage"]:has([aria-label="Chat message from user"]) {
            max-width:88%;
        }

        .st-key-chat_composer [data-testid="stChatInput"] {
            min-height:4.15rem !important;
            max-height:9rem !important;
        }

        .st-key-chat_composer [data-testid="stChatInput"] > div {
            min-height:4.15rem !important;
        }

        .st-key-chat_composer [data-testid="stChatInput"] textarea,
        .st-key-chat_composer [data-testid="stChatInputTextArea"] {
            min-height:calc(1em * 1.45) !important;
            max-height:calc(1em * 1.45 * 3) !important;
            padding:.1rem 0 !important;
        }

        .st-key-composer_model_slot [data-testid="stPopover"] {
            margin-left:10px !important;
        }
    }

    @media (max-width:520px) {
        .block-container {
            padding:0 .55rem .55rem;
        }

        .st-key-notebook_topbar {
            margin:0 -.55rem;
            padding:0 .55rem;
        }

        .st-key-notebook_topbar > [data-testid="stLayoutWrapper"]
        > [data-testid="stHorizontalBlock"] {
            grid-template-columns:2.55rem minmax(0,1fr) max-content;
            gap:.48rem;
        }

        .st-key-notebook_topbar div[data-testid="stButton"] button,
        .st-key-notebook_topbar div[data-testid="stPopover"] button {
            min-height:2.55rem;
        }

        .st-key-topbar_navigation div[data-testid="stButton"] button {
            width:2.55rem !important;
            min-width:2.55rem;
            padding:0 !important;
        }

        .st-key-topbar_navigation div[data-testid="stButton"] button p {
            font-size:0 !important;
        }

        .st-key-mobile_panel label p {
            font-size:.76rem;
        }

        .st-key-studio_panel,
        .st-key-chat_panel,
        .st-key-sources_panel {
            padding:1rem .8rem .8rem;
        }

        [class*="st-key-journey_stage_"]:has(.journey-state.current) {
            min-height:11rem;
        }
    }
</style>
"""


def inject_template_css() -> None:
    """Inject the active template stylesheet into the Streamlit page."""
    st.markdown(TEMPLATE_UI_CSS, unsafe_allow_html=True)


def render_theme_css() -> None:
    light_tokens = """
        color-scheme:light;
        --cd-bg:#F3F5F7;--cd-surface:#FFFFFF;--cd-surface-muted:#F7F9FA;
        --cd-text:#15202B;--cd-muted:#5B6B7C;--cd-border:#D5DCE3;
        --cd-panel:#EEF1F4;--cd-subtle:#E8ECF0;--cd-accent-soft:#E6F5F3;
        --cd-accent:#0F766E;--cd-accent-hover:#0D9488;--cd-success:#15803D;
        --cd-shadow:0 8px 24px rgba(21,32,43,.08);
    """
    dark_tokens = """
        color-scheme:dark;
        --cd-bg:#0F1419;--cd-surface:#171C22;--cd-surface-muted:#1C232B;
        --cd-text:#F2F5F7;--cd-muted:#9AA8B5;--cd-border:#2A343E;
        --cd-panel:#171C22;--cd-subtle:#1C232B;--cd-accent-soft:#14352F;
        --cd-accent:#2DD4BF;--cd-accent-hover:#5EEAD4;--cd-success:#4ADE80;
        --cd-shadow:0 18px 50px rgba(0,0,0,.34);
    """
    mode = st.session_state.get("appearance", "System")
    tokens = dark_tokens if mode == "Dark" else light_tokens
    portal_background = "#171C22" if mode == "Dark" else "#FFFFFF"
    portal_text = "#F2F5F7" if mode == "Dark" else "#15202B"
    portal_muted = "#9AA8B5" if mode == "Dark" else "#5B6B7C"
    system_portal_dark = (
        """
        @media (prefers-color-scheme:dark) {
            [data-testid="stPopoverBody"],
            [data-testid="stPopoverBody"] > div {
                background:#171C22 !important;
            }
            [data-testid="stPopoverBody"] p,
            [data-testid="stPopoverBody"] h3,
            [data-testid="stPopoverBody"] label {
                color:#F2F5F7 !important;
                -webkit-text-fill-color:#F2F5F7 !important;
            }
            [data-testid="stPopoverBody"] [data-testid="stCaptionContainer"],
            [data-testid="stPopoverBody"] [data-testid="stCaptionContainer"] p {
                color:#9AA8B5 !important;
                -webkit-text-fill-color:#9AA8B5 !important;
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
            [data-testid="stChatInput"] textarea {{
                color:var(--cd-text) !important;
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
                opacity:1;
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
