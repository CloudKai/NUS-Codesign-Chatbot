# Production AWS deployment (stateless EC2 + ECR)

This document describes the image-based production topology for
`cde2300chatbot.duckdns.org`. It does **not** delete local `data/` or migrate
existing SQLite/uploads automatically.

**A live DSQL + S3 smoke test is still required before declaring the migration
complete.** Passing unit tests alone is not sufficient.

## Topology

```text
Students
  → https://cde2300chatbot.duckdns.org
  → Caddy (TLS terminate, public auth/health only)
  → T4g.small EC2 / Docker
       ├── app (prebuilt linux/arm64 image from ECR)
       │     ├── Streamlit :8501 (internal)
       │     └── FastAPI :8000 (internal)
       │           ├── Cognito
       │           ├── Aurora DSQL (structured state, role co_design_app)
       │           ├── S3 (user uploads)
       │           └── Bedrock (us-west-2)
       └── DuckDNS cron on the host (not in the app container)
```

Persistent state lives in **Aurora DSQL** and **S3**. Replacing the app
container must not destroy conversations, progress, or uploads.

## Production data model

```text
users
 └── notebooks
      ├── messages
      └── sources
           ├── object_key → S3 raw/content object
           └── extracted_text_key → S3 derived text

oauth_login_states  (pre-auth, one-time, independent)
```

Cognito owns the browser session. The refresh token uses a Secure, HttpOnly,
SameSite=Lax cookie scoped to ``Path=/api/v1/auth``; the short-lived ID token
uses a Secure, HttpOnly, SameSite=Lax cookie at ``Path=/`` so server-rendered
Streamlit can ask FastAPI to validate it. When the ID token expires, Streamlit
redirects the browser through ``/api/v1/auth/refresh``; only the browser and
FastAPI handle the refresh cookie. There is **no** ``app_sessions`` table.
Refresh tokens are never sent to Streamlit, stored in DSQL, returned in API
JSON, logged, or exposed to browser JavaScript.

```text
Browser → Cognito Managed Login → authorization code + PKCE → FastAPI callback
        → Secure HttpOnly refresh cookie → Cognito refresh
        → verified Cognito sub → DSQL application user
```

Cognito is authoritative for credentials, refresh-token validity, revocation,
and login lifetime. DSQL owns only application identity/profile and learning
data; S3 owns uploaded bytes and extracted large text.

