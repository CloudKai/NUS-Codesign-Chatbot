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
- Use GPT-5.6 Terra with medium reasoning for normal implementation, tests,
  documentation, and routine debugging.
- Use GPT-5.6 Sol with high reasoning for architecture planning, data
  migrations, security review, or final high-risk review.
- If the current model is not appropriate, state the recommended escalation or
  downgrade; do not claim to have changed it automatically.
- Use targeted searches (`rg`) and focused reads. Do not repeatedly load large
  files, redo a completed audit, or generate duplicate documentation.
- Run focused tests after local changes. Run the full applicable suite only at
  phase boundaries and before handoff.
- Do not use subagents unless the user explicitly requests delegation and the
  work can proceed independently.
- After two evidence-based attempts at the same failure, stop retrying,
  summarize the evidence, and recommend a Sol-level review.

## Safety, data, and Git

- Inspect `git status --short --branch` before mutating files.
- This repository may contain user work and untracked baseline files. Do not
  stage, commit, delete, reset, overwrite, or migrate user data without clear
  authorization.
- Never commit `.env`, API keys, SQLite databases, uploaded files, generated
  private artifacts, or local virtual environments.
- Preserve existing entrypoints and local data. Make schema changes through
  explicit, tested migrations with a backup and rollback path.
- Paid OpenAI calls are prohibited unless the user explicitly approves a live
  smoke test and specifies a request/token or cost cap.
- Automated tests must use deterministic mock providers. Local Ollama smoke
  tests are optional and separately labelled.

## Architecture constraints

- Keep presentation, API, application, domain, and infrastructure concerns
  separate. Streamlit must not directly access SQLite, the filesystem, model
  SDKs, LangChain, or LangGraph.
- Keep core educational logic independent of Streamlit, LangChain, LangGraph,
  OpenAI, Ollama, SQLite, and future AWS services.
- Use dependency injection and narrow interfaces for repositories, file
  storage, retrieval, model providers, and the coach workflow.
- Use one LangGraph workflow for the six critical-thinking stages. Do not
  create six autonomous agents.
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
  .venv/bin/python -m compileall -q backend ui streamlit_app.py
```

`scripts/build.sh` also initializes the database; do not run it against user
data without checking its impact first. Do not claim Ruff or static typing
passed until those tools are configured and installed.

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
