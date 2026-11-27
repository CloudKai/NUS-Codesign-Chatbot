# 12: Read and confirm Thinking Path progress through typed resources

**What to build:** Migrate project progress, stage navigation and confirmation to generated contracts and revision-aware Query, preserving backend stage authority.

**Blocked by:** 01: Reproduce the baseline and establish coverage.

**Status:** ready-for-agent

- [ ] Project state, Thinking Path, stage selection and transition decisions use reviewed generated contracts and revision-aware confirmed Query state.
- [ ] A Stage recommendation alone awards no completion; explicit Stage confirmation applies the existing atomic transition exactly once.
- [ ] Rejection, stale/repeated confirmations, completed-stage revisits and terminal Reflection retain existing semantics across restart and identity changes.
- [ ] Use the approved public testing seams and deterministic external adapters; for behavior changes demonstrate one red test then its minimal green implementation per cycle, with no speculative tests or code.
- [ ] Update affected guidance and the authoritative implementation ledger with executed evidence, compatibility/migration/rollback, risks and the next exact action; complete this ticket in one fresh writer session without staging, committing, deploying or paid calls.
