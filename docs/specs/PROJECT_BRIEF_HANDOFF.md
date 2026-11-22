# Whole-chat project brief and clean Summary handoff (2026-11-22)

## Behavior

Summary now leads with **Your project so far**, replacing both recent prompts and
the separate coach recap. Five concise passages describe Who and why, Problem,
Current idea, What matters, and Still to explore. Missing facts remain **Not yet
established**; a failed/unavailable generation says **Not summarised yet**, which
does not imply that the student's project has been assessed as missing facts.
Tentative ideas stay tentative. A new brief is immediately included in Download.

The lecture materials define the brief's structure, not an extra lecture-links
section or invented project content. Sources checked: Week 2 PDF p66–67/p86
(JTBD and needs); Week 4 p20/p30–37 (persona, goals/values/features); Week 7 p56
(selection criteria); Week 8 p39–40 (problem, solution, assumptions/prototype plan);
Week 9 p31–34 (testing/feedback). See [course content](../../frontend/COURSE_CONTENT.md).

The requested Impeccable refinement keeps the established app identity and uses
progressive disclosure: one primary project brief; one flat Stage feedback
accordion; then the existing strongest/grow/Practice skill summary. Stage rows
start collapsed and show exact saved Going well / To work on counts or an
unreviewed caption. Their two groups remain independently collapsible. Six
individual skill scores and tips are under All six skill scores. No saved
feedback, score, practice action or stage is removed. The brief title has zero
extra top margin and 14px top padding; accent labels and fine separators provide
hierarchy without nested cards, decorative icons or a second progress display.

## Whole-chat and evidence guarantees

`ProjectBriefService` receives the entire active visible transcript from the
owner-scoped repository, independent of the browser's 20-message page. It uses
the configured review-capable model through a narrow port, without running stage
progression or persisting a new transcript turn. The five typed provider points
contain short text/null and up to three exact student quotations. Every populated
point must have quotations found in actual student messages; unsupported quotes
and malformed output fail closed. Instructions exclude coach suggestions unless
adopted, filler, unfinished scaffolds and unrelated questions; they preserve
later corrections, missing facts and uncertainty. This evidence check establishes
source presence, not semantic entailment. Live summarisation quality has not been
evaluated by scripted tests and is not claimed to be hallucination-proof.

A hash of every active message's identity/role/content/order binds the cache to the
whole chat. New turns and revisions invalidate it. A concurrent change discards the
result rather than displaying a stale brief. The adapters' full-history budgets
fail instead of falling back to a recent window; imported messages above 12,000
characters are refused, and the direct prompt has a 200,000-character bound.
No course retrieval call is needed to fill missing fields.

The existing settings-text merge and DSQL OCC wrapper persist only the new
`project_brief_v1` cache/failed-attempt receipt. No schema migration. A per-owner
service lock coalesces local duplicate requests, and shared rate/admission/usage
accounting applies as operation `project_brief`. Multi-worker exactly-once paid
generation and crash-proof provider-call deduplication are not claimed.

GET project reads cached state only. React requests a missing brief when the
student presses **Summarise chat**. Unchanged chats reuse saved output. The
button has a hover and keyboard tooltip. Provider failures require an
explicit strict-boolean retry, including after remount/restart. Owner verification
and the chat version fence late browser results. No brief enters browser storage.
The previous Review open/tab restoration and private-content clearing remain.

**Mock-mode limit:** the user's local app is configured for deterministic mock
replies. It honestly reports that a whole-chat summary is unavailable in this
preview, instead of making up a project brief. Populated browser examples use a
scripted external model fixture on disposable data. Real summaries require a
configured language model. AgentCore additionally needs the matching updated
Review runtime schema; an old runtime omitting the field fails safely. No paid
model call or runtime deployment was performed.

## Files changed in this phase

- `backend/coaching/project_brief.py`: focused service, repository/model ports,
  whole-chat cache, evidence checks and explicit retry policy.
- `backend/domain.py`: brief point/result types and optional assessment field.
- `backend/coaching/execution.py`: owner-scoped service composition.
- `backend/http/notebook_reader.py`: cached projection and strict brief POST.
- `backend/persistence/store/contracts.py`: additive settings-key allowlist.
- `backend/prompts/project_brief.py`, `composer.py`: full-history brief instructions
  and bounded direct-provider prompt, separate from normal chat prompt windows.
