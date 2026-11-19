# Classroom capacity and cash-funded release gate

Ticket local15 / GitHub #28. Local mock characterization is separate from a
classroom-readiness decision. **Live readiness and the S$30 plan are unresolved.**
No hosting, storage, model or default-interface migration is authorized here.

For the current post-promotion hosting/OpenAI shortlist, remaining owner decisions,
off-host rehearsal steps and study scheduling materials, use the
[readiness decision sheet](CLASSROOM_READINESS_DECISIONS.md). It records research
and preparation only; all external release gates remain open.

## Repeat the disposable local rehearsal

```sh
.venv/bin/python -m scripts.classroom_probe > /private/tmp/classroom-capacity.json
```

The driver starts a separate single-worker FastAPI process on an ephemeral
loopback port. Before importing the backend, the child pins mock generation,
SQLite/local files, empty paid-provider/KB configuration and new temporary paths.
It never opens the developer database. Each virtual participant has a real,
independently validated Guest cookie, one notebook and selected synthetic analogy
notes uploaded through HTTP. The same canonical reader stream, source retrieval,
idempotency, saved-turn recovery and admission services serve the requests.

The sequence grows to 10, 20, 40 and 80 persistent authenticated HTTP clients,
submits a barrier-released wave at each step, holds all 80 idle for two seconds,
reads them concurrently and submits another 80-request wave. Saved transcripts
grow across waves. Fixtures are short synthetic text, not measured production
corpus distributions or long student histories. These are keepalive HTTP sessions,
not 80 browser tabs, rendered React clients or Streamlit WebSocket sessions.

The initial **synthetic** policy has four running slots, 80 queued slots and a
30-second generation queue deadline. Its allowance/reservation numbers are fake
accounting fixtures, never a funding decision or suggested classroom configuration.
Separate fresh-worker runs exercise two queued slots with a one-second mock
provider delay, then 80 queued slots with a 50-ms deadline. The initial delay is
250 ms and configurable from 50 ms to two seconds. One explicit provider failure
must return a terminal error without creating a recoverable/saved answer.

For every wave, HTTP observations check that each `done` exactly matches the
saved recovery result, its citation belongs to that session's selected source,
and the transcript contains exactly the expected number of rows. Exact-key
replays must return the same turn without adding rows or changing aggregate
ledger charges. `started` is dispatch acknowledgement, **not acceptance**;
`thinking` marks admission and `done` marks durable completion. Failed/rejected
keys must have no saved recovery result. Compare admitted and completed counts;
do not count a truthful admission rejection as a lost accepted turn. All owner
lists must contain only their notebook; cross-owner message reads must return404.

Metrics have deliberately limited meanings:

- Waits are client-observed dispatch-to-thinking and queued-to-thinking. For
  rejected work, the queue observation ends after the explicit no-saved-answer
  recovery GET following the terminal error, so it includes that extra read.
  These include stream/transport scheduling; they are not precise internal queue
  timers. Completion includes dispatch through terminal stream receipt. Report
  saved completions separately from all outcomes. Nearest-rank p50/p95/max.
- The server sampler records Python thread and ledger occupancy peaks every20ms.
  Sampling can miss shorter peaks. Threads include framework/executor/sampler
  work; they are not model invocations. The four-slot policy bounds invocations.
- RSS is the **server process lifetime high-water mark**, in KiB, excluding the
  separate driver. It is cumulative across waves until a worker restarts, not
  incremental memory or a leak test. CPU seconds are cumulative user+system time.
  This shared developer machine is not a controlled EC2/container envelope.
- Errors remain categorized (`generation_capacity`, `generation_wait`,
  `generation_unavailable`, provider failure). Exceptions/incomplete streams
  abort the rehearsal; a successful script exit alone is not a capacity pass.

