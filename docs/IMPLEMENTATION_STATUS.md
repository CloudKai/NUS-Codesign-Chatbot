# Implementation status

## Current status

### Refactor items 1 and 2: one owner for first-pass scope, uncoupled eval commands (branch `improvement/backend`)

No behaviour change in production or in any eval number, and no live command
(AWS, Bedrock, AgentCore, Knowledge Base, OpenAI or any paid call). Mock tests
only. No settings default changed. Report:
`.agents/tasks/refactor-evidence-scope-2026-11-20.md` (git-ignored, committed
with `git add -f`).

| Step | What changed | Commits |
|---|---|---|
| Step 0 baseline | Per-message gate decisions and every offline eval output recorded under `.agents/tasks/refactor-baseline/` | `9d43fe6` |
| Item 1 | `backend/coaching/evidence_scope.py` owns the first-pass scope and mode rules; `execution.py` and the eval `gate_decision` both call it | `3e18abe`, `6c91e5c`, `26e6fed`, `dda9e34`, `94e8eed`, `c56233f` (pushed) |
| Item 2 | Shared eval code moved to `scripts/evals/lib/`; no eval command imports another; boundary test added | `21ebbf3` to `4a55e3c` (12 commits) |

- **Item 1 evidence.** Per-message decisions for all 295 gate messages and the 12
  follow-up cases: `gate-decisions-after.json` is byte-identical to
  `gate-decisions-before.json` (empty `diff`, same sha256 `7fa20f73...d9ff`). A
  5,652-row cross product of the old and new `gate_decision` is identical.
  Wrong-skip 76/154, false-retrieve 7/141 and recall@4 91/94 are unchanged to the
  digit. No existing test or setting default was edited.
- **Item 2 evidence.** `run_offline_evals.sh` re-run into
  `.agents/tasks/refactor-baseline/after/`: 41 comparisons, 0 differing after
  masking the recorded SHA, dirty flag, timestamps and (for the stub benchmark
  and `measure_stream_first_text`) timing floats. All 19 exit codes are the same
  (0, and 2 for the two refusal paths). `--help` output of nine commands is
  unchanged. Commands that need `laya`, `vegaml`, `setfit` or a checkpoint cannot
  run in the sandbox; their report-building code is compared through
  `stub_snapshots` (no difference) and the `tests/scripts` tests.
- **Validation (script run, mock env).** `ruff check .` passes before and after.
  Full suite: baseline `4fb7c92` 2753 passed, 2 failed, 1 skipped; after item 1
  2876 passed, 2 failed, 1 skipped; at `4a55e3c` (before the docs commit) 2905
  passed, 2 failed, 1 skipped. The +152 are new tests (item 1: 79 + 38 + 6;
  item 2: 29). The 2 failures are the known `tests/http/test_notebook_reader.py`
  pair (no `frontend/dist`); the skip is the missing `strands` package.
- **Risks.** `tests/domain/test_mode_classification.py::test_reflection_completion_request_skips_retrieval_and_completes_in_place`
  failed in one of two completed full runs at `4a55e3c` (and once in item 2). It asserts
  `len(client.calls) == 1` right after `submit`, and the second call it saw was the
  background stage-checkpoint review. It passes alone (8 of 8) and in the other
  runs; it was not run on `4fb7c92`, so it is not shown to be pre-existing.
  `current_stage_status_request`, `stage_progression_request`,
  `workflow_skips_retrieval` and `attachment_retrieval_scoped` are not in the
  perf allow-list and log `turn_perf_rejected_field` (unchanged; a separate
  decision). The setting `fast_chat_upload_retrieval_enabled` is now read twice
  per turn. A stale docstring in `backend/coaching/evidence_scope.py` still names
  `evaluate_retrieval.py` as the eval caller (code not touched in the docs step).
- **Compatibility and rollback.** No schema or stored-data change. Each commit is
  a separate revert unit; item 2 can be reverted without item 1.
- **Next exact action.** Review the report, then decide: (a) whether to add the
  four dropped telemetry names to the perf allow-list, (b) whether to fix the
  racy `len(client.calls) == 1` assertion, (c) candidate 3 (evidence acquisition),
  which was not started. See [RAG_ARCHITECTURE](RAG_ARCHITECTURE.md) (First-pass
  evidence scope) and [RETRIEVAL_EVAL](RETRIEVAL_EVAL.md) (Command layout).

### Phase 4 status (items 0 to 5 complete; branch `improvement/backend`)

No live command (AWS, Bedrock, AgentCore, Knowledge Base, OpenAI or any paid call)
was run in this phase. Every figure below is a script run unless marked. Detailed
entries for items 0 to 5 follow; the full report is
`.agents/tasks/phase4-2026-11-19.md` (git-ignored, committed with `git add -f`).

