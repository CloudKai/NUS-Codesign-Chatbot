# Implementation status

## Current status

### Implemented — "Improve my design" replaces Lecture help (2026-11-27 SGT)

The approved [spec](specs/IMPROVE_MY_DESIGN.md) is implemented across backend,
frontend, Streamlit student surface, and lecturer reporting. New: `improve_design`
intent, `POST /api/v1/reader/threads/{thread_id}/improve/stream`, the
`backend/prompts/shared/improve_design.md` prompt family (stage-blind: no stage
instructions, no recommendations, no transitions), `improve_design` row in the
evidence scope, `Intent = "improve" | "project"` in the reader with mode-aware
copy and `default_mode` read-back, `/lecture/stream` kept as a stale-client
compatibility route, and `LearningFunnel.improve_design` counted separately from
historical `lecture_help`. Validation: full backend suite **3443 passed**
(prompt-baseline lock updated to 7 files with the reviewed Improve prompt; route
inventory updated with `improve_stream`), frontend suite **213 passed**,
generated API client regenerated (`npm run api:generate` + `api:check`),
OpenAPI export refreshed, `compileall` clean. Compatibility: no stored student
data rewritten; legacy `lecture_help` metadata still read for analytics and
revised with the original mode via the compat route; tab draft keys migrated
without data loss. Rollback: revert the branch and redeploy the previous
bundle; the compat route keeps old clients working during cutover. **Next
exact action:** GitHub publication of the five tickets, then the follow-up
branch for context-window and memory work (out of scope here).

### Approved spec — "Improve my design" replaces Lecture help (2026-11-27 SGT, operator decisions)

[Spec](specs/IMPROVE_MY_DESIGN.md) records five operator decisions: the Lecture
help mode becomes **"Improve my design"** (freeform help on the student's
existing design; improvement focus discovered per conversation, never stored);
the mode is **completely stage-blind** (no stage context in the prompt, cannot
recommend or advance a stage — fenced like today's `lecture_help` path);
course-material retrieval stays available when relevant through the existing
evidence gate. Naming contract: frontend intent `lecture`→`improve`, backend
intent `lecture_help`→`improve_design`, route
`/threads/{id}/lecture/stream`→`/improve/stream`, stored `default_mode
"lecture"` reads back as `"improve"`. **No implementation has started.** Next
exact action: phase 1 of the spec (backend intent, `/improve/stream` route,
discovery prompt family, stage-blind invariant tests). Compatibility: no
stored student data changes; old transcripts render as-is; the generated
OpenAPI client must be regenerated in the same change as the route change.

### Fixed — restored Review panel trapped all clicks (2026-11-26 SGT, operator report)

**User report:** after clicking Continue on Home, nothing was clickable — "even
the tabs and the buttons inside." **Root cause (empirically reproduced with
Playwright):** the Thinking Path panel restores `open: true` from session
storage and the mount effect opened it with `showModal()` whenever the layout
was not docked (the 768–979 px window band — a half-screen window). The native
`::backdrop` covered the viewport and intercepted every click outside the
panel (`elementFromPoint` over the app header returned `dialog#project-panel`);
in-panel scaffold buttons "do nothing" by design when the drawer is open,
completing the dead-app perception. **Fix:** a restored-open panel now opens
**non-modal** (`show()`) with a visible "Reopened your saved Review panel"
announcement; only an explicit Review-button click earns the modal on
non-docked layouts. Docked behavior, Escape/backdrop dismissal, and ticket 44
focus semantics unchanged. Red-first: `frontend/tests/browser/review_restore.spec.ts`
failed on `panel.matches(':modal') === true` before the fix; 3 passed after.
Focused regressions (route_load, authoring_accessibility, guest_journey): 4
passed. Frontend rebuilt and live at :8080 — **refresh the browser tab to load
the fixed bundle.** Rollback: revert Conversation.tsx and the new spec.

### Home card redesign — To Work on + single Continue (2026-11-26 SGT, operator request)

The Home card no longer renders the pending stage decision (Move on / Stay
here). It now shows **To work on: …** — the saved coach rationale when a stage
recommendation is pending (bounded, quoted), otherwise the stage's saved
next action — with a single **Continue** button directly below that opens the
project chat. The stage decision itself is unchanged and still requires the
student's explicit confirmation in the conversation's recommendation card
(`StageRecommendation` → `resolveTransition`); Home is now fully read-only
(no transition write, no model call on page load, `decided` prop removed).
Red-first: the pending-project test failed against the old decision block
before the change, and pins one Continue → `openChat(thread)`, no
Move on/Stay here buttons, and no `/resolve` request from Home. The
next-action branch is covered too. Frontend **202 passed / 3 skipped**;
build exit 0. Rollback is source-only (HomeView.tsx, App.tsx, its test).

### Review fixes — five findings resolved (2026-11-26 SGT, OpenCode)

**All five findings from the code review are fixed with red-first evidence.**
They span tickets 15/20/22/28/30/52. A parallel writer session's separate
"six follow-up review findings" entry below covers six *different* findings;
the two sets coexist and the combined tree is green (validated jointly).

#### Findings and fixes

| Finding | Fix | Red-first evidence |
| --- | --- | --- |
| **P2** DSQL authoring writes bypass transaction retries | Added `create_artifact`, `update_artifact`, `restore_artifact`, `delete_artifact`, `create_canvas`, `update_canvas`, `restore_canvas` to `_OCC_WRITE_METHODS` in `backend/persistence/dsql_student_store.py`; the architecture OCC inventory pins them. | New `tests/persistence/test_authoring_occ_retry_p2.py`: a disposable adapter injected one SQLSTATE 40001 after a mid-unit write and observed `SerializationFailure` escaping both an artifact create and a canvas update before the list change; now each retries the whole unit and commits exactly once (2 passed). |
| **P1** Lost create acknowledgement duplicates an artifact | Deterministic request identity: additive `request_id` + `request_fingerprint` on `student_artifacts` (SQLite partial unique index; DSQL async unique index; in-place legacy migration), replayed owner+notebook-scoped on create with **no new revision**. A retry with a changed payload refuses (`422`). `CanvasDraftCard` uses the stable `draft:<draft.id>` key; `CanvasDevelopDialog` reuses one per-dialog key across retries; ambiguous failures say a retry is safe instead of "nothing was saved". | Storage test observed `TypeError: … unexpected keyword argument 'request_id'`; the legacy-upgrade test observed `no such column: request_id`; the changed-payload test observed `DID NOT RAISE` before the fingerprint guard; component red-first on the old copy. |
| **P2** Project exports omit child-chat work | `project_export` assembles the conversation from the **notebook family** (`notebook_family_ids`), labels each message with its bounded chat title, keeps the 200-message cap + truncation flag, and keeps Thinking Path with the requested notebook. | The family test first observed only the parent notebook's message — the child chat's message and title absent — then green; a second test pins the cap across the family. |
| **P2** A canvas suggestion can be accepted twice across sessions | **Root cause:** the server rejected `accepted_suggestion_ids` as an unsupported graph key, so every acceptance save failed 422 and dedupe stayed session-storage-only. `canonical_canvas_graph` now accepts a bounded optional list (≤1000, non-empty ≤64-char ids, dedupe, omitted when absent for exact legacy comparison); the client projection preserves it; re-acceptance shows "This suggestion was already applied." | Persistence: 6 failures with `CanvasValidationError: Graph contains unsupported keys`, then 7 passed; HTTP seam observed the 422 with the legacy key set, then 2 passed; the cross-session component test pins one save. |
| **P2** AI-synthesized artifacts lose provenance | `origin` allowlist (`editor` / `coach_draft`) stored on the artifact and its first checkpoint; `canvas_node` references accept an optional validated `revision`; the draft card stamps `coach_draft` + `draft.base_canvas_revision` on contributing nodes (the stable request id stores the draft identity) and the manual dialog stamps `canvas.revision`. | Storage observed `ReferenceError: Only artifact references carry a revision`, then round-trips; HTTP observed `422` for the unknown `origin` field before the contract change; component red-first on the missing provenance. |

#### Additional findings from this review pass (fixed)

| Finding | Fix | Red-first evidence |
| --- | --- | --- |
| **P2** The family export loaded every message from every family notebook before the 200 cap (unbounded work, amplified by the family change) | `project_export` now reads bounded keyset pages per family chat (`get_messages_page`, at most 200 newest per notebook across ≤2 pages), then the export-wide 200-message cap applies. | The 201-message cap test observed `101 != 200` with a single bounded page, then green with bounded paging (6 export tests passed). |
| **P2** After an ambiguous create, the draft payload stayed editable — a retry with edited title/text/selection hit the changed-operation refusal with misleading "nothing was created" copy | Both create dialogs freeze their editable payload after an ambiguous failure (draft title/text; development node selection and artifact type) so a retry is provably the same request and replays safely; the 422 copy now says an earlier attempt may already have saved the item and to check documents. | Component red-first: the draft title/type fields asserted enabled after the ambiguous failure (`expected false to be true`), then green; the develop dialog's checkbox/type assertions likewise (15 dialog tests passed). |
| **P3** Reference dedupe dropped a newer revision (the duplicate key ignored `revision`) | `canonical_references` now upgrades a duplicate entry in place when a strictly higher revision is supplied; absent/lower revisions keep the first entry, and revision-less lists keep exact legacy behaviour. | `10 passed` after the red run observed revision 1 kept where 3 was supplied. |
| **P2** A same-key create race surfaced a constraint error instead of a replay | `create` now catches a failed artifact INSERT, rolls back, re-reads the owner+notebook-scoped request row and replays it when the stored fingerprint matches (or is NULL), raises the changed-operation refusal on a mismatch, and re-raises unrelated failures unchanged. Version insert/commit stay outside the recovery. | Race reproduction observed `sqlite3.IntegrityError: UNIQUE constraint failed: student_artifacts.…request_id` before the fix, then replay; the changed-retry branch proved non-vacuous by a temporary mutation (`DID NOT RAISE`). |
| **P2** Existing DSQL clusters could never gain the student workspace tables/columns | New `plan_workspace_table_migrations` (+ inspect/apply seams, `--workspace-tables-only`, dry-run support) mirrors `dsql_schema.py` exactly: canonical CREATEs for absent tables, DSQL-safe `ALTER … ADD COLUMN name type` for the post-rollout columns (`kind`, `references_text`, `request_id`, `request_fingerprint`, version `references_text`), the five canonical async indexes (including the unique request index) and runtime GRANTs, one DDL per transaction with async-index waits. | 5 new tests failed with `AttributeError: … plan_workspace_table_migrations` before implementation; a canonical-comment parsing bug was caught by the fresh-shape parity test, then green (23 dsql tests passed). |
| **P2** Family scope excluded siblings when a child chat was requested | `notebook_family_ids` now returns the whole project — parent plus all children — from any member; export from a child includes parent and sibling conversations, and sibling evidence resolves across the project. | Child-request family observed `{child, parent}` missing two siblings, then green; a new export test pins the sibling message/title from a child-opened export. |
| **Test gap** The authoring writes had no DSQL adapter-path coverage (OCC whole-unit retry, request-id replay, fingerprint refusal, restore/delete semantics through `DsqlStudentStore`) | New `tests/persistence/test_authoring_dsql_occ.py`: 9 tests through the real `run_dsql_transaction` machinery with the established SQLite-backed fake-DSQL proxy (failures injected at the proxy, not monkeypatched; committed write units recorded for observable retry counts). The anticipated recovery-swallowing-40001 defect was investigated and does **not** exist — a mutation check confirmed the SQLite-level guard test is the one that catches it, and the adapter tests pin the observable contract. | 9 new tests; joint focused run with the existing DSQL deep-review suite: 14 passed. |
| **P2** Upgraded legacy DSQL clusters got NULL `kind`/`references_text` the read projections cannot render | The workspace planner now emits id-keyed, batched NULL-backfill UPDATEs after the DDL (`kind = 'notes'`, `references_text = '[]'`, version `references_text = '[]'`), ≤ 1000 rows per committed transaction per the DSQL row-limit rule, via one generalized batching mechanism shared with the revision backfills; idempotent rerun verified. `request_id`/`request_fingerprint` stay nullable by design. | Backfill test observed zero UPDATEs before the fix, then 5 exact id-keyed batches (1000+200, 1000+200, 3) with values verified and a clean rerun; 47 focused tests passed. |

**Reconciliation notes:** a draft in the shared tree asserted a different
contract for the same P1/P2 (`operation_id`/`provenance`/`ai_synthesis`); its
valuable changed-retry assertion was adopted (changed retries refuse) and its
test was rewritten to the implemented contract (`request_id`/`fingerprint`/
`origin='coach_draft'`). A broken untracked scratch
`tests/persistence/test_authoring_dsql_retry.py` (bad import, duplicate of the
passing red-first test) was removed.

#### Executed validation

| Command/check | Result |
| --- | --- |
| Joint focused set (guest sessions, artifacts, references, artifact/canvas HTTP, project export, OCC retry, suggestion acceptance) | **50 passed** |
| `npm test --prefix frontend` | **200 passed / 3 skipped** (31 files) |
| `npm run build --prefix frontend` / `npm run api:check --prefix frontend` | Exit 0 / exit 0 (contract regenerated once for `origin`/`request_id`) |
| `npm run test:browser --prefix frontend` | **13 passed** |
| `.venv/bin/ruff check .` / `compileall` | Exit 0 / exit 0 |
| Full mock suite | **Exit 0 — 3,416 passed / 1 skipped** (3,386 baseline + 30 new/updated backend tests across both review passes) |
| Hygiene | `git diff --check` clean; no leaked processes; nothing staged or committed |

#### Compatibility, rollback and limits

All persistence changes are additive with in-place legacy upgrades (rows
untouched, proven by tests); the contract change adds two optional fields, and
a create without `request_id` keeps the ordinary non-idempotent behaviour.
Rollback is source-only: revert the changed operations/reader/DSQL/schema/
migration/client/component files and their tests, and restore the two updated
test files.

Known limits, documented rather than silently accepted: a concurrent same-key
create can race between the replay read and the insert — the unique index
prevents the duplicate and the recovery replays the winner (a same-connection
aborted-transaction re-read is impossible because serialization-class failures
propagate before recovery); existing DSQL clusters need the explicit additive
`ALTER`s plus NULL backfills through the admin bootstrap
(`--workspace-tables-only`; runtime startup issues no DDL); replay returns the
artifact's current state if it was edited after creation; the family export
covers the direct parent and direct children only, reading at most the newest
200 messages per family notebook before the export-wide cap; the family
transcript labels chat titles only (ids stay out of the export); and after an
ambiguous create the dialogs freeze their payload — editing then requires
starting a fresh review, which is deliberate (one draft request can create at
most one artifact).

**Next exact action:** the user-reported five-finding review is closed. The
programme's remaining work is the separately gated external list in
`docs/operations/PROGRAMME_COMPLETION_REPORT.md` §6.

### TDD fixes for the six follow-up review findings (2026-11-26 SGT)

The six findings from the subsequent review are addressed using the approved
persistence, HTTP/component and browser seams. Each behavior regression was
observed failing before its implementation change.

| Finding | Behavior and files |
| --- | --- |
| Guest workspace transfer | `backend/student_store.py` transfers artifacts, canvases and both version histories in the notebook ownership transaction. The expanded `tests/persistence/test_guest_sessions.py` claim test failed when the account could not read its artifact, then passed with the account able to read the saved work and both histories. |
| Document-to-canvas transfer | `frontend/src/ArtifactToCanvasDialog.tsx` saves the revision of the graph being modified, merges an existing-node link into the current saved graph, and refuses a removed target. Its regression first demonstrated loss of a second node added after the dialog opened. |
| Stale AI feedback | `frontend/src/ArtifactFeedback.tsx` checks the proposal's base revision before applying any text. A mismatch or missing revision retains the editable proposal with instructions to copy it or request fresh feedback. Its regression first demonstrated acceptance over a newer document. |
| Document type | `frontend/src/App.tsx` forwards the chosen kind from the Documents tab. `frontend/tests/browser/artifact_type.spec.ts` verifies creation and reopening of a Reflection document through the built application. |
| Keyboard tabs | `frontend/src/NotebookPage.tsx` moves to the previous tab on ArrowLeft, including wraparound. The component regression first observed the opposite direction. |
| Mixed evidence references | `frontend/src/ArtifactEditor.tsx` retains reference kinds, canvas IDs and version origins when linking or detaching a source. The component regression first observed retained references being converted to sources. |

Compatibility requires no schema migration. These changes apply to new claim
transactions. Workspaces claimed before the fix may still have resources
under their former Guest owner and need a separately inventoried repair.
Source rollback can restore previous code, while ownership transfers already
committed retain their corrected owner IDs. The fixes preserve existing
uncommitted work and use disposable mock data for validation.

Executed validation on the combined tree passed. The full Python mock suite
reported 3,386 passed and 1 skipped (optional Strands dependency unavailable).
Vitest reported 194 passed and 3 skipped. Chromium reported 13 passed,
including the Reflection document regression, desktop and 390 px authoring,
and the integrated restart journey. The browser checks include console and
overflow assertions, and the editor desktop/mobile screenshots were inspected.
Production frontend build, TypeScript, ESLint, Ruff, compilation, offline API
schema/client drift and `git diff --check` passed. Vite retains its existing
large entry-chunk warning.

Next exact action is to include these corrections and their evidence in the
release candidate review. Any repair of previously claimed Guest workspaces
requires an inventory and a backed-up repair procedure before applying data
changes.

### Ticket 53 complete — programme verified and reported (2026-11-26 SGT, OpenCode)

**Ticket 53 closes the 53-ticket architecture-completion programme as
verification-and-reporting work with no code change: every feasible local
suite was re-run and recorded with actual numbers, the ledger and the ticket
graph were verified complete, the tree and secrets posture were checked, and
the comprehensive completion report now lives at
[docs/operations/PROGRAMME_COMPLETION_REPORT.md](operations/PROGRAMME_COMPLETION_REPORT.md).**
Final battery (all exit 0 unless noted): backend full mock suite **3,386
passed / 1 skipped** (the single historical Strands collection skip; pytest 9
suppresses the summary under `-q`, so the count was captured without it —
3,378 of those passes are this programme's tickets 01–52 evidence, 8 belong to
a parallel "codesign-fixes" writer session observed in the same tree on 26 Nov
and counted honestly as concurrent work, not claimed here); frontend
**190 passed / 3 skipped**; production build exit 0; `api:check` exit 0;
browser suite **12 passed** over 11 specs; `ruff check .` clean; compileall
exit 0; `git diff --check` clean; gitleaks git-history scan no leaks (the
working-tree `--no-git` scan reports only pre-existing untracked local runtime
data — none tracked, none introduced); ticket 51's release rehearsal driver
re-run exit 0 with no findings. Ledger verification: all 53 tickets have
entries with executed evidence (01–04 under the "Local completion ticket NN"
headings, 05–52 under "Ticket NN complete", 52 added this session), every
dependency edge in the approved graph resolves to acceptance evidence
(including 53's own blockers 3, 6, 34, 38, 40, 41, 42, 43, 44, 46, 49, 50,
51, 52), and the three newest entries' relative links all resolve. The report
states the honest remaining external gates — live AWS/Cognito verification,
real-model quality, runtime publication, live capacity/cost verification, the
unresolved S$30 objective, the formative study, the image inventory review and
the live additive DSQL migration — none of which this programme executed or
claims, and records the release manifest's **PREPARED-not-verified** status
and the exact working-tree state (nothing staged, committed or pushed; 106
modified + 133 untracked paths preserved; rollback = source-only).

#### New files and behavior

| File | Responsibility |
| --- | --- |
| `docs/operations/PROGRAMME_COMPLETION_REPORT.md` (new) | The comprehensive final report: executed final battery with actual numbers and the concurrent-session accounting note; per-milestone delivery table with evidence pointers into this ledger; requirement-coverage and architecture baseline→final comparison (retained/added/rejected-with-gates); the integrated student workflow; release posture (manifest PREPARED, rollback notes); the eight remaining external gates; the exact working-tree state; the next exact action. All relative links verified to resolve. |
| `docs/IMPLEMENTATION_STATUS.md` | This entry and the ticket 52 entry (same session), completing the 53/53 ledger. |

#### Executed validation

| Command/check | Result |
| --- | --- |
| `.venv/bin/python -m pytest --tb=no` | Exit 0, **3,386 passed / 1 skipped** in 206.76 s (3,378 programme + 8 concurrent-session tests; accounting in the report). |
| `npm test --prefix frontend` | **190 passed / 3 skipped** (30 files passed, 1 skipped). |
| `npm run build --prefix frontend` / `npm run api:check --prefix frontend` | Exit 0 / exit 0. |
| `npm run test:browser --prefix frontend` | **12 passed** (11 specs; 10 pre-programme + ticket 52's export spec + one concurrent-session spec). |
| `.venv/bin/ruff check .` / `compileall` / `git diff --check` | All pass / exit 0 / clean. |
| Leak checks | `gitleaks detect` (git mode): no leaks. `--no-git` working-tree scan: findings only in pre-existing untracked local data (`data/*.sqlite3-wal`, `.streamlit/secrets.toml`, vendored maps) — none tracked, none from this programme. |
| Ledger and graph verification | 53/53 tickets with executed evidence; blocker edges for 52 (19, 24, 25, 32) and 53 (3, 6, 34, 38, 40–44, 46, 49–52) all resolve to ledger entries; newest-entry relative links resolve. |
| Tree safety | `git status --short --branch`: branch unchanged at `4f12995`; staged set empty; nothing committed or pushed; the dirty ticket 01–52 tree preserved plus this session's files. |

#### Compatibility, rollback and known limits

- No code, schema, contract or generated file changed in this ticket — the
  only artifacts are two documentation files; rollback is trivially
  source-only and the release posture is unchanged from ticket 51 (manifest
  PREPARED, `actually_verified_live` entirely null, v36/v38/v39 not approved
  rollback targets).
- Limits recorded honestly in the report: all suites are mock-based and
  non-billable; the browser suite exercises the production build against a
  disposable stack but cannot prove live AWS or model behavior; the parallel
  codesign-fixes session's concurrent edits to the shared tree were counted in
  the final battery but are not attributed to this programme beyond the note.

#### Next exact action

The local programme is complete — 53/53 tickets evidenced. Remaining work is
the separately approved external gate list in
`operations/PROGRAMME_COMPLETION_REPORT.md` section 6 (release image inventory
review first, then capped live release verification per
`deploy/COORDINATED_RELEASE_REHEARSAL.md`). No further local ticket is queued.

### Follow-up from the tickets 01–49 review (2026-11-26 SGT)

The follow-up was implemented on the `4f12995` working tree alongside the
ticket 52 export changes. It addresses the code-review findings and supplies
local evidence for ticket 53. The prior execution entries below remain
historical. In particular, the revised ticket 49 scenario replaces the old
hourly Aurora DSQL estimate.

| Finding | Implemented behavior and files |
| --- | --- |
| Tickets 17 and 22, autosave | `frontend/src/useArtifactAutosave.ts`, `ArtifactEditor.tsx`, and `CanvasEditor.tsx` persist the draft base revision, keep trailing edits when an older save confirms, pause on conflict, and read the saved revision before replaying any uncertain save. Recovery requires an explicit decision for stale and legacy drafts. |
| Tickets 35 and 36, Deep Review | `backend/student_store.py` and `backend/coaching/execution.py` fence claims and invocation against the persisted marker, preserve ambiguous outcomes, and guard terminal writes. `backend/http/reader_deep_review.py`, the generated reader client, and `frontend/src/DeepReview.tsx` expose status, explicit start and job-bound cancellation. The Streamlit panel and its API client use the same service. |
| Saved-work layering and canvas deletion | `backend/workspace_service.py` owns the notebook checks for document and canvas saves and deletion. The Canvas tab requires confirmation of the displayed revision, and the persistence operation deletes the canvas and its history atomically. Existing inbound references retain provenance and links to the deleted target show unavailable. Other canvases can still save edits with those existing links. |
| Ticket 46, integrated browser evidence | `frontend/tests/browser/workspace_journey.spec.ts` exercises authoring, chat/canvas/artifact transfers, review of a suggestion, confirmation, recap, Home resume, and Deep Review through the production-built React frontend and a real mock FastAPI/SQLite restart. |
| Ticket 49, DSQL pricing | `scripts/cost_scenarios.py` and the shipped scenario use published DPU activity and GB-month rates. Unmeasured workload DPU quantities keep the three full totals unknown. The priced subtotals are S$30.90, S$82.89 and S$261.09 before credits, GST and any shared free allowance. The S$30 objective remains unresolved. See [Cost accounting](COST_ACCOUNTING.md). |

Local validation on the combined checkout passed: Python mock suite 3,386
passed and 1 skipped (optional Strands runtime missing), Vitest 190 passed and
3 skipped, and Chromium 12 passed, including the integrated journey and
ticket 52 export. Production frontend build, Ruff, ESLint, compilation,
offline OpenAPI and generated-client drift checks, Caddy configuration parsing,
and `git diff --check` passed.

The API additions are additive and present in both exact Caddy allowlists.
No schema migration is needed. A coordinated rollback uses the previous
frontend, backend and edge rules. An ordinary confirmed canvas deletion
removes the selected canvas and checkpoints. Recovery of deleted data
requires a workspace backup. Live DSQL, Cognito and paid provider behavior
remain outside the local validation.

**Next action:** carry the evidence from this follow-up into the ticket 53
requirements matrix alongside ticket 52, keeping live release gates open.

### Ticket 52 complete — selected project export (2026-11-26 SGT, OpenCode)

**Ticket 52 is implemented and locally verified: a student now selects which
saved documents and canvases to include, and the server assembles one bounded,
owner-checked portable project export from saved, authorized rows only.**
`GET /api/v1/reader/threads/{thread_id}/project/export` (schema-less, same
documented-download policy as the artifact/canvas/transcript exports) returns a
canonical JSON envelope combining the saved conversation (bounded transcript
projection), the exact student-facing summary and Thinking Path projections the
browser already reads (`reader_project_view` — no re-rendering service, no
model call), the selected artifacts (revision metadata, `origin` AI-provenance
marker, per-item references labeled with availability and originating revision)
and canvases (canonical graph), plus resolved source references. Bounds are
fail-closed: at most 12 artifacts / 12 canvases per request (parse-rejected
with 422 before any lookup), at most 200 transcript messages (truncation
labeled honestly), and a 1 MiB serialized-envelope cap that answers 422
instead of growing the response. Selections resolve only inside the owner's
notebook through the owner-bound store and the ticket 25 family-scoped
reference resolver; foreign or unknown artifact/canvas ids answer 404 with no
projection, unavailable references are labeled `available: false` and never
substituted, and workspace identifiers, owner identity and operational fields
never enter the envelope (pinned by test). The notebook page gained an
**Export** tab whose checkboxes drive the selection and download through the
new `downloadProjectExport` transport helper (same-origin, `no-store`,
cancellation, inert attachment). The edge allowlists gained the one exact
additive `project(/export)?` reader-GET alternation, pinned by the extended
edge-parity test; no contract regeneration was needed (the route is
schema-less like the other exports and no generated file was touched).

Starting revision/branch: `improvement/architecture-responsiveness` with the
dirty ticket 01–51 working tree preserved unchanged apart from this ticket's
files. Nothing staged, committed or deployed. Note: a parallel
"codesign-fixes" writer session was observed operating in this working tree
during validation (it refreshed the route-inventory test's deep-review/canvas
entries at 20:34 SGT while preserving this ticket's `project_export` entry);
all of this ticket's files were re-verified intact afterwards.

#### New files and behavior

| File | Responsibility |
| --- | --- |
| `backend/project_export.py` (new) | Pure bounded export assembly: `selected_ids` (comma-separated parse, dedupe, per-kind limits, malformed-id rejection), `build_project_export` (envelope from the student-facing `ReaderProject` projection, bounded transcript, resolved artifact/canvas rows; reference labels drop internal ids and keep title/availability/originating revision), `serialize_project_export` (canonical JSON with the 1 MiB fail-closed cap). No store, settings or provider import. |
| `backend/http/notebook_reader.py` | New schema-less `GET .../project/export` route: owner/thread 404 gate, bounded selection parse (422), per-item owner resolution (404 on foreign/unknown), reuse of `reader_project_view`, sanitized `-project.json` attachment with `nosniff`/`no-store`. Route inventory contract updated with the `project_export` entry. |
| `Caddyfile`, `Caddyfile.local` | One additive exact alternation `project(/export)?` in the reader GET matcher so the built frontend's export download passes the edge; nothing else changed. |
| `tests/http/test_reader_project_export.py` (new) | Red-first contracts: assembly with provenance and download policy (the red run also exposed a real title-shadowing defect in the first builder draft — caught before ledgering, fixed); foreign/unknown/unauthenticated 404/401 boundaries; fail-closed bounds; unavailable-reference labeling plus restart persistence (identical envelope from a fresh backend). **4 passed.** |
| `frontend/src/api/client.ts` + `src/api/projectExportDownload.test.ts` (new) | `downloadProjectExport` transport helper and its red-first policy test (path, `artifacts`/`canvases` query, same-origin, `no-store`, abort propagation). |
| `frontend/src/NotebookPage.tsx` + `src/NotebookPageExport.test.tsx` (new) | "Export" tab on the notebook page: checkbox selection over the saved document/canvas lists (loaded on demand), explicit download button with honest busy/status/error copy; red-first component test asserts only the ticked ids travel to `/project/export`. |
| `frontend/tests/browser/project_export.spec.ts` (new) | Browser-suite regression: guest signs in on the production-built reader, seeds a notebook + document + canvas through the same-origin API, selects exactly that work on the notebook page and downloads; asserts the `-project.json` filename and the envelope (`kind`, title, exactly the selected artifacts/canvases) with zero unexpected console errors. |
| `tests/test_deployment_config.py`, `docs/deploy/COORDINATED_RELEASE_REHEARSAL.md`, `backend/AGENTS.md` | Edge-parity test extended (red first) to require `/project/export` in both edge files; runbook edge description names the new route; backend guide gains the `project_export.py` row. |

#### Executed validation

| Command/check | Result |
| --- | --- |
| `pytest tests/http/test_reader_project_export.py` | **Red first** (route absent → 404), then green; during the first green run the envelope title assertion exposed the builder's `title` loop-variable shadowing the parameter — fixed before any test was weakened. **4 passed.** |
| `pytest tests/test_architecture_contracts.py` | Route-inventory test **red first** (extra `project_export` route), then green after the inventory entry. |
| `pytest tests/test_deployment_config.py::test_production_edge...` | **Red first** (`project/export` not allowlisted), then green after the exact `project(/export)?` alternation in both Caddyfiles. Full file **24 passed**; `scripts.release_rehearsal` re-run exit 0, findings `[]`. |
| Frontend transport/component tests | Both **red first** (missing helper / missing Export tab), then green. |
| Full mock suite | Exit 0, **3,378 passed / 1 skipped** (ticket 51's 3,374/1 + this ticket's 4 new backend tests — accounting exact; the summary line was captured without `-q` because pytest 9 suppresses it in quiet mode). |
| `npm test --prefix frontend` / build / `api:check` / `test:browser` | **181 passed / 3 skipped** (baseline 179 + 2 new); build exit 0; api:check exit 0 (schema-less route, generated files untouched); browser suite **11 passed** (baseline 10 + this ticket's spec). |
| `.venv/bin/ruff check .` / `compileall` / `git diff --check` / leak check | All pass / exit 0 / clean. Gitleaks git-history mode: no leaks. Working-tree (`--no-git`) mode reports findings only inside pre-existing untracked local runtime data (`data/*.sqlite3-wal`, `.streamlit/secrets.toml`, vendored maps) — none in this ticket's files, none tracked. |
| Focused regression re-run after the concurrent-session edit | `tests/test_reader_project_export.py + test_architecture_contracts.py + test_deployment_config.py` **37 passed**; the three touched frontend transport/component tests **3 passed**. |

#### Compatibility, rollback and known limits

- Fully additive: one new schema-less GET route, one new pure module, one edge
  alternation, one frontend helper/tab. No existing route, contract file,
  projection or schema changed; rollback is source-only (revert the listed
  files; no migration, no data change, no generated file touched).
- The export is a projection of already-saved rows: nothing new is persisted,
  so version restoration and restarts are covered by the existing persistence
  guarantees plus this ticket's restart test.
- Limits: the envelope carries per-item revision metadata but is not an
  archival manifest of every historical version (version history remains in
  the app's version routes); canvas node references inside an exported graph
  keep their saved form (the same shape as the existing canvas JSON export);
  unavailable source references are labeled but cannot be named, because
  naming them would require substituting data that no longer resolves.
- The transcript bound (200 messages) and size cap (1 MiB) are first bounds,
  chosen to exceed any legitimate single-notebook selection seen in the
  classroom-scale work; they are constants in one module if measurement later
  demands different values.

#### Next exact action

Ticket 53 (Verify and report the complete programme) — its final blocker (this
ticket) now has acceptance evidence in the ledger. It is verification and
reporting work: re-run the full validation battery, verify the ledger and the
tree, and write the comprehensive completion report with the honest remaining
gates (live AWS/Cognito, real-model quality, runtime publication, live
capacity/cost, the S$30 objective, the formative study — all separately
approved external work).

### Ticket 51 complete — coordinated release and rollback rehearsal prepared (2026-11-26 SGT, OpenCode)

**Ticket 51 is implemented and locally verified as preparation-only work: the
coordinated release is documented, the exact edge drift is fixed in repository
defaults, and the disposable rehearsal driver runs green — with no deployment,
no live migration, no publication and no model call anywhere in the ticket.**
Three state-changing findings were fixed red-first at the repository-defaults
level: (1) the production and local Caddy allowlists did not permit the
artifact/canvas reader routes (CRUD, versions, restores, exports, `workspace`)
or any PUT save that the built React workspace and its generated reader contract
require — the built frontend's saved workspace would have been 404'd at the edge
while every test bypassing Caddy stayed green; the fix is additive and exact
(bounded PUT matcher, unchanged `/ready`, professor and wildcard-404 posture,
documented local bootstrap difference preserved); (2) the `.dockerignore`
excludes the ticket-04 audit's `.agents/`, `.playwright-cli/` and `.scratch/`
planning state from the release image build context (no image was built; the
image inventory review still precedes release); (3) a new offline rehearsal
driver, `scripts/release_rehearsal.py`, rehearses the coordinated configuration
on disposable data only — configuration (stage flags, guardrail 4, immutable
image placeholder, session generation, edge privacy, reader-contract↔edge
parity, direct links), contracts/builds (35-path reader contract, production
`dist/` identity), coordinated startup (real API on disposable SQLite with mock
adapters: health 200, readiness 200, and the production fail-closed validation
refuses the mock tuple), and backup/restore (delegates to the ticket-47
workspace recovery rehearsal, exit 0). The new [versioned nonsecret
manifest](examples/deployment/release-rehearsal-ticket51-2026-11-26.json) keeps
repository defaults, last recorded deployment (2026-11-24 restoration, carried
forward unchanged) and `actually_verified_live` as three strictly separate
sections — the last entirely `null` — and the new [coordinated release
runbook](deploy/COORDINATED_RELEASE_REHEARSAL.md) records ordered release steps
(frontend build → backend image → generated contracts → additive migrations →
exact Caddy allowlists → runtime versions), backup/restore, health/readiness and
direct-link checks, Mantle-preservation verification for rollout **and**
rollback, and the known-good rollback procedure. **Manifest readiness status:
PREPARED, not verified** — repository-default configuration is rehearsal-verified;
live state remains unknown and every live step stays gated by the existing
release checklist and safety record, which are linked, not closed.

Starting revision/branch: `improvement/architecture-responsiveness` with the
dirty ticket 01–50 working tree preserved unchanged apart from this ticket's
files. Nothing staged, committed or deployed.

#### New files and behavior

| File | Responsibility |
| --- | --- |
| `Caddyfile`, `Caddyfile.local` | Additive exact allowlist fix: reader GET gains `artifacts(/id(/versions(/rev)?)?|/export)`, `canvases(…)` and `workspace`; reader POST gains artifact create/delete/duplicate/version-restore and canvas create/version-restore; a new bounded `@writer` PUT matcher allows only `threads/<id>/(artifacts|canvases)/<id>`. `/api/v1/ready`, professor/admin APIs and the `/api/*` 404 fallthrough unchanged; the documented local bootstrap omission unchanged. |
| `.dockerignore` | Excludes `.agents/`, `.playwright-cli/`, `.scratch/` (and `.impeccable/`) from the release build context per the ticket 04 privacy audit routing. |
| `scripts/release_rehearsal.py` (new) | Offline coordinated-release rehearsal driver: JSON report on stdout, exit 2 on findings, `--config-dir` for candidate configurations, no flag that can select real data; the `--serve` child boots only inside a driver-created token-marked temp tree with deterministic mock adapters (guard mirrors the ticket-47 pattern); includes the negative check that `validate_production_configuration` refuses the mock tuple. |
| `docs/examples/deployment/release-rehearsal-ticket51-2026-11-26.json` (new) | Manifest schema v2: `repository_defaults` (current working-tree hashes incl. the fixed `Caddyfile`/`.dockerignore` and built `dist/index.html`), `last_recorded_deployment` (ticket 04 evidence carried forward, with the v36/v38/v39 not-safe-for-rollback note) and `actually_verified_live` (all null, blocking), plus ordering, rehearsal status and compatibility/rollback contracts. Nonsecret: no ids, tokens, prompts or account locators. |
| `docs/deploy/COORDINATED_RELEASE_REHEARSAL.md` (new) | The prepare-only runbook: three-state manifest rule, what changed in the coordinated configuration, the eight ordered release steps, backup/restore requirements, Mantle-preservation checks for rollout and rollback, known-good rollback summary, and the disposable rehearsal evidence with its honest limits. |
| `tests/test_deployment_config.py` | Red-first: `test_production_edge_allows_the_built_reader_contract_and_keeps_internal_routes_private` (every reader-contract route + export routes must match the edge, `/ready` and near-miss paths must not), `test_caddy_local_omits_only_the_documented_bootstrap_difference` (local edge parity minus bootstrap), and the extended docker-context test requiring the three planning directories. |
| `tests/scripts/test_release_rehearsal.py` (new) | Red-first driver contracts: the default rehearsal passes with per-stage aggregate evidence on repository defaults and a throwaway tree; a candidate edge file that exposes `/ready` fails with exit 2 and a named finding. **2 passed.** |
| `docs/README.md`, `docs/PRODUCTION_RELEASE_CHECKLIST.md`, `docs/deploy/DEPLOYMENT_SAFETY_RECORD.md` | Incoming links to the new runbook and manifest; the checklist reconciliation block points to ticket 51's prepared configuration; the safety record marks the packaging finding resolved (image inventory review still pending) and replaces the "ticket 51 owns" forward reference with the concrete links. All relative links verified to resolve. |

#### Executed validation

| Command/check | Result |
| --- | --- |
| `pytest tests/test_deployment_config.py` | **Red first** (no `writer` matcher; missing `.dockerignore` entries), then green after the exact fixes. **24 passed.** |
| `pytest tests/scripts/test_release_rehearsal.py` | **Red first** (`No module named scripts.release_rehearsal`), then green after the driver; iterative corrections recorded: malformed compose-value regex, a `Path` used where text was required, the missing startup temp directory, and the disposable child initially launched without its guard token (caught because the guard fail-closed as designed). **2 passed.** |
| `.venv/bin/python -m scripts.release_rehearsal` | Exit 0; configuration/contracts_and_builds/coordinated_startup/backup_restore all `pass`; findings `[]`; backup/restore delegated to the workspace recovery rehearsal with exit 0. |
| Full mock suite | Exit 0, **3,374 passed / 1 skipped** (the historical single Strands skip; ticket 50's 3,370 + this ticket's 4 new tests — accounting exact). |
| `npm test --prefix frontend` / build / `api:check` / `test:browser` | **179 passed / 3 skipped**; build exit 0; api:check exit 0 (no contract change; generated files never hand-edited); browser slice **10 passed**. |
| `.venv/bin/ruff check .` / `compileall` / `git diff --check` / leak & link checks | All pass / exit 0 / clean / no AWS or network use beyond loopback rehearsal sockets; all edited docs' relative links resolve. |

#### Measured rehearsal results (disposable local data; NOT a live or production claim)

| Stage | Evidence |
| --- | --- |
| configuration | Stage flags `STUDENT_STAGE_SELECTION=true` / `AUTO_ADVANCE_STAGES=false`; guardrail version 4; `APP_IMAGE` immutable placeholder; session generation recorded; `/ready` private; `/api/*` 404 fallthrough; 6/6 direct-link paths allowlisted; reader-contract↔edge parity true (35 contract paths + 2 schema-less export routes). |
| coordinated_startup | Real API child on disposable SQLite with mock adapters: `/api/v1/health` 200 (`mode: local` — the rehearsal substitute, recorded honestly), `/api/v1/ready` 200; `APP_ENV=production` validation of the same tuple rejected (fail-closed gate proven negative). |
| backup_restore | `scripts.workspace_recovery_rehearsal` exit 0 in ~6 s on its synthetic disposable workspace. |
| manifest readiness | **PREPARED**: `repository_defaults` verified by rehearsal; `last_recorded_deployment` carried forward; `actually_verified_live` entirely null. Not verified, not deployed. |

#### Compatibility, rollback and known limits

- The edge fix is additive and exact: no previously allowed route is removed,
  no wildcard introduced; the coordinated invariant "every reader-contract route
  passes the edge; `/ready` and professor routes never do" is now test-pinned in
  both edge files.
- Rollback safety notes are explicit in the manifest and runbook: v36/v38/v39
  artifacts predate the Mantle provisional-output suppression and are not
  approved rollback targets; session generation must change again on rollback;
  additive DSQL columns stay during app rollback.
- Limits: the rehearsal boots the API in development/mock mode (production
  fail-closes on mocks by design — recorded as `mode: local`); no image was
  built so the image inventory review remains open; the Docker daemon is
  unavailable locally, so no container-level Compose rehearsal was possible;
  Caddy itself is not installed locally, so edge matchers are verified by
  regex semantics (pinned by tests) rather than a live `caddy validate` run —
  the CI workflow already runs that validation; `Caddyfile.local` still omits
  bootstrap GET by documented design.

#### Next exact action

Ticket 52 (Export selected project coursework) — its blockers 19, 24, 25, 32
all have acceptance evidence in the ledger. Start it in a fresh writer session
with the ticket file, the approved spec's export requirements (source sections
50–52), `docs/IMPLEMENTATION_STATUS.md` ticket 51 entry for the current
validation baseline, and the prior-art export/projection modules
(`backend/artifact_export.py`, `backend/canvas_export.py`, reader routes and
their defense-sweep tests). Ticket 53 remains blocked by 52 (and this ticket's
50/51 evidence is now recorded).

### Ticket 50 complete — extended authorised aggregate engagement signals (2026-11-26 SGT, OpenCode)

**Ticket 50 is implemented and locally verified as an additive, metadata-only
extension of the audited lecturer aggregate endpoint.**
`GET /api/v1/professor/learning-funnel` now returns an additional `engagement`
section alongside the unchanged lecture-help and project-work measures, within
the existing consent and access rules: same persisted lecturer/admin
authorization, same fail-closed `research_access_events` audit, same
active-branch and student-role predicates. The eleven new counts — returning
owners (saved student turns on ≥2 distinct UTC days), forward stage
progression, artifacts authored and saved artifact revisions, canvases explored
and saved canvas revisions, Deep Review job presence (any state), classified
student turns split project-coaching vs lecture-help, notebooks without saved
turns, and notebooks with saved error rows — each carry a numerator, an
eligible denominator and a unit, and are explicitly defined as **activity
signals, not evidence of educational quality**; the limitations list says so and
artifact/canvas/review content never leaves the aggregate (no titles, documents,
graphs or review identifiers). Implementation is metadata-only: the analytics
repository's `load_learning_rows` gains additive per-notebook SQL counts
(artifact/canvas presence and revision saves) plus notebook settings read solely
to detect a recorded Deep Review job; no schema, route or authorization change.
The protected Streamlit lecturer surface and the audited API are unchanged — no
React lecturer charts were added (they remain conditional future work per spec
section 94), and existing aggregate-endpoint privacy tests stayed green.

Starting revision/branch: `improvement/architecture-responsiveness` with the
dirty ticket 01–49 working tree preserved unchanged apart from this ticket's
files. Nothing staged, committed or deployed.

#### New files and behavior

| File | Responsibility |
| --- | --- |
| `backend/learning_signals.py` | `LearningFunnel.engagement: dict[str, FunnelCount] = {}` plus the projection logic: per-notebook artifact/canvas counts and revision saves (keyed per notebook because every message row repeats notebook-level values), Deep Review job detection from notebook settings, returning-owner days, forward stage movement via `STAGE_BY_ID` ordering, classified-turn split, notebooks-without-turns and notebooks-with-errors; eleven new definition strings and an activity-signal limitation. Existing fields and counts unchanged. |
| `backend/professor_analytics/repository.py` | `load_learning_rows` SELECT gains additive per-notebook subquery counts (`student_artifacts`/`student_canvases` presence and revision saves) and `notebook_settings_text` (read only for a recorded Deep Review job). Predicates, exclusion rules and row identity unchanged; no text content added. |
| `tests/http/test_learning_funnel.py` | Red-first `test_engagement_section_aggregates_activity_within_existing_authorization`: student 403 vs lecturer 200 on the same aggregate; all eleven counts with exact numerators/denominators (including the quiet second owner and the saved error row); a definition for every engagement key; the activity-signal limitation; and privacy assertions that the artifact/canvas titles and review id never appear. The prior session's fixture (invalid artifact/canvas documents) was corrected so the test failed for the intended reason (`KeyError: 'engagement'`) before implementation. |
| `docs/LEARNING_BASELINE.md` | New "Engagement activity extension (ticket 50)" subsection: what is counted, the metadata-only mechanism, the activity-not-quality boundary, and the unchanged lecturer surface/no-React-charts statement. |

#### Executed validation

| Command/check | Result |
| --- | --- |
| `pytest tests/http/test_learning_funnel.py` | **Red first** — after the fixture correction, `KeyError: 'engagement'`; then green. **8 passed.** |
| `pytest tests/http/test_professor_analytics.py tests/http/test_professor_research.py tests/test_architecture_contracts.py` | **48 passed** — existing aggregate endpoints, privacy tests and route inventory unchanged and green. |
| Full mock suite | Exit 0, **3,370 passed / 1 skipped** (the single historical Strands skip). Note: ticket 49's ledger recorded 3,368 passed / 1 skipped; exactly one test file changed in `tests/` for this ticket (+1 test), so the residual +1 pass vs. the prior ledger's arithmetic is an accounting drift in the earlier entry, not an untracked test. |
| `npm test --prefix frontend` / build / `api:check` / `test:browser` | **179 passed / 3 skipped** (unchanged baseline); build exit 0; api:check exit 0 (the `LearningFunnel` response field is additive and the reader contract is untouched); browser slice **10 passed**. |
| `.venv/bin/ruff check .` / `compileall` / `git diff --check` / leak check | All pass / exit 0 / clean / no background processes, no AWS, no network. |

#### Measured engagement signal inventory (the new aggregate section)

| Count | Definition (numerator / denominator) |
| --- | --- |
| `returning_students` | Owners with saved student turns on ≥2 distinct UTC days / owners with ≥1 saved student turn (owner identities) |
| `stage_progression` | Notebooks whose stage-tagged turns span a forward stage move / notebooks with a stage-tagged project turn |
| `artifacts_authored` | Notebooks with ≥1 saved artifact / all notebooks |
| `artifact_revisions_saved` | Saved artifact revision saves beyond creation / notebooks with ≥1 artifact |
| `canvases_explored` | Notebooks with ≥1 saved canvas / all notebooks |
| `canvas_revisions_saved` | Saved canvas revision saves beyond creation / notebooks with ≥1 canvas |
| `coaching_turns` | Saved project-coaching student turns / classified saved student turns |
| `lecture_help_turns` | Saved lecture-help student turns / classified saved student turns |
| `deep_reviews` | Notebooks with a recorded Deep Review job (any state) / all notebooks |
| `notebooks_without_saved_turns` | Notebooks without a saved non-error student turn / all notebooks |
| `notebooks_with_saved_errors` | Notebooks with a saved error row / all notebooks |

All are activity signals, never learning quality; `human_reviewed_substantive_stage2_notebooks` remains `null`, and Lecture help vs Project coaching stay separate.

#### Compatibility, rollback and known limits

- Fully additive: the new response key defaults to empty for any consumer that
  constructs the model; the Streamlit lecturer panels and the audited API are
  untouched; rollback is a revert of the two backend files and the test with no
  schema or data migration involved (the SQL change is read-only).
- Limits: counts come from the active conversation branch and current
  artifact/canvas revisions only (revised-away work excluded, as before); Deep
  Review presence is job metadata, not review judgement; Guest cookies and
  multiple notebooks can still duplicate people; no statistical claim is made.

#### Next exact action

Ticket 51 (Prepare a coordinated release and rollback rehearsal) — its blockers
04, 10, 11, 12, 13, 19, 24, 45 and 47 all have acceptance evidence in the
ledger. Start it in a fresh writer session with the ticket file, the approved
spec's sections 85–89, `docs/IMPLEMENTATION_STATUS.md` ticket 50 entry, and the
prior art `docs/PRODUCTION_RELEASE_CHECKLIST.md`,
`docs/deploy/DEPLOYMENT_SAFETY_RECORD.md` with the ticket 04 manifest,
`compose.prod.yaml` and `Caddyfile`.

### Ticket 49 complete — model operating costs and regional trade-offs (2026-11-26 SGT, OpenCode)

**Ticket 49 is implemented and locally verified as a documentation/measurement
ticket with no application behavior change.** A new offline scenario renderer —
`scripts/cost_scenarios.py` plus the shipped configuration
`docs/examples/cost-scenarios/scenarios-2026-11.json` — produces reproducible
low/expected/high monthly SGD operating-cost scenarios from **dated
public-pricing estimates** (as-of recorded on every line, mostly 2025-10
knowledge; Aurora DSQL 2024-12 announcement knowledge), **measured local
anchors** from tickets 38/39/40/48 plus the separately capped 2026-11-24 live
checks, and **documentation-based regional trade-off rows** — with no live
call, no AWS access and no network use anywhere in the tool. Totals reuse the
ticket-07 inventory semantics (all nine categories, estimate-only gross,
credits/cash honestly null, gross as the post-credit baseline) and the S$30
objective is assessed as **unresolved**: the rendered estimates (low S$65.45 /
expected S$170.02 / high S$607.08, before GST and credits) do not demonstrate
`C + H <= S$30`, dominated by the assumed 24/7 Aurora DSQL compute line whose
utilisation and minimum-billing granularity are the largest recorded unknowns.
No S$30 pass is claimed, no region migration is proposed, and the existing
classroom cost/capacity release gates remain open. Triage remains
`ready-for-agent`; nothing is staged, committed or deployed.

Starting revision/branch: `improvement/architecture-responsiveness` with the
dirty ticket 01–48 working tree preserved unchanged apart from this ticket's
files.

#### New files and behavior

| File | Responsibility |
| --- | --- |
| `scripts/cost_scenarios.py` (new) | Offline scenario renderer: pydantic-validated configuration (estimate lines require quantity, dated `price_as_of` and evidence; unknown lines must leave quantities/prices null and suppress the scenario total; not-applicable lines require explicit zeros with reasons; every scenario must cover all nine inventory categories), SGD conversion via an explicit planning FX rate, per-scenario gross/credits/cash/post-credit output with `bill_verified: false`, measured-vs-assumed-vs-unknown quantity labels, an S$30 assessment that can only report `unresolved`, and regional rows where only recorded datapoints may claim `measured` latency. CLI prints JSON; invalid input exits 2 without echoing content; module imports no network/AWS/database client (AST-checked). |
| `docs/examples/cost-scenarios/scenarios-2026-11.json` (new) | The shipped reproducible configuration: low (6 students, ~20 turns each), expected (24 students, ~40 turns) and high (80 students, ~80 turns) scenarios over the documented 24/7 us-west-2 topology (EC2, EBS, Aurora DSQL, S3, CloudFront, Cognito Lite, AgentCore Haiku 4.5 + Sonnet 4.6 Deep Review, Guardrails v4, MANAGED Knowledge Base); explicit zero lines for Cognito free tier, AWS Basic support, docker json-file logging (no CloudWatch shipper), unverified GST treatment, and hosted editor/canvas services (React Flow/Tiptap are client-side only — no hosted service required); six measured anchors sourced to tickets 38/39/40/48 and the 2026-11-24 live checks; eight regional rows (CloudFront edge, EC2, DSQL, Bedrock models, AgentCore, KB, Cognito, and the recorded bounded live latency datapoints) each stating data-residency considerations and that no automatic region migration is performed. |
| `tests/scripts/test_cost_scenarios.py` (new) | Red-first harness contracts: the shipped config renders three complete scenarios; estimate lines are dated with evidence while not-applicable lines carry zero gross plus reasons; estimated totals increase low < expected < high with `bill_verified: false` and a "not a bill" note; measured anchors reference tickets 38/39/40/48 and are labelled measured; credits/cash/runway stay null with a post-credit baseline note; the S$30 assessment stays `unresolved` naming all three totals; regional rows cite `compose.prod.yaml`/us-west-2, allow measured latency only with a recorded source, and always state no automatic region migration; an unknown-basis line nulls the scenario total and is named in `unknowns`; invalid config exits 2 with empty stdout; an AST check forbids network/AWS/database imports. **10 passed.** |
| `docs/COST_ACCOUNTING.md` | New "Scenario planning and regional trade-offs (ticket 49)" section: the reproducible command, the rendered totals with their largest lines, the honest S$30 assessment and pathways, the measured anchors, the regional trade-off summary (us-west-2 deployment vs Singapore students, estimated ~170–200 ms long-haul RTT, unknown DSQL/model/runtime/KB/Cognito latency, unverified ap-southeast-1 availability, residency as an owner/compliance decision), and the credits/cash/post-credit semantics. |
| `docs/operations/CLASSROOM_CAPACITY_GATE.md`, `docs/TESTING.md`, `scripts/AGENTS.md`, `tests/AGENTS.md` | Pointer from the cost/decision record and the testing guide to the scenario renderer, plus script/test-map rows. |

#### Executed validation

| Command/check | Result |
| --- | --- |
| `pytest tests/scripts/test_cost_scenarios.py` | **Red first** (`FileNotFoundError` — the script did not exist), then green after the renderer and shipped config; iterative corrections recorded: the category validator first required exactly one line per category, but multi-line categories (EC2 + EBS + DSQL under `hosting`) match `cost_report` semantics, so the validator and test were relaxed to "cover every category at least once". **10 passed.** |
| `.venv/bin/python -m scripts.cost_scenarios --config docs/examples/cost-scenarios/scenarios-2026-11.json` | Exit 0; rendered low S$65.445250 / expected S$170.017900 / high S$607.084400 (see measured/estimated table below). |
| Full mock suite | **Exit 0, 3,369 collected → 3,368 passed / 1 skipped** (the historical single skip: `test_strands_first_cycle_middleware` cannot import the absent `strands` module; baseline 3,359 + this ticket's 10 new tests). |
| `npm test --prefix frontend` / `npm run build --prefix frontend` / `npm run test:browser --prefix frontend` | **179 passed / 3 skipped** (unchanged baseline); build exit 0; browser slice **10 passed**. `npm run api:check` not run — no route or schema change. |
| `.venv/bin/ruff check .` / `compileall` / `git diff --check` / leak check | All pass / exit 0 / clean / no background processes started. |

#### Estimated scenario results (actual rendered output; ALL figures are estimates, not a bill)

Rendered 2026-11-26 from `docs/examples/cost-scenarios/scenarios-2026-11.json`
(FX planning rate 1.30 SGD/USD; before GST; before credits; every line is a
dated public-pricing estimate from model knowledge — never fetched from AWS,
never reconciled with a bill):

| Scenario | Students | Estimated gross S$/month | Largest contributing lines (estimate) |
| --- | ---: | ---: | --- |
| low | 6 | 65.445250 | DSQL compute 33.215 + EC2 t3.small 19.739 + EBS 3.12 |
| expected | 24 | 170.017900 | DSQL compute 83.038 + EC2 t3.medium 39.486 + model tokens ≈30.6 |
| high | 80 | 607.084400 | DSQL compute 332.150 + model tokens ≈152.1 + AgentCore runtime 46.8 |

S$30 assessment: **unresolved** — even the low scenario exceeds the objective
under these estimates, dominated by the assumed 24/7 DSQL compute line
(utilisation 0.1/0.25/1.0 DSQLU-hours assumed over 730 h at US$0.35, minimum
billing granularity unverified — the dominant planning unknown). Feasibility
requires verified billing evidence for C plus separately approved headroom with
`C + H <= S$30`; bounded hours, a SQLite/S3 envelope, verified lower
utilisation or credits are operator decisions, none taken here. Measured
anchors (labelled, never treated as live cost truth): ticket 48 write-volume
proxy (233,472 → 3,420,160 store bytes across the 80-student run) and autosave
p95s (≤39.5 ms artifact / ≤27.3 ms canvas); ticket 38 fresh-connection
simulation (~31 ms/transaction, not live DSQL); ticket 39 bounded admission
overload; ticket 40 measured prompt sizes (p50 ≈7,719 estimator tokens; one
recorded live smoke at 6,366 real input tokens); the 2026-11-24 capped live
checks (US$0.9800952 cumulative reservations ≈ US$0.0123/direct Gemma request —
a different model from the deployed Haiku 4.5). Regional: documented deployment
is us-west-2 while students are in Singapore (estimated ~170–200 ms long-haul
RTT per dynamic request; CloudFront edges only cover static assets);
Singapore→DSQL/model/AgentCore/KB/Cognito latency recorded **unknown** (never
measured here); DSQL in ap-southeast-1 not known from 2025 knowledge and Haiku
4.5 ap-southeast-1 availability expected but unverified; data residency is
flagged as an owner/compliance decision; **no automatic region migration is
performed or proposed**.

#### Compatibility, rollback and known limits

Purely additive documentation/tooling: a new script, config example, test file
and doc rows; no application, schema, contract, frontend or deployment change,
and rollback is delete-only. Known limits, documented rather than silently
accepted: every price is unverified dated knowledge and must be replaced by
billing evidence before any gate decision; the DSQLU utilisation model,
token-per-turn figures (anchored to ticket 40's estimator measurements), turn
counts, transfer volumes and KB-query estimates are assumptions; the DSQL
compute estimate is the dominant uncertainty and could move totals by hundreds
of SGD either way; GST treatment and credits are unknown; regional latency is
unmeasured and no live regional probe was run (any live probe needs fresh
capped approval per the classroom gate); the S$30 gate is reported unresolved
by construction — this tool can never resolve it.

**Next exact action:** ticket 50 — extend authorised aggregate engagement
signals — is unblocked (32/33/36 complete) and is next in this session per the
assignment; ticket 51 follows, then stop. 52 is also eligible; 53 waits on
49/50/51/52.

### Ticket 48 complete — measure mixed classroom workloads locally (2026-11-26 SGT, OpenCode)

**Ticket 48 executed the stepped 1/10/20/40/60/80-student synthetic mixed
classroom workload locally, mock-only, and recorded honest per-operation
latency/queueing/OCC/reconciliation evidence with explicit workload,
environment and sample-size limitations — no application behavior changed.**
The session first re-verified the resume evidence: ticket 46's
`mock-ci.yml`/`dependency-audit.yml` carry the deterministic set (mock Pytest
with collection, Ruff, `compileall`, schema/client drift, production build with
`tsc`, frontend lint, bundle measurement, pinned gitleaks, Playwright slice,
scheduled `pip-audit`), and ticket 47's `scripts/workspace_recovery_rehearsal.py`
was re-run green end to end (exit 0: 3 messages, 1 source, artifact/canvas at
revision 3, 1 recap, Deep Review `completed`, integrity `ok`, restart +
fresh-location restore + owner boundary 404s all passing). Work then resumed on
the probe script and harness test the interrupted session had already authored
(untracked, unexercised at scale): their three contracts were verified green
(including a real two-student mixed wave), the leftover "TEMPORARY DEBUG"
limiter-counting scaffolding was removed as dead code, and one genuine
measurement defect was diagnosed and fixed red-first.

**The defect (probe fixture, not application):** the probe pinned
`COACH_REQUESTS_PER_MINUTE=10000`, but `backend/settings._bounded_int`
silently restores the documented **default (8 RPM/owner)** for out-of-range
values, so the first full 80-student run produced 22 honest-but-artifactual
`user_rpm` rejections — 2 at level 60 and 20 at level 80, exactly the pattern
predicted by an 8-request rolling 60-second window against owners who
accumulate turns across waves (the level-1 owner trips at 60; the level-1 and
nine level-10 owners trip at 80). Every rejected turn was verified unsaved
through the idempotency recovery read and reconciliation stayed at zero
losses/duplicates, so the limiter behaved exactly as configured; the
measurement was simply measuring the wrong ceiling. Fix: pin the documented
production value (120, per the settings comment "Production Compose sets 120"),
and a new harness test asserts every probe limiter pin survives the settings
bounds — red first (the pin read back as the 8 default), then green. The
definitive run with the corrected pin had **zero** `user_rpm` rejections and
zero admission rejections. Separately capped live procedures are documented as
prepared-and-never-executed in `docs/operations/CLASSROOM_CAPACITY_GATE.md`.

Starting revision/branch: `improvement/architecture-responsiveness` with the
dirty ticket 01–47 working tree preserved unchanged apart from this ticket's
files.

#### New files and behavior

| File | Responsibility |
| --- | --- |
| `scripts/mixed_workload_probe.py` (new) | Stepped mixed-workload probe: at each level (1/10/20/40/60/80 persistent authenticated Guest HTTP sessions) a barrier-released wave mixes startup (guest start, notebook create, source + private attachment upload, artifact/canvas create) for new students and, for every student, navigation reads, one ordinary coaching turn, one source-grounded turn (citation required), a deliberate two-tab same-revision artifact OCC race (one 409 + fresh-base retry per student), a revision-guarded canvas autosave and, on arrival, one durable Deep Review submission — all through public HTTP. Records counts/errors with category detail, nearest-rank p50/p90/p95/p99/max, queue observations, OCC conflicts/retries, per-level throughput, transcript/revision reconciliation (loss/duplicates), write-volume proxy bytes, generation-ledger accounting and Deep Review completion to a bounded deadline; always `live_ready: false` with named unresolved gates. Separate guarded mock worker + driver-created disposable roots only; no supplied database, host or paid call. |
| `tests/scripts/test_mixed_workload_probe.py` (new) | Harness contracts: nearest-rank percentiles with the p90/p95/p99 tails, error/conflict/saved-latency separation in `summarize`, a real two-student mixed wave reconciled without loss or duplicates (every non-OCC category error-free, exactly one OCC conflict + retry per student, both Deep Reviews completed within deadline), and every limiter pin asserted to survive the settings bounds (the red-first guard against silently restored defaults). 4 passed. |
| `docs/operations/CLASSROOM_CAPACITY_GATE.md` | New "Mixed classroom workload probe (ticket 48)" section: repeat command, coverage, the 2026-11-26 headline, the diagnosed-and-fixed pin defect, and the separately capped live synthetic-account procedure (five unresolved preconditions: fresh cost/request/token cap approval, concurrency ceiling, agreed maximum wait, provider quota evidence, deployment-envelope evidence; hard call counter, rejection/error recording, local-mock and live results never merged). |
| `scripts/AGENTS.md`, `tests/AGENTS.md`, `docs/TESTING.md` | Guidance rows for the new probe and its tests, and the mixed-workload link beside the existing load-probe/classroom-gate guidance. |

#### Executed validation

| Command/check | Result |
| --- | --- |
| Resume verification (tickets 46/47) | `mock-ci.yml` + `dependency-audit.yml` carry the deterministic set as recorded; `.venv/bin/python -m scripts.workspace_recovery_rehearsal` re-run **exit 0** with the full seeded/restored workspace and owner-boundary evidence matching the ticket 47 entry. |
| `.venv/bin/python -m pytest tests/scripts/test_mixed_workload_probe.py` | Pin-bound test **red first** (`applied == 8 != 120` — the out-of-range pin really did silently restore the default), then green after the pin fix; **4 passed**. |
| First full probe run (defective pin) | Completed end to end with 22 `user_rpm` rejections (L60: 1 ordinary + 1 grounded; L80: 10 + 10) — the diagnosis evidence; reconciliation still 0 losses / 0 duplicates. |
| Definitive probe run (`.venv/bin/python -m scripts.mixed_workload_probe`) | **Exit 0**, all six levels, zero admission/rate-limit rejections, zero confirmed losses or duplicates at every level; the only errors are the deliberate one-per-student OCC 409s, each recovered by a successful fresh-base retry. |
| Full mock suite | **3,359 passed / 1 skipped** in 176.12 s (ticket-47 baseline 3,355 + this ticket's 4 harness tests), exit 0. |
| `npm test --prefix frontend` | **179 passed / 3 skipped** (unchanged baseline). |
| `npm run build --prefix frontend` / `npm run test:browser --prefix frontend` | Build success (exit 0); browser slice **10 passed**. |
| `.venv/bin/ruff check .` / `compileall` / `git diff --check` / leak check | All pass / exit 0 / clean / no uvicorn, playwright or probe processes left. |

#### Measured local results (actual numbers; local mock characterization only)

Environment: this macOS arm64 host (macOS 27.2.1, Python 3.12.7 repo venv),
single uvicorn worker on loopback, disposable temp SQLite/local-file stores,
deterministic mock provider with an injected 250 ms delay (an input, not a
model measurement), synthetic admission fixture 4 running / 80 queued / 30 s
wait, Deep Review concurrency 8, production-documented limiter pins
(120 coach RPM/owner, 120 model calls, 120 threadpool tokens), httpx keepalive
clients (not browsers/Streamlit), one run per level — sample sizes equal the
reported operation counts, no repetitions or confidence intervals. Recorded
2026-11-26 07:13 SGT. Latencies are all-outcome nearest-rank milliseconds.

| Level (students) | New | Wave s | Ops | Throughput ops/s | Navigation p50/p95/max | Coached turns p50/p95 (ordinary / grounded) | Startup p95 | Upload p95 | OCC conflicts/retries | Queue observations |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | 1 | 0.94 | 13 | 13.8 | 14.5 / 14.5 / 14.5 | 539.6 / 539.6 — 296.1 / 296.1 | 7.1 | 6.1 | 1/1 | 0 |
| 10 | 9 | 1.88 | 124 | 66.0 | 92.4 / 110.9 / 110.9 | 378.0 / 901.5 — 586.7 / 805.3 | 115.6 | 47.6 | 10/10 | 15 |
| 20 | 10 | 3.32 | 200 | 60.3 | 138.3 / 218.5 / 224.7 | 829.0 / 1234.6 — 1360.5 / 1387.9 | 236.1 | 273.9 | 20/20 | 39 |
| 40 | 20 | 6.46 | 400 | 61.9 | 269.6 / 476.9 / 1932.6 | 1625.3 / 2463.1 — 2433.1 / 2736.2 | 1075.2 | 312.2 | 40/40 | 76 |
| 60 | 20 | 9.99 | 540 | 54.0 | 668.9 / 824.4 / 2747.1 | 3000.7 / 4150.9 — 3848.4 / 4239.9 | 1447.2 | 368.6 | 60/60 | 116 |
| 80 | 20 | 13.97 | 680 | 48.7 | 1022.3 / 1234.3 / 3354.3 | 4428.7 / 5668.7 — 5593.7 / 5682.2 | 1951.8 | 780.3 | 80/80 | 156 |

Write-volume proxy (documented limitation, not a measured WAL/write-amplification
factor): the application SQLite store grew 233,472 → 3,420,160 bytes across the
run (80 notebooks, 1,222 messages, 160 sources, 502 artifact versions, 291
canvas versions at level 80); the fake-accounting generation ledger recorded 501
reservations with 8 unsettled at the final sample (queued/running at that
moment, reported honestly). Artifact autosave stayed fast at every level
(p95 ≤ 39.5 ms) and canvas autosave p95 ≤ 27.3 ms. All 80 durable Deep Review
jobs completed within the bounded 90 s poll (p50 17,184 ms / p90 35,971 /
p95 36,211 / p99 37,870 / max 37,870 from submission; none unfinished).
Server high-water marks: 173 threads, RSS ≈ 536 MiB, 90.6 CPU-seconds;
sampled admission peaks 4 running / 76 queued — the 80-queued synthetic bound
was never exceeded and no requester was rejected.

Interpretation against the documented engineering targets: every non-coaching
operation stays well under the 500 ms ordinary-API p95 target through 80
concurrent students **except** navigation reads (p95 824 ms at 60, 1,234 ms at
80) and wave-level startup (p95 1,447–1,952 ms at 60/80), and coached turns are
dominated by the synthetic 4-running admission fixture (grounded p50 ≈ 5.6 s at
80 versus ≈ 0.3 s solo) — a deliberate fixture, not a recommended classroom
configuration. These are single-run, machine-bound, mock-provider numbers: no
real model, guardrail, AgentCore, Cognito, DSQL or S3 time is included, sessions
are HTTP clients rather than 80 rendered browser tabs, and per-level samples are
small (n = operation counts). Local-mock results never infer live provider
capacity, classroom scale or cost; the live procedure and its unresolved gates
are recorded in `CLASSROOM_CAPACITY_GATE.md`.

#### Compatibility, rollback and known limits

No application, schema, contract or frontend behavior changed; rollback is
delete-only (remove the two new files and the four doc additions). Known
limits, documented rather than silently accepted: one run per level on one
shared developer machine with a contended disk and no repetition/intervals;
the mock delay, admission policy and its fake micro-SGD accounting are
fixtures (never funding or wait-time decisions); the Deep Review eligibility
gate is relaxed only inside the disposable child (same confined pattern as
ticket 47) while enqueue, worker, admission and persistence stay real; the
write-volume proxy is byte growth, not write amplification; navigation p95
exceedances and admission-dominated turn latency are observations to re-measure
under the real envelope, not adopted changes. Three earlier full-suite runs (executed while recovering a
clipped summary line after the first exit-0 pass) all exited 0; the recorded
3,359/1 figure is from the final run. No blockers: the one measurement defect
was diagnosed, fixed red-first and re-measured within the same session.

**Next exact action:** ticket 49 — model operating costs and regional
trade-offs — is **newly unblocked** by 48 (its other blockers 4 and 37 are
complete) and is the next ticket per the dependency graph, in a fresh writer
session. Also eligible: 50 (extend authorised aggregate engagement signals),
51 (coordinated release and rollback rehearsal) and 52 (export selected
coursework), whose blockers all carry ledger evidence. 53 (verify and report
the complete programme) remains blocked on 49/50/51/52. Stop after 48 per the
assignment.

### Ticket 47 complete — rehearse recovery of the complete saved workspace (2026-11-26 SGT, OpenCode)

**Ticket 47 adds a deterministic, disposable, mock-only rehearsal that backs up
and restores a COMPLETE saved workspace — chats, sources, both version
histories, learning state, recaps and Deep Review envelopes — into a fresh
location, and it found and fixed one genuine recovery gap red-first.** The new
`scripts/workspace_recovery_rehearsal.py` (driver + guarded child worker, the
proven `classroom_probe.py` pattern) seeds everything through public HTTP only:
coaching turns, an uploaded source, an artifact saved to revision 3, a canvas
saved to revision 3, a confirmed stage transition (whose acceptance builds the
milestone recap), and a durable Deep Review driven to `completed`. Because
stage completion has no public HTTP route — stage authority belongs to
confirmed coaching turns — the disposable child relaxes only the Deep Review
eligibility gate; enqueue, the durable worker, snapshot persistence and owner
fencing stay real. It then snapshots every public read (project with
recaps/review, messages page, settings, learning state, sources plus source
bytes, both version histories including a version-body read, the Deep Review
job, transcript bytes), proves that snapshot stable across a real restart,
performs the documented stopped-server backup (SQLite backup API with
`PRAGMA integrity_check`, file-tree copy, table-level inventory), makes the
original stores unavailable, restores into a **fresh** disposable location, and
re-verifies the identical snapshot through public interfaces plus the owner
boundary (a second owner is 404-refused on every read, before and after) and a
second restart. The documented inventory, procedure, compatibility limits and
the DSQL boundary are written up in
`docs/operations/WORKSPACE_RECOVERY_REHEARSAL.md`.

**The genuine gap the rehearsal proved:** local-provider uploads live under
`files_dir/threads/<thread>/uploads` and source rows carried the **absolute**
path written at upload time, so restoring a backup into a fresh location (the
rehearsal's supported scenario, and a real crashed-host recovery) returned 400
"Source file is not available" for original source bytes — the first rehearsal
run failed exactly there. Fixed red-first: a new HTTP test
(`tests/http/test_source_recovery_relocation.py`) failed with the restored read
at 400 (the same-location read was 200), then
`backend/sources/projection.py::safe_source_file_path` gained a minimal
re-anchor that re-roots a stale absolute path under the configured
`files_dir` using the stable `threads/<thread>/uploads` suffix, passing the
same traversal containment check as any stored path. The rehearsal then passed
end to end; all neighboring source/persistence/HTTP suites were re-run green.

Starting revision/branch: `improvement/architecture-responsiveness` with the
dirty ticket 01–46 working tree preserved unchanged apart from this ticket's
files.

#### New files and behavior

| File | Responsibility |
| --- | --- |
| `scripts/workspace_recovery_rehearsal.py` (new) | The full rehearsal above. Driver-created, token-marked temporary roots only; the child refuses any non-driver launch; output is aggregate JSON with no identities or content. |
| `tests/http/test_source_recovery_relocation.py` (new) | The red-first public-behavior test: upload via HTTP, stopped-server backup into a fresh location with the original files unavailable, source content must reopen with its original bytes (200) through the real route. |
| `backend/sources/projection.py` | **The one behavior fix (red-first):** `safe_source_file_path` re-anchors a stale absolute local path under the configured `files_dir` via `_reanchored_local_path` when the stored location no longer exists; containment and traversal guards unchanged, so existing same-location behavior is identical. |
| `docs/operations/WORKSPACE_RECOVERY_REHEARSAL.md` (new) | The documented backup inventory (application SQLite store with recaps/review envelopes and both version histories, generation ledger when configured, files/workspace/lecture trees), the rehearsal procedure and coverage, the found-and-fixed relocation limit, and the explicit DSQL boundary (SQLite results never infer live DSQL recoverability). |
| `scripts/AGENTS.md`, `backend/AGENTS.md`, `docs/README.md` | Guide updates: the new script row, the relocation-safe source-read rule for future source changes, and the operations index link. |

#### Executed validation

| Command/check | Result |
| --- | --- |
| `.venv/bin/python -m pytest tests/http/test_source_recovery_relocation.py` | **Red first for the intended reason**: post-restore source-content read returned 400 while the same-location read was 200; green after the `safe_source_file_path` re-anchor fix. |
| Neighbor suites after the fix | `tests/http/` + `tests/persistence/` + `tests/domain/test_source_library.py` + `tests/domain/test_retrieval.py`: all pass, 0 failures. |
| `.venv/bin/python -m scripts.workspace_recovery_rehearsal` | **Green end to end** (exit 0): seeded notebook with 3 messages, 1 source, artifact revision 3 (3 versions), canvas revision 3 (3 versions), 1 confirmed recap, Deep Review `completed`; backup inventory integrity `ok` (`notebooks` 2, `messages` 3, `sources` 1, `student_artifacts` 1 + versions 3, `student_canvases` 1 + versions 3); restart, fresh-location restore and second restart all match snapshot sha256 `2e633508…4afa0`; owner boundary 404 on all 8 foreign reads before and after restore. Two rehearsal-side corrections were recorded during authoring (the backup must also carry the child's `control.json`; failure diagnostics read the server log after the handle closes). |
| Full mock suite | **3,355 passed / 1 skipped** (the known module-level `strands` import skip), exit 0 — baseline 3,354 + the new relocation test. |
| Frontend (no behavior change; regression proof) | `npm test --prefix frontend` **179 passed / 3 skipped**; `npm run build` success; `npm run api:check` exit 0; `npm run test:browser` **10 passed**. No frontend file changed in this ticket. |
| `.venv/bin/ruff check .` / `compileall` / `git diff --check` / leak check | All pass / exit 0 / clean / no uvicorn or playwright processes left. |

#### Compatibility, rollback and known limits

The relocation fix only changes behavior where the stored absolute path no
longer exists (a genuine recovery failure); same-location restores and all
existing read paths take the original branch unchanged, as the untouched
neighbor suites confirm. Rollback is source-only: revert
`backend/sources/projection.py` (the rehearsal then documents the previous
fresh-location limit) and delete the new script/test/doc files. Known limits,
documented rather than silently accepted: the rehearsal exercises SQLite/local
only — DSQL recovery mechanisms (PITR/snapshot per the deployment runbooks) are
verified separately and were **not** executed, so no live recoverability claim
is made; the rehearsal's Deep Review eligibility override is confined to its
disposable child process and is not reachable in shipped configuration; the
generation admission ledger is only part of the inventory when
`GENERATION_ADMISSION_POLICY` is configured (the rehearsal runs without one, so
the ledger row of the inventory is documented rather than exercised); and
object-storage (S3) source relocation is reasoned (relative keys) but not
exercised, since the mock boundary has no S3.

**Next exact action:** ticket 48 — run the stepped 1/10/20/40/60/80 synthetic
mixed classroom workload locally (startup, navigation, coaching, source
upload, artifact/canvas autosave, Deep Review submission), record
throughput/errors, p50/p90/p95/p99/max, queueing and OCC behavior with
environment and sample-size limitations, and keep local mock results separate
from live claims.

### Ticket 46 complete — complete deterministic frontend and browser CI (2026-11-26 SGT, OpenCode)

**Ticket 46 closes the deterministic-CI checkpoint by completing the existing
GitHub Actions gate rather than adding a new one: minimal configured frontend
lint, bundle-size evidence and pinned secret scanning joined the standing
`mock-ci.yml` jobs, and the full composition was executed locally with recorded
numbers.** The workflow already carried most of the spec's composition — full
mock Pytest (collection included), Ruff, `compileall`, offline schema/client
drift (`export_reader_openapi.py --check` + `npm run api:check`), TypeScript via
`tsc --noEmit` inside the production build, Vitest/component tests, the
Playwright browser slice with the ticket 43 route-load and ticket 44
accessibility specs, frontend `npm audit`, a separate scheduled `pip-audit`
workflow for Python dependencies, and Python-only CodeQL — so the ticket added
the three missing pieces deterministically. First, **frontend lint**: ESLint 10
+ `typescript-eslint` 8.74 (exact-pinned) with a small flat config
(`frontend/eslint.config.js`, `npm run lint`) at recommended rules only, no
type-aware or stylistic rules, with the OpenAPI-generated client excluded from
lint because that directory is never hand-edited (ticket 33 generator quirk).
The first run found **19 valid unused-import/unused-variable errors**; every one
was fixed rather than suppressed — dead imports and two dead locals removed (a
duplicated page-defaults helper in `src/api/client.ts`, an unused `useMemo` in
`CanvasDevelopDialog`, an unused `base` URL in `useReader`, an unused `done`
count in `ThinkingPath`), signature-bound props aliased to `_`-prefixed names
(`onHelp` in `Conversation`, `startInChat` in `ThinkingPath`) and one dead
`setCheckedKey` destructure dropped — with `tsc`, Vitest and the browser slice
re-run green afterwards, so no behavior changed. Second, **bundle-size
evidence**: the `mock-suite` job now runs `npm run measure:bundle` after the
production build (evidence only; thresholds stay a ledger judgment). Third,
**secret scanning**: the `mock-suite` job runs pinned
`ghcr.io/gitleaks/gitleaks:v8.30.1 detect` over the checked-out git history with
a committed `.gitleaks.toml` that extends the default rules and allowlists
exactly three documented synthetic test fixtures (the deliberately fake planted
credential in `tests/http/test_security_readiness.py` and two deterministic
fixture strings whose names merely end in `key`); no path is allowlisted
wholesale, and any new finding fails the job. Dependency auditing needs no new
work: frontend advisories already run in `mock-suite`, and Python `pip-audit`
already runs in the separate path-filtered weekly `dependency-audit.yml`.
`docs/TESTING.md` gains a "Deterministic CI composition (ticket 46)" section
mapping every check to its job and local equivalent. No ordinary job needs live
AWS or paid AI; artifact uploads remain the failure-only Playwright report
(7-day retention).

Starting revision/branch: `improvement/architecture-responsiveness` with the
dirty ticket 01–45 working tree preserved unchanged apart from this ticket's
files.

#### New files and behavior

| File | Responsibility |
| --- | --- |
| `frontend/eslint.config.js` (new) | Minimal deterministic ESLint flat config: `typescript-eslint` recommended over hand-written `src/`, `tests/`, `scripts/` and config files; ignores `dist/`, `node_modules/` and the generated client (`src/api/generated/`); `no-explicit-any` off at the generated-client boundary and unused vars allowed only with a `_` prefix. |
| `.gitleaks.toml` (new) | Secret-scanning baseline: `[extend] useDefault = true` plus three documented synthetic-fixture allowlists (regex + path scoped, with rationale comments). |
| `frontend/package.json` / `package-lock.json` | `lint` script; exact-pinned `eslint@10.15.0` and `typescript-eslint@8.74.0` devDependencies (`npm install` reports 0 vulnerabilities). |
| `.github/workflows/mock-ci.yml` | Extended, not rewritten: `Frontend lint` step after the unit regressions, `Bundle size evidence` step after the reader build, and `Secret scanning (gitleaks)` with the pinned image and a comment explaining the shallow-checkout bound and the `pip-audit` split. |
| `docs/TESTING.md` | New "Deterministic CI composition (ticket 46)" section: every check → job → local command mapping and the allowlist policy. |
| 11 frontend source/test files | The 19 lint fixes listed above; behavior-preserving (Vitest 179 passed / 3 skipped and the 10 browser specs re-verified after the fixes). |

#### Executed validation

| Command/check | Result |
| --- | --- |
| `npm run lint --prefix frontend` | First run: **19 errors** (all unused imports/vars), each fixed individually; final run clean. `npx tsc --noEmit` clean after the fixes. |
| `npm test --prefix frontend` | **179 passed / 3 skipped** (baseline held through the lint fixes). |
| `npm run build --prefix frontend` | Success (vite build 1.95 s; includes `tsc --noEmit`). |
| `npm run measure:bundle --prefix frontend` | Entry **586,460 B raw / 173,543 B gzip** (2 assets); async **838,056 B raw / 270,093 B gzip** (5 assets). |
| `npm run api:check --prefix frontend` | Exit 0 (offline schema/client drift). |
| `npm run test:browser --prefix frontend` | **10 passed** in 34.6 s (incl. `route_load` evidence: home 631,846 B vs artifact route 1,060,478 B / canvas 909,069 B transfer). |
| `npm audit --audit-level=high --prefix frontend` | 0 vulnerabilities. |
| `gitleaks detect --no-banner --redact` (v8.30.1) | **No leaks** over 374 commits / 22.9 MB in ~2.7 s, after allowlisting the three synthetic fixtures found on the first run. CI-equivalent image tag `v8.30.1` verified present on GHCR. |
| Full mock suite | **3,354 passed / 1 skipped** (the known module-level `strands` import skip), exit 0, no failure/error markers. |
| `.venv/bin/ruff check .` / `compileall` / `git diff --check` / leak check | All pass / exit 0 / clean / no uvicorn or playwright processes left. |

#### Compatibility, rollback and known limits

No application behavior changed: the only source edits are unused-code
removals and `_`-prefixed parameter aliases, each covered by the existing Vitest
and browser regressions which were re-run green. CI runtime stays bounded (the
gitleaks step scans the default shallow checkout — one commit — in seconds; the
full-history scan remains a documented local/periodic command). Rollback is
source-only: revert `mock-ci.yml`, delete `eslint.config.js`/`.gitleaks.toml`
and the `lint` script + two devDependencies, and restore the 11 lint-fixed
files. Known limits, documented rather than silently accepted: ESLint runs at
recommended rules only (no type-aware lint — `tsc --noEmit` remains the type
gate); the workflow's gitleaks scan sees only the checked-out history
(`fetch-depth: 1`), so long-buried leaks rely on the scheduled full-history
runs locally; ESLint/gitleaks image versions are exact-pinned and need a
deliberate bump to move; CodeQL stays Python-only per its existing
configuration; and live AWS/Cognito/paid-provider behavior remains outside the
mock boundary everywhere.

**Next exact action:** ticket 47 — rehearse recovery of the complete saved
workspace (backup inventory covering documents/graphs, both version histories,
messages, learning state and recap/review metadata; restore into a fresh
disposable location and verify through public interfaces after restart).

### Ticket 45 complete — verify workspace ownership and hostile-content defenses (2026-11-26 SGT, OpenCode)

**Ticket 45 is complete as a verification ticket: every route and resource added
by the architecture-completion tickets was swept for second-owner leakage,
cross-family reference leakage, hostile content and unsafe rendering; one
genuine defense gap was found and fixed red-first, and everything else held.**
The new exhaustive suite — `tests/http/test_workspace_defense_sweep.py`
(7 tests) — sweeps the **real** resource ids (the earlier security suites used
unknown-id placeholders for artifact/canvas routes): a second registered owner
and a guest are refused (404/409/422, never a leaked projection) on every
artifact and canvas read, guarded save, duplicate, confirmed delete, version
list/read/restore and all six export formats, on every projection that carries
suggestions, feedback, drafts, recaps and resume state (messages page,
workspace, project, bookmarks), and on the canvas-coaching seam with A's real
canvas/node ids — with A's saved revisions, version histories and transcript
verified untouched afterwards. Cross-family evidence references (source,
message, artifact, canvas-node kinds) fail closed with 422 through the public
save contracts. Hostile content (`<script>` injection, prompt-injection text,
`]]>&'"` breakouts) is stored verbatim as data and stays inert in the SVG
export (XML-escaped, well-formed, nosniff attachment), the outline and all
artifact downloads, with unsafe `javascript:` link schemes dropped. Saved-work
bounds fail with explicit finite 422s over HTTP (101 nodes, 201 edges, a
256 KiB document, 21 references). A source scan proves the student frontend
contains no `dangerouslySetInnerHTML`, `eval`, `new Function` or
`document.write`. The fixed gap: **evidence references could never resolve
Library-linked sources** — reader uploads live in the owner's Library notebook
and link into notebooks through `reader_source_links` settings metadata, but
`resolve_references` joined only `sources.notebook_id IN family`, so the
normal upload→link→reference flow failed closed with 422 "Unresolved
reference" even for the legitimate owner (caught red by the sweep's own
fixture and pinned by a focused red test before the fix). Resolution now also
honors explicit `true` links from family notebooks, with ownership still
enforced by the owner join and detached (false) links refused.

Starting revision/branch: `improvement/architecture-responsiveness` with the
dirty ticket 01–44 working tree preserved unchanged apart from this ticket's
files.

#### New files and behavior

| File | Responsibility |
| --- | --- |
| `tests/http/test_workspace_defense_sweep.py` (new) | The 7-test sweep described above: real-id second-owner sweep (registered + guest, 23 routes each), cross-family reference refusals (4 kinds × save surfaces), Library-linked source resolution/detachment, hostile-content projections and exports, saved-work size bounds over HTTP, and the frontend unsafe-sink scan. Reuses the `World` two-owner fixture from `test_security_readiness.py`. |
| `backend/persistence/store/operations/references.py` | **The one behavior fix (red-first):** new `_family_linked_source_ids` reads `reader_source_links` metadata from the notebook family, and the `source` branch of `resolve_references` falls back to it (ownership still enforced by joining `notebooks.user_id`); detached (`false`) links and foreign owners still resolve unavailable, so `require_resolved` keeps failing closed. |

#### Executed validation

| Command/check | Result |
| --- | --- |
| `pytest tests/http/test_workspace_defense_sweep.py` | **Red first for the intended reason**: the sweep fixture itself failed with `422 {"detail":"Unresolved reference"}` when owner A referenced their own Library-linked upload; the focused `test_owner_can_reference_their_own_library_linked_source` pinned it, then went green after the resolver fix. During authoring two sweep-side corrections were recorded (the link route always links — detach uses `/select`; the graph validator correctly refuses self-edges, so the hostile fixture uses two nodes). Final: **7 passed**. |
| Neighbor suites after the resolver change | `tests/persistence/` + `tests/http/`: **678 passed** (reference contracts, reader artifact/canvas suites, canvas coaching/suggestion/feedback/draft flows, security readiness). |
| Full mock suite | **3,354 passed / 1 skipped** in 173.85 s (3,347 baseline + the 7 sweep tests; no flakes). |
| Frontend (no behavior change; regression proof) | `npm test --prefix frontend` **179 passed / 3 skipped**; the last production build (ticket 44) stands — no frontend file changed in this ticket. |
| `.venv/bin/ruff check .` | Pass (4 unused-import findings in the new test fixed before handoff). |
| `compileall` / `git diff --check` / leak check | Exit 0 / clean / no uvicorn or playwright processes left. |

#### Verification coverage and what was found

Swept (all green unless noted): artifact and canvas CRUD, duplicate, confirmed
delete, versions, version read, guarded restore, and markdown/text/json plus
json/outline/svg exports — under second registered and guest owners with real
ids; messages-page/workspace/project/bookmarks projections carrying
suggestions, feedback, drafts, recaps and resume state; the canvas-coaching
selection seam (foreign canvas 404, foreign family 404, unknown nodes 422 —
matching the existing `test_canvas_coaching.py` guards); cross-family
references of all four kinds through both artifact saves and canvas-node
saves; hostile content through persistence, projections and all export
formats; graph/document/reference size bounds; and frontend raw-HTML/JS sinks
(none exist; React escaping is the only HTML path). Found and fixed: the
Library-linked source evidence gap above. Found correct and left alone:
self-edge rejection, unknown/cross-family id 404/422 fail-closed behavior,
nosniff/attachment/sanitized-filename download headers, export envelope field
exclusion, and the hostile-name/upload limits already covered by
`test_security_readiness.py`.

#### Compatibility, rollback and known limits

The reference fix widens resolution to sources the owner explicitly linked into
the notebook family — no stored data changes, no migration, and the
fail-closed boundary (owner + explicit link) is unchanged, so previously saved
references keep resolving exactly as before and detached sources now honestly
resolve unavailable instead of never resolving. Rollback is source-only:
revert `references.py` (the sweep then documents the previous behavior). Known
limits, documented rather than silently accepted: account-switch/expiry and
late-response races during queries, saves and streams are verified at the
browser and Query seams (`owner_switch_inflight`, `saved_turn_survives_restart`,
Query identity-fencing tests) and are not re-swept here; the unsafe-rendering
scan is a source-text check plus export assertions, not a rendered-DOM audit
(ticket 44's browser spec covers the dialogs the editors render); rate limits
for AI jobs and uploads beyond the existing admission suites remain covered by
`test_security_readiness.py` and the load probe rather than duplicated; and
live AWS/Cognito behavior stays outside the mock boundary as everywhere else.

**Next exact action:** tickets 43, 44 and 45 — the assigned set — are complete.
Stop here; do not start ticket 46. The new frontier from the dependency graph:
46 (deterministic frontend and browser CI), 47 (workspace recovery rehearsal),
48 (mixed classroom workloads), 50 (aggregate engagement signals) and 52
(selected coursework export) are eligible; 49 waits on 48; 51 waits on later
tickets including 45 (now done) and 47; 53 waits on 43, 44, 46 and 49–52.

### Ticket 44 complete — complete accessible desktop and mobile authoring (2026-11-26 SGT, OpenCode)

**Ticket 44 closes the measured dialog-focus and reduced-motion gaps in the
authoring surfaces and records real browser evidence for keyboard, 390 px
touch, contrast and console cleanliness — with no design-system rewrite.** The
one genuine behavioral defect found: the six editor/composer dialogs
(Add-to-canvas ×2, Develop-into-artifact, suggestion review, artifact feedback
review, canvas draft review) rendered as **non-modal** `<dialog open>`
elements — no focus containment, no Escape handling, no backdrop, unlike the
established `showModal()` pattern used by the chat menus. They now render
through a new shared `ModalDialog` component (native `showModal()`, Escape
dismisses via the native cancel/close events, and closing restores focus to the
opener; review cards whose dialog replaces their own trigger control refocus it
explicitly). The second gap, caught red by the new browser spec: the canvas
Locate control ran a JS-driven 300 ms `fitView` zoom that the global CSS
reduced-motion rule cannot suppress; it now moves instantly under
`prefers-reduced-motion: reduce`. Everything else the ticket names already
held and is now evidenced in CI: keyboard-only authoring from the skip link
through toolbar (truthful `aria-pressed`), outline authoring and version
history; truthful `role="status"`/`role="alert"` save/error announcements (no
per-token announcements exist); 390 px touch authoring with no horizontal
overflow; WCAG 2.2 AA contrast spot checks computed for body, supporting and
primary-button text in Light and Dark; screenshots under
`output/playwright/a11y/` and an expected-error-free console. No new runtime
dependency was added (the axe checks are implemented as targeted computed-style
evaluations inside the Playwright spec). The chat composer and streaming are
untouched.

Starting revision/branch: `improvement/architecture-responsiveness` with the
dirty ticket 01–43 working tree preserved unchanged apart from this ticket's
files.

#### New files and behavior

| File | Responsibility |
| --- | --- |
| `frontend/src/ModalDialog.tsx` (new) | Shared native modal dialog: `showModal()` on mount (with a `show`-attribute fallback for jsdom, which lacks the API), `onClose` wired to the native `close` event, and `close()` in the unmount cleanup so focus returns to the opener even when a button closes the dialog. |
| `frontend/src/ArtifactToCanvasDialog.tsx`, `ChatToCanvas.tsx`, `CanvasDevelopDialog.tsx`, `CanvasSuggestions.tsx`, `ArtifactFeedback.tsx`, `CanvasDraftCard.tsx` | Converted from non-modal `<dialog open>` to `ModalDialog`; the three review cards keep a trigger ref and return focus to their Review control after close. |
| `frontend/src/workspaceLayout.tsx` | New `prefersReducedMotion()` helper for JS-driven movement the CSS rule cannot cover. |
| `frontend/src/CanvasEditor.tsx` | Locate's `fitView` uses duration 0 under reduced motion, 300 ms otherwise. |
| `frontend/src/CanvasSuggestions.test.tsx` | **Red-first** test: closing the suggestion review dialog returns focus to the card's Review control (failed with focus on `<body>` before the change). **5 passed.** |
| `frontend/tests/browser/authoring_accessibility.spec.ts` (new) | Two browser tests: desktop keyboard/dialog/reduced-motion/contrast evidence and 390 px touch evidence, with screenshots and console checks. The reduced-motion Locate assertion was **red first** (viewport transform mid-animation at 120 ms under `prefers-reduced-motion: reduce`) and is green after the fix. |
| `frontend/README.md`, `docs/TESTING.md` | Accessible-authoring note and browser-slice table row. |

#### Executed validation

| Command/check | Result |
| --- | --- |
| `npx vitest run src/CanvasSuggestions.test.tsx` | **Red first** (`expected <body> to be <button class="primary">`), then green after the `ModalDialog` conversion and explicit trigger refocus. **5 passed.** |
| `npx playwright test authoring_accessibility` | Reduced-motion Locate assertion **red first** (`translate(230px,12px) scale(2)` ≠ `translate(-10px,14px) scale(2)` mid-animation at 120 ms), green after `prefersReducedMotion()`. Final: **2 passed** (10.7 s). During authoring, one assertion was corrected against measured Chromium behavior rather than code: a modal dialog's Tab cycle passes through `body` between laps while no background control ever receives focus, so the spec asserts the meaningful invariant (focus never reaches a background control). |
| `npm test --prefix frontend` | **179 passed / 3 skipped / 27+1 files** (178 baseline + 1 new focus test; skips are the opt-in ticket-43 perf harness). |
| `npm run build --prefix frontend` | Exit 0; entry JS 510.37 kB / gzip 158.49 kB (+0.5 kB for `ModalDialog`) — the ticket-43 split is preserved. |
| `npm run test:browser --prefix frontend` | **10 passed** (33.5 s) — 7 baseline + `route_load` + 2 `authoring_accessibility`. |
| Full mock suite | **3,347 passed / 1 skipped** in 178.34 s. No flake this run. |
| `.venv/bin/ruff check .` / `compileall` / `git diff --check` / leak check | Pass / exit 0 / clean / no processes left. |

#### Compatibility, rollback and known limits

No API, schema, storage or chat-streaming behavior changed; the dialogs keep
the same content, handlers and `aria-label`s, so existing component tests pass
unchanged (plus the new focus test). Rollback is source-only: revert the six
dialog call sites to `<dialog open>`, delete `ModalDialog.tsx`, restore
`fitView`'s fixed 300 ms duration, and delete the new spec/tests. Known
limits, documented rather than silently accepted: the modal fallback in jsdom
exercises the non-modal path (real modality is asserted only in the browser
spec); the contrast checks are spot checks on the main text pairs, not a full
axe audit of every state (axe-core remains deliberately not installed; if a
full audit is wanted it is a separate decision because it adds a dependency);
screen-reader verification is structural (roles, labels, live regions) via
Playwright rather than with an actual screen reader; and the reduced-motion
Locate assertion samples the transform rather than counting frames.

**Next exact action:** ticket 45 (verify workspace ownership and
hostile-content defenses) starts in a fresh context in this same checkout.

### Ticket 43 complete — keep chat fast when editors are added (2026-11-26 SGT, OpenCode)

**Ticket 43 is implemented and locally verified as a measured, minimal change:
the routed document editor (Tiptap) and design canvas (React Flow) now load
behind dynamic imports, the startup bundle roughly halves, deep-link hosting and
hashed-asset caching are unchanged, and two pre-existing CSP defects that the
new route-load test surfaced were fixed red-first.** Before the change, the
production build emitted one 1,212.61 kB startup JS chunk containing both
editors. After it, the entry chunk is 509.88 kB (158.27 kB gzip) and the editors
load as their own hashed chunks on their routed views only. The public
red-first test — `frontend/tests/browser/route_load.spec.ts` — failed before the
change because the artifact route downloaded exactly the same two JS resources
as the home view, and now passes with real-browser per-route measurements. The
same test also exposed that every authenticated view logged two CSP
`style-src` violations (React inline `style` attributes carrying `--nav-w`/
`--review-w`, meaning saved panel widths silently fell back to defaults in
production) and that Tiptap's runtime `<style data-tiptap-style>` injection was
blocked on the artifact editor. Both are fixed without weakening the CSP: panel
widths move to CSSOM rules (`applyLayoutStyle`, which CSP does not restrict)
and Tiptap's `injectCSS` is disabled with its base ProseMirror styles vendored
into `styles.css`. No virtualization, batching or memoization was adopted: the
opt-in jsdom harness measured an 80-message chat mount at ~109 ms median, a
60-node canvas at ~192 ms and a 60-paragraph document at ~12 ms — all far from
a demonstrated bottleneck. Chat latency and the composer are untouched;
`no-store` and hashed-asset policies are unchanged.

Starting revision/branch: `improvement/architecture-responsiveness` with the
dirty ticket 01–42 working tree preserved unchanged apart from this ticket's
files.

#### New files and behavior

| File | Responsibility |
| --- | --- |
| `frontend/tests/browser/route_load.spec.ts` (new) | Real-browser route-load measurement on the disposable same-origin stack: signs in a synthetic guest, creates a notebook/artifact/canvas through the reader API, then asserts the home view downloads strictly fewer JS resources (and bytes) than the artifact and canvas deep links, that both editors still mount from deep links, and that the hashed entry chunk is reused across views. Prints one `route-load-measurement` JSON line (per-route JS URLs, transfer/decoded bytes, editor-ready ms); no wall-clock assertions. **Red first** (artifact route = home = 2 JS files), green after lazy loading; also red again when it exposed the CSP console errors. |
| `frontend/src/App.tsx` | `ArtifactEditor` and `CanvasEditor` are now `React.lazy` dynamic imports behind a `<Suspense>` fallback (`Loading editor…`, `role="status"`), so Tiptap/React Flow leave the startup bundle while routed deep links keep working. The workspace `--nav-w` inline style attribute is replaced by `applyLayoutStyle`. |
| `frontend/src/workspaceLayout.tsx` | New `applyLayoutStyle(className, declarations)`: installs/updates the dynamic panel-width custom properties as a CSSOM rule inserted into the bundled same-origin stylesheet (after its original class rule), a safe no-op when no readable same-origin stylesheet exists (tests). CSP does not restrict CSSOM insertion, so saved widths apply again under `style-src 'self'`. |
| `frontend/src/Conversation.tsx` | The Review `--review-w` inline style attribute is replaced by the same `applyLayoutStyle` rule. |
| `frontend/src/ArtifactEditor.tsx` | `useEditor({ injectCSS: false })` — Tiptap's runtime `<style data-tiptap-style>` injection violated the CSP; the identical base ProseMirror styles are vendored into `styles.css` with a re-verify-on-upgrade note. |
| `frontend/src/styles.css` | Vendored Tiptap/ProseMirror base editor styles (attributed comment) replacing the blocked runtime injection. |
| `frontend/src/renderPerf.test.tsx` (new) | Opt-in jsdom render-cost harness (`PERF_MEASURE=1 npx vitest run src/renderPerf.test.tsx`; skipped under plain `npm test`): median of five mount-to-content-ready trials for an 80-message conversation, a 60-node/80-edge canvas and a 60-paragraph document, printing one `render-perf` JSON line each. |
| `frontend/scripts/measure-bundle.mjs` (new) + `npm run measure:bundle` | Post-build asset measurement: classifies emitted JS/CSS as entry-HTML-referenced versus async dynamic-import chunks and prints raw + gzip bytes per asset and per group. |
| `frontend/README.md`, `docs/TESTING.md` | New "Editor loading and CSP-safe layout" note; browser-slice table row for `route_load.spec.ts`; coverage-map row for the measurement harnesses. |

#### Executed validation

| Command/check | Result |
| --- | --- |
| `npx playwright test route_load` | **Red first, twice for the intended reason**: (1) before lazy loading, `expect(artifact.urls.length).toBeGreaterThan(home.urls.length)` failed — both routes downloaded exactly 2 JS files; (2) after the lazy split the bundle assertions passed but the spec failed on the two pre-existing CSP `style-src` console errors, which drove the `applyLayoutStyle` + vendored-Tiptap-CSS fixes. Final: **passed** with the measurement line `home {js_urls:2, transfer 631,305 B, ready 60–65 ms}`; `artifact_route {js_urls:4, transfer 1,059,966 B, editor ready 828–829 ms}`; `canvas_route {js_urls:4, transfer 908,605 B, editor ready 835–837 ms}`. |
| `npm run build` (before → after) | Before: `index` JS **1,212.61 kB (388.75 kB gzip)** + `react-markdown` 120.82 kB = **1,333.43 kB JS (425.84 kB gzip) startup**; CSS 89.64 kB. After: entry JS **509.88 kB (158.27 kB gzip)** + react-markdown 120.82 kB (37.09 kB gzip, still fetched at startup by the existing preload) = **630.71 kB JS (195.36 kB gzip) at startup** (−52.7% raw, −54.1% gzip); lazy `ArtifactEditor` 425.52 kB (135.42 kB gzip), `CanvasEditor` 274.16 kB (93.68 kB gzip) + `CanvasEditor.css` 15.12 kB moved out of the startup CSS (75.56 kB now). |
| `npm run measure:bundle` | Reproduces the post-build table above from `dist/`. |
| `PERF_MEASURE=1 npx vitest run src/renderPerf.test.tsx` | `conversation-80-messages` median **109.0 ms** (min 60.1, max 175.0; 1,372 DOM nodes); `canvas-60-nodes` median **192.2 ms** (min 137.6, max 288.7; 3,560 DOM nodes); `artifact-60-paragraphs` median **11.6 ms** (min 11.4, max 30.5; 121 DOM nodes). jsdom: no layout/paint, so these capture React/prosemirror/react-flow work only. No bottleneck demonstrated → no virtualization/batching adopted. |
| `npm test --prefix frontend` | **178 passed / 3 skipped / 27+1 files** — the 178 baseline passes are unchanged; the 3 skips are the opt-in renderPerf harness. |
| `npm run build --prefix frontend` | Exit 0 (TypeScript + Vite, hashed output names unchanged in shape). |
| `npm run test:browser --prefix frontend` | **8 passed** (26.0 s) — the 7 baseline specs plus `route_load.spec.ts`. |
| `npm run api:check --prefix frontend` | Pass (no contract change; reader.json/generated untouched). |
| Full mock suite | **3,347 passed / 1 skipped** in 175.73 s. One first run failed only `tests/scripts/test_benchmark_concurrency.py::test_generation_admission_stays_bounded_under_overload` — the documented ticket-39 disk-load flake; the focused rerun passed (5 passed) and the full-suite rerun was clean, per the documented procedure. |
| `.venv/bin/ruff check .` / `compileall` | Pass / exit 0. |
| `git diff --check` / leak check | Clean; no uvicorn/playwright processes left. |

#### Compatibility, rollback and known limits

Rollback is source-only: restore the two static editor imports in `App.tsx`,
revert the `applyLayoutStyle` calls (and re-add the two `style` props),
re-enable `injectCSS`, drop the vendored CSS block, and delete the new
measurement files; no schema, contract or backend behavior changed (the CSP
header line was returned to its pre-ticket value after the fix proved
unnecessary). The one intentional behavior change besides loading order is that
saved panel widths now actually apply under the production CSP instead of
silently falling back — users who resized panels will see their saved widths
take effect. Known limits, documented rather than silently accepted: the
react-markdown chunk is still fetched at startup by the existing
`preloadMarkdown` call (measured, 120.82 kB — a future candidate only if
measured to matter); render measurements are jsdom (no layout/paint) and the
route-load numbers are single-trial local loopback samples, not classroom
latencies; `artifactText` is a small shared chunk both editors import; the
Tiptap vendored CSS must be re-verified on `@tiptap/core` upgrades (comment in
`styles.css`); and `npm test` now reports 3 opt-in skips, which is expected.

**Next exact action:** tickets 44 (accessible authoring) and 45 (ownership and
hostile-content verification) are assigned to this programme; per the
assignment the next writer session starts ticket 44 in a fresh context in this
same checkout.

### Ticket 42 complete — evaluate retrieval for workspace evidence (2026-11-26 SGT, OpenCode)

**Ticket 42 is implemented and locally verified as a measurement ticket with
no retrieval behavior change and no advanced-retrieval adoption.** A new
labelled corpus — `scripts/evals/datasets/workspace_evidence.synthetic.jsonl`
(24 synthetic rows, ids `we001`–`we024`, all marked `synthetic: true`) —
extends coverage exactly as the spec names: explicit lecture questions,
implicit lecture questions (concept described without naming the tool or
deck), project coaching (no course fact needed), ambiguous follow-ups
(history-dependent and vague), selected uploads, and canvas/artifact evidence
scenarios where the grounded answer must come from the server-resolved
workspace selection, not course retrieval. Two rows also carry
`authorized_materials` restrictions that measure the authorization filter
(the same verbatim sentence appears in a selected reading *and* an unselected
lecture deck, so an unselected-deck hit is a filter miss, not a hit). A new
offline command — `scripts/evals/evaluate_workspace_evidence.py` — runs the
production gate adapter (`scripts/evals/lib/gate.py` →
`backend.coaching.evidence_scope`, unchanged) and the same offline lexical
retriever (`OfflineCourseSearch`, one chunk per PDF page), measuring gate
agreement, precision/recall@1/2/4/8, MRR, citation correctness (the verbatim
`evidence` snippet must appear in the retrieved page text), authorization
filtering, honest evidence gaps and local search latency. Every evidence
snippet is verified against its tagged PDF page in test. The 295-message gate
corpus and all existing datasets, gates and defaults are unchanged; no
Bedrock/Knowledge Base call is possible; no chunking/reranking/rewriting/
router/vector-store change is adopted. Nothing is staged, committed or
deployed.

Starting revision/branch: `improvement/architecture-responsiveness` with the
dirty ticket 01–41 working tree preserved unchanged apart from this ticket's
files.

#### New files and behavior

| File | Responsibility |
| --- | --- |
| `scripts/evals/datasets/workspace_evidence.synthetic.jsonl` (new) | 24 labelled synthetic rows with the gate record fields plus `evidence_source` (`course`/`student_upload`/`workspace_context`/`both`/`none`) and `authorized_materials`; course-evidence rows carry `expected_material`/`expected_pages`/`evidence` under the same verbatim-page rule as the question set. |
| `scripts/evals/evaluate_workspace_evidence.py` (new) | Offline command: `load_corpus` (schema validation, synthetic marker, id uniqueness), `measure_gate` (production gate agreement, clear-only split, disagreements), `measure_retrieval` (per-row authorized or full-corpus `OfflineCourseSearch`, precision/recall@K, MRR, citation correctness, filter correctness, local latency, authorized-row detail), `measure_upload_gaps` (honest gaps; wrongly-credited course hits recorded rather than hidden), `build_report`/`main` (JSON marked `offline-simulation`, network blocked, `--i-approve-live-aws` refused with exit 2, no-adoption recommendation). |
| `tests/scripts/test_evaluate_workspace_evidence.py` (new) | Red-first contracts (red = missing command): coverage of all extended categories with coherent labels; every course-evidence snippet verified on its tagged page via PyMuPDF (skipped when PyMuPDF is absent); precision/recall@K/MRR/citation/filter/latency present with bounded values; zero unauthorized hits; upload gaps recorded; no boto3 client built; CLI live refusal and JSON `run` block. **8 passed.** |
| `docs/RETRIEVAL_EVAL.md`, `scripts/evals/datasets/README.md` | New "Workspace-evidence evaluation (offline)" section and dataset table row documenting the corpus, the command, the metric definitions and the stand-in limits. |
| `scripts/AGENTS.md`, `tests/AGENTS.md` | Script and test-map rows. |

#### Executed validation

| Command/check | Result |
| --- | --- |
| `pytest tests/scripts/test_evaluate_workspace_evidence.py` | **Red first** (`ImportError: cannot import name 'evaluate_workspace_evidence'`), then green after the command. Mid-implementation corrections recorded: the `evidence_source` vocabulary gained `both` (a mixed upload+course row legitimately carries course evidence), one corpus label (`we009`) was re-tagged to pages 65+67 after the verbatim page check proved the four matrix labels only co-occur on the built-up slide, and a leftover no-op block plus an undefined name in `measure_gate` were removed (caught by ruff, not by tests). **8 passed.** |
| Full mock suite | **3,347 passed / 1 skipped** in 189.37 s (3,338 after ticket 41 + this ticket's 8 new tests and the glob-parametrized eval-command-boundary cases the two new command files add). Exit 0. |
| `npm test --prefix frontend` | **178 passed / 27 files** — unchanged. |
| `npm run build --prefix frontend` | Exit 0. |
| `npm run test:browser --prefix frontend` | **7 passed** (24.0 s) — unchanged. |
| `.venv/bin/ruff check .` | Pass. |
| `compileall` (backend, ui, streamlit_app, tests, scripts, agentcore_runtime) | Exit 0. |
| `git diff --check` / leak check | Clean; no uvicorn/playwright processes left. |

#### Measured local results (actual local numbers; offline, lexical stand-in)

Environment: this macOS host, Python 3.12 (repo `.venv`),
`MOCK_OPENAI=true MODEL_PROVIDER=mock`, network blocked by the command,
`OfflineCourseSearch` over the 10 local lecture PDFs (one chunk per page) —
**numbers describe the lexical stand-in and say nothing about Knowledge Base
quality**. Report reproducible via the README command.

Gate (production first-pass adapter, 24 rows): agreement 17/24 (70.8%);
clear-only 15/22 (68.2%). All 7 disagreements are expected-`retrieve` →
actual-`skip` (`we003`, `we004`, `we007`, `we008`, `we009`, `we011`, `we016`)
— implicit lecture questions, reading questions and a history-dependent
follow-up that the first-pass gate does not route to course retrieval. That is
an **observed, labelled gap**: per the spec it is the entry condition for
considering any gate or classifier change, which stays measurement-gated and
is not adopted here.

Course-evidence retrieval (16 rows): precision@1 0.375, precision@4 0.125;
recall@1 6/16 (37.5%), recall@4 8/16 (50%), recall@8 10/16 (62.5%); MRR
0.4588; citation correctness 14/16 (87.5%) — two rows' acceptable hits
matched material/page but the verbatim snippet sat on a neighbouring
repeated-slide page; zero rows with no acceptable hit at any rank.
Authorization filtering: 16/16 correct (100%) — the two selected-material
rows (`we012`, `we013`) and the mixed upload+course row (`we020`) returned
zero hits outside their authorized set; notably `we012`'s only-in-scope hit
(Webb Young reading) first ranks 14th once the unselected Week 7 duplicate is
excluded, an honest ranking cost of correct filtering. Latency (local lexical
search wall time): p50 70.7 ms / p95 74.5 ms / max 74.5 ms.

Evidence gaps: the upload row's evidence is honestly absent from the course
corpus (gap recorded, no course hit wrongly credited —
`student_upload_rows_wrongly_credited_by_course_search` is empty); 3
canvas/artifact rows and 3 project-coaching rows are labelled
workspace-context/none and are excluded from course-retrieval scoring by
design.

#### Compatibility, rollback and known limits

Measurement only: no gate rule, retrieval default, prompt, route or schema
changed; the existing datasets, their pinned SHAs and the 295-message gate
numbers are untouched. Rollback is source-only: delete the corpus, the
command, its test and the documentation rows. Known limits, documented rather
than silently accepted: rows are synthetic and hand-labelled (cleaner wording
than real traffic); course numbers describe the offline lexical stand-in only
— live Knowledge Base numbers belong to the separately approved, capped
`--live-kb` mode of `evaluate_retrieval.py`, which was not executed;
`authorized_materials` models the server-side selection filter at the
retriever boundary, not the full evidence-scope precedence chain; and the
latency numbers are one host's local file parsing, not production retrieval
latency. Advanced retrieval variants (chunking, hybrid search, rewriting,
reranking, multi-query, multimodal, GraphRAG, extra vector stores, LLM
routers) remain rejected for want of demonstrated need beyond the recorded
gate gap; adopting any requires a separate evidence-gated decision.

**Next exact action:** tickets 36–42 are complete; per the assignment, stop
here — do not start ticket 43. The new frontier from the dependency graph:
43 (chat fast with editors), 44 (accessible authoring), 45 (workspace
ownership/defense), 46 (deterministic frontend and browser CI), 47 (workspace
recovery rehearsal), 48 (mixed classroom workloads), 50 (aggregate engagement
signals) and 52 (selected coursework export) are eligible; 49 waits on 48;
51 waits on later tickets; 53 (programme verification) is now unblocked by
40/41/42 but also waits on 43, 44, 46 and 49–52. The next writer session
should start ticket 43 in a fresh context in this same checkout.

### Ticket 41 complete — compare model and runtime paths fairly, offline (2026-11-26 SGT, OpenCode)

**Ticket 41 is implemented and locally verified as a measurement ticket with
no adoption and no runtime default change.** A new offline harness —
`scripts/evals/benchmark_runtime_paths_offline.py` — drives the three existing
provider paths through their **real adapter contracts with injected fakes
only** (the deterministic mock provider behind `MODEL_PROVIDER=mock`; the
canonical `AgentCoreCoachProvider` with an injected fake `bedrock-agentcore`
client returning a valid Fast Chat wire payload; the direct
`BedrockCoachProvider` with an injected fake `bedrock-runtime` client
returning a valid legacy `ProviderCoachOutput` tool-use envelope) over the
same representative synthetic turns, and records: this environment's actual
configured models (no secrets, no ARN values), structured-output
first-attempt success, latency accounting explicitly labelled
`SIMULATED-INPUT` (adapter+harness timings; any fake sleep is a documented
input), token accounting read from the production `co_design.usage`
`generation_usage` events, and error accounting through the production
`provider_error_category` mapping. The harness also records the honestly
inequivalent parts of each path rather than ignoring them: the direct
Bedrock arm implements the **legacy coaching contract, not the Fast Chat
one-call contract, and has no Bedrock guardrail**; the AgentCore arm's
guardrail, Strands loop and recovery turn are runtime-side and not exercised
offline; and SDK retry loops are not exercisable with injected fakes (both
adapters delegate retries to botocore's configured client — fakes are called
exactly once per attempt). `agentcore_runtime` stays canonical; the fair
live-comparison requirements (explicit call caps, guardrail equivalence, the
same pinned turns through both arms, dated confirmed pricing, session/
persistence/retry equivalence) are recorded as an unexecuted plan pointing at
the built, never-run, paid-live-gated
`scripts/evals/benchmark_agentcore_vs_converse.py`. No arm is promoted or
removed; nothing is staged, committed or deployed.

Starting revision/branch: `improvement/architecture-responsiveness` with the
dirty ticket 01–40 working tree preserved unchanged apart from this ticket's
files.

#### New files and behavior

| File | Responsibility |
| --- | --- |
| `scripts/evals/benchmark_runtime_paths_offline.py` (new) | Offline harness: `configured_paths` (settings-derived models per role + code-pinned runtime model IDs, ARN presence only), `_FakeAgentcoreClient`/`_FakeBedrockClient` (deterministic fakes with optional fault, malformed-reply and labelled simulated delay), `_UsageCapture` (production `generation_usage` logger events), `_run_arm` (same turns through each arm; success/latency/usage), `measure_error_accounting` (throttle/access/malformed through `provider_error_category`, one fake call per attempt, offline retry limit recorded), `path_characteristics` (honestly inequivalent contracts), `build_report`/`main` (JSON marked `offline-simulation`, network blocked, `--i-approve-live-aws` refused with exit 2, keep-agentcore-canonical recommendation with the unexecuted live plan). |
| `tests/scripts/test_benchmark_runtime_paths_offline.py` (new) | Red-first harness contracts (red = missing script): configuration documented without secrets/ARN values; all three arms complete the same turns offline with the latency input note; agentcore/bedrock arms meter usage through the production usage events while mock usage stays honestly unknown; safe error categories with exactly one fake call per attempt; inequivalent path characteristics asserted; keep-agentcore-canonical recommendation plus the unexecuted live plan; CLI live refusal and JSON `run` block; no boto3 client ever built. **8 passed.** |
| `scripts/AGENTS.md`, `tests/AGENTS.md` | Script and test-map rows for the new harness and its limits. |

#### Executed validation

| Command/check | Result |
| --- | --- |
| `pytest tests/scripts/test_benchmark_runtime_paths_offline.py` | **Red first** (`ImportError: cannot import name 'benchmark_runtime_paths_offline'`), then green after the harness. Mid-implementation corrections recorded: the usage logger needed its level raised to INFO (root-level default dropped the events) with the previous level restored; the report's `source` field moved from per-model to the configuration block; the secret assertion was sharpened to ban any `arn:aws` value; and the adapter-contract assertion moved to the recorded `path_characteristics`. **8 passed.** |
| Full mock suite | First run: **1 failed / 3,337 passed / 1 skipped** — the ticket-39 `test_benchmark_concurrency.py::test_generation_admission_stays_bounded_under_overload` flake under full-suite disk load (code unchanged in that area; it passed in ticket 40's full run). Rerun isolated: **1 passed** (0.97 s). Full-suite rerun: **3,338 passed / 1 skipped** in 156.14 s, exit 0. Documented per the rerun-once procedure; the overload probe remains load-sensitive under parallel full-suite I/O, not broken. |
| `npm test --prefix frontend` | **178 passed / 27 files** — unchanged. |
| `npm run build --prefix frontend` | Exit 0. |
| `npm run test:browser --prefix frontend` | **7 passed** (22.3 s) — unchanged. |
| `.venv/bin/ruff check .` | Pass. |
| `compileall` (backend, ui, streamlit_app, tests, scripts, agentcore_runtime) | Exit 0. |
| `git diff --check` / leak check | Clean; no uvicorn/playwright processes left. |

#### Measured local results (actual local numbers; offline simulation)

Environment: this macOS host, Python 3.12 (repo `.venv`),
`MOCK_OPENAI=true MODEL_PROVIDER=mock`, network blocked by the harness,
injected fakes only, `--sample 25` (25 evenly spaced rows of the 295-row
synthetic gate corpus), simulated model latency 0 ms. **All timings are
adapter+harness overhead on this machine with fake responses — they say
nothing about live model latency.**

Configuration recorded (this environment): `MODEL_PROVIDER=mock` default in
settings; configured `coaching` = bedrock /
`global.anthropic.claude-haiku-4-5-20251001-v1:0`, `review_deep` = bedrock /
`global.anthropic.claude-sonnet-4-6`, AgentCore runtime ARN configured
(presence recorded, value never); runtime-pinned IDs match the code contract.

Turn outcomes (25 turns per arm, first-attempt structured success): mock
25/25, agentcore 25/25, bedrock_direct 25/25. Latency ms
(p50/p95/max, adapter+harness): mock 0.128/0.504/12.763; agentcore
0.501/0.832/4.916; bedrock_direct 3.367/4.077/4.666. Usage (production
`generation_usage` events, values reported by the fakes, identical by
construction): agentcore and bedrock_direct 25 events each, 175,000 input /
7,500 output tokens total; mock leaves usage honestly unknown (0 events).

Error accounting (production `provider_error_category`): `ThrottlingException`
→ `throttled`, `AccessDeniedException` → `access_denied`,
malformed reply → `structured_output_failure` (agentcore) / `malformed`
(bedrock_direct) — all fail closed as `provider_unavailable`, exactly one
fake call per attempt on both paths. Category differences between the arms
(`structured_output_failure` vs `malformed` for the same malformed reply) are
a recorded real difference in the two adapters' failure vocabulary, not a
defect.

#### Compatibility, rollback and known limits

Measurement only: no provider, model ID, retry configuration, route or default
changed; `MODEL_PROVIDER`, the AgentCore runtime and the direct Bedrock
rollback path are exactly as configured. Rollback is source-only: delete the
harness, its test and the two guide rows. Known limits, documented rather than
silently accepted: injected fakes prove adapter contracts, not live model
capacity, guardrail behavior, session affinity under load or SDK retry
behavior (all recorded in `live_comparison_plan` as live-only, capped,
separately approved evidence); latencies are adapter overhead on one machine;
token totals are fake-reported values routed through the real metering path,
not live usage; and the mock arm validates no structured-output reliability
because it makes no model call.

**Next exact action:** tickets 36–41 are complete; the assignment continues
with ticket 42 (evaluate retrieval for workspace evidence) in this same
session, then stops. Ticket 43+ remains for later writer sessions.

### Ticket 40 complete — evaluate compact prompts and supported prompt caching (2026-11-26 SGT, OpenCode)

**Ticket 40 is implemented and locally verified as a measurement ticket with
no adoption.** A new offline harness —
`scripts/evals/benchmark_prompt_variants.py` — measures the existing canonical
Fast Chat prompts against a harness-local content-preserving compacted
variant, the token cost of selected workspace context at the composer's own
bounds, and the supported `SystemContentBlock` prefix-cache behaviour and
economics that `agentcore_runtime/prompt_cache.py` implements for Claude
Haiku 4.5, then records an adopt/reject recommendation with numbers. Three
measured findings drive the recommendation. (1) The canonical prompt files
contain **zero verbatim duplicate lines** across shared/stage/fast-chat: the
overlapping guidance is semantic restatement, so mechanical content-preserving
compaction (whitespace normalisation + exact-duplicate line dedup) saves only
0.8–1.0% of prefix tokens (28,055 → 27,788 estimated tokens across the five
stage prefixes) with no required pedagogy/evidence/schema/stage/security
marker dropped — meaningful reduction toward 4,000 tokens needs editorial
prompt rewriting, not deduplication, and token reduction remains an
experiment, not an acceptance shortcut. (2) Only **one of five stage prefixes**
(`problem_identification`, 5,777 estimated tokens at the cache estimator's
4.0 chars/token) clears the Haiku 4,096-token cache floor; the other four
(3,674–3,963) receive no cache point today, so enabling the flag would only
ever help one stage in the current rotation. (3) Cache shape checks pass
(off = exact string; on = one `cachePoint`, blocks concatenate back to the
uncached string) and the estimate economics are attractive (90% prefix
read-hit saving, break-even after 2 turns within the 5-minute TTL at ESTIMATE
pricing), but `FAST_CHAT_PROMPT_CACHE_ENABLED` stays off by default: savings
depend on live `cacheRead`/`cacheWrite` usage and real turn timing within the
TTL, which are capped approval-dependent provider evidence, recorded as an
explicit `live_evaluation_plan` and never executed here. No production prompt
file, composer constant or feature flag changed; nothing is staged, committed
or deployed.

Starting revision/branch: `improvement/architecture-responsiveness` with the
dirty ticket 01–39 working tree preserved unchanged apart from this ticket's
files.

#### New files and behavior

| File | Responsibility |
| --- | --- |
| `scripts/evals/benchmark_prompt_variants.py` (new) | Offline harness: `prompt_source_texts` (canonical AgentCore prompt files), `compact_prompt_text`/`duplicate_line_chars` (content-preserving compaction + verbatim-duplicate accounting), `measure_variants` (existing vs compacted per stage topic with required-marker retention), `measure_representative_turns` (25 evenly spaced synthetic turns composed through the production seam `compose_coach_prompt(context_policy="fast_chat")` + `specialist_system_prompt`), `measure_workspace_context_costs` (retrieved/canvas/project context at the composer's own caps), `measure_cache` (eligibility, off/on shapes, ESTIMATE economics with ineligible topics excluded from pricing), `build_report`/`main` (JSON report marked `offline-simulation`, network blocked, `--i-approve-live-aws` refused with exit 2). |
| `tests/scripts/test_benchmark_prompt_variants.py` (new) | Red-first harness contracts (red = missing script): variants measured for all five topics with compacted ≤ existing and `missing_markers == []`; compaction keeps first occurrences and real content; representative turns and workspace-cost scaling recorded; cache eligibility recorded per topic and equal to the floor rule; off/on shape checks; estimate economics with ineligible topics listed; recommendation carries structured `numbers` and an unexecuted live plan; CLI refuses live and writes a `run` block; no boto3 client is ever built. **10 passed.** |
| `scripts/AGENTS.md`, `tests/AGENTS.md` | Script and test-map rows for the new harness and its limits. |

#### Executed validation

| Command/check | Result |
| --- | --- |
| `pytest tests/scripts/test_benchmark_prompt_variants.py` | **Red first** (`ImportError: cannot import name 'benchmark_prompt_variants'`), then green after the harness. Mid-implementation corrections recorded honestly: the first compaction join inflated separator characters (compacted > existing), replaced with single-newline whitespace-normalised output; the marker string `Always include the \`hmw_scaffold_ready\` field...` needed the exact file wording; and the cache shape check originally asserted every stage gets a block list — the real behaviour is string-identical output for the four below-floor prefixes, which is now asserted as such. **10 passed.** |
| Full mock suite | **3,329 passed / 1 skipped** in 170.64 s (baseline 3,318 + this ticket's 10 new tests; suite collected 11 more than the ticket-39 count — attributed to the dirty tree's in-flight parametrised tests, exit 0 with the same single documented skip). |
| `npm test --prefix frontend` | **178 passed / 27 files** — unchanged. |
| `npm run build --prefix frontend` | Exit 0. |
| `npm run test:browser --prefix frontend` | **7 passed** (23.5 s) — unchanged. |
| `.venv/bin/ruff check .` | Pass (unused imports/locals removed after harness cleanup). |
| `compileall` (backend, ui, streamlit_app, tests, scripts, agentcore_runtime) | Exit 0. |
| `git diff --check` / leak check | Clean; no uvicorn/playwright processes left. |

#### Measured local results (actual local numbers; offline simulation)

Environment: this macOS host, Python 3.12 (repo `.venv`), `MOCK_OPENAI=true
MODEL_PROVIDER=mock`, network blocked by the harness; token counts are
`backend.context_planner.estimate_tokens` (3.0 chars/token) plus the cache
module's 4.0 chars/token eligibility estimator — **estimates, not live
tokenizer counts** (the historical live smoke measured 6,366 real input
tokens). Report: `/tmp` run of `--json-output`, reproducible per README
command.

Prompt prefix variants per stage (est tokens, existing → compacted; 0 verbatim
duplicate characters in all five): problem_identification 7,703 → 7,643
(−0.8%); concept_generation 5,127 → 5,075; design_specification 4,898 → 4,847;
ethics_critical 5,283 → 5,231; reflection 5,044 → 4,992 (each −1.0%). Required
markers retained in every compacted variant.

Representative turns (25 evenly spaced rows of the 295-row synthetic gate
corpus, composed through the production seam): AgentCore system prompt p50
7,719 / p95 10,298 / max 10,369 est tokens; legacy composed text p50 6,232 /
max 9,014.

Selected workspace context cost at the composer's own caps (delta est tokens
vs no context): canvas selection at cap (3,500 chars) +1,179; project brief at
cap (8,000 chars) +649; retrieved excerpts 2,000 chars +735, at cap (24,000
chars) +2,735; all contexts at cap +4,563.

Prompt cache (Claude Haiku 4.5, `agentcore_runtime/prompt_cache.py` behaviour):
eligible prefixes = `problem_identification` only (5,777 estimated tokens ≥
4,096 floor); `concept_generation` 3,845, `design_specification` 3,674,
`ethics_critical` 3,963, `reflection` 3,783 — all below the floor, no cache
point inserted, no padding. Shape checks pass for all topics. ESTIMATE
economics for the eligible prefix (USD 1.00 input / 0.10 cache read / 1.25
cache write per MTok, dated third-party figures, prefix tokens only): $0.005777
uncached vs $0.007221 first (write) turn and $0.000578 read-hit turn — 90.0%
saving per repeat turn, break-even after 2 turns within the documented
5-minute TTL. No shared cross-student response cache is involved or proposed.

#### Compatibility, rollback and known limits

Measurement only: no production prompt file, composer constant, feature-flag
default, route or schema changed. Rollback is source-only: delete the harness,
its test and the two guide rows. Known limits, documented rather than silently
accepted: estimator tokens are not tokenizer counts (live usage-based counts
belong to the recorded `live_evaluation_plan`, capped and separately
approved); the compacted variant is a harness-local construction, never a
prompt-file change; the workspace-context scenarios use deterministic
synthetic context bodies of representative size against the real composer
caps, not real student excerpts; the pricing is a dated estimate that must be
confirmed on the AWS pricing page before any cost claim; and the cache
economics model one account prefix shared across turns — per-student turn
mixes and multi-account effects are live-only evidence. The prompt-file SHA
locks (`tests/domain/test_coaching_prompt_baseline.py`) are untouched.

**Next exact action:** tickets 36–40 are complete; the assignment continues
with ticket 41 (compare model and runtime paths fairly, offline comparison
only) in this same session, then 42. Ticket 43+ remains for later writer
sessions.

### Ticket 39 complete — measure and bound backend concurrency (2026-11-25 SGT, OpenCode)

**Ticket 39 is implemented and locally verified.** A new offline harness —
`scripts/benchmark_concurrency.py` — isolates four representative blocking
categories (database writes on a scratch SQLite file, mock-SDK latency,
retrieval, serialization), measures the event-loop lag each causes when
placed on the asyncio loop versus bounded AnyIO threadpool offloading, and
exercises the real SQLite `GenerationAdmission` under overload (more
concurrent acquirers than `max_running`/`max_queued` capacity), recording
actual local numbers into a JSON report explicitly marked
`offline-simulation`. The measurement identified exactly one real on-loop
blocking site — the two `async` upload routes called their blocking
workspace file/SQLite writes directly on the event loop — and that received
the only behavior change: both routes now offload via `run_in_threadpool`,
matching every sync route, with a red-first contract test asserting upload
processing runs in a worker thread. The documented convergence-test flake
(`test_independent_dsql_stores_converge_on_one_provider_turn`) was
investigated: 51 fresh stress runs (40 isolated, 8 whole-file, 3
whole-directory) all passed, and analysis identified the underlying
load-sensitive race — cross-instance SQLite writer collisions in the
DSQL-over-SQLite test seam raise `database is locked`, which
`is_retryable_db_error` did not classify as the OCC analog, so the claim
unit would fail instead of retrying under full-suite disk load. That
classification is now red-first fixed (SQLite busy locks are retryable in
`run_dsql_transaction`; live DSQL behavior is unchanged since DSQL never
emits those messages), and the test's outer result timeout was raised from
8 s to 30 s as documented determinism hardening; the idempotency lease
itself remains the correctness bound. No mechanical async rewrite was made —
the measured evidence confirms the sync-threadpool architecture is already
correct everywhere else. Triage remains `ready-for-agent`; nothing is
staged, committed or deployed.

Starting revision/branch: `improvement/architecture-responsiveness` with the
dirty ticket 01–38 working tree preserved unchanged apart from this ticket's
files.

#### New files and behavior

| File | Responsibility |
| --- | --- |
| `scripts/benchmark_concurrency.py` (new) | Offline harness: `representative_workloads` (database/sdk/retrieval/serialization, deterministic, bounded), `measure_event_loop_lag` (ticker-based loop-lag percentiles on-loop vs `anyio.to_thread` with the bounded limiter), `measure_admission_under_overload` (the real `SQLiteGenerationAdmission` policy with bounded waits and honest rejections), `run_benchmark`/`main` (aggregate JSON report with environment note and a keep-sync-threadpool recommendation). |
| `tests/scripts/test_benchmark_concurrency.py` (new) | Red-first harness contracts: workload categories exist and finish offline; on-loop blocking produces materially larger loop-lag max than offloaded placement; database work records numbers in both placements; admission overload ends in admitted + bounded-wait/rejected covering every requester with waits far under the policy bound; the CLI writes the report. |
| `backend/persistence/dsql_connection.py` | `is_retryable_db_error` now classifies SQLite `database is locked` / `database table is locked` as retryable — the OCC analog in the DSQL-over-SQLite seam and any two-instance shared-file writer race. DSQL production behavior is unchanged (DSQL raises SQLSTATE 40001, already covered). |
| `backend/http/app.py` | The two `async` upload routes (`upload_sources`, `upload_attachments`) run their blocking workspace writes via `run_in_threadpool` instead of directly on the event loop. Request/response bodies, status codes and contracts are unchanged. |
| `tests/persistence/test_storage_providers.py` | Red-first retry test: a unit raising SQLite busy-lock errors twice then succeeding is retried to success, and both busy-lock messages classify as retryable. |
| `tests/http/test_upload_hardening.py` | Red-first event-loop contract: `upload_sources` processing observes a running event loop before the fix and a worker thread after it. |
| `tests/persistence/test_coach_idempotency.py` | Determinism hardening for the convergence test: outer `future.result` bound 8 s → 30 s with a comment recording the once-observed flake and why the lease remains the correctness bound. |
| `tests/AGENTS.md`, `docs/TESTING.md` | Test-map rows for the new harness and the upload offload contract. |

#### Executed validation

| Command/check | Result |
| --- | --- |
| `pytest tests/persistence/test_storage_providers.py::test_run_dsql_transaction_retries_sqlite_busy_lock_as_occ_analog` | **Red first** (`sqlite3.OperationalError: database is locked` propagated un-retried), then green after the retryable classification. |
| `pytest tests/http/test_upload_hardening.py::test_upload_processing_runs_off_the_event_loop` | **Red first** (`assert ['event-loop'] == ['worker-thread']` — the blocking write really was on the loop), then green after `run_in_threadpool` in both upload routes. |
| `pytest tests/scripts/test_benchmark_concurrency.py` | **Red first** (missing script), then green after the harness; one mid-implementation test correction recorded: the admission probe initially asserted `admitted <= max_running`, but admitted counts all eventual admissions over the run — the honest bounded contract is admitted + rejected == requesters with bounded waits. **5 passed.** |
| Flake stress evidence | 40 isolated + 8 whole-file + 3 whole-directory runs of the convergence test passed before the fix; after the busy-lock classification + timeout hardening, 2 further isolated runs and the full suite passed. The original single failure (ticket 35 ledger) is consistent with the now-fixed un-retried busy-lock race under full-suite disk load. |
| Full mock suite | **3,318 passed / 1 skipped** in 168.20 s (3,311 after ticket 38 + this ticket's 7 new tests). |
| Focused set (http + persistence + scripts) | **1,119 passed** in 94.09 s. |
| `npm test --prefix frontend` | **178 passed / 27 files** — unchanged. |
| `npm run build --prefix frontend` | Exit 0. |
| `npm run api:check --prefix frontend` | Pass — no route or schema change. |
| `.venv/bin/ruff check .` | Pass (unused imports removed after harness cleanup). |
| `compileall` (backend, ui, streamlit_app, tests, scripts, agentcore_runtime) | Exit 0. |
| `git diff --check` / leak check | Clean; no processes left. |

#### Measured results (actual local numbers; offline simulation)

Environment: this macOS host, Python 3.12 (repo `.venv`), temp SQLite,
deterministic mock workloads, default scale (40 loop ticks at 5 ms, admission
policy max_running 2 / max_queued 3 / wait 2 s, 8 requesters).

Event-loop lag (ms), on-loop vs bounded-threadpool offloaded:

| Category | on-loop p50 / p95 / max | offloaded p50 / p95 / max |
| --- | --- | --- |
| database | 0.689 / 0.734 / 1.927 | 0.718 / 2.070 / 2.714 |
| sdk (20 ms blocking unit ×3) | 0.734 / 2.922 / **66.437** | 0.700 / 4.189 / **6.140** |
| retrieval | 0.717 / 1.258 / 31.587 | 0.680 / 1.538 / 4.562 |
| serialization | 0.720 / 1.249 / 5.007 | 0.695 / 1.249 / 5.203 |

Admission under overload: 5 admitted / 3 rejected of 8 requesters, max wait
198.346 ms against the 2 s policy bound, `queue_bounded: true` — demand ends
in bounded waits or honest rejections, never unbounded queuing.

Interpretation: blocking work placed on the asyncio loop stalls every
concurrent request by the full blocking duration (sdk category: 66 ms max lag
for 60 ms of work), while bounded offloading keeps max lag at ~6 ms. Every
coaching route is already a sync `def` running in the AnyIO threadpool, and
the generation admission, deep-review background admission and sync
threadpool bounds held under overload; the only on-loop blocking site was the
upload pair, now fixed. These numbers isolate scheduling behavior only — they
are not live model, network or classroom capacity results.

#### Compatibility, rollback and known limits

The upload offload is behavior-preserving (same service call, same error
mapping, same contracts) and the busy-lock retry classification only widens
the retry set for SQLite-emitted messages, which live DSQL never raises.
Rollback is source-only: revert `run_in_threadpool` in the two routes, the
two added retryable strings, the convergence test's timeout comment/value,
and delete the harness/tests/doc rows. Known limits, documented rather than
silently accepted: the harness measures synthetic representative work, not
the app's exact payloads; the upload `await upload.read(...)` byte streaming
remains on the loop by design (it is async I/O, not blocking work); the
event-loop lag probe measures one loop at a time and does not model uvicorn's
production loop under concurrent HTTP; live latency/classroom capacity
belong to ticket 48's separately scoped mixed-load experiments; the flake
fix's busy-lock classification is validated by the store-level retry test,
not by a reproduced end-to-end failure (the original flake did not reproduce
in 51 fresh runs).

**Next exact action:** tickets 36, 38 and 39 are complete; stop here per the
assignment. The new frontier from the dependency graph: 40 (compact prompts /
prompt caching), 41 (model/runtime comparison), 42 (retrieval evaluation),
43 (chat fast with editors), 44 (accessible authoring), 45 (workspace
ownership/defense — newly unblocked by 36), 46 (deterministic frontend and
browser CI — newly unblocked by 36), 47 (workspace recovery rehearsal —
newly unblocked by 36), 48 (mixed classroom workloads — newly unblocked by
39), 50 (aggregate engagement signals — newly unblocked by 36) and 52
(selected coursework export) are all eligible; 49 waits on 48, and 51/53
wait on later tickets. The next writer session should take ticket 40 next in
a fresh context in this same checkout.

### Ticket 38 complete — measure DSQL connection overhead and pooling compatibility (2026-11-25 SGT, OpenCode)

**Ticket 38 is implemented and locally verified as a measurement ticket with
no adoption.** A reproducible offline harness —
`scripts/benchmark_dsql_connections.py` — separates controlled synthetic
connect/auth cost from real local SQL/transaction time and compares the
production fresh-connection strategy (one `connect_dsql` IAM-token connection
per transaction, as shipped) against a script-local bounded pool candidate
modeled on `psycopg_pool` and AWS's documented Aurora DSQL guidance. The
harness runs nine executable pool-contract checks against the candidate —
bounded acquisition, bounded size, lifetime replacement with jitter,
unhealthy-connection replacement, context-manager release, rollback/reset on
error, whole-transaction OCC retry (checkout→work→commit inside each
attempt), no cross-owner contamination, and clean shutdown — and records
actual local numbers into a JSON report explicitly marked
`offline-simulation` with the limit note that mock timings are not live DSQL
results. Current DSQL documentation was verified (2026-11-25) against AWS's
"Connection pooling strategies in Amazon Aurora DSQL" blog and the
`aurora-dsql-connectors` Python README, and the verified claims (100 new
connections/second rate limit, hard 1-hour connection age, server-side
per-transaction multiplexing, recommended psycopg pool bounds min 2–5 /
max 10–20 / 30 s acquisition / 55 min lifetime with jitter, per-connection
token generation, `sslmode=verify-full`) are carried inside the report
itself. **Decision recorded: keep the fresh-connection default** — no
pooling default, no live DSQL calls, no AWS, no configuration change; live
measurement remains separately approved and gated behind
`DSQL_BENCH_ALLOW_LIVE=1` (the `--live` flag refuses without it). Triage
remains `ready-for-agent`; nothing is staged, committed or deployed.

Starting revision/branch: `improvement/architecture-responsiveness` with the
dirty ticket 01–37 working tree preserved unchanged apart from this ticket's
files.

#### New files and behavior

| File | Responsibility |
| --- | --- |
| `scripts/benchmark_dsql_connections.py` (new) | Offline benchmark: `SimulatedDsqlBackend` (real SQLite SQL + synthetic per-connection setup cost), `BoundedConnectionPool` candidate (script-local, never imported by `backend/`), `run_benchmark` (fresh vs pooled with wall/p50/p95/connections-opened), `run_pool_contract_checks` (nine documented constraints as executable checks), verified `DOCUMENTATION_VERIFICATION` claims with source URLs, `LIMITS_NOTE`, and a `main()` CLI whose `--live` mode refuses without the operator opt-in environment. |
| `tests/scripts/test_benchmark_dsql_connections.py` (new) | Red-first harness contracts: both strategies record local numbers with `connections_opened == transactions` for fresh and strictly fewer for the pool; the report carries the documentation claims and the explicit `keep-fresh-connection-default` decision; all nine pool-contract checks pass; live mode exits 2 with a refusal naming `DSQL_BENCH_ALLOW_LIVE` and writes nothing; `main` writes the JSON report offline. |
| `docs/DATABASE.md` | New "Connection strategy and pooling evidence" subsection documenting the harness, the verified AWS constraints with dates, and the keep decision. |
| `docs/operations/ARCHITECTURE_IMPROVEMENTS.md` | The persistence row and P2 milestone now point at the completed offline evidence and the remaining approved-live-run gate. |
| `tests/AGENTS.md` | Test-map row for the new harness suite. |

#### Executed validation

| Command/check | Result |
| --- | --- |
| `pytest tests/scripts/test_benchmark_dsql_connections.py` | **Red first** (`FileNotFoundError` for the missing script), then green after the harness. **5 passed.** Iterative reds during implementation: frozen test clock deadlocked the acquisition wait (fixed with a real-time-offset clock), SQLite cross-thread connections (fixed with `check_same_thread=False`, mirroring pooled psycopg usage), and an incorrectly ordered unhealthy-replacement assertion. |
| Full mock suite | **3,311 passed / 1 skipped** in 158.02 s (3,306 after ticket 36 + this ticket's 5 new tests). |
| Focused set (`tests/scripts/`, `tests/persistence/`) | **635 passed** in 26.53 s. |
| `npm test --prefix frontend` | **178 passed / 27 files** — unchanged. |
| `npm run build --prefix frontend` | Exit 0. |
| `npm run api:check --prefix frontend` | Pass — no contract change. |
| `.venv/bin/ruff check .` | Pass (after removing a leftover duplicate stub and an unused variable). |
| `compileall` (backend, ui, streamlit_app, tests, scripts, agentcore_runtime) | Exit 0. |
| `git diff --check` / leak check | Clean; no processes left. |

#### Measured results (actual local numbers; offline simulation, not live DSQL)

Environment: this macOS host, Python 3.12 (repo `.venv`), scratch SQLite files
in the OS temp directory, synthetic connect cost 25 ms per physical
connection. Default run (`--transactions 200 --concurrency 8
--simulated-connect-ms 25`):

| Strategy | Connections opened | Wall (s) | per-transaction p50 / p95 (ms) |
| --- | --- | --- | --- |
| `fresh` (production shape) | 200 | 0.802 | 30.934 / 37.299 |
| `pooled` (candidate) | 8 | 0.395 | 0.384 / 126.829 |

All nine pool-contract checks passed (`passed: true`). The numbers show the
expected shape, not a live result: with a 25 ms synthetic setup cost the fresh
strategy pays ~31 ms per transaction, while the pool amortizes setup (p50
0.4 ms) but shows a p95 pool-wait spike (≈127 ms) when concurrency briefly
exceeds warm connections — exactly the acquisition-bound trade-off the
documented 30 s acquisition timeout exists to bound. Because the connect cost
is synthetic and DSQL multiplexes connections server-side per transaction,
these numbers cannot justify adoption; they demonstrate the harness works and
what to measure live.

#### Compatibility, rollback and known limits

Purely additive: a new script, a new test file, and documentation rows. No
backend, persistence, schema or API change; the pool candidate is not
imported anywhere in `backend/` and cannot become a default. Rollback is
deleting the script/test/doc rows. Known limits, documented rather than
silently accepted: connect/auth cost is simulated (SQLite + sleep), so no
number here transfers to Aurora DSQL; the pool candidate is untested against
real psycopg connections (the contract checks use the SQLite stand-in, and
`psycopg_pool` itself is not installed in this repository); live measurement
and any future adoption need separate operator approval with request/cost
caps, and would additionally have to prove IAM-token rotation at connection
recycling and behavior across the worker model.

**Next exact action:** ticket 39 (measure and bound backend concurrency;
unblocked by ticket 37) in this same session per the assignment, then stop —
do not start ticket 40.

### Ticket 36 complete — handle cancelled and ambiguous Deep Review execution (2026-11-25 SGT, OpenCode)

**Ticket 36 is implemented and locally verified.** Explicit Deep Review now
has explicit cancellation and honest ambiguity handling alongside ticket 35's
durable worker. The durable job envelope gains three student-visible states —
`cancel_requested` / `cancelled` / `ambiguous` — persisted in the same
owner-scoped notebook settings blob, so they survive navigation and restart
like every other job state. Cancellation is a two-phase cooperative protocol:
a *queued* job is cancelled immediately (it cannot have invoked the paid
model), a *claimed* job records `cancel_requested` and keeps its lease, and
the live worker decides at its pre-invocation boundary — cancel cleanly with
no provider call, or, once the invocation has started, commit the
already-billable result rather than discard or repeat it. A worker that dies
after a cancel request is finalized as `cancelled` on the next read, never
re-run. Ambiguous external outcomes are made explicit: the worker durably
marks `invoked_at` (with a lease heartbeat) before the billable invoke, and
recovery that finds a lapsed lease *after* that marker surfaces the job as
`ambiguous` / `review_outcome_unknown` — it never claims exactly-once, never
silently re-runs a possibly-successful billable call, keeps the admission and
periodic-counter accounting intact (the counter is not reset), and resolves
only through an explicit re-enqueue, which starts a fresh job with a new id.
Ambiguity takes precedence over attempt exhaustion, so a repeatedly crashed
job past `DEEP_REVIEW_MAX_ATTEMPTS` still reads `ambiguous` rather than a
misleading `review_timeout`. The worker pool gained a clean-shutdown seam
(`shutdown_deep_review_executor`, wired into the FastAPI lifespan) that stops
accepting dispatches without blocking on provider work and without losing
durable queued envelopes. A new owner-scoped `POST
/api/v1/threads/{thread_id}/deep-review/cancel` route exposes the protocol;
the browser contract is unchanged because Deep Review routes are outside the
curated reader allowlist (regeneration is byte-identical). Triage remains
`ready-for-agent`; nothing is staged, committed or deployed.

Starting revision/branch: `improvement/architecture-responsiveness` with the
dirty ticket 01–37 working tree preserved unchanged apart from this ticket's
files.

#### New files and behavior

| File | Responsibility |
| --- | --- |
| `backend/specialists/review_orchestration.py` | New statuses `cancel_requested` / `cancelled` / `ambiguous` in the durable status set (active set now includes `cancel_requested`), error codes `review_cancelled` / `review_outcome_unknown`, and a durable `invoked_at` field on the job blob (parsed and defaulted). |
| `backend/student_store.py` | Four fenced store transitions: `request_deep_review_cancellation` (queued→`cancelled` immediately; running→`cancel_requested` keeping the live lease; idempotent; refuses terminal jobs), `cancel_deep_review_job` (cancel-requested→`cancelled` under the same supersedence fence as completion), `mark_deep_review_job_invoked` (persists `invoked_at` + heartbeat for the current owner only; `False` tells a superseded worker never to invoke), and `mark_deep_review_job_ambiguous` (running→`ambiguous` fail-closed against a live lease). All are additive settings-blob writes with OCC retry loops. |
| `backend/persistence/dsql_student_store.py` | The four new methods added to `_OCC_WRITE_METHODS`, so each runs as a whole DSQL transaction with SQLSTATE 40001 retry. |
| `backend/coaching/execution.py` | `cancel_deep_review(thread_id)` service method; worker honors `cancel_requested` at the pre-invocation boundary and marks the invocation durably before `workflow.run` (a superseded claim returns without invoking); `get_deep_review_job` recovery finalizes stale cancel requests, surfaces stale post-invocation jobs as `ambiguous` (precedence over attempt exhaustion), and reuses a cancel-requested job on enqueue instead of starting a second worker. |
| `backend/coaching/deep_review_jobs.py` | Public `shutdown_deep_review_executor()` clean-shutdown seam (cancels unstarted dispatches, drops the pool, never blocks on provider work); the test reset helper now delegates to it. |
| `backend/http/app.py` | New `POST /api/v1/threads/{thread_id}/deep-review/cancel` route (404 without a job or notebook, terminal jobs answer unchanged) plus the lifespan shutdown hook; the GET route docstring documents the ambiguous outcome. |
| `backend/domain.py` | `DeepReviewJobStatus` gains `CANCEL_REQUESTED`, `CANCELLED`, `AMBIGUOUS`. |
| `tests/persistence/test_deep_review_leases.py` | Six red-first store-contract tests: queued cancellation is terminal without a worker; a running job keeps its lease under cancel-request; terminal jobs refuse; the live worker's fenced acknowledgement (and a foreign worker's refusal); a recovery claim of a cancel-requested job is refused. |
| `tests/domain/test_deep_review_cancellation.py` (new) | Eight red-first execution tests: queued cancellation never invokes and stays cancelled; the claimed worker cancels before the invocation (deterministic claim-then-cancel wrapper); cancel without a job is `None`; crash after the invoked marker reads `ambiguous` with no resubmission and retained counter; ambiguity beats attempt exhaustion; a crashed cancel-requested job is finalized cancelled; explicit re-enqueue after ambiguity runs a fresh job; clean shutdown loses no queued work and never hangs. |
| `tests/http/test_deep_review.py` | Three red-first route tests: queued cancellation returns `cancelled` with no snapshot; terminal jobs answer idempotently; 404 without a job or notebook. |
| `tests/test_architecture_contracts.py` | Route inventory gains the cancel route; StudentStore public and `_OCC_WRITE_METHODS` inventories gain the four new methods. |
| `backend/AGENTS.md`, `tests/AGENTS.md` | Module/test-map rows document the new states, the `invoked_at` marker, the shutdown seam and the cancellation/ambiguity contracts. |

#### Executed validation

| Command/check | Result |
| --- | --- |
| `pytest tests/persistence/test_deep_review_leases.py` (cycle 1) | **Red first** (`AttributeError: 'StudentStore' object has no attribute 'request_deep_review_cancellation'`), then green after the four fenced store transitions + status constants. |
| `pytest tests/domain/test_deep_review_cancellation.py` (cycle 2) | **Red first** (`'CoachApplicationService' object has no attribute 'cancel_deep_review'`; `module 'deep_review_jobs' has no attribute 'shutdown_deep_review_executor'`; recovery behaviors failing on the missing states), then green after the service method, worker boundaries and recovery branches. **8 passed.** |
| `pytest tests/http/test_deep_review.py` (cycle 3) | **Red first** (cancel route 404; the paused worker then hit its 2 s release timeout), then green after the route + lifespan wiring. **17 passed.** |
| Focused set (deep_review execution/restart/context/projection, leases, DSQL, cancellation, http, architecture contracts) | **76 passed** (all Deep Review store/worker/API contracts plus the architecture inventories). |
| Full mock suite | **3,306 passed / 1 skipped** in 150.72 s (3,290 after ticket 37 + this ticket's 16 new tests). |
| `npm test --prefix frontend` | **178 passed / 27 files** — unchanged. |
| `npm run build --prefix frontend` | Exit 0 (2.30 s). |
| `npm run api:check --prefix frontend` | Pass (drift check clean); `api:export`/`api:generate` re-run verified byte-idempotent — Deep Review routes are outside the curated reader allowlist, so the browser contract did not change. |
| `.venv/bin/ruff check .` | Pass after removing two unused imports the new recovery branch made unnecessary. |
| `compileall` (backend, ui, streamlit_app, tests, scripts, agentcore_runtime) | Exit 0. |
| `git diff --check` / leak check | Clean; no uvicorn/playwright processes left. |

#### Compatibility, rollback and known limits

No migration: the new states and `invoked_at` live in the existing JSON
settings blob; legacy blobs without the new fields parse with `invoked_at`
absent (never ambiguous) and keep their existing semantics. The one REST
route addition is additive and owner-scoped; the OpenAPI export and generated
client are byte-identical because the reader allowlist does not include
Deep Review. Rollback is source-only: revert `review_orchestration.py`
constants/parse, the four store methods, the execution worker/recovery
branches, `shutdown_deep_review_executor`, the route, the domain enum values,
the inventories and the three test files; jobs persisted with new states
would need those states to parse, so revert before any student exercises
cancellation in a shared deployment.

Known limits, documented rather than silently accepted: cancellation after
the invocation has started does not discard the result — the call is already
billable, so the validated result is committed and the job reads `completed`;
the `cancel_requested` window is visible to the student but the outcome is
the worker's phase boundary, not a guarantee. An `ambiguous` job never tells
the student whether the provider call succeeded — that is honest: the
process died between the invoke and the commit, so certainty is unavailable;
the cost reservation is retained (counter not reset) and only an explicit
re-enqueue (a new billable job) proceeds. Recovery finalization of stale
cancel requests trusts the read-time lease check, so a worker that renews its
lease in the microseconds between the check and the write can still win —
the store transitions are fenced, and the worst case is a completed job
after a cancel request, never a double result or a lost reservation.

**Next exact action:** ticket 38 (measure DSQL connection overhead and
pooling compatibility; unblocked since ticket 01) is the next eligible
frontier ticket, then 39 (blocked by 37, which is complete). Start the next
ticket in a fresh writer session in this same checkout, preserving the dirty
working tree.

### Ticket 37 complete — trace a coaching request without recording private content (2026-11-25 SGT, OpenCode)

**Ticket 37 is implemented and locally verified.** The existing privacy-safe
telemetry now distinguishes the three coaching-request boundaries the ticket
names — runtime-internal first token/reply text, the first *safe visible*
text, and the final *confirmed* completion — and labels unknown durations
instead of leaving them silent. `coach_turn_perf` gains
`first_safe_reply_ready_ms` (measured at the reply-ready boundary, i.e. after
validation, before saving) and `turn_confirmed_ms` (measured once the turn is
durably persisted), both request-relative so they read against
`request_total_ms`, plus a `first_text_timing_source` label
(`runtime_reported` / `not_reported`) so a provider that reports no internal
first-token timing is explicitly marked as unmeasured. Correlation is closed
end-to-end: the `http_request` access log now carries the same opaque
`X-Request-ID` the browser already sends and the TIMING lines, coach-turn
logs and `coach_turn_perf` events already use, so one coaching request can be
followed from browser UI TIMING through admission, database, retrieval,
context, runtime/provider, validation, persistence and idempotent-replay
accounting without any new observability service. No student text, prompts,
notebook ids, cookies or credentials are recorded anywhere on these paths;
guardrail latency stays out of local measurements because no guardrail call
is observable in mock mode (the configured flag remains), and that limit is
documented. Triage remains `ready-for-agent`; nothing is staged, committed
or deployed.

Starting revision/branch: `improvement/architecture-responsiveness` with the
dirty ticket 01–35 working tree preserved unchanged apart from this ticket's
files.

#### New files and behavior

| File | Responsibility |
| --- | --- |
| `backend/turn_perf.py` | `SAFE_PERF_FIELDS` gains `first_safe_reply_ready_ms`, `turn_confirmed_ms` and `first_text_timing_source` (still allowlist-gated: unknown keys are rejected and string values are content-hint screened). New `mark_elapsed(name)` records a request-relative phase boundary (distinct from span durations). `snapshot()` sets `first_text_timing_source` to `runtime_reported` when the provider reported `agentcore_ttft_ms` / `model_first_content_ms` / `model_first_reply_text_ms`, else `not_reported`. |
| `backend/coaching/execution.py` | The submit path marks `first_safe_reply_ready_ms` at the existing `emit_coach_reply_ready` boundary (the safety-validated visible-text moment, before persist) and `turn_confirmed_ms` immediately after `persist_coach_turn` returns (the durably-confirmed moment). No other behavior changes; boundaries no-op when no accumulator is bound. |
| `backend/operational_metrics.py` | `record_http_request` accepts an optional opaque `request_id` and includes it in the `http_request` JSON event only when present; all other callers are unaffected. |
| `backend/http/app.py` | The request-id middleware passes the stamped `X-Request-ID` value to both access-log emissions (success and unhandled-exception paths), completing browser↔access-log↔TIMING↔perf correlation. |
| `tests/domain/test_coach_turn_perf.py` | Two new red-first tests: a full `service.submit` records both boundaries in order (`0 ≤ first_safe_reply_ready_ms ≤ turn_confirmed_ms ≤ request_total_ms`) with `first_text_timing_source == "not_reported"` for a provider that reports no first-text metrics; a runtime payload carrying `time_to_first_token_ms`/`model_first_reply_text_ms` is labeled `runtime_reported` with the values recorded. Both assert the payload passes `assert_payload_is_safe` and contains no student text. |
| `tests/http/test_privacy_logging.py` | New red-first test: the `http_request` access-log event carries the client's `X-Request-ID` and no thread/student content. |
| `backend/AGENTS.md`, `tests/AGENTS.md` | `turn_perf.py` module row and the coach-turn-perf / privacy-logging test-map rows document the boundaries, the label and the access-log correlation. |

#### Executed validation

| Command/check | Result |
| --- | --- |
| `pytest tests/domain/test_coach_turn_perf.py::test_submit_records_visible_text_and_confirmation_boundaries` | **Red first** (`AssertionError: assert False` — `first_safe_reply_ready_ms` absent), then green after `mark_elapsed` + the two execution-path boundaries. |
| `pytest tests/domain/test_coach_turn_perf.py::test_runtime_reported_first_text_is_labeled_as_measured` | **Red first** (`KeyError: 'first_text_timing_source'`), then green after the allowlist + snapshot label. |
| `pytest tests/http/test_privacy_logging.py::test_http_request_log_correlates_the_client_request_id` | **Red first** (`KeyError: 'request_id'` on the access-log event), then green after the middleware wiring. |
| Focused set (coach_turn_perf, privacy_logging, coach_progress, ui_perf_logging, test_api, evidence_scope_turn) | **100 passed.** |
| Full mock suite | **3,290 passed / 1 skipped** in 160.19 s (3,287 after ticket 35 + this ticket's 3 new tests). |
| `npm test --prefix frontend` | **178 passed / 27 files** — unchanged (no frontend surface in this ticket). |
| `npm run build --prefix frontend` | Exit 0. |
| `npm run test:browser --prefix frontend` | **7 passed** (24.0 s) — unchanged journeys. |
| `npm run api:check --prefix frontend` | Not applicable — no route or schema change. |
| `.venv/bin/ruff check .` | Exit 0. |
| `compileall` (backend, ui, streamlit_app, tests, scripts, agentcore_runtime) | Exit 0. |
| `git diff --check` / leak check | Clean; no uvicorn/playwright processes left. |

#### Compatibility, rollback and known limits

No schema, migration or API-contract change: the three new fields are additive
entries on an existing allowlisted JSON log event, the access-log change adds
one optional key to an existing event (omitted for callers that do not pass
it), and no route, REST schema or persisted data changed. The logged
`X-Request-ID` is the same bounded, opaque correlation value already echoed in
response headers, coach-turn logs and TIMING lines, so the exposure surface is
unchanged. Rollback is source-only: revert `turn_perf.py`, the two execution
boundary marks, the `record_http_request`/middleware wiring, the three tests
and the two guide rows.

Known limits, documented rather than silently accepted: guardrail latency is
not locally measurable (ApplyGuardrail runs runtime-side; mock mode makes no
guardrail call, so only `guardrail_configured` is recorded) — live guardrail
timings belong to the separately-approved live evidence; admission and
reconciliation timings remain where they already exist (generation-admission
accounting events, idempotency claim/persist/complete spans and the usage
events' `replayed` flag) and were not duplicated; `first_safe_reply_ready_ms`
is only recorded on paths that reach the reply-ready boundary (idempotent
replays that return a stored turn legitimately leave it absent, and the
`not_reported` first-text label covers the unknown); and correlation remains
request-scoped — Deep Review worker phases log their own operational events
without a browser request id, since no browser request is waiting on them.

**Next exact action:** ticket 36 (handle cancelled and ambiguous Deep Review
execution; unblocked by ticket 35) is the next eligible frontier ticket, then
38. Start the next ticket in a fresh writer session in this same checkout,
preserving the dirty working tree.

### Ticket 35 complete — resume queued Deep Review safely after restart (2026-11-25 SGT, OpenCode)

**Ticket 35 is implemented and locally verified.** Explicit Deep Review now
demonstrably survives a restart: the durable job envelope (owner-scoped
notebook settings blob in SQLite/DSQL) keeps frozen input revision, idempotent
reuse, status, attempts, claim `lease_owner`/`lease_expires_at`, heartbeat time
and result/failure metadata; a worker claims queued or expired-lease jobs
atomically, heartbeats the lease around the bounded model invoke, commits
idempotently with supersedence fencing, and the owner's next job read recovers
safe queued/claimed work within the bounded attempt budget — exhausted
attempts fail honestly with `review_timeout` and preserved admission
accounting, and no stale result can overwrite newer authoritative student
state. One important note on resume state: the lease/heartbeat/recovery
machinery and two restart tests were found in the working tree from an
interrupted prior session with three red tests; this session completed the
TDD — one genuine behavior change red-first (the DSQL lease heartbeat was not
OCC-wrapped, so a serialization conflict mid-invoke would kill a healthy
worker), one fixture-bug fix, two obsolete-semantics tests rewritten to the
bounded-recovery design, the deterministic store-level lease/fence fault
contracts, and the architecture documentation that was still missing. No
queue infrastructure was added; the design decision is documented. Triage
remains `ready-for-agent`; nothing is staged, committed or deployed.

Starting revision/branch: `improvement/architecture-responsiveness` with the
dirty ticket 01–34 working tree preserved unchanged apart from this ticket's
files.

#### New files and behavior

| File | Responsibility |
| --- | --- |
| `backend/persistence/dsql_student_store.py` | `heartbeat_deep_review_job` joins `_OCC_WRITE_METHODS`, so a DSQL serialization conflict during the pre/post-invoke lease heartbeat retries as one whole OCC unit instead of surfacing to the worker and killing a live claim. One-line additive change; SQLite path untouched. |
| `tests/persistence/test_deep_review_leases.py` | New deterministic SQLite lease contracts: atomic claim refuses a live second claimant; an expired lease is re-claimed with `attempts` incremented; claims refuse once attempts are exhausted; heartbeat renews only the current owner's lease; and a superseded claimant can neither commit a duplicate result nor overwrite the winner's terminal state with a failure, while the live owner's completion stays idempotent. |
| `tests/persistence/test_deep_review_dsql.py` | New red-first test: heartbeat with an injected SQLSTATE 40001 retries through `run_dsql_transaction` (failed before the fix because the call bypassed the OCC wrapper entirely) and still extends the held lease. |
| `tests/domain/test_deep_review_restart.py` | Fixture fix only: the crash-after-claim recovery test seeded `stage_at_start="reflection"` while the fake runtime answered with the default stage, so the review failed closed as `wrong_stage`; the fake now answers with the matching frozen stage. Both restart-survival tests (queued crash before invocation; expired-lease crash after claim, attempts 1→2) pass. |
| `tests/http/test_deep_review.py` | `test_stale_running_deep_review_is_failed_on_get` replaced by `test_stale_running_deep_review_recovery_is_bounded_on_get`: with attempts remaining, a stale claim is recoverable work (the read seam resubmits; with a no-op submitter the job stays `running`); with attempts exhausted, GET fails honestly with `review_timeout` and the admission counter is preserved. |
| `tests/domain/test_deep_review_execution.py` | The thread-raced stale-worker test (obsolete "stale ⇒ immediate fail" semantics that conflicted with lease recovery) is removed; its promise — a late claimant can never replace a newer authoritative review — is now covered deterministically by the store-level supersedence-fence contracts plus the restart tests. Four orphaned imports removed. |
| `tests/test_architecture_contracts.py` | `heartbeat_deep_review_job` added to both the public `StudentStore` inventory and the DSQL OCC wrapper inventory. |
| `backend/coaching/deep_review_jobs.py` | Module docstring corrected: durable queued/claimed work is recovered on the next owner read within the bounded budget (the old text claimed restart loses jobs). |
| `backend/student_store.py` | One unused `_parse_job_timestamp` import removed from `complete_deep_review_job` (ruff; lease logic unchanged). |
| `docs/LOCAL_DEMO_IMPLEMENTATION.md` | New Durable Deep Review paragraph: envelope persistence, atomic claim/heartbeat/idempotent fenced commit, bounded restart recovery, frozen-provenance guarantee, at-least-once (never exactly-once) inference semantics, and the explicit design decision that the persistence-backed single-worker design suffices at classroom scale — a queue/Step Functions would need evidence, approval and cost analysis. |
| `tests/AGENTS.md` | Test map updated for the new leases file, the restart file and the bounded-recovery HTTP coverage. |

#### Executed validation

| Command/check | Result |
| --- | --- |
| `pytest tests/persistence/test_deep_review_dsql.py::test_dsql_heartbeat_retries_sqlstate_40001_and_extends_lease` | **Red first for the intended reason** (`assert 0 == 2` — the heartbeat never entered `run_dsql_transaction`), then green after the one-line `_OCC_WRITE_METHODS` addition. |
| `pytest tests/test_architecture_contracts.py` | Red twice while wiring (public inventory, then OCC inventory, missing the new name — confirming the change surface), then green. |
| `pytest tests/persistence/test_deep_review_leases.py` | 5 passed. One intermediate failure was a test bug (the attempts-exhausted test had not seeded prior attempts, so the first claim correctly succeeded) — fixed in the test, not the implementation. These five contracts passed against the pre-existing implementation and are the ticket's mandated fault-coverage regression evidence, not manufactured reds. |
| `pytest tests/domain/test_deep_review_restart.py` | Red first (fixture stage mismatch → `wrong_stage` fail-closed), green after the fake answers with the frozen stage. |
| Focused deep-review + contracts set (leases, dsql, restart, execution, http, architecture) | **60 passed.** |
| Full mock suite | Run 1: 1 failed (`tests/persistence/test_coach_idempotency.py::test_independent_dsql_stores_converge_on_one_provider_turn` — exact-equality comparison across two concurrent threads with a 0.15 s provider delay; passed 3/3 in isolation and in two subsequent full runs, so recorded as a transient load flake unrelated to this ticket's changes). Run 3 (authoritative): **3,287 passed / 1 skipped** in 153.03 s (3,280 after ticket 34 + 5 lease + 1 heartbeat + 2 restart tests − 1 removed obsolete test). |
| `npm test --prefix frontend` | **178 passed / 27 files** — unchanged from ticket 34 (no frontend surface in this ticket). |
| `npm run build --prefix frontend` | Exit 0. |
| `npm run test:browser --prefix frontend` | **7 passed** (22.7 s) — unchanged journeys. |
| `npm run api:check --prefix frontend` | Not applicable — no route or schema change. |
| `.venv/bin/ruff check .` | 5 auto-fixable findings fixed (4 orphaned imports from the removed test, 1 pre-existing unused import in the lease completion path), then exit 0. |
| `compileall` (backend, ui, streamlit_app, tests, scripts, agentcore_runtime) | Exit 0. |
| `git diff --check` / leak check | Clean; no uvicorn/playwright processes left. |

#### Compatibility, rollback and known limits

No schema or migration change: the job envelope already lives in the owned
notebook's persisted settings blob, and this ticket's only production change
is one method name added to the DSQL OCC retry wrapper list (additive; SQLite
behavior is untouched; legacy no-lease claim calls keep their compatibility
path). Rollback is source-only: remove the name from `_OCC_WRITE_METHODS` and
the two contract inventories, restore the three rewritten/removed tests and
the docstring, and delete the new leases test file. Restart recovery, bounded
attempts, fencing and admission accounting are unchanged from the
pre-ticket design except where the two rewritten tests now document it.

Known limits, documented rather than silently accepted: Deep Review outcomes
are at-least-once, not exactly-once — an inference possibly completed before a
crash surfaces as a bounded retry or an honest `review_timeout`, never as a
silently duplicated billable call; cancellation and ambiguous-outcome
reconciliation are ticket 36's scope; the envelope allows one in-flight job
per notebook by design (duplicate enqueues reuse it); and the transient
`test_independent_dsql_stores_converge_on_one_provider_turn` flake observed
once under full-suite load is recorded here as a known risk for ticket 39's
concurrency work.

**Next exact action:** ticket 37 (trace a coaching request without recording
private content; blocked by 1 ✓) is the next eligible frontier ticket, then
36 (now unblocked by this ticket), then 38. Start the next ticket in a fresh
writer session in this same checkout, preserving the dirty working tree.

### Ticket 34 complete — make stage requirements actionable (2026-11-25 SGT, OpenCode)

**Ticket 34 is implemented and locally verified.** Each Review stage row now
shows what a useful deliverable looks like: an authored, deterministic
criteria list per Thinking Path stage, projected server-side through the
existing `project_resume` → `ReaderProject` seam and rendered in the stage
detail directly beneath the saved next action, one tap from the existing
course tools, saved-work link and coach summary. The criteria restate the
same CDE2300-aligned expectations that already drive `_STAGE_WORK` actions
and the lecture templates — no new schedule, assessment rule or completion
authority exists anywhere in the path, and `LearningProgressService`
confirmation remains the only way a stage completes or advances. The
curriculum-activities question is answered honestly in the architecture doc:
the available CDE2300 evidence supports the contextual tools already shipped,
so resumable configurable activities are recorded as a documented curriculum
gap rather than invented. Stage prompt files are untouched (SHA lock intact);
the change is application-layer projection plus display. Triage remains
`ready-for-agent`; nothing is staged, committed or deployed.

Starting revision/branch: `improvement/architecture-responsiveness` with the
dirty ticket 01–33 working tree preserved unchanged apart from this ticket's
files.

#### New files and behavior

| File | Responsibility |
| --- | --- |
| `backend/learning/requirements.py` | New `stage_criteria(stage_id)`: authored per-stage criteria tuples aligned with the existing deliverable actions and lecture tools; returns `()` for unknown stage ids so an unrecognized saved stage can never invent requirements. Pure data — no model call, no completion logic. |
| `backend/learning/resume.py` | `StageResume` gains `criteria: list[str]` (default `[]`); `project_resume` populates it from `stage_criteria` alongside the existing deterministic next action. Read-only projection; stages, decisions and unlocks are unchanged. |
| `backend/http/notebook_reader.py` | No code change needed — `ReaderStage` extends `StageResume`, so criteria flow through the existing allowlisted `readerProject` operation automatically. |
| `frontend/openapi/reader.json`, `frontend/src/api/generated/*` | Regenerated REST contract adds `criteria` on `ReaderStage` (server default `[]`); no new schema names, so the allowlist set is unchanged. |
| `frontend/src/api.ts`, `frontend/src/api/client.ts` | `Stage` gains `criteria: string[]`; the client materializer applies the documented `[]` server default. |
| `frontend/src/ThinkingPath.tsx`, `frontend/src/styles.css` | The Review stage detail shows a "What a useful deliverable looks like" criteria list beneath `next_action` for every expanded stage, next to the existing course tools and saved-work links; no criteria text is presented as completion and unavailable stages keep their existing "Not available yet." copy. |
| `tests/http/test_reader_project.py`, `frontend/src/ThinkingPath.test.tsx`, `frontend/src/HomeView.test.tsx` | New seam tests: criteria projected per stage through the authenticated reader project (including the unknown-stage-truthfulness guard), criteria shown next to the next action once a stage is expanded, criteria never presented as completion or unlocking, and the typed fixture updates. |
| `docs/LOCAL_DEMO_IMPLEMENTATION.md` | Ticket 34 paragraph: criteria are authored restatements of existing guidance; resumable configurable activities are a recorded curriculum gap (no CDE2300 evidence for schedules/assessment rules/lecturer-configured sequences), not a silent omission. |

#### Executed validation

| Command/check | Result |
| --- | --- |
| `pytest tests/http/test_reader_project.py::test_reader_project_projects_stage_criteria` | Red first (`KeyError: 'criteria'` — no criteria existed on the projection), then green after `requirements.py` + the `StageResume` field. |
| `npx vitest run src/ThinkingPath.test.tsx` | Red first ("What a useful deliverable looks like" absent from the expanded stage detail), then green after the `StageDetail` criteria block. |
| `pytest tests/http/test_reader_project.py tests/http/test_reader_workspace.py tests/domain/test_student_journey.py` | 36 passed. |
| `npm test --prefix frontend` | **178 passed / 27 files** (baseline 176/26; +1 test file, +2 tests). |
| `npm run build --prefix frontend` | Exit 0 (`tsc --noEmit` + Vite production build) after the typed fixture updates. |
| `npm run api:check --prefix frontend` | Exit 0. The generator again emitted identical `" 3"`-suffixed duplicate copies in `src/api/generated/` — the documented pre-existing toolchain quirk, byte-identical same-run output, left untouched. |
| `npm run test:browser --prefix frontend` | **7 passed** — unchanged chat/restart journeys. |
| `.venv/bin/ruff check .` | Exit 0. |
| `compileall` (backend, ui, streamlit_app, tests, scripts, agentcore_runtime) | Exit 0. |
| Full mock suite | **3,280 passed / 1 skipped** (3,279 after ticket 33 + this ticket's 1 new backend test). |
| Post-run leak check | No criteria copy contains student or source content (all authored static lines); `git diff --check` clean. |

#### Compatibility, rollback and known limits

No schema or migration change: `criteria` is computed per read from authored
data, persisted nowhere, and additive on every existing response (server
default `[]`). The generated REST change is one new optional-to-materialize
field on an existing schema; no new schema names and no allowlist edit were
needed. Stage authority is untouched: criteria are static deliverable
descriptions — nothing reads them when confirming, resolving or selecting a
stage, and the prompt SHA lock was not touched. Rollback is source-only:
revert `requirements.py`, the `resume.py` field, the reader/UI wiring and the
two test files, regenerate the REST types.

Known limits, documented rather than silently accepted: criteria describe the
generic deliverable, not personalized feedback (saved coach feedback, Review
improvements and Facione tips remain the personalized surfaces); the
resumable-activities checkbox is satisfied by recording the curriculum gap —
any future activity feature requires actual CDE2300 evidence and existing
lecturer authority first; and the display surface is the Review stage detail
— surfacing criteria in the composer or chat briefings remains future work
and would need its own friction evidence.

**Next exact action:** ticket 35 (resume queued Deep Review safely after
restart; blocked by 1 ✓) is the next eligible frontier ticket, then 37, then
36 (blocked by 35). Start the next ticket in a fresh writer session in this
same checkout, preserving the dirty working tree.

### Ticket 33 complete — show deduplicated confirmed milestone recaps (2026-11-25 SGT, OpenCode)

**Ticket 33 is implemented and locally verified.** When the student confirms a
stage recommendation through the existing `LearningProgressService`
confirmation flow, one deterministic recap is now persisted inside the same
SQLite transaction: accomplishments and changes reuse the validated saved
assessment fields, remaining gaps reuse the assessment's saved missing
reasoning elements, relevant work lists the student's own saved stage-tagged
contributions (lecture help excluded), and the next action is the authored
deterministic prompt for the next stage. The recap binds to the confirmed
transition id, stage and next stage, and is keyed one-per-confirmed-stage so
repeated confirmation and reload can never duplicate it (bounded history of
10). Recaps are projected read-only on the reader project resource — malformed
saved entries are dropped — and the Home resume card shows the most recent
one. There is no model call anywhere, recaps never complete or advance a
stage, and page loads only read persisted data. Triage remains
`ready-for-agent`; nothing is staged, committed or deployed.

Starting revision/branch: `improvement/architecture-responsiveness` with the
dirty ticket 01–32 working tree preserved unchanged apart from this ticket's
files.

#### New files and behavior

| File | Responsibility |
| --- | --- |
| `backend/learning/recaps.py` | New `MilestoneRecap`/`RecapWork` contracts with stable content-derived ids (`recap-<sha1(transition)>`), `build_milestone_recap` (deterministic from the confirmed transition, saved assessment and saved stage work; a same-stage target builds nothing) and `merge_milestone_recaps` (one recap per confirmed stage, malformed entries dropped, history capped at `MAX_STAGE_RECAPS = 10`). |
| `backend/learning_service.py` | On an accepted resolve, builds the recap from the pending transition plus the notebook's saved messages and merges it into the metadata patch — inside the same atomic transition, so a crash cannot confirm a stage without its recap or the reverse. A recap build failure is logged and never fails the confirmation. |
| `backend/student_store.py` | `apply_phase_transition_decision` carries the bounded `milestone_recaps` patch through the transaction (recaps are settings metadata, not progress fields, so they pass the progress overlay untouched). |
| `backend/persistence/store/contracts.py` | `SETTINGS_KEYS` gains `milestone_recaps` additively (no schema or migration change; the key simply persists in the existing notebook settings blob like `journey_stage_reviews`). |
| `backend/http/notebook_reader.py` | `ReaderProject.recaps` (default `[]`) projects validated saved recaps; invalid entries are dropped. |
| `frontend/src/api.ts`, `frontend/src/api/client.ts`, `frontend/openapi/reader.json`, `frontend/src/api/generated/*` | Regenerated REST types add `MilestoneRecap`/`RecapWork` and `recaps` on `ReaderProject`; the client materializer applies the documented server defaults; `MilestoneRecapView` mirrors the public contract. |
| `frontend/src/HomeView.tsx` | The resume card shows the most recent persisted recap as a "Milestone recap" region: confirmed stage, accomplishments, what changed, still-open gaps and the next action — read-only history with no stage authority and no page-load generation. |
| `tests/domain/test_milestone_recaps.py`, `tests/domain/test_learning_service.py`, `tests/http/test_reader_project.py`, `tests/scripts/test_export_reader_openapi.py` | New seam tests: deterministic bounded builder, dedupe/cap/hostile-entry handling, recap persistence through a real confirmed workflow turn, HTTP projection with malformed-entry dropping, and the allowlist gaining `MilestoneRecap`/`RecapWork`. |

#### Executed validation

| Command/check | Result |
| --- | --- |
| `pytest tests/domain/test_milestone_recaps.py` | 3 passed (red first: the module did not exist; two intermediate reds were test bugs — the filler recaps reused a same-stage target the builder correctly rejects, and a wrong stage id `ethics_critical_thinking` that is not a Thinking Path id — fixed in the test, not the implementation). |
| `pytest tests/domain/test_learning_service.py::test_confirmation_persists_one_deduplicated_milestone_recap` | Red first (no recap persisted: the transition transaction dropped the unknown metadata key), then green after the additive carry-through in `student_store.py` + `SETTINGS_KEYS`. |
| `pytest tests/http/test_reader_project.py::test_reader_project_projects_saved_milestone_recaps` | Red first (`KeyError: 'recaps'` — the field did not exist), then green. |
| `npx vitest run src/HomeView.test.tsx` | 4 passed (the recap test red first: no "Milestone recap" region existed). |
| `npm test --prefix frontend` | **176 passed / 26 files** (was 175/26; one existing client test updated to expect the documented empty `recaps` default). |
| `npm run build --prefix frontend` | Exit 0 (`tsc --noEmit` + Vite production build). |
| `npm run api:generate --prefix frontend` + `npm run api:check --prefix frontend` | Regeneration deterministic; check exit 0. Note: this toolchain's generator writes twelve identical `​" 3"`-suffixed duplicate copies alongside the real generated files (verified reproducible from the pre-ticket spec too, so it predates this ticket); `src/api/generated` was left in the generated state that makes the tree comparison pass, as before this session. |
| `npm run test:browser --prefix frontend` | **7 passed** — unchanged chat journeys. |
| `.venv/bin/ruff check .` | Exit 0 (after removing one unused test import). |
| `compileall` (backend, ui, streamlit_app, tests, scripts, agentcore_runtime) | Exit 0. |
| Full mock suite | **3,279 passed / 1 skipped** (3,274 after ticket 32 + this ticket's 5 new backend tests). |
| Post-run leak check | No uvicorn/playwright processes; `git diff --check` clean. |

#### Compatibility, rollback and known limits

No schema or migration change: recaps live in the existing notebook settings
metadata blob under the additive `milestone_recaps` key (absent on every
existing notebook; `SETTINGS_KEYS` only controls which metadata keys persist,
so legacy data reads exactly as before). The REST contract change is additive
(`recaps` absent on no response — the server default `[]` — and only new
schema names added), and the allowlist test documents both new schemas.
Stage authority is untouched: recaps are written only after the existing
confirmation flow has already accepted a recommendation and are pure data —
nothing reads them to complete or advance a stage. Rollback is source-only:
revert `recaps.py`, the `learning_service`/`student_store`/`contracts`
wiring, the reader projection and allowlist, regenerate the REST types, and
delete the new tests plus the HomeView recap card and its test.

Known limits, documented rather than silently accepted: one recap exists per
confirmed stage, so a later re-confirmation of the same stage replaces the
earlier recap (the confirmation flow's own revision guards still apply — this
is a replace, not a duplicate); recap content is deterministic from the saved
recommendation's assessment, so a slim Fast Chat confirmation yields a
shorter recap rather than a fabricated one; relevant work lists at most the
two most recent saved stage contributions; and the display surface is the
Home resume card — an in-chat Thinking Path rendering of historical recaps
remains future work.

**Next exact action:** with 31, 32 and 33 done, the eligible frontier from the
approved graph is 34 (blocked by 12 ✓, 16 ✓, 21 ✓), 35, 37–40, 42 (blocked by
27 ✓, 29 ✓) and 44/46/47/50/52 as their remaining blockers close. Start the
next ticket in a fresh writer session in this same checkout, preserving the
dirty working tree.

### Ticket 32 complete — resume a project from persisted work (2026-11-25 SGT, OpenCode)

**Ticket 32 is implemented and locally verified.** The Home "continue" card now
resumes the whole project, not just the chat: a "Recent work" section lists
the project notebook's most recently edited documents and canvases from the
existing bounded typed list reads (timestamps reused as persisted, one click
opens the correct owned routed resource), and the current stage's saved coach
feedback is shown bound to that stage. Everything reuses persisted
projections — `readerProject`, the artifact/canvas summaries and chat
summaries — with two bounded list queries and no model call on page load, no
fabricated percentages and no activity counts presented as learning.
Incomplete states are truthful ("No documents yet", "No canvases yet"), a
failed list read simply shows the card without inventing work, and opening a
vanished resource keeps the editor's explicit not-found message. Triage
remains `ready-for-agent`; nothing is staged, committed or deployed.

Starting revision/branch: `improvement/architecture-responsiveness` with the
dirty ticket 01–31 working tree preserved unchanged apart from this ticket's
files.

#### New files and behavior

| File | Responsibility |
| --- | --- |
| `frontend/src/HomeView.tsx` | "Recent work" region on the continue card: the project notebook (the latest chat's parent, or the latest entry itself) loads its bounded artifact and canvas lists once, shows the two most recently edited of each with persisted timestamps, and opens them through new optional `openArtifact`/`openCanvas` routing callbacks; truthful empty states; the current stage's saved review feedback (`review.improvements` bound to `current_stage`, ≤ 2 items) renders under the stage actions. No new percentages, counts or model calls. |
| `frontend/src/App.tsx` | Wires the existing `openWorkspaceRoute` artifact/canvas navigation into `HomeView`. |
| `frontend/src/HomeView.test.tsx` | New public-behavior tests: recent work lists and opens the owned resource, saved stage feedback displays, and the no-history state is truthful with no fabricated feedback. |

No backend change was needed: current/recent project, stage, last
conversation, artifacts, canvases and feedback are all carried by the existing
typed persisted projections, so no route, schema or generated contract
changed.

#### Executed validation

| Command/check | Result |
| --- | --- |
| `npx vitest run src/HomeView.test.tsx` (within `npm test`) | 3 passed (red first: all three failed against the missing `openArtifact`/`openCanvas` props and resume behavior; one intermediate red was a test fixture gap — the project stub omitted `review.project_brief`, which the existing client materializer requires — fixed in the test, not the component). |
| `npm test --prefix frontend` | **175 passed / 26 files** (was 172/25). |
| `npm run build --prefix frontend` | Exit 0 (`tsc --noEmit` + Vite production build). |
| `npm run test:browser --prefix frontend` | **7 passed** — unchanged chat journeys. |
| `.venv/bin/ruff check .` | Exit 0 (backend untouched). |
| `compileall` (backend, ui, streamlit_app, tests, scripts, agentcore_runtime) | Exit 0. |
| Full mock suite | **3,274 passed / 1 skipped** — unchanged, as expected with no backend behavior change. |
| Post-run leak check | No uvicorn/playwright processes; `git diff --check` clean. |

#### Compatibility, rollback and known limits

Pure frontend addition on existing typed endpoints; the generated REST
contracts, schema and persisted data are untouched, and `openArtifact`/
`openCanvas` are optional props so no other `HomeView` call site breaks.
Rollback is source-only: revert the `HomeView`/`App` changes and delete
`frontend/src/HomeView.test.tsx`.

Known limits, documented rather than silently accepted: the resume card shows
the two most recently edited documents and canvases rather than the full
lists (the notebook page remains the complete inventory); "existing feedback"
means the persisted whole-chat review feedback bound to the current stage —
artifact before/after pairs and canvas suggestions stay in their saved chat
context, where they are already rendered; and a failed artifacts/canvases
read shows the card without that section's rows instead of an error banner,
so a transient failure never fabricates or hides the chat itself.

**Next exact action:** ticket 33 (show deduplicated confirmed milestone
recaps, blocked by 12 ✓) is eligible in this same checkout, as are 35 and
37–40, preserving the dirty working tree.

### Ticket 31 complete — return artifact reasoning to the canvas (2026-11-25 SGT, OpenCode)

**Ticket 31 is implemented and locally verified.** Students reading a saved
document can now send its reasoning back to a design canvas: the editor's new
"Add to canvas" action opens a dialog that works from the *saved* document
revision (never unsaved editor edits), lets the student pick the whole
document or one paragraph, and offers an editable new-node proposal or an
explicit link to an existing node. Every confirmation is the ordinary
revision-guarded canvas save and carries an artifact reference stamped with
the saved revision it came from. Nothing ever changes the artifact. Later
document edits are never silently synchronized: the canvas outline shows the
linked saved version, flags when the document has newer saved changes, and
offers an explicit per-node "Update from artifact" that lands the refreshed
text in the editable outline for review before the student saves. Triage
remains `ready-for-agent`; nothing is staged, committed or deployed.

Starting revision/branch: `improvement/architecture-responsiveness` with the
dirty ticket 01–30 working tree preserved unchanged apart from this ticket's
files.

#### New files and behavior

| File | Responsibility |
| --- | --- |
| `backend/persistence/store/operations/references.py` | Artifact references may now carry an optional server-validated `revision` (positive integer) recording which saved artifact version the linked content came from; the field stays absent when unsupplied so legacy snapshots compare exactly, and non-artifact references reject a smuggled revision. |
| `frontend/src/ArtifactToCanvasDialog.tsx` | New dialog: destination canvas picker, saved-content choice (whole document or one paragraph, prefilled from the canonical saved document), editable node proposal ("Create new node") and "Link to this node" (adds the artifact/revision reference while preserving every other field); both confirm through a fresh `readCanvas` + revision-guarded `saveCanvas`; 409 asks to confirm again, 422 and unknown canvases fail with explicit messages and no partial writes; no canvases is stated truthfully. |
| `frontend/src/ArtifactEditor.tsx` | "Add to canvas" toolbar action hands the saved artifact plus the cursor's paragraph (or the whole document) to the dialog. |
| `frontend/src/CanvasEditor.tsx` | Artifact links render with their linked saved version; the outline flags "the document has newer saved changes" when the artifact's current revision passed the linked one (bounded artifact list loaded lazily once a node links a document); the explicit "Update from artifact" action replaces that node's description with the document's current saved text and re-stamps the reference revision through the ordinary local-edit + save flow — never automatic. |
| `frontend/src/artifactText.ts` | Shared bounded plaintext projection of a saved document (whole document or one top-level block), used by the dialog and the stale-link update. |
| `frontend/src/api.ts` | `EvidenceReference` gains optional `revision` (artifact references only). No REST schema changed: references travel inside the canonical `graph` object, so no regeneration was required. |
| `tests/persistence/test_reference_links.py` | New seam test: artifact references keep their revision origin, absence stays legacy-exact, and invalid revisions or revision-carrying non-artifact references fail closed. |
| `frontend/src/ArtifactToCanvasDialog.test.tsx`, `frontend/src/CanvasEditor.test.tsx`, `frontend/src/ArtifactEditor.test.tsx` | New public-behavior tests: provenance on created nodes, link-preserving node references, truthful empty-canvas state, stale-linkage exposure + explicit update semantics, and the editor entry point. |

#### Executed validation

| Command/check | Result |
| --- | --- |
| `pytest tests/persistence/test_reference_links.py::test_artifact_references_keep_their_revision_origin` | Red first (the revision was silently dropped by `canonical_references`; one follow-up red — a revision smuggled onto a message reference was not yet rejected — fixed in the implementation, not the test), then green. |
| `pytest tests/persistence/test_reference_links.py tests/persistence/test_student_canvases.py tests/persistence/test_student_artifacts.py` | 19 passed, exit 0. |
| `npx vitest run src/ArtifactToCanvasDialog.test.tsx` (within `npm test`) | 3 passed (red first: the component did not exist so the suite failed to import; two initial reds were test-harness stubs — an empty-canvas stub and awaiting the loaded node list — corrected in the test, not the component). |
| `npx vitest run src/CanvasEditor.test.tsx` | 10 passed (the new stale-linkage test red first: no staleness UI existed). |
| `npx vitest run src/ArtifactEditor.test.tsx` | 3 passed (the new entry-point test red first: no "Add to canvas" button existed). |
| `npm test --prefix frontend` | **172 passed / 25 files** (was 167/24). |
| `npm run build --prefix frontend` | Exit 0 (`tsc --noEmit` + Vite production build). |
| `npm run test:browser --prefix frontend` | **7 passed** — unchanged chat journeys. |
| `.venv/bin/ruff check .` | Exit 0. |
| `compileall` (backend, ui, streamlit_app, tests, scripts, agentcore_runtime) | Exit 0. |
| Full mock suite | **3,274 passed / 1 skipped** (3,273 after ticket 30 + this ticket's 1 new backend test). |
| Post-run leak check | No uvicorn/playwright processes; `git diff --check` clean. |

#### Compatibility, rollback and known limits

No schema or migration change: the reference revision lives inside the
canonical canvas graph JSON and is additive (absent on every existing node;
`canonical_references` stays byte-exact for legacy snapshots). The REST
contract is unchanged — references travel inside `ReaderCanvas.graph` — so no
OpenAPI regeneration was needed and `api:check` is unaffected. No stage
authority touched; the artifact is never written by this flow. Rollback is
source-only: revert the reference validator, delete
`frontend/src/ArtifactToCanvasDialog.tsx` + `frontend/src/artifactText.ts`,
revert the `ArtifactEditor`/`CanvasEditor` wiring and the `EvidenceReference`
type, restore the three touched frontend tests and remove the new reference
test.

Known limits, documented rather than silently accepted: "Update from artifact"
replaces the node's description with the document's whole saved text (the
reference does not record which paragraph the node came from, so a
paragraph-scoped refresh is future work); a link without a recorded revision
(such as the canvas editor's manual "Link evidence" path) never shows stale
state rather than guessing; the refreshed text lands in the outline for review
and only reaches the server through the student's explicit save, so the
button alone persists nothing; and staleness is detected against the
notebook's bounded artifact list loaded when a node links a document.

**Next exact action:** ticket 32 (resume a project from persisted work,
blocked by 9 ✓, 15 ✓, 20 ✓) is eligible, as are 33 (blocked by 12 ✓) and
35, 37–40. Proceed in this same checkout with the same fresh-writer rules,
preserving the dirty working tree.

### Ticket 30 complete — develop artifacts from selected canvas nodes (2026-11-25 SGT, OpenCode)

**Ticket 30 is implemented and locally verified.** The canvas editor's new
"Develop into artifact" action lets the student tick any nodes on the canvas
and either assemble them into a new artifact themselves or explicitly ask the
coach for a bounded synthesis. Both paths end in the student's explicit
confirmation, and confirmation always creates a NEW artifact through the
ordinary authorized create — an existing artifact is never overwritten.
Created artifacts carry the contributing node ids and their resolved evidence
as provenance references, and the coach path adds an AI provenance marker
plus the base canvas snapshot for stale/unavailable origin handling. Triage
remains `ready-for-agent`; nothing is staged, committed or deployed.

Starting revision/branch: `improvement/architecture-responsiveness` with the
dirty ticket 01–29 working tree preserved unchanged apart from this ticket's
files.

#### New files and behavior

| File | Responsibility |
| --- | --- |
| `backend/canvas_draft.py` | New `CanvasDraftProposal` (stable `cd-…` id, bounded title/draft text, server-stamped `base_canvas_id`/`base_canvas_revision`/`node_ids`/`provenance`) and `bounded_canvas_draft`: at most one reviewable draft per turn, malformed/hostile proposals dropped, model-supplied node lists ignored in favor of the server-resolved selection, live-model drafts get a content-stable synthesized id. |
| `backend/domain.py` | `CanvasContextOrigin.node_ids` (server-resolved selection), `CoachRequest.canvas_selection_purpose` (`discuss` default / `draft`, server-filled only) and `canvas_draft` on `ProviderAssessmentResult` and `CoachTurn`. |
| `backend/http/notebook_reader.py` | `ReaderCanvasSelection.purpose` (`discuss`/`draft`); the resolved origin carries the selection node ids; `ReaderMessage` projects the validated saved draft (invalid entries dropped). |
| `backend/http/app.py` | Legacy `/coach/turn` routes also strip the client-supplied canvas purpose — node ids and purpose are always server-resolved. |
| `backend/mock_provider.py` | An explicit draft request over resolved nodes returns exactly one deterministic reviewable draft (content-stable id); discussion requests and context-free turns synthesize nothing (and a draft request suppresses the ticket 28 node proposal to avoid noise). |
| `backend/workflow.py` | Validates and origin-stamps the draft in both the sequential and LangGraph paths. |
| `backend/coaching/execution.py` | Persists the draft on the assistant message metadata inside the same transaction. |
| `frontend/src/CanvasDevelopDialog.tsx` | New dialog: node checkboxes (the selected node pre-checked), artifact type, "Assemble myself" (creates a new artifact from the saved node text with `canvas_node` provenance references) and "Draft with the coach" (opens the chat with a `draft`-purpose selection). |
| `frontend/src/CanvasDraftCard.tsx` | New draft card under the saved answer: edit title/text, confirm creates a NEW artifact via the ordinary create with contributing node ids plus their evidence links; a stale canvas snapshot warns and requires a deliberate second confirmation; an unavailable canvas (404) or unresolvable evidence (422) creates nothing with an explicit message; rejecting persists nothing; handled draft ids tracked per thread. |
| `frontend/src/CanvasEditor.tsx`, `frontend/src/App.tsx`, `frontend/src/chatLifecycle.ts`, `frontend/src/Conversation.tsx`, `frontend/src/styles.css` | "Develop into artifact" toolbar action, purpose threaded through `CanvasSelection` and the stream body (`purpose: "draft"` only when explicitly requested), draft cards under saved answers, and styles. |
| `frontend/src/api.ts`, `frontend/src/api/client.ts`, `frontend/openapi/reader.json`, `frontend/src/api/generated/*` | Regenerated REST types add `CanvasDraft` on reader messages and `purpose` on canvas selections; page materializers default the field to `null`. |
| `tests/domain/test_canvas_draft.py`, `tests/http/test_canvas_draft_flow.py` | New seam tests: validator bounds/hostility/origin stamping, synthesis vs discussion turns, stream-to-projection round trip with node provenance, and legacy-route stripping. |
| `tests/scripts/test_export_reader_openapi.py` | Contract allowlist gains the public `CanvasDraftProposal` schema. |

#### Executed validation

| Command/check | Result |
| --- | --- |
| `pytest tests/domain/test_canvas_draft.py` | 4 passed (red first: the module, turn field and purpose wiring did not exist; one early red observation — the test's origin omitted the selection node ids, which the server correctly requires, fixed in the test). |
| `pytest tests/http/test_canvas_draft_flow.py` | 3 passed (red first: the stream request rejected the unknown `purpose` field 422 before the reader wiring existed). |
| `pytest tests/domain tests/http/test_canvas_draft_flow.py tests/http/test_canvas_suggestion_flow.py tests/http/test_artifact_feedback_flow.py tests/http/test_canvas_coaching.py` | 1,868 passed / 1 skipped. |
| `npm test --prefix frontend` | **167 passed / 24 files** (was 161/22; the six new dialog/card tests red first against the missing components — including one stub fix where the generated client passes a `Request`, matching the existing test pattern). |
| `npm run build --prefix frontend` | Exit 0 (`tsc --noEmit` + Vite production build). |
| `npm run api:generate --prefix frontend` + `npm run api:check --prefix frontend` | Regeneration deterministic; check exit 0. |
| `npm run test:browser --prefix frontend` | **7 passed** — unchanged chat journeys. |
| `.venv/bin/ruff check .` | Exit 0. |
| `compileall` (backend, ui, streamlit_app, tests, scripts, agentcore_runtime) | Exit 0. |
| Full mock suite | **3,273 passed / 1 skipped** (3,266 after ticket 29 + this ticket's 7 new backend tests). |
| Post-run leak check | No uvicorn/playwright processes; `git diff --check` clean. |

#### Compatibility, rollback and next exact action

No schema or migration change: the draft lives in assistant message metadata
and the regenerated reader contract is additive (`canvas_draft` absent on
every existing message; `purpose` defaults to `discuss` so every existing
selection behaves exactly as before). Without a server-resolved canvas origin
and selection node ids no model draft survives on any path, and the legacy
routes strip the client purpose. Stage authority is untouched — a confirmed
draft creates an artifact and changes no stage. Rollback is source-only:
revert the backend modules, reader projection, the frontend
dialog/card/wiring/generated types and styles, restore the OpenAPI allowlist
test, and delete `tests/domain/test_canvas_draft.py` +
`tests/http/test_canvas_draft_flow.py` + `frontend/src/CanvasDraftCard.test.tsx`
+ `frontend/src/CanvasDevelopDialog.test.tsx`.

Known limits, documented rather than silently accepted: assembled and
confirmed drafts are plain-paragraph documents (node structure becomes
labeled text lines, and headings/lists from rich canvas descriptions are
flattened); provenance is machine-readable at the artifact level
(`canvas_node` references + evidence links) with the AI/coach marker on the
draft proposal itself — per-node AI provenance rendering in the editor
arrives with the tickets 31/45 provenance work; the stale-canvas path warns
and requires a second explicit confirmation rather than silently refreshing
the draft (the draft text is never auto-updated); and the mock synthesizes at
most one deterministic draft per turn.

**Next exact action:** ticket 31 (return artifact reasoning to the canvas,
blocked by 21 ✓, 25 ✓, 17 ✓) is eligible, as are 32 (blocked by 9 ✓, 15 ✓,
20 ✓), 35 and 37–40. Start exactly one fresh writer session for
`.scratch/architecture-completion/issues/31-return-artifact-reasoning-to-the-canvas.md`
in this same checkout, preserving the dirty working tree.

### Ticket 29 complete — review and accept artifact feedback (2026-11-25 SGT, OpenCode)

**Ticket 29 is implemented and locally verified.** Students can now ask the
coach about a whole saved artifact or the exact paragraph their cursor is in,
and the coach may return one bounded before/after text proposal rendered from
the server-resolved saved passage. The pair previews side by side under the
saved answer; acceptance is the student's explicit review-and-apply — the
ordinary revision-guarded artifact update, re-read fresh with the ticket 17
409 machinery — which creates a new version while every earlier version stays
restorable. Rejection persists nothing, handled proposal ids cannot be
offered twice, and stale revisions, foreign artifacts and out-of-range
paragraphs fail closed before the coach runs. Triage remains
`ready-for-agent`; nothing is staged, committed or deployed.

Starting revision/branch: `improvement/architecture-responsiveness` with the
dirty ticket 01–28 working tree preserved unchanged apart from this ticket's
files.

#### New files and behavior

| File | Responsibility |
| --- | --- |
| `backend/artifact_feedback.py` | New `ArtifactFeedback` model (stable `af-…` id, `revise_text`, bounded proposed/rationale text, server-stamped `base_artifact_id`/`base_artifact_revision`/`paragraph`/`original_text`) and `bounded_artifact_feedback`: at most one pair per turn, malformed/hostile entries dropped, live-model proposals get a content-stable synthesized id, and the origin always comes from the server. |
| `backend/domain.py` | `ArtifactFeedbackOrigin` (server-filled only: artifact id, revision, paragraph, resolved original text), `CoachRequest.artifact_context` + `artifact_feedback_origin`, and `artifact_feedback` on `ProviderAssessmentResult` and `CoachTurn` (≤ 1, default empty). |
| `backend/http/notebook_reader.py` | `ReaderArtifactSelection` (artifact id, seen revision, optional paragraph — never text) on the stream request; `_artifact_block_text` + `_resolve_artifact_feedback`: family-scoped visibility, revision guard (409 stale), paragraph bounds (422), and the bounded saved text + origin server-side; `ReaderMessage` projects validated saved pairs (invalid entries dropped). |
| `backend/http/app.py` | Legacy `/coach/turn` routes also strip client-supplied artifact context and origin (the shared server-resolved marker from ticket 28 gates both). |
| `backend/mock_provider.py` | Coaching with resolved artifact text proposes exactly one deterministic before/after refinement (content-stable id); Q&A, review and context-free turns propose nothing. |
| `backend/workflow.py` | Validates and origin-stamps provider feedback in both the sequential and LangGraph paths (`artifact_feedback` threads through the graph's per-node state like canvas suggestions). |
| `backend/coaching/execution.py` | Persists non-empty feedback on the assistant message metadata inside the same transaction. |
| `backend/agentcore_provider.py`, `agentcore_runtime/models.py`, `agentcore_runtime/structured_coach.py` | Additive fast-chat contract: optional single `artifact_feedback` object (`proposed_text` + `rationale`); dropped entirely without a resolved artifact origin; contract prompt text and schema description updated. |
| `frontend/src/api.ts`, `frontend/src/api/client.ts`, `frontend/openapi/reader.json`, `frontend/src/api/generated/*` | Regenerated REST types add `ArtifactFeedback` on reader messages; page materializers default the field to `[]`. |
| `frontend/src/ArtifactFeedback.tsx` | New before/after card: side-by-side preview with rationale, edit-before-apply dialog, paragraph acceptance replaces exactly that top-level block's text (node type kept), whole-document acceptance builds explicit reviewed paragraphs, and both run `readArtifact` + revision-guarded `saveArtifact` (409 reported without losing the editable proposal). Reject persists nothing; handled ids tracked in per-thread tab storage. |
| `frontend/src/ArtifactEditor.tsx` | "Ask the coach" (whole document) and "Ask about this paragraph" (cursor's top-level block) hand the artifact id/revision/paragraph to the chat. |
| `frontend/src/chatLifecycle.ts`, `frontend/src/Conversation.tsx`, `frontend/src/App.tsx`, `frontend/src/styles.css` | `ArtifactSelection` rides exactly one send (`artifact_selection`), a labeled composer chip with explicit clear, feedback cards under saved answers, and compare styles. |
| `tests/domain/test_artifact_feedback.py`, `tests/http/test_artifact_feedback_flow.py` | New seam tests: validator bounds/hostility/origin stamping, mock turn proposal, stream-to-projection round trip, whole-document resolution, stale/foreign/paragraph guards, legacy-route stripping, live-path origin guard. |
| `tests/scripts/test_export_reader_openapi.py` | Contract allowlist gains the public `ArtifactFeedback` schema. |

#### Executed validation

| Command/check | Result |
| --- | --- |
| `pytest tests/domain/test_artifact_feedback.py` | 5 passed (red first: the module, turn fields, live-path mapper and synthesized-id behavior did not exist; two early red observations — a hostile forged id was initially "repaired" by synthesis and a live proposal lacked `kind`, both fixed by distinguishing absent ids from hostile ones before green). |
| `pytest tests/http/test_artifact_feedback_flow.py` | 4 passed (red first: the stream request rejected the unknown selection 422, then guards resolved once implemented). |
| `pytest tests/domain` (full slice) | 1,853 passed / 1 skipped. |
| `npm test --prefix frontend` | **161 passed / 22 files** (was 157/21; four new card tests red first against the missing component). |
| `npm run build --prefix frontend` | Exit 0 (`tsc --noEmit` + Vite production build). |
| `npm run api:generate --prefix frontend` + `npm run api:check --prefix frontend` | Regeneration deterministic; check exit 0. |
| `npm run test:browser --prefix frontend` | **7 passed** — unchanged chat journeys. |
| `.venv/bin/ruff check .` | Exit 0. |
| `compileall` (backend, ui, streamlit_app, tests, scripts, agentcore_runtime) | Exit 0. |
| Full mock suite | **3,266 passed / 1 skipped** (3,257 after ticket 28 + this ticket's 9 new backend tests). |
| Post-run leak check | No uvicorn/playwright processes; `git diff --check` clean. |

#### Compatibility, rollback and next exact action

No schema or migration change: feedback lives in assistant message metadata
and the regenerated reader contract is additive (`artifact_feedback` absent on
every existing message; old clients ignore it). Existing prompts gain nothing
without a reader-resolved artifact selection, and without a resolved artifact
origin no model proposal survives on any path. Stage authority, retrieval,
citation checks and generation admission are untouched — feedback is one
specialist's bounded output, never an automatic stage completion or a second
artifact agent. Rollback is source-only: revert the backend modules, reader
projection, agentcore runtime/provider files, the frontend component/wiring/
generated types and the styles, restore the OpenAPI allowlist test, and
delete `tests/domain/test_artifact_feedback.py` +
`tests/http/test_artifact_feedback_flow.py` +
`frontend/src/ArtifactFeedback.test.tsx`.

Known limits, documented rather than silently accepted: paragraph acceptance
replaces the block's text as a single plain text run, so inline formatting
(bold, links) inside the revised passage is lost; list/table-style top-level
blocks are not auto-editable and the card says so instead of guessing;
whole-document acceptance rebuilds the document as reviewed paragraphs and
therefore loses headings and list structure (the previous version stays
restorable); provenance of the accepted edit is the artifact's existing
version history rather than a per-node AI marker (the deep provenance work
belongs to tickets 31/45); and the mock proposes at most one deterministic
refinement per turn.

**Next exact action:** ticket 30 (develop artifacts from selected canvas
nodes, blocked by 27 ✓, 16 ✓, 17 ✓) is eligible, as are 31 (blocked by 21 ✓,
25 ✓, 17 ✓), 32, 35 and 37–40. Start exactly one fresh writer session for
`.scratch/architecture-completion/issues/30-develop-artifacts-from-selected-canvas-nodes.md`
in this same checkout, preserving the dirty working tree.

### Ticket 28 complete — review and accept structured canvas suggestions (2026-11-25 SGT, OpenCode)

**Ticket 28 is implemented and locally verified.** Coaching about a selected
canvas node can now return bounded, validated canvas proposals. The coach
turn carries at most five inert suggestions with stable identity, proposed
node/relationship content, rationale and the server-resolved base canvas
snapshot; the student sees preview cards under the saved answer and only an
explicit review-and-confirm — the ordinary revision-guarded canvas save,
re-read fresh with the ticket 22 409 machinery — writes anything. Reject and
ignore persist nothing, handled suggestion ids cannot be offered twice, and
hostile model text is dropped by the shared validator rather than failing the
turn. Triage remains `ready-for-agent`; nothing is staged, committed or
deployed.

Starting revision/branch: `improvement/architecture-responsiveness` with the
dirty ticket 01–27 working tree preserved unchanged apart from this ticket's
files.

#### New files and behavior

| File | Responsibility |
| --- | --- |
| `backend/canvas_suggestions.py` | New `CanvasSuggestion` model (stable `sg-…` id, `new_node`/`new_edge`, allowlisted node kinds/relations, bounded text, server-stamped `base_canvas_id`/`base_canvas_revision`) and `bounded_canvas_suggestions`: drops malformed/hostile entries, caps at 5, dedupes by id, stamps the authoritative revision over any model-claimed one. |
| `backend/domain.py` | `CanvasContextOrigin` + `CoachRequest.canvas_context_origin` (server-filled only, reader dispatch), a `_canvas_server_resolved` private marker, and `canvas_suggestions` on `ProviderAssessmentResult` and `CoachTurn` (≤ 5, default empty). |
| `backend/mock_provider.py` | Deterministic coaching about a canvas selection proposes exactly one new-node idea derived from the resolved selection text, with a content-stable id; Q&A, review and context-free turns propose nothing. |
| `backend/workflow.py` | Validates and revision-stamps provider suggestions in both the sequential and LangGraph paths (the graph's per-node state replacement required threading `canvas_suggestions` through `recommend`). |
| `backend/coaching/execution.py` | Persists non-empty suggestion lists on the assistant message metadata inside the same transaction. |
| `backend/http/notebook_reader.py` | `_resolve_canvas_selection` also returns the snapshot origin; `ReaderMessage` projects validated saved suggestions (invalid entries dropped); the reader dispatch marks the request server-resolved. |
| `backend/http/app.py` | Legacy `/coach/turn` routes now strip client-supplied canvas context **only when it was not server-resolved by the reader dispatch** — fixing a latent ticket 27 gap where the unconditional strip deleted the reader's resolved context before the coach saw it (exposed by this ticket's red stream test). |
| `backend/agentcore_provider.py`, `agentcore_runtime/models.py`, `agentcore_runtime/structured_coach.py` | Additive fast-chat contract: optional `canvas_suggestions` array with the same validation, dropped entirely without a resolved canvas origin; contract prompt text and schema description updated. |
| `frontend/src/api.ts`, `frontend/src/api/client.ts`, `frontend/openapi/reader.json`, `frontend/src/api/generated/*` | Regenerated REST types add `CanvasSuggestion` on reader messages; page materializers default the field to `[]`. |
| `frontend/src/CanvasSuggestions.tsx` | New suggestion cards: preview with rationale, edit-before-accept dialog, accept runs `readCanvas` + revision-guarded `saveCanvas` (409/422 reported without losing the editable proposal), reject/dismiss save nothing, handled ids tracked in per-thread tab storage. |
| `frontend/src/Conversation.tsx`, `frontend/src/styles.css` | Cards render under saved assistant answers and are disabled while a turn is in flight. |
| `tests/domain/test_canvas_suggestions.py`, `tests/http/test_canvas_suggestion_flow.py` | New seam tests: validator bounds/hostility, mock turn suggestion and stamping, stream-to-projection round trip, legacy-route stripping, live-path origin guard. |
| `tests/scripts/test_export_reader_openapi.py` | Contract allowlist gains the public `CanvasSuggestion` schema. |

#### Executed validation

| Command/check | Result |
| --- | --- |
| `pytest tests/domain/test_canvas_suggestions.py` | 6 passed (red first: the module, turn fields and origin guard did not exist; two early test-data fixes while observing red, then minimal green — including the discovery that this LangGraph version replaces node state wholesale, so `recommend` must re-emit suggestions). |
| `pytest tests/http/test_canvas_suggestion_flow.py` | 2 passed (red first: the stream emitted `canvas_suggestions: []`, exposing the ticket 27 strip gap fixed above). |
| `pytest tests/domain tests/http/test_canvas_suggestion_flow.py` (full domain slice) | 1,847 passed / 1 skipped. |
| `npm test --prefix frontend` | **157 passed / 21 files** (was 153/20; the four new card tests red first against the missing component). |
| `npm run build --prefix frontend` | Exit 0 (`tsc --noEmit` + Vite production build). |
| `npm run api:generate --prefix frontend` + `npm run api:check --prefix frontend` | Regeneration deterministic; check exit 0. |
| `npm run test:browser --prefix frontend` | **7 passed** — unchanged chat journeys. |
| `.venv/bin/ruff check .` | Exit 0. |
| `compileall` (backend, ui, streamlit_app, tests, scripts, agentcore_runtime) | Exit 0. |
| Full mock suite | **3,257 passed / 1 skipped** (3,249 baseline + this ticket's 8 new backend tests). |
| Post-run leak check | No uvicorn/playwright processes; `git diff --check` clean. |

#### Compatibility, rollback and next exact action

No schema or migration change: suggestions live in assistant message metadata
and the regenerated reader contract is additive (`canvas_suggestions` absent
on every existing message; old clients ignore it). Existing prompts are
byte-identical without canvas context, and without a resolved canvas origin
no model proposal survives on any path. The legacy-route strip is now
conditional, which restores ticket 27's intended server-resolved context
while still failing closed for client-injected context. Rollback is
source-only: revert the backend modules, reader projection, agentcore
runtime/provider files, the frontend component/wiring/generated types and the
styles, restore the OpenAPI allowlist test, and delete
`tests/domain/test_canvas_suggestions.py` +
`tests/http/test_canvas_suggestion_flow.py` +
`frontend/src/CanvasSuggestions.test.tsx`.

Known limits, documented rather than silently accepted: acceptance currently
supports one proposal at a time through the review dialog and does not yet
write per-node AI-provenance metadata (the canvas node reference allowlist has
no suggestion kind; provenance labeling arrives with the ticket 31/45
provenance work); `new_edge` targets are validated against the real graph
only at the ordinary save (422 with nothing saved); suggestion cards live in
tab storage, so a different browser session may re-offer a handled id without
any duplicate write risk (the save is still revision-guarded and appends a
fresh node); and the mock proposes at most one deterministic node per turn.

**Next exact action:** ticket 29 (review and accept artifact feedback, blocked
by 6/16/17/25 — all ✓) is eligible, as are 30 (blocked by 27 ✓, 16 ✓, 17 ✓),
31 (blocked by 21 ✓, 25 ✓, 17 ✓), 32 and 35 and 37–40. Start exactly one
fresh writer session for
`.scratch/architecture-completion/issues/29-review-and-accept-artifact-feedback.md`
in this same checkout, preserving the dirty working tree.

### Ticket 27 complete — coach selected canvas reasoning (2026-11-25 SGT, OpenCode)

**Ticket 27 is implemented and locally verified.** The canvas editor's "Ask
the coach" action attaches the selected saved node to the next coaching send.
The request carries only the canvas id, seen revision and node ids; FastAPI
resolves the authorized text server-side from the stored canonical graph into
a bounded labeled prompt section — retrieval, citations, safety, admission and
stage authority are untouched, and nothing changes the graph automatically.
Triage remains `ready-for-agent`; nothing is staged, committed or deployed.

Starting revision/branch: `improvement/architecture-responsiveness` with the
dirty ticket 01–26 working tree preserved unchanged apart from this ticket's
files.

#### New files and behavior

| File | Responsibility |
| --- | --- |
| `backend/domain.py` | `CoachRequest.canvas_context` (server-filled only, ≤ 4,000 chars) beside the existing server-filled project context. |
| `backend/prompts/composer.py` | New untrusted `<canvas_context>` section between project context and retrieved evidence: added to the delimiter-neutralization tag inventory, clipped to `MAX_CANVAS_CONTEXT_CHARS` (3,500), and rendered only when non-empty so every existing prompt is byte-identical without it. |
| `backend/canvas_export.py` | Pure `render_canvas_selection_text`: kind/stage-labeled node lines plus depth-1 relationship lines, all from the stored canonical graph. |
| `backend/http/notebook_reader.py` | `LectureRequest.canvas_selection` (`ReaderCanvasSelection`: canvas id, seen revision, ≤ 5 node ids — never content) and `_resolve_canvas_selection`: family-scoped canvas visibility, revision guard (409 stale), node existence (422 unknown), and the resolved text onto the server-side context. |
| `backend/http/app.py` | The legacy `/coach/turn` routes strip any client-supplied `canvas_context`, keeping the field server-resolved only. |
| `frontend/src/chatLifecycle.ts` | `CanvasSelection` type and a `canvasSelection` lifecycle param: the next non-edit send carries `canvas_selection` exactly once and clears it. |
| `frontend/src/Conversation.tsx` | A labeled composer chip ("Discussing canvas node: …") with an explicit clear, wired through the lifecycle ref. |
| `frontend/src/CanvasEditor.tsx` + `frontend/src/App.tsx` | "Ask the coach" on the selected node hands the canvas id/revision/node id to App, which opens the family's notebook chat with the pending selection. |
| `tests/domain/test_prompt_architecture.py` | New composer test: the section orders between project and retrieval, hostile node text cannot close the section or open another, and the dedicated clip bounds it. |
| `tests/http/test_canvas_coaching.py` | New seam tests: a valid selection streams through the lifecycle; stale revision 409, unknown node 422, foreign-owner 404 and other-family 404 all fail closed. |

#### Executed validation

| Command/check | Result |
| --- | --- |
| `pytest tests/domain/test_prompt_architecture.py` | 30 passed (red first: the new section assertions were written against the composer before the section existed). |
| `pytest tests/http/test_canvas_coaching.py` | 2 passed (red first: the canvas_selection field was unknown to the stream request). |
| `pytest tests/domain/ tests/http/test_canvas_coaching.py tests/http/test_student_journey_readiness.py tests/persistence/test_reference_links.py` | **1,855 passed / 1 skipped.** |
| `npm test --prefix frontend` | **153 passed / 20 files** (no component behavior changed; typecheck-gated). |
| `npm run build --prefix frontend` | Exit 0 (`tsc --noEmit` + Vite production build). |
| `npm run test:browser --prefix frontend` | **7 passed** — the existing chat journeys confirm the stream body change is backward compatible. |
| `.venv/bin/ruff check .` | Exit 0. |
| `compileall` (backend, ui, streamlit_app, tests, scripts, agentcore_runtime) | Exit 0. |
| Full mock suite | **Exit 0 with 3,249 passed / 1 skipped** — the 3,246 baseline plus this ticket's three new backend tests. |
| Post-run leak check | No disposable-stack/uvicorn/playwright processes; `git diff --check` clean. |

#### Compatibility, rollback and next exact action

No schema, migration or saved-data change: the section renders only when the
reader dispatch resolves a selection, so every existing prompt (mock tests,
Deep Review, briefs) is byte-identical otherwise — pinned by the untouched
prompt-architecture suite including the client-injection invariant. The
stream-request field is optional with `extra="forbid"` validation and the
legacy coach routes strip client-supplied context. Rollback is source-only:
revert `domain.py`, `composer.py`, `canvas_export.py`, `notebook_reader.py`,
`app.py`, `chatLifecycle.ts`, `Conversation.tsx`, `CanvasEditor.tsx`,
`App.tsx`, the styles and the affected docs, and restore the two edited test
files; delete `tests/http/test_canvas_coaching.py`.

Known limits, documented rather than silently accepted: the UI selects one
node at a time (the contract already carries up to five; multi-select discuss
arrives with the selection work in ticket 28/30 flows); neighbor expansion is
fixed at depth 1 with all incident edges; the canvas section is descriptive
context only — it never awards completion, changes stages, or mutates the
graph; and unsaved student text is not part of the selection (the student's
composer message remains the explicit question).

**Next exact action:** tickets 20–27 all have acceptance evidence. The
frontier now includes ticket 28 (review and accept structured canvas
suggestions, blocked by 27 ✓ and 22 ✓), 29 (review and accept artifact
feedback, blocked by 6/16/17/25 — all ✓), 30 (develop artifacts from selected
canvas nodes, blocked by 27 ✓, 16 ✓, 17 ✓), 31 (return artifact reasoning to
the canvas, blocked by 21 ✓, 25 ✓, 17 ✓), 32 (resume a project from persisted
work, all ✓) and 35 and 37–40. Start exactly one fresh writer session for
`.scratch/architecture-completion/issues/28-review-and-accept-structured-canvas-suggestions.md`
in this same checkout, preserving the dirty working tree.

### Ticket 26 complete — turn selected chat content into canvas nodes (2026-11-25 SGT, OpenCode)

**Ticket 26 is implemented and locally verified.** Every message carries an
"Add to canvas" action that opens an editable proposal — node type, title,
content and destination canvas, prefilled from the exact message — and only
confirmation saves: the proposal re-reads the destination canvas and writes
over the fresh revision with the originating message id attached as the node's
evidence reference. Cancel saves nothing; a stale destination (409) keeps the
proposal open for a re-confirm; no reply is ever converted automatically.
Triage remains `ready-for-agent`; nothing is staged, committed or deployed.

Starting revision/branch: `improvement/architecture-responsiveness` with the
dirty ticket 01–25 working tree preserved unchanged apart from this ticket's
files.

#### New files and behavior

| File | Responsibility |
| --- | --- |
| `backend/persistence/store/operations/references.py` | The reference-resolution boundary is now the notebook family (the notebook, its parent and its child chats — matching how sources are shared across a notebook's chats), computed from the persisted `reader_parent_notebook_id` settings; sources and messages resolve anywhere in the family while artifacts and canvases stay anchored to the given notebook. Other families stay closed. |
| `frontend/src/ChatToCanvas.tsx` | New proposal dialog: destination canvas from the family's canvas list, editable node type/title/content prefilled from the exact message, confirmation as the only writer (fresh `readCanvas` + revision-guarded `saveCanvas`, node references `[{kind: 'message', id}]`), honest 409/422 recovery, and a no-canvas state that saves nothing. |
| `frontend/src/Conversation.tsx` | A per-message "Add to canvas" action beside copy/star, opening the proposal scoped to the chat's notebook family; on confirmation the transcript shows "Node added to your canvas." |
| `tests/persistence/test_reference_links.py` | New family-scoping test: a child-chat message resolves for the parent notebook's canvas while another family's message stays unavailable. |
| `frontend/src/ChatToCanvas.test.tsx` | New component suite: the edited proposal saves exactly once over the fresh revision carrying the message reference; a stale canvas (409) reports without creating anything and cancel saves nothing. |

#### Executed validation

| Command/check | Result |
| --- | --- |
| `pytest tests/persistence/test_reference_links.py` | 5 passed (red first: the family-scoping test observed the child-chat message unavailable before the boundary change). |
| `pytest tests/persistence/` | **180 passed** — every persistence suite stays green alongside the family boundary. |
| `npm test --prefix frontend` | **153 passed / 20 files** (151 before this ticket). |
| `npm run build --prefix frontend` | Exit 0 (`tsc --noEmit` + Vite production build). |
| `npm run test:browser --prefix frontend` | **7 passed**. |
| `.venv/bin/ruff check .` | Exit 0 (one unused-variable fix in the new test). |
| `compileall` (backend, ui, streamlit_app, tests, scripts, agentcore_runtime) | Exit 0. |
| Full mock suite | **Exit 0 with 3,246 passed / 1 skipped** — the 3,245 baseline plus this ticket's new family-scoping test. |
| Post-run leak check | No disposable-stack/uvicorn/playwright processes; `git diff --check` clean. |

#### Compatibility, rollback and next exact action

No schema or API contract change: the family boundary only widens which
same-owner rows a message/source reference may resolve against (the previous
same-notebook behavior remains a subset for single-notebook projects), and the
chat-to-canvas flow is pure frontend over the existing revision-guarded canvas
contract — no route, payload or generation behavior changed, and nothing
converts automatically. Rollback is source-only: revert
`references.py` (and its test), delete `ChatToCanvas.tsx` with its test, and
restore `Conversation.tsx`, `frontend/README.md`,
`docs/LOCAL_DEMO_IMPLEMENTATION.md` and `docs/TESTING.md`.

Known limits, documented rather than silently accepted: the proposal selects a
whole message rather than an arbitrary text span; the destination list shows
canvases anchored to the family's notebook (a chat without a parent uses its
own id); and the created node's evidence reference carries no excerpt — the
bounded selected-node coaching context remains ticket 27's work.

**Next exact action:** tickets 20–26 all have acceptance evidence. The
frontier now includes ticket 27 (coach selected canvas reasoning, blocked by
6 ✓, 21 ✓ and 25 ✓), 28 (structured canvas suggestions, blocked by 27 and 22),
29 (artifact feedback, blocked by 6/16/17/25 — all ✓), 32 (resume a project
from persisted work, all ✓) and 35 and 37–40. Start exactly one fresh writer
session for
`.scratch/architecture-completion/issues/27-coach-selected-canvas-reasoning.md`
in this same checkout, preserving the dirty working tree.

### Ticket 25 complete — link artifacts and canvas reasoning to evidence (2026-11-25 SGT, OpenCode)

**Ticket 25 is implemented and locally verified.** Artifacts and canvas nodes
can reference authorized evidence inside the same notebook — sources (course
material and uploads), active conversation messages, sibling artifacts and
canvas nodes — through visible authoring controls. The server structurally
validates bounded reference lists, resolves every reference under the
owner/project boundary, and fails closed (422) on fabricated, foreign or
cross-project references. Reads project resolved entries with an explicit
unavailable state; removed evidence is never substituted. Triage remains
`ready-for-agent`; nothing is staged, committed or deployed.

Starting revision/branch: `improvement/architecture-responsiveness` with the
dirty ticket 01–24 working tree preserved unchanged apart from this ticket's
files.

#### New files and behavior

| File | Responsibility |
| --- | --- |
| `backend/persistence/store/operations/references.py` | New shared module: pure `canonical_references` (four allowlisted kinds, bounded ids, ≤ 20 entries, duplicates collapse, canvas-node references require a canvas id) and owner-scoped `resolve_references`/`require_resolved` — sources and artifacts must belong to this notebook and owner, messages must be active (non-superseded) rows in this notebook, canvas nodes must exist inside an owned same-notebook canvas; unresolvable evidence stays explicitly `available: false, title: null`, never substituted. |
| `backend/persistence/store/sqlite_schema.py` + `backend/persistence/dsql_schema.py` + `backend/persistence/store/migrations.py` | Additive `references_text` columns (`DEFAULT '[]'`) on `student_artifacts` and `student_artifact_versions` with `migrate_artifact_reference_columns` upgrading legacy stores in place. |
| `backend/persistence/store/operations/artifacts.py` | Create/duplicate/update accept reference lists; omitted references keep the saved list while an explicit list (including empty) replaces it after every entry resolves; the read projection resolves references with availability and titles; version checkpoints carry the references so history and restores return them with the content. |
| `backend/persistence/store/operations/canvases.py` | Node `references` join the canonical graph (absent when unset, so legacy snapshots compare exactly); create/update fail closed unless every node reference resolves inside the notebook. |
| `backend/http/reader_artifacts.py` + `backend/http/reader_canvases.py` | Artifact payloads gain the optional `references` field and the artifact response projects resolved entries; `ReferenceError` maps to 422 in both readers. |
| `frontend/openapi/reader.json` + `frontend/src/api/generated/*` | Re-exported offline and regenerated; `npm run api:check` reports no drift. |
| `frontend/src/api.ts` + `frontend/src/api/client.ts` | `EvidenceReference` type; artifact create/save accept references; the artifact adapter passes resolved references through. |
| `frontend/src/ArtifactEditor.tsx` | An **Evidence** panel: the resolved list with an explicit "Unavailable or outdated evidence" state, a bounded source picker from the notebook's sources, and attach/detach through explicit revision-guarded saves (409 keeps everything and asks for a reload). Also fixes a pre-existing display gap: the explicit status line (restore/export/evidence outcomes) now renders instead of being shadowed by the autosave notice. |
| `frontend/src/CanvasEditor.tsx` | Node details gain an evidence picker (source list loaded once; kind select for source/artifact) with per-reference detach; a source reference displays "Unavailable or outdated" while its id is missing from the notebook's source list; changes flow through the debounced autosave, so the server re-validates every save. |
| `tests/persistence/test_reference_links.py` | Structural validation/bounds/duplicates, owner-and-notebook resolution across all four kinds, deleted/superseded/foreign/cross-project references resolving unavailable, canvas node references saving and failing closed, artifact references persisting with explicit-clear semantics. |
| `tests/http/test_reader_artifacts.py` | Public contract: references round-trip with resolution, omitted keeps / explicit replaces / empty clears, fabricated references fail 422. |
| `frontend/src/ArtifactEditor.test.tsx` | New component suite: linking a source issues exactly one guarded PUT carrying the reference and confirms "Evidence updated."; removed sources render as unavailable. |

#### Executed validation

| Command/check | Result |
| --- | --- |
| `pytest tests/persistence/test_reference_links.py` | 4 passed (red first: `ModuleNotFoundError: …operations.references`). |
| `pytest tests/http/test_reader_artifacts.py` | 5 passed (red first: missing `references` field in the create payload model). |
| `pytest tests/persistence/ tests/http/test_reader_artifacts.py tests/http/test_reader_canvases.py tests/test_architecture_contracts.py tests/http/test_security_readiness.py tests/scripts/test_export_reader_openapi.py tests/domain/test_canvas_export.py` | **265 passed.** |
| `npm test --prefix frontend` | **151 passed / 19 files** (149 before this ticket). |
| `npm run build --prefix frontend` | Exit 0 (`tsc --noEmit` + Vite production build). |
| `npm run api:check --prefix frontend` | Exit 0 — no schema or generated-client drift. |
| `npm run test:browser --prefix frontend` | **7 passed**. |
| `.venv/bin/ruff check .` | Exit 0. |
| `compileall` (backend, ui, streamlit_app, tests, scripts, agentcore_runtime) | Exit 0. |
| Full mock suite | **Exit 0 with 3,245 passed / 1 skipped** — the 3,240 baseline plus this ticket's five new backend tests. |
| Post-run leak check | No disposable-stack/uvicorn/playwright processes; `git diff --check` clean. |

#### Compatibility, migration and rollback

The migration is additive (`references_text DEFAULT '[]'`); legacy artifacts
and versions upgrade in place with empty reference lists and every existing
row untouched. The artifact payload/response change is additive; omitted
references keep saved behavior, so autosave and every existing caller are
unaffected. Canvas node references are absent-when-unset in the canonical
graph, so ticket 20–24 snapshots compare exactly (pinned by the legacy
comparison tests). Rollback is source-only: revert the schema/DDL, the
migration, `references.py`, the two operations modules, the two readers, the
regenerated client files, `api.ts`, `client.ts`, `ArtifactEditor.tsx`,
`CanvasEditor.tsx`, the styles, the affected docs, and restore the edited test
files; delete `tests/persistence/test_reference_links.py` and
`frontend/src/ArtifactEditor.test.tsx`.

Known limits, documented rather than silently accepted: the artifact Evidence
panel and canvas picker author source references visibly — message, artifact
and canvas-node references are fully validated and resolvable through the API
but gain their dedicated chat-to-canvas/artifact picker controls with tickets
26–31; canvas reference availability for non-source kinds renders as
kind + id until those pickers land; resolution is per read (bounded ≤ 20
references per artifact, ≤ 20 per canvas node); and linked evidence never
carries excerpts into the canvas — the bounded context planning for coaching
on selected nodes remains ticket 27's work.

**Next exact action:** tickets 20–25 all have acceptance evidence. The
frontier now includes ticket 26 (turn selected chat content into canvas nodes,
blocked by 21 ✓ and 25 ✓), 27 (coach selected canvas reasoning, blocked by
6 ✓, 21 ✓ and 25 ✓), 29 (review and accept artifact feedback, blocked by
6/16/17/25 — all ✓), 32 (resume a project from persisted work, all ✓) and 35
and 37–40. Start exactly one fresh writer session for
`.scratch/architecture-completion/issues/26-turn-selected-chat-content-into-canvas-nodes.md`
in this same checkout, preserving the dirty working tree.

### Ticket 24 complete — export complete canvases (2026-11-25 SGT, OpenCode)

**Ticket 24 is implemented and locally verified.** Students download the saved
canvas as structured graph JSON, a human-readable outline or a legible SVG
through bounded owner-checked attachments: the JSON envelope carries title,
revision metadata, editor provenance and the canonical graph with no workspace
identifiers, the outline names every node kind/stage and labeled relationship
without internal ids, and the SVG always spans the whole graph — off-screen
nodes included — with all text XML-escaped. No hosted rendering service was
introduced. Triage remains `ready-for-agent`; nothing is staged, committed or
deployed.

Starting revision/branch: `improvement/architecture-responsiveness` with the
dirty ticket 01–23 working tree preserved unchanged apart from this ticket's
files.

#### New files and behavior

| File | Responsibility |
| --- | --- |
| `backend/canvas_export.py` | New pure renderer: the JSON envelope (title, schema version, revision, origin, timestamps, canonical graph — no ids, owner or operational fields), the readable outline (kinds, stages, titles, descriptions, labeled relationships with explanations — internal node ids stay out), and a deterministic SVG whose extent derives from node positions so off-screen nodes are always included, with edges, relation labels and XML-escaped node text. |
| `backend/http/reader_canvases.py` | `GET …/canvases/{canvas_id}/export?format=json\|outline\|svg` — a documented download outside the JSON browser contract (like the artifact export): same-origin enforced, `nosniff` attachment with a sanitized `filename*` header, `Cache-Control: no-store`, and 422 for unsupported formats. |
| `frontend/src/api/client.ts` | `downloadCanvasExport` — the raw fetch download with same-origin cookies, `no-store`, caller cancellation and a sanitized local filename. |
| `frontend/src/CanvasEditor.tsx` | An export group (JSON / Outline / SVG) beside the header with the same owner-verification and honest failure handling as the other controls. |
| `tests/domain/test_canvas_export.py` | Pure-renderer tests: provenance-only JSON envelope, readable outline without node ids, SVG including the off-screen node with hostile text escaped (`Unsafe &lt;crossing&gt;`, raw `<crossing>` never present), unsupported-format refusal, and a truthful empty-canvas visual. |
| `tests/http/test_reader_canvases.py` | HTTP seam test: all three formats download with `nosniff`/attachment/`no-store`, sanitized filenames (path segments stripped), inert SVG content, 422 unsupported format, 404 foreign/unknown, 401 anonymous. |
| `tests/test_architecture_contracts.py` + `tests/http/test_security_readiness.py` | Route inventory extended with the export route (deliberately outside the generated JSON contract as the documented download exception); the same-origin and second-owner sweeps cover the new route. |
| `frontend/src/CanvasEditor.test.tsx` | jsdom transport journey: the Export JSON click issues the export request with `?format=json` and reports "Exported as json." once the download settles. |

#### Executed validation

| Command/check | Result |
| --- | --- |
| `pytest tests/domain/test_canvas_export.py` | 4 passed (red first: `ModuleNotFoundError: backend.canvas_export`). |
| `pytest tests/http/test_reader_canvases.py` | 4 passed (red first: 404 unmatched export route). |
| `pytest tests/persistence/ tests/http/test_reader_canvases.py tests/http/test_reader_artifacts.py tests/test_architecture_contracts.py tests/http/test_security_readiness.py tests/scripts/test_export_reader_openapi.py tests/http/test_notebook_reader.py tests/test_deployment_config.py tests/scripts/test_init_dsql.py` | **301 passed.** |
| `npm test --prefix frontend` | **149 passed / 18 files** (148 before this ticket). |
| `npm run build --prefix frontend` | Exit 0 (`tsc --noEmit` + Vite production build). |
| `npm run api:check --prefix frontend` | Exit 0 — the export route deliberately stays outside the generated contract as a download exception. |
| `npm run test:browser --prefix frontend` | **7 passed**. |
| `.venv/bin/ruff check .` | Exit 0. |
| `compileall` (backend, ui, streamlit_app, tests, scripts, agentcore_runtime) | Exit 0. |
| Full mock suite | **Exit 0 with 3,240 passed / 1 skipped** — the 3,235 baseline plus this ticket's five new backend tests. |
| Post-run leak check | No disposable-stack/uvicorn/playwright processes; `git diff --check` clean. |

#### Compatibility, rollback and next exact action

No schema or existing-API change: the export route is additive, excluded from
the generated JSON contract as the documented download exception, and every
existing route and payload is untouched. Exports contain the canonical graph,
student-facing metadata and provenance only — hidden prompts, operational
data, storage keys and other owners' canvases never enter the output, and
untrusted node/relationship text stays inert through attachment+nosniff
headers and XML escaping. Bounded by the canonical graph's existing 256 KiB
storage limit. Rollback is source-only: delete `backend/canvas_export.py`,
revert `reader_canvases.py`, remove the export group from `CanvasEditor.tsx`,
delete `downloadCanvasExport` from `client.ts` and the two new test files, and
restore `tests/test_architecture_contracts.py` and
`tests/http/test_security_readiness.py`.

Known limits, documented rather than silently accepted: the SVG is a
deterministic schematic rendering (positioned boxes, straight lines and
relation labels) rather than a pixel-perfect screenshot; node descriptions are
deliberately excluded from the visual (they remain in the outline and JSON) to
keep labels legible; and the outline/JSON exports carry no viewport state by
design — viewport preferences never create meaningful revisions.

**Next exact action:** tickets 20–24 all have acceptance evidence, closing the
canvas chain including exports. The frontier now includes ticket 25 (link
artifacts and canvas reasoning to evidence, blocked by 15 ✓ and 20 ✓), 32
(resume a project from persisted work, blocked by 9/15/20 — all ✓) and 35 and
37–40. Start exactly one fresh writer session for
`.scratch/architecture-completion/issues/25-link-artifacts-and-canvas-reasoning-to-evidence.md`
in this same checkout, preserving the dirty working tree.

### Ticket 23 complete — preview and restore canvas versions (2026-11-25 SGT, OpenCode)

**Ticket 23 is implemented and locally verified.** Every canvas save and
restore checkpoints a bounded version with truthful provenance; the editor's
History panel lists checkpoints, previews one as a readable node/relationship
outline, and restores it as a **new** revision guarded by the seen revision —
all intervening history survives restarts and foreign owners never see it.
Triage remains `ready-for-agent`; nothing is staged, committed or deployed.

Starting revision/branch: `improvement/architecture-responsiveness` with the
dirty ticket 01–22 working tree preserved unchanged apart from this ticket's
files.

#### New files and behavior

| File | Responsibility |
| --- | --- |
| `backend/persistence/store/sqlite_schema.py` + `backend/persistence/dsql_schema.py` | Additive `student_canvas_versions` table (per-canvas checkpoints with canonical graphs, `origin`, `restored_from` lineage, unique `(canvas_id, revision)`; the DSQL uniqueness uses `CREATE UNIQUE INDEX ASYNC`) and the notebook child-delete plan / DSQL child-table inventory extended. |
| `backend/persistence/store/migrations.py` | `migrate_student_canvas_versions` upgrades legacy stores in place; legacy canvases truthfully report no versions until their next save checkpoints one. |
| `backend/persistence/store/operations/canvases.py` | Every create/update checkpoints a version row before the OCC update (a lost race rolls the checkpoint back); `list_versions` returns bounded (≤ 50) newest-first metadata; `get_version` returns one readable preview; `restore` guards on the current revision, creates a new revision with `origin: 'restore'` and `restored_from` lineage, and keeps every intermediate. |
| `backend/student_store.py` | Façade gains `list_canvas_versions`, `get_canvas_version`, `restore_canvas`. |
| `backend/http/reader_canvases.py` | Three generated operations: `readerCanvasVersions` (bounded metadata), `readerCanvasVersion` (readable preview), `readerCanvasRestore` (POST with the seen-revision guard; 409 stale, 404 foreign/unknown). |
| `scripts/export_reader_openapi.py` | Allowlist extended from thirty-nine to forty-two operations. |
| `frontend/openapi/reader.json` + `frontend/src/api/generated/*` | Re-exported offline and regenerated; `npm run api:check` reports no drift. |
| `frontend/src/api/client.ts` + `frontend/src/api.ts` | `readCanvasVersions`, `readCanvasVersion`, `restoreCanvasVersion` over the generated SDK with the canonical-graph adapter for previews. |
| `frontend/src/CanvasEditor.tsx` | A **History** panel: bounded checkpoint list with truthful provenance labels, a readable plain-text outline preview (node kinds/titles/stages plus labeled relationships), and a restore action guarded by the seen revision with 409 recovery; restoring loads the confirmed content, reports the restored version and refreshes the checkpoint list on the next open. |
| `tests/persistence/test_student_canvases.py` | New test: versions per create/save, bounded newest-first metadata, preview, restore-as-new-revision keeping intermediates, stale restore, foreign invisibility. |
| `tests/http/test_reader_canvases.py` | New HTTP seam test: versions list without bodies, preview, guarded restore, stale 409, unknown 404, second-owner 404s. |
| `tests/test_architecture_contracts.py` + `tests/http/test_security_readiness.py` + `tests/scripts/test_export_reader_openapi.py` | Store/route inventories extended; the same-origin and second-owner sweeps cover the new routes; the schema inventory gains the three version models. |
| `frontend/src/api/client.test.ts` + `frontend/src/CanvasEditor.test.tsx` | Version transport coverage (paths, restore body, status-only errors) and the History panel journey (preview read-only, restore PUT carrying the seen revision, restored content shown). |

#### Executed validation

| Command/check | Result |
| --- | --- |
| `pytest tests/persistence/test_student_canvases.py` | 7 passed (red first: the missing `list_canvas_versions` façade). |
| `pytest tests/http/test_reader_canvases.py` | 3 passed (red first: missing version routes). |
| `pytest tests/persistence/ tests/http/test_reader_canvases.py tests/http/test_reader_artifacts.py tests/test_architecture_contracts.py tests/http/test_security_readiness.py tests/scripts/test_export_reader_openapi.py tests/http/test_notebook_reader.py tests/test_deployment_config.py tests/scripts/test_init_dsql.py` | **301 passed.** |
| `npm test --prefix frontend` | **148 passed / 18 files** (142 before this ticket). |
| `npm run build --prefix frontend` | Exit 0 (`tsc --noEmit` + Vite production build). |
| `npm run api:check --prefix frontend` | Exit 0 — no schema or generated-client drift. |
| `npm run test:browser --prefix frontend` | **7 passed**. |
| `.venv/bin/ruff check .` | Exit 0. |
| `compileall` (backend, ui, streamlit_app, tests, scripts, agentcore_runtime) | Exit 0. |
| Full mock suite | **Exit 0 with 3,235 passed / 1 skipped** — the 3,233 baseline plus this ticket's two new backend tests. |
| Post-run leak check | No disposable-stack/uvicorn/playwright processes; `git diff --check` clean. |

#### Compatibility, migration and rollback

The migration is additive: legacy stores gain the versions table in place with
no data rewrite (legacy canvases truthfully report no versions until their
next save), the DSQL DDL joins the admin-only bootstrap with the async unique
index, and no existing table, route or payload changed. Restores are new
revisions, so nothing is ever overwritten or lost; the autosave, conflict and
undo/redo flows keep their documented behavior (notebook deletion now also
removes canvas history). Rollback is source-only: revert the schema/DDL, the
migration, the operations and façade methods, `reader_canvases.py`, the
allowlist and regenerated client files, `client.ts`, `api.ts`,
`CanvasEditor.tsx`, `frontend/README.md`, `docs/DATABASE.md`,
`docs/LOCAL_DEMO_IMPLEMENTATION.md`, and restore the edited test files.

Known limits, documented rather than silently accepted: the history panel
lists at most the 50 most recent checkpoints (bounded by design, not a
complete audit log); version previews render as a bounded plain-text outline
rather than a visual mini-map; the restore takes the version's saved title
back with its content; and "duplicate restore" (restoring the same version
twice) is intentionally allowed — each restore is a new explicit revision.

**Next exact action:** tickets 20, 21, 22 and 23 all have acceptance evidence,
closing the canvas chain (20–23). The frontier now includes ticket 32 (resume
a project from persisted work, blocked by 9/15/20 — all ✓), 24 (export
complete canvases, blocked by 21 ✓ and 23 ✓), 25 (link artifacts and canvas
reasoning to evidence, blocked by 15 ✓ and 20 ✓) and 35 and 37–40. Start
exactly one fresh writer session for
`.scratch/architecture-completion/issues/24-export-complete-canvases.md`
in this same checkout, preserving the dirty working tree.

### Ticket 22 complete — autosave canvases without overwriting another tab (2026-11-24 SGT, OpenCode)

**Ticket 22 is implemented and locally verified.** Canvas edits now autosave
through the same revision-guarded cycle as artifacts: a burst of outline
edits inside the two-second pause collapses into exactly one confirmed
revision, edits during flight trail onto the confirmed revision, completed
drags produce at most one checkpoint (never one per pointer move), drafts are
owner-scoped in session storage and restored after refresh with a visible
notice, and a two-tab 409 conflict keeps the losing graph visible with
explicit reload / keep-and-save-over resolutions. The seam also surfaced a
latent stale-revision bug in the shared autosave hook — fixed for both the
artifact and canvas editors. Triage remains `ready-for-agent`; nothing is
staged, committed or deployed.

Starting revision/branch: `improvement/architecture-responsiveness` with the
dirty ticket 01–21 working tree preserved unchanged apart from this ticket's
files.

#### New files and behavior

| File | Responsibility |
| --- | --- |
| `frontend/src/useArtifactAutosave.ts` | Generalized over the saved subject (`AutosaveSubject`: id/owner/revision; artifacts and canvases both satisfy it) with a `draftKind` namespace (`codesign-canvas-draft:` vs the artifact key) and a new `onConfirmed` callback: after a successful save the caller reconciles the confirmed revision, so a second autosave carries the fresh revision instead of replaying a stale one and 409-ing (red test observed `[1, 1]` before the fix). |
| `frontend/src/ArtifactEditor.tsx` | Wires `onConfirmed` to the artifact state; the content-loading effect now loads content only on first open or explicit handoffs (pending content), so confirmed autosaves reconcile the revision without clobbering the editor mid-typing. |
| `frontend/src/CanvasEditor.tsx` | The canvas uses the shared hook: every outline mutation, duplication, connection, removal and completed drag routes through `markDirty`; a `graphRef` mirror lets the hook fold pre-flight edits into the in-flight snapshot; the explicit Save button calls `saveNow`; conflict resolution reuses the hook's `resolveByReload` plus the keep-and-save-over flow; drafts restore after refresh with a notice; the truthful Editing/Saving/Saved/Offline/Failure/Conflict notice replaces the bespoke status strings. |
| `frontend/src/CanvasAutosave.test.tsx` | New fake-timer component tests: a burst collapses into exactly one confirmed PUT carrying the added node at revision 1 and reconciles to "All changes saved."; an autosave 409 keeps the losing graph visible with the explicit conflict copy. |
| `frontend/src/useArtifactAutosave.test.ts` | New reconciliation test: two back-to-back autosaves carry revisions `[1, 2]` through `onConfirmed` alone (no manual state commit), pinning the stale-revision fix. |
| `frontend/src/CanvasEditor.test.tsx` | Pinned assertions updated for the new honest behavior: the editing notice replaces "not saved yet" and the undo flow is autosaved like any edit; sessionStorage is cleared between tests now that drafts restore. |

#### Executed validation

| Command/check | Result |
| --- | --- |
| `npx vitest run src/useArtifactAutosave.test.ts` | 7 passed (red first: the reconciliation test observed `[1, 1]` — the second autosave replayed the stale revision). |
| `npx vitest run src/CanvasAutosave.test.tsx` | 2 passed (red first: no autosave PUT occurred before the hook wiring). |
| `npm test --prefix frontend` | **142 passed / 18 files** (139 before this ticket). |
| `npm run build --prefix frontend` | Exit 0 (`tsc --noEmit` + Vite production build). |
| `npm run api:check --prefix frontend` | Exit 0 — no schema or generated-client drift. |
| `npm run test:browser --prefix frontend` | **7 passed**. |
| `npx tsc --noEmit` | Exit 0. |
| Post-run leak check | No disposable-stack/uvicorn/playwright processes; `git diff --check` clean. |

No backend, schema or API contract changed in this ticket; the backend suites
from tickets 20–21 remain the pinned evidence (full mock suite: 3,233 passed /
1 skipped) and were not re-run.

#### Compatibility, rollback and next exact action

No schema or API change: the autosave reuses the existing revision-guarded PUT
contract, drafts are owner-scoped and session-only, and nothing transfers
across owners or accounts. The artifact-editor change is a behavior fix —
previously a second autosave would have replayed the stale revision and forced
a conflict — and the content-guard preserves every existing load, restore and
keep-my-edits path. Rollback is source-only: revert `useArtifactAutosave.ts`
(and its test), `ArtifactEditor.tsx`, `CanvasEditor.tsx`, delete
`CanvasAutosave.test.tsx`, and restore `CanvasEditor.test.tsx`,
`frontend/README.md`, `docs/LOCAL_DEMO_IMPLEMENTATION.md` and `docs/TESTING.md`.

Known limits, documented rather than silently accepted: the artifact editor's
component-level wiring (reconciliation + content guard) is verified through the
shared hook contract and typecheck rather than a dedicated ArtifactEditor
component suite; undo/redo history clears on each confirmed save by design
(durable checkpoints are the saved revisions; ticket 23 adds inspectable
version history); the offline retry waits for the next edit or timer rather
than listening to browser online events (same as artifacts); and drafts are
canvas-scoped in this tab only — another tab editing the same canvas is the
conflict path.

**Next exact action:** ticket 22's dependency (20) has acceptance evidence.
The frontier now includes ticket 23 (preview and restore canvas versions,
blocked by 22 ✓), 32 (resume a project from persisted work, blocked by 9/15/20
— all ✓), 35 and 37–40. Start exactly one fresh writer session for
`.scratch/architecture-completion/issues/23-preview-and-restore-canvas-versions.md`
in this same checkout, preserving the dirty working tree.

### Ticket 21 complete — explore and edit a complete visual reasoning map (2026-11-24 SGT, OpenCode)

**Ticket 21 is implemented and locally verified.** The design canvas is now a
full visual reasoning map: nodes may associate with a Thinking Path stage
(server-validated, label only), the outline duplicates nodes with their content
and stage, the map supports multi-selection with safe incident-edge removal,
search narrows the outline and locates a match on the map, type/stage filters
dim non-matching nodes, and bounded local undo/redo restores edits without
pretending to be durable version history. Triage remains `ready-for-agent`;
nothing is staged, committed or deployed.

Starting revision/branch: `improvement/architecture-responsiveness` with the
dirty ticket 01–20 working tree preserved unchanged apart from this ticket's
files.

#### New files and behavior

| File | Responsibility |
| --- | --- |
| `backend/persistence/store/operations/canvases.py` | `CANVAS_STAGE_IDS` allowlist (the five persisted Thinking Path stage ids); an optional `stage` joins the canonical node only when set, so legacy ticket-20 snapshots compare exactly; unknown stages fail closed (`Unknown Thinking Path stage`). |
| `backend/http/reader_canvases.py` | The canvas list projects the server-owned `stages` allowlist beside `node_kinds`/`relations`; no route paths or payloads changed otherwise. |
| `frontend/openapi/reader.json` + `frontend/src/api/generated/*` | Re-exported offline and regenerated; `npm run api:check` reports no drift. |
| `frontend/src/api.ts` | `CANVAS_STAGE_IDS`/`CANVAS_STAGE_LABELS`, `CanvasNode.stage?`, `CanvasSummaries.stages`. |
| `frontend/src/CanvasEditor.tsx` | React Flow provider + `fitView` locate; node duplication beside the original with kind/title/description/stage; per-node stage select (add form and details); canvas remove changes (`onNodesChange`/`onEdgesChange` `remove` types) route through the same graph state with incident-edge handling, enabling native multi-select Delete/Backspace; search narrows the outline to title/description matches with a one-match Locate (fit-to-node); type and stage filters narrow the outline and dim non-matching nodes/edges (never hide, so the map stays honest); bounded (≤50-entry) tab-local undo/redo with buttons and ⌘Z/⇧⌘Z outside text fields, cleared on save and labelled local-only; the explicit status message now takes precedence over the derived summary so undo/redo outcomes are visible. |
| `frontend/src/styles.css` | Dimmed-node styling and the find/filter control row. |
| `tests/persistence/test_student_canvases.py` | New test: a node's stage association saves and reopens exactly, omission stays absent for legacy snapshots, and unknown stages fail closed. |
| `tests/http/test_reader_canvases.py` | The lifecycle asserts the `stages` allowlist in the listing and a staged graph round-trips through the public seam. |
| `frontend/src/CanvasEditor.test.tsx` | Four new tests: duplicate + stage association saved exactly (both nodes carry the stage), local undo restores a removed node with no save request, search narrows the node list and offers locate, and the type filter narrows the node list. |

#### Executed validation

| Command/check | Result |
| --- | --- |
| `pytest tests/persistence/test_student_canvases.py` | 6 passed (red first: the stage key was silently dropped by canonicalization — observed `KeyError: 'stage'` before the allowlist implementation). |
| `pytest tests/http/test_reader_canvases.py` | 2 passed (red first: missing `stages` in the listing). |
| `pytest tests/persistence/test_student_canvases.py tests/http/test_reader_canvases.py tests/test_architecture_contracts.py tests/http/test_security_readiness.py tests/http/test_notebook_reader.py tests/persistence/test_student_artifacts.py tests/http/test_reader_artifacts.py tests/scripts/test_export_reader_openapi.py` | **97 passed.** |
| `npm test --prefix frontend` | **139 passed / 17 files** (136 before this ticket). |
| `npm run build --prefix frontend` | Exit 0 (`tsc --noEmit` + Vite production build). |
| `npm run api:check --prefix frontend` | Exit 0 after regeneration (one genuine drift was caught by the check and fixed by re-running the export + generation together). |
| `npm run test:browser --prefix frontend` | **7 passed**. |
| `.venv/bin/ruff check .` | Exit 0. |
| `compileall` (backend, ui, streamlit_app, tests, scripts, agentcore_runtime) | Exit 0. |
| Full mock suite | **Exit 0 with 3,233 passed / 1 skipped** — the 3,232 baseline plus this ticket's new stage test. |
| Post-run leak check | No disposable-stack/uvicorn/playwright processes or listeners on ports 8121–8129; `git diff --check` clean. |

#### Compatibility, rollback and next exact action

No schema change: the optional `stage` lives inside the validated canonical
snapshot and only appears when set, so every ticket-20 canvas keeps opening and
comparing exactly (pinned by test). The `stages` field on the canvas list is
additive to the generated contract; no existing route, payload or behavior
changed. Undo/redo is client-only state with no server interaction. Rollback is
source-only: revert `canvases.py`, `reader_canvases.py`, the regenerated client
files, `api.ts`, `CanvasEditor.tsx`, `styles.css`, `frontend/README.md`,
`docs/LOCAL_DEMO_IMPLEMENTATION.md`, and restore the three edited test files.

Known limits, documented rather than silently accepted: undo/redo is bounded
(50 entries) and tab-local — closing the tab or saving discards it, and it is
never presented as version history (that remains ticket 23's persisted flow);
multi-select on the map uses React Flow's native shift-click/selection and
Delete/Backspace wiring, exercised through the remove-change handlers and the
outline rather than an automated canvas-drag browser spec; locate requires the
match to be unique to show the button (ambiguous matches stay in the outline);
and the stage association remains a visible label — creating nodes or tagging
stages never satisfies or changes Thinking Path requirements.

**Next exact action:** ticket 21's dependency (20) has acceptance evidence.
The frontier now includes ticket 22 (autosave canvases without overwriting
another tab, blocked by 20 ✓), 32 (resume a project from persisted work,
blocked by 9/15/20 — all ✓), 35 and 37–40. Start exactly one fresh writer
session for
`.scratch/architecture-completion/issues/22-autosave-canvases-without-overwriting-another-tab.md`
in this same checkout, preserving the dirty working tree.

### Ticket 20 complete — create and reopen a persistent Design Canvas (2026-11-24 SGT, OpenCode)

**Ticket 20 is implemented and locally verified.** A student can create an
empty design canvas from the notebook page's Canvas tab, add/edit course-aligned
nodes and labeled relationships, explicitly save, and reopen the exact graph
after a real backend restart through the routed React Flow view with an
accessible outline that supports every essential action without dragging.
Triage remains `ready-for-agent`; nothing is staged, committed or deployed.

Starting revision/branch: `improvement/architecture-responsiveness` with the
dirty ticket 01–19 working tree preserved unchanged apart from this ticket's
files.

#### New files and behavior

| File | Responsibility |
| --- | --- |
| `backend/persistence/store/sqlite_schema.py` + `backend/persistence/dsql_schema.py` | Additive `student_canvases` table (canonical `graph_text` snapshot, `schema_version`, monotonic `revision`, `origin`, timestamps) with the notebook/updated index, and the canvas table joining the notebook child-delete plan / DSQL child-table inventory. |
| `backend/persistence/store/migrations.py` | `migrate_student_canvases` upgrades legacy stores in place; pre-canvas databases gain the table with every existing row untouched. |
| `backend/persistence/store/operations/canvases.py` | New pure validation + repository module: `canonical_canvas_graph` (object with `nodes`/`edges` only; ≤ 100 nodes, ≤ 200 edges, ≤ 256 KiB; unique bounded node/edge ids; 12 allowlisted course-aligned node kinds; 9 allowlisted relations; edges joining existing distinct nodes only; finite positions; canonical JSON so stale-save comparison is exact), `create`/`get`/`list` (metadata only)/`update` with the revision guard (`CanvasConflictError`) and ownership enforced in every statement. |
| `backend/persistence/store/operations/__init__.py` + `backend/student_store.py` | Binds the canvas operations and exposes `create_canvas`/`get_canvas`/`list_canvases`/`update_canvas` on the store façade. |
| `backend/http/reader_canvases.py` | Four generated operations: `readerCanvases` (list with the server-owned `node_kinds`/`relations` allowlists), `readerCanvasCreate` (201), `readerCanvas` (read), `readerCanvasUpdate` (PUT with the seen-revision guard; 409 stale, 404 foreign/unknown, 422 unsafe graph); foreign or mismatched ids fail 404 without echoing other owners' graphs. |
| `backend/http/notebook_reader.py` | Registration plus the recognized view paths `/notebooks/{folder_id}/canvases/{canvas_id}` and its `/pilot/…` alias serving the SPA shell (Caddy's existing `/notebooks/*` matcher already covers them; no edge change). |
| `scripts/export_reader_openapi.py` | Allowlist extended from thirty-five to thirty-nine operations. |
| `frontend/openapi/reader.json` + `frontend/src/api/generated/*` | Re-exported offline and regenerated; `npm run api:check` reports no drift. |
| `frontend/src/api/client.ts` + `frontend/src/api.ts` | `readCanvases`, `createCanvas`, `readCanvas`, `saveCanvas` over the generated SDK with the canonical-graph adapter (a non-canonical graph fails closed) and the typed `CanvasGraph`/`CanvasNode`/`CanvasEdge`/`CANVAS_NODE_KINDS`/`CANVAS_RELATIONS` contracts. |
| `frontend/src/workspaceRoute.ts` | New typed nested route `/notebooks/{folder}/canvases/{canvas}` (+ `/pilot/…` alias); malformed or traversal-shaped identities render the public default. |
| `frontend/src/CanvasEditor.tsx` | React Flow (`@xyflow/react@13.0.3`, `npm audit` clean) map beside an accessible outline: add node (type/title/description), edit type/title/description, remove node with incident-edge handling, connect two nodes with a labeled relation and optional explanation (duplicate pair refused), edit/remove relations, and drag-to-position that stays local until the explicit revision-guarded Save; a 409 conflict keeps the student's edits visible with reload / keep-and-save-over resolutions; honest Editing/Not saved/Saving/All changes saved/Conflict statuses. |
| `frontend/src/NotebookPage.tsx` + `frontend/src/App.tsx` | The notebook **Canvas** tab creates one empty canvas through the generated contract, lists saved canvases and opens the typed route owned by App. |
| `frontend/src/styles.css` | Canvas surface/outline styles using the existing theme variables. |
| `tests/persistence/test_student_canvases.py` | Legacy in-place upgrade evidence, ownership isolation, revision-guarded stale saves, snapshot validation (duplicate ids, unknown/self endpoints, unsupported kinds/relations, too many nodes, oversized/unknown keys), notebook-deletion cleanup and restart persistence. |
| `tests/http/test_reader_canvases.py` | Full lifecycle through the public HTTP seam including a real backend restart, stale 409, unsafe 422, same-origin enforcement with valid bodies, and foreign-owner 404s. |
| `tests/test_architecture_contracts.py` + `tests/http/test_security_readiness.py` + `tests/http/test_notebook_reader.py` + `tests/scripts/test_export_reader_openapi.py` | Store and route inventories extended; the same-origin and second-owner sweeps cover the canvas routes; deep-link shell coverage for both canvas view prefixes; schema inventory extended. |
| `frontend/src/CanvasEditor.test.tsx` + `frontend/src/api/client.test.ts` + `frontend/src/workspaceRoute.test.ts` | Outline add/connect flows with exactly one confirmed PUT, honest 409 conflict keeping the draft, canvas transport bodies/paths/status-only errors, and canvas route parsing/round-trip. |

#### Executed validation

| Command/check | Result |
| --- | --- |
| `pytest tests/persistence/test_student_canvases.py` | 5 passed (red first: the missing `migrate_student_canvases` import; then the oversize-junk case observed passing silently before the unknown-keys/raw-size fail-closed fix). |
| `pytest tests/http/test_reader_canvases.py` | 2 passed (red first: 404 unmatched canvas routes). |
| `pytest tests/persistence/test_student_canvases.py tests/http/test_reader_canvases.py tests/test_architecture_contracts.py tests/http/test_security_readiness.py tests/http/test_notebook_reader.py tests/test_deployment_config.py tests/persistence/test_student_artifacts.py tests/http/test_reader_artifacts.py tests/scripts/test_export_reader_openapi.py tests/scripts/test_init_dsql.py` | **135 passed** (the first exporter run failed exactly the missing five canvas schemas, then the inventory was extended). |
| `npm test --prefix frontend` | **136 passed / 18 files** (126 before this ticket). |
| `npm run build --prefix frontend` | Exit 0 (`tsc --noEmit` + Vite production build). |
| `npm run api:check --prefix frontend` | Exit 0 — no schema or generated-client drift. |
| `npm audit --audit-level=high --prefix frontend` | Exit 0 with the new `@xyflow/react@^13.0.3` dependency. |
| `npm run test:browser --prefix frontend` | **7 passed**. |
| `.venv/bin/ruff check .` | Exit 0. |
| `compileall` (backend, ui, streamlit_app, tests, scripts, agentcore_runtime) | Exit 0. |
| Full mock suite | **Exit 0 with 3,232 passed / 1 skipped** — the 3,225 baseline plus this ticket's seven new backend tests. Log: `/private/tmp/ticket20-pytest-full.log`. |
| Post-run leak check | No disposable-stack/uvicorn/playwright processes or listeners on ports 8121–8129; `git diff --check` clean. |

#### Compatibility, migration and rollback

The migration is additive: the SQLite startup path creates `student_canvases`
in place on legacy databases with every existing row untouched (proven by the
legacy-upgrade test), the DSQL DDL joins the admin-only bootstrap and never
runs at application startup, and no existing table, route or payload changed.
The four canvas routes are new and generated; every existing route keeps its
path. The Canvas tab is additive to the notebook page and the canvas route is
additive to the typed route tree; the recognized-view SPA fallback extends only
to the new canvas deep links. Rollback is source-only: revert the schema/DDL,
the migration, the operations module and binding, the façade methods,
`reader_canvases.py` and its registration, the allowlist and regenerated client
files, `client.ts`, `api.ts`, `workspaceRoute.ts`, `CanvasEditor.tsx`,
`NotebookPage.tsx`, `App.tsx`, the styles, `frontend/README.md`,
`docs/DATABASE.md`, and restore the edited test files; drop
`@xyflow/react` from `package.json`/lockfile.

Known limits, documented rather than silently accepted: saving is explicit —
there is no canvas autosave (ticket 22), no version history (ticket 23) and no
export (ticket 24); unsaved edits are not checkpointed to session storage, so a
tab close before an explicit save loses that draft by design for this slice;
visual editing beyond dragging (connection drawing, node deletion on the map)
arrives with ticket 21 — the outline is the authoritative editing surface; node
counts and canvas activity never award completion or change stages; and the 12
kinds/9 relations are fixed server allowlists (extending them is a reviewed
contract change, not free text).

**Next exact action:** ticket 20's dependency (14) has acceptance evidence.
The frontier now includes ticket 21 (explore and edit a complete visual
reasoning map, blocked by 20), 22 (autosave canvases, blocked by 20), 32
(resume a project from persisted work, blocked by 9/15/20 — 9 and 15 have
acceptance evidence), 35 and 37–40. Start exactly one fresh writer session for
`.scratch/architecture-completion/issues/21-explore-and-edit-a-complete-visual-reasoning-map.md`
in this same checkout, preserving the dirty working tree.

### Ticket 19 complete — export student artifacts safely (2026-11-24 SGT, OpenCode)

**Ticket 19 is implemented and locally verified.** Students can export the
current saved artifact as meaningful Markdown, plaintext or canonical JSON
with title, kind, revision metadata and editor provenance — as inert
`nosniff` attachments that exclude hidden prompts, operational data and
storage details, and degrade unsafe URLs to plain text. Triage remains
`ready-for-agent`; nothing is staged, committed or deployed.

Starting revision/branch: `improvement/architecture-responsiveness` with the
dirty ticket 01–18 working tree preserved unchanged apart from this ticket's
files.

#### New files and behavior

| File | Responsibility |
| --- | --- |
| `backend/artifact_export.py` | New pure rendering module: canonical Tiptap document → Markdown (headings, emphasis, bullet/ordered lists, code blocks, safe `[text](url)` links), plaintext (no markers), and the JSON envelope (title, kind, schema version, revision, origin, timestamps, canonical document — no ids, owner or operational fields). Unsafe URL schemes (`javascript:` and anything not `http(s)`/root-relative) lose the link and keep the text, in every format. |
| `backend/http/reader_artifacts.py` | `GET …/artifacts/{artifact_id}/export?format=markdown\|text\|json` — a documented text download outside the JSON browser contract (like the transcript export): same-origin enforced, `nosniff` attachment with a sanitized `filename*` header (path segments stripped), `Cache-Control: no-store`, and 422 for unsupported formats. |
| `frontend/src/api/client.ts` | `downloadArtifactExport` — the raw fetch download with same-origin cookies, `no-store`, caller cancellation and a sanitized local filename. |
| `frontend/src/ArtifactEditor.tsx` | An export group (Markdown / Plain text / JSON) beside the editor actions with the same owner-verification and honest failure handling as the other controls. |
| `tests/domain/test_artifact_export.py` | Pure-renderer tests: meaningful Markdown with inert unsafe URLs, plaintext without markers, the provenance-only JSON envelope, and format refusal. |
| `tests/http/test_reader_artifacts.py` | HTTP seam test: all three formats download with `nosniff`/attachment/`no-store`, sanitized filenames (path segments stripped), inert URLs, 422 unsupported format, 404 foreign/unknown, 401 anonymous, 404 second owner. |
| `tests/test_architecture_contracts.py` | Route inventory extended with the export route (which deliberately stays out of the generated JSON contract as a download exception). |
| `frontend/src/api/artifactDownload.test.ts` | jsdom transport test: path, `format` query, same-origin credentials, `no-store` and caller cancellation. |

#### Executed validation

| Command/check | Result |
| --- | --- |
| `pytest tests/domain/test_artifact_export.py` | 2 passed (red first: link hrefs read from the wrong mark level and list items flattened incorrectly — both observed red). |
| `pytest tests/http/test_reader_artifacts.py tests/test_architecture_contracts.py tests/domain/test_artifact_export.py` | 15 passed. |
| `npm test --prefix frontend` | **126 passed / 16 files** (125 before this ticket). |
| `npm run build --prefix frontend` | Exit 0 (`tsc --noEmit` + Vite production build). |
| `npm run api:check --prefix frontend` | Exit 0 — the export route deliberately stays outside the generated contract as a download exception. |
| `npm run test:browser --prefix frontend` | **7 passed**. |
| `.venv/bin/ruff check .` | Exit 0. |
| `compileall` (backend, ui, streamlit_app, tests, scripts, agentcore_runtime) | Exit 0. |
| Full mock suite | **Exit 0 with 3,225 collected** — the 3,222 baseline plus this ticket's three new tests. Log: `/private/tmp/ticket19-pytest-full.log`. |
| Post-run leak check | No disposable-stack/uvicorn/playwright processes or listeners on ports 8121–8129. |

#### Compatibility, rollback and next exact action

No schema or existing-API change: the export route is additive, excluded from
the generated JSON contract as a documented download exception, and every
existing route and payload is untouched. Exports contain the canonical
document, student-facing metadata and provenance only — hidden prompts,
operational data, storage keys and other owners' work never enter the output,
and unsafe content stays inert through attachment+nosniff headers and URL
sanitization. Bounded by the canonical document's existing 256 KiB storage
limit. Rollback is source-only: delete `backend/artifact_export.py`, revert
`reader_artifacts.py`, remove the export group from `ArtifactEditor.tsx`,
delete `downloadArtifactExport` from `client.ts` and the two test files, and
restore `tests/test_architecture_contracts.py`.

Known limits, documented rather than silently accepted: images in documents
are not part of the text export surface (only their absence is rendered);
the JSON envelope excludes the artifact id by design so a shared file carries
no workspace identifiers; and print-friendly rendering is deferred — the
Markdown download covers the documented use until a print need is validated.

**Next exact action:** tickets 16 and 18 both have acceptance evidence, so
ticket 19 is complete and the artifact chain (15–19) is closed. The frontier
now includes tickets 20 (persistent Design Canvas, blocked by 14), 32 (resume
a project from persisted work, blocked by 9/15/20), 35 and 37–40. Start
exactly one fresh writer session for the next approved ticket in this same
checkout, preserving the dirty working tree.

### Ticket 18 complete — preview and restore artifact versions (2026-11-24 SGT, OpenCode)

**Ticket 18 is implemented and locally verified.** Every artifact exposes
bounded, owner-authorized version history with truthful provenance, a readable
per-version preview, and a restore that creates a **new** revision guarded by
the current one — intermediate versions and the previous current content are
never lost. Triage remains `ready-for-agent`; nothing is staged, committed or
deployed.

Starting revision/branch: `improvement/architecture-responsiveness` with the
dirty ticket 01–17 working tree preserved unchanged apart from this ticket's
files.

#### New files and behavior

| File | Responsibility |
| --- | --- |
| `backend/persistence/store/sqlite_schema.py` + `backend/persistence/dsql_schema.py` | Additive `student_artifact_versions` table (per-artifact checkpoints with canonical documents, `origin`, `restored_from` lineage, unique `(artifact_id, revision)`) and the notebook child-delete plan / DSQL child-table inventory extended. The DSQL uniqueness uses a `CREATE UNIQUE INDEX ASYNC` — a red run of the DSQL contract test caught the inline-UNIQUE dialect violation. |
| `backend/persistence/store/migrations.py` | `migrate_student_artifact_versions` upgrades legacy stores in place; legacy artifacts truthfully report no versions until their next save checkpoints one. |
| `backend/persistence/store/operations/artifacts.py` | Every create/update checkpoints a version row before the OCC update (the conflict path rolls the checkpoint back — a red test caught the version number being computed from the already-updated row); `list_versions` returns bounded (≤ 50) newest-first metadata; `get_version` returns one readable preview; `restore` guards on the current revision, creates a new revision with `origin: 'restore'` and `restored_from` lineage, and keeps every intermediate; artifact deletion removes its history. |
| `backend/student_store.py` | Façade gains `list_artifact_versions`, `get_artifact_version`, `restore_artifact`. |
| `backend/http/reader_artifacts.py` | Three generated operations: `readerArtifactVersions` (bounded metadata), `readerArtifactVersion` (readable preview), `readerArtifactRestore` (POST with the seen-revision guard; 409 stale, 404 foreign/unknown); foreign or mismatched ids fail 404 without echoing other owners' history. |
| `scripts/export_reader_openapi.py` | Allowlist extended from thirty-two to thirty-five operations. |
| `frontend/openapi/reader.json` + `frontend/src/api/generated/*` | Re-exported offline and regenerated; `npm run api:check` reports no drift. |
| `frontend/src/api/client.ts` + `frontend/src/api.ts` | `readArtifactVersions`, `readArtifactVersion`, `restoreArtifactVersion` with the canonical-document adapter for previews. |
| `frontend/src/ArtifactEditor.tsx` | A **History** panel: bounded checkpoint list with truthful provenance labels (saved automatically / restored from N / timestamps), a read-only plain-text preview of the selected version, and a restore action guarded by the seen revision with 409 recovery; restoring loads the confirmed content into the editor and reports the restored version. |
| `tests/persistence/test_student_artifacts.py` | New test: versions per create/save, bounded newest-first metadata, preview, restore-as-new-revision keeping intermediates, stale restore, foreign invisibility, and history deletion with the artifact. |
| `tests/http/test_reader_artifacts.py` | New HTTP seam test: versions list without bodies, preview, guarded restore, stale 409, unknown 404, second-owner 404s. |
| `tests/test_architecture_contracts.py` + `tests/http/test_security_readiness.py` | Inventories extended; the same-origin and second-owner sweeps cover the new routes. |
| `frontend/src/api/client.test.ts` | Version transport coverage via the inventory and editor suites. |

#### Executed validation

| Command/check | Result |
| --- | --- |
| `pytest tests/persistence/test_student_artifacts.py tests/persistence/test_student_store.py` | 22 passed (red first: version numbering computed from the already-updated row skipped a revision; the inline-UNIQUE DSQL dialect violation was also observed red). |
| `pytest tests/http/test_reader_artifacts.py tests/scripts/test_export_reader_openapi.py tests/test_architecture_contracts.py tests/http/test_security_readiness.py tests/http/test_reader_workspace.py tests/http/test_notebook_reader.py tests/test_deployment_config.py` | **111 passed.** |
| `npm test --prefix frontend` | **125 passed / 15 files.** |
| `npm run build --prefix frontend` | Exit 0 (`tsc --noEmit` + Vite production build). |
| `npm run api:check --prefix frontend` | Exit 0 — no schema or generated-client drift. |
| `npm run test:browser --prefix frontend` | **7 passed**. |
| `.venv/bin/ruff check .` | Exit 0 (one lambda-style fix in the new test). |
| `compileall` (backend, ui, streamlit_app, tests, scripts, agentcore_runtime) | Exit 0. |
| Full mock suite | **Exit 0 with 3,222 collected** — the 3,220 baseline plus this ticket's two new tests. Log: `/private/tmp/ticket18-pytest-full2.log`. |
| Post-run leak check | No disposable-stack/uvicorn/playwright processes or listeners on ports 8121–8129. |

#### Compatibility, migration and rollback

The migration is additive: legacy stores gain the versions table in place with
no data rewrite (legacy artifacts truthfully report no versions until their
next save), the DSQL DDL joins the admin-only bootstrap with the async unique
index, and no existing table, route or payload changed. Restores are new
revisions, so nothing is ever overwritten or lost; the autosave, duplicate,
delete and conflict flows keep their documented behavior (artifact deletion
now also removes its history). Rollback is source-only: revert the schema/DDL,
the migration, the operations and façade methods, `reader_artifacts.py`, the
allowlist and regenerated client files, `client.ts`, `api.ts`,
`ArtifactEditor.tsx`, `frontend/README.md`, `docs/DATABASE.md`, and restore
the edited test files.

Known limits, documented rather than silently acknowledged: the history panel
lists at most the 50 most recent checkpoints (bounded by design, not a
complete audit log); version previews render as bounded plain text rather
than rendered rich content; the restore takes the version's saved title back
with its content (a rename after the checkpoint is reverted with it), which
the checkpoint list makes visible; and "duplicate restore" (restoring the
same version twice) is intentionally allowed — each restore is a new explicit
revision.

**Next exact action:** tickets 15, 16, 17 and 18 all have acceptance
evidence. The frontier now includes tickets 19 (export student artifacts
safely, blocked by 16 and 18), 20, 32, 35 and 37–40. Start exactly one fresh
writer session for
`.scratch/architecture-completion/issues/19-export-student-artifacts-safely.md`
in this same checkout, preserving the dirty working tree.

### Ticket 17 complete — autosave artifacts without losing conflicting drafts (2026-11-24 SGT, OpenCode)

**Ticket 17 is implemented and locally verified.** Artifact edits now autosave
after a two-second writing pause through the existing revision-guarded
contract, with deduplicated requests, distinguishable Editing/Saving/Saved/
Offline/Failure/Conflict states, two-tab conflict resolution that preserves
the losing draft, and an owner-scoped session-storage draft policy for refresh
and recovery. Triage remains `ready-for-agent`; nothing is staged, committed
or deployed.

Starting revision/branch: `improvement/architecture-responsiveness` with the
dirty ticket 01–16 working tree preserved unchanged apart from this ticket's
files.

#### New files and behavior

| File | Responsibility |
| --- | --- |
| `frontend/src/useArtifactAutosave.ts` | New autosave state machine: `markDirty` checkpoints the owner-scoped draft (session storage per owner+artifact) and schedules one debounced save; the save snapshot folds pre-flight edits into the in-flight request (a red test caught a redundant trailing save of identical content), edits made during flight trail onto the confirmed revision, and a success reconciles the revision and clears the draft. Failures distinguish offline (network) from failure (HTTP), retry on the next edit or timer without replaying a lost write blindly; a 409 conflict freezes autosaving, keeps the losing local draft in the editor and storage, and requires explicit resolution — reload the server copy, or keep the local edits and save them over the reloaded revision. Late responses after an owner change route through the existing expiry boundary; nothing crosses owners. |
| `frontend/src/ArtifactEditor.tsx` | Wires Tiptap's update event to the hook, restores this owner's unsaved draft after refresh with a visible notice, renders the truthful state indicator (Editing/Saving/All changes saved/Offline/Failure/Conflict), and renders the conflict banner with the two explicit resolution actions; the Save button and title edits join the same deduplicated cycle. |
| `frontend/src/useArtifactAutosave.test.ts` | 6 hook tests with fake timers: debounce settles into exactly one confirmed save; a burst collapses into one checkpoint; edits during flight trail onto the confirmed revision (`[1, 2]`, never duplicated); offline vs failure distinguished; conflict keeps the losing draft persisted owner-scoped with no blind retry and explicit-only resolution; drafts clear on confirmed save and exist only for their owner; disabled while no artifact is loaded. |

#### Executed validation

| Command/check | Result |
| --- | --- |
| `npx vitest run src/useArtifactAutosave.test.ts` | 6 passed (red first: the deduplication bug — pre-flight edits produced a redundant trailing save of identical content — was observed before the snapshot fix). |
| `npm test --prefix frontend` | **125 passed / 15 files** (119 before this ticket). |
| `npm run build --prefix frontend` | Exit 0 (`tsc --noEmit` + Vite production build). |
| `npm run api:check --prefix frontend` | Exit 0 — no schema or generated-client drift. |
| `npm run test:browser --prefix frontend` | **7 passed**. |
| `.venv/bin/ruff check .` | Exit 0. |
| `compileall` (backend, ui, streamlit_app, tests, scripts, agentcore_runtime) | Exit 0. |
| Full mock suite | **Exit 0 with 3,220 collected** — the ticket 16 baseline (no backend change in this ticket). Log: `/private/tmp/ticket17-pytest-full.log`. |
| Post-run leak check | No disposable-stack/uvicorn/playwright processes or listeners on ports 8121–8129. |

#### Measured write amplification

The hook tests measure actual save counts against synthetic edit bursts: any
number of edits inside one two-second pause produces **exactly one revision**;
edits during an in-flight save produce at most one trailing save carrying the
confirmed revision. A continuously writing student therefore produces at most
one revision per idle checkpoint plus one trailing save, never one revision
per keystroke; explicit Save presses outside the debounce remain available
and follow the same deduplication.

#### Compatibility, rollback, risks and next exact action

No backend, schema or API change: the autosave uses the existing
revision-guarded PUT contract, and every state transition is client-side.
Drafts are owner-scoped, artifact-scoped and session-only — nothing enters
persistent browser storage and nothing transfers across owners or accounts;
sign-out and identity changes route through the existing expiry boundary and
the reader's session-storage cleanup. The explicit Save button remains and
now participates in the deduplicated cycle. Rollback is source-only: revert
`ArtifactEditor.tsx`, delete `useArtifactAutosave.ts` with its test, and
restore `frontend/README.md`.

Known limits, documented rather than silently accepted: the debounced save is
in this tab only — another tab editing the same artifact is still the
conflict path, resolved explicitly as above; "Keep my edits" re-applies the
losing draft onto the reloaded revision and can conflict again if a third
write raced, in which case the banner reappears with the draft still
preserved; the offline retry waits for the next edit or timer rather than
listening to browser online events; and the restored-draft notice does not
diff the draft against the saved document — the student sees their restored
content directly in the editor.

**Next exact action:** ticket 17's dependency (15) has acceptance evidence.
The frontier now includes ticket 18 (preview and restore artifact versions,
blocked by 17), 20, 32, 35 and 37–40. Start exactly one fresh writer session
for
`.scratch/architecture-completion/issues/18-preview-and-restore-artifact-versions.md`
in this same checkout, preserving the dirty working tree.

### Ticket 16 complete — manage course-aligned artifact types (2026-11-24 SGT, OpenCode)

**Ticket 16 is implemented and locally verified.** Artifacts now carry a
course-aligned kind (general notes plus one type per Thinking Path stage) with
creation-time selection, and support rename, duplicate and confirmed delete
through generated contracts. The editor gains keyboard-accessible formatting —
paragraphs, two heading levels, emphasis, bulleted and numbered lists and
safe `http(s)` links — with truthful pressed states and local undo/redo.
Triage remains `ready-for-agent`; nothing is staged, committed or deployed.

Starting revision/branch: `improvement/architecture-responsiveness` with the
dirty ticket 01–15 working tree preserved unchanged apart from this ticket's
files.

#### New files and behavior

| File | Responsibility |
| --- | --- |
| `backend/persistence/store/migrations.py` | `migrate_student_artifact_kind` adds the `kind` column additively (`NOT NULL DEFAULT 'notes'`), so legacy artifacts become general notes in place. |
| `backend/persistence/store/sqlite_schema.py` + `backend/persistence/dsql_schema.py` | The `kind` column joins the canonical schema on both providers (additive, matching the existing DDL style). |
| `backend/persistence/store/operations/artifacts.py` | The `ARTIFACT_KINDS` allowlist gates creation; `duplicate` copies kind, title and canonical document to a new identity; `delete` requires an explicit confirmation and deletes exactly one owned row. |
| `backend/student_store.py` | Façade gains `create_artifact(kind)` and exposes `duplicate_artifact`/`delete_artifact`. |
| `backend/http/reader_artifacts.py` | `readerArtifacts` now returns the supported `kinds` list; create carries `kind`; two new operations `readerArtifactDuplicate` (POST …/duplicate, 201) and `readerArtifactDelete` (POST …/delete with a strict `{confirmed}` body) with typed error models; kind is part of every artifact projection. |
| `scripts/export_reader_openapi.py` | Allowlist extended from thirty to thirty-two operations. |
| `frontend/src/api.ts` + `frontend/src/api/client.ts` | `ARTIFACT_KINDS`, kind-aware `createArtifact`, and `duplicateArtifact`/`deleteArtifact` over the generated SDK. |
| `frontend/src/NotebookPage.tsx` | The Documents tab gains a creation type selector with curriculum-facing labels, per-document type labels, Duplicate (opens the copy) and Delete with an explicit confirm/cancel step; the list updates from the confirmed deletion without a whole-panel reload. |
| `frontend/src/ArtifactEditor.tsx` | Adds a keyboard-accessible toolbar (undo, redo, bold, italic, two heading levels, bulleted and numbered lists, safe-link address input with add/remove) with truthful `aria-pressed` states; the Link extension validates `http(s)` URLs and never opens links while editing; local undo/redo uses StarterKit history with native shortcuts. |
| `frontend/package.json` | Adds `@tiptap/extension-link@^3.35.0` (`npm audit --audit-level=high` clean). |
| `tests/persistence/test_student_artifacts.py` | New test: kind allowlist, duplicate exactness, unconfirmed-delete refusal → confirmed delete → other artifacts untouched. |
| `tests/http/test_reader_artifacts.py` + `tests/test_architecture_contracts.py` + `tests/http/test_security_readiness.py` | The lifecycle, second-owner and route-inventory coverage extends to kind, duplicate and delete (including the intruder sweep bodies carrying the required kind). |
| `frontend/src/api/client.test.ts` + `frontend/src/workspaceRoute.test.ts` | Create body now carries the kind; duplicate/delete transport covered through the route-inventory and component suites. |

#### Executed validation

| Command/check | Result |
| --- | --- |
| `pytest tests/persistence/test_student_artifacts.py tests/http/test_reader_artifacts.py tests/scripts/test_export_reader_openapi.py tests/test_architecture_contracts.py tests/http/test_security_readiness.py` | **80 passed** (red first: unsupported-kind rejection, missing-kind create 422, and the route inventory pin). |
| `npm test --prefix frontend` | **119 passed / 14 files**. |
| `npm run build --prefix frontend` | Exit 0 (`tsc --noEmit` + Vite production build). |
| `npm run api:check --prefix frontend` | Exit 0 — no schema or generated-client drift. |
| `npm audit --audit-level=high --prefix frontend` | Exit 0 with `@tiptap/extension-link`. |
| `npm run test:browser --prefix frontend` | **7 passed**. |
| `.venv/bin/ruff check .` | Exit 0. |
| `compileall` (backend, ui, streamlit_app, tests, scripts, agentcore_runtime) | Exit 0. |
| Full mock suite | **Exit 0 with 3,220 collected** — the 3,219 baseline plus this ticket's kinds/duplicate/delete test. Log: `/private/tmp/ticket16-pytest-full.log`. |
| Post-run leak check | No disposable-stack/uvicorn/playwright processes or listeners on ports 8121–8129. |

#### Compatibility, migration and rollback

The `kind` column migration is additive with a safe default (`notes`), so
every pre-existing artifact remains readable and editable without a data
rewrite; the DSQL DDL joins the admin-only bootstrap and never runs at
application startup. Duplicate/delete are new operations with explicit
ownership, confirmation and single-row effects; the delete plan already
covers the table. No existing route, payload or behavior changed except that
artifact create now requires a kind (its only caller is this ticket's UI).
Rollback is source-only: revert the schema/DDL, the two migrations, the
operations and façade methods, `reader_artifacts.py`, the allowlist and
regenerated client files, `client.ts`, `api.ts`, `NotebookPage.tsx`,
`ArtifactEditor.tsx`, `frontend/README.md`, `docs/DATABASE.md`, remove
`@tiptap/extension-link`, and restore the edited test files.

Known limits, documented rather than silently accepted: the kind list is
fixed by the server allowlist (adding a curriculum type is a one-line,
reviewed contract change, not a free-text field); duplication copies the
current saved document rather than unsaved editor state; deletion has no undo
beyond the duplicate workflow; checklists and tables remain deliberately
absent until an educational need is validated.

**Next exact action:** tickets 15 and 16 both have acceptance evidence. The
frontier now includes tickets 17 (autosave artifacts without losing
conflicting drafts, blocked by 15), 18 (preview and restore artifact versions,
blocked by 17), 20, 32, 35 and 37–40. Start exactly one fresh writer session
for
`.scratch/architecture-completion/issues/17-autosave-artifacts-without-losing-conflicting-drafts.md`
in this same checkout, preserving the dirty working tree.

### Ticket 15 complete — create and reopen a persistent student artifact (2026-11-24 SGT, OpenCode)

**Ticket 15 is implemented and locally verified.** Students can create, edit,
explicitly save and reopen one real Tiptap artifact through the routed editor
and generated owner-authorized API, with the document surviving a full backend
restart. Artifacts anchor to an owned notebook with stable identity, canonical
validated document JSON, schema version, revision-guarded saves, timestamps
and editor provenance. Triage remains `ready-for-agent`; nothing is staged,
committed or deployed.

**Anchoring decision (explicit):** artifacts are first-class children of an
owned notebook (`student_artifacts.notebook_id`, no free-floating documents) —
the same anchor semantics as sources and messages, so notebook deletion cleans
them through the existing child-delete plan and ownership follows the
notebook.

#### New files and behavior

| File | Responsibility |
| --- | --- |
| `backend/persistence/store/sqlite_schema.py` | Additive `student_artifacts` table (id, notebook_id, user_id, title, canonical `document_text`, `schema_version`, monotonic `revision`, `origin` provenance, timestamps) with notebook/updated index, and the table added to the notebook child-delete plan. |
| `backend/persistence/dsql_schema.py` | The same additive DDL in the admin bootstrap (DSQL dialect: no FKs, ASYNC index) and the child-table inventory — schema lifecycle stays owned by `scripts/init_dsql.py`, never at application startup. |
| `backend/persistence/store/migrations.py` | `migrate_student_artifacts` runs in the SQLite startup path (idempotent `CREATE TABLE IF NOT EXISTS`), so legacy pre-artifact databases upgrade in place with all existing rows untouched; rollback is a source-only revert. |
| `backend/persistence/store/operations/artifacts.py` | Repository contract: `canonical_artifact_document` (doc-root + content nodes, bounded depth ≤ 32 and serialized size ≤ 256 KiB, canonical JSON so stale-save comparison is exact), `create`/`get`/`list` (metadata only)/`update` with the revision guard (`ArtifactConflictError`) and ownership enforced in every statement. |
| `backend/persistence/store/operations/__init__.py` + `backend/student_store.py` | Binds the artifact operations and exposes `create_artifact`/`get_artifact`/`list_artifacts`/`update_artifact` on the store façade. |
| `backend/http/reader_artifacts.py` | Generated contracts: `GET/POST /api/v1/reader/threads/{thread_id}/artifacts` and `GET/PUT .../artifacts/{artifact_id}` with operation IDs `readerArtifacts`, `readerArtifactCreate`, `readerArtifact`, `readerArtifactUpdate`; typed error models (401/403/404, 409 stale save, 422 unsafe document); foreign or mismatched thread/artifact ids fail 404 without echoing other owners' work. |
| `scripts/export_reader_openapi.py` | Allowlist extended from twenty-six to thirty operations. |
| `frontend/openapi/reader.json` + `frontend/src/api/generated/*` | Re-exported offline and regenerated; `npm run api:check` reports no drift. |
| `frontend/src/api/client.ts` + `frontend/src/api.ts` | `readArtifacts`, `createArtifact`, `readArtifact`, `saveArtifact` over the generated SDK with the documented-defaults artifact adapter (a non-canonical document fails closed). |
| `frontend/src/workspaceRoute.ts` | New typed nested route `/notebooks/{folder}/artifacts/{artifact}` (+ `/pilot/…` alias); malformed or traversal-shaped identities render the public default. |
| `frontend/src/ArtifactEditor.tsx` | Real Tiptap (v3) editor: editable only after the verified load, one explicit save per action, the confirmed response reconciles, a 409 offers the server copy reload and never replays, ambiguous failures keep explicit recovery, and the title edit joins the same revision-guarded save. |
| `frontend/src/NotebookPage.tsx` + `frontend/src/App.tsx` | The notebook **Documents** tab lists saved artifacts (bounded metadata) and creates one through the generated contract; opening navigates the typed route owned by App. |
| `backend/http/notebook_reader.py` + `Caddyfile` + `Caddyfile.local` | The recognized view paths include the artifact editor route for both hosting prefixes. |
| `tests/persistence/test_student_artifacts.py` | Legacy in-place upgrade evidence (pre-artifact DB: rows untouched, table added, migration idempotent), ownership isolation across every operation, revision-guarded stale saves, canonical bounded document validation, and artifact cleanup through notebook deletion. |
| `tests/http/test_reader_artifacts.py` | Full lifecycle through the public HTTP seam including a real backend restart, stale 409, unsafe 422, same-origin enforcement with valid bodies, and foreign-owner 404s. |
| `tests/http/test_security_readiness.py` | The same-origin sweep now uses each route's real method (covering PUT) with a plausible body, the second-owner sweep covers the artifact list/create/update routes, and the sweep updated with the artifact routes. |
| `tests/test_architecture_contracts.py` | StudentStore public-contract inventory and the FastAPI route inventory extended. |
| `tests/http/test_notebook_reader.py` + `tests/test_deployment_config.py` | Deep-link and Caddy coverage for the artifact editor route. |
| `frontend/src/api/client.test.ts` + `frontend/src/workspaceRoute.test.ts` | Artifact transport tests (bodies/paths/status-only errors) and route parsing/round-trip coverage. |

**Security fix found by the seam (behavior change):** the same-origin sweep
caught that the origin policy required the Origin header only for POST — the
new PUT route would have accepted state-changing writes with no Origin header
(verified 200 before the fix). The reader guard now requires a matching Origin
for every state-changing method (`POST`, `PUT`, `PATCH`, `DELETE`); all
existing POST routes are unaffected and the security-readiness, workspace and
journey suites stay green.

#### Executed validation

| Command/check | Result |
| --- | --- |
| `pytest tests/persistence/test_student_artifacts.py tests/persistence/test_student_store.py tests/scripts/test_init_dsql.py` | 38 passed (storage, legacy upgrade, DSQL planning). |
| `pytest tests/http/test_reader_artifacts.py tests/scripts/test_export_reader_openapi.py` | 5 passed (red first: missing artifact schemas in the reviewed contract). |
| `pytest tests/http/test_security_readiness.py tests/test_architecture_contracts.py tests/http/test_reader_artifacts.py tests/scripts/test_export_reader_openapi.py tests/http/test_reader_workspace.py tests/http/test_notebook_reader.py tests/test_deployment_config.py` | **111 passed** after the origin fix (the first full run failed exactly the three stability pins listed above, including the genuine origin gap). |
| `npm test --prefix frontend` | **119 passed / 14 files** (113 before this ticket). |
| `npm run build --prefix frontend` | Exit 0 (`tsc --noEmit` + Vite production build). |
| `npm run api:check --prefix frontend` | Exit 0 — no schema or generated-client drift. |
| `npm audit --audit-level=high --prefix frontend` | Exit 0 with the new `@tiptap/react@^3.35.0` and `@tiptap/starter-kit@^3.35.0` dependencies. |
| `npm run test:browser --prefix frontend` | **7 passed**. |
| `.venv/bin/ruff check .` | Exit 0. |
| `compileall` (backend, ui, streamlit_app, tests, scripts, agentcore_runtime) | Exit 0. |
| Full mock suite | **Exit 0 with 3,219 collected** — the 3,211 baseline plus this ticket's eight new backend tests. Log: `/private/tmp/ticket15-pytest-full2.log`. |
| Post-run leak check | No disposable-stack/uvicorn/playwright processes or listeners on ports 8121–8129. |

#### Compatibility, migration and rollback

The migration is additive: the SQLite startup path creates `student_artifacts`
in place on legacy databases with every existing row untouched (proven by the
legacy-upgrade test), the DSQL DDL joins the admin-only bootstrap's
one-DDL-per-transaction plan and never runs at application startup, and no
existing table, route or payload changed. The origin-policy fix tightens
behavior for state-changing requests without Origin — previously only POST was
covered; no legitimate browser flow sends PUT/PATCH/DELETE cross-origin or
origin-less, and all existing suites pass. Rollback is source-only: revert the
schema/DDL/migration, the operations module and binding, `reader_artifacts.py`,
the allowlist and regenerated client files, `client.ts`, `api.ts`,
`workspaceRoute.ts`, `ArtifactEditor.tsx`, `NotebookPage.tsx`, `App.tsx`, both
Caddyfiles, `notebook_reader.py`, `frontend/README.md`, `docs/DATABASE.md`,
delete the new test files, and restore the three edited test files.

Known limits, documented rather than silently accepted: the editor saves are
whole-document replacements guarded by the revision (no concurrent
field-level merging — the 409 reload flow is the reconciliation); deletion and
version history belong to tickets 17–18; DSQL has no FK constraints by design,
so artifact cleanup relies on the same explicit child-delete plan as the other
notebook children; and the editor does not prefetch or autosave — saving is
always the student's explicit action, per this ticket's scope.

**Next exact action:** ticket 15's dependency (14) has acceptance evidence.
The frontier now includes tickets 16 (manage course-aligned artifact types,
blocked by 15), 17 (autosave artifacts, blocked by 15), 20, 32, 35 and 37–40.
Start exactly one fresh writer session for
`.scratch/architecture-completion/issues/16-manage-course-aligned-artifact-types.md`
in this same checkout, preserving the dirty working tree.

### Ticket 14 complete — navigate existing workspaces through URLs (2026-11-24 SGT, OpenCode)

**Ticket 14 is implemented and locally verified.** The existing student views
now have typed URLs — `/` (home), `/chats/{thread}`, `/notebooks/{folder}`,
`/library`, `/search`, `/settings`, with the `/pilot/…` hosting alias rendering
the same views — through TanStack Router, with working direct links, refresh
and browser back/forward. The app's existing open flow remains the single
navigation loader, and the server and Caddy serve the SPA shell only for these
recognized paths. Triage remains `ready-for-agent`; nothing is staged,
committed or deployed.

Starting revision/branch: `improvement/architecture-responsiveness` with the
dirty ticket 01–13 working tree preserved unchanged apart from this ticket's
files.

#### New files and behavior

| File | Responsibility |
| --- | --- |
| `frontend/package.json` + lockfile | Adds `@tanstack/react-router@^1.170.46` (runtime dependency, installed with `--ignore-scripts`; `npm audit --audit-level=high` reports 0 vulnerabilities). |
| `frontend/src/workspaceRoute.ts` | Typed route tree (`createRouter` + browser history) with one builder/parser per view; the `/pilot` hosting alias is parsed into the same views; malformed or traversal-shaped identities and unrecognized paths render the public default; `openWorkspaceRoute` ignores same-path pushes, preserves the hosting prefix, and supports replace; `useWorkspaceRoute` subscribes the app to every URL change including back/forward. There is deliberately no data loader in the router: the app's existing open flow stays the single navigation truth and nothing prefetches before the verified bootstrap. |
| `frontend/src/App.tsx` | The view state and folder selection derive from the typed URL; every navigation function (home, chat, folder, library, search, settings, created workspaces) pushes a typed route; back/forward and refresh resolve through the same open flow. The session-storage selected-thread key is retired (the URL is the truth); composer drafts keep their owner-scoped session-storage lifecycle. A deep link to a foreign, deleted or expired thread shows no private data and returns to the default view via the existing epoch-fenced open. |
| `backend/http/notebook_reader.py` | Recognized view paths (`/library`, `/search`, `/settings`, `/chats/{thread_id}`, `/notebooks/{folder_id}` and their `/pilot/…` aliases) serve the SPA shell through the exact `browser_home` policy (streamlit redirect for lecturers, cookie-renewal redirect, `no-store`, `Vary: Cookie`). Unknown paths stay hard 404s and no API route is shadowed. |
| `Caddyfile` + `Caddyfile.local` | A `@student_views` matcher forwards only the recognized view paths to the app before the final 404; every API allowlist is unchanged. |
| `tests/http/test_notebook_reader.py` | New deep-link test: all recognized paths (both hosting prefixes) serve the shell with `no-store`/`Vary: Cookie` and no tokens in the HTML; unrecognized paths, extra segments and `/pilot/unknown` stay 404; the SPA fallback never swallows real API routes (`/api/v1/reader/session` stays 401). |
| `tests/test_deployment_config.py` | New edge test: both Caddyfiles forward exactly the recognized view paths with no wildcard API expansion. |
| `frontend/src/workspaceRoute.test.ts` | 7 router tests: every view and the hosting alias parse; unknown/malformed/traversal paths render the public default; identity round-trips; same-path pushes are ignored; simulated popstate traversals resolve exactly (jsdom cannot traverse natively — real traversal is covered by the browser slice in Chromium). |

#### Executed validation

| Command/check | Result |
| --- | --- |
| `pytest tests/http/test_notebook_reader.py tests/test_deployment_config.py tests/http/test_security_readiness.py` | 73 passed (red first: the missing view paths in both Caddyfiles). |
| `caddy validate --config Caddyfile` | Valid configuration. |
| `npm test --prefix frontend` | **113 passed / 14 files** (106 before this ticket). |
| `npm run build --prefix frontend` | Exit 0 (`tsc --noEmit` + Vite production build). |
| `npm run api:check --prefix frontend` | Exit 0 — no schema or generated-client drift. |
| `npm audit --audit-level=high --prefix frontend` | Exit 0, 0 vulnerabilities with the new dependency. |
| `npm run test:browser --prefix frontend` | **7 passed** — real Chromium navigation over the typed URLs. |
| `.venv/bin/ruff check .` | Exit 0. |
| `compileall` (backend, ui, streamlit_app, tests, scripts, agentcore_runtime) | Exit 0. |
| Full mock suite | **Exit 0 with 3,213 collected** — the 3,211 baseline plus this ticket's two new tests. Log: `/private/tmp/ticket14-pytest-full.log`. |
| Post-run leak check | No disposable-stack/uvicorn/playwright processes or listeners on ports 8121–8129. |

#### Compatibility, rollback, risks and next exact action

No schema, saved-data or API contract change: the recognized view paths are
additive GETs serving the same shell as `/`, every existing route keeps its
path, and the Caddy change only converts hard 404s into shell responses for
the recognized view paths. The retired session-storage selected key is
navigation-only state; composer drafts, review choices and check-in notes keep
their storage and restore behavior. Expired or foreign links render the public
shell and fail closed through the existing identity checks. Rollback is
source-only: revert `notebook_reader.py`, both Caddyfiles, `App.tsx`,
`frontend/README.md`, delete `workspaceRoute.ts` with its test, remove the
router dependency from `package.json`/lockfile, and restore the two edited
test files.

Known limits, documented rather than silently accepted: the settings surface
keeps its explicit return-route button alongside browser Back (both resolve
through the same typed routes); jsdom cannot execute native history
traversal, so back/forward is unit-tested through simulated popstate and
verified end-to-end in the Chromium browser slice; deep links never prefetch —
the first open happens after the verified bootstrap, which keeps one extra
bounded read compared with a speculative router loader but preserves the
identity-first ordering the seam requires.

**Next exact action:** tickets 6, 9 and 14 all have acceptance evidence. The
frontier now includes tickets 15 (create and reopen a persistent student
artifact, blocked by 14), 20 (persistent Design Canvas, blocked by 14), 32, 35
and 37–40. Start exactly one fresh writer session for
`.scratch/architecture-completion/issues/15-create-and-reopen-a-persistent-student-artifact.md`
in this same checkout, preserving the dirty working tree.

### Ticket 13 complete — read reviews, briefs and existing exports through typed resources (2026-11-24 SGT, OpenCode)

**Ticket 13 is implemented and locally verified.** The explicit whole-chat brief
request now runs through a reviewed generated contract, reading cached review
and brief state never starts generation implicitly, and every remaining
custom adapter (multipart submits, binary downloads, share and the coach-turn
NDJSON lifecycle) is documented as a deliberate binary/streaming exception
with its owner-verification, cancellation and no-store policy intact. Review
and brief content themselves were already typed through the ticket 12 project
projection. Triage remains `ready-for-agent`; nothing is staged, committed or
deployed.

Starting revision/branch: `improvement/architecture-responsiveness` with the
dirty ticket 01–12 working tree preserved unchanged apart from this ticket's
files.

#### New files and behavior

| File | Responsibility |
| --- | --- |
| `backend/http/notebook_reader.py` | The brief route gains operation ID `readerProjectBrief` with typed error models covering its real 401/403/404 conflicts, 429 rate limit and 503 provider-unavailable responses. No route path, payload, generation admission or persistence behavior changed. |
| `scripts/export_reader_openapi.py` | Allowlist extended from twenty-five to twenty-six operations. |
| `frontend/openapi/reader.json` + `frontend/src/api/generated/*` | Re-exported offline and regenerated; `npm run api:check` reports no drift. |
| `frontend/src/api/client.ts` | `requestProjectBrief(thread, retry, signal)` over the generated SDK with the same-origin/`no-store`/AbortSignal/status-only-error policy; the shared `briefView` adapter now materializes the documented brief defaults for both this operation and the project projection. |
| `frontend/src/ProjectBrief.tsx` | The explicit Summarise action writes through the generated contract; reading cached state never fetches; the existing version fencing, concurrent-turn invalidation, honest failure states and explicit-retry requirement are unchanged. |
| `tests/scripts/test_export_reader_openapi.py` | Schema inventory extended (`ReaderBriefRequest`). |
| `frontend/src/api/client.test.ts` | 2 new brief transport tests: the explicit `{retry}` body and path with envelope defaults, and 401/403/404/429/503 status-only errors. |
| `frontend/src/ProjectBrief.test.tsx` | New jsdom component tests on the real card: reading cached state issues no request, the explicit button issues exactly one generated POST with `{retry: false}` and reconciles the version-fenced result, and a 503 failure stays honest and requires an explicit `{retry: true}` retry. |
| `frontend/README.md` | Documents the brief contract and every deliberate binary/streaming exception (multipart submits, `nosniff` binary downloads, share, coach-turn NDJSON) with their owner-verification, cancellation and no-store policy. |

#### Executed validation

| Command/check | Result |
| --- | --- |
| `pytest tests/scripts/test_export_reader_openapi.py` | 3 passed (red first: missing `ReaderBriefRequest` schema). |
| `npm test --prefix frontend` | **106 passed / 13 files** (97 before this ticket). |
| `npm run build --prefix frontend` | Exit 0 (`tsc --noEmit` + Vite production build). |
| `npm run api:check --prefix frontend` | Exit 0 — no schema or generated-client drift. |
| `npm run test:browser --prefix frontend` | **7 passed**. |
| `.venv/bin/ruff check .` | Exit 0. |
| `compileall` (backend, ui, streamlit_app, tests, scripts, agentcore_runtime) | Exit 0. |
| Full mock suite | **Exit 0 with 3,211 collected** — the ticket 09–12 baseline. Log: `/private/tmp/ticket13-pytest-full.log`. |
| Post-run leak check | No disposable-stack/uvicorn/playwright processes or listeners on ports 8121–8129. |

#### Compatibility, rollback, risks and next exact action

No schema, saved-data or existing-API change: the brief route keeps its path,
payload and response; only OpenAPI metadata was added. Generation admission,
rate limits, unavailable/failure states and the mock-mode "summary
unavailable" honesty are unchanged and covered by the existing brief and
journey tests. Binary and streaming adapters retain owner verification,
cancellation, `no-store`, saved receipts and existing export contents; no
professor/admin endpoint entered the browser contract. Nothing enters
persistent browser storage. Rollback is source-only: revert `notebook_reader.py`,
the export allowlist, `reader.json`, regenerated client files, `client.ts`,
`ProjectBrief.tsx`, `frontend/README.md`, delete `ProjectBrief.test.tsx`, and
restore the two edited test files.

Known limits, documented rather than silently accepted: the brief response is
still the whole-chat generation trigger through the same bounded coordinator
path — mock and unavailable states are projected honestly rather than retried
automatically. The transcript export remains a binary exception by design; a
typed export-metadata resource would need a new reviewed operation and is not
implied by this ticket.

**Next exact action:** ticket 13's dependency is satisfied. Ticket 14
(navigate existing workspaces through URLs, blocked by 6 and 9, both complete)
is now eligible together with 35 and 37–40. Start exactly one fresh writer
session for
`.scratch/architecture-completion/issues/14-navigate-existing-workspaces-through-urls.md`
in this same checkout, preserving the dirty working tree.

### Ticket 12 complete — read and confirm Thinking Path progress through typed resources (2026-11-24 SGT, OpenCode)

**Ticket 12 is implemented and locally verified.** The project projection read,
the explicit transition decision and the explicit stage selection now run
through reviewed generated contracts, and each verified workspace open read and
confirmed decision reconciles the owner-fenced, revision-aware project Query
resource. A stage recommendation alone still awards nothing — only the explicit
decision writes through the existing atomic transition services. Triage remains
`ready-for-agent`; nothing is staged, committed or deployed.

Starting revision/branch: `improvement/architecture-responsiveness` with the
dirty ticket 01–11 working tree preserved unchanged apart from this ticket's
files.

#### New files and behavior

| File | Responsibility |
| --- | --- |
| `backend/http/notebook_reader.py` | Adds operation IDs `readerProject`, `readerProjectResolve`, `readerProjectSelect` with typed error models (resolve/select document their real 409 conflict responses). No route path, payload, ownership, stage-authority or persistence behavior changed. |
| `scripts/export_reader_openapi.py` | Allowlist extended from twenty-two to twenty-five operations; red observed through the fail-closed exporter before the backend change. |
| `frontend/openapi/reader.json` + `frontend/src/api/generated/*` | Re-exported offline and regenerated; `npm run api:check` reports no drift. |
| `frontend/src/api/queryKeys.ts` | Adds `project(owner, thread)` under the verified-owner root. |
| `frontend/src/api/client.ts` | `readProject`, `resolveTransition` and `selectStage` over the generated SDK — same-origin cookies, `no-store`, `AbortSignal`, status-only errors, and the ticket 09 documented-defaults project adapter. |
| `frontend/src/api/workspaceProject.ts` | New owner-fenced, revision-aware resource: `fetchConfirmedProject` rejects any answer for another owner or notebook; `projectPolicies` keep reads immediately stale (every read re-verifies saved stage authority) while the last confirmed projection stays in memory with a 5-minute gc solely as the reconciliation target; `seedProject` (workspace open seed) and `reconcileProject` (cancels superseded reads, then writes the confirmed decision so a late pre-write response can never roll it back; never writes into another owner's resource). |
| `frontend/src/useReader.ts` | The verified workspace open read seeds the project resource; loading earlier pages reads the project through the generated contract instead of a raw `get`. |
| `frontend/src/Conversation.tsx` | `stageAction` writes decisions through the generated contracts, reconciles the confirmed projection into the resource, and keeps the existing flow: the authoritative refresh still updates the view and milestone banner, ambiguous network failures keep the distinct "Could not verify" recovery, definitive 409s keep "no longer available. Saved project refreshed.", and decisions are never automatically replayed. |
| `frontend/src/HomeView.tsx` | The home card reads and resolves through the generated contracts with the same lock rules, no replay and re-read-either-way reconciliation. |
| `tests/scripts/test_export_reader_openapi.py` | Schema inventory extended (`ReaderDecision`, `ReaderSelection`). |
| `frontend/src/api/client.test.ts` | 3 new project transport tests: fenced read with cookie/cancellation policy, decision and stage-selection bodies/paths, 401/403/404/409 status-only errors. |
| `frontend/src/api/workspaceProject.test.ts` | New resource tests: immediate-stale/positive-gc policy, owner-and-thread rejection, confirmed-decision reconciliation with superseded-read cancellation, and never writing into another owner's resource. |

#### Executed validation

| Command/check | Result |
| --- | --- |
| `pytest tests/scripts/test_export_reader_openapi.py tests/test_architecture_contracts.py tests/http/test_reader_workspace.py` | 20 passed (red first through the fail-closed exporter). |
| `npm test --prefix frontend` | **97 passed / 12 files** (87 before this ticket). |
| `npm run build --prefix frontend` | Exit 0 (`tsc --noEmit` + Vite production build). |
| `npm run api:check --prefix frontend` | First run exit 1: the installed generator bundle again emitted numbered duplicate copies (documented ticket 06/08 pattern; copies deleted, never copied into source). Repaired with `npm ci --ignore-scripts` from the unchanged lockfile (run inside `frontend/`); `api:check` then exit 0. |
| `npm run test:browser --prefix frontend` | **7 passed**. |
| `.venv/bin/ruff check .` | Exit 0. |
| `compileall` (backend, ui, streamlit_app, tests, scripts, agentcore_runtime) | Exit 0. |
| Full mock suite | **Exit 0 with 3,211 collected** — the ticket 09/10/11 baseline. Log: `/private/tmp/ticket12-pytest-full.log`. |
| Post-run leak check | No disposable-stack/uvicorn/playwright processes or listeners on ports 8121–8129. |

#### Compatibility, rollback, risks and next exact action

No schema, saved-data or existing-API change: the three routes keep their
paths, payloads and responses; only OpenAPI metadata was added. Stage authority
remains entirely server-side — recommendations never award completion, and the
existing atomic transition apply, stale/repeated-decision 409 semantics,
completed-stage revisits and terminal Reflection behavior are covered by the
unchanged learning-service and journey tests. The project resource holds the
last confirmed projection in memory only; reads are never served from cache;
nothing enters persistent browser storage; no decision is applied optimistically.
Rollback is source-only: revert `notebook_reader.py`, the export allowlist,
`reader.json`, regenerated client files, `client.ts`, `queryKeys.ts`,
`useReader.ts`, `Conversation.tsx`, `HomeView.tsx`, delete `workspaceProject.ts`
with its test, and restore the two edited test files.

Known limits, documented rather than silently accepted: the project resource
does not live-sync across same-owner tabs — it reconciles on the next open,
decision or identity reset, matching the documented settings/sources/bookmarks
behavior. The project-brief generation trigger remains a specialized adapter
until ticket 13's brief contract, and the home card's resolved-state message
now distinguishes a definitive 409 from a lost response explicitly.

**Next exact action:** ticket 12's dependency is satisfied. The frontier now
includes tickets 13, 14 (blocked by 6 and 9, both complete), 35 and 37–40.
Start exactly one fresh writer session for
`.scratch/architecture-completion/issues/13-read-reviews-briefs-and-existing-exports-through-typed-resources.md`
in this same checkout, preserving the dirty working tree.

### Ticket 11 complete — keep My Work synchronized with message bookmarks (2026-11-24 SGT, OpenCode)

**Ticket 11 is implemented and locally verified.** The bookmark projection read
and the message-star write now run through reviewed generated contracts, and
both the ticket 09 workspace seed and every explicit star reconciliation write
the owner-fenced, revision-aware bookmarks Query resource. Stage grouping,
superseded-read exclusion, append-only edit semantics and the no-replay
recovery are unchanged. Triage remains `ready-for-agent`; nothing is staged,
committed or deployed.

Starting revision/branch: `improvement/architecture-responsiveness` with the
dirty ticket 01–10 working tree preserved unchanged apart from this ticket's
files.

#### New files and behavior

| File | Responsibility |
| --- | --- |
| `backend/http/notebook_reader.py` | The bookmarks read keeps its `readerBookmarks` operation ID and gains typed 401/403/404 error models; the star write gains operation ID `readerStar` with the same typed error models. No route path, payload, ownership or persistence behavior changed. |
| `scripts/export_reader_openapi.py` | Allowlist extended from twenty to twenty-two operations. |
| `frontend/openapi/reader.json` + `frontend/src/api/generated/*` | Re-exported offline and regenerated; `npm run api:check` reports no drift. |
| `frontend/src/api/client.ts` | `readBookmarks` and `setStar` over the generated SDK — same-origin cookies, `no-store`, `AbortSignal`, status-only errors. |
| `frontend/src/api/queryKeys.ts` | Adds `bookmarks(owner, thread)` under the verified-owner root. |
| `frontend/src/api/workspaceBookmarks.ts` | New owner-fenced, revision-aware resource: `fetchConfirmedBookmarks` rejects any answer for another owner or notebook; `bookmarksPolicies` keep reads immediately stale (every read re-verifies against the live conversation revision) while the last confirmed projection stays in memory with a 5-minute gc solely as the reconciliation target; `seedBookmarks` (workspace open seed) and `reconcileBookmarks` (cancels superseded reads, then writes the confirmed projection so a late pre-write response can never roll it back; never writes into another owner's resource). |
| `frontend/src/useReader.ts` | The verified workspace open read now seeds the bookmarks resource alongside the settings resource. |
| `frontend/src/Conversation.tsx` | `readBookmarks` runs through the generated read, keeps the read-epoch fencing and the live-revision check (superseded reads never apply), and reconciles the confirmed projection into the resource; `star` writes through the generated contract, still reconciles by the explicit revision-fenced read rather than replaying a lost write, and a definitive non-401/403 failure keeps the existing "Star was not saved" recovery because the read decides. Stage grouping and the page's starred fallback are unchanged. |
| `tests/scripts/test_export_reader_openapi.py` | Schema inventory extended (`ReaderBookmarks`, `ReaderBookmark`, `ReaderStar`). |
| `frontend/src/api/client.test.ts` | 3 new bookmark transport tests: fenced read with cookie/cancellation policy, star body and path, 401/403/404 status-only errors. |
| `frontend/src/api/workspaceBookmarks.test.ts` | New resource tests: immediate-stale/positive-gc policy, owner-and-thread rejection, confirmed-projection reconciliation with superseded-read cancellation, and never writing into another owner's resource. |

#### Executed validation

| Command/check | Result |
| --- | --- |
| `pytest tests/scripts/test_export_reader_openapi.py tests/test_architecture_contracts.py` | 12 passed (red first: missing `ReaderBookmarks`/`ReaderStar` schemas). |
| `npm test --prefix frontend` | **87 passed / 11 files** (78 before this ticket). |
| `npm run build --prefix frontend` | Exit 0 (`tsc --noEmit` + Vite production build). |
| `npm run api:check --prefix frontend` | Exit 0 — no schema or generated-client drift. |
| `npm run test:browser --prefix frontend` | **7 passed**. |
| `.venv/bin/ruff check .` | Exit 0. |
| `compileall` (backend, ui, streamlit_app, tests, scripts, agentcore_runtime) | Exit 0. |
| Full mock suite | **Exit 0 with 3,211 collected** — the ticket 09/10 baseline; this ticket changed contract metadata and the export inventory only. Log: `/private/tmp/ticket11-pytest-full.log`. |
| Post-run leak check | No disposable-stack/uvicorn/playwright processes or listeners on ports 8121–8129. |

#### Compatibility, rollback, risks and next exact action

No schema, saved-data or existing-API change: the two routes keep their paths,
payloads and responses; only OpenAPI metadata was added. Slow reads, ambiguous
writes, reload/restart and account switches keep their existing recovery: the
star write is still followed by an explicit revision-fenced read that decides
the reported outcome, the applied-seed rule never clobbers newer local
reconciliation, and My Work's stage grouping comes from the same server
projection. No optimistic learning change exists — stars carry no stage
authority. Reads stay immediately stale; nothing enters persistent browser
storage. Rollback is source-only: revert `notebook_reader.py`, the export
allowlist, `reader.json`, regenerated client files, `client.ts`, `queryKeys.ts`,
`useReader.ts`, `Conversation.tsx`, delete `workspaceBookmarks.ts` with its
test, and restore the two edited test files.

Known limits, documented rather than silently accepted: the bookmarks resource
does not live-sync across same-owner tabs — it reconciles on the next open,
star action or identity reset, matching the documented settings and sources
behavior. The transcript page's per-message `starred` fallback keeps its
existing semantics; only the bookmark projection is authoritative for My Work.

**Next exact action:** ticket 11's dependency is satisfied. The frontier now
includes tickets 12–14, 35 and 37–40. Start exactly one fresh writer session
for
`.scratch/architecture-completion/issues/12-read-and-confirm-thinking-path-progress-through-typed-resources.md`
in this same checkout, preserving the dirty working tree.

### Ticket 10 complete — manage sources through typed confirmed resources (2026-11-24 SGT, OpenCode)

**Ticket 10 is implemented and locally verified.** Source catalog, preview,
upload receipts, selection, Library linking, detachment and confirmed Library
deletion, and upload retry/discard now run through reviewed generated contracts
with stable operation IDs, and each confirmed catalog response reconciles the
owner-fenced sources Query resource before the existing authoritative refresh.
Multipart upload submission, composer attachments and binary downloads keep
their specialized browser adapters by design. Triage remains
`ready-for-agent`; nothing is staged, committed or deployed.

Starting revision/branch: `improvement/architecture-responsiveness` with the
dirty ticket 01–09 working tree preserved unchanged apart from this ticket's
files.

#### New files and behavior

| File | Responsibility |
| --- | --- |
| `backend/http/reader_sources.py` | Adds stable operation IDs `readerSources`, `readerSource`, `readerSourceSelect`, `readerSourceLink`, `readerSourceRemove`, `readerUploads`, `readerUploadRetry`, `readerUploadDiscard` with typed error models (select/link/remove/retry/discard additionally document their real 409 conflict responses). No route path, payload, ownership, queue or persistence behavior changed. Multipart submit, attachments and binary content downloads stay outside the browser contract by design. |
| `scripts/export_reader_openapi.py` | Allowlist extended from twelve to twenty operations; still fails closed on missing/untyped operations. |
| `frontend/openapi/reader.json` + `frontend/src/api/generated/*` | Re-exported offline and regenerated; `npm run api:check` reports no drift; the generator bundle stayed clean. |
| `frontend/src/api.ts` | Adds the shared `Source`, `SourceList`, `SourceDetail`, `UploadJob` and `UploadJobs` view types. |
| `frontend/src/api/queryKeys.ts` | Adds `sources(owner, thread)` and `uploads(owner, thread)` under the verified-owner root. |
| `frontend/src/api/client.ts` | `readSources`, `readSourceDetail`, `readUploads`, `setSourceSelected`, `linkLibrarySource`, `removeSource` (confirmation body only for Library deletion), `retryUpload` and `discardUpload` over the generated SDK — same-origin cookies, `no-store`, `AbortSignal`, status-only errors. |
| `frontend/src/api/workspaceSources.ts` | New owner-fenced resources: `fetchConfirmedSources`/`fetchConfirmedUploads` reject any answer for another owner or notebook; `sourcesPolicies` keep reads immediately stale (every read verifies against the server, and receipts change between polls) while the last confirmed data stays in memory with a 5-minute gc solely as the reconciliation target; `seedSources`/`seedUploads` and `reconcileSources` (cancels superseded reads, then writes the confirmed catalog so a late pre-write response can never roll it back; never writes into another owner's resource). |
| `frontend/src/Sources.tsx` | Reads and JSON mutations go through the generated contracts inside the existing write frame: ambiguous-write recovery (`unverified` state, explicit refresh, no automatic replay), upload polling, receipt retry/discard, upload-form close-on-accept and all notices are preserved. A confirmed select/link/remove response reconciles the sources resource and local surface immediately before the authoritative refresh; uploads submission keeps its multipart adapter; downloads keep their binary adapter. The component's catalog type is now the shared view type. |
| `tests/scripts/test_export_reader_openapi.py` | Schema inventory extended (`ReaderSources`, `ReaderSource`, `ReaderSourceSelection`, `ReaderLibraryDelete`, `ReaderSourceDetail`, `ReaderUploads`, `ReaderUpload`). |
| `frontend/src/api/client.test.ts` | 5 new source transport tests: catalog/preview/receipt reads, select/link/confirmed-remove bodies and paths, no-body notebook detachment, retry/discard receipts, and 401/403/404/409 status-only errors. |
| `frontend/src/api/workspaceSources.test.ts` | New resource tests: immediate-stale/positive-gc policy, owner-and-thread rejection for catalog and receipts, confirmed-catalog reconciliation with superseded-read cancellation, and never writing into another owner's resource. |
| `frontend/src/Sources.test.tsx` | New jsdom component test: the real embedded Sources surface reads through the generated contracts, saves a selection with exactly one generated POST, reconciles the confirmed catalog into the Query resource and renders the saved selection. |

#### Executed validation

| Command/check | Result |
| --- | --- |
| `pytest tests/scripts/test_export_reader_openapi.py tests/http/test_reader_workspace.py` | 11 passed (red first: missing source schemas in the reviewed contract). |
| `npm test --prefix frontend` | **78 passed / 10 files** (65 before this ticket). |
| `npm run build --prefix frontend` | Exit 0 (`tsc --noEmit` + Vite production build). |
| `npm run api:check --prefix frontend` | Exit 0 — no schema or generated-client drift. |
| `npm run test:browser --prefix frontend` | **7 passed**. |
| `.venv/bin/ruff check .` | Exit 0. |
| `compileall` (backend, ui, streamlit_app, tests, scripts, agentcore_runtime) | Exit 0. |
| Full mock suite | **Exit 0 with 3,211 collected** — the ticket 09 baseline; this ticket changed contract metadata and one export test's inventory only. Log: `/private/tmp/ticket10-pytest-full.log`. |
| Post-run leak check | No disposable-stack/uvicorn/playwright processes or listeners on ports 8121–8129. |

#### Compatibility, rollback, risks and next exact action

No schema, saved-data or existing-API change: the eight source routes keep
their paths, payloads and responses; only OpenAPI metadata was added, which is
additive for every existing caller. The Streamlit entrypoint, `api_client.py`,
upload coordinator and all other backend routes are untouched; citation
mapping (`test_citation_resolution`) and second-owner sweeps
(`test_security_readiness`, now including these contracts' conflict codes)
stay green through the full suite. Source mutations still run through the same
`set_library_link`/library-delete services, so selection changes affect only
future authorized context. Reads stay immediately stale; nothing enters
persistent browser storage. Rollback is source-only: revert
`reader_sources.py`, the export allowlist, `reader.json`, regenerated client
files, `client.ts`, `api.ts`, `queryKeys.ts`, `Sources.tsx`, delete
`workspaceSources.ts` with its test and `Sources.test.tsx`, and restore the
two edited test files.

Known limits, documented rather than silently accepted: the sources resource
is a reconciliation target written by confirmed responses and explicit
refreshes — it does not live-sync across same-owner tabs (same documented
behavior as settings and the notebooks listing). Upload receipts keep their
component-level polling loop rather than a Query subscription; the resource
records the last confirmed receipt set for reconciliation and future tickets
can move polling onto it if measurement justifies that. `retryUpload`/
`discardUpload` preserve the existing `dict[str, bool]` response contract
rather than introducing a typed model, matching the minimal contract change
rule; typing them belongs to a later contract pass if any browser consumer
needs it.

**Next exact action:** ticket 10's dependency is satisfied. The frontier now
includes tickets 11–13, 14 (navigate existing workspaces through URLs, blocked
by 6 and 9, both complete), 35 and 37–40. Start exactly one fresh writer
session for
`.scratch/architecture-completion/issues/11-keep-my-work-synchronized-with-message-bookmarks.md`
or another approved frontier ticket in this same checkout, preserving the
dirty working tree.

### Ticket 09 complete — open an aggregated, verified workspace (2026-11-24 SGT, OpenCode)

**Ticket 09 is implemented and locally verified.** Opening or refreshing a chat
now uses one bounded owner-consistent workspace read (initial message page and
revision, project/Thinking Path, bookmarks, notebook settings and bounded
counts) followed by the existing identity probe, and the verified response
seeds the settings Query resource and the sidebar's bookmark state so no
component refetches immediately. Triage remains `ready-for-agent`; nothing is
staged, committed or deployed.

Starting revision/branch: `improvement/architecture-responsiveness` with the
dirty ticket 01–08 working tree preserved unchanged apart from this ticket's
files.

#### New files and behavior

| File | Responsibility |
| --- | --- |
| `backend/http/notebook_reader.py` | Adds `ReaderThreadWorkspace` (owner-fenced aggregation of `ReaderPage`, `ReaderProject`, `ReaderBookmarks`, `ReaderNotebookSettings`) and `GET /api/v1/reader/threads/{thread_id}/workspace` with operation ID `readerThreadWorkspace` and typed 401/403/404 error models. The message-page, bookmarks and project route bodies moved into shared module-level projections (`reader_page_view`, `reader_bookmarks_view`, `reader_project_view`) with unchanged route paths, payloads and responses. The aggregated read reuses the existing services with a constant number of owner-scoped queries (no per-message N+1); bounded counts inside the included projections are the availability indicators, and full sources, unbounded history and version histories stay excluded. It is an owner-consistent collection, not a transactional snapshot. |
| `scripts/export_reader_openapi.py` | Allowlist extended from eleven to twelve operations. |
| `frontend/openapi/reader.json` + `frontend/src/api/generated/*` | Re-exported offline and regenerated; `npm run api:check` reports no drift and the generator bundle stayed clean after ticket 08's `npm ci` repair. |
| `frontend/src/api/client.ts` | `readThreadWorkspace` over the generated SDK with the same-origin/`no-store`/AbortSignal/status-only-error policy; extracted shared page/project adapters (`pageView`, `projectView`) that materialize documented server defaults for stages, project-brief points and message fields; `readMessagePage` reuses the page adapter. |
| `frontend/src/api.ts` | Adds the `ThreadWorkspace` view type. |
| `frontend/src/api/workspaceSettings.ts` | Adds `notebookSettingsQueryOptions` and `seedNotebookSettings` (cache entry built with the resource's measured 30 s freshness) so a verified workspace read satisfies the settings surface without an immediate refetch; `useNotebookSettings` now consumes the shared options. |
| `frontend/src/useReader.ts` | `open()` initial and refresh paths issue one workspace read (loading earlier pages keeps the revision-bound pagination lifecycle); the response is fenced against the verified owner, page/project/bookmarks/settings thread identities before anything is applied, then seeds the settings resource and carries the bookmarks projection in reader state. The session probe, epoch/abort fencing, target-following pagination and keep-window refresh semantics are unchanged. |
| `frontend/src/App.tsx` | Passes the reader's bookmarks projection to `Conversation` as `seededBookmarks`. |
| `frontend/src/Conversation.tsx` | Consumes the verified seed: when it matches this thread and revision the bookmarks state is seeded with no read; a mismatch falls back to the existing revision-fenced bookmarks read. The applied-seed ref never clobbers newer local reconciliation (for example an explicit star re-read within the same revision); star, jump and refresh flows are unchanged. |
| `tests/test_architecture_contracts.py` | Route inventory extended with the new route (red observed in the full suite before the update). |
| `tests/scripts/test_export_reader_openapi.py` | Schema inventory extended with the twelve newly reachable public models. |
| `tests/http/test_reader_workspace.py` | New behavior test: the workspace read equals the messages/page route output, is bounded (20 of 25 messages), contains the starred bookmark identity, settings and project identities, no `sources`/`transcript` keys, and rejects anonymous (401), staff (403), foreign-owner and unknown threads (404). |
| `tests/http/test_security_readiness.py` | The every-route second-owner sweep now includes the workspace read. |
| `frontend/src/api/client.test.ts` | Workspace transport test: path encoding, cookie policy, bookmark identity and adapter defaults. |
| `frontend/src/api/workspaceSettings.test.ts` | Seeded settings resource reuse with zero immediate refetch. |
| `frontend/src/useReader.test.tsx` | New measured request-count test: bootstrap/open/switch/revisit issue exactly one workspace read plus the identity probe per open, with zero bookmarks or settings component fetches, and the settings resource is seeded from the verified response. |

#### Executed validation

| Command/check | Result |
| --- | --- |
| `pytest tests/scripts/test_export_reader_openapi.py tests/http/test_reader_workspace.py tests/http/test_reader_bootstrap.py tests/http/test_reader_conversation.py tests/http/test_student_journey_readiness.py` | 28 passed (red first: workspace route 404 and missing `ReaderThreadWorkspace` schema). |
| `pytest tests/http/test_security_readiness.py` | 61 passed — the second-owner sweep covers the new route. |
| `pytest tests/test_architecture_contracts.py` | 9 passed (red first in the full suite: the stable route inventory rejected the unlisted route; the update is part of this ticket's contract change). |
| `npm test --prefix frontend` | **65 passed / 8 files** (62 before this ticket). |
| `npm run build --prefix frontend` | Exit 0 (`tsc --noEmit` + Vite production build). |
| `npm run api:check --prefix frontend` | Exit 0 — no schema or generated-client drift. |
| `npm run test:browser --prefix frontend` | **7 passed** — composed open journeys over the aggregated read. |
| `.venv/bin/ruff check .` | Exit 0 (one extraneous f-prefix in the new test fixed). |
| `compileall` (backend, ui, streamlit_app, tests, scripts, agentcore_runtime) | Exit 0. |
| Full mock suite | First run: exactly one failure (the route inventory above). After the inventory update: **exit 0 with 3,211 collected** — the historical 3,210 baseline plus this ticket's one new behavior test. Log: `/private/tmp/ticket09-pytest-full2.log`. |
| Post-run leak check | No disposable-stack/uvicorn/playwright processes or listeners on ports 8121–8129. |

#### Measured request counts

`frontend/src/useReader.test.tsx` records actual counts against the stubbed
transport: per open/switch/revisit, **2 requests** (one workspace read plus the
identity probe), down from the pre-ticket composed 5 reads per open (message
page, project, session probe, bookmarks on mount, settings on mount — the
baseline the red run observed at hook level as 3 reads, plus the two component
fetches). Loading earlier pages intentionally keeps its existing pagination
reads. These are synthetic in-memory counts, not production latency claims;
the startup bootstrap flow is unchanged at 2 requests.

#### Compatibility, rollback, risks and next exact action

No schema, saved-data or existing-API change: the workspace read is additive;
the page/bookmarks/project routes keep their paths, payloads, responses and
operation IDs through the shared projections; the OpenAPI metadata addition is
additive for every existing caller. The Streamlit entrypoint, `api_client.py`
and all other backend routes are untouched. Frontend reads stay immediately
stale; the only retained data is the same in-memory settings resource policy
(ticket 07) plus the reader-state bookmarks projection, and nothing enters
persistent browser storage. Rollback is source-only: revert `notebook_reader.py`,
the export allowlist, `reader.json`, regenerated client files, `client.ts`,
`api.ts`, `workspaceSettings.ts`, `useReader.ts`, `App.tsx`, `Conversation.tsx`,
restore the three backend test edits, delete `useReader.test.tsx` and restore
the two edited frontend test files.

Known limits, documented rather than silently accepted: the aggregated
response reads messages twice (once for the bounded page, once for the project
projection) — a constant per-open cost, not N+1, kept so the page reuses the
authoritative revision/cursor pagination path; collapsing it further would
reimplement pagination semantics for no measured gain. Bookmarks do not
live-sync across same-owner tabs — they reconcile on the next open, refresh,
star action or identity reset, matching the documented settings behavior. The
`review` project-brief projection now materializes documented optional fields
as empty defaults in the client adapter; the server contract is unchanged.

**Next exact action:** tickets 07, 08 and 09 all have acceptance evidence, so
ticket 14 (navigate existing workspaces through URLs, blocked by 6 and 9) is
now eligible together with the other already-eligible frontier tickets (10–13,
35, 37–40). Start exactly one fresh writer session for
`.scratch/architecture-completion/issues/14-navigate-existing-workspaces-through-urls.md`
in this same checkout, preserving the dirty working tree.

### Ticket 08 complete — notebooks through generated REST and Query (2026-11-24 SGT, OpenCode)

**Ticket 08 is implemented and locally verified.** Notebook creation, rename,
chat movement, pinning and confirmed deletion now run through reviewed
generated contracts with stable operation IDs, and every confirmed mutation
reconciles the owner-fenced notebooks listing resource before the existing
authoritative list revalidation. Triage remains `ready-for-agent`; nothing is
staged, committed or deployed.

Starting revision/branch: `improvement/architecture-responsiveness` with the
dirty ticket 01–07 working tree preserved unchanged apart from this ticket's
files.

#### New files and behavior

| File | Responsibility |
| --- | --- |
| `backend/http/reader_workspace.py` | Adds `ReaderRemoved` (owner-fenced `{owner_id, status: "deleted"}` receipt — identical JSON to the previous dict response) and stable operation IDs `readerThreadsCreate`, `readerThreadMove`, `readerThreadRemove` with typed 401/403/404 error models on create, move and remove. No route path, payload, ownership or persistence behavior changed. |
| `scripts/export_reader_openapi.py` | Allowlist extended from eight to eleven operations; still fails closed on missing/untyped operations (red observed before the backend change). |
| `frontend/openapi/reader.json` + `frontend/src/api/generated/*` | Re-exported offline and regenerated; `npm run api:check` reports no drift. |
| `frontend/src/api/client.ts` | `createThread`, `moveThread`, `removeThread` over the generated SDK — same-origin cookies, `no-store`, `AbortSignal`, status-only errors, the required `confirmed: true` body on delete, notebook adapter normalization. |
| `frontend/src/api/workspaceNotebooks.ts` | New owner-fenced notebooks-listing resource: `fetchConfirmedNotebooks` (foreign-owner rejection), `notebooksPolicies` (reads stay immediately stale so no read is served from cache; the last confirmed listing stays in memory with a 5-minute gc solely as the reconciliation target), `notebooksQueryOptions`, bootstrap `seedNotebooks`, `withEntry`/`withoutEntry` identity-preserving updates, and `reconcileNotebooks` (cancels superseded reads, then writes the confirmed result so a late pre-write response can never roll it back; never writes into another owner's resource). |
| `frontend/src/useReader.ts` | `reload` seeds the listing resource from the owner-verified bootstrap; `readNotebooks` uses the resource options; `updateChat` writes move/settings/remove through the generated contracts (rename and pin previously bypassed the ticket 07 generated settings write with a raw fetch), reconciles the confirmed entry or deletion into the resource, then keeps the existing authoritative `refreshList` revalidation and saved-predicate check. Epoch/abort fencing unchanged. |
| `frontend/src/WorkspaceTools.tsx` | Notebook create and confirmed delete run the generated contracts inside the existing write frame with identity probes; create reconciles the created entry (newest first, matching server ordering), delete drops the entry, its bounded summary and the removed notebook's settings resource. Definitive 4xx rejections still refresh the sidebar and report "That change was unavailable. Saved workspace refreshed."; ambiguous transport failures keep the explicit refresh recovery. |
| `tests/scripts/test_export_reader_openapi.py` | Schema inventory extended (`ReaderCreate`, `ReaderMoveChat`, `ReaderRemove`, `ReaderRemoved`). |
| `frontend/src/api/client.test.ts` | 6 new lifecycle transport tests: create POST shape/cookies/cancellation, move + confirmed-delete bodies and paths, HTTP 401/403/404/422 status-only errors. |
| `frontend/src/api/workspaceNotebooks.test.ts` | New resource tests: stale-zero/positive-gc policy, foreign-owner read rejection, identity-preserving entry updates, deletion drops only that entry's preview, confirmed-write reconciliation with superseded-read cancellation, and never writing into another owner's resource. |
| `frontend/src/WorkspaceTools.test.tsx` | 2 new jsdom tests: create through the generated POST contract reconciles the sidebar resource; confirmed delete drops the sidebar identity and the stale settings resource. The render helper now exposes the imperative actions ref and an optional current thread. |

#### Executed validation

| Command/check | Result |
| --- | --- |
| `pytest tests/scripts/test_export_reader_openapi.py` | 3 passed (red first: missing `ReaderCreate`/`ReaderMoveChat`/`ReaderRemoved`). |
| `pytest tests/http/test_reader_workspace.py tests/http/test_reader_bootstrap.py tests/http/test_reader_conversation.py` | 21 passed — same count as ticket 07. |
| `npm test --prefix frontend` | **62 passed / 7 files** (48 before this ticket). |
| `npm run build --prefix frontend` | Exit 0 (`tsc --noEmit` + Vite production build). |
| `npm run api:check --prefix frontend` | First run exit 1: the installed generator bundle emitted numbered duplicate copies (the documented ticket 06 contamination pattern; tracked sources were already correct and the copies were deleted, never copied into source). Repaired per the documented procedure with `npm ci --ignore-scripts --prefix frontend` from the unchanged lockfile; `api:check` then exit 0. Log: `/private/tmp/ticket08-npmci.log`. |
| `npm run test:browser --prefix frontend` | **7 passed** — full ticket 05 slice green after the notebook lifecycle changes. |
| `.venv/bin/ruff check .` | Exit 0. |
| `compileall` (backend, ui, streamlit_app, tests, scripts, agentcore_runtime) | Exit 0. |
| Full mock suite | Exit 0 with 3,210 tests collected, matching the historical 3,209 passed + 1 optional skip; the background log captured completion to 100% but displaced the one-line summary (log: `/private/tmp/ticket08-pytest-full.log`). |
| Post-run leak check | No disposable-stack/uvicorn/playwright processes or listeners on ports 8121–8129. |

#### Compatibility, rollback, risks and next exact action

No schema, API shape, saved-data or configuration change: the three lifecycle
routes keep their paths, payloads and response JSON (the remove receipt is
byte-identical); only OpenAPI metadata (operation IDs, documented error models)
was added, which is additive for every existing caller. The Streamlit
entrypoint, `api_client.py` and all other backend routes are untouched. Reads
stay immediately stale — no sidebar read is ever served from cache — so the
only retention change is in-memory availability of the last confirmed listing
for write reconciliation; nothing enters persistent browser storage. Rollback
is source-only: revert `reader_workspace.py`, the export allowlist,
`reader.json`, regenerated client files, `client.ts`, `useReader.ts`,
`WorkspaceTools.tsx`, delete `workspaceNotebooks.ts` with its test file and
restore the three edited test files.

Known limits, documented rather than silently accepted: a confirmed write still
performs one authoritative list revalidation afterwards (summaries, ordering
and the saved-predicate check), so a mutation costs one write plus one list
read; collapsing that into the confirmed response belongs to ticket 09's
aggregated workspace read. Same-owner cross-tab list edits are not live-synced
and reconcile on the next explicit refresh, navigation or identity reset, as
before. The generator-bundle contamination recurred this ticket; the documented
`npm ci --ignore-scripts` repair worked, and the next `api:generate` should be
followed by `api:check` with the same repair ready.

**Next exact action:** ticket 08's dependencies are satisfied (07 and 08 both
have acceptance evidence), so ticket 09 (aggregated verified workspace) is
unblocked. Start exactly one fresh writer session for
`.scratch/architecture-completion/issues/09-open-an-aggregated-verified-workspace.md`
in this same checkout, preserving the dirty working tree.

### Ticket 07 complete — preferences and settings through generated REST and Query (2026-11-24 SGT, OpenCode)

**Ticket 07 is implemented and locally verified.** Preference and
notebook-settings reads/writes now run through reviewed generated contracts
with stable operation IDs, targeted Query reconciliation and identity-safe
measured freshness. Triage remains `ready-for-agent`; nothing is staged,
committed or deployed.

Starting revision/branch: `improvement/architecture-responsiveness` with the
dirty ticket 01–06 working tree preserved unchanged apart from this ticket's
files.

#### New files and behavior

| File | Responsibility |
| --- | --- |
| `backend/http/reader_workspace.py` | Registers stable operation IDs `readerPreferences`, `readerPreferencesUpdate`, `readerNotebookSettings`, `readerNotebookSettingsUpdate` with typed 401/403/404 error models; `ReaderError` moved here so `notebook_reader.py` imports it without a cycle. No route path, payload, ownership or persistence behavior changed. |
| `scripts/export_reader_openapi.py` | Allowlist extended from four to eight operations; still fails closed on missing/untyped operations (red observed before the backend change). |
| `frontend/openapi/reader.json` + `frontend/src/api/generated/*` | Re-exported offline and regenerated; `npm run api:check` reports no drift. |
| `frontend/src/api/client.ts` | `readPreferences`, `updatePreferences`, `readNotebookSettings`, `updateNotebookSettings` over the generated SDK — same-origin cookies, `no-store`, `AbortSignal`, status-only errors, notebook adapter normalization. |
| `frontend/src/api/workspaceSettings.ts` | Owner-fenced preference/settings Query resources: per-resource `resourcePolicies` (preferences 90 s, notebook settings 30 s, gc 5 min each; global defaults stay zero), bootstrap seeding, foreign-owner fencing, 404→null settings resolution for removed notebooks, and mutation options that cancel superseded reads and reconcile only the confirmed resource. |
| `frontend/src/api/queryKeys.ts` | Adds `preferences(owner)` and `notebookSettings(owner, thread)` under the verified-owner root. |
| `frontend/src/useReader.ts` | Seeds the preferences resource from the owner-verified bootstrap result so no component refetches it immediately. |
| `frontend/src/WorkspaceTools.tsx` | Settings surface now consumes the Query resources; saves go through a shared write frame (`mutateAsync` + identity probes) that never replays a write; preferences saves issue no follow-up read (the confirmed response reconciles); settings saves keep the explicit list refresh; confirmed delete drops that notebook's settings entry. Create/remove remain on their existing routes until ticket 08. |
| `frontend/src/api/workspaceSettings.test.ts` | 7 resource tests: owner/notebook-scoped keys, separately configured freshness, bootstrap reuse with zero duplicate reads, measured-freshness refetch, foreign-owner rejection, cleared-identity delayed-response fencing, confirmed-save reconciliation with superseded-read cancellation (`MutationObserver`, no DOM). |
| `frontend/src/WorkspaceTools.test.tsx` | 4 jsdom component tests: save feedback with exactly one POST and no replayed read, remount reuse without duplicate reads, empty shared browser storage, foreign-owner save rejected and never applied. New devDependencies: `@testing-library/react@16.3.1`, `jsdom@27.2.0`. |
| `tests/scripts/test_export_reader_openapi.py` | Schema inventory extended (`ReaderPreferencesPatch`, `ReaderNotebookSettings`, `ReaderModel`, `ReaderSettingsPatch`). |

#### Executed validation

| Command/check | Result |
| --- | --- |
| `pytest tests/scripts/test_export_reader_openapi.py` | 3 passed (red first for the intended reason). |
| `pytest tests/http/test_reader_workspace.py tests/http/test_reader_bootstrap.py tests/http/test_reader_conversation.py` | 21 passed. |
| `npm test --prefix frontend` | 48 tests / 6 files pass. |
| `npm run build --prefix frontend` | Exit 0 (`tsc --noEmit` + Vite production build). |
| `npm run api:check --prefix frontend` | Exit 0 — no schema or generated-client drift. |
| `npm run test:browser --prefix frontend` | **7 passed** — full ticket 05 slice green after the settings-surface refactor. |
| `.venv/bin/ruff check .` | Exit 0. |
| Full mock suite | **3,210 passed, 1 skipped** — matches the historical count. |
| `compileall` (backend, ui, streamlit_app, tests, scripts, agentcore_runtime) | Exit 0. |
| Post-run leak check | No disposable-stack/uvicorn processes or listeners on ports 8121–8129. |

#### Compatibility, rollback, risks and next exact action

No schema, API shape, saved-data or configuration change: the four routes keep
their paths, payloads and responses; only OpenAPI metadata (operation IDs,
documented error models) was added, which is additive for every existing
caller. The Streamlit entrypoint, `api_client.py` and all other backend routes
are untouched. Rollback is source-only: revert `reader_workspace.py`/
`notebook_reader.py`, the export allowlist, `reader.json`, regenerated client
files, `workspaceSettings.ts`, `queryKeys.ts`, the `useReader.ts` seed and
`WorkspaceTools.tsx`, and delete the two new test files and the two new
devDependencies.

Known limits, documented rather than silently accepted: same-owner cross-tab
preference edits are not live-synced — they reconcile within the bounded
freshness window (or on the next write/navigation/identity reset), which the
component and resource tests bound rather than eliminate. Positive retention is
small, per-resource and derived from request-count measurements in tests
(bootstrap reuse, one refetch after expiry), not from production traffic
measurement. Settings saves still refresh the whole notebook list through the
existing `changed()` path; tightening that belongs to ticket 08's notebook
resource work.

**Next exact action:** ticket 07's dependencies are satisfied; per the
[approved ticket graph](../.scratch/architecture-completion/README.md#approved-ticket-graph)
the frontier now includes ticket 08 (notebooks through generated REST and
Query); ticket 09 (aggregated verified workspace) becomes unblocked when 08
completes. Start exactly one fresh writer session for
`.scratch/architecture-completion/issues/08-manage-notebooks-through-generated-rest-and-query.md`
in this same checkout, preserving the dirty working tree.

### Ticket 06 complete — chat lifecycle extraction (2026-11-24 SGT, OpenCode)

**Ticket 06 is implemented and locally verified.** The chat controller
(`frontend/src/Conversation.tsx`) was prefactored: an explicit lifecycle module
(`frontend/src/chatLifecycle.ts`) now owns the coach turn — request/owner
identity (`active`/`controller`/`lock`/`verify`), one mutually exclusive state
machine (`idle → requesting → streaming → saving → checking`) replacing the
former independent `watching`/`canStop`/`checking` booleans, plus the pending
receipt and its `checkedKey` recovery metadata, progress, preview and status.
`send`, `reconcile`, `stopGeneration`, `discardPending` and the mount/unmount
fences moved verbatim: the same status strings, NDJSON event handling,
cancelled-branch semantics (no reconcile, no replay), read-only recovery under
the original key and safety-eligible preview handling. No application behavior
changed, so the approved TDD contract used characterization coverage — green
before and after the extraction — with no manufactured red test or speculative
code. Triage remains `ready-for-agent`; nothing is staged, committed or
deployed.

**Coverage added before prefactoring (ticket 06 checkbox 1).** The ticket 05
slice covered generation, owner-switch isolation, exact-key recovery and
restart persistence, but **cancellation, ambiguous save and discard were
covered nowhere**. Two browser specs now cover them at the approved primary
seam:

- `frontend/tests/browser/student_stop_cancels.spec.ts` — the student clicks
  the real Stop control against a paused mock workflow. The mock provider
  finishes faster than a click can win the stop/save race, so the disposable
  stack serves `tests/browser/cancellable_stack_app.py`: the same
  paused-`CoachWorkflow.run` technique the FastAPI cancellation test uses, plus
  a fixture-only `/__fixture__/release-coach-turn` control route. The real stop
  route answers `stopping`, the released worker emits the canonical
  `reply_discard` → 409 `cancelled` terminal sequence, the prompt is kept,
  nothing is saved, no receipt exists and no generation is replayed — verified
  again after a reload. `disposable_stack.py` gained a `PW_STACK_APP` selector
  (mutually exclusive with `PW_REGISTERED_IDENTITY`); `stack.ts` exposes it as
  `startStack(..., { cancellableTurns: true })`.
- `frontend/tests/browser/ambiguous_save_recovers.spec.ts` — an interrupted
  stream (real server commit, then `route.abort()`) whose receipt read returns
  `null` (the real unsaved body) keeps the question pending with explicit
  actions only: a later explicit **Check saved answer** recovers the saved
  reply exactly once; an explicit **Discard and edit** restores the composer
  text without resending.

#### Files changed

| File | Change |
| --- | --- |
| `frontend/src/chatLifecycle.ts` | New: `useChatLifecycle` — request/owner identity, turn state machine, recovery metadata, operations. |
| `frontend/src/Conversation.tsx` | 193 lines smaller; consumes the lifecycle; rendering, drafts, scaffolds, feedback, evidence and review untouched. |
| `frontend/tests/browser/student_stop_cancels.spec.ts`, `ambiguous_save_recovers.spec.ts` | New characterization coverage (cancellation, ambiguous save, discard). |
| `tests/browser/cancellable_stack_app.py`, `tests/browser/disposable_stack.py`, `frontend/tests/browser/stack.ts` | Deterministic paused-workspace fixture app and its stack selector. |
| `frontend/vitest.config.ts` | **Pre-existing break repaired:** since ticket 05 added `tests/browser/*.spec.ts`, plain `vitest run` (used by `scripts/build.sh`) collected the Playwright specs and failed. Vitest is now scoped to `src/**` (30 tests / 4 files, the historical count). Ticket 05's ledger never reran `npm test`, so the break predates this ticket. |
| `docs/TESTING.md` | Slice table: two new specs; fixture-app selection documented. |

#### Executed validation

| Command/check | Result |
| --- | --- |
| `npm run test:browser --prefix frontend` | **7 passed**, before *and* after the extraction (guest, owner-switch, restart persistence, interrupted recovery, registered, stop-cancel, ambiguous/discard). Repeated — stable. |
| `npm test --prefix frontend` | 30 tests / 4 files pass. |
| `npm run build --prefix frontend` | Exit 0 (`tsc --noEmit` + Vite production build). |
| `sh scripts/build.sh` | Exit 0 after dependency repair: TypeScript/Vite build, 30 Vitest tests, offline OpenAPI + generated-client checks, compileall, and the full mock pytest suite (collection: **3,210**, matching the historical count; the double-quiet config omits the numeric summary). Log: `/private/tmp/ticket06-build.log`. |
| `npm run api:check --prefix frontend` | Initially failed with the ticket 02 contamination pattern (twelve numbered ` 2.gen.ts` copies emitted from the installed generator bundle after ticket 05's `npm install`; checked-in source correct). Repaired per the documented procedure with `npm ci --ignore-scripts --prefix frontend` from the unchanged lockfile; both `api:check` and `export_reader_openapi.py --check` then passed. No generated file, lockfile or comparison change. Log: `/private/tmp/ticket06-npm-ci.log`. |
| `.venv/bin/ruff check .` | Exit 0, `[]` (including the new fixture modules). |
| `compileall` on changed fixture modules | Exit 0. |
| Post-run leak check | No disposable-stack/uvicorn processes or listeners on ports 8121–8129. |

#### Compatibility, rollback, risks and next exact action

No schema, API, generated-contract, saved-data or configuration change; the
Streamlit entrypoint and all backend routes are untouched. Rollback is
source-only: restore `Conversation.tsx` from before this entry and delete
`chatLifecycle.ts`, the two new specs, the fixture app, the stack-selector
lines, the Vitest config and the doc/ledger sections. The frontend bundle hash
changes (module split), which is the only deployable-visible difference.

Known limits, documented rather than silently accepted: the cancellation spec's
server side is real, but the mock provider cannot lose the stop/save race to a
human-speed click, so the fixture pauses the workflow deterministically — the
same technique and terminal wire sequence the FastAPI seam proves. The
ambiguous-save spec intercepts only the receipt read with the route's real
unsaved body; both specs state their seams in their headers. Playwright
`route.fulfill` buffers streamed bodies, so mid-stream delivery timing could
not be simulated at the browser layer (probed and discarded during this
ticket).

**Next exact action:** ticket 06's dependencies are satisfied; per the
[approved ticket graph](../.scratch/architecture-completion/README.md#approved-ticket-graph)
the frontier now includes ticket 07 (save preferences through generated REST
and Query), ticket 08 (notebooks through generated REST and Query) and ticket
14's other prerequisite ticket 09 (aggregated verified workspace, blocked by
07+08). Start exactly one fresh writer session for
`.scratch/architecture-completion/issues/07-save-preferences-through-generated-rest-and-query.md`
in this same checkout, preserving the dirty working tree.

### Ticket 05 complete — browser CI slice (2026-11-24 SGT, OpenCode)

**Ticket 05 is implemented and locally verified; ticket 06 is unblocked.** The
manual Playwright CLI student journey is now finite, self-cleaning Playwright
Test CI covering Guest **and** a synthetic registered identity, exact-key
recovery of an interrupted response, in-flight owner-switch fault injection and
real backend restart persistence. No application behavior changed, so the
approved TDD contract used new public-seam tests only — no red/green cycle and
no speculative code. Triage remains `ready-for-agent`; nothing is staged,
committed or deployed.

Starting revision/branch: `4f12995` / `improvement/architecture-responsiveness`.
All prior uncommitted ticket 01–04 and handover work is preserved. The earlier
`@playwright/test@1.64.0` blocker was an offline-only install failure
(`ENOTCACHED`); with the registry reachable, the package installed cleanly into
the unchanged lockfile plus the new devDependency. No other dependency, schema,
API, generated-contract or configuration change.

#### New files and behavior

| File | Responsibility |
| --- | --- |
| `frontend/playwright.config.mts` | Chromium project, single worker, loopback `baseURL`, failure screenshots and JSON/HTML reports under ignored `output/playwright/`. |
| `frontend/tests/browser/stack.ts` | Starts, stops and **restarts** `tests/browser/disposable_stack.py` against a persistent temp workspace, so a spec can exercise a real backend restart. Honors `PW_PYTHON` for CI (no project `.venv` there). |
| `frontend/tests/browser/guest_journey.spec.ts` | Guest signs in, opens a notebook, submits a deterministic mock coaching turn, and reopens the committed reply after reload; asserts no fabricated chat-progress percentages and no unexpected console/page errors. |
| `frontend/tests/browser/interrupted_stream_recovers.spec.ts` | The real stream request completes server-side and only then the page's connection drops (`route.fetch()` then `route.abort()`); the client reconciles read-only via `GET /threads/{id}/coach-turn?idempotency_key=` with the **original** key and renders exactly one confirmed turn, no replayed write. |
| `frontend/tests/browser/owner_switch_inflight.spec.ts` | Guest switch while a generation request is pending: aborts the request, drops an approved late reply for the previous owner, hides the old chat, never replays generation (`page.route` fault injection). |
| `frontend/tests/browser/registered_journey.spec.ts` | Synthetic registered student opens a notebook, submits a mock turn and reopens the committed reply after a real backend restart while staying the same verified identity. |
| `frontend/tests/browser/saved_turn_survives_restart.spec.ts` | Actually stops and respawns the disposable API against the same SQLite workspace; the same browser context reopens the chat and the committed reply is present. |
| `tests/browser/disposable_stack.py` | Builds and validates a disposable temp workspace, pins mock/SQLite/local, matches `CO_DESIGN_PUBLIC_API_URL`/`CO_DESIGN_UI_URL` to the served origin (required by the guest-start same-origin check), terminates its uvicorn child on SIGTERM, and fails fast with the server log if the API dies before readiness. `PW_REGISTERED_IDENTITY=1` serves the registered-identity boundary. |
| `tests/browser/registered_stack_app.py` | Deterministic in-memory Cognito verifier injected into `create_app` (same pattern as `tests/http/test_production_critical_path.py`); forged/unknown tokens still rejected. |
| `frontend/package.json` | Adds `@playwright/test@1.64.0` (dev) and the repeatable `test:browser` script. |
| `.github/workflows/mock-ci.yml` | New finite `browser-ci-slice` job: build reader, install Chromium, run the slice with `PW_PYTHON=python3`, upload the report on failure. |
| `.gitignore` | Ignores `frontend/test-results/`. |
| `docs/TESTING.md` | Documents the slice, its coverage table and its explicit limits. |

#### Executed validation

| Command/check | Result |
| --- | --- |
| `npm run test:browser --prefix frontend` | **5 passed** (guest journey, interrupted recovery, owner switch, registered journey, restart persistence). Repeated — stable after replacing a transient-preview wait with a completed-coach-message wait. |
| Post-run leak check | No `uvicorn`/`disposable_stack` processes left and nothing listening on ports 8121–8125 — the SIGTERM teardown is clean. |
| `PW_PYTHON=python3` stack probe | Fails fast with the real server-log cause (missing `authlib` in the ambient interpreter) instead of burning the 60 s readiness timeout — this is the CI path, where `requirements-dev.txt` is installed first. |
| `npm run build --prefix frontend` | Exit 0: `tsc --noEmit` (type-checks the new specs/config) plus the Vite production build. |
| `.venv/bin/ruff check tests/browser/disposable_stack.py tests/browser/registered_stack_app.py` | Exit 0, no findings. |
| `.venv/bin/python -m pytest --collect-only -q -o addopts=''` | **3,210 collected** — unchanged; the new helpers are not collected as test modules. |
| Full mock pytest suite (`MOCK_OPENAI=true MODEL_PROVIDER=mock ... python -m pytest -q`) | **Exit 0** — no failures. The repo's double-quiet config omits the numeric summary; separate `--collect-only` establishes the count. |
| `python -c "yaml.safe_load(...)"` on `mock-ci.yml` | Parses cleanly. |
| Focused reader/journey tests | `tests/http/test_student_journey_readiness.py` + `tests/http/test_production_critical_path.py`: **7 passed**. |

#### Compatibility, rollback and limits

No application, schema, API, generated-client or saved-data change; existing
manual browser scripts, fixtures and the protected Streamlit entrypoint are
untouched. Rollback is source-only: remove the new files, the two
`package.json`/lockfile lines, the CI job, the `.gitignore` line and the doc
sections. The slice never touches a developer database, live Cognito, AWS
credentials or a paid provider; screenshots and reports land under ignored
paths.

**Known limit (documented, not silently accepted):** the registered journey seeds
verified cookies directly, so it exercises the real owner-scoped API path with a
synthetic identity but not the Cognito Hosted UI redirect or token exchange.
Live Cognito sign-in remains a manual, separately authorized check.

**Next exact action:** start ticket **06 — Extract the chat lifecycle without
changing behavior**
(`.scratch/architecture-completion/issues/06-extract-the-chat-lifecycle-without-changing-behavior.md`)
in a fresh session. Its only blocker (ticket 05) now has acceptance evidence.
The browser slice supplies the safety net ticket 06 needs: preserve existing
lifecycle behavior under verified coverage first.

### Browser CI slice for ticket 05 — partial (2026-11-24 SGT, OpenCode)

> **Superseded** by the ticket 05 completion entry above; retained for the
> intermediate evidence trail (Guest-only coverage and the two requirements that
> were still open at that checkpoint, both since implemented and verified).

**Ticket 05 is partially implemented and locally verified; registered identity
and injected interrupted-stream recovery remain open.** The slice converts part
of the manual Playwright CLI browser journey into finite, self-cleaning Playwright
Test CI. No application behavior changed, so the approved TDD contract used new
public-seam tests only — no red/green cycle and no speculative code. Triage
remains `ready-for-agent`; nothing is staged, committed or deployed.

Starting revision/branch: `4f12995` / `improvement/architecture-responsiveness`.
All prior uncommitted ticket 01–04 and handover work is preserved. The earlier
`@playwright/test@1.64.0` blocker was an offline-only install failure
(`ENOTCACHED`); with the registry reachable, the package installed cleanly into
the unchanged lockfile plus the new devDependency. No other dependency, schema,
API, generated-contract or configuration change.

#### New files and behavior

| File | Responsibility |
| --- | --- |
| `frontend/playwright.config.mts` | Chromium project, single worker, loopback `baseURL`, failure screenshots and JSON/HTML reports under ignored `output/playwright/`. |
| `frontend/tests/browser/stack.ts` | Starts, stops and **restarts** `tests/browser/disposable_stack.py` against a persistent temp workspace, so a spec can exercise a real backend restart. Honors `PW_PYTHON` for CI (no project `.venv` there). |
| `frontend/tests/browser/guest_journey.spec.ts` | Guest signs in, opens a notebook, submits a deterministic mock coaching turn, and reopens the committed reply after reload; asserts no fabricated chat-progress percentages and no unexpected console/page errors. |
| `frontend/tests/browser/owner_switch_inflight.spec.ts` | Guest switch while a generation request is pending: aborts the request, drops an approved late reply for the previous owner, hides the old chat, never replays generation (`page.route` fault injection). |
| `frontend/tests/browser/saved_turn_survives_restart.spec.ts` | Actually stops and respawns the disposable API against the same SQLite workspace; the same browser context reopens the chat and the committed reply is present. |
| `tests/browser/disposable_stack.py` | Builds and validates a disposable temp workspace, pins mock/SQLite/local, matches `CO_DESIGN_PUBLIC_API_URL`/`CO_DESIGN_UI_URL` to the served origin (required by the guest-start same-origin check), terminates its uvicorn child on SIGTERM, and fails fast with the server log if the API dies before readiness. |
| `frontend/package.json` | Adds `@playwright/test@1.64.0` (dev) and the repeatable `test:browser` script. |
| `.github/workflows/mock-ci.yml` | New finite `browser-ci-slice` job: build reader, install Chromium, run the slice with `PW_PYTHON=python3`, upload the report on failure. |
| `.gitignore` | Ignores `frontend/test-results/`. |
| `docs/TESTING.md` | Documents the slice, its coverage table and its explicit limits. |

#### Executed validation

| Command/check | Result |
| --- | --- |
| `npm run test:browser --prefix frontend` | **3 passed** (guest journey 1.7 s, owner switch 0.64 s, restart persistence 2.6 s). Repeated five times — stable, no flakes after replacing a transient-preview wait with a completed-coach-message wait. |
| Post-run leak check | No `uvicorn`/`disposable_stack` processes left and nothing listening on ports 8121–8123 — the SIGTERM teardown is clean. |
| `PW_PYTHON=python3` stack probe | Fails fast with the real server-log cause (missing `authlib` in the ambient interpreter) instead of burning the 60 s readiness timeout — this is the CI path, where `requirements-dev.txt` is installed first. |
| `npm run build --prefix frontend` | Exit 0: `tsc --noEmit` (type-checks the new specs/config) plus the Vite production build. |
| `.venv/bin/ruff check tests/browser/disposable_stack.py` | Exit 0, no findings. |
| `.venv/bin/python -m pytest --collect-only -q -o addopts=''` | **3,210 collected** — unchanged; the new helper is not collected as a test module. |
| `python -c "yaml.safe_load(...)"` on `mock-ci.yml` | Parses cleanly. |
| Full mock pytest suite (`MOCK_OPENAI=true MODEL_PROVIDER=mock ... python -m pytest -q`) | **Exit 0** — no failures. The repo's double-quiet config omits the numeric summary; separate `--collect-only` establishes **3,210 collected** with the one optional `strands` skip. |
| Earlier in this ticket | Focused `tests/http/test_student_journey_readiness.py` + `tests/http/test_production_critical_path.py`: **7 passed**. |

#### Compatibility, rollback, risks and remaining work

No application, schema, API, generated-client or saved-data change; existing
manual browser scripts, fixtures and the protected Streamlit entrypoint are
untouched. Rollback is source-only: remove the new files, the two
`package.json`/lockfile lines, the CI job, the `.gitignore` line and the two doc
sections. The slice never touches a developer database, live Cognito, AWS
credentials or a paid provider; screenshots and reports land under ignored
paths.

**Remaining for ticket 05 acceptance (explicit, not assumed complete):**

1. The approved synthetic **registered** identity journey (needs the
   deterministic OIDC adapter from `tests/http/test_production_critical_path.py`
   injected into the disposable stack's `create_app`).
2. An injected **interrupted** stream that recovers under the original request
   key and creates exactly one confirmed turn (the delayed relay in
   `tests/browser/reply_streaming_fixture.py` is the intended seam).
3. Re-run the slice plus the applicable full gates after those land, then record
   acceptance and update this ledger.

**Next exact action:** implement item 2 (interrupted-stream exact-key recovery)
in `frontend/tests/browser/`, reusing `stack.ts` and the delayed-relay behavior,
then item 1 (registered identity). Both stay inside the approved public seam
with deterministic adapters; no staging, commit, deployment or paid call.

### OpenCode transfer checkpoint — ticket 05 pending (2026-11-24 SGT)

The user stopped implementation for transfer to OpenCode. Resume in the existing
`improvement/architecture-responsiveness` checkout at
`4f12995afbfba4c5c975ad12eb9874fcd4cfea39`, preserving the dirty working tree
and the untracked local execution pack. [OpenCode handover](operations/AGENT_HANDOVER.md)
records the working tree, evidence, remaining requirements and execution contract.

Milestone 0 local evidence is complete through accepted tickets 01–04. Release
and redistribution gates remain open. Ticket 05 is the next unfinished ticket
and an early prerequisite for milestone 2. The writer inspected the accepted
baseline, test fixtures, auth boundary and CI entrypoint. Its single offline
Playwright Test install attempt ended with `ENOTCACHED`. Neither frontend
manifest changed. There is no ticket 05 test, runner, workflow change, verified
browser CI result or checked acceptance item. Triage stays `ready-for-agent`.

The transfer changes only this ledger and the handover document. It requires
no API/schema/configuration migration and leaves all existing source and data
in place. The prior local validation remains under tickets 01–04. No new test
suite or external verification was run for the documentation transfer.

**Next exact action after transfer:** open [local ticket 05](../.scratch/architecture-completion/issues/05-run-an-existing-student-journey-in-browser-ci.md)
in OpenCode and establish the pinned Playwright Test runner and the first
disposable Guest browser journey. Finish registered identity, actual API restart,
exact-key recovery and controlled owner/preview cases before accepting ticket 05.
Ticket 06 remains blocked on that acceptance. No next writer was dispatched.

### Local completion ticket 04 — deployment and safety records (2026-11-24 SGT)

**Local acceptance complete; live release verification remains open.** Added a
versioned nonsecret manifest and reviewable publication/session/OUTPUT-block
procedure. No application behavior changed; the approved TDD contract used
source/record reproduction and existing deterministic regressions, with no new
seam, speculative code or manufactured red test. Local checklist verified;
triage remains `ready-for-agent`. No GitHub issue changed or closed.

Starting revision/branch: `4f12995afbfba4c5c975ad12eb9874fcd4cfea39` /
`improvement/architecture-responsiveness`. Preserved all prior uncommitted work.
No staging, commit, push, deployment, image build, runtime publication, session
rollover, infrastructure/data change, paid call, credential access/rotation,
artifact deletion or history rewrite occurred.

#### Reconciled records and files

- Added [deployment safety record](deploy/DEPLOYMENT_SAFETY_RECORD.md) and
  [schema-v1 nonsecret manifest](examples/deployment/architecture-ticket04-2026-11-24.json).
  The manifest hashes fifteen relevant source/config/contract files and separates
  settings defaults, example/Compose configuration, last recorded deployment,
  local verification and actually verified live configuration. All live fields
  remain null. It records compatible application/edge/image/runtime/model/session
  identities and parser, safety and saved-data compatibility requirements.
- Latest historical restoration pins `GemmaStable37` to V1 deployment **38**;
  DEFAULT remained V2 **39**. The alias name is not its version. Recorded v38
  package hash is checked against the aggregate result JSON. The earlier app
  image/settings-patch identities are retained with carry-forward explicitly
  unverified; live registry digest and edge identity are unknown. The restoration
  records a fresh generation without its literal value: unknown, not the earlier
  v37 generation. No historical artifact is certified to contain the later
  Mantle provisional-output fix.
- Settings without overrides default to mock; `.env.example` and Compose select
  AgentCore/Haiku and different session generations. Corrected the architecture
  guide's assertion that copying `.env.example` supplies cost-safe mock settings.
  No configuration values were changed. Python 3.12 app versus Python 3.14/ARM64
  runtime recipes, old dependency comments and mutable Caddy tag are distinguished.
- Updated `docs/PRODUCTION_RELEASE_CHECKLIST.md`,
  `docs/deploy/AWS_STATELESS_EC2.md`, `docs/providers/MODEL_PROVIDERS.md`,
  `docs/SECURITY_BOUNDARIES.md`, `docs/LOCAL_DEMO_IMPLEMENTATION.md`,
  `docs/README.md`, this ledger and the local ticket 04 checklist. Existing
  incoming runbook heading links remain intact.
- Publication gates capture the release tuple, inspect the selected endpoint and
  DEFAULT independently, require READY, a unique generation and FastAPI recreation,
  associate fresh-session telemetry with the actual version, and distinguish
  INPUT refusal from controlled OUTPUT blocking. Test allowed/blocked text at
  runtime, app stream, browser and saved receipt/restart boundaries. These are
  reviewable unexecuted live steps requiring separate authorization and a cap.
  Rollback must retain the provisional-output fix; an old READY alias or host
  rollback script alone is insufficient. With no verified safe target, preserve
  saved work and suspend generation through an approved operational action.

#### Executed validation

| Command/check | Result and evidence |
| --- | --- |
| `.venv/bin/python -m pytest -q -o addopts='' tests/domain/test_runtime_reply_stream.py tests/domain/test_runtime_model.py tests/domain/test_agentcore_session_affinity.py tests/domain/test_reply_streaming.py tests/test_deployment_config.py tests/http/test_production_config.py` | Exit 0, **141 passed**, six warnings, 2.94 s. `/private/tmp/ticket04-focused.log`. Existing allowed/blocked Mantle source regression, provider/config/session isolation, streaming/save/recovery and deployment contracts with deterministic external substitutes. |
| `sh scripts/build.sh` | Exit 0: TypeScript/Vite production build, **30 Vitest tests/four files**, offline OpenAPI/generated-client checks, compileall and full **3,210-test mock Python suite** reached 100% with no failures. `/private/tmp/ticket04-build.log`. Double-quiet pytest omits numeric summary; separate collection establishes count. |
| `.venv/bin/python -m pytest --collect-only -q -o addopts='' -rs` | Exit 0, **3,210 collected**, 2.90 s. Optional module skip: `tests/domain/test_strands_first_cycle_middleware.py:16`, `strands` absent. `/private/tmp/ticket04-collection.log`. No runtime-dependency compatibility or live-artifact pass is claimed. |
| `.venv/bin/ruff check . --output-format json` | Exit 0, `[]`; `/private/tmp/ticket04-ruff.json`. No configuration/ignore change. Static typing remains unconfigured. |
| Manifest/documentation/preservation checks | JSON parses; source hashes, all-unknown live fields and recorded v38 artifact hash match. Added local link targets/anchors and every offline command path resolve; `git diff --check` passes. SHA-256 comparison of all **865** starting tracked files permits only the seven intended guide/ledger edits; application, tests, config and prior artifacts remain unchanged. Temporary checker/evidence: `/private/tmp/ticket04-doc-check.py`, `ticket04-doc-check.log`, `ticket04-start-hashes.json`. Durable manifest/procedure linked above. |

Existing Vite/dependency/HTTPX/SWIG warnings remain non-failing. No new startup,
browser/layout, live/cloud or runtime-dependency integration claim. Ticket 01/02
retain disposable real startup, citations, explicit stage confirmation, streaming
and actual process-restart evidence; this documentation-only ticket reran the
applicable full local mock gate. Temporary logs are not portable release artifacts.

#### Compatibility, rollback, risks and next exact action

No schema/API/generated-client/config/runtime change, migration or saved-data
impact. Reverting only this ticket's documents, manifest, links, ledger entry and
checklist reverses it; do not revert the existing source safety fix or prior work.
Live application/runtime/session/edge identities, publication and controlled
blocked-output behavior remain unverified. Ticket 01's local Caddy bootstrap gap
and ticket 03's historical-artifact Docker-context finding are recorded release
gates, not fixed or certified here; ticket 51 owns coordinated packaging/edge and
release rehearsal. Redistribution, live Cognito/DSQL/runtime capacity, restore
and monthly cost gates remain open. Local acceptance does not authorize live work.

**Next exact action:** start exactly one fresh `gpt-6.1-sol` writer for
`.scratch/architecture-completion/issues/05-run-an-existing-student-journey-in-browser-ci.md`
in the same checkout. Ticket 01 supplies its dependency acceptance. Convert the
existing real disposable production-frontend/FastAPI/SQLite browser journey into
finite deterministic Playwright Test CI, retaining synthetic identity, original
request-key recovery, controlled fault injection and real restart coverage. Use
the approved seams; no paid services, developer database or live credentials.

### Local completion ticket 03 — repository privacy audit (2026-11-24 SGT)

**Local acceptance complete; redistribution and live release gates remain
open.** Inventoried all 865 tracked working-tree paths without copying raw
private content or credential values into the report. No application behavior
changed. The approved TDD contract used inspection/reproduction and existing
public regressions; no new seam or fabricated failing test. Triage remains
`ready-for-agent`; the audit is not authorization to publish or remediate history.

Starting revision/branch: `4f12995` /
`improvement/architecture-responsiveness`. Preserved all ticket 01/02,
publication and local-pack work. No staging, commit, push, worktree, deployment,
live configuration/data change, external service/model call, artifact deletion,
untracking, history rewrite or credential rotation occurred. Private developer
databases, `.env`, real Streamlit secrets and ignored uploads were not opened.

#### Findings, files and remaining publication work

- Added the actionable [privacy report](security/PUBLIC_REPOSITORY_CONTENT_AUDIT.md)
  and [redacted metadata inventory](examples/security/repository-privacy-2026-11-24.json).
  The inventory contains paths, sizes, counts, archive metadata and candidate
  rule locations, never matched values. Updated `docs/README.md`,
  `docs/SECURITY_BOUNDARIES.md`, this ledger and the local ticket 03 checklist.
- Ten course PDFs plus course-derived evaluation excerpts still require owner
  redistribution review. Dataset provenance distinguishes authored synthetic
  messages from course-derived evidence; neither proves permission for every
  captured artifact. No approved fixture replacement target was identified;
  existing artifacts were preserved.
- Inventoried 25 tracked browser artifacts (ten snapshots, ten logs, five brief
  exports), 140 historical task/evaluation artifacts, eleven dataset paths,
  three fixture JSONs and sixteen binaries. Browser metadata checks found 911
  URLs without query/fragment components, including 139 on another hostname;
  no email/credential-term matches in that group. This is not participant
  consent, synthetic-provenance or session-free certification.
- Text rules found zero private-key headers, AWS access-key IDs or JWT shapes.
  The only provider-token pattern was the deliberate fake-secret regression
  constant at `tests/http/test_security_readiness.py:773`. Broader email,
  operational-locator and credential-assignment rules identify review candidates
  including test literals, source assignments, author metadata and recorded
  deployment details. No active credential was confirmed or tested for validity.
- `Dockerfile` copies the filtered context; `.dockerignore` excludes course
  PDFs/docs/secrets/databases/logs, but not `.agents/`, `.playwright-cli/` or
  `.scratch/` as directories. Eligible historical text/YAML/ZIP artifacts can
  enter that copy. No packaging edit or image inspection is claimed. Review
  context contents before release; coordinate verified packaging with ticket 04/51.
- Binary pixels, slide notes/text, PDF contents, learned-weight memorisation,
  complete participant provenance, entropy/encoded secrets, Git history and
  remote visibility were not certified. Gitleaks/TruffleHog are not installed.
  The report records concrete owner actions; deletion/history rewriting/live
  rotation remain separately and explicitly gated.

#### Executed validation

| Command/check | Result and evidence |
| --- | --- |
| `git ls-files -z` with metadata/text-rule audit | 865 tracked paths; 849 text files checked, sixteen binary paths inventoried without content certification. Exit 0; temporary implementation `/private/tmp/ticket03-audit.py`, starting hashes and rule locations `/private/tmp/ticket03-inventory.json`, summary `/private/tmp/ticket03-inventory-summary.log`. Durable redacted inventory linked above. |
| `git ls-files .env .streamlit/secrets.toml data .files output` | Exit 0, no tracked paths. `git check-ignore --no-index` confirms existing ignore rules for private paths and a tracked browser-snapshot name; ignoring does not untrack it. No ignored private files were read. |
| `.venv/bin/python -m pytest -q -o addopts='' tests/http/test_security_readiness.py tests/domain/test_retrieval_question_set.py tests/domain/test_retrieval_gate_message_set.py tests/scripts/test_extra_messages.py` | Exit 0, **104 passed**, six warnings, 12.46 s. `/private/tmp/ticket03-focused.log`. Public ownership/error/log contracts, corpus fixture schema/provenance and refusal/redaction of non-synthetic extra messages; deterministic adapters and disposable storage. |
| `sh scripts/build.sh` | Exit 0: TypeScript/Vite, **30 Vitest tests/four files**, offline OpenAPI/client drift checks, compileall and the full **3,210-test mock Python suite** reached 100% without failures. `/private/tmp/ticket03-build.log`. Double-quiet pytest suppresses its numeric summary; separate collection establishes the count. |
| `.venv/bin/python -m pytest --collect-only -q -o addopts='' -rs` | Exit 0; **3,210 collected** in 2.49 s. Optional module skip at `tests/domain/test_strands_first_cycle_middleware.py:16`: `strands` absent. `/private/tmp/ticket03-collection.log`. |
| `.venv/bin/ruff check . --output-format json` | Exit 0, `[]`; `/private/tmp/ticket03-ruff.json`. No ignore/config changes. |
| Documentation/evidence/preservation checks | Local Markdown targets in the affected guides/report resolve; inventory JSON parses, category/extension totals and referenced paths validate. Starting SHA-256 comparison confirms all 865 original tracked files unchanged except the three intended guide/ledger updates. `git diff --check` passes. No application/test/config artifact changed in this ticket. |

Existing dependency/HTTPX/SWIG deprecation and Vite `use client` warnings remain
non-failing. No new desktop/mobile/startup claim: this documentation-only audit
retains ticket 01/02's disposable startup, citations, streaming, explicit
confirmation and actual process-restart evidence. Full applicable mock checks
were rerun above. No new live/cloud, image, capacity, cost, comprehensive secret
scanner or static-typing claim follows.

#### Compatibility, rollback and next exact action

No schema, API, saved-data, generated-client, runtime or deployment change and
no migration. Rollback is limited to the audit documents/evidence, guide links,
ledger entry and checklist; user artifacts and credentials need no rollback.
Local audit acceptance does not resolve course rights, binary/provenance review
or authorize publication. These risks remain in the report for the final
release gate; they do not block independent local deployment-record work.

**Next exact action:** start exactly one fresh writer for
`.scratch/architecture-completion/issues/04-reconcile-deployment-and-safety-records.md`
in this same checkout; ticket 01 supplies its dependency acceptance. Prepare the
nonsecret manifest and Mantle publication/session-rollover/blocked-output
verification procedure, distinguishing repository defaults, last recorded and
actually verified live state. Preserve the provisional-output fix. Carry the
ticket 01 local Caddy/bootstrap parity gap and this audit's build-context finding
into review; do not deploy, rotate sessions, publish runtime versions or execute
billable live checks. No GitHub issue was changed or closed.

### Local completion ticket 02 — lint and collection blockers (2026-11-24 SGT)

**Local acceptance complete; live release gates remain open.** Reproduced and
cleared all ten configured Ruff findings without ignores or exclusions. Public
application behavior, compatibility façades, `tests/__init__.py` and the bare
helper imports in `tests/conftest.py` are preserved. No behavior correction was
needed, so the approved TDD contract used reproduction and existing regressions
instead of a fabricated red test. Triage remains `ready-for-agent`.

Starting revision/branch remains `4f12995` /
`improvement/architecture-responsiveness`. All ticket 01 and publication changes
were preserved. No staging, commit, push, worktree, deployment, live data change
or paid application call occurred.

#### Changes and diagnosed build failure

- `.agents/tasks/phase3d-work/sol-teacher/run.py`: split imports, remove unused
  imports, expand the one-line conditional and replace the assigned lambda with
  a typed function. A local import helper preserves the offline guard before
  importing Laya. Did not run training or overwrite its saved artifacts.
- `backend/coaching/streaming.py`: use a separate terminal-error local, retaining
  the existing cancellation precedence, discard ordering and error event.
- `tests/browser/project_brief_app.py` and `reply_streaming_fixture.py`: local
  application factories retain late application imports after the scripted
  provider installation/disposable-workspace guard, removing E402 without
  moving side-effecting application initialization before those prerequisites.
- `tests/domain/test_gemma_native_json.py`: split the semicolon statement.
- `frontend/README.md` and `docs/TESTING.md`: document dependency repair and
  separate Ruff/build/collection checks. This ledger and the local ticket 02
  checklist record acceptance; no GitHub issue was changed.

The client failure was **installed dependency contamination**, not checked-in
generated-source drift. A diagnostic generation into
`/private/tmp/ticket02-generated-before` contained the correct 16 files plus
12 numbered ` 3.gen.ts` copies in `client/` and `core/`. `sdk.gen.ts` matched.
The installed Hey API package also contained numbered duplicates; its
`generateClientBundle` recursively copies the transport bundle. The console's
“4 files” counts primary generated files and omits those copied bundle files.
`npm ci --offline --ignore-scripts --prefix frontend` rebuilt dependencies from
the unchanged lockfile (189 packages added; reported zero vulnerabilities).
The unchanged checker then passed. No generator filtering, comparison weakening,
manual generated-file edits or manifest/lockfile changes were needed.

#### Executed validation

| Command/check | Result and evidence |
| --- | --- |
| `.venv/bin/ruff check . --output-format json` before edits | Exit 1; same ten findings in five files as ticket 01. `/private/tmp/ticket02-ruff-before.json`. |
| `npm run api:check --prefix frontend` before repair | Exit 1; reproduced client drift. `/private/tmp/ticket02-client-before.log`. Diagnostic output compared against checked-in source before repair. |
| `.venv/bin/python -m pytest -q tests/http/test_reader_conversation.py tests/http/test_turn_lifecycle.py tests/domain/test_reply_streaming.py tests/domain/test_gemma_native_json.py` | Exit 0; 46 tests passed. `/private/tmp/ticket02-focused.log`. Covers stop/save races, owner scope, normal/revised/replayed streaming and native JSON. |
| `npm ci --offline --ignore-scripts --prefix frontend`, then `npm run api:check --prefix frontend` | Exit 0 for both. `/private/tmp/ticket02-npm-ci.log`, `/private/tmp/ticket02-client-after.log`. |
| `.venv/bin/python -m pytest --collect-only -o addopts='' -q -rs` | Exit 0; **3,210 collected** in 2.82 s. One optional module skip: `tests/domain/test_strands_first_cycle_middleware.py:16`, `strands` absent. `/private/tmp/ticket02-collection.log`. |
| `sh scripts/build.sh` | Exit 0: TypeScript/Vite production build, **30 Vitest tests in four files**, offline OpenAPI and generated-client drift, compileall, and full **3,210-test mock pytest run** reached 100% with no failures. `/private/tmp/ticket02-build.log`. Double-quiet pytest suppresses the numeric terminal summary; separate collection establishes the count. |
| `.venv/bin/ruff check . --output-format json` after changes | Exit 0, `[]`; `/private/tmp/ticket02-ruff-after.json`. No new suppression/config exclusion. |
| `PYTHONPYCACHEPREFIX=/private/tmp/co-design-pycache .venv/bin/python -m compileall -q .agents/tasks/phase3d-work/sol-teacher/run.py` | Exit 0; supplements the build's application/test compilation. Initial invocation without redirected cache was denied writing `__pycache__` under `.agents`; corrected to the documented temporary cache. |
| Shell syntax and preserved files | `sh -n scripts/start.sh scripts/build.sh scripts/start_prod.sh scripts/deploy_ecr.sh scripts/browser_e2e_smoke.sh` passed. `git diff --exit-code -- tests/__init__.py tests/conftest.py frontend/package-lock.json frontend/src/api/generated` passed; these files are unchanged. `git diff --check` passed. |

Disposable public HTTP smoke also passed through both edited fixture entrypoints:
`PYTHONPATH=. .venv/bin/python /private/tmp/ticket02-smoke.py`, output in
`/private/tmp/ticket02-smoke.log`, workspace
`/private/tmp/ticket02-smoke-rzeokc48`. Both Uvicorn fixtures started, the built
frontend returned 200, explicit Guest entry and a streamed project turn saved two
messages, and public bootstrap/messages were identical after a real API process
restart. The scripted-brief fixture also reopened that saved state. All owned
child processes were stopped. The sandbox initially denied loopback binding;
approved escalation enabled the probe. The first harness used an unrecognized
public-origin variable and correctly received 403; setting the repository's
`CO_DESIGN_PUBLIC_API_URL` resolved this harness error without application changes.
No new browser-layout claim: there are no presentation edits; ticket 01's
desktop/mobile/citations/confirmation evidence and the full regression suite
remain the applicable compatibility coverage.

#### Compatibility, remaining risks and next action

No schema, API, generated contract, provider behavior or saved-data migration.
Rollback is limited to these source/documentation edits; no database rollback is
needed. Dependency reinstall changes only ignored installed packages and is
reproducible from the unchanged lockfile. Full tests include existing migration,
restart, citations, graph inspection and confirmed-stage contracts; private
developer databases were never opened. Python/HTTPX/LangChain deprecation warnings
and Vite's ignored React Query `use client` directives remain non-failing.
Static typing is not configured (`mypy` absent); no frontend lint script exists.
No claim of remote CI, Docker/ARM64, live Cognito/DSQL/Guardrail publication,
capacity or cost verification follows from this local acceptance.

**Next exact action:** start the fresh writer for
`.scratch/architecture-completion/issues/03-audit-repository-privacy.md` in this
same checkout. Ticket 01 supplies its dependency acceptance. Inventory tracked
artifacts read-only first; report categories/actionable locations without private
content, deletion, history rewriting or credential rotation. Other independent
frontier tickets remain available, but no dependent feature is declared complete.

### Local completion ticket 01 — fresh baseline (2026-11-24 SGT)

**Local acceptance complete; application release gates remain open.** This phase
reproduced the baseline and recorded gaps; it changed no application behavior.
Ticket statuses remain `ready-for-agent` (triage). Ticket 02 is the lowest-numbered
eligible unfinished ticket; tickets 03–05, 07–08, 10–13, 35, 37–38 are also
independent frontier work. No dependent ticket is declared implemented by this audit.

Starting revision: `4f12995afbfba4c5c975ad12eb9874fcd4cfea39`, branch
`improvement/architecture-responsiveness`. Initial `git status --short --branch`
contained modified `docs/CONTRIBUTING.md`, `docs/IMPLEMENTATION_STATUS.md`,
`docs/README.md` and untracked `.scratch/`; all were preserved. No worktree,
staging, commit, push, deployment, live data access or paid call occurred.

#### Complete build, collection and lint checks

Fresh commands and results (historical results elsewhere are not this run):

| Command | Fresh result |
| --- | --- |
| `sh scripts/build.sh > /private/tmp/ticket01-build.log 2>&1` | **Failed** at `npm run api:check --prefix frontend`: generated reader client drift. React TypeScript/Vite build, 30 Vitest tests across four files, and offline OpenAPI check passed first. Compile/pytest were not reached by this invocation. Vite reported ignored React Query `use client` directives. |
| `.venv/bin/python -m pytest -q > /private/tmp/ticket01-pytest.log 2>&1` | Exit 0, **3,210 passed**, one module skipped during collection (`strands` not installed). Dependency deprecation warnings from LangChain, websockets/Uvicorn and HTTPX. |
| `.venv/bin/python -m pytest --collect-only -o addopts='' -q -rs > /private/tmp/ticket01-collection-skips.log 2>&1` | 3,210 tests collected in 2.74 s; exact optional skip: `tests/domain/test_strands_first_cycle_middleware.py:16`, missing `strands`. This confirmed the skip hidden by the double-quiet full-run configuration. Initial collect-only without `-rs` also passed. |
| `PYTHONPYCACHEPREFIX=/private/tmp/co-design-pycache .venv/bin/python -m compileall -q backend ui streamlit_app.py tests scripts agentcore_runtime` | Exit 0. |
| `.venv/bin/ruff check . --output-format json > /private/tmp/ticket01-ruff.json` | Exit 1, **10 findings in five files**, inventory below. No fixes or ignores applied. |
| `git diff --check` | Passed again after ledger/probe/measurement edits. |

Installed tools: Python 3.12.7 in `.venv`, Node v22.23.2, npm 10.9.8,
Ruff 0.11.13, Caddy v2.11.4, cached Playwright CLI and browser. No configured
frontend lint script or Python static-type gate; `mypy` is absent. No claim that
those checks passed. The Playwright wrapper attempted npm registry access and
failed DNS (`ENOTFOUND`); the already-installed CLI worked directly, without an
install: `node /Users/kaiming/.npm/_npx/31e32ef8478fbf80/node_modules/@playwright/cli/playwright-cli.js`.
Call that executable `PW` below. Restricted loopback binding/HTTP initially failed;
authorized sandbox escalation allowed the same disposable commands to run.

| File | Line: rule(s) |
| --- | --- |
| `.agents/tasks/phase3d-work/sol-teacher/run.py` | 1: E401 and two F401; 12: E402; 16: E701; 64: E731 |
| `backend/coaching/streaming.py` | 112: F841 |
| `tests/browser/project_brief_app.py` | 43: E402 |
| `tests/browser/reply_streaming_fixture.py` | 30: E402 |
| `tests/domain/test_gemma_native_json.py` | 51: E702 |

The generated source inventory has 16 files, matching the tracked count. The
checker produced four generated files before its content/inventory comparison
failed; the cause has not been fixed or assumed to be the earlier duplicate-file
problem. Ticket 02 must reproduce/diagnose this gate as well as lint. One observed
failure is sufficient baseline evidence; no repeated speculative retry occurred.

#### Disposable startup, browser and restart checks

Used `/private/tmp/codesign-ticket01`, separate SQLite/files/workspaces/empty
lecture directory; never a developer database. The launch environment is retained
at `/private/tmp/ticket01-env.sh`. Reproduce from the
[isolated Summary setup](TESTING.md#saved-summary-browser-regression-30), with
`APP_ENV=development`, `PYTHON_DOTENV_DISABLED=1`, `COURSE_MATERIAL_SYNC_ENABLED=false`,
empty `KNOWLEDGE_BASE_ID`, `COURSE_MATERIALS_BUCKET`, `AGENTCORE_RUNTIME_ARN`,
`LOCAL_COURSE_INTENT_CHECKPOINT`, `LOCAL_COURSE_INTENT_LEARNER_BUNDLE`,
`LOCAL_COURSE_INTENT_FIRST_TURN_THRESHOLD`, `GENERATION_ADMISSION_POLICY` and
`OPENAI_API_KEY`; use mock/SQLite/local, Guest enabled, auto-advance/stage-selection
false, allowance 120 RPM and all paths under the new temporary root. Start:

```sh
PYTHONPATH=. .venv/bin/python -m uvicorn tests.browser.reply_streaming_fixture:app --host 127.0.0.1 --port 8093
.venv/bin/python -m streamlit run streamlit_app.py --server.address 127.0.0.1 --server.port 8593 --server.baseUrlPath streamlit --server.headless true
sed -e 's/8080/8193/g' -e 's/8000/8093/g' -e 's/8501/8593/g' Caddyfile.local > /private/tmp/ticket01-Caddyfile
caddy run --config /private/tmp/ticket01-Caddyfile --adapter caddyfile
```

The existing relay preserves real mock events and only delays reply fragments;
GETs are not delayed by it. Student browser origin was direct same-origin FastAPI
on 8093. Ready returned 200 with mock/SQLite/local and sync disabled; Streamlit
health on 8593 returned 200; the unchanged local edge access guard at
`8193/streamlit/` returned 403 signed out. The local edge lacks the bootstrap
allowlist present in the production edge: direct-origin results do **not** prove
local proxy parity. Reconcile in ticket 04 and cover exact routes in later features.
Authenticated lecturer API/research and Streamlit AppTest journeys passed in the
full suite using deterministic external identity/client substitutes. No real
Cognito login or authenticated lecturer browser session is claimed.

Executed with `PW -s=ticket01 open http://127.0.0.1:8093 --headed`, then
`PW -s=ticket01 run-code --filename PATH`:

| PATH / sequence | Observed outcome |
| --- | --- |
| `tests/browser/stage_review_summary.js` | Five-stage saved feedback, wording/order, Facione tips/practice, keyboard tabs, reload, no Review writes and clean monitored console passed at 1440/390 px. Screenshots inspected at both widths. |
| `tests/browser/review_restart.js`, stop API PID 17575 with TERM, restart same command/database, run script again without browser reload between calls | Public project, transcript and bookmarks identical after real process restart; selected Summary and saved Review restored on reload. |
| `tests/browser/baseline_citations.js` | Synthetic `baseline.txt` uploaded through reader HTTP, real local retrieval returned `[S1]`, exact saved excerpt and original bytes matched; exact-key receipt equalled saved `done`, exactly two message rows; rendered citation excerpt opened. |
| `tests/browser/workspace_loading.js` | All six startup/open trial pairs completed; raw aggregate observations retained below. |
| `tests/browser/baseline_stage_confirmation.js` | Two project turns left stage at Problem identification with pending proposal; visible Move to Concept generation confirmed; saved stage survived reload. |
| temporary copy of `tests/browser/real_reply_streaming.js` replacing 8096 with 8093 | Growing normal and revised mock previews, validated save/reload, one active revised exchange and separate draft preservation passed. |
| `tests/browser/identity_inflight.js` | Owner switch aborted generation, hid old work, rejected late output and never replayed the write. |

The two small baseline browser probes are retained as reusable manual public-journey
checks, not new behavior or a fabricated red/green cycle. Synthetic source and
confirmation assertions ran before retaining the same code with module comments.
Raw command outputs are `/private/tmp/ticket01-{summary,restart-before,restart-after,citations,stage,streaming,identity,loading}.log`;
API/Streamlit/Caddy logs share that prefix. Screenshots are ignored under
`output/playwright/summary-30/`. Initial signed-out bootstrap/session/auth HTTP 401s
were expected; the Summary regression's monitored post-entry console was clean.
No browser exception was reported by the executed scripts. All owned browser/server
processes were stopped at handoff. These are deterministic engineering checks,
not model semantic quality, live identity, safety publication or capacity evidence.

Saved-data compatibility is fresh fixture evidence in the full suite:
`tests/persistence/test_student_store.py` covers legacy workspace copying,
camel-case user/OAuth migration, split-owner repair and notebook FK repair without
loss; `tests/scripts/test_reset_learning_data.py` covers recoverable backup and
account preservation. `tests/http/test_reader_bootstrap.py` covers Guest isolation
and restart. Real disposable process restart adds current saved-state evidence.
No private existing database was opened to claim compatibility.

#### Reproducible startup and chat-opening baseline

[Raw observations and environment](examples/performance/architecture-ticket01-2026-11-24.json)
retain three trials per input, collected after pytest completed, without another
suite running. Existing harness clears selected keys, drains prior reads, reloads,
waits for notebook visibility, then opens an empty synthetic chat. This run had
existing synthetic Guest work. Startup observed bootstrap + session + project
(**three** reader requests in every trial), versus historical two. Chat opening
remained **nine** in every trial. The extra startup project read requires follow-up;
do not call the historical two-request count freshly reproduced.

| Synthetic per-reader delay | Startup visible ms (trials; median) | Open visible ms (trials; median) |
| --- | --- | --- |
| 0 ms | 85, 83, 74; **83** | 61, 57, 56; **57** |
| 100 ms | 331, 328, 326; **328** | 305, 321, 313; **313** |

Historical bootstrap evidence was 74/338 ms visible startup and two reader reads;
open was about 308 ms with 100 ms input. Differences are descriptive, not a fair
before/after improvement claim. `settledMs` for open includes the harness's 800 ms
drain and is not navigation latency. No live RTT/provider/DSQL/80-user inference.

#### All 101 source sections: owner, current evidence and remaining work

This is an exhaustive section-range map to the approved pack (not invented
per-section titles). **Verified baseline** refers only to evidence above;
**pending** means the programme requirement remains incomplete. Source ranges are
non-overlapping and cover 1–101 exactly. The linked spec and ticket files retain
the detailed acceptance language; existing implementations do not unlock future
dependencies without their ticket acceptance evidence.

| Source sections | Primary ticket owners | Current source/evidence | Status and remaining acceptance |
| --- | --- | --- | --- |
| 1–5 | 01, 04, 53; execution contract | This entry; `SPEC.md`; architecture/glossary | Baseline verified; manifest and final comparison pending. |
| 6–8 | 07–13; 15–36, 50, 52 for new contracts | `frontend/src/api/`, Query; bootstrap HTTP tests; loading JSON | Partial existing contracts verified; generated drift red, resource REST/Query/aggregation pending. |
| 9–11 | 06, 14, 43 | `Conversation.tsx`, NDJSON browser regressions | Existing lifecycle verified; extraction, URL routing and editor performance pending. |
| 12–22 | 20–24, 44 | Canvas requirements in approved spec | Pending persisted, usable, versioned, accessible canvas. |
| 23–29 | 25–28, 34, 42 | Existing coach/provider authority and source isolation tests | Pending canvas evidence, selected coaching and reviewed suggestions. |
| 30–38 | 15–19, 29, 44 | Artifact requirements in approved spec | Pending editor/types, persistence, conflicts/history, exports and reviewed feedback. |
| 39–43 | 25–31, 52–53 | Existing chat/source provenance baseline | Pending connected artifact/canvas/chat transfers and references. |
| 44–49 | 12, 32–34 | `learning_service.py`, reader project tests; confirmation/Review browser runs | Existing authority verified; actionable requirements, recaps and persisted-work resume pending. |
| 50–52 | 19, 24, 52 | Existing source original download verified | Pending artifact/canvas/selected coursework exports. |
| 53–55 | 15, 17–18, 20, 22–23, 33, 35–36, 38 | Legacy SQLite, reset backup and DSQL fake-contract suites | Existing fixtures verified; new additive resource schemas, revision durability and DSQL experiment pending. |
| 56 | 39 | Existing admission/load probe | Pending measured backend concurrency changes. |
| 57–64 | 06, 37, 40–41 | Runtime/provider safety and reply-stream tests in full suite | Existing mock contracts verified; tracing/prompt/cache/model/runtime experiments pending. |
| 65–66 | 42 | Local source grounding and existing retrieval tests | Existing deterministic retrieval verified; new workspace corpus/evaluation pending. |
| 67 | 35–36 | Existing Deep Review tests; process-local worker limitation retained | Pending durable leases/restart, cancellation and ambiguity. |
| 68–72 | 14, 16, 21, 43–44 | Inspected desktop/mobile Summary; React production assets | Existing narrow layout verified; accessible new authoring/routing/performance pending. |
| 73–78 | 03, 25, 37, 45; per-feature controls | Ownership/security suites; in-flight owner-switch browser check | Existing tested isolation verified; privacy audit, new references, tracing and hostile-content checks pending. |
| 79–84 | 02, 05, 46; per-feature TDD | 3,210 Python + 30 frontend passes; compile; 10 lint findings; client drift | Baseline verified; full gate red, browser CI and expanded deterministic coverage pending. |
| 85–89 | 04, 47, 51 | Protected local stack; existing reset/restore fixtures | Baseline only; manifest, Mantle publication procedure and complete workspace release/restore rehearsal pending. |
| 90–92 | 48–49 | Bounded navigation JSON; historical mock load evidence remains historical | Pending mixed 1–80 workloads and evidenced SGD operating costs/region assessment. |
| 93–94 | 50; retained lecturer checks | Professor API/research and AppTest full-suite cases; protected stack | Existing deterministic lecturer checks verified; consent-bound aggregate extension and live identity pending. |
| 95–97 | 01, 53; execution contract | This ledger and dependency pack | Baseline handoff verified; incremental/final delivery evidence pending. |
| 98–101 | 45–53; per-ticket acceptance | Fresh baseline tests and limitations above | Pending full integrated authoring/security/restore/report and separately gated live release verification. |

#### Compatibility, rollback, risks and next exact action

Handoff checks: `node --check` passed for both retained probes; local file links resolved, all 101 source sections were checked for exact non-overlapping coverage, the measurement JSON has 12 rows, and Git whitespace passed.

Files changed by ticket 01: this ledger, `docs/TESTING.md`, two baseline browser
probes, the aggregate performance JSON, and ticket 01's local checklist. Prior
publication changes remain intact. No schema/API/runtime dependency or saved-data
migration; rollback removes only this phase's docs/probes/measurement additions,
without reverting prior publication or restoring a database.

Remaining blockers belong to their designated tickets: generated-client drift and
10 Ruff findings (02); local-edge bootstrap mismatch/deployment/safety records (04);
startup extra project read/9-call open (09 and later connectivity). Missing optional
Strands extras limits the runtime middleware integration gate. Live Mantle/runtime
publication/session rollover, registered Cognito browser verification, DSQL/AWS
recovery, lecturer study/accessibility breadth, classroom throughput and gross/
post-credit S$30 feasibility remain unverified; no paid tests authorized here.

Next exact action: **local ticket 02 — Clear lint and collection blockers**, at
`.scratch/architecture-completion/issues/02-clear-lint-and-collection-blockers.md`,
in one fresh `gpt-6.1-sol` writer on the same checkout. Read this entry first;
reproduce generated-client drift and all configured lint findings, preserve public
behavior/test-package binding, then run applicable full gates. No blocker here
required two attempts at the same concrete implementation failure; Astra escalation
was therefore not triggered. Ticket 01 is complete as baseline evidence, not as a
claim that the full build or programme is green.


### Approved local architecture-completion ticket pack (2026-11-24 SGT)

The user approved the specification's testing seams and 53-ticket breakdown,
requested local publication, then authorized TDD implementation with fresh
context per ticket. The [local execution pack](../.scratch/architecture-completion/README.md)
contains the approved spec, dependency/coverage index and one `ready-for-agent`
file per ticket. These are local numbers, distinct from earlier rollout tickets
and GitHub issue numbers. The contribution guide and docs index link the pack;
no GitHub issue or parent issue was changed.

The approved primary seam is the student browser through production-built React,
real same-origin FastAPI and disposable persistent SQLite with deterministic
external adapters. Supporting public API, storage/worker and runtime/provider
contracts cover ownership, SQLite/DSQL OCC, migrations, leases/restart and safety.
Behavior changes must use one observed red test followed by its minimal green
implementation; baseline and documentation work must not manufacture failing
tests for unchanged behavior. All existing data, source/citation, streaming,
confirmation and lecturer requirements remain acceptance gates.

Validation executed for this publication: all 53 ticket templates and acceptance
checklists, numeric order, backward-only dependencies, final-gate reachability,
approved seam wording, absence of implementation paths/snippets in ticket bodies,
and local links from the pack/docs/contribution guide passed. Git whitespace
checks passed. No application test suite, browser run or implementation phase is
claimed by this documentation-only publication.

Files added: `.scratch/architecture-completion/SPEC.md`, its `README.md` and 53
individual `issues/` documents. Files updated: docs index, contribution guide and
this status. No API/schema/runtime/data migration or deployment change; rollback
is documentation-only. No staging, commit, live call or deployment occurred.

Next exact action: start local ticket **01 — Reproduce the baseline and establish
coverage** in a fresh client-selected `gpt-6.1-sol` writer session, reading its
ticket and the pack's execution contract. Implementation has not started. This
chat has no in-place context-reset tool; the requested fresh-session execution
route must be resolved before starting ticket work. No model switch or context
clear is claimed. Existing live safety/cost/capacity gates remain open.

### Review cleanup and pre-commit verification (2026-11-24 SGT)

Resolved the review's duplicate-SDK finding by removing the 16 untracked
`* 2.ts` copies from the generated source directory, retaining the canonical
16 files. The removed copies were backed up outside the repository. The local
installed generator also contained duplicate templates; a clean
`npm ci --ignore-scripts --prefix frontend` restored the unchanged lockfile's
dependency tree and reported zero npm audit vulnerabilities. No dependency
version or generated contract was changed by this cleanup.

`sh scripts/build.sh` then passed end to end: TypeScript/Vite, all 30 frontend
tests, offline schema consistency, generated-client inventory/content checks,
Python compilation and the complete mock pytest suite. Scoped Ruff, Caddy
validation and Git whitespace checks also passed. The existing full-repository
lint findings remain documented below. Changed-file credential-pattern and
private-path checks found no matches. No student data, live configuration or
runtime deployment was changed. Source-only rollback and the next Query-coverage
phase remain as described below.

### CDE2300 verified bootstrap and fewer startup requests (2026-11-24 SGT)

The user confirmed CDE2300 as the active course; the other course is a separate
copy. No curriculum, source corpus or course name was changed. Existing local
work on `improvement/architecture-responsiveness` is preserved.

`GET /api/v1/reader/bootstrap` now combines the existing verified session,
notebook-list and allowlisted preference projections under one reader-owner
dependency. It performs one bulk list read, includes no transcript/source body,
and makes no model call. The browser still performs a fresh session probe and
compares session/list/preferences owner IDs before showing private work. Expired
cookie renewal uses the existing auth path. WorkspaceTools consumes the already
verified initial preferences instead of immediately rereading them; later chat
navigation and mutations retain their existing checks. Query retention stays zero.

The same browser harness measured six clean-startup reader requests before and
two afterward in all three trials per delay. With a synthetic 100ms delay per
reader request, median visible startup moved from 823ms to 338ms; without injected
delay it moved from 77ms to 74ms. These small local samples are illustrative:
the baseline overlapped part of pytest and neither run isolated CPU/network.
Chat-opening request counts remain nine; no navigation speedup is claimed.
[Raw before/after observations](examples/performance/cde2300-bootstrap-2026-11-24.json)
and [method/limitations](operations/ARCHITECTURE_IMPROVEMENTS.md#cde2300-bootstrap-follow-up)
are retained. An early harness that mixed trailing SPA reads into later trials
was corrected before retaining the comparison.

Validation: full mock suite **3,209 passed, one optional skip**; frontend
**30 tests passed**. After adding the exact Caddy matcher regression, its focused
deployment/bootstrap suite passed **24 tests**. The security/reader/journey suite
passed **90 tests**. TypeScript/Vite, generated schema/client consistency,
compileall, scoped Ruff, Git whitespace and Caddy configuration validation passed.
Browser tests passed for a held bootstrap across Guest cookie change, account
switch during pending generation, initial saved name/theme, theme mutation/reload
and desktop/390px layout. Screenshots were inspected; no JS exceptions in the
preference regression. Full-repository lint's earlier findings remain outside
this milestone; no paid/live service or deployment validation was performed.

Changed files add the route/projection, shared preference helper, generated
bootstrap SDK, browser loader/preference handoff, exact Caddy GET allowlist,
contract/security/browser tests, benchmark JSON and linked guides. No database
migration or saved-data change is needed. Existing separate reader endpoints
and Streamlit remain compatible. Deployment must update backend, frontend and
Caddy together; an older edge will reject bootstrap. Source/asset/config rollback
requires no database restore. No commit or deployment was performed.

Next local phase: expand targeted Query coverage in `frontend/src/WorkspaceTools.tsx`
and source/bookmark loaders, with measured stale/retention policies, owner fencing,
mutation reconciliation and tests for pending reads at account switch. Keep stage
progress and generation explicit. The separately authorized Mantle safety rollout,
deployment manifest reconciliation, durable Deep Review, live cost/capacity and
previously tracked browser-artifact review remain open.

### Architecture baseline, generated reader contracts and Mantle safety (2026-11-24 SGT)

The initial local milestones of the comprehensive improvement request are on
`improvement/architecture-responsiveness`, from clean `improvement/combined-testing1`
at `8a449a7`. The [audit, decisions, measurements and remaining plan](operations/ARCHITECTURE_IMPROVEMENTS.md)
distinguish this work from the still-open broader programme.

Full test collection now succeeds: a repository test-package marker prevents an
installed `tests` package from shadowing shared eval helpers. The existing mock
load probe now reports nearest-rank p50/p90/p95/p99/max and error/rejection rates.
The retained synthetic 1/10/20/40/60/80-user baseline accepted all 211 turns with
zero failures/rejections. The 80-user row measured p95 1,130.2ms and 55.3 turns/s
on this Mac with mock inference and temporary SQLite. It is not AWS sizing or
proof of live classroom capacity.

Three existing reader GETs now have stable operation IDs and a deterministic,
allowlisted offline OpenAPI export. Hey API generates the session/list/message
page client while preserving cookies, renewal, owner/revision checks, AbortSignal,
no-store and the explicit NDJSON lifecycle. Query keys/defaults are centralized;
private retention remains zero. CI/local build checks export and generated-client
drift and runs Vitest. Chat feedback now shows actual operation states with an
indeterminate track instead of fabricated percentages or an inferred cold start.

The audit reproduced a Mantle/Gemma output-safety gap: provisional text could
escape before the separate output guardrail. That runtime path now forwards no
preview fragments; only the checked final result continues to the existing save
protocol. Internal first-model-text telemetry remains; no extra provider or safety
calls are introduced. This fix requires a separately authorized runtime publication
and fresh application session generation to protect an existing deployment.

Validation: **3,206 Python tests passed, one skipped**; **23 Vitest tests passed**.
The safety regression failed before the fix and the 176 focused runtime/provider/
streaming tests passed afterward. TypeScript/Vite build, compileall, targeted
Ruff, schema/client checks and shell syntax passed. Browser QA passed at 1440/390px
in light/dark and reduced motion, including save/reload, cancellation/discard,
no automatic generation replay, new-owner isolation and an account switch while
a generation request was pending. Screenshots were inspected. There were no JS
exceptions; HTTP console errors were expected signed-out checks and injected
failure. Disposable FastAPI health/readiness and Streamlit health returned 200.
The npm dependency tree reported zero advisories with the patched YAML override.
Full-repository Ruff remains red on 10 pre-existing findings across five files
whose contents match HEAD; scoped Ruff passed. The audit lists these locations.
No full-lint or green-CI claim is made.

Changes cover the reader route metadata, runtime preview gate, frontend adapter/
generated SDK/Query/activity/parser, export/build/CI/load tooling, tests and linked
guides. No student schema, API method/path, saved data, source or learning migration
is required. Rollback is source/lockfile rebuild only; preserve all data. Reverting
the Mantle gate reintroduces the safety risk. No commit, live configuration change,
billable test or deployment was performed.

Open risks: Compose/runtime record drift; old deployed runtime safety until rollout;
process-local Deep Review restart loss; unreviewed previously tracked browser
artifacts; unmeasured live cost, latency and
80-student capacity. The next exact local phase starts in `frontend/src/useReader.ts`
and App preference/resource loaders: measure the authenticated startup/navigation
waterfall, then benchmark resource-specific Query policies and bootstrap aggregation
with identity-race tests before adopting them. The live safety rollout remains a
separate authorization gate. Do not treat the earlier estimated-percentage entry
below as the current UI behavior.

### React Query, Tailwind, and estimated reply progress implemented locally (2026-11-24 SGT)

The React frontend now provides TanStack Query 5 for owner-scoped notebook-list
request management. Lists remain immediately stale, unused query data has zero
retention, and the client is cleared at session reset and unmount. Older reads
are cancelled before mutation reconciliation. Focus/reconnect refetch and
automatic query/mutation retries are disabled. The existing authenticated
read checks, streaming sends, and durable-receipt recovery still own the chat
lifecycle.

Tailwind 4 is integrated through Vite with theme/utilities imports and no
Preflight reset. Existing CSS retains the application's appearance. A compact
feedback component beneath the composer shows estimated progress, approaching
65% while waiting, 90% on reply deltas, 98% while saving, and 100% on confirmed
saved completion. A conditional AWS startup explanation appears after six
seconds without reply text. Discards return to indeterminate feedback;
failures/cancellation clear it. Reduced motion disables animation, and timers
clean up when the request or component ends.

Files include the frontend manifest/lock, Vite config, Query provider and reader
hook, `ChatProgress.tsx`, Conversation integration, Tailwind/CSS, frontend
guides, and the delayed mock/browser regression. TypeScript and Vite build
passed; Vite reports ignored third-party `use client` directives in this static
SPA bundle. The targeted ownership/reader/streaming suite passed 32 tests.
The applicable backend, HTTP, persistence, architecture, and deployment suite
passed 2,482 tests with one skipped. Mock browser checks passed for
waiting/writing/saving/completion,
saved reload, failure without replay, cancellation/discard, separate owners,
desktop/mobile light/dark and reduced motion. The pre-existing streaming/edit
regression also passed. Screenshots were inspected at 1440 and 390 px.

No schema migration is required. The disposable mock workspace contains only
synthetic chats. Production deployment is a separate phase.
Roll back this frontend change by
restoring the touched frontend source and dependencies without restoring any
database. Next validate the built frontend in an authorized deployment, using
the mock browser recipe in [testing](TESTING.md).

### AgentCore platform V1 restored in production (2026-11-24 SGT)

Production is pinned to the `GemmaStable37` endpoint, which serves V1
deployment 38. The app uses a new session generation to start requests on the
restored runtime. Host readiness passed, production health returned `ok`, and
the workspace returned HTTP 200. Verification made no new model calls.
Gemma and Sonnet remain the configured Fast Chat and Deep Review models.
`HaikuRollback36` is READY. `DEFAULT` points to V2 deployment 39 for
the prior comparison; keep production on the pinned V1 alias during any
follow-up research. The waiting experience is deferred at the user's request.

### AgentCore platform V2 comparison on deployment 39 (2026-11-24 SGT)

Production Fast Chat moved to AgentCore V2 consumption pricing in Oregon
using the deployed Gemma artifact and new session generation. The host and
public readiness checks passed. The platform change requires no data migration.
The existing `GemmaStable37` alias pins the known-good V1 deployment 38 for
rollback, and `HaikuRollback36` remains available. See the
[live comparison and rollback evidence](operations/AGENTCORE_V2_LIVE_COMPARISON.md).

The matched browser comparison saved all 32 Design Coaching turns. Cold
median first visible text moved from 11.36 s to 9.63 s. Cold p95 moved from
12.85 s to 33.99 s with eight observations per platform. The slowest V2
request waited 27.67 s for reply text inside the runtime, and maximum AWS
platform overhead was 1.76 s across the V2 wave. A guarded citation smoke,
private synthetic PDF upload/citation/receipt check, and 2,482 applicable
offline tests passed, with one offline test skipped. The pilot used 54 of 60
approved live chat turns. The two-second cold p95 target did not pass and
80 concurrent live student generations remain unverified.

The first 11 complete minutes of V2 metering averaged approximately 1.62 GB
per session after adjusting for one earlier V1 session on the endpoint.
Using the planning assumptions in the live comparison, two 80-student
classes project to S$6.15 at 60 minutes or S$9.00 at 90 minutes in AgentCore
compute. The full S$30 bill remains unverified. Next investigate the timing
inside the runtime, separating input safeguards and the Gemma call before
attributing the slow replies to either component.


### Gemma citation retry fixed; version 38 serving; bounded 80-request checks (2026-11-24 SGT)

**Behavior and cause:** the Strands 1.52 schema converter broadens defaulted,
omittable strings into nullable strings. Version37 therefore permitted a null
citation title that canonical Pydantic validation rejected, causing a recovery
model call. `gemma_responses.py` now consults original canonical output schemas,
resolves their local definitions and removes only SDK-invented nullability before
native strict-schema generation. Genuine nullable fields, including Q&A
recommendations, remain nullable. Application validation is unchanged. Unknown
output contracts fail closed. No retry suppression or acceptance of invalid
citations was used to conceal failures.

**Files:** `agentcore_runtime/gemma_responses.py`,
`tests/domain/test_gemma_native_json.py`, this status, provider/capacity guidance
and the [aggregate result artifact](examples/classroom-capacity/gemma-results-2026-11-24.json).
Other dirty baseline files, including the user's startup-script edit, were
preserved; no files were staged or committed. The regression was observed red
before the fix (the native citation schema accepted null); it now rejects null
citation strings while retaining valid empty/default strings and Q&A nulls.
An offline interleaved 80-stream test also verifies per-invoke reply/tool-ID
isolation on a cached model instance.

**Validation:** 94 focused tests passed. Applicable domain/HTTP/persistence/
architecture/deployment suite: **2,482 passed, one skipped**. Compileall and
`git diff --check` passed. This does not supersede the earlier full-repository
collection blocker. No UI code changed. Existing persistence/confirmed-stage
contracts were covered by the mock suite; the live check used no student data.

**Runtime check:** new version38 passed a synthetic citation-grounded Q&A through
AgentCore and its real input/output guardrails, with **one model cycle**, **no
structured-output recovery**, 154 stream frames, 6,366 input/154 output tokens.
Reply streaming began around2.663s; total completion was9.202s including cold
startup. Its temporary session was explicitly stopped. This verifies the
observed retry cause, not a population retry rate or a controlled speedup:
the earlier13.582s version37 probe had different multimodal input.

**80-request provider burst:** all80 direct Mantle calls passed canonical
Pydantic/citation/fact assertions, zero failures, no client retries. Requests
used the full canonical coaching prompt with synthetic source Q&A, fixed strict
schema, no history and at most512 output tokens each. p50 **3.442s**, p95
**32.319s**, max **42.262s**; wall42.274s. The direct provider burst excludes
AgentCore session startup, guardrails, FastAPI, persistence, source retrieval
and browsers. It is not proof of80 simultaneous end-to-end chat completions.
The long tail is measured; its cause has not been isolated.

**80 application sessions:** created80 independent synthetic Guest cookies
(eight setup workers), then barrier-released80 empty-workspace reads through
CloudFront/FastAPI/DSQL. All80 returned their empty owned notebook list; p50
**3.585s**, p95 **6.506s**, max **6.657s**. No notebooks, uploaded sources or
student content were created/changed. Synthetic Guest identities remain until
normal expiration; no account deletion or research-data reset was performed.
These reads do not exercise generation, retrieval, uploads, browser rendering,
long histories or save/recovery under an80-generation load.

**Deployment and rollback:** production stayed pinned to `GemmaStable37` while
DEFAULT38 was published and checked. Serving Compose now selects `DEFAULT`
with generation `20261124-gemma38-nullability`; host readiness passed. Deep
Review remains Sonnet4.6. New runtime artifact SHA256:
`3e75266a14320388d48ea0c26598a80787d434eae4eecafed3427a0a2e002c80`.
Only `gemma_responses.py` changed in the deployed version37 dependency/source
zip. No EC2 image, IAM policy, database schema or student data migration changed.
Haiku36 stays READY on `HaikuRollback36`; its existing executable rollback script
and old image/settings remain on EC2. `GemmaStable37` is also retained. The
pre-promotion Compose backup is on EC2 in `.gemma-nullability-20261124/`.
No rollback drill was run; no rollback was needed.

**Budget:** temporary artifacts from the prior session were cleared. The prior
reservation **US$0.5000952** and known model-token estimate **US$0.00895796** were
recovered from this recorded handoff without releasing any prior reservation.
New reservations: runtime smoke0.06, provider burst0.40, application reads0.02;
cumulative **US$0.9800952 of US$1**. Known cumulative successful model-token
estimates are **US$0.0813692**, excluding unknown failed-call usage and non-model
charges. Reservations include margin, not reconciled AWS billing or a hard
AWS spending control. Paid testing has stopped. The new explicit80-request
instruction superseded the older42-attempt comparison limit; the cumulative
US$1 ceiling remained. Aggregate evidence is now in the repository so its scope,
cost record and outcomes survive temporary-file cleanup.

**Risks / next exact action:**80-provider capacity and80-workspace-read capacity
passed separately, with a provider p95 above32s. Full80-generation application
capacity and sustainable S$30/month remain **unproven**. Next, use the
[classroom gate](operations/CLASSROOM_CAPACITY_GATE.md) to prepare a separately
funded, end-to-end80-student generation run with defined queue/total latency
criteria, bounded retries, known context sizes, saves/recovery, quotas and
session cleanup. Do not launch more paid tests under the closed allowance.



### Gemma native JSON fixed and deployed; Haiku rollback retained (2026-11-23 SGT)

**Behavior:** normal Fast Chat and the configured lightweight legacy roles now
serve `google.gemma-4-31b` through Mantle Responses in Oregon. Deep Review stays
on Sonnet 4.6. The new `agentcore_runtime/gemma_responses.py` adapter replaces
Gemma's unusable function-argument output with native strict JSON-schema text,
then translates incremental JSON into the same Strands validation-tool events.
Application parsing, citations, input/output ApplyGuardrail, source scope,
persistence and confirmed stage progression keep their existing boundaries.
Malformed, truncated and punctuation-only output fails before success. Request
state is local to each stream. The SDK-flattened nullable recommendation enum
now includes null, so Q&A can return no stage recommendation.

**Files:** runtime factory + new Gemma transport, production settings validator,
new transport regressions and existing runtime/config tests, the runtime README, this status and
[provider guidance](providers/MODEL_PROVIDERS.md#gemma-4-31b).
The user's local startup-script edit and existing browser artifacts were left
alone. No source commit or staging was performed.

**Validation:** 92 focused tests passed; the applicable domain/HTTP/persistence/
architecture/deployment suite passed **2,480 tests, one skipped**. Compileall and
`git diff --check` passed. The previously observed full-repository collection
blocker involving `tests.scripts` remains; this is not a full-repository pass.
The earlier disposable mock startup/restart checks passed. No browser interaction
or real uploaded student content was used in this release's live tests.

Full canonical-prompt, pinned-SDK checks passed for coaching/stay (3.758s), image
Q&A (2.253s), application-extracted PDF Q&A with citations (2.758s), and a small
native PDF (2.807s). Native PDF initially needed a filename ending `.pdf`; the
application's existing PDF extraction path is unchanged. A combined full-runtime
image/PDF check passed real input/output guardrails and application parsing in
5.915s, one model cycle, 166 streaming frames. Synthetic PDF facts were seven
visitors, a 120cm ramp and the missing wheelchair-user test. The simple image
check establishes colours/placement, not precision vision: the model called a
slightly rectangular shape a square.

**Published gate:** version **37**, same existing runtime ARN, passed a synthetic
combined image/PDF-facts check before promotion. It returned a grounded Q&A
reply, citation, null recommendation and 333 stream frames in **13.582s**, with
reply streaming around **3.349s**. It used two model cycles: the first citation
had a null title, rejected by Pydantic; the bounded existing recovery produced a
valid result. Do not describe this as consistently one-call or Haiku-equivalent
latency. Strict-schema citation nullability is the next cost/latency improvement.
This is functional compatibility evidence, not a broad pedagogy benchmark or an
80-student load test. Office-file, scanned-PDF/OCR and large-image parity remain
unmeasured.

**Rollout:** students stayed pinned to READY endpoint `HaikuRollback36` while
version 37 was published and tested. DEFAULT is now READY on **37**, the serving
app uses `DEFAULT` and generation `20261123-gemma37-nativejson`, and host health /
readiness plus the public workspace returned HTTP200. The new runtime package
SHA256 is `39ac244e27082d36f740e630f38468fbe23941559c2ad7608b9cf7121848f6a2`.
Dependencies remain the original vendored Linux ARM64/Python3.14 pins. The
runtime's Gemma prompt cache is disabled; no unsupported cache savings claimed.

The EC2 image is a minimal settings-validation patch over the existing release
`dc83707dccc6fb08e666bfc310d3d3e0d3aff07d`, not an image of the whole dirty local
checkout. `APP_GIT_SHA` remains that base revision; the additional image label
`org.codesign.patch.settings.sha256` is
`13f9376a10a2a88135a1808b7c95b18dfa9d0ca038a6feb53c1f4c6ea0feea90`.
The immutable local image ID is
`sha256:494edc4b0b58a6d4f3a1ebb5b2acb5163dd54804c155a2a1727f1407e95bee02`.
Only the provider/model-pair validation was patched in that app image; the
frontend and other backend code stay at the base release. The deployed runtime
contains the canonical runtime sources, including the Gemma adapter.

The EC2 application role denied ECR authorization, so no publishing permission
was added. The derived image remains on the host. A small credential-free rebuild
recipe is durably archived in the existing deployment bucket at
`app-patches/gemma37-rebuild-c740fa0418d31145.zip`, SHA256
`c740fa0418d31145a13d2d02547679824a6d9b2c1540b330827f6cc9300cab36`. It pins the original ECR base image by digest and reproduces the exact settings
patch. A replacement host needs a deployment identity authorized to pull that
base image; the application role cannot publish/pull via ECR authorization. The
running service and Haiku rollback are healthy despite this archival limit.

**Budget:** the original ledger was retained, with **39/42 attempts including a
four-attempt conservative reservation for the published invoke**. Known
successful model-token estimates total **US$0.00895796**; **US$0.5000952** is
reserved across all tests, including failed/unknown usage and guardrail margin,
within the approved US$1. These are estimates, not a reconciled AWS bill. No
further paid calls are planned. Runtime/infrastructure ongoing use after
promotion is separate from this test allowance.

**Compatibility and rollback:** no schema/data migration, student-data reset,
source/file replacement or IAM policy change. The changed identity already had
the required access, and the runtime role already had Mantle + ApplyGuardrail
permissions. Haiku **36** remains READY on `HaikuRollback36`. On EC2, the private
`/home/ubuntu/NUS-Codesign-Chatbot/.gemma-rollout-20261123/` holds the old Compose,
environment, image ID, settings, container inventory and executable `rollback.sh`.
Running that script via SSM restores the old app/environment and pins requests to
Haiku36 with a new session generation, without depending on DEFAULT. An operator
may then point DEFAULT back to36 with the control API. No rollback was needed;
restore artifacts were verified present, but a rollback drill was not run.

**Next exact action:** offline, tighten the provider's nullable citation fields
against the application schema without accepting null titles; add a regression
for the observed first-cycle failure. Re-evaluate with a bounded allowance before
publishing another version. Separately run the documented classroom capacity
and recovery gate before promising 80 simultaneous students or S$30/month.


### Gemma rejection traced to test schema; semantic tool-output blocker remains (2026-11-23 SGT)

Further diagnosis corrected the interpretation of the earlier HTTP400 tests:
the temporary harness sent `FastChatTurnOutput.model_json_schema()` directly,
whereas pinned Strands 1.52.0 uses `convert_pydantic_to_tool_spec`. The latter
resolves references and flattens the schema, removing root `$defs`, `if` and
`then`. The former requests were not evidence of actual SDK-schema rejection.
No individual JSON Schema keyword has been isolated as the service's cause.

One bounded call using the actual SDK-generated schema returned HTTP200 and a
Pydantic-valid coaching/stay function call, but its `response_text` was only
`":"`. A second bounded call with the full canonical production coaching
prompt (5,771 input tokens) reproduced that unusable reply in 2.291 seconds.
The simple-prompt call took 1.619 seconds. Neither is an acceptable coaching
answer despite syntactic validity. The failure is now a semantic tool-output
generation/serialization blocker; no inference about general response quality
or about which component produces the colon is established.

Retries of that path stopped after two evidence-based attempts. The prescribed
next route is an Astra investigation of minimal tool calls, Chat Completions
tool calling and native JSON-schema Responses, keeping application validation,
source scope and explicit stage confirmation. Client routing is manual; no
model switch or delegation occurred. The corrected diagnostic artifact is
`/private/tmp/oregon-multimodal-check/gemma-diagnosis.json`.

The shared ledger is **27/42 attempts**, approximately **US$0.00137662** in
known successful token charges and **US$0.077036** conservatively reserved
across all attempts. No runtime/app configuration, IAM, schema or student data
changed. Haiku remains live. The local Gemma candidate remains unpromoted.

### Live Gemma/Ministral modality checks; Haiku remains live (2026-11-23 SGT)

The user authorized checking actual Gemma 4 31B access and a Ministral 3 8B
fallback within US$1. Using the changed `default` identity in Oregon, Gemma
returned successful Responses API results for text, a synthetic image,
application-extracted PDF text and a small directly supplied PDF. PDF answers
correctly reported 7 visitors, a 120 cm ramp and the missing wheelchair-user
test, with the supplied source label. Image replies identified colours and
left/right placement, but called the slightly rectangular red shape a square;
this is a basic vision check, not a precision or OCR pass.

Gemma's plain-prompt coaching reply was relevant but wrapped JSON in Markdown.
Two requests using the full `FastChatTurnOutput` tool schema returned HTTP 400
(`task request was rejected by the target`), with forced and automatic tool
selection respectively. Those retries stopped. This demonstrates access and
basic modalities, not production structured-output compatibility. The concrete
Gemma schema/endpoint blocker needs the prescribed focused Astra diagnosis if
pursued; no delegation or model switch was performed here.

Ministral rejected the Mantle Responses route as unsupported, then succeeded
through its documented Bedrock Converse route. It returned a Pydantic-valid
`FastChatTurnOutput` tool call with coaching/stay, answered the image placement
question, and answered the PDF-extracted-text question accurately. Its native
Converse PDF request failed explicitly (`This model doesn't support documents`).
The app's existing PDF extraction/retrieval path is therefore the viable PDF
route for this candidate. A single structured reply is not proof of complete
pedagogy, streaming, guardrail or stage-transition parity.

The shared experiment ledger now records **25 of 42 attempts**, including the
earlier denied calls. Successful-call token charges total approximately
**US$0.00043532**, with **US$0.0709176** conservatively reserved across all
attempts; these are estimates, not an AWS billing reconciliation. No production
database, student file, Knowledge Base or AgentCore generation was used. No IAM
policy, runtime version, DEFAULT qualifier, app release or source commit was
changed. Haiku/Sonnet version 36 remains the recorded live baseline. Evidence
and synthetic fixtures are private temporary artifacts under
`/private/tmp/oregon-multimodal-check/`; the aggregate ledger is preserved.

**Next exact action:** choose between diagnosing the Gemma tool-schema request
and a full-prompt Ministral Converse candidate evaluation. Keep the current
Haiku runtime available. Before promotion, verify streaming, source citations,
guardrails, confirmed progression and restart/recovery on the actual application
path, and separately establish classroom capacity. No 80-student performance or
provider-quality ranking is established by these small direct-model checks.

### Model selection reconsidered; deployment held (2026-11-23 SGT)

The user asked to hold Gemma deployment and reassess actual provider choices.
No IAM policy write, runtime publication, DEFAULT move, app change or new paid
inference occurred. The changed `default` identity successfully read and backed
up the existing runtime and DEFAULT endpoint: **Haiku/Sonnet version 36,
READY**. The restricted sign-in identity remains denied those reads.

Read-only Oregon account checks returned authorized/available status for Nova
Lite, Nova 2 Lite, Ministral 3 8B/14B, Gemma 3 12B/27B, Nemotron 12B VL,
GPT-OSS-120B and Qwen3 Next. The regular text foundation-model catalog contained
97 entries and did not include Gemma 4; the separate Mantle `/v1/models` listing
contained 49 entries and did include Gemma 4 31B, 26B-A4B and E2B. Neither list
proves successful inference. No Qwen4 listing was found; Qwen3 variants are
distinct. Exact model/endpoint access must be tested before deployment rather
than inferred from console visibility or public pricing. The local Gemma
candidate below remains inactive. Next action is a provider/model choice based
on text-and-image coaching needs and the complete S$30 budget, followed by the
user-authorized bounded test and existing-runtime rollout only if requested.

### Gemma 4 31B local candidate; AWS deployment blocked (2026-11-23 SGT)

The user requested Gemma 4 31B deployment and text/image/file checks. Local
preparation now accepts only the explicit `google.gemma-4-31b` /
`bedrock_mantle_responses` pair in the runtime and app validators. Converse
rejects this Mantle-only model. The factory retains stateless transcript
handling and existing `ApplyGuardrail`, disables SDK HTTP retries and parallel
tool calls, and caps reasoning plus visible output at 2,048 tokens per model
call. Agent repair/event-loop calls remain separately bounded by existing
rules. Serving Compose, model roles, Haiku/Sonnet, UI, data and schemas were
not switched. This completes local candidate preparation only.

- **Files:** `agentcore_runtime/model.py`, `backend/settings.py`,
  `tests/domain/test_runtime_model.py`, `tests/http/test_production_config.py`,
  this status and the [provider guide](providers/MODEL_PROVIDERS.md#gemma-4-31b).
- **Validation:** the first focused runtime/config/source/stream suite passed
  154 tests; a second focused config/files/upload/runtime suite passed 101
  tests. The broader backend/domain/HTTP/persistence/architecture/deployment
  suite passed **2,473 tests, one optional skip** in 80.88 seconds. Compileall
  for backend/UI/runtime/tests/scripts, diff whitespace and provider-guide
  local links passed. Disposable mock Uvicorn startup and restart against the
  same temporary store both returned health/readiness 200. No developer data
  or paid provider was used by those checks.
- **Actual SDK check:** a temporary environment with Strands 1.52.0 and
  Pydantic 2.13.4 passed a socket-blocked compatibility check of the Gemma
  `/openai/v1` route, extracted-file text, image byte conversion, FastChat
  schema, stateless requests, single-tool mode, output bound and SDK retry
  settings. This checks request formatting, not model understanding.
- **Full-suite blocker:** ordinary full pytest collection failed in two
  existing `tests.scripts` cross-imports. An evidence-based importlib-mode
  attempt instead failed in 11 existing bare sibling imports. Full-suite
  retries stopped under the repository's two-attempt rule; a separate Astra
  diagnosis is the prescribed route if that unrelated collection blocker is
  pursued. No model switch or delegation was performed here.
- **AWS blocker:** read-only `GetAgentRuntime` and `GetAgentRuntimeEndpoint`
  both returned AccessDeniedException for `chatbot-prod-signin`. Earlier
  model comparison attempts also lacked direct InvokeModel/CreateInference
  permissions. No new inference attempt, IAM edit, runtime publication,
  DEFAULT move, app release, staging or commit occurred in this preparation.
- **Compatibility/rollback:** no migration or student-data rewrite. Existing
  production remains the rollback baseline. Reverting the candidate code and
  test additions needs no database restore. Local launcher modifications and
  `.playwright-cli/` predate this work and were preserved.
- **Risks:** live Gemma coaching quality, schema acceptance, image formats,
  citations, streaming, progression and classroom latency remain unverified.
  AWS documents a 3.5 MB total request-body limit; general upload acceptance
  does not prove attachment parity. PDF/Office files use existing text
  extraction, not a new native document/OCR capability.
- **Next exact action:** an AWS administrator supplies an identity with scoped
  existing-runtime read/deploy and Gemma Mantle inference rights. Read and
  preserve the actual runtime/DEFAULT/rollback configuration before any
  update. Approve a bounded full-prompt/image integration envelope (the prior
  4K-input/1K-output comparison envelope does not cover it), then run candidate
  checks before following the existing runtime/release cutover procedure.
  Preserve the original comparison ledger: 12 access attempts already used
  from its US$1/42-attempt ceiling.

### Visible word groups and system motion preference (2026-11-23 SGT)

React paces provider reply fragments so a single network burst can produce
several visible word updates. Normal and edited sends share the same preview.
Validation and durable saves remain server-owned. Final-only replies show
without a typing effect. Settings no longer includes Reduce motion. The
browser's system motion preference controls animation and scrolling.

Frontend build and disposable browser checks passed. Normal and edited mock
replies visibly grew on delayed and fully batched delivery, including at
390 px with system reduced motion. Light and Dark, draft retention, saved
reply recovery and the console passed. EC2 and CloudFront now serve
`release-dc83707dccc6`, built from commit `dc83707` on
`improvement/combined-testing1`. The exact image passed a mock smoke;
host readiness, public health, the new React bundle and Stop authentication
passed after cutover. No schema or runtime change. Rollback uses
`releases/before-release-dc83707dccc6` on EC2. Next action is student review
on the public app.

### Compact Summary header live (2026-11-23 SGT)

Review puts **Summarise chat** at the top right of the brief, beside the title,
as a tinted button with a sparkle icon, full label and a 44px touch target.
The tooltip stays aligned to the button. Build, mock image and browser checks
passed at 1440, 390 and 320 px in Light and Dark. CloudFront serves
`summary-polish-12b7e4ce0167` and public health passed. Restore the previous app
and Caddy configuration from `releases/before-summary-polish-12b7e4ce0167`
for rollback. No stored data, schema or runtime changes are required.
Next action is student review of the Summary header on the public app.

### Lecture Help greeting and mode guidance (2026-11-23 SGT)

Lecture Help now answers a bare greeting without attachments with a short course
question prompt, without retrieval or a model call. Other lecture turns include
explicit course Q&A instructions so prior design coaching does not steer the
reply. The existing evidence scope and student-confirmed progression rules
still apply to substantive turns. Authenticated reader, evidence scope and
provider contract checks cover the change. No schema or runtime build change.
The app was deployed to the existing CloudFront site as
`release-e2fa69cae6d7`, built from the pushed commit `e2fa69c` on
`improvement/combined-testing1`. Host readiness and public health passed.
CloudFront serves `index-DwOZdiXQ.js` with the updated Summary action, and the
Stop endpoint remains authenticated. The exact release image passed a
network-free smoke including the Lecture Help greeting. No paid prompt,
schema migration, or runtime update was needed. The previous app and Caddy
configuration are available at `releases/before-release-e2fa69cae6d7`.
Next action: student review on the live app.

### Click-to-summarise and simpler student settings (2026-11-23 SGT)

The filled **Summarise chat** button sits above the project brief fields and
explains on hover and keyboard focus that it summarises the whole chat. Opening
Summary reads saved state without starting generation. The settings page drops
the duplicate export area and reasoning effort field. Review still downloads
the project, and chat actions still share or download the transcript. Chat
name, assignment context, and deletion remain in the current chat/notebook
section. The student response defaults are read-only English and the configured
model. Production chat is configured for Claude Haiku 4.5, and the mock preview
labels its mock coach accurately. Normal sends and both edit paths request
English for React without rewriting older preferences or changing the legacy
Streamlit path.

Focused HTTP, frontend build and disposable browser checks passed, including
click-to-generate, hover/keyboard, cached and failed states, download and
Light/Dark layouts down to 390 px. The full mock suite passed 3,182 tests with
one optional skip. Local preview is refreshed at port 8081.
No schema or runtime change was needed. These settings shipped in the same
app release recorded above.

### Legacy chats, composer Stop and session continuity (2026-11-23 SGT)

- The React sidebar projects all unmarked old conversations as standalone
  chats without rewriting their saved IDs, history or sources. New React
  notebooks carry an explicit settings marker. Older folders created before
  that marker also appear as chats. Existing saved parent source scope stays
  available. No database schema migration or data rewrite.
- The composer shows bouncing dots and an icon button that requests cancellation
  of the exact authenticated stream. Before save, the unfinished reply is
  discarded and the prompt remains available. A turn already saving can finish.
  Provider-stream closure is best effort. A previously recorded edit revision
  remains retryable with its original key.
- The chat actions menu opens upward and clamps to the visible viewport after
  its settings load. Quick tab switches keep the open chat and Review in memory.
  Quiet session checks are throttled to one minute. Explicit sign-out signals
  other tabs without storing any private data.
- The disposable browser passed Stop, prompt retention, menu bounds at 1440 px
  and 390 px in Light and Dark, keyboard open/close, and zero session requests
  during a quick tab switch with Review open. Final console was clear. Focused
  HTTP covered owner-scoped cancellation, preservation during the save race,
  retry and restored folder/chat identities. Build, compile, and Caddy checks
  passed. Local preview refreshed on port 8081.
- Deployed to the existing CloudFront app as `workspace-20261123-73468aa6ca11`.
  Host readiness and public health passed. CloudFront serves React bundle
  `index-B73H7hra.js`; the new Stop route returns 401 without credentials, and
  internal readiness remains private. The exact image passed a network-free
  mock smoke. The full mock run passed 3,181 tests with one optional skip.
  AgentCore DEFAULT remains ready on v36. No live generation or migration ran.
- Rollback: restore the previous app image and Caddy configuration from
  `releases/before-workspace-20261123-73468aa6ca11` on EC2. Existing settings and
  database rows need no rollback. Next action: student review on the live app.

### React and AgentCore streaming live on the existing app (2026-11-23 SGT)

The production student workspace serves the approved React/Review update.
AgentCore DEFAULT v36 is ready, and the app is healthy with session generation
`20261122-streaming-v36`. All five paid prompts streamed and saved. PDF grounding,
confirmed progression, edited-message image retention and notebook source reuse
were verified. Two image answers guessed the meaning of a visible marker. No
schema migration or IAM changes. The previous app and v35 are retained for
rollback. The [production validation report](specs/PRODUCTION_STREAMING_VALIDATION.md)
records exact artifacts, timings, answer quality, persistence and follow-up.


### Normal, edited and AgentCore LLM reply streaming implemented locally (2026-11-22)

Regular sends and edits now share the NDJSON partial-reply lifecycle. Deltas are
on by default for capable clients; legacy JSON edits and clients without the
header keep their contracts. Direct Bedrock and optional OpenAI forward actual
provider fragments. AgentCore Fast Chat requests the updated runtime's SSE
protocol, forwards Strands tool-input fragments while generation is running,
and extracts only top-level response_text in FastAPI. Only validated final
output is persisted. Failed/repaired attempts withdraw their earlier previews.
No extra model call simulates typing. Edited-message revision, attachments/intent,
usage/provenance, exact-key recovery and separate composer drafts are preserved.
Reduced motion keeps reply text visible. Caddy flushes stream responses promptly.

- **Files:** settings/example configuration, Caddy files, AgentCore provider plus
  `backend/agentcore_stream.py`, optional OpenAI provider, runtime main/README,
  shared streaming/revision service, canonical/reader HTTP routes, Conversation,
  HTTP/provider/runtime/route tests and browser fixtures/regressions. Guides and
  detailed rollout: [streaming handoff](specs/REPLY_STREAMING_HANDOFF.md).
- **Validation:** red/green cycles covered default enablement, provider fragments,
  runtime delivery before completion, streamed edits, and discard before retry.
  **236 focused**, **3,180 full mock tests passed** (one existing optional-SDK
  module skipped in the application venv). A separate temporary environment with
  exact runtime pins passed **16 SDK tests**, including real Strands callbacks
  through the public runtime entrypoint before the fake model finished; dependency
  diagnostics reported no AWS/paid calls. An older optional recovery test now uses
  an invalid recommendation rather than null, matching the existing default-to-stay
  change while retaining the two-turn repair check. Dependency warnings remain.
- **Browser/startup evidence:** real mock-server chunks visibly grew for normal
  and edited replies at 1440/390 Light/Dark with app/OS reduced motion, no replay,
  no provisional saved actions and clean console. Scroll, edit/failure recovery,
  bookmark and Summary regressions passed. Public messages/project/bookmarks
  remained identical across a disposable backend restart. Production-style Caddy
  delivered the first mock delta at 0.456s and done at 1.220s (delivery fixture
  timings, not LLM performance). Production build/typecheck, compileall, Caddy
  validation, documentation links and whitespace checks pass. Evidence lives in
  `/private/tmp/llm-streaming-qa/`; screenshots are ignored under
  `output/playwright/reply-streaming/`.
- **Compatibility/rollback:** no migration or data rewrite. Existing user work
  and startup script preserved. The user preview on 8081 was rebuilt/restarted in
  mock mode; health/Streamlit respond, and the new proxy route reaches credential
  checks (401 without credentials). Set `COACH_STREAM_REPLY_DELTAS_ENABLED=false`
  and restart for backend rollback; legacy JSON routes remain. Runtime rollback
  uses the previous READY qualifier on the existing ARN. No staging, commit,
  deployment, IAM edit or paid LLM request occurred.
- **Risks/remaining rollout:** code is locally implemented and mock/SDK verified,
  but the existing AWS runtime/app have **not** been republished. They need the
  compatible app parser then updated runtime on the existing ARN before live
  AgentCore fragments appear. No live-LLM performance or production rollout claim
  is made. Mobile QA uses browser emulation, not a native software keyboard.
- **Next exact action:** review the streaming handoff and approve publication to
  the existing application/runtime if wanted. Any paid live smoke check also
  needs an explicit request/token/cost cap. Local mock review remains on 8081.

### Text-sized edit width and reply-streaming audit (2026-11-22)

Short edit bubbles now start at 260px, aligned with the student's original
right-hand bubble. The longest edited line is measured in the field font;
longer text widens the editor up to the chat column, and height remains automatic.
The icons stay inside the bottom-right footer without covering text. Removing
text shrinks the editor; there is no manual resize control.

The separate streaming check confirms regular sends use FastAPI
`StreamingResponse` with NDJSON, and React reads its body incrementally. Actual
provider reply fragments require the default-off `COACH_STREAM_REPLY_DELTAS_ENABLED`
flag plus the client header (already sent by React). Direct Bedrock supports
`converse_stream`; AgentCore reads/assembles its result and emits no incremental
reply fragments. Revised-message sends use a regular JSON response. The local
preview forces mock providers, so this audit makes no live-LLM claim.

- **Files:** Conversation sizing, edit-width CSS, both message-edit browser
  regressions, React README/design, testing guide and this status entry. Streaming
  code/configuration is inspected only and unchanged.
- **Validation:** rendered red/green caught the full-width short editor, followed
  by Light/Dark desktop/390 short/long widths, automatic height, icon containment,
  hover/keyboard, save/reload, draft and failed-edit recovery checks. Smooth-scroll
  and saved-preview regression remains passing. Production build/typecheck,
  documentation links and whitespace checks pass. All **110 streaming/provider
  mock tests passed**. A disposable HTTP request confirmed NDJSON and five received
  chunks with progress/final-preview/save events under default-off configuration.
  Evidence: `/private/tmp/codesign-latest-control/width-*.log`,
  `streaming-audit-tests.log` and `streaming-http-check.log`.
- **Compatibility/rollback:** no API, schema, data or provider changes; undo only
  the width measurement and edit-width CSS, then rebuild, to restore full width.
  Existing user work remains intact; no paid call, staging, commit or deployment.
- **Risks:** HTTP streaming is not equivalent to token-by-token model output;
  AgentCore and revision responses need separate work for that behavior. Mobile
  width checks are emulated rather than native software-keyboard QA.
- **Next exact action:** refresh port 8081 and edit short/long messages. A future
  token-streaming phase should begin at the provider/transport boundary, especially
  AgentCore and revision handling; no streaming setting was enabled here.

### Compact automatic edit sizing without resize controls (2026-11-22)

Short edited messages use a compact one-line field (52px minimum), grow with text
up to 360px/the viewport cap, and shrink again as text is removed. The manual
resize handle is removed. Cross/up-arrow icons retain their inset bottom-right
footer, borders, hover colours, 44px targets and separate text space.

- **Files:** edit textarea CSS, both message-edit browser scripts, React
  README/design, testing guide and this status entry. Existing one-row/52px sizing
  in Conversation is preserved and validated.
- **Validation:** rendered red/green caught the remaining resize handle. Checks
  cover short-to-long-to-short sizing, Light/Dark desktop/390 compact/long states,
  icon containment/hover, keyboard, save/reload, draft preservation and failed-edit
  recovery; the smooth-scroll/saved-preview regression remains passing. Production
  build/typecheck, local documentation links and whitespace checks pass. Evidence:
  `/private/tmp/codesign-latest-control/autoheight-*.log`; compact screenshots use
  ignored `output/playwright/latest-control/edit-compact-*.png`.
- **Compatibility/rollback:** presentation only; no API, schema or data change.
  Restore `resize: vertical` to undo handle removal, then rebuild. Existing user
  work is preserved; no paid call or Git publication. Python is unchanged, with
  the preceding 3,168 passed / one skipped full mock baseline.
- **Risks:** no known blocker; mobile widths are emulated rather than native
  software-keyboard QA. Very long edits scroll inside the automatic height cap.
- **Next exact action:** refresh port 8081, edit a short message, add/remove lines
  and inspect automatic sizing with the two icons still inside the box.

### Edit icons inside the textbox (2026-11-22)

The edit cross/up arrow now sit at bottom right inside the textbox's shared
border, matching the composer's structure. A reserved footer keeps both icons
clear of long scrolling text. Borders, hover colours, 44px targets, accessible
names, keyboard actions and the short replacement/draft note are retained.

- **Files:** Conversation, styles, both message-edit browser scripts, React
  README/design, testing guide and this status entry.
- **Validation:** rendered red/green checks cover containment and inset placement,
  reserved text space, Light/Dark desktop/390, hover, keyboard, cancel/focus,
  successful revision/reload and failed-edit recovery without write replay.
  Production build/typecheck, documentation links and whitespace checks pass.
  Evidence: `/private/tmp/codesign-latest-control/inside-*.log`; screenshots under
  ignored `output/playwright/latest-control/edit-*.png`. Python code is unchanged;
  preceding full mock baseline is 3,168 passed / one skipped.
- **Compatibility/rollback:** presentation only; no API, schema or data change.
  Restore this phase's edit-box wrapper/footer CSS and rebuild to undo. Existing
  user work/startup script preserved; no paid calls or Git publication.
- **Risks:** no known blocker; mobile QA uses browser width emulation rather than
  a native software keyboard.
- **Next exact action:** refresh port 8081, open Edit on a message and check the
  inset cross/up arrow and their hover colours.

### Smooth latest scrolling and in-place message editor (2026-11-22)

The floating circle scrolls smoothly through the chat, then resumes following.
If a reply moves the destination during the animation, scrolling continues to
the new bottom. Transcript wheel/pointer/key interaction stops automatic pursuit.
App/OS reduced-motion preferences use an instant move. Existing dots, idle
visibility, transparent surround, compact size and 8px hints gap remain.

Edit now replaces the original student text/actions in that same message bubble
with a wider, auto-growing field (160–360px with a viewport cap), without showing
the saved text twice. Bordered 44px cross and up-arrow icons sit at bottom right,
with accessible names/tooltips, theme hover colours and a short consequence note.
Enter adds a newline; Escape/cross cancels and restores Edit focus. Chat symbols
also gain hover colours while saved stars retain gold. Existing revision requests,
read-first recovery and the separate composer draft remain intact. Failed-edit
discard restores both the draft and attempted edit together.

- **Files:** Conversation and styles; existing latest-control browser scripts;
  new `tests/browser/message_edit.js` and `message_edit_qa.js`; React README/design,
  testing guide and this status entry.
- **Validation:** separate red/green cycles reproduced instant movement and the
  duplicated/cramped editor. Browser checks cover intermediate smooth motion,
  output arriving during animation, reduced motion, desktop/900/390 Light/Dark,
  floating-control placement, keyboard, hover, exact original text, bounded large
  editor, empty-value prevention, one successful revision/reload and failed-edit
  recovery without write replay. Existing bookmark and Summary regressions pass.
  All **19 focused** and **3,168 full mock tests passed** (one existing skip;
  dependency warnings retained). Production build/typecheck, compileall, local
  documentation links and whitespace checks pass. The design detector reports
  existing style conventions, with no new blocking finding. Test evidence
  is under `/private/tmp/codesign-latest-control/` (`smooth-*`, `edit-*`, `final-*`);
  screenshots remain under ignored `output/playwright/latest-control/`.
- **Compatibility/rollback:** presentation only; no API, schema, provider or data
  change. Undo only this phase's frontend hunks and rebuild; no DB restore. Existing
  user work/startup script preserved. No paid calls, staging, commit or deployment.
- **Risks:** no known runtime blocker; phone widths/reduced motion are browser
  emulation, not native software-keyboard/device QA. Existing dependency warnings
  and process-local tests-package binding remain.
- **Next exact action:** refresh port 8081, scroll up and click the circle; then
  edit a message to review the larger in-place field and bottom-right icons.

### Latest circle floats transparently with an 8px gap (2026-11-22)

The compact control now overlays the transcript, centered 8px above coach hints,
expanded suggestions, Show suggestions or the composer when those are absent.
It reserves no blank horizontal band. Only its circle is opaque; surrounding
text remains visible and pointer interactions pass through outside the button.
The 44px tap target, working dots and scroll-aware idle visibility are retained.

- **Files:** frontend styles, `tests/browser/latest_above_hints.js`, React
  README/design, testing guide and this status entry.
- **Validation:** the rendered test measured the previous 13px visible gap, then
  passed at 8px with transcript overlap and pointer hit-testing around the circle.
  Light/Dark desktop/390 expanded/collapsed/check-in states, keyboard and console
  checks passed. Working/idle regressions also cover 1440/900/390, reduced motion,
  no request replay and unchanged saved previews/full originals. Production
  build/typecheck passed. Evidence: `/private/tmp/codesign-latest-control/floating-*.log`.
- **Compatibility/rollback:** CSS presentation only; no data, API or schema
  change. Restore the previous row positioning and rebuild to undo. Existing
  uncommitted work remains intact; no paid call or Git publication.
- **Risks:** the circle intentionally covers a small area of text while floating;
  its surroundings remain readable/selectable. Widths are browser-emulated.
  Backend code is unchanged and retains the preceding full mock-suite baseline.
- **Next exact action:** refresh port 8081, scroll up, and expand/hide suggestions
  to review the transparent floating circle and tighter gap.

### Compact latest control above hints (2026-11-22)

The working/latest circle is now visually 32px with a 16px arrow and smaller dots,
while retaining a 44px invisible tap/keyboard target. Its entire row sits above
coach check-ins, expanded suggestions and the collapsed Show suggestions control;
when these are absent it sits above the textbox. Existing generation and
scroll-aware visibility behavior is preserved.

- **Files:** Conversation, styles, latest-control browser test plus the new
  `tests/browser/latest_above_hints.js`, React README/design, testing guide and
  this status entry.
- **Validation:** separate red/green cycles reproduced the oversized circle and
  below-hints position. Production build/typecheck passed; rendered checks cover
  check-in, expanded/collapsed suggestions, Light/Dark desktop/390, keyboard,
  clean console, working/idle scroll behavior and saved-preview preservation.
  Evidence is under `/private/tmp/codesign-latest-control/sizing-*.log` and
  `placement-*.log`; screenshots remain under ignored `output/playwright/latest-control/`.
- **Compatibility/rollback:** presentation only; no data, API or schema change.
  Restore this phase's CSS and row order, then rebuild, to undo. Existing user
  work and local server remain intact; no paid calls or Git publication.
- **Risks:** no known blocker; mobile widths are browser-emulated. Backend code
  is unchanged and retains the preceding mock-suite baseline.
- **Next exact action:** refresh port 8081 and scroll up in Design coaching;
  expand/hide suggestions to inspect the compact circle above either state.

### Latest arrow follows scroll position (2026-11-22)

The idle down arrow appears only when the student is away from the bottom and
hides upon reaching the latest message, by button, keyboard or manual scroll.
Working dots remain visible during generation regardless of scroll position.
The control row also disappears when idle at the bottom, reclaiming its space.
Transcript/content resizing updates the state, with a 4px rounding tolerance;
a student who scrolls away keeps their place while new output arrives.

- **Files:** `frontend/src/Conversation.tsx`, the two latest-control browser
  scripts, React README/design, testing guide and this status entry.
- **Validation:** the rendered regression failed against the previous always-on
  arrow, then passed. Light/Dark 1440/900/390 checks cover working dots at the
  bottom, idle visibility, small/manual scrolling, Enter/Space, reduced motion,
  no extra requests, unchanged preview bounds and intact originals. Production
  build/typecheck and bookmark/Summary regression results recorded with browser
  logs in `/private/tmp/codesign-latest-control/visibility-*.log`.
- **Compatibility/rollback:** presentation only; no API, storage, data or schema
  change. Revert this scroll-visibility change and rebuild to restore the previous
  always-visible arrow. Existing uncommitted work and user server preserved.
- **Risks:** no known blocker; responsive QA uses browser emulation. Python code
  is unchanged; the preceding full mock suite is the backend baseline.
- **Next exact action:** refresh port 8081, scroll up to reveal the arrow, then
  return to the latest message to see it hide; send a mock question for dots.

### Working/latest circle and bounded My work previews verified (2026-11-22)

Chat now has a centered 44px circle directly above the textbox: three dots while
watching/checking a reply, then a down arrow when idle. Either state scrolls to
the bottom and resumes following. It never sends, aborts or retries a request;
textual status, Stop watching, recovery, draft and intentional scroll behavior
remain. Dot motion respects preferences; clean empty chats hide the control.

My work already had a **320-character API preview limit**. A newline-heavy
320-character sample still occupied eleven lines, so previews now have a **six-line
visual cap**. Full originals remain intact through Jump. Clamped coach Markdown
keeps formatting with display-only links to prevent invisible clipped focus targets;
full original links stay active.

- **Files:** Conversation, Icon, CoachText, ThinkingPath and styles; two rendered
  browser regressions; React README/design, testing guide and this status entry.
- **Validation:** red/green tests caught the missing working control and the
  newline-heavy overflow. New desktop/900/390 Light/Dark checks verify state
  changes, 44px placement, keyboard scroll, reduced motion, no request replay,
  intact saved replies/originals and preview bounds. All 25 focused and **3,168
  full mock Python tests passed** (existing namespace binding). Build, compileall,
  whitespace, links and existing bookmark/Summary regressions passed. Visual
  inspection confirmed the circle and capped previews; the design detector found
  existing style conventions, with no new blocking issue.
- **Compatibility/rollback:** frontend-only; no API, persistence, schema, provider
  or data changes. Revert only this phase's frontend changes and rebuild; no DB
  restore. Existing user work/startup script preserved. No paid call, staging,
  commit or deployment. User server remains available with the rebuilt frontend.
- **Risks:** no known runtime blocker; existing dependency warnings/import
  workaround remain. Preview content is deliberately abbreviated; Jump opens
  the full original. Browser motion/widths are emulated, not native OS-device QA.
- **Next exact action:** refresh port 8081 and send a mock message; inspect the
  circle while working/finished and a long saved preview in My work.

### Outer feedback count colours matched (2026-11-22)

Summary stage rows now show the Going well phrase/count in the same green as
its expanded feedback, and To work on in the same yellow/amber. The separator,
stage heading and No saved feedback yet caption remain neutral. Labels, exact
counts, screen-reader descriptions and collapse controls are unchanged.

- **Files:** `frontend/src/ThinkingPath.tsx`, `styles.css`, React README/design
  and this status entry. No backend/API/data/provider or migration change.
- **Validation:** frontend build, existing saved/empty Summary browser checks
  and direct expanded/outer colour comparisons at desktop/390px in Light/Dark.
  Wrapping/disclosures, whitespace and affected documentation links checked.
  Python was not rerun for this isolated JSX/CSS change; the unchanged backend's
  latest full mock run remains 3,168 passing tests.
- **Compatibility/rollback:** revert only the count spans/colour rule and rebuild;
  no data restore. Previous work and user server preserved. No paid call,
  staging, commit or deployment. No known blocker.
- **Next exact action:** refresh port 8081 and inspect the collapsed stage counts.

### Saved-star visibility and My work hierarchy verified (2026-11-22)

Saved stars now render as solid gold in Chat and My work; unstar restores an
outline. The repro confirmed correct saved/pressed state, but a more-specific
shared action rule forced indigo and the original fill was almost transparent.
The fix corrects that CSS override without changing persistence.

My work now has accent stage headers, actual saved-count badges, named parent
regions, inset entries with a subtle guide, clear separators and quieter Jump
controls. Canonical grouping, previews/labels, removal, exact jumps, independent
collapse, keyboard access and 44px controls are preserved in both themes.

- **Files:** ThinkingPath JSX/styles, one new rendered regression and affected
  React/testing guides. Detailed diagnosis, file list and evidence are in the
  [bookmark handoff](specs/STARRED_MESSAGES_HANDOFF.md#star-visibility-and-my-work-refinement-2026-11-22).
- **Validation:** 25 focused and **3,168 full mock Python tests passed**, no
  failures/skips. New Light/Dark 1440/900/390 browser checks, the existing main
  bookmark regression and both Summary regressions passed. Build, compileall,
  whitespace and local links passed; desktop/phone captures inspected.
- **Compatibility/rollback:** no API/schema/data/provider change or migration.
  Previous #30/#31/brief work and user startup script preserved. Revert only this
  refinement's JSX/CSS and rebuild; no DB restore. No paid call, commit or deployment.
- **Risks:** no runtime blocker; existing dependency warnings/import workaround
  remain. User server stays available with the rebuilt frontend.
- **Next exact action:** refresh port 8081 and inspect Chat stars / My work.
  No further implementation phase is pending.

### Whole-chat project brief and clean Summary implemented (2026-11-22)

Summary now leads with **Your project so far**, synthesising the complete active
chat into Who and why, Problem, Current idea, What matters and Still to explore.
It replaces recent prompts/recap, retains uncertainty and explicit unknowns, checks
exact student evidence, caches by whole-chat identity/content and rejects stale or
partial output. Provider failures require explicit retry. The lecture materials
shape the categories rather than becoming a lecture-connections block.

The Impeccable refinement makes the brief primary with a tighter title gap,
consolidates stage feedback into one compact group with real saved counts and
independent disclosures, and puts six detailed skill scores/tips on demand while
retaining strongest/grow/Practice. Download immediately includes a new brief.
Review persistence, privacy and all saved feedback remain.

- **Files:** focused brief service/types/prompts, provider transport, metadata key,
  reader projection/POST, usage and proxy allowlists; React brief/Review/export and
  styles; HTTP/browser tests and guides. See the full file list and evidence in the
  [project brief handoff](specs/PROJECT_BRIEF_HANDOFF.md).
- **Validation:** 160 focused and **3,168 full mock Python tests passed**, no
  failures/skips. Red/green HTTP/browser cycles, full-history/unknown/evidence/cache/
  retry/ownership checks, build/compile/proxy/whitespace/link checks and rendered
  Light/Dark desktop/390px QA are recorded in the handoff. Existing Summary,
  Review persistence and starred-message journeys are preserved.
- **Compatibility:** additive optional settings-text cache, no schema migration,
  personal-data edit or Streamlit source change. Existing #30/#31 and the user's
  startup script are preserved. Roll back this phase's app/UI/proxy changes and
  rebuild; old apps ignore optional caches. No DB restore, paid call, staging,
  commit or deployment.
- **Known limits:** the local app uses mock replies and honestly shows an
  unavailable summary preview. Populated QA uses a scripted model boundary.
  Real summaries need a configured model and matching AgentCore Review runtime;
  no live semantic-quality validation or deployment is claimed. Context budgets,
  per-owner local cache locking and existing dependency warnings remain.
- **Next exact action:** refresh the local app at 8081 and inspect Summary. No
  further implementation phase is pending. Any live test needs an approved cap;
  staging/commit/deployment require separate authorization.

### Review refinements verified locally (2026-11-22)

Summary now provides independent stage/Going well/To work on disclosures and a
Chat overview quoting recent saved student prompts with the unchanged, explicitly
partial saved coach recap. Redundant stage progress is removed from Summary.
Review restores its open/closed choice and selected view per verified owner/chat
through visibility resets, navigation and reload. Private content still clears
and is fetched again. Mobile Practice keeps Review open with a draft confirmation;
explicit close actions and #31's original-message navigation remain intentional.

- **Files/evidence:** React ThinkingPath, Conversation, App and styles; five new
  rendered-browser scripts and two adapted Summary fixtures; React/docs guides.
  Details, root cause, interaction choices and commands are in the
  [Review handoff](specs/REVIEW_REFINEMENTS_HANDOFF.md).
- **Validation:** four red/green behavioral slices, all 32 focused Python tests
  and all **3,163 mock Python tests passed**, no failures/skips. Existing test-namespace
  workaround retained. New browser checks, both Summary regressions and the main
  starred-message regression passed. Real API restart preserved identical public
  project/transcript/bookmarks and restored open Summary. Final frontend build,
  compileall, whitespace and local-link checks passed.
- **Browser:** rendered Light/Dark at 1440/900/390; keyboard, 44px targets, wrapping,
  no Review writes, clean unexpected-error checks, chat/owner isolation and explicit
  closes passed. Screenshots inspected. Native hidden-tab signaling is suppressed
  by the test browser; visibility events were supplied explicitly, with real
  navigation away/back and reload tested separately. See handoff for this limit.
- **Compatibility/rollback:** frontend-only change, no API/schema/data migration,
  paid call or personal-data edit. Only display choices enter tab-session storage.
  Roll back this phase's frontend changes/rebuild; no DB restore. Existing #30/#31
  work and user startup-script edits preserved. No staging/commit/deployment.
- **Risks:** blocked tab storage prevents remount restoration; overview excerpts
  deliberately cover only recent prompts, and the saved recap may be stage-scoped.
  Existing dependency warnings remain. No runtime blocker. User API/Streamlit
  health passed; final rebuilt app remains available at port 8081.
- **Next exact action:** refresh the local app and inspect Review → Summary.
  No further implementation phase is pending; any staging/commit/deployment
  requires separate authorization.

### Starred messages #31 verified; both approved tickets complete locally (2026-11-22)

Chat now saves stars for either author. My work contains only those bookmarks,
grouped by saved stage with bounded previews, author/lecture labels, Remove star
and exact original-message jumps, including messages outside the loaded page.
No stage is collapsed and present only when populated. Keyboard/mobile controls,
visible failure feedback and GET reconciliation are included. Summary #30 remains
intact; Progression's saved-work links now point to that stage's stars.

Implementation spans the reader API, workspace service, existing message metadata,
DSQL write inventory and React workspace; five new authenticated HTTP tests and
three rendered-browser regressions cover acceptance. Full file list, red/green
history, evidence and repeatable commands are in the
[bookmark handoff](specs/STARRED_MESSAGES_HANDOFF.md).

- **Validation:** all 44 focused tests and all **3,163 mock Python tests passed**,
  no failures/skips. Full suite uses the documented process-local test namespace
  binding for this machine's installed `tests` package collision. Final React build,
  Python compilation, diff whitespace and affected local doc links passed.
- **Browser/startup:** real 1440/390 Light/Dark checks passed for star/unstar,
  bookmark-only My work, failure retention, mode tags, old-page jumps, focus and
  highlighting, reload, keyboard, 44px targets and clean unexpected-error checks.
  Imported No stage/removal/empty states passed. Both #30 Summary regressions passed.
  Actual API restart preserved identical public bookmark/transcript/project JSON
  and reloaded rendered stars. FastAPI and Streamlit startup health returned 200.
  Disposable services/browser were stopped after validation.
- **Compatibility/rollback:** no schema migration or personal data changes. Strict
  booleans merge into existing message metadata; active ownership/revision checks
  exclude superseded messages and edits do not inherit stars. Roll back application
  changes/rebuild; the old app safely ignores stored booleans. User startup-script
  changes are untouched. No staging, commit, deployment or paid API call.
- **Risks:** dependency warnings and the existing test-import workaround remain.
  Bookmark reads scan active history; no index/schema was added for this local
  prototype. No runtime blocker remains. Evidence is under
  `/private/tmp/codesign-stars-31/` and ignored `output/playwright/stars-31/`.
- **Next exact action:** review both approved tickets' local changes, starting with
  `frontend/src/ThinkingPath.tsx` and the handoff. No further implementation ticket
  is pending; staging/commit/deployment require separate authorization.

### Summary #30 verified; bookmarks #31 next (2026-11-22)

Summary now renders its saved project summary at full panel width, each Thinking
Path stage's saved Going well and To work on feedback in canonical order, then
the existing Facione scores, tips and Practice action. Missing feedback is
explicitly unassessed; phone feedback groups have readable separation. My work
still has its existing journey until #31 replaces it with bookmarks.

Changed implementation: `frontend/src/ThinkingPath.tsx` and
`frontend/src/styles.css`; added two rendered-browser regressions under
`tests/browser/`. Updated React README/design and the testing guide. Detailed
evidence, file list, commands and #31 entry point are in the
[Summary handoff](specs/STAGE_REVIEW_SUMMARY_HANDOFF.md).

- **TDD and browser evidence:** missing ordered stage feedback and missing group
  spacing each failed before their implementation. Both browser regressions pass.
  Real 1440 px and 390 px Light/Dark QA verified exact saved wording, stage order,
  full-width summary, empty states, wrapping/spacing, unchanged score values,
  tips/Practice, keyboard tabs, reload, no Review POSTs and a clean console.
  API restart preserved the entire project response and rendered Summary.
- **Focused/full validation:** all 11 focused student-journey/notebook-reader HTTP
  tests passed. TypeScript/Vite build and Python compilation passed. All **3,158
  mock tests passed**, no failures or skips. The standard build's pytest collection
  encounters an installed `tests` package shadowing this repository; the full run
  explicitly bound the local test namespace without changing files or excluding
  tests. Exact command is in the handoff. Dependency deprecation warnings remain.
  FastAPI and Streamlit health/startup passed on disposable data; both test services
  and the test browser were stopped afterward.
- **Compatibility/rollback:** no API, schema, stored data, provider, prompt or
  configuration changes. Existing saved assessments and summary fallback are
  reused. Roll back only the frontend changes and rebuild. The user's startup
  script edits are untouched. No staging, commit, deployment or paid call occurred.
- **Risks:** normal full-suite collection needs the documented environment
  workaround on this machine. Existing design-detector warnings concern unchanged
  styles. No #30 runtime blocker remains.
- **Next exact action:** start #31 in a fresh `gpt-6.1-sol` Codex chat, read
  [Starred messages](specs/STARRED_MESSAGES.md) and the handoff, then write one failing
  authenticated reader HTTP test for explicit desired star state. HTTP and browser
  seams are already approved; no repeat confirmation is needed. Keep one writer.

### Starred messages and Summary specs published (2026-11-22)

The user approved both specs and the public test interfaces. Published
[Summary #30](https://github.com/CloudKai/NUS-Codesign-Chatbot/issues/30) and
[bookmarks #31](https://github.com/CloudKai/NUS-Codesign-Chatbot/issues/31) carry
ready-for-agent. Bookmarks depends on Summary. Local specifications are
[Summary](specs/STAGE_REVIEW_SUMMARY.md) and [bookmarks](specs/STARRED_MESSAGES.md).

Approved seams are the authenticated reader HTTP API for persistence, ownership
and edits, plus the rendered React workspace for starring, jumping and Summary.
Implement in vertical TDD cycles with deterministic mock providers and disposable
data. Summary runs first in a fresh ticket context. Its implementation session
must finish validation and a written handoff before starting bookmarks in another
fresh context. The user's repeated approval authorizes these sequential sessions.

Publication and label readback succeeded. Documentation diff checks passed.
Implementation and runtime validation remain pending. No schema or persisted data
changed during specification. The local startup-script modification belongs to
the user. No staging, commits or deployment are authorized.

Next exact action is to implement #30 from its local spec, starting with a failing
browser test of Summary's ordered project summary, per-stage feedback and Facione
sections. After validated completion, record evidence here and start #31 in a fresh
session using its local spec and the HTTP/browser seams already approved.

### Readiness audit and hardening (branch `improvement/combined-testing1`, five features)

Mock and offline only. No AWS, Bedrock or AgentCore call ran, and no script ran
against an account. Full mock suite: 3155 tests, no failure, no skip
(`.venv/bin/python -m pytest -q`, output in the session artifacts). Per-feature
evidence is in the entries below and in the commit messages.

| Feature | Result |
| --- | --- |
| Student journey over the reader routes | `tests/http/test_student_journey_readiness.py`; whitespace-only messages now 422 before any turn is saved; Home start mode, Discard for rejected questions |
| Browser flows at 1440 px and 390 px | Parent-run scripts: `crypto.randomUUID` fallback on plain HTTP (`frontend/src/requestKey.ts`), chips hidden during the milestone banner, 44 px touch targets on phones |
| Security | See the security entry below: download-only uploads, cross-origin write refusal, forged section tags, Windows path separators, unsafe Markdown links |
| Answer accuracy | See the answer accuracy entry below: shared-banner pages kept; recall floors locked |
| AWS | [Architecture proposal](deploy/AWS_ARCHITECTURE_PROPOSAL.md), `infra/aws/` templates, `scripts/aws/deploy_stack.sh` (dry run by default), `tests/test_infra_templates.py` (9 tests) |

- **No migration.** No schema, data or `.env.example` change. Rollback is a revert of the commits.
- **Open decisions for the user** (not changed because they alter what students see
  or what the prompts say): the hard-coded older-adult example lists in
  `backend/learning/journey.py` `personalized_stage_questions` (the app names groups and
  stakeholders the student should find); OCR for image-only slides (86 of 535 pages
  have no text); follow-up query rewriting; the gate wrong-skip rate (76/154);
  silently dropped raw HTML in coach Markdown; the process-local limiter and ledger.
- **Risks.** The templates are unvalidated by `cfn-lint` and untested in an account.
  The cost and speed figures are estimates. The CloudFront asset behavior and the
  deployment bundle and secret are manual steps. Latency percentiles are not
  alarmed (needs an app change).
- **Next exact action.** Review the proposal, then run
  `sh scripts/aws/deploy_stack.sh --app-params <file> --edge-params <file>` with
  `--validate-remote` in a sandbox account; apply only after the account id is confirmed.

### Security readiness pass (branch `improvement/combined-testing1`)

Mock tests only; no AWS, Bedrock or AgentCore call ran. Fixes and the tests that
lock them are in `tests/http/test_security_readiness.py`,
`tests/domain/test_student_chunk_security.py` and
`tests/domain/test_security_invariants.py`. Boundary changes are described in
[Security boundaries](SECURITY_BOUNDARIES.md).

| Finding | Fix |
| --- | --- |
| Owner-scoped source content route rendered uploaded HTML, XML and script inline | Only PDF, images and `text/plain` stay inline; the rest download as `nosniff` attachments |
| Owner-scoped write routes accepted a foreign `Origin` or cross-site fetch metadata | Middleware returns 403; Streamlit's server-side client is unaffected |
| Untrusted text could forge the composer's section delimiters | Composer tag names are rewritten inside untrusted bodies |
| Attachment filenames and the language setting reached the trusted runtime rules as free text | Filenames become one inert token; language is limited to the four supported values |
| Backslash paths kept their separators in upload names | `_safe_name` splits on both separators |

- **Left as is.** The AgentCore runtime phase dispatch (`fast_chat`, and
  `review` with `review_mode=incremental` for the stage checkpoint, are both
  sent in production), the process-local limiters, the first-hop
  `X-Forwarded-For` login key (safe behind Caddy) and the missing production
  requirement for `GENERATION_ADMISSION_POLICY`.
- **Rollback.** No schema or data change. Revert the commits for the five
  rows above independently.

### Answer accuracy over the real lecture PDFs (branch `improvement/combined-testing1`)

Mock and offline only. Material recall@4 is 91/94 and page recall@4 is 79/94 over
the 10 real PDFs, locked by `tests/domain/test_real_lecture_retrieval.py`.
Knowledge Base adapter mapping and citation tests use fake hits keyed by the real
object keys. One bug fixed: duplicate suppression compared only the first 400
characters, so a page that opens with the same banner as an earlier page (Reading
2 page 4) was dropped from the result and its citation lost. Not changed (needs a
decision): OCR for image-only slides (Week 1 has 27 of 32 pages without text),
follow-up query building, gate wrong-skip (76/154) and slide chunking. Details
are in [Retrieval evaluation](RETRIEVAL_EVAL.md).

### Head-to-head routing comparison: Laya vs KB-score routing (built, not run; branch `improvement/backend`)

No production routing change and no setting default changed (all stay off). Nothing
under `backend/`, `agentcore_runtime/` or `frontend/` changed. **No live command ran:**
no Knowledge Base call, no AWS call, no Laya weights. Mock tests only. Details, exact
commands, IAM and cost: [Head-to-head routing comparison](RETRIEVAL_EVAL.md#head-to-head-routing-comparison-built-not-run).

| Step | What changed | Commits |
|---|---|---|
| Pre-registration | `.agents/tasks/headtohead-prereg/plan.md`: sha256 split, how T is chosen, metrics M1 to M6, pass rule, written before any per-half figure. Never edited; dated amendments only | `8c51cdd` |
| `--live-kb-gate` | One `Retrieve` per gate message in `evaluate_retrieval.py`, cap 295, stops on the first auth error, ids and scores only | `6459ba8` |
| `compare_routing_arms` | New command and `scripts/evals/lib/` modules; `evaluate_combined_gate.py` re-exports the moved helpers, output unchanged | `f377a1c` |
| Laya all-rows host run | `benchmark_course_intent.py` host-note flags and per-row output | `1f6acb6` |
| `--extra-messages` | Optional human-labelled rows, reported apart from the 295; `synthetic: true` required unless `--allow-non-synthetic` | `a1bd91e` |
| Docs | Commands, IAM, cost, pre-registration, privacy | this commit |

- **Validation evidence.** Mock tests only: the four new test files (live gate, compare,
  host note, extra messages) plus the unchanged existing tests, and
  `tests/scripts/test_eval_command_boundaries.py`, which picks up
  `compare_routing_arms.py` and every new `lib` module through its directory globs and
  passes unedited (41 tests). `ruff check` and `compileall` pass. Counts per commit are in
  the commit messages. The full mock suite ran in the report commit `8736bf9`: 3041 passed,
  2 failed (the baseline's two `frontend/dist` failures, `assert 404 == 200` on `GET /`),
  1 skipped, against 2905 passed, 2 failed, 1 skipped at `e9bebcb`.
- **Compatibility and rollback.** `evaluate_retrieval.py` and `compare_routing_arms.py`
  only gain flags, and the existing flags, help text, JSON schemas and exit codes are
  unchanged. **One existing command changes behaviour:** `benchmark_course_intent.py
  --checkpoint` now exits 2 unless `--host-instance-type`, `--host-vcpu`, `--host-ram-gb`
  and `--host-arch` are given (placeholders such as `<TYPE>` and non-positive numbers are
  also refused). Every earlier real-model invocation needs those four flags; `--stub-ms`
  runs are unaffected. The three `--checkpoint` examples in `RETRIEVAL_EVAL.md` carry them.
  The output also gains `host_note` and `rows`. Revert the commits above to remove the
  work; no data or migration is involved.
- **Unresolved.** No arm can be declared the winner until two files exist: the live
  KB-score file (`--live-kb-gate --max-live-calls 295`, up to about $0.30 at the assumed
  $1 per 1,000 calls) and the all-rows Laya file on a named host. Host type, vCPU, RAM and
  arch are still `<TYPE>`, `<N>`, `<GB>`, `<arm64|x86_64>`. The AWS price per Retrieve
  call is the user's assumption and is unconfirmed. IAM `bedrock:Retrieve` on
  `arn:aws:bedrock:<region>:<account-id>:knowledge-base/<KB-ID>` is checked against the AWS
  Service Authorization Reference, not tested on an account.
- **Next exact action.** The report `.agents/tasks/headtohead-2026-11-20.md` is written
  (`8736bf9`) and the work is stopped for review. After approval, the operator runs the
  three commands in the RETRIEVAL_EVAL section (live gate, Laya all-rows host run,
  `compare_routing_arms`) and the comparison is re-reported. `compare_routing_arms` refuses
  a KB-score file whose recorded `kb_settings` differ from the plan (12 candidates, 4
  results, filter mode `required`).

### Refactor items 1 and 2: one owner for first-pass scope, uncoupled eval commands (branch `improvement/backend`)

No behaviour change in production or in any eval number, and no live command
(AWS, Bedrock, AgentCore, Knowledge Base, OpenAI or any paid call). Mock tests
only. No settings default changed. Report:
`.agents/tasks/refactor-evidence-scope-2026-11-20.md` (git-ignored, committed
with `git add -f`).

| Step | What changed | Commits |
|---|---|---|
| Step 0 baseline | Per-message gate decisions and every offline eval output recorded under `.agents/tasks/refactor-baseline/` | `9d43fe6` |
| Item 1 | `backend/coaching/evidence_scope.py` owns the first-pass scope and mode rules; `execution.py` and the eval `gate_decision` both call it | `3e18abe`, `6c91e5c`, `26e6fed`, `dda9e34`, `94e8eed`, `c56233f` (pushed) |
| Item 2 | Shared eval code moved to `scripts/evals/lib/`; no eval command imports another; boundary test added | `21ebbf3` to `4a55e3c` (12 commits) |

- **Item 1 evidence.** Per-message decisions for all 295 gate messages and the 12
  follow-up cases: `gate-decisions-after.json` is byte-identical to
  `gate-decisions-before.json` (empty `diff`, same sha256 `7fa20f73...d9ff`). A
  5,652-row cross product of the old and new `gate_decision` is identical.
  Wrong-skip 76/154, false-retrieve 7/141 and recall@4 91/94 are unchanged to the
  digit. No existing test or setting default was edited.
- **Item 2 evidence.** `run_offline_evals.sh` re-run into
  `.agents/tasks/refactor-baseline/after/`: 41 comparisons, 0 differing after
  masking the recorded SHA, dirty flag, timestamps and (for the stub benchmark
  and `measure_stream_first_text`) timing floats. All 19 exit codes are the same
  (0, and 2 for the two refusal paths). `--help` output of nine commands is
  unchanged. Commands that need `laya`, `vegaml`, `setfit` or a checkpoint cannot
  run in the sandbox; their report-building code is compared through
  `stub_snapshots` (no difference) and the `tests/scripts` tests.
- **Validation (script run, mock env).** `ruff check .` passes before and after.
  Full suite: baseline `4fb7c92` 2753 passed, 2 failed, 1 skipped; after item 1
  2876 passed, 2 failed, 1 skipped; at `4a55e3c` (before the docs commit) 2905
  passed, 2 failed, 1 skipped. The +152 are new tests (item 1: 79 + 38 + 6;
  item 2: 29). The 2 failures are the known `tests/http/test_notebook_reader.py`
  pair (no `frontend/dist`); the skip is the missing `strands` package.
- **Risks.** `tests/domain/test_mode_classification.py::test_reflection_completion_request_skips_retrieval_and_completes_in_place`
  failed in one of two completed full runs at `4a55e3c` (and once in item 2). It asserts
  `len(client.calls) == 1` right after `submit`, and the second call it saw was the
  background stage-checkpoint review. It passes alone (8 of 8) and in the other
  runs; it was not run on `4fb7c92`, so it is not shown to be pre-existing.
  `current_stage_status_request`, `stage_progression_request`,
  `workflow_skips_retrieval` and `attachment_retrieval_scoped` are not in the
  perf allow-list and log `turn_perf_rejected_field` (unchanged; a separate
  decision). The setting `fast_chat_upload_retrieval_enabled` is now read twice
  per turn. A stale docstring in `backend/coaching/evidence_scope.py` still names
  `evaluate_retrieval.py` as the eval caller (code not touched in the docs step).
- **Compatibility and rollback.** No schema or stored-data change. Each commit is
  a separate revert unit; item 2 can be reverted without item 1.
- **Next exact action.** Review the report, then decide: (a) whether to add the
  four dropped telemetry names to the perf allow-list, (b) whether to fix the
  racy `len(client.calls) == 1` assertion, (c) candidate 3 (evidence acquisition),
  which was not started. See [RAG_ARCHITECTURE](RAG_ARCHITECTURE.md) (First-pass
  evidence scope) and [RETRIEVAL_EVAL](RETRIEVAL_EVAL.md) (Command layout).

### Phase 4 status (items 0 to 5 complete; branch `improvement/backend`)

No live command (AWS, Bedrock, AgentCore, Knowledge Base, OpenAI or any paid call)
was run in this phase. Every figure below is a script run unless marked. Detailed
entries for items 0 to 5 follow; the full report is
`.agents/tasks/phase4-2026-11-19.md` (git-ignored, committed with `git add -f`).

| Item | State | Commits |
|---|---|---|
| 0 Record Phase 3c and Laya outcomes, product rule | Done, docs only | `f79f08f` |
| 1 Coaching reply with no recommendation defaults to `stay` | Done; needs a runtime republish; review finding F2 fixed (deploy order note, wire-shape test) | `ec3d87f`, `fd7a6e2`, `860eced` |
| 2 Combined offline gate evaluation (295 rows) | Done; no arm reaches the 25% wrong-skip target on all rows | `21d19ce`, `fabb2f2` |
| 3 Laya production readiness | Report and offline harness only; weight licences and memory not established | `343c8b4`, `5640ab8`, `53c001c`, `825cd2f` |
| 4 Reply text streaming | Mock and direct Bedrock only (opt-in, default off); AgentCore path blocked | `d49767e`, `b8893ec`, `3d375c3`, `2692c81` |
| 5 AgentCore vs Converse benchmark | Harness built and stub-tested, not run | `e77b60b`, `88c9914` |

- **Item 2 headline (script run, Wilson 95%).** Gate alone, all 295 rows: wrong skip
  76/154 = 49.4% [41.6, 57.2], false retrieve 7/141 = 5.0% [2.4, 9.9]. Gate plus
  Laya (multilingual, stored results, floor reading): 65/154 = 42.2% [34.7, 50.1];
  Laya Learn floor 67/154 = 43.5% [35.9, 51.4]; false retrieve unchanged. The
  intervals overlap in every reading. The title-wording arm is a stub-model bound
  only (oracle 0/154, rule stub 16/154, flag-all 120/141 false retrieve); only a
  live run measures wording. Cutoffs were the existing calibrated ones and were not
  tuned on these rows. Laya itself was not re-run (the package and weights are
  absent from the sandbox), so its arm uses the Phase 3d stored per-row decisions.
  Details: [RETRIEVAL_EVAL](RETRIEVAL_EVAL.md).
- **Validation (script run).** Starting baseline at `3060a17`: 2593 passed, 2 failed,
  1 skipped. Final: 2746 passed, 2 failed, 1 skipped (+153 tests). The 2 failures are
  the known `tests/http/test_notebook_reader.py` pair, which need a built
  `frontend/dist` (absent; with a built dist the suite had 0 failures during item 4).
  The skip is the missing `strands` package. No new failures. `ruff check .` passed.
- **Compatibility and rollback.** No schema or stored-data change. New settings
  (`COACH_STREAM_REPLY_DELTAS_ENABLED`) default off; every earlier opt-in setting is
  unchanged and off. Item 1 is the only unconditional behavior change and is
  reverted by reverting `ec3d87f` and `fd7a6e2` (and republishing the runtime).
  Deploy the backend before or with the runtime republish.
- **Open decision, not implemented.** Labelling answers on course Q&A turns where no
  search ran as "general, not from course materials". Described in the report.
- **Next exact action.** The user decides: (1) the item 1 live re-run (13 messages,
  26 calls, about $0.21); (2) whether to run the item 5 smoke (cap 2) and full run
  (cap 100); (3) the open labelling decision; (4) Laya deployment questions (weight
  licences, storage, memory, timeout, startup failure versus fallback);
  (5) whether to pursue AgentCore streaming (a runtime contract change). Entry point
  for the next phase: Phase 5, to be defined from those answers; the first code
  entry point is `backend/coaching/evidence_scope.py` (first-pass scope rules; called from
  `_prepare_authoritative_turn` in `backend/coaching/execution.py`) if the labelling
  decision is approved.

### AgentCore vs direct Converse benchmark harness (Phase 4 item 5, built, not run)

New script `scripts/evals/benchmark_agentcore_vs_converse.py`; no new setting, no
backend change. **No live command was run**: the harness was built and tested with
stub clients only (script run: 41 new tests in
`tests/scripts/test_benchmark_agentcore_vs_converse.py`). Full write-up (exact
paths, commands, IAM, cap counting, cost estimate): `docs/RETRIEVAL_EVAL.md`,
"AgentCore vs direct Bedrock Converse benchmark".

- **Turn set.** The existing synthetic gate messages, rows `i * 295 // 50`
  (`evenly_spaced_indices`), 50 turns, pinned by SHA-256 of the id list so a dataset
  change fails loudly. No new data file.
- **Paths.** `InvokeAgentRuntime` with the Fast Chat payload vs `Converse` (or
  `ConverseStream` with `--converse-stream`) with the same payload, system prompt,
  history and forced `FastChatTurnOutput` tool, both validated by
  `_validated_fast_chat`. The Converse arm has no guardrail, event loop or recovery turn.
- **Measures.** `total_ms`, `first_text_ms` (equal to total unless `--converse-stream`;
  AgentCore cannot show early text), input/output/cache-read/cache-write tokens as
  reported (missing is `null`, not zero), parse failures vs call failures, estimated
  model-token cost.
- **Safety.** Refuses with exit 2 before any client is built without `--live-benchmark`
  and `--max-live-calls` (1 to 100, one shared counter over both paths, 2 calls per turn).
  Stops after the first auth or access error. Records exception classes, exit code and
  a `run` block (git SHA, UTC timestamp); never message text.
- **IAM (documented, not tested in an account).** AgentCore: `bedrock-agentcore:InvokeAgentRuntime`
  on the runtime ARN and its `runtime-endpoint/DEFAULT` ARN. Converse: `bedrock:InvokeModel` on the
  three global-profile resources (Phase 3c report section 9.3); `InvokeModelWithResponseStream` too
  for `--converse-stream`.
- **Cost (estimate, hand arithmetic).** About $0.0086 per call at $1/$5 per million tokens and
  7,100 in / 300 out; about $0.86 for the full 100 calls, range $0.3 to $1.3. Prices are from
  third-party pages and unconfirmed on the AWS page.
- **Rollback.** Delete the script, its test and the docs rows. Nothing else depends on them.
- **Next action.** The user decides whether to run the smoke (cap 2) and then the full run.

### Reply text streaming (Phase 4 item 4, partly blocked)

New setting `COACH_STREAM_REPLY_DELTAS_ENABLED` (default off, in `.env.example`).
No live command was run. Marks: **(script run)**, **(hand)**, **(doc)**.

- **What shipped.** Two opt-in NDJSON events on `/api/v1/coach/turn/stream`:
  `reply_delta` (`{"event":"reply_delta","text":"..."}`, an unvalidated
  fragment, appended in order) and `reply_discard` (no payload, withdraws all
  fragments). A client gets them only when the setting is on and it sends
  `X-Coach-Reply-Deltas: 1`; older clients and the Streamlit transport see the
  original events (a client that rejects unknown events would otherwise end the
  stream as malformed). `reply_ready` is still the validated reply and `done`
  the only saved acknowledgement; idempotency, persistence and error events are
  unchanged. A turn that fails after streamed text sends `reply_discard` then
  `error`; the retry after a source check sends `reply_discard` before the second
  pass. React (`frontend/src/stream.ts`, `Conversation.tsx`) appends deltas to
  the unsaved preview only, clears it on `reply_discard`, `error` and stream end,
  and shows the existing "not confirmed saved" status after a failure.
- **Which providers stream.** Mock (a simulation: it cuts the finished reply into
  4-word pieces, so it proves the transport, not model timing) and direct Bedrock
  Converse (uses `converse_stream` when a client asked for deltas and decodes the
  top-level `response_text` from the streamed forced-tool JSON; validated as before;
  stub-tested only, never run against Bedrock).
- **Blocked: AgentCore Runtime (the production path).** Evidence (hand):
  `agentcore_runtime/main.py` `invoke` returns one dict and its docstring says
  "never `yield`" (lines 818-828); `_stream_specialist_invoke` is a stub that
  returns an error payload (805-815); `backend/agentcore_provider.py` calls
  `invoke_agent_runtime(..., accept="application/json")` (line 1886) and
  parses one response body (`_payload_from_runtime_response`). The runtime does
  see partial reply text (its `_first_text_timing_callback`, `main.py` 169-206,
  finds `response_text` in streamed tool-input JSON), but only for timing. AWS
  documents streaming for AgentCore Runtime (`InvokeAgentRuntime` "supports
  streaming responses"; entrypoints may `yield`) (doc), so the platform can do it.
  Using it needs a changed runtime entrypoint (republished runtime version), a
  streaming response contract, and a decision on the output guardrail, which runs
  on the complete output (`enforce_mantle_guardrail(..., source="OUTPUT")`) after
  generation. That changes the runtime contract, so it was not built.
- **Time to first visible text, mock provider, offline (script run,
  `scripts/evals/measure_stream_first_text.py`, 15 runs per mode, medians).**
  Plain mock: 15.1 ms before (`reply_ready`), 14.5 ms after (`reply_delta`).
  Simulated latency mock (150 ms first token + 20 ms per 4-word chunk, 6-7
  chunks): 286.7 ms before, 183.9 ms after. This shows the pipeline hands the
  first fragment to the consumer as soon as the provider emits it (about 14 ms
  of overhead on top of 170 ms) and that the old path waits for the full reply.
  It does not show real model, AgentCore or network latency, because the delays
  are inputs I chose; it does not show browser rendering time.
- **Tests (script run).** 21 new (18 `tests/domain/test_reply_streaming.py`, 3 in
  `test_bedrock_provider.py`): event order, nothing saved while text streams,
  discard then error after a validation failure, no deltas without opt-in,
  idempotent replay streams no text and calls no model, discard before the
  source-check retry, HTTP needs setting and header, extractor edge cases. Full
  mock suite 2703 passed, 1 skipped, 0 failed with a built `frontend/dist`; without
  it the two known `test_notebook_reader.py` failures return. No frontend unit test
  framework exists; `npm ci` and `npm run build` (`tsc --noEmit` then `vite build`)
  passed. `frontend/dist` and `node_modules` are git-ignored, were not committed
  and were removed afterwards.
- **Risks.** Streamed text can differ from the saved text (retries and
  server-side post-processing); the preview is replaced by `reply_ready`. An
  unvalidated fragment may show text that the final validation rejects, which is
  why it is opt-in, labelled unsaved and withdrawn on failure. Enabling the
  setting with `MODEL_PROVIDER=agentcore` changes nothing.
- **Rollback.** Leave the setting off (default), or revert the commits. No schema
  or stored-data change.

### Laya production readiness (Phase 4 item 3, report only)

No product behavior changed. The classifier stays off unless
`LOCAL_COURSE_INTENT_CHECKPOINT` is set. Nothing here was run against a real
Laya model: the `laya` and `vegaml` packages and every weight file are absent
from this sandbox. No live command was run. The exact harness commands are in
[RETRIEVAL_EVAL](RETRIEVAL_EVAL.md#laya-production-readiness-phase-4-item-3);
sources for each claim below are named inline or are the PyPI JSON pages
(`https://pypi.org/pypi/<package>/json`) read on 2026-11-19.

- **Where weights live.** The code reads only local paths
  (`LOCAL_COURSE_INTENT_CHECKPOINT`, `LOCAL_COURSE_INTENT_LEARNER_BUNDLE`) and
  never downloads at runtime. No weight file is tracked in git. The Learn bundle
  is fitted on the checked-in synthetic messages, so it holds no student data.
  Options, with the one this repo's deploy model favours first: a read-only
  host directory bind-mounted into the container (needs a compose change and a
  deliberate edit of `tests/test_deployment_config.py`, which pins the
  secrets-only mount), the image layer (every image and ECR pull grows; `COPY . .`
  would copy it unless placed deliberately), S3 (needs a new sync step; the app
  has none for models), or git (not recommended: size, and the repo rule against
  committing generated artifacts).
- **Packaging.** `requirements.txt` has no Laya, torch, transformers or
  safetensors. `laya==0.4.38` requires `torch>=2.0`, `transformers>=4.48`,
  `safetensors`, `huggingface_hub` and `vegaml>=0.17`; `vegaml==0.17.1` requires
  `torch>=2.4` and `transformers>=5.17` (PyPI metadata). The torch 2.15.0
  cp312 wheel is 461 MiB for aarch64 and 514 MiB for x86_64 on PyPI, and its
  metadata also lists `nvidia-*` packages with a Linux marker, whose installed
  size was not measured. The production image targets linux/arm64 on
  `python:3.12-slim`. The audit workflow checks only `requirements.txt` and
  `agentcore_runtime/requirements.txt`, so a separate Laya requirements file would
  not be audited unless it is added to `.github/workflows/dependency-audit.yml`.
  The mock CI installs `requirements-dev.txt` only; the Laya tests there use stand-in
  modules.
- **Licences (what was and was not established).** PyPI metadata gives
  `laya` 0.4.38 Apache-2.0 and `vegaml` 0.17.1 Apache-2.0, and the `laya` PyPI
  README states Apache 2.0 for its weights. PyPI metadata gives transformers,
  safetensors and huggingface-hub as Apache-2.0 and lists torch's licence
  expression (Apache-2.0, BSD-2/3-Clause, BSL-1.0, ISC, MIT, Zlib and others). The
  Hugging Face model cards for `convaiinnovations/laya-multilingual`,
  `laya-typed-decisions`, `nandakishorm/vega-U` and `Qwen/Qwen3.5-0.8B` could not
  be read here (HTTP 403), so their licence terms are **not established from a
  primary source**. Third-party cards say Apache-2.0 for Laya multilingual and for
  Qwen3.5-0.8B; nothing was found for `laya-typed-decisions` or `vega-U`. Read each
  model card and licence file before any deployment.
- **Memory and latency.** Not measured on real weights. The harness
  `scripts/evals/benchmark_course_intent.py` exists and was run here with a sleeping
  stand-in only (harness check, `real_model: false`). Recorded earlier figures
  (Phase 3d files, development Mac, not production hardware): multilingual load
  6.76 s and p95 211 ms; typed-decisions load 15.15 s and p95 450 ms; Laya Learn
  p95 about 0.93 to 1.09 s. Memory has no recorded figure anywhere in the repo.
- **Fallback.** A failing, abstaining, busy or malformed classifier leaves the turn
  running on the existing gate with no course search (9 new test cases, stub
  classifier and the real adapter over a stand-in `laya.Agent`). A configured but
  missing checkpoint or missing `laya` package does **not** fall back: it raises in
  `OwnerResolver.__init__` and stops API startup (tested). No timeout wraps
  `score()`, so a hung inference holds the single inference slot and its own turn.
- **Single slot.** Production runs one uvicorn worker, so one classifier and one lock;
  a second concurrent turn gets no score and uses the gate. Phase 3d recorded 93/94
  eligible requests abstaining with eight workers.
- **Dedupe of `.agents/tasks/phase3d-work/`.** All 8 JSON files have distinct sha256
  hashes, so none was removed.

Rollback: nothing to roll back for the report. Decisions left to the user: start-up
failure versus fallback for a missing checkpoint, a classifier timeout, where the
weights are stored, and a separate audited requirements file. Next action: Phase 4
item 4.

### Coaching reply with no recommendation defaults to stay (Phase 4 item 1)

- **Behavior.** A coaching `FastChatTurnOutput` with no recommendation (absent,
  null or blank) is parsed as `stay` instead of failing with "coaching mode
  requires recommendation stay or advance". The default is never `advance`. An
  unknown token still fails, an explicit `advance` and every Q&A reply are
  unchanged, and the model-facing JSON Schema still requires the field.
- **Why safe.** A defaulted `stay` follows the same path as a model-sent `stay`
  everywhere except one place, where it is deliberately treated differently. No
  pending transition is created from it, `auto_advance_stages` acts only on
  `advance`, and stage changes still need student confirmation. Free mode
  (`response_detail=long`, outside Problem Identification) promotes a
  model-sent coaching `stay` to a pending `advance` proposal in
  `backend/workflow.py::_promote_free_mode_advance`. That promotion skips a
  defaulted `stay`: the provider marks the assessment with an in-memory,
  non-persisted flag (`EducationalAssessment.recommendation_defaulted`, a
  pydantic private attribute that `model_copy` keeps), because the model never
  judged readiness. Tests: `tests/domain/test_fast_chat_recommendation_default.py`
  (defaulted `stay` in Free mode stays `stay` with no pending proposal and no
  stage change, graph and sequential paths, auto-advance on and off; explicit
  `stay` in Free mode is still promoted).
- **Observability.** Perf field `fast_chat_recommendation_defaulted` (set only
  when defaulted); live eval row field and summary `recommendation_defaulted`.
- **Deploy note.** The default sits in `agentcore_runtime/models.py`, which both
  the runtime and the backend import. The failure happened inside the runtime,
  so the fix takes effect after the runtime package is republished.
  Deploy order: the backend containing this fix (the commit that reads
  `recommendation_defaulted`, fd7a6e2) must go out before or together with the
  runtime republish. The republished runtime sends `stay` plus the marker; an older
  backend ignores the marker and would see an ordinary `stay`, so in Free mode a
  greeting whose recommendation the model omitted could open a "Next" proposal
  (the student must still confirm; no stage changes by itself). Tested with the
  runtime wire shape in `test_runtime_wire_shape_of_a_defaulted_stay_is_not_promoted_in_free_mode`.
  Rollback: revert the commit and republish; reverting the backend alone
  reintroduces the Free-mode proposal for a runtime that still sends the default.
- **Not measured live.** No live command was run. The re-run command is in the
  Phase 4 item 1 notes.

### Recorded retrieval outcomes (Phase 4 item 0)

This entry records results that were already measured; no behavior changed and
nothing was re-run. Full tables, sources and denominators are in
[Recorded results](RETRIEVAL_EVAL.md#recorded-results-phase-4-item-0).

- **Phase 3c live gate (Haiku 4.5, 169 rows: 109 `retrieve`, 60 `skip`, git
  SHA `61ff634`).** Wrong skip fell from 62/109 (56.9%, Wilson 95% 47.5 to
  65.8) with the baseline wording to 51/109 (46.8%, 37.7 to 56.1) with the
  source-check titles. The gate alone missed 73/109. False retrieve over scored
  rows was 2/57 and 2/58. With the 3 and 2 failed calls counted as errors it
  was 5/60 and 4/60; counted as gate-only it was 2/60. All 5 failed calls are
  greeting rows. The 25% wrong-skip target was not met. The intervals overlap.
  Source: `.agents/tasks/phase3c-work/live-item3-{baseline,titles}.json` (the
  counts and rates are in the files; the intervals are computed).
- **Greeting on/off run (34 messages, 68 calls).** 17 calls failed: 9 with the
  SOURCE CHECK rule on and 8 with it off, on 13 distinct messages, all with
  "coaching mode requires recommendation stay or advance". The rule is not
  shown to cause the failure. Source:
  `.agents/tasks/phase3c-work/live-item1-greetings-on-off.json`. The Phase 4
  item 1 fix is a separate change.
- **Laya.** Counts, rates and p95 times are from the files in
  `.agents/tasks/phase3d-work/`, each with its sample size and a computed
  Wilson interval in the linked tables. On the 169 Phase 3c rows: gate 73/109
  (67.0%, 57.7 to 75.1), typed-decisions 73/109, multilingual 62/109 (56.9%,
  47.5 to 65.8), false retrieve 2/60 in all. On the 84 held-out rows: gate
  24/51 (47.1%, 34.1 to 60.5), Laya Learn 18/51 (35.3%, 23.6 to 49.0) and with
  a first-turn cutoff 15/51 (29.4%, 18.7 to 43.0), false retrieve 2/33. The
  "at least 42/109" threshold-sweep figure in the Local Laya entry below is in
  no committed file.
- **Product rule (a requirement, not implemented as stated).** A course concept
  question requires a course citation. If no supporting excerpt is found, the
  coach says it could not verify the course definition and may add a clearly
  labelled general explanation. The code today only tells the model to say it
  "could not retrieve a validated excerpt" on a course search that returned
  nothing, and it disallows model knowledge on course-catalogue turns. Nothing
  covers a turn where the gate skipped retrieval.

Rollback: none needed, documentation only. Next action: Phase 4 item 1 (the
coaching-mode greeting failure).

### Calibrated routing and passage comparison

Keep the existing gate serving students. Laya improved exact evidence scope on
the fresh set but exceeded the unnecessary-retrieval limit. SetFit tied the
gate on exact scope and missed both retrieval-error limits. On the 307 historical
turns, the gate scored 211, Laya 218 and SetFit 229. Those turns were used only
for regression. Both classifiers selected cutoffs of 0.4 for scope and 0.6 for
mode from ten separate calibration turns.

| Fresh measure | Gate | Laya with fallback | SetFit with fallback |
| --- | ---: | ---: | ---: |
| Exact scope | 13/25 | 16/25 | 13/25 |
| Correct coach mode | 15/25 | 23/25 | 21/25 |
| Unnecessary retrieval | 0/10 | 3/10 | 2/10 |
| Missed retrieval | 10/15 | 1/15 | 5/15 |

Fresh exact-scope counts below include descriptive 95% Wilson intervals. The
25 turns come from four scenario families, so these intervals overstate the
independence of related turns.

| Fresh slice | Gate | Laya | SetFit |
| --- | ---: | ---: | ---: |
| Selected file | 4/15 (11%–52%) | 7/15 (25%–70%) | 4/15 (11%–52%) |
| Saved prior student turn | 6/8 (41%–93%) | 4/8 (22%–78%) | 5/8 (31%–86%) |
| Both sources needed | 1/5 (4%–62%) | 2/5 (12%–77%) | 0/5 (0%–43%) |
| Multilingual | 2/5 (12%–77%) | 3/5 (23%–88%) | 2/5 (12%–77%) |

Both policies preserved all 41 routes explicitly recognized by the gate.
A subsequent review flagged two additional workflow paraphrases in the frozen
fresh set. The existing gate left both unrecognized. Laya initiated retrieval
on both, and SetFit did so on one. Including those probes, preservation was
41/43 for Laya and 42/43 for SetFit. The audit flags are used only for reporting.

| Warm CPU path | One request p50 / p95 | Eight requests p50 / p95 | Busy fallbacks at eight |
| --- | ---: | ---: | ---: |
| Laya | 898.2 / 1023.0 ms | 0.2 / 892.7 ms | 56/64 |
| SetFit native | 19.1 / 24.9 ms | 0.2 / 19.3 ms | 56/64 |
| SetFit ONNX | 20.7 / 39.4 ms | 0.2 / 22.2 ms | 56/64 |

Native and ONNX agreed on both raw heads and both effective decisions on all
342 turns. A clean offline SetFit refit reproduced every saved probability
vector and cutoff. The single inference slot served one request per wave. Concurrent
medians primarily measure gate fallback. Eight waves on this Mac give a
development-machine estimate.

Reranking the same eight authorized candidates raised expected-page recall
from 78/94 to 82/94 with median added latency of 314 ms per question.
On the four fact-annotated questions, both orders found a supporting page for
4/4. All requested facts were present for 3/4 lexical and 2/4 reranked lists.
Laya abstained on all 40 individual passages and top-four lists. It called
zero of the 33 incomplete contexts sufficient, with zero decided incomplete
contexts from which to estimate conditional error.

The [reproduction guide](RETRIEVAL_EVAL.md#evaluate-evidence-scope-coach-mode-and-excerpt-sufficiency)
covers the routing evaluator, passage evaluator, grouped datasets, model
revisions and commands. Fitted bundles, ONNX graph, per-turn predictions,
latency samples, candidate orders and judge decisions are saved locally under
`artifacts/evals/turn-comparison/`. The original sufficiency bundle remains
under `artifacts/evals/laya-turn-decisions-sol/`.

Validation passed 109 focused tests and 2,602 full-suite tests with one
optional skip. Compile, scoped Ruff and Git whitespace checks passed. All
changes are confined to offline evaluation, fixtures, tests and guides.
Rollback requires no student-data migration or deployment action. Start the
next routing experiment with fresh rows 7, 17 and 24 in the Laya report.
All three had a selected file and needed no retrieval. Keep these as regression
cases and evaluate any revised policy on newly labelled families. Keep the
sufficiency judge offline. Haiku/Sonnet selection requires its separate
answer-quality and cost benchmark.

### Offline Laya experiment for three turn decisions

Sol authored 38 examples for evidence scope and coach mode and 31 for
excerpt sufficiency. The [offline evaluator](RETRIEVAL_EVAL.md#evaluate-evidence-scope-coach-mode-and-excerpt-sufficiency)
fit and reloaded both Laya Learn bundles with networking blocked. Existing
evidence-scope labels were kept out of fitting. Coach mode used labels
derived from existing categories, and sufficiency used controlled passage
swaps rather than independently reviewed search results.

On 307 labelled turns, exact evidence scope fell from 211/307 with the gate
to 182/307 with Laya and gate fallback. Wrong skips fell from 84/163 to 3/163,
while unnecessary retrieval rose from 7/144 to 110/144. Laya improved on
selected-file turns (18/37 to 23/37) and follow-ups (12/28 to 19/28), but lost
on turns needing both source types (10/12 to 5/12). The coach-mode head
matched 124/137 category-derived labels. The sufficiency head failed its
internal comparison with Vega. Vega then abstained on all 48 controlled cases.
Serial routing inference p95 was 2.29 seconds on the development Mac.

The 110 focused retrieval tests, evaluator checks, Ruff, and Git whitespace
checks passed. Reports and bundles are in the ignored local directory
`artifacts/evals/laya-turn-decisions-sol/`. There is no runtime change, data
migration, or deployment rollback. Haiku and Sonnet remain configured as
before. Keep the classroom gate and Phase 4 streaming plan. If routing work
resumes, predefine a narrow selected-file or follow-up policy, calibrate it on
a separate split, and measure independently labelled scope and host latency
before any runtime trial.

### Sol-authored training examples for Laya Learn

The offline experiment added 34 eligible examples to the 76-example training
set and recalibrated the thresholds on the original 61 rows. Across 60 new
synthetic messages, both bundles missed 6/30 requests needing retrieval and
falsely retrieved on 0/30 skips. On the earlier 84-row holdout, wrong-skips
fell from 15/51 to 13/51 (25.5%) and false retrieves stayed at 2/33 (6.1%).
Sol authored both the additional training examples and the new test set.
The test messages have no exact overlap with training or calibration, and
the labels lack independent review. The benchmark ran with networking
disabled.

The experiment requires no runtime changes or data migration. The previous
bundle remains the rollback artifact for an opt-in demo. Keep the classroom
gate as configured and proceed to Phase 4 streaming. The experiment inputs,
script, report and bundle are in
[phase3d-work/sol-teacher](../.agents/tasks/phase3d-work/sol-teacher/).

### First-turn calibration for Laya Learn

The pilot can use a separate cutoff before the first saved student message.
Offline calibration on 61 synthetic rows chose 0.6455845832824707 for opening
turns and 0.8563768182025443 thereafter. On the same 84-row comparison set,
wrong-skips fell from 18/51 to 15/51 (29.4%) with 2/33 false retrieves
(6.1%) in both runs. This set was previously examined. On 19 additional
course questions with IDs absent from the gate corpus, misses fell from two
to one. All 19 required retrieval. On the separate 12 follow-ups both
policies missed 1/9 retrieve cases and falsely retrieved on 0/3 skip cases.

A trial using shorter turn inputs and 121 training examples missed 22/51
on the main comparison, so the pilot retains the original learner format
and 76-example training set. Serial CPU inference p95 was 932 ms in the
final run. Focused tests and the full mock build passed. The change requires
no data migration. Clear `LOCAL_COURSE_INTENT_FIRST_TURN_THRESHOLD` to return
to the single cutoff. The classroom feature remains disabled. The pilot did
not reach the 25% wrong-skip target. Proceed to Phase 4 streaming with the
existing classroom gate. [Evaluation instructions](RETRIEVAL_EVAL.md#fit-and-evaluate-laya-learn)

### Laya Learn retrieval pilot

The local FastAPI classifier can load a fixed Laya Learn bundle. The
benchmark fitted on 76 eligible synthetic messages from the training split,
selected cutoffs on 61 calibration rows, then evaluated 84 held-out rows.
Question IDs and duplicate messages stay within one split. On holdout, the
existing gate and frozen Vega both missed 24/51 retrieve cases (47.1%).
The learned head missed 18/51 (35.3%), with false retrieves steady at 2/33
(6.1%). The learned head was used for all 41 eligible holdout turns. Its
CPU inference p95 was 1.09 seconds on the development Mac.

Focused tests and the full mock build passed. A disposable FastAPI run loaded
the real fitted bundle, returned cited course Q&A with mock generation, and
replayed the saved turn after restart. The learned classifier needs no data
migration and builds its bundle from synthetic labels. To roll back an
opt-in process, clear the checkpoint and bundle settings and restart
FastAPI. Keep this pilot disabled for classroom use because it missed the
25% wrong-skip target. If work resumes, test on independently labelled
course questions and measure concurrency on the intended host.
[Fitting and configuration](RETRIEVAL_EVAL.md#fit-and-evaluate-laya-learn)

### Local Laya retrieval pilot

FastAPI can use a local Laya checkpoint to route ambiguous chat turns to the
existing course retrieval and grounded Q&A path. A missing checkpoint setting
keeps the existing gate. Existing evidence scopes take precedence and a busy
or failed classifier falls back to the existing gate.

On the same 169 synthetic Phase 3c rows with a 0.8 cutoff, the gate missed
73/109 retrieve cases and falsely retrieved 2/60 skip cases. Laya
typed-decisions also missed 73/109. Multilingual Laya missed 62/109 and
kept false-retrieves at 2/60. CPU inference p95 was 450 ms and 211 ms,
respectively, on the development Mac. With eight benchmark workers, the
single-slot multilingual classifier bypassed 93/94 eligible requests in an
unpaced burst. A retrospective threshold sweep still missed at least 42/109
with false-retrieves below 10%. Neither checkpoint met the 25% wrong-skip
target.

The frontend build, compilation, and full mock suite passed. A disposable
FastAPI run using the real multilingual checkpoint and the mock response
provider retrieved a local lecture excerpt, returned cited Q&A, and replayed
the saved turn after an API restart. No migration is required. To roll back
an opt-in process, clear
`LOCAL_COURSE_INTENT_CHECKPOINT` and restart FastAPI. Keep the pilot disabled
for classroom use. If routing work resumes, use the local benchmark and a
held-out set for a course-trained classifier, then repeat burst testing on
the intended host. [Benchmark and configuration](RETRIEVAL_EVAL.md#local-course-intent-classifier)

### Local workspace

React serves the student workspace at `/`, with `/pilot/` as an alias.
Lecturers and accounts with Enabled Access use `/streamlit/`. Students can
resume notebook conversations, move or pin chats, search their workspace,
and open Review without a generation call. Stage changes require explicit
confirmation. Notebook Sources control reusable evidence, and chat
attachments apply to the submitted turn unless added as a notebook source.
Past local work checked persistence, source and citation handling, and desktop
and mobile browser behavior. [Application architecture](LOCAL_DEMO_IMPLEMENTATION.md) ·
[React workspace](../frontend/README.md)

Private Library uploads use one stored original and derived text with
owner-scoped links. Existing uploads retain their storage anchors. If legacy
files need to survive deletion of their original conversation, plan and
verify a separate storage migration. [Library and citation behavior](RAG_ARCHITECTURE.md#library-files-and-notebook-sources)

### Classroom and release

| Gate | Evidence and next action |
| --- | --- |
| [#28 Classroom capacity and cost](https://github.com/CloudKai/NUS-Codesign-Chatbot/issues/28) | Open. The mock rehearsal completed three 80-submission waves after the SQLite waiter fix. Obtain the actual gross AWS bill and credit dates, permitted processing locations, and a lecturer-approved wait target. Then assess live throughput, restore evidence, and full operating cost. |
| [#29 React release](https://github.com/CloudKai/NUS-Codesign-Chatbot/issues/29) | Open and depends on the classroom gate. Record the participant comparison, accessibility and capability gaps, and demonstrate rollback against the same saved data. |
| Two course modules | Proposed. Start with module membership, owner scope, and corpus isolation before exposing the second route. The readiness guide covers the shared S$30 budget and overlapping class peaks. |

[Capacity evidence](operations/CLASSROOM_CAPACITY_GATE.md) ·
[Decision register and release checks](operations/CLASSROOM_READINESS_DECISIONS.md) ·
[Post-credit hosting](operations/CLASSROOM_READINESS_DECISIONS.md#post-credit-hosting) ·
[Second course module](operations/CLASSROOM_READINESS_DECISIONS.md#second-course-module-proposal)

### Documentation consolidation

The root README now opens with the local mock workflow. The docs index points
to current architecture, AWS operations, classroom readiness, and contributing
guides. The security guide includes guest access and course-publication
decisions. The learning handbook includes all eight chapters on one page.
Documentation and the handbook PDF generator are the scope of this pass.

The React build, Python compilation and full mock suite passed via
`sh scripts/build.sh`. A disposable local stack served the React shell,
returned API readiness and created a guest session. The consolidated handbook
rendered as 41 pages with the codebase appendix. Local Markdown links and
heading anchors resolved.

The previous working-tree documents are backed up at
`/private/tmp/codesign-docs-before-tightening-2m_inlg6`. Application runtime
and deployment configuration were outside this phase. For the next technical
phase, use the classroom [decision register](operations/CLASSROOM_READINESS_DECISIONS.md#evidence-and-decision-register).

### Task-based documentation index

The [documentation index](README.md) now follows five reader tasks. The
[architecture guide](LOCAL_DEMO_IMPLEMENTATION.md#repository-layout-and-placement-rules)
includes the package map, placement rules and compatibility imports. The
[provider guide](providers/MODEL_PROVIDERS.md) covers AgentCore and direct
Bedrock. Mock load commands live in [testing](TESTING.md#mock-load-probe),
and pilot monitoring and deployment commands live in the
[AWS runbook](deploy/AWS_STATELESS_EC2.md). The
[release checklist](PRODUCTION_RELEASE_CHECKLIST.md) links to the August QA
report at a fixed revision. The
[decision register](operations/CLASSROOM_READINESS_DECISIONS.md#post-credit-hosting)
records the S$30 ceiling, the AWS decision and the second-module proposal.

Verified local Markdown links and heading anchors, the pinned QA Git blob,
script and example paths, and all six example files. The code reference and
handbook PDF generators ran successfully. The three-owner mock load probe
accepted all three turns, the cost examples produced their expected totals,
and the AgentCore smoke CLI passed its dry run. The full mock suite passed
2,595 tests with dependency deprecation warnings. `git diff --check` passed.
GitHub HTTP verification was unavailable because DNS could not resolve the
host. The pinned report is present in the tracked remote branch history.

This change needs no runtime, API, configuration or data migration. Previous
tracked documents remain recoverable from Git. The Sol evaluation artifacts
and findings are preserved. The next technical phase is Phase 4 streaming,
using the [coach stream implementation](../backend/coaching/streaming.py).

## Earlier evidence

The previous repository snapshot contains the original validation commands,
rollback notes, and full phase history.
[Implementation log at 948162e](https://github.com/CloudKai/NUS-Codesign-Chatbot/blob/948162e1eba9d0de3fbda7cbfce1d00731001158/docs/IMPLEMENTATION_STATUS.md) ·
[Original ticket handoffs](https://github.com/CloudKai/NUS-Codesign-Chatbot/tree/948162e1eba9d0de3fbda7cbfce1d00731001158/new_docs/ticket_handoffs) ·
[Streamlit design QA](https://github.com/CloudKai/NUS-Codesign-Chatbot/blob/948162e1eba9d0de3fbda7cbfce1d00731001158/design-qa.md)

For future phases, record the behavior change, validation evidence, compatibility,
rollback, and the next owner action here. Link to the relevant issue or guide
for detailed evidence.
