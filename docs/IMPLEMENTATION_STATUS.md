# Implementation status

## Current status

### Visible word groups and system motion preference (2026-11-23 SGT)

React paces provider reply fragments so a single network burst can produce
several visible word updates. Normal and edited sends share the same preview.
Validation and durable saves remain server-owned. Final-only replies show
without a typing effect. Settings no longer includes Reduce motion. The
browser's system motion preference controls animation and scrolling.

Frontend build and disposable browser checks passed. Normal and edited mock
replies visibly grew on delayed and fully batched delivery, including at
390 px with system reduced motion. Light and Dark, draft retention, saved
reply recovery and the console passed. Available locally on port 8081.
No schema, runtime, or production deployment change. Rollback restores the
previous frontend. Next action is review in the local preview.

### Compact Summary header live (2026-11-23 SGT)

Review puts **Summarise chat** at the top right of the brief, beside the title,
as a tinted button with a sparkle icon, full label and a 44px touch target.
The tooltip stays aligned to the button. Build, mock image and browser checks
passed at 1440, 390 and 320 px in Light and Dark. CloudFront serves
`summary-polish-12b7e4ce0167` and public health passed. Restore the previous app
and Caddy configuration from `releases/before-summary-polish-12b7e4ce0167`
for rollback. No stored data, schema or runtime changes are required.
Next action is student review of the Summary header on the public app.

### Lecture Help greeting and mode guidance (2026-11-23 SGT)

Lecture Help now answers a bare greeting without attachments with a short course
question prompt, without retrieval or a model call. Other lecture turns include
explicit course Q&A instructions so prior design coaching does not steer the
reply. The existing evidence scope and student-confirmed progression rules
still apply to substantive turns. Authenticated reader, evidence scope and
provider contract checks cover the change. No schema or runtime build change.
The app was deployed to the existing CloudFront site as
`release-e2fa69cae6d7`, built from the pushed commit `e2fa69c` on
`improvement/combined-testing1`. Host readiness and public health passed.
CloudFront serves `index-DwOZdiXQ.js` with the updated Summary action, and the
Stop endpoint remains authenticated. The exact release image passed a
network-free smoke including the Lecture Help greeting. No paid prompt,
schema migration, or runtime update was needed. The previous app and Caddy
configuration are available at `releases/before-release-e2fa69cae6d7`.
Next action: student review on the live app.

### Click-to-summarise and simpler student settings (2026-11-23 SGT)

The filled **Summarise chat** button sits above the project brief fields and
explains on hover and keyboard focus that it summarises the whole chat. Opening
Summary reads saved state without starting generation. The settings page drops
the duplicate export area and reasoning effort field. Review still downloads
the project, and chat actions still share or download the transcript. Chat
name, assignment context, and deletion remain in the current chat/notebook
section. The student response defaults are read-only English and the configured
model. Production chat is configured for Claude Haiku 4.5, and the mock preview
labels its mock coach accurately. Normal sends and both edit paths request
English for React without rewriting older preferences or changing the legacy
Streamlit path.

Focused HTTP, frontend build and disposable browser checks passed, including
click-to-generate, hover/keyboard, cached and failed states, download and
Light/Dark layouts down to 390 px. The full mock suite passed 3,182 tests with
one optional skip. Local preview is refreshed at port 8081.
No schema or runtime change was needed. These settings shipped in the same
app release recorded above.

### Legacy chats, composer Stop and session continuity (2026-11-23 SGT)

- The React sidebar projects all unmarked old conversations as standalone
  chats without rewriting their saved IDs, history or sources. New React
  notebooks carry an explicit settings marker. Older folders created before
  that marker also appear as chats. Existing saved parent source scope stays
  available. No database schema migration or data rewrite.
- The composer shows bouncing dots and an icon button that requests cancellation
  of the exact authenticated stream. Before save, the unfinished reply is
  discarded and the prompt remains available. A turn already saving can finish.
  Provider-stream closure is best effort. A previously recorded edit revision
  remains retryable with its original key.
- The chat actions menu opens upward and clamps to the visible viewport after
  its settings load. Quick tab switches keep the open chat and Review in memory.
  Quiet session checks are throttled to one minute. Explicit sign-out signals
  other tabs without storing any private data.
- The disposable browser passed Stop, prompt retention, menu bounds at 1440 px
  and 390 px in Light and Dark, keyboard open/close, and zero session requests
  during a quick tab switch with Review open. Final console was clear. Focused
  HTTP covered owner-scoped cancellation, preservation during the save race,
  retry and restored folder/chat identities. Build, compile, and Caddy checks
  passed. Local preview refreshed on port 8081.
- Deployed to the existing CloudFront app as `workspace-20261123-73468aa6ca11`.
  Host readiness and public health passed. CloudFront serves React bundle
  `index-B73H7hra.js`; the new Stop route returns 401 without credentials, and
  internal readiness remains private. The exact image passed a network-free
  mock smoke. The full mock run passed 3,181 tests with one optional skip.
  AgentCore DEFAULT remains ready on v36. No live generation or migration ran.
- Rollback: restore the previous app image and Caddy configuration from
  `releases/before-workspace-20261123-73468aa6ca11` on EC2. Existing settings and
  database rows need no rollback. Next action: student review on the live app.

### React and AgentCore streaming live on the existing app (2026-11-23 SGT)

The production student workspace serves the approved React/Review update.
AgentCore DEFAULT v36 is ready, and the app is healthy with session generation
`20261122-streaming-v36`. All five paid prompts streamed and saved. PDF grounding,
confirmed progression, edited-message image retention and notebook source reuse
were verified. Two image answers guessed the meaning of a visible marker. No
schema migration or IAM changes. The previous app and v35 are retained for
rollback. The [production validation report](specs/PRODUCTION_STREAMING_VALIDATION.md)
records exact artifacts, timings, answer quality, persistence and follow-up.


