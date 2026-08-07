# Implementation status

## Current phase

**AWS stateless EC2 migration: DSQL + S3 storage providers (code complete; AWS
resources not provisioned by this change)**

Branch ``Production-RemoveData``. Local SQLite + filesystem remain the default
for development and tests. Production Compose selects Aurora DSQL + S3 and pulls
a prebuilt ECR image with no ``./data`` bind mount.

### Behavior implemented

1. **Storage provider config** — ``DATABASE_PROVIDER=sqlite|dsql`` and
   ``FILE_STORAGE_PROVIDER=local|s3|memory`` with local defaults.
2. **FileStorage ports** — ``LocalFileStorage``, ``S3FileStorage`` (IAM/boto3,
   injectable fake client), ``MemoryFileStorage`` for tests. Safe object keys
   under ``users/<user>/<thread>/<uuid>/<sanitized-filename>``.
3. **Aurora DSQL store** — ``DsqlStudentStore`` reuses the ``StudentStore`` API;
   DSQL schema without foreign keys; application-level cascade deletes; IAM auth
   token helper with retries; no permanent DB password.
4. **Stateless production Compose** — ``compose.prod.yaml`` uses
   ``image: ${APP_IMAGE}``, ``DATABASE_PROVIDER=dsql``,
   ``FILE_STORAGE_PROVIDER=s3``, secrets mount only (no ``./data``).
5. **Local Compose unchanged for data** — ``compose.yaml`` still builds locally
   and mounts ``./data`` for SQLite/dev.
6. **Dockerfile** — architecture-neutral ``python:3.12-slim`` (build with
   ``--platform linux/arm64``). ``.dockerignore`` excludes secrets, ``data/``,
   SQLite files, DuckDNS env.
7. **Host DuckDNS** — ``scripts/host/duck.sh`` + example env; not inside the app
   container. ECR refresh helper: ``scripts/deploy_ecr.sh``.
8. **Startup validation** — ``start_prod.sh`` requires ``/app/data`` only for
   sqlite/local; requires ``DSQL_ENDPOINT`` / ``USER_UPLOADS_BUCKET`` for
   production providers. FastAPI ``/ready`` reports storage providers.

### Files changed (this phase)

- Added: ``backend/persistence/`` (ports, factory, local/s3/memory files, DSQL
  connection/schema/store), ``compose.prod.yaml``,
  ``docs/deploy/AWS_STATELESS_EC2.md``, ``scripts/deploy_ecr.sh``,
  ``scripts/host/duck.sh``, ``scripts/host/duck.env.example``,
  ``tests/test_storage_providers.py``
- Updated: ``backend/settings.py``, ``backend/file_processing.py``,
  ``backend/student_store.py``, ``backend/source_library.py``, ``backend/api.py``,
  ``backend/app_sessions.py``, ``backend/auth_*.py``, ``backend/chat_service.py``,
  ``ui/runtime.py``, ``compose.yaml``, ``Dockerfile``, ``.dockerignore``,
  ``scripts/start_prod.sh``, ``requirements.txt``, ``.env.example``,
  ``tests/conftest.py``, ``tests/test_deployment_config.py``, this status file.

### Commands run and results

- ``.venv/bin/python -m pytest -q`` → **186 passed** (mock providers; no AWS
  network; no paid model calls).
- ``compileall`` on ``backend ui streamlit_app.py tests`` → exit 0.
- ``docker compose -f compose.yaml config -q`` and
  ``APP_IMAGE=... docker compose -f compose.prod.yaml config -q`` → validated
  with host permissions (sandbox cannot read private ``.env``).
- Existing ``data/`` directory **not** deleted. No automatic data migration.

### Migration / compatibility / rollback

- Local defaults remain SQLite + local files; existing tests and
  ``StudentStore(path=...)`` keep working.
- Production cutover requires AWS Console steps (DSQL cluster, S3 bucket, ECR
  image, EC2 IAM role) documented in ``docs/deploy/AWS_STATELESS_EC2.md``.
- Rollback: run previous Compose with ``./data`` mount / prior image tag.
- Cognito callback unchanged:
  ``https://cde2300chatbot.duckdns.org/api/v1/auth/callback``.

### Risks / blockers

- DSQL incompatibilities (no FKs, OCC retries, TEXT JSON) handled in code but
  not smoke-tested against a live cluster.
- No automated migration of existing SQLite/uploads into DSQL/S3.
- ``boto3`` / ``psycopg`` added to ``requirements.txt`` (lazy-imported); local
  mock tests do not require live AWS.
- Lecture-notes sync still expects a readable lecture folder path when used.

### Next exact action

1. Create DSQL cluster + S3 bucket + ECR repo in ``us-west-2``.
2. Build/push ``linux/arm64`` image; set host ``APP_IMAGE``, ``DSQL_ENDPOINT``,
   ``USER_UPLOADS_BUCKET``.
3. Deploy with ``compose.prod.yaml``; smoke Cognito login and one upload without
   relying on ``/app/data``.
4. Only after verified cutover, plan (separate approval) retirement of the old
   EC2 data volume — do not delete local ``data/`` unless explicitly requested.

## Previous completed work

**Auth UX + test coverage follow-up on FastAPI application sessions**

**Auth hardening: OAuth state binder, no Streamlit auth cache, production redirect**

**FastAPI-owned application sessions replace Streamlit OIDC cookies**

**Public Caddy API exposure reduced / single-EC2 Docker deployment**
