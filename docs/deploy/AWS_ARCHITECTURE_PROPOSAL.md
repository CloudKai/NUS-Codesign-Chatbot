# AWS architecture proposal: one self-healing app tier

Status: proposal with deployable templates. Nothing here has been applied to
an AWS account. Templates live in [`infra/aws/`](../../infra/aws/) and are
deployed by [`scripts/aws/deploy_stack.sh`](../../scripts/aws/deploy_stack.sh),
which is a dry run unless `--apply --confirm-account <id>` is given. The current
manual topology is in [AWS_STATELESS_EC2.md](AWS_STATELESS_EC2.md); this
document changes how that same image is hosted, not what it does.

## Current state (read from the repository)

- CloudFront terminates TLS, forwards to Caddy on one EC2 instance, which
  proxies an allow-list to FastAPI (one Uvicorn worker) and Streamlit.
- State is in Aurora DSQL and S3. The instance holds no student data.
- The instance is created and replaced by hand. Nothing restarts it if it
  fails other than the Docker restart policy, nobody is paged, and there is no
  cost alarm.
- FastAPI sends `Cache-Control: no-store` on every `/pilot/*` file, including
  the content-hashed Vite files in `/pilot/assets/`. Each page load re-fetches
  about 0.5 MB of JavaScript and CSS (`index-*.js` 325 KB, `react-markdown-*.js`
  121 KB, `index-*.css` 54 KB, uncompressed sizes of the current build) from the origin.

## Why not scale out

These three facts decide the design:

1. `backend/rate_limit.py` counters are process-local. A second instance doubles every limit.
2. [GENERATION_ADMISSION.md](../GENERATION_ADMISSION.md) says the budget ledger is one local SQLite file and that multiple hosts need a shared replacement. A second instance splits the budget in two.
3. `compose.prod.yaml` runs a single Uvicorn worker and states the process-local limiter is not sufficient if workers are added.

So the tier stays at one instance and is made self-healing, cheaper and observable.

## Chosen design

Templates: `app-tier.yaml` (region of the app, default `us-west-2`) and
`edge-monitoring.yaml` (`us-east-1`, where CloudFront metrics live).

| Part | What it does |
| --- | --- |
| (a) Auto Scaling group, min=max=desired=1 | Launch template with the existing ARM64 image (`t4g.small` default), Amazon Linux 2023, IMDSv2 required, encrypted 20 GB gp3. The user-data script installs Docker, pins the Compose binary by SHA-256, downloads the deployment bundle (compose file, Caddyfile, `deploy_ecr.sh`), writes `.env` and `.streamlit/secrets.toml` from one Secrets Manager secret, and runs the existing `scripts/deploy_ecr.sh`. A terminated or unhealthy instance is replaced with no manual steps. |
| Stable origin | An Elastic IP is re-attached by the new instance at boot, so the CloudFront origin host name (stack output `OriginDomainName`) does not change on replacement. Security group allows TCP 80 from the CloudFront origin-facing prefix list only. No SSH; use SSM Session Manager. |
| Self-healing on readiness | A one-minute cron job on the host calls `/api/v1/ready` (not exposed publicly), publishes `CoDesign/ReadyOk`, and after five straight failures, past a 15 minute boot grace, marks the instance unhealthy so the group replaces it. EC2 status checks cover host failure. |
| (b) Asset caching | `edge-monitoring.yaml` creates a one-year cache policy and a `Cache-Control: public, max-age=31536000, immutable` response headers policy. Attach both to a new `/pilot/assets/*` behavior on the existing distribution. The minimum TTL overrides the origin's `no-store`, so no application change is needed. Vite file names contain a content hash, so a new build is a new URL. `index.html` and all API routes keep `no-store`. |
| (c) Alarms and dashboard | `ReadyOk` below 1 for 3 of 3 minutes (missing data counts as failing), no in-service instance for 5 minutes, 20 or more `ERROR`/`Traceback` lines in 5 minutes, 30 or more rate-limited coach turns in 5 minutes, CloudFront `5xxErrorRate` above 5% for 2 periods. A dashboard shows CloudFront error rates and requests, `ReadyOk`, coach turns per 5 minutes and error lines. |
| (d) Optional schedule | `ScheduleEnabled=true` scales the group to 0 at `ScheduleStopCron` and to 1 at `ScheduleStartCron` (UTC, defaults 15:00 and 22:00, which is 23:00 to 06:00 Singapore time). Scaling to 0 terminates the instance; the next start rebuilds it in about 3 to 5 minutes (estimate, depends on image pull). Off by default. |
| (e) Budget | An AWS Budgets monthly cost budget with email alerts at 80% actual and 100% forecast. The amount is a parameter (`MonthlyBudgetUsd`). |
| (f) IAM | One instance role, derived from the IAM section of AWS_STATELESS_EC2.md: ECR pull on the one repository; `dsql:DbConnect` on the one cluster; S3 get/put/delete only under `users/*` of the uploads bucket; S3 get only under `course/*` of the course bucket; `bedrock:Retrieve` on the one Knowledge Base (never `RetrieveAndGenerate`); `bedrock-agentcore:InvokeAgentRuntime` on the one runtime; `GetSecretValue` on the one secret; log writes to the one log group; `PutMetricData` limited to namespace `CoDesign`; `SetInstanceHealth` on its own group; `AssociateAddress` on its own Elastic IP. The only `*` resource is `ecr:GetAuthorizationToken`, which AWS does not allow to be scoped. No access keys anywhere. |

