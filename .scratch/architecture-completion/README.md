# Architecture completion: local execution pack

The user approved this 53-ticket breakdown and its testing seams on 24 November
2026 SGT, requested local publication and TDD implementation, and requested fresh
context for each ticket. No GitHub issue was created or changed.

Read the [approved specification](SPEC.md), the repository's [contribution
workflow](../../docs/CONTRIBUTING.md#ticket-execution), [glossary](../../GLOSSARY.md),
[architecture](../../docs/LOCAL_DEMO_IMPLEMENTATION.md) and current
[implementation status](../../docs/IMPLEMENTATION_STATUS.md) before a ticket.
Implementation status remains the authoritative evidence ledger. This index is
scope/dependency navigation, not a second implementation-status report.

## Execution contract

- Work one writer/ticket at a time in a fresh client-selected gpt-6.1-sol
  session. All ready-for-agent statuses describe triage readiness; a ticket can
  start only after every listed blocker has acceptance evidence. Follow the
  frontier, not just the next number. Ticket 01 is the initial frontier.
- Use the invoked TDD skill: write one failing public-behavior test, observe
  red for the intended reason, implement only enough for green, repeat. Do
  not bulk-write imagined tests, mock internals or make tests tautological.
  Baseline/audit/documentation work uses existing checks and inspection;
  do not manufacture a failing test for unchanged behavior. Prefactoring
  preserves public behavior through characterization coverage before edits.
- Approved primary seam: student-visible browser → production-built React →
  real same-origin FastAPI → disposable persistent SQLite, with deterministic
  external model/retrieval/auth adapters. It catches integrated navigation,
  saving and identity errors but cannot prove AWS or live-model behavior.
- Approved supporting seams: public FastAPI contracts for invalid input and
  ownership; storage/worker contracts for SQLite/DSQL OCC, migration, leases
  and crashes; runtime/provider contracts for guardrails/structured output.
  Fakes establish contracts, not live service capacity or semantic quality.
  Focused Vitest/component checks exercise public user/caller interfaces,
  rather than internals. If a genuinely new seam is necessary, confirm it
  before writing tests there; do not repeatedly ask about these approved seams.
- Each feature is a working vertical slice: actual persistence where needed,
  typed validated API/generated REST, confirmed Query state, usable UI, exact
  edge permissions when routes change, public regression evidence and docs.
  Keep NDJSON, existing stage authority, optional canvas usage, sources and
  lecturer compatibility intact. Do not stage, commit, deploy or modify live
  infrastructure. All default validation is deterministic and non-billable.
- Measure before adopting pooling/concurrency/model/prompt/cache/retrieval/
  virtualisation/region/infrastructure changes. Complete local infrastructure
  and record approval-dependent live evidence separately. Do not silently
  turn a mandatory canvas/editor/recovery feature into optional backlog.
- Run focused checks each cycle and applicable full checks at ticket/phase
  handoff. Report actual evidence only. Preserve all unrelated work/data.
  After two evidence-based failures, record the concrete blocker and route
  it as the repository requires; do not retry indefinitely.
- Before ending a ticket, update the existing implementation ledger, link
  evidence, check affected documentation/links, record compatibility and
  rollback, and identify the next eligible ticket. Start that ticket with a
  fresh context containing its ticket, spec, relevant guides and evidence;
  do not carry the whole preceding chat as its implementation prompt.

## Approved ticket graph

1. [Reproduce the baseline and establish coverage](issues/01-reproduce-the-baseline-and-establish-coverage.md) — blocked by: None.
2. [Clear lint and collection blockers](issues/02-clear-lint-and-collection-blockers.md) — blocked by: 1.
3. [Audit repository privacy](issues/03-audit-repository-privacy.md) — blocked by: 1.
4. [Reconcile deployment and safety records](issues/04-reconcile-deployment-and-safety-records.md) — blocked by: 1.
5. [Run an existing student journey in browser CI](issues/05-run-an-existing-student-journey-in-browser-ci.md) — blocked by: 1.
6. [Extract the chat lifecycle without changing behavior](issues/06-extract-the-chat-lifecycle-without-changing-behavior.md) — blocked by: 5.
7. [Save preferences through generated REST and Query](issues/07-save-preferences-through-generated-rest-and-query.md) — blocked by: 1.
8. [Manage notebooks through generated REST and Query](issues/08-manage-notebooks-through-generated-rest-and-query.md) — blocked by: 1.
9. [Open an aggregated, verified workspace](issues/09-open-an-aggregated-verified-workspace.md) — blocked by: 7, 8.
10. [Manage sources through typed confirmed resources](issues/10-manage-sources-through-typed-confirmed-resources.md) — blocked by: 1.
11. [Keep My Work synchronized with message bookmarks](issues/11-keep-my-work-synchronized-with-message-bookmarks.md) — blocked by: 1.
12. [Read and confirm Thinking Path progress through typed resources](issues/12-read-and-confirm-thinking-path-progress-through-typed-resources.md) — blocked by: 1.
13. [Read reviews, briefs and existing exports through typed resources](issues/13-read-reviews-briefs-and-existing-exports-through-typed-resources.md) — blocked by: 1.
14. [Navigate existing workspaces through URLs](issues/14-navigate-existing-workspaces-through-urls.md) — blocked by: 6, 9.
15. [Create and reopen a persistent student artifact](issues/15-create-and-reopen-a-persistent-student-artifact.md) — blocked by: 14.
16. [Manage course-aligned artifact types](issues/16-manage-course-aligned-artifact-types.md) — blocked by: 15.
17. [Autosave artifacts without losing conflicting drafts](issues/17-autosave-artifacts-without-losing-conflicting-drafts.md) — blocked by: 15.
18. [Preview and restore artifact versions](issues/18-preview-and-restore-artifact-versions.md) — blocked by: 17.
19. [Export student artifacts safely](issues/19-export-student-artifacts-safely.md) — blocked by: 16, 18.
20. [Create and reopen a persistent Design Canvas](issues/20-create-and-reopen-a-persistent-design-canvas.md) — blocked by: 14.
21. [Explore and edit a complete visual reasoning map](issues/21-explore-and-edit-a-complete-visual-reasoning-map.md) — blocked by: 20.
22. [Autosave canvases without overwriting another tab](issues/22-autosave-canvases-without-overwriting-another-tab.md) — blocked by: 20.
23. [Preview and restore canvas versions](issues/23-preview-and-restore-canvas-versions.md) — blocked by: 22.
24. [Export complete canvases](issues/24-export-complete-canvases.md) — blocked by: 21, 23.
25. [Link artifacts and canvas reasoning to evidence](issues/25-link-artifacts-and-canvas-reasoning-to-evidence.md) — blocked by: 15, 20.
26. [Turn selected chat content into canvas nodes](issues/26-turn-selected-chat-content-into-canvas-nodes.md) — blocked by: 21, 25.
27. [Coach selected canvas reasoning](issues/27-coach-selected-canvas-reasoning.md) — blocked by: 6, 21, 25.
28. [Review and accept structured canvas suggestions](issues/28-review-and-accept-structured-canvas-suggestions.md) — blocked by: 27, 22.
29. [Review and accept artifact feedback](issues/29-review-and-accept-artifact-feedback.md) — blocked by: 6, 16, 17, 25.
30. [Develop artifacts from selected canvas nodes](issues/30-develop-artifacts-from-selected-canvas-nodes.md) — blocked by: 27, 16, 17.
31. [Return artifact reasoning to the canvas](issues/31-return-artifact-reasoning-to-the-canvas.md) — blocked by: 21, 25, 17.
32. [Resume a project from persisted work](issues/32-resume-a-project-from-persisted-work.md) — blocked by: 9, 15, 20.
33. [Show deduplicated confirmed milestone recaps](issues/33-show-deduplicated-confirmed-milestone-recaps.md) — blocked by: 12.
34. [Make stage requirements actionable](issues/34-make-stage-requirements-actionable.md) — blocked by: 12, 16, 21.
35. [Resume queued Deep Review safely after restart](issues/35-resume-queued-deep-review-safely-after-restart.md) — blocked by: 1.
36. [Handle cancelled and ambiguous Deep Review execution](issues/36-handle-cancelled-and-ambiguous-deep-review-execution.md) — blocked by: 35.
37. [Trace a coaching request without recording private content](issues/37-trace-a-coaching-request-without-recording-private-content.md) — blocked by: 1.
38. [Measure DSQL connection overhead and pooling compatibility](issues/38-measure-dsql-connection-overhead-and-pooling-compatibility.md) — blocked by: 1.
39. [Measure and bound backend concurrency](issues/39-measure-and-bound-backend-concurrency.md) — blocked by: 37.
40. [Evaluate compact prompts and supported prompt caching](issues/40-evaluate-compact-prompts-and-supported-prompt-caching.md) — blocked by: 37.
41. [Compare model and runtime paths fairly](issues/41-compare-model-and-runtime-paths-fairly.md) — blocked by: 37.
42. [Evaluate retrieval for workspace evidence](issues/42-evaluate-retrieval-for-workspace-evidence.md) — blocked by: 27, 29.
43. [Keep chat fast when editors are added](issues/43-keep-chat-fast-when-editors-are-added.md) — blocked by: 16, 21, 14.
44. [Complete accessible desktop and mobile authoring](issues/44-complete-accessible-desktop-and-mobile-authoring.md) — blocked by: 16, 17, 18, 21, 22, 23, 28, 29.
45. [Verify workspace ownership and hostile-content defenses](issues/45-verify-workspace-ownership-and-hostile-content-defenses.md) — blocked by: 25, 28, 29, 36.
46. [Complete deterministic frontend and browser CI](issues/46-complete-deterministic-frontend-and-browser-ci.md) — blocked by: 2, 5, 26, 28, 29, 30, 31, 32, 33, 36.
47. [Rehearse recovery of the complete saved workspace](issues/47-rehearse-recovery-of-the-complete-saved-workspace.md) — blocked by: 18, 23, 33, 36.
48. [Measure mixed classroom workloads locally](issues/48-measure-mixed-classroom-workloads-locally.md) — blocked by: 9, 17, 22, 36, 39.
49. [Model operating costs and regional trade-offs](issues/49-model-operating-costs-and-regional-trade-offs.md) — blocked by: 4, 37, 48.
50. [Extend authorised aggregate engagement signals](issues/50-extend-authorised-aggregate-engagement-signals.md) — blocked by: 32, 33, 36.
51. [Prepare a coordinated release and rollback rehearsal](issues/51-prepare-a-coordinated-release-and-rollback-rehearsal.md) — blocked by: 4, 10, 11, 12, 13, 19, 24, 45, 47.
52. [Export selected project coursework](issues/52-export-selected-project-coursework.md) — blocked by: 19, 24, 25, 32.
53. [Verify and report the complete programme](issues/53-verify-and-report-the-complete-programme.md) — blocked by: 3, 6, 34, 38, 40, 41, 42, 43, 44, 46, 49, 50, 51, 52.


## Source coverage ownership

Ranges refer to the supplied 101-section brief, retained in the approved spec's
coverage table. Cross-cutting controls apply to every feature ticket, not just
the final audit. The baseline ticket expands this into the existing ledger.

| Source sections | Primary tickets |
| --- | --- |
| 1–5 | 01, 04, 53 and execution contract |
| 6–8 | 07–13; new resource contracts also in 15–36, 50, 52 |
| 9–11 | 06, 14, 43 |
| 12–22 | 20–24, 44 |
| 23–29 | 25–28, 34, 42 |
| 30–38 | 15–19, 29, 44 |
| 39–43 | 25–31, 52, 53 |
| 44–49 | 12, 32–34 |
| 50–52 | 19, 24, 52 |
| 53–55 | 15, 17–18, 20, 22–23, 33, 35–36, 38 |
| 56 | 39 |
| 57–64 | 06, 37, 40–41 |
| 65–66 | 42 |
| 67 | 35–36 |
| 68–72 | 14, 16, 21, 43–44 |
| 73–78 | 03, 25, 37, 45 and per-feature validation |
| 79–84 | 02, 05, 46 and per-feature TDD |
| 85–89 | 04, 47, 51 |
| 90–92 | 48–49 |
| 93–94 | 50 and retained lecturer checks |
| 95–97 | 01, 53 and execution contract |
| 98–101 | 45–53 and per-ticket acceptance |

Existing GitHub classroom/release gates #28–29 and locally implemented
Summary/bookmark work #30–31 remain unchanged. Their status is not inferred
from this pack. No automatic live safety, capacity or S$30 cost claim is made.
