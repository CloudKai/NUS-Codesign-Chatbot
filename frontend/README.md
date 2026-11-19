# React student workspace

React serves the default browser workspace at `/`. The `/pilot/` entrypoint
still works. FastAPI remains authoritative for workspace data and transcripts.
Build with Node 22:

```sh
npm ci --ignore-scripts --prefix frontend
npm run build --prefix frontend
```

Run `sh scripts/start.sh` with Caddy installed and open
`http://127.0.0.1:8080/`. Guest availability comes from `GUEST_ACCESS_ENABLED`.
Verified lecturers and admins use `/streamlit/`. Ordinary accounts can be
enabled for that workspace with a server-side `STREAMLIT_ACCESS_COGNITO_SUBS`
grant. The browser proxy checks every Streamlit request, including the
WebSocket handshake. The same builds run under the production container.

The public proxy exposes exact reader GET routes and bounded lecture/project stream and stage-action POST routes.
The adapter requires verified registered/Guest credentials even in anonymous-capable
local mode, rejects staff and foreign notebooks, checks same-origin requests,
requires Origin on writes, and sets no-store/Vary Cookie. Internal CRUD, coach,
upload and lecturer routes remain private; narrow reader adapters are public. Sign-in uses existing Cognito and returns to `/`, which selects the account’s
workspace. JavaScript never handles tokens.

Ticket #24 adds lecture questions through the existing CoachRequest/NDJSON lifecycle.
The bounded browser body contains only question and idempotency key; the server
loads stage/detail and fixes lecture intent. The same shared stream implementation,
owner-scoped service, retrieval, saved transcript and exact-key recovery remain
authoritative. Preview is explicitly unsaved and is cleared on failure, malformed
input, EOF and cancellation. Stop watching cancels the reader, not server work.
Recovery only reads by exact request key; it never automatically replays a POST.
A successful null reconciliation enables an explicit same-key retry. A null result
means not saved yet, not proof that the original worker stopped. New sends stay
blocked while a request is unresolved. Busy/budget failures leave reading/evidence
available. Project coaching uses its own fixed-intent adapter with the same bounded body and recovery identity. The receipt also retains intent so explicit retries use the original mode.

Saved messages project validated citation fields. Evidence inspection shows the
saved excerpt, and downloads original bytes only after exact active saved-message
and source authorization. Pasted notes download their stored text. Downloads use
attachment/octet-stream/nosniff; no untrusted HTML is embedded. Closing evidence
restores citation focus and scroll while preserving the draft. Legacy messages
without citation metadata remain readable as text.

Private lists/replies/search remain in component memory, cleared on hiding/leaving.
Drafts and pending request identity/question live in **sessionStorage in this tab**,
scoped to verified owner and notebook, so reload can reconcile without re-generation.
No replies, citations, sources or tokens are stored there. Changed owners discard
other owners' drafts. Browser storage denial falls back to memory with an explicit
copy-before-reload notice. Focus and 15-second visible probes detect session changes;
this is bounded detection, not instant cross-tab notification. No service worker or
persistent transcript cache is installed. Deployment must preserve cookies and disable
private caching for reader/auth routes, honoring no-store. No CDN change was deployed.

## Narrow visual direction

The user requested Impeccable design while keeping the three vertical panel style.
This Operate surface shares the visual direction of `DESIGN.md`: IBM Plex Sans, Source Serif 4 wordmark,
cool slate/teal, thin separators and visible focus. Notebook navigation stays left,
conversation and its mounted composer center, canonical Thinking Path right.
At 1100 px and below, Thinking Path becomes a temporary side panel with an explicit
return-to-chat action and focus restoration; notebook navigation collapses at 700 px.
The active stage label stays above chat in either mode, and
pending decisions remain reachable in either mode. Saved work and stage previews
are progressively disclosed; previewing a stage never changes the active stage.
The pilot retains its existing CSS palette values and header; its widths and
breakpoints are documented here rather than claimed identical to Streamlit.
Existing token differences are preserved. No new identity, concept roll or generated
assets are needed for this extension.

Ticket #25 projects canonical stage labels, selectable flags, saved student work,
separately attributed coach feedback/summary, one next action and the exact pending
recommendation. Browser code neither calculates unlocks nor awards completion.
Explicit confirmation/rejection and stage navigation call the shared learning service.
Duplicate/stale decisions return conflict and reconcile by GET. An ambiguous action
blocks further changes/sends until a successful canonical refresh; no automatic POST
replay. Stage updates preserve the mounted draft and loaded transcript window; decision
feedback moves focus to the Thinking Path heading. Returning from the mobile panel
restores its trigger focus.
Project reads invoke no model. Legacy untagged work stays in chat; no authorship or
completion is inferred.
The engineering findings in `docs/LEARNING_BASELINE.md` constrain this slice:
legible mobile reading, explicit loading/error recovery, independent evidence
access, and interrupted-session privacy. Citation excerpts and safe downloads support evidence inspection. Source upload, selection, inspection, download and removal are available in the pilot; remaining workspace parity stays in Streamlit and later tickets. The 5–8-student observations and two-week
pilot remain pending, with zero completed sessions. No learning or retention
benefit is inferred from this implementation.

