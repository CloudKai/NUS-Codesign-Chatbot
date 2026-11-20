# Testing and quality gates

## Safety contract

The default suite is deterministic and must not contact OpenAI, Cognito, AWS,
public webpages, or any other live service. `tests/conftest.py`
clears the OpenAI key, forces the mock provider, and gives each test an isolated
temporary database/files tree.

The current suite contains no live-marked tests. Any future live test must
self-skip without an explicit opt-in environment flag and require approval for
costs or writes. Use `-m "not live"` when selecting deterministic tests from a
suite that includes live cases.

## Standard commands

Focused test:

```sh
.venv/bin/python -m pytest -q tests/<subsystem>/test_<module>.py
```

Full mock suite:

```sh
.venv/bin/python -m pytest -q
```

Compile and shell/config checks:

```sh
PYTHONPYCACHEPREFIX=/private/tmp/co-design-pycache \
  .venv/bin/python -m compileall -q backend ui scripts tests streamlit_app.py agentcore_runtime

sh -n scripts/start.sh scripts/start_prod.sh scripts/build.sh \
  scripts/deploy_ecr.sh scripts/browser_e2e_smoke.sh

docker compose config --quiet
APP_IMAGE=co-design:test docker compose -f compose.prod.yaml config --quiet
git diff --check
```

`scripts/build.sh` builds React, compiles Python, and runs pytest.

## Coverage map

| Risk area | Principal deterministic suites |
|---|---|
| Auth cookies, refresh, OAuth state, logout | `http/test_app_sessions.py`, `ui/test_auth_gate.py`, `http/test_cognito_token_jwks.py` |
| Owner isolation | `http/test_multiuser_ownership.py`, `http/test_runtime_auth.py`, `http/test_production_critical_path.py` |
| API/client contracts | `http/test_api.py`, `http/test_api_client.py`, `http/test_workspace_api.py` |
| Five-phase workflow and progression | `domain/test_workflow.py`, `domain/test_primary_path.py`, `domain/test_learning_service.py`, `domain/test_student_journey.py` |
| Lecturer Research/analytics | `http/test_professor_research.py`, `http/test_professor_analytics.py`, `ui/test_professor_ui.py`, `domain/test_research_coding_domain.py`, `persistence/test_research_persistence.py` |
| Prompts/provider boundary | `domain/test_prompt_architecture.py`, `domain/test_bedrock_provider.py`, `domain/test_agentcore_provider.py`, `domain/test_models_and_support.py` |
| Retrieval/citations/sources | `domain/test_retrieval.py`, `domain/test_source_library.py`, `ui/test_sources_ui.py` |
| Retrieval eval script and data files | `scripts/test_evaluate_retrieval.py`, `domain/test_retrieval_question_set.py`, `domain/test_retrieval_gate_message_set.py` (see [retrieval evaluation](RETRIEVAL_EVAL.md)) |
| Persistence/migrations | `persistence/test_student_store.py`, `scripts/test_init_db.py`, `scripts/test_init_dsql.py`, `persistence/test_storage_providers.py` |
| Idempotency/revisions/deletion | `persistence/test_coach_idempotency.py`, `persistence/test_conversation_revision.py`, `persistence/test_delete_idempotency.py` |
| Upload/storage failure safety | `http/test_upload_hardening.py`, `persistence/test_hardening_storage_sync.py` |
| Streamlit behavior | `ui/test_streamlit_ui.py`, `ui/test_streamlit_api_mode.py`, `ui/test_rerun_scope.py`, `ui/test_theme_styles.py` |
| Production configuration/edge | `http/test_production_config.py`, `test_deployment_config.py` |
| Logging/rate limits | `http/test_privacy_logging.py`, `http/test_rate_limit.py` |
| Architecture façades and inventories | `test_architecture_contracts.py` |

## Regression workflow

Before a risky refactor, state the observable behavior and add a focused test
when coverage is weak. During implementation, run the nearest suite after each
cohesive change. At a phase boundary, run the full mock suite, compile checks,
and relevant deployment/browser validation.

For moved modules, preserve public imports when needed and update source-text
assertions deliberately. For API changes, verify the service, FastAPI route,
typed client, and API-mode Streamlit path together. For persistence changes,
test fresh schema, legacy upgrade, restart, rollback behavior, and both adapter
contracts.

