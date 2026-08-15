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
              FastAPI runtime rules + untrusted evidence
                            │
                            ▼
         AgentCore Q&A / Coaching / Review specialists
```

## Authority

| Layer | Owns |
|---|---|
| FastAPI / application services | Identity, notebook ownership, selected source IDs, retrieval scope, workflow |
| DSQL / SQLite | Authoritative transcript and application state |
| S3 | File bytes (canonical course objects and owner-scoped student objects) |
| Bedrock Knowledge Base | Semantic retrieve over official course material only |
| Local student retriever | Notebook-scoped chunks of extracted student text |
| AgentCore / Strands | Pedagogical reasoning over authorized `[S#]` evidence. No KB or S3 tools. |

The coach cannot choose sources. Prompt instructions are not authorization.

## Course material RAG

Official course PDFs have one canonical production copy under shared S3 keys
such as `course/lectureNotes/` and `course/readings/`. Bedrock Knowledge Base
indexes that copy. The application does not paste entire PDFs into prompts.

Shared course files appear in the student UI as **virtual catalog sources**.
They are not duplicated into each notebook's DSQL `sources` rows. Virtual
rows have empty `extractedText` on purpose. Course evidence must come from
Bedrock Knowledge Base `Retrieve`. A missing or empty `KNOWLEDGE_BASE_ID` is
an evidence gap, not a fallback onto `LocalChunkRetriever`. The local
retriever never ranks the display placeholder
`[This source is stored but has no analyzable text.]` as retrieved evidence.

`configured_context_retriever()` always returns `CompositeContextRetriever`.
Mock mode and an empty Knowledge Base id inject `knowledge_base=None` so
shared `course/` sources cannot become fake local chunks. Live providers with
a Knowledge Base id inject `BedrockKnowledgeBaseRetriever`.

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

Application-owned IDs are derived from the object key. Direct files keep the
historical form (`course/lectureNotes/week_02_jtbd.pdf` →
`lecture_week_02_jtbd`). Nested directories are included so the same filename
in two folders cannot collide (`course/readings/archive/week1.pdf` →
`reading_archive_week1`). Duplicate-id detection is available via
`course_material_id_collisions`. Course sync stores the same id on locked
source metadata.

If the live Knowledge Base does not yet contain that attribute, a filtered
Retrieve can return no hits. The adapter then retries **without** the filter
and still drops unselected or foreign S3 keys, unless
`KNOWLEDGE_BASE_STRICT_METADATA_FILTER=true`. Post-retrieval object-key
validation is always applied. Strict filter stays off until live KB metadata
is verified.

Until the Knowledge Base is re-ingested with `course_material_id` metadata,
the compatibility fallback is the production path. After re-ingestion, the
filter constrains semantic search; validation remains defense in depth. Do
not treat an unfiltered retry as proof that strict metadata mode is live.

Production with `COURSE_MATERIAL_SYNC_ENABLED=true` requires
`KNOWLEDGE_BASE_ID`, `KNOWLEDGE_BASE_REGION` (or `AWS_REGION`), and
`COURSE_MATERIALS_BUCKET`. Empty Knowledge Base id is valid only for mock
tests and local folder copies that still have extracted text.

## Student-upload RAG

Student files stay out of the shared course Knowledge Base. Storage is
owner- and notebook-scoped:

```text
users/<user-id>/notebooks/<notebook-id>/sources/<source-id>/raw|derived
```

`LocalChunkRetriever` searches only authenticated user + current notebook +
currently selected source IDs. There is no global student vector namespace.
Chunking is deterministic (~1,800 characters, overlap, per-source diversity,
bounded context). Student uploads keep extracted text; they do not use the
shared course Knowledge Base.

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
