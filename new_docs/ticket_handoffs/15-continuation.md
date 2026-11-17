# Ticket 15 / GitHub #28 — Local SQLite contention continuation

2026-11-17. **Local contention fix validated; overall #28 PARTIAL / OPEN, #29
blocked.** Continues only local15/#28 from HEAD
`2f1963a7f2d06cf17ccbc8d435e690d967002047`, branch
`improvement/Improve-architecture`. Sol sole writer; separate authorized Luna
Standards/Spec reviews read-only. No additional Astra escalation: the inherited
Astra hypothesis was reproduced and the two supported changes succeeded. No UI,
paid calls, push, deployment, external messages, issue comment or closure.

## Authorization, entry and preserved state

Git status inspected first. Read handoffs14/15 in full including final commit,
publication-rejection and **Keep the draft local** decision; EXECUTION/tracker,
root/backend/tests/scripts/docs guides, GLOSSARY/domain pointers, canonical status,
authoritative architecture, student-companion capacity/cost spec and admission,
cost, learning and load/recovery runbooks. Used diagnosing-bugs and TDD skills
with the already approved public HTTP seam; no additional admission test seam.
Read-only live GitHub verification: #28 title/body and OPEN state, native
blockers18/19/21 CLOSED/completed, #27 CLOSED/completed; evidence comments
6894802387/6895154795/6917206881/6947906270 read. #29 still has native #28 blocker.
Initial sandbox network restriction resolved with approved read-only escalation.
No rejected publication was retried; the existing draft remains local.

Fresh preservation snapshot `/private/tmp/ticket28-continuation-baseline/` contains
HEAD/status, real-index binary patch, original canonical status and handoff11–15
bytes. Original staged patch SHA256:
`3822626dc9314c8fef41f80427af7eba322a24a2157543d453c7bddf16bf034a`.
All unrelated staged/untracked/rootAGENTS/user work, duplicate ` 2.py` files,
private `.playwright-cli` artifacts and prior uncommitted publication/decision
appendices must remain unchanged. This separate handoff avoids modifying handoff15.
Canonical working status = original working bytes plus only the new continuation
block; committed status uses HEAD bytes plus only that block.

## Reproduction, supported fix and limits

New `tests/http/test_generation_contention.py` drives the ordinary public HTTP
coach endpoint with deterministic providers and disposable real SQLite/files.
One provider invocation occupies the sole slot. A native SQLite writer-lock
fault makes queued A's next poll time out with actual `SQLITE_BUSY`; A returns
429/category generation_unavailable. The original implementation leaves A's
uninvoked FIFO token behind. After releasing the active invocation, survivor B
fails the two-second completion assertion, well before A's eight-second deadline.
One command reproduced this specific public symptom:

```sh
.venv/bin/python -m pytest -o addopts='' -q tests/http/test_generation_contention.py --tb=short --show-capture=no
# RED: following.result(timeout=2) TimeoutError; 1 failed/6 warnings/9.65s
```

Private red log `/private/tmp/ticket28-contention-red.log`. Initial fault used
BEGIN IMMEDIATE; final boundary fixture uses BEGIN EXCLUSIVE so a poll read or
write can hit the same real native SQLite timeout. That fixture passed against
the cleanup-only implementation before read polling (1 passed/6 warnings/3.82s).
No admission methods are replaced/called; SQL observation only synchronizes the
fault. Behavioral assertions are HTTP: A unavailable/no saved recovery; B prompt
save/exact recovery/replay; a third funded call succeeds and a fourth is budget
rejected, proving the failed uninvoked reserve was refunded without spending
headroom. TestClient exercises the HTTP app in process; the capacity rehearsal
below uses a separate real loopback server process.

Three hypotheses were distinguished: abandoned queued token, lingering failed
transaction/connection, and writer-poll lock pressure. In
`backend/generation_admission.py`:

- Close a new SQLite connection if BEGIN IMMEDIATE fails.
- On acquire SQLite errors, best-effort settle/refund only that token still in
  `queued`, using one further bounded transaction. Preserve its initial queued
  identity even if a later promotion commit fails. If cleanup cannot write,
  finite queue expiry remains the fallback; no running/uncertain refund/reclaim.
- Ineligible waiters use read-only scheduling hints instead of taking the writer
  lock every20ms. Expired queued heads are excluded from hints. Every promotion
  still runs the original serialized expiry, own-state, overrun, running-count
  and FIFO checks. Stale hints may delay a poll; they cannot grant capacity.
- Emit bounded SQLite code/name on acquire failure and a cleanup-unavailable
  outcome, with existing correlation and no private exception text/content.

No deadline, allowance, running/queue ceiling, provider, accounting settlement,
invoked/uncertain quarantine or recovery policy was relaxed. The regression
proves the abandoned-uninvoked-wait mechanism under controlled native busy fault;
it does **not** prove the exact cause of every historical aggregate load error.

