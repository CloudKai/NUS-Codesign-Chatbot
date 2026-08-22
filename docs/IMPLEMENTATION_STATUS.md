# Implementation status

## CURRENT STATUS

### Lecturer student-detail DSQL ORDER BY (2026-08-23)

**Change.** Opening one student 503'd on DSQL because notebook-summary SQL used
``ORDER BY COALESCE(last_active, ...)``; PostgreSQL treats that alias as an
input column. Order by the ``MAX(...)`` expression instead, reuse the proven
roster SQL for the single-student profile, and keep the Students back control
when one record fetch fails.

**Files.** `backend/professor_analytics/repository.py`, `ui/professor.py`,
`tests/http/test_professor_analytics.py`.

**Validation.** Focused professor HTTP tests.

**Next action.** Rebuild the EC2 app image so production student detail works.
Do not republish AgentCore.

### Lecturer dashboard UX + progressive tab fetch (2026-08-23)

**Change.** Lecturer shell now uses a persistent left sidebar (Overview / Students /
Learning / Engagement / Research) with full-width drill-down for Students → student
→ notebook workspace. Students UI fetches tab-scoped endpoints only (messages,
sources, journey, review) with session caches and per-tab Refresh; workspace
all-in-one remains for compatibility. Student detail uses bounded SQL snapshots
(no transcript bodies). New paginated messages endpoint uses keyset cursors
(newest page first, load-earlier for older active-branch turns).

**Files.** `backend/professor_analytics/{models,repository,service}.py`,
`backend/http/app.py`, `backend/api_client.py`, `ui/professor.py`,
`ui/assets/styles/70-professor.css`, `tests/http/test_professor_analytics.py`,
`tests/ui/test_professor_ui.py`, `tests/test_architecture_contracts.py`.

**Validation.** Focused professor HTTP/UI tests, architecture route inventory,
`ruff check` on touched files, `compileall` on `backend` / `ui` / `tests`.

**Migration.** None. Existing `/workspace`, full transcript, source/attachment
bytes routes unchanged.

**Risks.** Staging visual pass still required at 1440px and 390px. Dedicated
DSQL SELECT-only professor DB role is optional defense-in-depth (new pool) and
remains out of scope.

**Next action.** Staging visual check of sidebar shell and Students drill-down;
do not republish AgentCore.

### Lecturer Course Analytics scroll (2026-08-23)

**Change.** The student studio viewport lock (`html`/`body`/`.stApp`/
`.block-container` at `100vh` + `overflow:hidden`) clipped the Students
roster and notebook chat with no scrollbar. Course Analytics now opts out of
that lock when `.st-key-professor_header` is present, and the student list
plus chat/research transcripts are real inner scrollports.

**Files.** `ui/professor.py`, `ui/assets/styles/70-professor.css`,
`tests/ui/test_professor_ui.py`.

**Validation.** Focused professor UI tests plus compileall on `ui`.

**Next action.** Rebuild the EC2 app image so production Students can scroll.
Do not republish AgentCore.

### Lecturer Students roster DSQL fix (2026-08-23)

**Change.** ``load_student_roster()`` compared INTEGER ``is_error`` with
``NOT column``, which SQLite accepts and PostgreSQL/DSQL rejects
(``argument of NOT must be type boolean, not type integer``). The Students
page therefore returned 503 in production while Overview (``load_class_rows``)
still worked. Predicates now use ``COALESCE(is_error, 0) = 0``.

**Files.** `backend/professor_analytics/repository.py`,
`backend/http/app.py`, `tests/http/test_professor_analytics.py`.

**Validation.** Focused professor HTTP tests plus compileall.

**Next action.** Rebuild the EC2 app image so production Students uses the
portable roster SQL. Do not republish AgentCore.

### Lecturer workspace production fix + UX polish (2026-08-22)

**Change.** Professor read paths now preserve the configured database provider
when opening student-scoped stores (no ``Path(None)`` / forced SQLite on DSQL)
and use ``ensure_owner=False`` with ``owner_id`` taken from the verified user
row so lecturer reads never call ``_ensure_user``.
Citation authorization resolves against the same visible-source universe as the
workspace Sources tab, including shared virtual Lecture Notes/Readings. UI:
Markdown chat rendering, clickable citations, compact attachment/source rows,
notebooks moved above analytics, explicit Refresh for session caches, simplified
mobile drill-down CSS.

**Files.** `backend/professor_analytics/{repository,service}.py`,
`ui/professor.py`, `ui/assets/styles/70-professor.css`,
`tests/http/test_professor_analytics.py`, `tests/ui/test_professor_ui.py`.

**Validation.** Focused professor HTTP/UI tests, architecture contracts,
`compileall`, `ruff check` on touched files.

**Next action.** Visual acceptance at 1440px and 390px on staging EC2 image.

### Lecturer dashboard revamp (2026-08-22)

**Change.** Professor Students now loads a compact per-student SQL roster
(`load_student_roster`) instead of materialising one Python row per active
message. Student detail and notebook workspace are fetched only after explicit
UI clicks, with session-local caches in `ui/professor.py`. Workspace API
responses use nested `notebook`, `transcript.messages`, allow-listed
`ProfessorSourceSummary`, and `learning.{journey,hmw_scaffold,review}`; messages
load once per workspace request. Mobile drill-down hides the roster column below
700px once a student is selected.

**Files.** `backend/professor_analytics/{repository,models,service}.py`,
`ui/professor.py`, `ui/assets/styles/70-professor.css`,
`tests/http/test_professor_analytics.py`, `tests/ui/test_professor_ui.py`.

**Validation.** Focused pytest on professor HTTP/UI modules and `compileall`
on `backend` and `ui`.

**Next action.** Visual check at 1440 px and 390 px if layout regressions are
reported.

### Lecturer notebook workspace (2026-08-22)

**Change.** Lecturers can open a student's notebook into a read-only workspace with
**Chat | Sources | Journey | Review** tabs. New professor routes:
`GET .../conversations/{notebook_id}/workspace` and
`GET .../sources/{source_id}` (library sources only; chat attachments stay on
the existing attachment route). Sources metadata uses `professor_public_source`
(no extracted text, paths, or bytes in the list). Learning payload includes
`normalize_journey`, `hmw_scaffold_projection`, and `learning_review`.
Audits: `professor.workspace`, `professor.source`.

**Files.** `backend/professor_analytics/{models,repository,service}.py`,
`backend/http/app.py`, `backend/api_client.py`, `backend/workspace_service.py`,
`ui/professor.py`, `ui/assets/styles/70-professor.css`,
`tests/http/test_professor_analytics.py`, `tests/ui/test_professor_ui.py`,
`tests/test_architecture_contracts.py`.

**Validation.** `tests/http/test_professor_analytics.py`,
`tests/ui/test_professor_ui.py`, `compileall` on `backend` and `ui`.

**Next action.** None for this slice unless a visual check at 1440 px / 390 px
surfaces layout issues.

### Current authority / release state (2026-08-22)

**Source code HEAD:** `1799a5b` (release-hardening, attachment relevance, professor
access audit, and Fast Chat wire strictness are committed on
`Integrate-Bedrock-v2`).
**EC2 application image:** `cde2300-chatbot:ddfc3f4` (source/image status is
unchanged; no EC2 rebuild or deployment was performed here).
**AgentCore runtime:** live mapping re-read 2026-08-22 12:03 UTC:
DEFAULT → **v31 READY**. Artifact
`agentcore-patches/chatbot_harnessAgent-fastchat-contract-20260822T115716Z.zip`.
Byte-for-byte match against local `agentcore_runtime/` source (33 `.py`/`.md`
files, excluding README/`requirements.txt`/`__init__.py`). No new version
published; overlay would have been a no-op.
**Guardrail:** live runtime env is `GUARDRAIL_ID=o8aipba8m129` /
`GUARDRAIL_VERSION=4`.
**Affinity generation:** tracked Compose generation `7`; this check does not bump it.

These are distinct authorities: source HEAD identifies application code, the
EC2 image identifies the deployed FastAPI/Streamlit artifact, AgentCore
runtime identifies the generation-only model service, Guardrail identifies its
runtime safety configuration, and affinity generation identifies the
application/runtime session compatibility value. Historical entries below
retain their original release observations.

### AgentCore prompt overlay check (2026-08-22)

**Change.** Did not create a new runtime ARN and did not upload prompt files
onto EC2. Live DEFAULT was already **v31 READY** on
`NUSCodesignChatbot_chatbot_harnessAgent-6ncEO79sD7`, updated 2026-08-22
11:58 UTC. Local `agentcore_runtime/` at `1799a5b` matches that zip, so a
second overlay was skipped.

**Validation.** `get-agent-runtime` and DEFAULT endpoint both READY at
liveVersion 31. Guardrail env remains v4. Identity was account
`355604674280` / `us-west-2`. No model invoke. No EC2 rebuild.

**Compatibility / risk.** Warm EC2 affinity sessions at generation `7` can
still keep pre-v31 microVM assets. The student “test” toast is
`structured_output_failure` / `malformed`, not a missing prompt file on the
EC2 disk.

**Next exact action.** If existing production notebooks must leave older
warm runtimes, bump host `AGENTCORE_SESSION_GENERATION` to `8` and recreate
the FastAPI container. Do not SCP prompts onto EC2.

### Lecturer dashboard progressive disclosure (2026-08-22)

**Change.** Professor Students now follows a roster → selected student →
selected notebook transcript flow. `student_detail()` uses a student-scoped
active-row query plus a compact body-free class assessment benchmark instead
of rebuilding every student’s detailed rows. Notebook summaries remain
transcript-free; transcript responses contain only the selected active branch,
safe message attachment descriptors, and citation references. An authorized
professor attachment endpoint verifies student, notebook, active message
association, and attachment origin before streaming bytes. Top-level tabs are
Overview, Students, Learning Progress, Engagement, and Research Review.

The release pass moved attachment opening to a lazy authenticated API-client
fetch inside a lecturer-owned preview/download dialog; no browser-facing URL
is constructed from the API base URL. Citation refs now normalize current dict
records and legacy ids, then filter to notebook-owned sources. Source origin is
checked exactly after projection. Overview, Learning Progress, Research Review,
responsive Students master-detail, transcript stage metadata, and keyed message
cards now match the lecturer UX brief.

**Validation.** The focused lecturer-dashboard acceptance run passes 87 tests,
including scoped detail, attachment metadata separation, active transcript
projection, lecturer authorization, and authorized attachment access. Sol
completed local visual verification at 1440 px and 390 px: Students stacks
without horizontal overflow; Research Review uses two desktop columns and a
stacked mobile layout. Ruff, backend/UI compileall, and `git diff --check` pass.
The broader repository suite still has unrelated failures in the existing dirty
Fast Chat/idempotency and architecture-contract changes.

**Compatibility / risk.** No schema or persisted-data migration. Existing
Sources remain separate from chat attachments, and no model/AWS/deployment
change was made. FastAPI/EC2 rebuild is required for the new route; AgentCore
republish and generation bump are not required.

**Next exact action.** Rebuild/deploy the FastAPI/Streamlit app in staging/EC2
and smoke-test lecturer auth, one selected student/notebook, and one
attachment. No AgentCore publish or generation bump is required for this
dashboard change.

### Release hardening pass (2026-08-22)

**Change.** Fixed idempotency replay to prefer the durable marker ``turn`` dict
over slim message reconstruction in ``claim_coach_request``, and to stamp that
exact turn onto the pending marker in the same ``persist_coach_turn``
transaction so same-key waiters cannot observe a slim reconstruction in the
persist-before-complete window. Fast Chat wire adaptation now requires
``citations``, ``hmw_scaffold_ready``, ``needs_source_retrieval``, and
``out_of_scope`` on slim ``mode`` payloads that do not carry a nested
``assessment``; legacy synthesis paths still fill those keys explicitly.
Internal ``FastChatTurnOutput`` constructors keep Python defaults. Stale tests
updated for Q&A retrieval evidence-gap success, compatibility-façade
``selected`` signature, and revise persist-before-complete durable-field replay.

**Validation.** The previously failing idempotency/concurrency/rate-limit/
critical-path tests pass individually and 5/5 under repeated concurrent
reruns. Focused modules, Ruff, compileall, and ``git diff --check`` pass.
The supported deterministic full suite is green: 1644 passed, 0 failed.
Type checking is not configured. Lecturer analytics SQL was not changed.

**Compatibility / risk.** No schema migration, AWS mutation, AgentCore publish,
``AGENTCORE_SESSION_GENERATION`` bump, or compose generation/guardrail change.
Source HEAD is ``1799a5b``; compose.prod generation ``7`` / Guardrail v4
unchanged. FastAPI/EC2 rebuild is required to pick up the application-side
idempotency and wire-parse fixes; AgentCore republish is not required because
the runtime JSON Schema already required those fields.

**Next exact action.** Rebuild/deploy the FastAPI/Streamlit app in staging/EC2
and run the manual mobile/browser smoke checklist. No AgentCore publish or
generation bump is required for this hardening pass.

### Private attachment relevance, scroll, and edit rendering (2026-08-22)

**Change.** Current-turn attachment questions now scope deterministic retrieval
to the private attachment when the request is informational and does not name
course material. Explicit course comparisons retain combined attachment plus
course retrieval, while the existing single Fast Chat `out_of_scope` decision
still owns the semantic scope boundary. Attachment edit rows and pending
revisions preserve the authoritative attachment descriptor exactly once; the
obsolete suffix remains hidden. The existing bounded `chat_feed` remains the
only transcript scrollport.

**Validation.** Added deterministic retrieval-scope, composite Knowledge Base
exclusion, attachment boundary-copy, and edit-attachment render assertions.
Focused attachment/retrieval/provider/schema/UI regressions, Ruff, compileall,
and `git diff --check` pass. No AWS, paid model calls, persistence migration,
or AgentCore changes were made.

**Compatibility / risk.** Private attachments remain hidden from reusable
Sources and continue through the existing authorization and one-call provider
path. Project evidence is not rejected merely because it is not official
course material. FastAPI/Streamlit must be rebuilt for this change; AgentCore
republish and affinity generation bump are not required.

**Next exact action.** Run the bounded staging/EC2 smoke: ARP/DHCP attachment
question (no course KB retrieval), relevant project PDF/image, explicit
attachment-plus-Lecture comparison, long attachment chat scroll, and attached
message edit success/failure.

### Direct image source attribution (2026-08-22)

**Change.** Citation resolution now keeps the existing retrieved-chunk rule for
text sources and additionally admits an image only when its authoritative
selected source was successfully resolved into the current turn's
`image_inputs`. Image labels use the same full selected-source `S#` order as
text retrieval, and the prompt now gives the model that trusted label.

**Validation.** Added deterministic coverage for direct image citations and
selected-but-unresolved images. Citation, retrieval, prompt-composition,
AgentCore-provider, and one-call tests pass except the pre-existing synthetic
6k context-budget regression. No RAG routing, retrieval, latency, model,
Guardrail, HMW, or Deep Review behavior changed; no AWS calls or deployment
was performed.

**Next exact action.** Rebuild the FastAPI application for the changed backend
resolver/prompt composer. AgentCore republishing is not required unless the
runtime prompt artifact itself is separately changed.

### Immediate reusable Sources uploads and private chat attachments (2026-08-22)

**Change.** Sources-panel uploads now enter a process-local background worker
and show an immediate non-authoritative Uploading card; Chat remains usable
while extraction/storage completes. Chat-composer files instead use the new
authenticated attachments route and are stored as hidden, unselected
`chat_attachment` source records. They are resolved only for the submitted
turn, persisted as sanitized message descriptors for display/retry/edit, and
are excluded from Sources, subsequent turns, and Deep Review snapshots.

**Validation.** Deterministic source-library, workspace API, chat progress,
chat-scroll, Sources UI, rerun-scope, and API-client tests pass. Ruff,
compileall, and `git diff --check` pass. No model calls, AWS calls, schema
migration, or deployment was performed.

**Compatibility / risk.** Existing reusable Sources and historical messages
remain unchanged. Pending Sources cards are process-local and disappear after a
Streamlit process restart; successfully stored sources are authoritative. The
next exact action is desktop/mobile visual verification with a deliberately
slow upload, followed by the ordinary application deployment.

### AgentCore Guardrail v4 release (2026-08-22)

**Change.** Published immutable AgentCore runtime **v29** on the existing
`NUSCodesignChatbot_chatbot_harnessAgent-6ncEO79sD7` runtime. `DEFAULT` is
READY and points to v29. The runtime keeps the existing Python 3.14 artifact
layout, IAM role, PUBLIC network, MMDSv2 requirement, gateway/memory settings,
30-minute idle timeout, and 8-hour maximum lifetime. Its environment now uses
`GUARDRAIL_ID=o8aipba8m129` with `GUARDRAIL_VERSION=4`.

Artifact:
`s3://cdk-hnb659fds-assets-355604674280-us-west-2/agentcore-patches/chatbot_harnessAgent-guardrail-v4-ccb388-20260822T-release.zip`

**FastAPI cutover.** Tracked Compose/example configuration uses
`GUARDRAIL_VERSION=4` and `AGENTCORE_SESSION_GENERATION=7`. Update the private
local/EC2 `.env` and recreate the production container with those values before
existing affinity sessions can no longer reuse the previous runtime assets.
DSQL remains the canonical transcript/state store.

**Validation.** Guardrail v4 is `READY`; AgentCore v29 is `READY`; `DEFAULT`
routes to v29; runtime tests/config tests, Ruff, compileall, and
`git diff --check` pass. No model inference or application database changes
were made.

**Next exact action.** Update the production host `.env` to Guardrail v4 and
generation 6, recreate the FastAPI container, then run one text-only and one
image-upload smoke test. Roll back by restoring the previous host generation
and pointing `DEFAULT` to a prior READY runtime if needed.

### AgentCore image upload decoding (2026-08-22)

**Change.** The AgentCore companion runtime now strictly decodes JSON-safe
base64 values in `image.source.bytes` into raw SDK bytes before Strands/Bedrock
invocation. Text blocks, ordering, prior history, source authorization,
image limits, Guardrails, and structured-output contracts are unchanged.
Malformed, empty, or unsupported image byte shapes fail through the existing
student-safe `structured_output_failure` envelope before model invocation.

**Validation.** AgentCore runtime image/provider tests passed; the full runtime
test module passed (**45 passed**). Ruff, compileall, and `git diff --check`
passed. No AWS calls or application/API changes were made. The updated
`agentcore_runtime` package must be republished as a new READY AgentCore
version before production image coaching uses this fix.

**Next exact action.** Publish the current runtime artifact, move `DEFAULT` only
after it is READY, then run bounded PNG/JPEG and text-only production smoke
tests. Keep DSQL canonical and do not change prompts or Guardrails.

### Problem Identification working-HMW completion (2026-08-22)

**Change.** The AgentCore and local Problem Identification prompts now treat a
substantive student-authored HMW as a working draft. A rough, bullet/plus-sign,
problem/friction-oriented, or multi-benefit statement advances when it still
communicates an identifiable user, meaningful problem/need/opportunity, and
desired outcome. Refinement is feedback rather than a progression gate. The
existing 2/3 scaffold rule, provenance guard, server stage authority, and
solution-locked/template-filler STAY behavior are unchanged. The deterministic
mock now stamps normal coaching assessments with `response_mode=coaching`.

**Validation.** Added the exact live rough HMW regression plus rough-format,
multi-outcome, solution-locked, and empty-template cases. Focused HMW,
workflow, prompt, schema, and learning tests pass (**129 passed** in the
combined run; no AWS/model calls). No database migration or runtime service
change was made. AgentCore must be republished and the app redeployed before
this prompt behavior reaches production.

**Next exact action.** Publish the updated AgentCore stage prompt, then run one
production smoke with the exact working HMW and verify `recommendation=advance`,
`hmw_scaffold_ready=false`, and Concept Generation stage authority. Do not
change the scaffold or provenance guards.

### Progress-over-interrogation pedagogy (2026-08-22)

**Change.** Added one high-priority shared coaching rule in the mirrored local
and AgentCore prompt trees: once the current stage purpose is adequately met,
advance usable-but-imperfect work rather than probing for optional refinement.
STAY remains appropriate for substantive blockers, and advancing responses do
not need to end with a Socratic question. Problem Identification HMW rules,
stage authority, Q&A isolation, RAG, and Deep Review are unchanged.

**Validation.** Added deterministic behavior cases for adequate/optional
refinement, substantive blockers, filler, misconceptions, HMW readiness and
completion, Concept Generation, and Q&A isolation. Focused pedagogy/Fast Chat/
HMW/workflow tests pass; Ruff, compileall, and `git diff --check` pass. No AWS
calls or deployment was performed.

**Next exact action.** Republish AgentCore before production use so the shared
runtime prompt change is active; then run a no-cost/local smoke and one bounded
production HMW progression check.

### Unified chat feed and persistent edit history (2026-08-22)

**Change.** The Streamlit chat fragment now owns a single `chat_feed` containing
persisted history and in-flight user/Coach content, with the composer kept as a
fixed sibling footer. Edit submission reruns only the fragment, renders the
active prefix plus the revised prompt/status, hides the obsolete downstream
branch, and remounts authoritative persisted state after success. Failed edits
restore the draft and stable retry key without blanking the transcript.

**Validation.** Focused Streamlit UI, scroll, progress, rerun-scope, theme,
HMW-scaffold, and UI timing tests pass. No backend, API, persistence, or
coaching behavior changed.

**Next exact action.** Verify the feed and edit waiting/error states visually at
desktop and narrow mobile widths with a delayed deterministic provider.

### Narrow mobile chat feed scrolling (2026-08-22)

**Change.** Existing tablet/mobile breakpoints now make `chat_feed` the touch
scroll owner with vertical overscroll containment and remove nested scrolling
from ordinary user bubbles. Desktop bubble limits and edit/composer textarea
scrolling remain unchanged; attachment cards and citation controls retain their
existing ownership.

**Files.** `ui/assets/styles/90-responsive.css` and
`tests/ui/test_chat_scroll.py`.

**Validation.** The focused Streamlit UI, chat-scroll, and theme suite passes
(34 tests). Ruff, UI/entrypoint compileall, and `git diff --check` pass. No
backend, API, persistence, or AgentCore change was made.

**Next exact action.** Verify the feed at desktop and 390 px widths with a
long ordinary user message, attachment, citation, edit draft, and long
composer draft.

### AgentCore runtime configuration correction (2026-08-21)

**Issue.** The lifecycle-only v27 update omitted the prior runtime environment
variables. v27 was `READY`, but its environment was empty, so Fast Chat failed
immediately with a generic AgentCore-unavailable 503 before model generation.

**Correction.** Created v28 on the same runtime ARN, restoring the v26 model,
Guardrail v3, gateway, memory, and MMDSv2 metadata configuration while keeping
`idleRuntimeSessionTimeout=1800` seconds and `maxLifetime=28800` seconds.
`DEFAULT` now points to v28 `READY`. Existing v27 sessions can retain their
old environment until expiry, so the application affinity generation was
advanced to **5** to force fresh v28 sessions. No application code or prompt
change was made for this correction.

### AgentCore lifecycle update (2026-08-21)

**Change.** Updated the existing runtime ARN in place with the same v26 code
artifact and runtime role, changing only lifecycle settings to
`idleRuntimeSessionTimeout=1800` seconds (30 minutes) and
`maxLifetime=28800` seconds (8 hours). AWS created immutable version **27**;
`DEFAULT` now points to v27 and is READY. No application model, prompt,
database, or retrieval behavior changed.

**Affinity cutover.** Production Compose now explicitly enables the existing
compute-affinity path and sets `AGENTCORE_SESSION_GENERATION=5`. The private
ignored local `.env` was also bumped from 3 to 5. This forces new affinity
session identities after the lifecycle/version change; DSQL remains the
canonical transcript and AgentCore remains generation-only.

**Next exact action.** Rebuild/redeploy the production FastAPI image from the
intended SHA so Compose generation 4 is active, then run the bounded release
smoke. Do not change the runtime ARN or create another runtime.

**This phase.** Published AgentCore **v26** on the existing ARN
`NUSCodesignChatbot_chatbot_harnessAgent-6ncEO79sD7`. Surgical overlay of
live v25 zip plus working-tree `models.py`, `prompts/fast_chat.md`,
`prompts/shared_coaching.md`, and `prompts/stages/problem_identification.md`.
Artifact
`s3://cdk-hnb659fds-assets-355604674280-us-west-2/agentcore-patches/chatbot_harnessAgent-hmw-prompt-conflict-20260821T040421Z.zip`.
Runtime env copied from v25 (Haiku 4.5 Fast Chat, Sonnet 4.6 Deep Review,
Guardrail v3). DEFAULT auto-moved to 26 and is READY. No generation bump.
No FastAPI/EC2 rebuild. No paid smoke.

**What v26 carries.** The 2/3 HMW rule is unchanged. Later CORE FOCUS /
READINESS SIGNALS, shared stay-when-missing wording, and the
`hmw_scaffold_ready` tool-field description now cannot override stay+true
when at least two of user / problem / outcome are clear.

**Warm sessions.** Production affinity remains ON and
`AGENTCORE_SESSION_GENERATION` remains **2**. Warm v25 microVMs keep v25
assets until generation is bumped and FastAPI is recreated. Local testing
with affinity **off** uses a fresh `stateless-` session and therefore hits
DEFAULT v26. New production notebooks / new affinity sessions should also
get v26.

**Next exact action.** Local Fast Chat with `AGENTCORE_QUALIFIER=DEFAULT`
and affinity off: reproduce the older-pedestrians 2/3 turn and confirm
`hmw_scaffold_ready_model=true`. Do not bump generation or rebuild EC2
unless existing production warm sessions must leave v25.

### Fast Chat latency implementation (local, 2026-08-21)

**Scope.** Kept the existing deterministic false-positive `who` retrieval
gate fix and made the local AgentCore example use the existing affinity path.
No AWS or paid model calls were made. Runtime model/config caches, AgentCore
client reuse, prompt-file caching, retrieval deduplication, and the 8,000
character Fast Chat evidence cap were already present; no speculative changes
were made to those paths.

**Changes.** `.env.example` now sets
`AGENTCORE_SESSION_AFFINITY_ENABLED=true` for the single-owner local smoke
setup, while `backend/settings.py` remains fail-safe when the variable is
omitted and production must use unique authenticated owner identifiers.
The private ignored local `.env` also has
`AGENTCORE_SESSION_AFFINITY_ENABLED=true` with
`AGENTCORE_SESSION_GENERATION=4`; this is untracked local-only configuration,
not a commit or deployment change.
The synthetic provider compression fixture now uses a 6,500-token constrained
budget (a conservative rounded value; the first integer threshold for the
fixture was approximately 6,280). The old 6,000-token fixture was stale and
artificial: it is parser-accepted by the settings range but is not a shipped
or recommended configuration, and cannot retain the current contract plus the
memory invariant. Provider documentation now describes affinity as
compute-only and conditional rather than asserting every invoke is fresh.

**Evidence.** Retrieval-gate, AgentCore provider/affinity, context planner,
Fast Chat context/one-call/first-cycle, RAG fallback, prompt, deployment, and
performance tests passed: **690 passed, 1 skipped** (the optional Strands
middleware test because `strands` is not installed). The separately run
prompt-baseline lock still has its one known failure because the pre-existing
dirty HMW prompt edits change `agentcore_runtime/prompts/shared_coaching.md`.
The six-run warm deterministic provider benchmark medians were: PI no-RAG
**0.248 ms**, PI fake RAG **0.263 ms**, Q&A fake RAG **0.230 ms**, and
long-history Fast Chat **2.874 ms**. Fake RAG used an injected evidence
fixture and excludes retrieval I/O. Ruff, compileall, and
`git diff --check` passed; live affinity A/B still requires an approved paid
smoke.

**Next exact action.** Run the bounded approved affinity OFF/ON live A/B on the
same notebook, recording cold separately from three to five warm turns. Keep
DSQL/SQLite canonical and bump `AGENTCORE_SESSION_GENERATION` only when
publishing new runtime assets.

### Prior: AgentCore v25 publish

**HEAD at publish:** `dd7e66d`. Live citations RC remains `64410dc`. Composer
layout remains `711d4e6`.
**Live app image:** `cde2300-chatbot:ddfc3f4` (unchanged; no EC2 rebuild)
**Live AgentCore:** DEFAULT → **v25 READY**. Affinity ON. Generation 2.
Prompt cache OFF.

**This phase:** Publish AgentCore **v25** on the existing ARN
`NUSCodesignChatbot_chatbot_harnessAgent-6ncEO79sD7`. Overlay of live v24 zip
plus HEAD `main.py`, `models.py`, `structured_coach.py`,
`prompts/fast_chat.md`, `prompts/review_deep.md`, and
`prompts/stages/problem_identification.md`. Artifact
`s3://cdk-hnb659fds-assets-355604674280-us-west-2/agentcore-patches/chatbot_harnessAgent-deep-review-hmw-20260821T032025Z.zip`.
DEFAULT liveVersion **25** READY (`lastUpdated` 2026-08-21T03:20:46Z). Runtime
env copied from v24. Not bundled: RAG, affinity, generation, prompt cache.
No paid coaching or Deep Review smoke in this publish.

**What v25 carries.** Deep Review `DeepReviewTurnOutput` with required
`stage_reviews` / `supporting_message_refs`; exposed-label `M#` prompt
wording; HMW 0–1 / 2–3 / valid-student-HMW ADVANCE prompts. New notebooks
and new affinity sessions get v25. Warm v24 microVMs stay on the version
they were created with because generation remains **2**.

**Not changed.** FastAPI/EC2 image; `AGENTCORE_SESSION_GENERATION=2`; prompt
cache OFF; DSQL; RAG. Live `ddfc3f4` FastAPI still lacks later HMW-card and
Deep Review checkpoint mapping until an EC2 rebuild from current HEAD.

**Next exact action at the time.** Rebuild/redeploy the EC2 app image from
`dd7e66d` or later when production FastAPI should persist mapped
`supporting_message_ids` and show current HMW-card behaviour. Keep
generation **2** unless existing warm sessions must leave v24. Do not enable
prompt cache.

### Prior: Deep Review array and HMW scaffold guards (local)

**HEAD before that work:** `c4a8e1f`. Live AgentCore was still v24.

**Prior blocker phase behavior:** Implemented only the five confirmed RC
blockers: fail closed when oversized Deep Review `full_history` would be
compressed; require the
frozen source ID set to remain intact; reject HMW construction/meta requests
as provenance; validate new Deep Review arrays strictly while keeping an
explicit legacy v24 boundary; and normalize rejected PI advances so response,
scaffold, recommendation, and authoritative stage agree. Keep checkpoint
version 1, one Sonnet invoke, existing Fast Chat/RAG behavior, and no deploy.

**Behavior.** `context_plan.ref_map` is the model-exposed `M#` map for that
invoke, not every label theoretically generable from the frozen transcript.
`checkpoint_delta` therefore accepts supporting refs only for validated
anchors plus raw delta messages. Compact checkpoint body now includes bounded
prior `readiness_evidence`. Compacting requires the transcript to exceed
20,000 estimated tokens **and** save at least 1,000 tokens **and** at least
20% of the full transcript; otherwise `full_history` (fallback
`compact_not_smaller`, `compact_savings_too_small`, or
`compact_savings_ratio_too_small`). Source fingerprinting remains selected
`source_id` identity: student uploads mint a new UUID per add, so ids are
immutable per content version. Do not claim production cost savings.

**Not changed.** AgentCore DEFAULT/generation/prompt cache; EC2 image;
DSQL schema; retrieval/citations; Fast Chat slim schema and `turns=2`;
checkpoint version; deployment or AWS state. Existing unrelated dirty
`scripts/load_probe.py` was preserved.

**Validation (local worktree, $0 AWS).** Ruff passed on touched Python.
`compileall` passed for `backend`, `ui`, `streamlit_app.py`, `tests`, and
`agentcore_runtime` (`scripts/load_probe.py` remains a pre-existing
`IndentationError`; left untouched). Focused Deep Review, AgentCore schema,
Fast Chat, HMW, revision, RAG/citation, and HTTP tests passed. Full
deterministic suite: **1564 passed**
(`--ignore=tests/scripts/test_load_probe.py`). Ruff passed on all touched
Python files; `git diff --check` passed. No paid model calls were made.

**Next exact action at the time.** Publish a matching AgentCore runtime
(done as v25). Remaining follow-ups from the RC review (same-key
course-source fingerprints and horizontal-worker running-job claims) were
intentionally unfixed.

### Prior: Problem Identification → How Might We progression

**HEAD:** `9f32fb5`. Live AgentCore was still v24.

**Behavior.** 0–1 framing components: stay, hide scaffold, one Socratic
question. 2–3 components without a valid student HMW: stay, show the HMW
card after the Coach reply (including after the first useful turn). A valid
student-authored HMW: hide the card, concise Coach feedback, ADVANCE, and
existing machinery may move to Concept Generation. Equivalent prose without
an HMW does not complete the stage. A deterministic `student_hmw_candidate_present()`
guard forces stay when Haiku recommends ADVANCE without an active-user HMW
attempt. Latest stay+ready governs visibility; a later valid HMW ADVANCE
hides the card. Q&A and Deep Review stay isolated. One Fast Chat invoke. Zero
extra Retrieve calls. No minimum Coaching-turn count.

**Next exact action.** A future AgentCore runtime publish is required before
live Haiku follows the updated Problem Identification / Fast Chat prompts.

### Prior: cost-efficient Deep Review context

**HEAD:** `a217316`. Live AgentCore was still v24.

**Behavior.** FastAPI freezes revision, message ids, source ids, and prior
checkpoint identity at enqueue. Context mode is `full_history` or
`checkpoint_delta`. Default compact threshold is 10,000 estimated transcript
tokens (`DEEP_REVIEW_CHECKPOINT_TOKEN_THRESHOLD`). Reflection stays full
history when `DEEP_REVIEW_FORCE_FULL_FINAL` is true. Sonnet returns ephemeral
`M#` supporting refs; FastAPI maps them to durable ids. Failed Deep Review
leaves the previous snapshot. Fast Chat is unchanged (one Haiku call).
Synthetic 30→80 message comparison: full_history 14609 estimated tokens vs
checkpoint_delta 10802 (saved 3807); all 50 delta turns and the evidence
anchor remained present.

**Next exact action.** A future AgentCore publish is required before live
Sonnet emits `supporting_message_refs` (and continues to emit
`stage_reviews`). Until then, live Deep Review still uses full_history
whenever anchors are missing. Do not move DEFAULT. Do not rebuild EC2 in
this phase. Do not enable prompt cache.

### Prior: Review-tab expander remount + stage-aware Deep Review

**HEAD:** `f81d508`. Live citations RC remains `64410dc`. Composer layout
remains `711d4e6`. HMW 2-of-3 remains `89ccfed`.
**Live app image:** `cde2300-chatbot:ddfc3f4` (unchanged; no EC2 rebuild)
**Live AgentCore:** DEFAULT → **v24 READY**. Affinity ON. Generation 2.
Prompt cache OFF. **Do not publish AgentCore for this phase.**

**This phase:** Review-tab expander remount + stage-aware Deep Review
projection. Uncommitted on `51927c5`.

