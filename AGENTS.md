# Co-design Chatbot agent guide

## Purpose and priority

This repository is a local, student-facing critical-thinking coach. Preserve the
existing Streamlit experience and all persisted notebooks, folders, chats,
sources, and learning data while improving the architecture.

For any architecture, backend, persistence, model-provider, source-retrieval,
or workflow task, read `docs/LOCAL_DEMO_IMPLEMENTATION.md` before editing. For
small, isolated UI fixes, read only the relevant source and this file.

Use `docs/IMPLEMENTATION_STATUS.md` to resume work. Update it at the end of
each completed implementation phase with evidence, migration notes, risks, and
the next exact action.

## Repository map

Open the nested guide for the area you are editing. Each guide is detailed about
that package's purpose, modules, constraints, and validation. Project-wide safety,
cost, and Git rules stay in this file.

| Path | Open when |
|---|---|
| [`backend/AGENTS.md`](backend/AGENTS.md) | API, domain, workflow, persistence, providers, sources, chat engine |
| [`ui/AGENTS.md`](ui/AGENTS.md) | Streamlit panels, theme, dialogs, workspace layout, `streamlit_app.py` |
| [`tests/AGENTS.md`](tests/AGENTS.md) | Adding or fixing automated tests, AppTest, mock-mode setup |
| [`docs/AGENTS.md`](docs/AGENTS.md) | Architecture spec, implementation status, phase handoff docs |
| [`scripts/AGENTS.md`](scripts/AGENTS.md) | Local run/build scripts, DB init, demo startup |

For small, isolated UI fixes, read [`ui/AGENTS.md`](ui/AGENTS.md) and the
relevant module only. For backend or migration work, read
[`docs/LOCAL_DEMO_IMPLEMENTATION.md`](docs/LOCAL_DEMO_IMPLEMENTATION.md) and
[`backend/AGENTS.md`](backend/AGENTS.md) first.

## Working model and cost policy

- `AGENTS.md` does not select or switch the Codex model. Model selection is
  manual in the Codex client.
- User-selected routing overrides earlier model defaults: `gpt-6.1-sol`
  implements tickets; `gpt-6-luna` performs read-only discovery;
  `gpt-6-astra` investigates concrete blockers. These roles are authorized.
  Use one writer and a fresh Sol session per ticket; read
  [ticket execution](docs/CONTRIBUTING.md#ticket-execution) before ticket work. The client selects models;
  report unavailable routing rather than claiming a switch occurred.
- Use targeted searches (`rg`) and focused reads. Do not repeatedly load large
  files, redo a completed audit, or generate duplicate documentation.
- Run focused tests after local changes. Run the full applicable suite only at
  phase boundaries and before handoff.
- Do not use subagents unless the user explicitly requests delegation and the
  work can proceed independently.
- After two evidence-based attempts at the same failure, stop retrying,
  summarize the evidence, and route the concrete blocker to `gpt-6-astra`.

## Safety, data, and Git

- Inspect `git status --short --branch` before mutating files.
- This repository may contain user work and untracked baseline files. Do not
  stage, commit, delete, reset, overwrite, or migrate user data without clear
  authorization.
- Never commit `.env`, API keys, SQLite databases, uploaded files, generated
  private artifacts, or local virtual environments.
- Preserve existing entrypoints and local data. Make schema changes through
  explicit, tested migrations with a backup and rollback path.
- Paid application API calls across providers are prohibited unless the user
  explicitly approves the live test and specifies a request/token or cost cap.
- Do not stage, commit, or deploy without explicit authorization.
- Automated tests must use deterministic mock providers.

## Architecture constraints

- Keep presentation, API, application, domain, and infrastructure concerns
  separate. Streamlit must not directly access SQLite, the filesystem, model
  SDKs, LangChain, or LangGraph.
- Keep core educational logic independent of Streamlit, LangChain, LangGraph,
  OpenAI, SQLite, and future AWS services.
- Use dependency injection and narrow interfaces for repositories, file
  storage, retrieval, model providers, and the coach workflow.
- Use one LangGraph workflow for the five research-aligned design-thinking
  phases. Do not create autonomous agents per phase.
- Model-generated stage recommendations must be structured, validated,
  persisted, shown to the student, and explicitly confirmed before a stage
  changes. Never use hidden HTML comments, keyword heuristics, or unrestricted
  manual stage advancement.
- Build a fully local prototype only. Create replaceable ports for future AWS
  adapters, but do not add AWS runtime dependencies unless explicitly asked.

## Code quality

- Add complete type annotations and Pydantic models at API and provider
  boundaries.
- Use small cohesive classes for services, entities, repositories, and
  adapters. Prefer typed pure functions when a class adds no useful state or
  encapsulation.
- Write useful docstrings for every public module, class, method, and function:
  responsibility, inputs, return value, and meaningful side effects/errors.
- Add inline comments only for non-obvious reasoning, security controls,
  compatibility behavior, or graph transitions. Do not comment self-evident
  code.
- Avoid global mutable state, circular imports, duplicated business logic, and
  provider-specific data structures outside infrastructure adapters.
- Use structured errors and logs with request and thread identifiers. Never log
  secrets or full private source content.

## Validation commands

Use the project virtual environment when present:

```sh
.venv/bin/python -m pytest -q
PYTHONPYCACHEPREFIX=/private/tmp/co-design-pycache \\
  .venv/bin/python -m compileall -q backend ui streamlit_app.py tests scripts
```

`scripts/build.sh` is validation-only (`compileall` + mock `pytest`) and does
not initialize the live database. Use `scripts/init_db.py` explicitly with
`--database` or `--force` when schema setup is needed. Do not claim Ruff or
static typing passed until those tools are configured and installed.

For UI changes, edit [`ui/`](ui/) modules and the thin
[`streamlit_app.py`](streamlit_app.py) entrypoint. Start Streamlit and inspect
the real interface at desktop and 390 px mobile widths. Check the browser
console. For backend changes, verify mock-mode startup, API contract tests, and
restart/persistence behavior.

## Phase handoff requirements

At the end of every phase, report:

1. What behavior changed and why.
2. Files changed.
3. Targeted and full validation results.
4. Migration/compatibility impact and rollback status.
5. Known risks or blockers.
6. The next exact phase and entry point.

Do not claim completion from code inspection alone. Completion requires
working local startup, mock-mode tests, source retrieval/citations, streaming,
graph-state resumption, confirmed stage progression, restart recovery, and
existing-data compatibility.

## Agent skills

- **Tracker:** Read [GitHub issues](docs/CONTRIBUTING.md#github-issues) before
  reading or publishing tickets.
- **Triage:** Read [triage labels](docs/CONTRIBUTING.md#triage-labels) before
  assigning triage states.
- **Domain:** Read [domain terms](docs/CONTRIBUTING.md#domain-terms) before
  domain exploration or architecture decisions.
