# Complete the CDE2300 architecture and unified student design workspace

## Problem Statement

CDE2300 students can already use Lecture help, Project coaching, the Thinking Path, Sources, My Work and Review, but useful reasoning remains concentrated in conversations. Students need connected tools to organise alternatives visually, author editable coursework, link evidence, retain revisions and resume meaningful work later. Their work must remain private, durable and under their control.

The current architecture has an improved verified startup flow, generated reader contracts, identity-scoped Query infrastructure, safe turn recovery and a source-level Mantle output-safety fix. Ordinary REST integration and Query coverage are incomplete, chat opening still has redundant reads, navigation is largely view-state driven, and Deep Review workers cannot resume after restart. Adding disconnected editors would compound these problems.

The programme must preserve existing data, student and lecturer functionality, educational requirements and security while completing a maintainable workspace. Approximately 80 simultaneous students and approximately S$30 monthly operating cost are evidence-dependent objectives. Local mock success does not establish live capacity, production safety or affordable operation.

## Solution

Extend the existing React and FastAPI application into a unified project workspace. Students can converse with the coach, organise reasoning in a React Flow Design Canvas, develop student-authored artifacts in Tiptap, connect these resources to authorised evidence, review and restore versions, explicitly accept AI suggestions, resume saved work and export useful coursework.

FastAPI remains authoritative for identity, ownership, retrieval, context, educational assessment, stage confirmation and persistence. Generated REST contracts, resource-specific Query management and TanStack Router make the workspace responsive and navigable while retaining the existing NDJSON lifecycle. Durable Deep Review, bounded resource usage, accessible interactions, deterministic CI and coordinated release procedures complete the reliability foundation.

Deliver the complete mandatory programme through milestones 0–10. Evaluate performance experiments separately and adopt them only with evidence. Prepare release and live verification procedures without deploying or running billable tests under this specification.

## User Stories

