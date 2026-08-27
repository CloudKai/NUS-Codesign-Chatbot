# Production release checklist

Operator checklist for promoting a SHA of `Integrate-Bedrock` to the
CloudFront + EC2 origin. No secrets, account IDs, ARNs, bucket names, or
endpoints belong in this file — use host `.env` placeholders.

Architecture: [`LOCAL_DEMO_IMPLEMENTATION.md`](LOCAL_DEMO_IMPLEMENTATION.md).  
Current SHA / CI / deploy impact: [`IMPLEMENTATION_STATUS.md`](IMPLEMENTATION_STATUS.md) (**CURRENT STATUS**).  
Topology and build commands: [`deploy/AWS_STATELESS_EC2.md`](deploy/AWS_STATELESS_EC2.md).

Production (`compose.prod.yaml`) matches the local demo stage policy:
`STUDENT_STAGE_SELECTION=true` and `AUTO_ADVANCE_STAGES=false`. Coach ADVANCE
opens Ready; students move with Journey **Work on this stage** or typed
`Move to`. Do not flip those flags back to Month-1 auto-advance during release
unless product explicitly reverts.

---

## Ordered cutover (this release)

Source-ready does **not** mean AgentCore is serving the new code. AgentCore
READY does **not** mean the EC2 image is new. Keep these gates separate.

### SOURCE CODE READY

1. Commit/push the intended SHA on `Integrate-Bedrock-v2`.
2. Confirm mock CI (`mock-suite` and `agentcore-runtime-compatibility`).

### AGENTCORE PUBLISHED (existing ARN only)

3. Publish a **new version** to the **existing** AgentCore runtime ARN.
   Do **not** create a new runtime ARN.
4. Wait until that new runtime version is **READY**.
5. Move the **DEFAULT** qualifier only after READY.
6. Increase `AGENTCORE_SESSION_GENERATION` in host `.env` so warm microVMs
   cannot keep the previous assets.

### EC2 IMAGE DEPLOYED

7. Build an immutable ARM64 EC2 app image from the **same git SHA**.
8. Deploy that image (`APP_IMAGE` immutable tag; never `:latest`).
9. Confirm host-local `/api/v1/ready` (Caddy must **not** expose `/ready`
   publicly).
10. Run a small controlled live validation.

Intended order is 1 → 10. Do not skip the READY wait. Do not move DEFAULT
onto a non-READY version. Prompt cache stays **off**. Session affinity is
enabled by `compose.prod.yaml` and is safe only while production owner ids
remain unique Cognito subjects.

---

## 1. Git SHA being released

| | |
|---|---|
| **How** | `git rev-parse HEAD` on the tree you build. Image must be built with `--build-arg GIT_SHA=<that-sha>` ([`deploy/AWS_STATELESS_EC2.md`](deploy/AWS_STATELESS_EC2.md) “Build and push”). |
| **Confirm on the host** | `docker inspect --format "{{index .Config.Labels \"org.opencontainers.image.revision\"}}" "$APP_IMAGE"` and the container env `APP_GIT_SHA`. `/api/v1/health` does **not** expose the SHA. |
| **Pass** | Label and `APP_GIT_SHA` both equal the intended full SHA. |

## 2. Docker image tag (`APP_IMAGE`)

| | |
|---|---|
| **How** | Set host `APP_IMAGE` to the ECR URI **plus an immutable tag** (the git SHA). `compose.prod.yaml` uses `image: ${APP_IMAGE}`. Refresh with `sh scripts/deploy_ecr.sh`. |
| **Rule** | **Never** tag or deploy `:latest`. CI’s `co-design:ci-<12-char-sha>` build is validation-only; it is not the production push. |
| **Pass** | `docker compose -f compose.prod.yaml config` shows the immutable URI; running container matches it (`docker inspect` / `docker compose ps`). |

## 3. AgentCore runtime version / DEFAULT / liveVersion

| | |
|---|---|
| **How** | AWS console: Bedrock AgentCore → this environment’s runtime (ARN from host `.env`) → **DEFAULT** endpoint. CLI used in prior publishes: control-plane `get-agent-runtime` / DEFAULT endpoint for the runtime id parsed from `AGENTCORE_RUNTIME_ARN` (do not paste ARNs into tickets). |
| **Expected** | Qualifier `DEFAULT`. Query the current liveVersion before this release; last documented value was **21** (slim `fast_chat`) and must not be assumed. This release publishes a **new version on the existing ARN**, waits until READY, then moves DEFAULT. FastAPI Compose: `MODEL_PROVIDER=agentcore`, `AGENTCORE_QUALIFIER=DEFAULT`. The published runtime environment must contain `DEEP_REVIEW_BEDROCK_READ_TIMEOUT_SECONDS=180`; this is runtime-only and must not be added to the EC2 app container. |
| **Pass** | Endpoint **READY**; DEFAULT liveVersion is the version you intend to serve; the runtime configuration reports the Deep Review Bedrock read timeout as **180s**. FastAPI host env qualifier is `DEFAULT`. |

