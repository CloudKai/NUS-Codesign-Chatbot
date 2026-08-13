# Implementation status

## Current phase

**Behavior-preserving architecture refactor — Phase 3 HTTP composition
completed locally on 2026-08-13.** Phase 2 remains rollbackable at local commit
``16b7f14``. FastAPI implementation ownership moved; its observable contract
did not.

### Phase 3 behavior and structure

1. **Thin compatibility façade.** ``backend/api.py`` is now a 25-line façade
   re-exporting the original schemas, ``register_workspace_routes``,
   ``create_app`` and module-level ASGI ``app``. The complete implementation is
   owned by ``backend/http/app.py``. All callers, uvicorn imports and test
   imports keep using ``backend.api`` unchanged.
2. **Historical seams preserved.** The established
   ``backend.api.validate_cognito_readiness`` monkeypatch seam still controls
   readiness validation, and operational logs keep logger name ``backend.api``
   so dashboards/tests do not lose events merely because the code moved.
3. **Route contracts unchanged.** Authentication registration remains separate;
   owner resolution is still injected through ``Depends(current_owner)``; all
   route paths, methods, operation names, status/response behavior, streaming
   events, headers, rate limits and exception mappings remain in the verified
   application factory.
4. **Deliberately bounded extraction.** Workspace/learning/coaching registrars
   were not split in this commit after a compile-time-only trial demonstrated
   that a line-range move could cut nested route functions. The failed
   uncommitted attempt was fully reverted before this safer ownership move.
   Smaller registrar extraction remains a later step, protected by this green
   commit and the complete route inventory gate.

### Phase 3 compatibility and migration

- No API, schema, database, authentication, authorization, owner resolution,
  provider, prompt, environment-variable or UI contract changed.
- No data migration or private-file access. Rollback is the Phase 3 local commit;
  no database/data rollback is required.

### Phase 3 verification

- Complete deterministic suite: **459 passed** with the same 52 framework
  deprecation warnings; no live or paid-provider call.
- API/auth/ownership/streaming focused gate: **74 passed**.
- Full route/method/name inventory and protected owner-dependency inventory pass.
- Ruff reports zero findings. Compileall and ``git diff --check`` passed.

### Next exact phase

Phase 4 starts with deterministic learning boundaries in
``backend/student_journey.py``: extract stage definitions/navigation and
Facione Review projection behind re-exports, then split request/citation helpers
from ``CoachApplicationService`` only where private test seams stay intact.
Source ingestion/context follows. Each group gets its own focused and full gate.

## Previous completed architecture phase — Phase 2 persistence

**Behavior-preserving architecture refactor — Phase 2 persistence foundation
completed locally on 2026-08-13.** Phase 1 remains rollbackable at local commit
``6e2f776``. This phase changes only implementation ownership behind the
existing ``StudentStore`` and ``DsqlStudentStore`` façades.

### Phase 2 behavior and structure

1. **Stable contracts extracted.** Persistence exceptions, immutable command
   results, JSON serialization helpers, Facione/progress/settings keys, and a
   narrow structural store context now live in
   ``backend.persistence.store.contracts``. ``backend.student_store`` re-exports
   the same names and private aliases used by existing services and tests.
2. **Schema lifecycle separated without migration.** The byte-equivalent local
   five-table schema moved to ``sqlite_schema``. OAuth/user/revision/FK repair
   logic moved to ``migrations`` while every legacy ``StudentStore`` static
   migration seam remains as a delegating compatibility wrapper. Startup order,
   implicit SQLite compatibility timing, commits, rollback paths, tables,
   columns and indexes are unchanged. DSQL still performs no runtime DDL.
3. **Composition introduced at a real boundary.** ``StoreOperations`` binds
   focused source operations to a narrow store context from both SQLite and
   DSQL constructors. A lazy compatibility binder protects historical tests
   that construct DSQL with ``object.__new__``. All source validation, owned
   queries, normalization, selection, rename/delete, and deterministic cleanup
   now reside in ``operations.sources``; ``StudentStore`` methods keep identical
   signatures and delegate to it.
4. **Provider-neutral repository names added.** New ``Store*Repository`` names
   describe adapters that work over either SQLite or DSQL. Every existing
   ``SQLite*Repository`` import remains an alias to the same implementation.
5. **Measured readability improvement.** ``student_store.py`` is now 3,121
   lines (down from the 3,732-line checkpoint) and no moved implementation was
   copied back into the façade. The remaining coaching/revision/notebook/user
   groups are intentionally deferred to later persistence slices rather than
   combined into one risky rewrite.

### Phase 2 compatibility and migration

- No data migration or rewrite. No schema, persisted JSON, ownership,
  transaction, S3 cleanup order, DSQL OCC method list, route, authentication,
  provider, prompt or UI contract changed.