1. As a CDE2300 student, I want my existing notebooks, chats, sources and learning state preserved, so that upgrading does not erase my work.
2. As a student, I want to enter through my existing registered or Guest session, so that I can access my own workspace safely.
3. As a student, I want account changes and expired sessions to hide incompatible work immediately, so that another account cannot see my private content.
4. As a student, I want a fast initial workspace load, so that classroom time goes toward coursework.
5. As a student, I want opening and reopening chats to avoid redundant reads, so that navigation feels responsive.
6. As a student, I want stable links to my chats, artifacts and canvases, so that I can return directly to the right task.
7. As a student, I want browser back, forward and refresh to work, so that navigation is predictable.
8. As a student, I want clear loading, unavailable and access-denied states, so that I understand what happened without exposing private data.
9. As a student, I want Lecture help supported by available course evidence, so that I can understand course concepts without being forced through project stages.
10. As a student, I want Project coaching within the existing five-stage Thinking Path, so that guidance matches my course.
11. As a student, I want honest generation statuses, so that I know whether my request is queued, retrieving, generating, saving or recovering.
12. As a student, I want only safety-eligible model text displayed, so that responsiveness does not bypass output protection.
13. As a student, I want cancellation and interrupted-turn recovery, so that network problems do not create duplicate confirmed turns.
14. As a student, I want provisional text clearly separated from saved responses, so that I know which work is durable.
15. As a student, I want my reading position and composer draft preserved during compatible navigation, so that switching views does not interrupt my reasoning.
16. As a student, I want an empty or optional guided canvas, so that the design begins with my own thinking.
17. As a student, I want to create, rename, reopen, duplicate where supported and delete canvases with clear confirmation, so that I can manage visual project work.
18. As a student, I want meaningful node categories for problems, stakeholders, needs, evidence, assumptions, constraints, concepts, specifications, ethics, evaluation, reflection and notes, so that I can organise course-relevant reasoning.
19. As a student, I want to edit, duplicate, position and remove nodes, so that my map can evolve with my understanding.
20. As a student, I want labelled relationships and explanations between nodes, so that connections communicate reasoning.
21. As a student, I want branching and alternative concepts, so that the canvas supports comparison beyond a rigid tree.
22. As a student, I want single and multiple selection, pan, zoom and fit-to-view, so that I can work with a growing canvas.
23. As a student, I want search and useful category or stage filters, so that I can find relevant ideas.
24. As a student, I want local undo and redo, so that I can recover from editing mistakes quickly.
25. As a student, I want debounced canvas autosave and explicit save feedback, so that I can work confidently without saving every pointer movement.
26. As a student, I want timestamped canvas versions and restoration, so that earlier reasoning remains recoverable.
27. As a student, I want conflicts detected without discarding my edits, so that another tab cannot silently overwrite my work.
28. As a student using a keyboard or assistive technology, I want an editable outline alternative to the visual canvas, so that essential reasoning tasks do not require dragging.
29. As a student, I want to turn selected chat content into an editable node proposal, so that useful conversation ideas become part of my map.
30. As a student, I want to choose the destination, type, title, content and references before creating a node, so that conversion remains deliberate.
31. As a student, I want to discuss selected nodes with the existing coach, so that feedback addresses my current reasoning.
32. As a student, I want contextual critique, comparison, assumption checks, ethical questions and relationship suggestions, so that the canvas supports critical thinking.
33. As a student, I want to accept, edit, reject or ignore structured AI suggestions, so that AI cannot change saved work independently.
34. As a student, I want stale suggestions revalidated, so that accepting feedback cannot overwrite newer work.
35. As a student, I want evidence links to authorised course excerpts, uploads, research notes and conversation citations, so that claims have traceable support.
36. As a student, I want unavailable or outdated references identified clearly, so that I do not mistake stale links for current evidence.
37. As a student, I want student content, AI contributions, evidence and assumptions distinguished, so that provenance is understandable.
38. As a student, I want to create and organise project artifacts aligned with the course, so that I can develop actual coursework.
39. As a student, I want paragraphs, headings, emphasis, lists and safe links with useful checklists or tables, so that documents are readable without an excessive toolbar.
40. As a student, I want artifact rename, duplication, deletion confirmation, undo and redo, so that I can manage drafts confidently.
41. As a student, I want artifact autosave to distinguish Editing, Saving, Saved, Offline, Failure and Conflict, so that I never mistake an unsaved draft for persisted work.
42. As a student, I want safe handling of refresh, slow networks, navigation and expired sessions, so that pending edits are not silently lost.
43. As a student, I want version history for every supported artifact type, so that recoverability is consistent.
44. As a student, I want to preview previous versions and restore one as a new revision, so that intervening work remains available.
45. As a student, I want feedback on a whole artifact or selected passage, so that I can focus coaching on a specific reasoning gap.
46. As a student, I want before-and-after previews of suggested edits, so that I can decide which changes to accept.
47. As a student, I want my prior document preserved when accepting AI edits, so that assistance does not erase my authorship history.
48. As a student, I want to assemble an artifact from selected canvas nodes manually or through reviewed synthesis, so that visual exploration can develop into coursework.
49. As a student, I want to create or link nodes from artifact selections, so that useful document reasoning can return to my map.
50. As a student, I want transfers to retain originating resource and revision references, so that I can trace how an idea developed.
51. As a student, I want explicit update options for linked content, so that changes do not silently synchronise over my edits.
52. As a student, I want the coach to use only selected, relevant project material, so that feedback stays focused and private.
53. As a student, I want canvas and artifact activity connected to stage guidance, so that I understand what reasoning remains necessary.
54. As a student, I want a Stage recommendation with a reason and an explicit Stage confirmation, so that I remain responsible for advancement.
55. As a student, I want Stage revisits to preserve existing completion semantics, so that refinement does not erase or fabricate progress.
56. As a returning student, I want a persisted resume dashboard showing recent work, current stage, feedback and a useful next action, so that I can continue without reconstructing my context.
57. As a student, I want a saved recap after a meaningful confirmed milestone, so that I understand accomplishments, remaining gaps and the next action.
58. As a student, I want clear course-supported criteria and optional learning activities, so that I know what a useful deliverable looks like.
59. As a student, I want Deep Review to continue safely across navigation, refresh and server restart, so that a long review is not lost.
60. As a student, I want review status, cancellation and honest retry information, so that I understand delayed or ambiguous outcomes.
61. As a student, I want old-revision review results identified and prevented from overwriting newer work, so that feedback remains trustworthy.
62. As a student, I want artifacts exported with content, references, revision and appropriate AI provenance, so that I can reuse them in coursework.
63. As a student, I want canvas JSON, an outline and a legible visual export including off-screen nodes, so that my reasoning is portable.
64. As a student, I want a selected project export combining relevant conversation, progress, artifacts, canvases and references, so that I can take useful work away.
65. As a mobile student, I want focused views, usable editing and touch controls, so that essential tasks work at a 390 px viewport.
66. As a student, I want consistent light and dark themes, reduced motion, visible focus and accessible statuses, so that the workspace matches my needs.
67. As a lecturer, I want existing protected Streamlit tools retained, so that student improvements do not require an administration rewrite.
68. As an authorised lecturer, I want privacy-conscious aggregate engagement signals, so that I can evaluate usefulness without equating message or node count with learning quality.
69. As an operator, I want bounded jobs, uploads, autosaves, exports and AI requests, so that legitimate classroom activity remains sustainable.
70. As an operator, I want restorable backups of student work and review metadata, so that failures have a tested recovery path.
71. As a maintainer, I want authoritative generated API contracts and deterministic drift checks, so that browser and backend changes remain compatible.
72. As a maintainer, I want regression tests across identity changes, conflicts, recovery and reference validation, so that new tools preserve existing guarantees.
73. As an operator, I want measured capacity, latency and total cost under representative workloads, so that classroom readiness claims are defensible.
74. As a maintainer, I want a nonsecret deployment manifest, coordinated migration and safe rollback instructions, so that release state is reviewable.
75. As a project owner, I want every mandatory requirement tracked with executed evidence and remaining gates, so that partial implementation cannot be mistaken for completion.

## Implementation Decisions

### Scope, authority and compatibility

- Continue from the inspected architecture-responsiveness baseline; architecture-completion is the suggested implementation branch. The user subsequently approved local tickets and TDD implementation. Staging, committing, deployment, live migrations and paid calls remain separately gated.
- Limit course changes to CDE2300. Preserve the separate other-course application, prompts, corpus and deployment. Preserve existing identities, persisted work, entrypoints, lecturer boundaries and compatibility facades.
- Retain React, TypeScript, Vite, Tailwind, FastAPI/Pydantic, existing authentication, the single LangGraph educational workflow, generation admission, retrieval and provider ports, SQLite/local storage and existing optional AWS adapters. Local mock operation must not require AWS, internet or paid APIs.
- Preserve the glossary distinction between Lecture help and Project coaching; the five Thinking Path stages remain Problem identification, Concept generation, Design specification, Ethics & Critical Thinking, and Reflection. Retain the internal persisted stage identifiers.
- Learning assessment and recommendations remain structured, validated and persisted. First-time advancement requires Stage confirmation; Stage revisit retains existing rules. Canvas content, polished artifacts, node counts, recaps and AI suggestions cannot independently award completion or change stages.
- The new student canvas is separate from the internal workflow graph and graph stream event. Reuse existing notebook/thread identifiers and parent relationships; document the resource anchor explicitly before schema implementation rather than inventing a parallel project identity.
- Respect existing architectural decisions; no dedicated ADR directory was found during discovery. Record any necessary superseding decision before implementation. Keep presentation, application/domain and infrastructure separate, with complete public typing and useful docstrings.

