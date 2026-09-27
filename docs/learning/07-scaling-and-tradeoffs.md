# 7. Scaling, operations, and architectural tradeoffs

[Handbook index](README.md) · [Next: interview and study](08-interview-and-study.md)

## 7.1 What capacity is actually configured?

The checked [production Compose](../../compose.prod.yaml) runs one application container with one Uvicorn worker. It configures:

| Limit | Configured value | What it means |
|---|---|---|
| Active coach requests per notebook | 1 | Local admission limit for simultaneous workflows |
| Active coach requests per user | 2 | A user can occupy at most two local workflow slots |
| Coach requests per minute per user | 8 | Per-process rate window |
| Global active workflows | 120 | Historical setting name is `MAX_CONCURRENT_MODEL_CALLS`, but it counts workflows |
| Synchronous threadpool tokens | 120 | Framework synchronous task admission capacity |
| Fast Chat input soft/hard limits | 12,000 / 16,000 estimated tokens | Model-context budgets, not database storage limits |
| Recent verbatim history | 6 messages / 3,000 estimated tokens | Bounded prompt history plus derived memory |
| Fast Chat retrieved evidence | Defaults 4 chunks / 8,000 characters | Separate retrieval budget from total model input |
| KB executor | Default 4 workers | Shared bounded admission for KB calls |
| Deep Review concurrency | Default 8 | Separate review-related execution configuration |

Some values are explicitly pinned by Compose; others are settings defaults that host configuration can change. These are implementation limits, not a measured service capacity. The comment “~100 concurrent students” is a target, not proof that one hundred simultaneous generation requests meet a latency SLO.

The KB pool can become the bottleneck long before 120 workflow slots are filled. The stream handler also creates a worker thread and consumes queue events, so the configured synchronous threadpool count is not a complete count of all OS threads. Measure actual thread/process behavior under load.

## 7.2 Students online, request rate, and concurrency

One hundred students logged in does not imply one hundred simultaneous model calls. Capacity depends on how often they send and how long requests remain active.

A useful planning relationship is:

```text
average active requests ≈ arrival rate × average request duration
```

For an illustrative class of 100 students sending once per minute, arrival rate is about 1.67 requests/second. At an assumed eight-second average duration, that is about 13.3 active requests on average. If the class sends together after an instructor prompt, the burst can be much larger. These are examples, not project measurements.

The configured per-user cap permits a theoretical 800 requests/minute across 100 users if everyone hits it. At eight seconds each, that would imply about 107 average active workflows before additional overhead. This calculation shows why limits and provider quotas must be analyzed together; it does not certify the machine can serve that load.

Plan for p95/p99 durations, synchronized classroom bursts, review jobs, upload CPU work, and KB admission. Average latency alone hides the experience of students waiting much longer than everyone else.

## 7.3 Why adding workers is not a complete scaling plan

The current limiter stores counters in process memory. Four workers each with a 120-workflow limit can admit roughly four independent sets of work. Per-user and per-notebook limits also stop being global.

Same-key SQL reservations still deduplicate that logical request while the lease remains valid. Distinct keys in the same notebook do not automatically share one reservation. Revision/stage checks reject some stale writes but are not a substitute for intentionally serializing all conflicting notebook operations.

Streamlit sessions also live in a process. Multiple replicas need a connection/session-routing strategy; moving SQL to a shared database does not migrate widget state or WebSocket connections. In-memory graph checkpoints, caches, and executors need explicit treatment.

Therefore the first scaling change should not be an arbitrary `--workers 4`. Design global admission, notebook coordination, background jobs, and UI session behavior, then add replicas and test them.

## 7.4 A practical scaling sequence

**First, measure the current path.** Use request-correlated timings for identity, notebook load, history/context, retrieval, generation, and persistence. Measure rejection categories, provider throttling, token usage, retries, and result quality. The local mock load probe exercises application admission behavior; it is not a benchmark of real Bedrock, DSQL, or the EC2 machine.

**Next, remove repeated work.** Load one authoritative source snapshot per turn, avoid repeated catalog lists, cache validated chunk artifacts with bounded memory, use lazy lecturer tabs, and paginate long transcripts. The project already implements several of these ideas. Measure their effect rather than count them as hypothetical future work.

**Then, make coordination distributed.** Introduce a global rate limiter or durable admission service, plus per-notebook execution fencing that covers different keys. Preserve request-level idempotency. A lease must be renewed safely or sized to bounded execution, and stale workers must still fail commit.

