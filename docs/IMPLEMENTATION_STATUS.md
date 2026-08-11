# Implementation status

## Current phase

**Production edge: CloudFront viewer TLS → Caddy HTTP origin.** CloudFront at
``d1sxfuoybzedj5.cloudfront.net`` is now the sole production hostname. Caddy
listens on EC2 port 80 as the route-security boundary; host port 443 and the
retired dynamic-DNS updater are removed. Both Compose contracts, CI deployment
tests, Cognito callback examples, operational docs, and manual QA now use the
CloudFront topology.

### CloudFront/Caddy edge alignment (completed)

1. CloudFront owns viewer HTTPS; Caddy accepts origin HTTP on ``:80`` and keeps
   the auth/health allow-list plus the catch-all ``/api/*`` 404 boundary.
2. ``compose.yaml`` and ``compose.prod.yaml`` use the CloudFront UI/API origin
   and Cognito callback. Neither publishes host port 443.
3. The obsolete host address-updater scripts and their secret-ignore rules were
   removed. A deterministic deployment test rejects their return in runtime,
   workflow, or documentation files.
4. CI's production configuration gate is explicitly named for the
   CloudFront/Caddy contract.
5. No database, DSQL, S3, Cognito resource, or student-data migration is
   required. Rollback is a code/config revert, but must not restore a second
   public hostname after Cognito and CloudFront cutover.

Validation: deployment/config/auth tests **50 passed**; full mock suite
**401 passed**; compileall, shell syntax, both Compose config validations, and
``git diff --check`` passed. No live AWS, DSQL, S3, Cognito, or paid-provider
call was made.

Next exact action: deploy the immutable image, restrict EC2 TCP 80 ingress to
the AWS-managed CloudFront origin-facing prefix list, verify the distribution
uses caching disabled plus full cookie/query/WebSocket forwarding, then run
``docs/security/CADDY_PUBLIC_BOUNDARY.md`` and the authenticated production
smoke. Do not open host TCP 443.

### Prior auth phase (still true)

**Auth: restore Cognito refresh after 1-hour ID cookie expiry.** The
non-sensitive Path=/ ``co_design_session`` hint now limits refresh attempts to
browsers with an established session. Cold visitors go directly to Sign in;
expired sessions see the app skeleton and centered loader while the refresh
bridge runs once; a Sign in launch cannot be intercepted by that bridge.

### Prior UI phase (still true)

**UI: fragment-scoped Streamlit reruns (local interactions).** Explicit
``rerun_app()`` / ``rerun_fragment()`` helpers replaced the ambiguous
``rerun()``. Sources select/search/sort/upload/delete, Journey preview
toggles, Guidance Level, response language, and display-name avatar stay
panel-local; notebook/auth/coach/layout/stage-select/**Appearance theme**
remain full-app. Debug counters: ``_app_runs``, ``_sources_fragment_runs``,
``_studio_fragment_runs``, ``_topbar_guidance_fragment_runs``,
``_topbar_profile_fragment_runs``.

### Full-app actions that remain intentional

- Notebook create / switch / rename / delete
- Auth / sign-in cooldown / logout
- Coach send / revise / composer model changes
- Workspace column collapse / mobile panel layout
- Sources course-sync stable ↔ polling fragment remount
- Thinking Path stage selection and transition confirm
- Appearance theme (entrypoint ``render_theme_css``)

3. **Full mock suite.** ``.venv/bin/python -m pytest -q`` → **397 passed**.

### Auth refresh fix (this pass)

1. ``should_attempt_session_refresh`` no longer requires a live ``co_design_id``
   cookie before redirecting to ``/api/v1/auth/refresh``.
2. Login/refresh/logout set or clear ``co_design_session`` (Path=/, Max-Age 30d,
   non-sensitive ``1``) alongside the Cognito token cookies.
3. Focused auth suites + full mock ``pytest`` green.

### Prior UI hardening

1. **Explicit edit retry.** On revise failure, clear ``pending_edit`` so the next
   rerun does not auto-resubmit; keep the stable ``get_retry_key`` UUID; restore
   the in-bubble draft; require Send to retry.
2. **Studio sanitized errors.** Stage-select and transition-confirm failures log
   internals and show fixed student-safe messages (no ``str(exc)``).
3. **Full mock suite (prior).** ``.venv/bin/python -m pytest -q`` → **393 passed**.

### Prior production-hardening (still true)

Append-only edit remains (no DELETE truncate). DSQL revision migration is
resumable/idempotent (DEFAULT + batched NULL backfill). Ownership stays
``messages.notebook_id → notebooks.user_id → users.id``.

### Hardening behavior changes (revision pass)

1. **DSQL revision migration.** ``scripts/init_dsql.py`` inspects
   ``information_schema`` name **and** ``column_default``, repairs missing
   DEFAULT 0, and batch-backfills NULL ``conversation_revision`` (1000 rows /
   transaction) for notebooks and messages. Safe to re-run; never app startup.
2. **Stable revise retry.** Streamlit keeps one UUID idempotency key (via
   ``get_retry_key`` scope ``revise:{message_id}``) until success; provider-
   failure retries resume without a second revision bump. After a failed
   attempt the UI requires an explicit Send (``pending_edit`` cleared).
3. **Active-branch pending rejects.** ``select_learning_stage`` only rejects
   ``decision_status='pending'`` rows active at the current revision.
4. **Conversation revision (internal).** Stored revision stays zero-based;
   student UI does not show a Conversation NN label.
5. **No destructive message content update.** ``StudentStore.update_message``
   raises; edits go through append-only revise only.

### Prior append-only phase (still true)

1. **Active-branch chat.** Discussion renders only active messages for the
   notebook's current ``conversation_revision``; superseded turns stay durable
   for revision history / reporting.
2. **Edit confirm copy.** Editing an earlier user turn states that a new
   conversation revision/branch is created; later turns leave the active view
   but remain in revision history (no truncate/delete claims).
3. **Post-edit reload.** Successful revise reloads journey state and reruns so
   ``get_messages`` shows the new active branch.
4. **Message revision columns (backend contract).** Messages carry
   ``conversation_revision``, ``previous_message_id``, and
   ``superseded_at_revision``; ownership stays
   ``messages.notebook_id → notebooks.user_id → users.id``.
5. **Assessment fields (expected).** User rows and the fixed coach welcome have
   ``assessment_text = NULL``; assessed coach assistant replies store
   ``assessment_text`` JSON. Do not treat welcome NULL assessment as a failure.
6. **Sources panel.** My Sources → Lecture Notes → Readings; course materials
   lock-only; Select all + Sort for personal uploads.

### PART 1 root-cause evidence (“only welcome” on DSQL) — code inspection

No live DSQL verification was run for this writeup.

**Primary mechanism (code evidence):**

- UI welcome seed (`ui/coach_welcome.py` → `store.add_message`) persists a fixed
  assistant welcome through the workspace CRUD path **without** the coach
  workflow / ``persist_coach_turn`` CAS.
- Coach turns persist via ``CoachApplicationService`` → ``persist_coach_turn``.
  At branch baseline ``6b54923``, this path required
  ``notebooks.conversation_revision`` for CAS while the simpler welcome insert
  did not.
- **Welcome-only root cause from code inspection:** an older DSQL cluster
  missing ``notebooks.conversation_revision`` could accept the independently
  committed welcome, then roll back every real coaching turn when
  ``persist_coach_turn`` reached its revision CAS.
- The new implementation also reads/writes the three message revision columns
  from normal and welcome inserts. Missing message columns are therefore a
  deployment failure prerequisite, not evidence that the new app will still
  seed a welcome successfully. Run admin ``scripts/init_dsql.py`` before
  deploying the new image.

**Secondary diagnostics (not claimed verified live):** wrong ``DSQL_ENDPOINT``,
database name, runtime role/owner (``DSQL_USER`` not ``co_design_app``), or
``.env``/Compose config mismatch can produce empty or partial notebooks and
should be checked after confirming schema columns exist.

### Owner reporting JOIN (do not denormalize messages)

```sql
SELECT
  u.id AS user_pk,
  u.identifier,
  u.cognito_sub,
  n.id AS notebook_id,
  n.conversation_revision AS notebook_revision,
  m.id AS message_id,
  m.role,
  m.conversation_revision AS message_revision,
  m.previous_message_id,
  m.superseded_at_revision,
  m.assessment_text,
  m.created_at
FROM messages m
JOIN notebooks n ON n.id = m.notebook_id
JOIN users u ON u.id = n.user_id
WHERE n.id = :notebook_id
ORDER BY m.created_at, m.id;
```

### Files changed (this append-only phase)

- ``backend/student_store.py``, ``backend/application.py``,
  ``backend/chat_service.py``, ``backend/repositories.py``, and
  ``backend/workspace_service.py`` — append-only persistence, snapshots, CAS,
  retry recovery, and legacy compatibility.
- ``backend/api.py``, ``backend/api_client.py``, and ``backend/domain.py`` —
  append-only contract documentation.
- ``backend/persistence/dsql_schema.py`` and ``scripts/init_dsql.py`` — fresh
  schema plus catalog-driven additive DSQL migration.
- ``ui/chat.py``, ``ui/assets/styles/30-chat.css``, and ``ui/AGENTS.md`` —
  Conversation label, edit warning, and failure fall-through.
- Revision, migration, idempotency, store, legacy-engine, and UI regression
  tests were updated under ``tests/``.
- ``docs/IMPLEMENTATION_STATUS.md`` and
  ``docs/deploy/AWS_STATELESS_EC2.md`` — migration, reporting, evidence, and
  deployment steps.

``tests/test_conversation_revision.py`` asserts append-only semantics
(``previous_message_id`` lineage, ``superseded_at_revision``, active
``get_messages`` / ``get_messages_at_revision(0)`` = Conversation 01, provider-
failure retention, stale CAS, revoked keys, pending supersede, API ownership,
DSQL message columns, ``assessment_text`` on assessed assistants only).

### Validation evidence

- Integrated revision/storage/UI selection:
  ``.venv/bin/python -m pytest -q tests/test_conversation_revision.py
  tests/test_init_dsql.py tests/test_coach_idempotency.py
  tests/test_streamlit_ui.py tests/test_student_store.py
  tests/test_storage_providers.py tests/test_learning_service.py`` → **115
  passed** (deterministic mocks; 2026-08-10).
- Full suite: ``.venv/bin/python -m pytest -q`` → **381 passed**.
- Compile: ``PYTHONPYCACHEPREFIX=/private/tmp/co-design-pycache
  .venv/bin/python -m compileall -q backend ui streamlit_app.py tests scripts``
  → passed.
- Patch integrity: ``git diff --check`` → passed.
- IDE diagnostics on edited Python modules: no errors.
- Paid OpenAI / live AWS calls: not run.

### Compatibility / migration / rollback

- Additive only: existing message rows backfill to revision ``0`` with
  ``superseded_at_revision`` NULL; display stays Conversation 01 until an edit.
- DSQL: admin manual DDL / ``init_dsql.py`` catalog path only — **app startup
  never DDL**. See ``docs/deploy/AWS_STATELESS_EC2.md``.
- Rollback: revert the application image/code; older code ignores the additive
  columns and retained historical rows. Avoid ``DROP COLUMN`` on live student
  data. Use the pre-migration backup/cluster snapshot if physical schema
  rollback is required. SQLite migrations are additive on open.

### Known risks / blockers

- Existing DSQL clusters must receive the additive notebook/message revision
  migration before this application version is deployed. Runtime cannot repair
  missing columns and app startup intentionally performs no DDL.
- The migration and behavior are covered by deterministic mocks, not a live
  DSQL write. No live browser/upload/RAG QA is claimed in this phase.

### Next exact action

**Stop architecture/feature edits.** Proceed only with live AWS / DSQL cutover:

1. Confirm host `.env` has ``DSQL_ENDPOINT``, ``AWS_REGION=us-west-2``, and
   admin identity available for DbConnectAdmin. Take a DSQL snapshot/export.
2. On the existing Aurora DSQL cluster, as admin only:
   ``DSQL_ENDPOINT=<hostname> AWS_REGION=us-west-2 \\
     .venv/bin/python scripts/init_dsql.py --admin-user admin``
   Then ``GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public
   TO co_design_app;`` (no schema USAGE). Re-run is safe/idempotent.
3. With separate live-write approval, run
   ``scripts/smoke_dsql_idempotency.py --confirm-live --identifier
   'cognito:<sub>'`` as ``DSQL_USER=co_design_app``.
4. Redeploy ARM64 ECR image; require internal ``/api/v1/ready`` 200; run the
   Cognito → notebook → coach → upload → edit/revise → restart smoke in
   ``docs/deploy/AWS_STATELESS_EC2.md`` (mock first; OpenAI only with cost cap).

### Prior pilot context (Phases 1–14)

**Phases 1–13 complete on ``Production-RemoveData``; Phase 14 verdict:
READY FOR CONTROLLED PILOT.** Live manual production QA documented in
``docs/MANUAL_PRODUCTION_QA.md`` (2026-08-10). **Month-1 product policy:**
``AUTO_ADVANCE_STAGES=true`` and ``STUDENT_STAGE_SELECTION=false`` in
``compose.prod.yaml`` (coach ADVANCE applies without Next; no Journey stage
pick controls). **Month-2+ operator flip:** set ``STUDENT_STAGE_SELECTION=true``
and ``AUTO_ADVANCE_STAGES=false`` — Journey shows audited **Work on this stage**
(``POST .../learning-state/select-stage``); if both flags are true, selection
wins and auto-advance is treated as off. Health ``mode`` now follows
``APP_ENV``. Login-start rate limit and allow-listed Cognito callback error
logging added. Coach chat shows a **thinking** status while the buffered
provider turn runs (early NDJSON ``status``); true token streaming remains
deferred. For lower wait times keep Guidance short, reasoning low, and avoid
extra selected sources. **Edit message** (pre–append-only) used
server-authoritative ``POST .../messages/{id}/revise`` with
``conversation_revision`` CAS and a **new** idempotency key; that path is being
replaced by append-only revision history on this branch. Regenerate remains
unavailable.

### Behavior changes (Phases 1–13)

1. Concurrent identical coach idempotency keys converge to one provider
   execution; completed markers replay without false lease-lost errors.
2. ``APP_ENV=production`` fail-closes via ``validate_production_configuration()``
   at ``create_app`` and ``/api/v1/ready``.
3. ``/api/v1/ready`` checks config, DB ping, file-store ping, provider
   credential shape, and Cognito HTTPS config without paid LLM calls.
4. ``compose.prod.yaml`` sets ``APP_ENV=production``, json-file log rotation
   (10m × 3), and ``no-new-privileges`` on ``app``/``caddy``.
5. ``backend/rate_limit.py`` provides single-EC2 in-process coach limits
   (``MAX_ACTIVE_COACH_REQUESTS_PER_USER=1``, ``COACH_REQUESTS_PER_MINUTE=8``,
   ``MAX_CONCURRENT_MODEL_CALLS=20``) wired into ``coach_turn`` /
   ``coach_turn_stream`` using authenticated ``owner.store.owner_id``. HTTP
   429 includes ``Retry-After``; slots release in ``finally``.
6. Uploads: Streamlit ``maxUploadSize=10``; API rejects excess file count and
   bounds each ``upload.read(max+1)``.
7. Coach info logs omit notebook/thread ids and message text; request IDs and
   aggregates remain.
8. Caddy adds HSTS / nosniff / Referrer-Policy / Permissions-Policy (no CSP).
   Curl checks live in ``docs/security/CADDY_PUBLIC_BOUNDARY.md``.
9. ``requirements.txt`` uses exact pins; Mock CI runs shell/compose/compile,
   production + idempotency gates, and full pytest.
10. ``scripts/load_probe.py`` + ``docs/operations/LOAD_PROBE.md``; AWS smoke
    checklist expanded; ``docs/deploy/GITHUB_BRANCH_PROTECTION.md``; public PDF
    audit lists 10 normal-blob lecture/reading PDFs (no LFS).

### Behavior changes

1. Public notebook/message payloads are typed and reject stage, progress, and
   transition metadata. Only the internal learning workflow can write
   authoritative stage state; Conclusion cannot propose or confirm another
   Conclusion transition.
2. Workflow/provider failures are not retried through the sequential fallback,
   preventing duplicate paid provider calls. A completed user/assistant turn,
   assessment, pending decision, and notebook summary now commit in one store
   transaction. DSQL notebook read/merge/write also uses one retryable
   transaction, preventing stale stage reversion.
3. New S3 uploads separate raw and derived namespaces. Batch uploads prevalidate
   sizes and clean up all accumulated objects on validation or put failure.
   PDF/Office extraction has bounded page, archive, compression, slide,
   paragraph, and cell limits.
4. Cognito logout derives the trusted same-origin ``/oauth2/revoke`` endpoint
   when discovery omits it. Unknown JWKS key IDs have a bounded forced-refresh
   window, avoiding unauthenticated network amplification. Expired OAuth login
   states are cleaned during new-state insertion.
5. Production readiness now verifies the configured file store, bounded S3
   list access, and SELECT access to all five required DSQL tables. The DSQL
   schema expresses non-primary uniqueness as explicit ``CREATE UNIQUE INDEX
   ASYNC`` jobs that bootstrap waits for.
6. The adapter-configured OpenAI/Ollama model is authoritative. Response
   language reaches the prompt, reasoning effort restores per notebook, and
   selected sources force model-knowledge fallback off. Request/image limits
   are enforced at the API/application boundary.
7. User-message **Edit** uses inline bubble Save → server
   ``revise_and_resubmit`` (append-only conversation revision, stage/journey
   recompute, ``conversation_revision`` CAS, new idempotency key). Regenerate
   remains unavailable. Normal send/stream retries use the durable idempotency
   contract described below.
8. Production documentation now uses ``compose.prod.yaml``/ECR and makes S3
   setup/readiness explicit. The default stateful Compose stack is labelled
   local-only; Bedrock permissions are not required in this phase.
9. Selected-source concatenation is replaced by a provider-neutral retrieval
   port and deterministic local chunk retriever. It uses sentence-aware chunks,
   current-turn-weighted lexical ranking, bounded conversation/project
   continuity, source diversity, stable ``[S#]`` labels, image markers, and
   strict context budgets in both preferred API and legacy development paths.
10. Assistant messages persist structured ``retrieval_refs`` for audit while
   ``source_refs`` remains limited to sources actually cited. Citation previews
   focus on matching evidence. Application code rebuilds prompt context only
   from validated chunks and rejects source IDs/labels outside the selected
   notebook, preserving the future Bedrock adapter boundary.
11. Live Aurora DSQL bootstrap corrections: async index waits now execute
   ``CALL sys.wait_for_job(?)`` on a dedicated verify-full admin connection
   with ``autocommit=True``; DDL remains one transaction per connection. The
   unsupported ``GRANT USAGE ON SCHEMA public`` was removed, leaving only
   SELECT/INSERT/UPDATE/DELETE on all application tables in ``public``.
12. Local legacy SQLite upgrades are additive and idempotent. The migration no
    longer renames/drops ``users`` (which previously cascaded deletion into
    legacy tables); it copies old threads, chat steps, source rows, stage state,
    and extracted source text into the five application tables while retaining
    the legacy rows as a rollback source. Legacy local source paths still
    preview/download, and copied extracted text remains available to the same
    provider-neutral local retriever used by new sources.
13. Cognito-scoped stores reconcile legacy/noncanonical identities and repair
    the earlier split-owner layout without dropping notebooks. Streamlit also
    reuses the first verified ``/auth/me`` result instead of making a second
    authentication request on every rerun.
14. Sign-in now uses a dialog-owned button callback instead of a fragment-owned
    callback. After the click, the original button remains the only visible
    sign-in control, is disabled for five seconds while the visible
    ``Redirecting...`` status is shown, and automatically becomes a retry
    button if Cognito navigation stalls.
15. Local startup repairs the broken ``notebooks.user_id -> users_legacy``
    foreign key left by the retired destructive user migration. The SQLite-only
    rebuild is transactional, preserves notebook/message/source IDs, checks for
    orphaned notebooks before commit, and is idempotent. DSQL schema SQL is not
    changed.
16. The deterministic mock provider now makes retrieved grounding visible in
    its normal reply by quoting one bounded validated chunk and emitting its
    stable ``[S#]`` label. The existing citation resolver persists and renders
    the corresponding source reference without test-only monkeypatching.
17. Chat-composer attachment failures render a recoverable in-chat error and do
    not submit a coaching turn. Authoritative source selection now enables
    broader model knowledge only when no source is selected, so stale notebook
    metadata cannot contradict the visible UI mode.
18. API-mode course-material sync snapshots the short-lived Cognito ID cookie
    on Streamlit's render thread before starting its background worker. This
    prevents the worker losing browser context, resolving the fallback owner,
    and retrying a protected notebook sync with 404 every second.
19. Coach submission now accepts a validated idempotency key in the typed body
    and standard HTTP header. A durable owner/notebook-scoped reservation in
    the existing ``messages`` table prevents concurrent/restarted retries from
    calling the provider or inserting the turn twice, replays the exact
    completed ``CoachTurn``, rejects changed-input key reuse with HTTP 409, and
    releases provider failures for a real retry. Lease ownership is verified in
    the same transaction that persists the user/assistant pair. No sixth table
    or DSQL schema change was introduced.
20. Production ``/api/v1/ready`` now also validates non-secret Cognito callback
    and metadata configuration locally, requires an HTTPS callback, and redacts
    DSQL/S3 exception details. Structured internal operational events cover
    route latency/status, provider/retrieval/citation results, coach stage
    recommendations, and accepted/rejected progression without prompts, source
    text, user/notebook/source/transition IDs, emails, or tokens.
21. A deterministic authenticated FastAPI production-parity regression covers
    Cognito cookie verification, notebook/source upload-selection-preview,
    grounded ``[S1]`` replies, idempotent replay/conflict, stage confirmation,
    process restart, object cleanup, and logout/revocation. A headed Playwright
    smoke runner preserves the real Cognito boundary and captures desktop,
    390 px mobile, and console evidence after a manually completed Hosted UI
    sign-in; it never installs a production auth bypass.
22. Streamlit retry keys now retain only a SHA-256 request scope, UUID, notebook
    id, and timestamp for one hour. The helper reuses unresolved retries, removes
    completed/deleted/expired entries, keeps at most eight per notebook and 24
    globally, preserves valid entries across notebook switches, and migrates
    only the active valid legacy entry without retaining raw prompt text.
23. The Cognito sign-in retry cooldown is server-authoritative. An absolute
    five-second deadline and a temporary 0.5-second Streamlit fragment keep the
    original button disabled without client-side DOM mutation. A bounded,
    non-sensitive per-tab query marker carries that exact deadline across a
    fresh Streamlit session after browser Back, then is consumed once; malformed,
    stale, or implausibly future values are rejected. The launch flag remains
    one-shot, and success, sign-out, logout, or configuration failure clears all
    transient state. Trusted auth navigation now uses Streamlit 1.60's
    non-iframed ``st.html`` API instead of the deprecated components helper.
24. DSQL idempotency tests now exercise two independent adapter instances,
    exact replay after restart, changed-payload conflict, provider-failure
    release, expired-lease takeover, stale-worker rejection, and whole-operation
    SQLSTATE ``40001`` retry without AWS. The guarded live runner requires
    ``--confirm-live``, the DSQL provider, ``co_design_app``, and an explicit
    ``cognito:<sub>`` owner; it uses runtime DML and the mock provider only.
25. Coach idempotency ``complete_coach_request`` is now idempotent when a waiter
    or restart already promoted the marker to ``completed`` from persisted
    message rows after the lease owner committed ``persist_coach_turn`` but
    before the owner completed. Matching key/fingerprint completed markers
    return successfully; expired takeover, provider-failure release, stale
    persist rejection, restart promotion, and DSQL OCC wrappers stay unchanged.
26. ``APP_ENV`` defaults to ``development``. When ``APP_ENV=production``,
    ``validate_production_configuration()`` fail-closes for mock provider,
    ``MOCK_OPENAI`` masking, sqlite/local/memory storage, DSQL admin runtime,
    insecure auth cookies, HTTP Cognito callbacks, incomplete Cognito/DSQL/S3/
    OpenAI configuration, and loopback or non-HTTPS public API/UI URLs. It
    reuses ``validate_storage_configuration`` and
    ``validate_cognito_readiness(require_https=True)`` with no network/AWS
    calls. ``create_app`` and ``/api/v1/ready`` both invoke it; readiness keeps
    a dual-gate for legacy dsql/s3 Cognito HTTPS checks during cutover.
    ``compose.prod.yaml`` and ``.env.example`` declare the env switch.

### Validation evidence

**Local (Phases 4–8 — this phase):**

- ``.venv/bin/python -m pytest -q tests/test_rate_limit.py
  tests/test_production_config.py tests/test_coach_idempotency.py
  tests/test_api.py`` → **64 passed**. Upload hardening covered by
  ``tests/test_upload_hardening.py``; compose/Caddy assertions in
  ``tests/test_deployment_config.py``.
- Branch ``Production-RemoveData``; no commit created in this phase.
- Phase 1–2 uncommitted work preserved.

**Local (Phase 2 — APP_ENV production fail-closed):**

- Focused suite → **39 passed** (1 warning: Starlette TestClient deprecation):
  ```sh
  .venv/bin/python -m pytest \
    tests/test_production_config.py \
    tests/test_api.py::test_local_api_ready_request_id_stream_and_graph \
    tests/test_api.py::test_readiness_fails_when_file_storage_is_unavailable \
    tests/test_api.py::test_production_readiness_requires_local_cognito_configuration_check \
    tests/test_api.py::test_production_readiness_redacts_dependency_error_details \
    tests/test_api.py::test_production_readiness_reports_cognito_configured_without_discovery \
    tests/test_deployment_config.py \
    tests/test_storage_providers.py::test_validate_storage_configuration_requires_production_fields \
    tests/test_cognito_token_jwks.py::test_production_cognito_readiness_is_local_and_requires_https_callback \
    tests/test_cognito_token_jwks.py::test_cognito_readiness_errors_do_not_echo_credentials
  ```
- ``tests/test_production_config.py`` alone → **21 passed**.
- ``tests/test_deployment_config.py`` alone → **10 passed**.
- No live OpenAI, DSQL, S3, or Bedrock calls. No schema migration.
- Branch ``Production-RemoveData``; no commit created in this phase.
- Phase 1 uncommitted files (``backend/student_store.py``,
  ``tests/test_coach_idempotency.py``) preserved.

**Local (Phase 1 — promote-vs-complete idempotency):**

- ``.venv/bin/python -m pytest -q tests/test_coach_idempotency.py`` → **15 passed**.
- Focused coverage added for promote-between-persist-and-complete, five-way
  concurrent same-key submissions, and API/stream HTTP 409 payload mismatch.
- No live OpenAI, DSQL, S3, or Bedrock calls. No schema migration.
- Branch ``Production-RemoveData``; no commit created in this phase.

**Prior local (previous production hardening phase):**

- ``.venv/bin/python -m pytest -q`` → **305 passed**.
- Focused auth/UI/production-path validation → **57 passed**.
- ``PYTHONPYCACHEPREFIX=/private/tmp/co-design-pycache .venv/bin/python -m
  compileall -q backend ui streamlit_app.py tests`` → exit 0.
- ``docker compose config --quiet`` and
  ``APP_IMAGE=co-design:test docker compose -f compose.prod.yaml config --quiet``
  → exit 0.
- ``sh -n scripts/start.sh scripts/start_prod.sh scripts/build.sh
  scripts/deploy_ecr.sh scripts/browser_e2e_smoke.sh`` → exit 0; the Python
  DSQL runner compiled, displayed ``--help``, and refused a missing
  ``--confirm-live`` before any connection attempt.
- ``git diff --check`` → exit 0.
- No live OpenAI, DSQL, S3, or Bedrock calls. No Bedrock implementation
  changes.
- The approved live-click smoke performed no credential entry: two clicks
  produced exactly two FastAPI login redirects and two Cognito Hosted UI GETs.
  Browser Back was invoked 2.7 seconds after the first click; the slow Streamlit
  reconnect completed after the five-second window with ``Redirecting...``
  retained and the original button enabled, proving the deadline was not
  restarted. The retry remained visible at 390 px and redirected exactly once.
  AppTest covers the complementary fast-remount case where Back completes before
  expiry and the same button must remain disabled.
- With the developer-authorized test account, the in-app browser completed the
  real Cognito Hosted UI PKCE login and callback, created/renamed a notebook,
  synchronized 7 lecture notes and 3 readings, displayed a grounded mock reply
  and ``[S1]`` citation preview, confirmed Focus → Evidence, restored the chat
  and stage after refresh, rendered Review scores, deleted the disposable
  notebook, and logged out.
- The live run reproduced and then verified the local foreign-key repair and
  authenticated background-sync fix. After cleanup, the test owner again had
  zero notebooks, messages, and sources.
- ``data/backups/co_design.pre-fk-repair-20260809.sqlite3`` is the pre-migration
  SQLite backup. It is local data and must never be committed.

### Compatibility, rollback, and known risks

- New S3 objects use ``raw/`` and ``derived/`` subpaths. Existing rows retain
  their full historical keys, remain readable, and stay within the same
  source/notebook deletion prefix. No object migration is required.
- DSQL bootstrap schema changed before live initialization. If an earlier
  draft schema was already applied, inspect existing uniqueness/index state
  before rerunning bootstrap; never drop production objects automatically.
- This DSQL bootstrap correction changes no table or index DDL. An earlier
  failed public-schema ``USAGE`` grant needs no rollback; rerun bootstrap, then
  apply only the documented object-level runtime grant.
- Public clients that sent unrestricted notebook/message metadata now receive
  422 and must use the typed settings or internal coaching endpoints.
- RAG requires no schema migration. New assistant/user metadata may include
  ``retrieval_refs``; older messages without it remain compatible.
- The current local retriever reads selected extracted text and chunks it at
  query time. This is deterministic and suitable for the bounded development
  corpus, but it is lexical rather than embedding-semantic and is not the
  long-term large-corpus index. Bedrock Knowledge Bases replaces this adapter.
- UI edit/regenerate stays unavailable until a transactional replacement
  design is implemented; the new request key protects retries of normal turns
  but does not define edit-in-place semantics.
- Existing local legacy tables are intentionally retained and left unchanged;
  rollback is a code revert because the older application ignores the added
  snake_case columns and the new five-table copies. A pre-existing database
  that already ran the earlier destructive users-table migration cannot have
  deleted legacy rows reconstructed from SQLite metadata; restore such rows
  from a pre-upgrade backup if available. Local upload files themselves are not
  deleted or rewritten by this migration.
- Split-owner repair preserves the authenticated Cognito row, moves any
  five-table notebooks onto it, merges preferences, and retains the obsolete
  empty row under a ``legacy-orphan:<id>`` identifier for inspection rather
  than deleting it.
- The SQLite foreign-key repair applies only when ``notebooks.user_id`` targets
  a table other than ``users`` and only when the known eight-column notebook
  layout matches. An unknown layout stops with a clear error instead of losing
  data. Restore the pre-repair backup to roll back the local database.
- This local compatibility phase changes no DSQL schema/bootstrap SQL, IAM,
  S3, Cognito infrastructure, EC2, paid-provider, or Bedrock behavior.
- Provider-token streaming is still simulated after a complete persisted turn
  and graph inspection state is process-local. Durable request idempotency now
  makes a disconnected stream safe to retry, but it does not turn the buffered
  response into upstream token streaming or persist graph inspection state.
- Completed idempotency reservations are stored as hidden internal rows in the
  existing ``messages`` table. No migration is required and current code omits
  them from chat/history/counts/activity. Rolling back to code that predates
  this filter can expose blank internal assistant rows; back up first and remove
  only rows explicitly marked ``_internal_type=coach_idempotency`` under an
  approved rollback procedure.
- The promote-vs-complete fix changes only ``complete_coach_request`` behavior
  for already-completed same-key/fingerprint markers. No schema or data
  migration is required; rollback is a code revert.
- ``APP_ENV`` and ``validate_production_configuration`` are additive. Local
  development remains the default; production Compose must set
  ``APP_ENV=production``. Rollback is a code/config revert with no schema or
  data migration.
- Fully automated protected-browser CI remains blocked by the deliberate lack
  of a production authentication bypass and by the uncached Playwright CLI.
  ``scripts/browser_e2e_smoke.sh`` therefore pauses for a human to complete the
  real Cognito Hosted UI before mobile/console capture. The deterministic
  authenticated HTTP regression and Streamlit AppTests run without live AWS.
- UI retry-key records are session-only and require no migration. Reverting the
  helper drops retry reuse after a disconnected Streamlit submission but does
  not change durable notebook/chat data or the HTTP idempotency contract.
- The DSQL concurrency suite uses independent ``DsqlStudentStore`` instances
  over an isolated SQLite transaction proxy, so it deterministically checks the
  adapter/lease/OCC contract without claiming wire-level Aurora behavior. The
  guarded live runner remains deliberately unexecuted until DSQL is ready and a
  separate live-write approval is given.
- Fresh Streamlit loads and ordinary reloads have a clean browser console. The
  in-app browser records React hydration errors ``#418``/``#423`` while restoring
  Streamlit itself from cross-origin browser history; the recovered page remains
  functional and no new error is emitted after it settles. The deprecated auth
  components iframe was removed, but eliminating this framework-level history
  artifact requires an upstream Streamlit/browser fix rather than more auth
  state mutation.
- The cooldown query marker contains only an epoch deadline, is scoped to one
  tab's URL, is accepted for at most a 30-second restore grace, and never
  authorizes a user or changes OAuth state. No API, cookie, schema, or data
  migration is required; rollback is limited to the two auth UI/test files.
- Rollback is a code/config revert. Do not commit `.env`, secrets, database
  files, or uploaded content. No live AWS resource was created or modified.

### Next exact action

Authoritative next steps for append-only revision are under **Current phase →
Next exact action** above. Continuing AWS cutover after that:

1. Configure GitHub branch protection per
   ``docs/deploy/GITHUB_BRANCH_PROTECTION.md``.
2. Owner decision on public lecture PDFs per
   ``docs/security/PUBLIC_REPOSITORY_CONTENT_AUDIT.md`` (do not delete/rewrite
   without explicit approval).
3. Create the private S3 uploads bucket in ``us-west-2`` with Block Public
   Access; attach bucket list plus ``users/*`` object permissions to the EC2
   instance role.
4. Finish Aurora DSQL, map the EC2 role to ``co_design_app``, run
   ``scripts/init_dsql.py`` as admin (or for existing clusters apply the
   manual notebook ``conversation_revision`` **and** three message revision
   column ``ALTER``s in ``docs/deploy/AWS_STATELESS_EC2.md``), then grant
   SELECT/INSERT/UPDATE/DELETE on all tables in ``public`` to
   ``co_design_app``. Do not grant schema ``USAGE``. App startup never DDL.
5. With separate live-write approval, run
   ``scripts/smoke_dsql_idempotency.py --confirm-live --identifier
   'cognito:<sub>'`` under ``DATABASE_PROVIDER=dsql`` and
   ``DSQL_USER=co_design_app``.
6. Deploy the immutable ECR image with ``scripts/deploy_ecr.sh`` and require
   internal ``/api/v1/ready`` 200. Verify Caddy edge curl checks in
   ``docs/security/CADDY_PUBLIC_BOUNDARY.md``.
7. Run the full Cognito → notebook → coach → upload → edit/revise → restart →
   isolation → logout live smoke in ``docs/deploy/AWS_STATELESS_EC2.md``. Use
   mock mode first; make an OpenAI request only with explicit approval and a
   cost cap.
8. Only after that smoke is green: open class-wide traffic; then consider
   durable provider streaming and Bedrock retrieval adapters.

## Previous completed work

**Provider-neutral stage prompts + retryable S3 cleanup** — ``19f5d4e`` on
``Production-RemoveData`` (pushed). Local mock suite 232 passed; GitHub Mock CI
failed on missing CI ``.env`` before compose validation.

**Final pre-AWS hardening (Cognito / DSQL / student S3)** — Cognito ID
``token_use``, JWKS cache, DSQL ``verify-full``, course-sync gate, orphan
object cleanup, ownership-in-write checks, ``ca-certificates`` in image.

**Multi-user FastAPI ownership + student S3 key isolation**

**Cognito-owned browser session + five-table persistence cleanup**

**DSQL bootstrap / adapter hardening**

**AWS stateless EC2 migration scaffolding**