### Generated contracts, Query and workspace loading

- Audit ordinary student REST operations and expand the existing Hey API generator: notebook CRUD/organisation, metadata and messages, bookmarks, My Work, project state/briefs, Thinking Path/selection/confirmation, sources, preferences/settings, review jobs/results, exports and new canvas/artifact/version operations. Preserve specialised multipart, binary and NDJSON adapters with documented exceptions. Do not expose professor/admin routes through a general generated client.
- FastAPI/Pydantic owns explicit request/response/error contracts, stable operation IDs, nullability, status codes, ownership and revision semantics. Never edit generated files manually. Retain necessary adapters for renewal, normalisation, status-only errors and identity fencing while removing duplicate REST shapes.
- Extend offline allowlisted schema export with disposable mock storage, blocked network access, reachable-schema filtering and deterministic drift detection. Keep production OpenAPI/Swagger disabled and never fetch production schemas for ordinary development.
- Preserve same-origin HttpOnly cookie authentication, credential renewal, origin/CSRF restrictions, private no-store, AbortSignal, revision-bound pagination and deployment aliases. Query cache eligibility never establishes authorisation.
- Expand owner/resource/revision-aware Query keys and confirmed server state to workspace metadata, paginated history, project/Thinking Path, bookmarks, sources, preferences, settings, reviews, artifacts, canvases and version lists. Keep drafts, live editor interaction, local undo and provisional model text outside confirmed Query state.
- Adopt resource-specific freshness only after measurement and identity lifecycle regressions. Investigate 30 seconds for lists/settings/bookmarks, 1–2 minutes for preferences and 2–5 minutes for course metadata; use mutation-, revision- or job-aware policies elsewhere. Select retention separately. These are experimental values, not prescribed defaults. Never persist private Query data in shared caches or browser local storage.
- On logout, account switch, Guest migration, expiry or owner change, detach incompatible streams, cancel private reads, invalidate the identity epoch, clear incompatible caches/drafts, reject late events, verify the new identity and reload authorised data. Include changes initiated by another tab. Retained data cannot bypass required probes.
- Reconcile confirmed mutation results into affected resources; cancel superseded reads and avoid blanket invalidation. Optimistic updates may apply only to reversible display preferences, renaming and bookmarks with rollback. Never optimistically confirm stages, model results or unpersisted revisions. Do not automatically retry model operations or ambiguous mutations.
- Preserve message ordering, cursor/revision semantics, append-only editing, scroll position and deduplication. Prefetch only bounded likely-next authorised resources, never every notebook transcript.
- Add an owner-verified bounded workspace read using existing reader conventions and projections: metadata, initial message page, conversation revision, project/Thinking Path, bookmark metadata, settings and small availability indicators. Reuse verified bootstrap preferences. Exclude full sources, unbounded history and complete version histories.
- Reuse existing owner, workspace, learning and persistence services; prevent N+1 access. Enforce revision consistency where required and distinguish an owner-consistent collection from an actual transactional snapshot. Seed confirmed Query resources without immediate duplicate component fetches.
- Preserve the verified two-request startup where safe and aim to reduce nine chat-opening reader requests toward two to four without removing necessary verification. Add exact edge method/path permissions; do not broadly allow all reader routes.

### Routing and chat lifecycle

- Introduce TanStack Router with typed notebook/thread, canvas and artifact parameters, authentication-aware loading/error states, browser history, refresh/deep linking, safe prefetch and lazy routes. Preserve the root student entry, the pilot base/alias, protected Streamlit and exact API boundaries. SPA fallback must cover recognised frontend routes without catching private/internal APIs.
- Handle unsaved navigation through safe save boundaries, compatible owner-scoped drafts and warnings where needed. Do not transfer drafts across owners. Follow the existing draft policy and explicitly document any extension for richer content.
- Extract a cohesive chat controller/reducer and focused message/composer/recovery responsibilities. Model idle, submission, queue, retrieval/preparation, generation/eligible preview, validation, save, completion, cancellation, recovery, failure and ambiguous persistence without contradictory booleans. Avoid cosmetic moves or unrelated broad refactors.
- Retain started, status, reply_delta, reply_discard, reply_ready, graph, done and error NDJSON semantics. Only a saved done or successful exact-key receipt recovery establishes committed output. Preserve request/owner binding, idempotency, cancellation, late/duplicate-event rejection and explicit ambiguous-outcome reconciliation. Never blindly resubmit a generation.
- Retain honest real-operation indicators and no fabricated percentages/cold-start explanations. Profile chunk updates, render counts, Markdown, scrolling and long histories before batching/memoisation or virtualisation changes.
- Preserve suppression of Mantle provisional output before final Guardrail validation. Audit other provider paths separately. Distinguish first internal token, internal reply text, first safe visible text and final committed completion. Do not remove safety to improve latency.

### Shared workspace persistence

