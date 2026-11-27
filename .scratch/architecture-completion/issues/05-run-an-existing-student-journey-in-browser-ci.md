# 05: Run an existing student journey in browser CI

**What to build:** Launch a disposable real local stack and production frontend; exercise Guest/fixture login, chat, saved-turn recovery and restart in Playwright Test.

**Blocked by:** 01: Reproduce the baseline and establish coverage.

**Status:** accepted locally (2026-11-24 SGT, OpenCode) — see
[the ledger entry](../../../docs/IMPLEMENTATION_STATUS.md#ticket-05-complete--browser-ci-slice-2026-11-24-sgt-opencode)

- [x] A repeatable Playwright Test command starts a production-built frontend and real disposable local FastAPI/SQLite application with deterministic external providers.
- [x] Guest and approved synthetic registered identities can open a notebook, submit a mock turn and reopen saved output after a real backend restart.
- [x] Interrupted-response recovery uses the original request key and creates one confirmed turn; owner-change and unsafe-preview regressions use controlled fault injection.
- [x] CI is finite, self-cleaning, non-billable and uses no developer database, live Cognito or AWS credentials; useful existing browser regressions remain available.
- [x] Use the approved public testing seams and deterministic external adapters; for behavior changes demonstrate one red test then its minimal green implementation per cycle, with no speculative tests or code.
- [x] Update affected guidance and the authoritative implementation ledger with executed evidence, compatibility/migration/rollback, risks and the next exact action; complete this ticket in one fresh writer session without staging, committing, deploying or paid calls.
