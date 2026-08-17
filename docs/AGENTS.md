# Docs agent guide

## Purpose

The `docs/` directory holds authoritative project documentation for agents and
developers. It records **what to build** (architecture) and **where work left
off** (implementation status).

Do not create parallel architecture documents. Extend or amend the files here.

## Read first

1. Root [`AGENTS.md`](../AGENTS.md) for global rules and the repository map.
2. The doc relevant to your task (see below).

## Document map

| File | Role | When to read or edit |
|---|---|---|
| [`LOCAL_DEMO_IMPLEMENTATION.md`](LOCAL_DEMO_IMPLEMENTATION.md) | Architecture authority: layers, ports, workflow, providers, verification phases, implemented package ownership | Before any backend, API, persistence, workflow, or migration task |
| [`CODEBASE_STRUCTURE.md`](CODEBASE_STRUCTURE.md) | Placement map for implemented packages and compatibility façades | When choosing where new code belongs |
| [`IMPLEMENTATION_STATUS.md`](IMPLEMENTATION_STATUS.md) | Living handoff log: current phase, completed work, validation evidence, risks, next action | At session start to resume; at phase end to record evidence |
| [`PROMPT_ARCHITECTURE.md`](PROMPT_ARCHITECTURE.md) | Local stage-prompt package, composer seam, local vs Knowledge Base Retrieve | Before editing `backend/prompts/` or provider prompt wiring |
| [`RAG_ARCHITECTURE.md`](RAG_ARCHITECTURE.md) | Course KB Retrieve, student extract retrieval, unified `[S#]` evidence | Before changing retrieval, Bedrock KB filters, or source scope |
| [`KB_REQUIRED_MODE_RUNBOOK.md`](KB_REQUIRED_MODE_RUNBOOK.md) | Operator checklist to enable `required` metadata filters | Before sidecar upload, KB sync, or setting `KNOWLEDGE_BASE_METADATA_FILTER_MODE=required` |
| [`SECURITY_BOUNDARIES.md`](SECURITY_BOUNDARIES.md) | Identity, retrieval authorization, citations, prompt injection, transcript authority | Before changing auth, retrieval, or provider adapters |
| [`providers/AGENTCORE_ADAPTER.md`](providers/AGENTCORE_ADAPTER.md) | AgentCore Runtime generation adapter (FastAPI stays the app) | Before changing `MODEL_PROVIDER=agentcore` or the harness patch |
| [`deploy/AWS_STATELESS_EC2.md`](deploy/AWS_STATELESS_EC2.md) | Production CloudFront + Caddy origin + ECR + DSQL + S3 topology; CloudShell `init_dsql.py` SSL/IPv4 checklist | Before AWS/EC2 cutover or re-running admin DSQL bootstrap |
| [`DATABASE.md`](DATABASE.md) | SQLite/DSQL logical model; DSQL is the only durable transcript | Before persistence, message export, or AgentCore history questions |

Related product docs outside `docs/`:

| File | Role |
|---|---|
| [`DESIGN.md`](../DESIGN.md) | UI/UX principles, information architecture, visual QA references |
| [`README.md`](../README.md) | Human setup and quick start |

## Hard constraints

- **`LOCAL_DEMO_IMPLEMENTATION.md` wins** on architecture disputes. Code must
  follow its layer boundaries unless the user explicitly changes direction.
- **Update `IMPLEMENTATION_STATUS.md` after every completed phase** with:
  - what changed and why
  - files touched
  - targeted and full validation results
  - migration/compatibility impact
  - risks or blockers
  - the next exact action and entry point
- **Do not duplicate** long architecture sections into `IMPLEMENTATION_STATUS.md`.
  Link to `LOCAL_DEMO_IMPLEMENTATION.md` instead.
- **Do not claim completion** from documentation alone. Evidence must include
  passing tests and, for UI phases, browser checks where applicable.

## Common edit paths

**Starting a new backend or migration phase**

Read `LOCAL_DEMO_IMPLEMENTATION.md` → confirm current state in
`IMPLEMENTATION_STATUS.md` → implement → update status with evidence.

**Finishing any phase**

Append to `IMPLEMENTATION_STATUS.md` under Completed / Validation evidence /
Next exact action. Keep the "Current phase" header accurate.

**UI-only polish**

Usually `DESIGN.md` is enough. Touch `IMPLEMENTATION_STATUS.md`
only when the work closes a named implementation phase.

## Validation

Documentation changes do not require tests unless they accompany code changes.
When docs describe commands, verify they still match
[`scripts/AGENTS.md`](../scripts/AGENTS.md) and root `AGENTS.md`.

## Handoff

The status doc is the primary handoff artifact for the next agent. Make the
**Next exact action** line specific enough to open the right file and test
command without re-auditing the repo.
