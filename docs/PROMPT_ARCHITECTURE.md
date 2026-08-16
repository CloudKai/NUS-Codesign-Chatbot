# Prompt architecture

Canonical **pedagogy** for production AgentCore lives in
`agentcore_runtime/prompts/`. FastAPI sends **application runtime rules**
(stage id, Quick/Strict, language, allowed `[S#]`, source-grounding,
research-coding contract). `backend/prompts/` remains the composer used by
mock, OpenAI, and Bedrock Converse, and is the token-budget stand-in for
AgentCore planning. Do not treat those two packages as competing curricula
on the live AgentCore path.

## Ownership

```text
Streamlit
    ↓
FastAPI (Cognito, notebook ownership, selected sources, RAG)
    ↓
DSQL / SQLite  (authoritative transcript + persisted stage)
    ↓
HistoryContextPlanner  (fast_chat: memory + last 6 / 3000 hist tokens; Deep Review: broader)
    ↓
runtime_context + runtime_instructions   ← application rules
untrusted turn (project, optional evidence, student text)
    ↓
ONE AgentCore Runtime
    ├── fast_chat (Haiku 4.5; one call chooses coaching | qa)
    └── Deep Review (Sonnet 4.6; POST /api/v1/threads/{id}/deep-review)
    ↓
structured output  (fast_chat_turn | review_turn)
    ↓
FastAPI validates → workflow → atomic DSQL persist
```

Integrate-Bedrock is the production shell. AgentCore is the pedagogical
brain. DSQL is transcript/state authority. AgentCore Memory is not used.

Deep Review is an explicit FastAPI operation
(`POST /api/v1/threads/{thread_id}/deep-review`). FastAPI stamps
`specialist=review` only after client-controlled fields are discarded.
`POST /api/v1/coach/turn` cannot choose Sonnet. Unlock still requires 3
successful Coaching replies; opening the Review tab is display-only until
the student starts Deep Review.
Legacy router / Q&A / Coaching / Incremental Review payloads remain in the
runtime for compatibility and are unused on the active FastAPI path.

## Framework preservation matrix

| Feature | POC | Current app | Target AgentCore | Status |
|---|---|---|---|---|
| Socratic coaching | harness `phases.py` | `backend/prompts/shared/coaching.md` | `agentcore_runtime/prompts/shared_coaching.md` | MERGE |
| Stage purpose / readiness | POC `COACHING_TOPICS` | `backend/prompts/stages/*.md` | `agentcore_runtime/prompts/stages/` (`ethics_critical.md` for `deep_analysis`) | MERGE |
| Assumption Check | POC silent block | shared coaching | runtime shared coaching | PRESERVE |
| V&V | absent in POC | shared coaching | runtime shared coaching | IMPROVE |
| Silent vs surface ethics / AT-EAI | POC ethics blocks | shared + `deep_analysis.md` | runtime shared + `ethics_critical.md` | MERGE |
| CLEAR / Facione / HCTSR research | not in POC runtime | shared coaching + research models | runtime shared + same structured fields | PRESERVE |
| Source grounding / citations | POC Q&A tools | composer + RAG | untrusted evidence `[S#]`; no KB tools | KEEP APPLICATION-SIDE |
| Quick/Strict | n/a | composer runtime instructions | `runtime_context.response_detail` | KEEP APPLICATION-SIDE |
| Research independence | n/a | shared coaching | runtime shared coaching | PRESERVE |
| Q&A specialist | POC + unrestricted KB tools | none | runtime `prompts/qa.md`, pre-retrieved evidence | IMPROVE |
| Scoring specialist | markdown critique | application Review tab | Formative Review specialist, not a grade | MERGE / RENAME |
| Duplicate full curriculum on AgentCore trusted channel | n/a | previously sent `backend/prompts` as trusted | removed from AgentCore payload | REMOVE DUPLICATE |

`backend/prompts/` is **KEEP APPLICATION-SIDE** for mock/OpenAI/Bedrock until
those providers are retired. Semantic equivalence is covered by prompt-content
tests; live AgentCore evaluation is not this pass.

## Current test architecture

