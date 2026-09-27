# Hybrid guest access phase handoff

## Current account append behavior (2026-09-26)

The user requested automatic guest-to-account append after sign-in or sign-up.
This supersedes the Phase 5 human preview/confirmation requirement below. On a
successful Cognito OAuth callback with a valid guest cookie from the same
browser and database, the server appends that guest's notebooks to the verified
Cognito account. Notebook IDs, transcripts, learning records, citations, and
uploaded objects retain the Phase 5 copy-then-commit safety rules. Existing
account notebooks and profile preferences remain unchanged except for
`active_thread_id`: when the guest's last-open notebook is among the transferred
notebooks, it becomes the account's active notebook in the same transaction.
An absent or stale guest selection leaves the account's selection unchanged. The guest cookie
is cleared only after the ownership commit. A failed transfer does not block
sign-in; the cookie remains and the UI gives a neutral retry message. Copying
a large workspace happens during the OAuth callback and may delay its redirect;
if the browser times out, the user can sign in again with the same guest cookie
to replay or retry the idempotent claim. Email or
display-name matches never establish ownership. Legacy preview/confirm API
routes remain for compatibility, but the student UI no longer requires them.
The previous separate temporary guest-trial SQLite database cannot be
automatically appended to the usual database by signing in; it needs a
separate, reviewed migration if that work is wanted.

## Decision and identity contract

- Cognito is optional for students and remains required for lecturer/admin
  access. `GUEST_ACCESS_ENABLED=false` is the default and rollback switch. When
  false, signed-out students see the current sign-in gate. When true, a student
  may use a guest workspace or sign in with Cognito; a verified Cognito session
  always resolves to its Cognito owner.
- The server creates an opaque guest owner identifier and a cryptographically
  random bearer secret (at least 256 bits). The browser receives only the
  secret in a dedicated HttpOnly, SameSite=Lax cookie, Secure outside loopback.
  FastAPI validates it and resolves a guest-scoped `OwnerServices` instance.
  Persist only a one-way digest of the bearer secret, never the raw secret.
- The guest cookie is a 400-day rolling credential. Streamlit's API client is
  server-to-server (`httpx` with nonpersistent cookies), so a `Set-Cookie` from
  its API request cannot renew the browser cookie. After successful guest
  activity, the UI must trigger a same-origin browser request to
  `POST /api/v1/auth/guest/renew` with browser credentials included. Caddy must
  allowlist this exact browser-facing route before its `/api/*` deny rule. The
  browser receives FastAPI's HttpOnly `Set-Cookie` with
  `Max-Age=34560000` (400 days), while FastAPI validates the guest cookie and
  slides the matching server-side expiry. Do not relay the credential through
  Streamlit or expose it to JavaScript. Validate expiry and revocation on every
  guest request. Logout/revoke returns an expired cookie and invalidates its
  credential for workspace access. The 400-day value is a browser maximum, not
  a promise of retention:
  private browsing, browser cleanup, browser policy (including shorter
  tracking-prevention limits), or changing browsers can remove it sooner.
  Losing the cookie loses the ability to recover an unclaimed guest workspace.
- Lecturer views and analytics display a stable guest pseudonym for guest
  activity and never expose a guest cookie, token digest, or raw guest
  identifier. Signed-in student display names and emails retain their current
  lecturer visibility and analytics behavior.
- Guest credentials authorize only that guest owner. Cognito identity is still
  established only from the verified ID token `sub`; client IDs, email matches,
  names, notebook IDs, and UI state never establish ownership. Guest sessions
  cannot access lecturer/admin endpoints.

## Superseded Phase 5 explicit account claim and transfer contract

- Account claim is an explicit user action after successful Cognito sign-in.
  The claim request must present both the valid guest cookie and the verified
  Cognito session. There is no automatic linking by email or other profile
  fields, and signing in alone never transfers guest data.
- Before transfer, show a user-visible preview naming the Cognito account and
  listing the guest notebooks plus their uploaded files (including file names
  and counts). Transfer begins only after the user explicitly confirms that
  preview; dismissing it or signing in alone leaves guest ownership intact.
- The server transfers all notebooks owned by that guest to the authenticated
  Cognito user. Notebook IDs and their messages, revisions, sources, learning
  state, and citations are preserved. Because upload/extraction object keys
  include the owner ID, first copy guest-owned raw and derived objects into the
  Cognito owner's generated notebook/source prefixes and verify each copy.
  Then update source key references and notebook ownership in one database
  transaction. Only after commit, best-effort delete old guest-prefix objects;
  failed cleanup leaves inaccessible orphan objects for a retryable cleanup
  path, never broken active references. A copy or transaction failure leaves
  the guest workspace authoritative and its credential usable; incomplete
  pre-commit copies are safely retryable/cleanable. Do not merge user roles or
  overwrite Cognito profile/preferences from guest state.
- Only the guest cookie holder may claim that guest owner. Claim is idempotent
  for retries by the same Cognito user, rejects a different already-claimed
  owner, and revokes the guest credential for workspace access after a
  successful transfer. Retain only a claim-result tombstone until the guest
  session expiry in effect at claim time. A retry must prove the same
  authenticated Cognito owner and matching revoked guest-token digest plus
  claim operation ID. The tombstone returns the prior claim result and never
  authorizes guest workspace access. A failed copy or transaction leaves
  ownership and guest workspace credential unchanged. No email-based recovery
  is implied.

