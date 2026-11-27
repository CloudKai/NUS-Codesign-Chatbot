# 18: Preview and restore artifact versions

**What to build:** Expose bounded history for every supported artifact type and restore an older document as a new conditional revision without losing intervening work.

**Blocked by:** 17: Autosave artifacts without losing conflicting drafts.

**Status:** ready-for-agent

- [ ] Each supported artifact type exposes bounded owner-authorized version metadata and a readable selected-version preview.
- [ ] Restoration checks the current revision and creates a new revision while preserving intermediate versions and the previous current content.
- [ ] Stale restore, foreign version, duplicate restore and restart behavior have public API/browser contract evidence; meaningful checkpoint labels/provenance are truthful.
- [ ] Use the approved public testing seams and deterministic external adapters; for behavior changes demonstrate one red test then its minimal green implementation per cycle, with no speculative tests or code.
- [ ] Update affected guidance and the authoritative implementation ledger with executed evidence, compatibility/migration/rollback, risks and the next exact action; complete this ticket in one fresh writer session without staging, committing, deploying or paid calls.
