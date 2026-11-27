# 09: Open an aggregated, verified workspace

**What to build:** Load bounded initial messages, metadata, bookmarks, settings and learning projections together, seed Query safely and measure fewer chat-opening reads.

**Blocked by:** 07: Save preferences through generated REST and Query; 08: Manage notebooks through generated REST and Query.

**Status:** ready-for-agent

- [ ] An owner-verified bounded workspace response contains the initial message page/revision, metadata, project/Thinking Path, bookmarks, settings and small resource indicators.
- [ ] No full uploaded source, unlimited transcript or revision history enters the projection; database access avoids N+1 behavior and makes no false transactional-snapshot promise.
- [ ] The generated browser request seeds compatible Query resources after required identity/revision checks without immediate duplicate component fetches.
- [ ] Exact edge permissions and private no-store remain enforced; repeated startup/open/switch/revisit measurements report actual requests and latency against the baseline.
- [ ] Use the approved public testing seams and deterministic external adapters; for behavior changes demonstrate one red test then its minimal green implementation per cycle, with no speculative tests or code.
- [ ] Update affected guidance and the authoritative implementation ledger with executed evidence, compatibility/migration/rollback, risks and the next exact action; complete this ticket in one fresh writer session without staging, committing, deploying or paid calls.