## Browser and visual QA

AppTest verifies logic and rendered structure; it does not prove visual layout,
browser-console cleanliness, keyboard navigation, or responsive behavior.
Visual changes require the real app at desktop and 390 px widths in Light and
Dark/System as applicable.

For a local headed smoke, start the app with `sh scripts/start.sh` and run
`sh scripts/browser_e2e_smoke.sh`. The helper can check selection mode
(**Ready** and **Move to**). It requires Node.js/`npx`, an installed
Playwright CLI wrapper, and approved manual Cognito sign-in. Keep the helper
outside CI and use the regular sign-in flow.

## Current gaps

Passing local tests do not prove:

- real Cognito Hosted UI/session behavior;
- wire-level Aurora DSQL concurrency or IAM grants;
- real S3 bucket policy/object lifecycle;
- paid OpenAI behavior;
- ARM64 image execution and container replacement;
- durable graph inspection after process restart;
- true upstream provider-token streaming;
- browser accessibility, console, and layout across engines.

Other tooling gaps are tracked rather than overstated: Ruff is installed and
enforced by project CI; static typing has no configured gate, coverage is not
measured, and Markdown links are not checked in CI.

## Mock load probe

Virtual users are **distinct authenticated owners**. The probe must not treat a
shared `local-student` store as many students.

The probe checks FastAPI concurrency, owner isolation, rate limits, SQLite
persistence, and Knowledge Base Retrieve admission. Treat delays and latency
percentiles as mock results. Use the [classroom capacity gate](operations/CLASSROOM_CAPACITY_GATE.md)
for the stepped 80-session rehearsal, bounded generation, restart and restore,
and the remaining live capacity and cost decisions.

```bash
PYTHONPATH=. .venv/bin/python scripts/load_probe.py --users 10 --requests-per-user 5
PYTHONPATH=. .venv/bin/python scripts/load_probe.py --scenario distinct-owners --users 100
PYTHONPATH=. .venv/bin/python scripts/load_probe.py --scenario two-notebooks
PYTHONPATH=. .venv/bin/python scripts/load_probe.py --scenario same-notebook
PYTHONPATH=. .venv/bin/python scripts/load_probe.py --scenario slow-distinct-owners --users 10
PYTHONPATH=. .venv/bin/python scripts/load_probe.py --scenario kb-pool --kb-workers 4 --users 16 --kb-delay-ms 500
PYTHONPATH=. .venv/bin/python scripts/load_probe.py --run-phase existing
PYTHONPATH=. .venv/bin/python scripts/load_probe.py --run-phase slow --provider-delay-ms 10000
PYTHONPATH=. .venv/bin/python scripts/load_probe.py --run-phase kb
PYTHONPATH=. .venv/bin/python scripts/load_probe.py --run-phase correctness
```

`--users` is clamped to 1–120. Fake provider delay is script-only (patch of
`DeterministicCoachProvider.assess` restored on exit). Fake KB delay injects a
client into the **real** `BedrockKnowledgeBaseRetriever`; only `client.retrieve`
is faked. Production worker count is not changed.

Scenarios:

| Scenario | What it measures | Expected mock result |
|---|---|---|
| `sequential` | Distinct owners, sequential turns per notebook | accepted |
| `distinct-owners` | One concurrent turn per distinct owner | N users accepted under global 120 |
| `two-notebooks` | One owner, two notebooks, overlapping turns | both accepted (`MAX_ACTIVE_COACH_REQUESTS_PER_USER=2`) |
| `same-notebook` | One owner, one notebook, overlapping turns | 1 accepted, 1 HTTP 429 |
| `slow-distinct-owners` | Same as distinct-owners with a fake provider sleep | accepted; P95 ≈ fake delay, not Haiku |
| `kb-pool` | Real Retrieve admission/validation + fake `client.retrieve` | `min(users, workers)` accepted; excess `capacity_exhausted` |
| `kb-timeout-slot` | Fake Retrieve longer than timeout | timed-out calls keep the slot; excess fail closed |
| `kb-fail-closed` | Fake hits from a foreign bucket | zero chunks; no unrelated evidence |
| `slow-idempotency` | Same idempotency key replayed | HTTP 200 twice, one provider call |
| `failed-no-partial` | Fake provider raises | no assistant turn persisted |
| `ownership-isolation` | Distinct owners list threads / read messages | zero ownership violations |

