# Local demonstration architecture

## Purpose and authority

This document is the architecture authority for Co-design Chatbot. It records
both the **implemented architecture** and explicit **target work**. A target is
not evidence that a feature exists. The working application and regression
tests remain the behavior specification.

The application is a student-facing critical-thinking coach with a Streamlit
workspace, a typed FastAPI boundary, one six-stage LangGraph workflow, local or
AWS-backed persistence adapters, and replaceable model/retrieval providers.
Automated development must work without AWS, internet access, or paid model
calls.

## Implemented system

```text
Browser
  -> Streamlit presentation (streamlit_app.py, ui/)
       -> WorkspaceFacade
            -> typed LocalApiClient -> FastAPI /api/v1       [normal startup]
            -> WorkspaceService in process                   [development fallback]
       -> typed CoachRequest
            -> FastAPI or CoachApplicationService in process
                 -> authoritative store/repositories
                 -> selected-source LocalChunkRetriever
                 -> one CoachWorkflow / LangGraph
                 -> configured mock or OpenAI provider
                 -> SQLite + local files, or DSQL + S3
```

`scripts/start.sh` is the canonical local launcher. It starts FastAPI and
Streamlit and forces `USE_LOCAL_API=true`. When API mode is disabled, Streamlit
still uses the same application/workflow services in process. The legacy
`StudentChatEngine` is retained for compatibility tests and is not the current
student-turn fallback.

### Current boundaries

| Layer | Implemented responsibility |
|---|---|
| Presentation | `ui/` renders state and calls `ui.runtime.WorkspaceFacade` and typed coach helpers. Panels do not open SQLite, read source paths, or call model SDKs. |
| API | `backend/api.py` composes owner-scoped workspace CRUD plus versioned health/readiness, auth, learning, revise, coach/stream, graph, and transition routes. |
| Application | `CoachApplicationService`, `WorkspaceService`, and `LearningProgressService` orchestrate use cases and transactions. |
| Domain/workflow | Pydantic contracts, six stage definitions, prompt composition, structured assessment validation, and one `CoachWorkflow`. |
| Persistence | `StudentStore`/`DsqlStudentStore`, narrow repository adapters, and local/S3 `FileStorage` implementations. |
| Providers/retrieval | Deterministic mock and OpenAI coach adapters plus a notebook-scoped local selected-source retriever. |

Folder organization is not a current UI/API feature. An ignored `folder_id`
parameter remains only for compatibility. Do not restore folders merely to
match older documentation.

### Implemented versus target

| Concern | Implemented now | Target / intentionally deferred |
|---|---|---|
| Coaching workflow | One LangGraph flow: load → assess → recommend → format | Further graph decomposition only when it preserves the same educational contract |
| Graph checkpoint | LangGraph `MemorySaver`; graph inspection is process-local | Durable graph inspection/checkpoint adapter if operationally required |
| Durable learning state | Messages, assessments, pending/resolved transitions, journey metadata, idempotency markers, and conversation revisions persist in SQLite/DSQL | No separate graph-state table is currently planned |
| Streaming | Early status event, then buffered completed response split into NDJSON token events | True upstream provider-token streaming |
| Edit | Append-only user-message revise/resubmit with revision CAS and stable idempotency key | Regenerate remains unavailable |
| Workspace | Notebook, message, source, preference, learning, and transition APIs | No folder API; no unrestricted metadata API |
| Retrieval | Query-time deterministic lexical chunking/ranking over selected sources | Bedrock Knowledge Base adapter behind the same retrieval contract |
| Production storage | DSQL and S3 adapters/configuration exist; live cutover remains an operator gate | Live wire-level DSQL/S3 proof and future Bedrock course-material path |

## Behavior compatibility baseline

Preserve:

- notebooks, history, source upload/selection/preview/download/removal;
- source-grounded conversation, stable citations, buffered streaming status,
  model configuration, Quick/Strict coaching profiles backed by the compatible
  ``short``/``long`` values, and persistence;
- Focus, Evidence, Assumptions, Perspectives, Synthesis, and Conclusion;
- prompt summaries, learning summaries, working conclusions, changes in
  understanding, and critical-understanding assessment;
- confirmation-gated progression, audited auto-advance, and audited student
  stage selection according to configuration;
- append-only message revision history and existing SQLite/DSQL data semantics;
- authenticated owner isolation and notebook-scoped retrieval/object keys.

