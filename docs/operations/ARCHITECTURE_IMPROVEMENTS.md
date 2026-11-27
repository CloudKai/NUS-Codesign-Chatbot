# Architecture improvements: audit and local milestones

24 November 2026 SGT. Starting revision `8a449a7`, branch
`improvement/architecture-responsiveness`, created from
`improvement/combined-testing1` with a clean working tree. This report records
the first implemented milestones of the comprehensive improvement request.
The remaining programme is explicitly open; this is not production acceptance.

## Executive findings

The repository already has the intended React/FastAPI split, TanStack Query,
Tailwind, NDJSON recovery, owner-scoped sources, prompt budgets, usage accounting,
admission controls and extensive security/workflow tests. Replacing them would
duplicate working behavior. Targeted changes in this branch:

1. Unblock full test collection. An installed `tests` package shadowed the
   repository's namespace directory; `tests/__init__.py` makes resolution explicit.
2. Correct load-probe statistics and retain the requested six-level mock baseline.
3. Replace fabricated chat percentages and inferred cold-start explanations
   with indeterminate activity and actual operation status.
4. Export an offline, explicit read-only OpenAPI subset; generate and use Hey API
   for identity, notebook lists and revision-bound message pages. Check schema
   and generated-file drift in CI without publishing production API docs.
5. Centralize Query keys/defaults and add executable frontend regressions.
6. Fix a confirmed Mantle/Gemma preview safety gap: its output guardrail runs
   after generation, so that runtime path must not emit provisional text first.

The user confirmed CDE2300 as the active scope; the other course is a separate
copy. Apply these improvements to the existing CDE2300 product, prompts and
corpus. No course renaming, second-course setup or corpus migration is required.

## Architecture and trust flow

| Boundary | Current owner and behavior | Assessment / next step |
| --- | --- | --- |
| Browser | `frontend/src/App.tsx`, `useReader.ts`, `api.ts`, `Conversation.tsx`; React 19.2, TypeScript 5.9.3, Vite 7.3.8, Query 5.108.4, Tailwind 4.3.5 | UI, drafts, temporary preview and reconciliation only. Identity probes fence saved views. |
| Edge | `Caddyfile`, `backend/http/notebook_reader.py`, `compose.prod.yaml` | Exact reader method/path allowlists, same-origin restrictions, private no-store data. No edge change needed for the three existing reads. |
| Authentication | `backend/http/app.py`, owner resolver, Cognito/guest adapters | Verified cookies resolve backend owner services. Reader explicitly refuses anonymous internal-demo ownership and staff/student role mismatch. Query keys grant no authority. |
| Reader / services | `backend/http/notebook_reader.py`, reader workspace/source adapters, `WorkspaceService`, `LearningProgressService` | Bounded saved views; stage changes remain backend decisions with student confirmation. Source management and lecturer Streamlit remain intact. |
| Retrieval | `backend/coaching/evidence_scope.py`, execution preparation, local/Bedrock retrievers | Existing pure first-pass scope, source ownership and citation validation. No extra routing LLM, embedding store or retrieval agent introduced. |
| Context | `context_planner.py`, coaching/deep review context, runtime prompts | Complete transcript stays persisted; bounded recent Fast Chat context and broader Deep Review context already exist. Do not truncate authoritative work for speed. |
| Normal turn | `backend/coaching/execution.py`, single workflow, AgentCore provider, `agentcore_runtime/main.py` | Application owns authorization/retrieval/state/save; runtime owns bounded structured generation. Recent native Gemma JSON/nullability fixes retained. |
| Stream | `backend/coaching/stream_events.py`, `streaming.py`, `frontend/src/stream.ts`, `replyPreview.ts` | Dispatch identity, status, provisional discard, validated reply, saved done and exact-key recovery already implemented. Browser never automatically retries generation. |
| Persistence | SQLite/DSQL store adapters, `dsql_connection.py`, transaction wrappers | DSQL currently opens/closes connections with fresh IAM tokens. Whole-transaction OCC retry and rollback are meaningful constraints on any future pool. Ticket 38's offline harness (`scripts/benchmark_dsql_connections.py`) records the comparison and nine pool-contract checks; the fresh-connection default is kept pending an approved live run. |
| Deep Review | `backend/coaching/deep_review_jobs.py` and execution snapshot/review projection | Persisted receipts and bounded process-local workers exist. Queued/running work does not resume after restart; GET marks it failed. Durable worker recovery is outstanding. |
| Observability | `turn_perf.py`, usage and operational JSON logs | Existing timing/usage seams should be extended before adding monitoring services. First-model-text and first-visible-text are distinct, especially after the Mantle safety fix. |