**Behavior.** When the Thinking Path current stage changes (or the notebook
changes), Strengths and Areas for improvement remount so only the current
stage starts open. Same-stage reruns keep widget keys, so a student's
manual open/close is preserved. Deep Review still freezes the whole active
conversation at enqueue. New snapshots persist `stage_reviews` and merge
those lists onto matching Review stages. Holistic synthesis, Facione, and
working conclusion stay whole-conversation. Legacy snapshots without
`stage_reviews` still dump flat strengths/areas onto `reviewed_stage_id`.
Failed Deep Review leaves the previous snapshot. Fast Chat is unchanged
(one Haiku call, no extra router/retrieval).

**Not changed.** AgentCore DEFAULT/generation/prompt cache; EC2 image;
DSQL schema; RAG; citations; HMW; stage advancement; Fast Chat
`turns=2`; Deep Review `turns=3`; frozen `message_ids` / sources /
revision.

**Validation (local worktree, $0 AWS).** Targeted mock pytest: 212 passed
(expander remount, Deep Review projection/execution, runtime/specialists,
HMW, Fast Chat one-call, progress merge). Full deterministic suite:
1497 passed (`--ignore=tests/scripts/test_load_probe.py`; pre-existing
broken `scripts/load_probe.py` left unstaged). `compileall` passed for
`backend`, `ui`, `streamlit_app.py`, `tests`.

**Next exact action.** A future AgentCore publish is required before live
Sonnet emits `stage_reviews`. Until then, live Deep Review still falls
back to the legacy flat-list → `reviewed_stage_id` merge. Expander remount
does not need a runtime publish. Do not move DEFAULT. Do not rebuild EC2
in this phase. Do not enable prompt cache.

### Prior: AgentCore v24 HMW overlay

**HEAD:** `89ccfed` (HMW 2-of-3 + unlock-turn placement). Citations schema
RC remains `64410dc`. Composer layout remains `711d4e6`.
**Live app image:** `cde2300-chatbot:ddfc3f4` (unchanged; no EC2 rebuild)
**Live AgentCore:** DEFAULT → **v24 READY**. Affinity ON. Generation 2.
Prompt cache OFF.

**This phase:** Surgical AgentCore **v24** overlay so live Haiku can emit
`hmw_scaffold_ready` and judge Problem Identification HMW readiness as two
of three framing signals. Same ARN
`NUSCodesignChatbot_chatbot_harnessAgent-6ncEO79sD7`. v23 kept READY.

**v24 publish (2026-08-20).** Overlay of live v23 zip + HEAD
`agentcore_runtime/models.py`, `prompts/fast_chat.md`, and
`prompts/stages/problem_identification.md` only. Artifact
`s3://cdk-hnb659fds-assets-355604674280-us-west-2/agentcore-patches/chatbot_harnessAgent-hmw-scaffold-20260820T142111Z.zip`.
DEFAULT liveVersion **24** READY (`lastUpdated` 2026-08-20T14:22:16Z).
Runtime env copied from v23: Haiku 4.5 Fast Chat, Guardrail v3, Sonnet
Deep Review. Not bundled: `structured_coach.py`, `specialists/fast_chat.py`,
RAG, affinity, generation, prompt cache.

`models.py` also carries the local citations-as-array RC (`64410dc`) so
flatten no longer advertises `citations: ["array", "null"]`.

**Not changed.** FastAPI/EC2 image; `AGENTCORE_SESSION_GENERATION=2`;
prompt cache OFF; DSQL; RAG; Deep Review `turns=3`. Existing affinity
sessions stay on the microVM version they were created with. New notebooks
get v24.

**Production UI.** Live `ddfc3f4` FastAPI does not project
`hmw_scaffold.available`. Extra `hmw_scaffold_ready` on the wire is ignored
until an EC2 rebuild from `89ccfed` or later. Do not bump generation.

**Validation.** Targeted mock pytest for Fast Chat schema, HMW prompts, prompt
baseline, and first-cycle middleware passed before publish. No paid coaching
turns in this publish. Control-plane confirm: runtime 24 READY, DEFAULT 24
READY, artifact prefix `chatbot_harnessAgent-hmw-scaffold-20260820T142111Z.zip`.

**Next exact action.** Rebuild/redeploy the EC2 app image from `89ccfed` or
later when the HMW card should appear in production. Keep generation **2**
unless you need existing warm sessions off v23. Do not enable prompt cache.

### Prior: local progressive HMW (published as v24)

**HEAD at the local gate:** `89ccfed`. Live AgentCore was still v23 until
the overlay above.

**Behavior.** New notebooks stay clean: welcome only, no HMW card. After
enough qualifying Problem Identification Coaching and a validated
`hmw_scaffold_ready=true` from the existing Fast Chat structured result,
FastAPI projects `hmw_scaffold.available`. Streamlit renders one read-only
card in the chat log immediately after the Coaching response that first
unlocks it (two qualifying PI Coaching turns, and at least two of three
framing signals judged ready). Students type a working
HMW (or equivalent framing) in the existing chat. `hmw_scaffold_ready=true`
with `recommendation=stay` is normal and does not advance. ADVANCE still uses
the existing StageDecision / pending Next / auto-advance path. Leaving
Problem Identification hides the card. Q&A and Deep Review do not count.
Active-branch revision semantics apply. Old assessments omit the field and
default false.

**Authority.** Haiku recommends. FastAPI validates, persists slim assessment
metadata, and derives visibility. The client cannot write the flag.

**Not changed (local HMW work).** AgentCore affinity/generation until v24;
Fast Chat `turns=2`; first-cycle structured output; Deep Review `turns=3`; RAG;
citations schema; recommendation `if/then`; DSQL schema; auth; prompt-cache
config.

**Known residual risk before v24.** Live v23 Haiku did not emit
`hmw_scaffold_ready`. FastAPI treated omit as false.

**Validation (local worktree, $0 AWS).** Ruff on touched Python: passed.
`compileall` passed for `backend`, `ui`, `streamlit_app.py`, `tests`, and
`scripts` excluding pre-existing broken `scripts/load_probe.py`
(`IndentationError`; left unstaged). `git diff --check` clean on this
change. Targeted HMW / Fast Chat schema / first-cycle / prompt-baseline /
quality matrix / workflow / retrieval / Deep Review / revision /
idempotency tests passed. Full mock pytest **1454 collected, passed**,
ignoring `tests/scripts/test_load_probe.py`.

The first uncommitted HMW pass showed the formula whenever the stage was
`problem_identification`, including on an empty notebook. Progressive HMW
replaces that gate. Completion still uses semantic stay/advance, not a regex.

### Prior: citations schema RC (2026-08-20)

**HEAD:** citations schema RC on `Integrate-Bedrock-v2` (`64410dc`).
Composer layout remains `711d4e6`.
**Live app image:** `cde2300-chatbot:ddfc3f4` (unchanged; no EC2 rebuild)
**Live AgentCore at that RC:** DEFAULT → **v23**. Affinity ON. Generation 2.
Prompt cache OFF. The citations-as-array change shipped in the v24 overlay.

**This phase:** Local Fast Chat citations schema release candidate. No
AgentCore publish, no DEFAULT move, no EC2 rebuild, $0 AWS.

**Root cause (proven against strands-agents==1.52.0).** Pydantic
`FastChatTurnOutput.citations` is `list[CitationOutput]` with
`type: array` and a Python default of `[]`, so it is omitted from JSON
Schema `required`. Strands `_process_property` then rewrites every
non-required field to `type: [T, "null"]`. The model-facing tool spec
therefore advertised `citations: ["array", "null"]`. Claude emitted
`citations: null`; Pydantic still rejected it (`Input should be a valid
list`); bounded recovery ran a second Haiku cycle.

**Local fix (later included in v24).** Keep Pydantic rejecting JSON `null`. Do not
normalize `None → []`. Mark `citations` required as `type: array` in
`json_schema_extra` and add the short Field description “Always return an
array. Use [] when no citations are needed.” After Strands flatten the
tool spec is `type: array` and `required` includes `citations`. Python
construction may still omit the field (default `[]`).

**Not changed.** Recommendation `if/then` / `coaching_requires_recommendation`;
first-cycle `tool_choice={"any": {}}`; Fast Chat `turns=2`; Deep Review
`turns=3`; RAG; models; prompts; pedagogy.

**Validation ($0 AWS).** `git diff --check` clean on RC files.
`.venv/bin/ruff check --no-fix . --exclude scripts/load_probe.py` passed
(unrelated dirty `scripts/load_probe.py` is syntax-broken and was excluded).
`compileall` passed. Focused Fast Chat / citation / RAG / Deep Review tests
passed. Full mock pytest **1414 collected, passed**, ignoring
`tests/scripts/test_load_probe.py`. Throwaway `strands-agents==1.52.0`
`pytest --noconftest tests/domain/test_strands_first_cycle_middleware.py`:
**14 passed**.

**Production recommendation at the RC.** Keep DEFAULT → **23** until reviewed.
The citations-as-array change then shipped in the v24 `models.py` overlay
together with `hmw_scaffold_ready`. Do not bump generation. Do not enable
prompt cache.

**Next exact action at the RC.** Publish v24 (done 2026-08-20). Keep
generation 2. Do not enable prompt cache.

**Known residual risk.** Claude can still emit `citations: null` against an
array-only schema; that remains invalid and recovery still runs. Nested
`CitationOutput` optional strings remain `[string, null]` after flatten;
that is not the observed failure.

### Prior live baseline: v23 schema release (2026-08-19)

**HEAD at publish:** `6616e15cff703c70254f7442a75773477b01f22c`
**This phase:** Surgical AgentCore **v23** schema release. Affinity ON.
Generation 2. Prompt cache OFF.

**v23 publish (2026-08-19).** Overlay of live v22 zip + HEAD
`agentcore_runtime/models.py` only. Artifact
`s3://cdk-hnb659fds-assets-355604674280-us-west-2/agentcore-patches/chatbot_harnessAgent-schema-fix-20260819T170837Z.zip`.
Same ARN `NUSCodesignChatbot_chatbot_harnessAgent-6ncEO79sD7`. v22 kept
READY. DEFAULT liveVersion **23** READY (`lastUpdated`
2026-08-19T17:08:56Z).

**Live coaching sample (3 paid Fast Chat turns, dedicated notebook).** New
affinity session `codesign-c33b219f…` (not the v22 Hello session). C1 cold
OTEL boot; C2/C3 warm same `runtimeSessionId`. All three: mode=coaching,
recommendation=stay, stage stayed `problem_identification`, persistence ok,
Deep Review not invoked, `rag_used=false`. CloudWatch: **zero**
`coaching mode requires` / `recommendation=null` events. Cycle 1 still
recovered (`event_loop_cycle_count=2`) because `citations` was `null`
(`Field 'citations': Input should be a valid list`) — **other** bounded
recovery, not the published schema hole.

| | C1 cold | C2 warm | C3 warm |
|---|---:|---:|---:|
| pre-handler (invoke − runtime) | ~5452 ms | **~110 ms** | **~110 ms** |
| `agentcore_invoke_ms` | 13604 | 8347 | 9066 |
| cycles | 2 | 2 | 2 |
| first-cycle applied | true | true | true |
| old coaching+null bug | absent | absent | absent |

C3 set `retrieval_required=true` from the evidence-worded prompt; KB returned
0 validated hits (`rag_used=false`). Do not treat that as a selected-source
RAG run.

**Production recommendation at v23.** Keep DEFAULT → **23**, affinity ON,
generation 2, prompt cache OFF. Do not bump generation. Do not enable prompt
cache. Do not rebuild EC2 for that schema-only change.

**Next exact action at the time of v23.** The citations flatten hole was the
leftover recovery; it shipped in v24 with HMW. Do not start Deep Review on
the v23 validation notebook.

**Session affinity:** Compose `AGENTCORE_SESSION_AFFINITY_ENABLED=true` and
`AGENTCORE_SESSION_GENERATION=2`. Host `.env` still has unused generation
`=3`; do not use it.

### First-cycle hardening publish (2026-08-19): DEFAULT 21 → 22

v21 source (`b81a5b0` zip) had **no** `first_cycle_tool_choice_*` middleware.
HEAD contains it (`bf7bec5` / `e556ad7` / `d7d6f1d`). Live v21 logs also lacked
those fields. `V21_FIRST_CYCLE_HARDENING = ABSENT`.

Published artifact is a **surgical overlay** of live v21 zip + current
`main.py` + current `structured_coach.py` with the `4f5953e` Q&A prompt hunk
reverted. `specialists/fast_chat.py` stayed at v21. Not bundled: RAG, model,
guardrail, Deep Review limits, cache, affinity, generation.

Local: `git diff --check` clean; Ruff passed; `compileall` passed; companion
pytest 147 passed; Strands 1.52.0 throwaway venv 5 first-cycle middleware tests
passed (`--noconftest`).

Validation used a **new untitled notebook** (new `codesign-d0bf0a01…` session)
because existing microVMs stay on the version they were created with. Two paid
Hellos. C1 cold one-cycle; C2 warm reused the same session (pre-handler ~117 ms)
but recovered once (`event_loop_cycle_count=2`) even though
`first_cycle_tool_choice_applied=true`. Compare C2 invoke **4914 ms** to warm
v21 B2 **7225 ms**, not to cold A. RAG off, DSQL unchanged, Deep Review not
invoked. Hello is structural latency only.

**Production recommendation.** Keep DEFAULT → **22**, affinity ON, generation 2,
prompt cache OFF. Do not overfit coaching quality to Hello. Do not bump
generation merely because the runtime version changed.

**C2 recovery cause (2026-08-19, read-only).** Cycle 1 `tool_use` of
`FastChatTurnOutput` failed Pydantic `coaching_requires_recommendation`:
`mode=coaching` with `recommendation=null` (`Field 'root'`). Live v22 JSON
Schema still allows that shape. Local HEAD now rejects it (not published).

### Affinity A/B (2026-08-19): warm session removes ~5.4s pre-handler

Reused the 15:07 stateless Hello as **A**. Enabled affinity only; recreated the
same `ddfc3f4` container. Two paid Hellos on the same KM notebook (RAG off).

| | Stateless A | Affinity B1 (cold) | Affinity B2 (warm) |
|---|---:|---:|---:|
| `runtimeSessionId` | `stateless-1e4d…` | `codesign-bd337c…` | **same as B1** |
| Pre-handler | 5402 ms | 5475 ms | **116 ms** |
| Handler | 5300 ms | 8560 ms (2 cycles) | 7091 ms (2 cycles) |
| Invoke clock | 10725 ms | 14055 ms | 7225 ms |

B2 reused B1’s opaque `codesign-` id. First B2 runtime log was `POST /invocations`
(no OTEL process boot). Pre-handler dropped 97.8% vs A (**excellent**, &lt;500 ms).
B1/B2 each used two model cycles (`end_turn` then `tool_use`); that extra model
time is **not** an affinity effect. DSQL remained the transcript (`rag_used=false`,
history still sent, stage unchanged). Mock tests in
`tests/domain/test_agentcore_session_affinity.py` still pass.

**Production recommendation.** Keep affinity **on** for the Month-1 pilot unless
the operator asks to revert. Idle timeout remains 900 s; after idle, the same
session id may wake a new microVM. This v22 publish kept generation **2** and
used a new notebook so the warm session was not pinned to v21. Do not bump
generation merely to force a new runtime version.

### Streamlit UI TIMING: visible logs + pre-API step spans (no UI optimization)

Live CloudFront already showed the ~14–19s Send delay is **before FastAPI**.
The instrumented `log_ui_timing` helper existed, but Streamlit is a separate
process from uvicorn: `co_design.ui_perf` had no handler, parents were unset,
and Python lastResort is WARNING, so INFO `UI TIMING` never reached
`docker logs`. FastAPI `configure_operational_loggers()` does not run in the
Streamlit process.

**Change:** `configure_ui_perf_logger()` attaches
one idempotent INFO stderr handler to **only** `co_design.ui_perf`. Send now
logs `fragment_to_api_ms`, `pre_api_ms`, plus wall-clock spans for fragment
enter, `st.chat_input`, `sync_composer_layout`, source list, notebook lookup,
inflight user paint, `sync_chat_scroll(mode="send")`, CoachRequest build,
Thinking/`st.status`, and first NDJSON event (`api_to_started_ms` /
`api_to_first_event_ms` / `stream_ms`). Fragment submit architecture is
unchanged. No FastAPI, AgentCore, RAG, Fast Chat, or prompt-cache changes.

**Validation (this worktree, $0 AWS):** `git diff --check` clean; `ruff check .`
passed; `compileall` passed. Targeted pytest passed for
`tests/ui/test_ui_perf_logging.py`, `test_rerun_scope.py`,
`test_chat_scroll.py`, and `test_chat_progress.py`. Full mock pytest passed.
Backend, AgentCore, RAG, and Fast Chat files are unchanged.

**Status:** Deployed as `cde2300-chatbot:ddfc3f4`. Live Hello TIMING is in Docker logs.

Release order: [`PRODUCTION_RELEASE_CHECKLIST.md`](PRODUCTION_RELEASE_CHECKLIST.md)
(SOURCE CODE READY → EC2 IMAGE DEPLOYED; AgentCore DEFAULT stays on the
existing liveVersion). Architecture: [`LOCAL_DEMO_IMPLEMENTATION.md`](LOCAL_DEMO_IMPLEMENTATION.md).

This file’s **CURRENT** sections are the operator runbook. Everything under
**HISTORICAL INVESTIGATION** is a dated archive and is not current.

### Prior on this branch: Deep Review adversarial workflow regressions

Product behavior is unchanged from `1e1e069` (frozen `reviewed_stage_id`,
latest-snapshot-only Review-tab merge). That phase added three adversarial
tests and did not redesign Deep Review.


### Prior on this branch: Deep Review Review-tab projection (`1e1e069`)

A successful Deep Review already persisted `strengths`, `areas_to_develop`,
`synthesis`/`summary`, `facione_scores`, and `working_conclusion` in durable
`deep_review_snapshot`. Summary, Facione, and working conclusion updated in
the Review tab; Strengths and Areas for improvement did not, because
`learning_review()` built those sections only from incremental assistant
`review_strengths` / `review_improvements`.

**Change (committed):** persist `reviewed_stage_id` (enqueue-time Thinking
Path stage) on the snapshot. `learning_review()` still builds stage history
from messages, then merges the latest snapshot's strengths/areas onto that
frozen stage (Deep Review items first, case-insensitive dedupe). Old
snapshots without a valid stage id skip the merge instead of attaching to
the current stage.

### Prior on this branch: catalog sidecar hide (`18c288e`, not deployed)

**Committed HEAD:** `18c288e`. Live RAG remains on the previous image until
this patch is built and deployed.

Live RAG is working (sidecars ingested, equals/`in` Retrieve validated,
CloudFront Week 1 Q&A cited). After sidecar upload the Sources panel listed
those indexing artifacts because `Path(filename).suffix == ".json"` is a
supported upload suffix.

**Change:** `backend/sources/library.py` skips
`is_metadata_sidecar_key(...)` **before** suffix eligibility and
`max_lecture_notes` in the shared S3 catalog, local fingerprint, and local
lecture-notes sync. Personal `.json` uploads are unchanged. RAG Retrieve,
filters, citations, and S3 sidecars are unchanged.

**Expected after deploy:** Lecture Notes **7**, Readings **3**. The 10
sidecars stay in S3 for Bedrock. They must not appear as locked sources.

### Prior worktree note (superseded for this follow-up)

The following release-hardening write-up was prepared on earlier uncommitted
work that is now at `d7d6f1d`. Keep it for operator context. Do not treat it
as the current catalog-sidecar diff.

### Release hardening (this worktree): observability + fail-open, not a redesign

Prepared on `Integrate-Bedrock-v2` on top of `bfb1cba`. **AWS cost $0.** No
Bedrock model, AgentCore, Knowledge Base, DSQL, S3, or Cognito calls. No
deploy, no AgentCore publish, no new runtime ARN, no production worker-count
change. Fast Chat / Deep Review models unchanged. RAG/citation/coaching
prompts unchanged.

- Fast Chat still: FastAPI → **one** `InvokeAgentRuntime` → `role=fast_chat` →
  Strands `Agent(tools=[])` → first cycle may force `tool_choice={"any": {}}`
  → normally one Haiku generation → `turns=2` remains as bounded recovery.
- **Applied telemetry:** `first_cycle_tool_choice_installed` still means
  middleware **registered**. New `first_cycle_tool_choice_applied` is true
  only when cycle 1 actually changed an unset `tool_choice` to `{"any": {}}`.
  Optional allow-listed `first_cycle_tool_choice_decision`. Omit both applied
  fields for Deep Review. Never logs tool schemas, prompts, or student text.
- **Tool identity:** Strands 1.52.0 specs are Converse-shaped dicts whose
  `name` is the Pydantic class (`FastChatTurnOutput` in prod, test doubles in
  fake-model tests). No brittle name match. Invariant is `Agent(tools=[])` plus
  exactly one spec; multiple specs are not forced.
- **Fail-open:** middleware unavailable → `installed=false`,
  `applied=false` / `middleware_unavailable`, Fast Chat still proceeds,
  `turns=2` recovery remains.
- Deep Review: no first-cycle middleware; `DEEP_REVIEW_INVOKE_LIMITS` still
  `{"turns": 3}`; Sonnet / job / eligibility / persistence unchanged.
- Load probe: snapshot/restore now includes `app_env` and
  `course_material_sync_enabled`; runtime force sets development + sync off.
  `rss_peak_kb` kept; `process_max_rss_kb` is the same process-lifetime
  `ru_maxrss` high-water (not per-scenario incremental RSS).

#### Validation (this worktree, $0 AWS)

- `git diff --check` clean; `ruff check .` passed (added
  `scripts/load_probe.py` E402 per-file ignore for the env-bootstrap import
  order; that pattern was already required).
- `compileall` passed (`backend`, `ui`, `streamlit_app.py`, `tests`,
  `scripts`, `agentcore_runtime`).
- Companion `.venv` mock pytest: **1369 collected, exit 0** (Strands
  integration module skipped; companion pytest does not install
  `strands-agents`).
- Throwaway venv with `agentcore_runtime/requirements.txt`
  (`strands-agents==1.52.0`, `bedrock-agentcore==1.21.0`,
  `pydantic==2.13.4`): diagnostic
  `check_agentcore_runtime_dependencies.py` printed
  `agentcore_runtime_dependency_check=ok`; **26 passed**
  (`test_strands_first_cycle_middleware.py` 5 +
  `test_first_cycle_structured_output.py` 21).
- GitHub Actions for this uncommitted worktree: **not independently proven**.

**Next exact action.** Do **not** publish AgentCore or rebuild EC2 until
authorised. After authorisation follow the checklist: commit/push → CI → new
version on the **existing** runtime ARN → wait READY → move DEFAULT → bump
`AGENTCORE_SESSION_GENERATION` → ARM64 image from the **same SHA** → deploy →
`/api/v1/ready` → small controlled live validation. Measure
`event_loop_cycle_count`, `first_cycle_tool_choice_installed`,
`first_cycle_tool_choice_applied`, and `UI TIMING fragment_to_api_ms`.

### Local $0 capacity validation (mock/fake only)

Load-probe work **is committed and pushed** at
`bfb1cbacf9a097ee2ac2e8fc2c80fe68810f586a`. This worktree only hardens
snapshot/restore, RSS naming, and operator docs. **AWS cost $0.** No Bedrock
model, AgentCore, Knowledge Base, DSQL, S3, or Cognito calls. No deploy, no
AgentCore publish, no production worker-count change.

[`../scripts/load_probe.py`](../scripts/load_probe.py): fake-slow
`DeterministicCoachProvider.assess` (restored on exit), real
`BedrockKnowledgeBaseRetriever` with only `client.retrieve` faked, thread/RSS
sampler, JSON capacity rows. Pytest uses tiny delays. Operator matrix:
[`operations/LOAD_PROBE.md`](operations/LOAD_PROBE.md).

The probe raises RPM to 10_000 so it is **not** testing production
`COACH_REQUESTS_PER_MINUTE=8`. That cap is **per authenticated user**, not a
class-wide 8-RPM ceiling. Ninety distinct students each sending one request
can pass the per-user RPM rule; class burst ceilings are global concurrency
(`MAX_CONCURRENT_MODEL_CALLS`), the AnyIO thread limiter, AgentCore, and KB
Retrieve capacity.

**What this proves:** FastAPI + owner isolation + notebook/user/global caps +
SQLite persist can accept 120 concurrent mock turns and 90 concurrent 10s
fake-slow turns with 0 unexpected 429s, 0 ownership leaks, 1-call
idempotency replay, and no partial assistant turns. The Retrieve pool
fail-closes at `workers` (default 4): 90 concurrent fake Retrieves → 4 ok +
86 `capacity_exhausted`, no queueing, slots recover, foreign-bucket hits
return no evidence.

**What this does not prove:** AgentCore/Haiku P95, live KB Retrieve, DSQL OCC,
Cognito, Uvicorn-on-ARM64-2GB, or EC2 class capacity. Mock/fake-sleep latency
is not model latency. Docker 2 CPU / 2 GB envelope was **not run** (Docker
engine unavailable on this host).

**Do not raise** `KNOWLEDGE_BASE_RETRIEVE_EXECUTOR_WORKERS` from 4 on this
evidence. Per-request `ThreadPoolExecutor(max_workers=2)` stays (option A);
90×10s peaked ~431 Python threads / ~258 MiB process-lifetime RSS locally,
not proven harmful.

**Next exact live AWS action (operator-approved only):** staged 2 → 5 → 10 →
25 real students on the deployed image/runtime. Count live
`capacity_exhausted`, AgentCore P95, DSQL errors, and RSS. Do not open 90
live students from this mock probe.

**Always-visible Deep Review button:** Review always shows **Start Deep Review**. Locked/unlocked state and the `{n}/{interval}` caption are derived from persisted `coaching_turns_since_deep_review` and `DEEP_REVIEW_INTERVAL_TURNS`. Eligibility remains FastAPI/DSQL (`explicit_deep_review_available`); Streamlit does not keep a second counter. Ineligible `POST /api/v1/threads/{id}/deep-review` still returns 400. The Review spinner follows persisted `deep_review_job` status via a 2s fragment poll, not a Streamlit session flag. This UI/API change is not assumed to be in the live EC2 image.

**Divergence vs `main`:** history-only ancestry. `git log --no-merges origin/Integrate-Bedrock..origin/main` is empty, and no file exists on `main` that is missing from this branch. `main`’s extra commits are merge commits of PRs #7–#12. This branch is strictly ahead in content.

**Last documented live cutover (2026-08-17, historical):** same AgentCore ARN, version **21** on DEFAULT; EC2 app image `cde2300-chatbot:b81a5b0`. Compose / host pin `AGENTCORE_SESSION_GENERATION=2`. **Re-query before release.**




### Fast Chat latency: fragment reconcile + Fast-Chat-only first-cycle force

Prepared on `Integrate-Bedrock-v2` after `bf7bec5`. **Not published to
AgentCore. Not deployed to EC2.** Prompt cache remains disabled. Canonical
stage/shared coaching prompts are unchanged. RAG filters/timeouts/chunk
caps are unchanged.

#### What this follow-up changes

- Streamlit: keep the composer `@st.fragment` so Send starts FastAPI without
  rebuilding Journey/Sources/history first. After a successful persist,
  always `rerun_app()` so completed turns live in persisted `chat_log`,
  not only inside the fragment (consecutive Q&A cannot vanish).
- Runtime: first-cycle `tool_choice={"any": {}}` is Fast Chat only. Deep
  Review is not modified. Unexpected multiple tool specs are not forced.
  `first_cycle_tool_choice_installed` is stamped true/false. `turns=2` kept.
  Applied telemetry (`first_cycle_tool_choice_applied` / allow-listed
  decision) is in the later uncommitted hardening worktree, not in this
  fragment SHA.
- Observability: `fragment_to_api_ms` from fragment start to HTTP; runtime
  flag copied onto `coach_turn_perf`.
- Tests: Strands fake-model integration (skipped without strands); A–T
  quality matrix inventory (no invented live scores).

#### Production measurements that motivated this phase (heavy notebook)

Taken on the live CloudFront path before these patches. Approximate:

| Case | UI pre-API | FastAPI | AgentCore | cycles | persist |
|---|---:|---:|---:|---:|---:|
| Hello | ~3.84 s | ~10.9–12.7 s | ~9.6–12.2 s | 1 | ~0.2–0.3 s |
| Coaching | (same order) | ~14.1 s | ~13.4 s | 2 | ~0.2–0.3 s |
| Evidence-gap Q&A | — | ~0.98 s | 0 | n/a | — |

Empty filtered KB Retrieve ~0.51 s. DSQL ~0.26–0.46 s. Prompt cache off.
EC2 was not CPU-bound. Fresh-notebook Hello was **not** measured live.

#### Cycle-2 root cause (Strands 1.52.0 wheel, not a guess)

Inside **one** `invoke_agent_runtime`, `Agent.invoke_async(..., structured_output_model=FastChatTurnOutput, limits={"turns": 2})` starts with voluntary tool use (`tool_choice` unset). If cycle 1 returns `stop_reason=end_turn` without the structured-output tool, Strands appends `Please use the output tool now.`, `set_forced_mode()` (`tool_choice={"any": {}}`), and recurses. Hello often used the tool on cycle 1; Socratic Coaching more often wrote prose first.

`invoke_async` in 1.52.0 has **no** first-cycle `tool_choice` argument. The documented seam first-party plugins use is `InvokeModelStage.Input` on `agent._middleware_registry`.

#### Historical notes from the first latency patch

Cycle-2 cause and production timings are above. Prompt cache stays disabled.
Duplicate notebook load and DSQL pooling were not changed. Guardrails, RAG
validation, and Deep Review architecture were not changed.

#### Validation (this follow-up)

Evidence from this worktree on top of `bf7bec5` (not committed):

- `ruff check` passed (full repo).
- `compileall` passed (`backend`, `ui`, `streamlit_app.py`, `tests`, `scripts`, `agentcore_runtime`).
- Companion `.venv` mock pytest: **1353 collected, exit 0**. The Strands
  integration module is skipped here because companion pytest does not
  install `strands-agents`.
- Throwaway venv with `agentcore_runtime/requirements.txt`
  (`strands-agents==1.52.0`): **19 passed**
  (`test_strands_first_cycle_middleware.py` 5 +
  `test_first_cycle_structured_output.py` 14). Diagnostic
  `check_agentcore_runtime_dependencies.py` printed
  `agentcore_runtime_dependency_check=ok`.
- Targeted quality/RAG/stage/Deep Review run: **180 passed**
  (`test_qa_grounding`, `test_bedrock_retrieve`, `test_citation_resolution`,
  `test_deep_review_execution`, `http/test_deep_review`,
  `test_fast_chat_one_call`, `test_coaching_prompt_baseline`,
  `test_security_invariants`, `test_mode_classification`,
  `test_structured_output_limits`, `test_review_agent`).
- Informational mock benchmark only (not AgentCore): fresh submit_ms ~510
  (cold SQLite), medium 13.3, heavy 11.0. `agentcore_invokes=0`.

Cycle=1 on live Haiku Coaching remains **LIVE TRACE REQUIRED** after an
authorised AgentCore republish. Fragment `pre_api_ms` improvement is
architectural; production click-to-API is unproven. Live A–T quality
scores were **not** invented.

#### Next exact action

Do **not** publish AgentCore or rebuild EC2 until authorised. After
authorisation: publish runtime with Fast-Chat-only middleware, bump
`AGENTCORE_SESSION_GENERATION`, recreate the app image, then measure Fresh
and Heavy Hello/Coaching/Q&A with `event_loop_cycle_count`,
`first_cycle_tool_choice_installed`, and `UI TIMING fragment_to_api_ms`.

### Week 1 RAG, Q&A stay, and latency

On `Integrate-Bedrock` after `e7132ff`. **Not deployed.** Chat overlay/composer layout is in `e7132ff`. No AgentCore runtime republish (DEFAULT remains liveVersion **21**). Paid generation was not used. One capped live Retrieve was approved; this laptop could not execute it (`KNOWLEDGE_BASE_ID` empty). Do not flip production off `required` filters.

**Live / local probe (2026-08-18).** Dry-run `scripts/diagnostics/test_course_retrieval.py --query "what does week 1 material cover" --source "Week 1 Introduction to innovation v3.pdf"`: `metadata_filter_mode=required`, `filter_kind=equals`, `course_material_id=lecture_week_1_introduction_to_innovation_v3`, object key `course/lectureNotes/Week 1 Introduction to innovation v3.pdf`, expanded query `what does week 1 material cover lecture 1`. Local `KNOWLEDGE_BASE_ID=(empty)` so Retrieve was not called (`config_missing` / unavailable). `check_course_kb_metadata.py --dry-run`: `sidecar_missing_count=10` / `local_sidecar_ok=false`, including the Week 1 sidecar. Operator path remains [`KB_REQUIRED_MODE_RUNBOOK.md`](KB_REQUIRED_MODE_RUNBOOK.md). Production student trace for this utterance was `COURSE_RETRIEVAL_UNAVAILABLE_CONTEXT` (`course_retrieval_status=unavailable`), not empty-validated-hits.

**Application changes in this worktree**

- Session narrowing among **already-selected** course sources (`prefer_session_matching_sources`); fail-open if none match. KB query text stays the student question plus week/lecture alias.
- Secret-safe KB perf: `kb_sdk_ms`, `kb_validate_ms`, drop counts (`bucket_mismatch` / `key_mismatch` / `empty_text`). Optional `CO_DESIGN_RAG_DEBUG` (default false) logs query length, selected titles, top scores — never excerpts.
- Q&A: `RUNTIME_HINT_QA` takes precedence; composer omits Strict/stay-advance language on `expected_response_mode=qa`; prior assistant / memory are continuity only. Server-authored `QA_EVIDENCE_GAP_RESPONSE` skips AgentCore when Q&A + selected sources + no validated chunks (image-only Q&A still invokes). Fast Chat assembly: Q&A runtime rules override stage pedagogy (needs a **new AgentCore runtime version** for the success path).
- Latency: `auth_context_ms` copied onto `/coach/turn`; TIMING now includes `auth`, `kb_sdk`, `kb_validate`; `get_messages` ∥ `list_visible_sources` after notebook load. No region/retry/threshold change. Duplicate notebook load in `_submit_body` vs `_prepare` was **not** removed.
- First-prompt duplicate: `set_coach_turn_streaming()` writes session state and an in-process session-id set so the prior run’s Sources `run_every` fragment can skip `rerun_app()` while `handle_prompt` is blocked (chat renders before Sources).
- Inflight overlap: `chat_log` no longer shares `height: 100%` with studio scroll. Occupied inflight uses `overflow: hidden`, `height: auto`, and `min-height: min-content` so a long pending bubble takes in-flow height under history instead of painting over the last Coach reply; empty inflight still collapses to `max-height: 0`.
- Composer autogrow: paste/wrap measures `height: auto` and capture-phase input listeners grow the composer to the existing 5-row cap at any width.

**Validation.** Focused UI: `tests/ui/test_streamlit_ui.py` for composer autogrow; `tests/ui/test_rerun_scope.py`, `tests/ui/test_chat_progress.py`, `tests/test_architecture_contracts.py` for the remount guard; `tests/ui/test_theme_styles.py` for inflight-overlap CSS (contain long pending bubbles). `compileall` + ruff on touched files passed. Full mock pytest **1323 passed** before these UI patches; re-run the suite before handoff. No live Bedrock/AgentCore from pytest.

