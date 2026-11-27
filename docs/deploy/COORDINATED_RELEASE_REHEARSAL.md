# Coordinated release and rollback rehearsal (ticket 51)

This is a **preparation** document, written 26 November 2026 SGT. No live step
in this file has been executed: no deployment, no publication, no live
migration, no session rollover and no model call was performed. Live execution
stays gated by the [production release checklist](../PRODUCTION_RELEASE_CHECKLIST.md)
and the [deployment safety record](DEPLOYMENT_SAFETY_RECORD.md); their
gates and open issues are neither closed nor modified by this ticket.

## The three-state rule

Every release decision reads from the [versioned nonsecret
manifest](../examples/deployment/release-rehearsal-ticket51-2026-11-26.json),
which keeps three sections strictly separate:

| State | Section | Meaning |
| --- | --- | --- |
| Repository defaults | `repository_defaults` | What the checked-in `compose.prod.yaml`, `Caddyfile`, Dockerfile and runtime recipes select. Intent, not fact about any host. |
| Last recorded deployment | `last_recorded_deployment` | Dated historical evidence (currently the 2026-11-24 restoration: `GemmaStable37` V1 v38, DEFAULT V2 v39). Never current by inference. |
| Actually verified live | `actually_verified_live` | Only values observed against the exact released tuple. `null` blocks the corresponding gate and is never filled from a default, an alias name or a successful health check. |

Append a dated manifest per approved release; keep superseded manifests as
history. Never edit an `actually_verified_live` section after the fact.

## What changed in the coordinated configuration (repository defaults)

1. **Edge allowlist (exact, additive).** The production `Caddyfile` and local
   `Caddyfile.local` now allow exactly the reader routes the built React
   workspace calls: artifact/canvas CRUD (GET/POST), version reads, version
   restore, confirmed canvas deletion, Deep Review status/start/cancel,
   exports, `project/export` (the ticket 52 selected project export),
   `workspace` GET, and a bounded PUT matcher for
   artifact/canvas guarded saves. Before this fix the built frontend's saved
   workspace would have been 404'd at the edge while every test that bypasses
   Caddy stayed green — the drift `test_production_edge_allows_the_built_reader_contract_and_keeps_internal_routes_private`
   now pins. `/api/v1/ready`, the professor APIs and everything outside the
   reader prefixes stay private. The documented local/production bootstrap
   difference is unchanged.
2. **Build context.** `.dockerignore` now excludes `.agents/`,
   `.playwright-cli/` and `.scratch/`, resolving the ticket 04 audit finding
   that `COPY . .` could package historical planning artifacts. No image has
   been built; the resulting image inventory still requires owner review.
3. **Schema, contracts and runtime recipes** are unchanged by this ticket; the
   manifest records their current hashes as the release baseline.

## Ordered release steps (prepare; execute only under the release checklist)

1. **Source ready.** Freeze the approved full SHA; mock CI green; generated
   reader contract (`frontend/openapi/reader.json`) committed at that SHA.
2. **Frontend build.** `npm run build --prefix frontend` from the same SHA;
   record `dist/index.html` and asset hashes in the release manifest.
3. **Backend image.** Immutable ARM64 image from the same SHA (`APP_IMAGE`
   tag = SHA, never `:latest`); push to ECR; record registry digest.
4. **Generated contracts.** Confirm the serving FastAPI accepts the deployed
   runtime's response shapes (deploy the compatible parser first when the
   runtime contract changes). `npm run api:check --prefix frontend` must be
   clean at the release SHA.
5. **Additive migrations.** Administrator applies the documented additive DSQL
   plan (`scripts/init_dsql.py`), one DDL statement per transaction, after a
   verified backup. Never app-startup DDL; never ad-hoc `psql` during release.
   Applied columns stay in place during any later app rollback.
6. **Edge allowlists.** Deploy the exact `Caddyfile` recorded in the manifest
   (additive reader routes + PUT matcher) together with — or before — the
   frontend that calls those routes. Validate with
   `caddy validate --config /etc/caddy/Caddyfile`.
