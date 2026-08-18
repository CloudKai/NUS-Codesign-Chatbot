# Mock load probe and EC2 monitoring

## Mock capacity probe (no paid providers)

Virtual users are **distinct authenticated owners**. The probe must not treat a
shared `local-student` store as many students.

This probe answers whether FastAPI, owner isolation, rate limits, SQLite
persistence, and the Knowledge Base Retrieve pool can hold many simultaneous
requests. It does **not** answer how fast live AgentCore/Haiku is. Do not
interpret mock or fake-sleep latency as model latency. Do not claim live EC2
capacity from these results.

```bash
PYTHONPATH=. .venv/bin/python scripts/load_probe.py --users 10 --requests-per-user 5
PYTHONPATH=. .venv/bin/python scripts/load_probe.py --scenario distinct-owners --users 100
PYTHONPATH=. .venv/bin/python scripts/load_probe.py --scenario two-notebooks
PYTHONPATH=. .venv/bin/python scripts/load_probe.py --scenario same-notebook
PYTHONPATH=. .venv/bin/python scripts/load_probe.py --scenario slow-distinct-owners --users 10
PYTHONPATH=. .venv/bin/python scripts/load_probe.py --scenario kb-pool --kb-workers 4 --users 16 --kb-delay-ms 500
PYTHONPATH=. .venv/bin/python scripts/load_probe.py --run-phase existing
PYTHONPATH=. .venv/bin/python scripts/load_probe.py --run-phase slow --provider-delay-ms 10000
PYTHONPATH=. .venv/bin/python scripts/load_probe.py --run-phase kb
PYTHONPATH=. .venv/bin/python scripts/load_probe.py --run-phase correctness
```

`--users` is clamped to 1–120. Fake provider delay is script-only (patch of
`DeterministicCoachProvider.assess` restored on exit). Fake KB delay injects a
client into the **real** `BedrockKnowledgeBaseRetriever`; only `client.retrieve`
is faked. Production worker count is not changed.

Scenarios:

| Scenario | What it measures | Expected mock result |
|---|---|---|
| `sequential` | Distinct owners, sequential turns per notebook | accepted |
| `distinct-owners` | One concurrent turn per distinct owner | N users accepted under global 120 |
| `two-notebooks` | One owner, two notebooks, overlapping turns | both accepted (`MAX_ACTIVE_COACH_REQUESTS_PER_USER=2`) |
| `same-notebook` | One owner, one notebook, overlapping turns | 1 accepted, 1 HTTP 429 |
| `slow-distinct-owners` | Same as distinct-owners with a fake provider sleep | accepted; P95 ≈ fake delay, not Haiku |
| `kb-pool` | Real Retrieve admission/validation + fake `client.retrieve` | `min(users, workers)` accepted; excess `capacity_exhausted` |
| `kb-timeout-slot` | Fake Retrieve longer than timeout | timed-out calls keep the slot; excess fail closed |
| `kb-fail-closed` | Fake hits from a foreign bucket | zero chunks; no unrelated evidence |
| `slow-idempotency` | Same idempotency key replayed | HTTP 200 twice, one provider call |
| `failed-no-partial` | Fake provider raises | no assistant turn persisted |
| `ownership-isolation` | Distinct owners list threads / read messages | zero ownership violations |

Each printed line is JSON with:

`scenario`, `users`, `fake_provider_delay_ms`, `fake_kb_delay_ms`, `kb_workers`,
`requests`, `accepted`, `rate_limited`, `capacity_exhausted`, `failed`,
`p50_ms`, `p95_ms`, `mean_ms`, `requests_per_sec`, `peak_threads`,
`peak_kb_admitted`, `peak_kb_worker_threads`, `rss_peak_kb`,
`process_max_rss_kb`.

`rss_peak_kb` is kept for compatibility. It is **not** exact per-scenario
incremental memory: both RSS fields are the process-lifetime maximum RSS
from `resource.getrusage(RUSAGE_SELF).ru_maxrss` (a high-water mark).
`process_max_rss_kb` is the same value with a clearer name.

Irrelevant fields are JSON `null`. Aggregate metrics only (no notebook IDs,
emails, or message text).

