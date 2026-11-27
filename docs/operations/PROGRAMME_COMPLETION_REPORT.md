# Programme completion report — CDE2300 architecture-completion programme

**Date:** 2026-11-26 SGT · **Author:** Sol writer session (tickets 52–53) ·
**Status:** local programme complete; live gates remain open (section 6).

This report closes the approved 53-ticket architecture-completion programme
(`.scratch/architecture-completion/README.md`, approved 2026-11-24 SGT). It
maps what was delivered to executed evidence, states the honest remaining
gates, and records the exact state of the working tree. The authoritative
evidence ledger remains [`docs/IMPLEMENTATION_STATUS.md`](../IMPLEMENTATION_STATUS.md);
every claim below points into that ledger rather than restating it.

**Honesty boundary.** Everything in sections 2–4 was executed locally against
deterministic mock providers, disposable SQLite and synthetic identities. No
claim in this report asserts live AWS/Cognito behavior, real-model quality,
production safety, classroom readiness, or the S$30 cost objective. Those are
separately approved external work (section 6).

## 1. Final validation battery (executed 2026-11-26 SGT)

| Check | Command | Actual final result |
| --- | --- | --- |
| Backend full mock suite | `.venv/bin/python -m pytest --tb=no` | Exit 0 — **3,386 passed / 1 skipped** (the single historical Strands collection skip; pytest 9 hides the summary line under `-q`, so the count was captured without it) |
| Frontend unit/component suite | `npm test --prefix frontend` | **190 passed / 3 skipped** (31 files: 30 passed, 1 skipped) |
| Production frontend build | `npm run build --prefix frontend` | Exit 0 (`tsc --noEmit` + Vite build) |
| Generated-contract drift | `npm run api:check --prefix frontend` | Exit 0 (generated files never hand-edited) |
| Browser suite (production build + real same-origin FastAPI + disposable SQLite) | `npm run test:browser --prefix frontend` | **12 passed** (11 specs) |
| Lint | `.venv/bin/ruff check .` | All checks passed |
| Bytecode compilation | `compileall` over `backend ui streamlit_app.py tests scripts agentcore_runtime` | Exit 0 |
| Whitespace hygiene | `git diff --check` | Clean |
| Secret scan (git history) | `gitleaks detect --no-banner --redact` | No leaks found |
| Secret scan (working tree, `--no-git`) | `gitleaks detect --no-git` | Findings only inside pre-existing untracked local runtime data (`data/*.sqlite3-wal`, `.streamlit/secrets.toml`, vendored source maps) — none tracked, none introduced by the programme |
| Release rehearsal (ticket 51 driver, re-run after ticket 52's edge change) | `.venv/bin/python -m scripts.release_rehearsal` | Exit 0, findings `[]` |

Accounting note: the ticket 51 ledger recorded 3,374 passed / 1 skipped.
Ticket 52 added 4 backend tests (3,378) and the frontend 179→181/190. The
final run's extra 8 backend tests (Deep Review leases/cancellation, canvas
reader, cost scenarios, chat-progress UI) and 1 extra browser spec belong to a
**parallel "codesign-fixes" writer session observed operating in this same
working tree on 26 Nov** (its pytest run: `/private/tmp/codesign-fixes-pytest-final.log`);
they are counted here because the battery ran against the shared tree, but
their authorship is not claimed by this programme's ledger beyond that note.

## 2. Per-milestone delivery summary (evidence: ledger entry headings)

