# Implementation status

## Current status

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
