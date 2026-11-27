# 47: Rehearse recovery of the complete saved workspace

**What to build:** Back up and restore synthetic messages, learning state, artifact/canvas histories and job metadata; prove existing-data compatibility and document rollback limits.

**Blocked by:** 18: Preview and restore artifact versions; 23: Preview and restore canvas versions; 33: Show deduplicated confirmed milestone recaps; 36: Handle cancelled and ambiguous Deep Review execution.

**Status:** ready-for-agent

- [ ] A documented backup inventory includes current documents/graphs, both version histories, messages, learning state, recap and relevant job metadata.
- [ ] Restore a complete synthetic workspace into a disposable local environment and verify content/history/references and recovery through public interfaces after restart.
- [ ] Verify supported DSQL recovery procedures separately, document version compatibility and rollback limits, and never run destructive production restoration or infer live recoverability from SQLite.
- [ ] Use the approved public testing seams and deterministic external adapters; for behavior changes demonstrate one red test then its minimal green implementation per cycle, with no speculative tests or code.
- [ ] Update affected guidance and the authoritative implementation ledger with executed evidence, compatibility/migration/rollback, risks and the next exact action; complete this ticket in one fresh writer session without staging, committing, deploying or paid calls.
