# Implementation status

## Current phase

**DSQL/S3 production adapter hardening (DDL out of runtime, co_design_app role,
OCC retries, S3 content reads)**

Branch ``Production-RemoveData``. Local SQLite + filesystem remain the default.
Production Compose selects Aurora DSQL + S3 with runtime role ``co_design_app``.
**Live DSQL/S3 smoke is still required before declaring migration complete.**

### Behavior implemented

1. **No runtime DDL** — ``DsqlStudentStore`` no longer runs ``DSQL_SCHEMA`` /
   ALTER / CREATE INDEX. Schema bootstrap is admin-only
   ``scripts/init_dsql.py`` (one DDL per committed transaction + reconnect).
2. **Runtime role** — ``DSQL_USER=co_design_app`` (compose.prod / settings /
   validation). ``admin`` rejected for app runtime. Tokens use DbConnect
   (``generate_db_connect_auth_token``), not DbConnectAdmin.
3. **OCC retries** — ``run_dsql_transaction`` retries idempotent write units on
   SQLSTATE 40001 with bounded exponential backoff; S3 cleanup stays after DB
   commit for notebook delete.
4. **S3 source reads** — ``WorkspaceService.read_source_content`` uses
   ``read_source_bytes`` (local path or FileStorage). ``S3FileStorage`` maps
   only missing-object codes to ``FileNotFoundError``; AccessDenied propagates.
5. **Tests** — DSQL provider selection without forcing SQLite path; bootstrap
   commit-per-DDL; OCC retry; S3 AccessDenied; upload→memory/S3→read round trip.

### Files changed (this follow-up)

- Added: ``scripts/init_dsql.py``
- Updated: ``backend/persistence/dsql_*.py``, ``s3_files.py``, ``factory.py``,
  ``backend/settings.py``, ``backend/workspace_service.py``,
  ``compose.prod.yaml``, ``scripts/start_prod.sh``, ``.env.example``,
  ``docs/deploy/AWS_STATELESS_EC2.md``, this status file,
  ``tests/test_storage_providers.py``, ``tests/test_deployment_config.py``

### Commands run and results

- ``.venv/bin/python -m pytest -q`` → **190 passed** (mocks/fakes only; no AWS
  network; no paid model calls).
- ``compileall`` on ``backend ui streamlit_app.py tests scripts`` → exit 0.
- ``docker compose -f compose.yaml config -q`` and
  ``APP_IMAGE=... docker compose -f compose.prod.yaml config -q`` → exit 0.
- Existing ``data/`` directory **not** deleted. No automatic data migration.
- Changes **not** committed (per request).

### Migration / compatibility / rollback

- Local defaults remain SQLite + local files.
- Production cutover still needs AWS Console + live smoke (documented).
- Cognito callback unchanged:
  ``https://cde2300chatbot.duckdns.org/api/v1/auth/callback``.

### Risks / blockers

- Live DSQL/S3 smoke not yet executed.
- Partial unique index support may vary by DSQL revision (bootstrap logs/fails
  per statement).
- Lecture-notes sync still expects a readable lecture folder when used.

### Next exact action

1. Run ``scripts/init_dsql.py --admin-user admin`` against the us-west-2 cluster.
2. GRANT privileges to ``co_design_app``; map EC2 IAM role to that DB user.
3. Deploy ``compose.prod.yaml`` with ``DSQL_USER=co_design_app``.
4. Execute the live smoke sequence in ``docs/deploy/AWS_STATELESS_EC2.md``.

## Previous completed work

**AWS stateless EC2 migration scaffolding (DSQL + S3 providers, compose.prod)**

**Auth UX + test coverage follow-up on FastAPI application sessions**

**Auth hardening / FastAPI application sessions / Caddy route reduction**
