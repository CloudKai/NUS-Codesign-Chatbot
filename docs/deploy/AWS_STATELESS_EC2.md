# Production AWS deployment (stateless EC2 + ECR)

This document describes the image-based production topology served through
`d1sxfuoybzedj5.cloudfront.net`. It does **not** delete local `data/` or
migrate existing SQLite/uploads automatically.

**A live DSQL + S3 smoke test is still required before declaring the migration
complete.** Passing unit tests alone is not sufficient.

## Topology

```text
Students
  → https://d1sxfuoybzedj5.cloudfront.net
  → CloudFront (viewer TLS, caching disabled, WebSocket forwarding)
  → T4g.small EC2 :80 / Docker
       ├── Caddy (HTTP origin; public auth/health allow-list)
       ├── app (prebuilt linux/arm64 image from ECR)
       │     ├── Streamlit :8501 (internal)
       │     └── FastAPI :8000 (internal)
       │           ├── Cognito
       │           ├── Aurora DSQL (structured state, role co_design_app)
       │           ├── S3 (user uploads under users/; shared course/ keys)
       │           └── AgentCore Runtime (production coach) or OpenAI / Bedrock Converse
```

Persistent state lives in **Aurora DSQL** and **S3**. Replacing the app
container must not destroy conversations, progress, or uploads.
Production coaching uses `MODEL_PROVIDER=agentcore` against runtime
`NUSCodesignChatbot_chatbot_harnessAgent-6ncEO79sD7` (qualifier `DEFAULT`,
currently liveVersion 19).
Invokes are stateless; Aurora DSQL `messages` is the only durable transcript.
The published runtime source of truth is `agentcore_runtime/` in this
repository (Q&A, Coaching, and Formative Review specialists). Do not treat
AgentCore session memory, DynamoDB, or a JSON file as chat history.
Direct Bedrock Converse remains a fallback. Course PDFs live in shared
`course/lectureNotes/` and `course/readings/` on the course-content bucket;
student uploads stay under `users/`. `COURSE_MATERIAL_SYNC_ENABLED=true`
exposes those shared objects as virtual catalog sources in the UI and does
not copy PDFs into the uploads prefix or duplicate them into notebook DSQL
source rows. Coaching does not call
`RetrieveAndGenerate`. The AgentCore coaching specialist must keep zero KB
tools so `[S#]` citations stay notebook-selected. Shared course files are
virtual catalog sources in the UI; they are not copied into each notebook and
do not rely on local `extractedText`. Production with shared course sync
**requires** `KNOWLEDGE_BASE_ID` so official materials retrieve through
Bedrock `Retrieve` mapped onto those `[S#]` labels. Student uploads stay on
local chunks. An empty Knowledge Base id must not silently rank placeholder
text as course evidence.

During pre-AgentCore testing, student-upload RAG is still functional: extracted
text is read from the selected S3-backed sources, chunked and ranked in the app
container for each turn, and passed to the provider through the same bounded
prompt contract.

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
sources before loading extracted text or invoking the coach/provider. New
uploads use separate notebook-scoped key namespaces:
`users/<user>/notebooks/<notebook>/sources/<source>/raw/<filename>` and
`.../derived/extracted.txt`. This prevents a raw file named `extracted.txt`
from being overwritten by derived text. Notebook S3 prefix deletion runs only
after the DSQL transaction commits, and per-object `DeleteObjects` errors fail
the operation rather than being counted as removed.

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
async indexes runs ``CALL sys.wait_for_job(?)`` on a dedicated admin connection
with autocommit enabled, only when a new ``job_id`` is returned. The procedure
cannot run in a transaction block; ``IF NOT EXISTS`` re-runs that find an
existing index return no job and skip the call.
Runtime never uses DbConnectAdmin.

#### CloudShell / laptop init_dsql checklist

Use this whenever you pull a newer bootstrap script and re-run admin migration
from **AWS CloudShell** (or any host whose system CA / IPv6 path is flaky).

**Symptoms this checklist fixes**