## Current architecture inventory

- `ui/auth_gate.py` renders the signed-out Cognito gate before normal session
  initialization. `ui/auth/cookies.py` reads browser cookies as hints only.
- `backend/auth_routes.py` owns Cognito OAuth, refresh, logout, and
  `sync_authenticated_user`; `backend/auth_profiles.py` maps verified `sub` to
  `cognito:{sub}`.
- `backend/owner_context.py` and `backend/http/app.py:current_owner` resolve
  owner-scoped services. A missing Cognito cookie currently falls back to the
  local default for injected/local configurations; production UI remains gated.
- `backend/student_store.py` persists users and notebooks. `notebooks.user_id`
  is the ownership boundary; messages, sources, and learning records are
  notebook-scoped. Local files and S3 object-key helpers also enforce owner
  prefixes. **Pre-Phase-2 baseline:** SQLite and DSQL had no guest credential
  table. Phase 2 now adds `guest_sessions` to both schemas; SQLite creates it
  additively, while existing DSQL clusters use the explicit admin-only
  `--guest-sessions-only` migration before any live guest route or production
  enablement.
- `docs/SECURITY_BOUNDARIES.md` defines the existing Cognito and retrieval
  authorization boundary. `docs/LOCAL_DEMO_IMPLEMENTATION.md` remains the
  architecture authority.

## Historical seven implementation phases

The Phase 5 manual confirmation and its acceptance rows below describe the
original plan. The current automatic append behavior is defined at the top of
this file and in the current acceptance rows below.

1. **Contracts and baseline (this phase).** Record identity/claim decisions,
   inventory, acceptance criteria, risks, and mock-mode validation baseline.
2. **Persistence.** Add an additive, indexed guest credential/owner mapping to
   SQLite and DSQL with explicit initialization, migration, backup, and rollback
   procedures. Add repository operations for credential create, validate,
   renew, and revoke. Never store raw bearer secrets.
3. **API ownership.** Add the feature flag and guest owner resolution in the
   FastAPI composition/dependency path. Keep current Cognito `sub` resolution
   authoritative and fail closed on invalid/expired guest credentials. Add
   `POST /api/v1/auth/guest/renew` and its exact Caddy allowlist entry; validate
   the guest cookie and renew server expiry only through this browser-facing
   same-origin route.
4. **Guest workspace UI.** Add the signed-out guest entry and guest-state
   handling while retaining the existing authenticated workspace and protected
   professor gate. After successful guest activity, have the browser call the
   renewal route with `credentials: "same-origin"`, so the browser receives
   FastAPI's `Set-Cookie` directly; Streamlit's `httpx` calls cannot renew it.
   Do not put secrets in Streamlit session state or URLs.
5. **Explicit account claim.** Add the authenticated claim endpoint and UI
   action; perform a transaction-safe transfer and revoke the guest credential
   only after success.
6. **Lecturer compatibility and analytics.** Verify guest activity appears
   under stable pseudonyms throughout lecturer rosters, notebook views, and
   aggregates, while signed-in student names/emails and existing analytics
   behavior remain intact. Check guest tokens and raw guest identifiers never
   appear in lecturer output.
7. **Full integration and release handoff.** Run the complete acceptance and
   security matrix: isolation, expiry/renewal, cookie loss, claim preview and
   confirmation/retry/failure, uploaded-file transfer, storage paths, lecturer
   compatibility, restart recovery, old data, and flag-off behavior. Document
   the release and rollback handoff. Keep the production feature flag off; do
   not deploy or enable guest access in this phase.

## Acceptance matrix

| Case | Expected result |
|---|---|
| Flag off; signed-out browser | Existing Cognito gate; no guest owner or data access |
| Flag on; first guest visit | Server issues one guest identity and cookie; workspace is owner-scoped |
| Guest A requests Guest B notebook/source/object | Denied; no identifiers from the client can change owner scope |
| Guest activity renews session | UI triggers same-origin browser `POST /api/v1/auth/guest/renew` with credentials included; Caddy allowlists it; FastAPI validates the cookie and returns HttpOnly `Set-Cookie` with 400-day `Max-Age` while sliding server expiry |
| Guest returns with valid cookie | Same guest owner and persisted workspace; browser cookie and server expiry are renewed by the browser-facing flow |
| Missing, malformed, revoked, or expired guest cookie | No guest data access; fresh guest may be created only by the guest entry flow |
| Guest cookie lost or unavailable in a browser | Existing workspace cannot be recovered from another browser; explain the limitation |
| Student signs in with a valid guest cookie | Cognito is optional for students; verified sign-in automatically appends the guest notebooks to the account |
| Student signs in without a valid guest cookie | Account notebooks load unchanged; no unrelated guest data is transferred |
| Automatic append after Cognito sign-in | Raw and derived uploaded files are copied to account prefixes, then notebook/key ownership changes atomically; IDs/content remain intact; old objects are cleaned after commit |
| Automatic append fails | Sign-in succeeds, guest cookie and ownership remain recoverable, and the UI shows a neutral retry warning |
| Claim retry for same account / claim by another account | Same account plus matching revoked guest-token digest and claim operation ID returns the prior result; tombstone grants no workspace access; another account is rejected |
| Lecturer views guest and signed-in students | Guest activity uses a stable pseudonym in views/analytics; signed-in names and emails retain current visibility |
| Guest requests professor endpoint | Denied; staff authorization still requires Cognito and a persisted protected role |
| Restart with guest data | Valid guest cookie resolves to same persisted guest workspace |
| Phase 7 release handoff | Full integration results and rollback are documented; production flag remains off and no deployment occurs |
| Rollback by setting flag off | New guest access is disabled; guest rows/data remain retained for safe re-enable or later claim |

