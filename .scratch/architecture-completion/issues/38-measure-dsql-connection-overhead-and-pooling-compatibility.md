# 38: Measure DSQL connection overhead and pooling compatibility

**What to build:** Produce reproducible connection/SQL/OCC experiments and a supported-adapter decision; adopt bounded pooling only if results justify it and validate shutdown/isolation.

**Blocked by:** 01: Reproduce the baseline and establish coverage.

**Status:** ready-for-agent

- [ ] A disposable benchmark separates fresh IAM/connection setup from SQL/transaction time and compares supported connector/bounded-pool alternatives fairly.
- [ ] Verify current DSQL documentation before adoption and record evidence, limits and a keep/change decision; mock timings are not live DSQL results.
- [ ] If pooling is justified, prove bounded acquisition/size/lifetime, healthy replacement, IAM support, close/context-manager release, rollback/reset, whole-transaction retries, shutdown and cross-owner isolation.
- [ ] No connection spans model inference; worker multiplication is accounted for; live measurements or configuration changes remain separately approved and capped.
- [ ] Use the approved public testing seams and deterministic external adapters; for behavior changes demonstrate one red test then its minimal green implementation per cycle, with no speculative tests or code.
- [ ] Update affected guidance and the authoritative implementation ledger with executed evidence, compatibility/migration/rollback, risks and the next exact action; complete this ticket in one fresh writer session without staging, committing, deploying or paid calls.