- ``StudentStore`` and ``DsqlStudentStore`` constructor/public/private seams,
  return dictionaries, exceptions, source error messages and file safety checks
  remain compatible. DSQL retries still wrap one complete public write method.
- Existing private ``.env``, database and upload data were untouched. Rollback
  is the Phase 2 local commit only; no data rollback is required.

### Phase 2 verification

- Complete deterministic suite: **459 passed** with the same 52 framework
  deprecation warnings; no live AWS/Cognito/DSQL/S3/model call was made.
- Persistence/source/DSQL/OCC focused gate: **145 passed**.
- Ruff reports zero findings. Compileall, dependency consistency and
  ``git diff --check`` passed.

### Next exact phase

Phase 3 starts at ``backend/api.py``. Move registration into
``backend.http.routes.workspace``, ``system``, ``learning`` and ``coaching``;
keep ``backend.api.create_app`` and all schemas/re-exports compatible. The
complete route/method/name/dependency inventory test is the merge gate, followed
by all API/auth/streaming tests and the full deterministic suite.

## Previous completed architecture phase — Phase 1 quality gates

**Behavior-preserving architecture refactor — Phase 1 quality and contract
gates completed locally on 2026-08-13.** The pre-refactor application state is
preserved in local commit ``5b94968`` on
``codex/pre-refactor-checkpoint-20260813``. Refactoring continues only on
``codex/architecture-refactor``; neither branch has been pushed.

### Phase 1 behavior and structure

1. **No product behavior changed.** The FastAPI paths, methods and operation
   names; ``StudentStore`` public methods; DSQL OCC write coverage; Streamlit
   widget/session behavior; authentication flow; prompts; scoring; and visible
   Light/Dark UI remain the compatibility baseline.
2. **Lint is now reproducible.** The previous 14 Ruff findings were removed
   through import ordering and unused-test-import cleanup. Ruff ``0.11.13`` is
   pinned with the development/test requirements and ``python -m ruff check .``
   is part of Mock CI. No formatting rewrite or runtime cleanup was mixed in.
3. **Architecture regression gates were added.** Tests now reject backend-to-UI
   imports, direct database/model/infrastructure SDK imports from Streamlit,
   production module-scope import cycles, missing compatibility exports or
   signatures, FastAPI route inventory drift, and accidental changes to the
   ``StudentStore``/DSQL OCC method inventories. These are boundary/contract
   checks, not arbitrary file-size rules.
4. **The UI import cycle was removed.** Cookie reading now lives in the neutral
   ``ui.auth.cookies`` helper used by both the authentication gate and runtime
   API client. ``ui.auth_gate._cookie_value`` remains as a compatibility alias,
   so existing tests and callers keep the same seam.

### Phase 1 compatibility and migration

- No database schema, migration, persisted JSON, route, request/response,
  authentication, provider, prompt, environment-variable, widget key,
  session-state key, copy, CSS, or visual layout changed.
- Existing private ``.env`` values, SQLite databases, uploaded files, notebooks,
  messages, sources, assessments, and OAuth/session records were untouched.
- Rollback is the single local Phase 1 commit after it is created; no data
  rollback is required.

### Phase 1 verification

- Complete deterministic suite: **459 passed** (the 453-test checkpoint plus 6
  architecture contract tests), with the same 52 framework deprecation
  warnings and no live/paid-provider call.
- Focused architecture/auth/workspace gate: **62 passed**.
- Ruff: **zero findings**. Compileall, ``pip check``, shell syntax, both Compose
  configuration checks, and ``git diff --check`` passed.
- Read-only local SQLite baseline remains ``quick_check=ok`` with zero foreign
  key violations and zero orphan notebooks, messages, or sources.
- Browser baselines at 1440 px and 390 px show the same student workspace before
  and after the dependency-cycle change. No CSS or rendered component changed.

### Next exact phase

Phase 2 starts at ``backend/student_store.py``: extract provider-neutral
persistence contracts plus SQLite schema/compatibility migration helpers, then
bind cohesive operation objects from both ``StudentStore`` and
``DsqlStudentStore``. Preserve the existing constructor, public/private seams,
transaction boundaries, DSQL retry units, tables, indexes and automatic SQLite
compatibility timing. Run persistence/DSQL tests and the full gate before the
next local commit.

## Previous completed phase — Quick/Strict and security hardening

**Quick/Strict coaching profiles, provider cleanup, and architecture/QA
hardening — implemented locally on 2026-08-13; immutable deployment smoke
pending.** The working application remains the behavior specification. This
phase preserves the existing ``short``/``long`` persistence and API values
while giving them the student-facing names **Quick** and **Strict**.

### Current behavior

