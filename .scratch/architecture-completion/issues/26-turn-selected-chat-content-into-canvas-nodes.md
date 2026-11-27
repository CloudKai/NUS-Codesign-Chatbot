# 26: Turn selected chat content into canvas nodes

**What to build:** Let students choose a destination, edit the proposed node and confirm creation while retaining originating message and evidence references.

**Blocked by:** 21: Explore and edit a complete visual reasoning map; 25: Link artifacts and canvas reasoning to evidence.

**Status:** ready-for-agent

- [ ] Selecting useful chat content opens an editable node proposal with type, title, content, destination canvas and optional evidence.
- [ ] Only confirmation saves the node through ordinary owner/revision checks, preserving the exact source message and appropriate provenance.
- [ ] Reject/cancel saves nothing; late owner changes, stale destination and source unavailability are handled explicitly without automatically converting replies.
- [ ] Use the approved public testing seams and deterministic external adapters; for behavior changes demonstrate one red test then its minimal green implementation per cycle, with no speculative tests or code.
- [ ] Update affected guidance and the authoritative implementation ledger with executed evidence, compatibility/migration/rollback, risks and the next exact action; complete this ticket in one fresh writer session without staging, committing, deploying or paid calls.