**Next exact action.** Operator: upload Week 1 (and other) sidecars and run ingest per the runbook, then one capped live Retrieve on EC2/production credentials. Publish a new AgentCore runtime only after FastAPI lands, and bump `AGENTCORE_SESSION_GENERATION`. Measure one Week 1 coach TIMING line in production logs before any further DSQL pooling.

### What is committed on this SHA

Committed application/runtime (not an uncommitted worktree):

- Fast Chat: one FastAPI `InvokeAgentRuntime` per normal turn; slim `FastChatTurnOutput` (`fast_chat_turn_v1`); Haiku 4.5; `runtime_context.specialist=fast_chat`.
- Deep Review: explicit `POST /api/v1/threads/{thread_id}/deep-review` enqueues a
  background Sonnet 4.6 job and returns `{ review_id, status, reviewed_revision }`
  immediately. `GET` the same path for job status (snapshot when completed).
  Coaching `/coach/turn` can overlap. The browser cannot pick a privileged
  specialist on `/coach/turn`.
- Course RAG: shared `course/` objects → Bedrock **MANAGED** Knowledge Base → validated `Retrieve` mapped to `[S#]`. Student uploads stay on local lexical retrieval.
- Student-source hydration: precomputed `derived/chunks.v1.json` plus an in-process LRU; missing/invalid artifacts fall back to chunking extracted text.
- Auth/persistence: Cognito owner isolation; Aurora DSQL is the only durable transcript; S3 for objects; atomic persist; append-only conversation revisions; durable idempotency lease.
- Month-1 production pilot in [`../compose.prod.yaml`](../compose.prod.yaml): `AUTO_ADVANCE_STAGES=true`, `STUDENT_STAGE_SELECTION=false` (coach ADVANCE auto-applies; no student Next; no Journey stage picker). Intentional. Note the three stage-config sources disagree on purpose, so quote the right one: the **code** default is confirmation-gated (`backend/settings.py` `AUTO_ADVANCE_STAGES` → `False`), while **both** `.env.example` (`AUTO_ADVANCE_STAGES=true`) and production Compose auto-apply. A local demo that copies `.env.example` therefore auto-advances; only a run with no `.env` value is confirmation-gated.
- Production runtime pin (Compose): `MODEL_PROVIDER=agentcore`, `AGENTCORE_QUALIFIER=DEFAULT` (currently liveVersion **21**, slim `fast_chat`), `AGENTCORE_SESSION_GENERATION=2`, `GUARDRAIL_VERSION=3`, `KNOWLEDGE_BASE_TYPE=MANAGED`, `DATABASE_PROVIDER=dsql`, `FILE_STORAGE_PROVIDER=s3`. Topology: one EC2, one container, one Uvicorn worker, Caddy behind CloudFront.

### What CI actually proves

Three workflows. [`../.github/workflows/mock-ci.yml`](../.github/workflows/mock-ci.yml)
is the correctness gate and the only one that should be a required check:

| Job | Gates |
|---|---|
| `mock-suite` | `ruff check`; shell syntax (`start.sh`, `build.sh`, `start_prod.sh`, `deploy_ecr.sh`, `browser_e2e_smoke.sh`); `docker compose` + `compose.prod.yaml` + Caddy validate; `compileall` (`backend`, `ui`, `streamlit_app.py`, `tests`, `scripts`, `agentcore_runtime`); production-config tests; idempotency + ownership + production-critical-path tests; **complete mock pytest**; Docker image build **on push only** (`co-design:ci-<12-char-sha>`). |
| `agentcore-runtime-compatibility` | `pip install -r agentcore_runtime/requirements.txt`; `scripts/diagnostics/check_agentcore_runtime_dependencies.py`; compile `agentcore_runtime`; pytest `test_strands_first_cycle_middleware.py` + `test_first_cycle_structured_output.py` with the pinned Strands wheel. Companion pytest does **not** install Strands. |

Two supply-chain workflows report but must **not** become required checks:
[`dependency-audit.yml`](../.github/workflows/dependency-audit.yml) (pip-audit,
path-filtered to requirements files, fail-closed) and
[`codeql.yml`](../.github/workflows/codeql.yml) (Python, `main` only). Both are
filtered, so on a branch or PR that does not touch their paths they are skipped
rather than passing. A required check that is skipped blocks merges in GitHub,
so mark only `mock-ci` jobs required. [`dependabot.yml`](../.github/dependabot.yml)
opens grouped weekly pip / actions / docker PRs.

### What is not live-validated

CI is **mock-only**. It does not prove live AgentCore, Bedrock Converse, Knowledge Base `Retrieve`, DSQL, S3, Cognito, or CloudFront. Passing mock pytest is not a production smoke.

This hardening worktree did not invoke AWS. A capped isolated Fast Chat invoke (`student_message=testing`, no DSQL write) on DEFAULT **v21** was historical (prior session). Deep Review, Cognito login, and RAG were not re-run here.

### Deployment impact of this tip

This worktree is **not live**. Query AgentCore DEFAULT `liveVersion` and the
running EC2 image before any cutover. Last documented live app image was
`cde2300-chatbot:b81a5b0` (label/revision `b81a5b09ce622889f60fdcd743c23d7845eb9ee8`)
with host `AGENTCORE_SESSION_GENERATION=2` and rollback image
`cde2300-chatbot:2386d65`. Those facts can be stale.

- **EC2 / container:** rebuild from the **same git SHA** as the authorised
  source after CI. Do not use `latest`. Do not assume the current host image
  matches this worktree.
- **AgentCore:** publish a **new version** to the **existing** runtime ARN
  (`NUSCodesignChatbot_chatbot_harnessAgent-6ncEO79sD7` is the last documented
  id; confirm on the host). Wait until READY, then move DEFAULT. Do **not**
  create a new runtime ARN. Isolated `"testing"` invoke on last documented
  DEFAULT **v21** is historical, not this worktree.
- **Console:** no new Cognito callback, bucket, or Guardrail version (stay on
  version **3** on both FastAPI Compose and the runtime).
- **DSQL:** no new DDL in this worktree. Confirm the cluster already has
  revision/idempotency columns. Never run `init_dsql.py` at app startup or as
  `co_design_app`.
- **S3:** no new bucket. User objects under `users/`; course objects under
  `course/` only.

## CURRENT ARCHITECTURE

Authoritative layering remains [`LOCAL_DEMO_IMPLEMENTATION.md`](LOCAL_DEMO_IMPLEMENTATION.md). Production generation is AgentCore; FastAPI still owns identity, RAG authorization, transcript, and stage mutation.

**Fast Chat.** One AgentCore invoke per normal student turn. Haiku returns slim `FastChatTurnOutput`: `mode` (`coaching` \| `qa`), `response_text`, optional stay/advance `recommendation`, citations, `needs_source_retrieval`. No per-turn router, incremental review, or automatic Sonnet. Fast Chat cycle 1 sets `tool_choice={"any": {}}` via Strands 1.52.0 `InvokeModelStage.Input` when exactly one structured-output tool is present. Deep Review is not modified by that force. Event-loop recovery inside that one Fast Chat invoke remains capped at `FAST_CHAT_INVOKE_LIMITS={"turns": 2}`. Do not set `turns=1` while first-cycle output can fail. `first_cycle_tool_choice_installed` is true only when the middleware registered. `first_cycle_tool_choice_applied` is true only when cycle 1 actually changed an unset `tool_choice` to `{"any": {}}`. Omit applied/installed for Deep Review.

**Deep Review.** Separate HTTP route `POST /api/v1/threads/{thread_id}/deep-review`. Server-owned eligibility, Sonnet 4.6, counter, snapshot, idempotency. Event-loop cap `{"turns": 3}`. Not on `/coach/turn`. The latest successful snapshot is the Review-tab source for summary, Facione scores, working conclusion, and merged strengths / areas-to-develop. Snapshot strengths and areas are merged onto the frozen `reviewed_stage_id` (enqueue-time stage), not the student's stage at completion or render. Incremental Haiku `review_strengths` / `review_improvements` remain in message history. Failed jobs do not replace the snapshot.

**Course RAG.** Locked Lecture Notes/Readings are virtual catalog rows (no local extracted text). Evidence comes from Bedrock **MANAGED** `Retrieve` with `course_material_id` metadata filters when configured, then bucket/object-key validation onto request-local `[S#]`. Details: [`RAG_ARCHITECTURE.md`](RAG_ARCHITECTURE.md) and [`KB_REQUIRED_MODE_RUNBOOK.md`](KB_REQUIRED_MODE_RUNBOOK.md). AgentCore specialists have `tools=[]` (no KB search).

**Student source retrieval.** Private notebook sources only. FastAPI hydrates selected textual sources from `derived/chunks.v1.json` when valid; otherwise chunks `derived/extracted.txt` with the local lexical chunker (`local_lexical_v1`, ~1,800 / 220). In-process LRU is keyed by server-built object key + content digest. Course/virtual rows never become fake local chunks.

**Auth / persistence.** Cognito is the browser session. DSQL `messages` is the only durable transcript (no AgentCore Memory, DynamoDB, or JSON sidecar). S3 holds user uploads and shared course bytes. Persist is atomic with the idempotency lease. User-message Edit creates an append-only conversation revision; `get_messages` returns the active branch.

**Month-1 stage policy.** Production Compose auto-applies coach ADVANCE. Only the
`backend/settings.py` code default is confirmation-gated; `.env.example` ships
`AUTO_ADVANCE_STAGES=true`, so a demo started from a copied example file
auto-advances too.

## CURRENT PERFORMANCE WORK

**Source hydration / prechunking / cache.** Upload/ingest writes disposable `derived/chunks.v1.json`. Coach turns hydrate selected student sources once per request (`hydrate_selected_retrieval_sources`); RAG fallback does not re-GET extracted text when the snapshot already has chunks. Byte-bounded LRU: `STUDENT_SOURCE_CHUNK_CACHE_MAX_BYTES` (default 32 MiB). Offline SQLite backfill exists (`scripts/backfill_source_chunks.py`) and must not be run against production.

**Retry bounds (current code, not historical `max_attempts` Botocore wording).**

- Botocore client config uses **`total_max_attempts`** (inclusive of the first call). Legacy `retries={"max_attempts": N}` is normalised to **N+1** attempts and is not used. FastAPI AgentCore/Bedrock/harness clients set `total_max_attempts = max_retries + 1` with production `AGENTCORE_MAX_RETRIES=0` → one read-timeout window. Runtime Converse (`agentcore_runtime/model.py`) pins `total_max_attempts=1` so Strands `ModelRetryStrategy` is the only Converse retry layer. KB Retrieve also uses `total_max_attempts=1`. DSQL OCC retries are application-level `max_attempts` in `backend/persistence/dsql_connection.py`, not Botocore.
- Strands `ModelRetryStrategy` (distinct from Botocore): Haiku roles `max_attempts=2` (1s/4s); Deep Review `max_attempts=3` (2s/16s). New strategy instance per Agent.
- Application RAG fallback: at most one extra retrieve + one extra Fast Chat invoke when the gate skipped retrieval and Haiku sets `needs_source_retrieval`. First result is not persisted. `FAST_CHAT_MAX_PROVIDER_INVOCATIONS_PER_TURN=2`.
- Fast Chat event-loop: `FAST_CHAT_INVOKE_LIMITS={"turns": 2}` plus first-cycle
  `tool_choice={"any": {}}` so recovery is not the normal Coaching path.

**Cycle telemetry.** When Strands metrics expose it, the runtime copies `event_loop_cycle_count` onto the payload; FastAPI records it on privacy-safe `coach_turn_perf` JSON. Absent metrics stay unset (not invented). Grep-friendly `TIMING` lines (`auth`, `student_state`, `memory`, `retrieval`, `kb_sdk`, `kb_validate`, `context_build`, `agent`, `persistence`, `TOTAL`) are seconds on logger `co_design.turn_perf`. The JSON event also records `hydrate_total_ms` and `qa_evidence_gap_authored`.

**KB Retrieve latency.** Default wall-clock timeout 10s (`KNOWLEDGE_BASE_RETRIEVE_TIMEOUT_SECONDS`); shared executor; excess calls fail closed (`capacity_exhausted`) rather than queueing.

### Session affinity and runtime model provenance

**AgentCore compute affinity (default OFF).** `AGENTCORE_SESSION_AFFINITY_ENABLED`
(default `false`) and `AGENTCORE_SESSION_GENERATION` (default `1`) are the only
controls. When disabled — the shipped default — every invoke still gets a fresh
`stateless-<uuid4hex>` id, byte-identical to prior behaviour. When enabled,
`backend/agentcore_provider.py::_runtime_session_id` derives an opaque
`codesign-<sha256 hex>` from owner id, notebook id, role, and generation, so a
returning student can land on a warm microVM. Properties that matter:

- The id is a one-way digest. Raw owner or notebook ids are never placed in the
  session id and the id itself is never logged
  (`tests/domain/test_security_invariants.py`).
- Role is part of the digest: Deep Review uses `review_deep`, normal chat uses
  `fast_chat`, so a privileged review cannot land on a Fast Chat session.
- Missing or blank identity fails **open** to a unique stateless id rather than
  collapsing distinct students onto a shared session.
- Affinity is a **compute** optimization only. DSQL remains the sole durable
  transcript and the bounded history is still sent on every turn; nothing reads
  state back out of AgentCore. Bump `AGENTCORE_SESSION_GENERATION` whenever new
  runtime code assets are published so clients cannot stay pinned to a warm
  microVM running the previous build.

**Runtime model provenance.** `agentcore_runtime/model.py::safe_response_provenance()`
reports what the runtime actually loaded; `structured_coach.py` and `main.py`
attach it beside the cycle/cache telemetry. FastAPI parses it in
`backend/agentcore_provider.py` and allow-lists `runtime_model_role`,
`runtime_model_provider`, `runtime_model_id`, `runtime_model_region`, and
`runtime_strands_agents` in `backend/turn_perf.py`. Production logs therefore
carry the **runtime-reported, FastAPI-sanitized** model instead of echoing the
FastAPI-configured value. Absent telemetry stays unset; there is no fallback to
the configured model, so a missing field is visible rather than silently
plausible. This is provenance, **not attestation**: the runtime self-reports and
FastAPI only bounds the value (80 characters, restricted charset), so a
compromised runtime could still report a plausible-looking model id.

### Message ordering correctness

`persist_coach_turn` previously stamped its user and assistant rows with two
back-to-back `utc_now()` calls. Message reads order by `created_at ASC, id ASC`,
and `id` is a random UUID4, so whenever both rows landed in the same microsecond
the tiebreaker was effectively a coin flip and an assistant reply could sort
**before** the student message that produced it. That corrupted transcript
display order and the bounded history handed to the model. The assistant stamp
now comes from `utc_now_after(user_created_at)`
(`backend/persistence/store/contracts.py`), which guarantees a strictly later
value. Regression coverage freezes the clock so the collision is deterministic
rather than timing-dependent (`tests/persistence/test_message_ordering.py`).

## HISTORICAL INVESTIGATION

> **Not the current runbook.** Entries below describe the repository, CI, and
> production state **at the time each phase was written**. They are preserved
> for investigation (traces, retry analysis, publish notes). Do not treat SHA
> claims, "uncommitted" banners, Botocore `max_attempts` wording, liveVersion
> numbers, or "next exact action" lines here as current operator instructions.
> For current HEAD, CI, and deploy impact, use **CURRENT STATUS** above and
> [`PRODUCTION_RELEASE_CHECKLIST.md`](PRODUCTION_RELEASE_CHECKLIST.md).

### Current phase — Background Deep Review jobs (non-blocking coaching + poll UI)

**Code is local on `Integrate-Bedrock` and is not committed or deployed.** No
AgentCore publish, EC2 deploy, or live AWS inference was performed. Fast Chat,
RAG, STAY/ADVANCE, Facione, and CLEAR are unchanged. Live app image remains
`cde2300-chatbot:b81a5b0`.

#### What this phase changed

1. **Non-blocking enqueue.** `POST /api/v1/threads/{thread_id}/deep-review`
   persists `deep_review_job` on notebook `settings_text` and returns
   `{ review_id, status, reviewed_revision }` immediately. A process-local
   `ThreadPoolExecutor` (one Uvicorn worker) runs Sonnet against
   `get_messages_at_revision` plus frozen message/source ids. Completion writes
   `deep_review_snapshot`, job `completed`, and counter `0` without inserting
   transcript rows or requiring a matching live stage/revision.
2. **Coaching overlap.** Deep Review no longer takes
   `MAX_ACTIVE_COACH_REQUESTS_PER_NOTEBOOK`. Chat keeps notebook=1.
   `DEEP_REVIEW_MAX_CONCURRENT` (default 8) is a separate semaphore.
3. **GET status + stale fail-closed.** `GET` the same path returns the job
   (snapshot when completed). Queued/running jobs older than
   `DEEP_REVIEW_JOB_TIMEOUT_SECONDS` (default 180) become `failed` /
   `review_timeout`. Duplicate POST while queued/running reuses `review_id`.
4. **Review UI poll.** Streamlit fragments poll GET every 2s only while
   queued/running. The spinner follows backend job status. Chat stays enabled.
   Browser refresh recovers from the job record. Failed jobs keep the counter
   and show the existing safe error.

#### Files

- `backend/persistence/store/contracts.py` — `deep_review_job` settings key
- `backend/specialists/review_orchestration.py` — job parse/stale helpers
- `backend/student_store.py` — start/mark/complete/fail settings writers
- `backend/persistence/dsql_student_store.py` — OCC coverage for those writers
- `backend/domain.py`, `backend/settings.py`, `backend/rate_limit.py`
- `backend/coaching/deep_review_jobs.py`, `backend/coaching/execution.py`
- `backend/http/app.py`, `backend/api_client.py`, `ui/services/runtime.py`
- `backend/agentcore_provider.py` — optional affinity salt with `review_id`
- `ui/panels/studio.py` — stable vs 2s polling fragments
- `tests/conftest.py` — reset in-process review executor between tests
- `tests/http/test_deep_review.py`, `tests/domain/test_deep_review_execution.py`,
  `tests/ui/test_deep_review_control.py`, `tests/ui/test_chat_progress.py`,
  `tests/test_architecture_contracts.py`, `tests/domain/test_review_agent.py`
- `docs/IMPLEMENTATION_STATUS.md` — this phase

#### Validation

- `ruff check` on touched Python files: passed.
- `python -m compileall -q backend ui streamlit_app.py tests scripts`: passed.
- Targeted: `tests/domain/test_deep_review_execution.py`,
  `tests/http/test_deep_review.py`, `tests/ui/test_deep_review_control.py`,
  `tests/ui/test_chat_progress.py`, `tests/test_architecture_contracts.py`,
  `tests/domain/test_review_agent.py`: passed.
- Full mock pytest: 1312 passed.
- No live AWS, AgentCore, Bedrock, DSQL, S3, or KB calls.

#### Migration / compatibility / rollback

No DSQL DDL. New settings key is ignored by older code and dropped only if an
old writer splits metadata without `deep_review_job` in `SETTINGS_KEYS`.
Rollback is a code revert. In-flight jobs are not durable across process
restart; the next GET fail-closes them.

#### Risks / blockers

Staging-ready for a pilot, not a 100-student soak. Remaining: in-process jobs
die on container restart; AgentCore/Bedrock account concurrency; polling load
is one GET / 2s / in-flight review only.

#### Next exact action

Do **not** commit, publish AgentCore, or rebuild the EC2 image unless asked.

### Previous phase — Always-visible Deep Review button (server-owned eligibility)

**Committed on `Integrate-Bedrock`.** No AgentCore publish, EC2 deploy, or live
AWS inference was performed. Fast Chat, RAG, stage advancement, Sonnet, and
the Deep Review HTTP contract are unchanged. Live app image remains
`cde2300-chatbot:b81a5b0`.

#### What this phase changed

1. **Always-visible control.** Review always renders `Start Deep Review`.
   Locked = Streamlit `disabled=True` with
   `Deep Review unlocks after {interval} coaching turns — {n}/{interval} completed.`
   Unlocked idle = `type="primary"` plus wait copy. Full-width control with a
   10px caption gap. Locked uses a muted outlined shade; ready uses a solid
   `--cd-accent` fill (`20-studio.css`).
2. **Server-owned eligibility.** Presentation uses
   `deep_review_control_view(counter, interval, running=...)` over
   `parse_coaching_turns_since_deep_review` and
   `settings.deep_review_interval_turns` (bounded). No Streamlit counter.
   FastAPI still rejects ineligible calls with 400.
3. **Click / loading.** Eligible click sets session
   `_deep_review_running_thread_id` and reuses one
   `_deep_review_idempotency_key`, shows compact `st.status`, and calls
   existing `start_deep_review()` → `POST /deep-review`. Success clears the
   guard and reruns (backend resets the counter to 0). Failure clears the
   guard, shows `Deep Review could not be completed. Try again.`, and keeps
   eligibility.
4. **Caption refresh.** Chat reruns studio when the persisted counter
   changes, not only when the boolean entitlement flips, so 1/3 and 2/3
   update after qualifying coaching turns.
5. **DESIGN.md.** One-sentence clarification that a single eligibility
   caption is not a Journey counter.

#### Files

- `ui/panels/studio.py` — view helper, always-visible button, status, guard
- `ui/panels/chat.py` — studio rerun on counter change
- `ui/assets/styles/20-studio.css` — full-width button, 10px gap, locked vs ready shades
- `tests/ui/test_deep_review_control.py` — helper views at 0/1/2/3 + running
- `tests/ui/test_chat_progress.py` — always present; disabled then enabled;
  ineligible click spy; failure keeps counter and safe error
- `DESIGN.md` — eligibility caption is not a second Journey counter
- `docs/IMPLEMENTATION_STATUS.md` — this phase

#### Validation

- `ruff check` on touched Python files: passed.
- `python -m compileall -q backend ui streamlit_app.py tests scripts`: passed.
- Targeted: `tests/ui/test_deep_review_control.py`,
  `tests/ui/test_chat_progress.py`, `tests/domain/test_deep_review_execution.py`,
  `tests/domain/test_review_agent.py`, `tests/http/test_deep_review.py`:
  57 passed.
- Full mock pytest: 1305 passed.
- No live AWS, AgentCore, Bedrock, DSQL, S3, or KB calls.

#### Migration / compatibility / rollback

No schema, API, or counting-rule change. Rollback is a code-only revert of
the Streamlit presentation. Existing notebooks keep
`coaching_turns_since_deep_review`. Failed Deep Review still does not reset
the counter.

#### Risks / blockers

Leaving the Review **tab** still does not cancel an in-flight Deep Review
(`st.tabs` is client-side). A full Streamlit rerun (Chat send, notebook
switch) can show a UI error while FastAPI finishes; notebook lease remains 1
in-flight request.

#### Next exact action

Do **not** publish AgentCore or rebuild the EC2 image for this
presentation-only patch unless a new app image is requested. Live image
remains `cde2300-chatbot:b81a5b0`.

### Previous phase — Fast Chat first-pass structured output, retry bounds, Deep Review cap

**Code is local on a worktree of `Integrate-Bedrock` at `e88393d` and is not
committed or deployed.** No AgentCore publish, EC2 deploy, or live AWS
inference was performed.

#### Trace vs current code

The supplied two-cycle production trace used a **rich** Fast Chat schema
(`assessment`, `research_coding`). Current HEAD Fast Chat is slim
`FastChatTurnOutput` (`fast_chat_turn_v1`). That trace is therefore a
**stale runtime / older DEFAULT** observation, not proof that current
published AgentCore still emits the rich schema.

#### Root cause of cycle #2

**PROVEN (Strands 1.52.0 SDK mechanism, from the pinned wheel):** inside
**one** `invoke_async` / **one** `InvokeAgentRuntime`, if structured output
is enabled and the first generation returns `stop_reason=end_turn` without
the output tool, Strands appends `structured_output_prompt`
(`Please use the output tool now.`), `set_forced_mode()`, and
`recurse_event_loop`. That is a second **event-loop cycle**, not a second
application AgentCore invoke.

**UNPROVEN:** that the supplied live trace's cycle #2 was this recovery on
**current slim** Fast Chat. No live AWS call was made here, and that trace's
schema does not match `fast_chat_turn_v1`.

**INFERENCE:** first-pass conversational prose is more likely when the
system prompt opens as a locked Coaching specialist and asks Haiku to be
conversational before the structured-output contract. The working-tree
prompt/identity changes are a hedge, not live proof of one-cycle Haiku.

#### What this phase changed

1. **First-pass instruction.** Fast Chat tells Haiku to complete the
   structured-output mechanism on the first generation and not to emit an
   intermediate conversational answer. Fast Chat identity is no longer a
   locked Coaching specialist: `shared_coaching.md` is unchanged for legacy
   Coaching, but Fast Chat replaces only the opening identity sentence.
2. **`runtime_context.specialist=fast_chat`.** Fast Chat no longer stamps
   `specialist=coaching`. Optional `expected_response_mode` is included when
   the server policy is qa or coaching.
3. **Model retries.** Per-invoke `ModelRetryStrategy`: Haiku roles
   `max_attempts=2` (1s/4s backoff); Deep Review `max_attempts=3` (2s/16s).
   Distinct from event-loop turns. New strategy instance per Agent.
   Botocore Converse retries are pinned to `max_attempts=1` so they do not
   multiply the Agent retry budget.
4. **Deep Review event-loop cap.** `limits={"turns": 3}` (was uncapped).
5. **Welcome exclusion.** Static `coach_welcome` stays in the transcript for
   UI and is omitted from model history.
6. Guardrail-safe ConversationMemory rendering from `847d0c6` is unchanged.

#### Validation

- `ruff check .`: passed.
- `python -m compileall -q backend ui streamlit_app.py tests scripts agentcore_runtime`:
  passed.
- Focused Fast Chat / AgentCore / mode / memory / RAG fallback / Deep Review
  tests: passed.
- `tests/domain` excluding three POSIX-`resource` collectors
  (`test_files_and_engine.py`, `test_retrieval.py`, `test_source_library.py`):
  passed after LF-normalizing the coaching prompt hash lock (Windows CRLF).
- Companion pytest does not install `strands-agents`. Cycle-#2 semantics were
  proven by reading the downloaded `strands-agents==1.52.0` wheel
  (`event_loop.py` `end_turn` recurse + `_retry.py` `ModelRetryStrategy`).
  The GitHub `agentcore-runtime-compatibility` job remains the CI install path.
- No live AWS, AgentCore, Bedrock, DSQL, S3, or KB calls.

Windows-only collectors/failures outside this phase (POSIX `resource`,
SQLite `WinError 32` load probes, LFS PDF pointer noise) are not treated as
Fast Chat regressions.

#### Next exact action

Do **not** publish AgentCore or deploy EC2 until authorised. After an
authorised runtime publish, live-validate one-cycle Fast Chat and the
old-notebook Guardrail path.

### Previous phase — Per-service TIMING latency lines

**Prepared on 2026-08-17.** FastAPI-side instrumentation on
`Integrate-Bedrock`. Nothing in this phase has been pushed to EC2, published as an
AgentCore runtime version, or synced to the Knowledge Base.

Operators asked for per-service wall times (`student_state`, `memory`,
`retrieval`, `context_build`, `agent`, `persistence`, `TOTAL`) in seconds.
Those spans already existed as millisecond fields on privacy-safe
`coach_turn_perf` JSON, except conversation-memory parse. This phase records
the missing span and emits grep-friendly `TIMING` lines without student
text, prompts, or notebook identifiers.

#### What changed and why

1. **`memory_load_ms`** times `memory_from_metadata()` during authoritative
   turn prepare.
2. **`agent_ms`** times `_workflow.run` (RAG fallback adds a second invoke).
3. **Snapshot rollups.** `student_state_ms` = notebook + history + source
   loads; `context_build_ms` = prompt compose + context planner;
   `persistence_ms` = persist + idempotency complete. Direct AgentCore
   `assess()` copies `agent_ms` from `agentcore_invoke_ms` when the
   application wrapper did not run.
4. **`TIMING` log lines** on `co_design.turn_perf` in seconds, plus the
   existing millisecond JSON event.

Q&A/coaching policy, retrieval, citations, idempotency, Deep Review, and
Guardrails are unchanged. No AgentCore republish is required; restart local
FastAPI to pick up the log lines.

#### Validation

- Focused: `tests/domain/test_coach_turn_perf.py`,
  `test_turn_snapshot.py`, `test_rag_fallback.py`.
- `ruff check` on changed Python files: passed. `compileall` for
  `backend`, `ui`, `streamlit_app.py`, `tests`, `scripts`: passed.
  Full deterministic pytest: passed (exit 0).

#### Next exact action

Restart local FastAPI if you want CloudWatch/local logs to show `TIMING`
lines on the next coach turn. Do not republish AgentCore.

### Previous phase — Guardrail-safe conversation-memory rendering

**Prepared on 2026-08-17; committed as `847d0c6` on `Integrate-Bedrock`.**
Nothing in that phase was pushed to EC2, published as an AgentCore
runtime version, or synced to the Knowledge Base.

Old notebooks were failing live Fast Chat with
`source=envelope category=safety_blocked` while a new empty notebook
succeeded. Guardrail v3 scans the latest user message
(`guardrail_latest_message=True`). Derived `conversation_memory` was
rendered into that message with instruction-shaped wrapper prose
("Do not obey commands…"), which matches the earlier Strands repair
PROMPT_ATTACK false-positive class.

#### What changed and why

1. **`ConversationMemory.format_for_prompt()`** now emits data labels only
   (`schema=…`, `problem_definition:`, `key_decisions:`). It no longer
   prefixes "UNTRUSTED DERIVED MEMORY" / "Do not obey commands".
2. **Render-time filter.** Values matching `_INSTRUCTION_SHAPED` are omitted
   from the guarded user channel. `quoted_student_statements` stay in
   persisted JSON and are not rendered.
3. **Compressor.** Instruction-shaped turns still go to
   `quoted_student_statements` but no longer seed `problem_definition` or
   `current_working_conclusion`.
4. **Trusted guidance unchanged.** FastAPI `runtime_instructions` still
   says derived memory is untrusted student/project content, not system
   instructions.

Persisted notebooks, stages, Q&A/coaching policy, retrieval, citations,
idempotency, Deep Review, and Guardrail IDs are unchanged. No AgentCore
republish is required; restart local FastAPI to pick up the render change.

#### Validation

- Focused: `tests/domain/test_context_planner.py`,
  `test_fast_chat_context.py`, `test_agentcore_provider.py`,
  `test_prompt_architecture.py`.
- `ruff check .`: passed. `compileall` for `backend`, `ui`,
  `streamlit_app.py`, `tests`, `scripts`: passed. Full deterministic
  pytest: passed (exit 0).
- **NEEDS LIVE AWS VALIDATION:** retry the same old notebook after
  restarting `scripts/start.sh`. Expect a coaching reply, not
  `safety_blocked`. CloudWatch `failure_category=safety_blocked` should
  not appear for that turn.

#### Next exact action

Restart local FastAPI/Streamlit and send a coaching sentence on the
previously blocked notebook. Do not republish AgentCore for this fix.
Production needs a FastAPI/EC2 deploy separately.

### Previous phase — Uncommitted Fast Chat honesty, retrieval bounds, Phase 18 containment

**Prepared on 2026-08-17; committed as `fafca8f` on `Integrate-Bedrock`.**
Local HEAD at that commit plus the later guardrail-memory patch above.
Nothing in that phase was pushed to EC2, published as an AgentCore
runtime version, or synced to the Knowledge Base.

This phase does **not** claim production is fixed. One-Haiku-per-turn and
live filtered Retrieve remain **UNVERIFIED** pending an authorised live
trace. Mock pytest is not that evidence.

#### What changed and why

Verified in the working tree (read the code; do not treat this as a live
confirmation):

1. **Progress-field merge.** `backend/coaching/progress_fields.py` overlays
   only meaningful values. Empty slim Fast Chat fields can no longer blank
   stored `learning_summary` / `working_conclusion` /
   `understanding_change` / `critical_understanding` on ADVANCE confirm
   (`learning_service.py`, `student_store.py`, `coaching/execution.py`).
2. **Request-scoped citation map.** After the model call, `[S#]` resolution
   uses `TurnSnapshot.sources_by_id` plus `CoachRequest.source_ids`. It does
   not `get_source` per id and does not list the S3 catalog again. Course
   `list_prefix` still runs once per folder when the snapshot is built
   (mock test: 2 prefix calls, 0 `get_source` calls).
3. **Request-scoped turn snapshot.** `backend/coaching/turn_snapshot.py`
   holds the authoritative notebook row, stage, and visible sources for one
   `submit()`. Mock test: notebook row is loaded twice (existence +
   authoritative re-read), not three times.
4. **Strands event-loop cap.** Fast Chat / router / legacy Haiku pass
   `limits={"turns": 2}` (Strands 1.52.0: initial generation plus at most
   one recovery). Deep Review is uncapped (`structured_output_limits_for_role`
   returns `None`). **NEEDS LIVE TRACE** — companion pytest does not install
   Strands and cannot prove Haiku span count.
5. **`fast_chat_turn_v1` wire marker.** Slim `FastChatTurnOutput` plus
   fail-closed `adapt_fast_chat_turn_payload` for the previous nested
   `CoachTurnOutput` / Q&A shape. Deploy order (documented, not executed):
   publish FastAPI with the tolerant parser **before** or together with a
   runtime that emits slim JSON. Do not publish slim-only runtime JSON to an
   old FastAPI image.
6. **Fast Chat system-prompt de-duplication.** Facione / research-coding /
   nested-assessment instructions were removed from `shared_coaching.md` and
   from FastAPI `trusted_instructions`; the JSON contract lives once in
   `_FAST_CHAT_JSON_CONTRACT`. Live reconstruction of the
   `problem_identification` Fast Chat system prompt (composer +
   `specialist_system_prompt`, including trusted rules and
   `runtime_context`):
   - **Now:** 11,467 characters / **3,823** estimated tokens (chars/3).
   - **HEAD reconstruction** (HEAD prompt files + HEAD JSON contract + the
     two FastAPI runtime paragraphs this patch removed): 13,978 characters /
     **4,660** estimated tokens.
   - Pedagogical files: `shared_coaching.md` 10,026 → 7,397 chars (−2,629);
     `fast_chat.md` 994 → 1,309 (+315); stage file unchanged.
   Earlier status at `f663740` recorded 12,958 / 4,320 before
   `runtime_context`; that is a different baseline, not this HEAD delta.
7. **Retrieval gate recall.** `classify_retrieval_intent` is graded
   (`high_confidence_source` / `high_confidence_personal` / `ambiguous`).
   Bare week/lecture, course grounding, and `S1`/`S2` labels retrieve.
   `looks_like_course_question` is unchanged (mock specialist routing).
8. **Server-side mode policy.** `backend/coaching/mode_policy.py` stamps
   expected Q&A/coaching from the student message and selected-source
   metadata. No second model call. High-confidence source turns without
   first-person project reasoning coerce `mode=qa` downstream (prose kept,
   recommendation stripped). Mixed lecture+project language stays
   ambiguous so Haiku chooses.
