# Testing and quality gates

## Safety contract

The default suite is deterministic and must not contact OpenAI, Cognito, AWS,
public webpages, or any other live service. `tests/conftest.py`
clears the OpenAI key, forces the mock provider, and gives each test an isolated
temporary database/files tree.

The current suite contains no live-marked tests. Any future live test must
self-skip without an explicit opt-in environment flag and require approval for
costs or writes. Use `-m "not live"` when selecting deterministic tests from a
suite that includes live cases.

## Standard commands

Focused test:

```sh
.venv/bin/python -m pytest -q tests/<subsystem>/test_<module>.py
```

Full mock suite:

```sh
.venv/bin/python -m pytest -q
```

Compile and shell/config checks:

```sh
PYTHONPYCACHEPREFIX=/private/tmp/co-design-pycache \
  .venv/bin/python -m compileall -q backend ui scripts tests streamlit_app.py agentcore_runtime

sh -n scripts/start.sh scripts/start_prod.sh scripts/build.sh \
  scripts/deploy_ecr.sh scripts/browser_e2e_smoke.sh

docker compose config --quiet
APP_IMAGE=co-design:test docker compose -f compose.prod.yaml config --quiet
git diff --check
```

`scripts/build.sh` builds React, compiles Python, and runs pytest.

## Coverage map

| Risk area | Principal deterministic suites |
|---|---|
| Auth cookies, refresh, OAuth state, logout | `http/test_app_sessions.py`, `ui/test_auth_gate.py`, `http/test_cognito_token_jwks.py` |
| Owner isolation | `http/test_multiuser_ownership.py`, `http/test_runtime_auth.py`, `http/test_production_critical_path.py` |
| API/client contracts | `http/test_api.py`, `http/test_api_client.py`, `http/test_workspace_api.py` |
| Five-phase workflow and progression | `domain/test_workflow.py`, `domain/test_primary_path.py`, `domain/test_learning_service.py`, `domain/test_student_journey.py` |
| Lecturer Research/analytics | `http/test_professor_research.py`, `http/test_professor_analytics.py`, `ui/test_professor_ui.py`, `domain/test_research_coding_domain.py`, `persistence/test_research_persistence.py` |
| Prompts/provider boundary | `domain/test_prompt_architecture.py`, `domain/test_bedrock_provider.py`, `domain/test_agentcore_provider.py`, `domain/test_models_and_support.py` |
| Retrieval/citations/sources | `domain/test_retrieval.py`, `domain/test_source_library.py`, `ui/test_sources_ui.py` |
| Retrieval eval script and data files | `scripts/test_evaluate_retrieval.py`, `domain/test_retrieval_question_set.py`, `domain/test_retrieval_gate_message_set.py` (see [retrieval evaluation](RETRIEVAL_EVAL.md)) |
| Persistence/migrations | `persistence/test_student_store.py`, `scripts/test_init_db.py`, `scripts/test_init_dsql.py`, `persistence/test_storage_providers.py` |
| Idempotency/revisions/deletion | `persistence/test_coach_idempotency.py`, `persistence/test_conversation_revision.py`, `persistence/test_delete_idempotency.py` |
| Upload/storage failure safety | `http/test_upload_hardening.py` (size/count/filename hardening plus the event-loop offload contract: blocking upload writes run in the bounded threadpool, never on the loop), `persistence/test_hardening_storage_sync.py` |
| Streamlit behavior | `ui/test_streamlit_ui.py`, `ui/test_streamlit_api_mode.py`, `ui/test_rerun_scope.py`, `ui/test_theme_styles.py` |
| Production configuration/edge | `http/test_production_config.py`, `test_deployment_config.py` |
| Logging/rate limits | `http/test_privacy_logging.py`, `http/test_rate_limit.py` |
| Architecture façades and inventories | `test_architecture_contracts.py` |
| Reader Query resources and settings surface | `frontend/src/api/workspaceSettings.test.ts`, `frontend/src/WorkspaceTools.test.tsx`, `frontend/src/api/queryClient.test.ts` |
| Persistent artifacts and canvases | `persistence/test_student_artifacts.py`, `persistence/test_student_canvases.py`, `persistence/test_reference_links.py`, `http/test_reader_artifacts.py`, `http/test_reader_canvases.py`, `frontend/src/CanvasEditor.test.tsx` |
| Canvas and artifact autosave | `frontend/src/useArtifactAutosave.test.ts`, `frontend/src/CanvasAutosave.test.tsx` |
| Bundle/route-load and long-content render cost | `frontend/tests/browser/route_load.spec.ts` (real-browser route downloads and lazy-editor guard), `frontend/src/renderPerf.test.tsx` (opt-in jsdom mount-cost harness, `PERF_MEASURE=1 npx vitest run src/renderPerf.test.tsx`), `npm run measure:bundle --prefix frontend` (post-build asset sizes). |

## Regression workflow

Before a risky refactor, state the observable behavior and add a focused test
when coverage is weak. During implementation, run the nearest suite after each
cohesive change. At a phase boundary, run the full mock suite, compile checks,
and relevant deployment/browser validation.

For moved modules, preserve public imports when needed and update source-text
assertions deliberately. For API changes, verify the service, FastAPI route,
typed client, and API-mode Streamlit path together. For persistence changes,
test fresh schema, legacy upgrade, restart, rollback behavior, and both adapter
contracts.

## Browser and visual QA

AppTest verifies logic and rendered structure; it does not prove visual layout,
browser-console cleanliness, keyboard navigation, or responsive behavior.
Visual changes require the real app at desktop and 390 px widths in Light and
Dark/System as applicable.