- `backend/agentcore_provider.py`, `agentcore_runtime/models.py`,
  `agentcore_runtime/prompts/review_deep.md`: optional structured brief transport.
- `backend/usage.py`: shared generation operation accounting.
- `Caddyfile`, `Caddyfile.local`: allow brief POST; also expose the already implemented
  #31 bookmark GET/star POST, which were missing from the proxy allowlists.
- React `ProjectBrief.tsx`, `ThinkingPath.tsx`, `Conversation.tsx`, `api.ts`,
  `projectExport.ts`, `styles.css`: brief, hierarchy, safe state and export.
- `tests/http/test_project_brief.py`: five authenticated/model-boundary cases.
- `tests/test_architecture_contracts.py`: explicit route inventory.
- Browser brief fixture/regressions, Summary hierarchy/design QA and adapted
  existing Summary/Review tests under `tests/browser/`.
- React README/design/course mapping, architecture, testing, docs index,
  implementation status and handoffs.

All earlier #30/#31 changes and the user's startup-script edits are preserved.
No Streamlit source changes, staging, commits or deployment.

## Validation and evidence

Public authenticated HTTP and rendered-browser seams remain the approved seams.
Red/green cycles covered missing brief endpoint; direct-provider recent-window
truncation; AgentCore dropping the new structured field; the replacement UI;
failed-summary replay; immediate download content; consolidated stage feedback;
and on-demand detailed skill scores. Scripted model/SDK boundaries made no paid
calls. The full-history budget refusal was already enforced by the adapter and
passed as a compatibility verification.

- **160 focused Python tests passed**, including all five new HTTP cases,
  existing notebook reader, bookmarks, student journey, architecture, AgentCore,
  prompt-baseline and cost accounting checks.
- **All 3,168 mock Python tests passed**, no failures/skips, using the documented
  process-local local-tests namespace binding. Full suite was repeated after the
  failed-attempt policy change; later changes were frontend/browser/docs only.
- TypeScript/Vite build, Python compileall, both Caddy configuration validations,
  whitespace and affected local documentation links passed.
- New brief, hierarchy and design checks passed with a substantive summary,
  tentative idea, unknown requirements, empty chat, failure and explicit retry.
  Rendered QA covered 1440/900/390 in Light/Dark, keyboard/focus, touch targets,
  overflow and no unexpected console errors. Download immediately includes the brief.
- Both existing Summary regressions, independent feedback disclosures, visibility/
  navigation/reload restoration, explicit close, mobile Practice, owner/chat
  isolation and the main star/unstar/old-page-jump browser regression passed.
- Disposable API restart preserved identical public project/transcript/bookmarks
  and restored open Summary. Existing focused/full journey coverage verifies
  streaming, source/citations, graph resumption and confirmed progression.
- Populated desktop/phone Light/Dark screenshots were visually inspected. Mechanical
  design warnings concern preserved font/gradient/border conventions and advisory
  token values. No new decorative system was introduced.
- Browser fixtures use uniquely named API-created chats to avoid a creation race
  when an old and new empty chat share the same visible title. Native tab hiding
  remains suppressed by the CLI: visibility events are supplied explicitly, while
  real navigation away/back/reload are tested separately.

Evidence: `/private/tmp/codesign-project-brief/`; ignored screenshots and export:
`output/playwright/project-brief/`. Repeat setup is in
[Testing](../TESTING.md#whole-chat-project-brief-and-clean-summary).

## Compatibility, rollback and next action

No schema migration, personal-data edit, model-provider switch, paid call,
commit or deployment. Normal application-generated caches are optional trusted
metadata; older apps ignore them. Roll back this phase's application/frontend and
proxy changes and rebuild. No DB restore or destructive metadata cleanup is needed.
The user's local mock stack is restarted with the current source/build; its API
and Streamlit health are checked afterward. Disposable services/browsers are stopped.

Remaining limits are the explicit mock-mode/old-runtime condition, context bounds,
model semantic quality not live-tested, existing dependency warnings and the local
single-worker cache lock. Next exact action: refresh the local app on port 8081
and inspect Summary. Live provider tests require separate approval with a request/
token or cost cap under the repository policy; staging/commit/deployment remain
separate authorized actions.
