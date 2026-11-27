# 40: Evaluate compact prompts and supported prompt caching

**What to build:** Compare representative prompt variants using the educational/security corpus, recording tokens, quality, citations, reliability and supported cache economics without automatic rollout.

**Blocked by:** 37: Trace a coaching request without recording private content.

**Status:** ready-for-agent

- [ ] Representative prompt variants reduce duplication without dropping pedagogy, evidence, structured schema, stage or security instructions; include selected workspace context costs.
- [ ] Use existing educational/security regression cases to report tokens, structured-output first/final success, recovery frequency, citation accuracy, quality, latency and cost per successful turn.
- [ ] Prompt caching is tested only for actual supported models and accounts for eligibility/hits/create/read costs; no shared cross-student response cache.
- [ ] Keep baseline/compact/cache variants reproducible and separate deterministic local checks from capped approval-dependent provider evaluation; no forced token target or unsupported quality claim.
- [ ] Use the approved public testing seams and deterministic external adapters; for behavior changes demonstrate one red test then its minimal green implementation per cycle, with no speculative tests or code.
- [ ] Update affected guidance and the authoritative implementation ledger with executed evidence, compatibility/migration/rollback, risks and the next exact action; complete this ticket in one fresh writer session without staging, committing, deploying or paid calls.
