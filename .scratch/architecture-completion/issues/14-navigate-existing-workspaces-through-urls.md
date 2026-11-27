# 14: Navigate existing workspaces through URLs

**What to build:** Add TanStack Router for existing student views, back/forward, refresh and deep links while preserving hosting aliases, ownership and unsaved drafts.

**Blocked by:** 06: Extract the chat lifecycle without changing behavior; 09: Open an aggregated, verified workspace.

**Status:** ready-for-agent

- [ ] Owned notebook/chat and existing student views have typed URLs with working direct links, refresh and browser back/forward behavior.
- [ ] Root/pilot hosting, hashed assets, recognized SPA fallbacks and protected lecturer routes work without exposing internal API paths.
- [ ] Navigation preserves safe generation/cancellation/recovery and compatible unsaved drafts; expired or foreign links show no private data.
- [ ] Route loaders avoid duplicate navigation truth and prefetch only bounded resources after identity verification.
- [ ] Use the approved public testing seams and deterministic external adapters; for behavior changes demonstrate one red test then its minimal green implementation per cycle, with no speculative tests or code.
- [ ] Update affected guidance and the authoritative implementation ledger with executed evidence, compatibility/migration/rollback, risks and the next exact action; complete this ticket in one fresh writer session without staging, committing, deploying or paid calls.
