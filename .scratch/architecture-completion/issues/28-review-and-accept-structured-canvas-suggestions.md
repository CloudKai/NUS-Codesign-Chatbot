# 28: Review and accept structured canvas suggestions

**What to build:** Preview validated node/relationship proposals, allow edit/reject/accept and save only explicitly accepted changes after revision revalidation.

**Blocked by:** 27: Coach selected canvas reasoning; 22: Autosave canvases without overwriting another tab.

**Status:** ready-for-agent

- [ ] The coach returns bounded structured proposals with stable suggestion identity, targets, proposed content/relationship, rationale/evidence and base canvas revision.
- [ ] Students can preview, edit, accept, reject or ignore suggestions; only explicit acceptance invokes an ordinary authorized conditional graph save.
- [ ] Changed base revisions trigger revalidation/conflict handling, duplicates cannot apply twice and invalid evidence/targets are rejected.
- [ ] Suggestions never execute database operations or independently alter stages; hostile model text cannot bypass validation.
- [ ] Use the approved public testing seams and deterministic external adapters; for behavior changes demonstrate one red test then its minimal green implementation per cycle, with no speculative tests or code.
- [ ] Update affected guidance and the authoritative implementation ledger with executed evidence, compatibility/migration/rollback, risks and the next exact action; complete this ticket in one fresh writer session without staging, committing, deploying or paid calls.