## Phase 1 result

Expected: documentation-only changes, zero runtime/schema/data changes, full
mock suite and compile check recorded as a pre-change baseline. Actual: this
handoff and the Phase 1 status entry were added; compileall passed; the baseline
suite completed with 12 failures (listed in the status entry), so the suite is
not green before guest-access implementation. No paid model calls or live
service were used.

**Next exact action:** begin Phase 2 at `backend/persistence/store/sqlite_schema.py`,
`backend/persistence/dsql_schema.py`, and the `StudentStore` migration and
repository seams; design the additive guest credential migration and rollback
before writing runtime code. Keep `GUEST_ACCESS_ENABLED=false`.

**Phase 1 continuation authorization:** the user replied “continue” after the
Phase 1 handoff, authorizing Phase 2 implementation. This does not authorize
guest API/UI exposure, a live DSQL migration, or production enablement.

## Phase 2 result — persistent guest sessions

**Expected:** add a SQLite and DSQL guest credential table keyed by a SHA-256
digest; server-generate a 256-bit bearer secret and opaque guest owner; expose
create, validate, 400-day rolling renew, and revoke operations; preserve
existing Cognito/local users and workspaces; provide a safe admin-only DSQL
migration; and prove operations through deterministic persistence tests. No
public route, guest UI, feature flag, live DSQL change, or production enablement.

**Actual:** implementation is present in `backend/persistence/guest_sessions.py`,
`backend/student_store.py`, both schema modules, `backend/persistence/dsql_student_store.py`,
and `scripts/dsql/cli.py`. SQLite initialization applies only additive
`CREATE TABLE/INDEX IF NOT EXISTS` statements. DSQL's runtime store does not
issue DDL, and readiness does not require `guest_sessions`, so Phase 2 code can
run against an existing production cluster with the feature dormant. Before
any live DSQL guest route or production guest enablement, run the explicit
admin migration; Phase 3 local/mock work does not touch live DSQL:

```sh
DSQL_ENDPOINT=<hostname> AWS_REGION=us-west-2 \
  .venv/bin/python scripts/init_dsql.py --guest-sessions-only --dry-run
DSQL_ENDPOINT=<hostname> AWS_REGION=us-west-2 \
  .venv/bin/python scripts/init_dsql.py --guest-sessions-only
```

The dry run reads the DSQL catalog and prints the planned additive table,
indexes, and `co_design_app` grant without writing. Take an approved DSQL
snapshot/export before applying. Each DDL/grant is committed separately; async
indexes are awaited. For a local SQLite database, take a SQLite online backup
before first startup with this code, using the actual database and backup
paths, for example:

```sh
sqlite3 /path/to/co_design.sqlite3 \
  ".backup '/path/to/co_design.pre-guest.sqlite3'"
```

The startup migration does not rewrite users, notebooks, or existing guest
data. Rollback is an application revert and leaving the additive
table/indexes/grant in place. Do not drop the table after guest rows may have
been created; retention and later cleanup need an explicit policy.

Validation: Luna's combined focused guest-session, storage-provider,
DSQL-admin, and persistence-contract command passed (56 tests). Sol
independently ran a broader focused command and passed 64 tests (6 guest,
31 storage-provider, 18 DSQL-init, and 9 architecture-contract tests).
Coverage includes out-of-order renewals and fake-admin inspection, dry-run,
apply/wait ordering, safe rerun, and CLI dispatch. Compileall and
`git diff --check` passed. The prior phase-boundary full suite retained the
same 12 pre-existing failures as the Phase 1 Luna baseline; it was not rerun
after these focused review fixes. No live DSQL or paid model calls were made.
No API/UI route or guest feature flag was added. Claim-transfer persistence is
deferred to the explicit claim phase so this phase only supports credential
lifecycle.

**Next exact action:** Phase 3 starts at `backend/owner_context.py` and
`backend/http/app.py`; implement flag-off guest owner resolution and the
browser-facing renewal route with local/mock tests. Keep production disabled;
the admin migration is a prerequisite before any live DSQL guest route or
production enablement.

## Phase 3 result — API ownership

**Expected:** add a default-off feature flag and guest cookie name; resolve a
valid guest credential to its isolated persisted owner per request while
keeping verified Cognito `sub` authoritative; reject invalid Cognito or guest
credentials without fallback; and add a same-origin renewal POST that validates
the cookie, slides server expiry, and sets a 400-day HttpOnly browser cookie.
Missing guest credentials after enabling guest mode must fail closed. Logout
must revoke and expire a presented guest credential only through a same-origin
POST, so cross-site navigation cannot discard the guest's recovery cookie.
Allow only that exact browser route through Caddy before the API deny rule.
Keep professor endpoints Cognito-only and production guest access disabled. No
guest UI, credential-creation route, claim route, lecturer pseudonym, live DSQL,
or deployment belongs to this phase.

