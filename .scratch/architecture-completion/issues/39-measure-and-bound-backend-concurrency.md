# 39: Measure and bound backend concurrency

**What to build:** Exercise representative blocking paths, identify event-loop/thread bottlenecks and apply only demonstrated bounded improvements without weakening admission or cancellation.

**Blocked by:** 37: Trace a coaching request without recording private content.

**Status:** ready-for-agent

- [ ] A representative disposable workload isolates blocking database/SDK/retrieval/document/serialization work and records event-loop/thread/queue behavior.
- [ ] Only measured bottlenecks receive bounded offloading, independent parallelism, client reuse or supported async changes; no mechanical async rewrite.
- [ ] Existing owner isolation, admission, cancellation, deadlines, finite tasks and safe shutdown remain correct under overload and failure.
- [ ] Use the approved public testing seams and deterministic external adapters; for behavior changes demonstrate one red test then its minimal green implementation per cycle, with no speculative tests or code.
- [ ] Update affected guidance and the authoritative implementation ledger with executed evidence, compatibility/migration/rollback, risks and the next exact action; complete this ticket in one fresh writer session without staging, committing, deploying or paid calls.