| Error | Cause |
|---|---|
| `SSL error: certificate verify failed` | System trust store lacks Amazon Root CA 1 |
| `Cannot assign requested address` on an `2600:…` host | CloudShell cannot open DSQL’s IPv6 AAAA |
| Traceback still shows `sslrootcert="system"` / no `hostaddr` | Wrong clone or branch; old script still on disk |
| `fatal: Need to specify how to reconcile divergent branches` | Local and `origin` diverged; no pull strategy set |

**1. Use one clone, on the branch that has the fix**

CloudShell sometimes has a nested tree
(`~/NUS-Codesign-Chatbot/NUS-Codesign-Chatbot/`). Always confirm:

```sh
pwd
git rev-parse --show-toplevel
git fetch origin
git checkout Production-AddEditFunction   # or the branch that carries the fix
git reset --hard origin/Production-AddEditFunction
git log -1 --oneline
grep -n "_prefer_ipv4_hostaddr\|connect_kwargs\|DSQL_SSLROOTCERT" scripts/init_dsql.py | head
```

Prefer `git pull --ff-only origin <branch>` when the local branch can fast-forward.
Do **not** set `git config pull.rebase` unless you intentionally want a repo-wide
default. `reset --hard` discards **local-only** commits on that clone.

Confirm the script prefers IPv4 (`_prefer_ipv4_hostaddr` / `hostaddr`) and reads
`settings.dsql_sslrootcert` (env ``DSQL_SSLROOTCERT``).

**2. Point TLS at Amazon Root CA 1**

```sh
# once per CloudShell home (persist across sessions in $HOME)
curl -fsSL -o "$HOME/AmazonRootCA1.pem" \
  https://www.amazontrust.com/repository/AmazonRootCA1.pem
export DSQL_SSLROOTCERT="$HOME/AmazonRootCA1.pem"
test -f "$DSQL_SSLROOTCERT" && echo "cert OK"
```

`/tmp/AmazonRootCA1.pem` is easy to lose when the session recycles; prefer
`$HOME`.

**3. Env + migrate**

```sh
# IAM identity must be allowed DbConnectAdmin on the cluster
export AWS_REGION="${AWS_REGION:-us-west-2}"
export DSQL_ENDPOINT="<cluster-hostname>.dsql.${AWS_REGION}.on.aws"
export DSQL_SSLROOTCERT="${DSQL_SSLROOTCERT:-$HOME/AmazonRootCA1.pem}"

cd "$(git rev-parse --show-toplevel)"
source .venv/bin/activate   # create/install deps first if needed
python scripts/init_dsql.py \
  --endpoint "$DSQL_ENDPOINT" \
  --region "$AWS_REGION" \
  --admin-user admin
```

Then GRANT runtime privileges as admin (see SQL below). Never run this script
as `co_design_app`, and never from application startup.

**4. Quick smoke if connect still fails**

```sh
python - <<'PY'
import os, socket
import psycopg
from backend.persistence.dsql_connection import generate_dsql_admin_auth_token
from backend.settings import settings

endpoint = os.environ["DSQL_ENDPOINT"]
region = os.environ.get("AWS_REGION", "us-west-2")
cert = os.environ.get("DSQL_SSLROOTCERT") or settings.dsql_sslrootcert
infos = socket.getaddrinfo(endpoint, 5432, socket.AF_INET, socket.SOCK_STREAM)
hostaddr = infos[0][4][0]
token = generate_dsql_admin_auth_token(endpoint=endpoint, region=region)
conn = psycopg.connect(
    host=endpoint, hostaddr=hostaddr, port=5432, dbname="postgres",
    user="admin", password=token, sslmode="verify-full", sslrootcert=cert,
)
print("ok", conn.info.host, hostaddr, "sslrootcert=", cert)
conn.close()
PY
```
Useful secondary indexes (ASYNC): ``users(identifier)``, ``users(cognito_sub)``,
``notebooks(user_id, updated_at)``, ``messages(notebook_id, created_at, id)``,
``messages(notebook_id, decision_status, created_at)``,
``sources(notebook_id, created_at, id)``.
Then grant runtime privileges (run as admin; no account ARNs in Git):

```sql
GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO co_design_app;
```

#### Existing clusters: append-only conversation revisions