Fonts are locally served under the bundled SIL Open Font Licenses, downloaded
from the Google Fonts upstream `ofl/ibmplexsans` and `ofl/sourceserif4` directories:
`https://github.com/google/fonts/tree/main/ofl/ibmplexsans` and
`https://github.com/google/fonts/tree/main/ofl/sourceserif4`.

Rollback: revert the ticket commit, rebuild the previous image, and remove its
reader/static proxy routes together. Existing Streamlit URLs, sessions,
notebooks, transcript, source bytes, and storage schemas need no migration.

Ticket #26 adds a Sources view in the existing 340px right column at widths
above 1100px. At 1100px and below it uses a temporary right-side panel up to
540px wide, filling narrow viewports. It provides canonical selection and bounded
plain-text inspection (24,000 characters), safe original downloads, and explicit
removal confirmation. The transcript/composer remain mounted; closing Sources or
inspection restores focus, and closing Sources restores chat reading position.
No source bytes or extracted text enter browser storage. Deselecting affects future
turns; an already running answer uses its original authorized snapshot. Saved
citation labels/IDs/excerpts are not reassigned when sources change. Removed
originals return unavailable instead of resolving to a different source.

Nine additive typed reader routes cover sources and upload jobs. Multipart upload
admission uses the existing SourceUploadCoordinator in the API process: defaults
32 global/4 owner retained batches and 200/50 MiB, two workers, 300-second first
failure retry lifetime and three attempts total. Progress distinguishes queued,
processing, saved and failed. Successful payload release and failed retry expiry
run independently of browser polling. Retry/discard are owner/notebook checked;
retry uses freshly authenticated services. Receipts are count/age bounded and
clear on API restart; saved sources persist. These limits are per process (separate
from Streamlit's coordinator), not deployment-wide, and exclude incoming multipart
parser buffers, disk quotas and chat attachments. No capacity/release claim follows.

Source writes use the reader's credential, role, ownership and mandatory Origin
guards. A lost write response pauses new questions and changes until successful
GET reconciliation; writes are never automatically replayed. Upload transport
failure may mean admission succeeded: check jobs and source filenames before
explicitly selecting files again. There is no cross-request upload deduplication
key or persistent upload queue. Partial batch failures can leave earlier files
saved; inspect the source list before retrying a failed multi-file batch.


## Workspace and preference scope (#27)

The pilot creates and renames notebooks, downloads the full active saved transcript,
and deletes a notebook only after explicit confirmation. The shared WorkspaceService
performs writes and owned-file cleanup. Preferences stay in the existing navigation;
on desktop it scrolls independently so the three-panel workspace remains intact.
Appearance is an owner preference (System, Light, Dark); coaching style (Guide/Free),
response language, configured model/reasoning and assignment title/context are notebook
settings. Changes affect future answers. Unknown existing preference keys and other
notebook learning fields remain intact. No schema or existing-data migration is needed.

Nine additional narrow reader routes expose only these required GET/POST commands,
plus shared append-only user-message editing and bounded learning receipts. Existing
reader credential, student role, owner, Origin and no-store controls apply. Internal
workspace routes stay private. Owner/notebook verification and request generations
fence asynchronous reads. A successful write reconciles canonical list/settings;
ordinary renames/preferences retain the mounted transcript/composer and loaded history.
An ambiguous workspace write blocks new questions and changes until explicit GET-only
Refresh workspace succeeds. No automatic POST replay is performed. An ambiguous create
may already exist: inspect the refreshed notebook list before creating another.
There is no cross-request notebook-create deduplication contract.

Saved messages can be copied. Editing a student message requires an explicit confirm
and reruns the shared append-only revision service, replacing the active suffix without
erasing historical revisions. The newer composer draft stays intact. An uncertain edit
keeps its original target, content and idempotency key in the existing owner/notebook/tab
receipt; Check saved answer and explicit same-key retry use the original command.
Stop watching does not prove cancellation. An early null check may require checking
again after the server saves. Editing is a JSON result from the existing route rather
than a second streaming lifecycle. Eligible lecture answers offer optional Useful /
Not useful feedback; HTTP failure is shown honestly and reads refresh canonical ratings.

### Remaining student capability gaps

This ticket does **not** establish complete student-interface parity or authorize a
default switch. Folder CRUD/moving has no current canonical service/API: StudentStore
explicitly ignores the legacy folder filter and Streamlit's notebook library documents
that organization was removed. This implementation neither revives folder metadata nor
adds a storage migration. There is no standalone regenerate capability in the current
workspace; edit-and-ask-again and exact-key retry retain their distinct existing meanings.

Other capabilities still in Streamlit include chat attachment entry, website/pasted-text
source ingestion, source renaming, Deep Review controls/PDF export, notebook display-name
editing, and lecturer work. Saved Coach content continues the existing literal plain-text
rendering; Markdown markers can be visible (including legacy/project mock replies). Rich
Markdown rendering is not claimed by this ticket. The external formative study and
two-week pilot remain pending, with zero participant sessions; engineering results are
not release, learning-outcome, capacity, actual-cost or real-model-quality evidence.

Rollback #27 code and its nine public route patterns together, then rebuild the previous
frontend. No database reset or data migration is required. Existing messages, revision
history, source bytes, preferences, and Streamlit workflows remain usable.
