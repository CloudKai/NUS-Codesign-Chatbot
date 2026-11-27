# 03: Audit repository privacy

**What to build:** Inventory tracked recordings, logs, screenshots and configuration; replace approved synthetic fixtures and document sensitive findings without exposing or deleting private work.

**Blocked by:** 01: Reproduce the baseline and establish coverage.

**Status:** ready-for-agent

- [x] Inventory tracked logs, screenshots, recordings, fixtures and configuration for student, research, restricted-course, session and credential exposure.
- [x] Report categories and actionable locations without reproducing secrets or private content; use synthetic replacements only within clear authorization.
- [x] Preserve user artifacts, Git history and credentials; any deletion, history rewrite or live rotation remains an explicit approval gate.
- [x] Use the approved public testing seams and deterministic external adapters; for behavior changes demonstrate one red test then its minimal green implementation per cycle, with no speculative tests or code.
- [x] Update affected guidance and the authoritative implementation ledger with executed evidence, compatibility/migration/rollback, risks and the next exact action; complete this ticket in one fresh writer session without staging, committing, deploying or paid calls.

Local audit acceptance and executed evidence: [implementation ledger](../../../docs/IMPLEMENTATION_STATUS.md#local-completion-ticket-03--repository-privacy-audit-2026-11-24-sgt).
See the [redacted report](../../../docs/security/PUBLIC_REPOSITORY_CONTENT_AUDIT.md)
for the remaining owner publication reviews. No artifact replacement/removal,
history rewrite, rotation or public release is implied by these checks.
