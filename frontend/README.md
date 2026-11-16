# Notebook reader pilot

Ticket #23 adds a read-only `/pilot/` alongside Streamlit at `/`. The existing
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

The public proxy permits only reader session/list/page GETs. The browser adapter
requires verified registered or Guest cookies even in local-demo mode, rejects
staff access, checks notebook ownership, and projects typed fields without
research, storage, or assessment metadata. Internal CRUD, source, generation,
and lecturer APIs remain private. Browser writes are limited to the existing
origin-checked Guest entry endpoint. Sign-in uses the existing Cognito route and
returns to Streamlit; students reopen `/pilot/` afterward. The reader never
handles passwords or tokens in JavaScript.

Private lists/history/search live only in component memory. Hiding/leaving the
page clears them. Reads verify the current owner before display; generations
and aborts discard superseded responses. Focus and a 15-second visible-page
probe detect session changes, including changes in another tab. This is not an
instantaneous cross-tab cookie notification. No service worker or persistent
transcript cache is installed. Proxy/CDN deployment must preserve all cookies
and disable caching on `/api/v1/reader/*` and auth routes; it must honor
`Cache-Control: no-store`. No CDN configuration was changed or deployed here.

## Narrow visual direction

This precisely specified reader extends the existing `DESIGN.md` world: IBM
Plex Sans interface, Source Serif 4 mark, cool slate/teal, notebook navigation
beside a readable transcript, and a collapsible list at 390 px. The task scope
and composition were proposed once; no answer arrived, so these remain stated
implementation assumptions. This is an inherited-world extension, not a new
visual identity. Impeccable's narrow-request exception applies: no concept roll,
new root PRODUCT.md, comparison comp, or duplicate architecture document was
needed. The direction is choose notebook → read saved student/Coach work →
continue writing and opening cited evidence in Streamlit.

The engineering findings in `docs/LEARNING_BASELINE.md` constrain this slice:
legible mobile reading, explicit loading/error recovery, independent evidence
access, and interrupted-session privacy. Citation labels remain literal saved
text; this reader does not add source preview, generation, or stage actions.
Later tickets own those interactions. The 5–8-student observations and two-week
pilot remain pending, with zero completed sessions. No learning or retention
benefit is inferred from this implementation.

Fonts are locally served under the bundled SIL Open Font Licenses, downloaded
from the Google Fonts upstream `ofl/ibmplexsans` and `ofl/sourceserif4` directories:
`https://github.com/google/fonts/tree/main/ofl/ibmplexsans` and
`https://github.com/google/fonts/tree/main/ofl/sourceserif4`.

Rollback: revert the ticket commit, rebuild the previous image, and remove its
reader/static proxy routes together. Existing Streamlit URLs, sessions,
notebooks, transcript, source bytes, and storage schemas need no migration.