**Actual:** the feature flag defaults false, is explicitly false in production
Compose, and guards guest resolution and renewal. With it off, owner resolution
does not query the guest table, preserving compatibility with DSQL clusters
before their explicit Phase 2 admin migration. A verified Cognito identity is
resolved first; invalid Cognito returns 401 even when a guest cookie is also
present. Missing or invalid/expired/revoked guest cookies return 401 while guest
mode is on; flag-on requests never fall through to `local-student`. Valid
guest cookies map to the persisted opaque guest identifier and owner UUID, so
notebook operations stay isolated. `POST /api/v1/auth/guest/renew` requires a
matching configured Origin and request Host, validates and renews the guest
credential, and returns `Max-Age=34560000`, `HttpOnly`, `SameSite=Lax`, and
Secure outside loopback / when production cookie security is enabled. The raw
secret appears only in the Set-Cookie header. Caddy allowlists this exact route
before `handle /api/*`. Professor routes continue to require Cognito and a
persisted staff role. Guest logout revokes and expires the cookie only through
a same-origin POST. GET and cross-origin POST preserve the guest cookie. With
the flag off, a same-origin POST expires the cookie and skips guest-table
access. No guest UI or creation/claim route was added.

**Files changed for Phase 3:** `backend/settings.py`,
`backend/owner_context.py`, `backend/http/app.py`, `backend/auth_routes.py`, `Caddyfile`,
`compose.prod.yaml`, `.env.example`, `tests/http/test_guest_access.py`,
`tests/test_deployment_config.py`, and `tests/test_architecture_contracts.py`.
The status entry was added to `docs/IMPLEMENTATION_STATUS.md`. Pre-existing
Phase 2 persistence edits, `docs/CODEBASE_STRUCTURE.md`, and untracked
`docs/learning/` were preserved.

**Validation:** Sol High independently passed 56 focused tests across guest
API ownership, Cognito sessions, Caddy deployment, and route inventory (with
the known production Compose baseline test excluded). After the logout fix,
`tests/http/test_guest_access.py tests/http/test_app_sessions.py` passed 24
tests. Compileall and `git diff --check` passed. The final full suite completed
with exactly the same 12 baseline failures recorded in `docs/IMPLEMENTATION_STATUS.md`
and no Phase 3 failure. The two pre-existing Streamlit failures observed in
that run are
`tests/ui/test_streamlit_ui.py::test_streamlit_notebook_workspace_smoke`
(source assertion finds `truncate` in a docstring/comment) and
`tests/ui/test_streamlit_ui.py::test_learning_studio_and_notebook_history_controls`
(rendered output no longer contains `Stage Progression`). No cause is recorded
for the other baseline failures. No live AWS/DSQL or paid calls were made.

**Compatibility and rollback:** no schema or data migration was run. Production
Compose keeps `GUEST_ACCESS_ENABLED=false`; setting it false disables guest API
ownership and skips guest-table reads. A same-origin POST logout while disabled
clears the browser cookie but does not revoke its stored credential; while
access remains disabled that credential cannot resolve an owner. Rollback is
to keep/set that flag false or revert the Phase 3 API/config/Caddy changes.
Retain Phase 2's additive guest table and any rows.

**Risks/blockers:** guest routes were exercised only with temporary SQLite.
Enabling them with DSQL requires the approved Phase 2 admin migration first.
The API supports existing valid credentials, but this phase intentionally does
not create them; the later UI phase must add the signed-out guest entry. For a
stored credential to be revoked on logout, guest access must be enabled so the
server can query the guest table. The local launcher serves Streamlit on 8501
and FastAPI on 8000; Phase 4 needs a single-origin browser route or proxy so
the renewal request passes the Origin check.

**Next exact action:** begin Phase 4 at `ui/auth_gate.py` and the browser cookie
bridge. Add the signed-out guest entry and guest-state handling, then make a
same-origin browser request to `POST /api/v1/auth/guest/renew` after successful
guest activity. Keep account claim and production enablement for later phases.

## Phase 4 result — guest workspace UI

**Expected:** add explicit guest start/reuse and safe guest probe routes with
flag-off 404 and origin/host validation; preserve Cognito precedence; add the
signed-out Continue as guest action; verify guest ownership through FastAPI
before initializing protected workspace state; forward only current browser
cookies via the per-request API client while retaining a nonpersistent shared
cookie jar; renew from the browser after successful activity; and clear
identity-dependent Streamlit state when owners switch. Preserve the professor
gate, keep account claim and production enablement out of scope, and provide an
exact-route local same-origin proxy that does not break the existing local
startup when Caddy is unavailable.

