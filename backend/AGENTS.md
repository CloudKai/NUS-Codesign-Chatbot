# Backend agent guide

## Purpose

The `backend/` package is the application, domain, and infrastructure layer for
Co-design Chatbot. It owns educational logic, persistence, model-provider
adapters, source handling, and the FastAPI boundary.

This package does **not** own Streamlit UI code. Presentation lives in
[`ui/`](../ui/) and [`streamlit_app.py`](../streamlit_app.py).

## Read first

1. Root [`AGENTS.md`](../AGENTS.md) for safety, Git, cost, and global architecture rules.
2. [`docs/LOCAL_DEMO_IMPLEMENTATION.md`](../docs/LOCAL_DEMO_IMPLEMENTATION.md) for the authoritative architecture spec.
3. [`docs/IMPLEMENTATION_STATUS.md`](../docs/IMPLEMENTATION_STATUS.md) for the current phase and next action.

## Layer map

```text
FastAPI (`api.py` façade → `http/app.py`)
  -> application services (`application.py` façade → `coaching/execution.py`,
     `learning_service.py`, `chat_service.py`, `professor_analytics/`)
  -> one LangGraph workflow (workflow.py)
  -> domain contracts (`domain.py`, `student_journey.py` façade → `learning/`)
  -> repositories + SQLite (repositories.py, student_store.py, research/)
  -> providers (providers.py, bedrock_provider.py, agentcore_provider.py, mock_provider.py)
  -> retrieval (retrieval.py, bedrock_retrieve.py)
  -> sources/files (`source_library.py` façade → `sources/`, `file_processing.py`)
```

## Module responsibilities

| Module | Responsibility |
|---|---|
| `domain.py` | Pydantic contracts: `CoachRequest`, `CoachTurn`, `EducationalAssessment`, `PendingPhaseTransition`, citations |
| `application.py` / `coaching/` | Compatibility import plus durable `CoachApplicationService` execution, including research-observation persist. `coaching/deep_review_context.py` owns Deep Review `full_history` vs `checkpoint_delta` planning. |
| `api.py` / `http/app.py` | Compatibility import plus FastAPI app factory/composition, student and professor routes, and HTTP error mapping |
| `api_client.py` | Typed client used by Streamlit when `USE_LOCAL_API=true` |
| `workspace_service.py` | Notebook/history/source/preference CRUD application service; student transcript export |
| `workflow.py` | Single LangGraph coach workflow wrapper (not one agent per phase) |
| `student_journey.py` / `learning/` | Compatibility imports plus the five research-aligned phases, journey normalization, review helpers, questions, and the How Might We scaffold projection (`learning/hmw.py`). New journeys default to Guide (`response_detail=short`). |
| `learning_service.py` | Confirmation-gated phase transitions and learning progression |
| `student_store.py` | SQLite/DSQL-compatible student, conversation, source, research, review, and audit persistence |
| `research/` | Provider-neutral research observations, human review/adjudication models, and repository adapter |
| `professor_analytics/` | Lecturer overview and Research application services |
| `persistence/` | Storage ports + factories: SQLite/DSQL student stores, local/S3 file storage; `persistence/store/` holds schema, migrations, and extracted source operations |
| `repositories.py` | Narrow repository adapters over `StudentStore` |
| `chat_service.py` | Legacy/direct chat engine retained for compatibility tests; not the current Streamlit fallback |
| `providers.py` | OpenAI, mock selection, Bedrock and AgentCore factory wiring |
| `bedrock_provider.py` | Amazon Bedrock Converse coach adapter (injected client; no AWS in tests) |
| `agentcore_provider.py` | AgentCore Runtime coach adapter (injected client; no AWS in tests). Live parsing lives in `agentcore_runtime/`. Runtime model/guardrail env is fail-closed in `agentcore_runtime/model.py`. |
| `specialists/` | Legacy server-owned `qa` / `coaching` / `review` helpers. Active AgentCore chat uses one `fast_chat` invoke. Explicit Deep Review is a dedicated FastAPI route; the browser cannot pick a privileged specialist on `/coach/turn`. |
| `prompts/` | Application composer for mock/OpenAI/Bedrock. Canonical AgentCore pedagogy is `agentcore_runtime/prompts/`. |
| `agentcore_harness_provider.py` | Isolated InvokeHarness Luna eval adapter (not production DEFAULT) |
| `context_planner.py` | Token-aware model-context planner (`fast_chat` vs Deep Review `full_history`) |
| `live_eval_config.py` | Trusted Luna override assertions for live evaluation |
| `bedrock_retrieve.py` | Bedrock Knowledge Base `Retrieve` adapter for selected locked course sources |
| `mock_provider.py` | Deterministic provider for tests and offline demo |
| `source_library.py` / `sources/` | Compatibility import plus ingestion, course sync, bounded context, and image/storage projection |
| `retrieval.py` | Provider-neutral retrieval port, local chunk retriever, and composite KB/local splitter |
| `retrieval_gate.py` | Deterministic, non-LLM gate for whether a normal chat turn retrieves |
| `turn_perf.py` | Privacy-safe per-request latency/context instrumentation (`coach_turn_perf` JSON plus `TIMING` seconds lines) |
| `file_processing.py` | Upload storage, text extraction, safe paths |
| `settings.py` | Environment-driven configuration (`Settings`) |
| `models.py` | Model registry and allowed model IDs |
| `title_service.py` | Deterministic notebook title shortening/generation |
| `student_support.py` | Support-mode constants and helpers |
| `analysis_tool.py` / `local_tools.py` | Optional local Python analysis tools for chat engine |

