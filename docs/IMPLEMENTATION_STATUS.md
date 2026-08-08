# Implementation status

## Current phase

**DSQL bootstrap idempotency + redundant index cleanup**

Branch ``Production-RemoveData``. Narrow follow-up:

1. ``CREATE INDEX ASYNC IF NOT EXISTS`` with no ``job_id`` row skips
   ``sys.wait_for_job`` (idempotent re-run).
2. Removed redundant ``idx_app_sessions_token_hash`` from DSQL schema
   (``tokenHash`` is already ``UNIQUE``); kept ``idx_app_sessions_user``.

**Live DSQL/S3 smoke is still required before declaring migration complete.**

### Files changed (this follow-up)

- Updated: ``scripts/init_dsql.py``, ``backend/persistence/dsql_schema.py``,
  ``tests/test_storage_providers.py``, ``docs/deploy/AWS_STATELESS_EC2.md``,
  this status file.

### Commands run and results

- ``.venv/bin/python -m pytest -q`` → **194 passed** (mocks/fakes only).
- ``compileall`` → exit 0.
- Not committed unless requested.

### Next exact action

1. Run ``scripts/init_dsql.py --admin-user admin`` against the us-west-2 cluster.
2. GRANT privileges to ``co_design_app``; map EC2 IAM role to that DB user.
3. Deploy ``compose.prod.yaml`` with ``DSQL_USER=co_design_app``.
4. Execute the live smoke sequence in ``docs/deploy/AWS_STATELESS_EC2.md``.

## Previous completed work

**DSQL admin token + ASYNC index bootstrap fixes**

**DSQL/S3 production adapter hardening (DDL out of runtime, co_design_app,
OCC retries, S3 content reads)**

**AWS stateless EC2 migration scaffolding (DSQL + S3 providers, compose.prod)**
