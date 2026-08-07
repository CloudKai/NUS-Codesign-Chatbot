# Implementation status

## Current phase

**DSQL admin token + ASYNC index bootstrap fixes**

Branch ``Production-RemoveData``. Follow-up on DSQL/S3 hardening:

1. ``scripts/init_dsql.py`` uses ``generate_db_connect_admin_auth_token``;
   runtime still uses DbConnect only (``co_design_app``).
2. Cognito unique index is ``CREATE UNIQUE INDEX ASYNC`` without ``WHERE``.
3. Bootstrap waits on ``sys.wait_for_job`` after each ASYNC index commit.
4. ``NoSuchBucket`` is not mapped to ``FileNotFoundError``.

**Live DSQL/S3 smoke is still required before declaring migration complete.**

### Files changed (this follow-up)

- Updated: ``backend/persistence/dsql_connection.py``, ``dsql_schema.py``,
  ``s3_files.py``, ``scripts/init_dsql.py``, ``tests/test_storage_providers.py``,
  ``docs/deploy/AWS_STATELESS_EC2.md``, this status file.

### Commands run and results

- ``.venv/bin/python -m pytest -q`` → **193 passed** (mocks/fakes only).
- ``compileall`` → exit 0.
- Existing ``data/`` not deleted. Not committed unless requested.

### Risks / blockers

- Live DSQL/S3 smoke not yet executed.
- Lecture-notes sync still expects a readable lecture folder when used.

### Next exact action

1. Run ``scripts/init_dsql.py --admin-user admin`` against the us-west-2 cluster.
2. GRANT privileges to ``co_design_app``; map EC2 IAM role to that DB user.
3. Deploy ``compose.prod.yaml`` with ``DSQL_USER=co_design_app``.
4. Execute the live smoke sequence in ``docs/deploy/AWS_STATELESS_EC2.md``.

## Previous completed work

**DSQL/S3 production adapter hardening (DDL out of runtime, co_design_app,
OCC retries, S3 content reads)**

**AWS stateless EC2 migration scaffolding (DSQL + S3 providers, compose.prod)**

**Auth UX / FastAPI application sessions / Caddy route reduction**