| Item | State | Commits |
|---|---|---|
| 0 Record Phase 3c and Laya outcomes, product rule | Done, docs only | `f79f08f` |
| 1 Coaching reply with no recommendation defaults to `stay` | Done; needs a runtime republish; review finding F2 fixed (deploy order note, wire-shape test) | `ec3d87f`, `fd7a6e2`, `860eced` |
| 2 Combined offline gate evaluation (295 rows) | Done; no arm reaches the 25% wrong-skip target on all rows | `21d19ce`, `fabb2f2` |
| 3 Laya production readiness | Report and offline harness only; weight licences and memory not established | `343c8b4`, `5640ab8`, `53c001c`, `825cd2f` |
| 4 Reply text streaming | Mock and direct Bedrock only (opt-in, default off); AgentCore path blocked | `d49767e`, `b8893ec`, `3d375c3`, `2692c81` |
| 5 AgentCore vs Converse benchmark | Harness built and stub-tested, not run | `e77b60b`, `88c9914` |

- **Item 2 headline (script run, Wilson 95%).** Gate alone, all 295 rows: wrong skip
  76/154 = 49.4% [41.6, 57.2], false retrieve 7/141 = 5.0% [2.4, 9.9]. Gate plus
  Laya (multilingual, stored results, floor reading): 65/154 = 42.2% [34.7, 50.1];
  Laya Learn floor 67/154 = 43.5% [35.9, 51.4]; false retrieve unchanged. The
  intervals overlap in every reading. The title-wording arm is a stub-model bound
  only (oracle 0/154, rule stub 16/154, flag-all 120/141 false retrieve); only a
  live run measures wording. Cutoffs were the existing calibrated ones and were not
  tuned on these rows. Laya itself was not re-run (the package and weights are
  absent from the sandbox), so its arm uses the Phase 3d stored per-row decisions.
  Details: [RETRIEVAL_EVAL](RETRIEVAL_EVAL.md).
- **Validation (script run).** Starting baseline at `3060a17`: 2593 passed, 2 failed,
  1 skipped. Final: 2746 passed, 2 failed, 1 skipped (+153 tests). The 2 failures are
  the known `tests/http/test_notebook_reader.py` pair, which need a built
  `frontend/dist` (absent; with a built dist the suite had 0 failures during item 4).
  The skip is the missing `strands` package. No new failures. `ruff check .` passed.
- **Compatibility and rollback.** No schema or stored-data change. New settings
  (`COACH_STREAM_REPLY_DELTAS_ENABLED`) default off; every earlier opt-in setting is
  unchanged and off. Item 1 is the only unconditional behavior change and is
  reverted by reverting `ec3d87f` and `fd7a6e2` (and republishing the runtime).
  Deploy the backend before or with the runtime republish.
- **Open decision, not implemented.** Labelling answers on course Q&A turns where no
  search ran as "general, not from course materials". Described in the report.
- **Next exact action.** The user decides: (1) the item 1 live re-run (13 messages,
  26 calls, about $0.21); (2) whether to run the item 5 smoke (cap 2) and full run
  (cap 100); (3) the open labelling decision; (4) Laya deployment questions (weight
  licences, storage, memory, timeout, startup failure versus fallback);
  (5) whether to pursue AgentCore streaming (a runtime contract change). Entry point
  for the next phase: Phase 5, to be defined from those answers; the first code
  entry point is `backend/coaching/evidence_scope.py` (first-pass scope rules; called from
  `_prepare_authoritative_turn` in `backend/coaching/execution.py`) if the labelling
  decision is approved.

### AgentCore vs direct Converse benchmark harness (Phase 4 item 5, built, not run)

New script `scripts/evals/benchmark_agentcore_vs_converse.py`; no new setting, no
backend change. **No live command was run**: the harness was built and tested with
stub clients only (script run: 41 new tests in
`tests/scripts/test_benchmark_agentcore_vs_converse.py`). Full write-up (exact
paths, commands, IAM, cap counting, cost estimate): `docs/RETRIEVAL_EVAL.md`,
"AgentCore vs direct Bedrock Converse benchmark".

- **Turn set.** The existing synthetic gate messages, rows `i * 295 // 50`
  (`evenly_spaced_indices`), 50 turns, pinned by SHA-256 of the id list so a dataset
  change fails loudly. No new data file.
- **Paths.** `InvokeAgentRuntime` with the Fast Chat payload vs `Converse` (or
  `ConverseStream` with `--converse-stream`) with the same payload, system prompt,
  history and forced `FastChatTurnOutput` tool, both validated by
  `_validated_fast_chat`. The Converse arm has no guardrail, event loop or recovery turn.
- **Measures.** `total_ms`, `first_text_ms` (equal to total unless `--converse-stream`;
  AgentCore cannot show early text), input/output/cache-read/cache-write tokens as
  reported (missing is `null`, not zero), parse failures vs call failures, estimated
  model-token cost.
- **Safety.** Refuses with exit 2 before any client is built without `--live-benchmark`
  and `--max-live-calls` (1 to 100, one shared counter over both paths, 2 calls per turn).
  Stops after the first auth or access error. Records exception classes, exit code and
  a `run` block (git SHA, UTC timestamp); never message text.
- **IAM (documented, not tested in an account).** AgentCore: `bedrock-agentcore:InvokeAgentRuntime`
  on the runtime ARN and its `runtime-endpoint/DEFAULT` ARN. Converse: `bedrock:InvokeModel` on the
  three global-profile resources (Phase 3c report section 9.3); `InvokeModelWithResponseStream` too
  for `--converse-stream`.