**Actual:** `POST /api/v1/auth/guest/start` creates a guest only after the
student explicitly clicks the guest entry, or reuses a valid existing guest
cookie. The raw secret is set only as a 400-day HttpOnly SameSite=Lax cookie;
the JSON body contains only `started` and the safe opaque persisted owner
identifier. A valid Cognito cookie returns 409 from guest start and an invalid
Cognito cookie returns 401, so guest mode cannot downgrade an attempted
Cognito session. `POST /api/v1/auth/guest/probe` is read-only, returns only the
opaque owner identifier, applies origin/API-host checks, and never creates or
renews a guest. Both routes return 404 when the feature flag is off. Streamlit
checks Cognito first, then probes the guest cookie with FastAPI before calling
`initialize_session()`. Its dynamic request-cookie provider forwards Cognito
ID and guest cookies; the shared `httpx` cookie jar continues to discard
`Set-Cookie`. After the workspace renders successfully, the browser calls the
relative renewal route with `credentials: 'same-origin'`; there is no idle
polling. Guest logout also uses a same-origin POST so its credential can be
revoked when guest is the active identity. Cognito sign-in from the guest
profile uses the existing login route and leaves the guest cookie untouched;
afterward Cognito owns the active workspace while guest data remains
unclaimed. Cognito logout uses the redirect/GET path, and the API also refuses
to revoke or expire a guest cookie on same-origin POST when either Cognito ID
or refresh cookies are present. After sign-out, the preserved guest cookie
resolves its original workspace. A pending Cognito refresh hint is processed
before guest probing, including when a guest cookie is also present. Owner
changes clear the previous Streamlit session state before binding the new
owner. The signed-out guest entry and guest profile display a short warning
that cookie loss may make history inaccessible and account linking is planned
for Phase 5.

`Caddyfile.local` exposes exact auth routes plus the lightweight health route,
denies the rest of `/api/*`, and proxies all other paths to Streamlit. When
`GUEST_ACCESS_ENABLED=true`, `scripts/start.sh` starts this proxy if Caddy is
installed and advertises port 8080. If Caddy is missing, it reports the
limitation, disables guest access in that launcher process, and retains the
existing Streamlit 8501 / API 8000 startup. Production Compose remains
disabled. No schema/data migration, live DSQL action, deployment, or claim
transfer was performed.

**Files:** `backend/http/app.py`, `backend/auth_routes.py`,
`backend/api_client.py`, `ui/auth_gate.py`, `ui/profile.py`,
`ui/services/runtime.py`, `streamlit_app.py`, `Caddyfile.local`,
`scripts/start.sh`, `tests/http/test_guest_access.py`,
`tests/ui/test_auth_gate.py`, `tests/ui/test_runtime_cache_safety.py`, and
`tests/scripts/test_guest_local_proxy.py`. Updated
`docs/IMPLEMENTATION_STATUS.md` and this handoff. Existing
`docs/CODEBASE_STRUCTURE.md`, `docs/learning/`, and prior-phase changes were
preserved.

**Validation:** Sol independently ran
`.venv/bin/python -m pytest -q tests/http/test_guest_access.py tests/http/test_app_sessions.py tests/ui/test_auth_gate.py tests/ui/test_runtime_cache_safety.py tests/scripts/test_guest_local_proxy.py`;
all 87 tests passed. Regressions cover combined cookies, refresh-before-probe,
guest-to-Cognito entry, guest credential preservation, and the warning copy.
`sh -n scripts/start.sh`, compileall over
`backend ui streamlit_app.py tests scripts`, and `git diff --check` passed. The
Phase 1 baseline of 12 full-suite failures was not rerun. An independent headed
Playwright check inspected the guest entry at 1280 px and 390 px with no app
console errors; only standard Streamlit warnings appeared. Caddy is unavailable
here, so local proxy behavior remains unverified. No paid model call, live
DSQL/AWS operation, or deployment occurred.

**Compatibility and rollback:** no migration was needed. Production and the
default feature flag remain off; disabling `GUEST_ACCESS_ENABLED` hides guest
entry and makes start/probe/renew unavailable. Caddy absence preserves normal
local startup and disables guest mode for that run. Revert the Phase 4 app,
UI, and local-proxy changes to roll back; retain Phase 2 additive guest rows.

**Known risks:** run the real Caddy route and end-to-end same-origin browser flow
once Caddy is available. Desktop and 390 px checks covered the signed-out guest
entry. Live DSQL guest use still requires the explicit Phase 2 admin migration.
Account claim and lecturer guest pseudonyms remain later work.

**Next exact action:** Phase 5 starts at `backend/student_store.py` and
`backend/http/app.py`. Define and implement the explicit guest claim preview
and confirmation API, transaction-safe ownership transfer, uploaded-file copy
and cleanup ordering, idempotent retries, and failure rollback. Keep
production access disabled.

## Phase 5 result — explicit account claim

**Expected:** require valid Cognito and guest credentials, same-origin preview
and explicit confirmation, and keep login alone from moving data. Bind consent
to the account, operation ID, and displayed inventory. Copy and verify private
raw/extracted objects before one database ownership commit; preserve notebook
IDs, messages/revisions/citations, sources, learning state, stable local file
paths, and account profile/roles/preferences. Fence guest requests during the
copy, revoke only after commit, support same-account retry/restart, avoid
overwriting account objects, and retain the default-off production state.