- Introduce dedicated typed artifact, canvas, revision, milestone recap and durable-review models behind cohesive application services/repository ports. Both SQLite and DSQL must preserve logical behaviour through supported transactions; do not assume unrestricted PostgreSQL functionality or add a graph database.
- Artifacts and canvases carry stable IDs, verified owner, existing notebook/project association, title/type, schema version, current revision, timestamps, provenance and validated references. Persist one canonical structured artifact document and a bounded graph snapshot initially where compatible; derived plaintext/export forms are projections.
- References to messages, sources, nodes, artifacts, versions and jobs must resolve under the authorised owner/project boundary. Reject forged, cross-project, foreign-owner and invalid references. Mark deleted/unavailable evidence and stale linked revisions clearly without substituting content or silently synchronising copies. Preserve origin authorship and AI provenance.
- Provide list/create/read/update/delete, bounded version history and version inspection/restoration for artifacts and canvases, plus approved export operations. Use repository route conventions, explicit models, generated contracts and exact edge permissions. Deletion must follow existing privacy/retention policy and handle inbound references explicitly.
- Use explicit base revisions, conditional atomic commits, bounded payloads, deterministic request identity and confirmed saved revisions. Equivalent duplicate requests cannot create duplicate revisions; stale writes return an actionable conflict and preserve the student's pending edits. Reconcile unknown outcomes before additional writes.
- Separate local edits/undo, confirmed current draft and meaningful persistent checkpoints. Define an explicit bounded checkpoint policy for debounce, inactivity/explicit save, milestone, accepted suggestion and restoration; avoid a permanent revision per keystroke or pointer move. Viewport changes must not create meaningful content revisions. Record the actual policy and measured write amplification.
- Restore a previous version by creating a new current revision with an expected-current-revision check, preserving intervening history. Offer previews and useful comparison/labels for every supported artifact type and canvases.
- Use explicit additive, repeatable migrations with existing-data compatibility fixtures, backup/restore instructions and a tested rollback path. No destructive reset, startup DSQL DDL, live migration or user-data modification during planning. Preserve legacy workflow-marker/readiness protections.

### Design Canvas

- Implement compatible stable React Flow through the existing application, lazy-loaded where practical. Support course-aligned problem statement, optional How Might We, stakeholder, user need, evidence, assumption, constraint, concept, specification, ethics, evaluation, reflection and generic note nodes. Validate pedagogy rather than inventing stage criteria.
- Nodes carry stable IDs, type/title/description/position, optional Thinking Path stage, authorised evidence/message/artifact references and provenance. Edges carry stable IDs, same-canvas endpoints, relation and optional explanation. Support meaningful relationships such as supports, addresses, depends on, conflicts with, requires, derived from, alternative to, evaluated against and raises concern about.
- Validate graph schemas, size, counts, IDs, endpoints and references on the backend. Keep rapid interaction local; use bounded debounced snapshot saves and revision-aware conflicts.
- Implement node creation/edit/duplicate/delete with incident-edge handling, connection editing, multi-selection, pan/zoom/fit, local undo/redo, node search, useful category/stage filtering/highlighting, details panel, save/autosave, version restore and export. Start empty or offer clearly optional labelled starter examples; never prefill a complete solution.
- Provide accessible labels, keyboard and touch operation, focus-managed editing and an alternative list/outline supporting essential actions. Canvas use is optional for students even though implementation is mandatory.

### Artifacts and connected AI assistance

- Implement compatible stable Tiptap with only needed extensions and no paid editor cloud. Support course-aligned problem statements, stakeholder/user needs, findings, constraints, alternatives, specification, evaluation, ethics, reflection and notes without duplicating educational rules.
- Use validated canonical document JSON, server-side allowed structures, nesting/text bounds and safe URL schemes. Reject arbitrary HTML, scripts, event handlers and unsupported embeds; sanitise previews and exports. Provide practical paragraphs/headings/emphasis/lists/links and educationally useful checklists/tables.
- Implement create/list/open/rename/edit/duplicate/confirmed-delete, undo/redo, autosave, honest save states, history/preview/restore, export and selected AI feedback. Handle offline/slow network, duplicates, refresh, navigation, identity expiry, save failures and conflicts without claiming unconfirmed saves.
- Reuse the existing coach, retrieval gate, provider layer, context planner and generation allowance for canvas/artifact actions. Do not add per-feature agents or routing layers. Student-selected contextual actions include explain, brainstorm, compare, critique, refine, reflect, evaluate and identify evidence gaps.
- Chat-to-canvas converts a selected passage into an editable proposal with chosen destination, type, title, content and references; creation requires confirmation and retains message provenance. Do not auto-convert all replies.
- Canvas-to-chat sends resource/revision and selected IDs; FastAPI resolves authorised persisted text server-side. Explicitly label unsaved student selections if supported. Extend deterministic token-budget planning with selected nodes/excerpts, bounded adjacent edges/neighbours, evidence, stage and existing summary; bound expansion depth, selections, evidence and tokens. Do not attach every artifact or an entire graph by default.
- AI suggestions use a validated bounded contract with suggestion identity/type, targets, proposed content/relationships, rationale, evidence and base revision. They are untrusted proposals, never executable mutations. Allow accept, edit-before-accept, reject and ignore. Acceptance uses ordinary authorised conditional persistence and revalidates changed revisions.
- Artifact feedback supports whole documents, selected paragraphs/text, requirements and reasoning gaps; show suitable before/after previews and apply only explicitly selected changes with recoverable provenance.
- Canvas-to-artifact supports manual assembly and optional bounded AI synthesis into a reviewed draft, preserving node/revision origins. Artifact-to-canvas creates or links nodes from selected content, preserving artifact/version origins. Linked content updates are explicit.
- Treat all selections, uploads, artifacts, graph text and linked evidence as untrusted data, never higher-priority instructions. They cannot change authorisation, tools, sources, stages, saved work or prompt visibility. Preserve citation validation and evidence-gap behaviour without fabricated references.

