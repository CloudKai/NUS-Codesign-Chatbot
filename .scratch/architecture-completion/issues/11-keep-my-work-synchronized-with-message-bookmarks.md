# 11: Keep My Work synchronized with message bookmarks

**What to build:** Move bookmark/message-star operations to generated contracts and revision-aware Query without losing stage grouping or append-only edit semantics.

**Blocked by:** 01: Reproduce the baseline and establish coverage.

**Status:** ready-for-agent

- [ ] Starring/un-starring updates confirmed message and bookmark resources without losing stage grouping or requiring complete transcript pagination.
- [ ] Generated contracts and Query preserve owner/revision checks, superseded-message exclusions and append-only editing semantics.
- [ ] Slow reads, ambiguous writes, reload/restart and account switches retain accurate My Work without optimistic learning changes.
- [ ] Use the approved public testing seams and deterministic external adapters; for behavior changes demonstrate one red test then its minimal green implementation per cycle, with no speculative tests or code.
- [ ] Update affected guidance and the authoritative implementation ledger with executed evidence, compatibility/migration/rollback, risks and the next exact action; complete this ticket in one fresh writer session without staging, committing, deploying or paid calls.
