# UI agent guide

## Purpose

The `ui/` package is the Streamlit presentation layer for Co-design Chatbot. It
renders notebooks, sources, discussion, thinking path, dialogs, and theme CSS.
It calls typed backend facades (`StudentStore`, `StudentChatEngine`,
`LocalApiClient`) but does not implement educational or persistence logic.

[`streamlit_app.py`](../streamlit_app.py) is the thin entrypoint: page config,
CSS injection, session init, top bar, workspace layout, and pending dialog
triggers.

## Read first

1. Root [`AGENTS.md`](../AGENTS.md) for safety and global architecture rules.
2. [`DESIGN.md`](../DESIGN.md) for product layout, density, and interaction principles.
3. [`ui/`](../ui/) module map below before editing a panel.
4. [`docs/IMPLEMENTATION_STATUS.md`](../docs/IMPLEMENTATION_STATUS.md) when UI work is part of a larger phase.

Backend architecture details live in
[`docs/LOCAL_DEMO_IMPLEMENTATION.md`](../docs/LOCAL_DEMO_IMPLEMENTATION.md).
Only read that for UI tasks that touch API migration or coaching flow.

## Module map

| Module | Responsibility |
|---|---|
| `constants.py` | Response languages and appearance modes |
| `components.py` | Shared HTML helpers for progress, empty states, review cards |
| `assets/template.css` | Static layout/component stylesheet (edit CSS here) |
| `theme.py` | Loads `assets/template.css`, `inject_template_css()`, dynamic `render_theme_css()` |
| `layout/` | Browser-side layout helpers (column resize, sources scroll, composer) |
| `runtime.py` | Cached `store`, `engine`, `course_material_sync()`, `local_api_client()`, `rerun()` |
| `session.py` | Session defaults, notebook create/select/delete, `save_journey()` |
| `topbar.py` | Brand, title, section switcher, Guidance, profile entry |
| `profile.py` | Compact settings popover (display name, appearance, language, help) |
| `workspace.py` | Mobile panel radio and three-column studio/chat/sources layout |
| `chat.py` | Message rendering, citations, composer, `handle_prompt()`, `render_chat_panel()` |
| `sources.py` | Source library with search/filter, add/viewer dialogs |
| `studio.py` | Thinking Path journey roadmap, review cards, pending transition UI |
| `notebooks.py` | Folder-free notebook library and actions dialog |
| `settings.py` | Preference persistence callbacks used by the profile popover |

Compatibility shims at `ui/column_resize.py`, `ui/sources_scroll.py`, and
`ui/composer_layout.py` re-export `ui.layout.*`. Prefer importing from
`ui.layout` (or `ui.layout.<module>`) in new code.

## Layout helpers (`ui/layout/`)

| Module | Responsibility |
|---|---|
| `column_resize.py` | Between-column drag handles and side-panel collapse widths |
| `sources_scroll.py` | Sources list scroll region sizing |
| `composer_layout.py` | Composer footer card / model-slot placement |

These modules inject small `components.html` scripts because Streamlit lacks
first-class APIs for those layout behaviours. Do not put educational logic here.

## Hard constraints

- **Presentation only.** Do not import SQLite drivers, LangChain, LangGraph,
  OpenAI/Ollama SDKs, or read/write the filesystem directly except through
  backend helpers already used in this package.
- **Import shared runtime from `ui.runtime` only.** Use `store`, `engine`,
  `local_api_client()`, and `course_material_sync()` from there — never from
  `streamlit_app.py`.
- **Preserve widget keys and dialog decorators.** Keep `@st.dialog` and
  `@st.fragment` on the functions that own them. Changing keys breaks session
  state and AppTest expectations.
- **Explicit CSS injection.** Call `inject_template_css()` from the entrypoint;
  do not auto-inject CSS on `ui.theme` import. Edit static styles in
  `ui/assets/template.css`, not by re-embedding large CSS strings in Python.
- **Avoid circular imports.** Typical flow: `runtime` → `session` → panels;
  `topbar` imports `notebooks` and `settings`; `workspace` imports panel modules.
- **No hidden stage controls.** Show coach recommendations and respect persisted
  transition state; do not add manual stage jump controls or HTML comment parsers.

## Entrypoint flow

```text
streamlit_app.py
  -> inject_template_css()
  -> initialize_session()
  -> sync_appearance_from_widget()
  -> render_theme_css()
  -> render_topbar()  -> model_id, reasoning_effort
  -> render_workspace(model_id, reasoning_effort)
  -> notebook_actions_dialog() if pending
```

## Common edit paths

**Panel layout or copy**

Edit the owning module (`chat.py`, `sources.py`, `studio.py`, etc.). Check
`DESIGN.md` for density and clutter rules.

**Theme or responsive CSS**

Edit `ui/assets/template.css` for static styles. Edit `theme.py` only for
Light/Dark/System token overrides in `render_theme_css()`. AppTest in
`tests/test_streamlit_ui.py` asserts many CSS strings from rendered output —
run UI tests after visual changes.

**Layout / scroll / composer DOM helpers**

Edit the matching module under `ui/layout/`.

**New dialog**

Add `@st.dialog` in the module that owns the feature. Import it from the
entrypoint or a parent panel if it must open on load.

**API vs legacy chat path**

`chat.py` branches on `local_api_enabled()`. Prefer the FastAPI coaching path
(`USE_LOCAL_API=true` via `scripts/start.sh`). The legacy `StudentChatEngine`
path remains for offline fallback during migration — do not add new stage or
vision behaviour only to the legacy path.

## Validation

```sh
.venv/bin/python -m pytest -q tests/test_streamlit_ui.py
PYTHONPYCACHEPREFIX=/private/tmp/co-design-pycache \
  .venv/bin/python -m compileall -q ui streamlit_app.py
```

For visual changes, also run Streamlit locally and check desktop and 390 px
widths with a clean browser console:

```sh
sh scripts/start.sh
```

If a test asserts text from a source file (not rendered output), update the
path when moving strings — e.g. `"Loading course materials…"` lives in
`sources.py`.

## Handoff

UI-only fixes usually do not need `IMPLEMENTATION_STATUS.md` updates unless
they complete a named phase. Larger UI migrations do. Defer to root
[`AGENTS.md`](../AGENTS.md) for the full handoff checklist.
