# Implementation status

## Current phase — Publish vendored AgentCore DEFAULT v14 and capped Sonnet smoke

**Completed on 2026-08-16.** Same runtime ARN
`NUSCodesignChatbot_chatbot_harnessAgent-6ncEO79sD7`. No second runtime.
`DEFAULT` is **version 14 READY**. One capped live smoke returned
`{"ok": true, "stage": "problem_identification", "recommendation": "stay"}`.

v11 was source-only (AgentCore does not pip-install `requirements.txt`).
v12 vendored linux/arm64 cp314 wheels but `main.py` never called `app.run()`,
so the process imported and exited (HTTP 502). v13 reused the last working
v9 site-packages zip plus current sources and OTEL entrypoint; it started,
then exited for the same missing `app.run()`. v14 is that zip with
`if __name__ == "__main__": app.run()`.

### Behavior delivered

1. Live artifact is a ~47MB zip: v9 linux/arm64 Python 3.14 site-packages
   (pydantic 2.13.4, strands-agents 1.52.0, bedrock-agentcore 1.21.0,
   aws-opentelemetry-distro) plus current `agentcore_runtime/` sources at zip
   root. Entrypoint `opentelemetry-instrument main.py`.
2. Runtime env unchanged except already-set Sonnet 4.6 + guardrail keys:
   `AGENTCORE_MODEL_PROVIDER=bedrock`,
   `AGENTCORE_MODEL_ID=global.anthropic.claude-sonnet-4-6`,
   `AGENTCORE_MODEL_REGION=us-west-2`, `GUARDRAIL_ID=o8aipba8m129`,
   `GUARDRAIL_VERSION=1`.
3. `agentcore_runtime/main.py` now starts `BedrockAgentCoreApp` when executed
   as `__main__`.

### Main files changed

- `agentcore_runtime/main.py`, `agentcore_runtime/README.md`
- Tests: `tests/domain/test_agentcore_runtime.py` asserts `app.run()`
- Docs: this file, `docs/providers/AGENTCORE_ADAPTER.md`

### Validation evidence

- Focused pytest `tests/domain/test_agentcore_runtime.py`
  `test_runtime_model.py` `test_security_invariants.py`: **passed**.
- `PYTHONPATH=. .venv/bin/python scripts/agentcore_smoke.py
  --i-approve-live-agentcore --cost-cap 1.00 --max-requests 1`: **passed**
  (`ok: true`, stage `problem_identification`, recommendation `stay`).
- `get-agent-runtime`: status READY, version **14**.
- `DEFAULT` endpoint: READY, `liveVersion` **14**.
- CloudWatch v13 showed OTEL + IAM credentials then silence (process exit).
  v11 showed `ModuleNotFoundError: pydantic` (source-only zip).

### Compatibility, migration, and rollback

- No schema change. ARN unchanged. `DEFAULT` auto-moved on each successful
  `update-agent-runtime` (preprod, accepted).
- Rollback is another `update-agent-runtime` with the v9 zip
  `agentcore-patches/chatbot_harnessAgent-structured-coach-21a5896f90b517ba8bc7843a8b5be5f5b12e33cf9c7130d81ca5c6dcb949685d.zip`
  or a new zip built the same way from that base.
- Live artifact:
  `s3://cdk-hnb659fds-assets-355604674280-us-west-2/agentcore-patches/chatbot_harnessAgent-sonnet46-v14-20260815T193913Z.zip`

### Known risks and next exact action

- This is **preprod**. Do not call the app student-ready until host `.env`,
  ECR/`APP_IMAGE`, and CloudFront/Caddy alignment are done.
- Next: fill the EC2/host `.env` with the existing ARN + `AGENTCORE_QUALIFIER=DEFAULT`,
  keep `MODEL_PROVIDER=agentcore`, then build/push `APP_IMAGE` if that is the
  remaining cutover blocker. Do not invoke unbounded Streamlit chat as the
  next paid test.

## Previous phase — AgentCore runtime dependency reproducibility

**Completed locally on 2026-08-16.** Integrate-Bedrock HEAD at start of this
pass: `529716c46fa45d20cdba02a145f6d63f088629b8`. This pass proved the
AgentCore runtime pins are installable from PyPI in a clean CPython 3.12.10
venv, locked them as exact versions, and added a network-free compatibility
diagnostic plus a GitHub job that actually installs
`agentcore_runtime/requirements.txt`. Architecture, specialists, Sonnet 4.6,
and guardrails are unchanged. No live AWS or paid model calls.

### Behavior delivered

1. Clean-venv `pip index` + install confirmed `strands-agents==1.52.0`,
   `bedrock-agentcore==1.21.0`, and `pydantic==2.13.4` are available together.
2. Installed Strands 1.52.0 exposes `Agent.invoke_async(...,
   structured_output_model=...)`, `AgentResult.structured_output`,
   `BedrockModel` guardrail kwargs including `guardrail_latest_message`,
   `tools=[]`, and Converse `messages`. `BedrockAgentCoreApp` + `@app.entrypoint`
   construct without AWS.
3. `scripts/diagnostics/check_agentcore_runtime_dependencies.py` inspects
   those APIs, validates a synthetic `CoachTurnOutput`, and checks Sonnet
   constructor kwargs. It does not call AWS or `specialist_invoke()`.
4. Provenance constants in `agentcore_runtime/model.py` stay explicit (a
   .py-only copy must still report pins). Pytest fails if they drift from
   `agentcore_runtime/requirements.txt`.
5. Mock CI job `agentcore-runtime-compatibility` installs the runtime
   requirements on Python 3.12, runs the diagnostic, and compiles
   `agentcore_runtime`. Companion pytest remains Strands-free.

### Main files changed

- `agentcore_runtime/requirements.txt`, `agentcore_runtime/model.py`
- `scripts/diagnostics/check_agentcore_runtime_dependencies.py`
- `.github/workflows/mock-ci.yml`
- Tests: `tests/domain/test_runtime_model.py` pin-sync assertions
- Docs: this file, AgentCore adapter, scripts/tests agent guides

### Validation evidence

- Clean CPython 3.12.10 venv `/tmp/codesign-agentcore-runtime-fresh`:
  `pip install -r agentcore_runtime/requirements.txt` **succeeded**.
- `python scripts/diagnostics/check_agentcore_runtime_dependencies.py`:
  **passed** (Strands 1.52.0, bedrock-agentcore 1.21.0, pydantic 2.13.4;
  structured_output_model, AgentResult.structured_output, and
  guardrail_latest_message present; Sonnet id explicit; no AWS).
- Imports of `agentcore_runtime.main`, `.model`, `.models`, and
  `.structured_coach` succeeded. `specialist_invoke()` was not called.
- `compileall` for `backend`, `ui`, `streamlit_app.py`, `tests`, `scripts`,
  and `agentcore_runtime`: **passed**.
- Full deterministic suite: **737 passed, 0 failed, 0 skipped** (735 prior
  plus two pin-sync tests). Starlette/httpx deprecation warnings unchanged
  in kind.
- Focused AgentCore / RAG / ownership / stage files: **201 passed**.
- `ruff check .` (ruff 0.11.13): **passed**.
- `git diff --check`: **passed**.
- `docker compose config --quiet`: **passed**.
- `APP_IMAGE=co-design:test docker compose -f compose.prod.yaml config --quiet`:
  **passed**.
