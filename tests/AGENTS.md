# Tests agent guide

## Purpose

The `tests/` package holds automated verification for Co-design Chatbot. Tests
enforce mock-mode, deterministic behavior, API contracts, persistence,
source handling, workflow routing, and Streamlit UI smoke expectations.

Tests do **not** replace browser QA for visual polish. They gate regressions in
logic, contracts, and key UI structure.

## Read first

1. Root [`AGENTS.md`](../AGENTS.md) for cost policy: no paid OpenAI in CI.
2. [`backend/AGENTS.md`](../backend/AGENTS.md) or [`ui/AGENTS.md`](../ui/AGENTS.md)
   depending on what you are testing.
3. [`tests/conftest.py`](conftest.py) before adding tests that touch the filesystem or DB.

## Test environment (`conftest.py`)

`conftest.py` sets cost-safe bootstrap env vars, then an **autouse fixture**
gives every test its own temporary data/database/files/lecture-notes tree and:

- Forces `MOCK_OPENAI=true`, `MODEL_PROVIDER=mock`, and clears `OPENAI_API_KEY`
  (asserted each test).
- Defaults `USE_LOCAL_API=false` for in-process `CoachApplicationService`
  AppTest; API-mode UI tests opt in.
- Defaults `AUTO_ADVANCE_STAGES=false`.
- Monkeypatches `backend.settings.settings` paths onto the per-test tree.
- Clears Streamlit `cache_resource` handles so AppTest does not reuse a store.

Do not point tests at a developer's real `data/` directory. Prefer explicit
`StudentStore(tmp_path / "...")` for backend tests; AppTest uses the isolated
default `StudentStore()` path.

## Test package map

Tests are organized by owning subsystem. Repository-wide architecture and
deployment contracts remain at the root. Subdirectories have **no**
`__init__.py`, so `http` and `ui` test folders cannot shadow application
modules.

| Package | Covers |
|---|---|
| `domain/` | Five-phase coaching, learning, prompts, workflow, retrieval, sources, research coding |
| `persistence/` | StudentStore, revisions, idempotency, research persistence, storage adapters |
| `http/` | FastAPI, auth, ownership, API clients, professor analytics/research, production paths |
| `ui/` | Streamlit AppTest, presentation state, themes, auth gate, professor UI |
| `scripts/` | SQLite/DSQL administration and learning-data reset |

## Detailed test map

| File | Covers |
|---|---|
| `test_architecture_contracts.py` | Façade signatures, StudentStore/OCC inventories, professor-inclusive FastAPI routes |
| `test_deployment_config.py` | Compose/Caddy/Dockerfile production auth route allow-list, Cognito redirect, stateless prod compose, host `.env` Knowledge Base contract |
| `http/test_api.py` | FastAPI `/api/v1` health, coaching turn, transitions, integrity guards |
| `http/test_api_client.py` | Typed `LocalApiClient` confirmation + auto-advance contracts; `/auth/me` session mapping |
| `http/test_app_sessions.py` | Cognito refresh/ID cookie sessions, OAuth state binder, callback/logout |
| `http/test_professor_analytics.py` | Lecturer overview/engagement analytics API |
| `http/test_professor_research.py` | Attributable lecturer Research API, review/adjudication, audited CSV |
| `ui/test_auth_gate.py` | Streamlit auth gate, Redirecting UX, Cognito profile upsert, owner binding |
| `ui/test_professor_ui.py` | Professor workbench AppTest contracts |
| `persistence/test_storage_providers.py` | SQLite/local defaults, DSQL/S3 provider selection, mocked DSQL auth + S3 |
| `http/test_runtime_auth.py` | Cognito owner isolation vs single-owner local API |
| `http/test_workspace_api.py` | Notebook/source/preference CRUD API, path redaction, student transcript download |
| `domain/test_agentcore_provider.py` | AgentCore Runtime adapter contract with an injected fake client; stateless session plus DSQL history as Converse messages |
| `domain/test_agentcore_runtime.py` | Production harness `AgentResult` → structured output (no Strands/AWS) |
| `domain/test_specialist_routing.py` | Deterministic qa / coaching / review routing |
| `domain/test_agentcore_specialists.py` | Runtime prompt ownership and specialist contracts |
| `domain/test_pedagogical_stage_fixtures.py` | Per-stage mock pedagogical fixtures |
| `domain/test_thinking_path_journey.py` | Complete five-stage mock journey |
| `domain/test_security_invariants.py` | Memory-not-transcript, no tools, adapter cannot persist stage |
| `domain/test_runtime_model.py` | Explicit Sonnet/Luna factory, no BedrockModel(), ApplyGuardrail for Mantle, runtime pin sync |
| `domain/test_agentcore_harness_provider.py` | Isolated Luna InvokeHarness eval adapter; trusted override; no AWS |
| `domain/test_context_planner.py` | Full-history-first planner, compression, revision invalidation |
| `domain/test_bedrock_retrieve.py` | Bedrock Knowledge Base Retrieve adapter: selected `[S#]` mapping, foreign-key drop, required/degraded/disabled filter modes, no silent unfiltered retry, shared-executor timeouts |
| `domain/test_kb_metadata.py` | Canonical `course_material_id` and Bedrock sidecar payload |
| `scripts/test_sync_course_kb_metadata.py` | Sidecar dry-run, idempotent bytes, local verify |
| `domain/test_fast_chat_schema.py` | Slim FastChatTurnOutput; legacy EducationalAssessment parse |
| `domain/test_coach_turn_perf.py` | Privacy-safe `coach_turn_perf` JSON and `TIMING` service-latency lines |
| `domain/test_coach_progress.py` | retrieving/thinking/saving execution-boundary events; slim persist |
| `domain/test_primary_path.py` | All five phases, stale/reject, restart, notebook isolation, schema |
| `domain/test_research_coding_domain.py` | Structured provisional CLEAR/Facione/ethics coding |
| `persistence/test_research_persistence.py` | Offset-only observations, revisions, human decisions, audit, workflow marker |
| `scripts/test_reset_learning_data.py` | Dry-run manifest, backup/quarantine, exact confirmation, stale-plan rejection |
| `domain/test_fast_chat_one_call.py` | One Haiku fast-chat invoke; no router/incremental/Sonnet on the normal path |
| `domain/test_fast_chat_context.py` | Six-message window, 3000/1500 history budgets, 12k/16k totals, system-prompt estimate, RAG repack |
| `domain/test_conversation_memory_continuity.py` | 20/50/100-message and chunky-history extractive memory; no LLM summarizer |
| `domain/test_rag_fallback.py` | Application-owned needs_source_retrieval retry; persist-final-only |
| `domain/test_deep_review_execution.py` | Background Deep Review enqueue, frozen snapshot, counter, no transcript rows |
| `http/test_deep_review.py` | Deep Review job POST/GET, coaching overlap, duplicate/stale/owner isolation |
| `domain/test_coaching_prompt_baseline.py` | SHA-256 lock on canonical Coaching/stage prompt files |
| `domain/test_prompt_cache.py` | SystemContentBlock prefix cache; no CacheConfig auto on student text |
| `scripts/test_evaluate_fast_chat_regression.py` | Dry-run and mocked live-candidate regression CLI; no live Claude |
| `domain/test_prompt_architecture.py` | Stage prompt files, composer ordering, authoritative stage selection |
| `domain/test_qa_grounding.py` | Failed Q&A authors the evidence-gap copy with zero AgentCore invokes; successful Q&A cites retrieved excerpts without coaching |
| `domain/test_bedrock_provider.py` | Bedrock Converse adapter contract with an injected fake client |
| `domain/test_learning_service.py` | Phase transition confirmation, resolution, atomic rollback |
| `persistence/test_student_store.py` | Notebook, folder, message, source persistence |
| `domain/test_student_journey.py` | Stage normalization, journey helpers, review |
| `domain/test_source_library.py` | Source import, lecture sync, locked course groups |
| `domain/test_title_service.py` | Notebook title shortening and legacy replacement |
| `domain/test_files_and_engine.py` | Upload processing and chat engine behavior |
| `domain/test_models_and_support.py` | Model registry and support-mode helpers |
| `ui/test_streamlit_ui.py` | AppTest smoke against `streamlit_app.py` (in-process path) |
| `ui/test_theme_styles.py` | Ordered CSS partial manifest and assembled stylesheet contracts |
| `ui/test_streamlit_api_mode.py` | AppTest API confirmation + auto-advance |
| `ui/test_rename.py` | Enter-only rename draft helpers and epochs |
| `scripts/test_init_db.py` | Safe `init_db.py` refuse-existing / `--force` behavior |
| `scripts/test_init_dsql.py` | Additive DSQL revision planning and five-phase/research bootstrap |