For a local headed smoke, start the app with `sh scripts/start.sh` and run
`sh scripts/browser_e2e_smoke.sh`. The helper can check selection mode
(**Ready** and **Move to**). It requires Node.js/`npx`, an installed
Playwright CLI wrapper, and approved manual Cognito sign-in. Keep the helper
outside CI and use the regular sign-in flow.

## Browser CI slice (ticket 05)

A finite, self-cleaning Playwright Test slice boots the production-built reader
frontend and a real same-origin disposable FastAPI/SQLite stack with the
deterministic mock provider. It is non-billable, binds to loopback only, uses a
temporary workspace (never a developer database), and covers Guest and a
synthetic registered identity — no live Cognito or AWS. Repeatable command:

```sh
npm run test:browser --prefix frontend
# CI equivalent: PW_PYTHON=python3 npm run test:browser --prefix frontend
```

The specs live in `frontend/tests/browser/`:

| Spec | Covers |
|---|---|
| `guest_journey.spec.ts` | Guest signs in, opens a notebook, submits a deterministic mock coaching turn, and reopens the committed reply after reload (saved-turn recovery). Also asserts no fabricated chat-progress percentages and no unexpected console/page errors. |
| `owner_switch_inflight.spec.ts` | Switching Guest while a generation request is pending aborts the request, drops an approved late reply for the previous owner, hides the old chat, and never replays generation (controlled `page.route` fault injection). |
| `saved_turn_survives_restart.spec.ts` | The disposable API process is actually stopped and respawned against the same SQLite workspace; the same browser context (Guest cookie preserved) reopens the chat and the committed reply is present. |
| `interrupted_stream_recovers.spec.ts` | The real stream request completes server-side and only then is the page's connection dropped (`route.fetch()` then `route.abort()`); the client reconciles read-only against `GET /threads/{id}/coach-turn?idempotency_key=` using the **original** key and renders exactly one confirmed turn with no replayed write. |
| `registered_journey.spec.ts` | A synthetic **registered** student (deterministic Cognito boundary in `tests/browser/registered_stack_app.py`) opens a notebook, submits a mock turn, and reopens the committed reply after a real backend restart while staying the same verified identity. |
| `student_stop_cancels.spec.ts` | The student clicks the real **Stop generating** control against a paused mock workflow (`tests/browser/cancellable_stack_app.py`, the same paused-`CoachWorkflow.run` technique the FastAPI cancellation test uses). The real stop route answers `stopping`, the released worker ends the turn with the canonical `reply_discard` → 409 `cancelled` sequence, the prompt is kept, nothing is saved, no receipt exists, and no generation is replayed — across a reload. |
| `route_load.spec.ts` | Route-load measurement and lazy-editor guard (ticket 43): the home view downloads strictly less JavaScript than the routed artifact/canvas editors, deep links still mount both editors, the hashed entry chunk is reused across views, and one JSON evidence line records per-route transfer bytes and editor-ready times (no wall-clock assertions). |
| `authoring_accessibility.spec.ts` | Accessible authoring evidence (ticket 44): keyboard-only artifact/canvas authoring from the skip link, modal `Add to canvas`/`Develop into artifact` dialogs (focus never reaches a background control, Escape closes, focus returns to the opener), version-history keyboard use, instant canvas Locate under `prefers-reduced-motion: reduce`, WCAG 2.2 AA contrast spot checks in Light and Dark, 390 px touch authoring with no horizontal overflow, screenshots under `output/playwright/a11y/` and a clean console. |
| `ambiguous_save_recovers.spec.ts` | An interrupted stream whose saved-receipt read returns `null` (the real unsaved body) leaves the question pending with explicit actions only: an explicit **Check saved answer** later recovers the saved reply once, and an explicit **Discard and edit** restores the composer text without resending. |
| `workspace_journey.spec.ts` | A student authors and explicitly saves a Tiptap document and a labeled canvas. The student transfers chat and document content to the canvas, assembles an artifact from a canvas node, reviews and accepts a coach suggestion, confirms stages, and starts Deep Review. A real backend restart verifies Home resume and recap, the durable review, and the saved document and canvas. The student then confirms canvas deletion. |
| `artifact_type.spec.ts` | A student selects Reflection in the notebook Documents tab, creates it through the routed app, reloads and verifies the saved document retains its selected type. |

`tests/browser/disposable_stack.py` builds and validates the disposable
workspace, pins mock/SQLite/local settings, matches `CO_DESIGN_PUBLIC_API_URL`
to the served origin (required by the guest-start same-origin check), and fails
fast with the server log if the API dies before readiness. Setting
`PW_REGISTERED_IDENTITY=1` (or `startStack(..., { registeredIdentity: true })`)
serves the deterministic registered-identity boundary instead of the plain mock
app; `PW_STACK_APP=<module>` (or `startStack(..., { cancellableTurns: true })`)
serves another `tests/browser` fixture app the same way (the modes are mutually
exclusive). `frontend/tests/browser/stack.ts` starts, stops and restarts that
process so a spec can exercise a real backend restart.
`.github/workflows/mock-ci.yml` runs the slice in the `browser-ci-slice` job.

The registered journey seeds verified cookies directly, so it exercises the real
owner-scoped API path with a synthetic identity but **not** the Cognito Hosted UI
redirect or token exchange — live Cognito sign-in remains a documented gap
outside CI. The delayed relay in `tests/browser/reply_streaming_fixture.py` and
the manual scripts in `tests/browser/*.js` remain available and are untouched.