| Milestone | Tickets | Delivered (one line each; full evidence in the named ledger entry) |
| --- | --- | --- |
| Milestone 0 — baseline, hygiene, records | 01–04 | Fresh baseline and coverage (ledger: "Local completion ticket 01 — fresh baseline", 2026-11-24); lint/collection blockers cleared (02); repository privacy audit (03); deployment and safety records reconciled (04) |
| Browser CI and chat lifecycle | 05–06 | Playwright slice against the production build + disposable stack (05); chat lifecycle extracted without behavior change (06) |
| Generated REST + Query workspace | 07–13 | Preferences, notebooks, aggregated verified workspace, typed sources, bookmark sync, Thinking Path progress, reviews/briefs/exports through generated contracts (07–13) |
| URL navigation | 14 | Existing workspaces navigable through URLs (14) |
| Persistent artifacts | 15–19 | Create/reopen artifacts (15); course-aligned types (16); conflict-safe autosave (17); version preview/restore (18); safe bounded exports (19) |
| Design Canvas | 20–24 | Persistent canvas (20); complete visual reasoning map (21); tab-conflict-safe autosave (22); canvas versions (23); complete canvas exports (24) |
| Evidence links | 25 | Artifacts/canvas nodes linked to owner-scoped family references with fail-closed resolution (25) |
| Connected AI assistance | 26–31 | Chat→canvas nodes (26); selected-node coaching (27); structured canvas suggestions with accept/reject (28); artifact feedback with before/after acceptance (29); canvas→artifact development (30); artifact→canvas return (31) |
| Continuity | 32–34 | Resume dashboard from persisted work (32); deduplicated confirmed-milestone recaps (33); actionable stage requirements (34) |
| Durable Deep Review | 35–36 | Restart-safe queued review (35); cancellation and honest ambiguous-outcome handling (36) |
| Measurement programme | 37–42 | Privacy-safe request tracing (37); DSQL connection/pooling measurement (38); bounded backend concurrency (39); prompt-variant/caching economics (40); fair runtime-path comparison (41); workspace-evidence retrieval evaluation (42) |
| Performance and accessibility | 43–44 | Measured chat speed with editors added (43); accessible desktop/mobile authoring gaps closed (44) |
| Security, CI, recovery | 45–47 | Ownership/hostile-content defense sweep (45); deterministic frontend/browser CI completed (46); full saved-workspace recovery rehearsal (47) |
| Capacity and cost | 48–49 | Stepped 1–80-student synthetic mixed-load measurements (48); offline cost scenarios with dated pricing and an unresolved S$30 assessment (49) |
| Lecturer signals and release preparation | 50–51 | Additive aggregate engagement signals within existing consent/access rules (50); coordinated release/rollback rehearsal PREPARED, not executed (51) |
| Selected project export | 52 | Bounded, owner-checked selected project export with the notebook-page Export tab (52 — see ledger entry of 2026-11-26) |

Every ticket entry in the ledger contains a "New files and behavior" table, an
"Executed validation" table with red-first evidence, and
compatibility/rollback/limits notes. Tickets 01–04 are recorded under the
"Local completion ticket NN" headings; 05–52 under "Ticket NN complete".

## 3. Requirement coverage and architecture comparison

