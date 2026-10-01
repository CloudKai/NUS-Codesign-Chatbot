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
              deterministic retrieval gate
                            │
                ┌───────────┴───────────┐
                │ skip                  │ retrieve
                ▼                       ▼
        conversation memory     Course materials
        + <=6 recent turns              │
        + <=3000 hist tokens            │
                                Bedrock KB Retrieve
                                + student-source retrieve
                                + ownership / selected-source checks
                                        │
                                        ▼
                              Unified [S#] excerpts (≤4, ~8k chars)
                            │
                            ▼
              FastAPI runtime rules + untrusted evidence
                            │
                            ▼
              AgentCore fast_chat (one FastAPI invoke; Haiku span count
              needs live traces)
                            │
              rare: needs_source_retrieval after skip
                            │
                            ▼
              FastAPI retrieves once, one FastAPI Haiku retry
              (provisional first result is not persisted)
```

A rare accuracy fallback runs only when the deterministic gate skipped
retrieval, selected sources exist, and Haiku sets
`needs_source_retrieval=true`. FastAPI owns that retrieve. AgentCore still
has `tools=[]` and cannot search KB, S3, or DSQL. Maximum two Haiku calls.

## Authority

| Layer | Owns |
|---|---|
| FastAPI / application services | Identity, notebook ownership, selected source IDs, retrieval scope, workflow |
| DSQL / SQLite | Authoritative transcript and application state |
| S3 | File bytes (canonical course objects and owner-scoped student objects) |
| Bedrock Knowledge Base | Semantic retrieve over official course material only |
| Local student retriever | Notebook-scoped chunks of extracted student text |
| AgentCore / Strands | Pedagogical reasoning over authorized `[S#]` evidence. No KB or S3 tools. One FastAPI `fast_chat` invoke for normal chat. Live traces must confirm event-loop/Haiku span count. |

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
RetrieveAndGenerate). Production Knowledge Base `JUQNP8AZAZ` is type
**MANAGED**, so Retrieve uses `managedSearchConfiguration`. Classic VECTOR
Knowledge Bases keep `vectorSearchConfiguration`. `compose.prod.yaml` sets
`KNOWLEDGE_BASE_TYPE=MANAGED`. Sending `vectorSearchConfiguration` to a
MANAGED Knowledge Base raises `ValidationException` and becomes
`course_retrieval_unavailable`.

When selected course sources have `course_material_id`
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

If the live Knowledge Base does not yet contain that attribute, operators must
set `KNOWLEDGE_BASE_METADATA_FILTER_MODE` explicitly:

- `required` (code default, production target after sidecar ingest): send
  `equals` for one selected `course_material_id` or `in` for several. A
  `ValidationException` or timeout is an evidence gap. There is **no**
  automatic unfiltered retry.
- `degraded_unfiltered`: one unfiltered Retrieve, then exact selected
  bucket/object-key validation. Temporary operator fallback until sidecars
  exist in the index.
- `disabled`: do not call Retrieve.

`KNOWLEDGE_BASE_STRICT_METADATA_FILTER=true` still maps to `required`. False
no longer skips the MANAGED filter.

Retrieve is optional evidence gathering: the adapter uses a wall-clock timeout
(`KNOWLEDGE_BASE_RETRIEVE_TIMEOUT_SECONDS`, default 10s, justified as twice
the previous 5s fail-closed cap and far below the 120s UI timeout),
`total_max_attempts=1`, and `numberOfResults` equal to
`FAST_CHAT_RETRIEVAL_MAX_CHUNKS` (default 4). A Python future timeout does not
cancel boto; abandoned calls reuse a shared executor
(`KNOWLEDGE_BASE_RETRIEVE_EXECUTOR_WORKERS`, default 4). The executor queue is
not used as a backlog: admission is a semaphore sized to the worker count, so
excess calls fail closed immediately as `unavailable` /
`capacity_exhausted` instead of queueing ghost Retrieves.

Post-retrieval object-key **and bucket** validation is always applied. A hit
whose bucket cannot be positively confirmed against `COURSE_MATERIALS_BUCKET`
is dropped, including empty configured buckets and empty-bucket URIs such as
`s3:///course/lectureNotes/week1.pdf`. Production startup fails if a
Knowledge Base is configured without `COURSE_MATERIALS_BUCKET`. The metadata
filter is retrieval precision only. FastAPI maps surviving chunks to
request-local `[S#]` labels.

Sidecar metadata files use the Bedrock S3 data-source format. Generate them
with `scripts/sync_course_kb_metadata.py` (dry-run by default; `--confirm`
uploads). Verify local identity with
`scripts/diagnostics/check_course_kb_metadata.py`. For the S3 data source,
Bedrock expects a sibling file named `<filename.ext>.metadata.json`:

```text
s3://<COURSE_MATERIALS_BUCKET>/course/lectureNotes/Week 1 Introduction to innovation v3.pdf
s3://<COURSE_MATERIALS_BUCKET>/course/lectureNotes/Week 1 Introduction to innovation v3.pdf.metadata.json
```

```json
{
  "metadataAttributes": {
    "course_material_id": {
      "value": {
        "type": "STRING",
        "stringValue": "lecture_week_1_introduction_to_innovation_v3"
      },
      "includeForEmbedding": false
    }
  }
}
```

Live validation procedure is **documentation only** and lives in
[`KB_REQUIRED_MODE_RUNBOOK.md`](KB_REQUIRED_MODE_RUNBOOK.md). Generate
sidecars → upload (`--confirm`) → sync the data source → wait for
`COMPLETE` → local metadata verification → one `equals` Retrieve → one
`in` Retrieve → only then set
`KNOWLEDGE_BASE_METADATA_FILTER_MODE=required`. Do not treat an unfiltered
Retrieve as proof that filtered mode is live. Those live AWS steps are not
executed by this repository's pytest.

Until sidecars are ingested, set `degraded_unfiltered` explicitly on the
live env. Do not switch production off `required` as a code fix.

Live Knowledge Base `JUQNP8AZAZ` previously returned HTTPS S3 locations under
`CDE2300_course_files_export/Course_materials/...`. The student catalog
selects `course/lectureNotes/...` and `course/readings/...`. Those keys do
not match. Re-point the data source at `s3://<COURSE_MATERIALS_BUCKET>/course/`
and complete ingestion/sync. Do not map the export prefix onto catalog keys
in application code.

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
Chunking is deterministic (~1,800 characters, overlap, per-source diversity).
Selected student sources are hydrated from `derived/chunks.v1.json` when that
artifact is valid; otherwise extracted text is chunked at query time.
Normal fast chat then keeps at most 4 chunks / 8,000 characters. Student
uploads keep extracted text; they do not use the shared course Knowledge Base.

## Unified evidence

Course and student chunks share `RetrievedChunk`:

- `source_id`, `label` (`[S#]`), `title`, `chunk_id`, `text`, `score`
- `group`, `url`, `retrieval_origin` (`knowledge_base` or `extracted_text`)

The composer presents them as one `<retrieved_course_context>` block with
stable `[S#]` labels for the turn. Internal ids such as `S1-C2` or `S1-KB1`
are audit metadata, not student-facing citations.

`retrieval_refs` record what was supplied to the model. `source_refs` record
what the model actually cited after application validation.

Citation resolution after the model call uses the request-scoped turn
snapshot (`TurnSnapshot.sources_by_id`) plus the selected `source_ids`
already on the `CoachRequest`. It does not list the S3 course catalog
again and does not call `get_source` per cited id. Course-catalog
`list_prefix` still runs once per folder when the snapshot is built
(Lecture Notes and Readings), before the model call.

## Untrusted evidence

Course PDFs, student uploads, websites, extracted text, project context, and
prior student messages are untrusted. Instructions inside that text cannot
override shared coaching rules, stage rules, authorization, output schema, or
runtime rules.
