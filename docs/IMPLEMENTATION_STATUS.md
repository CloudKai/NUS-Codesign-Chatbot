# Implementation status

## Current phase

**Final pre-AWS Cognito / DSQL / student-S3 hardening plus local stage-prompt
architecture** — integrated on ``Production-RemoveData``. This phase adds no
Bedrock resources and made no live paid-provider or AWS calls.

### Behavior and architecture

1. Cognito accepts only verified ID tokens (``token_use=id``); JWKS is cached
   in process with TTL refresh and one unknown-``kid`` refresh.
2. DSQL runtime/admin connections use ``verify-full`` plus system roots.
   Readiness uses ``SELECT 1`` and does not create a production
   ``local-student`` row. Child ownership checks and writes share one unit.
3. Production course-material sync is disabled; lecture PDFs are excluded
   from the image. Failed upload metadata writes clean raw/derived objects.
4. Source/notebook deletes commit DB work first, then delete deterministic
   authenticated-owner prefixes outside DSQL OCC. An absent-row retry repeats
   cleanup safely while FastAPI preserves not-found semantics.
5. ``backend/prompts/`` provides cached UTF-8 shared/stage prompt files and a
   framework-neutral bounded composer. The application supplies the
   DSQL-authoritative stage, assignment context, learning summary, and current
   selected-source context. Providers retain structured-output invocation.
6. ``scripts/preview_prompt.py`` previews fake local prompts; the future
   Bedrock seam replaces only the ``retrieved_course_context`` producer.

### Validation evidence

- Integrated focused suite (prompt, delete retry, workspace API, ownership,
  storage) → 50 passed.
- ``.venv/bin/python -m pytest -q`` → 232 passed.
- ``PYTHONPYCACHEPREFIX=/private/tmp/co-design-pycache .venv/bin/python -m
  compileall -q backend ui streamlit_app.py tests`` → exit 0.
- Local and production ``docker compose ... config --quiet`` → exit 0.
- ``git diff --check`` → exit 0.
- No live OpenAI, Cognito, DSQL, S3, or Bedrock calls.

### Compatibility, rollback, and known risks

- No schema/data migration; existing entrypoints and five-table schema remain.
- Production no longer auto-copies bundled lecture notes into student S3.
  Local development keeps sync enabled by default.
- Rollback is a code/config revert; no persisted data was rewritten.
- Optional expired ``oauth_login_states`` cleanup was intentionally skipped
  because it was not an isolated safe change.
- Test output has existing Starlette/httpx deprecation warnings only.
- Changes are not committed or pushed.

### Next exact action

With an explicit request/token cost cap, run one optional live OpenAI smoke
using ``MODEL_PROVIDER=openai``. Otherwise proceed to AWS deployment wiring;
future Knowledge Base work should replace only the retrieved-course-context
producer documented in ``docs/PROMPT_ARCHITECTURE.md``.

## Previous completed work

**Final pre-AWS hardening (Cognito / DSQL / student S3)** — deletion
idempotency, Cognito ID ``token_use``, JWKS cache, DSQL ``verify-full``,
course-sync gate, orphan object cleanup, ownership-in-write checks, mock CI
compose validation, ``ca-certificates`` in image.

**Multi-user FastAPI ownership + student S3 key isolation**

**Cognito-owned browser session + five-table persistence cleanup**

**DSQL bootstrap / adapter hardening**

**AWS stateless EC2 migration scaffolding**