## 4. `AGENTCORE_SESSION_GENERATION` (required on republish)

Publishing a **new AgentCore runtime version** requires changing
`AGENTCORE_SESSION_GENERATION` **and redeploying FastAPI**. Warm runtime
sessions can keep serving the code assets from when the microVM was created;
a new liveVersion on DEFAULT is not enough if FastAPI reuses the old session
generation.

| | |
|---|---|
| **When** | Every authorised AgentCore republish. Not required for an app-image-only deploy that does not publish a new runtime version. |
| **How** | **Always** set a new non-secret generation value in host `.env` for a republish (and redeploy the app container so FastAPI picks it up). This is required even when only runtime environment or prompt/schema assets changed. |
| **Pass** | Host env generation differs from the pre-publish value; app container recreated after the change; DEFAULT liveVersion is the new published version. |

Rolling back an AgentCore version has the same rule: change generation again
and redeploy FastAPI, or warm sessions may keep the version you just left.

## 5. DSQL schema

| | |
|---|---|
| **How** | Admin only: `scripts/init_dsql.py` (`--admin-user admin` as documented in [`deploy/AWS_STATELESS_EC2.md`](deploy/AWS_STATELESS_EC2.md)). Inspect/plan first; one DDL per transaction. |
| **Never** | App startup DDL. Runtime role `co_design_app`. Ad-hoc `psql` edits during release. |
| **This release** | No new DDL beyond the additive revision/idempotency schema already in `init_dsql.py`. Confirm the cluster already has those columns (`notebooks.conversation_revision`, message revision lineage). If they are already present, **do not** re-run bootstrap “just in case” during the cutover window unless you are applying a documented additive plan. |
| **Pass** | Host-local `/api/v1/ready` returns 200 (Caddy must **not** expose `/ready` publicly). DSQL ping succeeds. No schema change in the release ticket. |

## 6. S3 buckets

| | |
|---|---|
| **User uploads** | Host `USER_UPLOADS_BUCKET`. Keys under `users/<user-id>/notebooks/<notebook-id>/sources/...` (`raw/` and `derived/`). |
| **Course materials** | Host `COURSE_MATERIALS_BUCKET` with `COURSE_MATERIALS_PREFIX=course/`. Lecture Notes and Readings stay under `course/lectureNotes/` and `course/readings/`. |
| **Never** | Copy course PDFs into the `users/` prefix. Course sync exposes virtual catalog rows; it does not duplicate PDFs into notebook uploads. |
| **Pass** | Compose `COURSE_MATERIAL_SYNC_ENABLED=true` and prefix `course/`; a sample course object is under `course/`, not `users/`. |

## 7. Knowledge Base

| | |
|---|---|
| **Type** | Compose `KNOWLEDGE_BASE_TYPE=MANAGED`. Retrieve must use managed search configuration, not vector search. |
| **Id / filter mode** | Host `KNOWLEDGE_BASE_ID`. Filter mode is `KNOWLEDGE_BASE_METADATA_FILTER_MODE` (code default `required`). Until sidecars are ingested, follow [`KB_REQUIRED_MODE_RUNBOOK.md`](KB_REQUIRED_MODE_RUNBOOK.md) — do not enable `required` as a guess. |
| **Sidecars** | `course_material_id` sibling `.metadata.json` next to course objects. Generate/upload only via `scripts/sync_course_kb_metadata.py` (dry-run default; `--confirm` uploads). Never writes `users/`. |
| **Pass** | Data source indexes `course/` (not an export prefix); last ingestion job `COMPLETE` if you synced; filter mode matches the runbook for this environment. |

## 8. Guardrail version 4 (both sides)

| | |
|---|---|
| **FastAPI** | `compose.prod.yaml` sets `GUARDRAIL_VERSION=4`. Host `.env` supplies `GUARDRAIL_ID` (not in git). |
| **Runtime** | Same guardrail id **and version 4** on the AgentCore runtime process environment. |
| **Pass** | Compose config shows version `4`; runtime env shows version `4`; a coach turn does not fail closed for missing guardrail config. |