## Separate post-fix characterizations

No third unchanged retry of the inherited failure. Each implementation below had
one complete rehearsal. Both use the incumbent script, four running/80 queued,
30-second wait,250-ms deterministic provider delay, short synthetic sources/history,
one worker, authenticated Guest HTTP clients; shared developer host. Regression
suites did not overlap these two load runs. Not rendered browser tabs/Streamlit
WebSockets, deployment-envelope sizing, leak test, real model or live capacity.

1. Queued cleanup/connection fix only:
   `/private/tmp/ticket28-continuation-capacity-cleanup.json` (empty stderr).
   Steps10/20/40 save all; step80 saves78 with2 unavailable; repeat77/3;
   restored77/3; **zero queue expiries**. This supports cleanup's effect while
   explicitly exposing remaining contention. Normal-wave all-admitted==saved.
2. Cleanup plus read polling, including final `reserved_queue` tracking:
   `/private/tmp/ticket28-continuation-capacity-read-poll.json` (empty stderr).
   All310 normal submissions save once, with no unavailable/wait errors.

| Final wave | Saved | Saved completion p50 / p95 ms | Queue p95 ms |
| --- | ---: | ---: | ---: |
| Step10 |10/10|910.32 /1196.56|540.65|
| Step20 |20/20|966.01 /1521.37|1060.78|
| Step40 |40/40|1582.50 /2907.64|2214.99|
| Step80 |80/80|3641.45 /6090.34|5082.16|
| Repeat80 |80/80|3313.32 /5749.39|4736.30|
| Restored80 |80/80|4226.61 /6620.83|5141.70|

Deliberate two-queued overload saves6/rejects74 capacity;50-ms wait saves4/
rejects76 wait. Separate provider failure is admitted503/category unavailable,
unsaved, no recovery/transcript addition, full conservative synthetic charge.
Canonical transcript/recovery/citation/replay assertions pass; all same-key
replays leave ledger unchanged; zero owner-isolation violations. Idle80 clients
held2s,80 concurrent reads complete (hold+reads2.231s), no new reservations.
Server maximum RSS390176KiB,174 sampled threads, sampled running4/queued72.
RSS is process lifetime maximum, CPU cumulative; sampler can miss instant peaks.
These are one run per implementation, not statistical proof or controlled sizing.
The local aggregate report keeps **both** experiments unchanged:
`docs/examples/classroom-capacity/mock-results-2026-11-17-continuation.json`.

Final same-store restart and independent local backup restore snapshot SHA256:
`d5f41b728bed03a94b1000b7dc258a8c3c2a0021f8ebdd8ef7a90a94a5c73bf5`.
Messages, notebook settings/project state/source selection/bytes/export and
ledger match. Original active tree moved away, restored only independent backup
bytes to original paths. Both SQLite backups integrity-checked; all writers
stopped. Snapshot ledger230 reservations/23000 synthetic microSGD/unsettled0;
final397/32100/0. No physical off-host/DSQL/S3 recovery or real-price inference.

## Validation and reviews

Early cleanup HTTP admission/recovery:12 passed/6 warnings/6.43s. Read-poll version:
12 passed/6 warnings/6.33s (before final initial-queue tracking; final checks below
include that change). Focused final120 passed/6 warnings/19.15s:

```sh
.venv/bin/python -m pytest -o addopts='' -q tests/http/test_generation_contention.py tests/http/test_classroom_recovery.py tests/http/test_generation_admission.py tests/http/test_guest_admission.py tests/http/test_reader_conversation.py tests/http/test_reader_project.py tests/http/test_reader_sources.py tests/http/test_reader_workspace.py tests/http/test_confirmed_progression.py tests/http/test_project_resume.py tests/http/test_turn_lifecycle.py tests/http/test_lecture_help.py tests/http/test_upload_lifecycle.py tests/http/test_upload_hardening.py tests/http/test_cost_usage.py tests/domain/test_source_library.py tests/domain/test_primary_path.py tests/test_architecture_contracts.py --tb=short --show-capture=no
.venv/bin/python -m pytest -o addopts='' -q --ignore-glob='* 2.py' --tb=short --show-capture=no
PYTHONPYCACHEPREFIX=/private/tmp/co-design-pycache .venv/bin/python -m compileall -q backend ui streamlit_app.py tests scripts agentcore_runtime
git diff --check
```

Full final canonical suite: **2310 passed,1 skipped,293 warnings/91.33s**.

Focused/full logs `/private/tmp/ticket28-continuation-focused.log` and
`ticket28-continuation-full.log`. Only preserved unmanaged ` 2.py` duplicates
excluded; no canonical test excluded. Full regressions cover citations/source
retrieval, streaming, graph-state resumption, confirmed progression, restart,
owner isolation, provider/recovery and existing-data compatibility. Compileall
passes. No UI/frontend source changed, so no new browser/desktop390/console or
frontend-build certification; no Ruff/static Python typing/CI/image/live claim.

