# Implementation status

## Current phase

**Phase 3 — local workflow foundation and compatibility migration**

The application now has a working local FastAPI/LangGraph foundation while the
existing Streamlit UI remains compatible during the incremental migration.

## Completed

- Locked coaching to **GPT-5.6 Luna** with **low** reasoning: removed the
  composer model picker, collapsed the model registry to one entry, and set
  OpenAI coach calls to `gpt-5.6-luna` / `low`.
- Fixed Learning Path advancement for everyday startup: `scripts/run.sh` now
  starts FastAPI + Streamlit with `USE_LOCAL_API=true` (same as the local demo).
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
- Added `scripts/run_local_demo.sh`, `.env.example`, and local demo setup
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
- Enabled automatic stage advancement by default. Every advance remains an
  auditable persisted transition, but the application resolves it immediately
  and updates the visible Thinking Path without confirmation controls.
- Added the shared `lecture_notes/` drop folder. Supported files are
  safely copied into each active notebook, selected, refreshed on change,
  removed when the folder file disappears, and exposed as stable citation
  chips in the local coaching workflow.
- Grouped instructor-managed PDFs into locked **Lecture Notes** and **Readings**
  source folders. The UI exposes selection and preview only, while repository
  enforcement blocks interactive deletion and keeps synchronizer refreshes safe.
  A separate 50 MB trusted-course-file limit includes the supplied 27 MB and
  34 MB lecture PDFs without increasing the 25 MB student-upload limit.
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

## Validation evidence

- `pytest -q` passed in forced mock/auto mode: **63 tests** (including 11
  Streamlit AppTest cases against the redesigned `streamlit_app.py` / `ui/`
  entrypoint).
- Python compilation passed for `backend/`, `ui/`, and `streamlit_app.py`.
- A real LangGraph invocation passed against the deterministic provider.
- `sh -n scripts/run_local_demo.sh` passed.
- Browser acceptance passed at desktop and 390 px: greeting, first-turn
  guidance, second-turn Focus-to-Evidence recommendation, explicit transition
  confirmation, responsive composer, and a clean console.
- Browser acceptance also passed for automatic Focus-to-Evidence movement,
  lecture-folder synchronization, selected-source grounding, persisted `[S1]`
  citation rendering, and a fresh clean console.
- Final browser acceptance passed at desktop and 390 px with all 10 supplied
  PDFs grouped as **Lecture Notes (7)** and **Readings (3)**, locked source
  controls, in-dialog PDF viewing, personalized Evidence questions after
  automatic advancement, and a clean fresh-tab console.
- Latest browser acceptance passed for inline title editing and history sync,
  simplified Setting contents, responsive Sources-header alignment, removed
  contribution boilerplate, and a clean fresh-tab console.
- Citation browser acceptance passed for closed and expanded dropdown states at
  desktop, the compact state at 390 px, removal of the selected-source strip,
  source-viewer action retention, and a clean console. Temporary QA notebook
  data was deleted after the test.
- Header browser acceptance passed for desktop resting and active-title states,
  the 390 px responsive state, preserved action accessibility, and a clean
  console. The Streamlit input-root outline found in the first visual pass was
  removed.
- Sources/Guidance browser acceptance passed at desktop and 390 px: the help
  icon stays beside `Sources`, selector spacing is compact, Add remains aligned,
  and `Guidance: Quick/Complex` uses a compact field. The mock suite remains at
  **60 passing tests**, compilation passes, and the browser console is clean.
- Corrected the top-bar regression at desktop and wide-desktop: the notebook
  title is permanently visible and editable, Notebooks shows its Material icon
  plus label, and Setting stays icon-only. Both actions are compact, borderless,
  and interaction-tested; 390 px responsive behavior remains intact.
- Grouped Notebooks, Guidance, the response-detail selector, and Setting into
  compact grid tracks so their internal spacing stays consistent rather than
  stretching across the header. The narrow breakpoint uses the same compact
  control group after the title is hidden.
- Tightened the Sources title/count stack and the divider-to-source-list inset
  so the help icon and Add action remain aligned without leaving an oversized
  vertical gap above the selected-source controls.
- Restored a deliberate breathing space between the selected-source count and
  its divider, while keeping the source controls immediately below compact.
- Extracted the 5,653-line `streamlit_app.py` monolith into a presentation-layer
  `ui/` package (`constants`, `theme`, `runtime`, `session`, `sources`, `chat`,
  `studio`, `notebooks`, `settings`, `topbar`, `workspace`). The entrypoint is
  now a thin orchestrator; behavior, keys, CSS, and dialog wiring are unchanged.
- Made managed course-material imports refresh-safe: overlapping Streamlit
  runs now share one background synchronization job, and legacy duplicate rows
  are repaired by relative path. The Sources panel shows a loading state while
  Chat and Thinking Path remain visible and interactive.
- Redesigned the Streamlit presentation into a teal academic design system with
  IBM Plex Sans / Source Serif branding, a top section switcher
  (Journey / Review / Chat / Sources / Notebooks), and a profile dialog that
  replaces Setting. Journey uses a roadmap + progress bar; Review uses insight
  cards with a change notification fingerprint; Sources gained search/type/sort
  and empty states; Notebooks is folder-free with active highlighting; Chat uses
  a clearer composer placeholder, attach helper, and API retry.
- Browser acceptance reproduced the new-notebook refresh path, observed the
  in-panel loading state, and then verified **Lecture Notes (7)**,
  **Readings (3)**, desktop and 390 px layouts, and a clean console. The
  temporary QA notebook was removed afterward.

## Data and migration state

- Existing SQLite data and local uploads remain in ignored data paths.
- No schema migration is required. The next course-material refresh removes
  only duplicate managed copies created by the older race, preserving one
  canonical source for each of the 7 lecture notes and 3 readings.
- The affected local notebook was repaired in place: 8 stale managed copies
  were removed, leaving the expected 10 protected course sources.
- The new schema is additive and initialized by the current store initializer.
- No existing notebook, folder, message, source, or learning-state record was
  modified by migration code.

## Risks and open questions

- The project baseline remains mostly untracked; no Git commit was created.
- The Ollama provider still needs live host validation.
- Live OpenAI behavior remains unverified because paid requests require a
  rotated credential and an explicit request/token or cost cap.
- Lecture-folder retrieval currently uses the bounded selected-source context
  path; vector/embedding retrieval remains a later provider-adapter phase.
- Source, notebook, and folder CRUD still use the existing direct Streamlit
  store calls; only coaching turns and transition decisions use the API path.
- `scripts/build.sh` initializes the database and must not be used against user
  data until its behavior is reviewed.

## Next exact action

Migrate source/notebook/folder CRUD behind typed API routes and replace the
remaining direct Streamlit store calls while preserving the verified UI.