Fresh ``init_dsql.py`` runs include ``notebooks.conversation_revision`` plus
the three message revision columns
(``messages.conversation_revision``, ``messages.previous_message_id``,
``messages.superseded_at_revision``). **App startup never issues DDL.** Runtime
role ``co_design_app`` must never perform DDL. Prefer re-running
``scripts/init_dsql.py`` as admin (DbConnectAdmin): it inspects the catalog,
adds only missing objects, and commits **one DDL statement per transaction**,
then waits on any new ASYNC index jobs.

Before deploying application code that writes append-only revisions, confirm
the notebook CAS column exists (**prerequisite**), then the three message
columns. Manual admin path when not using ``init_dsql.py``:

Aurora DSQL ``ALTER TABLE ADD COLUMN`` accepts **only** a name and type — not
``NOT NULL`` or ``DEFAULT`` in the same statement (error:
``ALTER TABLE ADD COLUMN with constraint not supported``).

**Backup / rollback caution:** take a cluster snapshot or export before ALTER.
Prefer forward-fix + application code revert over ``DROP COLUMN`` on live
student data. Additive columns leave historical message content intact; do not
delete turns as part of migration.

Inspect catalog (admin):

```sql
SELECT table_name, column_name
FROM information_schema.columns
WHERE table_schema = 'public'
  AND (
    (table_name = 'notebooks' AND column_name = 'conversation_revision')
    OR (
      table_name = 'messages'
      AND column_name IN (
        'conversation_revision',
        'previous_message_id',
        'superseded_at_revision'
      )
    )
  )
ORDER BY table_name, column_name;
```

Notebook revision (prerequisite) — separate commits per statement. Re-run
safely: existence alone does **not** mean DEFAULT/backfill finished.

```sql
ALTER TABLE notebooks
  ADD COLUMN IF NOT EXISTS conversation_revision INTEGER;
```

```sql
ALTER TABLE notebooks
  ALTER COLUMN conversation_revision SET DEFAULT 0;
```

Prefer ``scripts/init_dsql.py`` (admin) which inspects
``information_schema.columns`` (name + ``column_default``), repairs missing
DEFAULT 0, then batch-backfills NULLs (1000 rows/transaction) for both
``notebooks`` and ``messages``. Do **not** rely on one unbounded
``UPDATE ... WHERE conversation_revision IS NULL`` on large tables.

Manual single-statement backfill (small clusters only):

```sql
UPDATE notebooks
SET conversation_revision = 0
WHERE conversation_revision IS NULL;
```

Message revision columns — add only missing ones; one DDL per transaction:

```sql
ALTER TABLE messages
  ADD COLUMN IF NOT EXISTS conversation_revision INTEGER;
```

```sql
ALTER TABLE messages
  ALTER COLUMN conversation_revision SET DEFAULT 0;
```

```sql
ALTER TABLE messages
  ADD COLUMN IF NOT EXISTS previous_message_id TEXT;
```

```sql
ALTER TABLE messages
  ADD COLUMN IF NOT EXISTS superseded_at_revision INTEGER;
```

Backfill / defaults (DML after DDL) — use batched updates via
``scripts/init_dsql.py`` on large tables. Small-cluster manual form:

```sql
UPDATE messages
SET conversation_revision = 0
WHERE conversation_revision IS NULL;
```

Leave ``previous_message_id`` and ``superseded_at_revision`` NULL for existing
rows (active at notebook revision 0). Fresh ``CREATE TABLE`` retains
``INTEGER NOT NULL DEFAULT 0`` for both revision counters. The application
treats null notebook/message revision as ``0`` (``COALESCE`` / ``or 0``) in
Python, but SQL CAS ``WHERE conversation_revision = 0`` does **not** match
SQL NULL — backfill before cutover. Student UI shows
``Conversation {notebook.conversation_revision + 1:02d}`` (stored ``0`` →
Conversation 01); do not renumber stored values.