## Hard constraints

- **Deterministic mocks only** for automated runs. No network or paid API calls.
- **AppTest loads `streamlit_app.py`**, not individual `ui/` modules. The
  entrypoint must import panels so dialogs and fragments register correctly.
- **Source-file assertions** must resolve the owning module with
  `inspect.getfile` so they still pass through compatibility aliases.
- **Prefer targeted tests** after a localized change; run the full suite at
  phase boundaries and before handoff.
- **Do not delete user data** in tests. Use the isolated paths from `conftest.py`.
- Live OpenAI tests stay `@pytest.mark.live` and disabled by default.
- Patch DSQL CLI internals on `scripts.dsql.cli` when the loaded
  `scripts/init_dsql.py` wrapper re-exports implementation functions.

## Common edit paths

**New backend behavior**

Add or extend the closest subsystem test file. Mirror production module
boundaries — e.g. source changes go in `domain/test_source_library.py`.

**New Streamlit UI control or copy**

Extend `ui/test_streamlit_ui.py` (in-process) or `ui/test_streamlit_api_mode.py`
(API). Assert on rendered output (`app.markdown`, `app.button`, etc.) when
possible.

**API contract change**

Update `http/test_api.py`, `http/test_api_client.py`, and
`backend/api_client.py` together. If the public route inventory changes, update
`test_architecture_contracts.py`.

## Validation

Targeted:

```sh
.venv/bin/python -m pytest -q tests/<subsystem>/test_<module>.py
```

Full suite:

```sh
.venv/bin/python -m pytest -q
```

With compile check:

```sh
PYTHONPYCACHEPREFIX=/private/tmp/co-design-pycache \
  .venv/bin/python -m compileall -q backend ui streamlit_app.py tests scripts agentcore_runtime
```

CI: [`.github/workflows/mock-ci.yml`](../.github/workflows/mock-ci.yml) runs
shell syntax, compileall, and mock pytest on push/PR. Job
`agentcore-runtime-compatibility` installs
`agentcore_runtime/requirements.txt` and runs
`scripts/diagnostics/check_agentcore_runtime_dependencies.py`. Companion
pytest does not install Strands.

## Handoff

Record new test counts and any gaps (e.g. unverified OpenAI smoke) in
[`docs/IMPLEMENTATION_STATUS.md`](../docs/IMPLEMENTATION_STATUS.md) when tests
are part of a completed phase.