7. **Runtime versions.** Publish a new version on the **existing** AgentCore
   ARN, wait READY, move only the approved qualifier (inspect DEFAULT
   separately), set a **new unique** `AGENTCORE_SESSION_GENERATION`, and
   recreate FastAPI so it is read. Warm microVMs otherwise keep the old assets.
8. **Health, readiness and direct links.** Public `/api/v1/health` → 200
   `"mode":"production"`; host-local `/api/v1/ready` → 200 (never public);
   recognized deep links (`/chats/*`, `/notebooks/*`, `/notebooks/*/artifacts/*`,
   `/library`, `/search`, `/settings`) serve the SPA shell through
   `@student_views`, while unknown `/api/*` paths stay a bounded 404.

## Backup and restore

Take a verified backup before any migration or image switch (stopped-server
SQLite/file backup locally; DSQL + S3 snapshot procedure per the runbook).
Restore drills happen **only** on disposable local or explicitly approved
staging data — never destructive production exercises. The rehearsed
restore path is `scripts/workspace_recovery_rehearsal` (ticket 47): it proves
the complete saved workspace — transcripts, sources, artifact and canvas
version histories, recaps, review metadata — reopens byte-identically after a
documented backup/restore, inside the same owner boundary.

## Mantle guardrail preservation (rollout AND rollback)

Source presence is not deployed protection. Before asserting production
protection, verify **through the real path** on the exact candidate tuple:

- The published runtime artifact retains the canonical Gemma nullability
  correction **and** the provisional-output suppression before
  `ApplyGuardrail(OUTPUT)` (`agentcore_runtime/main.py`; local regression
  `tests/domain/test_runtime_reply_stream.py::test_mantle_never_forwards_text_before_output_guardrail`).
- Guardrail id and **version 4** match on both FastAPI and runtime sides.
- Fresh-session evidence proves the new generation actually serves the new
  artifact (an existing synthetic notebook reopened under the new generation).
- A controlled output-block fixture in a disposable staging runtime reaches
  OUTPUT blocking (not merely INPUT refusal): expect `safety_blocked`, zero
  provisional text, no unsafe saved reply after reload/restart.
- **Rollback inherits every one of these checks.** Never restore v36/v38/v39
  or any artifact that predates the suppression fix; prefer a separately
  prepared known-good artifact that retains the fix. If no verified safe
  target exists, suspend generation under an approved operational action and
  preserve saved work.

## Known-good rollback (summary)

1. `APP_IMAGE` → verified safety-compatible immutable tag; EC2 refresh.
2. If the runtime changed: point the selected qualifier back to the verified
   READY rollback version **and** set a new session generation; recreate
   FastAPI. Version rollback without a new generation can leave warm sessions
   on the version you meant to leave.
3. Do not roll schema backward; additive columns stay.
4. Repeat the health/readiness, fresh-session, allowed/blocked-output and
   saved-data checks within the approved cap before declaring the rollback.

## Local rehearsal (disposable data only)

```sh
.venv/bin/python -m scripts.release_rehearsal            # all stages
.venv/bin/python -m scripts.release_rehearsal --skip-recovery
```

The driver rehearses on its own temporary tree with deterministic mock
adapters and refuses any pointer at real data. Recorded 2026-11-26 (exit 0):

| Stage | Result |
| --- | --- |
| `configuration` | pass — stage-selection flags, guardrail version 4, immutable image placeholder, session generation set, `/ready` private, `/api/*` 404 fallthrough, all six direct-link paths allowlisted, full reader-contract ↔ edge parity |
| `contracts_and_builds` | pass — reader contract 35 paths; production `dist/` built (index sha256 `66c1db39…`) |
| `coordinated_startup` | pass — real API, disposable SQLite, mock adapters: health 200, readiness 200; the production fail-closed validation **refused** the mock tuple |
| `backup_restore` | pass — `scripts.workspace_recovery_rehearsal` exit 0 |

A passing rehearsal is ordering and configuration evidence only. It is not a
live-environment, capacity, cost or production-safety verdict; the manifest's
`actually_verified_live` section stays entirely null until the gated live
checks in the release checklist are executed and recorded.