### Continuity, exports and lecturer experience

- Extend existing persisted project_resume/project brief/assessment projections into a resume dashboard: recent/current project, stage, last activity, artifacts/canvas, incomplete work, review feedback and useful next action. Avoid page-load AI summarisation, fabricated progress and activity-count proxies for learning quality.
- Persist deduplicated recaps bound to meaningful confirmed stage/project revisions, describing accomplishments, changes, relevant work, gaps and next action. Prefer deterministic use of saved assessments. Additional generation must be justified and bounded; recaps do not authorise progression.
- Investigate initial-stage friction through criteria clarity, repeated questioning, response length, visible deliverables and navigation. Make requirements actionable without weakening them. Add resumable configurable activities only where supported by actual CDE2300 curriculum and existing lecturer authority; do not invent schedules/assessment rules.
- Artifact exports provide useful Markdown, plaintext and structured JSON with safe print-friendly output where useful. Canvas exports must include structured graph JSON, human-readable outline and legible SVG or PNG including off-screen nodes. Include appropriate title/project/revision/references/AI provenance without internal prompts, hidden reasoning or operational information.
- Deliver a selected integrated project export using existing mechanisms where possible: relevant conversation, summary, Thinking Path, selected artifacts/canvases and source references. Keep ownership checks and bound export work; no unnecessary rendering service.
- Retain existing lecturer Streamlit and protected/audited APIs. Extend aggregate engagement only within existing consent/access rules, separating returning students, meaningful stage progression, artifacts/revisions, canvas/concept exploration, help/coaching/review, abandoned interactions, usefulness and errors. Counts are activity signals, not evidence of educational quality. Lecturer React charts/tables remain conditional future work.

### Durable Deep Review

- Extend persisted receipts into a persistence-backed bounded worker with explicit queued/claimed/running/cancel-requested/cancelled/succeeded/failed/retryable semantics adapted to current conventions. Persist owner/project/input revision/idempotency, attempts, lease owner/expiry, heartbeat, result/failure and timestamps.
- Atomically claim jobs, heartbeat leases, recover expired claims safely, bound attempts/concurrency and persist results idempotently with revision fencing. Cover cancellation, clean shutdown and restart. An old review cannot overwrite newer authoritative work.
- Distinguish recoverable pre-invocation failures from ambiguous external outcomes. Do not promise exactly-once inference or blindly repeat a possibly successful billable call. Surface honest reconciliation/failure or explicit retry requirements where certainty is unavailable.
- Keep existing admission/accounting protections across restart; do not release an unknown cost/capacity reservation merely because a worker disappeared. Introduce SQS/Step Functions only if evidence shows the persistence-backed design cannot meet requirements, with separate infrastructure approval and cost analysis.

### Measurement-gated performance, security and operations

