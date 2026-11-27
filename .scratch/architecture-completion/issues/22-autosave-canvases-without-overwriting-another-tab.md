# 22: Autosave canvases without overwriting another tab

**What to build:** Deliver bounded debounced graph saves, deduplication, offline/expiry/navigation handling and revision conflicts without a mutation per pointer move.

**Blocked by:** 20: Create and reopen a persistent Design Canvas.

**Status:** ready-for-agent

- [ ] Debounced graph saves return confirmed revisions and clear status; pointer movement and viewport-only changes do not produce excessive meaningful revisions.
- [ ] Duplicate and ambiguous save outcomes reconcile safely; incompatible late responses are ignored after an owner or canvas change.
- [ ] Two-tab conflicts preserve unsaved reasoning with explicit recovery options; offline, expiry, navigation and reload never silently overwrite confirmed student content.
- [ ] Use the approved public testing seams and deterministic external adapters; for behavior changes demonstrate one red test then its minimal green implementation per cycle, with no speculative tests or code.
- [ ] Update affected guidance and the authoritative implementation ledger with executed evidence, compatibility/migration/rollback, risks and the next exact action; complete this ticket in one fresh writer session without staging, committing, deploying or paid calls.
