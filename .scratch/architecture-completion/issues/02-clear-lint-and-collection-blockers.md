# 02: Clear lint and collection blockers

**What to build:** Make the complete configured lint/build/test checks pass without suppressing valid findings or losing the existing test-collection fix.

**Blocked by:** 01: Reproduce the baseline and establish coverage.

**Status:** ready-for-agent

- [x] Reproduce each full configured lint failure before changing code and correct the underlying issue without blanket ignores or excluding affected modules.
- [x] Full applicable Python lint and test collection pass; TypeScript/build and existing checks remain green, with tools not installed or configured reported honestly.
- [x] Preserve public behavior, compatibility imports and the existing test-package collection fix; use a failing behavior regression first only when a behavior correction is needed.
- [x] Use the approved public testing seams and deterministic external adapters; for behavior changes demonstrate one red test then its minimal green implementation per cycle, with no speculative tests or code.
- [x] Update affected guidance and the authoritative implementation ledger with executed evidence, compatibility/migration/rollback, risks and the next exact action; complete this ticket in one fresh writer session without staging, committing, deploying or paid calls.

Verified local acceptance: [ticket 02 evidence](../../../docs/IMPLEMENTATION_STATUS.md#local-completion-ticket-02--lint-and-collection-blockers-2026-11-24-sgt). Triage status remains unchanged; live release gates remain open.