1. **Profile semantics.** Quick remains the default and uses the lighter
   progression threshold plus the established Facione calibration. Strict uses
   the existing ``long`` value and adds an explicit higher threshold for stage
   advancement and newly demonstrated Facione evidence. The deterministic mock
   reflects that distinction without claiming semantic evaluation.
2. **Score isolation and compatibility.** New assessed assistant messages carry
   ``coaching_profile=quick|strict`` in existing metadata. Tagged Quick and
   Strict evidence is aggregated separately. Untagged legacy assessments seed
   both profiles. The first Quick→Strict switch stores a bounded,
   provenance-bearing baseline (scores plus the last included message
   position); later Quick evidence cannot raise Strict scores, while append-only
   edits remove superseded evidence from the active Strict projection. A brief
   legacy flat-baseline shape remains readable.
3. **Safe profile switching.** Changing profiles persists only the existing
   notebook ``response_detail`` setting, retains stage/completion/history and
   conversation revision, and atomically rejects active pending **Next**
   recommendations. A coach result generated under the previous profile fails
   the existing persistence CAS if the profile changes while provider work is
   in flight, so stale Quick output cannot recreate a pending Next after a
   Strict switch. Superseded historical pending decisions remain reconstructible.
   The profile widget uses Streamlit's normal full-app widget rerun, avoiding
   an explicit callback rerun and its no-op warning.
4. **English-only student UI.** The obsolete language control is removed. New
   sends and revisions use English even when a legacy notebook or direct client
   supplies another language. The request/schema field remains accepted for
   compatibility; existing stored data is not rewritten.
5. **Architecture hardening retained.** Owner-scoped workspace CRUD keeps its
   18-route owner-dependency inventory protected inside ``backend/api.py``.
   Audited auto-advance persists the final
   assistant reply, confirmed transition, summaries, and next stage atomically.
   The corrected mock load probe uses distinct owners and temporary memory file
   storage. No prompt provider, database, storage, or authentication SDK was
   moved into Streamlit.
6. **Provider surface simplified.** Runtime provider selection now supports
   only the deterministic mock and OpenAI adapters. The retired local-model
   adapter, its environment settings, readiness allowance, setup instructions,
   and stale architecture references were removed. Unknown or legacy provider
   values fail closed instead of silently selecting another provider. Shared
   stage prompts, Quick/Strict calibration, Facione assessment, retrieval, and
   persistence remain provider-neutral and unchanged.
7. **Database/API/auth hardening.** Login-start throttling uses the final valid
   address in an append-mode forwarded chain instead of the client-spoofable
   first value, with direct-peer fallback for malformed input. Modern browser
   cross-site GET logout is rejected before token revocation or cookie changes;
   the existing same-site GET profile action, POST route, paths, and responses
   remain intact. OAuth callback consumption also prunes other already-expired
   one-time state rows in the same transaction. No student record, active OAuth
   state, session, route, response schema, or visible UI changed.

### Compatibility and migration

- No database column/table migration is required. The profile tag and Strict
  baseline live in existing message/notebook metadata fields.
- Public ``response_detail`` remains ``short|long``; no API path, request model,
  response model, authentication contract, or authorization boundary changed.
- Existing Quick/legacy scores, notebook stages, completion records, append-only
  conversation history, sources, and user data remain intact.
- No private ``.env`` value was modified. Rollback is a code/documentation
  revert; no destructive data rollback is needed.
- Existing private files that still select a retired provider must be changed
  to ``MODEL_PROVIDER=mock`` or ``MODEL_PROVIDER=openai`` before restart.

### Current verification

- High-risk focused gate: **140 passed**, covering profile labels/defaults,
  Quick/Strict prompt and mock thresholds, profile-separated scores, legacy and
  structured baselines, active/superseded revisions, pending-Next rejection,
  in-flight profile CAS, auto-advance, workspace API, and Streamlit behavior.
- Final complete deterministic suite: **453 passed** with 52 existing
  FastAPI/Starlette deprecation warnings.
- Database/API/auth focused gate: **89 passed**, including owner isolation,
  workspace contracts, normal and cross-site logout, Cognito cookies/JWT
  behavior, login throttling, one-time OAuth state, learning persistence, and
  restart-safe store behavior. The local database read-only quick check is
  ``ok`` with zero foreign-key violations and zero orphan notebooks, messages,
  or sources.
- Review-hardening gate: **73 passed** across workspace/API contracts,
  Streamlit UI, theme, rerun scope, and source behavior. Workspace routes are
  contained in the tracked API module, runtime prompt Markdown remains
  trackable, attachment controls retain an accessible purpose label, and the
  composer helper now removes its observers/listeners before rebinding. These
  are deployment, accessibility, and lifecycle fixes only; no visible UI or
  application workflow changed.