- Establish reproducible baseline and experiment infrastructure for DSQL connection/auth versus SQL time, connector/bounded psycopg pool alternatives and async pooling only if justified. Verify supported behaviour against authoritative documentation before adoption. If pooled, bound acquisition/size/lifetime, replace unhealthy connections, preserve IAM/close/context/commit/rollback/whole-transaction OCC semantics, prevent contamination and owner leaks, cleanly shut down, account for worker multiplication and release connections before model waits. Do not make pooling default without demonstrated benefit.
- Audit repeated ownership/data reads and supported indexes while retaining access checks. Profile blocking SDK/database/retrieval/upload/serialisation work before bounded offloading, client reuse, parallel independent work or async changes. Preserve admission, budgets, cancellation and finite queues.
- Extend existing performance/usage telemetry with privacy-safe correlation across browser, authentication, admission, DB, retrieval, context, runtime/provider, guardrail, validation, save and reconciliation. Distinguish measured from inferred timing, internal from visible text and model latency from application latency. Use OpenTelemetry/CloudWatch only where useful; keep local operation independent of monitoring SaaS. Redact secrets and sensitive identity/content, sample appropriately and document retention.
- Benchmark compact prompts, supported prompt caching, existing Gemma Fast Chat and Haiku rollback plus justified available alternatives, retaining Sonnet Deep Review unless evaluation supports replacement. Compare existing, optimised AgentCore and dedicated direct-provider experiments fairly. Preserve native JSON/nullability fixes, pedagogy, structured output, citations, safety, sessions, retries and accounting. Measure first-attempt reliability, bounded recovery frequency and cost per successful turn. Token reduction toward 4,000 from the historical 6,366-token example is an experiment, not an acceptance shortcut. Verify representative current requests first.
- Retain the existing retrieval gate by default. Extend labelled corpus coverage to explicit/implicit lecture questions, project coaching, ambiguous follow-ups, selected sources/uploads and canvas/artifact evidence. Measure precision, recall@K, MRR, citations, filters, evidence gaps and latency. Evaluate chunking, semantic/hybrid search, rewriting, reranking, multi-query or multimodal retrieval only for demonstrated gaps and with educational demand/privacy/cost assessment. Do not automatically introduce GraphRAG, another vector database or an LLM router.
- Evaluate tail latency, provider queues, runtime capacity, cold/warm sessions, networking, guardrails, token processing, retries, admission and DB overhead separately. Model replacement, direct inference, region migration, virtualisation, extra AWS services and advanced retrieval remain measurement-gated; record rejected experiments and reasons.
- Preserve design language, themes and reduced motion. Target WCAG 2.2 AA through contrast, keyboard/focus, dialogs, touch targets, labels, status/error announcements and non-colour distinctions. Avoid hover-only essentials or token-by-token screen-reader noise. Accessible primitives/icons may be adopted selectively. Lazy-load canvas/editor and measure initial/total bundle and route/render cost while preserving hashed asset caching and private no-store.
- Bound document/graph size, depth, reference counts, revision/autosave frequency, export work, AI critique, jobs and uploads with legitimate classroom use in mind. Extend existing admission before adding distributed services. No default Redis or unbounded worker/task pools.
- Review tracked logs, recordings, screenshots, configurations and benchmark artifacts for student/research/course/session/credential exposure. Use synthetic fixtures, do not print secrets, and do not delete user artifacts, rewrite history or rotate live credentials without explicit authority.
- Reconcile Compose, edge, images, environment guidance, runtime/model/session identifiers and rollback into a nonsecret versioned deployment manifest distinguishing repository defaults, last recorded deployment and actually verified live state. Retain existing EC2/Compose/Caddy/CloudFront/Cognito/DSQL/S3/Knowledge Base/AgentCore unless evidence justifies change. Assess Singapore latency, data residency, model availability, transfer and cost before region decisions.
- Prepare coordinated release ordering for frontend, backend, generated contracts, additive migrations, exact Caddy allowlists and runtime versions. Include backup, compatibility, staging, health/readiness and known-good rollback. Preserve the Mantle fix through rollout and rollback; verify runtime publication/version, required session rollover, fresh sessions and blocked outputs before asserting production protection.
- Extend backups to current artifacts/canvases, both version histories, messages, learning state and review metadata. Verify supported DSQL recovery mechanisms and rehearse restoration on disposable local or explicitly approved staging data, never destructive production exercises.
- Prepare synthetic mixed-load experiments at 1/10/20/40/60/80 students covering startup, navigation, coaching, grounded Q&A, source uploads, editing/autosave and Deep Review. Record throughput/errors, p50/p90/p95/p99/max, queueing, connections, OCC retries, provider capacity, token use and cost with workload/environment/sample-size limitations. Separate local mock, direct-provider and live-application results.
- Validate a low/expected/high monthly SGD cost model with dated current pricing and realistic active students, turns/tokens, retrieval/review/retry frequency, saves/revisions, storage/retention, monitoring and transfer. Include all retained infrastructure and any proposed job service; distinguish gross cost, credits, cash and post-credit operation. React Flow/Tiptap require no hosted service. Do not guarantee S$30 or run live tests without explicit request/token or cost caps and concurrency approval.

## Testing Decisions

- **Approved primary acceptance seam:** student-visible browser journeys through the production-built React frontend, real same-origin FastAPI routes and disposable persistent SQLite, substituting only deterministic provider/retrieval/external-auth adapters. Use Playwright Test with controlled synthetic identities, time and fault injection. Restart the actual disposable backend and reopen saved work. This exercises routing, generated REST, Query, NDJSON, services, ownership and persistence together rather than duplicating tests at every internal extraction.
- **Supporting contract seams:** extend existing FastAPI TestClient behaviour tests for validation/authorisation and exhaustive race/invalid-input cases; storage/worker contract tests for additive migrations, DSQL OCC, conditional saves, leases, crashes and restart; runtime/provider tests for pre-Guardrail suppression and structured-output handling. Fakes verify application contracts, not actual AWS compatibility or live model quality. Live verification remains a separate gate.
- A good test asserts externally observable outcomes: visible saved content after restart, denied access with no leaked projection, a confirmed revision, preserved conflicting draft, one committed turn/recap, no unauthorised mutation or no unsafe output. Avoid assertions about private hook names, component layout, SQL call order or the mere presence of a dependency. Use stable role/label interactions and deterministic failure control.
- Existing prior art includes verified bootstrap projection/isolation/restart API tests; registered and Guest reader tests; owner-change delayed bootstrap and in-flight-generation browser regressions; bookmark/review restart scripts; Query cancellation/late-response and bootstrap renewal tests; streaming parser/preview/discard and runtime Guardrail regressions; Deep Review DSQL frozen-stage and SQLSTATE 40001 tests. Reuse these fixtures and convert useful browser scripts into reproducible CI journeys.
- Cover the full integrated student journey: existing project → resumed conversation → authored nodes/relationships/evidence → saved/reopened canvas → authored/saved/reopened artifact → version preview and restore → chat-to-canvas → selected-node coaching → accepted/rejected suggestions → canvas-to-artifact and artifact-to-canvas → stage recommendation/confirmation → deduplicated recap → later resume → selected export. Exercise every supported artifact type's version contract and graph export bounds.
- Cover logout/account switch/Guest migration/expiry and cross-tab cookie changes during reads, stream events, autosave and suggestion acceptance; old responses must never render, repopulate caches or save under another owner. Direct API tests must reject foreign artifact/canvas/version/job/source/message/node identifiers and cross-project references regardless of frontend guards.
- Cover slow/offline network, lost save acknowledgements, duplicate requests, stale base revisions, concurrent tabs, navigation with pending edits, owner expiry, restore conflicts and failed saves. Confirmed state survives restart; pending work receives truthful recovery/conflict handling and is never silently overwritten.
- Cover NDJSON framing, split UTF-8, cancellation, interruption, late/duplicate events, validation discard, no unsafe Mantle preview, ambiguous persistence and exact-key receipt recovery. Check no automatic generation replay and zero duplicate committed turns in tested scenarios.
- Cover durable review claim races, lease expiry/heartbeat, crashes before and after invocation/result commit, cancellation, bounded retries/admission and stale project revisions. Verify idempotent result persistence without asserting exactly-once external execution.
- Add focused Vitest tests for Query policy/mutations, controller transitions, parser, graph/document validation and bounded context, autosave/history/conflicts/suggestion acceptance. Add React Testing Library component tests for user actions, loading, toolbar/editor/node controls, save/error states, previews, versions, resume and focus. Use request mocking only where it improves component integration; avoid replacing the primary real application journey with an all-mocked UI.
- Use automatic axe checks plus manual keyboard, focus, screen-reader status, touch, contrast, reduced-motion, light/dark and desktop/390 px mobile checks. Inspect real console errors. Verify visual exports include off-screen nodes and editor/export rendering resists hostile content and unsafe URL schemes.
- Run focused tests per change, complete applicable suites at milestone boundaries and before handoff. Extend deterministic bounded GitHub Actions with full Python collection, configured Ruff/frontend lint, Pytest, TypeScript, Vitest/component tests, offline schema/client drift, production-style build, Playwright, accessibility, dependency/secret scanning and existing CodeQL. Preserve the collection fix and passing regressions; fix valid lint findings rather than suppressing them.
- Benchmark startup, first open, switches, cached revisit, refresh/deep links, injected delays and long bounded histories with repeated trials and recorded environment. Engineering targets: safe startup two reader requests; chat open approximately two to four; cached navigation under 200 ms; ordinary API p95 under 500 ms; immediate submission feedback under 100 ms; normal coaching 5–10 seconds where supported; first-attempt structured output above 99%. Report actual bottlenecks when missed. Security, safety, persistence and stage authority remain hard invariants.
- This specification pass performs discovery and document validation only. Historical 3,209 backend passes/one optional skip, 30 frontend passes and prior benchmark/audit results are recorded baseline evidence, not freshly executed verification. Reproduce them in milestone 0 before implementation claims.

