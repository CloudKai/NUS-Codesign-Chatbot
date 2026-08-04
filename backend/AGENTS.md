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
| `api.py` | FastAPI `/api/v1` routes, app factory, structured errors |
| `api_client.py` | Typed client used by Streamlit when `USE_LOCAL_API=true` |
| `workflow.py` | Single LangGraph coach workflow wrapper (not six agents) |
| `student_journey.py` | Six thinking stages, journey normalization, review helpers, stage questions |
| `learning_service.py` | Confirmation-gated phase transitions and learning progression |
| `student_store.py` | SQLite store for notebooks, folders, messages, sources, metadata |
| `repositories.py` | Narrow repository adapters over `StudentStore` |
| `chat_service.py` | Legacy/direct chat engine (`StudentChatEngine`) for non-API Streamlit path |
| `providers.py` | Ollama and OpenAI coach provider adapters |
| `mock_provider.py` | Deterministic provider for tests and offline demo |
| `source_library.py` | Source CRUD helpers, lecture-notes sync, URL import, citation context |
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
- **Mock-first testing**. Automated tests must not require paid APIs or internet.
- **No AWS runtime dependencies** unless explicitly requested. Keep ports
  replaceable for future adapters.
- **Notebook isolation**. Retrieval and citations must stay scoped to the active
  notebook and selected sources.

## Current migration state

Coaching turns and transition resolution run through the FastAPI path when
`USE_LOCAL_API=true` (`scripts/start.sh`). That path owns
structured assessments, image grounding, and stage advancement.

A second stack remains for compatibility:

| Path | Entry | Use |
|---|---|---|
| Preferred | `application.py` → `workflow.py` → providers → API | Stage progression, assessments, selected-image inputs |
| Legacy | `chat_service.StudentChatEngine` | Streamlit-only / `USE_LOCAL_API=false` fallback; does not mutate learning stages |

Do not add new coaching behaviour only to the legacy engine. The next
architecture step (including AWS cutover) is to collapse onto the API/workflow
path and retire `StudentChatEngine` for student turns.

`StudentStore` still concentrates notebooks, messages, sources, and preferences
in one SQLite module. Repository adapters in `repositories.py` already narrow
some access; when CRUD moves fully behind API routes (local or AWS), split
persistence along those boundaries without changing the Streamlit contracts.

Source, notebook, and folder CRUD may still be called directly from the
Streamlit UI via `StudentStore`. When migrating CRUD behind API routes,
preserve the verified UI behavior and existing SQLite data.

## Common edit paths

**Add or change an API route**

`domain.py` (request/response models) → `application.py` or service →
`api.py` → `api_client.py` → targeted tests in `tests/test_api.py`.

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
