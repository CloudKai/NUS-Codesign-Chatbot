# Amazon Bedrock coach adapter handoff

**Implemented** in `backend/bedrock_provider.py` and selected with
`MODEL_PROVIDER=bedrock`. Automated tests inject a fake Converse client in
`tests/domain/test_bedrock_provider.py` and never call AWS. Live smoke still
requires an explicit cost cap.

## Goal

Implement an Amazon Bedrock generation adapter behind the existing coach
provider contract. Bedrock performs the same single structured turn as the
current provider: student-facing coaching, educational assessment, transition
recommendation, Facione scores, and optional provisional research coding.

Do not move phase progression, notebook ownership, source filtering,
idempotency, persistence, or lecturer access into Bedrock. The application
remains authoritative.

## Contract

The adapter accepts the server-built `CoachRequest` and composed prompt, then
returns the provider-neutral structured result defined by the domain layer.

Required invariants:

- exactly one model invocation per coaching turn;
- the request's persisted phase overrides a model-supplied phase;
- structured coaching output is mandatory;
- research coding is optional and soft-validated independently;
- citations are restricted to the selected notebook's supplied `[S#]` labels;
- provider exceptions map to `ProviderUnavailableError` without exposing AWS
  request bodies, credentials, prompts, or student content;
- no database, S3, Cognito, Streamlit, or transition mutation in the adapter;
- sync and stream paths return the same final validated contract.

The existing mock provider remains the deterministic CI implementation.

## Recommended implementation

Use the AWS SDK `bedrock-runtime` client and the Bedrock Converse API. Build the
client through dependency injection so tests provide a fake client and never
contact AWS.

Configuration should be explicit and non-secret:

```env
MODEL_PROVIDER=bedrock
AWS_REGION=us-west-2
BEDROCK_MODEL_ID=<model-or-inference-profile-id>
BEDROCK_TIMEOUT_SECONDS=110
BEDROCK_MAX_RETRIES=0
```

Credentials come from the EC2 role, AWS SSO profile, or standard AWS credential
chain. Never add access keys to `.env` or Git.

Prefer Bedrock structured outputs through Converse `outputConfig.textFormat`
with a strict JSON schema when the selected model supports it. If the chosen
model supports strict tool use but not structured text output, define one
strict tool whose input schema is the provider-neutral result and accept only
that tool invocation. Do not parse prose, Markdown fences, or hidden comments
as a fallback.

Keep schema construction provider-neutral. A Bedrock-specific translator may
adapt the Pydantic schema, but provider-specific response objects must not leak
past the adapter.

Images, when supported by the selected model, are mapped from the existing
`CoachImageInput` values. Reject unsupported media explicitly rather than
silently dropping it.

## Streaming

`ConverseStream` may emit status/token events for the student interface, but
the final assembled payload must pass the same structured validation as a
non-streaming result before persistence. A disconnected client must not cause a
second model call when the existing idempotency key can recover the committed
turn.

## IAM and production controls

Grant the application role only the required inference actions for the exact
model or inference-profile resources, normally:

- `bedrock:InvokeModel`
- `bedrock:InvokeModelWithResponseStream` when streaming is enabled

Model access, marketplace subscription, guardrail permissions, and cross-region
inference-profile permissions depend on the selected model and account. Confirm
them before deployment. Do not grant Bedrock administrative permissions to the
runtime role.

Set boto retry and read/connect timeouts deliberately. The application already
owns request idempotency; provider SDK retries must not create an unbounded
latency or duplicate application persistence.

## Compatibility notes

- Confirm that the selected model supports the requested structured-output or
  strict-tool feature. Support varies by model and region.
- Bedrock may compile a new structured-output schema on first use, increasing
  the first request's latency. Reuse a stable schema name and warm it in a
  separately approved smoke test.
- Some Anthropic structured-output configurations cannot be combined with
  citations. Application `[S#]` citations come from the selected-source prompt
  contract; verify the chosen model/API combination rather than assuming native
  provider citations are available.
- Knowledge Base retrieval is a separate `ContextRetriever` in
  `backend/bedrock_retrieve.py`. It uses `Retrieve` with an optional
  `course_material_id` metadata filter plus post-retrieval exact canonical
  object-key equality (no suffix matching). See
  [`docs/RAG_ARCHITECTURE.md`](../RAG_ARCHITECTURE.md). Do not
  use `RetrieveAndGenerate`, because it would bypass the application's prompt,
  ownership, phase, and citation boundaries.

Official references:

- [Structured outputs](https://docs.aws.amazon.com/bedrock/latest/userguide/structured-output.html)
- [Converse and ConverseStream](https://docs.aws.amazon.com/bedrock/latest/userguide/conversation-inference.html)
- [Tool use](https://docs.aws.amazon.com/bedrock/latest/userguide/tool-use.html)
- [Inference permissions](https://docs.aws.amazon.com/bedrock/latest/userguide/inference-prereq.html)

## Required tests

All automated tests inject a fake client and use no AWS or paid model call.

Cover:

1. Valid structured coaching plus valid research coding.
2. Valid coaching with absent or invalid research coding retained as uncoded.
3. Invalid coaching rejected without persistence.
4. Persisted phase overriding a mismatched model phase.
5. Unknown citations removed by the application boundary.
6. Image mapping and unsupported-image failure.
7. Throttling, timeout, access denied, model unavailable, malformed event, and
   truncated stream error translation.
8. Sync/stream final-result equivalence.
9. Idempotent retry and restart recovery without duplicate messages or research
   observations.
10. Guide/Free and five-phase prompt parity with the mock provider.

After deterministic tests pass, an explicitly approved live smoke may make one
short request with a stated model, token/request ceiling, and cost cap. Record
the AWS account alias/ID, region, model ID, latency, request ID, and result
shape, but never record credentials, full prompts, or student content.