## Out of Scope

- Rebuilding the application, replacing React/FastAPI, changing NDJSON to SSE/WebSockets, adopting another AI SDK for streaming, or rewriting lecturer Streamlit as a prerequisite.
- Modifying the separate other-course application, curriculum, corpus or deployment; inventing unsupported course assessment rules; weakening stage criteria to increase completion statistics.
- AI-authored automatic completion, unapproved graph/document mutation, fabricated evidence, direct model access to persistence, per-stage/per-feature agents or multi-agent swarms.
- Paid Tiptap hosting, real-time collaborative editing infrastructure, a graph database, automatic GraphRAG/vector-store/router additions, shared cross-student response caching or private browser cache persistence.
- Unconditional adoption of pooling, async rewrites, prompt/model/provider changes, AgentCore removal, region migration, virtualisation, advanced retrieval or extra infrastructure without measured justification.
- Executing live infrastructure changes, production migrations, deployments, runtime publication, destructive recovery drills or billable provider/AWS benchmarks. These require separate explicit authorisation; live tests require request/token or cost caps and concurrency limits.
- Staging/committing source changes, deleting user data/artifacts, rewriting history, rotating credentials or claiming production protection/capacity/cost from repository code or mock tests.

## Further Notes

### Discovery baseline and related tracker work

Discovery on 24 November 2026 SGT found a clean architecture-responsiveness working tree at revision 4f12995. Source inspection confirms four allowlisted generated reader operations, Query keys for owner/notebook list with zero freshness/retention and no automatic retries, existing NDJSON event types and process-local Deep Review workers that lose queued/running execution on restart. The current dependency manifest does not include Router, React Flow, Tiptap, React Testing Library or Playwright Test. No application behaviour changed during this specification pass.

The recorded startup comparison is six to two reader requests and 823 to 338 ms with injected delay; chat opening remains nine requests, 298 versus 308 ms. These are small local synthetic samples, not an achieved production improvement. Prior mock 80-user success does not verify live AWS/provider capacity. Reproduce and extend measurements before selecting optimisations.

