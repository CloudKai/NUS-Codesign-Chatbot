# Co-design Student Chatbot

Local critical-thinking coach for university students. The app is a **Streamlit**
UI plus a **FastAPI** coaching API. Student data stays on your machine (SQLite +
files under `data/`). Amazon Cognito Managed Login authenticates students; the
application stores the stable Cognito subject and profile fields, never passwords
or refresh tokens.

Use **one command** to start everything. That command starts both services with
`USE_LOCAL_API=true`. The FastAPI process remains a single-owner local demo.
Authenticated Cognito sessions automatically use equivalent owner-scoped
in-process application services so one student's data cannot collapse into the
API's shared `local-student` owner.

Both paths support Thinking Path progression, structured assessments, Review
personalization, and selected image grounding.

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

Fill the private file with the Cognito app-client values. In the Cognito app
client, enable authorization-code grant, `openid email profile`, self-service
sign-up and confirmation as required by the course, and allow these exact local
URLs:

- Callback: `http://127.0.0.1:8501/oauth2callback`

Profile Logout clears Streamlit cookies through
`http://127.0.0.1:8000/api/v1/auth/logout/callback` and returns to the login
gate. Cognito hosted `/logout` is optional; only enable it after adding that
exact callback under Cognito Allowed sign-out URLs (a missing entry shows
Cognito's "Something went wrong" page).

Use the same hostname in `redirect_uri` and any `logout_uri` (their ports differ
locally); `localhost` and `127.0.0.1` are different hosts. Keep
`.streamlit/secrets.toml` uncommitted.

Streamlit 1.60 uses authorization code with PKCE when Cognito advertises it. Its
signed HttpOnly identity cookie lasts 30 days. Streamlit does not retain Cognito
refresh tokens, so Cognito refresh-token rotation does not control that cookie
lifetime.

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

Quick guidance is a lighter advance bar; Complex is stricter. To restore silent
auto-advance:

```bash
AUTO_ADVANCE_STAGES=true
```

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
do not add new behavior there. Cognito sessions use the same typed application
services in process until FastAPI has its own verified authenticated-owner
boundary.

---

## Production Docker deployment (single EC2)

The production-only stack keeps the local launcher unchanged:

```text
Internet :80/:443 -> Caddy
  /api/*           -> app:8000 (FastAPI, prefix preserved)
  everything else  -> app:8501 (Streamlit)
```

FastAPI and Streamlit share one `app` container and are not published to the
host. Only Caddy maps host ports. Caddy obtains and renews HTTPS certificates for
`cde2300chatbot.duckdns.org`; the DuckDNS record must already resolve to the
EC2 Elastic IP, and the EC2 security group must allow inbound TCP 80 and 443.

Before validating or starting the stack:

```bash
cp .env.example .env                         # then set private production values
cp .streamlit/secrets.toml.example .streamlit/secrets.toml
mkdir -p data
chmod 700 data .streamlit
chmod 600 .env .streamlit/secrets.toml
```

The image runs as uid/gid `1000:1000`. On Linux/EC2, make the persistent data
tree and mounted secrets file accessible to that account before startup:

```bash
sudo chown -R 1000:1000 data .streamlit/secrets.toml
test -d data && test -f .streamlit/secrets.toml
```

Compose refuses to create either bind source automatically. This prevents a
missing secrets file from silently becoming a directory and prevents a
root-owned empty data directory from being created during startup.

Set the private Cognito secrets file to use:

- `redirect_uri = "https://cde2300chatbot.duckdns.org/oauth2callback"`
- optional `logout_uri = "https://cde2300chatbot.duckdns.org/api/v1/auth/logout/callback"`

Add those exact URLs to the Cognito app client. Do not put private values in the
image or repository. Compose injects `.env` at runtime and bind-mounts
`.streamlit/secrets.toml` read-only.

Safe configuration/build checks (they do not start model providers):

```bash
docker compose config --quiet
docker compose build
sh -n scripts/start.sh scripts/start_prod.sh scripts/build.sh
.venv/bin/python -m pytest -q
```

On EC2, after securely transferring the private configuration and any existing
`data/` directory:

```bash
docker compose up -d --build
docker compose ps
docker compose logs --tail=100 app caddy
curl -fsS https://cde2300chatbot.duckdns.org/api/v1/health
```

The host `./data` bind mount persists the SQLite database, uploads, synced
course-material copies, and optional generated workspaces across image rebuilds
and container replacement. Back it up before deployment changes:

```bash
tar -czf "co-design-data-$(date +%Y%m%d-%H%M%S).tar.gz" data/
```

Do not run `docker compose down -v` unless removing Caddy's certificate/config
volumes is intentional. `docker compose down` alone does not delete `./data`.

> Security boundary: FastAPI routes currently have no authenticated request
> boundary. Although Cognito-authenticated Streamlit sessions use owner-scoped
> in-process services, `/api/*` is publicly routed as requested. Do not treat
> this deployment as production-safe for sensitive student data until API
> authentication and authorization are implemented in a separate phase.

---

## Tests

```bash
source .venv/bin/activate
python -m pytest -q
PYTHONPYCACHEPREFIX=/private/tmp/co-design-pycache \
  python -m compileall -q backend ui streamlit_app.py
```

---

## Troubleshooting

| Symptom | Likely cause | Fix |
|---|---|---|
| Progress bar never leaves Focus | UI started without API | Use `sh scripts/start.sh` only |
| Coach error about local API | API not up / wrong URL | Check `:8000/api/v1/health`; keep `CO_DESIGN_API_URL=http://127.0.0.1:8000` |
| Provider / OpenAI errors on first run | `.env` set to `openai` without a key | Set `MODEL_PROVIDER=mock` |
| Port already in use | Another process on 8000 or 8501 | Stop the other process, then restart `start.sh` |
| Imports missing | Wrong Python / no venv packages | `source .venv/bin/activate` then `python -m pip install -r requirements.txt` |
