# Mock load probe and EC2 monitoring

## Mock capacity probe (no paid providers)

Virtual users are **distinct authenticated owners**. The probe must not treat a
shared `local-student` store as many students.

```bash
.venv/bin/python scripts/load_probe.py --users 10 --requests-per-user 5
.venv/bin/python scripts/load_probe.py --scenario distinct-owners --users 100
.venv/bin/python scripts/load_probe.py --scenario two-notebooks
.venv/bin/python scripts/load_probe.py --scenario same-notebook
```

`--users` is clamped to 1–120. Scenarios:

| Scenario | What it measures | Expected mock result |
|---|---|---|
| `sequential` | Distinct owners, sequential turns per notebook | accepted |
| `distinct-owners` | One concurrent turn per distinct owner | 100 users accepted under global 120 |
| `two-notebooks` | One owner, two notebooks, overlapping turns | both accepted |
| `same-notebook` | One owner, one notebook, overlapping turns | 1 accepted, 1 HTTP 429 |

The probe uses a temporary SQLite store and the mock coach. It never calls
AgentCore or Bedrock. Aggregate metrics only (no notebook IDs, emails, or
message text) are printed: virtual users, accepted, rate-limited, failed,
requests/sec, p50/p95 latency.

Do **not** claim live EC2/AgentCore capacity from this mock probe. Staged live
validation (2 → 5 → 10 → 25 concurrent real students) is a separate gate.

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

1. Run the mock probe locally and record baseline latency/error rates.
2. Deploy an immutable ARM64 image to staging/EC2.
3. Confirm internal `/api/v1/ready` is healthy.
4. Run a small controlled pilot with real Cognito users before opening class-wide
   traffic.
5. Re-check CPU, RAM, container restarts, DSQL, and S3 during the pilot window.
