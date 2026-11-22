# Normal and edited reply streaming

Normal sends and streamed message revisions now deliver actual provider reply
fragments to the React chat while generation runs. Private assessment fields,
reasoning and raw structured JSON never become browser deltas. No second model
call is added to simulate typing. The deterministic provider remains a mock.

## Contracts and compatibility

- `COACH_STREAM_REPLY_DELTAS_ENABLED` defaults **true**. The browser opts in with
  `X-Coach-Reply-Deltas: 1`; clients without it retain the previous event set.
- Lecture/project sends and `/messages/{id}/revise/stream` use FastAPI NDJSON
  `StreamingResponse`. The canonical and reader JSON `/revise` endpoints remain.
  Caddy explicitly permits the reader stream route and uses immediate flushing.
- A partial `reply_delta` is provisional. A failed/replaced attempt emits
  `reply_discard`. Only a validated `reply_ready` can precede persistence; only
  `done` or exact-key read reconciliation acknowledges the saved turn. Neither
  partial text nor incomplete structured output is saved.
- Revised messages reuse append-only revision, attachments/intent, saved detail
  and language, execution lease, stable request identity and recovery. A replay
  returns the existing result without generating or bumping the revision again.
- Direct Bedrock uses ConverseStream. Optional OpenAI uses Responses text-delta
  events. Both decode only top-level `response_text` from their structured JSON.
- AgentCore Fast Chat adds `stream_reply: true` to the server-built runtime
  payload. The updated runtime returns SSE model tool-input frames
  `{event: model_delta, tool_id, input}` and then `{event: result, payload}`.
  FastAPI decodes UTF-8 incrementally with a 2MB transport bound, extracts only
  response_text, closes the body on success/failure, and validates the final
  payload with the existing schema. Changed tool ids and the existing outer
  structured retry withdraw previous text. SDK read failures retain their error
  category. Older JSON runtimes still have their final response accepted.
- The runtime still performs one structured `invoke_async`, with its existing
  tool choice, repair limits, guardrails, provenance and usage. Each stream owns
  a queue/task. Deep Review and legacy non-fast-chat contracts are unchanged.
- Reduced motion disables animation, not reply visibility. The composer Stop control requests cancellation by the exact owner, chat and
  request key. A disconnected viewer still reconciles through reads and never
  automatically replays a write. Separate
  composer drafts survive streamed edits.

The pinned SDK's returned-generator behavior and SSE encoding were checked
against [bedrock-agentcore 1.21.0](https://github.com/aws/bedrock-agentcore-sdk-python/blob/v1.21.0/src/bedrock_agentcore/runtime/app.py).

## Mock verification and reproduction

Use the process-local tests namespace binding from [the testing guide](../TESTING.md)
if this machine's installed `tests` package shadows the repository. Focused files:

```sh
.venv/bin/python -m pytest -q tests/domain/test_reply_streaming.py tests/domain/test_agentcore_provider.py tests/domain/test_runtime_reply_stream.py tests/domain/test_bedrock_provider.py tests/domain/test_prompt_architecture.py tests/http/test_reader_conversation.py
npm run build --prefix frontend
```

The provider/runtime tests pause the SDK output and assert a fragment reaches the
consumer before the final object is available. Malformed/truncated/invalid UTF-8
streams fail closed and close the body; Unicode split across bytes survives.
Tests also cover replacement/retry discard, legacy JSON, owner boundaries,
revision replay, grounding/citations, graph persistence and existing-data behavior.
Validation: 236 focused and 3,180 full mock tests passed (one optional-SDK
module skipped in the application environment). A separate exact-pin SDK
environment passed 16 tests including the real Strands callback/runtime-entrypoint
case; network-free dependency diagnostics passed. Remaining warnings are existing
SDK/dependency notices. Browser regressions and saved-state restart comparison
also passed. Full evidence is recorded in implementation status.

For browser QA, use a fresh directory under `/private/tmp` (or OS temp). Set
`APP_DATA_DIR`, `APP_DATABASE_PATH`, `APP_FILES_DIR`, `APP_WORKSPACES_DIR` and
`LECTURE_NOTES_DIR` explicitly under it; force `MODEL_PROVIDER=mock`,
`COACHING_MODEL_PROVIDER=mock`, `REVIEW_DEEP_MODEL_PROVIDER=mock`,
`AGENTCORE_MODEL_PROVIDER=mock`, `MOCK_OPENAI=true`, empty `OPENAI_API_KEY`,
`DATABASE_PROVIDER=sqlite`, `FILE_STORAGE_PROVIDER=local`, `GUEST_ACCESS_ENABLED=true`,
`AUTO_ADVANCE_STAGES=false`, and `COACH_REQUESTS_PER_MINUTE=120`.
Set public/UI URLs to `http://127.0.0.1:8096`. Then start the guarded relay:

```sh
PYTHONPATH="$PWD:$PWD/tests/browser" .venv/bin/python -m uvicorn reply_streaming_fixture:app --host 127.0.0.1 --port 8096
```

The fixture refuses non-temporary paths and non-mock mode. It only slows delivery
of real mock-server NDJSON events, so the browser can observe intermediate text;
it does not prove live model latency or move persistence ahead of validation.
Run `real_reply_streaming.js`, then `reply_streaming_qa.js` through the approved
Playwright CLI. Check 1440/390 Light/Dark, app/OS reduced motion, provisional
labels/no saved actions, no automatic replay, retained draft and the console.
Screenshots are ignored under `output/playwright/reply-streaming/`.

## Explicit cancellation

`POST /api/v1/reader/threads/{thread_id}/coach-turn/stop` operates in the
current single-worker FastAPI process. It requests cancellation only for the
matching authorized stream. Once reply persistence starts, the turn can finish
and save normally. Ordinary disconnects do not request cancellation. Provider
adapters close the active response stream when available and discard unfinished
text. A pending SDK call may take time to return, and provider-side work already
started may still be billed. An append-only edit recorded before generation
remains in the transcript and can resume using the same retry key.

## Rollout and rollback

No schema migration, data rewrite, staging, commit, deployment or paid LLM call
is included. The local preview remains mock-only. To use live AgentCore fragments,
publish the compatible application and this runtime to the **existing** runtime
ARN/qualifier, in that order. Follow the runtime's existing deployment guide;
production cloud changes need explicit authorization. Direct Bedrock callers
need `bedrock:InvokeModelWithResponseStream` permission; no IAM change is included. Until publication, the
old runtime can only provide a final reply.

For an immediate backend rollback, set `COACH_STREAM_REPLY_DELTAS_ENABLED=false`
and restart. Existing JSON routes remain available. Roll back the runtime to its
previous READY qualifier as documented in its guide. Do not undo unrelated user
work or restore a database for this presentation/transport change. A live smoke
check needs separately approved request/token/cost limits; none has been run.
