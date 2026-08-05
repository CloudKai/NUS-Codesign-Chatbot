# Local LangGraph demonstration architecture

## Goal

Evolve Co-design Chatbot into a professional local demonstration for a
professor: a student uses the existing Streamlit research workspace while the
backend visibly executes a single critical-thinking workflow. The local system
must work without AWS, internet access, or paid model APIs in mock mode.

The target architecture is:

```text
Streamlit UI -> typed FastAPI client -> FastAPI /api/v1 -> application services
    -> one LangGraph coach workflow -> model/retrieval/storage ports
    -> Ollama or mock model, SQLite, local files, and local vector search
```

OpenAI remains an optional provider. Future AWS adapters may provide Bedrock,
S3, DynamoDB/Aurora, Cognito, and CloudWatch behind the same ports. Do not add
AWS services to the required local runtime.

## Compatibility baseline

Preserve the current Streamlit NotebookLM-inspired UI and its existing
capabilities:

- notebooks, folders, history, source upload/selection/preview/download/removal;
- source-grounded conversation, stable citations, streaming, model selection,
  short/long response modes, and local persistence;
- the six thinking stages: Focus, Evidence, Assumptions, Perspectives,
  Synthesis, and Conclusion;
- prompt summaries, learning summaries, working conclusions, changes in
  understanding, and critical-understanding assessment.

Existing SQLite data, local source files, thread identities, and user-visible
entrypoints must remain usable. Schema changes require explicit migrations,
safe defaults, backup instructions, and a tested rollback path.

## Target layers and interfaces

### Presentation

Streamlit remains the frontend entrypoint. It only renders state and calls a
typed API client; it must not call SQLite, local files, model SDKs, LangChain,
or LangGraph directly.

### API

FastAPI exposes typed, versioned routes below `/api/v1`, consistent structured
errors, streaming chat, and development-only graph inspection. At minimum,
cover health/readiness, provider availability, notebooks, folders, history,
chat/edit/regenerate, source CRUD and selection, learning state, pending phase
transitions, and transition confirmation/rejection.

The graph inspection route must not expose secrets, hidden prompts, or raw
private filesystem paths.

### Application and domain

Introduce framework-independent services and typed domain objects for chat,
notebooks, sources, learning state, phase transitions, routing, citations, and
usage. Model external input and output with Pydantic.

Use narrow dependency-injected ports, including:

- `ChatModelProvider` and `EmbeddingProvider`;
- `KnowledgeRepository`, `ConversationRepository`, `NotebookRepository`,
  `LearningStateRepository`, and `PhaseTransitionRepository`;
- `FileStorage`, `CoachWorkflow`, and `ModelRouter`.

Local SQLite, local filesystem, local vector search, Ollama, OpenAI, and mock
implementations live in infrastructure. Do not leak their response schemas
into domain or application code.

## Educational workflow

Build one LangGraph workflow, not six agents. Give it explicit typed state and
durable per-thread checkpoints.

Its steps are:

1. Load the notebook, canonical conversation history, and learning state.
   Client-supplied stage, history, selected source IDs, source context, and
   image payloads are treated as hints only; the server reloads persisted values
   and rejects mismatches with typed 4xx responses.
2. Retrieve evidence from selected notebook sources.
3. Assess the student contribution against the current stage.
4. Execute the current stage handler.
5. Validate a structured educational assessment.
6. Recommend staying or advancing.
7. Persist a pending recommendation and wait for student confirmation.
8. Generate and stream the user-facing response with citations.
9. Update summaries, conclusion, understanding change, and learning state.
10. Persist conversation, source snapshot, usage, and graph state.

Each assessment includes: current stage, contribution summary, stage-specific
assessment, evidence, assumptions, missing reasoning elements,
critical-understanding level, confidence, stay/advance recommendation,
rationale, guidance questions, updated learning summary, working conclusion,
understanding change, citations, Facione dimension scores (0–4 Holistic rubric
plus not-started), supportive review strengths and improvements for the current
stage (may be empty), and user-facing response.

Only the student's explicit confirmation may apply an advancement in the safe
default mode (`AUTO_ADVANCE_STAGES=false`). The system must persist the
recommendation and confirmation/rejection event first. Remove hidden comment
parsing, keyword-stage heuristics, and unrestricted manual advancement.

Audited auto-advance (`AUTO_ADVANCE_STAGES=true`) is an explicit local demo
override: the coach ADVANCE recommendation is applied immediately without the
Next/confirm UI, but a transition row is still persisted for auditability. Do
not treat auto-advance as the repository default.

## Providers and retrieval

Repository defaults in `.env.example` and `backend/settings.py` are cost-safe:

```env
MODEL_PROVIDER=mock
MOCK_OPENAI=true
AUTO_ADVANCE_STAGES=false
USE_LOCAL_API=true
OLLAMA_BASE_URL=http://127.0.0.1:11434
OLLAMA_CHAT_MODEL=gpt-oss:20b
OLLAMA_EMBEDDING_MODEL=<local-embedding-model>
OPENAI_API_KEY=
OPENAI_CHAT_MODEL=gpt-5.6-luna
```

Set `MODEL_PROVIDER=ollama` or `openai` in a private `.env` when needed. Do not
hard-code a model in the workflow. Give a helpful, actionable error if Ollama is
unavailable. The mock provider must be deterministic and support all automated
tests without network access.

Retrieval is notebook-isolated and source-first. It stores chunk metadata and
stable source mappings, retrieves only selected sources from the active
notebook, and returns citations that open the correct source. Student uploads
remain private. Enforce existing file-count and size limits, prevent path
traversal, validate content types where practical, and preserve legacy source
attachments.

## Development sequence

Work in these verified phases:

1. Audit, Git/data safety baseline, and compatibility tests.
2. Domain models, repository ports, and local repository adapters.
3. FastAPI API and typed Streamlit API client, with old facades kept until
   migration is complete.
4. Structured educational assessment and one LangGraph workflow.
5. Confirmation-based phase transitions and durable checkpoint state.
6. Ollama, OpenAI, and deterministic mock provider adapters; local retrieval.
7. Streamlit migration, source/citation integration, graph inspection, and
   visual QA.
8. Full regression, migration, restart, local-Ollama, and optional approved
   OpenAI smoke testing.

At every phase, update `IMPLEMENTATION_STATUS.md` with evidence before moving
on. Do not begin a broad rewrite without first preserving behavior through
targeted tests.

## Required verification

Automated tests must require no paid API or internet connection. Cover domain
validation, repository contracts, migration, graph routing, all six stages,
stay/advance recommendations, confirmation/rejection, restart resumption,
source selection, citations, notebook isolation, provider errors, streaming
failures, upload safety, API contracts, and Streamlit client behavior.

Separately gate local Ollama and OpenAI smoke tests. UI changes require browser
checks on desktop and 390 px mobile with a clean console.

Final acceptance requires successful Streamlit and FastAPI startup, mock mode,
Ollama operation when installed, preserved user data, streaming, grounded
citations, inspectable graph state, confirmed progress transitions, recovery
after restart, responsive UI, passing tests, and accurate setup documentation.
