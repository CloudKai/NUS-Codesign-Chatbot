# 08: Manage notebooks through generated REST and Query

**What to build:** Deliver create, rename, move, pin and confirmed deletion using existing ownership semantics, generated contracts and scoped Query updates.

**Blocked by:** 01: Reproduce the baseline and establish coverage.

**Status:** ready-for-agent

- [ ] Notebook creation, rename, chat movement, pinning and confirmed deletion work through approved generated contracts using existing notebook/chat relationships.
- [ ] Owner-fenced Query updates preserve sidebar identity and confirmed mutation results without a whole-application reload or stale-read rollback.
- [ ] Canceled/ambiguous requests reconcile explicitly; changing owners during a pending operation never exposes or modifies another workspace.
- [ ] Use the approved public testing seams and deterministic external adapters; for behavior changes demonstrate one red test then its minimal green implementation per cycle, with no speculative tests or code.
- [ ] Update affected guidance and the authoritative implementation ledger with executed evidence, compatibility/migration/rollback, risks and the next exact action; complete this ticket in one fresh writer session without staging, committing, deploying or paid calls.
