# 17: Autosave artifacts without losing conflicting drafts

**What to build:** Deliver debounced confirmed saves, request deduplication, offline/expiry/navigation handling and two-tab conflict resolution with preserved student edits.

**Blocked by:** 15: Create and reopen a persistent student artifact.

**Status:** ready-for-agent

- [ ] Debounced saves confirm a server revision before displaying Saved; Editing, Saving, Offline, Failure and Conflict states are distinguishable.
- [ ] Duplicate save requests create no duplicate revisions; lost acknowledgements reconcile the original request rather than blindly replaying a mutation.
- [ ] Two tabs saving the same base revision preserve the losing local draft and offer explicit resolution without silent overwrites.
- [ ] Slow/offline/expired-session navigation and refresh have a documented owner-scoped draft/recovery policy; neither drafts nor late responses transfer to another owner.
- [ ] Checkpoint policy distinguishes current draft, meaningful versions and explicit saves without a permanent revision per keystroke; measure write amplification.
- [ ] Use the approved public testing seams and deterministic external adapters; for behavior changes demonstrate one red test then its minimal green implementation per cycle, with no speculative tests or code.
- [ ] Update affected guidance and the authoritative implementation ledger with executed evidence, compatibility/migration/rollback, risks and the next exact action; complete this ticket in one fresh writer session without staging, committing, deploying or paid calls.
