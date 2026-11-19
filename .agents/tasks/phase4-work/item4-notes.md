# Phase 4 item 4 notes: stream the reply text

No live command was run (no AWS, Bedrock, AgentCore, KB, OpenAI or paid call). Web reads: AWS AgentCore documentation pages and Strands documentation search results only.

Marks: **(script run)**, **(hand)** read or counted by hand, **(doc)** from AWS or Strands documentation, **(not run)** could not be run here.

Commits (author and committer `CloudKai <kaiming_01@live.com>` on each, script-checked with `git log -1 --format`): `d49767e` (measurement script and the "before" run), `b8893ec` (implementation, tests, frontend, AGENTS rows), plus the docs/notes commit that follows it (see `git log`). Push result is in the final message. No `gate-item4.json` existed, so this was the implementation pass.

## 1. AgentCore streaming support: can partial reply text pass through the current path?

**Answer: no, not through the current path. That part is stopped, no workaround built.**

Evidence in code (hand, file and line at HEAD b8893ec):

| Hop | Evidence |
|---|---|
| Runtime entrypoint | `agentcore_runtime/main.py` 818-828: `invoke` returns `await fast_chat_invoke(payload)` (a dict). Its docstring says "Route companion structured specialists to JSON return; never ``yield``." The module docstring (lines 1-14) describes structured specialists returning JSON. |
| Legacy streaming stub | `agentcore_runtime/main.py` 805-815: `_stream_specialist_invoke` ignores its arguments and returns `harness_error_payload("unavailable")`. There is no streaming implementation to enable. |
| Structured flow | `_structured_role_invoke` (`main.py` 499-724) calls `agent.invoke_async(user_prompt, structured_output_model=..., structured_output_prompt=..., limits=...)` and returns `structured_wire_payload(output)` after `parse(result)` and `enforce_mantle_guardrail(output_text(output), ..., source="OUTPUT")`. Fast Chat cycle 1 forces one tool via `tool_choice={"any": {}}` (`_install_first_cycle_structured_output`, 381-445). The reply is a field of that tool's JSON input. |
| Partial text is visible inside the runtime | `_first_text_timing_callback` (`main.py` 169-206) is the Strands `callback_handler` for Fast Chat. It reads `delta.toolUse.input` fragments and detects the start of `"response_text":"` with a regex. It records `model_first_reply_text_ms` for telemetry only and discards the text. So the model does stream the reply as tool-input JSON; nothing forwards it. |
| Backend invoke | `backend/agentcore_provider.py` 1886-1892: `invoke_agent_runtime(..., contentType="application/json", accept="application/json")`, then `_payload_from_runtime_response` (line 547) reads the whole body (`_read_response_bytes`), and for SSE content assembles the full text with `_text_from_stream_events` before parsing one JSON object. It never yields partial text to a caller. |
| Output guardrail | The output guardrail runs once on the complete output text after generation (`main.py` line 632, `enforce_mantle_guardrail(..., source="OUTPUT")`). Any fragment shown earlier would be unguarded text. |

Documentation (doc):

- AWS API reference for `InvokeAgentRuntime`: the operation supports streaming responses and returns partial responses as they become available. https://docs.aws.amazon.com/bedrock-agentcore/latest/APIReference/API_InvokeAgentRuntime.html
- AWS "Stream agent responses": an AgentCore Runtime entrypoint can be an async generator that yields events from Strands `agent.stream_async(...)`. https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/response-streaming.html
- Strands streaming concepts: the same events are available through async iterators or callback handlers. https://strandsagents.com/latest/documentation/docs/user-guide/concepts/streaming/
- Strands structured output returns a validated object (schema-checked). https://strandsagents.com/latest/documentation/docs/user-guide/concepts/agents/structured-output/

Conclusion: the platform can stream, but this repo's runtime returns one JSON object and the provider reads one JSON object, with structured output in a forced tool call whose JSON is only complete at the end. Streaming reply text from AgentCore would need all of: (a) a new runtime entrypoint that yields (new published runtime version; the brief and runtime docstring say not to change the ARN or create a second runtime); (b) a wire contract for partial text beside the final structured object; (c) an incremental `response_text` extractor on the runtime side (the one in `backend/coaching/reply_text.py` could be reused, it has no dependencies); (d) a decision about the output guardrail, which today sees only complete text; (e) provider-side iteration over the response body instead of reading it whole. That changes the runtime contract, so it is left for a user decision. I did not read the live runtime or its published version (not run).