```text
Streamlit
    ↓
FastAPI (Cognito-authenticated notebook)
    ↓
DSQL / SQLite authoritative current_stage
    ↓
shared prompt + stage file  (backend/prompts/)
    ↓
selected notebook sources (DSQL/SQLite metadata + S3/local extracted text)
    ↓
LocalChunkRetriever, or CompositeContextRetriever (Bedrock Retrieve for
locked course sources + local chunks for student uploads)
    ↓
RetrievalResult.context → PromptContext.retrieved_course_context
    ↓
PromptComposer (server-side, no Streamlit / OpenAI / Bedrock imports)
    ↓
OpenAI, Bedrock Converse, AgentCore Runtime, or deterministic mock
    ↓
structured coaching response (recommendation only)
    ↓
application transition logic → confirmation / auto-advance → persist stage
```

Authoritative stage, history, selected sources, and source context are resolved
by `CoachApplicationService` from the notebook store. Clients cannot submit
arbitrary prompt text or stage instructions. Providers never persist stage
changes.

## Current RAG structure

| Layer | Current development behavior |
|---|---|
| Ingestion | Existing upload/text/URL/course-sync code extracts bounded text. Raw bytes and derived text remain separate objects under S3 in production. |
| Source authority | `sources.selected` plus notebook ownership determines the only documents eligible for a turn. Unselected and other-notebook sources never reach retrieval. |
| Query | Current student message has the strongest weight. The last two student messages, project context, and learning summary provide lower-weight continuity. |
| Chunking | `LocalChunkRetriever` creates sentence-aware ~1,800-character chunks with 220-character overlap at query time. No new database migration is needed. |
| Ranking | Deterministic weighted lexical/BM25-style scoring uses term rarity, phrase overlap, title matches, and source diversity. Generic queries receive bounded representative excerpts. |
| Budget | Fast chat: deterministic retrieval gate, then at most `FAST_CHAT_RETRIEVAL_MAX_CHUNKS` (default 4) chunks and `FAST_CHAT_RETRIEVAL_MAX_CHARS` (default 8,000) characters. Deep Review may use the larger composer ceiling. |
| Images | Selected images travel as model image inputs; a text marker preserves their stable `[S#]` mapping. |
| Citations | `[S#]` is stable for the selected-source order. Internal chunk IDs such as `S1-C2` are audit metadata only and are never student-facing citation syntax. |
| Audit | The assistant message records `retrieval_refs` containing source ID, stable label, chunk ID, focused excerpt, and score. `source_refs` remains reserved for sources actually cited in the response. |

The retriever sees full extracted text locally, but the generation model sees
only the selected excerpts. Citation previews are focused around the matching
query evidence instead of the beginning of the document. Production generation
may use AgentCore Runtime (`MODEL_PROVIDER=agentcore`); the user payload is
this application's composed CDE2300 prompt plus bounded DSQL history as
Converse `messages`. Do not copy the POC CDE2500 Q&A specialist prompt.
Coaching must not receive Knowledge Base tools. Course grounding uses
server-side `Retrieve` when `KNOWLEDGE_BASE_ID` is set.

## Prompt structure

The composer orders and delimits these sections:

1. shared Socratic coaching behavior;
2. the one authoritative Thinking Path stage prompt;
3. student project context;
4. retrieved source excerpts;
5. bounded learning summary / derived ConversationMemory and, unless the
   provider already sends DSQL history as conversation messages, recent
   conversation. Fast chat sends at most 6 recent verbatim message objects,
   and at most ~3,000 estimated recent-history tokens, with each historical
   message capped at ~1,500 estimated tokens. The current student message
   stays separate and is not history-capped. Deep Review may keep a larger
   window.
6. the current student message;
7. runtime rules for language, detail, grounding, citations, and structured
   assessment.

Retrieved content is explicitly untrusted evidence. It cannot override shared,
stage, authorization, workflow, or runtime instructions. The shared prompt
includes an internal Interpret → Assumption/V&V check → one Socratic probe →
reflection trigger. Those headings are not student-facing. Grounding rules
require claim-level `[S#]` citations, prohibit invented sources/quotes, and
tell the coach to identify an evidence gap when the retrieved excerpts do not
answer the question. Trusted prompt files must not contain literal
prompt-attack examples; quoted override attempts remain evidence only when they
genuinely appear in retrieved or student content.

