# 27: Coach selected canvas reasoning

**What to build:** Resolve selected saved nodes and bounded neighbours server-side and discuss them through existing retrieval/coaching with token budgets and no automatic graph changes.

**Blocked by:** 06: Extract the chat lifecycle without changing behavior; 21: Explore and edit a complete visual reasoning map; 25: Link artifacts and canvas reasoning to evidence.

**Status:** ready-for-agent

- [ ] Students select saved nodes and request explain, critique, compare, assumption/evidence checks, ethical reflection or related contextual coaching.
- [ ] The request carries resource/revision and selected IDs; FastAPI resolves authorized text rather than trusting browser ownership or authoritative content.
- [ ] The existing context planner bounds node count, expansion depth, neighbors/edges, artifact excerpts, evidence and token budget; unselected complete workspaces are not attached.
- [ ] Existing retrieval/citation/safety/admission and stage authority remain intact; unsaved student text is explicitly labeled when supported, and no graph changes automatically.
- [ ] Use the approved public testing seams and deterministic external adapters; for behavior changes demonstrate one red test then its minimal green implementation per cycle, with no speculative tests or code.
- [ ] Update affected guidance and the authoritative implementation ledger with executed evidence, compatibility/migration/rollback, risks and the next exact action; complete this ticket in one fresh writer session without staging, committing, deploying or paid calls.