### Normal, edited and AgentCore LLM reply streaming implemented locally (2026-11-22)

Regular sends and edits now share the NDJSON partial-reply lifecycle. Deltas are
on by default for capable clients; legacy JSON edits and clients without the
header keep their contracts. Direct Bedrock and optional OpenAI forward actual
provider fragments. AgentCore Fast Chat requests the updated runtime's SSE
protocol, forwards Strands tool-input fragments while generation is running,
and extracts only top-level response_text in FastAPI. Only validated final
output is persisted. Failed/repaired attempts withdraw their earlier previews.
No extra model call simulates typing. Edited-message revision, attachments/intent,
usage/provenance, exact-key recovery and separate composer drafts are preserved.
Reduced motion keeps reply text visible. Caddy flushes stream responses promptly.

- **Files:** settings/example configuration, Caddy files, AgentCore provider plus
  `backend/agentcore_stream.py`, optional OpenAI provider, runtime main/README,
  shared streaming/revision service, canonical/reader HTTP routes, Conversation,
  HTTP/provider/runtime/route tests and browser fixtures/regressions. Guides and
  detailed rollout: [streaming handoff](specs/REPLY_STREAMING_HANDOFF.md).
- **Validation:** red/green cycles covered default enablement, provider fragments,
  runtime delivery before completion, streamed edits, and discard before retry.
  **236 focused**, **3,180 full mock tests passed** (one existing optional-SDK
  module skipped in the application venv). A separate temporary environment with
  exact runtime pins passed **16 SDK tests**, including real Strands callbacks
  through the public runtime entrypoint before the fake model finished; dependency
  diagnostics reported no AWS/paid calls. An older optional recovery test now uses
  an invalid recommendation rather than null, matching the existing default-to-stay
  change while retaining the two-turn repair check. Dependency warnings remain.
- **Browser/startup evidence:** real mock-server chunks visibly grew for normal
  and edited replies at 1440/390 Light/Dark with app/OS reduced motion, no replay,
  no provisional saved actions and clean console. Scroll, edit/failure recovery,
  bookmark and Summary regressions passed. Public messages/project/bookmarks
  remained identical across a disposable backend restart. Production-style Caddy
  delivered the first mock delta at 0.456s and done at 1.220s (delivery fixture
  timings, not LLM performance). Production build/typecheck, compileall, Caddy
  validation, documentation links and whitespace checks pass. Evidence lives in
  `/private/tmp/llm-streaming-qa/`; screenshots are ignored under
  `output/playwright/reply-streaming/`.
- **Compatibility/rollback:** no migration or data rewrite. Existing user work
  and startup script preserved. The user preview on 8081 was rebuilt/restarted in
  mock mode; health/Streamlit respond, and the new proxy route reaches credential
  checks (401 without credentials). Set `COACH_STREAM_REPLY_DELTAS_ENABLED=false`
  and restart for backend rollback; legacy JSON routes remain. Runtime rollback
  uses the previous READY qualifier on the existing ARN. No staging, commit,
  deployment, IAM edit or paid LLM request occurred.
- **Risks/remaining rollout:** code is locally implemented and mock/SDK verified,
  but the existing AWS runtime/app have **not** been republished. They need the
  compatible app parser then updated runtime on the existing ARN before live
  AgentCore fragments appear. No live-LLM performance or production rollout claim
  is made. Mobile QA uses browser emulation, not a native software keyboard.
- **Next exact action:** review the streaming handoff and approve publication to
  the existing application/runtime if wanted. Any paid live smoke check also
  needs an explicit request/token/cost cap. Local mock review remains on 8081.

### Text-sized edit width and reply-streaming audit (2026-11-22)

Short edit bubbles now start at 260px, aligned with the student's original
right-hand bubble. The longest edited line is measured in the field font;
longer text widens the editor up to the chat column, and height remains automatic.
The icons stay inside the bottom-right footer without covering text. Removing
text shrinks the editor; there is no manual resize control.

The separate streaming check confirms regular sends use FastAPI
`StreamingResponse` with NDJSON, and React reads its body incrementally. Actual
provider reply fragments require the default-off `COACH_STREAM_REPLY_DELTAS_ENABLED`
flag plus the client header (already sent by React). Direct Bedrock supports
`converse_stream`; AgentCore reads/assembles its result and emits no incremental
reply fragments. Revised-message sends use a regular JSON response. The local
preview forces mock providers, so this audit makes no live-LLM claim.

- **Files:** Conversation sizing, edit-width CSS, both message-edit browser
  regressions, React README/design, testing guide and this status entry. Streaming
  code/configuration is inspected only and unchanged.
- **Validation:** rendered red/green caught the full-width short editor, followed
  by Light/Dark desktop/390 short/long widths, automatic height, icon containment,
  hover/keyboard, save/reload, draft and failed-edit recovery checks. Smooth-scroll
  and saved-preview regression remains passing. Production build/typecheck,
  documentation links and whitespace checks pass. All **110 streaming/provider
  mock tests passed**. A disposable HTTP request confirmed NDJSON and five received
  chunks with progress/final-preview/save events under default-off configuration.
  Evidence: `/private/tmp/codesign-latest-control/width-*.log`,
  `streaming-audit-tests.log` and `streaming-http-check.log`.
- **Compatibility/rollback:** no API, schema, data or provider changes; undo only
  the width measurement and edit-width CSS, then rebuild, to restore full width.
  Existing user work remains intact; no paid call, staging, commit or deployment.