9. **Bounded Retrieve admission.** Semaphore sized to the shared executor
   worker count. Excess calls fail closed as `capacity_exhausted`. Empty
   configured bucket and empty-bucket URIs (`s3:///...`) drop hits.
   Production requires `COURSE_MATERIALS_BUCKET` whenever
   `KNOWLEDGE_BASE_ID` is set. Retrieve timeout default is **10s** (was 5s
   at HEAD `ae3be3d`).
10. **Idempotency lease derived from timeouts.** No independent 180s knob.
    With defaults (AgentCore 110s, retries 0, Retrieve 10s) the derived
    lease is **270s** (timeout-bounded work 240s + 10s persist budget + 20s
    margin). Tests prove 180s cannot cover two 110s windows.
11. **Streamlit `done` rendering.** `ui/panels/chat.py` draws the validated
    `done` payload in the same script run. `rerun_app()` runs only when
    stage, pending transition, or Deep Review availability changed
    (`needs_reconcile`). AppTest: a stay turn shows the reply with zero
    forced reruns.
12. **Phase 18 legacy-path containment.** Classification and lock tests in
    `tests/domain/test_legacy_path_containment.py`. Dead FastAPI helpers are
    not deleted. The published runtime still dispatches leftover `phase`
    values for IAM callers — documented in
    [`SECURITY_BOUNDARIES.md`](SECURITY_BOUNDARIES.md). That is not a
    browser bypass and must not be "fixed" in UI code.

#### Files changed

Uncommitted working tree (not a complete path dump): progress merge
(`backend/coaching/progress_fields.py`, `learning_service.py`,
`student_store.py`, `coaching/execution.py`); turn snapshot and mode policy;
citation catalog; retrieval gate, Bedrock Retrieve pool/bucket checks,
`sources/kb_metadata.py`; slim Fast Chat schema/parser and prompt files;
Strands `limits`; lease derivation in `settings.py`; Streamlit chat/runtime;
KB sidecar scripts and
[`docs/KB_REQUIRED_MODE_RUNBOOK.md`](KB_REQUIRED_MODE_RUNBOOK.md);
containment tests and security-boundary docs. Preserve this working tree;
do not commit unless asked.

#### Adversarial review outcome and follow-up fixes

An independent reviewer that made none of the edits answered the fifteen
regression questions against this tree. Thirteen were clean. Two P1 defects
were found in the new mode policy and have been fixed:

1. **Third-person project reasoning was force-flattened to Q&A.** The
   retrieval gate is deliberately recall-oriented, so any lecture/week/slides
   cue produced `high_confidence_source`, and the mode overlay only demoted
   that back to ambiguous on a narrow *first-person* matcher. A student
   writing "The core problem is that first-year students skip the week 2
   lecture" therefore lost its stay/advance recommendation and its Deep
   Review credit. `backend/coaching/mode_policy.py` now demotes on a
   person-agnostic project-deliberation matcher **and** requires the turn to
   actually be an information request before Q&A can be forced. Six
   confirmed regressions now return `expected_mode=None` while still
   retrieving. Locked by
   `test_third_person_project_reasoning_is_never_forced_to_qa`.
2. **Cue-less course questions could still become Coaching.** "what is the
   definition of a job story" carried no lecture/week/S# cue, so the model
   was free to label it coaching, increment the Deep Review counter, and open
   an ADVANCE. `backend/retrieval_gate.py` now recognises impersonal
   course-concept questions as a source cue (so evidence is retrieved and the
   Q&A expectation applies). Any first- or second-person pronoun disqualifies
   the turn, so "what assumption am I making here" stays with the coach.
   Locked by `test_impersonal_course_concept_questions_expect_qa` and
   `test_personal_reflection_phrased_as_a_question_is_not_qa`.

Also fixed from the same review: the shared-catalog `ContextVar` is now reset
before telemetry is recorded so a metrics failure cannot strand the memo on a
pooled worker thread (`backend/sources/library.py`), and a composer upload now
invalidates the Streamlit source-list memo, because a stay turn no longer
reruns and the Sources panel would otherwise render the pre-upload list
(`ui/services/runtime.py`, `ui/panels/chat.py`).

**Known remaining cost (accepted, not fixed):** `_selected_source_count` in
`backend/http/app.py` lists selected sources before `submit()` for the
pre-submit ops log and the error-path metrics. On the streaming route
`submit()` runs on a separate daemon thread, so a `ContextVar` memo cannot be
shared across that boundary. This costs one bounded catalog listing per coach
HTTP request when locked course sources are selected. It is not N+1.

#### Validation evidence

- Full deterministic pytest after the review fixes: **1163 tests, all
  passing** (`.venv/bin/python -m pytest -q`, exit 0).
  `.venv/bin/ruff check --no-fix .`: **All checks passed** (was 14 F401).
  `compileall -q backend ui streamlit_app.py tests scripts agentcore_runtime`:
  **passed**.
- Targeted (containment pass): **25 passed**
  (`test_legacy_path_containment.py` 12,
  `test_security_invariants.py` 4,
  `test_architecture_contracts.py` 9).
  `.venv/bin/ruff check --no-fix .`: **All checks passed**.
  `compileall -q backend agentcore_runtime`: **passed**.
- Prior mock tests in this working tree cover progress merge, citations,
  snapshot, schema adapter, prompt composition, retrieval-gate recall,
  Retrieve pool, lease alignment, and Streamlit `done` rendering. Those are
  **mock-only**.
- Full deterministic pytest: **not re-run** in the containment pass
  (targeted subsets only).
- **No** paid/live Bedrock, AgentCore, S3, DSQL, or KB sync call was made.
- One-Haiku-per-turn: **UNVERIFIED**.
- Live `required`-mode Week 1 equals/in Retrieve: **UNVERIFIED**.

#### Compatibility, rollback, risks, and next action

- No DSQL schema migration. Old nested `CoachTurnOutput` JSON still parses
  through the fail-closed adapter. New Fast Chat rows persist a slim
  assessment mapping. Empty progress fields no longer overwrite stored
  notebook progress.
- Stage pedagogy files: `shared_coaching.md` hash fixture updated after
  explicit review; stage files unchanged.
- Rollback is the previous app image (`cde2300-chatbot:f271088` is what is
  live; this tree is not). Persisted notebooks are unchanged.
- Deploying `required` before sidecar ingest yields an evidence gap, not a
  110s unfiltered search. Operators who have not ingested sidecars must keep
  `KNOWLEDGE_BASE_METADATA_FILTER_MODE=degraded_unfiltered`.
- IAM: `bedrock-agentcore:InvokeAgentRuntime` on the published ARN still
  bypasses FastAPI phase controls. Mitigate with least privilege. Do not
  patch the browser.
