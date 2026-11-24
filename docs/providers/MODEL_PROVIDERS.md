# Model providers

Production uses AgentCore Runtime with Haiku 4.5 for Fast Chat and Sonnet
4.6 for explicit Deep Review. Direct Bedrock Converse is an opt-in fallback
selected through deployment configuration. Production selects one of AgentCore,
direct Bedrock, or OpenAI. Local development and CI default to deterministic
mock generation.

FastAPI owns identity, source authorization, idempotency, transcript
persistence, and stage transitions for both providers. The backend validates
structured assessments and resolves application citations over authorized
`[S#]` sources. A coaching recommendation still requires an explicit
student decision. Course evidence comes from server-side Knowledge Base
`Retrieve`, with metadata filters and exact canonical object-key checks.
See [retrieval and citations](../RAG_ARCHITECTURE.md) and the
[AWS deployment runbook](../deploy/AWS_STATELESS_EC2.md).

## AgentCore Runtime

### AgentCore contract

The [AgentCore adapter](../../backend/agentcore_provider.py) sends one
`InvokeAgentRuntime` request for a normal Fast Chat turn. Optional retrieval
is gated without an LLM. Haiku chooses coaching or Q&A and writes the reply
in the same structured `fast_chat_turn` output. The runtime still supports
the legacy router, Q&A, coaching and incremental-review payloads for
compatibility.

FastAPI starts Sonnet Deep Review through
`POST /api/v1/threads/{thread_id}/deep-review` using `phase=review` and
`review_mode=deep`. Eligibility is bounded by `DEEP_REVIEW_INTERVAL_TURNS`.
Opening saved Journey, Review or Summary makes zero model calls. Browser
coach requests cannot select the review specialist.

```json
{
  "phase": "fast_chat",
  "topic": "problem_identification",
  "output_contract": "fast_chat_turn",
  "student_id": "cognito:<sub>",
  "runtime_context": {
    "current_stage": "problem_identification",
    "response_detail": "guide",
    "language": "English",
    "allowed_citations": ["S1"],
    "allow_model_knowledge": false,
    "specialist": "fast_chat"
  },
  "trusted_instructions": "<application runtime rules only>",
  "messages": [
    {"role": "user", "content": [{"text": "<recent DSQL turn>"}]},
    {"role": "assistant", "content": [{"text": "<recent coach reply>"}]},
    {"role": "user", "content": [{"text": "<untrusted current-turn content>"}]}
  ]
}
```

The runtime owns [canonical specialist prompts](../../agentcore_runtime/prompts/).
FastAPI sends runtime rules in `trusted_instructions` and structured
`runtime_context`. The last user content is untrusted. The owner identifier
goes in `student_id`. Fast Chat sends derived conversation memory and at
most 6 recent messages, 3,000 estimated recent-history tokens and 1,500 per
historical message. The total input estimate, including the runtime system
prompt, has a 12,000-token soft target and 16,000-token hard ceiling.
Deep Review uses a separate full-history policy.

FastAPI uses the persisted phase and maps `deep_analysis` to the runtime
topic `ethics_critical`. The visible stage remains **Ethics & Critical
Thinking**. Q&A leaves stage state unchanged. The runtime uses no Knowledge
Base or MCP tools. Images use Converse-style content blocks. The adapter
requires a valid structured result and maps malformed output or provider
failures to category-only errors. A guardrail intervention maps to
`safety_blocked` before any refusal text is parsed.

DSQL or SQLite remains authoritative for the complete transcript. AgentCore
invokes default to a fresh `stateless-…` session. Optional affinity reuses
an opaque owner/notebook/role compute ID without changing the history inputs
or persistence contract.

### AgentCore settings

Set on FastAPI:

