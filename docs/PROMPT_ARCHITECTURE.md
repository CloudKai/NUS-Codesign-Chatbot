# Prompt architecture

Framework-neutral retrieval and stage prompts for OpenAI/local testing of the
educational workflow. Prompt markdown files are the development/application
equivalent of future Bedrock Prompt Management. They contain **BEHAVIOUR**
only. Course PDFs are never prompt files; query-ranked chunks supply
**KNOWLEDGE** through `retrieved_course_context`.

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
LocalChunkRetriever (query-time chunks + deterministic lexical ranking)
    ↓
RetrievalResult.context → PromptContext.retrieved_course_context
    ↓
PromptComposer (server-side, no Streamlit / OpenAI / Bedrock imports)
    ↓
OpenAI (or deterministic mock)
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
| Budget | At most 8 chunks, at most 2 per source, and at most 16,000 retrieved characters enter the composer. The composer retains its independent 24,000-character retrieval ceiling. |
| Images | Selected images travel as model image inputs; a text marker preserves their stable `[S#]` mapping. |
| Citations | `[S#]` is stable for the selected-source order. Internal chunk IDs such as `S1-C2` are audit metadata only and are never student-facing citation syntax. |
| Audit | The assistant message records `retrieval_refs` containing source ID, stable label, chunk ID, focused excerpt, and score. `source_refs` remains reserved for sources actually cited in the response. |

The retriever sees full extracted text locally, but the generation model sees
only the selected excerpts. Citation previews are focused around the matching
query evidence instead of the beginning of the document.

## Prompt structure

The composer orders and delimits these sections:

1. shared Socratic coaching behavior;
2. the one authoritative Thinking Path stage prompt;
3. student project context;
4. retrieved source excerpts;
5. bounded learning summary and recent conversation;
6. the current student message;
7. runtime rules for language, detail, grounding, citations, and structured
   assessment.

Retrieved content is explicitly untrusted evidence. It cannot override shared,
stage, or runtime instructions. The grounding rules require claim-level `[S#]`
citations, prohibit invented sources/quotes, and tell the coach to identify an
evidence gap when the retrieved excerpts do not answer the question.

## Future architecture

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
    ↓
RetrievalResult (stable source IDs/labels + chunks)
    ↓
same PromptComposer + same educational workflow
    ↓
configured generation provider (Bedrock later)
```

For the Bedrock phase, implement a new `ContextRetriever` adapter and inject it
into `CoachApplicationService`. The adapter must:

- filter retrieval by authenticated user/notebook and the selected source IDs;
- store the durable application `source_id` in Knowledge Base metadata;
- map results back to the existing selected-source `[S#]` order;
- return bounded `RetrievedChunk` values with location metadata where
  available;
- use Knowledge Base `Retrieve`, then feed the existing composer/workflow, so
  stage decisions and persistence do not move into `RetrieveAndGenerate`;
- reject results whose source IDs or labels are outside the selected notebook.

The application already enforces the final scope check, so a faulty future
adapter cannot introduce another notebook's chunk.

## Package layout

| Path | Role |
|---|---|
| `backend/prompts/shared/coaching.md` | Shared Socratic coach behaviour |
| `backend/prompts/stages/{focus,evidence,assumptions,perspectives,synthesis,conclusion}.md` | Stage purpose, coaching strategy, advance/stay criteria |
| `backend/prompts/loader.py` | UTF-8 load + in-process cache; stage IDs from `STAGE_BY_ID` |
| `backend/prompts/composer.py` | Ordered composition with explicit delimiters |
| `backend/retrieval.py` | Retrieval port, local chunker/ranker, stable chunk metadata |
| `backend/application.py` | Authoritative source selection, retrieval injection, citation filtering, audit persistence |

## Local preview (no network)

```sh
.venv/bin/python scripts/preview_prompt.py --stage evidence
```

Uses demo context only. Does not read the student database, tokens, or API keys.