- **Risks:** HTTP streaming is not equivalent to token-by-token model output;
  AgentCore and revision responses need separate work for that behavior. Mobile
  width checks are emulated rather than native software-keyboard QA.
- **Next exact action:** refresh port 8081 and edit short/long messages. A future
  token-streaming phase should begin at the provider/transport boundary, especially
  AgentCore and revision handling; no streaming setting was enabled here.

### Compact automatic edit sizing without resize controls (2026-11-22)

Short edited messages use a compact one-line field (52px minimum), grow with text
up to 360px/the viewport cap, and shrink again as text is removed. The manual
resize handle is removed. Cross/up-arrow icons retain their inset bottom-right
footer, borders, hover colours, 44px targets and separate text space.

- **Files:** edit textarea CSS, both message-edit browser scripts, React
  README/design, testing guide and this status entry. Existing one-row/52px sizing
  in Conversation is preserved and validated.
- **Validation:** rendered red/green caught the remaining resize handle. Checks
  cover short-to-long-to-short sizing, Light/Dark desktop/390 compact/long states,
  icon containment/hover, keyboard, save/reload, draft preservation and failed-edit
  recovery; the smooth-scroll/saved-preview regression remains passing. Production
  build/typecheck, local documentation links and whitespace checks pass. Evidence:
  `/private/tmp/codesign-latest-control/autoheight-*.log`; compact screenshots use
  ignored `output/playwright/latest-control/edit-compact-*.png`.
- **Compatibility/rollback:** presentation only; no API, schema or data change.
  Restore `resize: vertical` to undo handle removal, then rebuild. Existing user
  work is preserved; no paid call or Git publication. Python is unchanged, with
  the preceding 3,168 passed / one skipped full mock baseline.
- **Risks:** no known blocker; mobile widths are emulated rather than native
  software-keyboard QA. Very long edits scroll inside the automatic height cap.
- **Next exact action:** refresh port 8081, edit a short message, add/remove lines
  and inspect automatic sizing with the two icons still inside the box.

### Edit icons inside the textbox (2026-11-22)

The edit cross/up arrow now sit at bottom right inside the textbox's shared
border, matching the composer's structure. A reserved footer keeps both icons
clear of long scrolling text. Borders, hover colours, 44px targets, accessible
names, keyboard actions and the short replacement/draft note are retained.

- **Files:** Conversation, styles, both message-edit browser scripts, React
  README/design, testing guide and this status entry.
- **Validation:** rendered red/green checks cover containment and inset placement,
  reserved text space, Light/Dark desktop/390, hover, keyboard, cancel/focus,
  successful revision/reload and failed-edit recovery without write replay.
  Production build/typecheck, documentation links and whitespace checks pass.
  Evidence: `/private/tmp/codesign-latest-control/inside-*.log`; screenshots under
  ignored `output/playwright/latest-control/edit-*.png`. Python code is unchanged;
  preceding full mock baseline is 3,168 passed / one skipped.
- **Compatibility/rollback:** presentation only; no API, schema or data change.
  Restore this phase's edit-box wrapper/footer CSS and rebuild to undo. Existing
  user work/startup script preserved; no paid calls or Git publication.
- **Risks:** no known blocker; mobile QA uses browser width emulation rather than
  a native software keyboard.
- **Next exact action:** refresh port 8081, open Edit on a message and check the
  inset cross/up arrow and their hover colours.

### Smooth latest scrolling and in-place message editor (2026-11-22)

The floating circle scrolls smoothly through the chat, then resumes following.
If a reply moves the destination during the animation, scrolling continues to
the new bottom. Transcript wheel/pointer/key interaction stops automatic pursuit.
App/OS reduced-motion preferences use an instant move. Existing dots, idle
visibility, transparent surround, compact size and 8px hints gap remain.

Edit now replaces the original student text/actions in that same message bubble
with a wider, auto-growing field (160–360px with a viewport cap), without showing
the saved text twice. Bordered 44px cross and up-arrow icons sit at bottom right,
with accessible names/tooltips, theme hover colours and a short consequence note.
Enter adds a newline; Escape/cross cancels and restores Edit focus. Chat symbols
also gain hover colours while saved stars retain gold. Existing revision requests,
read-first recovery and the separate composer draft remain intact. Failed-edit
discard restores both the draft and attempted edit together.

- **Files:** Conversation and styles; existing latest-control browser scripts;
  new `tests/browser/message_edit.js` and `message_edit_qa.js`; React README/design,
  testing guide and this status entry.
- **Validation:** separate red/green cycles reproduced instant movement and the
  duplicated/cramped editor. Browser checks cover intermediate smooth motion,
  output arriving during animation, reduced motion, desktop/900/390 Light/Dark,
  floating-control placement, keyboard, hover, exact original text, bounded large
  editor, empty-value prevention, one successful revision/reload and failed-edit
  recovery without write replay. Existing bookmark and Summary regressions pass.
  All **19 focused** and **3,168 full mock tests passed** (one existing skip;
  dependency warnings retained). Production build/typecheck, compileall, local
  documentation links and whitespace checks pass. The design detector reports
  existing style conventions, with no new blocking finding. Test evidence
  is under `/private/tmp/codesign-latest-control/` (`smooth-*`, `edit-*`, `final-*`);
  screenshots remain under ignored `output/playwright/latest-control/`.
- **Compatibility/rollback:** presentation only; no API, schema, provider or data
  change. Undo only this phase's frontend hunks and rebuild; no DB restore. Existing
  user work/startup script preserved. No paid calls, staging, commit or deployment.
- **Risks:** no known runtime blocker; phone widths/reduced motion are browser
  emulation, not native software-keyboard/device QA. Existing dependency warnings
  and process-local tests-package binding remain.
