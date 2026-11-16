# Notebook reader pilot

Tickets #23–24 add a lecture conversation `/pilot/` alongside Streamlit at `/`. The existing
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

The public proxy exposes exact reader GET routes and one lecture-stream POST.
The adapter requires verified registered/Guest credentials even in anonymous-capable
local mode, rejects staff and foreign notebooks, checks same-origin requests,
requires Origin on writes, and sets no-store/Vary Cookie. Internal CRUD, coach,
stage, upload and lecturer routes remain private. Sign-in uses existing Cognito
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
available. There is no general conversation or stage-authoring API expansion.

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

This precisely specified reader extends the existing `DESIGN.md` world: IBM
Plex Sans interface, Source Serif 4 mark, cool slate/teal, notebook navigation
beside a readable transcript, a lecture composer, saved-request recovery, and a collapsible list at 390 px. The task scope
and composition were proposed once; no answer arrived, so these remain stated
implementation assumptions. This is an inherited-world extension, not a new
visual identity. Impeccable's narrow-request exception applies: no concept roll,
new root PRODUCT.md, comparison comp, or duplicate architecture document was
needed. The direction is choose notebook → ask a lecture question → distinguish preview from saved answer → inspect evidence and return to the draft.

The engineering findings in `docs/LEARNING_BASELINE.md` constrain this slice:
legible mobile reading, explicit loading/error recovery, independent evidence
access, and interrupted-session privacy. Citation excerpts and safe downloads support evidence inspection. Project stages, source management and workspace parity remain in Streamlit and later tickets. The 5–8-student observations and two-week
pilot remain pending, with zero completed sessions. No learning or retention
benefit is inferred from this implementation.

Fonts are locally served under the bundled SIL Open Font Licenses, downloaded
from the Google Fonts upstream `ofl/ibmplexsans` and `ofl/sourceserif4` directories:
`https://github.com/google/fonts/tree/main/ofl/ibmplexsans` and
`https://github.com/google/fonts/tree/main/ofl/sourceserif4`.

Rollback: revert the ticket commit, rebuild the previous image, and remove its
reader/static proxy routes together. Existing Streamlit URLs, sessions,
notebooks, transcript, source bytes, and storage schemas need no migration.