- **Cost (estimate, hand arithmetic).** About $0.0086 per call at $1/$5 per million tokens and
  7,100 in / 300 out; about $0.86 for the full 100 calls, range $0.3 to $1.3. Prices are from
  third-party pages and unconfirmed on the AWS page.
- **Rollback.** Delete the script, its test and the docs rows. Nothing else depends on them.
- **Next action.** The user decides whether to run the smoke (cap 2) and then the full run.

### Reply text streaming (Phase 4 item 4, partly blocked)

New setting `COACH_STREAM_REPLY_DELTAS_ENABLED` (default off, in `.env.example`).
No live command was run. Marks: **(script run)**, **(hand)**, **(doc)**.

- **What shipped.** Two opt-in NDJSON events on `/api/v1/coach/turn/stream`:
  `reply_delta` (`{"event":"reply_delta","text":"..."}`, an unvalidated
  fragment, appended in order) and `reply_discard` (no payload, withdraws all
  fragments). A client gets them only when the setting is on and it sends
  `X-Coach-Reply-Deltas: 1`; older clients and the Streamlit transport see the
  original events (a client that rejects unknown events would otherwise end the
  stream as malformed). `reply_ready` is still the validated reply and `done`
  the only saved acknowledgement; idempotency, persistence and error events are
  unchanged. A turn that fails after streamed text sends `reply_discard` then
  `error`; the retry after a source check sends `reply_discard` before the second
  pass. React (`frontend/src/stream.ts`, `Conversation.tsx`) appends deltas to
  the unsaved preview only, clears it on `reply_discard`, `error` and stream end,
  and shows the existing "not confirmed saved" status after a failure.
- **Which providers stream.** Mock (a simulation: it cuts the finished reply into
  4-word pieces, so it proves the transport, not model timing) and direct Bedrock
  Converse (uses `converse_stream` when a client asked for deltas and decodes the
  top-level `response_text` from the streamed forced-tool JSON; validated as before;
  stub-tested only, never run against Bedrock).
