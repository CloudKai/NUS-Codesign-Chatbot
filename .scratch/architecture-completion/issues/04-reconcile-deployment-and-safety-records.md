# 04: Reconcile deployment and safety records

**What to build:** Produce a nonsecret version manifest and reviewable Mantle publication/session-rollover verification procedure, distinguishing recorded and verified live state.

**Blocked by:** 01: Reproduce the baseline and establish coverage.

**Status:** ready-for-agent

- [x] A versioned nonsecret manifest distinguishes repository defaults, last recorded deployment and actually verified configuration, leaving unverified fields unknown.
- [x] Record compatible application, edge, image, runtime, model and session-generation identifiers and explain discrepancies without changing live configuration.
- [x] Provide reviewable Mantle publication, version check, required session rollover, fresh-session and blocked-output checks; safe rollback never removes the provisional-output fix.
- [x] Use the approved public testing seams and deterministic external adapters; for behavior changes demonstrate one red test then its minimal green implementation per cycle, with no speculative tests or code.
- [x] Update affected guidance and the authoritative implementation ledger with executed evidence, compatibility/migration/rollback, risks and the next exact action; complete this ticket in one fresh writer session without staging, committing, deploying or paid calls.

Local acceptance evidence: [authoritative ledger](../../../docs/IMPLEMENTATION_STATUS.md#local-completion-ticket-04--deployment-and-safety-records-2026-11-24-sgt), [procedure](../../../docs/deploy/DEPLOYMENT_SAFETY_RECORD.md) and [manifest](../../../docs/examples/deployment/architecture-ticket04-2026-11-24.json). This completes offline reconciliation only; live publication/session rollover/blocked-output gates remain unverified. Triage remains `ready-for-agent`.