## Deterministic CI composition (ticket 46)

`.github/workflows/mock-ci.yml` is the standing deterministic gate. Every job is
bounded by a `timeout-minutes` limit and needs no live AWS, Cognito or paid
provider:

| Check | Where | Local equivalent |
|---|---|---|
| Offline schema/client drift | `mock-suite`: `scripts/export_reader_openapi.py --check`, `npm run api:check` | `npm run api:check --prefix frontend` |
| Python collection + compile | `mock-suite`: full `pytest` collection and `compileall` | full mock suite command below |
| Python lint | `mock-suite`: `ruff check .` | `.venv/bin/ruff check .` |
| TypeScript | `mock-suite`: the reader build runs `tsc --noEmit` | `npm run build --prefix frontend` |
| Frontend lint (added ticket 46) | `mock-suite`: `npm run lint` — minimal ESLint flat config (`frontend/eslint.config.js`), `typescript-eslint` recommended rules, generated client excluded (never hand-edited, ticket 33 generator quirk); valid findings are fixed, not suppressed | `npm run lint --prefix frontend` |
| Vitest/component tests | `mock-suite`: `npm test` (unit + component + resource regressions) | `npm test --prefix frontend` |
| Production-style build | `mock-suite` and `browser-ci-slice`: `npm run build` | same |
| Bundle-size evidence (added ticket 46) | `mock-suite`: `npm run measure:bundle` prints entry/async raw+gzip bytes after the build; evidence only, thresholds are judged in the ledger | `npm run measure:bundle --prefix frontend` |
| Playwright browser slice + accessibility | `browser-ci-slice`: includes `route_load`, `authoring_accessibility` and `workspace_journey`. The workspace journey authors and transfers work, accepts a reviewed suggestion, confirms stages, and reopens the saved workspace and Deep Review after a real mock-backend restart. | `npm run test:browser --prefix frontend` |
| Frontend dependency advisories | `mock-suite`: `npm audit --audit-level=high` | same |
| Python dependency audit | separate `dependency-audit.yml`: `pip-audit` on `requirements.txt` and `agentcore_runtime/requirements.txt`, weekly cron plus path-filtered PRs, fail-closed | n/a (workflow-only) |
| Secret scanning (added ticket 46) | `mock-suite`: pinned `ghcr.io/gitleaks/gitleaks:v8.30.1 detect` over the checked-out git history, config in `.gitleaks.toml` | `gitleaks detect --no-banner --redact` |
| CodeQL | separate `codeql.yml`: Python-only default security queries on `main` | n/a (workflow-only) |

`.gitleaks.toml` extends the default rules and allowlists exactly three
documented synthetic fixtures (the deliberately fake planted credential in
`tests/http/test_security_readiness.py` and two deterministic id/button strings
whose names merely end in `key`); it never allowlists a path wholesale. Any new
finding fails the job. The gitleaks step scans the default shallow checkout
(one commit), keeping the job bounded; the full-history local command above is
the deeper periodic check.

## Reader component tests (ticket 07)

`npm test --prefix frontend` also runs jsdom component and resource tests beside
the unit specs:

| File | Covers |
|---|---|
| `src/api/workspaceSettings.test.ts` | Owner/notebook-scoped Query keys; per-resource freshness configured separately from the zero global defaults; verified bootstrap preferences reused with no duplicate read; refetch after measured freshness expiry; foreign-owner rejection; delayed responses never repopulating a cleared identity; a confirmed save reconciling only the preferences resource and cancelling superseded reads (via `MutationObserver`, no DOM). |
| `src/WorkspaceTools.test.tsx` | The real settings surface: a theme save POSTs once, confirms with "Changes saved.", applies the appearance and updates the Query cache without replaying a preference read; a remount reuses the confirmed save with zero additional reads; private Query state never enters `sessionStorage`/`localStorage`; a saved answer for a foreign owner is expired, never applied or cached. |
| `src/api/queryClient.test.ts` | Zero-retention defaults, owner-separated keys, cleared-identity delayed-response fencing, pre-mutation read cancellation. |

## Saved Summary browser regression (#30)

The approved test boundary is the rendered React workspace backed by disposable
mock data. These scripts create their own guest-owned chats through the reader
HTTP API, complete the five-stage mock journey and verify the visible saved
feedback. They do not use Cognito or paid providers. Run outside CI with a local
Playwright CLI installation. Build first with `npm run build --prefix frontend`.

Start an isolated backend in a separate terminal (never use a personal database):

```sh
SUMMARY_TEST_ROOT="$(mktemp -d /private/tmp/codesign-summary-XXXXXX)"
mkdir -p "$SUMMARY_TEST_ROOT/lecture_notes"
APP_DATA_DIR="$SUMMARY_TEST_ROOT" \
APP_DATABASE_PATH="$SUMMARY_TEST_ROOT/workspace.sqlite3" \
APP_FILES_DIR="$SUMMARY_TEST_ROOT/files" \
APP_WORKSPACES_DIR="$SUMMARY_TEST_ROOT/workspaces" \
LECTURE_NOTES_DIR="$SUMMARY_TEST_ROOT/lecture_notes" \
MODEL_PROVIDER=mock MOCK_OPENAI=true OPENAI_API_KEY='' \
DATABASE_PROVIDER=sqlite FILE_STORAGE_PROVIDER=local \
GUEST_ACCESS_ENABLED=true AUTO_ADVANCE_STAGES=false \
STUDENT_STAGE_SELECTION=false COACH_REQUESTS_PER_MINUTE=120 \
CO_DESIGN_PUBLIC_API_URL=http://127.0.0.1:8093 \
CO_DESIGN_UI_URL=http://127.0.0.1:8093 \
.venv/bin/python -m uvicorn backend.http.app:app --host 127.0.0.1 --port 8093
```

