# 31: Return artifact reasoning to the canvas

**What to build:** Create or link nodes from document selections with artifact/revision provenance and explicit handling of stale linked content.

**Blocked by:** 21: Explore and edit a complete visual reasoning map; 25: Link artifacts and canvas reasoning to evidence; 17: Autosave artifacts without losing conflicting drafts.

**Status:** ready-for-agent

- [ ] Students select artifact content to create an editable node proposal or explicitly link an existing node, choosing the appropriate destination.
- [ ] Confirmation retains artifact/revision origin and valid evidence under ordinary graph ownership and revision checks.
- [ ] Later document/node changes are not silently synchronized; the UI exposes stale linkage and explicit update options while preserving edits.
- [ ] Use the approved public testing seams and deterministic external adapters; for behavior changes demonstrate one red test then its minimal green implementation per cycle, with no speculative tests or code.
- [ ] Update affected guidance and the authoritative implementation ledger with executed evidence, compatibility/migration/rollback, risks and the next exact action; complete this ticket in one fresh writer session without staging, committing, deploying or paid calls.
