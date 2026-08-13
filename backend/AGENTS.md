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
FastAPI (api.py)
  -> application services (application.py, learning_service.py, chat_service.py)
  -> one LangGraph workflow (workflow.py)
  -> domain contracts (domain.py, student_journey.py)
  -> repositories + SQLite (repositories.py, student_store.py)
  -> providers (providers.py, mock_provider.py)
  -> sources/files (source_library.py, file_processing.py)
```

## Module responsibilities

| Module | Responsibility |
|---|---|
| `domain.py` | Pydantic contracts: `CoachRequest`, `CoachTurn`, `EducationalAssessment`, `PendingPhaseTransition`, citations |
| `application.py` | `CoachApplicationService` — coordinates workflow, persistence, optional auto-advance |
| `api.py` | FastAPI app factory/composition plus owner-scoped workspace CRUD, auth, readiness, coach, learning, graph, revise, and transition routes |
| `api_client.py` | Typed client used by Streamlit when `USE_LOCAL_API=true` |
| `workspace_service.py` | Notebook/history/source/preference CRUD application service |
| `workflow.py` | Single LangGraph coach workflow wrapper (not six agents) |
| `student_journey.py` | Six thinking stages, journey normalization, review helpers, stage questions |
| `learning_service.py` | Confirmation-gated phase transitions and learning progression |
| `student_store.py` | Five-table SQLite/DSQL-compatible store for users, OAuth state, notebooks, messages, sources |
| `persistence/` | Storage ports + factories: SQLite/DSQL student stores, local/S3 file storage |
| `repositories.py` | Narrow repository adapters over `StudentStore` |
| `chat_service.py` | Legacy/direct chat engine retained for compatibility tests; not the current Streamlit fallback |
| `providers.py` | OpenAI coach provider adapter and provider selection (consumes composed prompts) |
| `prompts/` | Framework-neutral stage prompt files, loader, and composer |
| `mock_provider.py` | Deterministic provider for tests and offline demo |
| `source_library.py` | Source CRUD helpers, lecture-notes sync, URL import, citation context |
| `retrieval.py` | Provider-neutral retrieval port + deterministic local selected-source chunk retriever |
| `file_processing.py` | Upload storage, text extraction, safe paths |
| `settings.py` | Environment-driven configuration (`Settings`) |
| `models.py` | Model registry and allowed model IDs |
| `title_service.py` | Deterministic notebook title shortening/generation |
| `student_support.py` | Support-mode constants and helpers |
| `analysis_tool.py` / `local_tools.py` | Optional local Python analysis tools for chat engine |

## Hard constraints

- **No Streamlit imports** in any `backend/` module.
- **One workflow** for all six stages. Do not create six autonomous agents.
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
- **AWS production adapters are opt-in** via ``DATABASE_PROVIDER=dsql`` and
  ``FILE_STORAGE_PROVIDER=s3``. Keep ports replaceable; never bake credentials
  into images; tests must use mocks/fakes only.
- **Notebook isolation**. Retrieval and citations must stay scoped to the active
  notebook and selected sources.

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

`StudentStore` still concentrates notebooks, messages, sources, and preferences
in one SQLite module. Repository adapters in `repositories.py` already narrow
some access; when CRUD moves fully behind API routes (local or AWS), split
persistence along those boundaries without changing the Streamlit contracts.

Streamlit panels call `ui.runtime.WorkspaceFacade`, which selects typed FastAPI
CRUD in API mode or `WorkspaceService` in process. Panels must not call
`StudentStore` directly. Folder organization has been removed from the current
UI; the ignored `folder_id` argument is compatibility-only and must not be
documented as a current feature.

## Common edit paths

**Add or change an API route**

`domain.py` (request/response models) → `application.py` or service →
`api.py` → `api_client.py` → targeted route/client tests. Keep owner
resolution injected from `create_app`; moving a route must not weaken
`Depends(current_owner)` or alter its OpenAPI contract.

**Change stage behavior or coaching output**

`student_journey.py` / provider prompts in `providers.py` → `workflow.py` →
`application.py` → UI compatibility adapters in `ui/chat.py` if display-only.

**Change persistence or schema**

`student_store.py` / `repositories.py` with additive migrations, backup notes,
and rollback path. Update `docs/IMPLEMENTATION_STATUS.md`.

**Change source handling**

`source_library.py`, `file_processing.py`, and tests in
`tests/test_source_library.py`.

## Validation

```sh
.venv/bin/python -m pytest -q tests/test_api.py tests/test_workflow.py \
  tests/test_learning_service.py tests/test_student_store.py \
  tests/test_source_library.py tests/test_student_journey.py
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