**Actual:** `POST /api/v1/auth/guest/claim/preview` requires the configured
same origin, an active verified Cognito owner, and the existing guest cookie.
It shows account name/email and notebooks with uploaded filenames/counts. The
server stores a ten-minute operation ID, Cognito owner, and inventory
fingerprint in `guest_sessions`; preview does not fence or transfer anything.
`POST /api/v1/auth/guest/claim/confirm` requires the explicit confirmation
boolean and that preview operation. A changed inventory returns 409 with a
refresh-preview instruction before setting the write fence. Confirmation
fences new guest owner resolution, copies all guest notebook-prefix objects to
the Cognito owner prefix through the FileStorage port, verifies destination
bytes, and refuses to overwrite a different existing account object. It then
rechecks the full notebook/source fingerprint and atomically updates notebook
ownership, source object/extracted references, guest revocation, and the
account-bound retry tombstone. Notebook/message/source IDs, revisions,
citations, journey state, and the Cognito profile/role/preferences remain
intact. Local `files_dir/threads/<notebook>/uploads` and `metadata.local_path`
are owner-independent stable paths and are preserved. Old guest prefixes are
removed after commit; same-account recovery retries cleanup. Caddy now
allowlists only the exact claim preview, confirmation, and cancel paths in front
of the general API deny rule. Origin validation requires the configured public
Origin and accepts only a Host matching that public origin or the configured
internal API host used by Streamlit's server-side API client. The profile uses
plain text labels and a separate Confirm transfer button. A recreated app
session can resume a pending same-account operation, and the same account can
recover a completed result after a lost UI response. Cancel releases a pending
fence only when the Cognito owner, guest cookie, and operation ID all match.
Ambiguous confirm errors direct the student to retry or review status. Other
Cognito owners cannot use that operation.

**Files:** `backend/http/app.py`, `backend/api_client.py`,
`backend/guest_claims.py`, `backend/student_store.py`,
`backend/persistence/store/sqlite_schema.py`,
`backend/persistence/store/migrations.py`,
`backend/persistence/dsql_schema.py`,
`backend/persistence/dsql_student_store.py`, `scripts/dsql/cli.py`,
`Caddyfile`, `Caddyfile.local`, `ui/profile.py`,
`tests/http/test_guest_access.py`, `tests/persistence/test_guest_sessions.py`,
`tests/scripts/test_init_dsql.py`, `tests/scripts/test_guest_local_proxy.py`,
`tests/test_architecture_contracts.py`, `tests/test_deployment_config.py`, and
`tests/ui/test_auth_gate.py`. Earlier guest phases, user-modified
`docs/CODEBASE_STRUCTURE.md`, and untracked `docs/learning/` were preserved.

**Validation:** the final targeted deterministic suite passed across
guest API/persistence, DSQL admin migration planning, UI auth/cache safety,
storage providers, local proxy routes, architecture contracts, and deployment
route contracts. It covers no-transfer preview, stale preview rejection,
explicit transfer, verified object copies, stable local path preservation,
profile/role/preferences preservation, session fencing, revoked guest access,
same-account operation replay and store-restart recovery, completed claim
recovery, distinct public/internal hosts, owner-bound cancellation after store
restart, fresh DSQL fields, neutral UI error copy, and different-owner
rejection. Compileall, `sh -n scripts/start.sh`,
and `git diff --check` passed. The known unrelated production Compose test was
excluded; the full suite was not run. Sol independently reran the focused
command and confirmed 157 tests passed. No live DSQL/AWS, paid call, Caddy
server, or deployment was used.

**Migration and rollback:** SQLite startup additively adds four claim tombstone
and four preview-binding columns to `guest_sessions`; existing users, notebooks,
and guest rows are preserved. Fresh DSQL schema includes those fields. Existing
DSQL clusters require a backup and the admin-only
`--guest-sessions-only --dry-run` followed by `--guest-sessions-only` to add
the columns/indexes/grants; no live migration was run. For SQLite rollout, take
an online backup first. Rollback keeps `GUEST_ACCESS_ENABLED=false` or reverts
the application while leaving added columns/rows. A committed transfer is not
reversed by application rollback; account ownership and revoked guest
credentials remain authoritative.

**Known risks:** real S3 copy permissions and production Caddy routing remain
unverified. Expired account-bound tombstone fields remain physically stored
after replay expiry, although replay is denied. Partial copies can leave unreferenced account-prefix objects; a
retry reuses them only if bytes match. Best-effort old-prefix deletion may
leave inaccessible guest-object orphans; account-bound tombstone recovery
retries cleanup until the captured guest expiry. DSQL claim routes require the
admin migration before use. If Cancel races with an already committed
confirmation, it may return `released: false`; reopening the preview recovers
the completed result. The production feature flag remains off.

**Next exact action:** completed by the Phase 6 result below. Keep production
guest access disabled.

## Phase 6 result — lecturer guest identity projection

**Expected:** lecturer roster, overview/attention, detail, transcript/workspace
tabs, and Research queue/detail/CSV show stable guest pseudonyms and never
expose raw guest owner IDs, `guest:` identifiers, bearer secrets, token digests,
or hidden claims. Signed-in names/emails and established aggregates remain
unchanged. A claimed guest user is absent as a second active student, while its
notebooks and research evidence appear once under the Cognito owner. Preserve
research observations, reviews, adjudications, and historical audit IDs in
storage; target new access audits at the real internal owner. Require staff
auth, work with the guest feature flag off, and do not depend on
`guest_sessions`.

**Actual:** `backend/professor_analytics/guest_identity.py` provides a
provider-neutral, domain-separated SHA-256 projection over the immutable guest
owner ID. It returns a `guest_` public ID with a 20-hex digest and `Guest`
display name with a 10-hex suffix. Guest identity is determined from a
persisted `guest:` identifier plus no Cognito sub; email is null. Signed-in
identity fields remain unchanged. Professor population queries exclude only
guest rows that own no notebooks. The same narrow repository resolver handles
student detail, transcript, workspace, messages, sources, attachments,
journey, and review routes before the existing ownership checks and audit
targeting; it never consults `guest_sessions`, uses a global cache, or accepts a
raw guest owner ID as a public alias. Research queue/detail/CSV project the
same public identity. Research detail strips internal owner/classification
fields from returned observation dictionaries and pseudonymizes nested review
and adjudication actor IDs when they belong to a persisted guest; signed-in
actor IDs remain unchanged. After claim the current notebook owner is used. No
research or audit row is updated.

