# React student workspace

React serves students at `/` and keeps `/pilot/` as an alias. FastAPI owns
workspace data, evidence, and saved conversations. Use the
[local setup](../README.md#run-locally) to build with Node 22 and start the
same-origin Caddy stack. See [DESIGN.md](DESIGN.md) for layout and styles.

## Typed workspace URLs

TanStack Router owns the student view URLs as the single navigation truth:
`/` (home), `/chats/{thread}`, `/notebooks/{folder}`,
`/notebooks/{folder}/artifacts/{artifact}` (the persistent document editor),
`/notebooks/{folder}/canvases/{canvas}` (the persistent design canvas),
`/library`, `/search` and
`/settings`, with the `/pilot/…` hosting alias rendering the same views. The
app's existing open flow stays the only loader — route changes call it, so
there is no duplicate navigation truth and no prefetch before the verified
bootstrap and owner checks. Browser back/forward, refresh and deep links
resolve exactly; an expired, foreign or malformed link renders the public
default and shows no private data. Composer drafts keep their existing
owner-scoped session-storage lifecycle; navigation no longer needs a separate
selected-thread key. The server and Caddy serve the SPA shell only for these
recognized view paths; every API path keeps its own allowlisted route and
everything else stays a hard 404.

## Persistent documents

Student artifacts are real Tiptap documents anchored to one owned notebook.
The notebook page's **Documents** tab creates one with a course-aligned type
(general notes plus one type per Thinking Path stage), lists saved documents
with their type and last-edit time, and opens the routed editor at the
artifact URL. Documents can be duplicated (new identity, same kind, title and
canonical document) and deleted with an explicit confirmation. The editor
supports paragraphs, headings, emphasis, bulleted and numbered lists and safe
`http(s)` links through a keyboard-accessible toolbar with truthful pressed
states, plus local undo/redo (native shortcuts included); checklists and
tables are deliberately absent until an educational need is validated.

**Autosave.** Edits save automatically after a two-second writing pause; the
indicator distinguishes Editing, Saving, All changes saved, Offline, Failure
and Conflict, and never claims a save the server has not confirmed. Saves are
deduplicated: a burst of edits collapses into one checkpoint, edits made
during a save trail onto the confirmed revision, and no revision is ever
written per keystroke. If another tab saved the same base revision, the
losing tab keeps the student's draft visible and offers two explicit
resolutions — reload the saved document, or keep the local edits and save
them over the reloaded revision; nothing overwrites silently. Unsaved drafts
are checkpointed per owner and artifact in this browser's session storage
only, restored after a refresh with a visible notice, and cleared on the
confirmed save; drafts never transfer across owners, and sign-out or an
identity change discards access without exporting anything.

**Version history.** Every confirmed save and restore checkpoints a version
(bounded to the 50 most recent) with truthful provenance — saved automatically,
saved explicitly, or restored from an older version. The editor's **History**
panel lists the checkpoints and previews one as read-only text; restoring
creates a **new** revision guarded by the seen revision, so intervening
versions and the previous current content are never lost. A stale restore
(409) leaves everything untouched and asks for a reload; deleting an artifact
removes its history, and notebook deletion removes both.

**Exports.** The editor's export group downloads the current saved artifact as
meaningful Markdown, plaintext or canonical JSON — with the title, kind,
revision and editor provenance, and nothing else. Downloads are `nosniff`
attachments with sanitized filenames, never render in-browser, exclude
hidden prompts and operational data, and render unsafe URL schemes as plain
text.

## Design canvas

The notebook page's **Canvas** tab creates an empty persistent design canvas
and lists saved canvases; opening one navigates the routed canvas URL. The
editor renders the graph as a React Flow map (drag to position, pan and zoom)
beside an accessible **Outline** that supports the essential actions without
dragging: add a node with a course-aligned type (note, problem, stakeholder,
user need, evidence, assumption, constraint, concept, specification, ethics,
evaluation, reflection), edit its title/type/description, remove it with its
incident connections, connect two nodes with a labeled relationship (supports,
addresses, depends on, conflicts with, requires, derived from, alternative to,
evaluated against, raises concern about) and an optional explanation, and edit
or remove relationships. Nodes may optionally associate with one Thinking Path
stage; the association is a visible label only and never satisfies or changes
stage requirements — the server rejects unknown stage ids. Edits autosave after
a two-second pause (see below); a stale save (409) keeps the student's edits
visible and offers reload or save-over resolutions, and the internal coach
workflow graph is entirely separate from these canvases.

**Canvas autosave (ticket 22).** Outline edits, duplication, connections,
removals and completed drags share one deduplicated autosave cycle: a burst
inside the two-second pause produces exactly one revision, edits during flight
trail onto the confirmed revision, and a completed drag produces at most one
checkpoint — never one per pointer movement. The confirmed response
reconciles the saved revision (the next autosave never goes stale), drafts are
checkpointed per owner and canvas in this browser's session storage only and
restored after a refresh with a visible notice. Canvas and document drafts carry
their original base revision. Stale or older unversioned drafts reopen in
Conflict with explicit reload and keep-and-save-over options. A save
acknowledgement only clears the draft it confirmed. For an uncertain write,
the editor reads the saved revision and content before another PUT, and
recognizes a lost acknowledgement when the next revision exactly matches the
submitted snapshot. Offline, failure and expiry states remain distinguishable.
Undo and redo are local to this tab until the next save.

**Canvas version history (ticket 23).** Every confirmed save and restore
checkpoints a canvas version (bounded to the 50 most recent) with truthful
provenance — saved, or restored from an older version. The editor's **History**
panel lists the checkpoints and previews one as a readable node/relationship
outline; restoring creates a **new** revision guarded by the seen revision, so
intervening versions and the previous current snapshot are never lost. A stale
restore (409) leaves everything untouched and asks for a reload; the restore
lands server-side as a confirmed revision and the local undo history starts
fresh from it. The Canvas tab also supports confirmed deletion of the listed
revision and its history. A newer saved revision requires checking the canvas
and confirming again. Other saved work retains its original evidence links.

**Durable Deep Review.** Open **Review → Summary** in a chat to see saved
Deep Review eligibility and job status. The completed Thinking Path unlocks
the start action. Queued and running jobs can receive an explicit cancellation
request. A review already past invocation may still finish. If the previous
outcome is unknown, the student can check its status and choose whether to
start a new review.

**Canvas exports (ticket 24).** The editor's export group downloads the saved
canvas as structured graph JSON, a human-readable outline or a legible SVG.
Downloads are `nosniff` attachments with sanitized filenames and
`Cache-Control: no-store`; the JSON envelope carries title, revision metadata,
editor provenance and the canonical graph — never workspace identifiers or
operational fields — and the SVG spans the whole graph including off-screen
nodes with all text XML-escaped, so untrusted content stays inert without any
hosted rendering service.

**Evidence links (ticket 25).** Artifacts and canvas nodes can reference
authorized evidence inside the same notebook: sources (course material and
uploads), active conversation messages, sibling artifacts and canvas nodes.
The server validates structure, resolves every reference under the
owner/project boundary, and fails closed (422) on fabricated, foreign or
cross-project references — omitted references keep the saved list; an explicit
list replaces it. Reads project resolved references with an explicit
`available`/unavailable state, so removed or superseded evidence shows as
unavailable instead of disappearing or being substituted. Artifact references
are part of the saved revision and its version checkpoints; canvas node
references live inside the canonical graph snapshot and flow through
autosave, history and exports. The artifact editor's Evidence panel and the
canvas node details provide the visible authoring controls.

Linking or detaching evidence preserves the kinds and version origins of
the other saved references, including canvas nodes used to assemble a document.
Accepting artifact feedback checks the revision it was generated from.
When the document has changed, the proposal remains available to copy or edit
and the student can request feedback on the current version.
Document-to-canvas transfers merge the selected link or new node into a fresh
saved graph and submit that exact revision, so a concurrent save produces a
conflict.

**Chat to canvas (ticket 26).** Every message carries an "Add to canvas"
action that opens an editable proposal — node type, title, content and
destination canvas, prefilled from the exact message — and only confirmation
saves: the proposal re-reads the destination canvas and writes over the fresh
revision, keeping the originating message id as the node's evidence reference.
Cancel saves nothing, a stale destination (409) asks for a re-confirm, and no
reply is ever converted automatically.

**Coaching selected canvas nodes (ticket 27).** The canvas editor's "Ask the
coach" action attaches the selected saved node to the next coaching send: the
request carries only the canvas id, seen revision and node ids, and FastAPI
resolves the authorized text server-side from the stored canonical graph
(family-scoped, revision-guarded 409, unknown nodes 422) into a bounded
`<canvas_context>` prompt section — placed in the untrusted channel between
project context and retrieved evidence, delimiter-neutralized and clipped to
3,500 characters with depth-1 neighbors. Client-supplied canvas context on the
legacy coach routes is stripped; retrieval, citations, safety, admission and
stage authority are untouched, and nothing changes the graph automatically.
The chat composer shows a labeled chip while the selection rides the next
send, and it clears after exactly one send.

**Map exploration (ticket 21).** The canvas adds local undo/redo over the
outline and canvas edits (buttons plus ⌘Z / ⇧⌘Z outside text fields; history
is bounded, tab-local and cleared on save — never presented as durable version
history), node duplication beside the original with its content and stage,
multi-selection on the map (shift-click and the native Delete/Backspace key)
that removes nodes with their incident connections through the same guarded
state, a search box that narrows the outline to title/description matches and
offers one-click locate (fit to the match), and type/stage filters that narrow
the outline while dimming non-matching nodes so the map stays honest about
what exists. Touch and keyboard operation of the map come from React Flow's
native controls; the outline remains the authoritative authoring surface.

## Query and styling

**Editor loading and CSP-safe layout.** The routed document editor (Tiptap) and
design canvas (React Flow) load behind dynamic imports: the chat-first startup
bundle stays free of both, deep links still mount the same components with a
brief `Loading editor…` status, and hashed asset caching is unchanged
(`tests/browser/route_load.spec.ts` measures and guards this). Panel widths are
applied through CSSOM rules (`applyLayoutStyle`) because the production CSP
`style-src 'self'` blocks inline style attributes; Tiptap's runtime style
injection is disabled and its base ProseMirror styles are vendored in
`styles.css` for the same reason.

**Accessible authoring.** The editor and composer dialogs (Add to canvas,
Develop into artifact, suggestion/feedback/draft review) render through
`ModalDialog`, the native `showModal()` contract: focus is contained while
open, Escape dismisses, the backdrop renders, and closing returns focus to the
opener (review cards whose dialog replaces their own control refocus it
explicitly). The canvas Locate control moves instantly under the OS
reduced-motion preference. `tests/browser/authoring_accessibility.spec.ts`
records the keyboard, dialog, 390 px, reduced-motion and Light/Dark contrast
evidence.

TanStack Query manages owner-scoped notebook-list requests through the existing
session verification boundary. Reads stay immediately stale; the last confirmed
listing stays in memory only so a confirmed write can reconcile it, and is
removed when unused. Session reset, sign-out, owner change, and unmount clear
the query client. Write reconciliation cancels older list requests before
writing the confirmed result, so a late pre-write response never rolls a saved
change back; the sidebar then revalidates through the owner-fenced list read.
Focus/reconnect refetch and automatic retries are disabled. Generation,
streaming, and saved-receipt recovery retain their explicit request lifecycle.

Tailwind 4 runs through its Vite plugin. `src/tailwind.css` imports theme and
utilities without Preflight, preserving existing app styles and Markdown.
New progress layout uses utilities; colours and motion use existing CSS tokens.

Chat activity stays indeterminate while sending, queuing, retrieving, writing
and saving. Status text follows actual request/stream events. Only validated
`done` or a recovered saved receipt completes the indicator. It makes no elapsed
time estimate or cold-start diagnosis. Reduced motion disables animation.

## Generated read contracts

FastAPI/Pydantic own the reviewed bootstrap, session, notebook-list, message-page,
aggregated workspace-open, preferences and notebook-settings contracts (reads
and confirmed writes). Their
SDK and types live in `src/api/generated/`; never edit these
files manually. `src/api/client.ts` applies same-origin cookies, `no-store`,
AbortSignal and status-only errors, then materializes documented optional
defaults for existing views. Cookie renewal still belongs to `currentSession`.
Preference, notebook-settings, notebook-create, chat-move, confirmed-delete,
source-catalog and source-selection writes are generated operations too, as are
the bookmark projection read, the message-star write, the project
read/decision/stage-selection contracts and the explicit whole-chat brief
request (its retry flag is the only generation trigger; reading cached brief
state never starts generation). The remaining custom
routes keep their documented specialized adapters: multipart upload submit and
composer attachments (FormData bodies), binary downloads (original source
files and the transcript export, always served as `nosniff` attachments with
same-origin cookies and caller cancellation), share's Web Share/download flow,
and the coach-turn NDJSON lifecycle with its streaming and exact-key
recovery. Source
metadata, upload receipts, bookmarks and saved project progress reconcile
through owner-fenced Query resources
that stay immediately stale and keep only the last confirmed data in
memory.

From the repository root, after changing a reviewed backend model:

```sh
.venv/bin/python scripts/export_reader_openapi.py
npm run api:generate --prefix frontend
.venv/bin/python scripts/export_reader_openapi.py --check
npm run api:check --prefix frontend
npm test --prefix frontend
npm run build --prefix frontend
```

The exporter uses disposable SQLite/mock storage, blocks network connections,
and includes only explicitly reviewed operations (bootstrap, session,
notebook-list, message-page, aggregated workspace-open, preferences/settings,
source-metadata, bookmark, project, brief, artifact and canvas reads plus their
confirmed preference, settings, create, move, delete, source-selection, star,
Thinking Path decision, explicit-brief, artifact and canvas writes) and
reachable public
schemas. Production `/openapi.json`, `/docs` and `/redoc` stay disabled. Adding
an operation requires updating the export allowlist, stable operation ID,
response/error models and its contract/security tests together. Generated files
and `openapi/reader.json` are checked in so ordinary production builds need no
Python or running backend. Checks regenerate into a temporary directory and
compare every file without rewriting source. CI checks both schema and SDK drift.

If SDK drift reports extra numbered copies in `client/` or `core/`, inspect the
temporary generated inventory and the installed generator bundle first. The
generator copies its bundled transport files, so duplicate files in `node_modules`
can cause drift even when checked-in source is correct. Reinstall dependencies
with `npm ci --ignore-scripts --prefix frontend` from the repository root (add
`--offline` when the lockfile packages are cached), then rerun the check. Do not
copy those duplicates into source or weaken the inventory comparison.

Hey API and Vitest are development dependencies. The `js-yaml` override selects
4.3.2 to remove advisories in the generator's pinned transitive parser. Recheck
this override when updating Hey API. Node 22.18 or newer is required by Hey API;
the local validation used Node 22.23.2. Query keys/defaults are centralized in
`src/api/queryKeys.ts` and `src/api/queryClient.ts`. Retention stays zero pending
resource-specific lifecycle and responsiveness measurements; no private cache
is written to browser storage.

Initial CDE2300 loading uses `/api/v1/reader/bootstrap` for the verified session,
sidebar projections and preferences, followed by a fresh session probe before
rendering private state. All three owner IDs must agree. Expired cookies still
renew through the existing auth probe; mismatches fail closed. WorkspaceTools
uses those verified preferences for its initial preference-only mount. Later
notebook navigation and mutations keep their normal read/revalidation flow.
This reduces a clean startup from six reader requests to two without retaining
private resources longer. The response is an owner-bound set of presentation
reads, not a transactional conversation snapshot. No transcript/source body or
model output is included. Existing independent routes remain available.

Opening a chat uses one bounded
`/api/v1/reader/threads/{id}/workspace` read: the initial message page and
revision, project/Thinking Path, bookmarks, notebook settings and bounded
counts, followed by the same identity probe. The verified response seeds the
notebook-settings Query resource and the sidebar's bookmark state, so no
component refetches them immediately; the response is an owner-consistent
collection, not a transactional snapshot, and excludes full sources, unbounded
history and version histories. Loading earlier pages keeps the existing
revision-bound pagination lifecycle.

## Keep the browser contract

- **Authentication.** The proxy exposes specific reader and auth routes.
  FastAPI checks registered or guest identity, ownership and same-origin
  writes. Keep private responses out of caches. The browser uses cookies
  and application responses, with tokens kept out of JavaScript.
- **Lecture Help.** A bare greeting invites a lecture, reading, or concept
  question without running retrieval or generation. Course questions still use
  the selected evidence, and replies do not assess project stage progress.
- **Turn recovery.** Lecture help, Project coaching and edits share the NDJSON
  lifecycle and exact-key recovery. A preview is provisional until save
  completes. Both normal and edited sends request reply deltas and render growing
  provisional text in small word groups, including with the system reduced-motion preference. A discarded attempt clears
  its preview; only done/reconciliation establishes saved content. Edits use
  `/messages/{id}/revise/stream`; the legacy JSON route remains available to other
  clients. The composer cross requests cancellation before saving.
  Reconcile by reading the saved result with its original key. Retry the write
  only when the student explicitly asks.
- **Drafts and Review.** Scope the tab's draft and pending request to the verified
  owner and chat. Keep the composer mounted during navigation within the chat.
  Summary starts with **Your project so far**: Who and why, Problem, Current idea,
  What matters, Still to explore. It synthesises the complete active saved chat,
  including earlier pages and lecture questions, rather than displaying recent
  prompts or stage-progress prose. Unknown facts stay explicitly unestablished;
  tentative ideas remain tentative. The course materials guide the categories.
  The compact **Summarise chat** button in the card header requests a missing whole-chat brief. Unchanged results are
  reused from owner-scoped server metadata; edits/new turns invalidate the brief.
  Failures are retained and require explicit retry. Mock mode honestly states
  that a whole-chat summary is unavailable, instead of inventing demo facts.
  Stage feedback is one compact section: all five rows start collapsed, show
  saved feedback counts (green Going well / yellow To work on) or a neutral
  unreviewed caption, and disclose Going well / To
  work on independently. Facione's strongest/grow/Practice stay visible; the six
  detailed scores and tips are available under All six skill scores. Assessment
  and stage progression never change merely from opening or navigating Review.
  Downloads include a newly generated brief immediately, then existing saved work.
  Review's open/closed choice and selected view survive visibility resets,
  navigation and reload in this browser tab, scoped to verified owner/chat.
  Only display choices enter session storage; private summaries are fetched again.
  Close, the header toggle, Escape and the drawer backdrop dismiss it. Jump to
  message intentionally returns to the exact original. Mobile Practice/scaffold
  actions keep Review open and announce that the editable draft is ready.
  Blocked tab storage prevents remount restoration but leaves Review usable.
- **Starred messages.** Chat lets the owner star either author. My work contains only
  those bookmarks, grouped by the message's saved stage. Saved stars are solid
  gold in Chat and My work; unstarred Chat actions return to outlines. Stage
  headers use the accent colour and a saved-count badge. Inset message groups,
  a subtle guide and separators make parentage clear; author labels are quieter
  than headings/content and Jump to message is a tertiary action. Groups and
  actions retain 44px targets, keyboard access and explicit screen-reader names.
  Bookmarks retain server-bounded previews of at most 320 characters and a six-line
  visual cap, including newline-heavy text. Full saved messages are unchanged and
  remain available through Jump to message. Clamped coach previews keep Markdown
  formatting but links are display-only to avoid clipped keyboard targets; full
  original messages retain safe links. Entries also show
  author labels, a Lecture Help tag only for that mode, Remove star and Jump to message.
  No stage appears collapsed only when populated. Jumps load older pages as needed,
  focus the exact original and highlight it for six seconds. Stars are server-saved
  through the generated star contract and the revision-fenced bookmark resource;
  replaced/deleted originals disappear and revised text needs its own star. A failed
  save is reconciled through a read and reported without automatic write replay.
- **Working/latest control.** A compact 32px circle within a 44px tap target sits
  above coach hints and both expanded/collapsed suggestions, or above the composer
  when those are absent. The circle floats over the transcript with an 8px visible
  gap above that content; the surrounding row is transparent and passes pointer
  interactions through to the chat. Only the circle has an opaque surface.
  It appears once the chat has content (including an active
  first turn). It shows three dots while
  watching/checking a reply wherever you are reading. When idle, the down arrow
  appears only while scrolled away from the latest message and hides on reaching
  the bottom (including by manual scrolling). Clicking or pressing
  Enter/Space scrolls smoothly to the bottom and resumes following new output,
  including output arriving during the animation. Wheel, pointer and keyboard
  interaction in the transcript stop automatic pursuit. App/OS reduced-motion
  preferences use an instant move. It never sends,
  stops or retries a request. Reduced-motion preferences stop the dot animation.
  Text status and ambiguous-request recovery remain alongside the composer cross.
- **Editing messages.** Edit replaces the original text/actions inside that same
  message with a text-sized field: short edits start at a compact 260px outer
  width, longer lines widen it up to the chat column. It grows vertically from 52px to a bounded
  360px (with a viewport cap on small screens). Short edits shrink again when text is removed;
  no manual resize handle or expand control is shown. The exact saved text is
  retained. Cancel (cross)
  and submit (up arrow) are bordered 44px icons inside the shared textbox border
  at bottom right, with accessible names/tooltips and hover colours. Their footer
  reserves space below the editable text so neither control covers long content.
  Enter adds a newline; Escape cancels and returns
  focus to Edit. A short note explains that submitting replaces this message and
  later active replies. Save/retry/recovery keep the existing revision operation;
  the separate composer draft remains intact. On failed-edit discard, both the
  composer draft and attempted edit are restored together. Chat action hover
  colours use the theme accent; saved stars retain gold.
- **Sources and Library.** Notebook Sources control future evidence.
  Attachments belong to the submitted turn unless added as a reusable
  source. Resolve saved citations against their original authorized evidence.
  A removed original may be unavailable even while its citation label
  remains. See [RAG architecture](../docs/RAG_ARCHITECTURE.md) for storage
  and retrieval behavior.
- **Ambiguous writes.** Refresh authoritative workspace state before further
  changes. Verify whether a notebook or upload already exists before retrying.

## Verify changes

```sh
npm run build --prefix frontend
```

Check affected browser journeys at desktop and 390 px. Include keyboard focus,
draft preservation and failure recovery when the change touches those paths.
Use the [testing guide](../docs/TESTING.md) for API coverage and the
[readiness decisions](../docs/operations/CLASSROOM_READINESS_DECISIONS.md#pilot-and-release-acceptance)
for the release criteria. The [prior React ticket history](https://github.com/CloudKai/NUS-Codesign-Chatbot/tree/948162e1eba9d0de3fbda7cbfce1d00731001158/new_docs/ticket_handoffs)
records the original pilot scope.


### Chats, settings and stopping a reply

Old unmarked workspace entries appear under **Chats** with their original IDs,
messages, settings and sources. **New notebook** labels a real project folder
explicitly. Older entries used the same storage shape, including folders created
before this marker existed, so the sidebar treats those entries as chats too.

Chat actions open upward and are repositioned when settings finish loading or
the visible browser area changes. The menu scrolls internally on short screens.

If a saved-answer recovery read fails, the error and **Check saved answer**
control remain visible. This retries only the read, using the existing receipt;
it never resends the question. Waiting dots are shown only while checking. If
nothing was saved and the composer has a newer draft, both texts are retained.

While generation runs, the bouncing dots and the composer’s **Stop generating**
button show its state. The button requests server cancellation. If saving has
started, the reply can finish normally. A stopped edit leaves the already
recorded revision in place and can retry with the same request identity.

A quick tab switch keeps the open workspace in memory. Returning after the
one-minute verification window triggers a quiet owner check. Server routes still
verify authorization. Sign-out clears other workspace tabs through a timestamp
notification. No session or transcript is added to persistent browser storage.

Student settings show English and the configured coach as read-only values.
Download the project from Review or share the transcript from the chat menu.