**PART 1 (“only welcome”) — code inspection, not live-verified:** the UI
welcome seed persists through workspace ``add_message`` without the coach
workflow. At baseline ``6b54923``, coach persistence additionally used notebook
revision CAS, so an older cluster missing
``notebooks.conversation_revision`` could accept the independently committed
welcome while real turn transactions rolled back. The new application also
reads/writes all message revision columns from welcome and normal inserts; if
those columns are missing, even welcome seeding may fail. This is why the full
migration must precede the image deployment. Secondary diagnostics: wrong
``DSQL_ENDPOINT``, database name, owner/runtime role (must be
``co_design_app``), or Compose/``.env`` mismatch — check after confirming
columns exist. Do not claim live DSQL verification from docs alone.

**Assessment fields:** user rows and the fixed coach welcome keep
``assessment_text`` NULL; assessed coach assistant replies store
``assessment_text`` JSON. NULL on welcome/user is expected.

SQLite local DBs add missing notebook/message revision columns on open once
the backend migration lands. Back up the SQLite file before first startup;
older application code ignores additive columns, so local rollback is a code
rollback without deleting revision history.
Do not grant ``USAGE`` on the built-in ``public`` schema. Aurora DSQL manages
that schema as a system entity and rejects that grant. The object-level table
grant above is the required runtime grant while application tables remain in
``public``.

## Build and push (CI or developer machine)

```sh
export AWS_REGION=us-west-2
export ECR_REGISTRY="<account>.dkr.ecr.us-west-2.amazonaws.com"
export APP_IMAGE="${ECR_REGISTRY}/cde2300-chatbot:<git-sha>"

aws ecr get-login-password --region "${AWS_REGION}" \
  | docker login --username AWS --password-stdin "${ECR_REGISTRY}"

docker buildx build \
  --platform linux/arm64 \
  --build-arg GIT_SHA="$(git rev-parse HEAD)" \
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
- `COURSE_MATERIALS_BUCKET=cde2300-course-content-s3`
- `COURSE_MATERIALS_PREFIX=course/`
- `MODEL_PROVIDER=agentcore`
- `AGENTCORE_RUNTIME_ARN=arn:aws:bedrock-agentcore:us-west-2:355604674280:runtime/NUSCodesignChatbot_chatbot_harnessAgent-6ncEO79sD7`
- `AGENTCORE_QUALIFIER=DEFAULT`
- `AGENTCORE_MODEL_PROVIDER=bedrock`
- `AGENTCORE_MODEL_ID=global.anthropic.claude-haiku-4-5-20251001-v1:0`
- `AGENTCORE_MODEL_REGION=us-west-2`
- `ROUTER_MODEL_PROVIDER=bedrock`
- `ROUTER_MODEL_ID=global.anthropic.claude-haiku-4-5-20251001-v1:0`
- `QA_MODEL_PROVIDER=bedrock`
- `QA_MODEL_ID=global.anthropic.claude-haiku-4-5-20251001-v1:0`
- `COACHING_MODEL_PROVIDER=bedrock`
- `COACHING_MODEL_ID=global.anthropic.claude-haiku-4-5-20251001-v1:0`
- `REVIEW_INCREMENTAL_MODEL_PROVIDER=bedrock`
- `REVIEW_INCREMENTAL_MODEL_ID=global.anthropic.claude-haiku-4-5-20251001-v1:0`
- `REVIEW_DEEP_MODEL_PROVIDER=bedrock`
- `REVIEW_DEEP_MODEL_ID=global.anthropic.claude-sonnet-4-6`
- `ROUTER_MIN_CONFIDENCE=0.60`
- `DEEP_REVIEW_INTERVAL_TURNS=3`

Periodic Deep Review means every N newly executed, successful Coaching
turns since the previous successfully persisted Deep Review. It is
turn-based rather than time-based because it represents new learning
evidence, not elapsed time. Opening the Review tab does not invoke a
model. FastAPI/DSQL remain authoritative; AgentCore never writes stage
state.

- `GUARDRAIL_ID=<configured guardrail>`
- `GUARDRAIL_VERSION=3`
- `KNOWLEDGE_BASE_ID=<configured KB id>` (required when shared course sync is on)
- `KNOWLEDGE_BASE_TYPE=MANAGED` (Compose sets this; `JUQNP8AZAZ` is MANAGED)
- `KNOWLEDGE_BASE_REGION=us-west-2` (optional; falls back to `AWS_REGION`)
- `PUBLIC_ORIGIN=https://<cloudfront-domain>` (Compose interpolates browser URLs)
- Cognito client values in `.streamlit/secrets.toml` (host-only)