Existing SQLite data, source files, notebook identities, and user-visible
entrypoints must remain usable. Schema changes require explicit additive
migrations, safe defaults, backup instructions, deterministic tests, and a
rollback path. Never reset or recreate user databases as a normal startup step.

## Educational workflow

The server reloads authoritative notebook state, canonical active-branch
history, selected sources, retrieval context, and image inputs. Client-supplied
stage, history, source IDs, source context, and image payloads cannot override
persisted ownership or learning state.

For each turn the application:

1. resolves the authenticated owner and notebook;
2. validates the current conversation revision and idempotency reservation;
3. loads canonical history, journey state, and selected sources;
4. retrieves bounded notebook-scoped evidence;
5. composes the shared prompt plus exactly one authoritative stage prompt;
6. obtains and validates a structured educational assessment;
7. normalizes the terminal Conclusion stage;
8. persists the user/assistant turn, assessment, source audit snapshot, summary,
   and pending/automatic transition atomically where required;
9. exposes status, graph-summary, buffered token, and completed-turn events;
10. replays an identical completed request without another provider call.

Each assessment includes the stage, contribution summary, stage assessment,
evidence and assumption gaps, critical-understanding level, confidence,
stay/advance recommendation, rationale, guidance questions, learning summary,
working conclusion, understanding change, citations, six integer Facione
dimension scores, supportive strengths/improvements, and response text.

With `AUTO_ADVANCE_STAGES=false` and `STUDENT_STAGE_SELECTION=false`, an
ADVANCE recommendation persists as pending until the student confirms it.
With audited auto-advance enabled, it applies immediately and remains recorded.
With `STUDENT_STAGE_SELECTION=true`, the student may select any non-current
stage; selection takes precedence over auto-advance and does not manufacture
completion or Facione evidence.

## Providers and retrieval

Repository defaults are cost-safe:

```env
MODEL_PROVIDER=mock
MOCK_OPENAI=true
AUTO_ADVANCE_STAGES=false
STUDENT_STAGE_SELECTION=false
USE_LOCAL_API=true
OPENAI_API_KEY=
OPENAI_CHAT_MODEL=gpt-5.6-luna
```

Set `MODEL_PROVIDER=openai` only in a private `.env`. Tests clear the OpenAI
key and use deterministic providers. Provider-specific response objects must
not escape infrastructure adapters.

Retrieval is source-first and notebook-isolated. The local adapter creates
overlapping sentence-aware chunks at query time, ranks against the current
turn plus bounded continuity, and persists stable source/chunk audit mappings.
Only selected sources in the active notebook are eligible. `[S#]` labels are
student-facing; internal chunk IDs are audit-only. A future retrieval adapter
must preserve ownership filters, selected-source scope, bounded chunks, and
citation mapping.

## Persistence and security

The logical application tables are `users`, `oauth_login_states`, `notebooks`,
`messages`, and `sources`; preferences live on the user record. Local SQLite
uses foreign keys and additive compatibility migration. Aurora DSQL lacks those
foreign-key guarantees, so the application performs ordered child cleanup and
whole-unit OCC retries. See [`DATABASE.md`](DATABASE.md).

Cognito tokens stay in Secure/HttpOnly cookies according to environment and
are not stored in the application database or returned in API JSON. FastAPI
resolves the verified Cognito `sub`; every structured row, object key, source
read, retrieval result, and delete operation remains owner-scoped. Operational
logs must not contain prompts, source text, tokens, email addresses, or raw
private identifiers.

## Development and verification sequence

Use small reviewable phases:

1. inspect Git/data state and establish regression evidence;
2. add a failing deterministic regression before risky refactoring;
3. change one cohesive boundary at a time;
4. run the nearest focused suite;
5. run the full mock suite and compile checks at the phase boundary;
6. update `IMPLEMENTATION_STATUS.md` with behavior, compatibility, evidence,
   risks, and the next exact action;
7. perform browser or live infrastructure checks only when separately required
   and authorized.

Required automated coverage includes domain validation, repository behavior,
migrations, all six stages, stay/advance/selection modes, confirmation and
rejection, restart recovery of durable business state, source selection,
citations, notebook/owner isolation, provider failures, streaming event
contracts, upload safety, API contracts, and Streamlit behavior.

Current automated tests do not prove live Cognito, DSQL, S3, OpenAI,
ARM64 image execution, true provider-token streaming, or durable graph
inspection. Those gaps must remain explicit. See [`TESTING.md`](TESTING.md) and
the date-stamped evidence in [`MANUAL_PRODUCTION_QA.md`](MANUAL_PRODUCTION_QA.md).
