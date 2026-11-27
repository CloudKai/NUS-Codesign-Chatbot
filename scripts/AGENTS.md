# Scripts agent guide

## Purpose

The `scripts/` directory contains shell and Python helpers for local
development, demo startup, and database initialization. These scripts wire
together the backend and Streamlit entrypoint; they do not contain product
logic.

## Read first

1. Root [`AGENTS.md`](../AGENTS.md) for data safety and Git rules.
2. [`docs/LOCAL_DEMO_IMPLEMENTATION.md`](../docs/LOCAL_DEMO_IMPLEMENTATION.md)
   if changing how the local demo starts or which services run.

## Script map

| Script | Purpose | Safety notes |
|---|---|---|
| `start.sh` | **Canonical launcher** — FastAPI `:8000` + Streamlit `:8501` with `USE_LOCAL_API=true` | Everyday path |
| `start_prod.sh` | Docker app entrypoint — both services on `0.0.0.0`, supervised together | Production container; sqlite/local still may use `/app/data`; DSQL+S3 does not |
| `aws/deploy_stack.sh` | Plan or apply the CloudFormation stacks in `infra/aws/` (app tier, edge monitoring) | **Dry run by default and makes no AWS call** (`--validate-remote` adds read-only `validate-template`). Applying needs `--apply` and `--confirm-account <12-digit-id>` that matches `sts get-caller-identity`; one flag alone is refused, as are `REPLACE_ME` placeholders. Parameter files stay outside Git. Design: [`docs/deploy/AWS_ARCHITECTURE_PROPOSAL.md`](../docs/deploy/AWS_ARCHITECTURE_PROPOSAL.md). Never run against a real account without explicit approval |
| `deploy_ecr.sh` | ECR login + `compose.prod.yaml` pull/up | Host-only; needs `APP_IMAGE` + IAM role |
| `build.sh` | Validation-only: static reader TypeScript/build + `compileall` + full mock `pytest` | Install reader dependencies first with `npm ci --ignore-scripts --prefix frontend`; **does not** initialize or modify the live DB |
| `init_db.py` | Explicit SQLite schema setup | Refuses existing DB unless `--force`; prefer `--database PATH` for new files |
| `init_dsql.py` | Compatibility CLI for `scripts/dsql/cli.py` admin bootstrap | One DDL per transaction; async-job `CALL` on dedicated autocommit connection; initializes the five-phase workflow marker only with zero notebooks; keeps research DDL; never app startup; not `co_design_app`. CloudShell SSL/IPv4 checklist: [`docs/deploy/AWS_STATELESS_EC2.md`](../docs/deploy/AWS_STATELESS_EC2.md) (§ CloudShell / laptop init_dsql checklist) |
| `smoke_dsql_idempotency.py` | Explicitly approved live DSQL runtime-role idempotency smoke | Requires `--confirm-live`, `DATABASE_PROVIDER=dsql`, `DSQL_USER=co_design_app`, and `--identifier cognito:<sub>`; mock provider only; no DDL/S3/Bedrock |
| `agentcore_smoke.py` | Explicitly approved one-request AgentCore coaching smoke | Requires `PYTHONPATH=.`, `--i-approve-live-agentcore`, positive `--cost-cap`, and `--max-requests 1`; no pytest path |
| Canonical harness | [`agentcore_runtime/`](../agentcore_runtime/) is the production specialist runtime (Q&A, Coaching, Review). Copy the **entire package** onto existing DEFAULT | Do not maintain a second live implementation in `scripts/agentcore/harness_patch/` |
| `diagnostics/check_agentcore_runtime_dependencies.py` | Network-free AgentCore runtime pin + Strands API check | Requires `pip install -r agentcore_runtime/requirements.txt`; no AWS, no `specialist_invoke()`; asserts `structured_output_model` and `structured_output_prompt` on `Agent.invoke_async` |
| `diagnostics/test_course_retrieval.py` | Explicitly approved Bedrock KB `Retrieve` diagnostic | `--dry-run` is safe without live approval; live requires `--i-approve-live-bedrock`. Uses the settings-derived filter mode (same as production) and prints it. `--second-source` exercises `in`. No generation |
| `diagnostics/check_knowledge_base_retrieve.py` | Structured KB Retrieve health check using the production adapter | Refuses live AWS by default; `--dry-run` is safe; live requires `--i-approve-live-bedrock` and `--max-requests` 1 or 2. Constructs the retriever with `metadata_filter_mode` from settings (never `strict_metadata_filter=False`). Prints the mode. `--second-source` previews/tests `in`. No generation |
| `sync_course_kb_metadata.py` | Generate Bedrock `course_material_id` sidecar JSON beside course objects | Dry-run default; `--confirm` uploads; `--write-local` writes sibling files; never writes `users/` |
| `diagnostics/check_course_kb_metadata.py` | Local sidecar identity preflight | Default never calls AWS; answers sidecar presence and canonical `course_material_id` match. `--i-approve-live-bedrock` is refused — ingestion and filtered Retrieve are documented in [`docs/KB_REQUIRED_MODE_RUNBOOK.md`](../docs/KB_REQUIRED_MODE_RUNBOOK.md) |
| `evals/evaluate_live_coach.py` | Isolated GPT-5.6 Luna InvokeHarness quality evaluation | Requires `--i-approve-live-luna`; never changes production DEFAULT; no pytest AWS path |
| `evals/evaluate_fast_chat_regression.py` | Fast-chat coaching behaviour regression | Safe by default; `--dry-run` inspects cases; live candidate execution requires `--i-approve-live-claude` plus `AGENTCORE_RUNTIME_ARN`; `--baseline-artifact` is optional and never invented; does not publish AgentCore |
| `evals/evaluate_combined_gate.py` | Offline gate, gate + Laya and gate + Laya + title-wording comparison over all gate messages, with Wilson 95% intervals | Offline only, no AWS or model call. Laya decisions come from stored `phase3d-work` results unless `--checkpoint` re-runs the local weights; the wording arm is a stub-model bound, not a measurement. Never fits or tunes a cutoff |
| `evals/evaluate_retrieval.py` (`--live-kb-gate`) | One Bedrock `Retrieve` per gate message through the production adapter: top validated score, result count, status and elapsed ms per id, for the head-to-head routing comparison | **Paid live mode, built and never run.** Needs `--max-live-calls N` (1 to 295), `KNOWLEDGE_BASE_ID` and `COURSE_MATERIALS_BUCKET`; refused (exit 2, no client) when combined with `--live-kb`, `--live-model`, row filters or `--compare-source-check`; exit 3 on the first auth or access error. `--extra-messages FILE` sends only anonymised extra rows (`synthetic: true` required unless `--allow-non-synthetic`). Records ids, scores, counts and timings, never message text. Needs IAM `bedrock:Retrieve` on the Knowledge Base. See [`docs/RETRIEVAL_EVAL.md`](../docs/RETRIEVAL_EVAL.md#head-to-head-routing-comparison-built-not-run) |
| `evals/evaluate_workspace_evidence.py` | Offline workspace-evidence retrieval evaluation (ticket 42) over the extended `workspace_evidence.synthetic.jsonl` corpus: production gate agreement (with/without borderline rows), precision/recall@1/2/4/8, MRR, citation correctness, authorization-filter correctness on selected-material rows, honest upload/canvas evidence gaps and local search latency | Offline only (network blocked, no Bedrock, no Knowledge Base call; the local lexical stand-in only). `--i-approve-live-aws` is refused (exit 2). Does not change gate or retrieval behavior and adopts no chunking/reranking/router/vector-store variant; advanced methods stay measurement-gated |
| `evals/compare_routing_arms.py` | Pre-registered head-to-head of arms A (gate), B (gate + Laya), C (KB-score routing) and D (hybrid): calibration/holdout split, frozen T, M1 to M5, exact McNemar, pass rule, JSON and Markdown | Offline only (network blocked, no AWS or model call). Reads the `--live-kb-gate` file and stored or `--laya-full` Laya files; refuses a bad KB file, a stub or incomplete Laya file, or a plan whose constants differ from `lib/prereg.py`. The plan `.agents/tasks/headtohead-prereg/plan.md` is never edited (dated amendments only). Without the KB file and an all-rows Laya file no arm can be declared the winner |
| `evals/benchmark_course_intent.py` | Memory (RSS, peak RSS), load time and per-call latency of the local Laya classifier on the 147 eligible gate rows, with optional concurrency | Offline only (sockets blocked, `HF_HUB_OFFLINE=1`), no AWS or model call. `--checkpoint [--bundle]` needs `laya` and local weights; `--stub-ms` checks the harness with a sleeping stand-in and is marked `real_model: false`. `--checkpoint` also needs `--host-instance-type`, `--host-vcpu`, `--host-ram-gb` and `--host-arch` (operator notes, recorded as given, never detected); the output then carries `host_note` and `rows` (one per gate message) for `compare_routing_arms --laya-full`. Figures describe the machine they ran on |
| `evals/benchmark_agentcore_vs_converse.py` | Same fixed 50 gate turns through AgentCore `InvokeAgentRuntime` and a direct Bedrock Converse call: latency (first text, total), tokens, parse failures, estimated cost | **Paid live tool, built and never run.** Refuses (exit 2) before any client is built without `--live-benchmark` and `--max-live-calls N` (1 to 100; a turn costs 2 calls, `N // 2` turns are sent). Stops after the first auth or access error; stores exception classes only. `--dry-run` builds no client. `--converse-stream` also needs `bedrock:InvokeModelWithResponseStream`. Commands, IAM and cost estimate: `docs/RETRIEVAL_EVAL.md` |
| `evals/measure_stream_first_text.py` | Time to first visible reply text through `coach_events`, plain mock and simulated-latency mock, before/after labelled runs | Offline only (temp SQLite, mock provider, no network). The simulated first-token and per-chunk delays are inputs, not measurements of any model |
| `evals/fast_chat_quality_matrix.py` | Dry-run A–T quality matrix | Refuses AWS. Does not invent scores. |
| `evals/benchmark_prompt_variants.py` | Offline prompt-variant and supported prompt-cache benchmark (ticket 40): existing vs content-preserving compacted stage prefixes (estimator tokens, required-marker retention, verbatim-duplicate accounting), representative synthetic turns through the real composer seam, selected workspace context costs at the composer's own caps, and the `SystemContentBlock` prefix-cache eligibility/shapes/economics for Claude Haiku 4.5 with ESTIMATE pricing | Offline only (network blocked, no AWS, no model call). Token numbers are `backend.context_planner.estimate_tokens` counts (3.0 chars/token), never live tokenizer counts; `--i-approve-live-aws` is refused (exit 2). Records an adopt/reject recommendation; adoption of any prompt or cache-flag change needs separate approval and capped live evidence |
| `evals/benchmark_runtime_paths_offline.py` | Offline comparison of the three existing provider paths (mock, AgentCore adapter, direct Bedrock Converse adapter) over the same representative synthetic turns with injected fakes: structured first-attempt success, latency (adapter+harness; fake sleep is a labelled input), usage accounting read from the production `co_design.usage` events, error accounting through `provider_error_category`, and the honestly inequivalent path characteristics | Offline only (network blocked, injected fakes only, no AWS client, no live model). Documents this environment's configured models without secrets/ARN values; SDK retry loops are not exercisable offline (recorded, not silently accepted). Never publishes a runtime default: `agentcore_runtime` stays canonical; the fair live comparison requirements (call caps, guardrail equivalence, same turns, dated pricing) are recorded as an unexecuted plan pointing at the built, never-run `benchmark_agentcore_vs_converse.py` |
| `evals/lib/` | Offline helpers shared by the eval commands: dataset paths and loaders, metrics and intervals, run-block and JSON writers, offline course search and network block, the gate adapter, live-run guards and request builders, Laya state text, routing and passage scoring, prepared gate rows, the head-to-head split, metrics, pass rule and report, the KB-score and Laya file loaders, extra messages | Not commands: no `main`, no parser, no client built on import. **No command in `evals/` may import another command**; put shared code here (checked by `tests/scripts/test_eval_command_boundaries.py`). Model fitting and model loading stay in the command that owns the experiment. Commands re-export the names they used to define |
| `sync_course_materials.py` | Upload `lectureNotes/` and `readings/` to shared `course/` S3 keys | Requires `--confirm`; never writes `users/`; never deletes course objects |
| `preview_prompt.py` | Demo-only composed stage-prompt preview | No DB, student data, tokens, or provider calls |
| `reset_learning_data.py` | Dry-run inventory and explicit five-phase learning-data reset | Apply requires an unchanged signed manifest and exact phrase; preserves accounts/auth; creates SQLite backup and file quarantine |
| `backfill_source_chunks.py` | Offline SQLite maintenance: write missing `derived/chunks.v1.json` | Dry-run default; requires `--database`, `--identifier`, and `--confirm` to write. Runtime does not depend on it. **Do not run against production.** |
| `benchmark_student_source_chunks.py` | Informational dynamic vs precomputed vs cached chunk probe | In-memory + temp SQLite only. Prints counts and wall time; not a pytest latency SLO. Do not run against production data. |
| `benchmark_coach_turn_mock.py` | Informational mock `CoachApplicationService` submit time by history size | Isolated temp SQLite + deterministic provider. Refuses live AWS. Not a latency SLO. |
| `load_probe.py` | Free local FastAPI/rate-limit/ownership/KB-pool capacity probe | Mock + temp SQLite only. Fake provider/KB delays are script-only and restored. Never AgentCore/Bedrock/DSQL/S3/Cognito. Not an EC2/Haiku benchmark. |
| `classroom_probe.py` | Stepped80 Guest HTTP sessions, generation overload, restart and independent local backup restore | Separate loopback mock worker and new temporary data only; no supplied workspace. Reports real local failures and unresolved live/cost gates. See `docs/operations/CLASSROOM_CAPACITY_GATE.md`. |
| `workspace_recovery_rehearsal.py` | Complete-workspace backup/restore rehearsal (ticket local47): seeds chats, sources, artifact/canvas version histories, a confirmed recap and a Deep Review through public HTTP, backs up stopped stores, restores into a fresh disposable location and re-verifies every resource and the owner boundary | Separate loopback mock worker, guarded driver-created temporary roots only, never a supplied database or production. See `docs/operations/WORKSPACE_RECOVERY_REHEARSAL.md`. |
| `mixed_workload_probe.py` | Stepped 1/10/20/40/60/80-student mixed workload probe (ticket 48): startup, navigation, ordinary + grounded coaching, deliberate two-tab artifact OCC race, canvas autosave and durable Deep Review submission per wave, with percentiles, queueing, OCC, reconciliation and honest admission rejections | Separate loopback mock worker and driver-created disposable roots only; mock provider, SQLite/local files, no paid calls or AWS; always `live_ready: false`. See `docs/operations/CLASSROOM_CAPACITY_GATE.md` (mixed workload probe + capped live procedure). |
| `cost_scenarios.py` | Offline low/expected/high monthly SGD scenario renderer (ticket 49): reads one explicit configuration of dated public-pricing estimates, measured local anchors (tickets 38/39/40/48) and documentation-based regional trade-off rows, and reports gross/credits/cash/post-credit totals with an unresolved S$30 assessment | Read-only renderer over the named config file; no network, AWS, database or account access; every total is labelled estimate-only, never a bill. See `docs/COST_ACCOUNTING.md` (scenario planning section). |

## Environment variables

When changing browser API exports, follow the
[frontend contract workflow](../frontend/README.md#generated-read-contracts).
Run `export_reader_openapi.py` in a fresh process so its disposable-storage
bootstrap cannot reuse previously imported application settings.

`start.sh` sets:

- `USE_LOCAL_API=true`
- `CO_DESIGN_API_URL` (default `http://127.0.0.1:8000`)

`start_prod.sh` also forces `USE_LOCAL_API=true`; Compose keeps
`CO_DESIGN_API_URL` on container loopback and supplies the public HTTPS origins
for browser logout and UI redirects.

Other paths come from `backend/settings.py` and `.env` (see `.env.example`).
Repository defaults are `MODEL_PROVIDER=mock` and `AUTO_ADVANCE_STAGES=false`.
Never commit `.env` or embed API keys in scripts.

## Hard constraints

- **Do not run `init_db.py` against a developer's live DB** without an explicit
  `--database` target or `--force` after inspecting the path.
- **`build.sh` must stay validation-only** — never call `init_db.py` from it.
- **Do not hard-code secrets** or model API keys in scripts.
- **Prefer `.venv/bin/python`** when the virtual environment exists (as
  `start.sh` and `build.sh` do).
- **Keep mock vs paid OpenAI paths explicit** in documentation when adding new startup
  modes. Paid OpenAI smoke tests require explicit user approval per root
  `AGENTS.md`.

## Common edit paths

**Add a new local startup mode**

Add a script here, document it in `README.md` and this file, and verify
`streamlit_app.py` plus `backend/http/app.py` still start cleanly.

**Change DB initialization**

Edit `init_db.py` with additive migrations, backup/rollback notes, and tests.
Keep the refuse-existing-unless-`--force` guard. Update
`docs/IMPLEMENTATION_STATUS.md`.

**Prepare the five-phase research reset**

Run `reset_learning_data.py` without `--apply`, inspect its manifest and backup
targets, then follow [`docs/operations/RESEARCH_DATA_RESET.md`](../docs/operations/RESEARCH_DATA_RESET.md).
Never apply a reset merely to make readiness green.

## Validation

Syntax-check shell scripts:

```sh
sh -n scripts/start.sh
sh -n scripts/start_prod.sh
sh -n scripts/build.sh
```

After script changes that affect startup, smoke-test:

```sh
sh scripts/start.sh
```

Run in a separate terminal only when needed; stop after confirming startup.

Full automated gate (safe — no live DB init):

```sh
sh scripts/build.sh
```

Explicit DB init examples:

```sh
.venv/bin/python scripts/init_db.py --database /tmp/co-design-fresh.sqlite3
.venv/bin/python scripts/init_db.py --force   # only after confirming the path
```

## Handoff

If a script change affects setup or demo flow, update `README.md`,
`docs/IMPLEMENTATION_STATUS.md`, and `.env.example` when new variables are
introduced.