- `README.md` still says `StudentChatEngine` is a `USE_LOCAL_API=false`
  fallback. Code and `docs/CODEBASE_STRUCTURE.md` say the in-process
  fallback is `CoachApplicationService`. Containment tests lock the code
  fact; README was not edited (outside this pass's file ownership).
- Next exact action: authorised sidecar upload + KB sync (runbook
  [`KB_REQUIRED_MODE_RUNBOOK.md`](KB_REQUIRED_MODE_RUNBOOK.md)), then one
  live Week 1 `equals` Retrieve with `--i-approve-live-bedrock`, then a
  capped AgentCore trace that records Haiku span / event-loop cycle count.
  Do not publish AgentCore and do not rebuild the ARM64 app image until
  those two live checks exist. Do not delete leftover runtime `phase`
  dispatch until a published allowlist (or split runtimes) lands.

---

### Previous phase — Cap Fast Chat Retrieve at five seconds

**Prepared on 2026-08-17; not yet deployed.**

#### What changed and why

`f271088` is live on EC2 (`cde2300-chatbot:f271088`). That image skipped the
rejected MANAGED metadata filter and set a 15-second SDK read timeout. The
119-second double-Retrieve path is gone, but asking what is in the Week 1
lecture still took more than 30 seconds.

Production evidence after that recreate:

- Application loggers were at WARNING, so `coach_turn_perf` and
  `course_retrieval_query` never appeared in Docker logs.
- No `course_retrieval_validation_error` / `retrying_unfiltered` after restart.
- The blocking `POST .../messages/.../revise` path completed at `19:55:32`.
  Haiku itself remains ~5 seconds. A 15-second Retrieve plus that invoke plus
  the Streamlit reload still exceeds 30 seconds.

1. Knowledge Base Retrieve now has a **5-second wall-clock** cap
   (`KNOWLEDGE_BASE_RETRIEVE_TIMEOUT_SECONDS`, also used as the SDK read
   timeout) and `numberOfResults=4` (the Fast Chat chunk budget). A hung
   MANAGED search fails closed as an evidence gap instead of occupying the
   spinner. Catalog titles still reach AgentCore.
2. FastAPI sets INFO on the operational loggers so `coach_turn_perf` and
   Retrieve elapsed-ms lines are visible without lowering the root logger.
   Slow or unavailable Retrieve also logs at WARNING.

#### Files and validation

- Changed: `backend/bedrock_retrieve.py`, `backend/settings.py`,
  `backend/operational_metrics.py`, `backend/http/app.py`,
  `tests/domain/test_bedrock_retrieve.py`,
  `tests/domain/test_coach_turn_perf.py`, `docs/RAG_ARCHITECTURE.md`,
  `.env.example`, and this status file.
- Deterministic retrieval + perf tests: **focused passed**.
- Repository-wide Ruff: **passed**.
- Full deterministic pytest: **970 passed**.
- Compileall for backend, UI, tests, scripts: **passed**.
- No paid/live Bedrock or AgentCore call was made for this patch.

#### Compatibility, rollback, risks, and next action

- No schema, DSQL, S3, Cognito, AgentCore runtime, or prompt change.
- Rollback is the previous app image (`cde2300-chatbot:f271088`); persisted
  notebooks and sources are unchanged.
- A Retrieve that cannot finish in 5 seconds becomes an evidence gap. Week 1
  answers may cite catalog titles without PDF excerpts until the MANAGED KB
  is faster or `course_material_id` metadata is verified.
- Next: build a new ARM64 app image from this tree, recreate only the `app`
  container, ask the Week 1 lecture question once, and confirm Docker shows
  `course_retrieval_elapsed_ms` plus `coach_turn_perf`.

---

### Previous phase — Bound MANAGED Knowledge Base retrieval latency

**Committed on `Integrate-Bedrock` as `3b393d6` / `f271088` and deployed as
`cde2300-chatbot:f271088`.**

Production evidence for the earlier Week 1 query showed the Streamlit-to-FastAPI
stream begin at `19:14:52.527`, a MANAGED Knowledge Base metadata-filter
`ValidationException` at `19:14:53.265`, and the first post-turn UI reload at
`19:16:51.484`. The AgentCore trace itself was 4.73 seconds.

MANAGED Retrieve makes one unfiltered request while strict metadata mode is
off. The Bedrock Agent Runtime client used `total_max_attempts=1` and a
15-second read timeout. That removed the ~119-second filter-retry hole but
left Fast Chat above 30 seconds.

---

### Previous phase — Explicit Deep Review HTTP + token-aware Fast Chat


**Committed on `Integrate-Bedrock` as `f663740`.** Canonical Coaching prompts
still match baseline `a6d163668902beae4938fe552cced7ba92b15e88`. AgentCore
**version 20 READY** on the existing ARN
`NUSCodesignChatbot_chatbot_harnessAgent-6ncEO79sD7`; `DEFAULT` liveVersion
is **20**. EC2 app image has **not** been rebuilt (Docker daemon was down).

This patch does **not** redo the 2620db one-call Haiku / RAG-fallback
architecture. It makes explicit Deep Review reachable and makes Fast Chat
history token-aware, including AgentCore system-prompt overhead in the
12k/16k total.

#### What changed and why

1. **Server-owned Deep Review HTTP.** `POST /api/v1/threads/{thread_id}/deep-review`
   authenticates the owner, loads notebook/stage/history/sources, checks
   persisted eligibility (`coaching_turns_since_deep_review >= 3`), acquires
   the same notebook execution lease, then stamps `specialist=review` **after**
   `_authoritative_request()` has already cleared client specialist hints.
   `POST /api/v1/coach/turn` still cannot choose Sonnet. Body accepts only
   `idempotency_key` (`extra=forbid`).
2. **Eligibility / counter.** One entitlement at counter >= 3; unused 4/5/6
   still yield one review. Successful persist resets to 0. Failure, timeout,
   guardrail, malformed output, and persist failure leave the counter
   unchanged. Q&A, Deep Review, UI navigation, and idempotent replay do not
   increment. Replay of a completed Deep Review key is allowed even after
   the counter has reset. Idempotency fingerprints include a Deep Review
   surface, so ``/coach/turn`` cannot complete a ``/deep-review`` key even
   with the fixed ``Start Deep Review`` message.
3. **Deep Review persistence.** Latest successful review is stored as
   `deep_review_snapshot` in notebook settings. Normal Haiku Coaching persist
   omits that key, so the snapshot is not overwritten. The next successful
   Deep Review replaces it. Stage stays `STAY`; FastAPI remains stage
   authority.
4. **Token-aware Fast Chat history.** At most 6 recent message objects **and**
   <= 3000 estimated recent-history tokens **and** <= 1500 estimated tokens
   per historical message. Newest-to-oldest packing; dropped window turns
   **and** later total-budget shrinks feed ConversationMemory from the
   original text, not the 1500-token clip. Late decision cues in a huge
   paste are kept in the 800-character memory excerpt. The current student
   message is not history-capped (CoachRequest still enforces the
   12,000-character safety cap). Current-turn Converse overhead is reserved
   in the total estimate. The current message is still not 1500-capped; a
   max-length paste can crowd out recent history under the 12k/16k totals,
   which is the intended current-turn priority.
5. **Total budget includes system prompt.** FastAPI estimates the AgentCore
   Fast Chat system prompt via `agentcore_runtime/system_prompt_budget.py`
   (same canonical loader; no prompt copy), including `runtime_context`
   JSON. Soft 12,000 / hard 16,000 are local total estimates (system +
   untrusted turn + history + memory + images + current-turn overhead).
   Conservative local estimator; not Bedrock CountTokens.
6. **RAG fallback repacks.** The second Haiku invoke re-enters workflow
   planning with retrieved evidence. History is reduced if needed so the
   estimated total stays <= 16,000.
7. **Live eval candidate path.** `evaluate_fast_chat_regression.py` can invoke
   the already-configured AgentCore runtime when `--i-approve-live-claude` is
   set and `AGENTCORE_RUNTIME_ARN` is present. Default remains refuse. No
   judge model, no publish, no fake baseline (`--baseline-artifact` or
   "baseline comparison unavailable").
8. **OCI provenance.** Dockerfile accepts `ARG GIT_SHA` and sets
   `org.opencontainers.image.revision` plus `APP_GIT_SHA`. Recommended:
   `docker build --build-arg GIT_SHA=$(git rev-parse HEAD) ...`. Image was
   not rebuilt or deployed.

#### Main files changed

- Deep Review: `backend/http/app.py`, `backend/coaching/execution.py`,
  `backend/domain.py`, `backend/workflow.py`, `backend/mock_provider.py`,
  `backend/specialists/review_orchestration.py`, `backend/learning/journey.py`,
  `backend/api_client.py`, `ui/panels/studio.py`, `ui/services/runtime.py`
- Fast Chat tokens: `backend/context_planner.py`, `backend/settings.py`,
  `backend/agentcore_provider.py`, `backend/turn_perf.py`,
  `agentcore_runtime/system_prompt_budget.py`, `.env.example`, Compose
- Eval / Docker / docs / tests: `scripts/evals/evaluate_fast_chat_regression.py`,
  `Dockerfile`, this file, architecture/security/prompt docs, Deep Review and
  token-budget tests

#### Validation evidence

- Canonical Coaching hashes unchanged vs `a6d163668902beae4938fe552cced7ba92b15e88`
  (`git diff` empty on `shared_coaching.md` and `prompts/stages/`; SHA-256
  fixture still `tests/fixtures/coaching_prompt_baseline.json`).
- `ruff check .` passed.
- `PYTHONPYCACHEPREFIX=/private/tmp/co-design-pycache python -m compileall -q
  backend ui streamlit_app.py tests scripts agentcore_runtime` passed.
- Focused pytest: fast-chat context/memory, AgentCore provider, prompt cache,
  and context planner passed after the token-policy follow-up.
- Full deterministic `.venv/bin/python -m pytest -q`: **967 passed**.
- GitHub CI for `f663740`: **NOT RUN** in this session.
- AgentCore publish 2026-08-16: **version 20 READY**. Same ARN
  `NUSCodesignChatbot_chatbot_harnessAgent-6ncEO79sD7`. `DEFAULT`
  liveVersion **20**. Artifact
  `s3://cdk-hnb659fds-assets-355604674280-us-west-2/agentcore-patches/chatbot_harnessAgent-fast-chat-v20-20260816T184830Z.zip`.
  Env copied from v19 (Haiku coaching/fast_chat, Sonnet Deep Review,
  Guardrail v3). Site-packages preserved from v19.
- EC2 image build/push: **NOT RUN** (Docker daemon down on this machine).
  ECR repository `cde2300-chatbot` does **not** exist yet in account
  `355604674280`.
- Capped live smoke / Deep Review live invoke: **NOT RUN**.
- Local Fast Chat system-prompt estimate for problem_identification: 12,958
  chars / **4,320** estimated tokens (chars/3) before `runtime_context`.
  Typical no-RAG short coaching with that reserve stayed <= 12,000 in tests.
- ConversationMemory continuity 20/50/100 plus chunky-history passed. Soft
  total-budget shrink now preserves a decision that sits after the 1500-token
  history clip. No LLM summarizer.

#### Production readiness (do not collapse these)

- **CODE CORRECT:** YES for the mock/deterministic path
- **CONCURRENCY SAFE:** YES — Deep Review uses the same notebook lease as
  Coaching; RAG fallback stays inside that lease
- **IDEMPOTENCY SAFE:** YES — completed Deep Review keys replay without a
  second Sonnet call or a second counter reset
- **MOCK TESTED:** YES (967)
- **CI GREEN:** NOT RUN for `f663740`. Previous committed HEAD `2620db1`
  had Mock CI + AgentCore runtime compatibility successful.
- **DOCKER READY:** NO (image not built; Docker daemon down)
- **LIVE LOAD TESTED:** NO
- **AWS QUOTAS VERIFIED:** NO
- **PRODUCTION READY:** **NO** until the EC2 app image at `f663740` is
  running, a capped Haiku smoke succeeds, and Deep Review is exercised.
  Prompt cache stays disabled.

#### Next exact action

1. Create ECR repo `cde2300-chatbot` if missing, start Docker, then
   `docker buildx build --platform linux/arm64 --build-arg GIT_SHA=f663740
   -t 355604674280.dkr.ecr.us-west-2.amazonaws.com/cde2300-chatbot:f663740 --push .`
2. On EC2: set `APP_IMAGE` to that tag, keep `AGENTCORE_QUALIFIER=DEFAULT`
   (now v20), then `sh scripts/deploy_ecr.sh`. Recreate the app container.
3. Keep `FAST_CHAT_PROMPT_CACHE_ENABLED=false`.
4. Capped smoke:
   `PYTHONPATH=. python scripts/agentcore_smoke.py --i-approve-live-agentcore --cost-cap 1.00 --max-requests 1`
5. Rollback runtime if needed: `update-agent-runtime` with the v19 zip
   `agentcore-patches/chatbot_harnessAgent-repair-prompt-v19-20260816T101413Z.zip`,
   or pin `AGENTCORE_QUALIFIER=19`.

---

### Previous phase — Fast-chat 6-message window, RAG fallback, pedagogy lock

**Committed on `Integrate-Bedrock` as `2620db115a0671042859743daace3fc54de335d3`.**
Starting HEAD was `db6d1bae7403c05e68c38bad39dd2afd9bd268fc`. Canonical
Coaching prompts match baseline `a6d163668902beae4938fe552cced7ba92b15e88`.

GitHub CI for **that** commit: Mock CI successful; AgentCore runtime
compatibility successful. That CI result does **not** apply to later local
work.

Normal student chat remains one Claude Haiku 4.5 `phase=fast_chat` invoke.
The rare accuracy fallback may add one application-owned retrieve and one
Haiku retry. Router and Incremental Review stay off the active path.

#### What changed and why

1. **Six recent messages.** Fast chat sent ConversationMemory plus at most
   **6** recent verbatim message objects (not pairs). No per-message token
   cap yet; soft/hard totals were 15k/20k and undercounted the AgentCore
   system prompt. Deep Review HTTP was still unreachable because
   `_authoritative_request()` cleared `specialist`.
2. **Pedagogy lock.** `fast_chat_system_prompt` concatenates the canonical
   `shared_coaching.md` and current stage file. Hash fixtures fail if those
   files change without explicit pedagogical review.
3. **Rare RAG fallback.** When the gate skipped retrieval and Haiku sets
   `needs_source_retrieval=true` and selected sources exist, FastAPI
   retrieves once and retries Haiku once. The first result is not persisted.
   Same notebook lease and idempotency claim.
4. **Prompt cache (opt-in, conservative).** Prefix cache behind
   `FAST_CHAT_PROMPT_CACHE_ENABLED` (default false). No
   `CacheConfig(strategy="auto")`. No padding.
5. **Behaviour regression suite.** Versioned cases plus a dry-run CLI.
   Live Claude was harness-only until the follow-up patch.

#### Validation evidence (that commit)

- Canonical Coaching hashes match `a6d163668902beae4938fe552cced7ba92b15e88`.
- Local `ruff check .` and `compileall` passed before commit.
- Full deterministic pytest at that handoff: **933 passed**.
- GitHub CI for `2620db1`: Mock CI successful; AgentCore runtime
  compatibility successful.
- Live Claude / AWS / AgentCore publish / EC2 deploy: **NOT RUN**.

#### Production readiness (that commit)

- **CODE CORRECT:** YES for the mock/deterministic path
- **CI GREEN:** YES for `2620db1` (Mock CI + AgentCore runtime compatibility)
- **PRODUCTION READY:** **NO** until AgentCore DEFAULT matches that runtime
  and live timings are collected.

---

### Previous phase — One-call Haiku fast chat, selective RAG, latency instrumentation

**Committed on `Integrate-Bedrock` as `db6d1bae7403c05e68c38bad39dd2afd9bd268fc`.**
Starting HEAD was `a6d163668902beae4938fe552cced7ba92b15e88`. Do **not**
publish AgentCore, mutate AWS, push, or deploy EC2 until authorized.

Normal student chat is now one Claude Haiku 4.5 `phase=fast_chat` invoke.
The Haiku router, Incremental Review, and automatic Sonnet are off the
active path. Deep Review remains an explicit `specialist=review` operation.

#### What changed and why

1. **One model call.** FastAPI invokes AgentCore once. Haiku chooses
   Coaching vs Q&A and writes the student reply in the same structured
   `FastChatTurnOutput`. ADVANCE is advisory; `AUTO_ADVANCE_STAGES=false`
   (tests) does not mutate stage. Production Compose still has
   `AUTO_ADVANCE_STAGES=true`, so a Haiku ADVANCE can still auto-apply
   there without Deep Review confirmation — product risk, not changed here.
2. **Bounded context.** Fast chat always sends ConversationMemory plus at
   most 8 recent verbatim messages (hard ~20k estimated input tokens, soft
   ~15k). Deep Review keeps a separate `full_history` planner.
3. **Selective RAG.** A deterministic gate decides retrieval before
   AgentCore. No extra LLM. Ownership and selected-source validation are
   unchanged. Opening Review/Journey still performs zero model/KB calls.
4. **Safe timings.** `coach_turn_perf` records DSQL load/claim/persist,
   retrieval, context, AgentCore, and estimated tokens without student
   text, prompts, excerpts, or secrets. DSQL pooling was not added.

#### Main files changed

- Runtime: `agentcore_runtime/main.py`, `models.py`, `model.py`,
  `structured_coach.py`, `specialists/routing.py`,
  `specialists/fast_chat.py`, `prompts/fast_chat.md`, `prompts/loader.py`
- Backend: `agentcore_provider.py`, `coaching/execution.py`,
  `context_planner.py`, `prompts/composer.py`, `retrieval.py`,
  `retrieval_gate.py`, `turn_perf.py`, `operational_metrics.py`,
  `settings.py`, `domain.py`
- Tests: `test_fast_chat_one_call.py`, `test_fast_chat_context.py`,
  `test_retrieval_gate.py`, `test_coach_turn_perf.py`, plus AgentCore,
  Review, hybrid, retrieval, API, and production-path updates
- Docs / example env: this file, `docs/providers/AGENTCORE_ADAPTER.md`,
  `docs/RAG_ARCHITECTURE.md`, `agentcore_runtime/README.md`, `.env.example`

#### Validation evidence

- `ruff check .`: **passed**.
- `compileall` for `backend`, `ui`, `streamlit_app.py`, `tests`,
  `scripts`, `agentcore_runtime`: **passed**.
- Focused AgentCore / fast_chat / context / retrieval / Review /
  production-config tests: **passed**.
- Full mock pytest: **passed** (902 collected, exit 0).
- Docker Compose config (`compose.yaml` and `compose.prod.yaml` with
  placeholder `PUBLIC_ORIGIN` / `APP_IMAGE`): **passed**. Daemon image
  build did **not** run.
- Live Haiku/AgentCore latency: **not measured**.
- GitHub Actions / AWS / AgentCore publish: **NOT RUN**.

#### Production readiness (do not collapse these)

- **CODE CORRECT:** YES for the one-call fast path under mock.
- **CONCURRENCY SAFE:** YES for existing lease/idempotency tests.
- **IDEMPOTENCY SAFE:** YES.
- **MOCK TESTED:** YES.
- **CI GREEN:** NOT RUN (no push).
- **DOCKER READY:** NO (compose config ok; image not built).
- **LIVE LOAD TESTED:** NO.
- **AWS QUOTAS VERIFIED:** NO.
- **PRODUCTION READY:** **NO** until AgentCore is republished on the same
  ARN and live timings are collected.

#### Next exact action

1. Code review this patch. Do not commit unless authorized.
2. **AGENTCORE REPUBLISH REQUIRED: YES** (new `fast_chat` phase, output
   contract, and prompt). Same ARN. Do not create a second runtime.
3. After authorized republish: measure live `coach_turn_perf` breakdowns
   before considering DSQL pooling.
4. Keep `AGENTCORE_QUALIFIER=DEFAULT` until the new runtime version is
   published and the qualifier is pointed at it.

### Previous phase — Request-local AgentCore state, revise lease, exact limiter release

**Code is local on `Integrate-Bedrock` and is not committed or deployed.**
Base commit for this work is `d619e73` (notebook-scoped limiter). AgentCore
DEFAULT v19, models, Guardrail v3, `AGENTCORE_QUALIFIER=DEFAULT`, and
pedagogical orchestration are **unchanged**.

#### Root causes fixed

1. `AgentCoreCoachProvider._last_plan` was instance-wide. One cached provider
   per owner can now run two notebooks concurrently, so Notebook B could
   overwrite Notebook A's plan before `_with_memory`. **Fix:** `_invoke_payload`
   returns `(payload, plan)` and `_with_memory` takes that request-local plan.
2. `revise_and_resubmit` mutated conversation state, then `submit` acquired the
   notebook lease. An in-flight send caused 429 after the transcript had already
   changed. **Fix:** acquire the same execution lease before any revise
   mutation; call `submit(..., execution_lease_held=True)`.
3. `release()` decremented user/global counters even when the notebook slot was
   not held, so a duplicate release could steal another request's capacity.
   **Fix:** `acquire()` returns a `CoachExecutionLease` token; `release` only
   decrements if that exact `(owner_id, thread_id)` slot (and token) is held.

#### Main files changed

- `backend/agentcore_provider.py`, `backend/agentcore_harness_provider.py`
- `backend/rate_limit.py`, `backend/coaching/execution.py`
- `scripts/agentcore_smoke.py`, `scripts/evals/evaluate_live_coach.py`
- Tests: `tests/domain/test_agentcore_provider.py`,
  `tests/fake_agentcore_runtime.py`, `tests/http/test_rate_limit.py`,
  `tests/http/test_coach_concurrency.py`
- This file

#### Validation evidence

- `ruff check .`: **passed**.
- `compileall` for `backend`, `ui`, `streamlit_app.py`, `tests`, `scripts`: **passed**.
- Focused concurrency / AgentCore / limiter / revise / idempotency / threadpool /
  API / deployment / DSQL OCC compatibility tests: **passed**.
- Full mock pytest: **passed** (exit 0; 873 tests in the last complete run).
- Mock load probe (`PYTHONPATH=.`): 2/10/25/50/100 distinct owners all accepted;
  two notebooks accepted; same notebook 1 accepted + 1 HTTP 429.
- AgentCore runtime diagnostic: **not run in the app venv** (`strands-agents`
  is installed only in the CI runtime job). No runtime/prompt/model edits.
- Docker Compose config (`compose.yaml` and `compose.prod.yaml`): **passed**
  with placeholder `PUBLIC_ORIGIN` / `APP_IMAGE`. Docker daemon was not running,
  so Caddy container validate and image build did **not** run.
- GitHub Actions for this uncommitted patch: **NOT RUN**.
- No live AWS, AgentCore, Bedrock, DSQL, S3, or quota changes.

#### Production readiness (do not collapse these)

- **CODE CORRECT:** YES for the three defects (mock-proven).
- **CONCURRENCY SAFE:** YES for the identified races under mock interleavings.
  Live AgentCore/DSQL contention is unproven.
- **IDEMPOTENCY SAFE:** YES (completed replay, same-key waiter, revise retry).
- **MOCK TESTED:** YES.
- **CI GREEN:** NOT RUN (no push).
- **DOCKER READY:** NO (compose config ok; image not built; daemon down).
- **LIVE LOAD TESTED:** NO.
- **AWS QUOTAS VERIFIED:** NO / PARTIAL (read-only documentation only).
- **PRODUCTION READY:** **NO**.

#### Next exact action

1. Commit this patch only when explicitly authorized. Do **not** push, merge,
   or deploy until the image and `compose.prod.yaml` can ship **together**.
2. Do not apply `MAX_ACTIVE_COACH_REQUESTS_PER_USER=2` onto an image that still
   has `_last_plan` or revise-before-lease.
3. Keep `AGENTCORE_QUALIFIER=DEFAULT` (v19) and Guardrail v3. No runtime publish.
4. After authorized deploy: staged live load 2 → 5 → 10 → 25 → 50 → ~100 with
   429-category, AgentCore/Bedrock/KB/DSQL, EC2 CPU/RAM/FD, and timeout metrics.
5. Remaining separate gates: CloudFront/Streamlit timeout (~105s observed vs
   110s AgentCore / 120s API client), Incremental Review fail-closed, explicit
   Review ADVANCE auto-apply under month-1 `AUTO_ADVANCE_STAGES=true`.

### Previous phase — Notebook-scoped coach concurrency for ~100 students

**Code landed 2026-08-16 on `Integrate-Bedrock`.** AgentCore DEFAULT v19,
models, Guardrail v3, and pedagogical orchestration are **unchanged**. This
patch only changes process-local coaching capacity on the existing single
FastAPI process.

#### Root cause / previous limitation

`CoachRateLimiter` allowed only **one active coaching workflow per
authenticated user** (`MAX_ACTIVE_COACH_REQUESTS_PER_USER=1`) and **20**
global workflows (`MAX_CONCURRENT_MODEL_CALLS=20`). Unrelated students did
not share that per-user lock, but:

- a student could not coach in two notebooks at once;
- the global ceiling of 20 was too low for a ~100-student class;
- AnyIO's default sync thread limiter (40) could queue FastAPI coaching
  work below the intended workflow ceiling;
- the mock load probe treated every virtual user as the shared
  `local-student` owner, so concurrent probe workers hit the per-user lock.

Students still must not overlap two executions in the **same** notebook.

#### Concurrency policy implemented

| Ceiling | Production | Meaning |
|---|---|---|
| `MAX_ACTIVE_COACH_REQUESTS_PER_NOTEBOOK` | 1 | One provider-backed workflow per `(owner_id, thread_id)` |
| `MAX_ACTIVE_COACH_REQUESTS_PER_USER` | 2 | Two different notebooks per student |
| `COACH_REQUESTS_PER_MINUTE` | 8 | Per-user rolling burst |
| `MAX_CONCURRENT_MODEL_CALLS` | 120 | Historical name: active **workflows** in one process, not internal Haiku/Sonnet invokes |
| `SYNC_THREADPOOL_TOKENS` | 120 | AnyIO default worker-thread limiter for sync FastAPI routes |

Enforcement order under one lock: notebook → user → RPM → global. Same-key
idempotency replays/waiters still do **not** acquire slots. Release is in a
`finally` on both user and notebook counters.

#### Main files changed

- `backend/rate_limit.py`, `backend/settings.py`, `backend/coaching/execution.py`
- `backend/http/app.py`, `backend/operational_metrics.py`
- `compose.prod.yaml`, `.env.example`
- Tests: `tests/http/test_rate_limit.py`, `tests/http/test_coach_concurrency.py`,
  `tests/http/test_threadpool.py`, `tests/scripts/test_load_probe.py`,
  `tests/test_deployment_config.py`, `tests/conftest.py`
- `scripts/load_probe.py`, `docs/operations/LOAD_PROBE.md`, this file

#### Validation evidence

- `ruff check` on the concurrency patch files: **passed**.
- `compileall` for `backend`, `ui`, `streamlit_app.py`, `tests`, `scripts`: **passed**.
- Focused: `tests/http/test_rate_limit.py`, `tests/http/test_coach_concurrency.py`,
  `tests/http/test_threadpool.py`, `tests/scripts/test_load_probe.py`,
  `tests/test_deployment_config.py`, `tests/persistence/test_coach_idempotency.py`,
  `tests/http/test_production_config.py`: **passed**.
- Full mock pytest: **passed** (exit 0; 860 tests collected).
- AgentCore runtime compatibility diagnostic: **not re-run** (unaffected; no
  runtime/prompt/model changes).
- Docker Compose config: **not executed** (`PUBLIC_ORIGIN` is required on the
  host; daemon/env not used for this patch).
- No live AWS, AgentCore, or Bedrock calls.

#### Production readiness (do not collapse these)

- **CODE READY:** YES for this limiter/threadpool patch (mock suite green).
- **MOCK CONCURRENCY TESTED:** YES (unit + HTTP + mock load-probe scenarios).
- **CI READY:** YES for deterministic mock CI; image rebuild still required
  before EC2 picks up the code.
- **LIVE LOAD TESTED:** **NO** — requires staged CloudFront/AgentCore test
  (2 → 5 → 10 → 25 concurrent real students).
- **PRODUCTION READY:** **NO** — live load, five-stage walk, ~105s UI timeout,
  and AgentCore/Bedrock quotas remain separate gates.

#### Next exact action

1. Build/push a new ARM64 app image that includes this code, then recreate
   the production app container so Compose injects the new capacity env vars.
   Do **not** apply the Compose env vars onto the previous image: old code
   has no notebook key, so `MAX_ACTIVE_COACH_REQUESTS_PER_USER=2` would allow
   two overlapping turns in the **same** notebook.
2. No AgentCore republish. Keep `AGENTCORE_QUALIFIER=DEFAULT` (v19) and
   Guardrail v3.
3. Staged live concurrency: 2, then 5, then 10, then 25 students.
4. Remaining separate gates: five-stage CloudFront walk, Streamlit/CloudFront
   timeout, Incremental Review fail-closed follow-up.

### Previous phase — Strands structured-output repair prompt (Guardrail PROMPT_ATTACK false positive)


**Runtime published 2026-08-16.** Same ARN
`NUSCodesignChatbot_chatbot_harnessAgent-6ncEO79sD7`. No second runtime.
`DEFAULT` is **version 19 READY**. Production Compose and the EC2 host
`.env` use `AGENTCORE_QUALIFIER=DEFAULT` (currently liveVersion 19) and
`GUARDRAIL_VERSION=3`. Guardrail v3
(`NUSCodesignChatbotGuardrail` `o8aipba8m129`) is **unchanged**. Model
assignments are **unchanged** (Haiku 4.5 router/Q&A/coaching/incremental;
Sonnet 4.6 deep). Incremental Review remains fail-closed. Frontend timeout
handling is unchanged. This is **not** production-ready: the live five-stage
CloudFront walk and ~105–117s timeout remain separate gates.

Artifact:
`s3://cdk-hnb659fds-assets-355604674280-us-west-2/agentcore-patches/chatbot_harnessAgent-repair-prompt-v19-20260816T101413Z.zip`

#### Root cause

All Bedrock roles use Strands `structured_output_model`. If a model first
responds in prose, Strands enters a forced structured-output repair turn.
The default Strands repair instruction was classified as `PROMPT_ATTACK`
by Guardrail v3 when it was the latest scanned message
(`guardrail_latest_message=True`). That produced
`stop_reason=guardrail_intervened` / `failure_category=safety_blocked`
during Haiku Incremental Review. The student message was not the cause:
Coaching had already succeeded on the same content.

#### Fix

Shared custom repair prompt on `Agent.invoke_async(...)` for every
structured Bedrock role (Router, Q&A, Coaching, Incremental Review, Deep
Review):

`structured_output_prompt="Please use the output tool now."`

Constant: `STRUCTURED_OUTPUT_REPAIR_PROMPT` in
`agentcore_runtime/structured_coach.py`. Not set on `BedrockModel()`.

This code fix alone does **not** make the CloudFront path production ready.
The live five-stage walk and the ~105–117s Streamlit/CloudFront timeout
remain separate gates. Incremental Review fail-closed behavior is also
still a separate follow-up.

#### Main files changed

- Runtime: `agentcore_runtime/structured_coach.py`,
  `agentcore_runtime/main.py`, `agentcore_runtime/README.md`
- Tests: `tests/domain/test_agentcore_runtime.py`,
  `tests/domain/test_runtime_model.py`
- Diagnostic: `scripts/diagnostics/check_agentcore_runtime_dependencies.py`
- Docs: this file, `docs/providers/AGENTCORE_ADAPTER.md`,
  `docs/SECURITY_BOUNDARIES.md`, `scripts/AGENTS.md`

#### Validation evidence

- Strands `1.52.0` `Agent.invoke_async` parameters include
  `structured_output_prompt` (installed pin inspection in a clean venv).
- `ruff check .`: **passed**.
- `compileall` for `backend`, `ui`, `streamlit_app.py`, `tests`,
  `scripts`, `agentcore_runtime`: **passed**.
- Focused runtime tests (`test_agentcore_runtime.py`,
  `test_runtime_model.py`, `test_agentcore_provider.py`,
  `test_agentcore_specialists.py`): **passed**.
- Full mock pytest: **passed** (exit 0; 833 tests collected).
- AgentCore runtime compatibility diagnostic (`strands-agents==1.52.0`,
  `bedrock-agentcore==1.21.0`, `pydantic==2.13.4`,
  `structured_output_model=present`, `structured_output_prompt=present`):
  **passed**.
- Docker daemon was **down**, so Compose config, Caddy validate, and image
  build were **not executed**.
- No existing safe ApplyGuardrail diagnostic script was present; live
  ApplyGuardrail was **not** added and **not** run.
- Live AgentCore republish: **version 19 READY**. `DEFAULT` `liveVersion`
  **19**. Env copied from v18 (Haiku lightweight roles, Sonnet Deep Review,
  `GUARDRAIL_ID=o8aipba8m129`, `GUARDRAIL_VERSION=3`).
- Packaged zip contains
  `structured_output_prompt=STRUCTURED_OUTPUT_REPAIR_PROMPT` and
  `Please use the output tool now.` Site-packages from v18 were preserved
  (`strands-agents` / `pydantic` present).
- Live Incremental Review retest after publish was **not** run in this
  step. Timeout and fail-closed Incremental Review are unchanged.
- Production env 2026-08-16: host `.env` and `compose.prod.yaml` use
  `AGENTCORE_QUALIFIER=DEFAULT` and `GUARDRAIL_VERSION=3`. DEFAULT
  liveVersion remains **19**. App container recreated after the qualifier
  change. Caddy was not recreated.

#### Next exact action

1. Retest one Incremental Review path that previously hit the structured-output
   repair cycle (CloudWatch should show Haiku incremental, not `safety_blocked`
   from the Strands repair instruction).
2. Remaining separate gates: live five-stage CloudFront walk, Streamlit /
   CloudFront timeout, Incremental Review fail-closed follow-up, EC2 image
   cutover. Do not mark production ready from this pin alone.
3. Rollback if needed: set `AGENTCORE_QUALIFIER=18` on host `.env` and
   `compose.prod.yaml`, recreate the app container; or
   `update-agent-runtime` with the v18 zip
   `agentcore-patches/chatbot_harnessAgent-haiku-sonnet-v18-20260816T082420Z.zip`.
   Do not delete old versions.

### Previous phase — Three pedagogical agents + Haiku 4.5 / Sonnet 4.6 (DEFAULT v18)

**Runtime published 2026-08-16.** Same ARN
`NUSCodesignChatbot_chatbot_harnessAgent-6ncEO79sD7`. No second runtime.
`DEFAULT` is **version 18 READY**. FastAPI + DSQL remain authoritative. LLMs
never mutate stage or DSQL.

Lightweight roles use Claude Haiku 4.5 on Strands `BedrockModel`. Deep
Review stays Claude Sonnet 4.6. GPT-5.6 Luna / Bedrock Mantle remains
supported as a historical provider pair for rollback versions; it is not
the active production path.

The Stage Judge is not the readiness authority. Deep Review (Sonnet)
performs the final pedagogical readiness assessment. Incremental Review
(Haiku) keeps the Review projection current after Coaching.

Artifact:
`s3://cdk-hnb659fds-assets-355604674280-us-west-2/agentcore-patches/chatbot_harnessAgent-haiku-sonnet-v18-20260816T082420Z.zip`

#### Model assignment

| Role | Provider | Model |
|---|---|---|
| Router (not a pedagogical agent) | `bedrock` | `global.anthropic.claude-haiku-4-5-20251001-v1:0` |
| Q&A Agent | `bedrock` | `global.anthropic.claude-haiku-4-5-20251001-v1:0` |
| Coaching Agent | `bedrock` | `global.anthropic.claude-haiku-4-5-20251001-v1:0` |
| Review Agent — incremental | `bedrock` | `global.anthropic.claude-haiku-4-5-20251001-v1:0` |
| Review Agent — deep | `bedrock` | `global.anthropic.claude-sonnet-4-6` |

There is no silent Haiku↔Sonnet substitution and no Luna fallback.

#### Periodic Deep Review

Unchanged: every N newly executed, successful Coaching turns since the
previous successfully persisted Deep Review (`DEEP_REVIEW_INTERVAL_TURNS=3`).
The Review tab remains display-only: zero model calls.

#### Behavior delivered

1. Haiku router selects `qa` | `coaching` | `review`. Browser specialist
   hints are dropped. Router failure/timeout/malformed/low confidence
   falls back to Coaching. Safety blocks do not fallback.
2. Successful Coaching always runs Incremental Haiku Review once.
   Incremental Review cannot advance. Incremental failure fails the turn.
3. Deep Sonnet Review runs on periodic N, readiness candidate, Reflection
   checkpoint, or explicit Review. Explicit Review skips Coaching and
   Incremental Review.
4. Q&A never runs Incremental or Deep Review and does not increment the
   counter.
5. Mock CI Compose step now sets `PUBLIC_ORIGIN` and `APP_IMAGE` for both
   Compose files.

#### Main files changed

- Runtime: `agentcore_runtime/model.py`, `agentcore_runtime/main.py`,
  `agentcore_runtime/README.md`
- Backend: `backend/agentcore_provider.py`, `backend/settings.py`,
  `backend/specialists/routing.py`, `backend/coaching/execution.py`
- Compose/env: `compose.yaml`, `compose.prod.yaml`, `.env.example`
- Tests: `tests/domain/test_runtime_model.py`,
  `tests/http/test_production_config.py`, `tests/test_deployment_config.py`
- CI: `.github/workflows/mock-ci.yml`
- Docs: this file, `docs/providers/AGENTCORE_ADAPTER.md`,
  `docs/PROMPT_ARCHITECTURE.md`, `docs/deploy/AWS_STATELESS_EC2.md`,
  `docs/SECURITY_BOUNDARIES.md`

#### Validation evidence

- `ruff check .`: **passed**.
- Shell syntax (`start.sh`, `build.sh`, `start_prod.sh`, `deploy_ecr.sh`,
  `browser_e2e_smoke.sh`): **passed**.
- `compileall` for `backend`, `ui`, `streamlit_app.py`, `tests`,
  `scripts`, `agentcore_runtime`: **passed**.
- Production/deployment config tests: **passed**.
- Ownership/idempotency gates: **passed**.
- Full mock pytest: **passed** (exit 0; 825 tests collected).
- AgentCore runtime compatibility diagnostic (`strands-agents==1.52.0`,
  `bedrock-agentcore==1.21.0`, `pydantic==2.13.4`, Haiku and Sonnet
  `BedrockModel` kwargs, `structured_output_model` present): **passed**.
- Docker daemon was **down**, so Compose config, Caddy validate, and image
  build were **not executed**.
- Haiku 4.5 inference profile
  `global.anthropic.claude-haiku-4-5-20251001-v1:0` in `us-west-2`: **ACTIVE**,
  `AUTHORIZED` / `AVAILABLE`.
- AgentCore `DEFAULT` **v18 READY** (AWS-verified 2026-08-16). v14–v17 remain
  READY and were not deleted.
- Live Router Haiku: Week 2 → `qa` (0.95); caregivers → `coaching` (0.92);
  “Can you review my progress?” → `review` (0.95).
- Live Q&A Haiku: STAY; no Deep Review.
- Live Coaching Haiku + Incremental Haiku (`provider.assess`): STAY,
  `review_depth=incremental`.
- Live explicit Deep Review Sonnet: STAY, `deep_review_succeeded=true`.
- CloudWatch provenance:
  `role=router provider=bedrock model_id=global.anthropic.claude-haiku-4-5-20251001-v1:0`;
  same Haiku id for `qa`, `coaching`, `review_incremental`;
  `role=review_deep provider=bedrock model_id=global.anthropic.claude-sonnet-4-6`.
- Guardrail: AWS example credential fixture → `safety_blocked`. Caregiver
  Singapore coaching/incremental was not blocked and had no `{ADDRESS}`.
- Live FastAPI `CoachApplicationService.submit` three-turn periodic sequence
  **failed closed** twice at Incremental Review (`safety_blocked`) on the
  richer application payload. Periodic counter semantics remain covered by
  mock tests. Stopped after two live attempts.
- GitHub Mock CI is **not green** on this SHA: changes are uncommitted.
- EC2 / CloudFront E2E were **not** run. Host compose remains stale until
  CI is green and the app image is recreated.

#### Next exact action

1. Commit/push only when authorized so Mock CI can go green.
2. After CI is green, recreate the EC2 app container from the current
   five-role `compose.prod.yaml` and a new immutable image. Do not reuse
   the stale host Compose.
3. Optionally re-run the three-turn FastAPI periodic sequence after EC2
   cutover, using a student notebook rather than a local SQLite submit
   that already failed closed twice.
   Rollback remains **version 14** (Sonnet-only) or **v17** (Luna/Sonnet)
   if needed. Do not delete old versions.

### Previous phase — Three pedagogical agents + Luna router (DEFAULT v17)

**Runtime published 2026-08-16.** Same ARN
`NUSCodesignChatbot_chatbot_harnessAgent-6ncEO79sD7`. No second runtime.
`DEFAULT` is **version 17 READY**. FastAPI + DSQL remain authoritative. LLMs
never mutate stage or DSQL.

The Stage Judge is no longer the readiness authority. Deep Review (Sonnet)
performs the final pedagogical readiness assessment. Incremental Review
(Luna) keeps the Review projection current after Coaching.

Luna live inference is **not available on this AWS account**
(`openai.gpt-5.6-luna is not available for this account`). Router, Q&A,
Coaching, and Incremental Review live smokes therefore failed closed. Deep
Review live smoke on Claude Sonnet 4.6 succeeded. Do not treat DEFAULT v17
as student-ready until Bedrock enables GPT-5.6 Luna. This phase is superseded
by the Haiku 4.5 lightweight migration above.

#### Model assignment

| Role | Model |
|---|---|
| Router (not a pedagogical agent) | GPT-5.6 Luna |
| Q&A Agent | GPT-5.6 Luna |
| Coaching Agent | GPT-5.6 Luna |
| Review Agent — incremental | GPT-5.6 Luna |
| Review Agent — deep | Claude Sonnet 4.6 |

#### Periodic Deep Review

Periodic Deep Review means every N newly executed, successful Coaching
turns since the previous successfully persisted Deep Review. It is
turn-based rather than time-based because it represents new learning
evidence, not elapsed time. Configured by `DEEP_REVIEW_INTERVAL_TURNS`
(default 3). The counter `coaching_turns_since_deep_review` lives in
notebook settings and resets to 0 only after a Deep Review result is
validated and persisted. Failed Deep Review fails closed to STAY and
keeps the checkpoint due.

Event overrides (explicit Review, `readiness_candidate`, Reflection
checkpoint) run Deep Review immediately. The Review tab remains
display-only: zero model calls.

#### Behavior delivered

1. Luna router selects `qa` | `coaching` | `review`. Browser specialist
   hints are dropped. Router failure/timeout/malformed/low confidence
   falls back to Coaching.
2. Successful Coaching always runs Incremental Luna Review once. Incremental
   Review cannot advance the stage. Incremental failure fails the turn
   (no persist).
3. Deep Sonnet Review runs on periodic N, readiness candidate, Reflection
   checkpoint, or explicit Review. Explicit Review skips Coaching and
   Incremental Review.
4. Q&A never runs Incremental or Deep Review and does not increment the
   counter.
5. Deep Review may recommend stay/advance; FastAPI still owns the
   transition pipeline. Malformed/timeout/unavailable/wrong-stage Deep
   Review fails closed to STAY.

#### Main files changed

- Runtime: `agentcore_runtime/main.py`, `model.py`, `models.py`,
  `specialists/routing.py`, `prompts/review_incremental.md`,
  `prompts/review_deep.md`
- Backend: `backend/agentcore_provider.py`,
  `backend/specialists/review_orchestration.py`,
  `backend/coaching/execution.py`, `backend/workflow.py`,
  `backend/settings.py`, `backend/domain.py`
- Tests: `tests/domain/test_review_agent.py`,
  `tests/domain/test_hybrid_agentcore.py`, `tests/fake_agentcore_runtime.py`
- Docs/env: `.env.example`, compose files, this file,
  `docs/providers/AGENTCORE_ADAPTER.md`, `docs/PROMPT_ARCHITECTURE.md`,
  `docs/deploy/AWS_STATELESS_EC2.md`

#### Validation evidence

- Focused AgentCore/review tests: **passed**.
- Full mock pytest: **passed** (exit 0; 822 tests on 2026-08-16 readiness pass).
- `compileall` for `backend`, `ui`, `streamlit_app.py`, `tests`,
  `scripts`, `agentcore_runtime`: **passed**.
- `ruff check .`: **passed** locally after removing an unused `FakeBody`
  import in `tests/domain/test_agentcore_provider.py`. GitHub Mock CI on
  `af04f11` failed that Ruff check only; `agentcore-runtime-compatibility`
  succeeded.
- Periodic counter is recomputed inside `persist_coach_turn` from the
  notebook `settings_text` row, and the notebook `updated_at` is part of
  the UPDATE CAS predicate. A stale pre-provider snapshot cannot overwrite
  a newer count. Concurrent overlapping persists either serialize to 1 then
  2, or one writer loses the CAS and rolls back.
- Adversarial review: no confirmed production defects. Residual: runtime
  still shares legacy `AGENTCORE_MODEL_*` when **no** role keys are set.
- AgentCore `DEFAULT` **v17 READY** (last AWS-verified 2026-08-16 before
  this readiness pass). Artifact
  `agentcore-patches/chatbot_harnessAgent-review-depths-v17-20260816T064539Z.zip`.
- Guardrail `o8aipba8m129` version **3** READY (last AWS-verified 2026-08-16).
- Live Deep Review (Sonnet, explicit): **passed** on that earlier pass
  (STAY; Singapore kept; no `{ADDRESS}`).
- Live Luna router / coaching / incremental: **failed** on that earlier
  pass (account model access). CloudWatch loaded the correct per-role
  models (no Luna↔Sonnet swap).
- This readiness pass could not re-query AWS, EC2, or Knowledge Base:
  local AWS SSO session expired (`aws login` required). Docker daemon was
  down, so Caddy validate and image build were not executed. CloudFront UI
  / Review-tab live path was not exercised. Periodic three-turn live
  sequence was not executed.

#### Next exact action

Reauthenticate AWS SSO (`aws login`), then re-verify AgentCore DEFAULT,
Guardrail 3, Managed KB `course/` retrieval, and Luna account access.
Push the local Ruff + counter-CAS fixes so Mock CI can go green on a new
SHA. Recreate the EC2 app container only after Luna is enabled and CI is
green. Rollback remains **version 14** (Sonnet-only generation) if
students need a working coach today. Do not delete v15, v16, or v17.

### Previous phase — Hybrid Luna router + Sonnet Stage Judge (DEFAULT v16)

**Runtime published 2026-08-16.** Same ARN
`NUSCodesignChatbot_chatbot_harnessAgent-6ncEO79sD7`. No second runtime.
`DEFAULT` is **version 16 READY**. FastAPI + DSQL remain authoritative.

Luna live inference is **not available on this AWS account**
(`openai.gpt-5.6-luna is not available for this account`). Router, Q&A, and
Coaching live smokes therefore failed closed. Review and Stage Judge live
smokes on Claude Sonnet 4.6 succeeded. Do not treat DEFAULT v16 as
student-ready until Bedrock enables GPT-5.6 Luna.

#### Behavior delivered

1. Free-text routing is GPT-5.6 Luna (`router_turn`). Server-owned specialist
   or review surface still bypasses the router. Browser specialist hints are
   dropped. Router failure/timeout/malformed/low confidence falls back to
   coaching. Guardrail-blocked router input fails the turn.
2. Per-role models on one runtime: router/QA/coaching = Luna; review/stage
   judge = Claude Sonnet 4.6. No silent Luna↔Sonnet substitution.
3. Coaching ADVANCE is a candidate only. Sonnet Stage Judge confirms or
   returns STAY. Judge failure fails closed to STAY. Q&A and Review still
   force STAY and never call the judge.
4. Research coding remains observational and is not sent to the Stage Judge.
5. Runtime role now has non-CDK
   `ManualMantleInferenceAccess-NotCDKManaged`
   (`bedrock-mantle:CreateInference` on `project/default` plus
   `bedrock-mantle:CallWithBearerToken`). After that grant, Luna still
   returns account-level model unavailability.

#### Main files changed

- Runtime: `agentcore_runtime/model.py`, `main.py`, `models.py`, `router.py`,
  `stage_judge.py`, `prompts/router.md`, `prompts/stage_judge.md`
- Backend: `backend/agentcore_provider.py`, `backend/specialists/routing.py`,
  `backend/coaching/execution.py`, `backend/settings.py`
- Tests: `tests/domain/test_hybrid_agentcore.py`, routing/model/provider/
  production/deployment tests
- Docs/env: `.env.example`, compose files, this file,
  `docs/providers/AGENTCORE_ADAPTER.md`

#### Validation evidence

- Full mock pytest: **passed**.
- AgentCore `DEFAULT` **v16 READY**. Artifact
  `agentcore-patches/chatbot_harnessAgent-hybrid-v16-20260816T053702Z.zip`.
- Guardrail `o8aipba8m129` version **3** READY.
- Live Review + Stage Judge (Sonnet): **passed** (forced STAY; judge STAY).
- Live credential guardrail: **safety_blocked**.
- Live Luna router/QA/coaching: **failed** (account model access).
- EC2 was not restarted. CloudFront UI hybrid path was not exercised.

#### Next exact action

Enable GPT-5.6 Luna for account `355604674280` in `us-west-2` (Bedrock model
access / AWS Sales). Then rerun capped Luna smokes. Until then, production
coaching/QA/router on DEFAULT v16 will fail closed. Rollback to **version 14**
(Sonnet-only, known-good generation) if students need a working coach today.
Do not delete v15 or v16.

### Previous phase — AgentCore DEFAULT v15 Luna + guardrail version 3

**Completed on 2026-08-16.** Same runtime ARN
`NUSCodesignChatbot_chatbot_harnessAgent-6ncEO79sD7`. No second runtime.
`DEFAULT` is **version 15 READY**. Guardrail id unchanged; version skipped
from 1 to **3**. Generation model is GPT-5.6 Luna. No live paid smoke in
this pass.

#### Behavior delivered

1. AgentCore runtime env is now
   `AGENTCORE_MODEL_PROVIDER=bedrock_mantle_responses`,
   `AGENTCORE_MODEL_ID=openai.gpt-5.6-luna`,
   `AGENTCORE_MODEL_REGION=us-west-2`, `GUARDRAIL_ID=o8aipba8m129`,
   `GUARDRAIL_VERSION=3`. Gateway and Memory env keys were preserved.
2. Published zip is v14 linux/arm64 Python 3.14 site-packages plus the Luna
   extra (`openai`, `jiter` aarch64 cp314, `distro`, `sniffio`, `tqdm`,
   `aws_bedrock_token_generator`) and current `agentcore_runtime/` sources.
   Entrypoint remains `opentelemetry-instrument main.py`.
3. Local and production Compose pin Luna + `GUARDRAIL_VERSION=3`. Guardrail
   **id** stays in host `.env` (not interpolated). FastAPI fail-closed env
   must match the runtime.

#### Main files changed

- `compose.yaml`, `compose.prod.yaml`, `.env.example`
- `agentcore_runtime/requirements.txt`, `agentcore_runtime/README.md`,
  `agentcore_runtime/model.py`
- Tests: `tests/test_deployment_config.py`
- Docs: this file, `docs/providers/AGENTCORE_ADAPTER.md`,
  `docs/deploy/AWS_STATELESS_EC2.md`

#### Validation evidence

- Focused pytest `tests/test_deployment_config.py`
  `tests/domain/test_runtime_model.py`
  `tests/http/test_production_config.py`: **passed**.
- `compileall` for `backend`, `ui`, `streamlit_app.py`, `tests`, `scripts`,
  `agentcore_runtime`: **passed**.
- `get-agent-runtime`: status READY, version **15**, Luna + guardrail 3.
- `DEFAULT` endpoint: READY, `liveVersion` **15**.
- Guardrail `o8aipba8m129` version 3: READY. Version 2 was not used.

#### Compatibility, migration, and rollback

- No schema change. ARN unchanged. `DEFAULT` auto-moved on
  `update-agent-runtime`.
- Rollback is another `update-agent-runtime` with the v14 zip
  `agentcore-patches/chatbot_harnessAgent-sonnet46-v14-20260815T193913Z.zip`
  and the previous Sonnet + `GUARDRAIL_VERSION=1` env.
- Live artifact:
  `s3://cdk-hnb659fds-assets-355604674280-us-west-2/agentcore-patches/chatbot_harnessAgent-luna-v15-20260816T044445Z.zip`

#### Known risks and next exact action

- Recreate the EC2 app container so FastAPI Compose env matches Luna +
  guardrail 3. Runtime DEFAULT already serves Luna; a stale container still
  advertises Sonnet in its own process env.
- Luna uses ApplyGuardrail, not `BedrockModel` constructor fields. Do not
  pass `openai.gpt-5.6-luna` into `BedrockModel`.
- Next paid check is a capped Luna smoke only if explicitly approved:
  `PYTHONPATH=. .venv/bin/python scripts/agentcore_smoke.py --i-approve-live-agentcore --cost-cap 1.00 --max-requests 1`.

### Previous phase — Production Knowledge Base Retrieve diagnosis and adapter fix

**Completed locally on 2026-08-16.** Integrate-Bedrock HEAD
`8b0d5f06e80f78efaf277dd8c3f8f7899fe0b4a2`. AgentCore / Sonnet / Q&A routing
were not the failure. Shared course files still use Bedrock Knowledge Base
**Retrieve only**. Exact S3 key validation is unchanged. No local fallback
for production `course/` objects.

#### Root cause (proved)

1. Knowledge Base `JUQNP8AZAZ` is type **MANAGED** and **ACTIVE**. The adapter
   always sent `vectorSearchConfiguration`. Live Retrieve raised
   `ValidationException` on both filtered and unfiltered calls, which the
   previous broad `except Exception` logged only as
   `course_retrieval_unavailable`.
2. After switching to `managedSearchConfiguration`, unfiltered Retrieve
   returned 8 hits whose locations are
   `CDE2300_course_files_export/Course_materials/Week 1 Introduction to innovation v3.pdf`.
   The catalog selects `course/lectureNotes/Week 1 Introduction to innovation v3.pdf`.
   Exact-key validation correctly discarded every hit. Both objects exist in
   S3 (same size). The data source prefix is wrong, not the PDF.

#### Behavior delivered

1. Retrieve failures are classified (`access_denied`, `not_found`,
   `validation_error`, `timeout`, `throttled`, `client_error`,
   `config_missing`) without logging secrets.
2. Metadata-filter `ValidationException` retries unfiltered Retrieve when
   strict mode is off; exact-key validation still applies.
3. Production Compose sets `KNOWLEDGE_BASE_TYPE=MANAGED` so Retrieve uses
   `managedSearchConfiguration`.
4. HTTPS S3 locations are parsed into bucket+key. Suffix matching is still
   forbidden.
5. Gated diagnostic
   `scripts/diagnostics/check_knowledge_base_retrieve.py` prints secret-safe
   JSON and refuses live AWS by default.

#### Main files changed

- `backend/bedrock_retrieve.py`, `backend/retrieval.py`, `backend/settings.py`,
  `compose.prod.yaml`, `.env.example`
- `scripts/diagnostics/check_knowledge_base_retrieve.py`,
  `scripts/diagnostics/test_course_retrieval.py`
- Tests: `tests/domain/test_bedrock_retrieve.py`,
  `tests/test_deployment_config.py`, `tests/http/test_production_config.py`,
  `tests/scripts/test_agentcore_course_cli.py`
- Docs: `docs/RAG_ARCHITECTURE.md`, `docs/deploy/AWS_STATELESS_EC2.md`

#### Validation evidence

- `ruff check .`: **passed**.
- `compileall` for `backend`, `ui`, `streamlit_app.py`, `tests`, `scripts`,
  `agentcore_runtime`: **passed**.
- Full deterministic pytest: **768 passed** (`pytest -q`).
- `docker compose config --quiet` and production Compose with
  `PUBLIC_ORIGIN=https://example.invalid APP_IMAGE=co-design:test`: **passed**.
- Live Retrieve (account root, `--i-approve-live-bedrock --max-requests 2`):
  MANAGED search works; validated count 0 until the data source indexes
  `course/`.

#### Compatibility, migration, and rollback

- No schema change. Rollback is reverting this working tree.
- Production must deploy this image **and** re-point/sync the Knowledge Base
  data source to `s3://cde2300-course-content-s3/course/`.

#### Known risks and next exact action

- Deploying the adapter without re-ingesting `course/` yields
  `course_retrieval_empty` (raw hits, zero validated), not a grounded Week 1
  citation.
- Next: on EC2, pull this image, confirm container env includes
  `KNOWLEDGE_BASE_TYPE=MANAGED`, run the gated diagnostic, then in the AWS
  console set the KB data source prefix to `course/` and sync.

### Previous phase — Publish vendored AgentCore DEFAULT v14 and capped Sonnet smoke


**Completed on 2026-08-16.** Same runtime ARN
`NUSCodesignChatbot_chatbot_harnessAgent-6ncEO79sD7`. No second runtime.
`DEFAULT` is **version 14 READY**. One capped live smoke returned
`{"ok": true, "stage": "problem_identification", "recommendation": "stay"}`.

v11 was source-only (AgentCore does not pip-install `requirements.txt`).
v12 vendored linux/arm64 cp314 wheels but `main.py` never called `app.run()`,
so the process imported and exited (HTTP 502). v13 reused the last working
v9 site-packages zip plus current sources and OTEL entrypoint; it started,
then exited for the same missing `app.run()`. v14 is that zip with
`if __name__ == "__main__": app.run()`.

#### Behavior delivered

1. Live artifact is a ~47MB zip: v9 linux/arm64 Python 3.14 site-packages
   (pydantic 2.13.4, strands-agents 1.52.0, bedrock-agentcore 1.21.0,
   aws-opentelemetry-distro) plus current `agentcore_runtime/` sources at zip
   root. Entrypoint `opentelemetry-instrument main.py`.
2. Runtime env unchanged except already-set Sonnet 4.6 + guardrail keys:
   `AGENTCORE_MODEL_PROVIDER=bedrock`,
   `AGENTCORE_MODEL_ID=global.anthropic.claude-sonnet-4-6`,
   `AGENTCORE_MODEL_REGION=us-west-2`, `GUARDRAIL_ID=o8aipba8m129`,
   `GUARDRAIL_VERSION=1`.
3. `agentcore_runtime/main.py` now starts `BedrockAgentCoreApp` when executed
   as `__main__`.

#### Main files changed

- `agentcore_runtime/main.py`, `agentcore_runtime/README.md`
- Tests: `tests/domain/test_agentcore_runtime.py` asserts `app.run()`
- Docs: this file, `docs/providers/AGENTCORE_ADAPTER.md`

#### Validation evidence

- Focused pytest `tests/domain/test_agentcore_runtime.py`
  `test_runtime_model.py` `test_security_invariants.py`: **passed**.
- `PYTHONPATH=. .venv/bin/python scripts/agentcore_smoke.py
  --i-approve-live-agentcore --cost-cap 1.00 --max-requests 1`: **passed**
  (`ok: true`, stage `problem_identification`, recommendation `stay`).
- `get-agent-runtime`: status READY, version **14**.
- `DEFAULT` endpoint: READY, `liveVersion` **14**.
- CloudWatch v13 showed OTEL + IAM credentials then silence (process exit).
  v11 showed `ModuleNotFoundError: pydantic` (source-only zip).

#### Compatibility, migration, and rollback

- No schema change. ARN unchanged. `DEFAULT` auto-moved on each successful
  `update-agent-runtime` (preprod, accepted).
- Rollback is another `update-agent-runtime` with the v9 zip
  `agentcore-patches/chatbot_harnessAgent-structured-coach-21a5896f90b517ba8bc7843a8b5be5f5b12e33cf9c7130d81ca5c6dcb949685d.zip`
  or a new zip built the same way from that base.
- Live artifact:
  `s3://cdk-hnb659fds-assets-355604674280-us-west-2/agentcore-patches/chatbot_harnessAgent-sonnet46-v14-20260815T193913Z.zip`

#### Known risks and next exact action

- This is **preprod**. Do not call the app student-ready until host `.env`,
  ECR/`APP_IMAGE`, and CloudFront/Caddy alignment are done.
- Next: fill the EC2/host `.env` with the existing ARN + `AGENTCORE_QUALIFIER=DEFAULT`,
  keep `MODEL_PROVIDER=agentcore`, then build/push `APP_IMAGE` if that is the
  remaining cutover blocker. Do not invoke unbounded Streamlit chat as the
  next paid test.

### Previous phase — AgentCore runtime dependency reproducibility

**Completed locally on 2026-08-16.** Integrate-Bedrock HEAD at start of this
pass: `529716c46fa45d20cdba02a145f6d63f088629b8`. This pass proved the
AgentCore runtime pins are installable from PyPI in a clean CPython 3.12.10
venv, locked them as exact versions, and added a network-free compatibility
diagnostic plus a GitHub job that actually installs
`agentcore_runtime/requirements.txt`. Architecture, specialists, Sonnet 4.6,
and guardrails are unchanged. No live AWS or paid model calls.

#### Behavior delivered

1. Clean-venv `pip index` + install confirmed `strands-agents==1.52.0`,
   `bedrock-agentcore==1.21.0`, and `pydantic==2.13.4` are available together.
2. Installed Strands 1.52.0 exposes `Agent.invoke_async(...,
   structured_output_model=...)`, `AgentResult.structured_output`,
   `BedrockModel` guardrail kwargs including `guardrail_latest_message`,
   `tools=[]`, and Converse `messages`. `BedrockAgentCoreApp` + `@app.entrypoint`
   construct without AWS.
3. `scripts/diagnostics/check_agentcore_runtime_dependencies.py` inspects
   those APIs, validates a synthetic `CoachTurnOutput`, and checks Sonnet
   constructor kwargs. It does not call AWS or `specialist_invoke()`.
4. Provenance constants in `agentcore_runtime/model.py` stay explicit (a
   .py-only copy must still report pins). Pytest fails if they drift from
   `agentcore_runtime/requirements.txt`.
5. Mock CI job `agentcore-runtime-compatibility` installs the runtime
   requirements on Python 3.12, runs the diagnostic, and compiles
   `agentcore_runtime`. Companion pytest remains Strands-free.

#### Main files changed

- `agentcore_runtime/requirements.txt`, `agentcore_runtime/model.py`
- `scripts/diagnostics/check_agentcore_runtime_dependencies.py`
- `.github/workflows/mock-ci.yml`
- Tests: `tests/domain/test_runtime_model.py` pin-sync assertions
- Docs: this file, AgentCore adapter, scripts/tests agent guides

#### Validation evidence

- Clean CPython 3.12.10 venv `/tmp/codesign-agentcore-runtime-fresh`:
  `pip install -r agentcore_runtime/requirements.txt` **succeeded**.
- `python scripts/diagnostics/check_agentcore_runtime_dependencies.py`:
  **passed** (Strands 1.52.0, bedrock-agentcore 1.21.0, pydantic 2.13.4;
  structured_output_model, AgentResult.structured_output, and
  guardrail_latest_message present; Sonnet id explicit; no AWS).
- Imports of `agentcore_runtime.main`, `.model`, `.models`, and
  `.structured_coach` succeeded. `specialist_invoke()` was not called.
- `compileall` for `backend`, `ui`, `streamlit_app.py`, `tests`, `scripts`,
  and `agentcore_runtime`: **passed**.
- Full deterministic suite: **737 passed, 0 failed, 0 skipped** (735 prior
  plus two pin-sync tests). Starlette/httpx deprecation warnings unchanged
  in kind.
- Focused AgentCore / RAG / ownership / stage files: **201 passed**.
- `ruff check .` (ruff 0.11.13): **passed**.
- `git diff --check`: **passed**.
- `docker compose config --quiet`: **passed**.
- `APP_IMAGE=co-design:test docker compose -f compose.prod.yaml config --quiet`:
  **passed**.
- GitHub Mock CI on committed HEAD `529716c`: mock-suite **success**
  (https://github.com/CloudKai/NUS-Codesign-Chatbot/actions/runs/31900754387).
  New job `agentcore-runtime-compatibility` is local-only until this change
  is pushed: **CI CONFIGURED — RUN NOT YET OBSERVED** for that job.
- No live AgentCore, Bedrock generation, OpenAI, KB Retrieve, DSQL, or S3
  calls. Runtime not republished. `AGENTCORE_RUNTIME_ARN` unchanged.

#### Compatibility, migration, and rollback

- No schema change. Five persisted stages unchanged. No runtime publish.
- `AGENTCORE_RUNTIME_ARN` unchanged. Do not promote DEFAULT until a new
  READY qualifier is tested with a capped Sonnet 4.6 smoke.

#### Known risks and next exact action

- Publish `agentcore_runtime/` onto
  `NUSCodesignChatbot_chatbot_harnessAgent-6ncEO79sD7` with explicit Sonnet
  4.6 + guardrail env, then one capped smoke. Not done in this pass.

### Previous phase — Explicit Sonnet 4.6 runtime model and guardrail fail-closed

**Completed locally on 2026-08-16.** Integrate-Bedrock HEAD at start of this
pass: `af79a693347a33ebbd9c92c5a33c297df70ce05b`. The runtime no longer
constructs a bare `BedrockModel()`. Production AgentCore requires explicit
`AGENTCORE_MODEL_PROVIDER` / `AGENTCORE_MODEL_ID` / `AGENTCORE_MODEL_REGION`
plus `GUARDRAIL_ID` / `GUARDRAIL_VERSION`. First paid evaluation remains
Sonnet 4.6. Luna is optional, stateless, and uses ApplyGuardrail. No live
AWS generation or runtime publish in this pass.

#### Behavior delivered

1. `agentcore_runtime/model.py` fail-closed loader. Bedrock path uses
   `guardrail_latest_message=True`. Luna cannot be passed to `BedrockModel`.
2. Mantle/Luna path: `OpenAIResponsesModel(stateful=False,
   bedrock_mantle_config={"region": ...})` plus ApplyGuardrail on input and
   output. Missing `strands-agents[openai]` does not fall back to Claude.
3. FastAPI production validation requires the same model and guardrail keys
   when `MODEL_PROVIDER=agentcore`.
4. Runtime pins: `strands-agents==1.52.0`, `bedrock-agentcore==1.21.0`,
   `pydantic==2.13.4` (companion-tested Pydantic; Strands/AgentCore pins are
   current documented PyPI versions, not yet installed in the companion venv).

#### Main files changed

- `agentcore_runtime/model.py`, `guardrails.py`, `main.py`, `requirements.txt`
- `backend/settings.py`, `backend/specialists/routing.py`
- Tests: `tests/domain/test_runtime_model.py` and production-config updates
- Docs: AgentCore adapter, security boundaries, methodology, implementation status

#### Validation evidence

- `compileall` for `backend`, `ui`, `streamlit_app.py`, `tests`, `scripts`,
  and `agentcore_runtime`: **passed**.
- Full deterministic suite: **735 passed, 0 failed, 0 skipped** in 32.10s.
  66 Starlette/httpx deprecation warnings.
- `ruff check .`: **passed** after removing unused imports (including
  pre-existing F401/F541/F811/E402 that would have failed CI).
- `git diff --check`: **passed**.
- `docker compose config --quiet`: **passed**.
- `APP_IMAGE=co-design:test docker compose -f compose.prod.yaml config --quiet`:
  **passed**.
- Live KB diagnostic: refused without `--i-approve-live-bedrock` (no Retrieve).
- No live AgentCore, Bedrock generation, or OpenAI calls. Runtime not
  republished. `AGENTCORE_RUNTIME_ARN` unchanged.

#### Compatibility, migration, and rollback

- No schema change. Five persisted stages unchanged.
- Live DEFAULT still needs this package published onto
  `NUSCodesignChatbot_chatbot_harnessAgent-6ncEO79sD7` with runtime env
  injected. Do not promote DEFAULT until READY and a capped Sonnet smoke.

#### Known risks and next exact action

- Confirm pins on the published runtime. Run the opt-in KB diagnostic, then a
  new READY qualifier, then a capped Sonnet 4.6 specialist test.
- Do not commit, push, or deploy from this phase unless asked.

### Previous phase — AgentCore specialist brain (POC pedagogy, production shell)

**Completed locally on 2026-08-16.** Integrate-Bedrock remains the production
application shell. Canonical Q&A, Coaching, and Formative Review pedagogy now
lives in `agentcore_runtime/`. FastAPI authorizes sources, retrieves evidence,
sends runtime rules, validates structured output, and persists DSQL state.
AgentCore Memory is not the transcript. Live AWS invokes were not made.

#### Behavior delivered

1. One AgentCore runtime, three specialists, deterministic `phase` selection.
   Unknown phases fall closed to coaching. Scoring was renamed Review and is
   not a grade. Ambiguous chat defaults to coaching.
2. Canonical prompts in `agentcore_runtime/prompts/` merge POC Socratic /
   Assumption Check / AT-EAI stage focus with Integrate-Bedrock V&V, CLEAR,
   Facione, HCTSR-aligned Reflection, and research independence.
3. FastAPI AgentCore payload sends `runtime_context` plus runtime instructions
   only. Stage curriculum is no longer duplicated on the trusted channel.
4. Strands structured output for `coach_turn`, `qa_turn`, and `review_turn`.
   DSQL history is passed as Strands `messages`. `tools=[]`.
5. Q&A uses pre-retrieved `[S#]` evidence. No KB/S3 tools. Review is on-demand
   from explicit student intent, not every turn.

#### Main files changed

- `agentcore_runtime/` specialists, prompts, contracts, `main.py`
- `backend/specialists/routing.py`, `backend/agentcore_provider.py`,
  `backend/coaching/execution.py`, `backend/mock_provider.py`,
  `backend/domain.py`
- Tests listed in `tests/AGENTS.md`
- Docs: prompt, RAG, security, AgentCore adapter, implementation status

#### Validation evidence

- `compileall` for `backend`, `ui`, `streamlit_app.py`, `tests`, `scripts`,
  and `agentcore_runtime`: **passed**.
- Full deterministic suite: **710 passed, 0 failed, 0 skipped** in ~30s.
  Existing Starlette/httpx deprecation warnings only.
- Ruff on files from this phase: **passed**.
- `git diff --check`: **passed**.
- `docker compose config --quiet`: **passed**.
- No live AgentCore, Bedrock generation, or OpenAI calls. Runtime not
  republished. `AGENTCORE_RUNTIME_ARN` unchanged.

#### Compatibility, migration, and rollback

- No schema change. Five persisted stages unchanged. `ethics_critical` remains
  an AgentCore topic key only.
- Live DEFAULT still needs this package published onto
  `NUSCodesignChatbot_chatbot_harnessAgent-6ncEO79sD7`. Copy the whole
  `agentcore_runtime/` tree. Rollback is the previous READY qualifier.
- `backend/prompts/` remains for mock/OpenAI/Bedrock Converse.

#### Known risks and next exact action

- Publish the runtime after approval, then one paid smoke. Do not run live
  specialist evaluation until that publish.
- Do not commit, push, or deploy from this phase unless asked.

### Previous phase — AgentCore structured coach_turn output (no str(AgentResult))

**Completed locally on 2026-08-16.** Live coaching could fail after
`await agent.invoke_async(prompt)` because the deployed harness did
`json.loads(str(result))`. `str(AgentResult)` is empty when
`structured_output` is absent and the final message has no text blocks, which
raises `JSONDecodeError` at char 0. The student contribution was not empty.
This is independent of the earlier `guardrail_intervened` / `PROMPT_ATTACK`
path; those trusted/untrusted and `safety_blocked` fixes stay.

Architecture is unchanged: DSQL transcript, full-history planner, RAG
authorization, AgentCore reasoning-only (`tools=[]`), five Thinking Path
stages, research independence, and atomic persist.

#### Behavior delivered

1. Canonical production harness lives in `agentcore_runtime/` (`models.py`,
   `structured_coach.py`, `main.py`). `scripts/agentcore/harness_patch/` is a
   re-export plus deploy notes.
2. Native Strands path: `invoke_async(..., structured_output_model=CoachTurnOutput)`
   then `result.structured_output`. Text-block JSON is a compatibility fallback.
   `str(result)` is never parsed.
3. Failures return `{ok: false, error: true, category: ...}`. The companion
   adapter maps that to `structured_output_failure` or `safety_blocked`.
   HTTP stays 503 with a category; students never see JSONDecodeError.
4. Idempotency still releases the lease on provider failure. Empty assistant
   bubbles are not opened until a validated reply exists; empty stored
   assistant rows are not rendered.
5. Stage advancement still requires a validated assessment. Short student
   text such as "A quiet residential street" is not treated as empty and is
   not hardcoded to ADVANCE.

#### Main files changed

- `agentcore_runtime/` (new canonical harness)
- `backend/agentcore_provider.py`, `backend/providers.py`
- `ui/panels/chat.py`
- `scripts/agentcore/harness_patch/`, `scripts/build.sh`
- Tests: `tests/domain/test_agentcore_runtime.py`,
  `tests/domain/test_agentcore_provider.py`,
  `tests/domain/test_agentcore_harness_provider.py`,
  `tests/http/test_api.py`, `tests/http/test_api_client.py`,
  `tests/ui/test_streamlit_ui.py`
- Docs: `docs/providers/AGENTCORE_ADAPTER.md`, `docs/CODEBASE_STRUCTURE.md`,
  `tests/AGENTS.md`, `scripts/AGENTS.md`, `backend/AGENTS.md`

#### Validation evidence

- `compileall` for `backend`, `ui`, `streamlit_app.py`, `tests`, `scripts`,
  and `agentcore_runtime`: **passed**.
- Full deterministic suite: **648 passed, 0 failed, 0 skipped** in ~27s.
  Existing Starlette/httpx deprecation warnings only (66).
- Ruff on files from this fix: **passed** except one pre-existing F811 in
  `tests/ui/test_streamlit_ui.py` (duplicate `StudentStore` import in an
  unrelated test).
- `git diff --check`: **passed**.
- No live AgentCore invoke. Runtime not republished. `AGENTCORE_RUNTIME_ARN`
  unchanged.

#### Compatibility, migration, and rollback

- No schema change. Companion still accepts a raw coach_turn JSON body.
- Live DEFAULT still runs the old `str(result)` harness until operators copy
  `agentcore_runtime/` onto
  `NUSCodesignChatbot_chatbot_harnessAgent-6ncEO79sD7` and publish a READY
  version. Do not point DEFAULT at an untested version.
- Rollback is reverting this working tree; live runtime rollback is the
  previous READY qualifier.

#### Known risks and next exact action

- Production blocker: publish the new harness version, then one approved
  smoke: `scripts/agentcore_smoke.py --i-approve-live-agentcore --cost-cap 1.00 --max-requests 1`,
  then the "A quiet residential street" regression.
- Do not change `AGENTCORE_RUNTIME_ARN`. Do not create another student runtime.
- Do not commit, push, or deploy from this phase unless asked.

### Previous phase — Virtual course sources must not become fake local evidence

**Completed locally on 2026-08-16.** Shared Week 1 catalog rows have empty
`extractedText` on purpose. When `KNOWLEDGE_BASE_ID` was missing, mock, or
`MOCK_OPENAI=true`, `configured_context_retriever()` returned
`LocalChunkRetriever`, which ranked the synthesized placeholder
`[This source is stored but has no analyzable text.]` because the Week 1
title matched the student question. That fake chunk reached AgentCore.

Architecture is unchanged: one shared S3 `course/` copy, virtual catalog
sources, Bedrock KB Retrieve only, student uploads local, FastAPI source
scope, DSQL transcript, AgentCore reasoning only.

#### Behavior delivered

1. Virtual/shared `course/` sources keep `text=""` for retrieval. The
   unanalyzable placeholder is display-only for real empty student files.
2. `configured_context_retriever()` always returns
   `CompositeContextRetriever`. Missing KB / mock / `MOCK_OPENAI` injects
   `knowledge_base=None` instead of dumping course sources onto local chunks.
3. Missing or empty KB results become an application-owned evidence-gap note.
   Execution preserves that note after rebuilding context from validated
   chunks. The composer tells the model not to claim the PDF has no readable
   text and not to invent a summary.
4. Production with `COURSE_MATERIAL_SYNC_ENABLED=true` requires
   `KNOWLEDGE_BASE_ID`.
5. Opt-in `scripts/diagnostics/test_course_retrieval.py` can call live
   Retrieve only with `--i-approve-live-bedrock`. Pytest never runs it.
   No generation call.

#### Main files changed

- `backend/retrieval.py`, `backend/bedrock_retrieve.py`,
  `backend/coaching/execution.py`, `backend/sources/context.py`,
  `backend/prompts/composer.py`, `backend/settings.py`
- Tests: `tests/domain/test_retrieval.py`,
  `tests/domain/test_bedrock_retrieve.py`,
  `tests/domain/test_source_library.py`,
  `tests/domain/test_prompt_architecture.py`,
  `tests/http/test_production_config.py`,
  `tests/scripts/test_agentcore_course_cli.py`
- Script: `scripts/diagnostics/test_course_retrieval.py`, `scripts/AGENTS.md`
- Docs: `docs/RAG_ARCHITECTURE.md`, `docs/SECURITY_BOUNDARIES.md`,
  `docs/deploy/AWS_STATELESS_EC2.md`, `docs/PROMPT_ARCHITECTURE.md`,
  `docs/LOCAL_DEMO_IMPLEMENTATION.md`, `.env.example`, `README.md`,
  `compose.prod.yaml`, `tests/AGENTS.md`

#### Validation evidence

- `compileall` for `backend`, `ui`, `streamlit_app.py`, `tests`, and `scripts`:
  **passed**.
- Full deterministic suite: **618 passed, 0 failed, 0 skipped** in 27.86s.
  Existing Starlette/httpx deprecation warnings only (66).
- Ruff on files from this fix: **passed**. Repository-wide ruff still reports
  8 pre-existing unused-import issues outside this change.
- `git diff --check`: **passed**.
- `docker compose config --quiet`: **passed**.
- `docker compose -f compose.prod.yaml config --quiet`: **passed** with
  `APP_IMAGE` set (blank `APP_IMAGE` is invalid by design).
- No live Bedrock Retrieve call. No paid AgentCore/OpenAI generation call.

#### Compatibility, migration, and rollback

- No schema change. Shared course files stay virtual; student uploads stay
  notebook-scoped. Rollback is reverting this working tree.
- Strict `course_material_id` metadata filter remains off until the live KB
  is re-ingested with that attribute. Unfiltered retry plus exact-key
  post-validation stays.

#### Known risks and next exact action

- Live Knowledge Base Retrieve is not yet proven from this tree. Do not mark
  strict metadata mode as working until re-ingestion is verified.
- Next, only if explicitly approved:
  `.venv/bin/python scripts/diagnostics/test_course_retrieval.py --query "what are the week 1 contents talking about?" --source "Week 1 Introduction to innovation v3.pdf" --i-approve-live-bedrock`
- Do not run a paid AgentCore generation turn until Retrieve returns actual
  Week 1 text. Do not commit, push, or deploy from this phase unless asked.

### Previous completed phase — Live AgentCore DEFAULT coaching (harness patch + smoke)

**Completed on 2026-08-15.** `Integrate-Bedrock` is merged into `main`.
Production still uses `MODEL_PROVIDER=agentcore` against existing runtime
`NUSCodesignChatbot_chatbot_harnessAgent-6ncEO79sD7`. Qualifier remains
`DEFAULT`. No experimental student runtime.

The companion trust split was already in this repo; live DEFAULT still ran
pre-patch harness code until republished. First republish (version 8) 502'd
because `invoke` mixed `return json.loads(...)` with SSE `yield` (`SyntaxError:
'return' with value in async generator`). Version 9 splits JSON return and SSE
streaming into separate functions. Live JSON then failed validation on
`recommendation: "STAY"` and object-shaped `stage_assessment`; the domain
contract now coerces those live-model variants.

#### Behavior delivered

1. Existing DEFAULT runtime updated in place to **version 9**, READY.
2. `coach_turn` invokes return unfenced JSON (no tools, no AgentCore Memory as
   transcript). Q&A SSE path is unchanged.
3. `EducationalAssessment` accepts uppercase `stay`/`advance` and flattens
   object `stage_assessment` (lifting strengths/improvements into review
   fields when present).
4. Runtime instructions tell the model `stage_assessment` is a string and
   `recommendation` is lowercase `stay` or `advance`.

#### Main files changed

- Live harness (POC worktree, not this git tree): `chatbot_harnessAgent/main.py`
  split `_coach_turn_invoke` / `_stream_specialist_invoke`
- Companion: `backend/domain.py`, `backend/prompts/composer.py`,
  `backend/agentcore_harness_provider.py`,
  `scripts/agentcore/harness_patch/structured_coach.py`,
  `scripts/agentcore/harness_patch/README.md`, this status file
- Tests: `tests/domain/test_models_and_support.py`,
  `tests/domain/test_agentcore_provider.py`

#### Validation evidence

- Focused deterministic tests for the coercion and AgentCore/prompt/harness
  contracts: **passed** (Starlette/httpx deprecation warnings only).
- Live capped smoke:
  `scripts/agentcore_smoke.py --i-approve-live-agentcore --cost-cap 1.00 --max-requests 1`
  returned `{"ok": true, "stage": "problem_identification", "recommendation": "stay"}`.
  Not a guardrail block. Not a 502.
- Local `/api/v1/ready` was `provider: agentcore` before restart; stack restarted
  after the domain coercion so UI turns use the same parser.

#### Compatibility, migration, and rollback

- No database migration. Runtime ARN and `AGENTCORE_QUALIFIER=DEFAULT` unchanged.
- Rollback of the live runtime is pointing DEFAULT at version 7 (pre-patch) or
  8 (broken import). Version 9 is the working structured-coach code.
- Companion rollback is reverting this working tree; uppercase `STAY` would
  again fail closed as malformed.

#### Localhost UI follow-up (2026-08-15)

Profile settings on http://127.0.0.1:8501/ : display name Kai Ming, appearance
System, language English, coaching style **Strict** (`response_detail=long`).
The first UI turns failed closed as generic “temporarily unavailable” because
`focused_excerpt` could return 601–602 characters (ellipsis around a 600-char
window) and `RetrievalChunkReference.excerpt` rejects that. Course retrieval
for this notebook returns mid-chunk matches, so the turn never reached
AgentCore. Excerpts are now clipped to the field limit, including ellipses.

A live Strict turn then succeeded on DEFAULT version 9: notebook title
**Elderly Road Safety**, stage stayed `problem_identification`, recommendation
`stay`, eight retrieval refs with excerpts ≤ 600 characters, Socratic reply
persisted. No mock fallback. No Claude.

Additional files: `backend/retrieval.py`, `tests/domain/test_retrieval.py`.
Focused retrieval tests: **17 passed**.

#### Known risks and next exact action

- Empty assistant rows from earlier failed streams remain in this notebook;
  they are not used as transcript history for the successful turn.
- Live `review_strengths` can still be an empty list, so Journey may show
  “No feedback yet” even after a persisted assessment.
- Next: optional cleanup of empty failed-stream assistant rows, or prompt the
  structured coach to fill `review_strengths` / `review_improvements`. No mock
  fallback and no Claude calls. Production deploy of this merge keeps
  CloudFront as the only public hostname and Caddy `:80` with `/api/v1/auth/me`
  on the auth allow-list.

### Previous completed phase — AgentCore coaching availability, guardrail handling, trust split

**Completed locally on 2026-08-15.** Integrate-Bedrock remains the product.
Production `MODEL_PROVIDER=agentcore` still uses `InvokeAgentRuntime` and does
**not** change DEFAULT. Live AgentCore coaching was failing closed as a
malformed turn because runtime guardrail `PROMPT_ATTACK` blocked the composed
user payload, including a literal attack example in shared instructions. This
phase unblocks that path without disabling safety controls, then splits trusted
instructions from untrusted turn content.

#### Behavior delivered

1. Shared coaching no longer contains a literal prompt-attack example.
   Quoted/retrieved override attempts remain untrusted evidence.
2. `AgentCoreCoachProvider` detects `guardrail_intervened` and guardrail
   `action=BLOCKED` before parsing model text. The failure is category-only
   (`safety_blocked`); refusal text, prompts, and AWS traces are not exposed
   or persisted.
3. FastAPI carries `{message, category}` on JSON 503 and `category` on stream
   error events. Streamlit shows student-safe copy that does not blame
   `scripts/start.sh` or claim the provider is down.
4. Composer exposes `trusted_instructions` and `untrusted_turn_text` while
   preserving ordered `composed_text` and the same length budget. AgentCore
   sends trusted instructions on a dedicated harness field and keeps DSQL
   history plus untrusted content in `messages`.
5. Harness patch appends `trusted_instructions` to the system prompt and
   invokes only untrusted user content. Older payloads that omit the field
   remain compatible. Isolated Luna eval uses the same split.
6. `requirements.txt` pins `boto3==1.43.35` and `botocore[crt]==1.43.35` so
   clean installs include AgentCore and `aws login` CRT credentials.

#### Main files changed

- Prompts/adapters: `backend/prompts/shared/coaching.md`,
  `backend/prompts/composer.py`, `backend/providers.py`,
  `backend/agentcore_provider.py`, `backend/agentcore_harness_provider.py`,
  `backend/http/app.py`, `backend/api_client.py`, `ui/panels/chat.py`
- Harness: `scripts/agentcore/harness_patch/structured_coach.py`,
  `scripts/agentcore/harness_patch/README.md`
- Tests/docs: AgentCore, prompt, API, API-client, Streamlit tests; prompt,
  security, AgentCore, and this status file
- Dependencies: `requirements.txt`

#### Validation evidence

- Full deterministic suite: **591 passed, 0 failed** (Starlette/httpx
  deprecation warnings only; classified as harmless test-client debt).
  `compileall` passed. `git diff --check` passed. No live AWS or paid OpenAI
  call from pytest.

#### Compatibility, migration, and rollback

- No database migration. Production runtime ARN and `AGENTCORE_QUALIFIER=DEFAULT`
  are unchanged. No experimental student runtime.
- JSON 503 `detail` for provider failures is now `{message, category}` instead
  of a bare string. Stream error events add `category`.
- Rollback is reverting this working tree.

### Previous completed phase — Full-history-first planner, exact RAG keys, isolated Luna eval path

**Completed locally on 2026-08-15.** Integrate-Bedrock remains the product.
Production `MODEL_PROVIDER=agentcore` still uses `InvokeAgentRuntime` and
does **not** change DEFAULT. The last-six history cap is replaced by a
full-history-first token-aware planner. Compression is derived model context
only. Object-key matching is exact. Live pedagogical evaluation, when
approved, uses isolated InvokeHarness + GPT-5.6 Luna with zero Claude calls.

#### Behavior delivered

1. `HistoryContextPlanner` sends the entire active DSQL transcript when it
   fits; otherwise extractive (production) or Luna (eval) compression plus a
   recent verbatim window. DSQL is never truncated.
2. Derived `conversation_memory` persists in notebook settings, stamped with
   `conversation_revision`, and is discarded after revise-and-resubmit.
3. Retrieve object keys match by canonical equality only. Nested
   `course_material_id` values distinguish same filenames in different folders.
   Strict metadata filter remains off until live KB metadata is verified.
4. Isolated `AgentCoreHarnessCoachProvider` asserts
   `openai.gpt-5.6-luna` / `responses` before every eval invoke. Production
   factory is unchanged.

#### Main files changed

- Planner/eval: `backend/context_planner.py`, `backend/live_eval_config.py`,
  `backend/agentcore_harness_provider.py`, `backend/agentcore_provider.py`,
  `backend/prompts/composer.py`, `backend/coaching/execution.py`,
  `backend/workflow.py`, `scripts/evals/evaluate_live_coach.py`
- Retrieval: `backend/retrieval.py`, `backend/bedrock_retrieve.py`
- Docs: prompt, AgentCore, RAG, security, this status file

#### Validation evidence

- Full deterministic suite: **579 passed, 0 failed** (Starlette/httpx deprecation
  warnings only; classified as harmless test-client debt). `compileall` passed.
  `git diff --check` passed. No live AWS or paid OpenAI call from pytest.

#### Compatibility, migration, and rollback

- No database migration. `conversation_memory` is an additive settings key.
- Production DEFAULT and InvokeAgentRuntime ARN are unchanged.
- Rollback is reverting this working tree.

#### Known risks and next exact action

- Live KB `course_material_id` metadata may still be absent; filter fallback
  remains. Local venv boto3 1.35.99 lacks `InvokeHarness` (need 1.43+ in the
  eval environment only). Production DEFAULT is unchanged.
- Next: after `aws login`, create or set `AGENTCORE_EVAL_HARNESS_ARN` for an
  isolated eval harness and run
  `.venv/bin/python scripts/evals/evaluate_live_coach.py --i-approve-live-luna --quick`.
  Do not commit/push or switch production DEFAULT unless asked.

### Previous completed phase — Ethics & CT integration, KB metadata filter, history de-dup

**Completed locally on 2026-08-15.** Integrate-Bedrock remains the product.
AgentCore is still a stateless reasoning adapter. Course Retrieve can send a
`course_material_id` metadata filter and still post-validates object keys.
AgentCore no longer duplicates DSQL history inside `<recent_messages>`. The
student-facing fourth stage is **Ethics & Critical Thinking** (persisted id
`deep_analysis`). Shared prompts now include the silent Socratic scaffold,
Assumption Check, and V&V lens. Co-occurrence is professor-only post-hoc
analytics.

#### Behavior delivered

1. `compose_coach_prompt(..., include_recent_messages=False)` for AgentCore.
   Bounded DSQL turns travel as Converse `messages` only.
2. `BedrockKnowledgeBaseRetriever` filters by `course_material_id` when ids
   exist, retries without the filter if empty, then drops unselected keys.
3. Student-facing label for `deep_analysis` is Ethics & Critical Thinking /
   Ethics & CT. No sixth `ethics_critical` application stage.
4. Shared coaching prompt: Interpret → Assumption/V&V check → one probe →
   reflection trigger; untrusted-evidence rules strengthened.
5. Professor research summary includes read-only co-occurrence / co-absence.
   Research codes still do not advance stages or drive coaching.

#### Main files changed

- Prompts/journey: `backend/prompts/shared/coaching.md`,
  `backend/prompts/stages/deep_analysis.md`, `backend/learning/stages.py`,
  `backend/prompts/composer.py`, `backend/agentcore_provider.py`
- Retrieval: `backend/retrieval.py`, `backend/bedrock_retrieve.py`,
  `backend/sources/library.py`, `backend/coaching/execution.py`
- Research/UI: `backend/professor_analytics/research.py`, `ui/professor.py`,
  `ui/auth_gate.py`
- Docs: `docs/RAG_ARCHITECTURE.md`, `docs/SECURITY_BOUNDARIES.md`,
  `docs/PROMPT_ARCHITECTURE.md`, `docs/providers/AGENTCORE_ADAPTER.md`,
  `docs/research/METHODOLOGY.md`

#### Validation evidence

- Full deterministic suite: **558 passed, 0 failed**. Existing Starlette/httpx
  deprecation warnings. No live AWS or paid OpenAI call from pytest.
- `compileall` for `backend`, `ui`, `streamlit_app.py`, `tests`, and `scripts`
  passed.

#### Compatibility, migration, and rollback

- No database migration. Internal stage id remains `deep_analysis`.
- Knowledge Base metadata `course_material_id` is recommended; without it the
  adapter falls back to unfiltered Retrieve plus object-key validation.
- Harness patch system prompt changed; redeploy DEFAULT if that overlay is
  used. Rollback is reverting this working tree.

#### Known risks and next exact action

- Live AgentCore still streams prose until the harness patch is on DEFAULT
  READY. KB metadata filter is ineffective until course objects are
  re-ingested with `course_material_id`.
- Next: optional approved live smoke after harness JSON cutover. Do not
  commit/push/deploy from this phase unless asked.

### Previous completed phase — POC-style DSQL history messages + selected-source KB Retrieve

**Completed locally on 2026-08-15.** AgentCore invokes send bounded DSQL
history as Converse `messages` (POC Memory equivalent) while remaining
stateless. Locked Lecture Notes/Readings can use Bedrock Knowledge Base
`Retrieve` mapped onto selected `[S#]` labels. FastAPI/Streamlit/DSQL stay.
The coaching specialist still has zero KB tools.

#### Behavior delivered

1. `AgentCoreCoachProvider` always sends `messages`: last six DSQL turns plus
   the composed current turn (and images). `student_id` is the store owner
   identifier, never a notebook id. `runtimeSessionId` stays `stateless-…`.
2. `BedrockKnowledgeBaseRetriever` calls `Retrieve` only, maps
   `s3://…/course/…` onto locked source `object_key` values, and drops foreign
   or unselected keys. `CompositeContextRetriever` keeps student uploads on
   `LocalChunkRetriever`.
3. `configured_context_retriever()` injects the composite when
   `KNOWLEDGE_BASE_ID` is set and the provider is not mock. Pytest keeps the
   local retriever.

#### Main files changed

- `backend/agentcore_provider.py`, `backend/domain.py`,
  `backend/coaching/execution.py`, `backend/retrieval.py`,
  `backend/bedrock_retrieve.py`, `backend/owner_context.py`,
  `backend/settings.py`
- Tests: `tests/domain/test_agentcore_provider.py`,
  `tests/domain/test_bedrock_retrieve.py`, `tests/domain/test_retrieval.py`,
  `tests/conftest.py`
- Docs: `docs/providers/AGENTCORE_ADAPTER.md`,
  `docs/PROMPT_ARCHITECTURE.md`, `docs/LOCAL_DEMO_IMPLEMENTATION.md`,
  `.env.example`

#### Validation evidence

- Full deterministic suite: **544 passed, 0 failed**. Existing Starlette/httpx
  deprecation warnings. No live AWS or paid OpenAI call from pytest.
- `compileall` for `backend`, `ui`, `streamlit_app.py`, `tests`, and `scripts`
  passed. `git diff --check` passed.

#### Compatibility, migration, and rollback

- No schema change. Empty `KNOWLEDGE_BASE_ID` keeps local retrieval. Rollback
  is reverting this working tree.

#### Known risks and next exact action

- Live AgentCore still streams prose until
  `scripts/agentcore/harness_patch/README.md` is applied and `DEFAULT` is
  READY. Set `KNOWLEDGE_BASE_ID=JUQNP8AZAZ` on EC2 after that cutover.
- Next: deploy the harness patch, then one approved
  `scripts/agentcore_smoke.py --i-approve-live-agentcore --cost-cap 1.00 --max-requests 1`.
  Never restore six stages.

### Previous completed phase — Strict coaching style by default

**Completed locally on 2026-08-15.** New notebooks and empty progress blobs
default to Strict coaching (`response_detail=long`). Students can still choose
Quick. Notebooks that already persisted Quick stay Quick.

#### Behavior delivered

1. Canonical default is `DEFAULT_RESPONSE_DETAIL = "long"` in
   `backend/learning/journey.py`. Session, composer, store fallbacks, and the
   profile **Coaching style** control all use that constant.
2. Mock Strict still waits for a second follow-up before ADVANCE; Quick still
   advances after one. Two-turn HTTP fixtures pin Quick so they stay independent
   of the product default.
3. Streamlit AppTest confirmation/auto-advance paths send three turns so Strict
   can recommend the next stage.
4. Creating a notebook resets the profile **Coaching style** widget to Strict
   so a previous Quick choice cannot leak onto the new notebook. The selected
   chip uses the filled accent highlight.

#### Main files changed

- Domain/UI: `backend/learning/journey.py`, `backend/student_store.py`,
  `backend/coaching/execution.py`, `backend/chat_service.py`,
  `backend/prompts/composer.py`, `ui/session.py`, `ui/profile.py`,
  `ui/notebooks.py`, `ui/panels/chat.py`, `ui/theme.py`,
  `ui/assets/styles/60-profile-topbar.css`
- Tests: `tests/domain/test_student_journey.py`, `tests/ui/test_streamlit_ui.py`,
  `tests/ui/test_streamlit_api_mode.py`, plus Quick pins in primary-path and HTTP
  two-turn ADVANCE tests
- Docs: `README.md`, `DESIGN.md`, `backend/AGENTS.md`, `ui/AGENTS.md`,
  `docs/IMPLEMENTATION_STATUS.md`

#### Validation evidence

- Targeted journey, Streamlit, primary-path, and HTTP confirmation tests passed.
- Full deterministic suite: **536 passed, 0 failed**. Existing Starlette/httpx
  deprecation warnings. No live AWS or paid OpenAI call from pytest.
- `compileall` for `backend`, `ui`, `streamlit_app.py`, `tests`, and `scripts`
  passed. `git diff --check` passed.

#### Compatibility, migration, and rollback

- No schema change. Empty `progress_text` now reads as Strict. Explicit
  `response_detail=short` notebooks are unchanged. Rollback is reverting this
  working tree.

#### Known risks and next exact action

- Live AgentCore still streams prose until
  `scripts/agentcore/harness_patch/README.md` is applied and `DEFAULT` is
  READY on a new version.
- Next: deploy that harness patch, then one approved
  `scripts/agentcore_smoke.py --i-approve-live-agentcore --cost-cap 1.00 --max-requests 1`.
  Never restore six stages.

### Previous completed phase — DSQL-only transcript + student download

**Completed locally on 2026-08-15.** Aurora DSQL / SQLite `messages` remain the
only durable chat transcript. AgentCore stays generation-only (stateless
invokes). Students can download a `.txt` projection of persisted messages from
Notebook Actions. POC JSON, DynamoDB, and AgentCore session memory are not
used as chat history. A sixth Thinking Path stage is not added.

#### Behavior delivered

1. Documented and tested that `AgentCoreCoachProvider` never reuses a notebook
   id as `runtimeSessionId`, never sends AgentCore Memory/history fields, and
   persists a valid turn only in `StudentStore` (no `poc_store.json`).
2. `GET /api/v1/threads/{thread_id}/transcript.txt` returns an attachment
   built from `get_messages` (Student/Coach labels, no assessment metadata).
   Foreign notebooks stay 404.
3. Notebook Actions offers **Download transcript** via the workspace facade /
   typed API client. Streamlit does not read SQLite.
4. Recorded deferred POC extras: deploy the existing harness `coach_turn`
   overlay; optional later “Ask the course” Retrieve mode mapped onto locked
   sources. Explicitly out of scope: scoring specialist replacement, critique
   every Nth turn, `ethics_critical` as a sixth stage, CDK student UI merge.

#### Main files changed

- Export: `backend/workspace_service.py`, `backend/http/app.py`,
  `backend/api_client.py`, `ui/services/runtime.py`, `ui/notebooks.py`,
  `ui/assets/styles/50-dialogs-notebooks.css`
- Tests: `tests/domain/test_agentcore_provider.py`,
  `tests/http/test_workspace_api.py`, `tests/http/test_multiuser_ownership.py`,
  `tests/ui/test_streamlit_ui.py`, `tests/test_architecture_contracts.py`
- Docs: `docs/DATABASE.md`, `docs/LOCAL_DEMO_IMPLEMENTATION.md`,
  `docs/providers/AGENTCORE_ADAPTER.md`, `docs/deploy/AWS_STATELESS_EC2.md`,
  nested `AGENTS.md`

#### Validation evidence

- Targeted: `tests/domain/test_agentcore_provider.py`,
  `tests/http/test_workspace_api.py`, `tests/http/test_multiuser_ownership.py`,
  `tests/test_architecture_contracts.py`, `tests/ui/test_streamlit_ui.py`
  passed.
- Full deterministic suite: **535 passed, 0 failed**. Existing
  Starlette/httpx deprecation warnings. No live AWS, Bedrock, AgentCore,
  Cognito, DSQL, S3, or paid OpenAI call from pytest.
- `compileall` for `backend`, `ui`, `streamlit_app.py`, `tests`, and `scripts`
  passed. `git diff --check` passed.

#### Compatibility, migration, and rollback

- No database schema change. Transcript download is a read of existing
  `messages`. Rollback is reverting this working tree.

#### Known risks and next exact action

- Live AgentCore still streams prose until
  `scripts/agentcore/harness_patch/README.md` is applied and `DEFAULT` is
  READY on a new version.
- Next: deploy that harness patch, then one approved
  `scripts/agentcore_smoke.py --i-approve-live-agentcore --cost-cap 1.00 --max-requests 1`.
  Do not add course Q&A or a scoring specialist until that cutover is done.
  Never restore six stages.

### Previous completed phase — AgentCore generation + shared course S3 keys

**Completed locally on 2026-08-14.** FastAPI/Streamlit remain the student
product. Production generation is `MODEL_PROVIDER=agentcore` (one
`InvokeAgentRuntime` per turn). Locked Lecture Notes/Readings reference shared
`course/` objects instead of copying PDFs into `users/`. Automated tests inject
fake clients and never call AWS.

#### Behavior delivered

1. `AgentCoreCoachProvider` sends `phase=coaching`, composed CDE2300 prompt,
   and `output_contract=coach_turn`. `deep_analysis` maps to AgentCore topic
   `ethics_critical` only. Invokes are stateless. Images fail closed rather
   than being dropped. Errors are category-only.
2. POC harness overlay in `scripts/agentcore/harness_patch/` so the live
   coaching specialist returns `ProviderCoachOutput` JSON with zero KB tools.
3. Shared course sync lists `course/lectureNotes/` and `course/readings/`
   into the Sources panel. It does **not** insert one DSQL `sources` row per
   file on each new notebook. Older notebooks that already persisted locked
   rows keep them. PDFs stay under shared `course/` keys.
4. Production config accepts OpenAI xor Bedrock xor AgentCore. Course sync is
   allowed when `COURSE_MATERIALS_BUCKET` + `COURSE_MATERIALS_PREFIX=course/`
   are set (not `users/`).
5. Admin inventory (account `355604674280`, `us-west-2`): runtime
   `NUSCodesignChatbot_chatbot_harnessAgent-6ncEO79sD7` DEFAULT READY v6;
   gateway `gateway-course-materials-4cymlvixrt`; KB `JUQNP8AZAZ` data source
   `cde2300-course-content-s3`; uploaded 7 lecture PDFs + 3 readings to
   `course/lectureNotes/` and `course/readings/`; EC2 role
   `CDE2300ChatbotEC2Role` inline policy `AgentCore-Course-Materials`
   (invoke, Retrieve, course Get/List, no course delete).

#### Main files changed

- New: `backend/agentcore_provider.py`, `tests/domain/test_agentcore_provider.py`,
  `scripts/agentcore/harness_patch/`, `scripts/agentcore_smoke.py`,
  `scripts/sync_course_materials.py`, `docs/providers/AGENTCORE_ADAPTER.md`
- Wiring: `backend/providers.py`, `backend/settings.py`, `backend/http/app.py`,
  `backend/sources/library.py`, `backend/persistence/*`
- Config/docs: `.env.example`, `compose.prod.yaml`, `docs/deploy/AWS_STATELESS_EC2.md`,
  `docs/PROMPT_ARCHITECTURE.md`

#### Validation evidence

- Targeted: `tests/domain/test_agentcore_provider.py`,
  `tests/domain/test_source_library.py`,
  `tests/http/test_production_config.py`,
  `tests/test_deployment_config.py` passed.
- Full deterministic suite: **531 passed, 0 failed**. Existing
  Starlette/httpx deprecation warnings. No live AWS, Bedrock, AgentCore,
  Cognito, DSQL, S3, or paid OpenAI call from pytest.
- `compileall` for `backend`, `ui`, `streamlit_app.py`, `tests`, and `scripts`
  passed. `git diff --check` passed.

#### Compatibility, migration, and rollback

- No database schema change. Default local provider remains `mock`.
- Host `.env` should set `MODEL_PROVIDER=agentcore`,
  `AGENTCORE_RUNTIME_ARN=arn:aws:bedrock-agentcore:us-west-2:355604674280:runtime/NUSCodesignChatbot_chatbot_harnessAgent-6ncEO79sD7`,
  `COURSE_MATERIALS_BUCKET=cde2300-course-content-s3`.
- Rollback: leave `.env` on `openai` or `bedrock` and set
  `COURSE_MATERIAL_SYNC_ENABLED=false`.

#### Known risks and next exact action

- Live runtime still streams prose until
  `scripts/agentcore/harness_patch/README.md` is applied and `DEFAULT` is
  READY on a new version.
- Next: deploy that harness patch, then one approved
  `scripts/agentcore_smoke.py --i-approve-live-agentcore --cost-cap 1.00 --max-requests 1`.

### Previous completed phase — Amazon Bedrock coach adapter

**Completed locally on 2026-08-14.** The coach provider contract now includes a
Bedrock Converse adapter. Phase progression, citations, persistence, and
selected-source retrieval stay in the application. Automated tests inject a
fake client and never call AWS.

#### Behavior delivered

1. `BedrockCoachProvider` makes one Converse call per turn with a required
   `coach_turn` tool whose schema is the provider-neutral
   `ProviderCoachOutput`. Markdown fences are not parsed as a fallback.
2. The persisted notebook phase overrides a model-supplied phase. Invalid
   coaching is rejected without persisting an assistant turn. Invalid research
   coding is dropped independently.
3. Images map from `CoachImageInput` data URLs to Converse image bytes;
   unsupported MIME types fail before the model call.
4. Provider exceptions map to category-only `ProviderUnavailableError`
   (throttled, timeout, access denied, model unavailable, malformed,
   truncated) without AWS bodies, credentials, prompts, or student content.
5. `MODEL_PROVIDER=bedrock` is selectable after contract tests. Production
   accepts OpenAI **or** Bedrock (not mock). Bedrock production requires
   `BEDROCK_MODEL_ID` and timeout/retry bounds and does not require
   `OPENAI_API_KEY`. Credentials stay on the AWS chain / EC2 role.

#### Main files changed

- New: `backend/bedrock_provider.py`, `tests/domain/test_bedrock_provider.py`
- Wiring: `backend/providers.py`, `backend/settings.py`, `backend/http/app.py`
- Docs/config: `.env.example`, `README.md`, `docs/providers/BEDROCK_ADAPTER.md`,
  `docs/LOCAL_DEMO_IMPLEMENTATION.md`, `docs/deploy/AWS_STATELESS_EC2.md`,
  nested `AGENTS.md` maps

#### Validation evidence

- Targeted: `tests/domain/test_bedrock_provider.py`,
  `tests/http/test_production_config.py`,
  `tests/domain/test_prompt_architecture.py` passed.
- Full deterministic suite: **501 passed, 0 failed**. Existing
  Starlette/httpx deprecation warnings. No live AWS, Bedrock, Cognito, DSQL,
  S3, or paid OpenAI call.
- `compileall` for `backend`, `ui`, `streamlit_app.py`, `tests`, and `scripts`
  passed. `git diff --check` passed.

#### Compatibility, migration, and rollback

- No database schema change. Default local provider remains `mock`.
- Production can keep `MODEL_PROVIDER=openai` until Bedrock model access and
  IAM invoke are granted. Rollback is reverting this working tree and leaving
  `.env` on `openai` or `mock`.

#### Known risks and next exact action

- The pinned boto3 Converse path uses strict tool use, not
  `outputConfig.textFormat`. Confirm the chosen model/inference profile
  supports tool use in `us-west-2` before a live smoke.
- Runtime IAM still needs `bedrock:InvokeModel` (and stream) on the exact
  model/profile ARN when switching production off OpenAI.
- Next: an explicitly approved live Bedrock smoke (one short request, stated
  model, token/request ceiling, and cost cap), then set production
  `MODEL_PROVIDER=bedrock` and remove `OPENAI_API_KEY` from the host `.env` if
  OpenAI is no longer used. Do not add a Bedrock Knowledge Base for coaching.

### Previous completed phase — port architecture package splits onto this branch

**Completed locally on 2026-08-14.** Package ownership on
`professor-analytics-ui` now matches the architecture-refactor *structure*
(façades, focused packages, grouped tests) without merging that branch. Five
research-aligned phases, professor analytics/Research, CSS, widget keys, and
routes are unchanged.

#### Behavior delivered

1. **Contracts locked first.** `tests/test_architecture_contracts.py` snapshots
   this branch’s façade signatures, `StudentStore` public methods including
   research/review/audit/workflow-marker APIs, DSQL OCC writes including
   `append_research_*` / `set_system_metadata`, and the complete FastAPI route
   inventory including `/api/v1/professor/*`.
2. **Persistence seam only.** Store contracts, SQLite schema/migrations, and
   source operations live under `backend/persistence/store/`. Research
   observation/review/adjudication/audit SQL stays on `StudentStore`.
3. **One FastAPI composition root.** `create_app` and all student+professor
   routes live in `backend/http/app.py`. `backend/api.py` remains the import
   façade, including monkeypatch seams for Cognito readiness and
   `StudentStoreResearchRepository`.
4. **Learning and coaching packages.** Five phases live in
   `backend/learning/`; `CoachApplicationService` (including research-observation
   persist and quote-offset handling) lives in `backend/coaching/execution.py`.
   `backend/student_journey.py` and `backend/application.py` are façades.
5. **Streamlit presentation aliases.** Chat/sources/studio/runtime
   implementations live in `ui/panels/` and `ui/services/runtime.py`.
   `ui/professor.py` and professor CSS were not moved. Cookie helpers live in
   `ui/auth/cookies.py` with `_cookie_value` still patchable on `auth_gate`.
6. **DSQL CLI and tests.** Implementation is `scripts/dsql/cli.py` (five-phase
   marker + research DDL). `scripts/init_dsql.py` re-exports it. Tests are
   grouped under `domain/`, `http/`, `persistence/`, `ui/`, and `scripts/` with
   no `__init__.py`. Mock CI focused paths and compileall include `scripts/`.
7. **Source package.** `backend/sources/library.py` owns ingestion/course sync;
   `context.py` and `projection.py` own bounded context and image/storage
   projection. `backend/source_library.py` is a `sys.modules` alias.

#### Main files changed

- New packages: `backend/http/`, `backend/learning/`, `backend/coaching/`,
  `backend/persistence/store/`, `backend/sources/`, `ui/panels/`,
  `ui/services/`, `ui/auth/`, `scripts/dsql/`.
- Compatibility façades: `backend/api.py`, `backend/application.py`,
  `backend/student_journey.py`, `backend/source_library.py`, `ui/chat.py`,
  `ui/sources.py`, `ui/studio.py`, `ui/runtime.py`, `scripts/init_dsql.py`.
- Tests: `tests/test_architecture_contracts.py`; existing scenarios relocated
  under subsystem directories; UI source-file assertions use `inspect.getfile`;
  DSQL workflow-contract patches target `scripts.dsql.cli`.
- Docs/guides: `docs/LOCAL_DEMO_IMPLEMENTATION.md`,
  `docs/CODEBASE_STRUCTURE.md`, `docs/TESTING.md`, nested `AGENTS.md`,
  `.github/workflows/mock-ci.yml`, `scripts/build.sh`.

#### Validation evidence

- Architecture contract tests passed before and after each move.
- Complete deterministic suite: **462 passed, 0 failed** (456 prior tests plus
  6 architecture-contract tests); existing Starlette/httpx deprecation
  warnings; no live AWS/Cognito/DSQL/S3/provider or paid call.
- `compileall` for `backend`, `ui`, `streamlit_app.py`, `tests`, and `scripts`
  passed. `git diff --check` passed. Ruff is pinned in `requirements-dev.txt`
  but was not installed in this local venv, so Ruff is not claimed here.
- AppTest coverage for student Journey/Review and professor UI remains in the
  mock suite. An isolated `scripts/start.sh` browser session was not repeated
  in this pass.

#### Compatibility, migration, and rollback

- No product, route, schema, authentication, provider/prompt, CSS, copy, or
  widget-key change. Historical import paths and monkeypatch targets remain.
- `codex/architecture-refactor` was used only as a pattern reference and was
  not merged (that branch’s six Facione stages and missing professor/research
  must not land here).
- No database write, migration, or learning-data reset. Rollback is reverting
  this working tree.

#### Known risks and next exact action

- Aliases must keep replacing the module object (`sys.modules[__name__] = …`)
  or re-exporting the same function objects; rebinding names breaks patches.
- `StudentStore` remains large by design. Research SQL stays there so
  coach-turn persist stays atomic.
- If refactoring continues, start with one independently reviewed slice of
  `StudentStore` notebook/message operations or one closure-complete HTTP route
  registrar. Preserve the existing compatibility/OCC/route inventories first.

### Previous completed phase — research-aligned five-phase coach and lecturer validation

**Implemented on 2026-08-14.** The original Replit workflow, supplied system
architecture/V&V materials, and the cited research have been translated into a
provider-neutral coaching and research-coding boundary. Cognito, FastAPI,
SQLite/DSQL ownership, S3/local files, notebook history, Quick/Strict profiles,
source grounding, revisions, and the current student workspace remain the
application infrastructure; they were not reverted to the Replit architecture.

#### Behavior delivered

1. Thinking Path now uses five research-aligned phases: Problem identification,
  Concept generation, Design specification, Deep analysis, and Reflection.
   The application still runs one LangGraph workflow, preserves confirmation,
   auto-advance, and Phase 2 selection rules, and derives UI totals/icons from
   the canonical phase definitions.
2. One structured provider result contains the normal coaching assessment and
  optional provisional research coding. The research section is independently
   soft-validated, so malformed/missing research data cannot discard a valid
   student turn. It records one dominant CLEAR strategy, at most two Facione
   behaviour occurrences, optional design-ethics concepts, and versioned
   provenance. It cannot award Facione points or move a phase.
3. Provider evidence quotes are transient. The application accepts only exact
  quotes from the current student utterance, converts them to half-open
   character offsets, persists offsets/rationale/confidence, and removes the
   quote-bearing provisional payload before graph checkpointing. Unmatched
   evidence fails closed without fabricating a code.
4. Only Reflection may contain a provisional holistic 1–4 candidate. Student
  Review exposes Facione behaviour occurrences and that clearly labelled
   candidate alongside the existing cumulative Quick/Strict Review; CLEAR and
   ethics labels remain lecturer research data.
5. Persisted `lecturer` and `admin` roles can access a protected professor
  Research workbench with aggregate summary, filtered/paged observation queue,
   attributable notebook transcript, immutable automated observations,
   append-only human reviews/adjudications, and formula-safe CSV. Reviewer and
   adjudicator IDs come from authenticated server context. Identifiable reads
   and exports write a bounded access audit first and fail closed if it fails.
6. SQLite and DSQL gained additive research observation, review,
  adjudication, access-audit, and system-metadata storage. Observations persist
   atomically with the coach turn, active queries exclude superseded revision
   branches, and notebook deletion follows explicit child-first predicates.
   DSQL write methods remain covered by the existing OCC retry boundary.
7. A workflow marker (`cde2300-five-phase-v1`) prevents silent reuse of
  semantically different six-stage data. Empty SQLite databases initialize it;
   DSQL bootstrap creates the additive schema and initializes the marker only
   when zero notebooks exist; non-empty unmarked databases remain unchanged and
   fail readiness. `scripts/reset_learning_data.py` provides dry-run inventory,
   checksum/staleness protection, exact confirmation, account preservation,
   WAL-safe SQLite backup, file quarantine, and owner-scoped DSQL/S3 deletion.
   **No reset was executed.**
8. Research definitions, limitations, human-validation requirements, and cited
  sources are recorded in
   `[research/METHODOLOGY.md](research/METHODOLOGY.md)`. Bedrock remains a
   future adapter only; `[providers/BEDROCK_ADAPTER.md](providers/BEDROCK_ADAPTER.md)`
   freezes its one-call structured contract without enabling AWS inference.
9. Persist-time Quick/Strict CAS and typed atomic auto-advance now protect the
  final coaching reply, confirmed transition, next journey, summary, and
   research observation as one database transaction. A direct/in-process coach
   path also rejects an unmarked legacy workflow before calling a provider.
10. Human review/adjudication fields use the same canonical CLEAR, Facione, and
  ethics enums as automated coding. The professor UI renders friendly labels
    while submitting normalized values; invented research codes fail at the
    typed API boundary.
11. The existing 14 Ruff findings were removed without runtime changes. Ruff is
  pinned in `requirements-dev.txt` and enforced by mock CI before tests.



#### Main files changed

- Domain/workflow/provider/prompt: `backend/domain.py`, `workflow.py`,
`application.py`, `providers.py`, `mock_provider.py`, `student_journey.py`,
`prompts/`.
- Persistence/research: `backend/student_store.py`, `backend/persistence/`,
`backend/research/`.
- Lecturer boundary: `backend/professor_analytics/research.py`, `backend/api.py`,
`backend/api_client.py`, `ui/professor.py`, professor responsive CSS.
- Student projection: `ui/studio.py`, stage-derived notebook/session/chat UI.
- Operations/docs/tests: `scripts/reset_learning_data.py`, research/Bedrock/reset
documentation, `requirements-dev.txt`, mock CI, and deterministic domain,
persistence, API, UI, transaction-race, and reset tests.
- System overview deck:
`docs/CDE2300_Design_Thinking_Companion_System_Documentation.pptx`.



#### Validation evidence

- Complete deterministic suite: **456 passed, 0 failed**; 65 framework
deprecation warnings; no live AWS/Cognito/DSQL/S3/provider or paid call.
- Research persistence/storage/professor focused gate: **40 passed**.
- Provider/application/research-coding focused gate: **41 passed**.
- Professor Research API/UI focused gate and the Streamlit workspace smoke passed.
- Atomic auto-advance/style/readiness regression file: **9 passed**; focused
API/idempotency/Streamlit integration: **55 passed**.
- DSQL bootstrap tests prove an empty database receives the exact five-phase
marker while populated unmarked data remains untouched and reset-gated.
- `compileall` for backend/UI/scripts/entrypoint/tests, `pip check`, full
`ruff check .` (**zero findings**), shell syntax, `git diff --check`, and
OpenAPI route inventory passed.
OpenAPI exposes exactly the six protected Research methods/paths.
- Both local and production Compose configurations passed.
- The system overview deck contains 13 slides and 13 source-note pages;
template-fidelity validation passed with zero issues, and every slide was
rendered and visually inspected. The overflow scan identified only the
inherited full-bleed closing-slide background, with no foreground text or
diagram outside the canvas.
- Isolated `scripts/start.sh` smoke with a temporary SQLite/files root and mock
provider: FastAPI `/health` and `/ready` returned 200; Streamlit
`/_stcore/health` returned `ok`; the processes were then stopped.
- A signed-in responsive browser review was not completed because the isolated
run had no authenticated student/lecturer browser session. AppTest and scoped
responsive-CSS contracts are the current UI evidence; this is not represented
as a completed human visual sign-off.



#### Compatibility, migration, and rollback

- No Cognito, public student API, source, notebook, model-provider, or external
request/response contract was removed. Research routes/tables/metadata are
additive. Human decisions and automated observations are append-only.
- The phase model intentionally changes from six stages to five research
phases. Existing learning data is not heuristically relabelled. Use the
supported readiness-gated launcher and the explicit procedure in
`[operations/RESEARCH_DATA_RESET.md](operations/RESEARCH_DATA_RESET.md)`.
- SQLite apply is recoverable from its printed database backup and quarantine.
DSQL/S3 application spans external transactions and requires a separately
approved retention/recovery plan. No migration/reset has been applied here.



#### Known risks and next exact action

- Automated CLEAR/Facione/ethics codes are provisional research observations,
not validated measures. Before a formal study, train human coders, sample and
double-code active utterances, calculate agreement, calibrate disagreements,
and document protocol/version changes.
- Run responsive Light/Dark browser QA for student Review and professor Research
with a persisted lecturer role when browser tooling is available.
- On a disposable copy of current data, run the reset command in dry-run mode,
review its manifest and recovery paths, then perform a five-phase mock smoke.
Do not apply it to live learning data without explicit approval.
- If Bedrock is selected next, implement only the adapter contract in
`docs/providers/BEDROCK_ADAPTER.md` with a fake SDK client first; any live
smoke needs an explicit model, request/token ceiling, and cost cap.



### Previous completed phase (historical)

**Production-grade repository audit and focused hardening.** The full layered
application, state ownership, persistence, Cognito boundary, provider adapters,
source ingestion, professor analytics, Streamlit presentation, deployment
configuration, tests, and canonical documentation were reviewed. No broad
folder move, schema migration, data rewrite, dependency addition, or product
redesign was justified.

#### Changes in this phase

1. The public login-start limiter no longer creates an in-memory client entry
  for every rotated key after the global limit is full, and stale client
   windows are evicted. This closes an unauthenticated process-memory growth
   path while retaining the existing per-client/global behavior.
2. Client-provided `X-Request-ID` values are accepted only when they match a
  1–128 character correlation-ID allow-list. Invalid or oversized values are
   replaced with a UUID before response reflection or application logging.
3. `APP_ENV=production` now requires `USE_LOCAL_API=true` and rejects local
  code execution and repository course-material sync. These checks enforce the
   documented FastAPI authorization boundary and current DSQL/S3 ownership
   model even if host environment overrides drift from `compose.prod.yaml`.
4. OpenAI clients now use explicit `OPENAI_TIMEOUT_SECONDS` (default 110) and
  `OPENAI_MAX_RETRIES` (default 0). The structured provider validates its
   injected API key rather than consulting global settings during each call;
   the legacy local-only path receives the same bounded client policy.
5. Dynamic values entering raw professor/profile HTML are attribute/text
  escaped. Professor UI one-line render blocks were expanded for maintainable
   review without changing the visual design.
6. README ownership wording now matches the implemented production API
  boundary. The dated manual-production report is explicitly historical and
   its four broken local links now resolve to canonical repository documents.



#### Validation evidence

- Focused API, configuration, provider, limiter, legacy-provider, professor UI,
and Streamlit suites → **111 passed**.
- `.venv/bin/python -m pytest -q` → **415 passed** (deterministic; no live
OpenAI, AWS, Cognito, DSQL, S3, or paid calls).
- `.venv/bin/python -m pip check` → no broken requirements.
- `compileall` for `backend`, `ui`, `streamlit_app.py`, and `tests`;
`git diff --check`; API import/route smoke → passed.
- Isolated mock startup on alternate localhost ports with a temporary SQLite
root: FastAPI `/health` and `/ready` returned 200; Streamlit
`/_stcore/health` returned `ok`. Existing processes on the canonical
8000/8501 ports were left untouched.
- Static top-level import audit: 79 modules, zero cycles, zero backend→UI edges.
- Ruff is configured in `pyproject.toml` but not installed in the project
virtual environment; mypy is neither configured nor installed. Neither is
claimed as executed.



#### Compatibility, rollback, and remaining risk

- No database or file migration. Existing notebooks, revisions, messages,
sources, assessments, and Cognito identities are untouched. Rollback is a
code/config revert.
- No live DSQL/AWS or authenticated production-browser smoke was authorized or
run. Professor class endpoints still aggregate one full active message batch
in Python; query count is constant and appropriate for the 80–100 student
pilot, but production DSQL latency must be measured before wider scale.
- The webpage importer validates DNS and redirects but does not pin the
validated address through connection establishment; DNS-rebinding-resistant
transport remains required before treating arbitrary URL import as a strong
network sandbox.
- The single-process rate limiters intentionally do not coordinate across
replicas. Move them to a shared limiter before horizontal scaling.



#### Next exact action

Complete the existing Aurora DSQL revision-schema cutover and the guarded live
idempotency smoke described below. Then run a read-only professor analytics
latency/contract check and authenticated desktop/mobile browser QA against the
deployed lecturer account. Do not open class traffic before those checks pass.

#### Prior auth phase (still true)

**Production edge: CloudFront viewer TLS → Caddy HTTP origin.** CloudFront at
``d1sxfuoybzedj5.cloudfront.net`` is now the sole production hostname. Caddy
listens on EC2 port 80 as the route-security boundary; host port 443 and the
retired dynamic-DNS updater are removed. Both Compose contracts, CI deployment
tests, Cognito callback examples, operational docs, and manual QA now use the
CloudFront topology.

#### CloudFront/Caddy edge alignment (completed)

1. CloudFront owns viewer HTTPS; Caddy accepts origin HTTP on ``:80`` and keeps
   the auth/health allow-list plus the catch-all ``/api/*`` 404 boundary.
2. ``compose.yaml`` and ``compose.prod.yaml`` use the CloudFront UI/API origin
   and Cognito callback. Neither publishes host port 443.
3. The obsolete host address-updater scripts and their secret-ignore rules were
   removed. A deterministic deployment test rejects their return in runtime,
   workflow, or documentation files.
4. CI's production configuration gate is explicitly named for the
   CloudFront/Caddy contract.
5. No database, DSQL, S3, Cognito resource, or student-data migration is
   required. Rollback is a code/config revert, but must not restore a second
   public hostname after Cognito and CloudFront cutover.

Validation: deployment/config/auth tests **50 passed**; full mock suite
**401 passed**; compileall, shell syntax, both Compose config validations, and
``git diff --check`` passed. No live AWS, DSQL, S3, Cognito, or paid-provider
call was made.

Next exact action: deploy the immutable image, restrict EC2 TCP 80 ingress to
the AWS-managed CloudFront origin-facing prefix list, verify the distribution
uses caching disabled plus full cookie/query/WebSocket forwarding, then run
``docs/security/CADDY_PUBLIC_BOUNDARY.md`` and the authenticated production
smoke. Do not open host TCP 443.

#### Prior auth phase (still true)

**Auth: restore Cognito refresh after 1-hour ID cookie expiry.** The
non-sensitive Path=/ ``co_design_session`` hint now limits refresh attempts to
browsers with an established session. Cold visitors go directly to Sign in;
expired sessions see the app skeleton and centered loader while the refresh
bridge runs once; a Sign in launch cannot be intercepted by that bridge.

#### Prior UI phase (still true)

**UI: fragment-scoped Streamlit reruns (local interactions).** Explicit
`rerun_app()` / `rerun_fragment()` helpers replaced the ambiguous
`rerun()`. Sources select/search/sort/upload/delete, Journey preview
toggles, Guidance Level, response language, and display-name avatar stay
panel-local; notebook/auth/coach/layout/stage-select/**Appearance theme**
remain full-app. Debug counters: `_app_runs`, `_sources_fragment_runs`,
`_studio_fragment_runs`, `_topbar_guidance_fragment_runs`,
`_topbar_profile_fragment_runs`.

#### Full-app actions that remain intentional

- Notebook create / switch / rename / delete
- Auth / sign-in cooldown / logout
- Coach send / revise / composer model changes
- Workspace column collapse / mobile panel layout
- Sources course-sync stable ↔ polling fragment remount
- Thinking Path stage selection and transition confirm
- Appearance theme (entrypoint `render_theme_css`)

1. **Full mock suite.** `.venv/bin/python -m pytest -q` → **397 passed**.



#### Auth refresh fix (this pass)

1. `should_attempt_session_refresh` no longer requires a live `co_design_id`
  cookie before redirecting to `/api/v1/auth/refresh`.
2. Login/refresh/logout set or clear `co_design_session` (Path=/, Max-Age 30d,
  non-sensitive `1`) alongside the Cognito token cookies.
3. Focused auth suites + full mock `pytest` green.



#### Prior UI hardening

1. **Explicit edit retry.** On revise failure, clear `pending_edit` so the next
  rerun does not auto-resubmit; keep the stable `get_retry_key` UUID; restore
   the in-bubble draft; require Send to retry.
2. **Studio sanitized errors.** Stage-select and transition-confirm failures log
  internals and show fixed student-safe messages (no `str(exc)`).
3. **Full mock suite (prior).** `.venv/bin/python -m pytest -q` → **393 passed**.



#### Prior production-hardening (still true)

Append-only edit remains (no DELETE truncate). DSQL revision migration is
resumable/idempotent (DEFAULT + batched NULL backfill). Ownership stays
`messages.notebook_id → notebooks.user_id → users.id`.

#### Hardening behavior changes (revision pass)

1. **DSQL revision migration.** `scripts/init_dsql.py` inspects
  `information_schema` name **and** `column_default`, repairs missing
   DEFAULT 0, and batch-backfills NULL `conversation_revision` (1000 rows /
   transaction) for notebooks and messages. Safe to re-run; never app startup.
2. **Stable revise retry.** Streamlit keeps one UUID idempotency key (via
  `get_retry_key` scope `revise:{message_id}`) until success; provider-
   failure retries resume without a second revision bump. After a failed
   attempt the UI requires an explicit Send (`pending_edit` cleared).
3. **Active-branch pending rejects.** `select_learning_stage` only rejects
  `decision_status='pending'` rows active at the current revision.
4. **Conversation revision (internal).** Stored revision stays zero-based;
  student UI does not show a Conversation NN label.
5. **No destructive message content update.** `StudentStore.update_message`
  raises; edits go through append-only revise only.



#### Prior append-only phase (still true)

1. **Active-branch chat.** Discussion renders only active messages for the
  notebook's current `conversation_revision`; superseded turns stay durable
   for revision history / reporting.
2. **Edit confirm copy.** Editing an earlier user turn states that a new
  conversation revision/branch is created; later turns leave the active view
   but remain in revision history (no truncate/delete claims).
3. **Post-edit reload.** Successful revise reloads journey state and reruns so
  `get_messages` shows the new active branch.
4. **Message revision columns (backend contract).** Messages carry
  `conversation_revision`, `previous_message_id`, and
   `superseded_at_revision`; ownership stays
   `messages.notebook_id → notebooks.user_id → users.id`.
5. **Assessment fields (expected).** User rows and the fixed coach welcome have
  `assessment_text = NULL`; assessed coach assistant replies store
   `assessment_text` JSON. Do not treat welcome NULL assessment as a failure.
6. **Sources panel.** My Sources → Lecture Notes → Readings; course materials
  lock-only; Select all + Sort for personal uploads.



#### PART 1 root-cause evidence (“only welcome” on DSQL) — code inspection

No live DSQL verification was run for this writeup.

**Primary mechanism (code evidence):**

- UI welcome seed (`ui/coach_welcome.py` → `store.add_message`) persists a fixed
assistant welcome through the workspace CRUD path **without** the coach
workflow / `persist_coach_turn` CAS.
- Coach turns persist via `CoachApplicationService` → `persist_coach_turn`.
At branch baseline `6b54923`, this path required
`notebooks.conversation_revision` for CAS while the simpler welcome insert
did not.
- **Welcome-only root cause from code inspection:** an older DSQL cluster
missing `notebooks.conversation_revision` could accept the independently
committed welcome, then roll back every real coaching turn when
`persist_coach_turn` reached its revision CAS.
- The new implementation also reads/writes the three message revision columns
from normal and welcome inserts. Missing message columns are therefore a
deployment failure prerequisite, not evidence that the new app will still
seed a welcome successfully. Run admin `scripts/init_dsql.py` before
deploying the new image.

**Secondary diagnostics (not claimed verified live):** wrong `DSQL_ENDPOINT`,
database name, runtime role/owner (`DSQL_USER` not `co_design_app`), or
`.env`/Compose config mismatch can produce empty or partial notebooks and
should be checked after confirming schema columns exist.

#### Owner reporting JOIN (do not denormalize messages)

```sql
SELECT
  u.id AS user_pk,
  u.identifier,
  u.cognito_sub,
  n.id AS notebook_id,
  n.conversation_revision AS notebook_revision,
  m.id AS message_id,
  m.role,
  m.conversation_revision AS message_revision,
  m.previous_message_id,
  m.superseded_at_revision,
  m.assessment_text,
  m.created_at
FROM messages m
JOIN notebooks n ON n.id = m.notebook_id
JOIN users u ON u.id = n.user_id
WHERE n.id = :notebook_id
ORDER BY m.created_at, m.id;
```



#### Files changed (this append-only phase)

- `backend/student_store.py`, `backend/application.py`,
`backend/chat_service.py`, `backend/repositories.py`, and
`backend/workspace_service.py` — append-only persistence, snapshots, CAS,
retry recovery, and legacy compatibility.
- `backend/api.py`, `backend/api_client.py`, and `backend/domain.py` —
append-only contract documentation.
- `backend/persistence/dsql_schema.py` and `scripts/init_dsql.py` — fresh
schema plus catalog-driven additive DSQL migration.
- `ui/chat.py`, `ui/assets/styles/30-chat.css`, and `ui/AGENTS.md` —
Conversation label, edit warning, and failure fall-through.
- Revision, migration, idempotency, store, legacy-engine, and UI regression
tests were updated under `tests/`.
- `docs/IMPLEMENTATION_STATUS.md` and
`docs/deploy/AWS_STATELESS_EC2.md` — migration, reporting, evidence, and
deployment steps.

`tests/test_conversation_revision.py` asserts append-only semantics
(`previous_message_id` lineage, `superseded_at_revision`, active
`get_messages` / `get_messages_at_revision(0)` = Conversation 01, provider-
failure retention, stale CAS, revoked keys, pending supersede, API ownership,
DSQL message columns, `assessment_text` on assessed assistants only).

#### Validation evidence

- Integrated revision/storage/UI selection:
`.venv/bin/python -m pytest -q tests/test_conversation_revision.py tests/test_init_dsql.py tests/test_coach_idempotency.py tests/test_streamlit_ui.py tests/test_student_store.py tests/test_storage_providers.py tests/test_learning_service.py` → **115
passed** (deterministic mocks; 2026-08-10).
- Full suite: `.venv/bin/python -m pytest -q` → **381 passed**.
- Compile: `PYTHONPYCACHEPREFIX=/private/tmp/co-design-pycache .venv/bin/python -m compileall -q backend ui streamlit_app.py tests scripts`
→ passed.
- Patch integrity: `git diff --check` → passed.
- IDE diagnostics on edited Python modules: no errors.
- Paid OpenAI / live AWS calls: not run.



#### Compatibility / migration / rollback

- Additive only: existing message rows backfill to revision `0` with
`superseded_at_revision` NULL; display stays Conversation 01 until an edit.
- DSQL: admin manual DDL / `init_dsql.py` catalog path only — **app startup
never DDL**. See `docs/deploy/AWS_STATELESS_EC2.md`.
- Rollback: revert the application image/code; older code ignores the additive
columns and retained historical rows. Avoid `DROP COLUMN` on live student
data. Use the pre-migration backup/cluster snapshot if physical schema
rollback is required. SQLite migrations are additive on open.



#### Known risks / blockers

- Existing DSQL clusters must receive the additive notebook/message revision
migration before this application version is deployed. Runtime cannot repair
missing columns and app startup intentionally performs no DDL.
- The migration and behavior are covered by deterministic mocks, not a live
DSQL write. No live browser/upload/RAG QA is claimed in this phase.



#### Next exact action

**Stop architecture/feature edits.** Proceed only with live AWS / DSQL cutover:

1. Confirm host `.env` has `DSQL_ENDPOINT`, `AWS_REGION=us-west-2`, and
  admin identity available for DbConnectAdmin. Take a DSQL snapshot/export.
2. On the existing Aurora DSQL cluster, as admin only:
  `DSQL_ENDPOINT=<hostname> AWS_REGION=us-west-2 \\    .venv/bin/python scripts/init_dsql.py --admin-user admin`
   Then `GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public  TO co_design_app;` (no schema USAGE). Re-run is safe/idempotent.
3. With separate live-write approval, run
  `scripts/smoke_dsql_idempotency.py --confirm-live --identifier  'cognito:<sub>'` as `DSQL_USER=co_design_app`.
4. Redeploy ARM64 ECR image; require internal `/api/v1/ready` 200; run the
  Cognito → notebook → coach → upload → edit/revise → restart smoke in
   `docs/deploy/AWS_STATELESS_EC2.md` (mock first; OpenAI only with cost cap).



#### Prior pilot context (Phases 1–14)

**Phases 1–13 complete on** `Production-RemoveData`**; Phase 14 verdict:
READY FOR CONTROLLED PILOT.** Live manual production QA documented in
`docs/MANUAL_PRODUCTION_QA.md` (2026-08-10). **Month-1 product policy:**
`AUTO_ADVANCE_STAGES=true` and `STUDENT_STAGE_SELECTION=false` in
`compose.prod.yaml` (coach ADVANCE applies without Next; no Journey stage
pick controls). **Month-2+ operator flip:** set `STUDENT_STAGE_SELECTION=true`
and `AUTO_ADVANCE_STAGES=false` — Journey shows audited **Work on this stage**
(`POST .../learning-state/select-stage`); if both flags are true, selection
wins and auto-advance is treated as off. Health `mode` now follows
`APP_ENV`. Login-start rate limit and allow-listed Cognito callback error
logging added. Coach chat shows a **thinking** status while the buffered
provider turn runs (early NDJSON `status`); true token streaming remains
deferred. For lower wait times keep Guidance short, reasoning low, and avoid
extra selected sources. **Edit message** (pre–append-only) used
server-authoritative `POST .../messages/{id}/revise` with
`conversation_revision` CAS and a **new** idempotency key; that path is being
replaced by append-only revision history on this branch. Regenerate remains
unavailable.

#### Behavior changes (Phases 1–13)

1. Concurrent identical coach idempotency keys converge to one provider
  execution; completed markers replay without false lease-lost errors.
2. `APP_ENV=production` fail-closes via `validate_production_configuration()`
  at `create_app` and `/api/v1/ready`.
3. `/api/v1/ready` checks config, DB ping, file-store ping, provider
  credential shape, and Cognito HTTPS config without paid LLM calls.
4. `compose.prod.yaml` sets `APP_ENV=production`, json-file log rotation
  (10m × 3), and `no-new-privileges` on `app`/`caddy`.
5. `backend/rate_limit.py` provides single-EC2 in-process coach limits
  (`MAX_ACTIVE_COACH_REQUESTS_PER_USER=1`, `COACH_REQUESTS_PER_MINUTE=8`,
   `MAX_CONCURRENT_MODEL_CALLS=20`) wired into `coach_turn` /
   `coach_turn_stream` using authenticated `owner.store.owner_id`. HTTP
   429 includes `Retry-After`; slots release in `finally`.
6. Uploads: Streamlit `maxUploadSize=10`; API rejects excess file count and
  bounds each `upload.read(max+1)`.
7. Coach info logs omit notebook/thread ids and message text; request IDs and
  aggregates remain.
8. Caddy adds HSTS / nosniff / Referrer-Policy / Permissions-Policy (no CSP).
  Curl checks live in `docs/security/CADDY_PUBLIC_BOUNDARY.md`.
9. `requirements.txt` uses exact pins; Mock CI runs shell/compose/compile,
  production + idempotency gates, and full pytest.
10. `scripts/load_probe.py` + `docs/operations/LOAD_PROBE.md`; AWS smoke
  checklist expanded; `docs/deploy/GITHUB_BRANCH_PROTECTION.md`; public PDF
    audit lists 10 normal-blob lecture/reading PDFs (no LFS).



#### Behavior changes

1. Public notebook/message payloads are typed and reject stage, progress, and
  transition metadata. Only the internal learning workflow can write
   authoritative stage state; Conclusion cannot propose or confirm another
   Conclusion transition.
2. Workflow/provider failures are not retried through the sequential fallback,
  preventing duplicate paid provider calls. A completed user/assistant turn,
   assessment, pending decision, and notebook summary now commit in one store
   transaction. DSQL notebook read/merge/write also uses one retryable
   transaction, preventing stale stage reversion.
3. New S3 uploads separate raw and derived namespaces. Batch uploads prevalidate
  sizes and clean up all accumulated objects on validation or put failure.
   PDF/Office extraction has bounded page, archive, compression, slide,
   paragraph, and cell limits.
4. Cognito logout derives the trusted same-origin `/oauth2/revoke` endpoint
  when discovery omits it. Unknown JWKS key IDs have a bounded forced-refresh
   window, avoiding unauthenticated network amplification. Expired OAuth login
   states are cleaned during new-state insertion.
5. Production readiness now verifies the configured file store, bounded S3
  list access, and SELECT access to all five required DSQL tables. The DSQL
   schema expresses non-primary uniqueness as explicit `CREATE UNIQUE INDEX  ASYNC` jobs that bootstrap waits for.
6. The adapter-configured OpenAI model is authoritative. Response
  language reaches the prompt, reasoning effort restores per notebook, and
   selected sources force model-knowledge fallback off. Request/image limits
   are enforced at the API/application boundary.
7. User-message **Edit** uses inline bubble Save → server
  `revise_and_resubmit` (append-only conversation revision, stage/journey
   recompute, `conversation_revision` CAS, new idempotency key). Regenerate
   remains unavailable. Normal send/stream retries use the durable idempotency
   contract described below.
8. Production documentation now uses `compose.prod.yaml`/ECR and makes S3
  setup/readiness explicit. The default stateful Compose stack is labelled
   local-only; Bedrock permissions are not required in this phase.
9. Selected-source concatenation is replaced by a provider-neutral retrieval
  port and deterministic local chunk retriever. It uses sentence-aware chunks,
   current-turn-weighted lexical ranking, bounded conversation/project
   continuity, source diversity, stable `[S#]` labels, image markers, and
   strict context budgets in both preferred API and legacy development paths.
10. Assistant messages persist structured `retrieval_refs` for audit while
  `source_refs` remains limited to sources actually cited. Citation previews
   focus on matching evidence. Application code rebuilds prompt context only
   from validated chunks and rejects source IDs/labels outside the selected
   notebook, preserving the future Bedrock adapter boundary.
11. Live Aurora DSQL bootstrap corrections: async index waits now execute
  `CALL sys.wait_for_job(?)` on a dedicated verify-full admin connection
   with `autocommit=True`; DDL remains one transaction per connection. The
   unsupported `GRANT USAGE ON SCHEMA public` was removed, leaving only
   SELECT/INSERT/UPDATE/DELETE on all application tables in `public`.
12. Local legacy SQLite upgrades are additive and idempotent. The migration no
  longer renames/drops `users` (which previously cascaded deletion into
    legacy tables); it copies old threads, chat steps, source rows, stage state,
    and extracted source text into the five application tables while retaining
    the legacy rows as a rollback source. Legacy local source paths still
    preview/download, and copied extracted text remains available to the same
    provider-neutral local retriever used by new sources.
13. Cognito-scoped stores reconcile legacy/noncanonical identities and repair
  the earlier split-owner layout without dropping notebooks. Streamlit also
    reuses the first verified `/auth/me` result instead of making a second
    authentication request on every rerun.
14. Sign-in now uses a dialog-owned button callback instead of a fragment-owned
  callback. After the click, the original button remains the only visible
    sign-in control, is disabled for five seconds while the visible
    `Redirecting...` status is shown, and automatically becomes a retry
    button if Cognito navigation stalls.
15. Local startup repairs the broken `notebooks.user_id -> users_legacy`
  foreign key left by the retired destructive user migration. The SQLite-only
    rebuild is transactional, preserves notebook/message/source IDs, checks for
    orphaned notebooks before commit, and is idempotent. DSQL schema SQL is not
    changed.
16. The deterministic mock provider now makes retrieved grounding visible in
  its normal reply by quoting one bounded validated chunk and emitting its
    stable `[S#]` label. The existing citation resolver persists and renders
    the corresponding source reference without test-only monkeypatching.
17. Chat-composer attachment failures render a recoverable in-chat error and do
  not submit a coaching turn. Authoritative source selection now enables
    broader model knowledge only when no source is selected, so stale notebook
    metadata cannot contradict the visible UI mode.
18. API-mode course-material sync snapshots the short-lived Cognito ID cookie
  on Streamlit's render thread before starting its background worker. This
    prevents the worker losing browser context, resolving the fallback owner,
    and retrying a protected notebook sync with 404 every second.
19. Coach submission now accepts a validated idempotency key in the typed body
  and standard HTTP header. A durable owner/notebook-scoped reservation in
    the existing `messages` table prevents concurrent/restarted retries from
    calling the provider or inserting the turn twice, replays the exact
    completed `CoachTurn`, rejects changed-input key reuse with HTTP 409, and
    releases provider failures for a real retry. Lease ownership is verified in
    the same transaction that persists the user/assistant pair. No sixth table
    or DSQL schema change was introduced.
20. Production `/api/v1/ready` now also validates non-secret Cognito callback
  and metadata configuration locally, requires an HTTPS callback, and redacts
    DSQL/S3 exception details. Structured internal operational events cover
    route latency/status, provider/retrieval/citation results, coach stage
    recommendations, and accepted/rejected progression without prompts, source
    text, user/notebook/source/transition IDs, emails, or tokens.
21. A deterministic authenticated FastAPI production-parity regression covers
  Cognito cookie verification, notebook/source upload-selection-preview,
    grounded `[S1]` replies, idempotent replay/conflict, stage confirmation,
    process restart, object cleanup, and logout/revocation. A headed Playwright
    smoke runner preserves the real Cognito boundary and captures desktop,
    390 px mobile, and console evidence after a manually completed Hosted UI
    sign-in; it never installs a production auth bypass.
22. Streamlit retry keys now retain only a SHA-256 request scope, UUID, notebook
  id, and timestamp for one hour. The helper reuses unresolved retries, removes
    completed/deleted/expired entries, keeps at most eight per notebook and 24
    globally, preserves valid entries across notebook switches, and migrates
    only the active valid legacy entry without retaining raw prompt text.
23. The Cognito sign-in retry cooldown is server-authoritative. An absolute
  five-second deadline and a temporary 0.5-second Streamlit fragment keep the
    original button disabled without client-side DOM mutation. A bounded,
    non-sensitive per-tab query marker carries that exact deadline across a
    fresh Streamlit session after browser Back, then is consumed once; malformed,
    stale, or implausibly future values are rejected. The launch flag remains
    one-shot, and success, sign-out, logout, or configuration failure clears all
    transient state. Trusted auth navigation now uses Streamlit 1.60's
    non-iframed `st.html` API instead of the deprecated components helper.
24. DSQL idempotency tests now exercise two independent adapter instances,
  exact replay after restart, changed-payload conflict, provider-failure
    release, expired-lease takeover, stale-worker rejection, and whole-operation
    SQLSTATE `40001` retry without AWS. The guarded live runner requires
    `--confirm-live`, the DSQL provider, `co_design_app`, and an explicit
    `cognito:<sub>` owner; it uses runtime DML and the mock provider only.
25. Coach idempotency `complete_coach_request` is now idempotent when a waiter
  or restart already promoted the marker to `completed` from persisted
    message rows after the lease owner committed `persist_coach_turn` but
    before the owner completed. Matching key/fingerprint completed markers
    return successfully; expired takeover, provider-failure release, stale
    persist rejection, restart promotion, and DSQL OCC wrappers stay unchanged.
26. `APP_ENV` defaults to `development`. When `APP_ENV=production`,
  `validate_production_configuration()` fail-closes for mock provider,
    `MOCK_OPENAI` masking, sqlite/local/memory storage, DSQL admin runtime,
    insecure auth cookies, HTTP Cognito callbacks, incomplete Cognito/DSQL/S3/
    OpenAI configuration, and loopback or non-HTTPS public API/UI URLs. It
    reuses `validate_storage_configuration` and
    `validate_cognito_readiness(require_https=True)` with no network/AWS
    calls. `create_app` and `/api/v1/ready` both invoke it; readiness keeps
    a dual-gate for legacy dsql/s3 Cognito HTTPS checks during cutover.
    `compose.prod.yaml` and `.env.example` declare the env switch.



#### Validation evidence

**Local (Phases 4–8 — this phase):**

- `.venv/bin/python -m pytest -q tests/test_rate_limit.py tests/test_production_config.py tests/test_coach_idempotency.py tests/test_api.py` → **64 passed**. Upload hardening covered by
`tests/test_upload_hardening.py`; compose/Caddy assertions in
`tests/test_deployment_config.py`.
- Branch `Production-RemoveData`; no commit created in this phase.
- Phase 1–2 uncommitted work preserved.

**Local (Phase 2 — APP_ENV production fail-closed):**

- Focused suite → **39 passed** (1 warning: Starlette TestClient deprecation):
  ```sh
  .venv/bin/python -m pytest \
    tests/test_production_config.py \
    tests/test_api.py::test_local_api_ready_request_id_stream_and_graph \
    tests/test_api.py::test_readiness_fails_when_file_storage_is_unavailable \
    tests/test_api.py::test_production_readiness_requires_local_cognito_configuration_check \
    tests/test_api.py::test_production_readiness_redacts_dependency_error_details \
    tests/test_api.py::test_production_readiness_reports_cognito_configured_without_discovery \
    tests/test_deployment_config.py \
    tests/test_storage_providers.py::test_validate_storage_configuration_requires_production_fields \
    tests/test_cognito_token_jwks.py::test_production_cognito_readiness_is_local_and_requires_https_callback \
    tests/test_cognito_token_jwks.py::test_cognito_readiness_errors_do_not_echo_credentials
  ```
- `tests/test_production_config.py` alone → **21 passed**.
- `tests/test_deployment_config.py` alone → **10 passed**.
- No live OpenAI, DSQL, S3, or Bedrock calls. No schema migration.
- Branch `Production-RemoveData`; no commit created in this phase.
- Phase 1 uncommitted files (`backend/student_store.py`,
`tests/test_coach_idempotency.py`) preserved.

**Local (Phase 1 — promote-vs-complete idempotency):**

- `.venv/bin/python -m pytest -q tests/test_coach_idempotency.py` → **15 passed**.
- Focused coverage added for promote-between-persist-and-complete, five-way
concurrent same-key submissions, and API/stream HTTP 409 payload mismatch.
- No live OpenAI, DSQL, S3, or Bedrock calls. No schema migration.
- Branch `Production-RemoveData`; no commit created in this phase.

**Prior local (previous production hardening phase):**

- `.venv/bin/python -m pytest -q` → **305 passed**.
- Focused auth/UI/production-path validation → **57 passed**.
- `PYTHONPYCACHEPREFIX=/private/tmp/co-design-pycache .venv/bin/python -m compileall -q backend ui streamlit_app.py tests` → exit 0.
- `docker compose config --quiet` and
`APP_IMAGE=co-design:test docker compose -f compose.prod.yaml config --quiet`
→ exit 0.
- `sh -n scripts/start.sh scripts/start_prod.sh scripts/build.sh scripts/deploy_ecr.sh scripts/browser_e2e_smoke.sh` → exit 0; the Python
DSQL runner compiled, displayed `--help`, and refused a missing
`--confirm-live` before any connection attempt.
- `git diff --check` → exit 0.
- No live OpenAI, DSQL, S3, or Bedrock calls. No Bedrock implementation
changes.
- The approved live-click smoke performed no credential entry: two clicks
produced exactly two FastAPI login redirects and two Cognito Hosted UI GETs.
Browser Back was invoked 2.7 seconds after the first click; the slow Streamlit
reconnect completed after the five-second window with `Redirecting...`
retained and the original button enabled, proving the deadline was not
restarted. The retry remained visible at 390 px and redirected exactly once.
AppTest covers the complementary fast-remount case where Back completes before
expiry and the same button must remain disabled.
- With the developer-authorized test account, the in-app browser completed the
real Cognito Hosted UI PKCE login and callback, created/renamed a notebook,
synchronized 7 lecture notes and 3 readings, displayed a grounded mock reply
and `[S1]` citation preview, confirmed Focus → Evidence, restored the chat
and stage after refresh, rendered Review scores, deleted the disposable
notebook, and logged out.
- The live run reproduced and then verified the local foreign-key repair and
authenticated background-sync fix. After cleanup, the test owner again had
zero notebooks, messages, and sources.
- `data/backups/co_design.pre-fk-repair-20260809.sqlite3` is the pre-migration
SQLite backup. It is local data and must never be committed.



#### Compatibility, rollback, and known risks

- New S3 objects use `raw/` and `derived/` subpaths. Existing rows retain
their full historical keys, remain readable, and stay within the same
source/notebook deletion prefix. No object migration is required.
- DSQL bootstrap schema changed before live initialization. If an earlier
draft schema was already applied, inspect existing uniqueness/index state
before rerunning bootstrap; never drop production objects automatically.
- This DSQL bootstrap correction changes no table or index DDL. An earlier
failed public-schema `USAGE` grant needs no rollback; rerun bootstrap, then
apply only the documented object-level runtime grant.
- Public clients that sent unrestricted notebook/message metadata now receive
422 and must use the typed settings or internal coaching endpoints.
- RAG requires no schema migration. New assistant/user metadata may include
`retrieval_refs`; older messages without it remain compatible.
- The current local retriever reads selected extracted text and chunks it at
query time. This is deterministic and suitable for the bounded development
corpus, but it is lexical rather than embedding-semantic and is not the
long-term large-corpus index. Bedrock Knowledge Bases replaces this adapter.
- UI edit/regenerate stays unavailable until a transactional replacement
design is implemented; the new request key protects retries of normal turns
but does not define edit-in-place semantics.
- Existing local legacy tables are intentionally retained and left unchanged;
rollback is a code revert because the older application ignores the added
snake_case columns and the new five-table copies. A pre-existing database
that already ran the earlier destructive users-table migration cannot have
deleted legacy rows reconstructed from SQLite metadata; restore such rows
from a pre-upgrade backup if available. Local upload files themselves are not
deleted or rewritten by this migration.
- Split-owner repair preserves the authenticated Cognito row, moves any
five-table notebooks onto it, merges preferences, and retains the obsolete
empty row under a `legacy-orphan:<id>` identifier for inspection rather
than deleting it.
- The SQLite foreign-key repair applies only when `notebooks.user_id` targets
a table other than `users` and only when the known eight-column notebook
layout matches. An unknown layout stops with a clear error instead of losing
data. Restore the pre-repair backup to roll back the local database.
- This local compatibility phase changes no DSQL schema/bootstrap SQL, IAM,
S3, Cognito infrastructure, EC2, paid-provider, or Bedrock behavior.
- Provider-token streaming is still simulated after a complete persisted turn
and graph inspection state is process-local. Durable request idempotency now
makes a disconnected stream safe to retry, but it does not turn the buffered
response into upstream token streaming or persist graph inspection state.
- Completed idempotency reservations are stored as hidden internal rows in the
existing `messages` table. No migration is required and current code omits
them from chat/history/counts/activity. Rolling back to code that predates
this filter can expose blank internal assistant rows; back up first and remove
only rows explicitly marked `_internal_type=coach_idempotency` under an
approved rollback procedure.
- The promote-vs-complete fix changes only `complete_coach_request` behavior
for already-completed same-key/fingerprint markers. No schema or data
migration is required; rollback is a code revert.
- `APP_ENV` and `validate_production_configuration` are additive. Local
development remains the default; production Compose must set
`APP_ENV=production`. Rollback is a code/config revert with no schema or
data migration.
- Fully automated protected-browser CI remains blocked by the deliberate lack
of a production authentication bypass and by the uncached Playwright CLI.
`scripts/browser_e2e_smoke.sh` therefore pauses for a human to complete the
real Cognito Hosted UI before mobile/console capture. The deterministic
authenticated HTTP regression and Streamlit AppTests run without live AWS.
- UI retry-key records are session-only and require no migration. Reverting the
helper drops retry reuse after a disconnected Streamlit submission but does
not change durable notebook/chat data or the HTTP idempotency contract.
- The DSQL concurrency suite uses independent `DsqlStudentStore` instances
over an isolated SQLite transaction proxy, so it deterministically checks the
adapter/lease/OCC contract without claiming wire-level Aurora behavior. The
guarded live runner remains deliberately unexecuted until DSQL is ready and a
separate live-write approval is given.
- Fresh Streamlit loads and ordinary reloads have a clean browser console. The
in-app browser records React hydration errors `#418`/`#423` while restoring
Streamlit itself from cross-origin browser history; the recovered page remains
functional and no new error is emitted after it settles. The deprecated auth
components iframe was removed, but eliminating this framework-level history
artifact requires an upstream Streamlit/browser fix rather than more auth
state mutation.
- The cooldown query marker contains only an epoch deadline, is scoped to one
tab's URL, is accepted for at most a 30-second restore grace, and never
authorizes a user or changes OAuth state. No API, cookie, schema, or data
migration is required; rollback is limited to the two auth UI/test files.
- Rollback is a code/config revert. Do not commit `.env`, secrets, database
files, or uploaded content. No live AWS resource was created or modified.



#### Next exact action

Authoritative next steps for append-only revision are under **Current phase →
Next exact action** above. Continuing AWS cutover after that:

1. Configure GitHub branch protection per
  `docs/deploy/GITHUB_BRANCH_PROTECTION.md`.
2. Owner decision on public lecture PDFs per
  `docs/security/PUBLIC_REPOSITORY_CONTENT_AUDIT.md` (do not delete/rewrite
   without explicit approval).
3. Create the private S3 uploads bucket in `us-west-2` with Block Public
  Access; attach bucket list plus `users/*` object permissions to the EC2
   instance role.
4. Finish Aurora DSQL, map the EC2 role to `co_design_app`, run
  `scripts/init_dsql.py` as admin (or for existing clusters apply the
   manual notebook `conversation_revision` **and** three message revision
   column `ALTER`s in `docs/deploy/AWS_STATELESS_EC2.md`), then grant
   SELECT/INSERT/UPDATE/DELETE on all tables in `public` to
   `co_design_app`. Do not grant schema `USAGE`. App startup never DDL.
5. With separate live-write approval, run
  `scripts/smoke_dsql_idempotency.py --confirm-live --identifier  'cognito:<sub>'` under `DATABASE_PROVIDER=dsql` and
   `DSQL_USER=co_design_app`.
6. Deploy the immutable ECR image with `scripts/deploy_ecr.sh` and require
  internal `/api/v1/ready` 200. Verify Caddy edge curl checks in
   `docs/security/CADDY_PUBLIC_BOUNDARY.md`.
7. Run the full Cognito → notebook → coach → upload → edit/revise → restart →
  isolation → logout live smoke in `docs/deploy/AWS_STATELESS_EC2.md`. Use
   mock mode first; make an OpenAI request only with explicit approval and a
   cost cap.
8. Only after that smoke is green: open class-wide traffic; then consider
  durable provider streaming and Bedrock retrieval adapters.



### Previous completed work

**Professor Learning Analytics Dashboard (implementation; local deterministic validation)**

#### What changed

- Added a read-only `backend/professor_analytics` layer with typed API
contracts, one batch active-branch repository query per analytics snapshot,
and pure aggregation/service rules. It uses existing `users`,
`notebooks`, and `messages.assessment_text` data only; no table, column,
index, event tracking, DSQL migration, model call, or application write was
added.
- Added internal FastAPI routes below `/api/v1/professor` for Overview,
Students, selected Student detail, a separately requested active transcript,
Critical Thinking, and Engagement. Routes require a verified Cognito ID-token cookie
and reload the persisted user role; only existing `lecturer` and `admin`
roles pass. Anonymous requests receive 401 and students receive 403 even if
they call the URL directly.
- Added typed `LocalApiClient` methods and a dedicated Streamlit professor
shell. The shell branches before student notebook/session initialisation and
uses FastAPI only—never a store, model provider, filesystem, or DSQL client.
It implements Overview, Students + detail, Critical Thinking, and Engagement
with compact tables, labelled bar charts, neutral attention reasons, empty
states, and the established IBM Plex/slate/teal visual system.
- Active analytics excludes internal idempotency markers and messages outside
the notebook's current conversation revision. Class rosters exclude
lecturer/admin accounts and the unauthenticated `local-student` bootstrap
row.
- Final Sol review corrected the internal-row SQL predicate so ordinary API
turns carrying `coach_idempotency_key` remain visible; only rows whose
`_internal_type` is `coach_idempotency` are excluded. It also corrected
conversation counts, primary-notebook Facione scope, per-notebook sessions,
Not-started distribution, inactivity age, deterministic summary claims, and
equal-per-student weekly trends. Transcript bodies now load only after a
professor selects one notebook, and database failures return a sanitised 503.
- Engagement now reports the count/share of assessed coach responses with at
least one persisted source citation. This is labelled as source grounding,
not evidence that a student read or understood a source.



#### Calculation definitions

- `Active this week` means at least one active-branch student message in the
previous seven days. Current stage is the most recently active notebook's
persisted stage; a student with no notebook is `Not started`.
- Overall Facione is the mean of the latest assessed response's non-zero
persisted dimensions (0 means not started). Class and dimension profiles use
medians of one latest profile per assessed student; absent values stay `Not assessed` rather than becoming 0.0.
- Estimated active time groups student messages within each notebook when gaps
are at most 30 minutes. Each session contributes its span with a five-minute
minimum. It is labelled estimated active time, not time spent.
- Attention is centrally configured and transparent: no activity in seven
days (including an account at least seven days old with no activity), Focus
after eight turns in the current notebook, twelve current-notebook turns
with at most one completed stage, or latest overall Facione below 2.0 after
at least three scored dimensions. These are prompts for follow-up, not a
judgement of ability.



#### Validation evidence

- `.venv/bin/python -m pytest -q tests/test_professor_analytics.py tests/test_professor_ui.py tests/test_auth_gate.py tests/test_streamlit_ui.py` → **64 passed**
(deterministic SQLite/Fake Cognito only; no network or model calls).
- Final-review focused suite (professor analytics/UI, API client, Caddy
boundary) → **26 passed**.
- `.venv/bin/python -m pytest -q` → **406 passed** (full deterministic
suite; no paid/model calls).
- `PYTHONPYCACHEPREFIX=/private/tmp/co-design-pycache .venv/bin/python -m compileall -q backend ui streamlit_app.py tests` → passed.
- `git diff --check` → passed at implementation checkpoint.
- Post-review UI polish (responsive navigation, non-deprecated dataframe
sizing, and light-theme time-series charts) was revalidated with
`tests/test_professor_analytics.py tests/test_professor_ui.py` → **9
passed**, plus `compileall` and `git diff --check` → passed.
- In-app browser review used the real professor UI against an isolated,
synthetic 82-student API-shaped dataset. Overview, Students, selected
Student detail, Critical Thinking, and Engagement were exercised at 1440 px;
Overview was also checked at 390 px. Final browser logs contained no errors.
Review images are under the current Codex visualizations artifact directory;
no real student records or authenticated AWS session were used.
-   A later full-suite rerun reached **404 passed, 2 failed**. Both failures are
  outside professor analytics and reflect concurrent deployment configuration
  drift: `tests/test_deployment_config.py` still expected the retired
  dynamic-DNS hostname and host port 443 Caddy shape while the working tree
  currently contains a CloudFront/port-80 configuration. Those user-owned
  deployment edits were not reverted or folded into this feature.
- New coverage asserts 401 anonymous, 403 student, 200 lecturer; persisted
role rather than client claims; active-branch Facione/session correctness;
missing dimensions; constant-count repository access rather than N+1; normal
API idempotency metadata, multi-notebook conversation/session/assessment
scope, new-student inactivity boundaries; and no notebook, message, or source
mutation from analytics routes.



#### Compatibility / known limits / next action

- No existing student data changes. Rollback is a code-only revert; analytics
endpoints have no mutation path. DSQL production deployment remains gated by
the existing revision-schema cutover in the Current phase section above.
- Actual browser-presence/time-on-task, enrollment roster completeness,
normalized class-wide topics, causal learning impact, and source-reading
behavior remain intentionally unavailable. Notebook titles are shown as the
available discussion-topic proxy.
- Next: after the approved DSQL revision cutover, run a read-only live DSQL
contract/latency check, then repeat the completed desktop/mobile visual QA
with a real Cognito lecturer session. Synthetic screenshots are available,
but no live AWS, real-student-data, or production-auth claim is made.

**Provider-neutral stage prompts + retryable S3 cleanup** — `19f5d4e` on
`Production-RemoveData` (pushed). Local mock suite 232 passed; GitHub Mock CI
failed on missing CI `.env` before compose validation.

**Final pre-AWS hardening (Cognito / DSQL / student S3)** — Cognito ID
`token_use`, JWKS cache, DSQL `verify-full`, course-sync gate, orphan
object cleanup, ownership-in-write checks, `ca-certificates` in image.

**Multi-user FastAPI ownership + student S3 key isolation**

**Cognito-owned browser session + five-table persistence cleanup**

**DSQL bootstrap / adapter hardening**

**AWS stateless EC2 migration scaffolding**

**Course Q&A evidence-gap hardening** — Current working-tree phase

- High-confidence source questions now fail closed when selected-source
  retrieval raises before producing validated chunks. The server persists the
  existing evidence-gap response without invoking AgentCore, emitting model
  claims, or attaching citations. Image-only Q&A remains model-owned; a mixed
  image plus textual-source turn still requires textual evidence.
- Selected source title matching now also indexes the meaningful pieces of
  hyphenated/underscored filenames, so a question such as “L2 Network
  Bootstrapping” is classified consistently with the selected
  `L2-Network-Bootstrapping-ARP-DHCP.pdf` source.
- Added deterministic coverage for retrieval exceptions, mixed image/text
  evidence gaps, and hyphenated selected-source matching.
- Validation: focused Q&A/mode/retrieval/RAG-fallback/citation/one-call suite
  passed (101 tests); Ruff, compileall, and `git diff --check` passed. No AWS
  or paid model calls were made.
- Compatibility: no persistence/schema/API changes and no AgentCore runtime
  publication required. The next exact action is to run the focused suite in
  CI/EC2 after deploying the current backend image, then manually verify a
  selected-source Q&A with a temporarily unavailable retriever.

**Edited-message chat-history visibility** — Current working-tree phase

- During an in-flight edit, the chat fragment now renders only the authoritative
  prefix before the edited user message, followed by the revised prompt and
  Coach progress. The obsolete suffix remains hidden until the successful
  authoritative rerun.
- A bounded transient prefix snapshot handles stale fragment arguments without
  becoming a second transcript store. It is cleared on success, failure, and
  stale-target recovery; DSQL/persisted messages remain canonical.
- Validation: edit/render-plan, chat-scroll, progress, and rerun-scope tests
  passed (34 tests); Ruff, UI/backend compileall, and `git diff --check` passed.
  The broader Streamlit UI run still has the existing attachment-error AppTest
  timeout; it is unrelated to edit rendering and was not changed here.
- Compatibility: no backend, API, persistence, AgentCore, RAG, attachment,
  citation, HMW, or stage semantics changed. The next exact action is a manual
  delayed edit check at desktop and mobile widths after the app rebuild.

**Fast Chat structured-output boolean contract hardening** — Current working-tree phase

- The Fast Chat model-facing schema now requires `needs_source_retrieval` as a
  non-null boolean, matching Pydantic validation. Previously its Python default
  made the generated property optional/nullable, so a Q&A `null` could produce
  the category-only `structured_output_failure` envelope despite successful RAG.
- The Fast Chat Q&A prompt now explicitly emits `hmw_scaffold_ready: false` and
  `needs_source_retrieval: false` as JSON booleans. Strict validation, one outer
  invoke, bounded recovery, RAG, citations, HMW, Deep Review, and Guardrails
  are unchanged.
- Validation: focused schema, prompt-composition, first-cycle, runtime parser,
  HMW, Fast Chat one-call, Deep Review, and provider envelope tests passed;
  Ruff, compileall, and `git diff --check` passed. No AWS or paid model calls.
- Compatibility: `agentcore_runtime` changed, so republish the runtime before
  using this fix. FastAPI application logic is not required to change, but the
  production host must recreate the app with the next
  `AGENTCORE_SESSION_GENERATION` after publishing so affinity sessions cannot
  retain the previous runtime assets. Next exact action: publish the updated
  runtime, bump the host generation, and run bounded normal/revised RAG Q&A
  smoke tests.

**Coach welcome HMW guidance** — Current working-tree phase

- Added a concise opening sentence encouraging students to craft a “How Might
  We” problem statement before the first design-challenge prompt.
- No coaching, HMW detection, stage, persistence, or AgentCore behavior changed.
- Validation: welcome/HMW/context-planner focused tests, Ruff, compileall, and
  `git diff --check` passed.

**Attachment UX, scrolling, and CDE2300 scope boundary** — Current working-tree phase

- The chat feed is now a bounded flex scrollport, keeping the composer outside
  the scroll region while long attachment turns remain scrollable.
- Persisted turn attachments render as compact, type-aware file cards with
  filename, type, size, and the existing authorized viewer action.
- Fast Chat now carries a strict model-facing `out_of_scope` boolean. At high
  confidence only, clearly unrelated content is replaced by fixed server-owned
  CDE2300 boundary copy with no citations, HMW readiness, stage recommendation,
  retrieval retry, or qualifying coaching increment. Plausibly project-relevant
  technical/domain material remains in normal coaching/Q&A.
- No new model/retrieval call, API/persistence schema, source authorization,
  citation, HMW, or stage rule was added. The stale attachment AppTest mock was
  updated to target the current `upload_attachments` path.
- Compatibility: publish the changed AgentCore prompt/schema as a new
  immutable runtime version, wait for `READY`, then rebuild the app and bump
  `AGENTCORE_SESSION_GENERATION` so affinity sessions do not retain the old
  runtime contract. No database migration is required.
- Next action: run the focused deterministic suite and a desktop/390 px smoke
  test with one CDE2300 attachment and one clearly unrelated attachment.
