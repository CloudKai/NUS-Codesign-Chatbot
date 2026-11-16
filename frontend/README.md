# Notebook reader pilot

Tickets #23–25 add a lecture and project companion `/pilot/` alongside Streamlit at `/`. The existing
FastAPI workspace and transcript remain authoritative. Build with Node 22:

```sh
npm ci --ignore-scripts --prefix frontend
npm run build --prefix frontend
```

Run the existing local launcher with Guest enabled and Caddy installed, or the
existing container build. Open the same-origin browser proxy at `/pilot/`.
FastAPI serves only `frontend/dist`; an absent build returns 404 for the pilot
while Streamlit continues to start. CI and the image build compile the pilot;
`scripts/build.sh` validates it using already installed dependencies before pytest.

The public proxy exposes exact reader GET routes and bounded lecture/project stream and stage-action POST routes.
The adapter requires verified registered/Guest credentials even in anonymous-capable
local mode, rejects staff and foreign notebooks, checks same-origin requests,
requires Origin on writes, and sets no-store/Vary Cookie. Internal CRUD, coach,
upload and lecturer routes remain private; only the reader stage adapters are public. Sign-in uses existing Cognito
and returns to Streamlit; reopen `/pilot/`. JavaScript never handles tokens.

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
access, and interrupted-session privacy. Citation excerpts and safe downloads support evidence inspection. Source management and remaining workspace parity stay in Streamlit and later tickets. The 5–8-student observations and two-week
pilot remain pending, with zero completed sessions. No learning or retention
benefit is inferred from this implementation.

Fonts are locally served under the bundled SIL Open Font Licenses, downloaded
from the Google Fonts upstream `ofl/ibmplexsans` and `ofl/sourceserif4` directories:
`https://github.com/google/fonts/tree/main/ofl/ibmplexsans` and
`https://github.com/google/fonts/tree/main/ofl/sourceserif4`.

Rollback: revert the ticket commit, rebuild the previous image, and remove its
reader/static proxy routes together. Existing Streamlit URLs, sessions,
notebooks, transcript, source bytes, and storage schemas need no migration.
