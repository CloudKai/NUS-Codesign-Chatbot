# 30: Develop artifacts from selected canvas nodes

**What to build:** Assemble selected reasoning manually or via bounded reviewed AI synthesis, preserving node/revision origins and requiring explicit document confirmation.

**Blocked by:** 27: Coach selected canvas reasoning; 16: Manage course-aligned artifact types; 17: Autosave artifacts without losing conflicting drafts.

**Status:** ready-for-agent

- [ ] Students choose canvas nodes and manually assemble an artifact or explicitly request bounded AI synthesis into a reviewable draft.
- [ ] The draft can be edited, rejected or confirmed; an existing artifact is never overwritten automatically.
- [ ] Accepted content retains contributing node IDs, graph revision, evidence and AI provenance, with conditional save and unavailable/stale origin handling.
- [ ] Use the approved public testing seams and deterministic external adapters; for behavior changes demonstrate one red test then its minimal green implementation per cycle, with no speculative tests or code.
- [ ] Update affected guidance and the authoritative implementation ledger with executed evidence, compatibility/migration/rollback, risks and the next exact action; complete this ticket in one fresh writer session without staging, committing, deploying or paid calls.
