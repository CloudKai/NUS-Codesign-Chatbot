# Monthly cost accounting

Ticket 07 / #20 supplies offline operator accounting. It does not retrieve an
account bill, choose infrastructure, or enforce a generation budget (#21).
Use a current complete bill before assessing the S$30/month release gate.
The repository contains no verified account prices or remaining credit balance.

Ticket15's [cash-funded gate record](operations/CLASSROOM_CAPACITY_GATE.md)
inventories the recurring categories with explicit unknowns, requires positive
approved headroom and records the pending funding/usage decision. It establishes
no S$30 pass; its empty partial usage input is not zero actual monthly usage.

Run from the repository root:

```sh
.venv/bin/python -m scripts.cost_report \
  --inventory docs/examples/cost-accounting/synthetic-inventory.json \
  --events docs/examples/cost-accounting/synthetic-usage.jsonl
```

This synthetic example has S$35.20 gross recurring cost, S$30.20 credits,
S$5.00 cash charges, S$35.20 monthly cost after credits, and two months of credit
runway. Four generation attempts (including one failed attempt, one recovery,
and a Deep Review) have a separate S$4.20 token estimate. It is already represented
in the example's generation inventory line and is never added twice. These are
invented arithmetic fixtures, not quotations, account evidence or affordability
results. The `unknown-inventory.json` example produces null totals and runway.

## Collect usage

The configured operational stream emits JSON `generation_usage` and
`operation_usage` events under `co_design.usage`. Export only those complete JSON
objects, one per line, as the CLI's `--events` file. Log-prefix text, mixed event
types and private bodies are deliberately not accepted by the CLI. Keep exports
private and apply the deployment's approved log retention and access policy.
No new database, retention daemon or student-visible endpoint is introduced.

Each generation event records a random event/operation id, UTC time, operation
kind, provider/model/region/role, outcome and nullable input/output/cache meters,
model-call count and SDK retry count. The operation event records completion,
application-visible generation attempts, replay and a saved-answer indicator.
Only a persisted, nonempty chat answer is `answer_delivered`; this does not prove
the browser received it or the student found it useful. Deep Review and stage
checkpoints never inflate this answer count. Idempotent replay produces no new
generation and no new saved answer. Application RAG fallback and runtime recovery
produce distinct generation events. Student text, prompts, excerpts, source ids,
raw notebook/owner ids, credentials and exception text are excluded.

`session_key` is a hash of a high-entropy notebook UUID and UTC date. It links
operations only within one notebook/day, for a clearly labelled session proxy;
it is neither a person count nor measured browser/learning session duration.
Useful-answer count is null until an operator provides an independently assessed
count and evidence for that export. Saved answers alone never establish usefulness.

AgentCore events cover each outer Runtime invocation, including failed envelopes
and retries. New runtime assets forward available accumulated model input/output
usage across returned Strands cycles, including returned results rejected during
validation. Missing result usage, SDK retries, internal model retries and cache
meters stay unknown. Model call counts are not guessed from event-loop cycles.
Runtime provenance overrides configured model/region when supplied. Application
failure does not erase its earlier generation cost. OpenAI input tokens subtract
supplied cache reads so pricing classes are disjoint. Bedrock uses its supplied
Converse meters. Unknown adapters get a logical assessment event with unknown
usage. Mock meters are explicitly zero, including model/SDK calls.

Logs are not an exactly-once durable invoice: process death, rotation, SDK retry
responses and incomplete exports can leave gaps. Reconcile against separately
authorized billing evidence; missing meters are not free calls. Hidden retry
coverage prevents a complete generation estimate. Duplicate event ids with the
same payload are deduplicated; conflicting duplicates fail. Missing attempt or
operation events are reported and suppress complete usage/unit-cost claims.
The optional legacy `BedrockCoachProvider.assess_stream` test seam is not the
student generation path; it does not supply this new accounting event. Production
student streaming continues to meter the ordinary assessment before NDJSON reply.

## Supply a complete SGD inventory

Copy the unknown example into a private operator location. Supply the target UTC
month, evidence as-of date, and one or more charge lines for every category:

| Category | Inventory items to check |
| --- | --- |
| hosting | EC2/runtime compute, EBS, load-balancing or other host charges |
| generation | Model inference, AgentCore runtime and guardrails; include failures/retries/Deep Review/checkpoints |
| retrieval | Knowledge Base queries, vector/index/database capacity and requests |
| ingestion | Parsing, embeddings, reindexing, ingestion jobs; amortize recurring ingestion explicitly |
| storage | S3 objects, derived files, DSQL capacity/requests, storage API requests |
| backups | Snapshots, backup storage, retention, restore testing allocations |
| observability | Logs, metrics, traces, alarms and retention |
| network | CDN/CloudFront, egress, NAT, transfer and request charges |
| other | DNS/domain amortization, certificates if charged, support, taxes and other recurring costs |

Each line requires `name`, `category`, `basis` and `evidence`; gross and applied
credits are nullable SGD decimals. `basis` is actual, estimate, unknown or
not_applicable. Not-applicable lines require explicit zero amounts and a reason.
Cover every service and applicable taxes once, with consistent monthly allocation;
category presence alone does not prove completeness. Set `inventory_complete`
only after checking the complete billing/service inventory. Missing categories,
unknown gross or unknown credits prevent the corresponding complete total.
Known subtotals remain visible and must not be presented as a complete bill.

Convert foreign-currency charges to SGD before input. Record the original currency,
amount, conversion rate/date/source and tax treatment in `evidence`; rates are
never fetched or silently invented. Credit offsets cannot exceed their line's
gross charge. `credit_eligible` describes the recurring burn eligible for the
specified balance, independently of that month's actual applied credits.

For token estimates, supply per-million SGD rates keyed by provider, exact model
and region, with dated evidence. Input, output, cache-read and cache-write rates
must use disjoint classes and the same pricing/version, region, tax and FX basis.
The estimate is separate from gross inventory charges and never fills unknown
invoice lines automatically. It is a known subtotal if any attempt is unpriced
or retry/usage coverage is unavailable. Set `usage_complete` only for a complete
month's export; an empty partial log is not proof of zero usage.

Credit runway requires the remaining SGD balance with evidence, its expiry,
and a complete monthly eligible gross burn. It assumes constant future usage
and is capped by expiry (30.4375 days/month). Unknown eligibility/balance/expiry
keeps runway null. Model restricted balances as separate inventories with matching
eligible charges; a pooled balance cannot represent incompatible service-specific
credits. A zero eligible burn leaves runway unavailable rather than claiming
infinite funding. Gross monthly cost remains the baseline after credits end.

## Scenario planning and regional trade-offs (ticket 49)

Ticket 49 adds a reproducible, offline planning renderer beside the ticket-07
accounting port. It reads one explicit configuration (dated public-pricing
estimates, measured local anchors, regional trade-off notes) and reports
low/expected/high monthly SGD scenarios using the same inventory semantics:

```sh
.venv/bin/python -m scripts.cost_scenarios \
  --config docs/examples/cost-scenarios/scenarios-2026-11.json
```

The offline configuration records the checked regional Aurora DSQL list prices
from the AWS price lists published 2026-09-11 and retrieved 2026-11-26. In Oregon,
database activity costs US$8 per million Distributed Processing Units (DPUs).
DPUs cover compute, reads and writes, including failed work. An idle cluster
accrues zero activity DPUs. Primary storage costs US$0.33 per GB-month for one
logical copy in the Region. The estimate uses list prices before the account-wide
free tier of 100,000 DPUs and 1 GB-month, whose available balance is unknown.
The estimated storage quantities of 2, 5 and 15 GB-month cover retained primary
data, indexes and revision history. The separate backups line assumes S3 copies.
Add a separate inventory line if AWS Backup for DSQL is enabled.
[Oregon price list](https://pricing.us-east-1.amazonaws.com/offers/v1.0/aws/AuroraDSQL/current/us-west-2/index.json) ·
[AWS billing mechanics](https://aws.amazon.com/rds/aurora/dsql/pricing/)

The mock operation counts, SQLite growth and simulated connection latency cannot
establish monthly DPU consumption. All three scenarios therefore leave the DSQL
activity cost and full gross unknown. The priced subtotals use dated rate and
quantity assumptions for the other lines and exclude GST and credits.

| Scenario | Students | Priced subtotal (SGD) | Full gross |
| --- | ---: | ---: | --- |
| low | 6 | 30.904250 | Unknown |
| expected | 24 | 82.885400 | Unknown |
| high | 80 | 261.089400 | Unknown |

The renderer reports the S$30 gate as `unresolved`. Collect the account's
monthly DPU usage and storage from billing or cluster metrics for a
representative workload, reconcile the rest of the inventory, and check
`C + H <= S$30` using the verified post-credit baseline C and a separately
approved positive headroom H. Hosted editor and canvas service costs are zero
because React Flow and Tiptap run client-side.
[Classroom capacity gate](operations/CLASSROOM_CAPACITY_GATE.md)

Measured local evidence is carried as labelled anchors and never as live cost
truth: ticket 48's write-volume proxy (store growth 233,472 → 3,420,160 bytes
across the 80-student run), autosave p95s (≤39.5 ms artifact / ≤27.3 ms
canvas), ticket 38's fresh-connection simulation (~31 ms/transaction with 25 ms
synthetic connect), ticket 39's bounded admission overload, ticket 40's
measured prompt sizes (system prompt p50 ≈7,719 estimator tokens; one recorded
live smoke at 6,366 real input tokens), and the separately capped 2026-11-24
live checks (US$0.9800952 cumulative reservations, ≈US$0.0123 per direct Gemma
request — a different model from the deployed Haiku 4.5).

Regional trade-offs are documentation-based rows, with no live regional call
made: the documented deployment is **us-west-2** (compose.prod.yaml and
AWS_STATELESS_EC2.md) while students are in Singapore, so dynamic requests pay
an estimated ~170–200 ms long-haul round trip (estimate; CloudFront edges only
cover static assets). The app-to-DSQL hop in Oregon and Singapore-origin
latencies for DSQL, model, AgentCore, KB and Cognito are unmeasured. AWS lists
Aurora DSQL in Singapore at US$9 per million DPUs and US$0.40 per GB-month.
Haiku 4.5 availability there remains unverified for this deployment. Any
change to processing or storage residency requires a separate operator
decision and measurements.
[AWS DSQL region availability](https://docs.aws.amazon.com/aurora-dsql/latest/userguide/what-is-aurora-dsql.html) ·
[Singapore price list](https://pricing.us-east-1.amazonaws.com/offers/v1.0/aws/AuroraDSQL/current/ap-southeast-1/index.json)

The only recorded live-shaped datapoints remain the bounded
2026-11-24 checks (direct Gemma p50 3.442 s / p95 32.319 s; workspace reads
through CloudFront/FastAPI/DSQL p95 6.506 s), which justify re-measurement,
not movement.

The report leaves `credits_sgd` and `cash_sgd` null because there is no verified
credit balance or expiry. It lists missing cost lines in `unknowns` and exposes
`priced_subtotal_sgd` alongside the nullable `estimated_gross_sgd`. The full
gross, once complete, is the baseline after credits end. Use the
[`cost_report` path](#monthly-cost-accounting) for billing evidence. Invalid
configurations exit 2 without echoing content.

## Compatibility and rollout

No schema, data or environment migration is required. Local API and Streamlit
entrypoints remain intact. Runtime token extraction is additive and requires a
future authorized AgentCore asset publication to appear live; old runtimes remain
compatible and their missing usage remains unknown. This ticket does not publish
runtime assets, access billing accounts, run paid calls, push or deploy. Rollback
is the ticket commit alone; persisted notebooks/sources/history are unaffected.
