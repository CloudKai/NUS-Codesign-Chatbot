# 35: Resume queued Deep Review safely after restart

**What to build:** Implement a bounded persistence-backed lease worker and demonstrate one review surviving restart, with idempotent result persistence and stale-project fencing.

**Blocked by:** 01: Reproduce the baseline and establish coverage.

**Status:** ready-for-agent

- [ ] Starting Deep Review persists owner/project/input revision, idempotency, state, attempts, lease owner/expiry/heartbeat and result/failure metadata.
- [ ] A bounded worker atomically claims jobs and recovers safe expired queued/claimed work after a real restart while the student can navigate away and later retrieve the result.
- [ ] Concurrent claims cannot commit duplicate results; stale-project results do not overwrite newer authoritative student state and review admission remains enforced.
- [ ] SQLite and DSQL lease/OCC contracts have deterministic fault coverage; document when a persistence-backed design suffices without adding queue infrastructure.
- [ ] Use the approved public testing seams and deterministic external adapters; for behavior changes demonstrate one red test then its minimal green implementation per cycle, with no speculative tests or code.
- [ ] Update affected guidance and the authoritative implementation ledger with executed evidence, compatibility/migration/rollback, risks and the next exact action; complete this ticket in one fresh writer session without staging, committing, deploying or paid calls.