The probe uses a temporary SQLite store and the mock coach. It never calls
AgentCore, Bedrock models, Knowledge Base, DSQL, S3, or Cognito. CLI bootstrap
and the runtime mutation path both force `APP_ENV=development` and
`COURSE_MATERIAL_SYNC_ENABLED=false` (snapshot/restore includes those
fields even if `backend.settings` was already imported). RPM is raised
to 10_000 so this measures concurrency architecture, not the production
`COACH_REQUESTS_PER_MINUTE=8` cap. That production cap is **per
authenticated user**, not a class-wide 8-RPM ceiling. Ninety distinct
students each sending one request can pass the per-user RPM rule; class
burst ceilings are global concurrency (`MAX_CONCURRENT_MODEL_CALLS`), the
AnyIO thread limiter, AgentCore, and Knowledge Base Retrieve capacity.
`SYNC_THREADPOOL_TOKENS` is set to 120 to match Compose.

Pytest uses tiny delays only. Do not put 5–12 second sleeps on the CI path.

## Resource-envelope approximation (not EC2)

Local Docker with `--cpus=2 --memory=2g` is a **resource-envelope
approximation**. It is not an AWS ARM64 EC2 benchmark. macOS/x86 Docker is not
identical to the production Graviton host.

Do **not** run `compose.prod.yaml` or `scripts/start_prod.sh` for this phase:
those wire AgentCore, DSQL, S3, and Cognito.

Simplest safe method (mock + SQLite inside a constrained container):

```bash
docker run --rm \
  --cpus=2 \
  --memory=2g \
  --memory-swap=2g \
  --pids-limit=512 \
  -e MODEL_PROVIDER=mock \
  -e MOCK_OPENAI=true \
  -e DATABASE_PROVIDER=sqlite \
  -e FILE_STORAGE_PROVIDER=local \
  -e KNOWLEDGE_BASE_ID= \
  -e MAX_CONCURRENT_MODEL_CALLS=120 \
  -e SYNC_THREADPOOL_TOKENS=120 \
  -e PYTHONPATH=/work \
  -v "$PWD":/work \
  -w /work \
  python:3.12-bookworm \
  bash -c 'pip install -q -r requirements.txt && python scripts/load_probe.py --scenario distinct-owners --users 25 && python scripts/load_probe.py --scenario slow-distinct-owners --users 10 --provider-delay-ms 5000 && python scripts/load_probe.py --scenario kb-pool --kb-workers 4 --users 30 --kb-delay-ms 500'
```

If installing `requirements.txt` inside the container is too heavy, run the
same `scripts/load_probe.py` commands on the host with `.venv/bin/python` and
treat Docker as optional confirmation, not as a substitute for a live EC2
pilot.

## What to watch on EC2 during a pilot

| Signal | Why |
|---|---|
| CPU / RAM (`htop`, CloudWatch) | Coach turns and PDF extract are CPU/RAM heavy |
| Disk free on `/` and Docker volumes | Caddy state + container logs; no student data mount |
| `docker compose ps` / restart count | Unexpected restarts under load |
| App container logs | Provider/rate-limit failures (must stay privacy-safe) |
| Aurora DSQL errors | OCC conflicts, permission denials, connectivity |
| S3 4xx/5xx | Upload/preview/delete failures |
| Cognito auth failures | Misconfigured callback or cookie Secure flags |
| `/api/v1/ready` via Docker healthcheck | Dependency readiness without public exposure |

## Suggested pilot sequence

1. Run the mock probe locally (`--run-phase existing`, `--run-phase slow`,
   `--run-phase kb`) and record baseline error rates and peak threads.
2. Optionally repeat a small subset under the 2 CPU / 2 GB Docker envelope.
3. Deploy an immutable ARM64 image to staging/EC2 only after an explicit
   operator decision. This local phase must not deploy or publish AgentCore.
4. Confirm internal `/api/v1/ready` is healthy.
5. Run a small controlled live pilot with real Cognito users before opening
   class-wide traffic: 2 → 5 → 10 → 25 concurrent real students.
6. Re-check CPU, RAM, container restarts, DSQL, S3, AgentCore P95, and KB
   Retrieve during the pilot window.