What remains blocked: reply streaming on `MODEL_PROVIDER=agentcore`, the production path. With that provider the new setting changes nothing; the stream is exactly as before.

## 2. What was built (mock and direct Bedrock providers)

- Events: `reply_delta` and `reply_discard`, in `backend/coaching/stream_events.py` (validated by the same `COACH_EVENT_ADAPTER`).
- Request-scoped sink: `backend/coaching/progress.py` (`emit_coach_reply_delta`, `emit_coach_reply_discard`, `reply_delta_sink_bound`, a third context variable next to progress and reply).
- `coach_events(..., reply_deltas=False)` in `backend/coaching/streaming.py` turns sink calls into events and, when a turn ends in an exception after text was previewed, puts `reply_discard` before the error.
- `CoachApplicationService.submit(..., reply_delta=...)`; `_maybe_rag_fallback` calls `emit_coach_reply_discard()` just before the second model pass.
- `backend/http/app.py`: deltas only when `settings.coach_stream_reply_deltas_enabled` AND header `X-Coach-Reply-Deltas: 1`. Streamlit's `coach_events` call is unchanged (no deltas).
- Providers: `DeterministicCoachProvider.assess` emits the finished reply in 4-word pieces when a sink is bound (simulation, labelled in the docstring). `BedrockCoachProvider._assess_metered` uses `converse_stream` when a sink is bound, feeds tool-input fragments to `ReplyTextExtractor` (`backend/coaching/reply_text.py`), then parses the full tool input and validates exactly as before; usage tokens come from the stream `metadata` event so metering still works. Stub-tested only.
- Frontend: `frontend/src/stream.ts` decodes both events and exports `REPLY_DELTAS_HEADER`; `Conversation.tsx` sends the header on the stream request only (not the edit/revise call), appends deltas to the existing unsaved preview state, clears it on `reply_discard`, replaces it on `reply_ready`, and keeps the existing terminal-error flow ("The answer was not confirmed saved. Your question is kept..."). The preview state never feeds saved messages; after the stream ends the preview is cleared and only the GET reconcile result is shown as saved.
- New setting `COACH_STREAM_REPLY_DELTAS_ENABLED`, default off, in `backend/settings.py`, `.env.example`, `docs/IMPLEMENTATION_STATUS.md`.

## 3. Event shape decision and old-client compatibility

Choice (open point): two new event names rather than changing `reply_ready`.

- `{"event":"reply_delta","text":"<fragment>"}`: append-only fragment; non-empty text. No sequence number: NDJSON over one ordered HTTP response preserves order, and the client replaces everything at `reply_ready`.
- `{"event":"reply_discard"}`: withdraw all fragments (failure, or the retry after a source check, where the first-pass text is replaced).
- `reply_ready` keeps its meaning (the final validated reply) and replaces the preview, so any difference between streamed text and final text (server-side post-processing, retries) self-corrects.
- Why separate names: the old frontend `decode()` throws `Malformed coach event` on an unknown event, which ends the stream and sends the client into GET reconciliation. So unknown events must never reach a client that did not ask. Hence double gating: a server setting (default off) and a per-request header `X-Coach-Reply-Deltas: 1` the new frontend sends. An old cached tab, Streamlit, or any other consumer sends no header and gets today's event set (test `test_without_opt_in_the_original_event_set_is_unchanged`, and the failure case sends no `reply_discard` to them either).
- Alternative not chosen: reuse `reply_ready` with a `partial` flag. Old clients would show half text as a final preview.

## 4. Time to first visible text, mock provider, offline (script run)

Script: `scripts/evals/measure_stream_first_text.py` (committed in `d49767e`, before any streaming code). It builds a temp SQLite store and `CoachApplicationService`, runs `coach_events` 15 times per mode and takes marks in ms from dispatch. "First visible text" is the first `reply_delta` when the stream has one, otherwise `reply_ready`. The same script ran on both versions. Results: `.agents/tasks/phase4-work/item4-first-text-before.json` (git_sha 825cd2f, no streaming code) and `item4-first-text-after.json` (git_sha b8893ec).

