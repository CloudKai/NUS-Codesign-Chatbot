# Monthly cost accounting

Ticket 07 / #20 supplies offline operator accounting. It does not retrieve an
account bill, choose infrastructure, or enforce a generation budget (#21).
Use a current complete bill before assessing the S$30/month release gate.
The repository contains no verified account prices or remaining credit balance.

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

## Compatibility and rollout

No schema, data or environment migration is required. Local API and Streamlit
entrypoints remain intact. Runtime token extraction is additive and requires a
future authorized AgentCore asset publication to appear live; old runtimes remain
compatible and their missing usage remains unknown. This ticket does not publish
runtime assets, access billing accounts, run paid calls, push or deploy. Rollback
is the ticket commit alone; persisted notebooks/sources/history are unaffected.
