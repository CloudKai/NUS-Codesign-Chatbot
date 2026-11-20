# Local LangGraph demonstration architecture

## Goal

Evolve Co-design Chatbot into a professional local demonstration for a
professor: students use the React workspace while the backend executes a single
critical-thinking workflow. Streamlit serves the protected lecturer and Enabled
Access workspaces. The local system
must work without AWS, internet access, or paid model APIs in mock mode.

The target architecture is:

```text
React or protected Streamlit UI -> FastAPI /api/v1 -> application services
    -> one LangGraph coach workflow -> model/retrieval/storage ports
    -> mock or optional OpenAI model, SQLite, local files, and local vector search
```

OpenAI remains an optional provider. Future AWS adapters may provide Bedrock,
S3, DynamoDB/Aurora, Cognito, and CloudWatch behind the same ports. Do not add
AWS services to the required local runtime.

The [AWS topology](deploy/AWS_STATELESS_EC2.md#topology) describes the adapters
selected by production Compose and the current deployment boundaries.

## Compatibility baseline

Preserve the current Streamlit NotebookLM-inspired UI and its existing
capabilities:

- notebooks, folders, history, source upload/selection/preview/download/removal;
- source-grounded conversation, stable citations, streaming, model selection,
  short/long response modes, and local persistence;
- the five research-aligned phases: Problem identification, Concept generation,
  Design specification, Ethics & Critical Thinking, and Reflection
  (internal persisted id for Ethics & Critical Thinking remains
  `deep_analysis`);
- prompt summaries, learning summaries, working conclusions, changes in
  understanding, and critical-understanding assessment.

Existing local source files, account identities, and user-visible entrypoints
must remain safe. The old six-stage and new five-phase learning contracts are
not silently mapped. Non-empty databases without the exact workflow marker
fail readiness until an explicit, inventoried reset/bootstrap is approved.
SQLite reset creates a recoverable backup and file quarantine and preserves
users/auth records; DSQL reset is admin-only and explicit. Schema changes
require safe initialization, backup instructions, and tested rollback paths.

## Implemented package ownership

Ticket 05 / #18 bounds new Guest workspace creation before inserting owner or
session records. The injected, locked admission limiter allows 120 new starts
per rolling minute and 480 per rolling hour by default, configurable through
`GUEST_STARTS_PER_MINUTE` / `GUEST_STARTS_PER_HOUR`. It does not key on IP, so
80 arrivals sharing a classroom network fit within the defaults. Registered
identity precedence and origin validation run first; valid Guest sessions reuse
their existing workspace without consuming admission. Rejections return 429,
`Retry-After`, no cookie, and browser wait/retry/lecturer-help guidance.

This is a single-worker, process-local creation bound; reservations reset on
restart, and failed creation attempts conservatively consume a reservation.
Multiple workers/containers require shared admission before claiming the same
deployment-wide bounds. It is not a lifetime identity quota, DDoS defense,
generation budget, or evidence of live classroom capacity. No schema or Guest
history migration is required.

Ticket 06 / #19 bounds retained Sources uploads in `backend/upload_queue.py`,
with owner-bound adapters in UI runtime. Per Streamlit process, running, queued
and retry-retained payloads share atomic ceilings: 32 global/four per-owner
batches, 200 MiB global/50 MiB per owner by default. Optional bounded
`SOURCE_UPLOAD_GLOBAL_JOBS`, `SOURCE_UPLOAD_OWNER_JOBS`,
`SOURCE_UPLOAD_GLOBAL_BYTES`, `SOURCE_UPLOAD_OWNER_BYTES` and
`SOURCE_UPLOAD_RETRY_SECONDS` configure them. Success releases payloads before
completion. Failed retries expire independently of browser polling after 300
seconds from first failure, with three attempts maximum; retries never renew
that deadline. Active operations keep their allowance until completion. Small
payload-free terminal receipts are separately count/age bounded. Retry uses
fresh credentials and owner/notebook guards; discard checks ownership.

Library admission feedback remains visible until dismissed or superseded by a
new successful admission. Terminal completion during rendering repaints locally,
so Uploading cannot strand a completed batch without a polling timer. Successful
source ingestion persists the existing source-grounding mode before a UI revisit.
No schema/data migration is required. Queue retries are ephemeral across process
restart; saved sources remain durable. These bounds exclude incoming HTTP/parser/
widget buffering, chat attachments and disk quotas. Additional UI processes
multiply limits; this is not shared deployment-wide upload admission.

Ticket 07 / #20 adds provider-call and operation accounting in `backend/usage.py`
without storing content or raw identity/notebook ids. Failed and retried calls,
Deep Review and stage checkpoints remain separate from saved-answer counts.
Nullable meters preserve unknown SDK/model retry usage. The offline
`scripts/cost_report.py` consumes explicit, evidenced monthly SGD inventory and
usage exports; gross, credits, cash, post-credit baseline, runway and unknowns
remain distinct. Generation estimates never double-count inventory charges.
See [COST_ACCOUNTING.md](COST_ACCOUNTING.md). No schema/data migration or billing
account access; runtime meter extraction is additive and not deployed here.

Ticket 08 / #21 adds optional local generation admission through
`GenerationAdmission` and a dedicated operator-selected SQLite ledger. With
`GENERATION_ADMISSION_POLICY` configured, every visible provider call reserves
conservative allowance before invocation, shares finite running/queue ceilings,
and settles known complete usage or retains the full unknown charge. Failed,
recovery, RAG fallback, Deep Review and checkpoint calls all use this seam.
Expired invokes retain charge and capacity until settlement or backed-up operator
recovery after all workers stop. Background review submissions also have finite
process-local retained-work and wait ceilings. Streams distinguish actual queued
work from thinking; limit errors preserve notebook/source/export access and explain
the UTC monthly reset. Missing policy preserves local behavior without enforcement;
multiple hosts/DSQL require a shared admission adapter before release. See
[GENERATION_ADMISSION.md](GENERATION_ADMISSION.md) for configuration, headroom,
reconciliation, recovery, and unsettled classroom wait/cost gates. No student
schema/data migration or AWS/paid operation was performed.

Production AgentCore pedagogy is not this local mock path. Canonical
specialist and stage prompts live in `agentcore_runtime/`. FastAPI still
owns identity, RAG authorization, transcript persistence, and stage
transitions.

## Repository layout and placement rules

```text
streamlit_app.py              thin Streamlit entrypoint
frontend/                     React student workspace
ui/                           presentation, dialogs, session/view state, CSS
  panels/                     chat, source, Journey/Review implementations
  professor.py                lecturer Research/analytics workbench
  services/                   cached API/application resource facades
backend/
  api.py                      FastAPI compatibility facade
  http/app.py                 FastAPI composition, routes and HTTP errors
  api_client.py               typed client used by Streamlit
  application.py              coaching compatibility facade
  coaching/                   coach execution, review context, and turn state
  workspace_service.py        workspace use cases and transcript export
  learning_service.py         transition confirmation and stage selection
  domain.py                   Pydantic API/workflow contracts
  student_journey.py          learning compatibility facade
  learning/                   five-phase stages, journey rules and review projection
  workflow.py                 one LangGraph coach workflow
  prompts/                    shared and five-phase provider-neutral prompts
  professor_analytics/        lecturer overview and Research application services
  research/                   observation/review/adjudication models and adapters
  source_library.py           source compatibility facade
  sources/                    ingestion, course sync, context, image projection
  retrieval.py                retrieval port, local chunk retriever, composite splitter
  retrieval_gate.py           deterministic non-LLM retrieve / skip classifier
  bedrock_retrieve.py         Bedrock Knowledge Base Retrieve adapter
  sources/kb_metadata.py      canonical course_material_id + sidecar payload
  repositories.py             narrow store-backed repository adapters
  student_store.py            stable persistence facade and remaining operations
  persistence/store/          contracts, schema/migrations, extracted operations
  persistence/                DSQL, local-file, memory, and S3 adapters/ports
  providers.py                OpenAI adapter and provider selection
  bedrock_provider.py         Amazon Bedrock Converse coach adapter
  agentcore_provider.py       Amazon Bedrock AgentCore Runtime coach adapter
  specialists/                compatibility helpers and explicit Deep Review
  mock_provider.py            deterministic offline coach
  agentcore_harness_provider.py  isolated Luna InvokeHarness eval adapter
  auth_*.py / cognito_*.py    Cognito/OIDC boundary and cookie behavior
tests/                        domain/, persistence/, http/, ui/, scripts/ suites
scripts/                      startup, validation and operator entrypoints
  dsql/                       DSQL catalog, migration and execution implementation
  agentcore/harness_patch/    compatibility re-export for the runtime
agentcore_runtime/            canonical AgentCore prompts, specialists, and contracts
docs/                         architecture, tests, deployment, and classroom guides
```

### Streamlit presentation

Put panels, dialogs, widget callbacks, session-view state, and responsive
helpers in `ui/`. Panels call `ui.runtime.WorkspaceFacade` and typed coach
helpers. They must not import database drivers, model SDKs, LangGraph, or read
storage paths directly.

The React student workspace lives in `frontend/`. Keep Streamlit CSS in the
matching `ui/assets/styles/` partial and its browser-side layout helpers in
`ui/layout/`. Keep `streamlit_app.py` a thin composition root so AppTest can
load the complete application.

### HTTP/API boundary

Public request and response models belong in `backend/domain.py`.
`backend/http/app.py` is the application/owner composition root and owns workspace
CRUD, coach, learning, graph, readiness, transition, and professor/research HTTP
orchestration. Do not split professor routes into a second app.
Routes validate HTTP input, call an application service, and map structured
failures. Mirror client changes in `backend/api_client.py` and contract tests.

Do not place educational decisions, SQL, object-store calls, or provider prompt
construction in route functions.

### Application and domain logic

Use `CoachApplicationService` for coaching-turn orchestration,
`WorkspaceService` for workspace CRUD, and `LearningProgressService` for stage
decisions. Keep the five research-aligned phase definitions and review projections in
`backend/learning/`; keep provider-neutral request/assessment contracts in
`domain.py`. Lecturer Research coding models stay in `backend/research/`.

Use a focused class when it owns dependencies or state. Prefer a typed pure
function for deterministic transformations. Do not add wrapper classes or
interfaces without a real substitution/test boundary.

### Persistence and external services

Store-facing behavior belongs behind repository or storage ports. SQLite and
DSQL must preserve the same logical semantics. Local and S3 file storage must
preserve owner/notebook/source key scope. Provider-specific JSON and SDK types
stay inside provider adapters.

Schema changes require an explicit additive migration and tests. Application
startup must never run DSQL DDL. See [`DATABASE.md`](DATABASE.md).

### Tests

Place a regression beside the closest behavior boundary rather than creating a
generic test dump. API contract changes normally need service, route, client,
and UI-path coverage. External services use fakes only in the default suite.
See [`TESTING.md`](TESTING.md).

### Compatibility modules

`ui.chat`, `ui.sources`, `ui.studio` and `ui.runtime` preserve established
imports while implementations live in `ui.panels` and `ui.services`.
`backend.api`, `backend.application`, `backend.student_journey` and
`backend.source_library` preserve established imports while implementation is
owned by `backend.http`, `backend.coaching`, `backend.learning` and
`backend.sources`.
`ui/professor.py` and `ui/assets/styles/70-professor.css` stay in place.
Keep research writes on `StudentStore` so coach-turn persistence remains atomic.
`ui/column_resize.py`, `ui/sources_scroll.py`, and `ui/composer_layout.py`
re-export the corresponding `ui.layout` modules. `StudentChatEngine` in
`backend/chat_service.py` is retained for compatibility tests and is not the
current Streamlit fallback. Do not extend these seams with new student
behavior.

## Target layers and interfaces

### Presentation

The React/TypeScript workspace is built from `frontend/` and served at `/` by
`backend/http/notebook_reader.py`, with `/pilot/` retained as an alias. FastAPI
routes verified staff and explicitly enabled Cognito subjects to `/streamlit/`.
Caddy checks that permission before proxying every Streamlit request, including
WebSocket handshakes. Streamlit rechecks access on application reruns. Enabled
Access does not grant lecturer permissions. The existing typed
browser routes cover session, notebook list, saved message page/citations, lecture
stream, exact-key recovery, cited-original download, canonical project view, project
stream and explicit decision/selection adapters. Verified registered or
enabled Guest credentials are mandatory even in anonymous-capable internal mode;
staff, cross-origin and foreign-notebook requests are rejected. POST requires
Origin. Caddy exposes exact methods/paths only, with private no-store responses.
The lecture adapter constructs the existing CoachRequest from saved stage/detail
and fixed lecture intent, delegates to the same coach stream, and recovers through
the existing completed-turn service. It never invents a second lifecycle/backend.
Preview is ephemeral; malformed/EOF/canceled streams only trigger read reconciliation.
Explicit retry retains the original identity. Citation download checks an exact
active owner/notebook/message and its saved source mapping before serving attachment
bytes; pasted notes use authorized extracted text. Source mutations use only the explicit typed source adapters described below.
`StudentStore.get_active_message` is an indexed, revision-guarded read, with no
schema migration. Older messages lacking citation metadata remain plain saved text.

Browser replies/list/search stay in memory and clear on hiding/leaving. Unsent text
and pending identity/question are tab-sessionStorage only, scoped by verified owner
and notebook; replies/sources/tokens are never stored there. Owner changes discard
other owners' drafts. Aborts, request generations and owner verification fence late
responses; focus and 15-second visible probes detect changed sessions. These are
bounded checks, not instantaneous cross-tab notification. See
[`frontend/README.md`](../frontend/README.md) for build, recovery/privacy and rollback.
The external formative study remains pending; this pilot is engineering scope.

Ticket12/#25 renders the existing `project_resume` projection, canonical stage
labels/selectability and pending recommendation in React's right Thinking Path
panel. Project coaching delegates to the same stream with fixed project intent;
confirmation/rejection and gated revisits delegate to `LearningProgressService`.
The browser calculates no unlocks, readiness or completion. Every action reconciles
saved state without optimistic advancement; ambiguous responses block further actions
until a successful read. Draft/intent/original receipt survive reload and stage moves.
The three-panel desktop layout uses a temporary Thinking Path panel on mobile with
explicit return focus. Saved student contributions and coach summaries remain distinct.
No schema/data migration or source/workspace management expansion is introduced.

Ticket13/#26 adds nine narrow reader routes for source list/plain-text inspection,
original attachment download, explicit selection/removal and bounded upload
submit/status/retry/discard. These delegate to WorkspaceService and the existing
SourceUploadCoordinator, owned/drained by the API lifespan. Queue/processing states
are captured under the coordinator lock; success releases payloads and failed
retry leases expire without a browser revisit. Bounds remain per process and do
not include multipart/parser buffers or disk quotas; Streamlit retains its separate
coordinator. No new persistence schema or data migration. Source changes apply to
future requests; in-flight authorized snapshots and saved exact citation mapping
remain unchanged. Removed originals cannot be downloaded through old citations.
The temporary Sources view preserves the mounted transcript/composer, draft,
reading position and return focus. Ambiguous writes require GET reconciliation
before further source changes/new questions, with no automatic replay. Upload
receipts are ephemeral across restart; saved source bytes remain durable. See the
pilot README for upload ambiguity/partial-batch limitations and rollback.

Ticket14/#27 adds nine typed browser workspace adapters over existing services:
notebook create/settings/update/confirmed-remove/transcript export, global appearance
read/update, append-only message revise and bounded learning receipts. Learning state,
model registry and response preference normalization remain server-owned. Appearance
uses existing owner preferences; response detail/language/model/reasoning and assignment
context use notebook metadata. Browser invalidation refreshes only verified owner/list/
settings state without remounting ordinary transcript updates. Ambiguous mutations
require GET reconciliation without automatic replay. Message edits retain the original
target/content/request key for shared-service recovery; the composer draft survives.
No schema/data migration. Current folder organization was removed from the canonical
backend and remains a documented capability gap; no folder parity is claimed. Additional
Streamlit-only workflows and existing literal Markdown rendering are recorded in the
pilot README; this bounded engineering slice does not authorize a default frontend switch.

`streamlit_app.py` remains the entrypoint for the protected Streamlit workspace.
Streamlit renders state and calls a typed API client. Keep SQLite, filesystem,
model SDK, LangChain and LangGraph access behind FastAPI and its services.

### API

FastAPI exposes typed, versioned routes below `/api/v1`, consistent structured
errors, streaming chat, and development-only graph inspection. At minimum,
cover health/readiness, provider availability, notebooks, folders, history,
chat/edit/regenerate, source CRUD and selection, learning state, pending phase
transitions, and transition confirmation/rejection.

The graph inspection route must not expose secrets, hidden prompts, or raw
private filesystem paths.

The existing coach-turn contract accepts an optional public `interaction_intent`:
`lecture_help` or `project_coaching`. Omitting it preserves inferred routing and
existing retry fingerprints. It grants no source, stage, or specialist authority.
Lecture help uses authorized shared course material and selected personal sources,
answers from validated evidence (or states an evidence gap), and cannot navigate,
create recommendations, award completion, change project summaries, dirty stage
reviews, or increment/reset review counters. Intent is saved with transcript rows
and preserved by append-only edits. The optional UI application action selects
project coaching for the next student-authored message in the same notebook;
it does not send or award work on the student's behalf.

### Application and domain

Introduce framework-independent services and typed domain objects for chat,
notebooks, sources, learning state, phase transitions, routing, citations, and
usage. Model external input and output with Pydantic.

Use narrow dependency-injected ports, including:

- `ChatModelProvider` and `EmbeddingProvider`;
- `KnowledgeRepository`, `ConversationRepository`, `NotebookRepository`,
  `LearningStateRepository`, and `PhaseTransitionRepository`;
- `FileStorage`, `CoachWorkflow`, and `ModelRouter`;
- `ResearchRepository` for immutable automated observations, append-only human
  reviews/adjudications, and attributable access audit.

Local SQLite, local filesystem, local vector search, OpenAI, and mock
implementations live in infrastructure. Do not leak their response schemas
into domain or application code.

## Educational workflow

Build one LangGraph workflow, not one agent per phase. Give it explicit typed
state and durable per-thread recovery through saved turns and learning state.
The implemented graph has no interrupt/resume nodes: intermediate run checkpoints
are ephemeral, and completed runs retain no LangGraph checkpoints. Keep at most
64 latest runtime summaries per workflow; graph inspection reconstructs saved
output from the transcript after eviction or restart. Provider handoff data stays
available until the application persists or fails the leased execution.

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

Each assessment includes: current phase, contribution summary, phase-specific
assessment, evidence, assumptions, missing reasoning elements,
critical-understanding level, confidence, stay/advance recommendation,
rationale, guidance questions, updated learning summary, working conclusion,
understanding change, citations, Facione dimension scores (0–4 Holistic rubric
plus not-started), supportive review strengths and improvements for the current
phase (may be empty), and user-facing response.

The same single provider result may also include optional provisional research
coding. It is soft-validated independently from coaching: one dominant CLEAR
strategy, no more than two Facione behaviour occurrences, design-ethics
concepts, and evidence quotes that the application resolves to offsets in the
current student utterance. Invalid research coding never discards a valid
coach turn. Research codes do not award Review points, complete a phase, or
force progression. Only Reflection may yield a provisional holistic candidate.

Lecturer/admin access is attributable. Protected professor routes expose an
aggregate summary, paginated observation queue, notebook detail/transcript,
append-only review/adjudication, and formula-safe CSV. Every identifiable read
or export writes an access audit first and fails closed when auditing fails.
Students receive the established Review projection plus Facione behaviour
occurrences and the provisional Reflection candidate; CLEAR and ethics labels
remain research-review data. The latest successful Deep Review snapshot, when
present, also contributes its strengths and areas-to-develop onto the frozen
reviewed Thinking Path stage; it does not replace historical incremental
assessments.

Only the student's explicit confirmation may apply an advancement in the safe
default mode (`AUTO_ADVANCE_STAGES=false`). The system must persist the
recommendation and confirmation/rejection event first. Remove hidden comment
parsing, keyword-stage heuristics, and unrestricted manual advancement.

Ticket 03 / #16 clarifies the default confirmation contract: a nonterminal
ADVANCE creates a pending recommendation without completing the current stage
or unlocking its destination. Thinking Path shows **Confirm next stage** and
**Stay here**; one acceptance atomically awards first completion and changes
focus. Literal chat confirmation uses the same decision service. Repeated or
stale decisions cannot award completion twice. The store conditionally claims
the pending row, revalidates its active conversation revision, and builds the
completion from transaction-current journey data, preserving concurrent edits
and preferences. Terminal Reflection retains complete-in-place behavior.

Stage selection remains controlled by `STUDENT_STAGE_SELECTION`. Navigation
may revisit explicitly completed stages and return to the first unfinished
stage after the contiguous completed prefix. Existing focus and explicit legacy
completion records are preserved, including non-contiguous records; neither
focus nor a gap infers a missing completion or unlocks a later unfinished stage.
Selecting the current stage is a no-op and preserves its pending recommendation.
Revisit coaching creates no new first-completion recommendation or award.

Problem Identification uses the provider's validated structured semantic
assessment of student-authored affected people, problem/context, desired
outcome, and openness to alternative solutions. Meaningful informal prose is
accepted; vague filler and solution-locked drafts remain STAY. The HMW formula
is optional scaffolding. Application regex/wording checks neither veto an
informal ADVANCE nor promote a formal-looking STAY. Shared and stage prompts
keep coaching in the current stage until confirmation. Deterministic mocks
verify routing and persistence, not real-model semantic quality.

Ticket 04 / #17 adds a read-only `project_resume` projection to learning-state.
It uses active, stage-tagged transcript contributions as student work, labels
completion summaries and historical replies as coach-generated feedback, and
supplies one deterministic action for each stage (including pending decisions
and completed-stage refinement). Untagged legacy text remains in Chat; no
stage or authorship is guessed and no model/review job starts from this read.
Thinking Path exposes this saved work in the active stage and opened previews.
Unsent composer text is scoped by owner/notebook in browser-tab sessionStorage;
reload and stage revisits restore it, and a text send clears it. File payloads
are not copied into browser storage. Stage selection keeps the composer mounted.

Audited auto-advance (`AUTO_ADVANCE_STAGES=true`) is an explicit local demo
override: the coach ADVANCE recommendation is applied immediately without the
Next/confirm UI, but a transition row is still persisted for auditability. Do
not treat auto-advance as the repository default.

Production on `compose.prod.yaml` uses the stage-selection policy recorded on
2026-08-28 (`AUTO_ADVANCE_STAGES=false`, `STUDENT_STAGE_SELECTION=true`).
Students can explicitly select a Thinking Path stage; a coach ADVANCE
recommendation does not automatically move them. This supersedes the earlier
Month-1 auto-advance pilot override. Operator release steps:
[`PRODUCTION_RELEASE_CHECKLIST.md`](PRODUCTION_RELEASE_CHECKLIST.md).

## Providers and retrieval

Repository defaults in `.env.example` and `backend/settings.py` are cost-safe:

```env
MODEL_PROVIDER=mock
MOCK_OPENAI=true
AUTO_ADVANCE_STAGES=false
USE_LOCAL_API=true
OPENAI_API_KEY=
OPENAI_CHAT_MODEL=gpt-5.6-luna
```

Set `MODEL_PROVIDER=openai`, `MODEL_PROVIDER=bedrock`, or
`MODEL_PROVIDER=agentcore` in a private `.env`
when needed. Do not hard-code a model in the workflow. The mock provider must
be deterministic and support all automated tests without network access.
Bedrock and AgentCore use the default AWS credential chain (SSO or the EC2 role).
Never put access keys in `.env`. The Bedrock adapter is
generation-only and must not call RetrieveAndGenerate. AgentCore is the
production generation path: FastAPI stays the application; the runtime is not
the student UI. Invokes are stateless so DSQL/SQLite ``messages`` remain the
only durable transcript. Do not port POC JSON, DynamoDB, or AgentCore session
caches as chat history. See the [model provider guide](providers/MODEL_PROVIDERS.md)
for provider contracts, settings, IAM, streaming, and validation.

Retrieval is notebook-isolated and source-first. The current local adapter
creates sentence-aware overlapping chunks from extracted selected-source text
(precomputed `derived/chunks.v1.json` when valid; otherwise at query time),
ranks them against the current turn plus bounded continuity,
and records stable source/chunk audit mappings on the assistant message. It
retrieves only selected sources from the active notebook and returns citations
that open the correct source. Student uploads remain private. Enforce existing
file-count and size limits, prevent path traversal, validate content types
where practical, and preserve legacy source attachments. When
``KNOWLEDGE_BASE_ID`` is set outside mock mode, locked Lecture Notes/Readings
use Bedrock Knowledge Base ``Retrieve`` (never ``RetrieveAndGenerate``) mapped
onto selected ``[S#]`` labels; student uploads stay on the local chunk
retriever. Virtual shared course sources do not store extracted text and must
not fall back to a synthesized placeholder chunk. Empty ``KNOWLEDGE_BASE_ID``
is an evidence gap for those sources. The composer, citations, and coaching
specialist tools do not change.

## Development sequence

Work in these verified phases:

1. Audit, Git/data safety baseline, and compatibility tests.
2. Domain models, repository ports, and local repository adapters.
3. FastAPI API and typed Streamlit API client, with old facades kept until
   migration is complete.
4. Structured educational assessment and one LangGraph workflow.
5. Confirmation-based phase transitions and durable checkpoint state.
6. OpenAI and deterministic mock provider adapters; local retrieval.
7. Streamlit migration, source/citation integration, graph inspection, and
   visual QA.
8. Full regression, migration, restart, and optional approved
   OpenAI smoke testing.

At every phase, update `IMPLEMENTATION_STATUS.md` with evidence before moving
on. Do not begin a broad rewrite without first preserving behavior through
targeted tests.

## Required verification

Automated tests must require no paid API or internet connection. Cover domain
validation, repository contracts, migration, graph routing, all five phases,
stay/advance recommendations, confirmation/rejection, restart resumption,
source selection, citations, notebook isolation, provider errors, streaming
failures, upload safety, API contracts, and Streamlit client behavior.

Separately gate OpenAI smoke tests. UI changes require browser
checks on desktop and 390 px mobile with a clean console.

Final acceptance requires successful Streamlit and FastAPI startup, mock mode,
preserved user data, streaming, grounded
citations, inspectable graph state, confirmed progress transitions, recovery
after restart, responsive UI, passing tests, and accurate setup documentation.

## Learning-funnel baseline (ticket 09 / #22)

`backend/learning_signals.py` defines bounded typed explicit usefulness ratings,
citation-action receipts and recommendation-detail openings. The existing
owner-scoped workspace path persists at most three receipt fields in assistant
message metadata; SQLite acquires write authority before checking active revision
and merging receipts, and DSQL uses the whole-operation OCC wrapper. No schema or
student-data migration. The HTTP/client boundary returns canonical typed receipts
so fragment feedback updates preserve the loaded transcript window.

The existing authorized, fail-closed audited lecturer API exposes an aggregate
`/api/v1/professor/learning-funnel`, rendered under Participation. Metadata-only
repository reads exclude superseded/internal rows; no transcript or identity is
returned. Lecture usefulness/return and project recommendation/confirmation/saved
turn proxies remain separate, with population definitions and Guest/notebook
limits. Invalid imported receipt fields remain unknown while valid sibling fields
survive. Human-reviewed substance is explicitly unknown and uses the existing
Research workflow. See [LEARNING_BASELINE.md](LEARNING_BASELINE.md) for exact
numerators/denominators, reproducible desktop/mobile tasks and the pending
5–8-student formative study; engineering/mock evidence is not student outcomes.