- **Next exact action:** refresh port 8081, scroll up and click the circle; then
  edit a message to review the larger in-place field and bottom-right icons.

### Latest circle floats transparently with an 8px gap (2026-11-22)

The compact control now overlays the transcript, centered 8px above coach hints,
expanded suggestions, Show suggestions or the composer when those are absent.
It reserves no blank horizontal band. Only its circle is opaque; surrounding
text remains visible and pointer interactions pass through outside the button.
The 44px tap target, working dots and scroll-aware idle visibility are retained.

- **Files:** frontend styles, `tests/browser/latest_above_hints.js`, React
  README/design, testing guide and this status entry.
- **Validation:** the rendered test measured the previous 13px visible gap, then
  passed at 8px with transcript overlap and pointer hit-testing around the circle.
  Light/Dark desktop/390 expanded/collapsed/check-in states, keyboard and console
  checks passed. Working/idle regressions also cover 1440/900/390, reduced motion,
  no request replay and unchanged saved previews/full originals. Production
  build/typecheck passed. Evidence: `/private/tmp/codesign-latest-control/floating-*.log`.
- **Compatibility/rollback:** CSS presentation only; no data, API or schema
  change. Restore the previous row positioning and rebuild to undo. Existing
  uncommitted work remains intact; no paid call or Git publication.
- **Risks:** the circle intentionally covers a small area of text while floating;
  its surroundings remain readable/selectable. Widths are browser-emulated.
  Backend code is unchanged and retains the preceding full mock-suite baseline.
- **Next exact action:** refresh port 8081, scroll up, and expand/hide suggestions
  to review the transparent floating circle and tighter gap.

### Compact latest control above hints (2026-11-22)

The working/latest circle is now visually 32px with a 16px arrow and smaller dots,
while retaining a 44px invisible tap/keyboard target. Its entire row sits above
coach check-ins, expanded suggestions and the collapsed Show suggestions control;
when these are absent it sits above the textbox. Existing generation and
scroll-aware visibility behavior is preserved.

- **Files:** Conversation, styles, latest-control browser test plus the new
  `tests/browser/latest_above_hints.js`, React README/design, testing guide and
  this status entry.
- **Validation:** separate red/green cycles reproduced the oversized circle and
  below-hints position. Production build/typecheck passed; rendered checks cover
  check-in, expanded/collapsed suggestions, Light/Dark desktop/390, keyboard,
  clean console, working/idle scroll behavior and saved-preview preservation.
  Evidence is under `/private/tmp/codesign-latest-control/sizing-*.log` and
  `placement-*.log`; screenshots remain under ignored `output/playwright/latest-control/`.
- **Compatibility/rollback:** presentation only; no data, API or schema change.
  Restore this phase's CSS and row order, then rebuild, to undo. Existing user
  work and local server remain intact; no paid calls or Git publication.
- **Risks:** no known blocker; mobile widths are browser-emulated. Backend code
  is unchanged and retains the preceding mock-suite baseline.
- **Next exact action:** refresh port 8081 and scroll up in Design coaching;
  expand/hide suggestions to inspect the compact circle above either state.

### Latest arrow follows scroll position (2026-11-22)

The idle down arrow appears only when the student is away from the bottom and
hides upon reaching the latest message, by button, keyboard or manual scroll.
Working dots remain visible during generation regardless of scroll position.
The control row also disappears when idle at the bottom, reclaiming its space.
Transcript/content resizing updates the state, with a 4px rounding tolerance;
a student who scrolls away keeps their place while new output arrives.

- **Files:** `frontend/src/Conversation.tsx`, the two latest-control browser
  scripts, React README/design, testing guide and this status entry.
- **Validation:** the rendered regression failed against the previous always-on
  arrow, then passed. Light/Dark 1440/900/390 checks cover working dots at the
  bottom, idle visibility, small/manual scrolling, Enter/Space, reduced motion,
  no extra requests, unchanged preview bounds and intact originals. Production
  build/typecheck and bookmark/Summary regression results recorded with browser
  logs in `/private/tmp/codesign-latest-control/visibility-*.log`.
- **Compatibility/rollback:** presentation only; no API, storage, data or schema
  change. Revert this scroll-visibility change and rebuild to restore the previous
  always-visible arrow. Existing uncommitted work and user server preserved.
- **Risks:** no known blocker; responsive QA uses browser emulation. Python code
  is unchanged; the preceding full mock suite is the backend baseline.
- **Next exact action:** refresh port 8081, scroll up to reveal the arrow, then
  return to the latest message to see it hide; send a mock question for dots.

### Working/latest circle and bounded My work previews verified (2026-11-22)

Chat now has a centered 44px circle directly above the textbox: three dots while
watching/checking a reply, then a down arrow when idle. Either state scrolls to
the bottom and resumes following. It never sends, aborts or retries a request;
textual status, Stop watching, recovery, draft and intentional scroll behavior
remain. Dot motion respects preferences; clean empty chats hide the control.

My work already had a **320-character API preview limit**. A newline-heavy
320-character sample still occupied eleven lines, so previews now have a **six-line
visual cap**. Full originals remain intact through Jump. Clamped coach Markdown
keeps formatting with display-only links to prevent invisible clipped focus targets;
full original links stay active.

- **Files:** Conversation, Icon, CoachText, ThinkingPath and styles; two rendered
  browser regressions; React README/design, testing guide and this status entry.
- **Validation:** red/green tests caught the missing working control and the
  newline-heavy overflow. New desktop/900/390 Light/Dark checks verify state
  changes, 44px placement, keyboard scroll, reduced motion, no request replay,
  intact saved replies/originals and preview bounds. All 25 focused and **3,168
  full mock Python tests passed** (existing namespace binding). Build, compileall,
  whitespace, links and existing bookmark/Summary regressions passed. Visual
  inspection confirmed the circle and capped previews; the design detector found
  existing style conventions, with no new blocking issue.
