# Review refinements handoff (2026-11-22)

The later [whole-chat project brief and clean Summary handoff](PROJECT_BRIEF_HANDOFF.md)
supersedes this phase's recent-prompts overview and expanded-by-default feedback.
The restoration/privacy behavior below remains in force.

## Behavior

Summary's five Thinking Path stages now each have a disclosure button. Going well
and To work on collapse independently within each stage. They start expanded,
preserving existing feedback visibility, exact saved wording, missing-feedback
messages, canonical order and Facione controls. Buttons expose expanded state and
controlled regions, work with Enter/Space and have 44px targets. Switching Review
views retains disclosure choices; a complete Review remount restores expanded
feedback rather than storing assessment content in the browser.

The leading card is now **Chat overview**, without Stage X of 5, a stage title or
progress segments. It quotes up to three latest saved student prompts, bounded
to 240 characters each and followed by an ellipsis when truncated, including
Lecture help as well as project contributions. The card retains the existing
saved coach text under **Saved coach recap**, with an explicit partial-chat scope
note. Long recaps retain Read more. Missing recaps retain the honest empty state.

The contract inspection matters: `learning_review` derives `saved_summary` from
an assessment or Deep Review synthesis. The reader falls back to thread
`learning_summary`; the frontend already falls back to the current stage's
`coach_summary`. None promises a complete overview of every student prompt.
Reframing that text alone would overstate its scope. Recent saved prompts provide
an extractive overview while the original recap stays intact and accurately
labeled. No new provider call, summary generation, API field or saved-data change.

## Review restoration diagnosis and interaction choices

`useReader` deliberately clears private in-memory state on `visibilitychange`
when hidden and on `pagehide`. Returning reloads and verifies identity, remounting
`ReaderWorkspace` and `Conversation`. The previous `pathOpen=false` initializer
therefore lost Review on every such remount. Internal Review tabs and responsive
dialog placement were not the underlying cause.

Keep that privacy lifecycle unchanged. Store only `{open, tab}` in tab-scoped
session storage under the verified owner/chat identity. The owner-fenced reader
must load the authorized chat/project before Conversation can restore Review.
No transcript, feedback, prompt excerpt or assessment is saved by this feature.
Sign-out/access refusal clears the preference. Storage refusal falls back to
in-memory behavior; reopening after a remount then cannot be guaranteed.

- Close Review, the chat-header toggle, Escape and the drawer backdrop remain
  intentional close actions. Their closed choice survives reload.
- Each chat has its own preference. A new chat starts closed. Another owner never
  inherits a previous owner's view or private content.
- The last selected Review tab returns after visibility reset, navigation and
  reload. A pending decision can still explicitly open Progression from the header.
- Responsive docked/drawer/fullscreen transitions preserve Review and its view.
- Mobile Practice/scaffold insertion used to close Review automatically. It now
  keeps Review open, retains focus in the modal and announces that the editable
  draft is ready: close Review to edit. No message is sent.
- **Jump to message** remains an explicit navigation back to the original chat
  message, closing Review and focusing/highlighting that exact original as #31
  requires. It is distinct from passive tab/visibility changes.

## Files changed in this phase

- `frontend/src/ThinkingPath.tsx`: disclosures, extractive overview, selected-tab callback.
- `frontend/src/Conversation.tsx`: owner/chat display preference restoration,
  recent saved prompts, mobile scaffold status and focus behavior.
- `frontend/src/App.tsx`: preference cleanup on sign-out/access refusal.
- `frontend/src/styles.css`: disclosure sizing/spacing and prompt wrapping.
- `tests/browser/review_refinements.js`, `review_overview.js`,
  `review_persistence.js`, `review_boundaries.js`, `review_restart.js`: public
  rendered regressions with disposable mock data.
- Existing `stage_review_summary.js`: hero's new accessible name;
  `stage_review_summary_empty.js`: disambiguate New Chat from saved unnamed chats.
- React README/design, testing guide, docs index, implementation status and this handoff.

Earlier uncommitted #30/#31 implementation and the user's startup script remain
preserved. This phase makes no backend or Streamlit source changes.

## Validation evidence

Four vertical red/green slices ran through the approved rendered-browser seam:
missing stage/group disclosures; missing Chat overview with saved mixed-mode
prompts; Review absent after the visibility lifecycle; mobile Practice unexpectedly
closing Review. Each failed before its minimal implementation. Fixture corrections
included server-owned intent routes and the established five-stage mock journey
needed to expose assessed Facione Practice controls.

- All **32 focused Python tests passed**: student journey readiness, notebook
  reader, starred messages, reader workspace and architecture contracts.
- All **3,163 mock Python tests passed**, with no failures/skips. Used the existing
  process-local local-tests namespace binding documented in the
  [Summary handoff](STAGE_REVIEW_SUMMARY_HANDOFF.md#validation-evidence). No exclusion
  or dependency modification. Deprecation warnings remain.
- All five new browser scripts passed, including two runs of the restart script
  around an actual disposable API restart. Public project, full transcript and
  bookmarks were identical; reloaded Review restored Summary.
- Both existing Summary regressions and the existing main starred-message
  regression passed, preserving exact saved feedback/scores, empty states,
  editable Practice drafts, star/unstar/failure behavior and old-page message jumps.
- Real rendered Light/Dark checks passed at **1440, 900 and 390 px**: selected tabs,
  independent disclosure, keyboard/focus, 44px controls, wrapping/overflow,
  intentional Escape/backdrop closes, no Review POSTs and no unexpected console
  errors. Desktop/phone screenshots in both themes were visually inspected.
- Native tab visibility is suppressed by this CLI even after disabling Chromium
  focus emulation. After two attempts, no further native retries were made; a
  model switch is client-controlled and no delegation was authorized. The test
  delivers `document.hidden`/`visibilitychange` through the same rendered seam,
  verifies private-content clearing, then verifies owner-checked restoration.
  Actual navigation away/back and reload were also exercised. This is a browser
  automation limitation, not evidence of a native OS app-switch test.
- Final TypeScript/Vite build, Python compilation, diff whitespace and affected
  local doc links passed. Mechanical design findings concern the preserved
  existing palette/font/gradient/border conventions and advisory token values.
- User stack stayed available: API through 8081 and Streamlit health returned
  healthy; the restarted disposable API also returned healthy. Frontend rebuilt
  for the user's review at 8081. Only disposable services/browsers were stopped.

Evidence logs: `/private/tmp/codesign-review/`. Screenshots:
ignored `output/playwright/review/` (existing Summary/bookmark captures are also
refreshed). Repeatable setup and scripts are in
[Testing](../TESTING.md#review-refinements-and-restoration).

## Compatibility, rollback and next exact action

No migration, persisted feedback change, personal-data edit, provider/prompt
change, paid API call, staging, commit or deployment. Existing entrypoints and
user server remain. Roll back only this phase's frontend changes and rebuild;
old application versions ignore the optional session-storage display preference.
No database restore is needed. Discarding tab storage discards only this feature's
presentation preference, subject to the app's existing separate draft behavior.

No implementation blocker remains. Limits are the explicit recent-prompt excerpt
scope, tab-session lifetime/storage availability and the native-visibility test
limitation above. Next exact action: refresh `http://127.0.0.1:8081/`, open Review →
Summary and review the three changes. No further implementation phase is pending;
staging, commits or deployment require separate authorization.