```env
MODEL_PROVIDER=agentcore
MOCK_OPENAI=false
AWS_REGION=us-west-2
AGENTCORE_RUNTIME_ARN=arn:aws:bedrock-agentcore:us-west-2:<account>:runtime/<id>
AGENTCORE_QUALIFIER=DEFAULT
AGENTCORE_TIMEOUT_SECONDS=110
AGENTCORE_MAX_RETRIES=0
DEEP_REVIEW_AGENTCORE_TIMEOUT_SECONDS=200
DEEP_REVIEW_JOB_TIMEOUT_SECONDS=240
DEEP_REVIEW_INTERVAL_TURNS=3
AGENTCORE_MODEL_PROVIDER=bedrock
AGENTCORE_MODEL_ID=global.anthropic.claude-haiku-4-5-20251001-v1:0
```

Production sets affinity with `AGENTCORE_SESSION_AFFINITY_ENABLED=true` and
uses `AGENTCORE_SESSION_GENERATION` to invalidate warm compute after publishing.
The job timeout bounds Deep Review result acceptance and stale recovery. A
running worker can still finish after that deadline.

Set these shared model and guardrail values on both FastAPI and the published
runtime:

```env
AGENTCORE_MODEL_REGION=us-west-2
COACHING_MODEL_PROVIDER=bedrock
COACHING_MODEL_ID=global.anthropic.claude-haiku-4-5-20251001-v1:0
REVIEW_DEEP_MODEL_PROVIDER=bedrock
REVIEW_DEEP_MODEL_ID=global.anthropic.claude-sonnet-4-6
GUARDRAIL_ID=<configured guardrail>
GUARDRAIL_VERSION=4
```

Set the following only on the published runtime:

```env
DEEP_REVIEW_BEDROCK_READ_TIMEOUT_SECONDS=180
```

