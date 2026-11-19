# Implementation status

## Current status

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
  Rollback: revert the commit and republish.
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
| Two course modules | Proposed. Start with module membership, owner scope, and corpus isolation before exposing the second route. The hosting plan covers the shared S$30 budget and overlapping 80- or 160-enrolment peaks. |

[Capacity evidence](operations/CLASSROOM_CAPACITY_GATE.md) ·
[Decision register and release checks](operations/CLASSROOM_READINESS_DECISIONS.md) ·
[Hosting plan](deploy/HOSTING_PLAN.md)

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

## Earlier evidence

The previous repository snapshot contains the original validation commands,
rollback notes, and full phase history.
[Implementation log at 948162e](https://github.com/CloudKai/NUS-Codesign-Chatbot/blob/948162e1eba9d0de3fbda7cbfce1d00731001158/docs/IMPLEMENTATION_STATUS.md) ·
[Original ticket handoffs](https://github.com/CloudKai/NUS-Codesign-Chatbot/tree/948162e1eba9d0de3fbda7cbfce1d00731001158/new_docs/ticket_handoffs) ·
[Streamlit design QA](https://github.com/CloudKai/NUS-Codesign-Chatbot/blob/948162e1eba9d0de3fbda7cbfce1d00731001158/design-qa.md)

For future phases, record the behavior change, validation evidence, compatibility,
rollback, and the next owner action here. Link to the relevant issue or guide
for detailed evidence.