Related existing issues, checked during discovery: [#28 classroom capacity and sustainable cost](https://github.com/CloudKai/NUS-Codesign-Chatbot/issues/28) and [#29 React comparison/reversible release](https://github.com/CloudKai/NUS-Codesign-Chatbot/issues/29) remain open release gates; [#30 stage feedback in Summary](https://github.com/CloudKai/NUS-Codesign-Chatbot/issues/30) and [#31 stage-grouped bookmarks](https://github.com/CloudKai/NUS-Codesign-Chatbot/issues/31) remain open despite local implementation evidence. Preserve/reverify these behaviours; do not duplicate their work or close them without acceptance evidence. This programme may proceed with independent local milestones while live release gates remain open. No issue-state changes or dependency edits are implied by this spec.

### Requirement coverage and delivery sequence

The source is the supplied 101-section architecture-completion brief. All sections remain covered by this programme; conditional experiments remain conditional rather than disappearing from the ledger.

| Source sections | Coverage |
| --- | --- |
| 1–5 | Course scope, current baseline, discovery, non-negotiable authority and mandatory versus experimental work |
| 6–8 | Generated REST, Query policies, identity lifecycle and bounded workspace aggregation |
| 9–11 | Router, chat lifecycle, NDJSON/recovery and cohesive code boundaries |
| 12–22 | Unified information architecture and mandatory persisted accessible Design Canvas |
| 23–29 | Bounded canvas coaching, explicit structured suggestions, evidence and Thinking Path integration |
| 30–38 | Mandatory student artifact editor, persistence, revisions, autosave and reviewed AI editing |
| 39–43 | Shared project resources, bidirectional transfers and complete connected student workflow |
| 44–49 | Resume, persisted milestone recaps, stage guidance, supported activities and student authorship |
| 50–52 | Artifact, canvas and selected integrated project exports |
| 53–56 | DSQL experiments, additive persistence, DB optimisation and bounded backend concurrency |
| 57–66 | AI authority, latency, prompts/cache/models/provider experiments and retrieval evaluation |
| 67 | Durable Deep Review leases, restart, cancellation, revision and ambiguity handling |
| 68–72 | Existing design language, selective primitives, mobile, accessibility and bundle/render measurement |
| 73–78 | Privacy-safe observability, ownership/content/injection security, resource bounds and repository audit |
| 79–84 | Lint, Vitest, component/browser/backend coverage and deterministic CI |
| 85–89 | Deployment manifest, safety rollout procedure, coordinated release, retained infrastructure and restore |
| 90–92 | Mixed capacity matrix, explicit performance objectives and evidenced total cost model |
| 93–94 | Protected lecturer continuity and consent-bound aggregate engagement |
| 95–97 | Full milestone sequence, authoritative ledger and incremental evidence-driven execution |
| 98–101 | Technical/student/security acceptance and comprehensive final report |

| Milestone | Required outcome |
| --- | --- |
| 0 — Baseline/release blockers | Reproduce current local behaviour and baseline checks; resolve full lint blockers; establish remaining-work ledger; assess deployment drift and repository privacy; preserve safety fix. |
| 1 — Connectivity | Expand generated REST/Query, safe measured cache policies and workspace aggregation; verify identity races and before/after request counts. |
| 2 — Frontend foundation | Router, chat controller/boundaries, NDJSON compatibility, component coverage and Playwright Test foundation. |
| 3 — Shared persistence | Artifact/canvas models, reference/revision semantics, SQLite/DSQL adapters, approved APIs, migrations and ownership tests. |
| 4 — Tiptap artifacts | Fully persisted editing, autosave, all-type history/restore, conflicts, reviewed AI refinement and exports. |
| 5 — React Flow canvas | Authored nodes/relations, interaction, persistence, undo/redo, autosave/history, accessible alternative and exports. |
| 6 — Integrated AI workspace | Chat/canvas/artifact transfers, bounded context, evidence, explicit suggestions and Thinking Path integration. |
| 7 — Student engagement | Persisted resume, deduplicated recaps, contextual actions, curriculum-supported activities, actionable stage guidance and selected project export. |
| 8 — Backend/AI measurement | Connection/concurrency benchmarks, evidence-gated improvements, prompt/provider/AgentCore experiments, retrieval evaluation and observability. |
| 9 — Durable review/quality | Restart-safe review, complete browser CI, accessibility/security, deployment manifest, migration/restore rehearsal, cost and classroom procedures. |
| 10 — Final verification | Execute all feasible local suites/build/contract checks and integrated restart workflows; retain measurements, coverage report, release/rollback procedures and explicit live gates. |

Respect dependencies when reordering for security or shared contracts; durable-review risk assessment can start earlier. Do not stop at milestone 1 or silently defer mandatory canvas/editor features. Use one writer and a fresh client-selected implementation session per approved ticket, as required by repository contribution policy. Do not claim a model switch or delegate without the required user authorisation.

Maintain the existing authoritative implementation ledger rather than creating competing status documents. Each concrete requirement needs status (pending/in progress/implemented/verified/blocked), source locations, executed tests, evidence and remaining work. Installation, a component, a written test or a mock screenshot alone is not completion. Update documentation and evidence at each completed milestone, including behaviour/reason, changed files, targeted/full checks, migration/compatibility/rollback, known risks and the next exact action.

Final acceptance includes successful local React/FastAPI and protected Streamlit startup; preserved existing-data fixtures and sources/citations; safe streaming/cancellation/recovery; saved educational state/inspection after restart; Stage confirmation; persisted artifacts/canvases/history with no silent conflict loss; explicit AI acceptance; durable review recovery; accessible desktop/mobile operation; passing applicable suites and production-style build. Tested scenarios must show zero cross-account exposure, unauthorised resource/revision access, invalid cross-project references, unsafe rendering/provisional Mantle output, automatic AI mutation/stage changes, duplicate committed turns and lost confirmed artifact/canvas revisions.

The final implementation report must compare combined-testing1, architecture-responsiveness and the final implementation; map every mandatory requirement and experiment to verified status; explain technology choices, integration, alternatives and cost; document all user workflows; separate local/mock/direct-provider/live performance; list actual commands/pass/fail/skip and remaining live gates; describe coordinated migrations/release/rollback; and distinguish mandatory gaps, approval-dependent verification, optional improvements and rejected changes. Completion remains qualified until all required live release gates are satisfied.

The user confirmed the testing seams, approved the 53-ticket breakdown, and chose local publication; no GitHub publication is requested. Local tickets use the exact ready-for-agent status. Treat it as an umbrella specification implemented through the ordered milestones, not as a claim that the full application is already complete.
