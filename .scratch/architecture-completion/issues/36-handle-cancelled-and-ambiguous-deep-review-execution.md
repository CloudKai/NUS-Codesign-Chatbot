# 36: Handle cancelled and ambiguous Deep Review execution

**What to build:** Support cancellation, expired claims, bounded recovery and honest retry/reconciliation after uncertain provider outcomes without blind repeat inference.

**Blocked by:** 35: Resume queued Deep Review safely after restart.

**Status:** ready-for-agent

- [ ] Student-visible queued/claimed/running/cancel-requested/cancelled/succeeded/failed/retryable behavior is explicit and persists across navigation/restart.
- [ ] Cancellation, lease expiry, heartbeats, bounded attempts and crashes around invocation/result commit are tested through agreed worker/API/browser contracts.
- [ ] Unknown external outcomes retain conservative cost/capacity handling and show explicit retry/reconciliation; never claim exactly-once inference or automatically repeat uncertain paid work.
- [ ] Old-revision completion, repeated requests and late worker results cannot overwrite newer work or create duplicate confirmed review results.
- [ ] Use the approved public testing seams and deterministic external adapters; for behavior changes demonstrate one red test then its minimal green implementation per cycle, with no speculative tests or code.
- [ ] Update affected guidance and the authoritative implementation ledger with executed evidence, compatibility/migration/rollback, risks and the next exact action; complete this ticket in one fresh writer session without staging, committing, deploying or paid calls.
