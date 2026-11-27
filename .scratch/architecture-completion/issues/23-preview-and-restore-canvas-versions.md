# 23: Preview and restore canvas versions

**What to build:** Expose meaningful graph history and conditional restoration as a new revision, separating viewport state and local undo from persistent checkpoints.

**Blocked by:** 22: Autosave canvases without overwriting another tab.

**Status:** ready-for-agent

- [ ] Students browse bounded canvas version metadata and preview a selected previous graph through owner-authorized contracts.
- [ ] Restore checks the latest revision and creates a new current snapshot, retaining all intervening meaningful history.
- [ ] History survives restart; stale/foreign/duplicate restores fail or reconcile predictably, independently of local undo/redo and viewport preferences.
- [ ] Use the approved public testing seams and deterministic external adapters; for behavior changes demonstrate one red test then its minimal green implementation per cycle, with no speculative tests or code.
- [ ] Update affected guidance and the authoritative implementation ledger with executed evidence, compatibility/migration/rollback, risks and the next exact action; complete this ticket in one fresh writer session without staging, committing, deploying or paid calls.