The runtime-only Deep Review Bedrock timeout accepts 30–600 seconds. Legacy
`ROUTER_MODEL_*`, `QA_MODEL_*` and `REVIEW_INCREMENTAL_MODEL_*` selectors are
optional when unused. FastAPI production validation requires
`AGENTCORE_MODEL_PROVIDER` and `AGENTCORE_MODEL_ID`. The runtime uses them as
a fallback when role keys are absent. Missing model and guardrail configuration
fails closed. Haiku and Sonnet have no cross-role fallback.
The [AWS runbook](../deploy/AWS_STATELESS_EC2.md#publish-an-agentcore-runtime-version)
covers publishing model, prompt, or environment changes on the existing ARN.

### AgentCore IAM

Grant FastAPI's EC2 role `bedrock-agentcore:InvokeAgentRuntime` on the
deployed runtime and its DEFAULT endpoint. The principal can call legacy
phases or request Sonnet directly, so the grant belongs only to the trusted
application role. The runtime execution role needs `bedrock:InvokeModel`
for both configured inference profiles. Historical Luna rollback versions
also need Mantle permissions. See the [AWS role policies](../deploy/AWS_STATELESS_EC2.md#iam-role-permissions-ec2)
and [security boundaries](../SECURITY_BOUNDARIES.md).

### AgentCore streaming

The adapter can decode a structured JSON body or supported runtime event
envelopes. The student stream can emit progress and a validated
`reply_ready` preview before persistence, followed by completion after the
save. The preview contains the assembled reply. Use the saved-turn receipt
and the same idempotency key to reconcile interrupted streams. Discard the
preview if saving fails.

### AgentCore validation

Run the fake-client [adapter tests](../../tests/domain/test_agentcore_provider.py).
The runtime CI compatibility job checks the
[pinned dependencies](../../agentcore_runtime/requirements.txt) and Strands
structured-output API. Botocore allows one total Converse attempt and Strands
owns transient retries. Fast Chat uses up to two event-loop turns and Deep
Review up to three. See the [runtime contract](../../agentcore_runtime/README.md)
for structured-output recovery, retry settings and model provenance.

After explicit cost and request approval, follow the
[AgentCore smoke command](../deploy/AWS_STATELESS_EC2.md#guarded-agentcore-smoke).
A separate [InvokeHarness evaluation](../../scripts/evals/evaluate_live_coach.py)
can override the model with `openai.gpt-5.6-luna` and `apiFormat=responses`
through the [isolated adapter](../../backend/agentcore_harness_provider.py).
It leaves production DEFAULT unchanged and uses Luna for any compression.
Claude fallback is disabled on that path.

<a id="gemma-4-31b-candidate-not-deployed"></a>

## Gemma 4 31B

**2026-11-24 update:** V1 deployment 38 serves the citation-nullability fix
through the pinned `GemmaStable37` production endpoint.
The provider now restores canonical Pydantic nullability after SDK flattening,
so defaulted citation strings cannot be generated as null. Q&A recommendations
remain nullable. A real runtime check completed in one cycle with no recovery;
this is not a guarantee of zero future validation retries. An80-call direct
provider burst passed80/80 (p50 3.442s, p95 32.319s), separately from80/80
application workspace reads. Full application generation capacity is unproven.
`HaikuRollback36` remains READY. See the
[measured results](../examples/classroom-capacity/gemma-results-2026-11-24.json)
and [current release evidence](../IMPLEMENTATION_STATUS.md#agentcore-platform-v1-restored-in-production-2026-11-24-sgt).

The following2026-11-23 record describes the preceding version37 rollout.

**Promoted 2026-11-23:** DEFAULT
version37 now serves `bedrock_mantle_responses` / `google.gemma-4-31b` in Oregon
for Fast Chat and configured lightweight roles. Deep Review remains Sonnet4.6.
Haiku36 remains READY on the separate `HaikuRollback36` endpoint. See the
[release evidence and rollback](../IMPLEMENTATION_STATUS.md#gemma-native-json-fixed-and-deployed-haiku-rollback-retained-2026-11-23-sgt).

The exact Gemma pair is accepted by the runtime and production validators;
Converse rejects that model ID before constructing a client. Pinned Strands1.52
selects `https://bedrock-mantle.us-west-2.api.aws/openai/v1`. The Gemma-only
`gemma_responses.py` adapter uses native strict JSON-schema text in place of
function arguments, which returned punctuation-only replies in earlier tests.
Incremental text becomes the existing framework validation-tool stream. Pydantic
still validates every result; malformed, truncated or punctuation-only replies
fail. SDK schema conversion's missing null recommendation enum case is restored
so Q&A does not have to invent a stage recommendation. No application tools are
enabled; multiple tool specs fail closed.

The factory keeps `stateful=False`, disables SDK HTTP retries and parallel tool
calls, and limits total reasoning plus visible output to2,048 tokens per model
call. Existing Strands retry/repair limits still apply; this is not a per-turn or
monthly spending limit. Mantle input/output `ApplyGuardrail`, notebook-scoped
sources, citations and confirmed stage progression remain enforced. Prompt cache
is disabled for Gemma; no cache savings have been established.

Text and images use the pinned SDK's conversions. PDFs and Office/text files
continue through application extraction/retrieval. A small directly supplied PDF
also passed a synthetic SDK check when its filename ended `.pdf`, but native
layout, scanned-document OCR, Office formats and large multimodal requests have
not been established. AWS documents a **3.5MB total Gemma request-body limit**,
including images; the application's upload limit does not prove a request fits.

Synthetic full-prompt text, image and PDF checks passed, including citations,
streaming and full runtime guardrails. The published runtime check took13.582s
with one recovery (reply streaming around3.349s): the first citation title was
null and failed validation; recovery returned a valid string. This remains a
known efficiency risk. These checks do not establish 80-student concurrency,
consistent one-call latency, broad coaching quality or an S$30 monthly ceiling.

References: [Gemma model card](https://docs.aws.amazon.com/bedrock/latest/userguide/model-card-google-gemma-4-31b.html)
and [pinned adapter API](https://strandsagents.com/docs/api/python/strands.models.openai_responses).

## Direct Bedrock Converse

### Direct Bedrock contract

The [direct adapter](../../backend/bedrock_provider.py) makes one Converse
or ConverseStream invocation for a server-built coaching request. It uses the
structured `coach_turn` tool and validates the provider-neutral result.
Provisional research coding is optional and validated independently.
Persisted stage and authorized source labels take precedence over model
output. Unsupported image inputs fail explicitly. Provider failures return
sanitized categories.

### Direct Bedrock settings

```env
MODEL_PROVIDER=bedrock
AWS_REGION=us-west-2
BEDROCK_MODEL_ID=<model-or-inference-profile-id>
BEDROCK_TIMEOUT_SECONDS=110
BEDROCK_MAX_RETRIES=0
```

Confirm the model and region support the required tool/schema and image
inputs. Application citations use selected-source labels. Native citation
features can conflict with structured output. Account for first-use schema
compilation where applicable.

### Direct Bedrock IAM

Use the standard AWS credential chain, such as the EC2 role or local AWS
SSO. Grant `bedrock:InvokeModel` and, for streaming,
`bedrock:InvokeModelWithResponseStream` on the exact model or inference
profile and required destination resources. Verify model access and any
guardrail grants. See the [AWS IAM setup](../deploy/AWS_STATELESS_EC2.md#iam-role-permissions-ec2).

### Direct Bedrock streaming

`ConverseStream` assembles the tool payload and validates it against the
same contract as the sync path. Truncated or malformed streams fail before
persistence. An interrupted client can recover a committed turn with the
original idempotency key.

### Direct Bedrock validation

Use the fake-client [Bedrock tests](../../tests/domain/test_bedrock_provider.py)
to exercise structured replies, uncoded research fallbacks, stage and citation
scope, images, provider errors and sync/stream equivalence. Use the
[application testing guide](../TESTING.md) for persistence, retry, restart
and phase parity checks.

A live check requires an explicitly approved model, request/token ceiling
and cost cap. Record region, model, latency, request ID and result shape
without credentials, prompts or student content. Follow the
[deployment and smoke runbook](../deploy/AWS_STATELESS_EC2.md#live-smoke-test-required-before-cutover).

AWS references include [Converse and ConverseStream](https://docs.aws.amazon.com/bedrock/latest/userguide/conversation-inference.html),
[structured outputs](https://docs.aws.amazon.com/bedrock/latest/userguide/structured-output.html),
[tool use](https://docs.aws.amazon.com/bedrock/latest/userguide/tool-use.html)
and [inference permissions](https://docs.aws.amazon.com/bedrock/latest/userguide/inference-prereq.html).

### Oregon candidate checks (2026-11-23)

Small approved synthetic calls confirmed Gemma 4 31B text, image, extracted-PDF
text and direct-PDF access through Mantle Responses. Initial HTTP400 requests
used a raw Pydantic schema, not the actual Strands-converted schema. Correcting
the temporary harness to use the pinned SDK conversion removed the HTTP400,
but two accepted calls (including the full production coaching prompt) returned
only `":"` as `response_text`. Pydantic accepted this nonempty string, but it
is not a useful reply. The Gemma native JSON transport described above replaced
that path and passed the later production gate without loosening validation.

`mistral.ministral-3-8b-instruct` rejected Mantle `/v1/responses` but succeeded
through Bedrock Converse, including one Pydantic-valid FastChat tool result,
image input and the app's extracted-PDF text. Native Converse document input was
explicitly unsupported. Preserve application extraction/retrieval for PDFs and
Office files; these checks do not establish native document support or every
file type's answer quality. The later native-JSON Gemma release is now serving with Haiku rollback retained.
Classroom capacity and broader quality remain unmeasured.
See [implementation evidence](../IMPLEMENTATION_STATUS.md#live-gemmaministral-modality-checks-haiku-remains-live-2026-11-23-sgt).
