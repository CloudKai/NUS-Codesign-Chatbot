# Co-design Student Chatbot

Local critical-thinking coach for university students. The app is a **Streamlit**
UI plus a **FastAPI** coaching API. Student data stays on your machine (SQLite +
files under `data/`). Amazon Cognito Managed Login proves identity; FastAPI
keeps Cognito refresh + ID tokens in HttpOnly cookies (never DB / localStorage).

```text
Cognito authentication
        ↓
FastAPI /api/v1/auth/callback
        ↓
HttpOnly Cognito refresh + ID-token cookies (Path=/api/v1/auth)
        ↓
Streamlit asks FastAPI /api/v1/auth/me
```

Use **one command** to start everything. That command starts both services with
`USE_LOCAL_API=true`. Authenticated students call FastAPI with their Cognito
ID-token cookie; FastAPI verifies Cognito `sub`, binds the application user,
and scopes every notebook/source/message operation to that owner. The shared
`local-student` owner remains only for explicit local/mock demos and tests.

Both paths support Thinking Path progression, structured assessments, Review
personalization, and selected image grounding.

The current research workflow uses five phases: **Problem identification**,
**Concept generation**, **Design specification**, **Deep analysis**, and
**Reflection**. Automated research coding is provisional and evidence-linked;
it never grades the student or changes a phase by itself.

---

## Prerequisites