The composer exposes two bounded products in addition to `composed_text`:

- `trusted_instructions`: shared coaching, the authoritative stage file, and
  runtime/output rules;
- `untrusted_turn_text`: project context, retrieved evidence, summary/memory,
  and the current student contribution.

Mock, OpenAI, and Bedrock Converse still send the ordered `composed_text`.
AgentCore sends trusted instructions in a dedicated `trusted_instructions`
harness field and keeps DSQL history plus the untrusted current turn in
`messages`. Fast-chat token budgeting estimates the AgentCore system prompt
through `agentcore_runtime/system_prompt_budget.py` (the same canonical
loader the runtime uses) plus the untrusted turn, history, memory, RAG, and
per-message overhead. That local total is what the 12k/16k Fast Chat
targets mean. It is not a Bedrock CountTokens measurement.

AgentCore omits duplicated `<recent_messages>` from the untrusted turn because
the same turns are already Converse `messages`. When history no longer fits,
derived `<conversation_memory>` is inserted once between summary and
recent_messages. That block is untrusted student/project content, not
instructions. Mock, OpenAI, and Bedrock Converse keep the inline recent-history
block unless a provider opts into the same planner.

## Production Knowledge Base path

```text
Streamlit
    ↓
FastAPI
    ↓
DSQL current_stage
    ↓
selected source IDs + notebook/user filter
    ↓
Bedrock Knowledge Base `Retrieve` adapter implementing ContextRetriever
(locked Lecture Notes/Readings only; student uploads stay local)
    ↓
RetrievalResult (stable source IDs/labels + chunks)
    ↓
same PromptComposer + same educational workflow
    ↓
configured generation provider (AgentCore Runtime, or Bedrock/OpenAI fallback)
```

`backend/bedrock_retrieve.py` implements this adapter. `configured_context_retriever()`
always returns `CompositeContextRetriever`. A live Knowledge Base id is injected
only when the provider is not mock and `MOCK_OPENAI` is false. Empty
`KNOWLEDGE_BASE_ID` keeps `knowledge_base=None` so virtual course sources
become an evidence gap instead of local placeholder chunks. It:

- filters retrieval by selected source IDs already loaded for the notebook;
- sends a `course_material_id` Knowledge Base metadata filter when ids exist,
  then retries without the filter if that returns no hits (compatibility until
  the KB is re-ingested with metadata);
- maps S3 locations onto locked course `object_key` values and `[S#]` labels
  using exact canonical key equality (URL-decoded, slash-normalized, S3 URI
  extracted). Suffix matching is not used, so `week1.pdf` cannot match
  `archive/week1.pdf` or `myweek1.pdf`;
- returns bounded `RetrievedChunk` values with `retrieval_origin`;
- uses Knowledge Base `Retrieve`, then feeds the existing composer/workflow, so
  stage decisions and persistence do not move into `RetrieveAndGenerate`;
- drops results whose S3 keys are outside the selected notebook sources.

The application already enforces the final scope check, so a faulty adapter
cannot introduce another notebook's chunk.

## Package layout

| Path | Role |
|---|---|
| `backend/prompts/shared/coaching.md` | Shared Socratic coach behaviour, Assumption Check, V&V |
| `backend/prompts/stages/{problem_identification,concept_generation,design_specification,deep_analysis,reflection}.md` | Stage purpose, coaching strategy, advance/stay criteria. `deep_analysis.md` is student-facing Ethics & Critical Thinking |
| `backend/prompts/loader.py` | UTF-8 load + in-process cache; stage IDs from `STAGE_BY_ID` |
| `backend/prompts/composer.py` | Ordered composition with explicit delimiters and a trusted/untrusted channel split |
| `backend/retrieval.py` | Retrieval port, local chunker/ranker, composite splitter |
| `backend/bedrock_retrieve.py` | Bedrock Knowledge Base `Retrieve` adapter (injected client in tests) |
| `backend/application.py` | Authoritative source selection, retrieval injection, citation filtering, audit persistence |

## Local preview (no network)

```sh
.venv/bin/python scripts/preview_prompt.py --stage evidence
```

Uses demo context only. Does not read the student database, tokens, or API keys.