Local SQLite uses the same logical model. Existing developer
``data/*.sqlite3`` files are **not** auto-migrated; create a fresh DB or use
``scripts/init_db.py --database …`` for a new file.

**Do not run ``scripts/init_dsql.py`` against the real cluster until this
branch has been reviewed and the local suite is green.** A prior draft that
included ``app_sessions`` must not be treated as the production schema.

| Table | Purpose |
|---|---|
| `users` | Cognito-bound profile + `preferences_text` (+ retained `role` / `identifier`) |
| `oauth_login_states` | One-time OAuth state + PKCE verifier |
| `notebooks` | Conversation root; `current_stage`, `progress_text`, `settings_text` |
| `messages` | Chat history, assessments, stage decisions |
| `sources` | Source metadata and S3 object keys (not file bytes) |

Removed from production: `app_sessions`, `threads`, `steps`, `folders`,
`thread_folders`, `feedbacks`, `model_turns`, `openai_thread_state`,
`notebook_sources`, `phase_transitions`.

`sources.selected` is authoritative: application queries filter unselected
sources before loading extracted text or invoking the coach/provider. Uploaded
bytes and extracted text use generated notebook-scoped S3 keys. Notebook S3
prefix deletion runs only after the DSQL transaction commits, and per-object
`DeleteObjects` errors fail the operation rather than being counted as removed.

## Local vs production storage

| Concern | Local / tests | Production |
|---|---|---|
| Structured state | SQLite (`DATABASE_PROVIDER=sqlite`) | Aurora DSQL (`dsql`) |
| Uploads | Local files (`FILE_STORAGE_PROVIDER=local`) | S3 (`s3`) |
| Compose file | `compose.yaml` (build + `./data` mount) | `compose.prod.yaml` (image, no data mount) |
| DB role | n/a | Runtime `DSQL_USER=co_design_app` (never `admin`) |
| Secrets | `.env` + `.streamlit/secrets.toml` (never in Git) | Host files + IAM role |

## DSQL security model

| Role | Purpose | Privileges |
|---|---|---|
| `admin` | Schema migration only (`scripts/init_dsql.py`) | CREATE / ALTER / INDEX / GRANT |
| `co_design_app` | Application runtime | SELECT / INSERT / UPDATE / DELETE only |

- Runtime tokens use IAM **DbConnect** (`generate_db_connect_auth_token`), not
  DbConnectAdmin.
- Map the EC2 instance IAM role to `co_design_app` in IAM (do not commit ARNs).
- Application startup must **not** run DDL.

### Admin schema bootstrap

Aurora DSQL allows **one DDL statement per transaction**. Indexes use
``CREATE INDEX ASYNC`` / ``CREATE UNIQUE INDEX ASYNC`` (no partial ``WHERE``
predicates). Apply schema with:

```sh
DSQL_ENDPOINT=<hostname> AWS_REGION=us-west-2 \
  .venv/bin/python scripts/init_dsql.py --admin-user admin
```

The script authenticates with **DbConnectAdmin**
(``generate_db_connect_admin_auth_token``), commits each DDL alone, and for
async indexes waits on ``sys.wait_for_job`` only when a new ``job_id`` is
returned (``IF NOT EXISTS`` re-runs that find an existing index skip wait).
Runtime never uses DbConnectAdmin.
Useful secondary indexes (ASYNC): ``users(cognito_sub)``,
``notebooks(user_id, updated_at)``, ``messages(notebook_id, created_at, id)``,
``messages(notebook_id, decision_status, created_at)``,
``sources(notebook_id, created_at, id)``.
Then grant runtime privileges (run as admin; no account ARNs in Git):

```sql
GRANT USAGE ON SCHEMA public TO co_design_app;
GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO co_design_app;
```

## Build and push (CI or developer machine)

```sh
export AWS_REGION=us-west-2
export ECR_REGISTRY="<account>.dkr.ecr.us-west-2.amazonaws.com"
export APP_IMAGE="${ECR_REGISTRY}/cde2300-chatbot:<git-sha>"

aws ecr get-login-password --region "${AWS_REGION}" \
  | docker login --username AWS --password-stdin "${ECR_REGISTRY}"

docker buildx build \
  --platform linux/arm64 \
  -t "${APP_IMAGE}" \
  --push .
```

Do not bake `.env`, secrets, `data/`, SQLite files, or AWS keys into the image
(`.dockerignore` enforces this).

## EC2 refresh

On the host (IAM role preferred):

```sh
export APP_IMAGE="<account>.dkr.ecr.us-west-2.amazonaws.com/cde2300-chatbot:<tag>"
export ECR_REGISTRY="<account>.dkr.ecr.us-west-2.amazonaws.com"
export AWS_REGION=us-west-2
sh scripts/deploy_ecr.sh
```

Required production `.env` keys (host-only):

- `DATABASE_PROVIDER=dsql`
- `FILE_STORAGE_PROVIDER=s3`
- `AWS_REGION=us-west-2`
- `DSQL_ENDPOINT=<hostname>`
- `DSQL_USER=co_design_app`
- `USER_UPLOADS_BUCKET=<bucket>`
- Cognito + public URL values already set in `compose.prod.yaml`

## Live smoke test (required before cutover)

1. Admin runs `scripts/init_dsql.py --admin-user admin`.
2. Admin grants table privileges to `co_design_app` (SQL above).
3. EC2 IAM role mapped to `co_design_app` (DbConnect).
4. Host `.env` has `DSQL_USER=co_design_app` (not admin).
5. App connects via IAM DbConnect token.
6. Create Cognito user/session; create notebook; save/reload messages.
7. Upload a file (lands in S3); preview/download succeeds.
8. Restart or remove/recreate the app container (no `/app/data` mount).
9. Login again: notebook + messages still present; S3 upload still
   previews/downloads.
10. Delete notebook: DSQL rows and S3 objects under the thread prefix are gone.

Until this smoke sequence passes against real DSQL/S3 in `us-west-2`, the
migration is **not** complete.

## DuckDNS (host)

Install `scripts/host/duck.sh` under `/home/ubuntu/duckdns/` with a mode-600
`duck.env` containing `DUCKDNS_TOKEN` (see `duck.env.example`). Cron:

```cron
*/5 * * * * /home/ubuntu/duckdns/duck.sh >/dev/null 2>&1
```

Application startup must not depend on DuckDNS success.

## IAM role permissions (EC2)

Grant least privilege for:

- `ecr:GetAuthorizationToken` + repository pull
- Aurora DSQL DbConnect for `co_design_app` (not admin)
- S3 read/write/delete on the uploads bucket prefix
- Bedrock invoke (existing model access)
- Optional CloudWatch logs

Do **not** place long-lived AWS access keys in `.env`.

## Manual AWS Console steps still required

1. Create/confirm Aurora DSQL cluster in `us-west-2` and note the endpoint.
2. Create the S3 uploads bucket in `us-west-2` (block public access).
3. Create ECR repository and push the first `linux/arm64` image.
4. Attach the EC2 instance profile; map it to DB role `co_design_app`.
5. Run `scripts/init_dsql.py` as admin, then GRANT runtime privileges.
6. Confirm Cognito callback remains
   `https://cde2300chatbot.duckdns.org/api/v1/auth/callback`.
7. In the Cognito app client, set **Refresh token expiration** to approximately
   **30 days** and keep token revocation enabled. This setting, not an
   application DB timeout, controls long-lived login duration.
8. Confirm authorization-code grant and the `openid email profile` scopes are
   enabled. Keep the app-client secret only in the host secrets configuration.
9. Pass the live smoke sequence above, then cut over DuckDNS.

## Aurora DSQL assumptions

- PostgreSQL wire protocol via `psycopg`
- One DDL statement per transaction (admin bootstrap only)
- No foreign keys / ON DELETE CASCADE — child rows deleted in application code
- JSON-shaped fields stored as TEXT
- IAM DbConnect tokens for `co_design_app` (no permanent DB password)
- OCC serialization failures (SQLSTATE 40001) retry the whole DB unit of work
- Do not assume every PostgreSQL feature works (no temp tables, limited DDL)

## Before removing the old EC2 `/app/data` volume

1. Confirm production Compose uses DSQL + S3 and no `./data` mount.
2. Migrate or accept loss of any SQLite-only history (manual, approved).
3. Verify the live smoke sequence (including container replace).
4. Keep local `data/` for development unless separately instructed to delete it.
