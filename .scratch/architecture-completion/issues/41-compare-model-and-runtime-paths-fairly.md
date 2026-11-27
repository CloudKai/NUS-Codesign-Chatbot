# 41: Compare model and runtime paths fairly

**What to build:** Provide a bounded repeatable comparison of configured models and existing/optimized/direct inference paths with equivalent guardrails and explicit live-test caps.

**Blocked by:** 37: Trace a coaching request without recording private content.

**Status:** ready-for-agent

- [ ] Document actual configured Fast Chat/Deep Review models and runtime versions before comparing justified available candidates and rollback configurations.
- [ ] Compare existing, optimized AgentCore and compatible direct-provider adapters with equivalent instructions, guardrails, citation validation, safe streaming, session, retries and persistence.
- [ ] Report quality, structured-output/native-nullability reliability, context, safety, first safe visible text, tail latency, throughput and cost on comparable workloads.
- [ ] Provide finite dry-run/mock infrastructure and explicit request/token/cost/concurrency gates for live execution; do not replace models or remove AgentCore solely on novelty or size.
- [ ] Use the approved public testing seams and deterministic external adapters; for behavior changes demonstrate one red test then its minimal green implementation per cycle, with no speculative tests or code.
- [ ] Update affected guidance and the authoritative implementation ledger with executed evidence, compatibility/migration/rollback, risks and the next exact action; complete this ticket in one fresh writer session without staging, committing, deploying or paid calls.
