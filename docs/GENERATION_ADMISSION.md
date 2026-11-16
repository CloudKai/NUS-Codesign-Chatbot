# Local generation admission

Ticket 08 / #21 adds opt-in, shared local application allowance enforcement.
It does not promise a complete S$30 bill, actual classroom capacity, or a settled
classroom wait target. Use [COST_ACCOUNTING.md](COST_ACCOUNTING.md) for the complete
monthly inventory and external charges. Funded/classroom release remains blocked
until the operator evidences a conservative ceiling, headroom, real usage,
provider/runtime bounds, shared topology and an acceptable maximum wait.

## Configuration and scope

Set `GENERATION_ADMISSION_POLICY` to an absolute operator-owned JSON file. Missing
configuration preserves existing local/demo behavior **without budget enforcement**.
Invalid configured policy fails startup rather than silently disabling it. Keep the
policy and ledger outside Git. The ledger parent directory must already exist.
All API and in-process UI workers on the same host must use the **same persistent
SQLite file and policy**; no per-owner file or ephemeral container path. Network
filesystems, multiple hosts, DSQL deployment and split ledger paths require a
shared replacement of `GenerationAdmission` before release. No AWS service is added.

Synthetic example only (amounts are integer micro-SGD, 1,000,000 = S$1):

```json
{
  "ledger_path": "/absolute/operator/path/generation.sqlite3",
  "monthly_micro_sgd": 10000000,
  "headroom_micro_sgd": 3000000,
  "call_reserve_micro_sgd": 100000,
  "max_running": 4,
  "max_queued": 16,
  "max_wait_seconds": 10,
  "lease_seconds": 600,
  "ceiling_evidence": "REPLACE: model/region prices, input/output limits, SDK/runtime retries and worst-case calculation"
}
```

These values are invented configuration examples, not recommended funding or price
estimates. The ceiling covers the most expensive allowed model/role, image/cache
charges and **all hidden SDK/model retries inside one metered application call**.
Review existing Fast Chat/Deep Review input/output settings and SDK retry bounds,
including separately published AgentCore runtime settings, against that evidence.
The application reserves again before every visible recovery/RAG fallback call,
Deep Review and completed-stage checkpoint. It never substitutes a cheaper model
or reduces grounding to conceal exhaustion. Existing provider timeout, context,
output, retry and per-notebook/user/RPM guards still apply. A new budget does not
make an arbitrary provider safe or establish an external worst-case price.

The monthly generation allowance is `monthly_micro_sgd - headroom_micro_sgd`.
Headroom is strictly positive and reserved for delayed usage/external charges;
the rest of the complete cost inventory still needs independent verification.
Reservations, pending waits, charges and active/uncertain slots are serialized
with short SQLite `BEGIN IMMEDIATE` transactions. Locks have a two-second timeout;
content/identities/prompts are absent from the ledger and admission events.

## Waiting and reconciliation

Only the winning durable chat execution reaches call admission; same-key replays
and waiters do not spend twice. Chat streams acknowledge dispatch with `started`;
this is **pending**, not saved or a guaranteed model slot. `status/queued` means a
cost reservation and bounded generation wait really exist. `thinking` follows
slot admission; `reply_ready` is unsaved, and `done` acknowledges persistence.
Nonstream requests wait within the same finite policy. Capacity/full queue,
wait expiry, budget and unavailable-ledger rejections have separate categories.
HTTP 429 includes `Retry-After`; streams carry equivalent status/category/retry.
Queue expiry refunds only the uninvoked reservation. Queued retries do not invoke.

Global generation running/queued ceilings apply across owners/processes using
the ledger. FIFO applies among surviving queued calls. Existing notebook/user/RPM
limits can reject earlier. The wait policy is operator configured from zero
(immediate rejection) to 30 seconds per generation queue; this bound is **not a
classroom-approved wait target**. It excludes retrieval, provider execution,
saving and transport. SQLite contention can add bounded lock time.

Background Deep Review/checkpoints also share a process-local cap of 32 retained
jobs (`GENERATION_BACKGROUND_JOBS`, 1–160) and a 30-second worker-queue deadline
(`GENERATION_BACKGROUND_WAIT_SECONDS`, 1–30). Expiry runs independently of browser
polling. Expired work never invokes; its retained-work slot stays occupied until
the executor consumes the wrapper, preventing cancelled-work-item accumulation.
Running jobs retain their slots. Extra processes multiply this *submission* cap;
actual generation still shares the ledger. A background job may wait in the worker
queue and then in generation admission. Failed review envelopes persist the
specific limit category; stage completion and old reviews remain intact.

Successful and failed calls both settle exactly their reservation token once.
Without a complete priced meter, the full conservative ceiling remains charged.
Optional `rates` contains exact `provider`, `model`, `region`, `input`, `output`,
`cache_read`, `cache_write` integer micro-SGD per million tokens and `evidence`.
Only complete input/output/cache meters with known model-call count and zero SDK
retries qualify for a smaller charge, rounded upward to one micro-SGD. Unknown
SDK/model usage is never silently free. Rates must match provider meter token
semantics (OpenAI cached input is disjoint; runtime aggregate input is forwarded).
Observed ceiling overruns remain charged and block all later calls; correct and
reconcile the evidenced policy before any operator intervention. No automatic
allowance reset clears an overrun safety hold.

## Reset, expiry and recovery

Allowance periods are calendar months in UTC, resetting at 00:00 UTC on day one.
No timer, restart, student retry or identity change resets spent allowance. Reads,
source operations and transcript export bypass generation admission. Student
messages explain the UTC reset and lecturer-help path; admission outages/uncertain
slots may require operator attention rather than a monthly reset.

An expired running reservation is **uncertain**, retaining its charge **and slot**.
A timeout/expired lease cannot prove that an external invocation stopped billing.
A late original worker can settle its token; a replacement cannot reclaim it as
free capacity. Dead queued reservations expire without charge on the next ledger
transaction. Admission is bounded; expiry does not kill threads/model processes.

If workers crashed, stop **every** API/UI worker sharing this ledger, preserve the
policy, then explicitly back up and recover orphan slots:

```sh
.venv/bin/python scripts/recover_generation_ledger.py \
  --policy /absolute/operator/policy.json \
  --backup /absolute/operator/new-generation-backup.sqlite3 \
  --confirm-all-workers-stopped
```

The command requires an existing dedicated ledger and an unused backup path. It
uses SQLite backup, releases orphan running/uncertain slots retaining all invoked
charges, and releases/refunds uninvoked waits. It does not clear overrun holds.
Verify external billing separately. Never delete the ledger to recover capacity.
A restore is safe only with all workers stopped and reconciled post-backup usage;
blindly restoring an old ledger can restore already-spent allowance.

No student schema/data migration. Startup creates only the explicitly selected
new sidecar table; it refuses a SQLite file containing unrelated tables. Preserve
this ledger across application rollback/restart. Reverting ticket code disables
this protection, so stop funded generation before rollback. No paid calls or live
price/account evidence were used to validate the implementation.