## 9. Cognito callback and origins

`compose.prod.yaml` interpolates from `PUBLIC_ORIGIN`:

- `COGNITO_REDIRECT_URI=${PUBLIC_ORIGIN}/api/v1/auth/callback`
- `CO_DESIGN_UI_URL` and `CO_DESIGN_PUBLIC_API_URL` = `PUBLIC_ORIGIN`

| | |
|---|---|
| **Console** | Cognito app client **Allowed callback URLs** must include exactly that HTTPS callback. **Allowed sign-out URLs** must include the UI origin `${PUBLIC_ORIGIN}/` (app logout clears cookies and redirects to `/?signed_out=1` on `CO_DESIGN_UI_URL`). |
| **Pass** | Login returns to the workspace; logout lands on the signed-out gate; callback host matches `PUBLIC_ORIGIN` (HTTPS, path `/api/v1/auth/callback`). |

## 10. Post-deploy smoke

Historical live matrix: [`MANUAL_PRODUCTION_QA.md`](MANUAL_PRODUCTION_QA.md) (dated; not current HEAD evidence). Optional **local** headed path after `sh scripts/start.sh`: `sh scripts/browser_e2e_smoke.sh` (manual Cognito; selection-mode Ready / Move to).

Ordered production smoke (selection mode):

1. Public `/api/v1/health` → 200, `"mode":"production"`. Host-local `/api/v1/ready` → 200.
2. Cognito login → workspace. Refresh keeps the session.
3. Create or open a notebook. Send a coaching turn. Expect a reply (not `safety_blocked` / 503).
4. When Ready appears, focus stays until the student moves via Journey **Work on this stage** or typed `Move to <stage>`. Do **not** expect silent auto-advance.
5. Upload a small personal source, select it, ask a grounded question, open `[S#]` preview.
6. Recreate the app container (no student data volume). Log in again; notebook, messages, and stage persist (DSQL + S3).
7. Logout → signed-out gate; back-navigation does not restore protected data.

Stop if health/ready fails, login loops, or coach turns return 503/`provider-unavailable`.

## 11. Rollback

1. Set `APP_IMAGE` to the **previous immutable tag** (known-good SHA). Run `sh scripts/deploy_ecr.sh`.
2. If this release also published an AgentCore version: point DEFAULT back to the previous **READY** liveVersion **and** change `AGENTCORE_SESSION_GENERATION`, then recreate the app container. Version rollback without a new session generation can leave warm microVMs on the version you meant to leave.
3. Do not roll schema forward/back during the app rollback. Additive DSQL columns already applied stay; old app code ignores extra columns.
4. Pass: previous image SHA is running; DEFAULT liveVersion matches the rollback target; login + one coach turn succeed.

## 12. CloudWatch / logs after deploy

Container logs (json-file → CloudWatch or the host sink). No student text.

| Check | Pass |
|---|---|
| `coach_turn_perf` | JSON events on successful/failed turns (`co_design.turn_perf` / operational metrics). |
| `TIMING` | Lines `TIMING student_state|memory|retrieval|context_build|agent|persistence|TOTAL` in **seconds**. |
| 5xx rate | No sustained API 5xx after the smoke. |
| 429 rate | Brief 429s under concurrency are expected (`Retry-After`); a spike at idle is not. |
| Provider 503s | `ProviderUnavailableError` / category-only 503 bodies stay rare. Investigate `failure_category` (including `safety_blocked`) without logging prompts. |

---

## Do not do during release

- Live DSQL DML/DDL outside a documented `init_dsql.py` admin plan.
- Knowledge Base re-sync or filter-mode flip except via [`KB_REQUIRED_MODE_RUNBOOK.md`](KB_REQUIRED_MODE_RUNBOOK.md).
- Deploy or retag `:latest`.
- Schema change in the app container or as `co_design_app`.
- Paid/live AgentCore or Bedrock smokes without an explicit cost cap.
- Copy course objects into `users/`.
- Flip `STUDENT_STAGE_SELECTION` / `AUTO_ADVANCE_STAGES` away from the
  selection-mode Compose defaults without an explicit product decision.
- Republish AgentCore without changing `AGENTCORE_SESSION_GENERATION` and recreating FastAPI.
- Create a **new** AgentCore runtime ARN (publish a new version on the existing ARN).
- Enable `FAST_CHAT_PROMPT_CACHE_ENABLED` on this baseline. Session affinity is
  already enabled in `compose.prod.yaml`; do not enable it with shared owner
  identifiers.
