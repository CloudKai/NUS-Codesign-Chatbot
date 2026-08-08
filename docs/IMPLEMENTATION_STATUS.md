# Implementation status

## Current phase

**Cognito-owned browser session + five-table persistence cleanup**

Branch ``Production-RemoveData``. Preserved the uncommitted notebook/message/source
refactor and replaced opaque FastAPI ``app_sessions`` with Cognito refresh +
ID-token HttpOnly cookies.

```text
users
 └── notebooks
      ├── messages
      └── sources → S3 object keys / extracted text keys

oauth_login_states  (pre-auth, transient)

Cognito refresh token → HttpOnly cookie (Path=/api/v1/auth)
Cognito ID token      → short-lived HttpOnly cookie (Path=/)
```

**Do not initialize the real Aurora DSQL cluster until this branch is reviewed
and the local suite stays green.** Local `data/` was not migrated or deleted.

### What changed (auth)

- Callback returns verified identity plus refresh/ID tokens for cookies only.
- ``/auth/me`` validates the ID cookie, falls back to Cognito refresh, looks up
  exact ``sub``, sets a refreshed ID cookie, returns no tokens.
- When the short-lived ID cookie expires, Streamlit redirects the browser to
  ``/api/v1/auth/refresh``. The browser attaches the auth-scoped refresh cookie;
  FastAPI refreshes Cognito and returns to Streamlit. The refresh token never
  reaches Streamlit or browser JavaScript.
- Refresh failure clears both cookies and returns 401.
- Logout best-effort revokes the refresh token and always clears cookies.
- Removed ``AppSessionService``, ``app_sessions`` table/methods, and opaque
  session token generators (OAuth state/PKCE retained).
- Caddy exposes ``/api/v1/auth/me`` and ``/api/v1/auth/refresh``.

### What changed (persistence hardening)

- Preserved runtime DSQL IAM ``DbConnect`` as ``co_design_app``, explicit
  admin-only ``DbConnectAdmin`` bootstrap, whole-operation OCC retries, and the
  no-runtime-DDL boundary.
- Replaced OAuth-specific ``INSERT OR REPLACE`` adaptation with an explicit
  ``oauth_login_states ... ON CONFLICT (state) DO UPDATE`` query. The DSQL SQL
  adapter now rejects ``INSERT OR REPLACE`` instead of accumulating
  table-specific rewrites.
- Renamed object-key inputs/prefixes from thread terminology to notebook
  terminology while retaining generated UUID isolation and filename
  sanitization.
- Moved extracted-text writes out of ``StudentStore.add_source``. Source
  services write deterministic ``extracted_text_key`` objects before invoking
  the retryable metadata transaction, so OCC retries never repeat S3 writes.
- Removed legacy no-op ``get_state``, ``save_state``, and ``record_turn``
  persistence APIs. Canonical conversation history now comes directly from
  ``messages``.
- ``S3FileStorage.delete_prefix`` now raises on per-object ``DeleteObjects``
  errors. Missing-object semantics remain narrow; bucket, permission,
  credential, and other failures propagate.
- ``sources.selected`` remains persisted and is filtered in SQL before source
  text is loaded or sent to the coach/provider.

### Intentional compatibility names

- Public ``/api/v1/threads`` routes and ``thread_id`` service method arguments
  remain temporarily for Streamlit/API compatibility. They operate only on the
  ``notebooks`` table.
- Public ``phase-transitions`` routes remain for the existing confirmation UI;
  recommendation state is stored on ``messages``, not a
  ``phase_transitions`` table.
- Legacy local ``files/threads`` paths remain readable so existing developer
  uploads are not deleted. New object-storage keys use notebook terminology.

### Files changed (this auth phase)

- Added: ``backend/cognito_cookies.py``
- Rewrote: ``backend/auth_oidc.py``, ``backend/auth_routes.py``,
  ``backend/session_tokens.py``, ``tests/test_app_sessions.py``
- Deleted: ``backend/app_sessions.py``
- Updated: ``backend/settings.py``, ``backend/api.py``, ``backend/api_client.py``,
  ``backend/student_store.py``, ``backend/persistence/dsql_schema.py``,
  ``backend/persistence/dsql_student_store.py``, ``ui/auth_gate.py``,
  ``.env.example``, ``compose.yaml``, ``compose.prod.yaml``, ``Caddyfile``,
  auth-related tests, ``docs/deploy/AWS_STATELESS_EC2.md``, this status file

### Commands run and results

- ``.venv/bin/python -m pytest -q`` → **200 passed**
- Focused persistence/storage/API regression suite → **76 passed**
- ``PYTHONPYCACHEPREFIX=/private/tmp/co-design-pycache .venv/bin/python -m
  compileall -q backend ui streamlit_app.py`` → exit 0
- Local and production ``docker compose ... config --quiet`` → exit 0
- No live Cognito / AWS / paid model calls
- Not committed

### Known risks

- Refresh requests are serialized only within one FastAPI process. Cognito
  remains authoritative across multiple workers/instances; deployments using
  refresh-token rotation should verify concurrent-tab behavior in a live smoke
  test.
- GET logout can be triggered by a cross-site top-level navigation under
  ``SameSite=Lax``. Its only effect is idempotent sign-out; other state-changing
  APIs do not receive the auth-scoped refresh cookie.

### Next exact action

1. Review Cognito cookie-session + five-table schema locally.
2. Confirm Cognito app client refresh-token validity (~30d) matches ops intent.
3. Only then run ``scripts/init_dsql.py --admin-user admin`` against us-west-2.
4. GRANT privileges to ``co_design_app``; map EC2 IAM role to that DB user.
5. Deploy ``compose.prod.yaml`` and run the live smoke sequence in
   ``docs/deploy/AWS_STATELESS_EC2.md``.

## Previous completed work

**Six-table production data model (local + DSQL schema aligned)** — superseded
for auth: ``app_sessions`` removed; notebooks/messages/sources/users/oauth remain.

**DSQL bootstrap idempotency + redundant index cleanup**

**DSQL admin token + ASYNC index bootstrap fixes**

**DSQL/S3 production adapter hardening**

**AWS stateless EC2 migration scaffolding**
