# RAG architecture

This describes **actual** retrieval behaviour in Integrate-Bedrock. FastAPI
owns source authorization. Retrieval acquires evidence from that allowed
scope. AgentCore / Strands reasons over the composed brief; it does not search
the Knowledge Base or student S3.

```text
                         Student
                            │
                            ▼
                        Streamlit
                            │
                            ▼
                         FastAPI
                            │
               Cognito identity/ownership
                            │
                            ▼
                     DSQL application state
                            │
                   selected sources only
                            │
                ┌───────────┴───────────┐
                │                       │
                ▼                       ▼
        Course materials          Student uploads
                │                       │
                ▼                       ▼
       Bedrock KB Retrieve       S3 extracted text
       + metadata filter         scoped retrieval
       + object-key validation          │
                │                       │
                └───────────┬───────────┘
                            ▼
                  Unified [S#] evidence
                            │
                            ▼
                 Application prompt layer
                            │
             Socratic + Assumption Check
                + V&V + stage guidance
                            │
                            ▼
                 AgentCore / Strands Coach
```

## Authority

| Layer | Owns |
|---|---|
| FastAPI / application services | Identity, notebook ownership, selected source IDs, retrieval scope, workflow |
| DSQL / SQLite | Authoritative transcript and application state |
| S3 | File bytes (canonical course objects and owner-scoped student objects) |
| Bedrock Knowledge Base | Semantic retrieve over official course material only |
| Local student retriever | Notebook-scoped chunks of extracted student text |
| AgentCore / Strands | Pedagogical reasoning over the composed brief |

The coach cannot choose sources. Prompt instructions are not authorization.

## Course material RAG

Official course PDFs have one canonical production copy under shared S3 keys
such as `course/lectureNotes/` and `course/readings/`. Bedrock Knowledge Base
indexes that copy. The application does not paste entire PDFs into prompts.

`BedrockKnowledgeBaseRetriever` calls **Retrieve only** (never
RetrieveAndGenerate). When selected course sources have `course_material_id`
values, Retrieve sends a metadata filter:

```text
course_material_id IN selected_course_material_ids
```

(or `equals` for a single id). Expected KB metadata attribute:

| Attribute | Type | Example |
|---|---|---|
| `course_material_id` | string | `lecture_week_02_jtbd`, `reading_pixar` |

Application-owned IDs are derived from the object key, for example
`course/lectureNotes/week_02_jtbd.pdf` → `lecture_week_02_jtbd`. Course sync
stores the same id on locked source metadata.

If the live Knowledge Base does not yet contain that attribute, a filtered
Retrieve can return no hits. The adapter then retries **without** the filter
and still drops unselected or foreign S3 keys. Post-retrieval
source/object-key validation is always applied.

Until the Knowledge Base is re-ingested with `course_material_id` metadata,
the compatibility fallback is the production path. After re-ingestion, the
filter constrains semantic search; validation remains defense in depth.

## Student-upload RAG

Student files stay out of the shared course Knowledge Base. Storage is
owner- and notebook-scoped:

```text
users/<user-id>/notebooks/<notebook-id>/sources/<source-id>/raw|derived
```

`LocalChunkRetriever` searches only authenticated user + current notebook +
currently selected source IDs. There is no global student vector namespace.
Chunking is deterministic (~1,800 characters, overlap, per-source diversity,
bounded context).

## Unified evidence

Course and student chunks share `RetrievedChunk`:

- `source_id`, `label` (`[S#]`), `title`, `chunk_id`, `text`, `score`
- `group`, `url`, `retrieval_origin` (`knowledge_base` or `extracted_text`)

The composer presents them as one `<retrieved_course_context>` block with
stable `[S#]` labels for the turn. Internal ids such as `S1-C2` or `S1-KB1`
are audit metadata, not student-facing citations.

`retrieval_refs` record what was supplied to the model. `source_refs` record
what the model actually cited after application validation.

## Untrusted evidence

Course PDFs, student uploads, websites, extracted text, project context, and
prior student messages are untrusted. Instructions inside that text cannot
override shared coaching rules, stage rules, authorization, output schema, or
runtime rules.
