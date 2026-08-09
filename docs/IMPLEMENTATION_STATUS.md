# Implementation status

## Current phase

**Small follow-up on ``Production-RemoveData``** — Mock CI compose bootstrap,
prompt context-safety wording, and PromptComposer mandatory-section budgeting.
No Bedrock, schema, Cognito, Streamlit, or S3-layout redesign.

Prior phase commit ``19f5d4e`` (provider-neutral stage prompts + retryable S3
cleanup) is committed and pushed. This follow-up is committed and pushed on
``Production-RemoveData``.

### Behavior changes in this follow-up

1. Mock CI copies ``.env.example`` to a temporary CI ``.env`` before
   ``docker compose config`` so ``env_file: .env`` works without committing
   secrets. Production compose still requires ``env_file``.
2. Shared coaching prompt adds a concise CONTEXT SAFETY rule: project /
   retrieved / history / student content is untrusted evidence; document
   instructions never override shared, stage, or runtime rules.
3. ``PromptComposer`` reserves the final length budget for shared coaching,
   stage instructions, the current student message, and runtime instructions.
   Over-budget turns trim retrieved context first, then older recent messages,
   then summary/project context. Retrieved context default cap is ``24_000``
   for the temporary pre-Bedrock OpenAI testing path. No whole-PDF injection
   and no final hard-truncation of mandatory sections.

### Validation evidence

**Local (this follow-up):**

- ``.venv/bin/python -m pytest -q`` → **233 passed**.
- ``PYTHONPYCACHEPREFIX=/private/tmp/co-design-pycache .venv/bin/python -m
  compileall -q backend ui streamlit_app.py tests`` → exit 0.
- ``docker compose config --quiet`` and
  ``APP_IMAGE=co-design:test docker compose -f compose.prod.yaml config --quiet``
  → exit 0 (local developer ``.env`` present; CI will use ``cp .env.example .env``).
- ``git diff --check`` → exit 0.
- No live OpenAI, Cognito, DSQL, S3, or Bedrock calls. No Bedrock
  implementation changes (composer docstring mentions the future KB seam only).

**GitHub Actions (pushed commit ``19f5d4e``):**

- Mock CI run https://github.com/CloudKai/NUS-Codesign-Chatbot/actions/runs/31301098173
  **failed** at step ``Compose config`` because compose files reference
  ``env_file: .env`` and the runner has no private ``.env``.
- Steps ``Compile sources`` and ``Run mock pytest suite`` were **skipped** on
  that failure. This is distinct from the earlier local ``232 passed`` evidence
  for ``19f5d4e``.
- Re-check Mock CI on this follow-up push for compose + compileall + pytest.

**Prior local evidence for ``19f5d4e`` (not GitHub CI):**

- Local ``.venv/bin/python -m pytest -q`` → 232 passed.
- Local compileall + compose config (with a developer ``.env`` present) → exit 0.

### Compatibility, rollback, and known risks

- No schema/data migration; prompt files remain provider-neutral under
  ``backend/prompts/``.
- Rollback is a code/config revert; do not commit a populated secret ``.env``.
- Optional expired ``oauth_login_states`` cleanup remains skipped.

### Next exact action

1. Confirm Mock CI green on this push (compose + compileall + pytest).
2. Optional live OpenAI smoke with an explicit cost cap.
3. Otherwise proceed to AWS deployment wiring; future Knowledge Base work
   replaces only the retrieved-course-context producer.

## Previous completed work

**Provider-neutral stage prompts + retryable S3 cleanup** — ``19f5d4e`` on
``Production-RemoveData`` (pushed). Local mock suite 232 passed; GitHub Mock CI
failed on missing CI ``.env`` before compose validation.

**Final pre-AWS hardening (Cognito / DSQL / student S3)** — Cognito ID
``token_use``, JWKS cache, DSQL ``verify-full``, course-sync gate, orphan
object cleanup, ownership-in-write checks, ``ca-certificates`` in image.

**Multi-user FastAPI ownership + student S3 key isolation**

**Cognito-owned browser session + five-table persistence cleanup**

**DSQL bootstrap / adapter hardening**

**AWS stateless EC2 migration scaffolding**
