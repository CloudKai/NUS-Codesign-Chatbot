# Security boundaries

This describes **enforced** application boundaries, not prompt-only rules.

```text
Student → React or protected Streamlit → FastAPI
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

## Browser request and download boundaries

- Every `/api/v1/reader/*` route requires a verified credential and a
  same-origin request. A write needs an `Origin` equal to
  `PUBLIC_API_BASE_URL`, and `Sec-Fetch-Site: cross-site` is refused on every
  method. `tests/http/test_security_readiness.py` posts to every registered
  reader route with no, foreign, look-alike and cross-site origins.
- The owner-scoped `/api/v1` write routes used by Streamlit (threads, sources,
  coach turn, Deep Review, lecturer research) refuse a write that carries a
  foreign `Origin` or fetch metadata other than `same-origin` or `none`.
  Streamlit's server-side client sends neither header, so it is unaffected.
  Caddy still does not publish these routes.
- Uploaded files never render on the application origin. Reader citation and
  source downloads are `application/octet-stream` attachments with
  `nosniff`. The owner-scoped source content route serves only PDF, PNG,
  JPEG, WEBP, GIF and `text/plain` inline; HTML, XML, script and any other
  type download as attachments.
- Coach Markdown renders with `skipHtml` and no images. A link survives only
  with an `http`, `https` or `mailto` address, opens in a new tab with
  `noopener noreferrer`, and any other link shows as plain text.
- Upload names are reduced to a base name on both `/` and `\`, so a Windows
  path cannot leave the title or the storage key.

## Guest workspaces

FastAPI resolves a verified Cognito account before considering a guest session.
Guest access is enabled explicitly with `GUEST_ACCESS_ENABLED`. A guest
credential authorizes only its own workspace. Lecturer and admin access
requires a verified account and a staff role.

FastAPI issues an opaque HttpOnly, SameSite=Lax guest cookie, stores its digest
and checks expiry and revocation on each request. The same-origin browser
renewal endpoint can extend the rolling 400-day expiry. A lost browser cookie
can make an unclaimed workspace inaccessible.

After a successful Cognito sign-in, a valid guest cookie from the same browser
allows automatic append into the verified account. The transfer verifies
owner-scoped file copies before committing ownership and source references.
It preserves IDs, messages, citations and learning state. Documents, canvases
and their version histories transfer ownership in that same commit. A failed transfer
leaves the guest credential usable so the same account can retry. Lecturer
views show guest pseudonyms. [Original rollout and tests](https://github.com/CloudKai/NUS-Codesign-Chatbot/blob/948162e1eba9d0de3fbda7cbfce1d00731001158/docs/GUEST_ACCESS_PHASE_HANDOFF.md)

## Course material publication

Ten course PDFs are tracked in `lecture_notes/` and available in Git history.
Check the owner's permission to distribute them before publishing a clone or
new copy. Local Compose bind-mounts the corpus. Production retrieves official
materials through S3 and the Bedrock Knowledge Base, with `lecture_notes/`
excluded from the image. If the owner chooses removal, distinguish removal
from the current tree from a separately coordinated history rewrite.
[Original content inventory](https://github.com/CloudKai/NUS-Codesign-Chatbot/blob/948162e1eba9d0de3fbda7cbfce1d00731001158/docs/security/PUBLIC_REPOSITORY_CONTENT_AUDIT.md)

The [24 November 2026 repository privacy audit](security/PUBLIC_REPOSITORY_CONTENT_AUDIT.md)
also inventories course-derived evaluation excerpts, tracked browser captures,
historical task outputs, configuration and binary provenance. Its local
acceptance does not authorize redistribution. Keep private data out of new
captures; ignore rules do not remove tracked artifacts or define Docker's
build context. Owner review and separately authorized remediation remain
publication gates.

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

**Why the allowlist is not added yet.** The backend does send two phases in
production: `fast_chat` for every normal turn, and `phase=review` with
`review_mode=incremental` for the background stage checkpoint
(`assess_stage_checkpoint`). A runtime allowlist limited to `fast_chat` and
deep review would break that job. Nothing in `backend/` calls the router, Q&A
or Coaching helpers, and
`tests/domain/test_security_invariants.py::test_production_backend_sends_only_fast_chat_and_review_phases`
fails if that changes. Adding the allowlist later needs `review/incremental`
to stay permitted, or the checkpoint to move to its own runtime.

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

The composer rewrites any of its own section tag names (for example
`</retrieved_course_context>` or `<runtime_instructions>`) inside untrusted
bodies to `&lt;...`, so student text, uploads, excerpts, memory and history
cannot close a section or open a look-alike one. Two student-writable values
used to reach the trusted runtime rules and no longer do: attachment filenames
are reduced to one inert token (letters, digits, `.`, `-`, `_`), and the
response-language setting must be one of English, 中文, Bahasa Melayu or தமிழ்
(anything else becomes English, and the settings routes return 422).

Runtime guardrail intervention (`guardrail_intervened` or `action=BLOCKED`)
fails closed as category `safety_blocked`. Refusal text, prompt text, and AWS
trace bodies are never returned to the student UI or persisted.

Mantle/Gemma output is checked by a separate `ApplyGuardrail(OUTPUT)` after
generation. The runtime therefore suppresses its provisional text deltas:
students see actual operation status until the checked final result is ready.
An eventual discard cannot undo prior text exposure. Deterministic runtime
tests cover both passing and blocked output, with no extra model/safety calls.
First-model-text telemetry is internal and differs from first visible reply.
Existing deployments need the updated runtime published and a fresh session
generation; this local fix does not change live runtime versions. Use the
[deployment manifest and publication/blocked-output gates](deploy/DEPLOYMENT_SAFETY_RECORD.md)
before claiming deployed protection or selecting a rollback target.

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

## Rate limits and admission

- Guest admission is one global bucket, so `X-Forwarded-For` and similar
  headers cannot buy extra guest workspaces. A new guest does not receive new
  generation allowance: the monthly ledger is shared across every owner.
- The login-start limiter keys on the first `X-Forwarded-For` hop. Behind
  Caddy that value is Caddy's own view of its peer, which a client cannot set.
  If the app is ever exposed without Caddy, a client can rotate the header to
  defeat only the per-client bucket; the global bucket still caps login starts.
- Coach concurrency (one per notebook, two per user, a global ceiling) is
  process-local. It holds under a 16-thread race. The durable coach lease is
  the cross-process lock if workers are ever added.
- A funded classroom release needs an evidenced `GENERATION_ADMISSION_POLICY`.
  Without one, only the process-local limits above bound provider spend.

## Logging and secrets

Do not log secrets, full private source content, or raw AWS exception bodies
to clients. Provider failures map to category-only errors.