Canonical `scripts/start.sh` mock API+Streamlit startup and same-store restart
both give ready/health/document200 on a fresh disposable root **with the updated
admission policy enabled**. Private launcher/result/log under
`/private/tmp/ticket28-continuation-startup*`. Guest disabled only in canonical
launcher to avoid unrelated8080; capacity runs exercise real Guest entry. All
owned workers stopped;8000/8501/18080 clear, unrelated8080 untouched. Initial
unprivileged capacity command was sandbox-blocked on loopback bind before load;
approved loopback escalation succeeded. The later local-commit approval-review rejection is recorded below; no
rejected action executed or was retried.

Independent read-only Luna Standards and Spec reviews and final code re-reviews
report no concrete findings. No concurrent writer; helpers did not run load/tests.
Spec requested accurate separate intermediate/final results and preserved external
readiness caveats; this handoff/status/runbook supply those. Final Standards and Spec document reviews found no material discrepancy.
The rejected local commit attempt and exact hold are recorded below.

## Compatibility, open gates and next exact action

Changed: admission adapter, one HTTP regression, admission/runbook docs, local
aggregate report, canonical status continuation block and this separate handoff.
No student schema, dependency, auth, UI, entrypoint, provider or data migration.
Existing notebooks/files/chats/sources/learning data were not opened by fixtures.
Rollback only this continuation's code/docs/test; preserve all student data and
ledger, and stop funded generation before removing admission protection. A
revert does not require or authorize resetting or rewriting the ledger.

#28 remains PARTIAL/OPEN; #29 remains blocked. Still missing: lecturer-approved
maximum queue **and total answer wait**; real model/provider/region/runtime/KB
capacity and evidenced worst-case prices; complete current recurring bill/monthly
workload/FX/tax/credit balance-expiry and separately approved positive headroom.
Require evidenced post-credit recurring C plus positive approved H with C+H<=S$30,
or explicit funding/measured-usage/postponement decision. All nine categories are
still explicitly unknown; completeness false, complete gross/credits/cash/post-
credit/generation estimate/runway null. Empty partial usage is not zero spending.
True funded off-host recovery remains unproven. External5–8-student formative
study and two-week pilot pending, **ZERO participant sessions**. All #27 capability
gaps stay disclosed; no default-interface switch, pedagogy/adoption or release claim.

Next exact action: continue **#28 only** at the external evidence/decision gates
in `docs/operations/CLASSROOM_CAPACITY_GATE.md`. Use the recorded final local
rehearsal as engineering evidence, obtain agreed classroom wait and full funded
provider/cost/off-host inputs before any readiness claim. Any live test needs
fresh explicit approval and a request/token/cost cap. No further unchanged local
load retry is required. No issue comment/closure/new #29 task is authorized.
Publication remains **KEEP LOCAL**; do not ask again or retry the old rejected
draft. Any later publication needs fresh explicit payload/destination approval.

## Final preservation and local commit hold

Both final read-only Standards/Spec code reviews found no concrete defect; final
Standards and Spec document reviews also found no material discrepancy. Focused/full/startup/recovery
results above are complete. All original real-index patch and prior handoff11–15
bytes remain unchanged; canonical status preserves every original publication/
user-decision byte plus the new continuation block. Unrelated user work remains.

Attempted bounded action:
`python3 /private/tmp/ticket28-continuation-selective-commit.py > /private/tmp/ticket28-continuation-commit.log 2>&1`.
**Automatic approval review rejected before execution; no commit created.**
Stated reason: “The local commit is bounded and carefully preserves existing staged work, but the trusted AGENTS.md explicitly prohibits committing without clear user authorization, and the user only authorized continuation—not this exact commit.”
Risk: creating a Git commit without the exact trusted authorization required by
the review. No alternate tool/route, indirect execution or retry. Exact rejection
record `/private/tmp/ticket28-continuation-commit-rejection.json`. HEAD remains
`2f1963a7f2d06cf17ccbc8d435e690d967002047`; original staged patch SHA256 unchanged.
All seven continuation paths remain **uncommitted/unstaged**; original user staging
is preserved. Fresh selective script remains saved, unexecuted, for review only.

Required next approval is **only** the seven-path local commit named
“Fix abandoned generation waiters and reduce SQLite poll contention”: admission
adapter, HTTP contention regression, admission/gate docs, aggregate continuation
report, canonical status (HEAD bytes plus only continuation block), and this
separate handoff. No push, publication, closure, deployment or #29 work. The earlier
KEEP LOCAL publication decision still applies independently and is not reopened.
After exact commit approval, recheck snapshots and prepare the final reviewed
script/payload before execution; do not blindly rerun a prior-ticket script.
External readiness gates still remain after any local commit.