Then run from the repository root:

```sh
mkdir -p output/playwright/summary-30
PWCLI="$HOME/.codex/skills/playwright/scripts/playwright_cli.sh"
"$PWCLI" -s=summary30 open http://127.0.0.1:8093 --headed
"$PWCLI" -s=summary30 run-code --filename tests/browser/stage_review_summary.js
"$PWCLI" -s=summary30 run-code --filename tests/browser/stage_review_summary_empty.js
"$PWCLI" -s=summary30 close
```

The main regression checks exact saved wording and stage order, full-width summary,
mobile wrapping and spacing, scores/tips/practice, keyboard tab navigation, reload
recovery and absence of Review writes or browser errors. The empty-state regression
checks the missing summary, all five unassessed stages and absent score actions.
Screenshots are written under ignored `output/playwright/summary-30/`. Stop the test
backend afterward. The temporary rate allowance is test-only; no production setting
changes. Use unique request keys for every fixture chat because idempotency is
owner-scoped, and validate NDJSON `done` events rather than HTTP 200 alone.

## Whole-chat project brief and clean Summary

The authenticated/model-boundary regressions are in `tests/http/test_project_brief.py`.
They verify early-message coverage beyond the browser page, null missing facts,
unsupported evidence refusal, cache/restart reuse, stale invalidation, owner/origin
and strict-input guards, explicit retry, real adapter transport and context refusal.
All model responses/SDKs are scripted; these are not live model-quality evaluations.

Use the isolated mock environment from the Summary setup above, substituting **8095**
for 8093, adding `PYTHONPATH="$PWD"`, and replacing the server command with:

```sh
.venv/bin/python -m uvicorn project_brief_app:app --app-dir tests/browser \
  --host 127.0.0.1 --port 8095
```

The fixture refuses databases outside `/private/tmp`, delegates ordinary chat to
its deterministic provider and supplies a known brief only for the explicit test
conversation. It is a test app, never a production startup target. Run after building:

```sh
"$PWCLI" -s=brief open http://127.0.0.1:8095 --headed
"$PWCLI" -s=brief run-code --filename tests/browser/project_brief.js
"$PWCLI" -s=brief run-code --filename tests/browser/project_brief_qa.js
"$PWCLI" -s=brief run-code --filename tests/browser/summary_design_qa.js
"$PWCLI" -s=brief run-code --filename tests/browser/summary_hierarchy.js
```

These cover the whole-chat brief, click-to-generate and tooltip, immediate download, explicit unknowns, clean
collapsed defaults, actual saved feedback counts, skill detail/tips, error recovery,
keyboard/touch/overflow and desktop/phone Light/Dark. Screenshot/export output is
under ignored `output/playwright/project-brief/`. Rerun existing Summary, Review
and bookmark scripts against this API using temporary copies with 8093/8094 replaced
by 8095. `review_restart.js` runs twice around a real disposable API restart without
navigating between calls. Do not use personal data or a paid provider for this setup.

Normal mock app responses report an unavailable preview instead of inventing a
semantic summary. A real configured AgentCore model needs the updated Review runtime
contract as well as the app. Full evidence and limits:
[Project brief handoff](specs/PROJECT_BRIEF_HANDOFF.md).

## Review refinements and restoration

Use the disposable mock stack on **8093** above; keep personal servers/databases separate.
After building, run the following through the same Playwright CLI session. The first
script signs in a disposable guest; the others reuse that browser identity and selected
chat. Run the two existing Summary scripts too, then the existing bookmark regression
(substitute 8093 for 8094 in a temporary copy when sharing this test stack).

```sh
"$PWCLI" -s=review open http://127.0.0.1:8093 --headed
"$PWCLI" -s=review run-code --filename tests/browser/review_refinements.js
"$PWCLI" -s=review run-code --filename tests/browser/review_overview.js
"$PWCLI" -s=review run-code --filename tests/browser/review_persistence.js
"$PWCLI" -s=review run-code --filename tests/browser/review_boundaries.js
```

These verify independent stage/group disclosure, exact saved mixed-mode prompt excerpts
and recap, visibility-reset restoration, real navigation away/back, reload, explicit
close actions, mobile draft insertion, chat and owner boundaries, keyboard use, 44px
controls, no Review writes, console errors and overflow at 1440/900/390 in Light/Dark.
Theme capture waits for the actual rendered theme. The CLI suppresses native tab hiding,
so the visibility test supplies `document.hidden` plus `visibilitychange` explicitly;
navigation away/back is real. It asserts the private-content checking screen before
owner-verified restoration. Deliberate guest-cookie swaps allow only the expected 401
session probes; other console errors fail. Test fixtures never use paid providers.

Run `review_restart.js` twice around an actual stop/start of the disposable API using
its unchanged environment/database. Do not navigate between calls: the first keeps its
public baseline in the test page. The second compares project, messages and bookmarks,
reloads and verifies the restored open Summary. Screenshots are under ignored
`output/playwright/review/`. Stop disposable services and browsers afterward.
See [Review refinement evidence](specs/REVIEW_REFINEMENTS_HANDOFF.md).

## Current gaps

Passing local tests do not prove:

