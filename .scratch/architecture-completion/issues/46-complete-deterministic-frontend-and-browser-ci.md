# 46: Complete deterministic frontend and browser CI

**What to build:** Run the integrated workspace journey plus component, backend, contract-drift, build, accessibility, audit and existing CodeQL checks without paid services.

**Blocked by:** 02: Clear lint and collection blockers; 05: Run an existing student journey in browser CI; 26: Turn selected chat content into canvas nodes; 28: Review and accept structured canvas suggestions; 29: Review and accept artifact feedback; 30: Develop artifacts from selected canvas nodes; 31: Return artifact reasoning to the canvas; 32: Resume a project from persisted work; 33: Show deduplicated confirmed milestone recaps; 36: Handle cancelled and ambiguous Deep Review execution.

**Status:** ready-for-agent

- [ ] A deterministic integrated Playwright journey covers authored/saved/reopened work, chat/canvas/artifact transfers, reviewed suggestions, confirmation/recap, resume and durable review.
- [ ] CI includes applicable full Python collection/lint/tests, TypeScript/frontend lint, Vitest/component tests, offline schema/client drift and production build without deleting existing regressions.
- [ ] Browser/accessibility, dependency audit, secret scanning and existing CodeQL checks have bounded reproducible configuration; no ordinary job needs live AWS or paid AI.
- [ ] Record actual passes/failures/skips and artifact privacy/retention; later tickets extend their own new behavior coverage rather than relying on this checkpoint as future proof.
- [ ] Use the approved public testing seams and deterministic external adapters; for behavior changes demonstrate one red test then its minimal green implementation per cycle, with no speculative tests or code.
- [ ] Update affected guidance and the authoritative implementation ledger with executed evidence, compatibility/migration/rollback, risks and the next exact action; complete this ticket in one fresh writer session without staging, committing, deploying or paid calls.