`/api/v1/ready` checks non-secret Cognito configuration locally (it does not
perform OIDC discovery), queries all five required DSQL tables, and performs a
bounded read-only S3 list against the `users/` prefix. A missing schema, table
grant, bucket, wrong region, or Cognito callback configuration therefore
keeps the app unhealthy instead of failing on the first student action. In
production the Cognito callback must be HTTPS and end in
`/api/v1/auth/callback`.

The readiness endpoint is intentionally container-/host-internal: Caddy only
publishes `/api/v1/health`. Monitor `/api/v1/ready` from Docker's healthcheck
or a host-local monitor; never expose it as a public metrics endpoint.

The application writes compact JSON operational events to its normal container
logs: API route/method/status/latency and aggregate coach provider, selected
source, retrieval, citation, recommendation, and accepted/rejected stage
outcomes. These events omit prompts, source text, notebook/source/transition
IDs, emails, and tokens. Ship only those logs to CloudWatch (or another
protected log sink) with the normal retention policy.

### S3 uploads bucket (required before the live smoke)

Create a dedicated private bucket in `us-west-2`, enable Block Public Access,
and keep object ownership private to the account. The EC2 role needs bucket
list access and object access beneath `users/*`; no public ACL or
website hosting is used. Set only the bucket name in the host `.env`:

```dotenv
USER_UPLOADS_BUCKET=<private-bucket-name>
FILE_STORAGE_PROVIDER=s3
AWS_REGION=us-west-2
```

