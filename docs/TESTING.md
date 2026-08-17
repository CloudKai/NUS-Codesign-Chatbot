# Testing and quality gates

## Safety contract

The default suite is deterministic and must not contact OpenAI, Cognito, AWS,
public webpages, or any other live service. `tests/conftest.py`
clears the OpenAI key, forces the mock provider, and gives each test an isolated
temporary database/files tree.

The `live` marker is excluded by the default pytest addopts
(`-m "not live"`). There are no live-marked tests today. Any future live test
must also self-skip without a separate opt-in environment flag and require the
appropriate cost/write approval.

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

`scripts/build.sh` runs compileall (including `scripts/`) plus pytest.

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

`scripts/browser_e2e_smoke.sh` is a manual operator helper. It requires a
running app, Node.js/`npx`, an installed Playwright CLI wrapper, and approved
manual Cognito sign-in. It is not a CI dependency and must not embed
credentials or fabricate a production auth bypass.

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

The mock load probe now uses distinct owner-scoped stores, but remains a local
SQLite/memory/mock diagnostic rather than EC2, DSQL, S3, Cognito, or provider
capacity evidence. See [`operations/LOAD_PROBE.md`](operations/LOAD_PROBE.md).

## Phase handoff

Report focused and full results separately, including failures and warnings.
State what was not tested, whether any live system was contacted, migration and
rollback impact, browser evidence, and the next exact validation step. Test
counts and current phase evidence belong in
[`IMPLEMENTATION_STATUS.md`](IMPLEMENTATION_STATUS.md), not duplicated here.