Browser → same-origin edge → verified owner → FastAPI reader → service →
retrieval gate → authorized context → provider → bounded AgentCore model →
structured validation/output guardrail → atomic persistence → `done` →
owner-verified browser reconciliation remains the normal flow. Deep Review
uses its separate bounded job/snapshot path, not an autonomous learning agent.

The legacy `backend/chat_service.py`, Streamlit and compatibility facades are
retained. Their existence does not justify removing working entrypoints.
No new AWS runtime, infrastructure, database or production dependency is added.

## Implemented decisions and contracts

**Generated reads.** FastAPI/Pydantic remain authoritative. Eight operations have
stable IDs (`readerSession`, `readerNotebooks`, `readerMessages`, `readerBootstrap`,
`readerPreferences`, `readerPreferencesUpdate`, `readerNotebookSettings`,
`readerNotebookSettingsUpdate`) and documented read-error models.
`scripts/export_reader_openapi.py` forces temporary mock
storage before importing the app, refuses reused settings, blocks network
connections, and projects only allowlisted routes and reachable schemas.
`--check` compares deterministic output without writing. Internal professor,
admin, model and graph routes cannot accidentally enter this subset.

Hey API 0.99.0 generates SDK, types and bundled Fetch support under
`frontend/src/api/generated/`. The adapter keeps HttpOnly cookie transport,
same-origin credentials, no-store, cancellation, status-only errors, cookie
refresh, pagination, revision checks and `/pilot/` compatibility. Existing
view defaults are materialized in the adapter. Other REST resources remain on
the existing client for incremental migration. NDJSON is not generated REST.
Production OpenAPI/docs remain disabled. The
[update workflow](../../frontend/README.md#generated-read-contracts) is authoritative.

**Privacy and caching.** Owner-scoped Query keys/defaults now have one home.
Zero stale/retention times and no automatic retry/focus/reconnect refetch remain
until resource-specific benefits can be measured. Clearing a client aborts its
pending query, and late completion cannot repopulate the old owner's entry.
No local-storage query cache or optimistic educational outcome is introduced.
Expanded caching, query coverage and aggregate reads remain a later milestone.

**Honest activity.** Sending is local submission state; queued/retrieving/
thinking/saving follow actual backend events. Deltas indicate writing, discard
returns to preparation, and saved completion requires `done` or recovery.
Unknown progress has no numeric accessibility value. The former 200ms estimate
interval is removed; no rendering-speed claim is inferred from this alone.
Existing indigo styling, light/dark themes and reduced motion remain.

**Output safety.** The deterministic runtime regression went red in both
passing-output and blocked-output cases because a model fragment escaped before
the separate Mantle output guardrail. `capture_model` now suppresses Mantle
preview forwarding while retaining internal first-text telemetry. Its final
result still passes structured parsing and the existing output guardrail.
No additional provider/guardrail call is made. Other provider paths are unchanged;
their streaming safety is not newly certified by this fix. An old deployed
runtime remains unchanged until an authorized publication/session rollover.

**Dependencies.** Hey API and Vitest 5.1.1 are dev dependencies. A `js-yaml`
4.3.2 override resolves advisories in the generator's pinned parser chain.
The final installed dependency tree reported zero npm audit vulnerabilities.
No existing direct runtime dependency was upgraded or removed. The generated
Fetch runtime is bundled code; ordinary builds require neither schema export
nor a running Python backend. Node 22.23.2 was used locally.

## Reproducible performance baseline

Changed-file inventory:

| Area | Created | Modified |
| --- | --- | --- |
| API contract | `scripts/export_reader_openapi.py`, `frontend/openapi/reader.json`, `frontend/openapi-ts.config.ts`, `frontend/scripts/check-api.mjs`, 16 generated files under `frontend/src/api/generated/` | `backend/http/notebook_reader.py` operation/error metadata |
| Frontend | `api/client.ts`, `api/errors.ts`, `api/queryClient.ts`, `api/queryKeys.ts`, their client/Query unit tests, `stream.test.ts` (all under `frontend/src/`) | `api.ts`, `useReader.ts`, `main.tsx`, `ChatProgress.tsx`, `Conversation.tsx`, `stream.ts`, `styles.css`, manifest and lockfile |
| Safety / verification | `tests/__init__.py`, `tests/scripts/test_export_reader_openapi.py`, `tests/browser/identity_inflight.js` | Runtime `main.py`, runtime-stream regression, load probe/regression, browser activity regression, conftest comment, build script, Mock CI, `.gitignore` |
| Guidance / evidence | This report and aggregate benchmark JSON | Root/frontend/runtime READMEs, frontend design, architecture/status/testing/security/provider/streaming guides, docs index and script guide |

No API path or database table was added or removed. The generated read contract
is additive; other frontend requests keep their existing adapters.

The [aggregate JSON](../examples/performance/local-mock-baseline-2026-11-24.json)
contains six independent processes with synthetic authenticated owners and
temporary SQLite. Each process runs one simultaneous burst, one normal mock
coaching turn per owner. No pytest workload ran concurrently for this retained
matrix. An earlier exploratory matrix overlapped tests and is not retained as
the reference. No CPU isolation, repeated-trial confidence interval, live model,
network proxy, DSQL or browser timing is represented. Non-monotonic rows show
why single bursts are smoke evidence rather than a stable scaling model.

| Users | Accepted | p50 ms | p90 ms | p95 ms | p99 ms | Max ms | Turns/s | Failed | Peak threads | Process max RSS KiB |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | 1 | 304.4 | 304.4 | 304.4 | 304.4 | 304.4 | 3.28 | 0 | 5 | 150448 |
| 10 | 10 | 417.0 | 430.1 | 433.5 | 433.5 | 433.5 | 23.04 | 0 | 38 | 166208 |
| 20 | 20 | 686.8 | 1024.2 | 1030.9 | 1181.7 | 1181.7 | 16.91 | 0 | 78 | 187424 |
| 40 | 40 | 622.3 | 682.3 | 695.3 | 758.2 | 758.2 | 51.58 | 0 | 137 | 233024 |
| 60 | 60 | 892.6 | 967.8 | 1011.5 | 1134.1 | 1134.1 | 52.3 | 0 | 189 | 280032 |
| 80 | 80 | 1003.6 | 1101.1 | 1130.2 | 1355.6 | 1355.6 | 55.3 | 0 | 250 | 320528 |

All admission-rejection rates were zero. Structural validation failed zero
turns; ownership cross-read probes were not enabled in this particular matrix
and remain null rather than being described as measured zero. Separate tests
exercise isolation. RSS is a whole-process high-water mark. CPU utilization was
not measured. Tail percentiles use nearest rank; p99 with 80 samples is the max,
not a population p99 estimate. Previous floor-based probe reports underreported
small-sample tails and are not directly comparable.

| Frontend / AI measure | Before | After / status |
| --- | --- | --- |
| Main JS build output | 369.23 kB / 114.13 kB gzip | 379.03 kB / 117.65 kB gzip; generated transport costs 9.80 kB raw / 3.52 kB gzip net |
| Markdown JS chunk | 120.92 kB / 37.12 kB gzip | 120.92 kB / 37.12 kB gzip |
| CSS build output | 70.57 kB / 14.12 kB gzip | 69.00 kB / 13.82 kB gzip |
| Vite bundling time, one run | 988 ms | 985 ms; no statistically supported speedup |
| Reader reload sequence, source inspection | session → list → session | Unchanged; preferences have their own lifecycle. Aggregate endpoint benefit is unmeasured. |
| Ordinary notebook open, source inspection | page + project, then session check | Unchanged; optional refresh adds a list read. Full UI may load other resources. |
| Load/interactive, navigation wall time, render counts | Not measured | Not measured; bundle timing is not time-to-interactive |
| DB connect/query, auth, retrieval stage timings | Not isolated | Existing telemetry/probes identified; no DSQL calls made |
| Provider first token/visible text, output reliability, tokens/cost | Not remeasured | No billable requests authorized; no claimed AI speed/quality gain |
| 80 live students | Not established | Remains unverified; mock capacity is not full application/provider capacity |

Reproduction commands and estimator compatibility are in
[testing](../TESTING.md#architecture-baseline-matrix). Do not use this snapshot
to claim the 500ms ordinary-read SLO or 1–3s visible AI target has passed.

## Verification and security review

- Test collection originally stopped with two `ModuleNotFoundError: tests.scripts`
  errors. The package marker unblocked the full suite without excluding tests.
- Full Python validation and final counts are recorded in
  [implementation status](../IMPLEMENTATION_STATUS.md). The final suite passed
  **3,206 tests with one optional skip**; 176 targeted runtime/provider/streaming
  tests also passed. The skip is the optional installed-Strands integration.
- Vitest: 23 tests passed, covering generated transport, HTTP and abort behavior,
  owner keys, late Query results, pre-mutation cancellation, byte-split Unicode,
  invalid NDJSON identities/terminals/error fields and truncated streams.
- OpenAPI export/drift checks, generated-client consistency, TypeScript/Vite,
  Python compileall, targeted Ruff and shell syntax passed locally. Existing
  third-party Vite `use client` notices and Python dependency deprecations remain.
- Full-repository Ruff still reports 10 existing findings across five byte-for-byte
  unchanged files: the archived `.agents/tasks/phase3d-work/sol-teacher/run.py`,
  `backend/coaching/streaming.py`, two browser fixture bootstraps and
  `tests/domain/test_gemma_native_json.py`. The unchanged-content comparison was
  verified against HEAD. Scoped Ruff passes; full lint/green CI is not claimed.
- Real mock browser: 1440px/390px light/dark, reduced motion, actual streaming,
  indeterminate/saving/saved feedback, reload, failed send without replay,
  discard/cancellation and new-owner isolation passed. The separate
  `identity_inflight.js` test passed: account change aborts an intercepted pending
  generation and rejects its late result. It uses no real provider. Screenshots
  were inspected; no JavaScript exceptions. Console HTTP errors were expected
  signed-out 401 checks and the deliberate 503 injection.
- FastAPI and Streamlit startup were exercised with temporary mock storage.
  The full suite includes source/citation, confirmed stage progression,
  graph/restart and existing-data compatibility regressions. No personal DB
  or schema was migrated for validation.
- A current tracked-file scan (827 files, files up to 5 MB) found no matches for
  the checked private-key/AWS-access-key/OpenAI-key patterns. This limited scan
  is not a full secret/history audit. There are 25 already tracked Playwright
  logs/snapshots/summary artifacts requiring content/retention review before
  publication. They were preserved; new `.playwright-cli/` output is ignored.
  No history rewrite, deletion or credential rotation was performed.
- The design detector found existing stylesheet warnings/advisories and no
  findings in the changed progress/Conversation components. This is not an
  automated WCAG certification or justification for an unrelated redesign.

## Deployment, compatibility, cost and rollback

No path/method, request payload, student schema, saved transcript, source or
learning-stage migration is required. Operation IDs and error documentation
are additive. Existing clients/Streamlit remain compatible. Same-origin cookies,
owner checks, CSRF/origin restrictions, no-store, explicit stage confirmation,
idempotency and receipt recovery remain in place.

Compose currently names `DEFAULT`, a November 22 session generation and Haiku
role values. The latest operations record describes a pinned `GemmaStable37`
V1 alias with Gemma Fast Chat/Sonnet Deep Review. This is confirmed repository
configuration/document drift, not a fresh verification of live state. Do not
apply Compose to production until an operator reconciles a nonsecret deployment
manifest against actual host/runtime state. Local tests do not validate Caddy/
CloudFront streaming, regional latency, IAM, backups or a deployment rollback.

The security fix must be included in a newly published runtime version with a
fresh application session generation. Until that authorized rollout, production
cannot be claimed protected by this change. Preserve model/provider settings;
this work does not select or benchmark another live model.

No new recurring service cost or extra AI call is introduced. Actual existing
and future monthly totals, AWS price/usage assumptions and savings are unknown.
The S$30/month target remains unvalidated. Use the existing
[cost accounting](../COST_ACCOUNTING.md),
[admission](../GENERATION_ADMISSION.md) and
[readiness register](CLASSROOM_READINESS_DECISIONS.md) rather than duplicate bills.
For planning, vary active students, monthly classes, turns/student, input/output
tokens, retrieval/review/retry frequency and storage/network growth; multiply by
verified regional prices and add fixed infrastructure once. Low/expected/high
costs require agreed inputs and current pricing before numerical claims.

Rollback is source-only for these local changes: restore the touched frontend,
reader contract, build/CI/export tooling and runtime source from the starting
revision, then reinstall the corresponding lockfile and rebuild. Keep data
directories unchanged. The former full-suite import collision would recur if
the test marker is reverted. Reverting the runtime safety condition restores
the preview exposure risk; do not choose that as an operational remedy.
No commit, deployment or live rollback was performed in this phase.

## CDE2300 bootstrap follow-up

The user confirmed this programme applies to CDE2300; the other course remains
a separate copy. This follow-up implements the startup portion of P1.

`GET /api/v1/reader/bootstrap` returns session, listing and allowlisted preferences
from one verified reader owner. It reuses existing projections and performs one
bulk notebook-list read rather than per-notebook lookups. The shared preference
projection now lives in `backend/http/reader_workspace.py::reader_preferences`;
the independent preference route uses the same helper. These reads are
owner-consistent, not a transactional snapshot of all resources. There is no
new persistence, model invocation, conversation body or source payload.

The generated client includes `readerBootstrap`. `verifiedBootstrap` retains
cookie renewal and performs a fresh session probe afterward, comparing all
three projection identities before returning. Reader request epochs/aborts still
fence resets. The verified bootstrap seeds the owner's preferences Query
resource (`src/api/workspaceSettings.ts`), so no component refetches them
immediately; the same module owns the four generated preference/settings
operations. Thread changes and all mutation
reconciliation keep their existing checks. Preferences and notebook settings
carry small measured per-resource freshness (90 s and 30 s, inside the approved
investigation ranges) adopted only after identity-lifecycle tests pass; every
other resource keeps zero retention, and no private cache persistence is
enabled.

The [before/after JSON](../examples/performance/cde2300-bootstrap-2026-11-24.json)
retains three observations per scenario with the same corrected browser harness.
The original loader bundle was built temporarily, sources restored, and the
updated bundle rebuilt afterward. Each run uses synthetic Guest data, empty
chats, temporary SQLite and deterministic mock mode, with zero generation calls.

| Measure | Before | After |
| --- | --- | --- |
| Clean authenticated startup reader requests | 6 in every trial | 2 in every trial |
| Initial preference round trips | Separate GET + two session checks | Included in bootstrap; subsequent owner probe retained |
| Median visible sidebar, no injected delay | 77ms | 74ms |
| Median visible sidebar, injected 100ms per reader request | 823ms | 338ms |
| Open empty chat reader requests, including trailing reads | 9 in every trial | 9 in every trial |
| Median visible composer, no injected delay | 42ms | 49ms |
| Median visible composer, injected 100ms delay | 298ms | 308ms |

Request reduction is the primary result. Timings are illustrative local samples,
not SLOs or production improvements: three observations, no resource isolation,
baseline overlap with part of pytest, browser scheduling variation and synthetic
transport delay. The harness drains trailing SPA requests explicitly; its
`settledMs` includes an 800ms wait and is not a completion-latency measurement.
An earlier exploratory harness incorrectly carried some trailing requests into
the next trial; only corrected-run observations are retained here. No chat-open
speedup is claimed. Reproduce with `tests/browser/workspace_loading.js` after
opening a disposable mock server URL through the documented Playwright CLI.

Full suite: 3,209 passed, one optional skip; Vitest: 30 passed. After the full
run, an added exact Caddy matcher test and bootstrap tests passed in the 24-test
focused suite. A 90-test reader/security/student-journey suite also passed.
Build, schema/client drift, compileall, scoped Ruff, whitespace and Caddy validate
passed. Browser regressions cover bootstrap held across cookie-owner change,
late-generation owner change, saved preferences, theme write/reload, desktop and
390px layout. Screenshots were inspected. The preference regression recorded
no JS exceptions. Existing full-repository lint findings remain documented above.

New files: `tests/http/test_reader_bootstrap.py`, frontend `api/bootstrap.test.ts`,
the three browser scripts `workspace_loading.js`, `bootstrap_identity.js` and
`bootstrap_preferences.js`, and benchmark JSON. Modified files: reader route and
preference projection, export allowlist/schema/generated SDK, browser API/reader/
App/WorkspaceTools, Caddy GET matcher, route/export/deployment contracts and guides.

No database migration, data restore or course-content change is needed. Existing
reader routes and Streamlit remain compatible. Release the backend, frontend and
Caddy update together: an old proxy intentionally does not expose bootstrap.
Rollback restores those source/assets/config files together without changing data.
The separate production runtime safety rollout remains pending authorization.

## Remaining implementation plan

| Priority | Concrete milestone / entry point | Verification gate |
| --- | --- | --- |
| P0 | Reconcile nonsecret deployment manifest from `compose.prod.yaml` and latest operations records; arrange the Mantle safety rollout | Authorized operator verifies actual runtime, fresh session and safety-blocked stream; no blind live configuration overwrite |
| P1 implemented | Startup profiling and owner-verified bootstrap in `useReader.ts` and initial preferences | Six to two startup reads; owner-race and saved-preference regressions pass; navigation remains unchanged |
| P1 | Add resource-specific Query coverage/retention with centralized keys; benchmark bootstrap/workspace aggregation before adoption | Account switch during reads/streams, logout, stale revision, mutation reconciliation and measured request reduction |
| P1 | Extend approved generated REST operations in small read groups, then ordinary mutations | Explicit allowlist/models/errors, codegen checks, compatibility tests; keep NDJSON and generation explicit |
| P2 | Benchmark DSQL connect/transaction cost through injected adapters before bounded lifespan pooling | Offline harness complete (ticket 38): nine pool-contract checks pass and local numbers are recorded. Remaining gate: approved, capped live DSQL run via `scripts/benchmark_dsql_connections.py --live` before any adoption |
| P2 | Separate provider/runtime/guardrail latency and compare compact prompts/models/direct inference | Shared quality corpus, citation/structured-output rate, first-visible latency and token/cost evidence; no extra model per turn |
| P3 | Recover durable Deep Review work through persisted jobs/leases using existing store boundaries | Restart/failure/cancel/duplicate tests, revision fence, bounded retries and no stale-work overwrite |
| P3 | Extract cohesive chat lifecycle/API boundaries only where tests/profiling identify maintenance problems | Existing normal/edit/cancel/recovery contracts and owner isolation retained |
| P3 | Expand component/browser CI, accessibility and observability | React Testing Library and reproducible Playwright Test setup remain outstanding; no claim that CLI smoke is browser CI |
| P4 | CDE2300 student-authored artifacts/version history/resume/milestone/export improvements | Ownership, conflict-safe versions, restore, accepted AI suggestions, restart/export and lecturer-reviewed educational criteria |
| P5 | Evaluate Router, editor, Radix/Lucide, maps and multimodal uploads only against observed needs | Accessible working flows, no placeholder actions or arbitrary new stages |
| P6 | Full mixed 80-student app rehearsal, cost/region/privacy/backup/restore/accessibility/deployment rehearsal | Synthetic accounts, approved cost/concurrency caps, current price evidence, explicit deployment authorization and rollback rehearsal |

Retain React/FastAPI, NDJSON, the single existing workflow and current local/AWS
adapter split. No demonstrated requirement currently warrants Next.js, another
frontend server, Redux, WebSockets/SSE migration, Kubernetes, Redis, additional
vector storage, autonomous phase agents or a monitoring SaaS. These are deferred
choices, not implemented features or benchmarked rejections.