- **Python 3.12+** (3.12 recommended)
- macOS or Linux shell (`zsh` / `bash`)
- Optional later: [Ollama](https://ollama.com/) or an OpenAI API key

---

## First-time setup

From the project root (`Co-design Chatbot`):

### 1. Create and activate a virtual environment

```bash
cd "/path/to/Co-design Chatbot"
python3 -m venv .venv
source .venv/bin/activate
```

On Windows (PowerShell):

```powershell
cd "\path\to\Co-design Chatbot"
python -m venv .venv
.\.venv\Scripts\Activate.ps1
```

Confirm the venv is active (`which python` / `where python` should point inside
`.venv`).

### 2. Install dependencies

Prefer `pip` from the active venv (same as `pip3` inside `.venv`):

```bash
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
```

Equivalent if the venv is already active:

```bash
pip3 install -r requirements.txt
```

### 3. Create a local env file

```bash
cp .env.example .env
```

The example defaults are safe for local development:

- `MODEL_PROVIDER=mock` — no API key required
- `USE_LOCAL_API=true` — coaching API enabled (also forced by `scripts/start.sh`)
- `AUTO_ADVANCE_STAGES=false` — coach recommends a stage; press **Next** and confirm

Do **not** commit `.env` (it may contain secrets later).

### 4. Configure Cognito authentication

```bash
cp .streamlit/secrets.toml.example .streamlit/secrets.toml
```

Fill the private file (or equivalent env vars) with the Cognito app-client
values. In the Cognito app client, enable authorization-code grant,
`openid email profile`, self-service sign-up/confirmation as required by the
course, and allow this exact local callback URL:

- Callback: `http://127.0.0.1:8000/api/v1/auth/callback`

Sign-in starts at `http://127.0.0.1:8000/api/v1/auth/login`. Profile Logout
revokes the Cognito refresh token (best-effort) at
`http://127.0.0.1:8000/api/v1/auth/logout`, clears auth cookies, and returns to
the login gate with `?signed_out=1`.

Keep every local URL on `127.0.0.1` (not `localhost`) so host-only cookies stay
consistent. Keep `.streamlit/secrets.toml` uncommitted.

Cognito owns the browser session via HttpOnly refresh + ID-token cookies
(`AUTH_COOKIE_SECURE=false` locally; Compose sets `true` in production).
Refresh cookie Max-Age defaults to 30 days; Cognito app-client refresh validity
is authoritative. Tokens are never stored in SQLite or returned in API JSON.

### 5. Start the whole program (one command)

```bash
sh scripts/start.sh
```

Then open:

| Service | URL |
|---|---|
| Streamlit UI | [http://127.0.0.1:8501](http://127.0.0.1:8501) |
| API health | [http://127.0.0.1:8000/api/v1/health](http://127.0.0.1:8000/api/v1/health) |

Stop with `Ctrl+C` in the terminal that ran the script (it stops both API and UI).

---

## Everyday restart

If the venv already exists and dependencies are installed:

```bash
cd "/path/to/Co-design Chatbot"
source .venv/bin/activate
sh scripts/start.sh
```

You can also run without activating first; `scripts/start.sh` prefers
`.venv/bin/python` when that interpreter exists.

---

## What you get in mock mode

With `MODEL_PROVIDER=mock` (default in `.env.example`):

1. First chat turn at a stage gets guidance (stage stays).
2. Second turn at that stage recommends ADVANCE; with the default
   `AUTO_ADVANCE_STAGES=false`, press **Next** on Thinking Path and confirm to
   move the progress bar.
3. Upload/select sources (including images); the API coach path receives selected
   image inputs for grounding.

No OpenAI key is required.

---

## Optional: live providers

### Ollama (local model)

```bash
ollama pull gpt-oss:20b
```

In `.env`:

```bash
MODEL_PROVIDER=ollama
OLLAMA_BASE_URL=http://127.0.0.1:11434
OLLAMA_CHAT_MODEL=gpt-oss:20b
```

Then:

```bash
sh scripts/start.sh
```

### OpenAI (paid — only with explicit approval / budget)

In `.env`:

```bash
MODEL_PROVIDER=openai
OPENAI_API_KEY=sk-...
OPENAI_CHAT_MODEL=gpt-5.6-luna
DEFAULT_REASONING_EFFORT=low
MOCK_OPENAI=false
```

Paid calls are **not** part of the default local workflow. Keep mock or Ollama
for routine development.

### Thinking Path Next confirmation

Default: `AUTO_ADVANCE_STAGES=false`. After the coach recommends the next stage:

1. Press **Next** on Thinking Path.
2. Read the warning that confirming early can make the process less critical.
3. Press **Next** again in the dialog to confirm (or Cancel).

Quick coaching uses the practical evidence threshold; Strict requires clearer,
more consistently demonstrated reasoning before recommending advancement. The
profiles retain separate cumulative Review evidence. To restore silent
auto-advance:

```bash
AUTO_ADVANCE_STAGES=true
```

## Research review and lecturer visibility

Each coach turn may include a separately validated, provisional observation of
the current student utterance: one dominant CLEAR strategy, up to two Facione
behaviours, optional design-ethics concepts, and evidence offsets. Raw quote
copies are not stored in the research record. These codes do not award Facione
points, complete a phase, or determine a grade.

Authenticated users with persisted `lecturer` or `admin` roles can use the
professor **Research** view to see attributable student/notebook context,
inspect the active transcript, submit append-only reviews or adjudications, and
export filtered CSV. Identifiable reads and exports are themselves audited and
fail closed if the audit write fails. Students see their existing Review plus
Facione behaviour occurrences and a clearly provisional Reflection candidate;
CLEAR and ethics research labels remain staff-facing.

See [Research coding methodology](docs/research/METHODOLOGY.md) for operational
definitions, limitations, and cited sources. A future Bedrock adapter must
preserve the same provider-neutral one-call contract described in the
[Bedrock adapter handoff](docs/providers/BEDROCK_ADAPTER.md).

### Existing data and the five-phase contract

The six-stage and five-phase workflows are not silently mapped because their
educational meanings differ. A non-empty database without the exact workflow
marker fails readiness. Use the supported `scripts/start.sh` path and follow
[Research data reset](docs/operations/RESEARCH_DATA_RESET.md) to inventory and
back up learning data before any explicit reset. The reset is never automatic;
accounts and authentication identities are preserved.

---

## Course materials (`lecture_notes/`)

Put instructor PDFs and related files under:

- `lecture_notes/lectureNotes/`
- `lecture_notes/readings/`

They sync into each notebook as locked **Lecture Notes** / **Readings** groups.
`lecture_notes/README.txt` is instructional only and is not imported. Course
materials in this folder are shared in the repo; originals are never moved.
Prefer compressed PDFs. Future large PDFs under `lecture_notes/` are marked for
Git LFS in `.gitattributes` (existing blobs are unchanged until an explicit
migrate).

Trusted course files may be up to **50 MB**; student uploads remain **10 MB**
(up to 5 files per add). Student-upload compression uses `pymupdf` and `Pillow`
from `requirements.txt` when installed; lecture sync does not re-compress
shared course files.

### Local RAG behavior

Selected notebook sources are retrieved per turn rather than concatenated into
the prompt. The local retriever builds overlapping, sentence-aware chunks,
ranks them against the student's current question and bounded notebook context,
and sends only the strongest diverse excerpts to the coach. Source labels
remain stable (`[S1]`, `[S2]`), while internal chunk IDs are stored only for
audit/debugging. See
[`docs/PROMPT_ARCHITECTURE.md`](docs/PROMPT_ARCHITECTURE.md) for the complete
ingestion → retrieval → prompt → citation flow and the later Bedrock adapter
contract.

---

## Architecture (local)

```text
scripts/start.sh
  ├── FastAPI  backend.api:app     :8000   (coach turns, transitions)
  └── Streamlit streamlit_app.py   :8501   (ui/ panels)

ui/  → presentation only
backend/ → domain, workflow, providers, SQLite, sources
```

Prefer the API coaching path for all new behaviour. The legacy
`StudentChatEngine` path exists only as a fallback when `USE_LOCAL_API` is off;
do not add new behavior there. Production requires `USE_LOCAL_API=true`:
Streamlit calls FastAPI, which verifies the Cognito session and applies the
authenticated-owner boundary before accessing student data. The in-process
fallback is limited to local development and deterministic tests.

---

## Production Docker deployment (single EC2)

Production is the stateless ECR + Aurora DSQL + S3 stack described in
[`docs/deploy/AWS_STATELESS_EC2.md`](docs/deploy/AWS_STATELESS_EC2.md). The
default `compose.yaml`, its `./data` mount, and `docker compose up --build` are
for local development only; do not use them for the EC2 production service.

The production network boundary is:

```text
Internet :80/:443 -> Caddy
  /api/v1/auth/login           -> app:8000
  /api/v1/auth/callback        -> app:8000
  /api/v1/auth/logout          -> app:8000
  /api/v1/health               -> app:8000 (optional public probe)
  other /api/*                 -> 404 (never reaches FastAPI)
  everything else              -> app:8501 (Streamlit)
```

FastAPI and Streamlit share one `app` container and are not published to the
host. Only Caddy maps host ports. Inside the container, Streamlit reaches
FastAPI on `http://127.0.0.1:8000` for `/api/v1/auth/me` and other internal
calls; that loopback path is not published. Caddy obtains and renews HTTPS
certificates for `cde2300chatbot.duckdns.org`; the DuckDNS record must already
resolve to the EC2 Elastic IP, and the EC2 security group must allow inbound
TCP 80 and 443.

On EC2, install a private `.env` and `.streamlit/secrets.toml`, set an immutable
ECR image tag, and deploy with the production wrapper:

```bash
export APP_IMAGE="<account>.dkr.ecr.us-west-2.amazonaws.com/cde2300-chatbot:<git-sha>"
export ECR_REGISTRY="<account>.dkr.ecr.us-west-2.amazonaws.com"
export AWS_REGION="us-west-2"
sh scripts/deploy_ecr.sh
docker compose -f compose.prod.yaml ps
docker compose -f compose.prod.yaml logs --tail=100 app caddy
```

Production does not mount or transfer `data/`. Student state must be in DSQL
and S3. Before deployment, the host-only configuration must include:

```dotenv
DATABASE_PROVIDER=dsql
FILE_STORAGE_PROVIDER=s3
AWS_REGION=us-west-2
DSQL_ENDPOINT=<cluster-hostname>
DSQL_USER=co_design_app
USER_UPLOADS_BUCKET=<private-bucket-name>
```

Set the Cognito callback to
`https://cde2300chatbot.duckdns.org/api/v1/auth/callback`, keep
`AUTH_COOKIE_SECURE=true`, and do not put private values in the image or
repository. The current model path is configured independently (OpenAI or
mock); Bedrock/course-material integration is not required for this deployment
phase.

Safe pre-deployment checks, which do not call a model provider or AWS service:

```bash
docker compose config --quiet
APP_IMAGE=co-design:test docker compose -f compose.prod.yaml config --quiet
sh -n scripts/start.sh scripts/start_prod.sh scripts/build.sh scripts/deploy_ecr.sh
.venv/bin/python -m pytest -q
PYTHONPYCACHEPREFIX=/private/tmp/co-design-pycache \
  .venv/bin/python -m compileall -q backend ui streamlit_app.py tests
```

The production readiness endpoint verifies configuration, all required DSQL
tables/grants, and read access to the S3 bucket. It will deliberately return
503 until DSQL bootstrap/grants and the private S3 bucket/IAM permissions are
complete.

After DSQL is ready, and only with separate approval for live writes, check
runtime-role idempotency with the deterministic smoke:

```bash
DATABASE_PROVIDER=dsql DSQL_USER=co_design_app \
  .venv/bin/python scripts/smoke_dsql_idempotency.py \
  --confirm-live --identifier 'cognito:<sub>'
```

The command uses two independent runtime connections and the mock coach,
creates one disposable notebook, performs no DDL/S3/Bedrock/provider calls,
and removes its rows in `finally`. Do not run it until Aurora DSQL is ready and
the live operation has been explicitly approved.

For local development only, use the stateful default Compose stack:

```bash
cp .env.example .env
cp .streamlit/secrets.toml.example .streamlit/secrets.toml
mkdir -p data
chmod 700 data .streamlit
chmod 600 .env .streamlit/secrets.toml
sudo chown -R 1000:1000 data .streamlit/secrets.toml
docker compose up -d --build
```

> Security boundary: Caddy publicly exposes only auth browser routes
> (`/api/v1/auth/login`, `/callback`, `/logout`) and `/api/v1/health`.
> `/api/v1/auth/me` stays on the container loopback. Cognito-authenticated
> Streamlit sessions continue to use owner-scoped in-process services. Other
> `/api/*` paths return 404 at Caddy and never reach FastAPI on the public
> hostname.

---

## Tests

Install the pinned development tools with `python -m pip install -r requirements-dev.txt`,
then run:

```bash
source .venv/bin/activate
python -m pytest -q
ruff check .
PYTHONPYCACHEPREFIX=/private/tmp/co-design-pycache \
  python -m compileall -q backend ui scripts streamlit_app.py tests
```

### Headed Cognito browser smoke

The deterministic suite covers the authenticated API critical path with an
in-memory Cognito verifier and object store. A real browser cannot perform the
protected workspace flow without either real Cognito authentication or a test
cookie bypass, and the application deliberately has no such bypass. After
explicitly approving a real Cognito smoke test, start the local stack and run:

```bash
sh scripts/start.sh
sh scripts/browser_e2e_smoke.sh
```

The runner captures the signed-out desktop shell, pauses for a manual Hosted
UI login and disposable-notebook check, then captures the authenticated 390 px
mobile layout and browser console errors. It stores ignored artifacts under
`output/playwright/browser-smoke/`; do not enter credentials into scripts or
commit those artifacts.

---

## Troubleshooting

| Symptom | Likely cause | Fix |
|---|---|---|
| Thinking Path never leaves Problem identification | UI started without API | Use `sh scripts/start.sh` only |
| Coach error about local API | API not up / wrong URL | Check `:8000/api/v1/health`; keep `CO_DESIGN_API_URL=http://127.0.0.1:8000` |
| Provider / OpenAI errors on first run | `.env` set to `openai` without a key | Set `MODEL_PROVIDER=mock` |
| Port already in use | Another process on 8000 or 8501 | Stop the other process, then restart `start.sh` |
| Imports missing | Wrong Python / no venv packages | `source .venv/bin/activate` then `python -m pip install -r requirements.txt` |