- GitHub Mock CI on committed HEAD `529716c`: mock-suite **success**
  (https://github.com/CloudKai/NUS-Codesign-Chatbot/actions/runs/31900754387).
  New job `agentcore-runtime-compatibility` is local-only until this change
  is pushed: **CI CONFIGURED — RUN NOT YET OBSERVED** for that job.
- No live AgentCore, Bedrock generation, OpenAI, KB Retrieve, DSQL, or S3
  calls. Runtime not republished. `AGENTCORE_RUNTIME_ARN` unchanged.

### Compatibility, migration, and rollback

- No schema change. Five persisted stages unchanged. No runtime publish.
- `AGENTCORE_RUNTIME_ARN` unchanged. Do not promote DEFAULT until a new
  READY qualifier is tested with a capped Sonnet 4.6 smoke.

### Known risks and next exact action

- Publish `agentcore_runtime/` onto
  `NUSCodesignChatbot_chatbot_harnessAgent-6ncEO79sD7` with explicit Sonnet
  4.6 + guardrail env, then one capped smoke. Not done in this pass.

## Previous phase — Explicit Sonnet 4.6 runtime model and guardrail fail-closed

**Completed locally on 2026-08-16.** Integrate-Bedrock HEAD at start of this
pass: `af79a693347a33ebbd9c92c5a33c297df70ce05b`. The runtime no longer
constructs a bare `BedrockModel()`. Production AgentCore requires explicit
`AGENTCORE_MODEL_PROVIDER` / `AGENTCORE_MODEL_ID` / `AGENTCORE_MODEL_REGION`
plus `GUARDRAIL_ID` / `GUARDRAIL_VERSION`. First paid evaluation remains
Sonnet 4.6. Luna is optional, stateless, and uses ApplyGuardrail. No live
AWS generation or runtime publish in this pass.

### Behavior delivered

1. `agentcore_runtime/model.py` fail-closed loader. Bedrock path uses
   `guardrail_latest_message=True`. Luna cannot be passed to `BedrockModel`.
2. Mantle/Luna path: `OpenAIResponsesModel(stateful=False,
   bedrock_mantle_config={"region": ...})` plus ApplyGuardrail on input and
   output. Missing `strands-agents[openai]` does not fall back to Claude.
3. FastAPI production validation requires the same model and guardrail keys
   when `MODEL_PROVIDER=agentcore`.
4. Runtime pins: `strands-agents==1.52.0`, `bedrock-agentcore==1.21.0`,
   `pydantic==2.13.4` (companion-tested Pydantic; Strands/AgentCore pins are
   current documented PyPI versions, not yet installed in the companion venv).

### Main files changed

- `agentcore_runtime/model.py`, `guardrails.py`, `main.py`, `requirements.txt`
- `backend/settings.py`, `backend/specialists/routing.py`
- Tests: `tests/domain/test_runtime_model.py` and production-config updates
- Docs: AgentCore adapter, security boundaries, methodology, implementation status

### Validation evidence

- `compileall` for `backend`, `ui`, `streamlit_app.py`, `tests`, `scripts`,
  and `agentcore_runtime`: **passed**.
- Full deterministic suite: **735 passed, 0 failed, 0 skipped** in 32.10s.
  66 Starlette/httpx deprecation warnings.
- `ruff check .`: **passed** after removing unused imports (including
  pre-existing F401/F541/F811/E402 that would have failed CI).
- `git diff --check`: **passed**.
- `docker compose config --quiet`: **passed**.
- `APP_IMAGE=co-design:test docker compose -f compose.prod.yaml config --quiet`:
  **passed**.
- Live KB diagnostic: refused without `--i-approve-live-bedrock` (no Retrieve).
- No live AgentCore, Bedrock generation, or OpenAI calls. Runtime not
  republished. `AGENTCORE_RUNTIME_ARN` unchanged.

### Compatibility, migration, and rollback

- No schema change. Five persisted stages unchanged.
- Live DEFAULT still needs this package published onto
  `NUSCodesignChatbot_chatbot_harnessAgent-6ncEO79sD7` with runtime env
  injected. Do not promote DEFAULT until READY and a capped Sonnet smoke.

### Known risks and next exact action

- Confirm pins on the published runtime. Run the opt-in KB diagnostic, then a
  new READY qualifier, then a capped Sonnet 4.6 specialist test.
- Do not commit, push, or deploy from this phase unless asked.

## Previous phase — AgentCore specialist brain (POC pedagogy, production shell)

**Completed locally on 2026-08-16.** Integrate-Bedrock remains the production
application shell. Canonical Q&A, Coaching, and Formative Review pedagogy now
lives in `agentcore_runtime/`. FastAPI authorizes sources, retrieves evidence,
sends runtime rules, validates structured output, and persists DSQL state.
AgentCore Memory is not the transcript. Live AWS invokes were not made.

### Behavior delivered

1. One AgentCore runtime, three specialists, deterministic `phase` selection.
   Unknown phases fall closed to coaching. Scoring was renamed Review and is
   not a grade. Ambiguous chat defaults to coaching.
2. Canonical prompts in `agentcore_runtime/prompts/` merge POC Socratic /
   Assumption Check / AT-EAI stage focus with Integrate-Bedrock V&V, CLEAR,
   Facione, HCTSR-aligned Reflection, and research independence.
3. FastAPI AgentCore payload sends `runtime_context` plus runtime instructions
   only. Stage curriculum is no longer duplicated on the trusted channel.
4. Strands structured output for `coach_turn`, `qa_turn`, and `review_turn`.
   DSQL history is passed as Strands `messages`. `tools=[]`.
5. Q&A uses pre-retrieved `[S#]` evidence. No KB/S3 tools. Review is on-demand
   from explicit student intent, not every turn.

### Main files changed

- `agentcore_runtime/` specialists, prompts, contracts, `main.py`
- `backend/specialists/routing.py`, `backend/agentcore_provider.py`,
  `backend/coaching/execution.py`, `backend/mock_provider.py`,
  `backend/domain.py`
- Tests listed in `tests/AGENTS.md`
- Docs: prompt, RAG, security, AgentCore adapter, implementation status

### Validation evidence

- `compileall` for `backend`, `ui`, `streamlit_app.py`, `tests`, `scripts`,
  and `agentcore_runtime`: **passed**.
- Full deterministic suite: **710 passed, 0 failed, 0 skipped** in ~30s.
  Existing Starlette/httpx deprecation warnings only.
- Ruff on files from this phase: **passed**.
- `git diff --check`: **passed**.
- `docker compose config --quiet`: **passed**.
- No live AgentCore, Bedrock generation, or OpenAI calls. Runtime not
  republished. `AGENTCORE_RUNTIME_ARN` unchanged.

### Compatibility, migration, and rollback

- No schema change. Five persisted stages unchanged. `ethics_critical` remains
  an AgentCore topic key only.
- Live DEFAULT still needs this package published onto
  `NUSCodesignChatbot_chatbot_harnessAgent-6ncEO79sD7`. Copy the whole
  `agentcore_runtime/` tree. Rollback is the previous READY qualifier.
- `backend/prompts/` remains for mock/OpenAI/Bedrock Converse.

### Known risks and next exact action

- Publish the runtime after approval, then one paid smoke. Do not run live
  specialist evaluation until that publish.
- Do not commit, push, or deploy from this phase unless asked.

## Previous phase — AgentCore structured coach_turn output (no str(AgentResult))

**Completed locally on 2026-08-16.** Live coaching could fail after
`await agent.invoke_async(prompt)` because the deployed harness did
`json.loads(str(result))`. `str(AgentResult)` is empty when
`structured_output` is absent and the final message has no text blocks, which
raises `JSONDecodeError` at char 0. The student contribution was not empty.
This is independent of the earlier `guardrail_intervened` / `PROMPT_ATTACK`
path; those trusted/untrusted and `safety_blocked` fixes stay.

Architecture is unchanged: DSQL transcript, full-history planner, RAG
authorization, AgentCore reasoning-only (`tools=[]`), five Thinking Path
stages, research independence, and atomic persist.

### Behavior delivered

1. Canonical production harness lives in `agentcore_runtime/` (`models.py`,
   `structured_coach.py`, `main.py`). `scripts/agentcore/harness_patch/` is a
   re-export plus deploy notes.
2. Native Strands path: `invoke_async(..., structured_output_model=CoachTurnOutput)`
   then `result.structured_output`. Text-block JSON is a compatibility fallback.
   `str(result)` is never parsed.
3. Failures return `{ok: false, error: true, category: ...}`. The companion
   adapter maps that to `structured_output_failure` or `safety_blocked`.
   HTTP stays 503 with a category; students never see JSONDecodeError.
4. Idempotency still releases the lease on provider failure. Empty assistant
   bubbles are not opened until a validated reply exists; empty stored
   assistant rows are not rendered.
5. Stage advancement still requires a validated assessment. Short student
   text such as "A quiet residential street" is not treated as empty and is
   not hardcoded to ADVANCE.

### Main files changed

- `agentcore_runtime/` (new canonical harness)
- `backend/agentcore_provider.py`, `backend/providers.py`
- `ui/panels/chat.py`
- `scripts/agentcore/harness_patch/`, `scripts/build.sh`
- Tests: `tests/domain/test_agentcore_runtime.py`,
  `tests/domain/test_agentcore_provider.py`,
  `tests/domain/test_agentcore_harness_provider.py`,
  `tests/http/test_api.py`, `tests/http/test_api_client.py`,
  `tests/ui/test_streamlit_ui.py`
- Docs: `docs/providers/AGENTCORE_ADAPTER.md`, `docs/CODEBASE_STRUCTURE.md`,
  `tests/AGENTS.md`, `scripts/AGENTS.md`, `backend/AGENTS.md`

### Validation evidence

- `compileall` for `backend`, `ui`, `streamlit_app.py`, `tests`, `scripts`,
  and `agentcore_runtime`: **passed**.
- Full deterministic suite: **648 passed, 0 failed, 0 skipped** in ~27s.
  Existing Starlette/httpx deprecation warnings only (66).
- Ruff on files from this fix: **passed** except one pre-existing F811 in
  `tests/ui/test_streamlit_ui.py` (duplicate `StudentStore` import in an
  unrelated test).
- `git diff --check`: **passed**.
- No live AgentCore invoke. Runtime not republished. `AGENTCORE_RUNTIME_ARN`
  unchanged.

### Compatibility, migration, and rollback

- No schema change. Companion still accepts a raw coach_turn JSON body.
- Live DEFAULT still runs the old `str(result)` harness until operators copy
  `agentcore_runtime/` onto
  `NUSCodesignChatbot_chatbot_harnessAgent-6ncEO79sD7` and publish a READY
  version. Do not point DEFAULT at an untested version.
- Rollback is reverting this working tree; live runtime rollback is the
  previous READY qualifier.

### Known risks and next exact action

- Production blocker: publish the new harness version, then one approved
  smoke: `scripts/agentcore_smoke.py --i-approve-live-agentcore --cost-cap 1.00 --max-requests 1`,
  then the "A quiet residential street" regression.
- Do not change `AGENTCORE_RUNTIME_ARN`. Do not create another student runtime.
- Do not commit, push, or deploy from this phase unless asked.

## Previous phase — Virtual course sources must not become fake local evidence

**Completed locally on 2026-08-16.** Shared Week 1 catalog rows have empty
`extractedText` on purpose. When `KNOWLEDGE_BASE_ID` was missing, mock, or
`MOCK_OPENAI=true`, `configured_context_retriever()` returned
`LocalChunkRetriever`, which ranked the synthesized placeholder
`[This source is stored but has no analyzable text.]` because the Week 1
title matched the student question. That fake chunk reached AgentCore.

Architecture is unchanged: one shared S3 `course/` copy, virtual catalog
sources, Bedrock KB Retrieve only, student uploads local, FastAPI source
scope, DSQL transcript, AgentCore reasoning only.

### Behavior delivered

1. Virtual/shared `course/` sources keep `text=""` for retrieval. The
   unanalyzable placeholder is display-only for real empty student files.
2. `configured_context_retriever()` always returns
   `CompositeContextRetriever`. Missing KB / mock / `MOCK_OPENAI` injects
   `knowledge_base=None` instead of dumping course sources onto local chunks.
3. Missing or empty KB results become an application-owned evidence-gap note.
   Execution preserves that note after rebuilding context from validated
   chunks. The composer tells the model not to claim the PDF has no readable
   text and not to invent a summary.
4. Production with `COURSE_MATERIAL_SYNC_ENABLED=true` requires
   `KNOWLEDGE_BASE_ID`.
5. Opt-in `scripts/diagnostics/test_course_retrieval.py` can call live
   Retrieve only with `--i-approve-live-bedrock`. Pytest never runs it.
   No generation call.

### Main files changed

- `backend/retrieval.py`, `backend/bedrock_retrieve.py`,
  `backend/coaching/execution.py`, `backend/sources/context.py`,
  `backend/prompts/composer.py`, `backend/settings.py`
- Tests: `tests/domain/test_retrieval.py`,
  `tests/domain/test_bedrock_retrieve.py`,
  `tests/domain/test_source_library.py`,
  `tests/domain/test_prompt_architecture.py`,
  `tests/http/test_production_config.py`,
  `tests/scripts/test_agentcore_course_cli.py`
- Script: `scripts/diagnostics/test_course_retrieval.py`, `scripts/AGENTS.md`
- Docs: `docs/RAG_ARCHITECTURE.md`, `docs/SECURITY_BOUNDARIES.md`,
  `docs/deploy/AWS_STATELESS_EC2.md`, `docs/PROMPT_ARCHITECTURE.md`,
  `docs/LOCAL_DEMO_IMPLEMENTATION.md`, `.env.example`, `README.md`,
  `compose.prod.yaml`, `tests/AGENTS.md`

### Validation evidence

- `compileall` for `backend`, `ui`, `streamlit_app.py`, `tests`, and `scripts`:
  **passed**.
- Full deterministic suite: **618 passed, 0 failed, 0 skipped** in 27.86s.
  Existing Starlette/httpx deprecation warnings only (66).
- Ruff on files from this fix: **passed**. Repository-wide ruff still reports
  8 pre-existing unused-import issues outside this change.
- `git diff --check`: **passed**.
- `docker compose config --quiet`: **passed**.
- `docker compose -f compose.prod.yaml config --quiet`: **passed** with
  `APP_IMAGE` set (blank `APP_IMAGE` is invalid by design).
- No live Bedrock Retrieve call. No paid AgentCore/OpenAI generation call.

### Compatibility, migration, and rollback

- No schema change. Shared course files stay virtual; student uploads stay
  notebook-scoped. Rollback is reverting this working tree.
- Strict `course_material_id` metadata filter remains off until the live KB
  is re-ingested with that attribute. Unfiltered retry plus exact-key
  post-validation stays.

### Known risks and next exact action

- Live Knowledge Base Retrieve is not yet proven from this tree. Do not mark
  strict metadata mode as working until re-ingestion is verified.
- Next, only if explicitly approved:
  `.venv/bin/python scripts/diagnostics/test_course_retrieval.py --query "what are the week 1 contents talking about?" --source "Week 1 Introduction to innovation v3.pdf" --i-approve-live-bedrock`
- Do not run a paid AgentCore generation turn until Retrieve returns actual
  Week 1 text. Do not commit, push, or deploy from this phase unless asked.

## Previous completed phase — Live AgentCore DEFAULT coaching (harness patch + smoke)

**Completed on 2026-08-15.** `Integrate-Bedrock` is merged into `main`.
Production still uses `MODEL_PROVIDER=agentcore` against existing runtime
`NUSCodesignChatbot_chatbot_harnessAgent-6ncEO79sD7`. Qualifier remains
`DEFAULT`. No experimental student runtime.

The companion trust split was already in this repo; live DEFAULT still ran
pre-patch harness code until republished. First republish (version 8) 502'd
because `invoke` mixed `return json.loads(...)` with SSE `yield` (`SyntaxError:
'return' with value in async generator`). Version 9 splits JSON return and SSE
streaming into separate functions. Live JSON then failed validation on
`recommendation: "STAY"` and object-shaped `stage_assessment`; the domain
contract now coerces those live-model variants.

### Behavior delivered

1. Existing DEFAULT runtime updated in place to **version 9**, READY.
2. `coach_turn` invokes return unfenced JSON (no tools, no AgentCore Memory as
   transcript). Q&A SSE path is unchanged.
3. `EducationalAssessment` accepts uppercase `stay`/`advance` and flattens
   object `stage_assessment` (lifting strengths/improvements into review
   fields when present).
4. Runtime instructions tell the model `stage_assessment` is a string and
   `recommendation` is lowercase `stay` or `advance`.

### Main files changed

- Live harness (POC worktree, not this git tree): `chatbot_harnessAgent/main.py`
  split `_coach_turn_invoke` / `_stream_specialist_invoke`
- Companion: `backend/domain.py`, `backend/prompts/composer.py`,
  `backend/agentcore_harness_provider.py`,
  `scripts/agentcore/harness_patch/structured_coach.py`,
  `scripts/agentcore/harness_patch/README.md`, this status file
- Tests: `tests/domain/test_models_and_support.py`,
  `tests/domain/test_agentcore_provider.py`

### Validation evidence

- Focused deterministic tests for the coercion and AgentCore/prompt/harness
  contracts: **passed** (Starlette/httpx deprecation warnings only).
- Live capped smoke:
  `scripts/agentcore_smoke.py --i-approve-live-agentcore --cost-cap 1.00 --max-requests 1`
  returned `{"ok": true, "stage": "problem_identification", "recommendation": "stay"}`.
  Not a guardrail block. Not a 502.
- Local `/api/v1/ready` was `provider: agentcore` before restart; stack restarted
  after the domain coercion so UI turns use the same parser.

### Compatibility, migration, and rollback

- No database migration. Runtime ARN and `AGENTCORE_QUALIFIER=DEFAULT` unchanged.
- Rollback of the live runtime is pointing DEFAULT at version 7 (pre-patch) or
  8 (broken import). Version 9 is the working structured-coach code.
- Companion rollback is reverting this working tree; uppercase `STAY` would
  again fail closed as malformed.

### Localhost UI follow-up (2026-08-15)

Profile settings on http://127.0.0.1:8501/ : display name Kai Ming, appearance
System, language English, coaching style **Strict** (`response_detail=long`).
The first UI turns failed closed as generic “temporarily unavailable” because
`focused_excerpt` could return 601–602 characters (ellipsis around a 600-char
window) and `RetrievalChunkReference.excerpt` rejects that. Course retrieval
for this notebook returns mid-chunk matches, so the turn never reached
AgentCore. Excerpts are now clipped to the field limit, including ellipses.

A live Strict turn then succeeded on DEFAULT version 9: notebook title
**Elderly Road Safety**, stage stayed `problem_identification`, recommendation
`stay`, eight retrieval refs with excerpts ≤ 600 characters, Socratic reply
persisted. No mock fallback. No Claude.

Additional files: `backend/retrieval.py`, `tests/domain/test_retrieval.py`.
Focused retrieval tests: **17 passed**.

### Known risks and next exact action

- Empty assistant rows from earlier failed streams remain in this notebook;
  they are not used as transcript history for the successful turn.
- Live `review_strengths` can still be an empty list, so Journey may show
  “No feedback yet” even after a persisted assessment.
- Next: optional cleanup of empty failed-stream assistant rows, or prompt the
  structured coach to fill `review_strengths` / `review_improvements`. No mock
  fallback and no Claude calls. Production deploy of this merge keeps
  CloudFront as the only public hostname and Caddy `:80` with `/api/v1/auth/me`
  on the auth allow-list.

## Previous completed phase — AgentCore coaching availability, guardrail handling, trust split

**Completed locally on 2026-08-15.** Integrate-Bedrock remains the product.
Production `MODEL_PROVIDER=agentcore` still uses `InvokeAgentRuntime` and does
**not** change DEFAULT. Live AgentCore coaching was failing closed as a
malformed turn because runtime guardrail `PROMPT_ATTACK` blocked the composed
user payload, including a literal attack example in shared instructions. This
phase unblocks that path without disabling safety controls, then splits trusted
instructions from untrusted turn content.

### Behavior delivered

1. Shared coaching no longer contains a literal prompt-attack example.
   Quoted/retrieved override attempts remain untrusted evidence.
2. `AgentCoreCoachProvider` detects `guardrail_intervened` and guardrail
   `action=BLOCKED` before parsing model text. The failure is category-only
   (`safety_blocked`); refusal text, prompts, and AWS traces are not exposed
   or persisted.
3. FastAPI carries `{message, category}` on JSON 503 and `category` on stream
   error events. Streamlit shows student-safe copy that does not blame
   `scripts/start.sh` or claim the provider is down.
4. Composer exposes `trusted_instructions` and `untrusted_turn_text` while
   preserving ordered `composed_text` and the same length budget. AgentCore
   sends trusted instructions on a dedicated harness field and keeps DSQL
   history plus untrusted content in `messages`.
5. Harness patch appends `trusted_instructions` to the system prompt and
   invokes only untrusted user content. Older payloads that omit the field
   remain compatible. Isolated Luna eval uses the same split.
6. `requirements.txt` pins `boto3==1.43.35` and `botocore[crt]==1.43.35` so
   clean installs include AgentCore and `aws login` CRT credentials.

### Main files changed

- Prompts/adapters: `backend/prompts/shared/coaching.md`,
  `backend/prompts/composer.py`, `backend/providers.py`,
  `backend/agentcore_provider.py`, `backend/agentcore_harness_provider.py`,
  `backend/http/app.py`, `backend/api_client.py`, `ui/panels/chat.py`
- Harness: `scripts/agentcore/harness_patch/structured_coach.py`,
  `scripts/agentcore/harness_patch/README.md`
- Tests/docs: AgentCore, prompt, API, API-client, Streamlit tests; prompt,
  security, AgentCore, and this status file
- Dependencies: `requirements.txt`

### Validation evidence

- Full deterministic suite: **591 passed, 0 failed** (Starlette/httpx
  deprecation warnings only; classified as harmless test-client debt).
  `compileall` passed. `git diff --check` passed. No live AWS or paid OpenAI
  call from pytest.

### Compatibility, migration, and rollback

- No database migration. Production runtime ARN and `AGENTCORE_QUALIFIER=DEFAULT`
  are unchanged. No experimental student runtime.
- JSON 503 `detail` for provider failures is now `{message, category}` instead
  of a bare string. Stream error events add `category`.
- Rollback is reverting this working tree.

## Previous completed phase — Full-history-first planner, exact RAG keys, isolated Luna eval path

**Completed locally on 2026-08-15.** Integrate-Bedrock remains the product.
Production `MODEL_PROVIDER=agentcore` still uses `InvokeAgentRuntime` and
does **not** change DEFAULT. The last-six history cap is replaced by a
full-history-first token-aware planner. Compression is derived model context
only. Object-key matching is exact. Live pedagogical evaluation, when
approved, uses isolated InvokeHarness + GPT-5.6 Luna with zero Claude calls.

### Behavior delivered

1. `HistoryContextPlanner` sends the entire active DSQL transcript when it
   fits; otherwise extractive (production) or Luna (eval) compression plus a
   recent verbatim window. DSQL is never truncated.
2. Derived `conversation_memory` persists in notebook settings, stamped with
   `conversation_revision`, and is discarded after revise-and-resubmit.
3. Retrieve object keys match by canonical equality only. Nested
   `course_material_id` values distinguish same filenames in different folders.
   Strict metadata filter remains off until live KB metadata is verified.
4. Isolated `AgentCoreHarnessCoachProvider` asserts
   `openai.gpt-5.6-luna` / `responses` before every eval invoke. Production
   factory is unchanged.

### Main files changed

- Planner/eval: `backend/context_planner.py`, `backend/live_eval_config.py`,
  `backend/agentcore_harness_provider.py`, `backend/agentcore_provider.py`,
  `backend/prompts/composer.py`, `backend/coaching/execution.py`,
  `backend/workflow.py`, `scripts/evals/evaluate_live_coach.py`
- Retrieval: `backend/retrieval.py`, `backend/bedrock_retrieve.py`
- Docs: prompt, AgentCore, RAG, security, this status file

### Validation evidence

- Full deterministic suite: **579 passed, 0 failed** (Starlette/httpx deprecation
  warnings only; classified as harmless test-client debt). `compileall` passed.
  `git diff --check` passed. No live AWS or paid OpenAI call from pytest.

### Compatibility, migration, and rollback

- No database migration. `conversation_memory` is an additive settings key.
- Production DEFAULT and InvokeAgentRuntime ARN are unchanged.
- Rollback is reverting this working tree.

### Known risks and next exact action

- Live KB `course_material_id` metadata may still be absent; filter fallback
  remains. Local venv boto3 1.35.99 lacks `InvokeHarness` (need 1.43+ in the
  eval environment only). Production DEFAULT is unchanged.
- Next: after `aws login`, create or set `AGENTCORE_EVAL_HARNESS_ARN` for an
  isolated eval harness and run
  `.venv/bin/python scripts/evals/evaluate_live_coach.py --i-approve-live-luna --quick`.
  Do not commit/push or switch production DEFAULT unless asked.

## Previous completed phase — Ethics & CT integration, KB metadata filter, history de-dup

**Completed locally on 2026-08-15.** Integrate-Bedrock remains the product.
AgentCore is still a stateless reasoning adapter. Course Retrieve can send a
`course_material_id` metadata filter and still post-validates object keys.
AgentCore no longer duplicates DSQL history inside `<recent_messages>`. The
student-facing fourth stage is **Ethics & Critical Thinking** (persisted id
`deep_analysis`). Shared prompts now include the silent Socratic scaffold,
Assumption Check, and V&V lens. Co-occurrence is professor-only post-hoc
analytics.

### Behavior delivered

1. `compose_coach_prompt(..., include_recent_messages=False)` for AgentCore.
   Bounded DSQL turns travel as Converse `messages` only.
2. `BedrockKnowledgeBaseRetriever` filters by `course_material_id` when ids
   exist, retries without the filter if empty, then drops unselected keys.
3. Student-facing label for `deep_analysis` is Ethics & Critical Thinking /
   Ethics & CT. No sixth `ethics_critical` application stage.
4. Shared coaching prompt: Interpret → Assumption/V&V check → one probe →
   reflection trigger; untrusted-evidence rules strengthened.
5. Professor research summary includes read-only co-occurrence / co-absence.
   Research codes still do not advance stages or drive coaching.

### Main files changed

- Prompts/journey: `backend/prompts/shared/coaching.md`,
  `backend/prompts/stages/deep_analysis.md`, `backend/learning/stages.py`,
  `backend/prompts/composer.py`, `backend/agentcore_provider.py`
- Retrieval: `backend/retrieval.py`, `backend/bedrock_retrieve.py`,
  `backend/sources/library.py`, `backend/coaching/execution.py`
- Research/UI: `backend/professor_analytics/research.py`, `ui/professor.py`,
  `ui/auth_gate.py`
- Docs: `docs/RAG_ARCHITECTURE.md`, `docs/SECURITY_BOUNDARIES.md`,
  `docs/PROMPT_ARCHITECTURE.md`, `docs/providers/AGENTCORE_ADAPTER.md`,
  `docs/research/METHODOLOGY.md`

### Validation evidence

- Full deterministic suite: **558 passed, 0 failed**. Existing Starlette/httpx
  deprecation warnings. No live AWS or paid OpenAI call from pytest.
- `compileall` for `backend`, `ui`, `streamlit_app.py`, `tests`, and `scripts`
  passed.

### Compatibility, migration, and rollback

- No database migration. Internal stage id remains `deep_analysis`.
- Knowledge Base metadata `course_material_id` is recommended; without it the
  adapter falls back to unfiltered Retrieve plus object-key validation.
- Harness patch system prompt changed; redeploy DEFAULT if that overlay is
  used. Rollback is reverting this working tree.

### Known risks and next exact action

- Live AgentCore still streams prose until the harness patch is on DEFAULT
  READY. KB metadata filter is ineffective until course objects are
  re-ingested with `course_material_id`.
- Next: optional approved live smoke after harness JSON cutover. Do not
  commit/push/deploy from this phase unless asked.

## Previous completed phase — POC-style DSQL history messages + selected-source KB Retrieve

**Completed locally on 2026-08-15.** AgentCore invokes send bounded DSQL
history as Converse `messages` (POC Memory equivalent) while remaining
stateless. Locked Lecture Notes/Readings can use Bedrock Knowledge Base
`Retrieve` mapped onto selected `[S#]` labels. FastAPI/Streamlit/DSQL stay.
The coaching specialist still has zero KB tools.

### Behavior delivered

1. `AgentCoreCoachProvider` always sends `messages`: last six DSQL turns plus
   the composed current turn (and images). `student_id` is the store owner
   identifier, never a notebook id. `runtimeSessionId` stays `stateless-…`.
2. `BedrockKnowledgeBaseRetriever` calls `Retrieve` only, maps
   `s3://…/course/…` onto locked source `object_key` values, and drops foreign
   or unselected keys. `CompositeContextRetriever` keeps student uploads on
   `LocalChunkRetriever`.
3. `configured_context_retriever()` injects the composite when
   `KNOWLEDGE_BASE_ID` is set and the provider is not mock. Pytest keeps the
   local retriever.

### Main files changed

- `backend/agentcore_provider.py`, `backend/domain.py`,
  `backend/coaching/execution.py`, `backend/retrieval.py`,
  `backend/bedrock_retrieve.py`, `backend/owner_context.py`,
  `backend/settings.py`
- Tests: `tests/domain/test_agentcore_provider.py`,
  `tests/domain/test_bedrock_retrieve.py`, `tests/domain/test_retrieval.py`,
  `tests/conftest.py`
- Docs: `docs/providers/AGENTCORE_ADAPTER.md`,
  `docs/PROMPT_ARCHITECTURE.md`, `docs/LOCAL_DEMO_IMPLEMENTATION.md`,
  `.env.example`

### Validation evidence

- Full deterministic suite: **544 passed, 0 failed**. Existing Starlette/httpx
  deprecation warnings. No live AWS or paid OpenAI call from pytest.
- `compileall` for `backend`, `ui`, `streamlit_app.py`, `tests`, and `scripts`
  passed. `git diff --check` passed.

### Compatibility, migration, and rollback

- No schema change. Empty `KNOWLEDGE_BASE_ID` keeps local retrieval. Rollback
  is reverting this working tree.

### Known risks and next exact action

- Live AgentCore still streams prose until
  `scripts/agentcore/harness_patch/README.md` is applied and `DEFAULT` is
  READY. Set `KNOWLEDGE_BASE_ID=JUQNP8AZAZ` on EC2 after that cutover.
- Next: deploy the harness patch, then one approved
  `scripts/agentcore_smoke.py --i-approve-live-agentcore --cost-cap 1.00 --max-requests 1`.
  Never restore six stages.

## Previous completed phase — Strict coaching style by default

**Completed locally on 2026-08-15.** New notebooks and empty progress blobs
default to Strict coaching (`response_detail=long`). Students can still choose
Quick. Notebooks that already persisted Quick stay Quick.

### Behavior delivered

1. Canonical default is `DEFAULT_RESPONSE_DETAIL = "long"` in
   `backend/learning/journey.py`. Session, composer, store fallbacks, and the
   profile **Coaching style** control all use that constant.
2. Mock Strict still waits for a second follow-up before ADVANCE; Quick still
   advances after one. Two-turn HTTP fixtures pin Quick so they stay independent
   of the product default.
3. Streamlit AppTest confirmation/auto-advance paths send three turns so Strict
   can recommend the next stage.
4. Creating a notebook resets the profile **Coaching style** widget to Strict
   so a previous Quick choice cannot leak onto the new notebook. The selected
   chip uses the filled accent highlight.

### Main files changed

- Domain/UI: `backend/learning/journey.py`, `backend/student_store.py`,
  `backend/coaching/execution.py`, `backend/chat_service.py`,
  `backend/prompts/composer.py`, `ui/session.py`, `ui/profile.py`,
  `ui/notebooks.py`, `ui/panels/chat.py`, `ui/theme.py`,
  `ui/assets/styles/60-profile-topbar.css`
- Tests: `tests/domain/test_student_journey.py`, `tests/ui/test_streamlit_ui.py`,
  `tests/ui/test_streamlit_api_mode.py`, plus Quick pins in primary-path and HTTP
  two-turn ADVANCE tests
- Docs: `README.md`, `DESIGN.md`, `backend/AGENTS.md`, `ui/AGENTS.md`,
  `docs/IMPLEMENTATION_STATUS.md`

### Validation evidence

- Targeted journey, Streamlit, primary-path, and HTTP confirmation tests passed.
- Full deterministic suite: **536 passed, 0 failed**. Existing Starlette/httpx
  deprecation warnings. No live AWS or paid OpenAI call from pytest.
- `compileall` for `backend`, `ui`, `streamlit_app.py`, `tests`, and `scripts`
  passed. `git diff --check` passed.

### Compatibility, migration, and rollback

- No schema change. Empty `progress_text` now reads as Strict. Explicit
  `response_detail=short` notebooks are unchanged. Rollback is reverting this
  working tree.

### Known risks and next exact action

- Live AgentCore still streams prose until
  `scripts/agentcore/harness_patch/README.md` is applied and `DEFAULT` is
  READY on a new version.
- Next: deploy that harness patch, then one approved
  `scripts/agentcore_smoke.py --i-approve-live-agentcore --cost-cap 1.00 --max-requests 1`.
  Never restore six stages.

## Previous completed phase — DSQL-only transcript + student download

**Completed locally on 2026-08-15.** Aurora DSQL / SQLite `messages` remain the
only durable chat transcript. AgentCore stays generation-only (stateless
invokes). Students can download a `.txt` projection of persisted messages from
Notebook Actions. POC JSON, DynamoDB, and AgentCore session memory are not
used as chat history. A sixth Thinking Path stage is not added.

### Behavior delivered

1. Documented and tested that `AgentCoreCoachProvider` never reuses a notebook
   id as `runtimeSessionId`, never sends AgentCore Memory/history fields, and
   persists a valid turn only in `StudentStore` (no `poc_store.json`).
2. `GET /api/v1/threads/{thread_id}/transcript.txt` returns an attachment
   built from `get_messages` (Student/Coach labels, no assessment metadata).
   Foreign notebooks stay 404.
3. Notebook Actions offers **Download transcript** via the workspace facade /
   typed API client. Streamlit does not read SQLite.
4. Recorded deferred POC extras: deploy the existing harness `coach_turn`
   overlay; optional later “Ask the course” Retrieve mode mapped onto locked
   sources. Explicitly out of scope: scoring specialist replacement, critique
   every Nth turn, `ethics_critical` as a sixth stage, CDK student UI merge.

### Main files changed

- Export: `backend/workspace_service.py`, `backend/http/app.py`,
  `backend/api_client.py`, `ui/services/runtime.py`, `ui/notebooks.py`,
  `ui/assets/styles/50-dialogs-notebooks.css`
- Tests: `tests/domain/test_agentcore_provider.py`,
  `tests/http/test_workspace_api.py`, `tests/http/test_multiuser_ownership.py`,
  `tests/ui/test_streamlit_ui.py`, `tests/test_architecture_contracts.py`
- Docs: `docs/DATABASE.md`, `docs/LOCAL_DEMO_IMPLEMENTATION.md`,
  `docs/providers/AGENTCORE_ADAPTER.md`, `docs/deploy/AWS_STATELESS_EC2.md`,
  nested `AGENTS.md`

### Validation evidence

- Targeted: `tests/domain/test_agentcore_provider.py`,
  `tests/http/test_workspace_api.py`, `tests/http/test_multiuser_ownership.py`,
  `tests/test_architecture_contracts.py`, `tests/ui/test_streamlit_ui.py`
  passed.
- Full deterministic suite: **535 passed, 0 failed**. Existing
  Starlette/httpx deprecation warnings. No live AWS, Bedrock, AgentCore,
  Cognito, DSQL, S3, or paid OpenAI call from pytest.
- `compileall` for `backend`, `ui`, `streamlit_app.py`, `tests`, and `scripts`
  passed. `git diff --check` passed.

### Compatibility, migration, and rollback

- No database schema change. Transcript download is a read of existing
  `messages`. Rollback is reverting this working tree.

### Known risks and next exact action

- Live AgentCore still streams prose until
  `scripts/agentcore/harness_patch/README.md` is applied and `DEFAULT` is
  READY on a new version.
- Next: deploy that harness patch, then one approved
  `scripts/agentcore_smoke.py --i-approve-live-agentcore --cost-cap 1.00 --max-requests 1`.
  Do not add course Q&A or a scoring specialist until that cutover is done.
  Never restore six stages.

## Previous completed phase — AgentCore generation + shared course S3 keys

**Completed locally on 2026-08-14.** FastAPI/Streamlit remain the student
product. Production generation is `MODEL_PROVIDER=agentcore` (one
`InvokeAgentRuntime` per turn). Locked Lecture Notes/Readings reference shared
`course/` objects instead of copying PDFs into `users/`. Automated tests inject
fake clients and never call AWS.

### Behavior delivered

1. `AgentCoreCoachProvider` sends `phase=coaching`, composed CDE2300 prompt,
   and `output_contract=coach_turn`. `deep_analysis` maps to AgentCore topic
   `ethics_critical` only. Invokes are stateless. Images fail closed rather
   than being dropped. Errors are category-only.
2. POC harness overlay in `scripts/agentcore/harness_patch/` so the live
   coaching specialist returns `ProviderCoachOutput` JSON with zero KB tools.
3. Shared course sync lists `course/lectureNotes/` and `course/readings/`
   into the Sources panel. It does **not** insert one DSQL `sources` row per
   file on each new notebook. Older notebooks that already persisted locked
   rows keep them. PDFs stay under shared `course/` keys.
4. Production config accepts OpenAI xor Bedrock xor AgentCore. Course sync is
   allowed when `COURSE_MATERIALS_BUCKET` + `COURSE_MATERIALS_PREFIX=course/`
   are set (not `users/`).
5. Admin inventory (account `355604674280`, `us-west-2`): runtime
   `NUSCodesignChatbot_chatbot_harnessAgent-6ncEO79sD7` DEFAULT READY v6;
   gateway `gateway-course-materials-4cymlvixrt`; KB `JUQNP8AZAZ` data source
   `cde2300-course-content-s3`; uploaded 7 lecture PDFs + 3 readings to
   `course/lectureNotes/` and `course/readings/`; EC2 role
   `CDE2300ChatbotEC2Role` inline policy `AgentCore-Course-Materials`
   (invoke, Retrieve, course Get/List, no course delete).

### Main files changed

- New: `backend/agentcore_provider.py`, `tests/domain/test_agentcore_provider.py`,
  `scripts/agentcore/harness_patch/`, `scripts/agentcore_smoke.py`,
  `scripts/sync_course_materials.py`, `docs/providers/AGENTCORE_ADAPTER.md`
- Wiring: `backend/providers.py`, `backend/settings.py`, `backend/http/app.py`,
  `backend/sources/library.py`, `backend/persistence/*`
- Config/docs: `.env.example`, `compose.prod.yaml`, `docs/deploy/AWS_STATELESS_EC2.md`,
  `docs/PROMPT_ARCHITECTURE.md`

### Validation evidence

- Targeted: `tests/domain/test_agentcore_provider.py`,
  `tests/domain/test_source_library.py`,
  `tests/http/test_production_config.py`,
  `tests/test_deployment_config.py` passed.
- Full deterministic suite: **531 passed, 0 failed**. Existing
  Starlette/httpx deprecation warnings. No live AWS, Bedrock, AgentCore,
  Cognito, DSQL, S3, or paid OpenAI call from pytest.
- `compileall` for `backend`, `ui`, `streamlit_app.py`, `tests`, and `scripts`
  passed. `git diff --check` passed.

### Compatibility, migration, and rollback

- No database schema change. Default local provider remains `mock`.
- Host `.env` should set `MODEL_PROVIDER=agentcore`,
  `AGENTCORE_RUNTIME_ARN=arn:aws:bedrock-agentcore:us-west-2:355604674280:runtime/NUSCodesignChatbot_chatbot_harnessAgent-6ncEO79sD7`,
  `COURSE_MATERIALS_BUCKET=cde2300-course-content-s3`.
- Rollback: leave `.env` on `openai` or `bedrock` and set
  `COURSE_MATERIAL_SYNC_ENABLED=false`.

### Known risks and next exact action

- Live runtime still streams prose until
  `scripts/agentcore/harness_patch/README.md` is applied and `DEFAULT` is
  READY on a new version.
- Next: deploy that harness patch, then one approved
  `scripts/agentcore_smoke.py --i-approve-live-agentcore --cost-cap 1.00 --max-requests 1`.

## Previous completed phase — Amazon Bedrock coach adapter

**Completed locally on 2026-08-14.** The coach provider contract now includes a
Bedrock Converse adapter. Phase progression, citations, persistence, and
selected-source retrieval stay in the application. Automated tests inject a
fake client and never call AWS.

### Behavior delivered

1. `BedrockCoachProvider` makes one Converse call per turn with a required
   `coach_turn` tool whose schema is the provider-neutral
   `ProviderCoachOutput`. Markdown fences are not parsed as a fallback.
2. The persisted notebook phase overrides a model-supplied phase. Invalid
   coaching is rejected without persisting an assistant turn. Invalid research
   coding is dropped independently.
3. Images map from `CoachImageInput` data URLs to Converse image bytes;
   unsupported MIME types fail before the model call.
4. Provider exceptions map to category-only `ProviderUnavailableError`
   (throttled, timeout, access denied, model unavailable, malformed,
   truncated) without AWS bodies, credentials, prompts, or student content.
5. `MODEL_PROVIDER=bedrock` is selectable after contract tests. Production
   accepts OpenAI **or** Bedrock (not mock). Bedrock production requires
   `BEDROCK_MODEL_ID` and timeout/retry bounds and does not require
   `OPENAI_API_KEY`. Credentials stay on the AWS chain / EC2 role.

### Main files changed

- New: `backend/bedrock_provider.py`, `tests/domain/test_bedrock_provider.py`
- Wiring: `backend/providers.py`, `backend/settings.py`, `backend/http/app.py`
- Docs/config: `.env.example`, `README.md`, `docs/providers/BEDROCK_ADAPTER.md`,
  `docs/LOCAL_DEMO_IMPLEMENTATION.md`, `docs/deploy/AWS_STATELESS_EC2.md`,
  nested `AGENTS.md` maps

### Validation evidence

- Targeted: `tests/domain/test_bedrock_provider.py`,
  `tests/http/test_production_config.py`,
  `tests/domain/test_prompt_architecture.py` passed.
- Full deterministic suite: **501 passed, 0 failed**. Existing
  Starlette/httpx deprecation warnings. No live AWS, Bedrock, Cognito, DSQL,
  S3, or paid OpenAI call.
- `compileall` for `backend`, `ui`, `streamlit_app.py`, `tests`, and `scripts`
  passed. `git diff --check` passed.

### Compatibility, migration, and rollback

- No database schema change. Default local provider remains `mock`.
- Production can keep `MODEL_PROVIDER=openai` until Bedrock model access and
  IAM invoke are granted. Rollback is reverting this working tree and leaving
  `.env` on `openai` or `mock`.

### Known risks and next exact action

- The pinned boto3 Converse path uses strict tool use, not
  `outputConfig.textFormat`. Confirm the chosen model/inference profile
  supports tool use in `us-west-2` before a live smoke.
- Runtime IAM still needs `bedrock:InvokeModel` (and stream) on the exact
  model/profile ARN when switching production off OpenAI.
- Next: an explicitly approved live Bedrock smoke (one short request, stated
  model, token/request ceiling, and cost cap), then set production
  `MODEL_PROVIDER=bedrock` and remove `OPENAI_API_KEY` from the host `.env` if
  OpenAI is no longer used. Do not add a Bedrock Knowledge Base for coaching.

## Previous completed phase — port architecture package splits onto this branch

**Completed locally on 2026-08-14.** Package ownership on
`professor-analytics-ui` now matches the architecture-refactor *structure*
(façades, focused packages, grouped tests) without merging that branch. Five
research-aligned phases, professor analytics/Research, CSS, widget keys, and
routes are unchanged.

### Behavior delivered

1. **Contracts locked first.** `tests/test_architecture_contracts.py` snapshots
   this branch’s façade signatures, `StudentStore` public methods including
   research/review/audit/workflow-marker APIs, DSQL OCC writes including
   `append_research_*` / `set_system_metadata`, and the complete FastAPI route
   inventory including `/api/v1/professor/*`.
2. **Persistence seam only.** Store contracts, SQLite schema/migrations, and
   source operations live under `backend/persistence/store/`. Research
   observation/review/adjudication/audit SQL stays on `StudentStore`.
3. **One FastAPI composition root.** `create_app` and all student+professor
   routes live in `backend/http/app.py`. `backend/api.py` remains the import
   façade, including monkeypatch seams for Cognito readiness and
   `StudentStoreResearchRepository`.
4. **Learning and coaching packages.** Five phases live in
   `backend/learning/`; `CoachApplicationService` (including research-observation
   persist and quote-offset handling) lives in `backend/coaching/execution.py`.
   `backend/student_journey.py` and `backend/application.py` are façades.
5. **Streamlit presentation aliases.** Chat/sources/studio/runtime
   implementations live in `ui/panels/` and `ui/services/runtime.py`.
   `ui/professor.py` and professor CSS were not moved. Cookie helpers live in
   `ui/auth/cookies.py` with `_cookie_value` still patchable on `auth_gate`.
6. **DSQL CLI and tests.** Implementation is `scripts/dsql/cli.py` (five-phase
   marker + research DDL). `scripts/init_dsql.py` re-exports it. Tests are
   grouped under `domain/`, `http/`, `persistence/`, `ui/`, and `scripts/` with
   no `__init__.py`. Mock CI focused paths and compileall include `scripts/`.
7. **Source package.** `backend/sources/library.py` owns ingestion/course sync;
   `context.py` and `projection.py` own bounded context and image/storage
   projection. `backend/source_library.py` is a `sys.modules` alias.

### Main files changed

- New packages: `backend/http/`, `backend/learning/`, `backend/coaching/`,
  `backend/persistence/store/`, `backend/sources/`, `ui/panels/`,
  `ui/services/`, `ui/auth/`, `scripts/dsql/`.
- Compatibility façades: `backend/api.py`, `backend/application.py`,
  `backend/student_journey.py`, `backend/source_library.py`, `ui/chat.py`,
  `ui/sources.py`, `ui/studio.py`, `ui/runtime.py`, `scripts/init_dsql.py`.
- Tests: `tests/test_architecture_contracts.py`; existing scenarios relocated
  under subsystem directories; UI source-file assertions use `inspect.getfile`;
  DSQL workflow-contract patches target `scripts.dsql.cli`.
- Docs/guides: `docs/LOCAL_DEMO_IMPLEMENTATION.md`,
  `docs/CODEBASE_STRUCTURE.md`, `docs/TESTING.md`, nested `AGENTS.md`,
  `.github/workflows/mock-ci.yml`, `scripts/build.sh`.

### Validation evidence

- Architecture contract tests passed before and after each move.
- Complete deterministic suite: **462 passed, 0 failed** (456 prior tests plus
  6 architecture-contract tests); existing Starlette/httpx deprecation
  warnings; no live AWS/Cognito/DSQL/S3/provider or paid call.
- `compileall` for `backend`, `ui`, `streamlit_app.py`, `tests`, and `scripts`
  passed. `git diff --check` passed. Ruff is pinned in `requirements-dev.txt`
  but was not installed in this local venv, so Ruff is not claimed here.
- AppTest coverage for student Journey/Review and professor UI remains in the
  mock suite. An isolated `scripts/start.sh` browser session was not repeated
  in this pass.

### Compatibility, migration, and rollback

- No product, route, schema, authentication, provider/prompt, CSS, copy, or
  widget-key change. Historical import paths and monkeypatch targets remain.
- `codex/architecture-refactor` was used only as a pattern reference and was
  not merged (that branch’s six Facione stages and missing professor/research
  must not land here).
- No database write, migration, or learning-data reset. Rollback is reverting
  this working tree.

### Known risks and next exact action

- Aliases must keep replacing the module object (`sys.modules[__name__] = …`)
  or re-exporting the same function objects; rebinding names breaks patches.
- `StudentStore` remains large by design. Research SQL stays there so
  coach-turn persist stays atomic.
- If refactoring continues, start with one independently reviewed slice of
  `StudentStore` notebook/message operations or one closure-complete HTTP route
  registrar. Preserve the existing compatibility/OCC/route inventories first.

## Previous completed phase — research-aligned five-phase coach and lecturer validation

**Implemented on 2026-08-14.** The original Replit workflow, supplied system
architecture/V&V materials, and the cited research have been translated into a
provider-neutral coaching and research-coding boundary. Cognito, FastAPI,
SQLite/DSQL ownership, S3/local files, notebook history, Quick/Strict profiles,
source grounding, revisions, and the current student workspace remain the
application infrastructure; they were not reverted to the Replit architecture.

### Behavior delivered

1. Thinking Path now uses five research-aligned phases: Problem identification,
  Concept generation, Design specification, Deep analysis, and Reflection.
   The application still runs one LangGraph workflow, preserves confirmation,
   auto-advance, and Phase 2 selection rules, and derives UI totals/icons from
   the canonical phase definitions.
2. One structured provider result contains the normal coaching assessment and
  optional provisional research coding. The research section is independently
   soft-validated, so malformed/missing research data cannot discard a valid
   student turn. It records one dominant CLEAR strategy, at most two Facione
   behaviour occurrences, optional design-ethics concepts, and versioned
   provenance. It cannot award Facione points or move a phase.
3. Provider evidence quotes are transient. The application accepts only exact
  quotes from the current student utterance, converts them to half-open
   character offsets, persists offsets/rationale/confidence, and removes the
   quote-bearing provisional payload before graph checkpointing. Unmatched
   evidence fails closed without fabricating a code.
4. Only Reflection may contain a provisional holistic 1–4 candidate. Student
  Review exposes Facione behaviour occurrences and that clearly labelled
   candidate alongside the existing cumulative Quick/Strict Review; CLEAR and
   ethics labels remain lecturer research data.
5. Persisted `lecturer` and `admin` roles can access a protected professor
  Research workbench with aggregate summary, filtered/paged observation queue,
   attributable notebook transcript, immutable automated observations,
   append-only human reviews/adjudications, and formula-safe CSV. Reviewer and
   adjudicator IDs come from authenticated server context. Identifiable reads
   and exports write a bounded access audit first and fail closed if it fails.
6. SQLite and DSQL gained additive research observation, review,
  adjudication, access-audit, and system-metadata storage. Observations persist
   atomically with the coach turn, active queries exclude superseded revision
   branches, and notebook deletion follows explicit child-first predicates.
   DSQL write methods remain covered by the existing OCC retry boundary.
7. A workflow marker (`cde2300-five-phase-v1`) prevents silent reuse of
  semantically different six-stage data. Empty SQLite databases initialize it;
   DSQL bootstrap creates the additive schema and initializes the marker only
   when zero notebooks exist; non-empty unmarked databases remain unchanged and
   fail readiness. `scripts/reset_learning_data.py` provides dry-run inventory,
   checksum/staleness protection, exact confirmation, account preservation,
   WAL-safe SQLite backup, file quarantine, and owner-scoped DSQL/S3 deletion.
   **No reset was executed.**
8. Research definitions, limitations, human-validation requirements, and cited
  sources are recorded in
   `[research/METHODOLOGY.md](research/METHODOLOGY.md)`. Bedrock remains a
   future adapter only; `[providers/BEDROCK_ADAPTER.md](providers/BEDROCK_ADAPTER.md)`
   freezes its one-call structured contract without enabling AWS inference.
9. Persist-time Quick/Strict CAS and typed atomic auto-advance now protect the
  final coaching reply, confirmed transition, next journey, summary, and
   research observation as one database transaction. A direct/in-process coach
   path also rejects an unmarked legacy workflow before calling a provider.
10. Human review/adjudication fields use the same canonical CLEAR, Facione, and
  ethics enums as automated coding. The professor UI renders friendly labels
    while submitting normalized values; invented research codes fail at the
    typed API boundary.
11. The existing 14 Ruff findings were removed without runtime changes. Ruff is
  pinned in `requirements-dev.txt` and enforced by mock CI before tests.



### Main files changed

- Domain/workflow/provider/prompt: `backend/domain.py`, `workflow.py`,
`application.py`, `providers.py`, `mock_provider.py`, `student_journey.py`,
`prompts/`.
- Persistence/research: `backend/student_store.py`, `backend/persistence/`,
`backend/research/`.
- Lecturer boundary: `backend/professor_analytics/research.py`, `backend/api.py`,
`backend/api_client.py`, `ui/professor.py`, professor responsive CSS.
- Student projection: `ui/studio.py`, stage-derived notebook/session/chat UI.
- Operations/docs/tests: `scripts/reset_learning_data.py`, research/Bedrock/reset
documentation, `requirements-dev.txt`, mock CI, and deterministic domain,
persistence, API, UI, transaction-race, and reset tests.
- System overview deck:
`docs/CDE2300_Design_Thinking_Companion_System_Documentation.pptx`.



### Validation evidence

- Complete deterministic suite: **456 passed, 0 failed**; 65 framework
deprecation warnings; no live AWS/Cognito/DSQL/S3/provider or paid call.
- Research persistence/storage/professor focused gate: **40 passed**.
- Provider/application/research-coding focused gate: **41 passed**.
- Professor Research API/UI focused gate and the Streamlit workspace smoke passed.
- Atomic auto-advance/style/readiness regression file: **9 passed**; focused
API/idempotency/Streamlit integration: **55 passed**.
- DSQL bootstrap tests prove an empty database receives the exact five-phase
marker while populated unmarked data remains untouched and reset-gated.
- `compileall` for backend/UI/scripts/entrypoint/tests, `pip check`, full
`ruff check .` (**zero findings**), shell syntax, `git diff --check`, and
OpenAPI route inventory passed.
OpenAPI exposes exactly the six protected Research methods/paths.
- Both local and production Compose configurations passed.
- The system overview deck contains 13 slides and 13 source-note pages;
template-fidelity validation passed with zero issues, and every slide was
rendered and visually inspected. The overflow scan identified only the
inherited full-bleed closing-slide background, with no foreground text or
diagram outside the canvas.
- Isolated `scripts/start.sh` smoke with a temporary SQLite/files root and mock
provider: FastAPI `/health` and `/ready` returned 200; Streamlit
`/_stcore/health` returned `ok`; the processes were then stopped.
- A signed-in responsive browser review was not completed because the isolated
run had no authenticated student/lecturer browser session. AppTest and scoped
responsive-CSS contracts are the current UI evidence; this is not represented
as a completed human visual sign-off.



### Compatibility, migration, and rollback

- No Cognito, public student API, source, notebook, model-provider, or external
request/response contract was removed. Research routes/tables/metadata are
additive. Human decisions and automated observations are append-only.
- The phase model intentionally changes from six stages to five research
phases. Existing learning data is not heuristically relabelled. Use the
supported readiness-gated launcher and the explicit procedure in
`[operations/RESEARCH_DATA_RESET.md](operations/RESEARCH_DATA_RESET.md)`.
- SQLite apply is recoverable from its printed database backup and quarantine.
DSQL/S3 application spans external transactions and requires a separately
approved retention/recovery plan. No migration/reset has been applied here.



### Known risks and next exact action

- Automated CLEAR/Facione/ethics codes are provisional research observations,
not validated measures. Before a formal study, train human coders, sample and
double-code active utterances, calculate agreement, calibrate disagreements,
and document protocol/version changes.
- Run responsive Light/Dark browser QA for student Review and professor Research
with a persisted lecturer role when browser tooling is available.
- On a disposable copy of current data, run the reset command in dry-run mode,
review its manifest and recovery paths, then perform a five-phase mock smoke.
Do not apply it to live learning data without explicit approval.
- If Bedrock is selected next, implement only the adapter contract in
`docs/providers/BEDROCK_ADAPTER.md` with a fake SDK client first; any live
smoke needs an explicit model, request/token ceiling, and cost cap.



## Previous completed phase (historical)

**Production-grade repository audit and focused hardening.** The full layered
application, state ownership, persistence, Cognito boundary, provider adapters,
source ingestion, professor analytics, Streamlit presentation, deployment
configuration, tests, and canonical documentation were reviewed. No broad
folder move, schema migration, data rewrite, dependency addition, or product
redesign was justified.

### Changes in this phase

1. The public login-start limiter no longer creates an in-memory client entry
  for every rotated key after the global limit is full, and stale client
   windows are evicted. This closes an unauthenticated process-memory growth
   path while retaining the existing per-client/global behavior.
2. Client-provided `X-Request-ID` values are accepted only when they match a
  1–128 character correlation-ID allow-list. Invalid or oversized values are
   replaced with a UUID before response reflection or application logging.
3. `APP_ENV=production` now requires `USE_LOCAL_API=true` and rejects local
  code execution and repository course-material sync. These checks enforce the
   documented FastAPI authorization boundary and current DSQL/S3 ownership
   model even if host environment overrides drift from `compose.prod.yaml`.
4. OpenAI clients now use explicit `OPENAI_TIMEOUT_SECONDS` (default 110) and
  `OPENAI_MAX_RETRIES` (default 0). The structured provider validates its
   injected API key rather than consulting global settings during each call;
   the legacy local-only path receives the same bounded client policy.
5. Dynamic values entering raw professor/profile HTML are attribute/text
  escaped. Professor UI one-line render blocks were expanded for maintainable
   review without changing the visual design.
6. README ownership wording now matches the implemented production API
  boundary. The dated manual-production report is explicitly historical and
   its four broken local links now resolve to canonical repository documents.



### Validation evidence

- Focused API, configuration, provider, limiter, legacy-provider, professor UI,
and Streamlit suites → **111 passed**.
- `.venv/bin/python -m pytest -q` → **415 passed** (deterministic; no live
OpenAI, AWS, Cognito, DSQL, S3, or paid calls).
- `.venv/bin/python -m pip check` → no broken requirements.
- `compileall` for `backend`, `ui`, `streamlit_app.py`, and `tests`;
`git diff --check`; API import/route smoke → passed.
- Isolated mock startup on alternate localhost ports with a temporary SQLite
root: FastAPI `/health` and `/ready` returned 200; Streamlit
`/_stcore/health` returned `ok`. Existing processes on the canonical
8000/8501 ports were left untouched.
- Static top-level import audit: 79 modules, zero cycles, zero backend→UI edges.
- Ruff is configured in `pyproject.toml` but not installed in the project
virtual environment; mypy is neither configured nor installed. Neither is
claimed as executed.



### Compatibility, rollback, and remaining risk

- No database or file migration. Existing notebooks, revisions, messages,
sources, assessments, and Cognito identities are untouched. Rollback is a
code/config revert.
- No live DSQL/AWS or authenticated production-browser smoke was authorized or
run. Professor class endpoints still aggregate one full active message batch
in Python; query count is constant and appropriate for the 80–100 student
pilot, but production DSQL latency must be measured before wider scale.
- The webpage importer validates DNS and redirects but does not pin the
validated address through connection establishment; DNS-rebinding-resistant
transport remains required before treating arbitrary URL import as a strong
network sandbox.
- The single-process rate limiters intentionally do not coordinate across
replicas. Move them to a shared limiter before horizontal scaling.



### Next exact action

Complete the existing Aurora DSQL revision-schema cutover and the guarded live
idempotency smoke described below. Then run a read-only professor analytics
latency/contract check and authenticated desktop/mobile browser QA against the
deployed lecturer account. Do not open class traffic before those checks pass.

### Prior auth phase (still true)

**Production edge: CloudFront viewer TLS → Caddy HTTP origin.** CloudFront at
``d1sxfuoybzedj5.cloudfront.net`` is now the sole production hostname. Caddy
listens on EC2 port 80 as the route-security boundary; host port 443 and the
retired dynamic-DNS updater are removed. Both Compose contracts, CI deployment
tests, Cognito callback examples, operational docs, and manual QA now use the
CloudFront topology.

### CloudFront/Caddy edge alignment (completed)

1. CloudFront owns viewer HTTPS; Caddy accepts origin HTTP on ``:80`` and keeps
   the auth/health allow-list plus the catch-all ``/api/*`` 404 boundary.
2. ``compose.yaml`` and ``compose.prod.yaml`` use the CloudFront UI/API origin
   and Cognito callback. Neither publishes host port 443.
3. The obsolete host address-updater scripts and their secret-ignore rules were
   removed. A deterministic deployment test rejects their return in runtime,
   workflow, or documentation files.
4. CI's production configuration gate is explicitly named for the
   CloudFront/Caddy contract.
5. No database, DSQL, S3, Cognito resource, or student-data migration is
   required. Rollback is a code/config revert, but must not restore a second
   public hostname after Cognito and CloudFront cutover.

Validation: deployment/config/auth tests **50 passed**; full mock suite
**401 passed**; compileall, shell syntax, both Compose config validations, and
``git diff --check`` passed. No live AWS, DSQL, S3, Cognito, or paid-provider
call was made.

Next exact action: deploy the immutable image, restrict EC2 TCP 80 ingress to
the AWS-managed CloudFront origin-facing prefix list, verify the distribution
uses caching disabled plus full cookie/query/WebSocket forwarding, then run
``docs/security/CADDY_PUBLIC_BOUNDARY.md`` and the authenticated production
smoke. Do not open host TCP 443.

### Prior auth phase (still true)

**Auth: restore Cognito refresh after 1-hour ID cookie expiry.** The
non-sensitive Path=/ ``co_design_session`` hint now limits refresh attempts to
browsers with an established session. Cold visitors go directly to Sign in;
expired sessions see the app skeleton and centered loader while the refresh
bridge runs once; a Sign in launch cannot be intercepted by that bridge.

### Prior UI phase (still true)

**UI: fragment-scoped Streamlit reruns (local interactions).** Explicit
`rerun_app()` / `rerun_fragment()` helpers replaced the ambiguous
`rerun()`. Sources select/search/sort/upload/delete, Journey preview
toggles, Guidance Level, response language, and display-name avatar stay
panel-local; notebook/auth/coach/layout/stage-select/**Appearance theme**
remain full-app. Debug counters: `_app_runs`, `_sources_fragment_runs`,
`_studio_fragment_runs`, `_topbar_guidance_fragment_runs`,
`_topbar_profile_fragment_runs`.

### Full-app actions that remain intentional

- Notebook create / switch / rename / delete
- Auth / sign-in cooldown / logout
- Coach send / revise / composer model changes
- Workspace column collapse / mobile panel layout
- Sources course-sync stable ↔ polling fragment remount
- Thinking Path stage selection and transition confirm
- Appearance theme (entrypoint `render_theme_css`)

1. **Full mock suite.** `.venv/bin/python -m pytest -q` → **397 passed**.



### Auth refresh fix (this pass)

1. `should_attempt_session_refresh` no longer requires a live `co_design_id`
  cookie before redirecting to `/api/v1/auth/refresh`.
2. Login/refresh/logout set or clear `co_design_session` (Path=/, Max-Age 30d,
  non-sensitive `1`) alongside the Cognito token cookies.
3. Focused auth suites + full mock `pytest` green.



### Prior UI hardening

1. **Explicit edit retry.** On revise failure, clear `pending_edit` so the next
  rerun does not auto-resubmit; keep the stable `get_retry_key` UUID; restore
   the in-bubble draft; require Send to retry.
2. **Studio sanitized errors.** Stage-select and transition-confirm failures log
  internals and show fixed student-safe messages (no `str(exc)`).
3. **Full mock suite (prior).** `.venv/bin/python -m pytest -q` → **393 passed**.



### Prior production-hardening (still true)

Append-only edit remains (no DELETE truncate). DSQL revision migration is
resumable/idempotent (DEFAULT + batched NULL backfill). Ownership stays
`messages.notebook_id → notebooks.user_id → users.id`.

### Hardening behavior changes (revision pass)

1. **DSQL revision migration.** `scripts/init_dsql.py` inspects
  `information_schema` name **and** `column_default`, repairs missing
   DEFAULT 0, and batch-backfills NULL `conversation_revision` (1000 rows /
   transaction) for notebooks and messages. Safe to re-run; never app startup.
2. **Stable revise retry.** Streamlit keeps one UUID idempotency key (via
  `get_retry_key` scope `revise:{message_id}`) until success; provider-
   failure retries resume without a second revision bump. After a failed
   attempt the UI requires an explicit Send (`pending_edit` cleared).
3. **Active-branch pending rejects.** `select_learning_stage` only rejects
  `decision_status='pending'` rows active at the current revision.
4. **Conversation revision (internal).** Stored revision stays zero-based;
  student UI does not show a Conversation NN label.
5. **No destructive message content update.** `StudentStore.update_message`
  raises; edits go through append-only revise only.



### Prior append-only phase (still true)

1. **Active-branch chat.** Discussion renders only active messages for the
  notebook's current `conversation_revision`; superseded turns stay durable
   for revision history / reporting.
2. **Edit confirm copy.** Editing an earlier user turn states that a new
  conversation revision/branch is created; later turns leave the active view
   but remain in revision history (no truncate/delete claims).
3. **Post-edit reload.** Successful revise reloads journey state and reruns so
  `get_messages` shows the new active branch.
4. **Message revision columns (backend contract).** Messages carry
  `conversation_revision`, `previous_message_id`, and
   `superseded_at_revision`; ownership stays
   `messages.notebook_id → notebooks.user_id → users.id`.
5. **Assessment fields (expected).** User rows and the fixed coach welcome have
  `assessment_text = NULL`; assessed coach assistant replies store
   `assessment_text` JSON. Do not treat welcome NULL assessment as a failure.
6. **Sources panel.** My Sources → Lecture Notes → Readings; course materials
  lock-only; Select all + Sort for personal uploads.



### PART 1 root-cause evidence (“only welcome” on DSQL) — code inspection

No live DSQL verification was run for this writeup.

**Primary mechanism (code evidence):**

- UI welcome seed (`ui/coach_welcome.py` → `store.add_message`) persists a fixed
assistant welcome through the workspace CRUD path **without** the coach
workflow / `persist_coach_turn` CAS.
- Coach turns persist via `CoachApplicationService` → `persist_coach_turn`.
At branch baseline `6b54923`, this path required
`notebooks.conversation_revision` for CAS while the simpler welcome insert
did not.
- **Welcome-only root cause from code inspection:** an older DSQL cluster
missing `notebooks.conversation_revision` could accept the independently
committed welcome, then roll back every real coaching turn when
`persist_coach_turn` reached its revision CAS.
- The new implementation also reads/writes the three message revision columns
from normal and welcome inserts. Missing message columns are therefore a
deployment failure prerequisite, not evidence that the new app will still
seed a welcome successfully. Run admin `scripts/init_dsql.py` before
deploying the new image.

**Secondary diagnostics (not claimed verified live):** wrong `DSQL_ENDPOINT`,
database name, runtime role/owner (`DSQL_USER` not `co_design_app`), or
`.env`/Compose config mismatch can produce empty or partial notebooks and
should be checked after confirming schema columns exist.

### Owner reporting JOIN (do not denormalize messages)

```sql
SELECT
  u.id AS user_pk,
  u.identifier,
  u.cognito_sub,
  n.id AS notebook_id,
  n.conversation_revision AS notebook_revision,
  m.id AS message_id,
  m.role,
  m.conversation_revision AS message_revision,
  m.previous_message_id,
  m.superseded_at_revision,
  m.assessment_text,
  m.created_at
FROM messages m
JOIN notebooks n ON n.id = m.notebook_id
JOIN users u ON u.id = n.user_id
WHERE n.id = :notebook_id
ORDER BY m.created_at, m.id;
```



### Files changed (this append-only phase)

- `backend/student_store.py`, `backend/application.py`,
`backend/chat_service.py`, `backend/repositories.py`, and
`backend/workspace_service.py` — append-only persistence, snapshots, CAS,
retry recovery, and legacy compatibility.
- `backend/api.py`, `backend/api_client.py`, and `backend/domain.py` —
append-only contract documentation.
- `backend/persistence/dsql_schema.py` and `scripts/init_dsql.py` — fresh
schema plus catalog-driven additive DSQL migration.
- `ui/chat.py`, `ui/assets/styles/30-chat.css`, and `ui/AGENTS.md` —
Conversation label, edit warning, and failure fall-through.
- Revision, migration, idempotency, store, legacy-engine, and UI regression
tests were updated under `tests/`.
- `docs/IMPLEMENTATION_STATUS.md` and
`docs/deploy/AWS_STATELESS_EC2.md` — migration, reporting, evidence, and
deployment steps.

`tests/test_conversation_revision.py` asserts append-only semantics
(`previous_message_id` lineage, `superseded_at_revision`, active
`get_messages` / `get_messages_at_revision(0)` = Conversation 01, provider-
failure retention, stale CAS, revoked keys, pending supersede, API ownership,
DSQL message columns, `assessment_text` on assessed assistants only).

### Validation evidence

- Integrated revision/storage/UI selection:
`.venv/bin/python -m pytest -q tests/test_conversation_revision.py tests/test_init_dsql.py tests/test_coach_idempotency.py tests/test_streamlit_ui.py tests/test_student_store.py tests/test_storage_providers.py tests/test_learning_service.py` → **115
passed** (deterministic mocks; 2026-08-10).
- Full suite: `.venv/bin/python -m pytest -q` → **381 passed**.
- Compile: `PYTHONPYCACHEPREFIX=/private/tmp/co-design-pycache .venv/bin/python -m compileall -q backend ui streamlit_app.py tests scripts`
→ passed.
- Patch integrity: `git diff --check` → passed.
- IDE diagnostics on edited Python modules: no errors.
- Paid OpenAI / live AWS calls: not run.



### Compatibility / migration / rollback

- Additive only: existing message rows backfill to revision `0` with
`superseded_at_revision` NULL; display stays Conversation 01 until an edit.
- DSQL: admin manual DDL / `init_dsql.py` catalog path only — **app startup
never DDL**. See `docs/deploy/AWS_STATELESS_EC2.md`.
- Rollback: revert the application image/code; older code ignores the additive
columns and retained historical rows. Avoid `DROP COLUMN` on live student
data. Use the pre-migration backup/cluster snapshot if physical schema
rollback is required. SQLite migrations are additive on open.



### Known risks / blockers

- Existing DSQL clusters must receive the additive notebook/message revision
migration before this application version is deployed. Runtime cannot repair
missing columns and app startup intentionally performs no DDL.
- The migration and behavior are covered by deterministic mocks, not a live
DSQL write. No live browser/upload/RAG QA is claimed in this phase.



### Next exact action

**Stop architecture/feature edits.** Proceed only with live AWS / DSQL cutover:

1. Confirm host `.env` has `DSQL_ENDPOINT`, `AWS_REGION=us-west-2`, and
  admin identity available for DbConnectAdmin. Take a DSQL snapshot/export.
2. On the existing Aurora DSQL cluster, as admin only:
  `DSQL_ENDPOINT=<hostname> AWS_REGION=us-west-2 \\    .venv/bin/python scripts/init_dsql.py --admin-user admin`
   Then `GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public  TO co_design_app;` (no schema USAGE). Re-run is safe/idempotent.
3. With separate live-write approval, run
  `scripts/smoke_dsql_idempotency.py --confirm-live --identifier  'cognito:<sub>'` as `DSQL_USER=co_design_app`.
4. Redeploy ARM64 ECR image; require internal `/api/v1/ready` 200; run the
  Cognito → notebook → coach → upload → edit/revise → restart smoke in
   `docs/deploy/AWS_STATELESS_EC2.md` (mock first; OpenAI only with cost cap).



### Prior pilot context (Phases 1–14)

**Phases 1–13 complete on** `Production-RemoveData`**; Phase 14 verdict:
READY FOR CONTROLLED PILOT.** Live manual production QA documented in
`docs/MANUAL_PRODUCTION_QA.md` (2026-08-10). **Month-1 product policy:**
`AUTO_ADVANCE_STAGES=true` and `STUDENT_STAGE_SELECTION=false` in
`compose.prod.yaml` (coach ADVANCE applies without Next; no Journey stage
pick controls). **Month-2+ operator flip:** set `STUDENT_STAGE_SELECTION=true`
and `AUTO_ADVANCE_STAGES=false` — Journey shows audited **Work on this stage**
(`POST .../learning-state/select-stage`); if both flags are true, selection
wins and auto-advance is treated as off. Health `mode` now follows
`APP_ENV`. Login-start rate limit and allow-listed Cognito callback error
logging added. Coach chat shows a **thinking** status while the buffered
provider turn runs (early NDJSON `status`); true token streaming remains
deferred. For lower wait times keep Guidance short, reasoning low, and avoid
extra selected sources. **Edit message** (pre–append-only) used
server-authoritative `POST .../messages/{id}/revise` with
`conversation_revision` CAS and a **new** idempotency key; that path is being
replaced by append-only revision history on this branch. Regenerate remains
unavailable.

### Behavior changes (Phases 1–13)

1. Concurrent identical coach idempotency keys converge to one provider
  execution; completed markers replay without false lease-lost errors.
2. `APP_ENV=production` fail-closes via `validate_production_configuration()`
  at `create_app` and `/api/v1/ready`.
3. `/api/v1/ready` checks config, DB ping, file-store ping, provider
  credential shape, and Cognito HTTPS config without paid LLM calls.
4. `compose.prod.yaml` sets `APP_ENV=production`, json-file log rotation
  (10m × 3), and `no-new-privileges` on `app`/`caddy`.
5. `backend/rate_limit.py` provides single-EC2 in-process coach limits
  (`MAX_ACTIVE_COACH_REQUESTS_PER_USER=1`, `COACH_REQUESTS_PER_MINUTE=8`,
   `MAX_CONCURRENT_MODEL_CALLS=20`) wired into `coach_turn` /
   `coach_turn_stream` using authenticated `owner.store.owner_id`. HTTP
   429 includes `Retry-After`; slots release in `finally`.
6. Uploads: Streamlit `maxUploadSize=10`; API rejects excess file count and
  bounds each `upload.read(max+1)`.
7. Coach info logs omit notebook/thread ids and message text; request IDs and
  aggregates remain.
8. Caddy adds HSTS / nosniff / Referrer-Policy / Permissions-Policy (no CSP).
  Curl checks live in `docs/security/CADDY_PUBLIC_BOUNDARY.md`.
9. `requirements.txt` uses exact pins; Mock CI runs shell/compose/compile,
  production + idempotency gates, and full pytest.
10. `scripts/load_probe.py` + `docs/operations/LOAD_PROBE.md`; AWS smoke
  checklist expanded; `docs/deploy/GITHUB_BRANCH_PROTECTION.md`; public PDF
    audit lists 10 normal-blob lecture/reading PDFs (no LFS).



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
4. Cognito logout derives the trusted same-origin `/oauth2/revoke` endpoint
  when discovery omits it. Unknown JWKS key IDs have a bounded forced-refresh
   window, avoiding unauthenticated network amplification. Expired OAuth login
   states are cleaned during new-state insertion.
5. Production readiness now verifies the configured file store, bounded S3
  list access, and SELECT access to all five required DSQL tables. The DSQL
   schema expresses non-primary uniqueness as explicit `CREATE UNIQUE INDEX  ASYNC` jobs that bootstrap waits for.
6. The adapter-configured OpenAI model is authoritative. Response
  language reaches the prompt, reasoning effort restores per notebook, and
   selected sources force model-knowledge fallback off. Request/image limits
   are enforced at the API/application boundary.
7. User-message **Edit** uses inline bubble Save → server
  `revise_and_resubmit` (append-only conversation revision, stage/journey
   recompute, `conversation_revision` CAS, new idempotency key). Regenerate
   remains unavailable. Normal send/stream retries use the durable idempotency
   contract described below.
8. Production documentation now uses `compose.prod.yaml`/ECR and makes S3
  setup/readiness explicit. The default stateful Compose stack is labelled
   local-only; Bedrock permissions are not required in this phase.
9. Selected-source concatenation is replaced by a provider-neutral retrieval
  port and deterministic local chunk retriever. It uses sentence-aware chunks,
   current-turn-weighted lexical ranking, bounded conversation/project
   continuity, source diversity, stable `[S#]` labels, image markers, and
   strict context budgets in both preferred API and legacy development paths.
10. Assistant messages persist structured `retrieval_refs` for audit while
  `source_refs` remains limited to sources actually cited. Citation previews
   focus on matching evidence. Application code rebuilds prompt context only
   from validated chunks and rejects source IDs/labels outside the selected
   notebook, preserving the future Bedrock adapter boundary.
11. Live Aurora DSQL bootstrap corrections: async index waits now execute
  `CALL sys.wait_for_job(?)` on a dedicated verify-full admin connection
   with `autocommit=True`; DDL remains one transaction per connection. The
   unsupported `GRANT USAGE ON SCHEMA public` was removed, leaving only
   SELECT/INSERT/UPDATE/DELETE on all application tables in `public`.
12. Local legacy SQLite upgrades are additive and idempotent. The migration no
  longer renames/drops `users` (which previously cascaded deletion into
    legacy tables); it copies old threads, chat steps, source rows, stage state,
    and extracted source text into the five application tables while retaining
    the legacy rows as a rollback source. Legacy local source paths still
    preview/download, and copied extracted text remains available to the same
    provider-neutral local retriever used by new sources.
13. Cognito-scoped stores reconcile legacy/noncanonical identities and repair
  the earlier split-owner layout without dropping notebooks. Streamlit also
    reuses the first verified `/auth/me` result instead of making a second
    authentication request on every rerun.
14. Sign-in now uses a dialog-owned button callback instead of a fragment-owned
  callback. After the click, the original button remains the only visible
    sign-in control, is disabled for five seconds while the visible
    `Redirecting...` status is shown, and automatically becomes a retry
    button if Cognito navigation stalls.
15. Local startup repairs the broken `notebooks.user_id -> users_legacy`
  foreign key left by the retired destructive user migration. The SQLite-only
    rebuild is transactional, preserves notebook/message/source IDs, checks for
    orphaned notebooks before commit, and is idempotent. DSQL schema SQL is not
    changed.
16. The deterministic mock provider now makes retrieved grounding visible in
  its normal reply by quoting one bounded validated chunk and emitting its
    stable `[S#]` label. The existing citation resolver persists and renders
    the corresponding source reference without test-only monkeypatching.
17. Chat-composer attachment failures render a recoverable in-chat error and do
  not submit a coaching turn. Authoritative source selection now enables
    broader model knowledge only when no source is selected, so stale notebook
    metadata cannot contradict the visible UI mode.
18. API-mode course-material sync snapshots the short-lived Cognito ID cookie
  on Streamlit's render thread before starting its background worker. This
    prevents the worker losing browser context, resolving the fallback owner,
    and retrying a protected notebook sync with 404 every second.
19. Coach submission now accepts a validated idempotency key in the typed body
  and standard HTTP header. A durable owner/notebook-scoped reservation in
    the existing `messages` table prevents concurrent/restarted retries from
    calling the provider or inserting the turn twice, replays the exact
    completed `CoachTurn`, rejects changed-input key reuse with HTTP 409, and
    releases provider failures for a real retry. Lease ownership is verified in
    the same transaction that persists the user/assistant pair. No sixth table
    or DSQL schema change was introduced.
20. Production `/api/v1/ready` now also validates non-secret Cognito callback
  and metadata configuration locally, requires an HTTPS callback, and redacts
    DSQL/S3 exception details. Structured internal operational events cover
    route latency/status, provider/retrieval/citation results, coach stage
    recommendations, and accepted/rejected progression without prompts, source
    text, user/notebook/source/transition IDs, emails, or tokens.
21. A deterministic authenticated FastAPI production-parity regression covers
  Cognito cookie verification, notebook/source upload-selection-preview,
    grounded `[S1]` replies, idempotent replay/conflict, stage confirmation,
    process restart, object cleanup, and logout/revocation. A headed Playwright
    smoke runner preserves the real Cognito boundary and captures desktop,
    390 px mobile, and console evidence after a manually completed Hosted UI
    sign-in; it never installs a production auth bypass.
22. Streamlit retry keys now retain only a SHA-256 request scope, UUID, notebook
  id, and timestamp for one hour. The helper reuses unresolved retries, removes
    completed/deleted/expired entries, keeps at most eight per notebook and 24
    globally, preserves valid entries across notebook switches, and migrates
    only the active valid legacy entry without retaining raw prompt text.
23. The Cognito sign-in retry cooldown is server-authoritative. An absolute
  five-second deadline and a temporary 0.5-second Streamlit fragment keep the
    original button disabled without client-side DOM mutation. A bounded,
    non-sensitive per-tab query marker carries that exact deadline across a
    fresh Streamlit session after browser Back, then is consumed once; malformed,
    stale, or implausibly future values are rejected. The launch flag remains
    one-shot, and success, sign-out, logout, or configuration failure clears all
    transient state. Trusted auth navigation now uses Streamlit 1.60's
    non-iframed `st.html` API instead of the deprecated components helper.
24. DSQL idempotency tests now exercise two independent adapter instances,
  exact replay after restart, changed-payload conflict, provider-failure
    release, expired-lease takeover, stale-worker rejection, and whole-operation
    SQLSTATE `40001` retry without AWS. The guarded live runner requires
    `--confirm-live`, the DSQL provider, `co_design_app`, and an explicit
    `cognito:<sub>` owner; it uses runtime DML and the mock provider only.
25. Coach idempotency `complete_coach_request` is now idempotent when a waiter
  or restart already promoted the marker to `completed` from persisted
    message rows after the lease owner committed `persist_coach_turn` but
    before the owner completed. Matching key/fingerprint completed markers
    return successfully; expired takeover, provider-failure release, stale
    persist rejection, restart promotion, and DSQL OCC wrappers stay unchanged.
26. `APP_ENV` defaults to `development`. When `APP_ENV=production`,
  `validate_production_configuration()` fail-closes for mock provider,
    `MOCK_OPENAI` masking, sqlite/local/memory storage, DSQL admin runtime,
    insecure auth cookies, HTTP Cognito callbacks, incomplete Cognito/DSQL/S3/
    OpenAI configuration, and loopback or non-HTTPS public API/UI URLs. It
    reuses `validate_storage_configuration` and
    `validate_cognito_readiness(require_https=True)` with no network/AWS
    calls. `create_app` and `/api/v1/ready` both invoke it; readiness keeps
    a dual-gate for legacy dsql/s3 Cognito HTTPS checks during cutover.
    `compose.prod.yaml` and `.env.example` declare the env switch.



### Validation evidence

**Local (Phases 4–8 — this phase):**

- `.venv/bin/python -m pytest -q tests/test_rate_limit.py tests/test_production_config.py tests/test_coach_idempotency.py tests/test_api.py` → **64 passed**. Upload hardening covered by
`tests/test_upload_hardening.py`; compose/Caddy assertions in
`tests/test_deployment_config.py`.
- Branch `Production-RemoveData`; no commit created in this phase.
- Phase 1–2 uncommitted work preserved.

**Local (Phase 2 — APP_ENV production fail-closed):**

- Focused suite → **39 passed** (1 warning: Starlette TestClient deprecation):
  ```sh
  .venv/bin/python -m pytest \
    tests/test_production_config.py \
    tests/test_api.py::test_local_api_ready_request_id_stream_and_graph \
    tests/test_api.py::test_readiness_fails_when_file_storage_is_unavailable \
    tests/test_api.py::test_production_readiness_requires_local_cognito_configuration_check \
    tests/test_api.py::test_production_readiness_redacts_dependency_error_details \
    tests/test_api.py::test_production_readiness_reports_cognito_configured_without_discovery \
    tests/test_deployment_config.py \
    tests/test_storage_providers.py::test_validate_storage_configuration_requires_production_fields \
    tests/test_cognito_token_jwks.py::test_production_cognito_readiness_is_local_and_requires_https_callback \
    tests/test_cognito_token_jwks.py::test_cognito_readiness_errors_do_not_echo_credentials
  ```
- `tests/test_production_config.py` alone → **21 passed**.
- `tests/test_deployment_config.py` alone → **10 passed**.
- No live OpenAI, DSQL, S3, or Bedrock calls. No schema migration.
- Branch `Production-RemoveData`; no commit created in this phase.
- Phase 1 uncommitted files (`backend/student_store.py`,
`tests/test_coach_idempotency.py`) preserved.

**Local (Phase 1 — promote-vs-complete idempotency):**

- `.venv/bin/python -m pytest -q tests/test_coach_idempotency.py` → **15 passed**.
- Focused coverage added for promote-between-persist-and-complete, five-way
concurrent same-key submissions, and API/stream HTTP 409 payload mismatch.
- No live OpenAI, DSQL, S3, or Bedrock calls. No schema migration.
- Branch `Production-RemoveData`; no commit created in this phase.

**Prior local (previous production hardening phase):**

- `.venv/bin/python -m pytest -q` → **305 passed**.
- Focused auth/UI/production-path validation → **57 passed**.
- `PYTHONPYCACHEPREFIX=/private/tmp/co-design-pycache .venv/bin/python -m compileall -q backend ui streamlit_app.py tests` → exit 0.
- `docker compose config --quiet` and
`APP_IMAGE=co-design:test docker compose -f compose.prod.yaml config --quiet`
→ exit 0.
- `sh -n scripts/start.sh scripts/start_prod.sh scripts/build.sh scripts/deploy_ecr.sh scripts/browser_e2e_smoke.sh` → exit 0; the Python
DSQL runner compiled, displayed `--help`, and refused a missing
`--confirm-live` before any connection attempt.
- `git diff --check` → exit 0.
- No live OpenAI, DSQL, S3, or Bedrock calls. No Bedrock implementation
changes.
- The approved live-click smoke performed no credential entry: two clicks
produced exactly two FastAPI login redirects and two Cognito Hosted UI GETs.
Browser Back was invoked 2.7 seconds after the first click; the slow Streamlit
reconnect completed after the five-second window with `Redirecting...`
retained and the original button enabled, proving the deadline was not
restarted. The retry remained visible at 390 px and redirected exactly once.
AppTest covers the complementary fast-remount case where Back completes before
expiry and the same button must remain disabled.
- With the developer-authorized test account, the in-app browser completed the
real Cognito Hosted UI PKCE login and callback, created/renamed a notebook,
synchronized 7 lecture notes and 3 readings, displayed a grounded mock reply
and `[S1]` citation preview, confirmed Focus → Evidence, restored the chat
and stage after refresh, rendered Review scores, deleted the disposable
notebook, and logged out.
- The live run reproduced and then verified the local foreign-key repair and
authenticated background-sync fix. After cleanup, the test owner again had
zero notebooks, messages, and sources.
- `data/backups/co_design.pre-fk-repair-20260809.sqlite3` is the pre-migration
SQLite backup. It is local data and must never be committed.



### Compatibility, rollback, and known risks

- New S3 objects use `raw/` and `derived/` subpaths. Existing rows retain
their full historical keys, remain readable, and stay within the same
source/notebook deletion prefix. No object migration is required.
- DSQL bootstrap schema changed before live initialization. If an earlier
draft schema was already applied, inspect existing uniqueness/index state
before rerunning bootstrap; never drop production objects automatically.
- This DSQL bootstrap correction changes no table or index DDL. An earlier
failed public-schema `USAGE` grant needs no rollback; rerun bootstrap, then
apply only the documented object-level runtime grant.
- Public clients that sent unrestricted notebook/message metadata now receive
422 and must use the typed settings or internal coaching endpoints.
- RAG requires no schema migration. New assistant/user metadata may include
`retrieval_refs`; older messages without it remain compatible.
- The current local retriever reads selected extracted text and chunks it at
query time. This is deterministic and suitable for the bounded development
corpus, but it is lexical rather than embedding-semantic and is not the
long-term large-corpus index. Bedrock Knowledge Bases replaces this adapter.
- UI edit/regenerate stays unavailable until a transactional replacement
design is implemented; the new request key protects retries of normal turns
but does not define edit-in-place semantics.
- Existing local legacy tables are intentionally retained and left unchanged;
rollback is a code revert because the older application ignores the added
snake_case columns and the new five-table copies. A pre-existing database
that already ran the earlier destructive users-table migration cannot have
deleted legacy rows reconstructed from SQLite metadata; restore such rows
from a pre-upgrade backup if available. Local upload files themselves are not
deleted or rewritten by this migration.
- Split-owner repair preserves the authenticated Cognito row, moves any
five-table notebooks onto it, merges preferences, and retains the obsolete
empty row under a `legacy-orphan:<id>` identifier for inspection rather
than deleting it.
- The SQLite foreign-key repair applies only when `notebooks.user_id` targets
a table other than `users` and only when the known eight-column notebook
layout matches. An unknown layout stops with a clear error instead of losing
data. Restore the pre-repair backup to roll back the local database.
- This local compatibility phase changes no DSQL schema/bootstrap SQL, IAM,
S3, Cognito infrastructure, EC2, paid-provider, or Bedrock behavior.
- Provider-token streaming is still simulated after a complete persisted turn
and graph inspection state is process-local. Durable request idempotency now
makes a disconnected stream safe to retry, but it does not turn the buffered
response into upstream token streaming or persist graph inspection state.
- Completed idempotency reservations are stored as hidden internal rows in the
existing `messages` table. No migration is required and current code omits
them from chat/history/counts/activity. Rolling back to code that predates
this filter can expose blank internal assistant rows; back up first and remove
only rows explicitly marked `_internal_type=coach_idempotency` under an
approved rollback procedure.
- The promote-vs-complete fix changes only `complete_coach_request` behavior
for already-completed same-key/fingerprint markers. No schema or data
migration is required; rollback is a code revert.
- `APP_ENV` and `validate_production_configuration` are additive. Local
development remains the default; production Compose must set
`APP_ENV=production`. Rollback is a code/config revert with no schema or
data migration.
- Fully automated protected-browser CI remains blocked by the deliberate lack
of a production authentication bypass and by the uncached Playwright CLI.
`scripts/browser_e2e_smoke.sh` therefore pauses for a human to complete the
real Cognito Hosted UI before mobile/console capture. The deterministic
authenticated HTTP regression and Streamlit AppTests run without live AWS.
- UI retry-key records are session-only and require no migration. Reverting the
helper drops retry reuse after a disconnected Streamlit submission but does
not change durable notebook/chat data or the HTTP idempotency contract.
- The DSQL concurrency suite uses independent `DsqlStudentStore` instances
over an isolated SQLite transaction proxy, so it deterministically checks the
adapter/lease/OCC contract without claiming wire-level Aurora behavior. The
guarded live runner remains deliberately unexecuted until DSQL is ready and a
separate live-write approval is given.
- Fresh Streamlit loads and ordinary reloads have a clean browser console. The
in-app browser records React hydration errors `#418`/`#423` while restoring
Streamlit itself from cross-origin browser history; the recovered page remains
functional and no new error is emitted after it settles. The deprecated auth
components iframe was removed, but eliminating this framework-level history
artifact requires an upstream Streamlit/browser fix rather than more auth
state mutation.
- The cooldown query marker contains only an epoch deadline, is scoped to one
tab's URL, is accepted for at most a 30-second restore grace, and never
authorizes a user or changes OAuth state. No API, cookie, schema, or data
migration is required; rollback is limited to the two auth UI/test files.
- Rollback is a code/config revert. Do not commit `.env`, secrets, database
files, or uploaded content. No live AWS resource was created or modified.



### Next exact action

Authoritative next steps for append-only revision are under **Current phase →
Next exact action** above. Continuing AWS cutover after that:

1. Configure GitHub branch protection per
  `docs/deploy/GITHUB_BRANCH_PROTECTION.md`.
2. Owner decision on public lecture PDFs per
  `docs/security/PUBLIC_REPOSITORY_CONTENT_AUDIT.md` (do not delete/rewrite
   without explicit approval).
3. Create the private S3 uploads bucket in `us-west-2` with Block Public
  Access; attach bucket list plus `users/*` object permissions to the EC2
   instance role.
4. Finish Aurora DSQL, map the EC2 role to `co_design_app`, run
  `scripts/init_dsql.py` as admin (or for existing clusters apply the
   manual notebook `conversation_revision` **and** three message revision
   column `ALTER`s in `docs/deploy/AWS_STATELESS_EC2.md`), then grant
   SELECT/INSERT/UPDATE/DELETE on all tables in `public` to
   `co_design_app`. Do not grant schema `USAGE`. App startup never DDL.
5. With separate live-write approval, run
  `scripts/smoke_dsql_idempotency.py --confirm-live --identifier  'cognito:<sub>'` under `DATABASE_PROVIDER=dsql` and
   `DSQL_USER=co_design_app`.
6. Deploy the immutable ECR image with `scripts/deploy_ecr.sh` and require
  internal `/api/v1/ready` 200. Verify Caddy edge curl checks in
   `docs/security/CADDY_PUBLIC_BOUNDARY.md`.
7. Run the full Cognito → notebook → coach → upload → edit/revise → restart →
  isolation → logout live smoke in `docs/deploy/AWS_STATELESS_EC2.md`. Use
   mock mode first; make an OpenAI request only with explicit approval and a
   cost cap.
8. Only after that smoke is green: open class-wide traffic; then consider
  durable provider streaming and Bedrock retrieval adapters.



## Previous completed work

**Professor Learning Analytics Dashboard (implementation; local deterministic validation)**

### What changed

- Added a read-only `backend/professor_analytics` layer with typed API
contracts, one batch active-branch repository query per analytics snapshot,
and pure aggregation/service rules. It uses existing `users`,
`notebooks`, and `messages.assessment_text` data only; no table, column,
index, event tracking, DSQL migration, model call, or application write was
added.
- Added internal FastAPI routes below `/api/v1/professor` for Overview,
Students, selected Student detail, a separately requested active transcript,
Critical Thinking, and Engagement. Routes require a verified Cognito ID-token cookie
and reload the persisted user role; only existing `lecturer` and `admin`
roles pass. Anonymous requests receive 401 and students receive 403 even if
they call the URL directly.
- Added typed `LocalApiClient` methods and a dedicated Streamlit professor
shell. The shell branches before student notebook/session initialisation and
uses FastAPI only—never a store, model provider, filesystem, or DSQL client.
It implements Overview, Students + detail, Critical Thinking, and Engagement
with compact tables, labelled bar charts, neutral attention reasons, empty
states, and the established IBM Plex/slate/teal visual system.
- Active analytics excludes internal idempotency markers and messages outside
the notebook's current conversation revision. Class rosters exclude
lecturer/admin accounts and the unauthenticated `local-student` bootstrap
row.
- Final Sol review corrected the internal-row SQL predicate so ordinary API
turns carrying `coach_idempotency_key` remain visible; only rows whose
`_internal_type` is `coach_idempotency` are excluded. It also corrected
conversation counts, primary-notebook Facione scope, per-notebook sessions,
Not-started distribution, inactivity age, deterministic summary claims, and
equal-per-student weekly trends. Transcript bodies now load only after a
professor selects one notebook, and database failures return a sanitised 503.
- Engagement now reports the count/share of assessed coach responses with at
least one persisted source citation. This is labelled as source grounding,
not evidence that a student read or understood a source.



### Calculation definitions

- `Active this week` means at least one active-branch student message in the
previous seven days. Current stage is the most recently active notebook's
persisted stage; a student with no notebook is `Not started`.
- Overall Facione is the mean of the latest assessed response's non-zero
persisted dimensions (0 means not started). Class and dimension profiles use
medians of one latest profile per assessed student; absent values stay `Not assessed` rather than becoming 0.0.
- Estimated active time groups student messages within each notebook when gaps
are at most 30 minutes. Each session contributes its span with a five-minute
minimum. It is labelled estimated active time, not time spent.
- Attention is centrally configured and transparent: no activity in seven
days (including an account at least seven days old with no activity), Focus
after eight turns in the current notebook, twelve current-notebook turns
with at most one completed stage, or latest overall Facione below 2.0 after
at least three scored dimensions. These are prompts for follow-up, not a
judgement of ability.



### Validation evidence

- `.venv/bin/python -m pytest -q tests/test_professor_analytics.py tests/test_professor_ui.py tests/test_auth_gate.py tests/test_streamlit_ui.py` → **64 passed**
(deterministic SQLite/Fake Cognito only; no network or model calls).
- Final-review focused suite (professor analytics/UI, API client, Caddy
boundary) → **26 passed**.
- `.venv/bin/python -m pytest -q` → **406 passed** (full deterministic
suite; no paid/model calls).
- `PYTHONPYCACHEPREFIX=/private/tmp/co-design-pycache .venv/bin/python -m compileall -q backend ui streamlit_app.py tests` → passed.
- `git diff --check` → passed at implementation checkpoint.
- Post-review UI polish (responsive navigation, non-deprecated dataframe
sizing, and light-theme time-series charts) was revalidated with
`tests/test_professor_analytics.py tests/test_professor_ui.py` → **9
passed**, plus `compileall` and `git diff --check` → passed.
- In-app browser review used the real professor UI against an isolated,
synthetic 82-student API-shaped dataset. Overview, Students, selected
Student detail, Critical Thinking, and Engagement were exercised at 1440 px;
Overview was also checked at 390 px. Final browser logs contained no errors.
Review images are under the current Codex visualizations artifact directory;
no real student records or authenticated AWS session were used.
-   A later full-suite rerun reached **404 passed, 2 failed**. Both failures are
  outside professor analytics and reflect concurrent deployment configuration
  drift: `tests/test_deployment_config.py` still expected the retired
  dynamic-DNS hostname and host port 443 Caddy shape while the working tree
  currently contains a CloudFront/port-80 configuration. Those user-owned
  deployment edits were not reverted or folded into this feature.
- New coverage asserts 401 anonymous, 403 student, 200 lecturer; persisted
role rather than client claims; active-branch Facione/session correctness;
missing dimensions; constant-count repository access rather than N+1; normal
API idempotency metadata, multi-notebook conversation/session/assessment
scope, new-student inactivity boundaries; and no notebook, message, or source
mutation from analytics routes.



### Compatibility / known limits / next action

- No existing student data changes. Rollback is a code-only revert; analytics
endpoints have no mutation path. DSQL production deployment remains gated by
the existing revision-schema cutover in the Current phase section above.
- Actual browser-presence/time-on-task, enrollment roster completeness,
normalized class-wide topics, causal learning impact, and source-reading
behavior remain intentionally unavailable. Notebook titles are shown as the
available discussion-topic proxy.
- Next: after the approved DSQL revision cutover, run a read-only live DSQL
contract/latency check, then repeat the completed desktop/mobile visual QA
with a real Cognito lecturer session. Synthetic screenshots are available,
but no live AWS, real-student-data, or production-auth claim is made.

**Provider-neutral stage prompts + retryable S3 cleanup** — `19f5d4e` on
`Production-RemoveData` (pushed). Local mock suite 232 passed; GitHub Mock CI
failed on missing CI `.env` before compose validation.

**Final pre-AWS hardening (Cognito / DSQL / student S3)** — Cognito ID
`token_use`, JWKS cache, DSQL `verify-full`, course-sync gate, orphan
object cleanup, ownership-in-write checks, `ca-certificates` in image.

**Multi-user FastAPI ownership + student S3 key isolation**

**Cognito-owned browser session + five-table persistence cleanup**

**DSQL bootstrap / adapter hardening**

**AWS stateless EC2 migration scaffolding**