# Implementation status

## Current phase

**Single-EC2 production Docker deployment preparation complete**

The unchanged local launcher still binds FastAPI and Streamlit to loopback.
Production now has a Python 3.12 app image, supervised dual-process entrypoint,
two-service Compose stack, and Caddy HTTPS routing for
``cde2300chatbot.duckdns.org``. Only Caddy publishes host ports 80/443; app
ports 8000/8501 stay on the Compose network.

### Behavior implemented

- Added ``Dockerfile``, ``.dockerignore``, ``compose.yaml``, ``Caddyfile``, and
  ``scripts/start_prod.sh``.
- The production entrypoint starts readiness-gated FastAPI and Streamlit on
  ``0.0.0.0``, monitors both required processes, and terminates both on stop.
- Compose loads private environment values at runtime, bind-mounts Streamlit
  secrets read-only, bind-mounts ``./data`` for durable SQLite/uploads/workspaces,
  and persists Caddy certificate/config state in named volumes. Bind sources
  must already exist; Docker cannot silently create root-owned directories.
- Caddy preserves ``/api`` while routing ``/api/*`` to ``app:8000`` and all
  other requests (including Streamlit WebSockets/OIDC callback) to ``app:8501``.
  API response flushing preserves public NDJSON streaming.
- Production startup refuses a missing/unwritable data mount or a missing,
  unreadable, or directory-valued Streamlit secrets mount with a clear error.
- Added a backward-compatible ``CO_DESIGN_PUBLIC_API_URL`` so server-side API
  calls stay on container loopback while browser logout uses the public HTTPS
  origin. Local defaults and ``scripts/start.sh`` behavior are unchanged.
- Course inputs under ``lecture_notes/`` remain in the image; private ``data/``,
  ``.env``, secrets, virtual environments, and caches are excluded from builds.

### Files changed

- Added: ``Dockerfile``, ``.dockerignore``, ``compose.yaml``, ``Caddyfile``,
  ``scripts/start_prod.sh``, ``tests/test_deployment_config.py``.
- Updated: ``.env.example``, ``README.md``, ``backend/api.py``,
  ``backend/settings.py``, ``ui/auth_gate.py``, ``tests/test_auth_gate.py``,
  ``scripts/AGENTS.md``, this status file.

### Commands run and results

- ``docker compose config --quiet`` → passed.
- ``sh -n scripts/start.sh scripts/start_prod.sh scripts/build.sh`` → passed.
- Deployment/auth selection → **33 passed**.
- Full deterministic mock suite → **157 passed**, one existing
  Starlette/httpx deprecation warning.
- ``compileall -q backend ui streamlit_app.py tests`` → passed.
- IDE diagnostics and ``git diff --check`` → passed.
- Docker image build could not run because the local Docker daemon was not
  running. Caddy binary validation was unavailable; Caddy routing is covered by
  static tests and Compose config validation.
- Ruff is configured but not installed, so no Ruff result is claimed.

### Migration / compatibility / rollback

- No schema or data migration. ``./data`` remains the persistence boundary,
  covering ``co_design.sqlite3`` (including SQLite WAL sidecars), ``files/``,
  and ``workspaces/``. Container replacement does not remove this host path.
- The app runs as uid/gid ``1000:1000``. Linux/EC2 operators must pre-create
  and assign the data tree and secrets file to that identity.
- Existing ``scripts/start.sh`` and its ``127.0.0.1`` bindings were not changed.
- Rollback removes the production deployment files and public-URL setting;
  no database, upload, private environment, or private Streamlit secret was
  modified.

### Risks / blockers

- FastAPI has no authenticated request boundary. Publicly routing ``/api/*`` is
  not safe for sensitive production student data; authentication/authorization
  is intentionally deferred because this phase forbids changing auth semantics.
- Existing database source rows store absolute paths. Data first created outside
  the container may need a separately tested path-portability migration before
  transfer; rebuilds of data first created at ``/app/data`` remain stable.
- EC2/DuckDNS/Cognito settings and live HTTPS were not changed or tested in this
  preparation-only phase.

### Next exact action

- Start Docker locally or on a staging EC2 host, run ``docker compose build``,
  then verify mock-mode startup, internal health checks, public HTTPS routing,
  Cognito callback/logout, source upload/retrieval, and restart persistence.

## Previous completed work

**Cognito login redesign complete — same-tab local logout fixed**

Streamlit-native Amazon Cognito authorization-code login remains the identity
boundary. The signed-out gate now matches the product design, explains course
research use, and states clearly that chatbot work is never graded. Cognito
subjects use owner-scoped in-process application services instead of the
unauthenticated single-owner local API. Logout stays in the current browser tab,
uses a fixed FastAPI callback to expire Streamlit's HttpOnly cookies, and stops
at the app's signed-out gate.

## Latest completed work (Cognito review and redesign)

### Behavior implemented

- Unauthenticated and malformed-identity paths stop before notebook/session
  initialization; logged-in identities without ``sub`` are cleared.
- ``ui/auth_gate.py``: compact branded dialog, Cognito-managed account CTA,
  student-safe configuration error, grade/research notice, strict logout URLs.
- ``ui/assets/styles/55-auth.css``: token-based desktop and 390 px auth layout.
- Login remains Streamlit-native authorization code with PKCE when advertised;
  access/ID tokens are not exposed to app UI or logs.
- ``backend/auth_profiles.py`` + ``StudentStore.upsert_cognito_user``: match by
  ``cognitoSub``, default role ``student``, preserve lecturer/admin, converge
  safely on concurrent first-login inserts.
- Non-destructive SQLite columns: ``cognitoSub``, ``email``, ``displayName``,
  ``role``, ``updatedAt``, ``lastLoginAt``.
- Cognito users no longer route persistence through FastAPI's shared
  ``local-student`` store; stage confirmation works on either application path.
- Same-tab logout: the profile uses a regular button rather than
  ``st.link_button`` (which opens an external URL in a second tab). The local
  ``/api/v1/auth/logout/callback`` expires Streamlit auth cookies with matching
  attributes and redirects only to the configured ``CO_DESIGN_UI_URL`` gate.
- Logout never calls ``st.logout()`` because Streamlit sends Cognito's
  ``/logout`` endpoint incompatible OIDC parameters, producing Cognito's
  “Invalid request” page.
- Secrets example now uses placeholders and documents the exact callback,
  scopes, sign-out callback, and Streamlit session limitation.

### Files changed

- ``streamlit_app.py``, ``ui/auth_gate.py``, ``ui/profile.py``, ``ui/runtime.py``,
  ``ui/studio.py``, ``ui/theme.py``, ``ui/assets/styles/55-auth.css``
- ``backend/auth_profiles.py``, ``backend/student_store.py``,
  ``backend/learning_service.py``, ``backend/api.py``, ``backend/settings.py``
- ``requirements.txt``, ``.gitignore``, ``.streamlit/secrets.toml.example``
- ``tests/conftest.py``, ``tests/test_auth_gate.py``,
  ``tests/test_runtime_auth.py``, related API/learning/UI tests
- ``README.md``, ``DESIGN.md``, ``docs/IMPLEMENTATION_STATUS.md``

### Commands run and results

- Focused auth/API/UI regression selection → **67 passed**
- Full suite: ``.venv/bin/python -m pytest -q`` → **150 passed**
- ``compileall -q backend ui streamlit_app.py tests`` → passed
- ``sh -n scripts/start.sh`` and ``git diff --check`` → passed
- Browser: signed-in app + logout initiation checked; redesigned gate checked at
  desktop and 390 px with no horizontal overflow.
- Latest logout regression selection → **13 passed**; restarted API/UI and
  confirmed the signed-out gate remained stable with no delayed AWS redirect.

### Migration / compatibility / rollback

- Non-destructive ``ALTER TABLE`` / unique index on ``users``.
- Existing ``local-student`` notebooks are not auto-attached to Cognito users.
- Cognito sessions use owner-scoped in-process services until FastAPI gets a
  verified authenticated-owner boundary; local API contract tests remain.
- Rollback: revert the auth gate/owner binding and logout callback code. No
  existing notebook, source, upload, or database row is deleted.

### Risks / blockers

- Streamlit 1.60 hard-codes a 30-day signed HttpOnly identity cookie and does
  not retain Cognito refresh tokens. Refresh-token rotation and a configurable
  app-cookie lifetime cannot be implemented without replacing native auth.
- Local logout deliberately does not clear Cognito's hosted session. A later
  sign-in may therefore use Cognito SSO without asking for credentials again.
- Cognito Managed Login owns signup, confirmation, password reset, MFA, and
  account-enumeration-safe messages; these require AWS configuration/manual QA.

### Next exact action

- Manually smoke one complete sign-in → same-tab logout → sign-in cycle, then
  decide separately whether clearing the hosted Cognito SSO session is required.

## Previous phase

**UI stylesheet split complete — stop for review**

Split the monolithic ``ui/assets/template.css`` into ordered component
partials under ``ui/assets/styles/``. ``ui/theme.py`` concatenates them in a
fixed cascade order into the same single ``<style>`` injection. No schema,
API, or educational-behavior changes. Private `.env` was not modified.

## Latest completed work (stylesheet split)

### Behavior implemented

- Static CSS now lives in eight ordered partials:
  ``00-foundations``, ``10-workspace``, ``20-studio``, ``30-chat``,
  ``40-sources``, ``50-dialogs-notebooks``, ``60-profile-topbar``,
  ``90-responsive``.
- ``ui/theme.py`` loads every partial, caches on per-file
  ``(name, mtime_ns, size)`` signature, and still injects one ``<style>``
  block.
- UI tests assert the assembled stylesheet via ``_template_stylesheet()``;
  ``tests/test_theme_styles.py`` covers manifest order and markers.

### Files changed

- Added ``ui/assets/styles/*.css``; removed ``ui/assets/template.css``
- ``ui/theme.py``, ``ui/assets/__init__.py``, ``ui/AGENTS.md``, ``DESIGN.md``
- ``ui/rename.py``, ``ui/chat.py``, ``ui/layout/user_message_edit_layout.py``
- ``tests/test_theme_styles.py``, ``tests/test_streamlit_ui.py``,
  ``tests/AGENTS.md``, ``docs/IMPLEMENTATION_STATUS.md``

### Commands run and results

- Focused: ``.venv/bin/python -m pytest -q tests/test_theme_styles.py tests/test_streamlit_ui.py -k 'theme or language_theme or rename_and_icon or assembled'`` → **4 passed**
- Full: ``.venv/bin/python -m pytest -q`` → **113 passed**
- ``PYTHONPYCACHEPREFIX=/private/tmp/co-design-pycache .venv/bin/python -m compileall -q backend ui streamlit_app.py`` → ok
- Live Streamlit at ``http://127.0.0.1:8501/``: assembled partial markers present in injected CSS (including ``foundations stylesheet``); top bar, chat composer, Sources/Journey structure rendered.

### Migration / compatibility / rollback

- No data migration. Browser still receives one concatenated stylesheet.
- Rollback: restore ``ui/assets/template.css`` and the previous single-file
  loader in ``ui/theme.py``, or concatenate the partials back into one file
  in the same order.

### Risks / blockers

- Cascade depends on manifest order in ``ui/theme.py``; reordering partials
  can change override winners without a Python failure.

### Next exact action

- **Stop for review.** Stylesheet split is complete; no further action required
  for this phase unless a visual regression is reported.

## Previous phase

**Phase 6 complete (streaming, checkpoints, observability, legacy retirement)**

Phases 1–5 covered UI rename/a11y, safe defaults, backend integrity, test
isolation, and CRUD behind the typed API. Phase 6 added readiness polling,
request IDs, NDJSON coach streaming, multi-step LangGraph with inspectable
checkpoints, retired ``StudentChatEngine`` for student turns, and removed the
dead composer model picker. Private `.env` was not modified.

## Completed

- Locked coaching to **GPT-5.6 Luna** with **low** reasoning: removed the
  composer model picker, collapsed the model registry to one entry, and set
  OpenAI coach calls to `gpt-5.6-luna` / `low`.
- Fixed Learning Path advancement for everyday startup: `scripts/start.sh`
  starts FastAPI + Streamlit with `USE_LOCAL_API=true`.
  Legacy Streamlit-only chat never mutated the journey; that was why the
  progress bar stayed on Focus.
- Hardened OpenAI structured coaching output (`additionalProperties: false`
  schema, stage coercion, clearer Focus advance rule) and verified a live
  Focus→Evidence auto-advance with Luna low.
- Added the durable `AGENTS.md` rules and the authoritative local architecture
  specification in `docs/LOCAL_DEMO_IMPLEMENTATION.md`.
- Added typed domain contracts for educational assessments, source citations,
  coaching turns, and pending phase transitions.
- Added repository adapters, confirmation-gated learning progression,
  deterministic mock provider, Ollama/OpenAI provider ports, and one
  inspectable LangGraph workflow wrapper.
- Added FastAPI `/api/v1` health, coaching-turn, learning-state,
  pending-transition, and transition-resolution endpoints plus a typed client.
- Added the additive SQLite `phase_transitions` table; existing rows are not
  converted or deleted.
- Added `scripts/start.sh`, `.env.example`, and local demo setup
  documentation.
- Removed hidden HTML stage-control markers and legacy automatic progression.
  Streamlit now shows a coach recommendation only after one is persisted, then
  requires the student's confirm/reject decision.
- Added a feature-gated Streamlit API path with `USE_LOCAL_API=true`; the
  legacy direct path remains available while source/notebook CRUD is migrated.
- Added a conversational coach greeting for empty notebooks and removed the
  generic OpenAI-knowledge status strip when no sources are selected.
- Made the deterministic local demonstration history-aware: it gives tailored
  guidance on the first stage contribution, recommends a confirmation-gated
  transition after the follow-up, and never presents that turn-based behavior
  as semantic model evaluation.
- Added recent canonical history and non-repetitive coaching requirements to
  the OpenAI provider prompt while retaining structured stage decisions.
- Repository defaults use confirmation mode (`AUTO_ADVANCE_STAGES=false`).
  Audited auto-advance (`AUTO_ADVANCE_STAGES=true`) remains an explicit local
  override that still persists a transition row.
- Added the shared `lecture_notes/` drop folder. Supported files are
  safely copied into each active notebook, selected, refreshed on change,
  removed when the folder file disappears, and exposed as stable citation
  chips in the local coaching workflow.
- Grouped instructor-managed PDFs into locked **Lecture Notes** and **Readings**
  source folders. The UI exposes selection and preview only, while repository
  enforcement blocks interactive deletion and keeps synchronizer refreshes safe.
  A separate 50 MB trusted-course-file limit covers compressed lecture PDFs
  without increasing the 10 MB student-upload limit. New notebooks keep Sources
  open so course-material import can start immediately; sync runs quietly in
  the background without re-compressing shared lecture files.
- Student uploads stored through ``save_uploads`` (Sources Add, chat attachments)
  are compressed when safe. PDFs keep extractable text; images are downscaled.
  Lecture-note sync copies prepared folder files without recompression.
  Sources **Add** is a compact file picker in the original header spot: choose
  files and they import immediately, with no dialog. Upload dedupe is scoped to
  the current picker generation (claim → import → reset), and failures clear the
  picker so the 1s Sources fragment does not retry forever.
- Isolated short-lived corner toasts in ``ui/toasts.py`` (new-notebook
  ``Course materials are loading.`` notice). Presentation HTML helpers stay in
  ``ui/components.py``.
- Replaced automatic-stage movement announcements with the next stage heading
  and one or two topic-specific coaching questions. Provider prompts use the
  selected course context; deterministic mock/offline mode includes a focused
  fallback for older-adult and other student topics.
  Older persisted responses receive the same presentation through a read-only
  compatibility adapter; canonical chat history is not rewritten.
- Simplified the notebook workspace header and Sources panel: notebook names are
  now editable inline, the response-detail control is labelled `Mode`, and the
  Setting dialog contains only language, appearance, and model selection.
- Added deterministic concise notebook-title generation from the first student
  contribution and the structured coach summary. Recognized legacy prompt-based
  titles are shortened on view without changing manually named notebooks.
- Removed contribution-restatement boilerplate such as `You're exploring` from
  both new provider instructions and the display of existing persisted replies.
- Removed the first-source promotion, sync caption, top-bar New action, pencil
  edit action, mode guide, Assignment context, and Notebook details from the
  default interface. Lecture Notes and Readings remain visible source groups.
- Kept the Sources title, contextual help, and Add action aligned in one row at
  desktop and 390 px. The help text now explains that selected materials
  personalize and ground coaching responses.
- Removed the selected-source status strip from the conversation so the
  scrollable chat log receives the full available panel height. A single source
  remains an inline citation; two or more citations collapse into one
  `Sources used (N)` disclosure with all source-viewer actions preserved.
- Reduced top-bar chrome by making Notebooks and Setting borderless icon-only
  actions with accessible hover help. The editable notebook title and its input
  outline are hidden at rest, then revealed on hover or keyboard/mouse focus;
  Streamlit's character counter stays hidden during editing.
- Tightened the Sources header so its help action sits directly beside the
  heading and the source selector begins immediately below the divider. Renamed
  the response control to `Guidance`, presenting the existing persisted
  `short`/`long` values as compact `Quick`/`Complex` choices without a data change.
- Restored the editable notebook title as permanently visible text in the top
  bar. Notebooks now shows its Material notebook icon and label in a content-fit,
  borderless action; Setting remains a compact icon-only action. Both controls
  keep their behavior without an outlined selection container.
- Phase 1: shared Enter-only rename + a11y for Settings, Source actions, and
  rail collapse/expand.
- Phase 2: validation-only `scripts/build.sh`; `init_db.py` refuses existing DB
  without `--force`; repository defaults mock + confirmation; test suite clears
  `OPENAI_API_KEY`; all configured data paths resolve via `_project_path`.
- Phase 3: API coaching turns reject spoofed stage/history/sources/images;
  domain validates known stages; confirmations apply journey + transition status
  atomically; provider outages return HTTP 503 with request/thread logging.
- Phase 4: per-test isolated data dirs; `LocalApiClient` session injection;
  API-mode AppTest (confirmation + auto-advance) plus legacy fallback;
  all-six-stage / stale / restart / isolation tests; `.github/workflows/mock-ci.yml`.
- Phase 5: notebook/message/source/preference CRUD API; `WorkspaceService` +
  `WorkspaceFacade`; source content endpoint; UI no longer reads source paths.

## Validation evidence

- Historical browser and feature acceptance notes remain for continuity; the
  latest automated counts are under Phase 1 / Phase 2 evidence.
- `sh -n scripts/start.sh` and `sh -n scripts/build.sh` passed.
- Private interactive `.env` may still use OpenAI + auto-advance; repository
  defaults and automated tests use mock + confirmation.

## Data and migration state

- Existing SQLite data and local uploads remain in ignored data paths.
- No schema migration is required for Phase 2.
- `scripts/init_db.py` no longer runs from `build.sh`; explicit `--database` or
  `--force` is required to touch an existing file.
- Private `.env` was left unchanged.

## Risks and open questions

- The project baseline remains mostly untracked; no Git commit was created.
- Private `.env` may still enable OpenAI / auto-advance; that is intentional and
  out of repository defaults.
- The Ollama provider still needs live host validation.
- Lecture-folder retrieval currently uses the bounded selected-source context
  path; vector/embedding retrieval remains a later provider-adapter phase.
- Source, notebook, and folder CRUD still use the existing direct Streamlit
  store calls; only coaching turns and transition decisions use the API path.
- Corner toasts use a ``components.html`` parent-DOM injection; Streamlit
  upgrades can break that path (fallback to ``st.toast`` is in place).
- Shared lecture PDFs in ``lecture_notes/`` remain large git blobs; prefer
  compressed PDFs and Git LFS for future large files.
- Website / Paste Sources Add was intentionally removed from the UI; backend
  ``add_url_source`` / ``add_text_source`` remain for tests and API use.
- Rename Apply remains CSS-hidden so Enter can submit Streamlit forms; if CSS
  fails to inject, Apply becomes visible. Source draft reset still depends on
  popover open-edge detection inside the 1s Sources fragment.
- Profile leave-to-close still uses parent-DOM MutationObserver automation.
- AppTest defaults to ``USE_LOCAL_API=false`` (in-process coach); preferred API
  coaching is covered by ``tests/test_streamlit_api_mode.py`` and
  ``tests/test_api_client.py``.
- Course-material sync still uses the in-process coordinator from the facade
  (HTTP sync endpoint exists for non-UI callers). Legacy engine artifact
  ``render_media`` may still read workspace/files paths.
- ``StudentChatEngine`` remains only for dedicated unit tests
  (``tests/test_files_and_engine.py``); UI student turns use the typed coach path.
- LangGraph checkpoints are in-memory (``MemorySaver``); they do not survive
  API process restart. Graph inspection returns the latest in-process summary.

## Phase 1 evidence (UI rename / a11y)

### Behavior implemented

- Shared Enter-only rename helper in ``ui/rename.py`` used by notebook actions,
  source menus, and the top-bar title.
- Rename commits only on form Apply/Enter; blur alone does not persist.
- Closing notebook actions or a source menu without Enter discards draft keys
  via explicit prefixes and bumps an epoch so the next open shows the saved
  title.
- Accessible help restored/added for Settings, Source actions, and workspace
  collapse/expand controls; source ⋯ keeps a visible ``:focus-visible`` ring.
- ``Press Enter to apply`` remains the focused-field hint; ``help`` exposes the
  same instruction to assistive tech.

### Files changed

- ``ui/rename.py`` (new)
- ``ui/session.py``, ``ui/notebooks.py``, ``ui/sources.py``, ``ui/topbar.py``
- ``ui/profile.py``, ``ui/workspace.py``, ``ui/assets/template.css``, ``ui/AGENTS.md``
- ``tests/test_rename.py`` (new), ``tests/test_streamlit_ui.py``
- ``docs/IMPLEMENTATION_STATUS.md``

### Commands run and results

- Focused: ``.venv/bin/python -m pytest -q tests/test_rename.py tests/test_streamlit_ui.py`` → **17 passed**
- Full: ``.venv/bin/python -m pytest -q`` → **85 passed** (before Phase 2)
- ``PYTHONPYCACHEPREFIX=/private/tmp/co-design-pycache .venv/bin/python -m compileall -q backend ui streamlit_app.py tests`` → success

### Manual validation

- Not re-run in-browser in this phase boundary. Recommend hard-refresh and check:
  topbar Enter-only title, notebook actions dismiss reset, source ⋯ rename
  dismiss reset, keyboard focus ring on source menu, Settings help on profile.

### Migration and rollback

- No database or schema changes.
- Rollback: restore the listed UI/test files; private ``.env`` and SQLite data
  were not modified.

### Known incomplete items

- Browser acceptance for Phase 1 controls still pending manual hard-refresh.
- Phase 4+ not started (test isolation, API-mode UI coverage, all-six-stage /
  restart tests, CI workflow).

## Phase 2 evidence (safety / repository defaults)

### Behavior implemented

- ``scripts/build.sh`` is validation-only: prefers ``.venv/bin/python``,
  ``compileall`` on ``backend ui streamlit_app.py tests``, then mock ``pytest``.
  It no longer calls ``init_db.py``.
- ``scripts/init_db.py`` refuses an existing database unless ``--force``; prefer
  ``--database PATH`` for a fresh file.
- Repository defaults in ``.env.example`` and ``backend/settings.py``:
  ``MODEL_PROVIDER=mock``, ``MOCK_OPENAI=true``, ``AUTO_ADVANCE_STAGES=false``.
- All configured data paths resolve through ``_project_path`` relative to the
  project root when not absolute.
- ``tests/conftest.py`` clears ``OPENAI_API_KEY``.
- Docs/AGENTS/README/DESIGN aligned: confirmation is the safe default;
  auto-advance is an explicit audited local mode. Dark DESIGN tokens match the
  live teal dark theme (no purple accent table).
- Removed unused ``asyncio_mode`` from ``pyproject.toml``.
- Private ``.env`` untouched.

### Files changed

- ``scripts/build.sh``, ``scripts/init_db.py``, ``scripts/AGENTS.md``
- ``.env.example``, ``backend/settings.py``, ``tests/conftest.py``
- ``tests/test_init_db.py`` (new), ``pyproject.toml``
- ``README.md``, ``docs/LOCAL_DEMO_IMPLEMENTATION.md``, ``DESIGN.md``
- ``AGENTS.md``, ``tests/AGENTS.md``, ``docs/IMPLEMENTATION_STATUS.md``

### Commands run and results

- ``sh -n scripts/start.sh && sh -n scripts/build.sh`` → success
- Focused: ``.venv/bin/python -m pytest -q tests/test_init_db.py`` (with models) → passed
- Full: ``.venv/bin/python -m pytest -q`` → **89 passed**
- ``PYTHONPYCACHEPREFIX=/private/tmp/co-design-pycache .venv/bin/python -m compileall -q backend ui streamlit_app.py tests`` → success
- Fresh init: ``scripts/init_db.py --database /tmp/co-design-phase2-fresh.sqlite3`` → created
- Second init without ``--force`` → refused (exit 1)

### Migration and rollback

- No schema migration. Existing live DB is unchanged.
- Rollback: restore listed files; re-enable old ``build.sh`` init only if needed.
- Developers with an existing private ``.env`` keep current provider/stage mode.

### Known incomplete items

- Superseded by Phase 3 completion notes below.

## Phase 3 evidence (backend integrity)

### Behavior implemented

- ``CoachApplicationService`` reloads persisted stage, canonical history,
  selected source IDs, source context, and image inputs from the notebook store.
  Mismatched or unknown client hints return HTTP 400.
- ``CoachRequest.current_stage`` is validated against the six Thinking Path IDs
  (HTTP 422 for unknown values).
- ``StudentStore.apply_phase_transition_decision`` updates transition status and
  journey metadata in one SQLite transaction; injected journey-write failures
  leave the transition pending.
- ``ProviderUnavailableError`` maps to HTTP 503. API routes log thread IDs
  without source text or secrets.

### Files changed

- ``backend/application.py``, ``backend/domain.py``, ``backend/api.py``
- ``backend/learning_service.py``, ``backend/student_store.py``, ``backend/workflow.py``
- ``backend/AGENTS.md``, ``docs/LOCAL_DEMO_IMPLEMENTATION.md``
- ``tests/test_api.py``, ``tests/test_learning_service.py``
- ``docs/IMPLEMENTATION_STATUS.md``

### Commands run and results

- Focused: ``.venv/bin/python -m pytest -q tests/test_api.py tests/test_learning_service.py tests/test_workflow.py`` → **18 passed**
- Full: ``.venv/bin/python -m pytest -q`` → **95 passed**
- ``PYTHONPYCACHEPREFIX=/private/tmp/co-design-pycache .venv/bin/python -m compileall -q backend ui streamlit_app.py tests`` → success

### Migration and rollback

- No schema migration. Existing live DB and private ``.env`` unchanged.
- Rollback: restore the listed backend/test/doc files.

### Known incomplete items

- Superseded by Phase 4 completion notes below.

## Phase 4 evidence (test isolation / primary-path coverage)

### Behavior implemented

- Autouse ``isolated_test_environment`` gives each test its own data/DB/files
  tree, asserts mock mode + empty ``OPENAI_API_KEY``, and clears Streamlit
  resource caches.
- ``LocalApiClient`` accepts an injectable sync session for in-process FastAPI
  ``TestClient`` contracts; adds ``learning_state``.
- API-mode AppTest covers confirmation (pending transition) and auto-advance
  (Thinking Path moves); one legacy AppTest remains on ``USE_LOCAL_API=false``.
- Primary-path tests cover all six stages, reject/stale transitions, restart
  recovery, cross-notebook isolation, and additive ``phase_transitions`` schema.
- Mock CI workflow runs shell syntax, compileall, and pytest on push/PR.

### Files changed

- ``tests/conftest.py``, ``tests/AGENTS.md``
- ``tests/test_api_client.py`` (new), ``tests/test_primary_path.py`` (new)
- ``tests/test_streamlit_api_mode.py`` (new)
- ``backend/api_client.py``
- ``.github/workflows/mock-ci.yml`` (new)
- ``docs/IMPLEMENTATION_STATUS.md``

### Commands run and results

- Focused: ``tests/test_api_client.py tests/test_primary_path.py tests/test_streamlit_api_mode.py`` → **11 passed**
- Full: ``.venv/bin/python -m pytest -q`` → **106 passed**
- ``PYTHONPYCACHEPREFIX=/private/tmp/co-design-pycache .venv/bin/python -m compileall -q backend ui streamlit_app.py tests`` → success

### Migration and rollback

- No schema migration. Existing live DB and private ``.env`` unchanged.
- Rollback: restore listed test/client/CI files.

### Known incomplete items

- Superseded by Phase 5 completion notes below.

## Phase 5 evidence (CRUD behind typed API)

### Behavior implemented

- ``WorkspaceService`` owns notebook/history/source/preference CRUD and safe
  source-byte reads; API responses redact filesystem ``path`` (``has_file``).
- FastAPI routes under ``/api/v1`` for preferences, threads, messages, sources,
  upload, select-all, content, legacy backfill, and course-material sync.
- ``LocalApiClient`` covers the new contracts; ``ui.runtime.store`` is a
  ``WorkspaceFacade`` that uses the API when ``USE_LOCAL_API=true`` else the
  in-process service.
- Sources preview/download and uploads go through the facade (no direct path
  reads in ``ui/sources.py`` / chat upload path).

### Files changed

- ``backend/workspace_service.py`` (new), ``backend/api.py``, ``backend/api_client.py``
- ``backend/domain.py``, ``backend/repositories.py``, ``backend/source_library.py``
- ``ui/runtime.py``, ``ui/sources.py``, ``ui/chat.py``, ``ui/session.py``
- ``ui/AGENTS.md``, ``backend/AGENTS.md``
- ``tests/test_workspace_api.py`` (new)
- ``docs/IMPLEMENTATION_STATUS.md``

### Commands run and results

- Full: ``.venv/bin/python -m pytest -q`` → **109 passed**
- ``PYTHONPYCACHEPREFIX=/private/tmp/co-design-pycache .venv/bin/python -m compileall -q backend ui streamlit_app.py tests`` → success

### Migration and rollback

- No schema migration. Existing live DB and private ``.env`` unchanged.
- Rollback: restore listed backend/UI/test files.

### Known incomplete items

- None for Phase 5; Phase 6 evidence follows.

## Phase 6 evidence (streaming / checkpoints / legacy retirement)

### Behavior implemented

- ``scripts/start.sh`` polls ``GET /api/v1/ready`` before starting Streamlit.
- FastAPI stamps ``X-Request-ID`` on every response and exposes readiness,
  ``POST /api/v1/coach/turn/stream`` (NDJSON), and
  ``GET /api/v1/threads/{id}/graph``.
- ``CoachWorkflow`` runs ``load_context → assess → recommend → format`` with
  LangGraph ``MemorySaver`` when available; sequential fallback remains.
- Streamlit student turns always use typed coaching (API or in-process
  ``CoachApplicationService``) with streamed tokens; ``StudentChatEngine`` is
  no longer on the UI path.
- Removed the one-option composer model picker, related layout JS, and dead
  model-slot CSS.

### Files changed

- ``scripts/start.sh``
- ``backend/workflow.py``, ``backend/api.py``, ``backend/api_client.py``
- ``ui/runtime.py``, ``ui/chat.py``, ``ui/layout/composer_layout.py``
- ``ui/assets/template.css``, ``ui/AGENTS.md``
- ``tests/test_api.py``, ``tests/test_api_client.py``, ``tests/test_workflow.py``
- ``tests/test_streamlit_ui.py``, ``tests/test_streamlit_api_mode.py``,
  ``tests/conftest.py``
- ``docs/IMPLEMENTATION_STATUS.md``

### Commands run and results

- Full: ``.venv/bin/python -m pytest -q`` → **111 passed**
- ``PYTHONPYCACHEPREFIX=/private/tmp/co-design-pycache .venv/bin/python -m compileall -q backend ui streamlit_app.py tests`` → success

### Migration and rollback

- No schema migration. Existing live DB and private ``.env`` unchanged.
- Rollback: restore listed backend/UI/test/script files.

### Known incomplete items / risks

- In-memory LangGraph checkpoints do not survive API process restart.
- ``StudentChatEngine`` unit tests remain; do not rewire UI to that path.
- CSS cleanup removed model-slot rules from the recovered working-tree stylesheet;
  re-check desktop and 390 px composer layout visually after restart.

## Next exact action

**Stop for review.** After approval, optional follow-ups: durable checkpoint
adapter beyond ``MemorySaver``, further CSS maintainability splits, or a live
Ollama smoke (labelled, separate from mock CI). Do not start unpaid OpenAI
calls or commits unless explicitly requested.