Each printed line is JSON with:

`scenario`, `users`, `fake_provider_delay_ms`, `fake_kb_delay_ms`, `kb_workers`,
`requests`, `accepted`, `rate_limited`, `capacity_exhausted`, `failed`,
`p50_ms`, `p95_ms`, `mean_ms`, `requests_per_sec`, `peak_threads`,
`peak_kb_admitted`, `peak_kb_worker_threads`, `rss_peak_kb`,
`process_max_rss_kb`.

`rss_peak_kb` is kept for compatibility. It is **not** exact per-scenario
incremental memory: both RSS fields are the process-lifetime maximum RSS
from `resource.getrusage(RUSAGE_SELF).ru_maxrss` (a high-water mark).
`process_max_rss_kb` is the same value with a clearer name.

Irrelevant fields are JSON `null`. Aggregate metrics only (no notebook IDs,
emails, or message text).

The probe uses a temporary SQLite store and the mock coach. It never calls
AgentCore, Bedrock models, Knowledge Base, DSQL, S3, or Cognito. CLI bootstrap
and the runtime mutation path both force `APP_ENV=development` and
`COURSE_MATERIAL_SYNC_ENABLED=false` (snapshot/restore includes those
fields even if `backend.settings` was already imported). RPM is raised
to 10_000 so this measures concurrency architecture, not the production
`COACH_REQUESTS_PER_MINUTE=8` cap. That production cap is **per
authenticated user**, not a class-wide 8-RPM ceiling. Ninety distinct
students each sending one request can pass the per-user RPM rule; class
burst ceilings are global concurrency (`MAX_CONCURRENT_MODEL_CALLS`), the
AnyIO thread limiter, AgentCore, and Knowledge Base Retrieve capacity.
`SYNC_THREADPOOL_TOKENS` is set to 120 to match Compose.

Pytest uses tiny delays only. Do not put 5–12 second sleeps on the CI path.

### Constrained Docker rehearsal

Local Docker with `--cpus=2 --memory=2g` approximates a CPU and memory limit for
local mock testing. Use the target EC2 host for pilot capacity measurements.

Do **not** run `compose.prod.yaml` or `scripts/start_prod.sh` for this phase:
those wire AgentCore, DSQL, S3, and Cognito.

Simplest safe method (mock + SQLite inside a constrained container):

```bash
docker run --rm \
  --cpus=2 \
  --memory=2g \
  --memory-swap=2g \
  --pids-limit=512 \
  -e MODEL_PROVIDER=mock \
  -e MOCK_OPENAI=true \
  -e DATABASE_PROVIDER=sqlite \
  -e FILE_STORAGE_PROVIDER=local \
  -e KNOWLEDGE_BASE_ID= \
  -e MAX_CONCURRENT_MODEL_CALLS=120 \
  -e SYNC_THREADPOOL_TOKENS=120 \
  -e PYTHONPATH=/work \
  -v "$PWD":/work \
  -w /work \
  python:3.12-bookworm \
  bash -c 'pip install -q -r requirements.txt && python scripts/load_probe.py --scenario distinct-owners --users 25 && python scripts/load_probe.py --scenario slow-distinct-owners --users 10 --provider-delay-ms 5000 && python scripts/load_probe.py --scenario kb-pool --kb-workers 4 --users 30 --kb-delay-ms 500'
```

If installing `requirements.txt` inside the container is too heavy, run the
same `scripts/load_probe.py` commands on the host with `.venv/bin/python` and
treat Docker as optional confirmation, not as a substitute for a live EC2
pilot.

## Phase handoff

Report focused and full results separately, including failures and warnings.
State what was not tested, whether any live system was contacted, migration and
rollback impact, browser evidence, and the next exact validation step. Test
counts and current phase evidence belong in
[`IMPLEMENTATION_STATUS.md`](IMPLEMENTATION_STATUS.md), not duplicated here.
