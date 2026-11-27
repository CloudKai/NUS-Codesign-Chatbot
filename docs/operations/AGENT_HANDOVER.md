# OpenCode implementation handover

Checkpoint on 24 November 2026 SGT. The user paused implementation for transfer
to OpenCode. The [implementation ledger](../IMPLEMENTATION_STATUS.md#current-status)
remains the source of truth for acceptance and evidence. Resume with ticket 05
in the existing checkout when the user starts the OpenCode session.

## Checkout and approved scope

- Working directory `Co-design Chatbot`, branch `improvement/architecture-responsiveness`,
  tracking `origin/improvement/architecture-responsiveness` as reported by local Git.
- HEAD `4f12995afbfba4c5c975ad12eb9874fcd4cfea39` (24 November 2026),
  `Improve CDE2300 loading, reader contracts, and output safety`.
- Preserve the dirty checkout and untracked files. In particular, carry the
  entire `.scratch/architecture-completion/` directory if the checkout is moved.
  A clone of HEAD alone omits the approved local tickets and working-tree evidence.
- The approved [specification](../../.scratch/architecture-completion/SPEC.md)
  retains the supplied 101-section brief as an implementation spec and coverage
  map. The [local execution pack](../../.scratch/architecture-completion/README.md)
  defines all 53 tickets, their dependencies and the testing agreement. Start
  with the [repository guide](../../AGENTS.md), [ticket execution](../CONTRIBUTING.md#ticket-execution),
  [glossary](../../GLOSSARY.md) and [architecture](../LOCAL_DEMO_IMPLEMENTATION.md).
- Local ticket numbers are independent of the historical GitHub rollout.
  Existing release gates [#28](https://github.com/CloudKai/NUS-Codesign-Chatbot/issues/28)
  (classroom capacity/cost) and [#29](https://github.com/CloudKai/NUS-Codesign-Chatbot/issues/29)
  (React release/comparison) remained open in the recorded discovery.
  [#30](https://github.com/CloudKai/NUS-Codesign-Chatbot/issues/30) (Summary feedback)
  and [#31](https://github.com/CloudKai/NUS-Codesign-Chatbot/issues/31) (stage-grouped
  bookmarks) were implemented and verified locally and last recorded open.
  The transfer did not refresh or change GitHub state. The 53-ticket pack is local.

## Accepted work and active ticket

| Scope | Status | Evidence and remaining boundary |
| --- | --- | --- |
| Pre-programme baseline | Implemented and locally verified | React verified bootstrap and four generated reader operations, owner-fenced Query foundation, honest progress, and runtime suppression of provisional Mantle output. The source safety fix has local regression evidence. Live publication and compatible session rollover remain unverified. See the [baseline and bootstrap ledger entries](../IMPLEMENTATION_STATUS.md#cde2300-verified-bootstrap-and-fewer-startup-requests-2026-11-24-sgt). |
| Ticket 01, baseline and coverage | Verified and locally accepted | Built React, disposable mock FastAPI/SQLite and Streamlit startup, citation retrieval, stage confirmation, normal and edited streaming, owner switch and actual API restart. Recorded build/lint reds and timing limitations. [Evidence](../IMPLEMENTATION_STATUS.md#local-completion-ticket-01--fresh-baseline-2026-11-24-sgt) |
| Ticket 02, lint and collection | Implemented, verified and locally accepted | Fixed ten Ruff findings in five files, rebuilt ignored frontend dependencies from the unchanged lockfile, restored generator consistency and completed the mock gate. [Evidence](../IMPLEMENTATION_STATUS.md#local-completion-ticket-02--lint-and-collection-blockers-2026-11-24-sgt) |
| Ticket 03, repository privacy | Audit implemented, verified and locally accepted | Redacted inventory and publication review queue. Redistribution, comprehensive history/artifact review and Docker context remediation remain open. [Audit](../security/PUBLIC_REPOSITORY_CONTENT_AUDIT.md) |
| Ticket 04, deployment and safety records | Records implemented, verified and locally accepted | Versioned nonsecret manifest and runtime publication, session and rollback procedures. Live values remain unknown. The historical V1 v38 and V2 v39 record supplies provenance only. [Safety record](../deploy/DEPLOYMENT_SAFETY_RECORD.md) |
| Milestone 0 | Local baseline and record scope verified | Ticket 01–04 acceptance is recorded. Edge parity, packaging, redistribution and live runtime/safety verification remain open. |
| Ticket 05, browser CI | Implemented, verified and locally accepted | Playwright Test slice (`frontend/tests/browser/`, `tests/browser/disposable_stack.py`, `tests/browser/registered_stack_app.py`) covers the Guest journey with reload recovery, in-flight owner-switch fault injection, interrupted-stream exact-key recovery, the synthetic registered identity and real backend restart persistence; wired as the finite `browser-ci-slice` Mock CI job. Live Cognito Hosted UI sign-in remains a documented manual gap. [Evidence](../IMPLEMENTATION_STATUS.md#ticket-05-complete--browser-ci-slice-2026-11-24-sgt-opencode) |
| Ticket 06, lifecycle extraction | Unblocked — next ticket | Extract the chat lifecycle without changing behavior; the browser slice is the safety net. |

Ticket 05 is an early prerequisite for milestone 2 (frontend foundation). Existing
manual browser scripts and deterministic HTTP fixtures provide working starting
coverage. The integrated Playwright Test journey, synthetic registered browser
journey, finite process supervision and automated restart/fault assertions are
still pending. The interrupted writer did not implement a new feature.

## Working tree at transfer

Run `git status --short --branch` and review diffs before editing. Before these
handover edits, Git reported 15 modified tracked files, 62 untracked files and
an empty staged diff.

| Existing changes | What to preserve |
| --- | --- |
| `.agents/tasks/phase3d-work/sol-teacher/run.py`, `backend/coaching/streaming.py`, `tests/browser/project_brief_app.py`, `tests/browser/reply_streaming_fixture.py`, `tests/domain/test_gemma_native_json.py` | Ticket 02 lint fixes. Streaming still gives cancellation precedence and discards provisional text before error. Fixture factories preserve pre-import setup. |
| `docs/CONTRIBUTING.md`, `docs/IMPLEMENTATION_STATUS.md`, `docs/LOCAL_DEMO_IMPLEMENTATION.md`, `docs/PRODUCTION_RELEASE_CHECKLIST.md`, `docs/README.md`, `docs/SECURITY_BOUNDARIES.md`, `docs/TESTING.md`, `docs/deploy/AWS_STATELESS_EC2.md`, `docs/providers/MODEL_PROVIDERS.md`, `frontend/README.md` | Prior publication, testing, privacy and release documentation. This transfer also updates the status ledger. |
| `.scratch/architecture-completion/` | Untracked approved spec, dependency graph and 53 local issue files. Tickets 01–04 contain accepted local checklists. Leave ticket 05 unchecked until verified. |
| `tests/browser/baseline_citations.js`, `tests/browser/baseline_stage_confirmation.js`, `docs/examples/performance/architecture-ticket01-2026-11-24.json` | Untracked manual probes and reproducible measurements. |
| `docs/security/PUBLIC_REPOSITORY_CONTENT_AUDIT.md`, `docs/examples/security/repository-privacy-2026-11-24.json`, `docs/deploy/DEPLOYMENT_SAFETY_RECORD.md`, `docs/examples/deployment/architecture-ticket04-2026-11-24.json` | Untracked privacy audit and deployment evidence. |

This transfer adds this document and its ledger entry. No runtime rollback or
database restore is needed for the transfer. Treat ignored `.env`, databases,
uploads, credentials and old captures as private. Transfer the working-tree
source and approved evidence through the existing checkout.

## Architecture, dependencies and contracts

| Entry point | Responsibility |
| --- | --- |
| [frontend/src/Conversation.tsx](../../frontend/src/Conversation.tsx) and [stream.ts](../../frontend/src/stream.ts) | Composer, provisional output, cancellation and exact-key recovery. NDJSON framing, validation and stream identity. Lifecycle extraction belongs to ticket 06. |
| [frontend/src/useReader.ts](../../frontend/src/useReader.ts), [frontend/src/api](../../frontend/src/api), [schema exporter](../../scripts/export_reader_openapi.py) | Verify identity, fence private reads, manage selection, adapt same-origin requests and generate the allowlisted reader SDK offline. |
| [backend/http/app.py](../../backend/http/app.py), [notebook_reader.py](../../backend/http/notebook_reader.py), [reader_workspace.py](../../backend/http/reader_workspace.py) | FastAPI composition, admission and auth. Same-origin production assets, owner-scoped reader projections and workspace mutations, stream and receipt routes. |
| [backend/auth_oidc.py](../../backend/auth_oidc.py), [tests/http/test_production_critical_path.py](../../tests/http/test_production_critical_path.py) | Cognito boundary and reference deterministic registered-identity adapter injected into `create_app`. |
| [backend/coaching/streaming.py](../../backend/coaching/streaming.py), [backend/workflow.py](../../backend/workflow.py), [backend/learning_service.py](../../backend/learning_service.py) | Stream events, one workflow, server learning authority and confirmation-gated transitions. |
| [backend/student_store.py](../../backend/student_store.py), [store schema and migrations](../../backend/persistence/store), [database guide](../DATABASE.md) | Durable SQLite/DSQL notebook, history, revision, source, learning and recovery boundaries. |
| [agentcore_runtime](../../agentcore_runtime), [stream relay](../../tests/browser/reply_streaming_fixture.py), [Mock CI workflow](../../.github/workflows/mock-ci.yml) | Runtime safety path, real mock NDJSON with timing control, and the existing build/validation job to extend. |

React/TypeScript, Vite and Tailwind form the student frontend. TanStack React
Query supports owner-scoped confirmed data. Current private retention stays
zero until measurement and account-switch tests justify a policy. Hey API
generates the allowlisted client from offline OpenAPI, keeping FastAPI/Pydantic
as contract authority. Vitest covers frontend unit behavior. FastAPI and a
single LangGraph workflow keep canonical educational state outside presentation
and provider adapters. SQLite and local files provide the deterministic local
path. Production adapters include DSQL, S3, Cognito and AgentCore. The existing
protected Streamlit staff and Enabled Access entrypoint stays supported.

Tickets 01–04 introduced no new installed dependency or schema requirement.
Ticket 05 has yet to add `@playwright/test` and its compatible Chromium install
for finite browser CI. The existing Playwright CLI supports manual scripts.
TanStack Router, React Flow, Tiptap and additional component/accessibility tooling
are planned by the approved spec. Review dependency changes within the owning
ticket and validate them through the lockfile.

Current generated reader GETs cover `/api/v1/reader/session`, `/threads`,
`/bootstrap`, and `/threads/{thread_id}/messages/page` beneath the reader prefix.
Bootstrap returns one verified owner's session, notebook list and preferences.
The browser re-verifies the owner before showing private content. Chat retains
its reader `POST /threads/{thread_id}/{lecture|project}/stream` and message-revision
stream, `GET /threads/{thread_id}/coach-turn?idempotency_key=...` for recovery, and
`POST /threads/{thread_id}/coach-turn/stop`. NDJSON events remain `started`,
`status`, `reply_delta`, `reply_discard`, `reply_ready`, `graph`, `done` and
`error`. Committed output requires saved `done` or an authoritative exact-key
receipt. Existing SQLite/DSQL persists turn pairs and idempotency receipts with
owner/notebook scope, payload fingerprints, leases and revision checks.
There are no new API methods, schema changes, migration steps or changes to
production configuration in tickets 01–05 at this checkpoint. Artifact, canvas,
version and durable-job schema work is pending. Future additive migrations need
a backup, compatibility verification and a rollback path.

## Invariants and execution contract

- Preserve CDE2300 data, existing entrypoints, student and staff experience,
  notebook/source isolation and the separate course deployment. SQLite/DSQL
  remains the only durable transcript. Keep internal runtime session IDs opaque.
- Scope all private reads and writes to verified owners. Preserve same-origin
  HttpOnly cookies, exact proxy allowlists, private `no-store`, revision checks,
  and auth renewal. Abort old reads/streams and reject late results on an owner
  change. Keep private content and tokens out of logs and persistent browser caches.
- Preserve explicit retry under the original key and read-only reconciliation
  for interrupted or ambiguous responses. Keep drafts and provisional content
  separate from confirmed Query data. Give discarded fragments no saved-message
  actions and suppress Mantle preview text before final Guardrail validation.
- Lecture help uses authorised evidence. Project coaching uses the five Thinking
  Path stages. Structured validated stage recommendations require explicit Stage
  confirmation for first-time advancement. Preserve Stage revisit rules and
  student authorship. No AI authorship change, canvas metric or generated recap
  can independently confer progression. Preserve exact citation-to-source mapping.
- Use one writer per ticket and fresh ticket context. Prior client writer choice
  was `gpt-6.2-sol`. Use the available OpenCode routing and report any unavailable
  model rather than claiming a switch. After two evidence-based attempts at the
  same failure, record the blocker and follow the root escalation rule.
- The approved primary seam is the student-visible browser through production
  React and real same-origin FastAPI into disposable persistent SQLite. Supporting
  seams are public FastAPI validation/ownership, storage/worker restart and
  migration contracts, and runtime/provider guardrails/structured output. Use
  deterministic external adapters. For behavior changes, demonstrate one public
  regression red for the intended reason before the minimal green fix. Reuse
  working characterization for a test/CI conversion. No approval is needed to
  use these seams. Keep browser fixtures synthetic and disposable.

## Executed checks and open verification gaps

The archived commands below are prior executed evidence. The transfer itself is
documentation-only. It did not rerun application tests.

| When | Exact command or recorded procedure | Result |
| --- | --- | --- |
| Ticket 01 | `sh scripts/build.sh` | Initial exit 1 at `npm run api:check --prefix frontend`. Vite, TypeScript, 30 Vitest tests and offline schema check passed first. Ticket 02 resolved the installed dependency contamination. |
| Ticket 01 | `.venv/bin/python -m pytest -q` and `.venv/bin/ruff check . --output-format json` | Python passed 3,210 tests, with one optional module skipped. Ruff identified ten findings in five files. Ticket 02 cleared them. |
| Ticket 01 | Existing Playwright CLI `-s=ticket01 run-code --filename PATH` against the disposable direct-origin stack, with actual stop/restart between the `review_restart.js` runs | Saved transcript and Review reopened identically. Citation upload and original bytes, exact-key receipt, explicit stage confirmation, streamed normal/edit turns, desktop and 390 px Summary, and owner switch without replay passed. The [ledger](../IMPLEMENTATION_STATUS.md#disposable-startup-browser-and-restart-checks) lists the exact startup and script sequence. |
| Ticket 02 | `npm ci --offline --ignore-scripts --prefix frontend` then `npm run api:check --prefix frontend` | Both exited 0. Restored the installed package tree from the unchanged lockfile. |
| Ticket 02 | `.venv/bin/python -m pytest -q tests/http/test_reader_conversation.py tests/http/test_turn_lifecycle.py tests/domain/test_reply_streaming.py tests/domain/test_gemma_native_json.py` | 46 passed. Both mock fixture entrypoints also reopened identical saved transcripts after a real restart in the recorded disposable HTTP smoke. |
| Ticket 03 | `.venv/bin/python -m pytest -q -o addopts='' tests/http/test_security_readiness.py tests/domain/test_retrieval_question_set.py tests/domain/test_retrieval_gate_message_set.py tests/scripts/test_extra_messages.py` | 104 passed. Inventory/redaction evidence in the [privacy audit](../security/PUBLIC_REPOSITORY_CONTENT_AUDIT.md). |
| Ticket 04 | `.venv/bin/python -m pytest -q -o addopts='' tests/domain/test_runtime_reply_stream.py tests/domain/test_runtime_model.py tests/domain/test_agentcore_session_affinity.py tests/domain/test_reply_streaming.py tests/test_deployment_config.py tests/http/test_production_config.py` | 141 passed, six warnings, 2.94 s. |
| Tickets 02–04 | `sh scripts/build.sh` | Passed TypeScript/Vite production build, 30 Vitest tests, offline OpenAPI and generated-client checks, compilation, and the full 3,210-test mock Python gate. |
| Ticket 04 | `.venv/bin/python -m pytest --collect-only -q -o addopts='' -rs` and `.venv/bin/ruff check . --output-format json` | 3,210 collected. Strands middleware module skipped because `strands` was absent. Ruff exited 0 with `[]`. |
| Ticket 05 | `npm install --prefix frontend --save-dev --save-exact --ignore-scripts --offline --no-audit --no-fund @playwright/test@1.64.0` | Exit 1, `ENOTCACHED` on the `@playwright/test` registry metadata request. npm cache listings showed entries, yet the chosen offline install could not use them. This was the only ticket 05 attempt. No manifest/lockfile edit and no test run followed. |

Ticket 05's offline package resolution is unresolved. Use the approved package
source available to the next environment and establish a lockfile-backed install.
The ticket 01 CLI wrapper had failed DNS before the installed CLI entrypoint
worked. Local browser CI must bind to loopback. The old sandbox required an
authorized escalation for this during ticket 01/02. Check OpenCode's execution
environment when reproducing the disposable stack.

`Caddyfile.local` lacks the bootstrap allowlist present in the production edge.
Direct-origin test success leaves edge parity open. The privacy audit also found
historical artifact paths eligible for the Docker build context. Deep Review
cannot resume queued/running work after a backend restart under the current
process-local execution path. Optional Strands coverage, broader accessibility
and current live runtime/identity/release verification remain outstanding.

## Performance evidence and limits

The [ticket 01 observations](../examples/performance/architecture-ticket01-2026-11-24.json)
used production-built React, one local machine, synthetic Guest data, disposable
SQLite and three trials per input. Median visible startup/open were 83/57 ms at
zero injected delay and 328/313 ms at 100 ms injected per reader request. Startup
made three reader reads and chat opening nine. An earlier bootstrap comparison
recorded two startup reads. The extra project read needs follow-up in workspace
aggregation. The opening harness's settled time includes an 800 ms drain.

The [earlier mock baseline](../IMPLEMENTATION_STATUS.md#architecture-baseline-generated-reader-contracts-and-mantle-safety-2026-11-24-sgt)
accepted 211/211 turns across the 1/10/20/40/60/80-user rows. At 80 users, p95 was
1,130.2 ms and throughput 55.3 turns/s with mock generation and local SQLite.
The samples do not establish production RTT, DSQL overhead, model or guardrail
latency, live classroom capacity or a sustainable S$30 monthly cost. Ticket 05
collected no new measurements.

## Remaining sequence and exact restart point

1. Start [ticket 06](../../.scratch/architecture-completion/issues/06-extract-the-chat-lifecycle-without-changing-behavior.md)
   — its only blocker (ticket 05) now has acceptance evidence. The browser slice
   is implemented and locally verified: run it with
   `npm run test:browser --prefix frontend` (CI: `PW_PYTHON=python3 npm run
   test:browser --prefix frontend`). It covers Guest and synthetic registered
   identities, interrupted-stream exact-key recovery, in-flight owner-switch
   fault injection and real backend restart persistence — see the
   [ticket 05 entry](../IMPLEMENTATION_STATUS.md#ticket-05-complete--browser-ci-slice-2026-11-24-sgt-opencode).
   The earlier `ENOTCACHED` blocker is resolved: `@playwright/test@1.64.0` is
   installed with the repeatable `test:browser` script.
2. Extend that CI slice to Guest and the approved synthetic registered identity
   opening a notebook, sending a mock turn and reopening its saved output after
   a real API process restart on the same disposable database. Inject an
   interrupted response, observe the browser recovering under the original key
   and verify one committed exchange through the public UI/API. Add controlled
   owner-change and unsafe-preview/discard checks. Keep failures bounded, verify
   teardown on failure as well as success, and preserve the manual scripts. Wire
   the repeatable command into Mock CI and capture exact evidence in the ledger.
3. After ticket 05 acceptance, ticket 06 can extract the chat lifecycle. The local
   [dependency graph](../../.scratch/architecture-completion/README.md#approved-ticket-graph)
   controls the order. Connectivity work 07–13 has independent eligible slices.
   Ticket 14 waits for 06 and 09. Durable reviews 35–36 and measurement 37–42
   follow their own dependencies. Keep one writer active per ticket.

| Programme work still mandatory | Status at transfer |
| --- | --- |
| Connectivity and frontend foundation, milestones 1–2 | Partial baseline only. Expand generated REST/Query and bounded workspace aggregation, measure navigation, implement URL routing and cohesive chat lifecycle, and finish browser/component coverage. |
| Shared persistence, artifacts and canvas, milestones 3–5 | Pending additive SQLite/DSQL contracts, optimistic concurrency and version history, usable Tiptap and React Flow authoring, autosave/conflicts/restore and exports. |
| Integrated AI and student engagement, milestones 6–7 | Pending explicit approval of structured suggestions and edits, traceable evidence, cross-resource transfer, resumable work, deduplicated recaps, actionable Thinking Path and selected coursework export. |
| Backend/AI measurements, milestone 8 | Pending new correlation, DSQL/concurrency and workload measurements, provider/prompt/retrieval comparisons and evidence-based decisions. Keep experiments conditional on their evidence. |
| Durable review and quality, milestone 9 | Partial manifest and historical mock evidence. Pending durable leases/cancellation/ambiguity handling, accessibility/content/ownership and full CI, restore rehearsal, release/rollback and evidenced capacity/cost. Preserve protected lecturer behavior and consent-bound aggregate access. |
| Final verification, milestone 10 | Pending complete requirement map, integrated saved-work/restart and restore evidence, baseline comparisons and full implementation report. |

## Operations that require separate approval

Staging, committing, pushing, deployment and GitHub issue changes require
separate authorization. The same applies to live AWS/Cognito/DSQL changes,
AgentCore runtime publication or rollback, session generation changes, credential
actions, private artifact deletion, history rewriting and live migrations or
restores. Any billable test requires explicit approval with a request/token or
cost cap and applicable concurrency limits. Confirm the actual application,
edge, runtime/model and session identities before rollout, and preserve the
Mantle output-safety fix through coordinated rollback. Use disposable data for
mock tests and rehearsals. No live deployment, migration, credentials or billing
operation is needed to resume ticket 05.
