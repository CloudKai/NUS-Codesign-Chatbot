# 42: Evaluate retrieval for workspace evidence

**What to build:** Extend labelled retrieval evaluation to canvas/artifact selections, report evidence quality/latency and evaluate advanced methods only for measured gaps.

**Blocked by:** 27: Coach selected canvas reasoning; 29: Review and accept artifact feedback.

**Status:** ready-for-agent

- [ ] Extend labeled evaluation to explicit/implicit course questions, project coaching, ambiguous follow-ups, selected uploads and canvas/artifact references while retaining the existing gate by default.
- [ ] Record retrieval precision, recall@K, MRR, citation correctness, authorization/filtering, evidence gaps and latency on reproducible labeled examples.
- [ ] Evaluate chunking/search/reranking/rewriting/multimodal variants only for an observed gap, documenting demand/privacy/cost and rejected variants; no automatic new router/vector store.
- [ ] Use the approved public testing seams and deterministic external adapters; for behavior changes demonstrate one red test then its minimal green implementation per cycle, with no speculative tests or code.
- [ ] Update affected guidance and the authoritative implementation ledger with executed evidence, compatibility/migration/rollback, risks and the next exact action; complete this ticket in one fresh writer session without staging, committing, deploying or paid calls.
