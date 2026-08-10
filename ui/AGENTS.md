# UI agent guide

## Purpose

The `ui/` package is the Streamlit presentation layer for Co-design Chatbot. It
renders notebooks, sources, discussion, thinking path, dialogs, and theme CSS.
It calls the workspace facade (`store` from `ui.runtime`) and the typed coaching
helpers (`submit_coach_turn` / `stream_coach_turn_events`); it does not implement
educational or persistence logic and must not open SQLite or source files directly.

[`streamlit_app.py`](../streamlit_app.py) is the thin entrypoint: page config,
CSS injection, Cognito OIDC gate (`ui/auth_gate.py`), session init, top bar,
workspace layout, and pending dialog triggers. Unauthenticated visitors never
reach `initialize_session()` or protected notebook/source data.

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
| `auth_gate.py` | Signed-out shell, Cognito login dialog, logout helpers |
| `constants.py` | Response languages and appearance modes |
| `components.py` | Shared HTML helpers for progress, empty states, review cards |
| `toasts.py` | Corner toast helper (timed slide-in; falls back to `st.toast`) |
| `assets/styles/` | Ordered static CSS partials (edit the matching component file) |
| `theme.py` | Loads `assets/styles/` in fixed order, `inject_template_css()`, dynamic `render_theme_css()` |
| `layout/` | Browser-side layout helpers (column resize, sources scroll, composer) |
| `runtime.py` | Cached store/workspace/coach + `WorkspaceFacade`, `local_api_client()`, coach helpers, `rerun()` |
| `session.py` | Session defaults, notebook create/select/delete, `save_journey()` |
| `rename.py` | Shared Enter-only rename forms, draft discard, select-all helper |
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
| `composer_layout.py` | Composer footer card / textarea sizing |

These modules inject small `components.html` scripts because Streamlit lacks
first-class APIs for those layout behaviours. Do not put educational logic here.
`ui/toasts.py` uses the same pattern for timed corner toasts and falls back to
`st.toast` if injection fails.

## Hard constraints

- **Presentation only.** Do not import SQLite drivers, LangChain, LangGraph,
  OpenAI/Ollama SDKs, or read/write the filesystem directly except through
  backend helpers already used in this package.
- **Import shared runtime from `ui.runtime` only.** Use `store` (workspace
  facade), `local_api_client()`, coach helpers, and `rerun()` from there — never
  from `streamlit_app.py`. When `USE_LOCAL_API=true`, `store` routes CRUD through
  the typed API; otherwise it uses in-process `WorkspaceService`. Student turns
  always use the typed coach path (API or in-process), not `StudentChatEngine`.
- **Preserve widget keys and dialog decorators.** Keep `@st.dialog` and
  `@st.fragment` on the functions that own them. Changing keys breaks session
  state and AppTest expectations.
- **Explicit CSS injection.** Call `inject_template_css()` from the entrypoint;
  do not auto-inject CSS on `ui.theme` import. Edit static styles in the matching
  file under `ui/assets/styles/` (fixed cascade order in `ui/theme.py`), not by
  re-embedding large CSS strings in Python.
- **Avoid circular imports.** Typical flow: `runtime` → `session` → panels;
  `topbar` imports `notebooks` and `settings`; `workspace` imports panel modules.
- **No hidden stage controls.** Show coach recommendations and respect persisted
  transition state; do not use HTML comment parsers. Audited Journey stage
  selection is allowed only when ``STUDENT_STAGE_SELECTION=true`` (server
  ``select-stage`` API); never let the client spoof ``current_stage`` on coach
  turns.

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
  -> else notebooks_dialog() if reopen after actions dismiss/delete
```

## Common edit paths

**Panel layout or copy**

Edit the owning module (`chat.py`, `sources.py`, `studio.py`, etc.). Check
`DESIGN.md` for density and clutter rules.

**Theme or responsive CSS**

Edit the matching partial under `ui/assets/styles/` for static styles
(`00-foundations`, `10-workspace`, `20-studio`, `30-chat`, `40-sources`,
`50-dialogs-notebooks`, `60-profile-topbar`, `90-responsive`). Keep the
manifest order in `ui/theme.py`. Edit `theme.py` only for Light/Dark/System
token overrides in `render_theme_css()`. AppTest in
`tests/test_streamlit_ui.py` and `tests/test_theme_styles.py` assert assembled
CSS contracts — run UI tests after visual changes.

**Layout / scroll / composer DOM helpers**

Edit the matching module under `ui/layout/`.

**New dialog**

Add `@st.dialog` in the module that owns the feature. Import it from the
entrypoint or a parent panel if it must open on load.

**API vs in-process coach path**

`chat.py` always submits typed `CoachRequest` turns. Prefer
`USE_LOCAL_API=true` via `scripts/start.sh` (readiness-gated). The in-process
`CoachApplicationService` path remains for Streamlit-only runs. Keep
`StudentChatEngine` only for legacy unit tests in `backend/chat_service.py`.

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