## Hard constraints

- **No Streamlit imports** in any `backend/` module.
- **One workflow** for all five phases. Do not create autonomous agents per phase.
- **Structured assessments** at provider boundaries. Validate before persisting.
- **Confirmation-gated advancement** when not in automatic-resolve mode. Persist
  recommendations and student decisions; never use hidden HTML markers or keyword
  heuristics for stage changes.
- **Server-authoritative coaching inputs** on the API path: persisted stage,
  canonical history, selected sources, source context, and image inputs come from
  the notebook store. Reject mismatched or unknown client values with 4xx.
- **Atomic transition apply** for confirmations (journey metadata + transition
  status in one SQLite transaction).
- **Structured provider failures** map to HTTP 503 at the API boundary.
- **Mock-first testing**. Automated tests must not require paid APIs or internet.
- **AWS production adapters are opt-in** via ``DATABASE_PROVIDER=dsql``,
  ``FILE_STORAGE_PROVIDER=s3``, and ``MODEL_PROVIDER=agentcore`` (or
  ``bedrock`` / ``openai``). Keep ports
  replaceable; never bake credentials into images; tests must use mocks/fakes
  only.
- **Notebook isolation**. Retrieval and citations must stay scoped to the active
  notebook and selected sources.
- **DSQL/SQLite is the transcript.** AgentCore Runtime is generation-only and
  must not own chat history (no runtime LRU, AgentCore Memory, DynamoDB, or
  JSON sidecar). Student transcript download is a projection of ``messages``.
- **Professor/research stays one API.** Lecturer routes live in `http/app.py`
  with the student API. Do not split them into a second FastAPI app.

## Current migration state

Coaching turns, transition resolution, and workspace CRUD (notebooks, messages,
sources, preferences, source content) run through the FastAPI path when
`USE_LOCAL_API=true` (`scripts/start.sh`). Streamlit panels use
`ui.runtime.store` (a `WorkspaceFacade`) so they do not open SQLite or source
paths directly.

A compatibility implementation remains, but it is not a second student UI
stack:

| Path | Entry | Use |
|---|---|---|
| Preferred | `application.py` → `workflow.py` → providers → API | Stage progression, assessments, selected-image inputs |
| In-process fallback | `application.py` → `workflow.py` → providers | Same typed coach path when `USE_LOCAL_API=false` |
| Legacy test seam | `chat_service.StudentChatEngine` | Compatibility/unit tests only; does not mutate learning stages |

Do not add new coaching behaviour to the legacy engine. Student turns already
use the API/workflow application path or its in-process equivalent;
`StudentChatEngine` can be retired only after its remaining compatibility tests
and non-student utilities are accounted for.

`StudentStore` still concentrates notebooks, messages, sources, preferences,
and research SQL in one module. Source operations are extracted to
`persistence/store/operations/sources.py`; research observation/review/audit
SQL stays on the store so coach-turn persist remains atomic.

Streamlit panels call `ui.runtime.WorkspaceFacade`, which selects typed FastAPI
CRUD in API mode or `WorkspaceService` in process. Panels must not call
`StudentStore` directly.

## Common edit paths

**Add or change an API route**

`domain.py` (request/response models) → `coaching/` or service →
`http/app.py` → `api_client.py` → targeted route/client tests. Keep owner
resolution injected from `create_app`; moving a route must not weaken
`Depends(current_owner)` or alter its OpenAPI contract. Professor Research
routes stay in the same composition root.

**Change stage behavior or coaching output**

`learning/` / provider prompts in `providers.py` → `workflow.py` →
`coaching/execution.py` → UI compatibility adapters in `ui/chat.py` if display-only.

**Change persistence or schema**

`student_store.py` / `repositories.py` with additive migrations, backup notes,
and rollback path. Update `docs/IMPLEMENTATION_STATUS.md`.

**Change source handling**

`sources/`, `file_processing.py`, and tests in
`tests/domain/test_source_library.py`.

## Validation

```sh
.venv/bin/python -m pytest -q tests/http/test_api.py \
  tests/domain/test_workflow.py tests/domain/test_learning_service.py \
  tests/persistence/test_student_store.py \
  tests/domain/test_source_library.py tests/domain/test_student_journey.py
PYTHONPYCACHEPREFIX=/private/tmp/co-design-pycache \
  .venv/bin/python -m compileall -q backend
```

Run the full suite at phase boundaries:

```sh
.venv/bin/python -m pytest -q
```

## Handoff

When backend work completes a phase, update
[`docs/IMPLEMENTATION_STATUS.md`](../docs/IMPLEMENTATION_STATUS.md) with
evidence, migration impact, risks, and the next exact action. Defer to root
[`AGENTS.md`](../AGENTS.md) for the full handoff checklist.
