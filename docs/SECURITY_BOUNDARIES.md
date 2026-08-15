# Security boundaries

This describes **enforced** application boundaries, not prompt-only rules.

```text
Student → Streamlit → FastAPI
                         │
            Cognito identity / notebook ownership
                         │
            DSQL state + selected sources
                         │
            Composite retrieval (course KB + student extract)
                         │
            Application-composed coaching brief
                         │
            AgentCore / Strands (no KB/S3 tools)
                         │
            Validate coach_turn + citations
                         │
            Atomic DSQL persistence
```

## Identity and ownership

- Cognito proves the browser session. FastAPI maps `sub` to the application
  user and scopes notebooks, sources, messages, images, and S3 keys to that
  owner.
- Student A cannot retrieve Student B's notebook, source, extracted text,
  image, conversation, or S3 object by forging a `source_id`, guessing an
  object key, or placing instructions in an uploaded document.
- Client-supplied `history`, `retrieved_chunks`, `image_inputs`, and
  `source_context` are rejected. The server loads those from the store.

## Retrieval authorization

- Retrieval runs only after selected sources are loaded for the authenticated
  notebook.
- Course Retrieve results are mapped onto locked `object_key` values using
  exact canonical equality after URL decoding, slash normalization, and S3 URI
  extraction. Foreign buckets and unselected keys are dropped. Suffix overlap
  is not a match.
- Student retrieval is local to extracted text of selected sources in the
  current notebook.
- The AgentCore coach has no Knowledge Base tool and no S3 tool. It cannot
  pass `user_id`, `notebook_id`, `bucket`, `object_key`, `knowledge_base_id`,
  or `source_id` as model-controlled retrieval parameters.

## Citations and structured output

- `[S#]` in model output must resolve to a retrieved, selected, authorized
  source. Fabricated labels such as `[S99]` are not persisted as
  `source_refs`.
- Malformed AgentCore JSON, prose, or schema-invalid `coach_turn` fails
  closed. No partial coach turn is persisted.
- Research coding may degrade independently; it does not salvage invalid
  coaching output and does not by itself invalidate a valid coach reply.

## Prompt injection

Retrieved course text, student uploads, websites, student messages, prior
conversation turns, and derived conversation memory are untrusted evidence.
The composer delimits them. Shared, stage, and runtime sections remain
authoritative. Authorization is structural, not instructional.

## Conversation integrity

- DSQL / SQLite is the only authoritative transcript.
- The context planner is full-history-first. Compression affects model input
  only and never deletes stored messages. `conversation_memory` is a derived
  cache/projection that is invalidated when `conversation_revision` changes.
- AgentCore Memory is not a production transcript. Runtime sessions are
  `stateless-<uuid>`.
- Conversation revision keeps the active branch authoritative. Superseded
  branches do not feed current coach history or active research analytics.
- Idempotent retries do not duplicate student/coach pairs or transitions.

## Logging and secrets

Do not log secrets, full private source content, or raw AWS exception bodies
to clients. Provider failures map to category-only errors.