**Move long jobs to durable workers.** Use a job queue with persistent status, claim tokens, retries, attempt limits, and a dead-letter/manual-recovery policy. Deep Review, stage review, and document extraction can then run independently of web process restarts. An outbox can tie job creation to SQL changes so “database committed but queue publish failed” is recoverable.

**Scale the serving tier.** Separate Streamlit and FastAPI deployment units if independent scaling is useful. Add replicated API instances behind appropriate private routing. Keep notebook ownership checks at the service boundary and define session affinity for Streamlit. Consider a browser SPA only if product interaction requirements justify the rewrite.

**Finally, tune data access and retrieval.** Review query plans, connection reuse, index coverage, research aggregation strategy, object storage consistency, and KB concurrency. Add semantic retrieval or reranking based on measured quality gaps, not because the deployment has grown.

## 7.5 What I would change first

These are proposals prioritized from the inspected implementation, not fixes made in this documentation task.

1. **Establish a current release baseline.** Resolve the recorded full-suite failures and verify the actual deployed image/runtime/configuration. The September 5 status entry records 13 failures outside the lecturer redesign; no new test run here establishes their current state.
2. **Reconcile operational documentation with code.** Correct the ten-table model, current course-catalog scope, selection policy, graph persistence description, and effective session-generation override instructions.
3. **Make review job recovery consistent.** Stage reviews have resubmission behavior; explicit Deep Review can become a stale failure after restart. A durable queue/worker contract would make both easier to operate.
4. **Strengthen the API idempotency contract.** Decide whether coach keys must be required, how missing keys are generated/reused, and whether review job keys should replay completed jobs. Keep backward compatibility explicit.
5. **Separate operation/job records from chat rows when justified.** Dedicated request/job tables would make uniqueness, expiry lookup, retention, and reporting clearer. This requires an additive migration and recovery compatibility for old markers.
6. **Move distributed coordination ahead of replicas.** Introduce global and notebook-level admission before increasing worker/container count.
7. **Evaluate retrieval quality and extraction coverage.** Test scanned PDFs, tables, synonyms, multilingual queries, course scope, and citation support before adding complexity.

These priorities reflect reliability boundaries visible in code. A production incident, measured bottleneck, or different product target could change the order.

## 7.6 Why this architecture versus alternatives?

| Alternative | Potential benefit | Cost or risk | When it would be justified here |
|---|---|---|---|
| Everything inside Streamlit | Minimal initial plumbing | UI reruns can become coupled to SQL/model effects; hard to reuse API | Very small disposable prototype, not the current persisted research app |
| Current layered single-origin app | Reusable backend with simple deployment | Single origin and local coordination limit scaling | Controlled pilot and gradual hardening |
| Separate autonomous agent per phase | Specialized behavior and independent reasoning | More calls, context duplication, contested progression authority | Only if evaluated quality benefit exceeds complexity |
| Parallel critic/research agents | Independent checks can run concurrently | Correlated model errors, more costs, synthesis conflicts | Bounded advisory review with a clear reconciliation policy |
| Full CRAG-style pipeline | Correct weak retrieval before answering | Extra evaluator/retrieval calls and new source policy | Demonstrated evidence-retrieval failures where bounded correction helps |
| Generic self-critique pass | Catch some weak answers | The same model can confidently approve its own error | Targeted evaluated checks, not universal reassurance |
| Browser SPA plus FastAPI | Fine-grained UI state, streaming/reconnect control | Separate frontend stack and broader browser-facing API security work | Streamlit DOM/rerun limitations become sustained product cost |
| Serverless request handlers | Elastic short-lived web execution | Long model calls, streaming and job recovery need explicit design | Split short CRUD endpoints from asynchronous generation jobs |
| Container orchestration platform | Replicas, rollout controls, workload separation | Operational overhead and more moving parts | Enough scale/availability need to justify platform ownership |
| Self-hosted inference | Model/runtime control and local processing | GPU capacity, serving reliability and quality responsibility | Data/control requirements or measured workload economics justify it |

These alternatives operate at different layers. CRAG changes retrieval control; multi-agent changes reasoning orchestration; Kubernetes changes deployment; LangGraph changes workflow execution. They are not mutually exclusive substitutes for the same single component.

## 7.7 Latency and cost: follow the full path

