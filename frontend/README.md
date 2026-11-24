# React student workspace

React serves students at `/` and keeps `/pilot/` as an alias. FastAPI owns
workspace data, evidence, and saved conversations. Use the
[local setup](../README.md#run-locally) to build with Node 22 and start the
same-origin Caddy stack. See [DESIGN.md](DESIGN.md) for layout and styles.

## Query and styling

TanStack Query manages owner-scoped notebook-list requests through the existing
session verification boundary. Queries are immediately stale and are removed
when unused. Session reset, sign-out, owner change, and unmount clear the query
client. Write reconciliation cancels older list requests before reading again.
Focus/reconnect refetch and automatic retries are disabled. Generation,
streaming, and saved-receipt recovery retain their explicit request lifecycle.

Tailwind 4 runs through its Vite plugin. `src/tailwind.css` imports theme and
utilities without Preflight, preserving existing app styles and Markdown.
New progress layout uses utilities; colours and motion use existing CSS tokens.

The chat bar labels its percentages as estimated. It approaches 65% while
waiting, reaches 90% on reply deltas, 98% while saving, and 100% only on a
validated saved `done` event or a recovered durable receipt. Discarded previews
return to indeterminate feedback. After six seconds without reply text, a
conditional explanation describes possible AWS startup. Timers clean up with
the component, and reduced-motion settings disable animation.

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
  focus the exact original and highlight it for six seconds. Stars are server-saved;
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
