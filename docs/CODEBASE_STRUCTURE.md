# Codebase structure

## Purpose

This guide tells contributors where implemented responsibilities live. It is a
placement guide, not a second architecture specification; architectural rules
remain in [`LOCAL_DEMO_IMPLEMENTATION.md`](LOCAL_DEMO_IMPLEMENTATION.md).

```text
streamlit_app.py              thin Streamlit entrypoint
ui/                           presentation, dialogs, session/view state, CSS
  panels/                     chat, source, Journey/Review implementations
  professor.py                lecturer Research/analytics workbench (not aliased)
  services/                   cached API/application resource facades
backend/
  api.py                      FastAPI compatibility facade
  http/app.py                 FastAPI composition, routes and HTTP errors
  api_client.py               typed client used by Streamlit
  application.py              coaching compatibility facade
  coaching/                   durable coach-turn execution
  workspace_service.py        notebook/message/source/preference use cases; transcript export
  learning_service.py         transition confirmation and stage selection
  domain.py                   Pydantic API/workflow contracts
  student_journey.py          learning compatibility facade
  learning/                   five-phase stages, journey rules and review projection
  workflow.py                 one LangGraph coach workflow
  prompts/                    shared and five-phase provider-neutral prompts
  professor_analytics/        lecturer overview and Research application services
  research/                   observation/review/adjudication models and adapters
  source_library.py           source compatibility alias
  sources/                    ingestion, course sync, context, image projection
  retrieval.py                retrieval port, local chunk retriever, composite splitter
  bedrock_retrieve.py         Bedrock Knowledge Base Retrieve adapter
  repositories.py             narrow store-backed repository adapters
  student_store.py            stable persistence facade and remaining operations
  persistence/store/          contracts, schema/migrations, extracted operations
  persistence/                DSQL, local-file, memory, and S3 adapters/ports
  providers.py                OpenAI adapter and provider selection
  bedrock_provider.py         Amazon Bedrock Converse coach adapter
  agentcore_provider.py       Amazon Bedrock AgentCore Runtime coach adapter
  specialists/                server-owned qa / coaching / review routing
  mock_provider.py            deterministic offline coach
  agentcore_harness_provider.py isolated Luna InvokeHarness eval adapter
  auth_*.py / cognito_*.py    Cognito/OIDC boundary and cookie behavior
tests/                        domain/, persistence/, http/, ui/, scripts/ suites
scripts/                      startup, validation and operator entrypoints
  dsql/                       DSQL catalog, migration and execution implementation
  agentcore/harness_patch/    compatibility re-export; not the live harness
agentcore_runtime/            canonical AgentCore specialists, prompts, contracts, model factory
docs/                         architecture, status, QA, deployment, and security guides
```

## Placement rules

### Streamlit presentation

Put panels, dialogs, widget callbacks, session-view state, and responsive
helpers in `ui/`. Panels call `ui.runtime.WorkspaceFacade` and typed coach
helpers. They must not import database drivers, model SDKs, LangGraph, or read
storage paths directly.

Static CSS belongs in the matching `ui/assets/styles/` partial. Browser-side
layout helpers belong in `ui/layout/`. `streamlit_app.py` should remain a thin
composition root so AppTest can load the complete application.

### HTTP/API boundary

Public request and response models belong in `backend/domain.py`.
`backend/http/app.py` is the application/owner composition root and owns workspace
CRUD, coach, learning, graph, readiness, transition, and professor/research HTTP
orchestration. Do not split professor routes into a second app.
Routes validate HTTP input, call an application service, and map structured
failures. Mirror client changes in `backend/api_client.py` and contract tests.

Do not place educational decisions, SQL, object-store calls, or provider prompt
construction in route functions.

### Application and domain logic

Use `CoachApplicationService` for coaching-turn orchestration,
`WorkspaceService` for workspace CRUD, and `LearningProgressService` for stage
decisions. Keep the five research-aligned phase definitions and review projections in
`backend/learning/`; keep provider-neutral request/assessment contracts in
`domain.py`. Lecturer Research coding models stay in `backend/research/`.

Use a focused class when it owns dependencies or state. Prefer a typed pure
function for deterministic transformations. Do not add wrapper classes or
interfaces without a real substitution/test boundary.

### Persistence and external services

Store-facing behavior belongs behind repository or storage ports. SQLite and
DSQL must preserve the same logical semantics. Local and S3 file storage must
preserve owner/notebook/source key scope. Provider-specific JSON and SDK types
stay inside provider adapters.

Schema changes require an explicit additive migration and tests. Application
startup must never run DSQL DDL. See [`DATABASE.md`](DATABASE.md).

### Tests

Place a regression beside the closest behavior boundary rather than creating a
generic test dump. API contract changes normally need service, route, client,
and UI-path coverage. External services use fakes only in the default suite.
See [`TESTING.md`](TESTING.md).

## Compatibility modules

`ui.chat`, `ui.sources`, `ui.studio` and `ui.runtime` preserve established
imports while implementations live in `ui.panels` and `ui.services`.
`backend.api`, `backend.application`, `backend.student_journey` and
`backend.source_library` preserve established imports while implementation is
owned by `backend.http`, `backend.coaching`, `backend.learning` and
`backend.sources`.
`ui/professor.py` and `ui/assets/styles/70-professor.css` stay in place.
`ui/column_resize.py`, `ui/sources_scroll.py`, and `ui/composer_layout.py`
re-export the corresponding `ui.layout` modules. `StudentChatEngine` in
`backend/chat_service.py` is retained for compatibility tests and is not the
current Streamlit fallback. Do not extend these seams with new student
behavior.

## Navigation by change type

| Change | Start here | Verify with |
|---|---|---|
| Coach assessment/stage behavior | `learning/`, prompts, `workflow.py` | domain workflow, prompt, primary-path, learning tests |
| Notebook/source/preference CRUD | `workspace_service.py` | workspace API, store, source tests |
| Edit/revise/idempotency | `coaching/execution.py`, repositories/store | persistence revision and idempotency suites |
| Authentication/owner isolation | auth modules, `owner_context.py` | session, auth-gate, ownership, critical-path suites |
| SQLite/DSQL/S3 | `persistence/`, `student_store.py` | storage, migration, delete-idempotency suites |
| Streamlit layout or copy | owning `ui/panels/` module or `ui/professor.py` and CSS partial | AppTest plus desktop/390 px browser review |
| Lecturer Research/analytics | `professor_analytics/`, `research/`, `ui/professor.py` | professor HTTP/UI and research persistence suites |
| Deployment boundary | Compose, Dockerfile, Caddy, scripts | production/deployment tests and config validation |

## Remaining large-module boundaries

The refactor deliberately did not impose an arbitrary line limit. The largest
remaining modules have materially coupled transaction or framework behavior:

- `backend/student_store.py` retains notebook/message/revision/coach-request
  operations plus research observation/review/adjudication/audit SQL. Those
  research writes stay on the store so coach-turn persist remains atomic.
- `backend/http/app.py` still registers closure-heavy learning/coaching routes;
  the stable route and dependency inventory is the prerequisite for moving each
  registrar independently.
- `backend/sources/library.py` still co-locates ingestion and course-material
  synchronization because both share storage cleanup and sync monkeypatch seams;
  context and image/storage projection are already separate.
- `ui/panels/*.py` remain sizeable Streamlit rendering modules, but splitting
  fragments/dialogs further requires preserving widget keys and rerun ownership.

These are active technical-debt boundaries, not generic utility dumping grounds.
New work should add behavior to the focused packages and avoid expanding the
compatibility façades.
