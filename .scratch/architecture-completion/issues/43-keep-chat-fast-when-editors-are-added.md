# 43: Keep chat fast when editors are added

**What to build:** Measure chat/editor/canvas bundles and rendering; lazy-load heavy features and improve only demonstrated render/scroll bottlenecks.

**Blocked by:** 16: Manage course-aligned artifact types; 21: Explore and edit a complete visual reasoning map; 14: Navigate existing workspaces through URLs.

**Status:** ready-for-agent

- [ ] Measure initial and total assets, chat-only startup, canvas/artifact route loading and representative long-content render/scroll behavior.
- [ ] Canvas/editor and optional heavy features load lazily without breaking deep-link hosting or hashed-asset caching; private API responses remain no-store.
- [ ] Apply batching/memoization/virtualization only with measured benefit and preserved selection, reading position, streaming safety, accessibility and reduced motion.
- [ ] Use the approved public testing seams and deterministic external adapters; for behavior changes demonstrate one red test then its minimal green implementation per cycle, with no speculative tests or code.
- [ ] Update affected guidance and the authoritative implementation ledger with executed evidence, compatibility/migration/rollback, risks and the next exact action; complete this ticket in one fresh writer session without staging, committing, deploying or paid calls.