- **Compatibility/rollback:** frontend-only; no API, persistence, schema, provider
  or data changes. Revert only this phase's frontend changes and rebuild; no DB
  restore. Existing user work/startup script preserved. No paid call, staging,
  commit or deployment. User server remains available with the rebuilt frontend.
- **Risks:** no known runtime blocker; existing dependency warnings/import
  workaround remain. Preview content is deliberately abbreviated; Jump opens
  the full original. Browser motion/widths are emulated, not native OS-device QA.
- **Next exact action:** refresh port 8081 and send a mock message; inspect the
  circle while working/finished and a long saved preview in My work.

### Outer feedback count colours matched (2026-11-22)

Summary stage rows now show the Going well phrase/count in the same green as
its expanded feedback, and To work on in the same yellow/amber. The separator,
stage heading and No saved feedback yet caption remain neutral. Labels, exact
counts, screen-reader descriptions and collapse controls are unchanged.

- **Files:** `frontend/src/ThinkingPath.tsx`, `styles.css`, React README/design
  and this status entry. No backend/API/data/provider or migration change.
- **Validation:** frontend build, existing saved/empty Summary browser checks
  and direct expanded/outer colour comparisons at desktop/390px in Light/Dark.
  Wrapping/disclosures, whitespace and affected documentation links checked.
  Python was not rerun for this isolated JSX/CSS change; the unchanged backend's
  latest full mock run remains 3,168 passing tests.
- **Compatibility/rollback:** revert only the count spans/colour rule and rebuild;
  no data restore. Previous work and user server preserved. No paid call,
  staging, commit or deployment. No known blocker.
- **Next exact action:** refresh port 8081 and inspect the collapsed stage counts.

### Saved-star visibility and My work hierarchy verified (2026-11-22)

Saved stars now render as solid gold in Chat and My work; unstar restores an
outline. The repro confirmed correct saved/pressed state, but a more-specific
shared action rule forced indigo and the original fill was almost transparent.
The fix corrects that CSS override without changing persistence.

My work now has accent stage headers, actual saved-count badges, named parent
regions, inset entries with a subtle guide, clear separators and quieter Jump
controls. Canonical grouping, previews/labels, removal, exact jumps, independent
collapse, keyboard access and 44px controls are preserved in both themes.

