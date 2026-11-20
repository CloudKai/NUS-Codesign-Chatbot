# Co-design Student Chatbot

A critical-thinking coach for university students. Ask questions about course
readings, develop a design project, and revisit your reasoning in Review.
Students use React. Lecturers and accounts with Enabled Access use the
protected Streamlit workspace. FastAPI handles both.

[Documentation](docs/README.md) · [Current status](docs/IMPLEMENTATION_STATUS.md) · [AWS deployment](docs/deploy/AWS_STATELESS_EC2.md)

## Run locally

Use Python 3.12, Node 22, Caddy, and a POSIX shell. From the repository root:

```sh
python3.12 -m venv .venv
.venv/bin/python -m pip install -r requirements-dev.txt
test -f .env || cp .env.example .env
npm ci --ignore-scripts --prefix frontend
npm run build --prefix frontend
GUEST_ACCESS_ENABLED=true MODEL_PROVIDER=mock sh scripts/start.sh
```

Open the [student workspace](http://127.0.0.1:8080/). The mock provider needs
no model key and saves local work under `data/` by default. Use `Ctrl+C` to
stop the stack. Run the last command again to restart and rebuild React after
frontend edits.

If port 8080 is occupied, build React once and use the alternate local launcher:

```sh
npm run build --prefix frontend
sh scripts/start_local_8081.sh
```

Open `http://127.0.0.1:8081/` and press `Ctrl+C` to stop the app.

| Local service | Address |
| --- | --- |
| Student workspace | [127.0.0.1:8080](http://127.0.0.1:8080/) |
| Protected Streamlit workspace | [127.0.0.1:8080/streamlit/](http://127.0.0.1:8080/streamlit/) |
| FastAPI readiness | [127.0.0.1:8000/api/v1/ready](http://127.0.0.1:8000/api/v1/ready) |

### Use registered sign-in

Copy `.streamlit/secrets.toml.example` to `.streamlit/secrets.toml` if you need
a new local template. Configure the private Cognito app-client values.
Enable the authorization-code grant and the `openid email profile` scopes,
and allow the callback `http://127.0.0.1:8000/api/v1/auth/callback`.
Use `127.0.0.1` consistently for the browser and callback so the cookies share
a host. Keep both local config files private.

For an ordinary account that needs the protected Streamlit workspace, add
its verified Cognito subject to `STREAMLIT_ACCESS_COGNITO_SUBS` and restart.
Lecturer tools require a persisted staff role. See the
[security boundaries](docs/SECURITY_BOUNDARIES.md) for permissions and guest
transfer behavior.

### Use local Docker Compose

With Docker running, ensure `.env` and `.streamlit/secrets.toml` exist.
The container reads the secrets file and writes to `data/` as UID 1000.
Use `docker compose up --build` for the local stack. Production uses
`compose.prod.yaml` and Aurora DSQL with S3.
[Production configuration and release instructions](docs/deploy/AWS_STATELESS_EC2.md)

## Find your way around

| Path | Purpose |
| --- | --- |
| `frontend/` | React student workspace |
| `backend/` | FastAPI, the coaching workflow, retrieval, and persistence |
| `ui/` and `streamlit_app.py` | Protected Streamlit workspace |
| `agentcore_runtime/` | Production coaching runtime and its prompts |
| `scripts/` and `tests/` | Local startup, operator tools, and regression tests |
| `docs/` | Architecture, operations, and contributor guides |

The five Thinking Path stages are Problem identification, Concept generation,
Design specification, Ethics & Critical Thinking, and Reflection. A student
confirms a stage recommendation before advancing. Research coding is
provisional and separate from grading.
[Workflow architecture](docs/LOCAL_DEMO_IMPLEMENTATION.md#educational-workflow) · [Learning and research](docs/LEARNING_BASELINE.md)

## Validate a change

```sh
sh scripts/build.sh
```

The build script builds React, compiles Python, and runs the deterministic test suite.
See the [testing guide](docs/TESTING.md) for focused tests and browser checks,
or the [React guide](frontend/README.md) for frontend development.

If startup fails, open the readiness URL and check the startup output.
Use an installed Caddy, a built `frontend/dist/`, and free ports 8000,
8080, and 8501. For local demos, use `MODEL_PROVIDER=mock`.
