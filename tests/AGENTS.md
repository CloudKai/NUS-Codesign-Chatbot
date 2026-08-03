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

`conftest.py` runs before the suite and:

- Creates a temporary `APP_DATA_DIR` under a temp prefix.
- Points `APP_DATABASE_PATH`, `APP_FILES_DIR`, `APP_WORKSPACES_DIR`, and
  `LECTURE_NOTES_DIR` at isolated paths.
- Sets `MOCK_OPENAI=true` so provider code stays deterministic.

Do not point tests at a developer's real `data/` directory.

## Test file map

| File | Covers |
|---|---|
| `test_api.py` | FastAPI `/api/v1` health, coaching turn, transitions |
| `test_workflow.py` | LangGraph workflow routing and structured output |
| `test_learning_service.py` | Phase transition confirmation and resolution |
| `test_student_store.py` | Notebook, folder, message, source persistence |
| `test_student_journey.py` | Stage normalization, journey helpers, review |
| `test_source_library.py` | Source import, lecture sync, locked course groups |
| `test_title_service.py` | Notebook title shortening and legacy replacement |
| `test_files_and_engine.py` | Upload processing and chat engine behavior |
| `test_models_and_support.py` | Model registry and support-mode helpers |
| `test_streamlit_ui.py` | AppTest smoke against `streamlit_app.py` |

## Hard constraints

- **Deterministic mocks only** for automated runs. No network or paid API calls.
- **AppTest loads `streamlit_app.py`**, not individual `ui/` modules. The
  entrypoint must import panels so dialogs and fragments register correctly.
- **Source-file assertions** must track moved strings. If UI copy moves from
  `streamlit_app.py` to `ui/sources.py`, update the test path accordingly.
- **Prefer targeted tests** after a localized change; run the full suite at
  phase boundaries and before handoff.
- **Do not delete user data** in tests. Use the isolated paths from `conftest.py`.

## Common edit paths

**New backend behavior**

Add or extend the closest subsystem test file. Mirror production module
boundaries — e.g. source changes go in `test_source_library.py`.

**New Streamlit UI control or copy**

Extend `test_streamlit_ui.py`. Assert on rendered output (`app.markdown`,
`app.button`, etc.) when possible. Read source files only when checking static
CSS or strings not exposed in AppTest output.

**API contract change**

Update `test_api.py` and the typed client in `backend/api_client.py` together.

## Validation

Targeted:

```sh
.venv/bin/python -m pytest -q tests/test_<module>.py
```

Full suite:

```sh
.venv/bin/python -m pytest -q
```

With compile check:

```sh
PYTHONPYCACHEPREFIX=/private/tmp/co-design-pycache \
  .venv/bin/python -m compileall -q backend ui streamlit_app.py tests
```

## Handoff

Record new test counts and any gaps (e.g. unverified Ollama/OpenAI smoke) in
[`docs/IMPLEMENTATION_STATUS.md`](../docs/IMPLEMENTATION_STATUS.md) when tests
are part of a completed phase.