- **Blocked: AgentCore Runtime (the production path).** Evidence (hand):
  `agentcore_runtime/main.py` `invoke` returns one dict and its docstring says
  "never `yield`" (lines 818-828); `_stream_specialist_invoke` is a stub that
  returns an error payload (805-815); `backend/agentcore_provider.py` calls
  `invoke_agent_runtime(..., accept="application/json")` (line 1886) and
  parses one response body (`_payload_from_runtime_response`). The runtime does
  see partial reply text (its `_first_text_timing_callback`, `main.py` 169-206,
  finds `response_text` in streamed tool-input JSON), but only for timing. AWS
  documents streaming for AgentCore Runtime (`InvokeAgentRuntime` "supports
  streaming responses"; entrypoints may `yield`) (doc), so the platform can do it.
  Using it needs a changed runtime entrypoint (republished runtime version), a
  streaming response contract, and a decision on the output guardrail, which runs
  on the complete output (`enforce_mantle_guardrail(..., source="OUTPUT")`) after
  generation. That changes the runtime contract, so it was not built.
- **Time to first visible text, mock provider, offline (script run,
  `scripts/evals/measure_stream_first_text.py`, 15 runs per mode, medians).**
  Plain mock: 15.1 ms before (`reply_ready`), 14.5 ms after (`reply_delta`).
  Simulated latency mock (150 ms first token + 20 ms per 4-word chunk, 6-7
  chunks): 286.7 ms before, 183.9 ms after. This shows the pipeline hands the
  first fragment to the consumer as soon as the provider emits it (about 14 ms
  of overhead on top of 170 ms) and that the old path waits for the full reply.
  It does not show real model, AgentCore or network latency, because the delays
  are inputs I chose; it does not show browser rendering time.
- **Tests (script run).** 21 new (18 `tests/domain/test_reply_streaming.py`, 3 in
  `test_bedrock_provider.py`): event order, nothing saved while text streams,
  discard then error after a validation failure, no deltas without opt-in,
  idempotent replay streams no text and calls no model, discard before the
  source-check retry, HTTP needs setting and header, extractor edge cases. Full
  mock suite 2703 passed, 1 skipped, 0 failed with a built `frontend/dist`; without
  it the two known `test_notebook_reader.py` failures return. No frontend unit test
  framework exists; `npm ci` and `npm run build` (`tsc --noEmit` then `vite build`)
  passed. `frontend/dist` and `node_modules` are git-ignored, were not committed
  and were removed afterwards.
- **Risks.** Streamed text can differ from the saved text (retries and
  server-side post-processing); the preview is replaced by `reply_ready`. An
  unvalidated fragment may show text that the final validation rejects, which is
  why it is opt-in, labelled unsaved and withdrawn on failure. Enabling the
  setting with `MODEL_PROVIDER=agentcore` changes nothing.
- **Rollback.** Leave the setting off (default), or revert the commits. No schema
  or stored-data change.

### Laya production readiness (Phase 4 item 3, report only)

No product behavior changed. The classifier stays off unless
`LOCAL_COURSE_INTENT_CHECKPOINT` is set. Nothing here was run against a real
Laya model: the `laya` and `vegaml` packages and every weight file are absent
from this sandbox. No live command was run. The exact harness commands are in
[RETRIEVAL_EVAL](RETRIEVAL_EVAL.md#laya-production-readiness-phase-4-item-3);
sources for each claim below are named inline or are the PyPI JSON pages
(`https://pypi.org/pypi/<package>/json`) read on 2026-11-19.

- **Where weights live.** The code reads only local paths
  (`LOCAL_COURSE_INTENT_CHECKPOINT`, `LOCAL_COURSE_INTENT_LEARNER_BUNDLE`) and
  never downloads at runtime. No weight file is tracked in git. The Learn bundle
  is fitted on the checked-in synthetic messages, so it holds no student data.
  Options, with the one this repo's deploy model favours first: a read-only
  host directory bind-mounted into the container (needs a compose change and a
  deliberate edit of `tests/test_deployment_config.py`, which pins the
  secrets-only mount), the image layer (every image and ECR pull grows; `COPY . .`
  would copy it unless placed deliberately), S3 (needs a new sync step; the app
  has none for models), or git (not recommended: size, and the repo rule against
  committing generated artifacts).
- **Packaging.** `requirements.txt` has no Laya, torch, transformers or
  safetensors. `laya==0.4.38` requires `torch>=2.0`, `transformers>=4.48`,
  `safetensors`, `huggingface_hub` and `vegaml>=0.17`; `vegaml==0.17.1` requires
  `torch>=2.4` and `transformers>=5.17` (PyPI metadata). The torch 2.15.0
  cp312 wheel is 461 MiB for aarch64 and 514 MiB for x86_64 on PyPI, and its
  metadata also lists `nvidia-*` packages with a Linux marker, whose installed
  size was not measured. The production image targets linux/arm64 on
  `python:3.12-slim`. The audit workflow checks only `requirements.txt` and
  `agentcore_runtime/requirements.txt`, so a separate Laya requirements file would
  not be audited unless it is added to `.github/workflows/dependency-audit.yml`.
  The mock CI installs `requirements-dev.txt` only; the Laya tests there use stand-in
  modules.
- **Licences (what was and was not established).** PyPI metadata gives
  `laya` 0.4.38 Apache-2.0 and `vegaml` 0.17.1 Apache-2.0, and the `laya` PyPI
  README states Apache 2.0 for its weights. PyPI metadata gives transformers,
  safetensors and huggingface-hub as Apache-2.0 and lists torch's licence
  expression (Apache-2.0, BSD-2/3-Clause, BSL-1.0, ISC, MIT, Zlib and others). The
  Hugging Face model cards for `convaiinnovations/laya-multilingual`,
  `laya-typed-decisions`, `nandakishorm/vega-U` and `Qwen/Qwen3.5-0.8B` could not
  be read here (HTTP 403), so their licence terms are **not established from a
  primary source**. Third-party cards say Apache-2.0 for Laya multilingual and for
  Qwen3.5-0.8B; nothing was found for `laya-typed-decisions` or `vega-U`. Read each
  model card and licence file before any deployment.
- **Memory and latency.** Not measured on real weights. The harness
  `scripts/evals/benchmark_course_intent.py` exists and was run here with a sleeping
  stand-in only (harness check, `real_model: false`). Recorded earlier figures
  (Phase 3d files, development Mac, not production hardware): multilingual load
  6.76 s and p95 211 ms; typed-decisions load 15.15 s and p95 450 ms; Laya Learn
  p95 about 0.93 to 1.09 s. Memory has no recorded figure anywhere in the repo.
- **Fallback.** A failing, abstaining, busy or malformed classifier leaves the turn
  running on the existing gate with no course search (9 new test cases, stub
  classifier and the real adapter over a stand-in `laya.Agent`). A configured but
  missing checkpoint or missing `laya` package does **not** fall back: it raises in
  `OwnerResolver.__init__` and stops API startup (tested). No timeout wraps
  `score()`, so a hung inference holds the single inference slot and its own turn.
- **Single slot.** Production runs one uvicorn worker, so one classifier and one lock;
  a second concurrent turn gets no score and uses the gate. Phase 3d recorded 93/94
  eligible requests abstaining with eight workers.
- **Dedupe of `.agents/tasks/phase3d-work/`.** All 8 JSON files have distinct sha256
  hashes, so none was removed.

Rollback: nothing to roll back for the report. Decisions left to the user: start-up
failure versus fallback for a missing checkpoint, a classifier timeout, where the
weights are stored, and a separate audited requirements file. Next action: Phase 4
item 4.

### Coaching reply with no recommendation defaults to stay (Phase 4 item 1)

- **Behavior.** A coaching `FastChatTurnOutput` with no recommendation (absent,
  null or blank) is parsed as `stay` instead of failing with "coaching mode
  requires recommendation stay or advance". The default is never `advance`. An
  unknown token still fails, an explicit `advance` and every Q&A reply are
  unchanged, and the model-facing JSON Schema still requires the field.
- **Why safe.** A defaulted `stay` follows the same path as a model-sent `stay`
  everywhere except one place, where it is deliberately treated differently. No
  pending transition is created from it, `auto_advance_stages` acts only on
  `advance`, and stage changes still need student confirmation. Free mode
  (`response_detail=long`, outside Problem Identification) promotes a
  model-sent coaching `stay` to a pending `advance` proposal in
  `backend/workflow.py::_promote_free_mode_advance`. That promotion skips a
  defaulted `stay`: the provider marks the assessment with an in-memory,
  non-persisted flag (`EducationalAssessment.recommendation_defaulted`, a
  pydantic private attribute that `model_copy` keeps), because the model never
  judged readiness. Tests: `tests/domain/test_fast_chat_recommendation_default.py`
  (defaulted `stay` in Free mode stays `stay` with no pending proposal and no
  stage change, graph and sequential paths, auto-advance on and off; explicit
  `stay` in Free mode is still promoted).
- **Observability.** Perf field `fast_chat_recommendation_defaulted` (set only
  when defaulted); live eval row field and summary `recommendation_defaulted`.
- **Deploy note.** The default sits in `agentcore_runtime/models.py`, which both
  the runtime and the backend import. The failure happened inside the runtime,
  so the fix takes effect after the runtime package is republished.
  Deploy order: the backend containing this fix (the commit that reads
  `recommendation_defaulted`, fd7a6e2) must go out before or together with the
  runtime republish. The republished runtime sends `stay` plus the marker; an older
  backend ignores the marker and would see an ordinary `stay`, so in Free mode a
  greeting whose recommendation the model omitted could open a "Next" proposal
  (the student must still confirm; no stage changes by itself). Tested with the
  runtime wire shape in `test_runtime_wire_shape_of_a_defaulted_stay_is_not_promoted_in_free_mode`.
  Rollback: revert the commit and republish; reverting the backend alone
  reintroduces the Free-mode proposal for a runtime that still sends the default.
- **Not measured live.** No live command was run. The re-run command is in the
  Phase 4 item 1 notes.

### Recorded retrieval outcomes (Phase 4 item 0)

This entry records results that were already measured; no behavior changed and
nothing was re-run. Full tables, sources and denominators are in
[Recorded results](RETRIEVAL_EVAL.md#recorded-results-phase-4-item-0).

- **Phase 3c live gate (Haiku 4.5, 169 rows: 109 `retrieve`, 60 `skip`, git
  SHA `61ff634`).** Wrong skip fell from 62/109 (56.9%, Wilson 95% 47.5 to
  65.8) with the baseline wording to 51/109 (46.8%, 37.7 to 56.1) with the
  source-check titles. The gate alone missed 73/109. False retrieve over scored
  rows was 2/57 and 2/58. With the 3 and 2 failed calls counted as errors it
  was 5/60 and 4/60; counted as gate-only it was 2/60. All 5 failed calls are
  greeting rows. The 25% wrong-skip target was not met. The intervals overlap.
  Source: `.agents/tasks/phase3c-work/live-item3-{baseline,titles}.json` (the
  counts and rates are in the files; the intervals are computed).
- **Greeting on/off run (34 messages, 68 calls).** 17 calls failed: 9 with the
  SOURCE CHECK rule on and 8 with it off, on 13 distinct messages, all with
  "coaching mode requires recommendation stay or advance". The rule is not
  shown to cause the failure. Source:
  `.agents/tasks/phase3c-work/live-item1-greetings-on-off.json`. The Phase 4
  item 1 fix is a separate change.
- **Laya.** Counts, rates and p95 times are from the files in
  `.agents/tasks/phase3d-work/`, each with its sample size and a computed
  Wilson interval in the linked tables. On the 169 Phase 3c rows: gate 73/109
  (67.0%, 57.7 to 75.1), typed-decisions 73/109, multilingual 62/109 (56.9%,
  47.5 to 65.8), false retrieve 2/60 in all. On the 84 held-out rows: gate
  24/51 (47.1%, 34.1 to 60.5), Laya Learn 18/51 (35.3%, 23.6 to 49.0) and with
  a first-turn cutoff 15/51 (29.4%, 18.7 to 43.0), false retrieve 2/33. The
  "at least 42/109" threshold-sweep figure in the Local Laya entry below is in
  no committed file.
- **Product rule (a requirement, not implemented as stated).** A course concept
  question requires a course citation. If no supporting excerpt is found, the
  coach says it could not verify the course definition and may add a clearly
  labelled general explanation. The code today only tells the model to say it
  "could not retrieve a validated excerpt" on a course search that returned
  nothing, and it disallows model knowledge on course-catalogue turns. Nothing
  covers a turn where the gate skipped retrieval.

Rollback: none needed, documentation only. Next action: Phase 4 item 1 (the
coaching-mode greeting failure).

### Calibrated routing and passage comparison

Keep the existing gate serving students. Laya improved exact evidence scope on
the fresh set but exceeded the unnecessary-retrieval limit. SetFit tied the
gate on exact scope and missed both retrieval-error limits. On the 307 historical
turns, the gate scored 211, Laya 218 and SetFit 229. Those turns were used only
for regression. Both classifiers selected cutoffs of 0.4 for scope and 0.6 for
mode from ten separate calibration turns.

| Fresh measure | Gate | Laya with fallback | SetFit with fallback |
| --- | ---: | ---: | ---: |
| Exact scope | 13/25 | 16/25 | 13/25 |
| Correct coach mode | 15/25 | 23/25 | 21/25 |
| Unnecessary retrieval | 0/10 | 3/10 | 2/10 |
| Missed retrieval | 10/15 | 1/15 | 5/15 |

Fresh exact-scope counts below include descriptive 95% Wilson intervals. The
25 turns come from four scenario families, so these intervals overstate the
independence of related turns.

| Fresh slice | Gate | Laya | SetFit |
| --- | ---: | ---: | ---: |
| Selected file | 4/15 (11%–52%) | 7/15 (25%–70%) | 4/15 (11%–52%) |
| Saved prior student turn | 6/8 (41%–93%) | 4/8 (22%–78%) | 5/8 (31%–86%) |
| Both sources needed | 1/5 (4%–62%) | 2/5 (12%–77%) | 0/5 (0%–43%) |
| Multilingual | 2/5 (12%–77%) | 3/5 (23%–88%) | 2/5 (12%–77%) |

Both policies preserved all 41 routes explicitly recognized by the gate.
A subsequent review flagged two additional workflow paraphrases in the frozen
fresh set. The existing gate left both unrecognized. Laya initiated retrieval
on both, and SetFit did so on one. Including those probes, preservation was
41/43 for Laya and 42/43 for SetFit. The audit flags are used only for reporting.

| Warm CPU path | One request p50 / p95 | Eight requests p50 / p95 | Busy fallbacks at eight |
| --- | ---: | ---: | ---: |
| Laya | 898.2 / 1023.0 ms | 0.2 / 892.7 ms | 56/64 |
| SetFit native | 19.1 / 24.9 ms | 0.2 / 19.3 ms | 56/64 |
| SetFit ONNX | 20.7 / 39.4 ms | 0.2 / 22.2 ms | 56/64 |

Native and ONNX agreed on both raw heads and both effective decisions on all
342 turns. A clean offline SetFit refit reproduced every saved probability
vector and cutoff. The single inference slot served one request per wave. Concurrent
medians primarily measure gate fallback. Eight waves on this Mac give a
development-machine estimate.

Reranking the same eight authorized candidates raised expected-page recall
from 78/94 to 82/94 with median added latency of 314 ms per question.
On the four fact-annotated questions, both orders found a supporting page for
4/4. All requested facts were present for 3/4 lexical and 2/4 reranked lists.
Laya abstained on all 40 individual passages and top-four lists. It called
zero of the 33 incomplete contexts sufficient, with zero decided incomplete
contexts from which to estimate conditional error.

The [reproduction guide](RETRIEVAL_EVAL.md#evaluate-evidence-scope-coach-mode-and-excerpt-sufficiency)
covers the routing evaluator, passage evaluator, grouped datasets, model
revisions and commands. Fitted bundles, ONNX graph, per-turn predictions,
latency samples, candidate orders and judge decisions are saved locally under
`artifacts/evals/turn-comparison/`. The original sufficiency bundle remains
under `artifacts/evals/laya-turn-decisions-sol/`.

Validation passed 109 focused tests and 2,602 full-suite tests with one
optional skip. Compile, scoped Ruff and Git whitespace checks passed. All
changes are confined to offline evaluation, fixtures, tests and guides.
Rollback requires no student-data migration or deployment action. Start the
next routing experiment with fresh rows 7, 17 and 24 in the Laya report.
All three had a selected file and needed no retrieval. Keep these as regression
cases and evaluate any revised policy on newly labelled families. Keep the
sufficiency judge offline. Haiku/Sonnet selection requires its separate
answer-quality and cost benchmark.

### Offline Laya experiment for three turn decisions

Sol authored 38 examples for evidence scope and coach mode and 31 for
excerpt sufficiency. The [offline evaluator](RETRIEVAL_EVAL.md#evaluate-evidence-scope-coach-mode-and-excerpt-sufficiency)
fit and reloaded both Laya Learn bundles with networking blocked. Existing
evidence-scope labels were kept out of fitting. Coach mode used labels
derived from existing categories, and sufficiency used controlled passage
swaps rather than independently reviewed search results.

On 307 labelled turns, exact evidence scope fell from 211/307 with the gate
to 182/307 with Laya and gate fallback. Wrong skips fell from 84/163 to 3/163,
while unnecessary retrieval rose from 7/144 to 110/144. Laya improved on
selected-file turns (18/37 to 23/37) and follow-ups (12/28 to 19/28), but lost
on turns needing both source types (10/12 to 5/12). The coach-mode head
matched 124/137 category-derived labels. The sufficiency head failed its
internal comparison with Vega. Vega then abstained on all 48 controlled cases.
Serial routing inference p95 was 2.29 seconds on the development Mac.

The 110 focused retrieval tests, evaluator checks, Ruff, and Git whitespace
checks passed. Reports and bundles are in the ignored local directory
`artifacts/evals/laya-turn-decisions-sol/`. There is no runtime change, data
migration, or deployment rollback. Haiku and Sonnet remain configured as
before. Keep the classroom gate and Phase 4 streaming plan. If routing work
resumes, predefine a narrow selected-file or follow-up policy, calibrate it on
a separate split, and measure independently labelled scope and host latency
before any runtime trial.

### Sol-authored training examples for Laya Learn

The offline experiment added 34 eligible examples to the 76-example training
set and recalibrated the thresholds on the original 61 rows. Across 60 new
synthetic messages, both bundles missed 6/30 requests needing retrieval and
falsely retrieved on 0/30 skips. On the earlier 84-row holdout, wrong-skips
fell from 15/51 to 13/51 (25.5%) and false retrieves stayed at 2/33 (6.1%).
Sol authored both the additional training examples and the new test set.
The test messages have no exact overlap with training or calibration, and
the labels lack independent review. The benchmark ran with networking
disabled.

The experiment requires no runtime changes or data migration. The previous
bundle remains the rollback artifact for an opt-in demo. Keep the classroom
gate as configured and proceed to Phase 4 streaming. The experiment inputs,
script, report and bundle are in
[phase3d-work/sol-teacher](../.agents/tasks/phase3d-work/sol-teacher/).

### First-turn calibration for Laya Learn

The pilot can use a separate cutoff before the first saved student message.
Offline calibration on 61 synthetic rows chose 0.6455845832824707 for opening
turns and 0.8563768182025443 thereafter. On the same 84-row comparison set,
wrong-skips fell from 18/51 to 15/51 (29.4%) with 2/33 false retrieves
(6.1%) in both runs. This set was previously examined. On 19 additional
course questions with IDs absent from the gate corpus, misses fell from two
to one. All 19 required retrieval. On the separate 12 follow-ups both
policies missed 1/9 retrieve cases and falsely retrieved on 0/3 skip cases.

A trial using shorter turn inputs and 121 training examples missed 22/51
on the main comparison, so the pilot retains the original learner format
and 76-example training set. Serial CPU inference p95 was 932 ms in the
final run. Focused tests and the full mock build passed. The change requires
no data migration. Clear `LOCAL_COURSE_INTENT_FIRST_TURN_THRESHOLD` to return
to the single cutoff. The classroom feature remains disabled. The pilot did
not reach the 25% wrong-skip target. Proceed to Phase 4 streaming with the
existing classroom gate. [Evaluation instructions](RETRIEVAL_EVAL.md#fit-and-evaluate-laya-learn)

### Laya Learn retrieval pilot

The local FastAPI classifier can load a fixed Laya Learn bundle. The
benchmark fitted on 76 eligible synthetic messages from the training split,
selected cutoffs on 61 calibration rows, then evaluated 84 held-out rows.
Question IDs and duplicate messages stay within one split. On holdout, the
existing gate and frozen Vega both missed 24/51 retrieve cases (47.1%).
The learned head missed 18/51 (35.3%), with false retrieves steady at 2/33
(6.1%). The learned head was used for all 41 eligible holdout turns. Its
CPU inference p95 was 1.09 seconds on the development Mac.

Focused tests and the full mock build passed. A disposable FastAPI run loaded
the real fitted bundle, returned cited course Q&A with mock generation, and
replayed the saved turn after restart. The learned classifier needs no data
migration and builds its bundle from synthetic labels. To roll back an
opt-in process, clear the checkpoint and bundle settings and restart
FastAPI. Keep this pilot disabled for classroom use because it missed the
25% wrong-skip target. If work resumes, test on independently labelled
course questions and measure concurrency on the intended host.
[Fitting and configuration](RETRIEVAL_EVAL.md#fit-and-evaluate-laya-learn)

### Local Laya retrieval pilot

FastAPI can use a local Laya checkpoint to route ambiguous chat turns to the
existing course retrieval and grounded Q&A path. A missing checkpoint setting
keeps the existing gate. Existing evidence scopes take precedence and a busy
or failed classifier falls back to the existing gate.

On the same 169 synthetic Phase 3c rows with a 0.8 cutoff, the gate missed
73/109 retrieve cases and falsely retrieved 2/60 skip cases. Laya
typed-decisions also missed 73/109. Multilingual Laya missed 62/109 and
kept false-retrieves at 2/60. CPU inference p95 was 450 ms and 211 ms,
respectively, on the development Mac. With eight benchmark workers, the
single-slot multilingual classifier bypassed 93/94 eligible requests in an
unpaced burst. A retrospective threshold sweep still missed at least 42/109
with false-retrieves below 10%. Neither checkpoint met the 25% wrong-skip
target.

The frontend build, compilation, and full mock suite passed. A disposable
FastAPI run using the real multilingual checkpoint and the mock response
provider retrieved a local lecture excerpt, returned cited Q&A, and replayed
the saved turn after an API restart. No migration is required. To roll back
an opt-in process, clear
`LOCAL_COURSE_INTENT_CHECKPOINT` and restart FastAPI. Keep the pilot disabled
for classroom use. If routing work resumes, use the local benchmark and a
held-out set for a course-trained classifier, then repeat burst testing on
the intended host. [Benchmark and configuration](RETRIEVAL_EVAL.md#local-course-intent-classifier)

### Local workspace

React serves the student workspace at `/`, with `/pilot/` as an alias.
Lecturers and accounts with Enabled Access use `/streamlit/`. Students can
resume notebook conversations, move or pin chats, search their workspace,
and open Review without a generation call. Stage changes require explicit
confirmation. Notebook Sources control reusable evidence, and chat
attachments apply to the submitted turn unless added as a notebook source.
Past local work checked persistence, source and citation handling, and desktop
and mobile browser behavior. [Application architecture](LOCAL_DEMO_IMPLEMENTATION.md) ·
[React workspace](../frontend/README.md)

Private Library uploads use one stored original and derived text with
owner-scoped links. Existing uploads retain their storage anchors. If legacy
files need to survive deletion of their original conversation, plan and
verify a separate storage migration. [Library and citation behavior](RAG_ARCHITECTURE.md#library-files-and-notebook-sources)

### Classroom and release

| Gate | Evidence and next action |
| --- | --- |
| [#28 Classroom capacity and cost](https://github.com/CloudKai/NUS-Codesign-Chatbot/issues/28) | Open. The mock rehearsal completed three 80-submission waves after the SQLite waiter fix. Obtain the actual gross AWS bill and credit dates, permitted processing locations, and a lecturer-approved wait target. Then assess live throughput, restore evidence, and full operating cost. |
| [#29 React release](https://github.com/CloudKai/NUS-Codesign-Chatbot/issues/29) | Open and depends on the classroom gate. Record the participant comparison, accessibility and capability gaps, and demonstrate rollback against the same saved data. |
| Two course modules | Proposed. Start with module membership, owner scope, and corpus isolation before exposing the second route. The readiness guide covers the shared S$30 budget and overlapping class peaks. |

[Capacity evidence](operations/CLASSROOM_CAPACITY_GATE.md) ·
[Decision register and release checks](operations/CLASSROOM_READINESS_DECISIONS.md) ·
[Post-credit hosting](operations/CLASSROOM_READINESS_DECISIONS.md#post-credit-hosting) ·
[Second course module](operations/CLASSROOM_READINESS_DECISIONS.md#second-course-module-proposal)

### Documentation consolidation

The root README now opens with the local mock workflow. The docs index points
to current architecture, AWS operations, classroom readiness, and contributing
guides. The security guide includes guest access and course-publication
decisions. The learning handbook includes all eight chapters on one page.
Documentation and the handbook PDF generator are the scope of this pass.

The React build, Python compilation and full mock suite passed via
`sh scripts/build.sh`. A disposable local stack served the React shell,
returned API readiness and created a guest session. The consolidated handbook
rendered as 41 pages with the codebase appendix. Local Markdown links and
heading anchors resolved.

The previous working-tree documents are backed up at
`/private/tmp/codesign-docs-before-tightening-2m_inlg6`. Application runtime
and deployment configuration were outside this phase. For the next technical
phase, use the classroom [decision register](operations/CLASSROOM_READINESS_DECISIONS.md#evidence-and-decision-register).

### Task-based documentation index

The [documentation index](README.md) now follows five reader tasks. The
[architecture guide](LOCAL_DEMO_IMPLEMENTATION.md#repository-layout-and-placement-rules)
includes the package map, placement rules and compatibility imports. The
[provider guide](providers/MODEL_PROVIDERS.md) covers AgentCore and direct
Bedrock. Mock load commands live in [testing](TESTING.md#mock-load-probe),
and pilot monitoring and deployment commands live in the
[AWS runbook](deploy/AWS_STATELESS_EC2.md). The
[release checklist](PRODUCTION_RELEASE_CHECKLIST.md) links to the August QA
report at a fixed revision. The
[decision register](operations/CLASSROOM_READINESS_DECISIONS.md#post-credit-hosting)
records the S$30 ceiling, the AWS decision and the second-module proposal.

Verified local Markdown links and heading anchors, the pinned QA Git blob,
script and example paths, and all six example files. The code reference and
handbook PDF generators ran successfully. The three-owner mock load probe
accepted all three turns, the cost examples produced their expected totals,
and the AgentCore smoke CLI passed its dry run. The full mock suite passed
2,595 tests with dependency deprecation warnings. `git diff --check` passed.
GitHub HTTP verification was unavailable because DNS could not resolve the
host. The pinned report is present in the tracked remote branch history.

This change needs no runtime, API, configuration or data migration. Previous
tracked documents remain recoverable from Git. The Sol evaluation artifacts
and findings are preserved. The next technical phase is Phase 4 streaming,
using the [coach stream implementation](../backend/coaching/streaming.py).

## Earlier evidence

The previous repository snapshot contains the original validation commands,
rollback notes, and full phase history.
[Implementation log at 948162e](https://github.com/CloudKai/NUS-Codesign-Chatbot/blob/948162e1eba9d0de3fbda7cbfce1d00731001158/docs/IMPLEMENTATION_STATUS.md) ·
[Original ticket handoffs](https://github.com/CloudKai/NUS-Codesign-Chatbot/tree/948162e1eba9d0de3fbda7cbfce1d00731001158/new_docs/ticket_handoffs) ·
[Streamlit design QA](https://github.com/CloudKai/NUS-Codesign-Chatbot/blob/948162e1eba9d0de3fbda7cbfce1d00731001158/design-qa.md)

For future phases, record the behavior change, validation evidence, compatibility,
rollback, and the next owner action here. Link to the relevant issue or guide
for detailed evidence.
