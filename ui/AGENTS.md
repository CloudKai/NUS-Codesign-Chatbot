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
| `auth/cookies.py` | Cookie helpers extracted from the login gate; `_cookie_value` remains a patch seam on `auth_gate` |
| `constants.py` | Response languages and appearance modes |
| `coach_welcome.py` | Seeded welcome copy and the progressive How Might We scaffold card (shown after the first useful Coach turn when FastAPI projects availability; hidden after a valid student HMW) |
| `components.py` | Shared HTML helpers for progress, empty states, review cards |
| `toasts.py` | Corner toast helper (timed slide-in; dismiss/timers live on the parent window; falls back to `st.toast`) |
| `assets/styles/` | Ordered static CSS partials (edit the matching component file) |
| `theme.py` | Loads `assets/styles/` in fixed order, `inject_template_css()`, dynamic `render_theme_css()` |
| `layout/` | Browser-side layout helpers (column resize, sources scroll, composer) |
| `runtime.py` | Compatibility alias for `services/runtime.py` (cached store/workspace/coach, `WorkspaceFacade`, coach helpers, rerun) |
| `session.py` | Session defaults (Quick coaching / `response_detail=short`), notebook create/select/delete, `save_journey()` |
| `rename.py` | Shared Enter-only rename forms, draft discard, select-all helper |
| `topbar.py` | Brand, title, section switcher, Guidance, profile entry |
| `profile.py` | Compact settings popover (display name, Coaching style Quick/Strict, appearance, logout) |
| `workspace.py` | Gemini mobile header (menu overlay / new chat / chat ⋮) and three-column nav/chat/studio layout |
| `chat.py` | Compatibility alias for `panels/chat.py` (messages, citations, composer, `handle_prompt()`) |
| `sources.py` | Compatibility alias for `panels/sources.py` (library, search/filter, add/viewer dialogs) |
| `studio.py` | Compatibility alias for `panels/studio.py` (five-phase Journey/Review, pending transitions). Review stage expanders remount when notebook or current stage changes; keys stay stable within a stage. |
| `panels/nav.py` | Gemini-style left chat rail: New chat, Search, Library, Recents rename/delete |
| `panels/search.py` | Center Search chats pane (substring match via `list_threads`) |
| `professor.py` | Lecturer Research/analytics workbench. Do not relocate. CSS lives in `assets/styles/70-professor.css`. |
| `notebooks.py` | Shared notebook helpers (`thread_overview`); legacy Your Notebooks dialog kept unused by the top bar |
| `settings.py` | Preference persistence callbacks used by the profile popover |

`ui.chat`, `ui.sources`, `ui.studio`, and `ui.runtime` replace themselves with
the owning implementation module so historical imports and monkeypatch targets
keep the same function objects.

Compatibility shims at `ui/column_resize.py`, `ui/sources_scroll.py`, and
`ui/composer_layout.py` re-export `ui.layout.*`. Prefer importing from
`ui.layout` (or `ui.layout.<module>`) in new code.

## Layout helpers (`ui/layout/`)

| Module | Responsibility |
|---|---|
| `column_resize.py` | Nav fixed widths, Library hide, Thinking Path rail, drag handles |
| `sources_scroll.py` | Sources list scroll region sizing |
| `chat_scroll.py` | Send snaps bottom; reply remount pins latest coach top unless scrolled away |
| `composer_layout.py` | Composer footer card / textarea sizing |

These modules inject small `components.html` scripts because Streamlit lacks
first-class APIs for those layout behaviours. Do not put educational logic here.
`ui/toasts.py` uses the same pattern for timed corner toasts and falls back to
`st.toast` if injection fails.

## Hard constraints

- **Presentation only.** Do not import SQLite drivers, LangChain, LangGraph,
  OpenAI SDKs, or read/write the filesystem directly except through
  backend helpers already used in this package.
- **Import shared runtime from `ui.runtime` only.** Use `store` (workspace
  facade), `local_api_client()`, coach helpers, `rerun_app()`,
  `rerun_fragment()`, `coach_turn_is_streaming()`, and
  `set_coach_turn_streaming()` from there — never from
  `streamlit_app.py`. When
  `USE_LOCAL_API=true`, `store` routes CRUD through the typed API; otherwise it
  uses in-process `WorkspaceService`. Student turns always use the typed coach
  path (API or in-process), not `StudentChatEngine`.