- real Cognito Hosted UI/session behavior;
- wire-level Aurora DSQL concurrency or IAM grants;
- real S3 bucket policy/object lifecycle;
- paid OpenAI behavior;
- ARM64 image execution and container replacement;
- durable graph inspection after process restart;
- true upstream provider-token streaming;
- browser accessibility, console, and layout across engines.

Other tooling gaps are tracked rather than overstated: Ruff is installed and
enforced by project CI; static typing has no configured gate, coverage is not
measured, and Markdown links are not checked in CI.

Run `.venv/bin/ruff check .` separately from `sh scripts/build.sh`: the build
checks TypeScript/Vite, Vitest, offline OpenAPI/client drift, Python compilation
and mock pytest, but does not invoke Ruff. There is no configured frontend lint
script. For numbered duplicate generator files, use the
[dependency repair guidance](../frontend/README.md#generated-read-contracts)
before regenerating checked-in source. Keep fixture environment guards before
application imports, which can construct storage at import time.

## Mock load probe

Virtual users are **distinct authenticated owners**. The probe must not treat a
shared `local-student` store as many students.

The probe checks FastAPI concurrency, owner isolation, rate limits, SQLite
persistence, and Knowledge Base Retrieve admission. Treat delays and latency
percentiles as mock results. Use the [classroom capacity gate](operations/CLASSROOM_CAPACITY_GATE.md)
for the stepped 80-session rehearsal, bounded generation, restart and restore,
the stepped 1/10/20/40/60/80 **mixed** workload probe (navigation, ordinary and
grounded coaching, deliberate OCC races, canvas autosaves and durable Deep
Review submissions with percentiles, queueing, reconciliation and the capped
live procedure), and the remaining live capacity and cost decisions. For
offline monthly SGD cost scenarios with dated pricing estimates and
regional trade-offs, run `scripts/cost_scenarios.py`
(see [cost accounting](COST_ACCOUNTING.md)); its totals are estimates,
never bills, and the S$30 gate stays unresolved there.

```bash
PYTHONPATH=. .venv/bin/python scripts/load_probe.py --users 10 --requests-per-user 5
PYTHONPATH=. .venv/bin/python scripts/load_probe.py --scenario distinct-owners --users 100
PYTHONPATH=. .venv/bin/python scripts/load_probe.py --scenario two-notebooks
PYTHONPATH=. .venv/bin/python scripts/load_probe.py --scenario same-notebook
PYTHONPATH=. .venv/bin/python scripts/load_probe.py --scenario slow-distinct-owners --users 10
PYTHONPATH=. .venv/bin/python scripts/load_probe.py --scenario kb-pool --kb-workers 4 --users 16 --kb-delay-ms 500
PYTHONPATH=. .venv/bin/python scripts/load_probe.py --run-phase existing
PYTHONPATH=. .venv/bin/python scripts/load_probe.py --run-phase slow --provider-delay-ms 10000
PYTHONPATH=. .venv/bin/python scripts/load_probe.py --run-phase kb
PYTHONPATH=. .venv/bin/python scripts/load_probe.py --run-phase correctness
```

`--users` is clamped to 1–120. Fake provider delay is script-only (patch of
`DeterministicCoachProvider.assess` restored on exit). Fake KB delay injects a
client into the **real** `BedrockKnowledgeBaseRetriever`; only `client.retrieve`
is faked. Production worker count is not changed.

Scenarios:

| Scenario | What it measures | Expected mock result |
|---|---|---|
| `sequential` | Distinct owners, sequential turns per notebook | accepted |
| `distinct-owners` | One concurrent turn per distinct owner | N users accepted under global 120 |
| `two-notebooks` | One owner, two notebooks, overlapping turns | both accepted (`MAX_ACTIVE_COACH_REQUESTS_PER_USER=2`) |
| `same-notebook` | One owner, one notebook, overlapping turns | 1 accepted, 1 HTTP 429 |
| `slow-distinct-owners` | Same as distinct-owners with a fake provider sleep | accepted; P95 ≈ fake delay, not Haiku |
| `kb-pool` | Real Retrieve admission/validation + fake `client.retrieve` | `min(users, workers)` accepted; excess `capacity_exhausted` |
| `kb-timeout-slot` | Fake Retrieve longer than timeout | timed-out calls keep the slot; excess fail closed |
| `kb-fail-closed` | Fake hits from a foreign bucket | zero chunks; no unrelated evidence |
| `slow-idempotency` | Same idempotency key replayed | HTTP 200 twice, one provider call |
| `failed-no-partial` | Fake provider raises | no assistant turn persisted |
| `ownership-isolation` | Distinct owners list threads / read messages | zero ownership violations |

Each printed line is JSON with:

`scenario`, `users`, `fake_provider_delay_ms`, `fake_kb_delay_ms`, `kb_workers`,
`requests`, `accepted`, `rate_limited`, `capacity_exhausted`, `failed`,
`p50_ms`, `p95_ms`, `mean_ms`, `requests_per_sec`, `peak_threads`,
`peak_kb_admitted`, `peak_kb_worker_threads`, `rss_peak_kb`,
`process_max_rss_kb`.

`rss_peak_kb` is kept for compatibility. It is **not** exact per-scenario
incremental memory: both RSS fields are the process-lifetime maximum RSS
from `resource.getrusage(RUSAGE_SELF).ru_maxrss` (a high-water mark).
`process_max_rss_kb` is the same value with a clearer name.

Irrelevant fields are JSON `null`. Aggregate metrics only (no notebook IDs,
emails, or message text).

The probe uses a temporary SQLite store and the mock coach. It never calls
AgentCore, Bedrock models, Knowledge Base, DSQL, S3, or Cognito. CLI bootstrap
and the runtime mutation path both force `APP_ENV=development` and
`COURSE_MATERIAL_SYNC_ENABLED=false` (snapshot/restore includes those
fields even if `backend.settings` was already imported). RPM is raised
to 10_000 so this measures concurrency architecture, not the production
`COACH_REQUESTS_PER_MINUTE=8` cap. That production cap is **per
authenticated user**, not a class-wide 8-RPM ceiling. Ninety distinct
students each sending one request can pass the per-user RPM rule; class
burst ceilings are global concurrency (`MAX_CONCURRENT_MODEL_CALLS`), the
AnyIO thread limiter, AgentCore, and Knowledge Base Retrieve capacity.
`SYNC_THREADPOOL_TOKENS` is set to 120 to match Compose.

Pytest uses tiny delays only. Do not put 5–12 second sleeps on the CI path.

### Constrained Docker rehearsal

Local Docker with `--cpus=2 --memory=2g` approximates a CPU and memory limit for
local mock testing. Use the target EC2 host for pilot capacity measurements.

Do **not** run `compose.prod.yaml` or `scripts/start_prod.sh` for this phase:
those wire AgentCore, DSQL, S3, and Cognito.

Simplest safe method (mock + SQLite inside a constrained container):

```bash
docker run --rm \
  --cpus=2 \
  --memory=2g \
  --memory-swap=2g \
  --pids-limit=512 \
  -e MODEL_PROVIDER=mock \
  -e MOCK_OPENAI=true \
  -e DATABASE_PROVIDER=sqlite \
  -e FILE_STORAGE_PROVIDER=local \
  -e KNOWLEDGE_BASE_ID= \
  -e MAX_CONCURRENT_MODEL_CALLS=120 \
  -e SYNC_THREADPOOL_TOKENS=120 \
  -e PYTHONPATH=/work \
  -v "$PWD":/work \
  -w /work \
  python:3.12-bookworm \
  bash -c 'pip install -q -r requirements.txt && python scripts/load_probe.py --scenario distinct-owners --users 25 && python scripts/load_probe.py --scenario slow-distinct-owners --users 10 --provider-delay-ms 5000 && python scripts/load_probe.py --scenario kb-pool --kb-workers 4 --users 30 --kb-delay-ms 500'
```

If installing `requirements.txt` inside the container is too heavy, run the
same `scripts/load_probe.py` commands on the host with `.venv/bin/python` and
treat Docker as optional confirmation, not as a substitute for a live EC2
pilot.

## Phase handoff

Report focused and full results separately, including failures and warnings.
State what was not tested, whether any live system was contacted, migration and
rollback impact, browser evidence, and the next exact validation step. Test
counts and current phase evidence belong in
[`IMPLEMENTATION_STATUS.md`](IMPLEMENTATION_STATUS.md), not duplicated here.

## Starred-message regression (#31)

The authenticated HTTP seam is `tests/http/test_starred_messages.py`. It covers
both authors, explicit/idempotent state, ownership and origin guards, legacy
context, complete bookmark reads beyond the transcript page, edits/removal,
restart, concurrent ratings/appends and invisible transition rows. All fixtures
use disposable SQLite and deterministic mock providers.

Use the isolated mock startup under [Saved Summary browser regression](#saved-summary-browser-regression-30),
substituting port **8094** in both URLs and the server argument, and a fresh
`/private/tmp/codesign-stars-*` root. Keep the same mock, SQLite/local and guest
settings; set `STUDENT_STAGE_SELECTION=true`. Never use a personal database.
Build React, then run:

```sh
mkdir -p output/playwright/stars-31
PWCLI="$HOME/.codex/skills/playwright/scripts/playwright_cli.sh"
"$PWCLI" -s=stars31 open http://127.0.0.1:8094 --headed
"$PWCLI" -s=stars31 run-code --filename tests/browser/starred_messages.js
```

This creates a guest-owned chat over HTTP and checks star/unstar for both authors,
bookmark-only My work, refused-save feedback, old-message loading, exact jump/focus
and highlighting, reload, Lecture Help tags, keyboard controls, 44px phone targets,
Light/Dark desktop/390px layouts and console errors. It deliberately simulates one
503 write response; that expected network error is excluded from the clean-console
assertion. Request routes are cleared at the start so a failed regression cannot
leave its simulation active in the next run. Screenshots go under the ignored
`output/playwright/stars-31/` directory.

For imported history, get the disposable guest's `owner_id` from the browser's
`/api/v1/reader/session` response, then run:

```sh
PYTHONPATH=. MODEL_PROVIDER=mock MOCK_OPENAI=true .venv/bin/python \
  tests/browser/seed_starred_messages_legacy.py \
  --database /private/tmp/codesign-stars-EXAMPLE/workspace.sqlite3 \
  --owner-id THE_DISPOSABLE_GUEST_OWNER_ID
"$PWCLI" -s=stars31 run-code --filename tests/browser/starred_messages_legacy.js
```

The seeder refuses databases outside `/private/tmp` and non-guest owners. It adds
an imported quick chat containing starred and unstarred historical rows. Run it
once per fresh fixture; the legacy regression verifies collapsed/populated No stage,
last-star removal and stage empty guidance. This fixture-only seeding is not a product import feature.

For a real process restart, run `tests/browser/starred_messages_restart.js` once,
stop and restart the same mock API against the same disposable database, then run
it again **without reloading the browser between those two calls**. It compares
complete public bookmark/transcript/project responses and then reloads My work.
Also rerun both Summary regressions against this API (substitute 8094 for their
8093 URL in temporary copies) to protect #30. See the
[bookmark handoff](specs/STARRED_MESSAGES_HANDOFF.md) for acceptance evidence.

### Star visibility and My work hierarchy

Against the same disposable mock stack on **8094**, run after building:

```sh
"$PWCLI" -s=mywork open http://127.0.0.1:8094 --headed
"$PWCLI" -s=mywork run-code --filename tests/browser/my_work_polish.js
```

This signs in a disposable guest, saves both authors and verifies the actual Chat
pressed state, gold hue/solid fill, parent stage regions, differentiated heading
colour, inset entries and selected My work star controls. It checks keyboard
collapse/expand, unstar/re-star, saved-state reload, 44px group/actions, horizontal
overflow and unexpected console errors at 1440/900/390 in Light/Dark. Captures are
under ignored `output/playwright/mywork-polish/`. The original reproduction showed
`aria-pressed=true` with an indigo outline and almost-transparent fill; this is a
CSS-state regression, not a persistence test replacement. Continue running the
existing bookmark failure/old-page jump and Summary regressions. Stop only the
disposable browser/server after validation. No personal data or paid provider.

## Working/latest circle and saved-preview bounds

Use the disposable mock environment on **8094** from the bookmark setup. After
building, run through the existing Playwright CLI:

```sh
"$PWCLI" -s=latest open http://127.0.0.1:8094 --headed
"$PWCLI" -s=latest run-code --filename tests/browser/chat_latest_control.js
"$PWCLI" -s=latest run-code --filename tests/browser/chat_latest_control_qa.js
"$PWCLI" -s=latest run-code --filename tests/browser/latest_above_hints.js
```

The first script creates its own guest/chat and newline-heavy saved message. It
holds the real mock stream at the HTTP boundary to observe working dots, then
releases it to verify the finished arrow is hidden at the bottom, appears after
scrolling up and hides again after either a keyboard jump or manual scrolling.
It also checks actual intermediate smooth scrolling, 44px placement, keyboard scrolling,
no interrupted save and intact full original. The bookmarks API must return a
320-character preview; rendered height must stay within six base text lines.
The second script reuses that chat and checks working/complete/preview states at
1440/900/390 in Light/Dark, working dots at the bottom, scroll-aware idle-arrow
visibility (including a small upward scroll), reduced-motion animation suppression, Enter/Space,
no send/replay from the scroll control, preview bounds and full original jumps.
It waits for asynchronous Review close before testing the next composer state.
The third script uses the same disposable chat, switches to Design coaching,
then verifies the 32px visible circle/44px tap target is fully above a coach
check-in, expanded suggestions and Show suggestions with an 8px visible gap.
It checks that the circle overlays the transcript without reserving a blank row,
that pointer hit-testing beside it reaches the transcript, and that its own
surface remains opaque. It checks Light/Dark
desktop/390px, keyboard jump and console errors. Run after the first script has
created a fresh chat (the check-in must not already be dismissed).
Screenshots are under ignored `output/playwright/latest-control/`. Stop only the
disposable browser/backend. Also run the existing bookmark failure/jump and Summary
regressions. No paid providers or personal data are used.

## In-place message editing

After the latest-control fixture creates a fresh disposable chat, run:

```sh
"$PWCLI" -s=latest run-code --filename tests/browser/message_edit.js
"$PWCLI" -s=latest run-code --filename tests/browser/message_edit_qa.js
```

The first checks exact original text, no duplicate saved text while editing,
automatic short/long width and height growth/shrinking without a resize handle, and bordered
icon-only actions inside the shared textbox at bottom
right (with reserved text space above), cancel/focus and draft
preservation. The second checks Light/Dark desktop/390px, compact one-line edits, long scrolling text,
empty-value prevention, newline Enter, Escape, hover colours, 44px actions,
one successful revision and reload, and one mocked HTTP failure. Recovery must
use reads without automatically resubmitting; Discard and edit must retain both
the existing composer draft and attempted edit. It intentionally changes only
the disposable chat, so run it after tests that require the original long text.
Screenshots use ignored `output/playwright/latest-control/edit-*.png`.
The existing latest-control QA also checks output arriving during smooth movement
and OS reduced-motion behavior. No paid calls or personal data are used.

## Reply streaming (normal messages, edits and AgentCore)

Regular sends and `/messages/{id}/revise/stream` use the shared FastAPI NDJSON
`StreamingResponse`. The legacy JSON revise route is retained. React reads both
with `response.body.getReader()` and requests `X-Coach-Reply-Deltas: 1`.
`COACH_STREAM_REPLY_DELTAS_ENABLED` defaults true; false disables deltas without
changing final save/recovery semantics. Caddy flushes POST responses immediately.
Direct Bedrock uses ConverseStream, AgentCore Fast Chat opts into the runtime SSE
protocol, and optional OpenAI consumes Responses text-delta events. The runtime
must be published to the existing ARN before its live deltas are available.

Focused deterministic checks:

```sh
.venv/bin/python -m pytest -q tests/domain/test_reply_streaming.py tests/domain/test_bedrock_provider.py tests/domain/test_agentcore_provider.py tests/domain/test_runtime_reply_stream.py tests/domain/test_prompt_architecture.py tests/http/test_reader_conversation.py
```

Use the process-local tests-package binding documented above where needed.
Provider/runtime tests pause SDK generation to prove fragments arrive before the
terminal result. Cases cover private-field filtering, malformed/truncated streams,
closure, structured retry/discard, saved validation and exact-key replay. The
optional pinned-SDK test module is `tests/domain/test_strands_first_cycle_middleware.py`;
run after installing `agentcore_runtime/requirements.txt` in a disposable venv.

For rendered QA, use the **disposable mock delayed-NDJSON fixture** described in
[the streaming handoff](specs/REPLY_STREAMING_HANDOFF.md), on port 8096.

For the event-based activity regression, additionally set
`STREAM_FIXTURE_INITIAL_DELAY_SECONDS=7` and
`STREAM_FIXTURE_SAVE_DELAY_SECONDS=1` before starting that fixture. Run
`tests/browser/chat_progress.js` with Playwright CLI. It checks the waiting
indicator stays indeterminate, writing/saving/completion states, saved reload,
failure without replay, cancelled/discarded previews, new-owner isolation,
reduced motion, and 1440/390 px light/dark layouts. Screenshots go to
`/private/tmp/chat-progress-*.png`. The delay settings default to zero for
existing tests. The fixture operates only on disposable mock workspaces.
Open the fixture's URL before running the script; it uses that origin, so a
different free loopback port can be used without touching an existing server.
Run `tests/browser/identity_inflight.js` afterward to verify that changing Guest
identity aborts a pending generation, drops its late response and never replays
the write. It creates only synthetic chats and intercepts the model request.

```sh
"$PWCLI" -s=streaming open http://127.0.0.1:8096 --headed
"$PWCLI" -s=streaming run-code --filename tests/browser/real_reply_streaming.js
"$PWCLI" -s=streaming run-code --filename tests/browser/reply_streaming_qa.js
"$PWCLI" -s=streaming run-code --filename tests/browser/batched_reply_streaming.js
```

The relay slows delivery of real mock-server events for observation; this proves
browser rendering, not live LLM latency. Check growing normal/edited text,
provisional labels/no saved-message actions, 1440/390 Light/Dark, OS reduced
motion, retained drafts, no replay and the console. Wait for authoritative refresh
before selecting the edited message by its stable id. Captures are under ignored
`output/playwright/reply-streaming/`. Existing edit/recovery/bookmark/Summary
regressions remain applicable; editor request intercepts now target `/revise/stream`.
No paid calls or deployment are authorized by these commands.

## Browser contract and frontend unit checks

For the CDE2300 bootstrap follow-up, open an isolated mock server and run
`tests/browser/workspace_loading.js`, `bootstrap_identity.js`,
`bootstrap_preferences.js` and the existing `identity_inflight.js` through
Playwright CLI. The loading script records three trials each at 0/100ms injected
reader-request delay; this is a synthetic transport input, not measured RTT.
Its SPA `settledMs` includes an explicit 800ms drain and is not a latency metric.
Identity regressions hold the old response or generation across a Guest change;
no real provider is called. Preference screenshots go to `/private/tmp/cde2300-bootstrap-*.png`.
See the [retained evidence and limitations](operations/ARCHITECTURE_IMPROVEMENTS.md#cde2300-bootstrap-follow-up).

```sh
.venv/bin/python scripts/export_reader_openapi.py --check
npm run api:check --prefix frontend
npm test --prefix frontend
```

These checks are included in `scripts/build.sh` and Mock CI. Vitest exercises
the real generated transport with stubbed Fetch, Query cancellation/identity
cleanup, and NDJSON framing/lifecycle. The exporter tests production-shaped
environment isolation, deterministic output, allowlisted schemas and drift
refusal. No test uses a paid provider. See the
[client update workflow](../frontend/README.md#generated-read-contracts).
`tests/__init__.py` ensures shared helpers resolve to this repository even when
a dependency installs another package named `tests`; retain the existing bare
helper import path in `tests/conftest.py` for compatibility.

## Architecture baseline matrix

Run these locally against new disposable data, without other tests competing
for resources, and retain the aggregate JSON rows:

```sh
for users in 1 10 20 40 60 80; do
  .venv/bin/python scripts/load_probe.py --scenario distinct-owners --users "$users"
done
```

The probe reports nearest-rank p50/p90/p95/p99/max, throughput, errors,
admission rejections, thread high-water mark and process maximum RSS. Earlier
reports used a floor-based percentile estimator and omitted tail/max fields;
do not compare small-sample p95 across estimators. One burst per level is a
smoke baseline, not statistically stable capacity evidence. No real model,
DSQL, network proxy or browser latency is represented. See the
[audit and milestone evidence](operations/ARCHITECTURE_IMPROVEMENTS.md).

## Architecture-completion baseline (local ticket 01)

The [fresh baseline ledger](IMPLEMENTATION_STATUS.md#local-completion-ticket-01--fresh-baseline-2026-11-24-sgt) records exact build/lint/collection results, safe startup settings and remaining gates. Against the disposable Summary stack on 8093, run `tests/browser/baseline_citations.js` and `tests/browser/baseline_stage_confirmation.js` through the existing Playwright CLI. They verify local uploaded evidence, saved citations/original bytes, exact-key recovery and visible student confirmation without paid calls. Run the stage probe after the citation probe. Use the existing delayed reply fixture for visible streaming; the ordinary mock API is sufficient for these two probes.

For an offline machine where the CLI wrapper attempts registry access, use an already installed Playwright CLI entry point; do not claim the wrapper worked or install dependencies implicitly. Collect skip reasons with `.venv/bin/python -m pytest --collect-only -o addopts='' -q -rs` when the configured double-quiet output hides collection skips.