- **Mandatory requirement mapping.** The approved spec's 101-section coverage
  table (`.scratch/architecture-completion/README.md`, "Source coverage
  ownership") assigns every source section to primary tickets; each of those
  tickets carries executed acceptance evidence in the ledger. No mandatory
  requirement is silently unowned. Partial implementation is not recorded as
  completion anywhere: measurement tickets (38–42, 48–49) record evaluated/
  adopted/rejected/deferred-with-gate decisions explicitly, and release work
  (51) is recorded as PREPARED, not verified.
- **Architecture baseline → final (retained).** FastAPI single app (student +
  professor routes in one composition root), one LangGraph workflow for all
  five phases, SQLite/DSQL as the transcript of record, Caddy edge with exact
  allowlists, AgentCore Runtime as the canonical coach path, Streamlit
  lecturer surface — all retained, per the spec's out-of-scope list.
- **Added.** Generated reader contracts + drift checks; React Router/Query
  typed resources; persistent Tiptap artifacts and React Flow canvases with
  version histories; family-scoped evidence references; durable persistence-
  backed Deep Review worker; bounded selected project export; deterministic
  measurement harnesses (DSQL pooling, concurrency, prompt variants, runtime
  paths, retrieval, mixed workload, cost scenarios); recovery and release
  rehearsal drivers.
- **Rejected or deferred with gates (from the measurement tickets).** No
  default connection pooling without demonstrated benefit (38); no unbounded
  worker pools (39); prompt-cache adoption gated on live economics (40);
  AgentCore retained as canonical — direct-provider paths documented but not
  adopted (41); no new vector store/GraphRAG/router (42); no region migration
  or infrastructure change (49). No AI-authored automatic completion, no
  shared cross-student caches, no hosted Tiptap/React Flow services.

## 4. Integrated student workflow now covered end-to-end

Existing project → resumed conversation → authored nodes/relationships/
evidence → saved/reopened canvas → authored/saved/reopened artifact → version
preview/restore → chat-to-canvas → selected-node coaching → accepted/rejected
suggestions → canvas-to-artifact and artifact-to-canvas → stage
recommendation/confirmation → deduplicated recap → later resume → selected
project export. The journey is exercised at three seams: HTTP contract tests,
the Vitest component/transport layer, and the Playwright browser suite against
the production build with real restarts (see `frontend/tests/browser/`).

## 5. Release posture

- The ticket 51 [versioned nonsecret release
  manifest](../examples/deployment/release-rehearsal-ticket51-2026-11-26.json)
  and [coordinated release runbook](../deploy/COORDINATED_RELEASE_REHEARSAL.md)
  remain **PREPARED, not verified**: repository-default configuration is
  rehearsal-verified (including ticket 52's additive `project(/export)?` edge
  alternation), the last recorded deployment is carried forward from ticket 04
  evidence, and `actually_verified_live` is entirely null. The v36/v38/v39
  artifacts predate the Mantle provisional-output suppression and are not
  approved rollback targets.
- Release, migration, backup and rollback instructions live in the runbook and
  the recovery rehearsal (`WORKSPACE_RECOVERY_REHEARSAL.md`, ticket 47); the
  image inventory review and live release checklist remain open gates.

## 6. Remaining external gates (not claimed, never executed by this programme)

1. **Live AWS/Cognito verification** — real Cognito sessions, IAM, DSQL and S3
   behavior under the deployed stack; every automated test used deterministic
   fakes by design.
2. **Real-model quality** — all pedagogy/structured-output evidence is
   mock-based; live quality, guardrail behavior and first-attempt reliability
   were never measured (tickets 40–41 recorded the *plans* and refused live
   execution without caps).
3. **Runtime publication** — AgentCore runtime version/endpoint publication,
   fresh-session behavior, and blocked-output verification through the real
   edge (ticket 51's `LIVE_GATES`).
4. **Live capacity and cost verification** — the 1–80-student results are
   synthetic local mock measurements; live concurrency, provider queues and
   token-cost verification remain gated (tickets 48–49).
5. **The S$30 objective** — the cost model presents three dated scenarios and
   explicitly leaves the S$30 question unresolved; no live test was run.
6. **The formative study** — the spec's student-facing formative evaluation
   has not been executed; it is separate, approval-dependent external work.
7. **Image inventory review** — no release image was built locally (Docker
   daemon unavailable), so the packaging review from ticket 51 stays open.
8. **Live additive DSQL migration** — planned and rehearsed on disposable
   data only; execution requires an administrator and separate approval.

## 7. Exact working-tree state

- Branch `improvement/architecture-responsiveness`, last commit `4f12995`
  (unchanged all programme). **Nothing staged, nothing committed, nothing
  pushed by this programme**: 106 tracked files modified, 133 untracked paths
  (new modules, tests, docs, planning state, and pre-existing local data) —
  the dirty ticket 01–53 tree is intentionally preserved.
- Rollback is **source-only**: revert the working tree; no schema migration,
  no generated artifact, no live resource was touched. All schema changes the
  programme made are additive SQLite columns with documented rollback notes in
  their ledger entries.
- Known concurrent writer: a parallel "codesign-fixes" session operated in
  this tree on 26 Nov (see section 1); its files were left untouched and its
  tests are green in the shared battery.

## 8. Next exact action

The local programme is complete. The next actions are the gated external items
in section 6, in the order the runbook and safety record require: owner review
of the release image inventory, then the coordinated live release steps under
explicit approval with capped live verification. No further local ticket work
is queued; `.scratch/architecture-completion/` remains as the approved plan of
record.
