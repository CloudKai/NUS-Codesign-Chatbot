# Implementation status

## Current phase

**Final pre-AWS hardening (Cognito / DSQL / student S3)**

Branch ``Production-RemoveData``. No Bedrock/KB/OCR/course-material-S3 work.

### Hardening landed

1. Cognito ID tokens require ``token_use == "id"``.
2. In-process JWKS/KeySet cache with TTL + one refresh on unknown ``kid``.
3. DSQL runtime + admin connections use ``sslmode=verify-full`` and
   ``sslrootcert=system``.
4. ``COURSE_MATERIAL_SYNC_ENABLED`` gate (production compose ``false``) so
   lecture PDFs are not copied into ``USER_UPLOADS_BUCKET``.
5. Raw + extracted object keys cleaned when source metadata insert fails.
6. Production DSQL bootstrap uses ``__auth_bootstrap__`` with
   ``ensure_owner=False`` (no ``local-student`` row); readiness uses ``ping()``.
7. ``add_message`` / ``add_source`` / ``create_phase_transition`` verify notebook
   ownership inside the same DB unit of work as the child write.

### Commands run and results

- ``.venv/bin/python -m pytest -q`` → **212 passed**
- ``PYTHONPYCACHEPREFIX=/private/tmp/co-design-pycache .venv/bin/python -m
  compileall -q backend ui streamlit_app.py tests`` → exit 0
- ``docker compose config --quiet`` → exit 0
- ``APP_IMAGE=co-design:local docker compose -f compose.prod.yaml config --quiet``
  → exit 0
- No live Cognito / DSQL / S3 / OpenAI / Bedrock calls
- Not committed unless requested

### Next exact action

1. Review this hardening pass.
2. Confirm Cognito refresh-token validity (~30d).
3. Run ``scripts/init_dsql.py`` as admin when ready.
4. GRANT ``co_design_app``; map EC2 IAM role; set ``USER_UPLOADS_BUCKET``.
5. Deploy ``compose.prod.yaml`` and smoke-test.
6. Hand off course-material S3 / Bedrock / KB / OCR to the other developer.

## Previous completed work

**Multi-user FastAPI ownership + student S3 key isolation**

**Cognito-owned browser session + five-table persistence cleanup**

**DSQL bootstrap / adapter hardening**

**AWS stateless EC2 migration scaffolding**
