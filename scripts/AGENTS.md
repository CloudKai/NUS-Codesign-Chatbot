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
| `start.sh` | **Canonical launcher** — FastAPI `:8000` + Streamlit `:8501` with `USE_LOCAL_API=true` | Preferred everyday path |
| `run.sh` | Alias → `start.sh` | Same full stack |
| `dev.sh` | Alias → `start.sh` | Same full stack (do not start UI-only) |
| `run_local_demo.sh` | Alias → `start.sh` | Same full stack |
| `build.sh` | `compileall`, full `pytest`, then `init_db.py` | **Initializes the database** — do not run blindly on user data |
| `init_db.py` | Database initialization / schema setup | Same caution as `build.sh` |

## Environment variables

`start.sh` sets:

- `USE_LOCAL_API=true`
- `CO_DESIGN_API_URL` (default `http://127.0.0.1:8000`)

Other paths come from `backend/settings.py` and `.env` (see `.env.example`).
Never commit `.env` or embed API keys in scripts.

## Hard constraints

- **Inspect `build.sh` and `init_db.py` impact** before running against a
  developer's existing `data/` directory.
- **Do not hard-code secrets** or model API keys in scripts.
- **Prefer `.venv/bin/python`** when the virtual environment exists (as
  `run_local_demo.sh` does).
- **Keep mock/Ollama paths explicit** in documentation when adding new startup
  modes. Paid OpenAI smoke tests require explicit user approval per root
  `AGENTS.md`.

## Common edit paths

**Add a new local startup mode**

Add a script here, document it in `README.md` and this file, and verify
`streamlit_app.py` plus `backend/api.py` still start cleanly.

**Change DB initialization**

Edit `init_db.py` with additive migrations, backup/rollback notes, and tests.
Update `docs/IMPLEMENTATION_STATUS.md`.

## Validation

Syntax-check shell scripts:

```sh
sh -n scripts/run_local_demo.sh
sh -n scripts/build.sh
sh -n scripts/dev.sh
sh -n scripts/run.sh
```

After script changes that affect startup, smoke-test:

```sh
sh scripts/run_local_demo.sh
```

Run in a separate terminal only when needed; stop after confirming startup.

Full automated gate (caution: `build.sh` runs `init_db.py`):

```sh
sh scripts/build.sh
```

## Handoff

If a script change affects setup or demo flow, update `README.md`,
`docs/IMPLEMENTATION_STATUS.md`, and `.env.example` when new variables are
introduced.
