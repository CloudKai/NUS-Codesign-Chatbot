# 13: Read reviews, briefs and existing exports through typed resources

**What to build:** Migrate remaining existing review/brief/status/export metadata contracts with explicit generation, honest loading and documented binary exceptions.

**Blocked by:** 01: Reproduce the baseline and establish coverage.

**Status:** ready-for-agent

- [ ] Existing Review, project brief, job status/result and export metadata operations use reviewed generated types without exposing professor/admin endpoints.
- [ ] Reading cached state never starts generation implicitly; explicit existing generation/retry behavior and unavailable/failure states remain honest.
- [ ] Binary and streaming exceptions are documented and preserve owner verification, cancellation, no-store, saved receipts and existing export contents.
- [ ] Use the approved public testing seams and deterministic external adapters; for behavior changes demonstrate one red test then its minimal green implementation per cycle, with no speculative tests or code.
- [ ] Update affected guidance and the authoritative implementation ledger with executed evidence, compatibility/migration/rollback, risks and the next exact action; complete this ticket in one fresh writer session without staging, committing, deploying or paid calls.