| Mode | Marks | Before (825cd2f) median ms | After (b8893ec) median ms |
|---|---|---|---|
| plain mock (no added delay) | first visible text | 15.1 (`reply_ready`) | 14.5 (`reply_delta`) |
| plain mock | `reply_ready` / `done` | 15.1 / 16.8 | 14.5 / 16.2 |
| simulated mock (150 ms first token + 20 ms per 4-word chunk) | first visible text | 286.7 (`reply_ready`) | 183.9 (`reply_delta`) |
| simulated mock | `reply_ready` / `done` | 286.7 / 288.5 | 286.7 / 288.7 |

Ranges (min-max, script run): simulated first visible text 285.9-287.6 before, 183.4-184.6 after. The plain-mock maximum (about 460-475 ms in both runs) is the first of the 15 runs warming up; medians are shown.

What it proves: the new pipeline hands the first fragment to the stream consumer right after the provider emits it (about 14 ms of pipeline overhead over the 170 ms I set for first token plus one chunk), the final events are not delayed (`done` 288.5 before, 288.7 after), and the old path shows nothing until the whole reply exists.

What it does not prove: anything about real latency. The 150 ms and 20 ms are numbers I chose; the mock builds the whole reply instantly, and plain mock shows 15 ms in both cases because there is nothing to wait for. Real time to first text depends on the model's first token, prompt size, AgentCore cold start and network, none of which ran. For AgentCore it is zero improvement today because that path cannot stream (section 1). The runtime already records `model_first_reply_text_ms` in live telemetry, which is the right number for real first-text timing at the model.

## 5. Frontend build (script run)

- `npm ci` in `frontend/`: exit 0, "added 152 packages", 0 vulnerabilities, about 2 s.
- `npm run build` (`tsc --noEmit && vite build --base=/pilot/`): exit 0. Type check passed (no tsc errors); vite built 205 modules, `dist/assets/index-BT9g9LJx.js` 289.96 kB (gzip 88.98 kB). Node v22.23.4, npm 11.4.2.
- No frontend unit-test framework exists in the repo (package.json has only `build`), so the frontend check is type check plus build. The stream decoder logic is not unit tested in JS; the server events it decodes are covered by the Python tests (not run in a browser).
- `frontend/dist` and `frontend/node_modules`: git-ignored by `frontend/.gitignore` lines 1-2 (`git check-ignore -v`), 0 tracked files (`git ls-files frontend/dist frontend/node_modules | wc -l` is 0). Both were removed after the checks (`rm -rf`), `git status` shows only intended source changes.
- Effect of dist on the two baseline failures: with `frontend/dist` built, the full suite had 0 failures (below). After deleting dist, `tests/http/test_notebook_reader.py` again gave `2 failed, 3 passed` (`test_pilot_serves_only_built_public_assets` and `test_default_workspace_and_streamlit_gate`, `GET /` 404). Dist was not committed.

## 6. Tests and ruff (script run)

- Full mock suite with dist built, at the implementation tree (before the docs-only commit): `2703 passed, 1 skipped, 295 warnings in 142.21s`, 0 failed. The one skip is `tests/domain/test_strands_first_cycle_middleware.py` (`strands` not installed), as in baseline. Total 2704 (the item-0 baseline was 2596 at 3060a17; items 1-3 and this item added the rest; I did not count those splits separately).
- Without dist: the same two baseline failures, nothing new (only the notebook_reader file was re-run without dist; the other tests do not depend on dist).
- New tests: 21 (script-collected: `test_reply_streaming.py` 18, `test_bedrock_provider.py` 30 collected of which 3 are new).
- `ruff check .`: `All checks passed!`.

## 7. Stuck policy

No piece hit two failed attempts. The AgentCore piece was stopped on evidence, not on failed attempts.

## 8. Risks and decisions left for the user

- AgentCore streaming (production) is blocked on a runtime contract change (section 1 a-e). Decide whether to pursue it; the Item 5 benchmark may show whether first-text matters enough.
- A preview can show text the final validation rejects; it is opt-in, labelled "not saved yet", withdrawn on failure.
- The direct Bedrock streaming path is stub-tested only. Real `converse_stream` event shapes, guardrail behaviour mid-stream and usage reporting were not observed.
- Pre-existing line `docs/learning/REFERENCE.md` L21 still says "progress events, then the final turn"; I did not renumber that generated reference table.
- The `reply_discard` on failure is only sent to clients that opted in; old clients clear on `error` as before.