- **Rerun scope.** Use `rerun_fragment()` for panel-local updates inside an
  `@st.fragment` (Sources list, Journey preview toggles, Guidance Level,
  response language, display-name avatar). The chat composer lives in
  `_render_composer_submit_fragment` so a normal Send does not rebuild
  Journey, Deep Review, Sources, or chat history before FastAPI starts.
  After a successful persisted turn, always ``rerun_app()`` so
  authoritative history owns the completed bubbles. Use ``rerun_app()``
  when application-wide state changed (notebook switch,
  auth, coach ADVANCE / pending transition / Deep Review progress, composer
  uploads, revise, layout collapse, course-sync fragment remount, stage
  selection, **Appearance theme** — `render_theme_css()` only runs on a
  full script). Sources and Deep Review must not
  call `rerun_app()` while `coach_turn_is_streaming()` is true (a remount
  during `handle_prompt` stacks a second workspace). Do not keep a generic
  `rerun()` helper.
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
- **Coach wait UX.** While a turn is in flight, show an explicit thinking status
  (`st.status`) driven by early stream ``status`` events. Do not fake provider
  token streaming in the UI beyond what the API emits.
- **Edit via server revise only.** User-message Edit uses the in-bubble editor
  (8-row max, then scroll) and must call ``store.revise_message`` /
  ``POST .../messages/{id}/revise`` with a **stable** revise idempotency key for
  that edit attempt (reuse across provider-failure retries until success or
  abandon). The server creates an append-only conversation revision (later turns
  leave the active view but stay in revision history); never delete or rewrite
  history only in Streamlit session state. ``get_messages`` returns the active
  branch. Do not show a student-facing ``Conversation NN`` revision label in
  the chat panel (revision tracking stays internal). On revise failure, clear
  ``pending_edit`` (so the next rerun does not auto-resubmit), keep the stable
  revise idempotency key, restore the in-bubble draft, and require an explicit
  Send click to retry; never blank the panel.
- **Sources panel.** Order is My Sources → Lecture Notes → Readings. Course
  materials show a lock only (no checkboxes); Select all / indeterminate /
  none and Sort (Recent / Name) apply to personal uploads. Lecture Notes and
  Readings expanders default collapsed until the student opens them. Never show
  raw ``str(exc)`` for source upload/sync/rename/download failures — log the
  internal error and display a fixed student-safe message.
- **Thinking Path studio.** Never show raw ``str(exc)`` for stage-select or
  transition-confirm failures — log internals and show a fixed student-safe
  message.

## Entrypoint flow

```text
streamlit_app.py
  -> inject_template_css()
  -> initialize_session()
  -> sync_appearance_from_widget()
  -> render_theme_css()
  -> render_topbar()  -> model_id, reasoning_effort
  -> render_workspace(model_id, reasoning_effort)
  -> notebooks_dialog() from the Notebooks button, or while
     pending_notebook_actions / reopen_notebooks_dialog (inline actions;
     no nested Notebook Actions dialog)
```

## Common edit paths

**Panel layout or copy**

Edit the owning module (`ui/panels/chat.py`, `ui/panels/sources.py`,
`ui/panels/studio.py`, or `ui/professor.py`). Check `DESIGN.md` for density
and clutter rules.

**Theme or responsive CSS**

Edit the matching partial under `ui/assets/styles/` for static styles
(`00-foundations`, `10-workspace`, `20-studio`, `30-chat`, `40-sources`,
`50-dialogs-notebooks`, `60-profile-topbar`, `90-responsive`). Keep the
manifest order in `ui/theme.py`. Edit `theme.py` only for Light/Dark/System
token overrides in `render_theme_css()`. AppTest in
`tests/ui/test_streamlit_ui.py` and `tests/ui/test_theme_styles.py` assert assembled
CSS contracts — run UI tests after visual changes. Source-file assertions must
use `inspect.getfile` so they follow the panel aliases.

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
.venv/bin/python -m pytest -q tests/ui/test_streamlit_ui.py
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
`ui/panels/sources.py`.

## Handoff

UI-only fixes usually do not need `IMPLEMENTATION_STATUS.md` updates unless
they complete a named phase. Larger UI migrations do. Defer to root
[`AGENTS.md`](../AGENTS.md) for the full handoff checklist.