The log metrics (`CoachTurnPerfEvents`, `RateLimitedTurns`, `AppErrorLines`)
come from CloudWatch metric filters over the container logs, which the
CloudWatch agent ships from Docker's JSON log files. The filters count the
`coach_turn_perf` event and the `coach_rate_limited` line; they do not extract
latency values, because the line is wrapped in Docker's JSON envelope.

### Operator steps the templates do not do

- Attach the cache and response headers policies to a `/pilot/assets/*`
  behavior of the existing distribution, and point its origin at `OriginDomainName`.
  The distribution is not managed by these templates because it already serves students.
- Put the deployment bundle in a bucket and the `env_file` and
  `streamlit_secrets` fields in a Secrets Manager secret.
- Confirm the email subscriptions that SNS and Budgets send.

## Rejected options

| Option | Reason |
| --- | --- |
| Two instances behind an ALB | Doubles limits and splits the generation budget (facts 1 and 2 above); adds about $16 to $20 per month for the ALB (estimate) for no safe capacity gain. |
| ECS on Fargate | Same single-process limiter and ledger constraints. Fargate costs more per vCPU hour than the same load on one `t4g.small`, and the image already runs under Compose. Revisit with the scale-out gate. |
| AWS App Runner | Scales out by design, so it breaks the limiter and ledger, and it does not run the Caddy plus Streamlit forward-auth arrangement the image relies on. |
| Staying on a hand-made instance | Works, but a failed instance stays down until someone notices. |

## Cost and speed estimates

All figures are estimates, not quotes. Prices are assumed `us-west-2` on-demand
list prices and must be checked against the account's current price list and bill.
This repository holds no verified prices (see [COST_ACCOUNTING.md](../COST_ACCOUNTING.md)).

Inputs: `t4g.small` at about US$0.0168 per hour; 730 hours per month; 20 GB gp3
at about US$0.08 per GB-month; public IPv4 address at US$0.005 per hour; CloudWatch
Logs ingestion at US$0.50 per GB with an assumed 1 GB per month; standard-resolution
alarm at US$0.10 per month with 5 alarms; the first 3 dashboards and the first 2
budgets free; schedule off 7 hours per day.

| Item | Always on | With schedule |
| --- | --- | --- |
| Instance | about $12.3 | about $8.7 (17 of 24 hours) |
| EBS 20 GB | about $1.6 | about $1.6 |
| Public IPv4 (Elastic IP) | about $3.7 | about $3.7 (counted as in use while attached; idle when the group is at 0 is charged at the same rate) |
| Logs, alarms | about $1.0 | about $1.0 |
| Total added or retained by this tier | about $18.6 | about $15.0 |

The IPv4 and instance lines already exist today; the new lines are logs,
alarms and, with the schedule on, a saving of about $3.6. Net new spend is about
$1 to $2 per month; it excludes data transfer, DSQL, S3, Bedrock and AgentCore.

Speed: with the asset policy, the roughly 0.5 MB of hashed files (uncompressed;
less after gzip or Brotli) is served from a CloudFront edge on repeat loads, and
the browser keeps it with `immutable`. This removes those requests from the single
origin instance and its connection to the viewer. Page load gain depends on viewer
distance to the origin region; expect a visible gain for repeat visits and no
change to coach turn time, which is dominated by the model call. Not measured.
Recovery time for a failed instance falls from "until someone notices" to about
10 to 15 minutes (estimate: 5 failed probes, then replacement and image pull).

## Later scale-out gate

Do not raise `MaxSize` above 1 until all of these exist and are tested:

1. A shared rate limiter in Aurora DSQL replacing the process-local counters in `backend/rate_limit.py`.
2. A DSQL-backed `GenerationAdmission` ledger replacing the local SQLite file.
3. A load test (mock provider) showing the shared limiter keeps the stated limits across two instances.
4. An ALB (or equivalent) health check on `/api/v1/ready` and a decision on Streamlit session affinity.

The template asserts the single-instance rule in `tests/test_infra_templates.py`
(`MinSize`, `MaxSize` and `DesiredCapacity` all `"1"`), so a scale-out change
has to update that test deliberately.

## Not covered

No latency percentile alarm. The `coach_turn_perf` line carries `request_total_ms`
but inside Docker's JSON envelope; a percentile alarm needs the app to emit
CloudWatch Embedded Metric Format, which is an application change left to a decision.

## Deploy (dry run first)

```sh
sh scripts/aws/deploy_stack.sh --help
sh scripts/aws/deploy_stack.sh --app-params my-app.txt --edge-params my-edge.txt
# after review, with credentials for the intended account:
sh scripts/aws/deploy_stack.sh --apply --confirm-account <12-digit-id> \
  --app-params my-app.txt --edge-params my-edge.txt
```

Parameter files are `Key=Value` lines (examples: `infra/aws/parameters.*.example.txt`).
Keep them outside Git. The script refuses placeholders, a mismatched account id,
and either confirmation flag on its own.
