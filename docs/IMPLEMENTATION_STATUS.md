# Implementation status

## Current phase

**Multi-user FastAPI ownership + student S3 key isolation**

Branch ``Production-RemoveData``. Cognito-authenticated application traffic now
follows:

```text
Cognito ID-token cookie
    ↓
FastAPI (verified sub)
    ↓
application user (users.cognito_sub)
    ↓
owner-scoped StudentStore
    ↓
DSQL / student-upload S3
```

Streamlit no longer bypasses FastAPI for Cognito users when
``USE_LOCAL_API=true``. Client-supplied ``user_id`` / owner headers are ignored.
``local-student`` remains only for explicit local/mock demos and tests.

Student upload object keys:

```text
users/<user-id>/notebooks/<notebook-id>/sources/<source-id>/<safe-filename>
```

Five-table schema unchanged:

```text
users
oauth_login_states
notebooks
messages
sources
```

**Out of scope (not implemented):** AWS Bedrock, Knowledge Base, S3 Vectors,
OCR redesign, course-material bucket, prompt/guardrail/model-provider changes.

**Do not initialize the real Aurora DSQL cluster until this branch is reviewed
and the local suite stays green.** Local `data/` was not migrated or deleted.

### What changed (this phase)

- Added ``backend/owner_context.py``: request-scoped Cognito → owner services.
- FastAPI notebook/message/source/coach routes resolve ownership from the
  verified ID-token cookie; DSQL/S3 deployments reject anonymous fallback.
- Streamlit ``local_api_enabled()`` is true for Cognito sessions; API client
  forwards only the short-lived ID cookie.
- Object keys include ``notebooks/`` + ``sources/<source-id>/``; source ids are
  generated server-side before S3 writes.
- DSQL ``delete_source`` keeps object-storage deletes outside OCC retries.
- Added deterministic multi-user isolation + S3 key tests.

### Commands run and results

- ``.venv/bin/python -m pytest -q`` → **207 passed**
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
- Existing S3 objects written under the previous key shape
  (``users/<user>/<notebook>/<uuid>/...``) are not rewritten; new uploads use
  the ``notebooks/.../sources/...`` shape. Notebook delete still uses the
  current prefix helper.

### Next exact action

1. Review multi-user FastAPI ownership + student S3 key isolation locally.
2. Confirm Cognito app client refresh-token validity (~30d) matches ops intent.
3. Only then run ``scripts/init_dsql.py --admin-user admin`` against us-west-2.
4. GRANT privileges to ``co_design_app``; map EC2 IAM role to that DB user.
5. Create/configure the student-upload bucket (``USER_UPLOADS_BUCKET``) and IAM.
6. Deploy ``compose.prod.yaml`` and run the live smoke sequence in
   ``docs/deploy/AWS_STATELESS_EC2.md``.
7. Hand off Bedrock / Knowledge Base / course-material bucket work to the other
   developer.

## Previous completed work

**Cognito-owned browser session + five-table persistence cleanup**

**Six-table production data model (local + DSQL schema aligned)** — superseded
for auth: ``app_sessions`` removed; notebooks/messages/sources/users/oauth remain.

**DSQL bootstrap idempotency + redundant index cleanup**

**DSQL admin token + ASYNC index bootstrap fixes**

**DSQL/S3 production adapter hardening**

**AWS stateless EC2 migration scaffolding**