The application creates object prefixes automatically. Do not pre-create
folders and do not copy local course materials into the student-uploads
`users/` prefix. Shared Lecture Notes and Readings live on
`cde2300-course-content-s3` under `course/lectureNotes/` and
`course/readings/`. Set `COURSE_MATERIALS_BUCKET` to that bucket. The EC2 role
may `GetObject`/`ListBucket` on `course/*` and must not delete those objects.
Replace both bucket placeholders in this EC2 role policy before attaching it:

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Sid": "ListStudentUploads",
      "Effect": "Allow",
      "Action": "s3:ListBucket",
      "Resource": "arn:aws:s3:::<private-bucket-name>",
      "Condition": {
        "StringLike": {"s3:prefix": ["users", "users/*"]}
      }
    },
    {
      "Sid": "ManageStudentUploadObjects",
      "Effect": "Allow",
      "Action": ["s3:GetObject", "s3:PutObject", "s3:DeleteObject"],
      "Resource": "arn:aws:s3:::<private-bucket-name>/users/*"
    }
  ]
}
```

If the bucket uses a customer-managed KMS key, add only the corresponding KMS
permissions for that key; the default S3-managed encryption needs no KMS grant.

## Live smoke test (required before cutover)

Do **not** mark student cutover complete until every step below has been
executed against real Cognito / Aurora DSQL / S3 in `us-west-2`. Live-write
scripts require an explicit `--confirm-live` flag.

### Infrastructure prerequisites

1. Create/confirm Aurora DSQL in `us-west-2`.
2. Run admin schema initialization once (`scripts/init_dsql.py --admin-user admin`).
3. Grant `co_design_app` SELECT/INSERT/UPDATE/DELETE on application tables.
4. Verify the application runtime `.env` uses `DSQL_USER=co_design_app` (never admin)
   and cannot perform DDL.
5. Map the EC2 IAM instance profile to DSQL `DbConnect` for `co_design_app`.
6. Create the private uploads bucket; enable Block Public Access.
7. Attach least-privilege S3 list/read/write/delete for `users/*` only.
8. Configure Cognito callbacks, logout, scopes, refresh lifetime, and revocation.
9. Configure host-only production `.env` (`APP_ENV=production`, no secrets in Git).
10. Build and push a `linux/arm64` immutable image tag to ECR; deploy that exact tag.
11. Verify **internal** `/api/v1/ready` (Docker healthcheck / private network only).

### Guarded DSQL concurrency smoke

After separate approval for live writes:

```sh
DATABASE_PROVIDER=dsql DSQL_USER=co_design_app \
  .venv/bin/python scripts/smoke_dsql_idempotency.py \
  --confirm-live --identifier 'cognito:<sub>'
```

Uses two independent runtime connections and the deterministic mock provider.
Performs no DDL/S3/Bedrock/provider-paid calls; removes disposable rows in
`finally`.

### End-to-end product smoke (real Cognito users)

1. Cognito login.
2. Create notebook.
3. Send message / generate coach turn.
4. Upload source; preview source.
5. Confirm stage transition (recommend → student confirm).
6. Restart/remove/recreate the application container (no `/app/data` mount).
7. Log back in; confirm notebook, messages, progress, and source still exist.
8. Delete source/notebook; confirm S3 cleanup under the owner prefix.
9. Logout; confirm session invalidation (refresh rejected / auth cookies cleared).
10. Two distinct real users cannot read or mutate each other's notebooks/sources.
11. Simultaneous duplicate coach submission with the same idempotency key converges
    to one provider execution and one persisted turn.

Until this smoke sequence passes, the migration is **not** complete and the
application remains **READY FOR CONTROLLED PILOT** at best.

## CloudFront distribution and Caddy origin

Configure the distribution with HTTPS-only viewers (redirect HTTP to HTTPS),
an HTTP-only EC2 origin on port 80, all HTTP methods enabled, caching disabled,
and an origin request policy that forwards cookies, query strings, and the
headers required by Streamlit WebSockets and Cognito. The EC2 security group
must allow TCP 80 only from the AWS-managed CloudFront origin-facing prefix
list. Do not expose TCP 443 on the host; Caddy does not own production TLS.

## Edge route checks (CloudFront → Caddy)

CloudFront terminates viewer TLS. Caddy exposes only Cognito auth routes,
health, and Streamlit from the HTTP origin. Coaching/CRUD `/api/*` paths must
remain blocked at Caddy. Security headers (HSTS, nosniff, Referrer-Policy,
Permissions-Policy) are set in the site block and passed through CloudFront;
Content-Security-Policy is intentionally not configured.

From a laptop (replace the host if the domain changes):

```sh
# Public auth/health should reach FastAPI (expect 2xx/3xx/401/403 — not 404).
curl -sI https://d1sxfuoybzedj5.cloudfront.net/api/v1/health | head -n 1
curl -sI https://d1sxfuoybzedj5.cloudfront.net/api/v1/auth/me | head -n 1

# Coaching/CRUD must be blocked at Caddy (expect HTTP 404 Not Found).
curl -sI https://d1sxfuoybzedj5.cloudfront.net/api/v1/coach/turn | head -n 1
curl -sI https://d1sxfuoybzedj5.cloudfront.net/api/v1/threads | head -n 1
curl -sI https://d1sxfuoybzedj5.cloudfront.net/api/v1/ready | head -n 1
```

Readiness stays host-/container-internal via Docker healthcheck; do not publish
`/api/v1/ready` publicly.

## IAM role permissions (EC2)

Grant least privilege for:

- `ecr:GetAuthorizationToken` + repository pull
- Aurora DSQL DbConnect for `co_design_app` (not admin)
- S3 bucket list plus read/write/delete on the uploads bucket's
  `users/*` objects
- `s3:ListBucket` + `s3:GetObject` on the course-content bucket's `course/*`
  prefix only (no delete on `course/*`)
- Optional CloudWatch logs
- When `MODEL_PROVIDER=agentcore`: `bedrock-agentcore:InvokeAgentRuntime` on
  runtime `NUSCodesignChatbot_chatbot_harnessAgent-6ncEO79sD7` (and its
  `DEFAULT` endpoint)
- Bedrock Knowledge Base **Retrieve only** (never `RetrieveAndGenerate`) as
  documented below
- When `MODEL_PROVIDER=bedrock`: `bedrock:InvokeModel` and
  `bedrock:InvokeModelWithResponseStream` on the exact model or
  inference-profile ARN only (no `bedrock:*` admin)

Do **not** place long-lived AWS access keys in `.env`. Credentials must come
from the EC2 instance profile.

### AgentCore runtime execution role (Haiku / Sonnet Bedrock)

Haiku 4.5 and Sonnet 4.6 use `bedrock:InvokeModel` on the existing runtime
role. They do **not** use Bedrock Mantle.

Historical DEFAULT versions that ran GPT-5.6 Luna still needed
`bedrock-mantle:CreateInference` on this account's default Mantle project
and `bedrock-mantle:CallWithBearerToken`. Keep those statements on the
runtime role for rollback to v14–v17. Do not treat Mantle as the current
lightweight path.

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Sid": "BedrockMantleInference",
      "Effect": "Allow",
      "Action": "bedrock-mantle:CreateInference",
      "Resource": "arn:aws:bedrock-mantle:us-west-2:355604674280:project/default"
    },
    {
      "Sid": "BedrockMantleCallWithBearerToken",
      "Effect": "Allow",
      "Action": "bedrock-mantle:CallWithBearerToken",
      "Resource": "*"
    }
  ]
}
```

### Bedrock Knowledge Base Retrieve (required for shared course files)

Official AWS Knowledge Base permissions document that calling `Retrieve`
requires the IAM action `bedrock:Retrieve` on the knowledge-base resource
ARN. This application does **not** call `RetrieveAndGenerate`, so do not
grant that action to the EC2 role.

Replace the account and Knowledge Base id before attaching. Current
production Knowledge Base id is `JUQNP8AZAZ` in `us-west-2`:

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Sid": "BedrockKnowledgeBaseRetrieve",
      "Effect": "Allow",
      "Action": "bedrock:Retrieve",
      "Resource": "arn:aws:bedrock:us-west-2:355604674280:knowledge-base/JUQNP8AZAZ"
    }
  ]
}
```

`bedrock:GetKnowledgeBase` is optional for this adapter (it never calls
GetKnowledgeBase). The Knowledge Base **service role** that Bedrock uses to
read S3 during ingestion is separate from the EC2 instance role; do not
confuse the two.

If production logs `course_retrieval_access_denied`, this statement is the
first thing to attach and verify on the instance profile.

### Knowledge Base Retrieve diagnostic

Dry-run (no AWS):

```sh
PYTHONPATH=. python scripts/diagnostics/check_knowledge_base_retrieve.py --dry-run
```

One approved live Retrieve (from EC2, after `aws sts get-caller-identity`):

```sh
docker compose -f compose.prod.yaml exec app \
  python scripts/diagnostics/check_knowledge_base_retrieve.py \
  --i-approve-live-bedrock --max-requests 2 \
  --query "week 1 introduction innovation"
```

`--max-requests 2` allows the production metadata-filter fallback. Default is
1. The script never calls RetrieveAndGenerate.

The Knowledge Base data source must index
`s3://cde2300-course-content-s3/course/`, not
`CDE2300_course_files_export/Course_materials/`. After changing the prefix,
run a full ingestion sync. Exact catalog keys such as
`course/lectureNotes/Week 1 Introduction to innovation v3.pdf` must appear in
Retrieve locations.

## Manual AWS Console steps still required

1. Create/confirm Aurora DSQL cluster in `us-west-2` and note the endpoint.
2. Create the S3 uploads bucket in `us-west-2` (block public access).
3. Create ECR repository and push the first `linux/arm64` image.
4. Attach the EC2 instance profile; map it to DB role `co_design_app`.
5. Run `scripts/init_dsql.py` as admin, then GRANT runtime privileges.
6. Confirm Cognito callback remains
   `https://d1sxfuoybzedj5.cloudfront.net/api/v1/auth/callback`.
7. In the Cognito app client, set **Refresh token expiration** to approximately
   **30 days** and keep token revocation enabled. This setting, not an
   application DB timeout, controls long-lived login duration.
8. Confirm authorization-code grant and the `openid email profile` scopes are
   enabled. Keep the app-client secret only in the host secrets configuration.
9. Pass the live smoke sequence above, then enable class traffic on the
   CloudFront distribution.

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