- Compileall, dependency consistency, shell syntax, both Compose contracts,
  and ``git diff --check`` passed. A separately available Ruff binary reports
  the same 14 pre-existing findings; Ruff is not installed in the project
  environment. Static typing and coverage gates remain unconfigured.
- No live AWS, Cognito, DSQL, S3, OpenAI, or other paid-provider call
  was made. Light/Dark browser QA for Profile and Review passed, including the
  immediate Strict note after a full-app rerun. The console retained pre-existing
  layout-helper ``MutationObserver`` errors and ``components.html`` deprecation
  warnings; no coaching failure was observed.

### Remaining risks and next action

Wire-level DSQL concurrency, immutable ARM64 deployment, real CloudFront/Caddy
header propagation, Cognito/S3 behavior, 390 px responsive QA, and cleanup of
the pre-existing browser-console warnings remain outside local mock proof. The
owner-service cache remains intentionally unbounded because each service owns
the current process-local graph inspection state; eviction requires a separate
durable-checkpoint design and is not a behavior-neutral fix. Splitting the
large ``api.py`` / ``student_store.py`` modules is likewise deferred to a
contract-protected architecture phase. Next provider phase: implement an
Amazon Bedrock adapter behind the existing assessment-provider boundary while
retaining the same prompt composer and structured coaching contract. Until
then, deploy or test with ``MODEL_PROVIDER=mock`` unless an explicitly approved
OpenAI smoke is required.

## Historical implementation ledger (retained evidence before 2026-08-13)

The sections below preserve earlier phase notes and their original test counts.
They are historical evidence, not the current completion verdict. Current
architecture and behavior are stated above and in
``docs/LOCAL_DEMO_IMPLEMENTATION.md``; current testing guidance is in
``docs/TESTING.md``.

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
  deterministic mock and OpenAI provider ports, and one
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
- Added a feature-gated Streamlit API path with `USE_LOCAL_API=true`; at that
  historical phase, the legacy direct path remained while CRUD was migrated.
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
- At that historical phase, the notebook workspace header exposed a `Mode`
  response-detail control and a Setting dialog with language, appearance, and
  model selection. The current UI instead uses Profile → Coaching style
  (Quick/Strict), is English-only, and has no student model selector.
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
  heading and the source selector begins immediately below the divider. At that
  historical phase the response control used `Quick`/`Complex`; the current
  labels are `Quick`/`Strict`, still backed by ``short``/``long``.
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

## Historical validation evidence

- Historical browser and feature acceptance notes remain for continuity; the
  latest automated counts are under Phase 1 / Phase 2 evidence.
- `sh -n scripts/start.sh` and `sh -n scripts/build.sh` passed.
- Private interactive `.env` may still use OpenAI + auto-advance; repository
  defaults and automated tests use mock + confirmation.

## Historical data and migration state

- Existing SQLite data and local uploads remain in ignored data paths.
- No schema migration is required for Phase 2.
- `scripts/init_db.py` no longer runs from `build.sh`; explicit `--database` or
  `--force` is required to touch an existing file.
- Private `.env` was left unchanged.

## Historical risks and open questions

- The project baseline remains mostly untracked; no Git commit was created.
- Private `.env` may still enable OpenAI / auto-advance; that is intentional and
  out of repository defaults.
- Lecture-folder retrieval currently uses the bounded selected-source context
  path; vector/embedding retrieval remains a later provider-adapter phase.
- At that historical phase, source/notebook CRUD still used direct Streamlit
  store calls. The current UI uses ``WorkspaceFacade`` (HTTP API or the same
  in-process application service according to runtime mode).
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

## Historical Phase 1 evidence (UI rename / a11y)

### Behavior implemented

- Shared Enter-only rename helper in ``ui/rename.py`` used by notebook actions,
  source menus, and the top-bar title.
- Rename commits only on form Apply/Enter; blur alone does not persist.
- Closing notebook actions or a source menu without Enter discards draft keys
  via explicit prefixes and bumps an epoch so the next open shows the saved
  title.
- Accessible help restored/added for Settings, Source actions, and workspace
  collapse/expand controls; source ⋯ keeps a visible ``:focus-visible`` ring.

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

## Historical Phase 2 evidence (safety / repository defaults)

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

## Historical Phase 3 evidence (backend integrity)

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

## Historical Phase 4 evidence (test isolation / primary-path coverage)

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

## Historical Phase 5 evidence (CRUD behind typed API)

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

## Historical Phase 6 evidence (streaming / checkpoints / legacy retirement)

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

## Historical next action

**Stop for review.** After approval, optional follow-ups: durable checkpoint
adapter beyond ``MemorySaver`` or further CSS maintainability splits. Do not
start OpenAI calls or commits unless explicitly requested.