**Files:** `backend/professor_analytics/guest_identity.py`,
`backend/professor_analytics/repository.py`,
`backend/professor_analytics/service.py`,
`backend/professor_analytics/research.py`, `backend/research/models.py`,
`backend/http/app.py`, `backend/student_store.py`,
`tests/http/test_professor_analytics.py`,
`tests/http/test_guest_access.py`, `docs/IMPLEMENTATION_STATUS.md`, and this
handoff. Phase 1–5 changes, `docs/CODEBASE_STRUCTURE.md`, and
`docs/learning/` were preserved.

**Validation:**
`.venv/bin/python -m pytest -q tests/http/test_guest_access.py tests/http/test_professor_analytics.py tests/http/test_professor_research.py tests/persistence/test_research_persistence.py`
→ **61 passed**. The tests cover two guests, stable aliases after store
recreation, secret/raw identity redaction, unchanged signed-in profile display,
guest pseudonym detail/transcript/journey/source drill-down, cross-guest
notebook/source denial, raw guest-ID alias rejection, guest credential denial
with the flag off, Research queue/detail/CSV, staff auth, internal audit
targets, and a real Phase 5 claim commit. That commit checks one Cognito roster
and overview student, current-owner Research attribution, post-claim
pseudonymization of nested historical guest actor IDs, retained evidence, and
byte-for-byte preservation of observation/review/adjudication rows plus
historical audit actor/target IDs. Full suite, live DSQL/AWS, paid calls, and
deployment were not run. The suite has previously recorded unrelated baseline
failures. Sol High initially found the nested historical actor-ID leak; the
projection fix passed independent re-review. The four-suite rerun passed 61
tests, the strengthened claim regression passed again, backend compileall
passed, and `git diff --check` passed.

**Migration and rollback:** no schema migration or data rewrite. Queries depend
only on `users` and `notebooks`; DSQL deployments without the optional
`guest_sessions` table remain compatible. Rollback is a code revert. It does
not undo an already committed claim or change the retained research records.

**Known risks:** full Phase 7 integration/release coverage, live DSQL/S3
permissions, real Cognito, restart recovery, and desktop/mobile browser checks
remain unverified. Public guest IDs remain stable pseudonyms; internal IDs stay
server-side for ownership and audit.

**Next exact action:** Phase 7 begins with the mocked renewal/claim/lecturer
acceptance paths, then completes the remaining integration and restart matrix
in this handoff. Record rollback evidence and keep production guest access off;
do not deploy or enable the flag in that phase.

## Phase 7 result — integration and release handoff (2026-09-26)

**Expected:** close the mock guest acceptance gaps; test a pre-Phase-5 SQLite
guest session through online backup, current startup migration, restore, and
flag off/on; capture safe mock startup/restart evidence; and leave production
guest access disabled. Do not touch live DSQL/AWS/Cognito/S3, deploy, or run
`init_dsql`.

**Actual:** focused tests now cover Guest A denied access to Guest B's notebook,
source, and a real attachment referenced by a persisted victim message. They
also verify that object-copy and ownership-commit failures leave guest owner,
credential, and source references usable for same-operation retry; old-prefix
cleanup failure after commit keeps the account workspace available and same-
account recovery retries cleanup; cookie loss followed by explicit start
creates a distinct owner; and feature flag on → off → on returns 404 for guest
routes without resolving a guest owner while off, retaining the workspace for
re-enable. Existing tests cover completed-claim account ownership and guest
revocation.

The migration regression creates a legacy five-column `guest_sessions` table
with a valid guest, notebook, and message, takes a SQLite online backup, then
opens the working copy with current `StudentStore`. It verifies claim columns
are added while the old records and unexpired session remain intact. The
pre-migration backup is restored to a second temporary DB; current startup
migrates that copy and resolves the same guest workspace. Both DBs live only
under pytest temporary storage.

**Files changed in this phase:** `tests/http/test_guest_access.py`,
`tests/persistence/test_guest_sessions.py`,
`tests/ui/test_streamlit_ui.py` (one source-text assertion narrowed to the two
coaching-style functions it covers), and only the Phase 7 sections of
`docs/IMPLEMENTATION_STATUS.md` and this handoff.

**Validation and exact commands:**

The existing guest acceptance block was run first, before adding the Phase 7
cases, and exited 0. It excluded only the known unrelated Compose baseline test:

```sh
.venv/bin/python -m pytest -q tests/http/test_guest_access.py tests/persistence/test_guest_sessions.py tests/http/test_professor_analytics.py tests/http/test_professor_research.py tests/persistence/test_research_persistence.py tests/http/test_app_sessions.py tests/ui/test_auth_gate.py tests/ui/test_runtime_cache_safety.py tests/persistence/test_storage_providers.py tests/scripts/test_init_dsql.py tests/scripts/test_guest_local_proxy.py tests/test_architecture_contracts.py tests/test_deployment_config.py -k 'not test_production_compose_is_stateless_and_uses_prebuilt_image'
```

