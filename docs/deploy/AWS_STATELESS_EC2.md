# Production AWS deployment (stateless EC2 + ECR)

This document describes the image-based production topology for
`cde2300chatbot.duckdns.org`. It does **not** delete local `data/` or migrate
existing SQLite/uploads automatically.

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
       │           ├── Aurora DSQL (structured state)
       │           ├── S3 (user uploads)
       │           └── Bedrock (us-west-2)
       └── DuckDNS cron on the host (not in the app container)
```

Persistent state lives in **Aurora DSQL** and **S3**. Replacing the app
container must not destroy conversations, progress, or uploads.

## Local vs production storage

| Concern | Local / tests | Production |
|---|---|---|
| Structured state | SQLite (`DATABASE_PROVIDER=sqlite`) | Aurora DSQL (`dsql`) |
| Uploads | Local files (`FILE_STORAGE_PROVIDER=local`) | S3 (`s3`) |
| Compose file | `compose.yaml` (build + `./data` mount) | `compose.prod.yaml` (image, no data mount) |
| Secrets | `.env` + `.streamlit/secrets.toml` (never in Git) | Host files + IAM role |

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
- `USER_UPLOADS_BUCKET=<bucket>`
- Cognito + public URL values already set in `compose.prod.yaml`

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
- Aurora DSQL `db-connect` / IAM DB auth for the cluster
- S3 read/write/delete on the uploads bucket prefix
- Bedrock invoke (existing model access)
- Optional CloudWatch logs

Do **not** place long-lived AWS access keys in `.env`.

## Manual AWS Console steps still required

1. Create/confirm Aurora DSQL cluster in `us-west-2` and note the endpoint.
2. Create the S3 uploads bucket in `us-west-2` (block public access).
3. Create ECR repository and push the first `linux/arm64` image.
4. Attach the EC2 instance profile with the permissions above.
5. Apply DSQL schema (store init / controlled migration) — no automatic data
   migration from the old SQLite volume is performed by this codebase.
6. Confirm Cognito callback remains
   `https://cde2300chatbot.duckdns.org/api/v1/auth/callback`.
7. Cut over DNS/DuckDNS to the new instance when ready.

## Aurora DSQL assumptions

- PostgreSQL wire protocol via `psycopg`
- No foreign keys / ON DELETE CASCADE — child rows deleted in application code
- JSON-shaped fields stored as TEXT
- IAM auth tokens (no permanent DB password)
- OCC serialization failures should be retried by the connection helper
- Do not assume every PostgreSQL feature works (no temp tables, limited DDL)

## Before removing the old EC2 `/app/data` volume

1. Confirm production Compose uses DSQL + S3 and no `./data` mount.
2. Migrate or accept loss of any SQLite-only history (manual, approved).
3. Verify uploads readable from S3 and coaching resumes after container replace.
4. Keep local `data/` for development unless separately instructed to delete it.