- **Files:** ThinkingPath JSX/styles, one new rendered regression and affected
  React/testing guides. Detailed diagnosis, file list and evidence are in the
  [bookmark handoff](specs/STARRED_MESSAGES_HANDOFF.md#star-visibility-and-my-work-refinement-2026-11-22).
- **Validation:** 25 focused and **3,168 full mock Python tests passed**, no
  failures/skips. New Light/Dark 1440/900/390 browser checks, the existing main
  bookmark regression and both Summary regressions passed. Build, compileall,
  whitespace and local links passed; desktop/phone captures inspected.
- **Compatibility/rollback:** no API/schema/data/provider change or migration.
  Previous #30/#31/brief work and user startup script preserved. Revert only this
  refinement's JSX/CSS and rebuild; no DB restore. No paid call, commit or deployment.
- **Risks:** no runtime blocker; existing dependency warnings/import workaround
  remain. User server stays available with the rebuilt frontend.
- **Next exact action:** refresh port 8081 and inspect Chat stars / My work.
  No further implementation phase is pending.

### Whole-chat project brief and clean Summary implemented (2026-11-22)

Summary now leads with **Your project so far**, synthesising the complete active
chat into Who and why, Problem, Current idea, What matters and Still to explore.
It replaces recent prompts/recap, retains uncertainty and explicit unknowns, checks
exact student evidence, caches by whole-chat identity/content and rejects stale or
partial output. Provider failures require explicit retry. The lecture materials
shape the categories rather than becoming a lecture-connections block.

The Impeccable refinement makes the brief primary with a tighter title gap,
consolidates stage feedback into one compact group with real saved counts and
independent disclosures, and puts six detailed skill scores/tips on demand while
retaining strongest/grow/Practice. Download immediately includes a new brief.
Review persistence, privacy and all saved feedback remain.

- **Files:** focused brief service/types/prompts, provider transport, metadata key,
  reader projection/POST, usage and proxy allowlists; React brief/Review/export and
  styles; HTTP/browser tests and guides. See the full file list and evidence in the
  [project brief handoff](specs/PROJECT_BRIEF_HANDOFF.md).
- **Validation:** 160 focused and **3,168 full mock Python tests passed**, no
  failures/skips. Red/green HTTP/browser cycles, full-history/unknown/evidence/cache/
  retry/ownership checks, build/compile/proxy/whitespace/link checks and rendered
  Light/Dark desktop/390px QA are recorded in the handoff. Existing Summary,
  Review persistence and starred-message journeys are preserved.
- **Compatibility:** additive optional settings-text cache, no schema migration,
  personal-data edit or Streamlit source change. Existing #30/#31 and the user's
  startup script are preserved. Roll back this phase's app/UI/proxy changes and
  rebuild; old apps ignore optional caches. No DB restore, paid call, staging,
  commit or deployment.
- **Known limits:** the local app uses mock replies and honestly shows an
  unavailable summary preview. Populated QA uses a scripted model boundary.
  Real summaries need a configured model and matching AgentCore Review runtime;
  no live semantic-quality validation or deployment is claimed. Context budgets,
  per-owner local cache locking and existing dependency warnings remain.
- **Next exact action:** refresh the local app at 8081 and inspect Summary. No
  further implementation phase is pending. Any live test needs an approved cap;
  staging/commit/deployment require separate authorization.

### Review refinements verified locally (2026-11-22)

Summary now provides independent stage/Going well/To work on disclosures and a
Chat overview quoting recent saved student prompts with the unchanged, explicitly
partial saved coach recap. Redundant stage progress is removed from Summary.
Review restores its open/closed choice and selected view per verified owner/chat
through visibility resets, navigation and reload. Private content still clears
and is fetched again. Mobile Practice keeps Review open with a draft confirmation;
explicit close actions and #31's original-message navigation remain intentional.

- **Files/evidence:** React ThinkingPath, Conversation, App and styles; five new
  rendered-browser scripts and two adapted Summary fixtures; React/docs guides.
  Details, root cause, interaction choices and commands are in the
  [Review handoff](specs/REVIEW_REFINEMENTS_HANDOFF.md).
- **Validation:** four red/green behavioral slices, all 32 focused Python tests
  and all **3,163 mock Python tests passed**, no failures/skips. Existing test-namespace
  workaround retained. New browser checks, both Summary regressions and the main
  starred-message regression passed. Real API restart preserved identical public
  project/transcript/bookmarks and restored open Summary. Final frontend build,
  compileall, whitespace and local-link checks passed.
- **Browser:** rendered Light/Dark at 1440/900/390; keyboard, 44px targets, wrapping,
  no Review writes, clean unexpected-error checks, chat/owner isolation and explicit
  closes passed. Screenshots inspected. Native hidden-tab signaling is suppressed
  by the test browser; visibility events were supplied explicitly, with real
  navigation away/back and reload tested separately. See handoff for this limit.
- **Compatibility/rollback:** frontend-only change, no API/schema/data migration,
  paid call or personal-data edit. Only display choices enter tab-session storage.
  Roll back this phase's frontend changes/rebuild; no DB restore. Existing #30/#31
  work and user startup-script edits preserved. No staging/commit/deployment.
- **Risks:** blocked tab storage prevents remount restoration; overview excerpts
  deliberately cover only recent prompts, and the saved recap may be stage-scoped.
  Existing dependency warnings remain. No runtime blocker. User API/Streamlit
  health passed; final rebuilt app remains available at port 8081.
- **Next exact action:** refresh the local app and inspect Review → Summary.
  No further implementation phase is pending; any staging/commit/deployment
  requires separate authorization.

### Starred messages #31 verified; both approved tickets complete locally (2026-11-22)

Chat now saves stars for either author. My work contains only those bookmarks,
grouped by saved stage with bounded previews, author/lecture labels, Remove star
and exact original-message jumps, including messages outside the loaded page.
No stage is collapsed and present only when populated. Keyboard/mobile controls,
visible failure feedback and GET reconciliation are included. Summary #30 remains
intact; Progression's saved-work links now point to that stage's stars.

Implementation spans the reader API, workspace service, existing message metadata,
DSQL write inventory and React workspace; five new authenticated HTTP tests and
three rendered-browser regressions cover acceptance. Full file list, red/green
history, evidence and repeatable commands are in the
[bookmark handoff](specs/STARRED_MESSAGES_HANDOFF.md).

- **Validation:** all 44 focused tests and all **3,163 mock Python tests passed**,
  no failures/skips. Full suite uses the documented process-local test namespace
  binding for this machine's installed `tests` package collision. Final React build,
  Python compilation, diff whitespace and affected local doc links passed.
- **Browser/startup:** real 1440/390 Light/Dark checks passed for star/unstar,
  bookmark-only My work, failure retention, mode tags, old-page jumps, focus and
  highlighting, reload, keyboard, 44px targets and clean unexpected-error checks.
  Imported No stage/removal/empty states passed. Both #30 Summary regressions passed.
  Actual API restart preserved identical public bookmark/transcript/project JSON
  and reloaded rendered stars. FastAPI and Streamlit startup health returned 200.
  Disposable services/browser were stopped after validation.
- **Compatibility/rollback:** no schema migration or personal data changes. Strict
  booleans merge into existing message metadata; active ownership/revision checks
  exclude superseded messages and edits do not inherit stars. Roll back application
  changes/rebuild; the old app safely ignores stored booleans. User startup-script
  changes are untouched. No staging, commit, deployment or paid API call.
- **Risks:** dependency warnings and the existing test-import workaround remain.
  Bookmark reads scan active history; no index/schema was added for this local
  prototype. No runtime blocker remains. Evidence is under
  `/private/tmp/codesign-stars-31/` and ignored `output/playwright/stars-31/`.
- **Next exact action:** review both approved tickets' local changes, starting with
  `frontend/src/ThinkingPath.tsx` and the handoff. No further implementation ticket
  is pending; staging/commit/deployment require separate authorization.

### Summary #30 verified; bookmarks #31 next (2026-11-22)

Summary now renders its saved project summary at full panel width, each Thinking
Path stage's saved Going well and To work on feedback in canonical order, then
the existing Facione scores, tips and Practice action. Missing feedback is
explicitly unassessed; phone feedback groups have readable separation. My work
still has its existing journey until #31 replaces it with bookmarks.

Changed implementation: `frontend/src/ThinkingPath.tsx` and
`frontend/src/styles.css`; added two rendered-browser regressions under
`tests/browser/`. Updated React README/design and the testing guide. Detailed
evidence, file list, commands and #31 entry point are in the
[Summary handoff](specs/STAGE_REVIEW_SUMMARY_HANDOFF.md).

- **TDD and browser evidence:** missing ordered stage feedback and missing group
  spacing each failed before their implementation. Both browser regressions pass.
  Real 1440 px and 390 px Light/Dark QA verified exact saved wording, stage order,
  full-width summary, empty states, wrapping/spacing, unchanged score values,
  tips/Practice, keyboard tabs, reload, no Review POSTs and a clean console.
  API restart preserved the entire project response and rendered Summary.
- **Focused/full validation:** all 11 focused student-journey/notebook-reader HTTP
  tests passed. TypeScript/Vite build and Python compilation passed. All **3,158
  mock tests passed**, no failures or skips. The standard build's pytest collection
  encounters an installed `tests` package shadowing this repository; the full run
  explicitly bound the local test namespace without changing files or excluding
  tests. Exact command is in the handoff. Dependency deprecation warnings remain.
  FastAPI and Streamlit health/startup passed on disposable data; both test services
  and the test browser were stopped afterward.
- **Compatibility/rollback:** no API, schema, stored data, provider, prompt or
  configuration changes. Existing saved assessments and summary fallback are
  reused. Roll back only the frontend changes and rebuild. The user's startup
  script edits are untouched. No staging, commit, deployment or paid call occurred.
- **Risks:** normal full-suite collection needs the documented environment
  workaround on this machine. Existing design-detector warnings concern unchanged
  styles. No #30 runtime blocker remains.
- **Next exact action:** start #31 in a fresh `gpt-6.1-sol` Codex chat, read
  [Starred messages](specs/STARRED_MESSAGES.md) and the handoff, then write one failing
  authenticated reader HTTP test for explicit desired star state. HTTP and browser
  seams are already approved; no repeat confirmation is needed. Keep one writer.

### Starred messages and Summary specs published (2026-11-22)

The user approved both specs and the public test interfaces. Published
[Summary #30](https://github.com/CloudKai/NUS-Codesign-Chatbot/issues/30) and
[bookmarks #31](https://github.com/CloudKai/NUS-Codesign-Chatbot/issues/31) carry
ready-for-agent. Bookmarks depends on Summary. Local specifications are
[Summary](specs/STAGE_REVIEW_SUMMARY.md) and [bookmarks](specs/STARRED_MESSAGES.md).

Approved seams are the authenticated reader HTTP API for persistence, ownership
and edits, plus the rendered React workspace for starring, jumping and Summary.
Implement in vertical TDD cycles with deterministic mock providers and disposable
data. Summary runs first in a fresh ticket context. Its implementation session
must finish validation and a written handoff before starting bookmarks in another
fresh context. The user's repeated approval authorizes these sequential sessions.

Publication and label readback succeeded. Documentation diff checks passed.
Implementation and runtime validation remain pending. No schema or persisted data
changed during specification. The local startup-script modification belongs to
the user. No staging, commits or deployment are authorized.

Next exact action is to implement #30 from its local spec, starting with a failing
browser test of Summary's ordered project summary, per-stage feedback and Facione
sections. After validated completion, record evidence here and start #31 in a fresh
session using its local spec and the HTTP/browser seams already approved.

### Readiness audit and hardening (branch `improvement/combined-testing1`, five features)

Mock and offline only. No AWS, Bedrock or AgentCore call ran, and no script ran
against an account. Full mock suite: 3155 tests, no failure, no skip
(`.venv/bin/python -m pytest -q`, output in the session artifacts). Per-feature
evidence is in the entries below and in the commit messages.

| Feature | Result |
| --- | --- |
| Student journey over the reader routes | `tests/http/test_student_journey_readiness.py`; whitespace-only messages now 422 before any turn is saved; Home start mode, Discard for rejected questions |
| Browser flows at 1440 px and 390 px | Parent-run scripts: `crypto.randomUUID` fallback on plain HTTP (`frontend/src/requestKey.ts`), chips hidden during the milestone banner, 44 px touch targets on phones |
| Security | See the security entry below: download-only uploads, cross-origin write refusal, forged section tags, Windows path separators, unsafe Markdown links |
| Answer accuracy | See the answer accuracy entry below: shared-banner pages kept; recall floors locked |
| AWS | [Architecture proposal](deploy/AWS_ARCHITECTURE_PROPOSAL.md), `infra/aws/` templates, `scripts/aws/deploy_stack.sh` (dry run by default), `tests/test_infra_templates.py` (9 tests) |

- **No migration.** No schema, data or `.env.example` change. Rollback is a revert of the commits.
- **Open decisions for the user** (not changed because they alter what students see
  or what the prompts say): the hard-coded older-adult example lists in
  `backend/learning/journey.py` `personalized_stage_questions` (the app names groups and
  stakeholders the student should find); OCR for image-only slides (86 of 535 pages
  have no text); follow-up query rewriting; the gate wrong-skip rate (76/154);
  silently dropped raw HTML in coach Markdown; the process-local limiter and ledger.
- **Risks.** The templates are unvalidated by `cfn-lint` and untested in an account.
  The cost and speed figures are estimates. The CloudFront asset behavior and the
  deployment bundle and secret are manual steps. Latency percentiles are not
  alarmed (needs an app change).
- **Next exact action.** Review the proposal, then run
  `sh scripts/aws/deploy_stack.sh --app-params <file> --edge-params <file>` with
  `--validate-remote` in a sandbox account; apply only after the account id is confirmed.

### Security readiness pass (branch `improvement/combined-testing1`)

Mock tests only; no AWS, Bedrock or AgentCore call ran. Fixes and the tests that
lock them are in `tests/http/test_security_readiness.py`,
`tests/domain/test_student_chunk_security.py` and
`tests/domain/test_security_invariants.py`. Boundary changes are described in
[Security boundaries](SECURITY_BOUNDARIES.md).

| Finding | Fix |
| --- | --- |
| Owner-scoped source content route rendered uploaded HTML, XML and script inline | Only PDF, images and `text/plain` stay inline; the rest download as `nosniff` attachments |
| Owner-scoped write routes accepted a foreign `Origin` or cross-site fetch metadata | Middleware returns 403; Streamlit's server-side client is unaffected |
| Untrusted text could forge the composer's section delimiters | Composer tag names are rewritten inside untrusted bodies |
| Attachment filenames and the language setting reached the trusted runtime rules as free text | Filenames become one inert token; language is limited to the four supported values |
| Backslash paths kept their separators in upload names | `_safe_name` splits on both separators |

- **Left as is.** The AgentCore runtime phase dispatch (`fast_chat`, and
  `review` with `review_mode=incremental` for the stage checkpoint, are both
  sent in production), the process-local limiters, the first-hop
  `X-Forwarded-For` login key (safe behind Caddy) and the missing production
  requirement for `GENERATION_ADMISSION_POLICY`.
- **Rollback.** No schema or data change. Revert the commits for the five
  rows above independently.

### Answer accuracy over the real lecture PDFs (branch `improvement/combined-testing1`)

Mock and offline only. Material recall@4 is 91/94 and page recall@4 is 79/94 over
the 10 real PDFs, locked by `tests/domain/test_real_lecture_retrieval.py`.
Knowledge Base adapter mapping and citation tests use fake hits keyed by the real
object keys. One bug fixed: duplicate suppression compared only the first 400
characters, so a page that opens with the same banner as an earlier page (Reading
2 page 4) was dropped from the result and its citation lost. Not changed (needs a
decision): OCR for image-only slides (Week 1 has 27 of 32 pages without text),
follow-up query building, gate wrong-skip (76/154) and slide chunking. Details
are in [Retrieval evaluation](RETRIEVAL_EVAL.md).

### Head-to-head routing comparison: Laya vs KB-score routing (built, not run; branch `improvement/backend`)

No production routing change and no setting default changed (all stay off). Nothing
under `backend/`, `agentcore_runtime/` or `frontend/` changed. **No live command ran:**
no Knowledge Base call, no AWS call, no Laya weights. Mock tests only. Details, exact
commands, IAM and cost: [Head-to-head routing comparison](RETRIEVAL_EVAL.md#head-to-head-routing-comparison-built-not-run).

| Step | What changed | Commits |
|---|---|---|
| Pre-registration | `.agents/tasks/headtohead-prereg/plan.md`: sha256 split, how T is chosen, metrics M1 to M6, pass rule, written before any per-half figure. Never edited; dated amendments only | `8c51cdd` |
| `--live-kb-gate` | One `Retrieve` per gate message in `evaluate_retrieval.py`, cap 295, stops on the first auth error, ids and scores only | `6459ba8` |
| `compare_routing_arms` | New command and `scripts/evals/lib/` modules; `evaluate_combined_gate.py` re-exports the moved helpers, output unchanged | `f377a1c` |
| Laya all-rows host run | `benchmark_course_intent.py` host-note flags and per-row output | `1f6acb6` |
| `--extra-messages` | Optional human-labelled rows, reported apart from the 295; `synthetic: true` required unless `--allow-non-synthetic` | `a1bd91e` |
| Docs | Commands, IAM, cost, pre-registration, privacy | this commit |

- **Validation evidence.** Mock tests only: the four new test files (live gate, compare,
  host note, extra messages) plus the unchanged existing tests, and
  `tests/scripts/test_eval_command_boundaries.py`, which picks up
  `compare_routing_arms.py` and every new `lib` module through its directory globs and
  passes unedited (41 tests). `ruff check` and `compileall` pass. Counts per commit are in
  the commit messages. The full mock suite ran in the report commit `8736bf9`: 3041 passed,
  2 failed (the baseline's two `frontend/dist` failures, `assert 404 == 200` on `GET /`),
  1 skipped, against 2905 passed, 2 failed, 1 skipped at `e9bebcb`.
- **Compatibility and rollback.** `evaluate_retrieval.py` and `compare_routing_arms.py`
  only gain flags, and the existing flags, help text, JSON schemas and exit codes are
  unchanged. **One existing command changes behaviour:** `benchmark_course_intent.py
  --checkpoint` now exits 2 unless `--host-instance-type`, `--host-vcpu`, `--host-ram-gb`
  and `--host-arch` are given (placeholders such as `<TYPE>` and non-positive numbers are
  also refused). Every earlier real-model invocation needs those four flags; `--stub-ms`
  runs are unaffected. The three `--checkpoint` examples in `RETRIEVAL_EVAL.md` carry them.
  The output also gains `host_note` and `rows`. Revert the commits above to remove the
  work; no data or migration is involved.
- **Unresolved.** No arm can be declared the winner until two files exist: the live
  KB-score file (`--live-kb-gate --max-live-calls 295`, up to about $0.30 at the assumed
  $1 per 1,000 calls) and the all-rows Laya file on a named host. Host type, vCPU, RAM and
  arch are still `<TYPE>`, `<N>`, `<GB>`, `<arm64|x86_64>`. The AWS price per Retrieve
  call is the user's assumption and is unconfirmed. IAM `bedrock:Retrieve` on
  `arn:aws:bedrock:<region>:<account-id>:knowledge-base/<KB-ID>` is checked against the AWS
  Service Authorization Reference, not tested on an account.
- **Next exact action.** The report `.agents/tasks/headtohead-2026-11-20.md` is written
  (`8736bf9`) and the work is stopped for review. After approval, the operator runs the
  three commands in the RETRIEVAL_EVAL section (live gate, Laya all-rows host run,
  `compare_routing_arms`) and the comparison is re-reported. `compare_routing_arms` refuses
  a KB-score file whose recorded `kb_settings` differ from the plan (12 candidates, 4
  results, filter mode `required`).

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
