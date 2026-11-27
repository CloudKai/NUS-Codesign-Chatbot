# 37: Trace a coaching request without recording private content

**What to build:** Extend existing latency/usage correlation from browser through save, distinguishing measured phases and first safe visible text with privacy-safe logs.

**Blocked by:** 01: Reproduce the baseline and establish coverage.

**Status:** ready-for-agent

- [ ] Existing telemetry correlates browser request, identity/admission, database, retrieval, context, runtime/provider, guardrail, validation, persistence and reconciliation where observable.
- [ ] Measurements distinguish internal first token/reply text, first safe visible text and final confirmed completion; unknown/inferred durations are labeled.
- [ ] Logs avoid prompts, complete student content, raw unnecessary identifiers, cookies and credentials; local use does not require a paid observability service.
- [ ] Use the approved public testing seams and deterministic external adapters; for behavior changes demonstrate one red test then its minimal green implementation per cycle, with no speculative tests or code.
- [ ] Update affected guidance and the authoritative implementation ledger with executed evidence, compatibility/migration/rollback, risks and the next exact action; complete this ticket in one fresh writer session without staging, committing, deploying or paid calls.
