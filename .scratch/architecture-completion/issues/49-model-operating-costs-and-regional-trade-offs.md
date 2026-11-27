# 49: Model operating costs and regional trade-offs

**What to build:** Produce low/expected/high SGD scenarios including models, reviews, autosaves, storage and transfer, with dated pricing and no guaranteed S$30 or automatic region migration.

**Blocked by:** 04: Reconcile deployment and safety records; 37: Trace a coaching request without recording private content; 48: Measure mixed classroom workloads locally.

**Status:** ready-for-agent

- [ ] Produce low/expected/high monthly SGD scenarios with dated current prices and realistic students, turns/tokens, retrieval/review/retry, autosaves, growth and retention assumptions.
- [ ] Include compute, CDN, identity, DSQL, S3, Knowledge Base, AgentCore/models, monitoring, transfer and any conditional jobs; distinguish gross, credits, cash and post-credit baseline.
- [ ] Measure or clearly mark unknown Singapore-to-origin/database/model regional latency, availability, processing location and transfer trade-offs without automatically migrating regions.
- [ ] Assess the approximate S$30 objective honestly and retain existing classroom cost/capacity release gates; hosted editor/canvas services are not required.
- [ ] Use the approved public testing seams and deterministic external adapters; for behavior changes demonstrate one red test then its minimal green implementation per cycle, with no speculative tests or code.
- [ ] Update affected guidance and the authoritative implementation ledger with executed evidence, compatibility/migration/rollback, risks and the next exact action; complete this ticket in one fresh writer session without staging, committing, deploying or paid calls.
