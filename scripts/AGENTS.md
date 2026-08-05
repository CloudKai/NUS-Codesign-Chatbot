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
| `build.sh` | Validation-only: `compileall` + full mock `pytest` | **Does not** initialize or modify the live DB |
| `init_db.py` | Explicit DB schema setup | Refuses existing DB unless `--force`; prefer `--database PATH` for new files |

## Environment variables

`start.sh` sets:

- `USE_LOCAL_API=true`
- `CO_DESIGN_API_URL` (default `http://127.0.0.1:8000`)

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

## Validation

Syntax-check shell scripts:

```sh
sh -n scripts/start.sh
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
