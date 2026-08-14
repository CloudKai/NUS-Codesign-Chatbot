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
| `deploy_ecr.sh` | ECR login + `compose.prod.yaml` pull/up | Host-only; needs `APP_IMAGE` + IAM role |
| `host/duck.sh` | DuckDNS IP updater | Host cron only; token in `duck.env` (not Git) |
| `build.sh` | Validation-only: `compileall` + full mock `pytest` | **Does not** initialize or modify the live DB |
| `init_db.py` | Explicit SQLite schema setup | Refuses existing DB unless `--force`; prefer `--database PATH` for new files |
| `init_dsql.py` | Admin-only Aurora DSQL schema bootstrap | One DDL per transaction; async-job `CALL` on dedicated autocommit connection; initializes the workflow marker only with zero notebooks; never app startup; not `co_design_app`. CloudShell SSL/IPv4 checklist: [`docs/deploy/AWS_STATELESS_EC2.md`](../docs/deploy/AWS_STATELESS_EC2.md) (§ CloudShell / laptop init_dsql checklist) |
| `smoke_dsql_idempotency.py` | Explicitly approved live DSQL runtime-role idempotency smoke | Requires `--confirm-live`, `DATABASE_PROVIDER=dsql`, `DSQL_USER=co_design_app`, and `--identifier cognito:<sub>`; mock provider only; no DDL/S3/Bedrock |
| `preview_prompt.py` | Demo-only composed stage-prompt preview | No DB, student data, tokens, or provider calls |
| `reset_learning_data.py` | Dry-run inventory and explicit five-phase learning-data reset | Apply requires an unchanged signed manifest and exact phrase; preserves accounts/auth; creates SQLite backup and file quarantine |

## Environment variables

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
- **Keep mock/Ollama paths explicit** in documentation when adding new startup
  modes. Paid OpenAI smoke tests require explicit user approval per root
  `AGENTS.md`.

## Common edit paths

**Add a new local startup mode**

Add a script here, document it in `README.md` and this file, and verify
`streamlit_app.py` plus `backend/api.py` still start cleanly.

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