Total user wait includes authentication, application reads, source hydration, retrieval, prompt assembly, model generation, validation, persistence, and UI update. A provider returning in five seconds does not prove a five-second end-to-end interaction.

Historical September 4 diagnostics recorded neighboring Fast Chat calls around 4.2–9.7 seconds and a much faster structured-output error. That supports diagnosing that particular error as a harness/structured-result issue rather than simply “the model is slow.” It is dated evidence, not a current performance SLO.

A useful cost model is:

```text
period cost = app hosting + storage + database + retrieval
            + sum(model input tokens × input rate
                  + model output tokens × output rate)
            + runtime/service overhead + observability
```

Use actual provider usage and current rates when budgeting. Token estimates used for context planning are not an invoice. Include retries, repair cycles, explicit reviews, ingestion/embedding where applicable, and idle/warm runtime costs if the service bills them. This handbook makes no dollar-price claim.

Prompt caching is currently disabled in production Compose. Compute affinity is enabled. Those are different optimizations: keeping compute warm is not proof that repeated prompt tokens receive cache billing or processing benefits.

## 7.8 Failure handling playbook

| Symptom | Inspect first | Likely layer; do not assume |
|---|---|---|
| Login returns to login repeatedly | Callback origin, cookie settings, OIDC validation and refresh flow | Identity/configuration |
| Health is 200 but app not ready | Host-local readiness, DSQL marker/schema/grants, storage access | Dependency readiness; health is intentionally lightweight |
| Course summary says evidence unavailable | KB type, filter mode, ingestion path, exact bucket/key validation | Retrieval; visible course files do not prove index readiness |
| A source citation opens wrong/unsupported content | Turn source mapping, retrieved chunks, source identity/version | Citation mapping or grounding |
| Chat succeeds but client reports timeout | Request key, durable marker/result, stream logs | Lost response versus failed generation |
| Duplicate-looking turns | UI key reuse, two distinct keys, internal rows accidentally rendered | Client operation identity or projection |
| 429 during bursts | Per-user/global/notebook category and KB capacity | Admission; raising every limit may worsen tail latency |
| Structured-output failure | Schema version, runtime version, stop reason, cycle telemetry | Contract/harness; not always transport timeout |
| Review stuck after restart | Job type, timestamp, lease/status and resubmission behavior | Background job lifecycle |
| Edited conversation shows stale progress | Revision lineage, memory invalidation, completion projection | Application state consistency |
| UI duplicates or loses scroll position | Fragment/full rerun triggers, widget keys, DOM lifecycle | Frontend reconciliation |

Use correlation IDs to connect observations across layers. Log categories and counts, not full student prompts or raw source content. A reproducible synthetic notebook is often more useful than copying private production text into logs.

## 7.9 Security design considerations

Security boundaries include verified identity, notebook ownership, staff roles, source scope, public routing, upload/URL validation, prompt trust separation, and audited research access. They complement each other.

An injected document instruction cannot grant new API privileges because the runtime has no database/retrieval tools. But it could still influence generated prose, so prompt separation and evaluation matter. A valid Cognito token identifies a user; it does not authorize reading another user's notebook. A private API route reduces exposure; it does not remove the need for authorization when reached internally.

If a future SPA calls FastAPI directly, revisit Caddy/public routing, CSRF protections for cookie-authenticated mutations, CORS, token handling, rate limits, and streaming reconnection. Do not simply expose every internal endpoint and assume the current browser threat model is unchanged.

## 7.10 Release and recovery discipline

Use an immutable image tied to a Git SHA. If runtime assets change, publish to the existing AgentCore runtime, wait for readiness, move DEFAULT, update effective session generation, and recreate the app. Verify image, runtime, guardrail, and configuration separately.

Readiness probes are a gate, not a complete user test. Exercise authentication, a controlled model turn, source/citation flow, movement, persisted state after recreate, and logout. Live inference testing needs an explicit request/cost cap under the repository's operating rules.

Rollback means returning to a known-good image and, when relevant, runtime version with a fresh affinity generation. Additive schema changes should remain compatible rather than attempting destructive schema reversal during an incident. Define which writes occurred after cutover and how they remain readable by the rollback version.

For high availability, define an SLO and recovery targets first. “Scale to more users” is different from “survive an origin failure without noticeable outage.” Database durability, job recovery, session continuity, and origin availability must be evaluated separately.
