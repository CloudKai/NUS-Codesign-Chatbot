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
deployment contracts remain at the root.

| Package | Covers |
|---|---|
| `domain/` | Coaching, learning, prompts, workflow, retrieval and source behavior |
| `persistence/` | StudentStore, revisions, idempotency and storage adapters |
| `http/` | FastAPI, auth, ownership, API clients and production request paths |
| `ui/` | Streamlit AppTest, presentation state, themes and auth gate |
| `scripts/` | SQLite/DSQL administration and mock load probe |

## Detailed test map

| File | Covers |
|---|---|
| `http/test_api.py` | FastAPI `/api/v1` health, coaching turn, transitions, integrity guards; legacy Streamlit-cookie logout callback |
| `test_api_client.py` | Typed `LocalApiClient` confirmation + auto-advance contracts; `/auth/me` session mapping |
| `test_app_sessions.py` | Cognito refresh/ID cookie sessions, OAuth state binder, callback/logout, redirect URI precedence |
| `test_auth_gate.py` | Streamlit auth gate, Redirecting UX, Cognito profile upsert, owner binding, no `st.login`/`st.user` authority |
| `test_cognito_token_jwks.py` | Cognito token-use validation, JWKS refresh/cache, local readiness validation |
| `test_multiuser_ownership.py` / `test_runtime_auth.py` | Authenticated owner isolation and API-mode owner selection |
| `test_coach_idempotency.py` | Durable request replay/conflict, leases, concurrency, DSQL OCC wrappers |
| `test_conversation_revision.py` | Append-only edit branches, CAS, retry recovery, active-history semantics |
| `test_delete_idempotency.py` | Retryable owner-scoped source/notebook object cleanup |
| `test_deployment_config.py` | Compose/Caddy/Dockerfile production auth route allow-list, Cognito redirect, stateless prod compose |
| `test_production_config.py` | `APP_ENV=production` fail-closed settings |
| `test_production_critical_path.py` | Authenticated HTTP notebook/source/RAG/restart/cleanup journey with fakes |
| `test_storage_providers.py` | SQLite/local defaults, DSQL/S3 provider selection, mocked DSQL auth + S3 (no AWS calls) |
| `test_workspace_api.py` | Notebook/source/preference CRUD API and path redaction |
| `test_primary_path.py` | All six stages, stale/reject, restart, notebook isolation, schema |
| `test_workflow.py` | LangGraph workflow routing and structured output |
| `test_prompt_architecture.py` | Stage prompt files, composer ordering, authoritative stage selection, no raw prompts in API |
| `test_learning_service.py` | Phase transition confirmation, resolution, atomic rollback |
| `test_student_store.py` | Notebook, message, source, preference, owner, and legacy migration persistence |
| `test_student_journey.py` | Stage normalization, journey helpers, review |
| `test_source_library.py` | Source import, lecture sync, locked course groups |
| `test_retrieval.py` | Selected-source chunking/ranking, scope enforcement, citation audit excerpts |
| `test_upload_hardening.py` / `test_hardening_storage_sync.py` | Upload bounds and object cleanup on partial failure |
| `test_title_service.py` | Notebook title shortening and legacy replacement |
| `test_files_and_engine.py` | Upload processing and chat engine behavior |
| `test_models_and_support.py` | Model registry and support-mode helpers |
| `test_streamlit_ui.py` | AppTest smoke against `streamlit_app.py` (in-process application path) |
| `test_theme_styles.py` | Ordered CSS partial manifest and assembled stylesheet contracts (incl. auth) |
| `test_streamlit_api_mode.py` | AppTest API confirmation + auto-advance; one in-process parity smoke |
| `test_sources_ui.py` / `test_rerun_scope.py` | Source ordering/selection and fragment/full-app rerun contracts |
| `test_retry_keys.py` | Bounded, privacy-safe UI retry-key lifecycle |
| `test_rate_limit.py` | Per-owner/global coach limits and public login-start throttling |
| `test_privacy_logging.py` | Privacy-safe operational logging |
| `test_rename.py` | Enter-only rename draft helpers and epochs |
| `test_init_db.py` | Safe `init_db.py` refuse-existing / `--force` behavior |
| `scripts/test_init_dsql.py` | Additive/idempotent DSQL revision migration planning and bootstrap behavior |
| `scripts/test_load_probe.py` | Direct CLI bootstrap plus distinct-owner mock load-probe behavior |

## Hard constraints

- **Deterministic mocks only** for automated runs. No network or paid API calls.
- **AppTest loads `streamlit_app.py`**, not individual `ui/` modules. The
  entrypoint must import panels so dialogs and fragments register correctly.
- **Source-file assertions** must track moved strings. If UI copy moves from
  `streamlit_app.py` to `ui/sources.py`, update the test path accordingly.
- **Prefer targeted tests** after a localized change; run the full suite at
  phase boundaries and before handoff.
- **Do not delete user data** in tests. Use the isolated paths from `conftest.py`.
- The registered `live` marker is excluded by the default pytest addopts
  (`-m "not live"`). There are no live-marked tests today. Any future live test
  must additionally self-skip unless its explicit opt-in environment flag is
  set; never rely on a marker alone for cost/write safety.

## Common edit paths

**New backend behavior**

Add or extend the closest subsystem test file. Mirror production module
boundaries — e.g. source changes go in `test_source_library.py`.

**New Streamlit UI control or copy**

Extend `test_streamlit_ui.py` (in-process application path) or
`test_streamlit_api_mode.py` (HTTP API path).
Assert on rendered output (`app.markdown`, `app.button`, etc.) when possible.

**API contract change**

Update `test_api.py`, `test_api_client.py`, and `backend/api_client.py` together.

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
  .venv/bin/python -m compileall -q backend ui scripts streamlit_app.py tests
```

CI: [`.github/workflows/mock-ci.yml`](../.github/workflows/mock-ci.yml) runs
shell syntax, compileall, and mock pytest on push/PR.

## Handoff

Record new test counts and any gaps (e.g. unverified OpenAI smoke) in
[`docs/IMPLEMENTATION_STATUS.md`](../docs/IMPLEMENTATION_STATUS.md) when tests
are part of a completed phase.
