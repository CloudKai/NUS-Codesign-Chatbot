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
            Runtime rules + untrusted evidence (not a second curriculum)
                         │
            AgentCore / Strands specialists (no KB/S3 tools)
                         │
            Validate structured output + citations
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
- Client-supplied `history`, `retrieved_chunks`, `image_inputs`,
  `source_context`, and privileged `specialist` names are not authoritative.
  Normal `POST /api/v1/coach/turn` always clears `specialist`. Explicit Deep
  Review is `POST /api/v1/threads/{thread_id}/deep-review`, which loads
  owner, notebook, stage, history, sources, and eligibility from server
  state and stamps `specialist=review` only after that sanitization.

## AgentCore `InvokeAgentRuntime` IAM boundary

FastAPI authorization (Cognito cookie, notebook ownership, specialist
sanitization) applies to the student browser path:

```text
Student → Streamlit → FastAPI → InvokeAgentRuntime(phase=fast_chat)
```

It does **not** apply to a principal that can call
`bedrock-agentcore:InvokeAgentRuntime` on the published runtime ARN
directly. The published entrypoint (`agentcore_runtime/main.py`) still
dispatches on the request `phase`. A caller holding that IAM permission
can send `phase=review` (Sonnet Deep Review), `phase=router`, `phase=qa`,
`phase=coaching`, or `review_mode=incremental` and bypass every FastAPI
check, including Deep Review eligibility.

This is **not** a browser-reachable bypass. Streamlit and
`POST /api/v1/coach/turn` cannot reach those phases: the server clears
`specialist` and always invokes `fast_chat`. Do not "solve" this in
browser or UI code. A Streamlit change cannot constrain an IAM caller.

What actually mitigates it today:

- IAM least privilege: only the FastAPI / EC2 instance role should have
  `bedrock-agentcore:InvokeAgentRuntime` on this runtime ARN (and its
  `DEFAULT` endpoint).
- Do not grant that action to students, lecturers, CI users, or a broad
  `bedrock-agentcore:*` policy.

What would remove the dispatch hole (not implemented, not deployed):

- Runtime-side allowlisting so the published entrypoint accepts only
  `phase=fast_chat` and explicit `phase=review` + `review_mode=deep`, or
- Separate runtimes per model role (Haiku Fast Chat vs Sonnet Deep Review).

Until one of those is published, treat `InvokeAgentRuntime` as a privileged
generation backdoor, equivalent to holding the model invocation keys for
this runtime.

## Retrieval authorization

- Retrieval runs only after selected sources are loaded for the authenticated
  notebook.
- Course Retrieve results are mapped onto locked `object_key` values using
  exact canonical equality after URL decoding, slash normalization, and S3 URI
  extraction. The hit bucket must be present and equal
  `COURSE_MATERIALS_BUCKET`. Empty configured buckets, empty-bucket URIs
  (`s3:///...`), foreign buckets, and unselected keys are dropped. Suffix
  overlap is not a match. Production startup fails if a Knowledge Base is
  configured without `COURSE_MATERIALS_BUCKET`.
- Student retrieval is local to extracted text of selected sources in the
  current notebook.
- Virtual shared course sources have empty extracted text. They must not be
  converted into searchable placeholder chunks. If Knowledge Base Retrieve is
  unavailable or returns no validated excerpt, the coach receives an
  application-owned evidence-gap note, not a claim that the PDF has no text.
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
The composer delimits them and exposes a dedicated untrusted product.
Shared, stage, and runtime pedagogy for AgentCore is loaded inside the
runtime as system instruction. FastAPI runtime rules travel on
`trusted_instructions`. Authorization is structural, not instructional. Trusted prompt files must not include literal
jailbreak examples; those n-grams may appear only inside delimited retrieved
or student content.

Runtime guardrail intervention (`guardrail_intervened` or `action=BLOCKED`)
fails closed as category `safety_blocked`. Refusal text, prompt text, and AWS
trace bodies are never returned to the student UI or persisted.

On the Haiku and Sonnet `BedrockModel` path, `GUARDRAIL_ID` and
`GUARDRAIL_VERSION` are required and `guardrail_latest_message=True` so input
evaluation targets the latest untrusted user turn (current student/evidence),
not the trusted specialist curriculum. Specialists use `tools=[]`, so the
Strands tool-result guardrail wrapping bug does not apply. The runtime also
overrides Strands' structured-output repair prompt with
`Please use the output tool now.` so the latest-message scan does not treat
the framework recovery turn as `PROMPT_ATTACK`. Guardrail policy is unchanged.
The historical Luna
`OpenAIResponsesModel` path does not accept those constructor fields; it must
call Bedrock `ApplyGuardrail` on untrusted input and on model output. Missing
guardrail configuration fails production startup and the runtime loader.

## Conversation integrity

- DSQL / SQLite is the only authoritative transcript.
- Fast-chat planning always sends derived `conversation_memory` plus a bounded
  recent verbatim window (at most 6 messages, 3,000 estimated recent-history
  tokens, 1,500 per historical message). Deep Review may still use
  full-history when it fits that broader budget. Compression affects model
  input only and never deletes stored messages. `conversation_memory` is a
  derived cache/projection that is invalidated when `conversation_revision`
  changes.
- AgentCore Memory is not a production transcript. Runtime sessions are
  `stateless-<uuid>`.
- Conversation revision keeps the active branch authoritative. Superseded
  branches do not feed current coach history or active research analytics.
- Idempotent retries do not duplicate student/coach pairs or transitions.

## Logging and secrets

Do not log secrets, full private source content, or raw AWS exception bodies
to clients. Provider failures map to category-only errors.
