# 48: Measure mixed classroom workloads locally

**What to build:** Run reproducible 1/10/20/40/60/80-user synthetic mixed loads, report latency/error/queue/write metrics and prepare separately capped live procedures.

**Blocked by:** 09: Open an aggregated, verified workspace; 17: Autosave artifacts without losing conflicting drafts; 22: Autosave canvases without overwriting another tab; 36: Handle cancelled and ambiguous Deep Review execution; 39: Measure and bound backend concurrency.

**Status:** ready-for-agent

- [ ] Run finite synthetic 1/10/20/40/60/80-user workloads mixing startup/open/switch, ordinary and grounded coaching, sources, document/graph edits/autosaves and Deep Review.
- [ ] Report throughput, failures/rejections, p50/p90/p95/p99/max, queueing, connection/OCC behavior, tokens and cost only where actually measured, with repetitions/sample/environment limitations.
- [ ] Measure confirmed turn/revision loss and duplicates plus write amplification; local/mock/provider/live application results remain distinct.
- [ ] Prepare a synthetic-account live procedure requiring explicit cost/request/token/concurrency approval; report actual bottlenecks against targets without weakening safety or authority.
- [ ] Use the approved public testing seams and deterministic external adapters; for behavior changes demonstrate one red test then its minimal green implementation per cycle, with no speculative tests or code.
- [ ] Update affected guidance and the authoritative implementation ledger with executed evidence, compatibility/migration/rollback, risks and the next exact action; complete this ticket in one fresh writer session without staging, committing, deploying or paid calls.