The output always says `live_ready: false`. Inspect actual outcomes and risks in
[handoff15](https://github.com/CloudKai/NUS-Codesign-Chatbot/blob/948162e1eba9d0de3fbda7cbfce1d00731001158/new_docs/ticket_handoffs/15.md); do not infer 80-provider capacity
from 80 sessions, fake delays, a configured ceiling, or passing mock tests.

## Independent backup and restart rehearsal

The script stops its API worker, restarts the same stores, and compares exact
canonical HTTP snapshots of messages, settings, project state, source selection,
source bytes and transcript exports. It also checks the generation ledger totals.
With all writers stopped it uses SQLite backup for both student and admission
databases and copies the file/workspace/lecture trees and policy into a separate
backup directory. It moves the original active tree away, restores **only backup
bytes** to the original paths, launches a fresh worker and repeats the comparisons
and a submission wave. Existing absolute local attachment paths therefore remain
valid without a schema/path migration. This exercises independent backup contents
on one local machine; no separate host, remote vault or physical disk-loss test.

Operational release requires a separately funded, access-controlled off-host
backup for every durable component, defined retention/RPO/RTO and a rehearsed
restore under the real SQLite/files or DSQL/S3 topology. Do not copy a live SQLite
file without its WAL; use its backup API. Stop **all** writers for coordinated
file/DB snapshots. Verify source bytes and permissions after restore. Preserve
encryption/key access, Guest/auth records and policy/ledger with the student data.
Never reset the admission ledger during rollback. A stale ledger backup can
re-enable already-spent funding: keep generation disabled until post-backup usage
and external charges are reconciled. Orphan/uncertain slots require the stopped-
worker, new-backup procedure in [GENERATION_ADMISSION.md](../GENERATION_ADMISSION.md).
This ticket does not automatically recover or waive uncertain charges.

## Complete recurring cost and decision record

As of 2026-11-17, no complete current bill, measured monthly workload, priced
worst-case provider ceiling, credit balance/expiry or approved headroom is supplied.
The [explicit unknown inventory](../examples/classroom-capacity/cost-inventory-2026-11.json)
covers hosting, generation, retrieval, ingestion, primary storage, backups,
observability, network and other charges (identity, DNS/domain, support, FX/taxes).
Each line lists services to reconcile, including failures/retries, Deep Review,
checkpoints, backup operations and retention. Presence of all categories is not
an attestation that all active account services have been discovered.

Run the existing accounting port without inventing a complete usage export:

```sh
: > /private/tmp/classroom-empty-partial-usage.jsonl
.venv/bin/python -m scripts.cost_report \
  --inventory docs/examples/classroom-capacity/cost-inventory-2026-11.json \
  --events /private/tmp/classroom-empty-partial-usage.jsonl
```

Both coverage attestations remain false. Complete gross, credits, cash,
post-credit baseline, generation estimate and credit runway are **null**. Empty
partial usage and known-subtotal0 mean no evidence, not free operation. Mock
admission charges are not included as real SGD expenses. Do not double-count
generation estimates already represented by an inventory line.

Decision **pending operator/lecturer approval**: retain the existing deployment
and make no new cash-funded classroom rollout claim. To keep S$30, supply an
evidenced conservative monthly **post-credit** recurring total C and a separately
approved positive headroom H, with `C + H <= S$30`. Do not deduct temporary
credits when testing sustainability. Headroom is additional unallocated margin;
do not count the same contingency twice in C and H. Reconcile application
generation allowance with fixed/external costs and the full bill. Record credit
offsets, current cash payable, restricted eligible balance and expiry/runway
separately using [COST_ACCOUNTING.md](../COST_ACCOUNTING.md).

If C is infeasible or unknown, the operator must choose and evidence one of:
increase recurring funding, approve bounded usage/access hours/turn allowance
supported by measured costs, or postpone cash-funded classroom availability.
Any provider/storage/hosting change is a separately scoped decision. No amount,
usage quota, sponsor funding or feasibility approval is invented by this record.

## Gates still requiring evidence

1. Lecturer-approved maximum queue wait **and** maximum total answer wait,
   measured from stated boundaries; document rejection/retry/help expectations.
   A 30-second limiter setting is not the agreed target.
2. Real provider/model/region/runtime quotas, requests/tokens per minute, allowed
   context/output/retries, KB capacity, shared topology and current worst-case
   call-price evidence. New live tests require explicit request/token or cost
   cap approval. No prior approval carries forward.
3. Repeated load under the intended deployment resource envelope and expected
   corpus/history/upload volumes, including actual client connection type.
   Investigate any local `generation_unavailable`/contention or quarantine before
   a successful classroom claim; bounded rejections are not capacity proof.
4. Complete billed recurring inventory, measured usage, cash/post-credit totals,
   credit runway and approved positive headroom/funding decision; off-host restore.
5. External 5–8-student formative study and two-week pilot remain pending,
   **ZERO participant sessions**. Engineering tests establish no learning gain,
   retention, pedagogy quality or adoption. Remaining React/Streamlit capability
   gaps in handoff14 remain; no default-interface switch.

Leave #28 open while required decisions/evidence are missing. Do not start #29
past its native #28 blocker. The next action is to resolve the recorded evidence
gates, then rerun the same characterization with approved inputs in a fresh
#28 session; any live test still needs fresh capped approval.

## Initial observed local capacity limit

[Measured aggregate results](../examples/classroom-capacity/mock-results-2026-11-17.json)
record the second full run. Steps10/20/40 saved all submissions. Step80 saved48,
with29 wait expiries and3 admission-unavailable outcomes; repeated80 saved48,
with30/2 respectively; restored80 saved22, with50/8. Every normal-wave
`thinking` admission matched a saved completion; transcript, recovery, citation
and replay assertions passed. The deliberate provider failure is separately
admitted but unsaved, terminal503, with no saved recovery result. The first full
run independently showed the same wait/unavailable pattern. Neither is an
acceptable-wait or 80/80 completion result.

After the repository's two-attempt limit, read-only Astra diagnosis identified
a plausible mechanism in `backend/generation_admission.py`: queued callers poll
with serialized `BEGIN IMMEDIATE` transactions; an SQLite error can exit a caller
without retiring its already-inserted **uninvoked** queued token. Later FIFO
callers can remain behind that abandoned head until expiry. The connection helper
also lacks explicit close when beginning a transaction fails. These are supported
code findings, **not a proven causal reproduction**: exact SQLite error codes and
idle-slot time were not captured, and sampler overhead can perturb contention.
No production admission change or third attempt at the same80 load was made.

The next-action diagnosis above was completed by the local continuation below.
Historical results remain unchanged.

## Local contention continuation (2026-11-17)

The public HTTP regression `tests/http/test_generation_contention.py` forces a
real native SQLite busy timeout on queued A while one deterministic invocation
is held. Before the fix, A returns429/unavailable and B cannot complete within
two seconds of the running call completing, despite capacity being free. After
the fix, B saves/recovers/replays promptly, A has no saved answer, and public
budget checks show only the uninvoked reservation was refunded. The final fault
fixture uses an exclusive SQLite transaction so either a poll read or write can
hit the same native timeout; it never substitutes admission methods.

Failed acquires now best-effort retire only their own still-queued reservation;
failed BEGIN connections close. This alone saved78/77/77 of the three80-request
waves with2/3/3 admission-unavailable outcomes and no queue expiries. Ineligible
waiters now use read-only scheduling hints, while promotion still rechecks all
original expiry, FIFO and capacity conditions under BEGIN IMMEDIATE. No queue
deadline, allowance, running/queued ceiling or uncertain-invocation protection
was relaxed. The controlled test proves the abandoned-wait mechanism; it does
not establish the exact cause of every earlier aggregate load failure.

The final rehearsal (same250-ms mock delay/four running/80 queued/30-second wait)
completed310/310 normal submissions, with no admission errors or queue expiries:

| Wave | Saved | Saved completion p50 / p95 ms | Observed queue p95 ms |
| --- | ---: | ---: | ---: |
| Step10 |10/10|910.32 /1196.56|540.65|
| Step20 |20/20|966.01 /1521.37|1060.78|
| Step40 |40/40|1582.50 /2907.64|2214.99|
| Step80 |80/80|3641.45 /6090.34|5082.16|
| Repeat80 |80/80|3313.32 /5749.39|4736.30|
| Restored80 |80/80|4226.61 /6620.83|5141.70|

Separate overload still saves6/rejects74 capacity; short-wait saves4/rejects76
wait. The admitted deliberate provider503 remains unsaved and conservatively
charged. All canonical transcript/citation/recovery/replay checks pass; replays
leave the ledger unchanged and owner isolation checks pass. Idle80-session reads
complete with no reservations. Server maximum RSS390176KiB/174 sampled threads;
maximum sampled running4/queued72. Same-store restart and independent local
restore match, with final397 reservations/32100 synthetic microSGD/unsettled0.
Both runs are retained in the [local aggregate report](../examples/classroom-capacity/mock-results-2026-11-17-continuation.json).

Each implementation has one characterization here; results on a shared developer
host are not statistical or production-capacity evidence. No regression suite
overlapped these runs. These are authenticated HTTP clients, not rendered browser
tabs or Streamlit WebSockets. No true off-host recovery, paid/model/region/KB
capacity, approved classroom wait, complete cost/headroom or student-study claim.
#28 remains OPEN/#29 blocked. All funding and external gates above still apply.
See [continuation handoff](https://github.com/CloudKai/NUS-Codesign-Chatbot/blob/948162e1eba9d0de3fbda7cbfce1d00731001158/new_docs/ticket_handoffs/15-continuation.md) for
validation, compatibility, local-only Git and the next exact action.
