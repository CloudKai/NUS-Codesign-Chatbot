# Mock load probe and EC2 monitoring

## Mock capacity probe (no paid providers)

```bash
.venv/bin/python scripts/load_probe.py --users 10 --requests-per-user 5
```

Supported `--users` values: `5`, `10`, `20`, `30`. The probe uses a temporary
SQLite store and the mock coach. Aggregate metrics only (no notebook IDs or
message text) are printed: requests/sec, p50/p95 latency, errors, and HTTP 429
counts.

Do **not** claim `t4g.small` is sufficient until the same workload shape is
measured against the live EC2 stack with the real provider configuration.

## What to watch on EC2 during a pilot

| Signal | Why |
|---|---|
| CPU / RAM (`htop`, CloudWatch) | Coach turns and PDF extract are CPU/RAM heavy |
| Disk free on `/` and Docker volumes | Caddy certs + container logs; no student data mount |
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