After additions, `.venv/bin/python -m pytest -q tests/http/test_guest_access.py tests/persistence/test_guest_sessions.py` passed **28 tests**. Eleven selected compatibility tests passed for retrieval/citations, streaming, health/readiness, graph inspection, confirmation mode, and stage behavior. Sol High independently reran the final guest acceptance block and it passed. The first post-addition focused run caught a test-only `NameError` caused by guest-start assertions being placed in the neighboring test; the assertions were moved back and the next run passed.

Sol ran the full mock suite once with `.venv/bin/python -m pytest -q --tb=line`:
**12 failures**. Eleven match the Phase 1 baseline; the Phase 1 research-persistence
failure `tests/persistence/test_research_persistence.py::test_atomic_observation_is_attributed_offset_only_and_revision_aware` now
passes. The additional failure was
`tests/ui/test_streamlit_ui.py::test_coaching_style_keeps_existing_short_long_mapping`;
its source-text scan included unrelated guest-claim UI between the coaching
functions. The assertion was narrowed to `_select_coaching_style` and
`_persist_coaching_style`, and the isolated rerun passed (**1 test**). The full
suite was not rerun after this test-only correction, so the resulting full-suite
count is unverified. Sol's compileall, `sh -n scripts/start.sh`, and
`git diff --check` passed; `git diff --check` passed again after the narrow
correction and documentation update. No paid provider, live DSQL/AWS/Cognito/S3,
or deployment was used.

The mock API and Streamlit startup used `APP_DATA_DIR`, `APP_DATABASE_PATH`,
`APP_FILES_DIR`, `APP_WORKSPACES_DIR`, and `LECTURE_NOTES_DIR` below
`/private/tmp/phase7-guest-smoke`. `/api/v1/health` and `/api/v1/ready` each
returned HTTP 200; readiness reported development/mock/SQLite/local. Streamlit
reported its loopback URL and was stopped. The separate guest create/restart
loopback check was interrupted before returning evidence, so API restart
recovery via a running server is **not verified**. Initial sandbox bind attempts
failed with `PermissionError: [Errno 1] operation not permitted`; escalation
allowed the API/UI startup and health/readiness check. Both started processes
were stopped. `command -v caddy` returned no path, so no Caddy guest browser flow
or desktop/390 px guest UI check was completed. The initial test-only NameError
is resolved; no Phase 7 test failure remains.

**Migration, flag state, and rollback:** no developer DB or DSQL schema was
migrated. `.env.example` and `compose.prod.yaml` both retain
`GUEST_ACCESS_ENABLED=false`. Setting the flag off disables guest routes while
retaining session/workspace data for a later safe re-enable. Rollback is to
leave that flag off or revert only Phase 7 tests/docs; keep additive guest
columns and persisted rows. No live infrastructure or deployment action
occurred.

**Known gaps:** loopback guest persistence across process restart; Caddy route
behavior; real Cognito and S3 permissions; desktop/mobile browser validation.
These are outstanding because the loopback restart command did not complete and
Caddy is unavailable. DSQL evidence remains limited to existing fake/schema
planning tests; no DSQL CLI or connection was used. Expected and actual results
therefore match for the focused mock security/compatibility tests, migration,
flag retention, and health/readiness startup smoke, but Phase 7's full release
acceptance is **partial**. Do not treat the 12-failure full-suite observation as
the post-correction suite result.

**Next exact action:** user review and acceptance of these documented Phase 7
gaps, or arrange Caddy and a successful loopback guest create/restart check to
complete them. Keep the production flag off and retain this handoff until all
phases are accepted.

## Post-Phase-7 local validation (2026-09-26)

The Caddy and loopback restart gaps above were closed in a later local mock
check. In a separate Playwright browser, first visit opened the chatbot as
Guest without the welcome gate. A sent chat received a mock coaching reply;
reload preserved both messages, and New chat plus recent-chat selection restored
the conversation. The sidebar sign-in button reached Cognito Managed Login.
At 390 px, opening the navigation menu showed Guest and the sign-in button.
The browser reported zero errors and 18 Chromium/Streamlit feature/iframe
warnings. AppTest verifies that a signed-in profile shows the account name and
omits the guest sign-in button; a real Cognito login was not attempted.

An isolated FastAPI process and SQLite database under `/private/tmp` created a
guest and notebook, stopped and restarted, then resolved the same browser
cookie, owner, and notebook. Guest reuse and HttpOnly renewal passed after
restart. Local Caddy returned 200 for health, 401 for the allowed renewal route
without a cookie, and 404 for the blocked general notebook API route. Both
Caddyfiles validated. The running student app was not restarted for this test.

Sol High's full mock suite collected 2,195 tests: **2,183 passed, 12 failed**.
Eleven failures are the remaining recorded Phase 1 baseline; the former
research-persistence failure and corrected coaching-style assertion pass. The
extra rate-limit same-key concurrency assertion failed only in the full run
and passed alone. The focused guest/auth/claim/professor/persistence/deployment
block passed **231/231** with the known Compose assertion deselected. Compileall,
shell syntax, and diff checks passed. Production `GUEST_ACCESS_ENABLED=false`
is unchanged. Real Cognito login/claim and DSQL/S3 permissions still require
environment-specific validation before any production enablement.
