# Implementation status

## Current phase

**Production-test + provider-neutral RAG hardening on
``Production-RemoveData``** — Cognito, stateless EC2, Aurora DSQL,
student-upload S3, query-aware local retrieval, and the temporary OpenAI
provider path. Bedrock remains explicitly out of scope.

### Behavior changes

1. Public notebook/message payloads are typed and reject stage, progress, and
   transition metadata. Only the internal learning workflow can write
   authoritative stage state; Conclusion cannot propose or confirm another
   Conclusion transition.
2. Workflow/provider failures are not retried through the sequential fallback,
   preventing duplicate paid provider calls. A completed user/assistant turn,
   assessment, pending decision, and notebook summary now commit in one store
   transaction. DSQL notebook read/merge/write also uses one retryable
   transaction, preventing stale stage reversion.
3. New S3 uploads separate raw and derived namespaces. Batch uploads prevalidate
   sizes and clean up all accumulated objects on validation or put failure.
   PDF/Office extraction has bounded page, archive, compression, slide,
   paragraph, and cell limits.
4. Cognito logout derives the trusted same-origin ``/oauth2/revoke`` endpoint
   when discovery omits it. Unknown JWKS key IDs have a bounded forced-refresh
   window, avoiding unauthenticated network amplification. Expired OAuth login
   states are cleaned during new-state insertion.
5. Production readiness now verifies the configured file store, bounded S3
   list access, and SELECT access to all five required DSQL tables. The DSQL
   schema expresses non-primary uniqueness as explicit ``CREATE UNIQUE INDEX
   ASYNC`` jobs that bootstrap waits for.
6. The adapter-configured OpenAI/Ollama model is authoritative. Response
   language reaches the prompt, reasoning effort restores per notebook, and
   selected sources force model-knowledge fallback off. Request/image limits
   are enforced at the API/application boundary.
7. UI edit, regenerate, and ambiguous retry controls are disabled until there
   is an idempotent server-side replacement contract. This prevents duplicate
   turns and accidental repeated model calls during production testing.
8. Production documentation now uses ``compose.prod.yaml``/ECR and makes S3
   setup/readiness explicit. The default stateful Compose stack is labelled
   local-only; Bedrock permissions are not required in this phase.
9. Selected-source concatenation is replaced by a provider-neutral retrieval
   port and deterministic local chunk retriever. It uses sentence-aware chunks,
   current-turn-weighted lexical ranking, bounded conversation/project
   continuity, source diversity, stable ``[S#]`` labels, image markers, and
   strict context budgets in both preferred API and legacy development paths.
10. Assistant messages persist structured ``retrieval_refs`` for audit while
   ``source_refs`` remains limited to sources actually cited. Citation previews
   focus on matching evidence. Application code rebuilds prompt context only
   from validated chunks and rejects source IDs/labels outside the selected
   notebook, preserving the future Bedrock adapter boundary.
11. Live Aurora DSQL bootstrap corrections: async index waits now execute
   ``CALL sys.wait_for_job(?)`` on a dedicated verify-full admin connection
   with ``autocommit=True``; DDL remains one transaction per connection. The
   unsupported ``GRANT USAGE ON SCHEMA public`` was removed, leaving only
   SELECT/INSERT/UPDATE/DELETE on all application tables in ``public``.

### Validation evidence

**Local (this phase):**

- ``.venv/bin/python -m pytest -q`` → **255 passed**.
- ``PYTHONPYCACHEPREFIX=/private/tmp/co-design-pycache .venv/bin/python -m
  compileall -q backend ui streamlit_app.py tests`` → exit 0.
- ``docker compose config --quiet`` and
  ``APP_IMAGE=co-design:test docker compose -f compose.prod.yaml config --quiet``
  → exit 0.
- ``sh -n scripts/start.sh scripts/start_prod.sh scripts/build.sh
  scripts/deploy_ecr.sh`` → exit 0.
- ``git diff --check`` → exit 0.
- No live OpenAI, Cognito, DSQL, S3, or Bedrock calls. No Bedrock
  implementation changes.

### Compatibility, rollback, and known risks

- New S3 objects use ``raw/`` and ``derived/`` subpaths. Existing rows retain
  their full historical keys, remain readable, and stay within the same
  source/notebook deletion prefix. No object migration is required.
- DSQL bootstrap schema changed before live initialization. If an earlier
  draft schema was already applied, inspect existing uniqueness/index state
  before rerunning bootstrap; never drop production objects automatically.
- This DSQL bootstrap correction changes no table or index DDL. An earlier
  failed public-schema ``USAGE`` grant needs no rollback; rerun bootstrap, then
  apply only the documented object-level runtime grant.
- Public clients that sent unrestricted notebook/message metadata now receive
  422 and must use the typed settings or internal coaching endpoints.
- RAG requires no schema migration. New assistant/user metadata may include
  ``retrieval_refs``; older messages without it remain compatible.
- The current local retriever reads selected extracted text and chunks it at
  query time. This is deterministic and suitable for the bounded development
  corpus, but it is lexical rather than embedding-semantic and is not the
  long-term large-corpus index. Bedrock Knowledge Bases replaces this adapter.
- UI edit/regenerate stays unavailable until a transactional idempotency and
  replacement design is implemented.
- Rollback is a code/config revert. Do not commit `.env`, secrets, database
  files, or uploaded content. No live AWS resource was created or modified.

### Next exact action

1. Create the private S3 uploads bucket in ``us-west-2`` with Block Public
   Access; attach bucket list plus ``users/*`` object permissions to
   the EC2 instance role.
2. Finish Aurora DSQL, map the EC2 role to ``co_design_app``, run
   ``scripts/init_dsql.py`` as admin, then grant SELECT/INSERT/UPDATE/DELETE on
   all tables in ``public`` to ``co_design_app``. Do not grant schema ``USAGE``.
3. Deploy the immutable ECR image with ``scripts/deploy_ecr.sh`` and require
   ``/api/v1/ready`` to return 200.
4. Run the Cognito → notebook → message → S3 upload/download → container
   replacement → delete live smoke sequence. Use mock mode first; make an
   OpenAI request only with explicit approval and a cost cap.
5. Integrate Bedrock later by implementing ``ContextRetriever`` from
   ``backend/retrieval.py`` with Knowledge Base ``Retrieve`` and selected
   user/notebook/source metadata filters. Keep the existing composer,
   citations, workflow, and persistence boundaries unchanged.

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
