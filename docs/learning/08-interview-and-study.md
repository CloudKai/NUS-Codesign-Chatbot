# 8. Interview preparation and a practical study plan

[Handbook index](README.md) · [Code reference](REFERENCE.md)

## 8.1 A thirty-second project explanation

“This is a design-thinking learning notebook built with Streamlit and FastAPI. Students discuss a project, use evidence, and receive structured formative coaching across five phases. The backend owns identity, retrieval, stage state, and durable conversation history. Production uses DSQL and S3 for persistence and a constrained AgentCore runtime for Bedrock generation. I focused on making the AI interaction behave like a reliable application: grounded citations, safe retries, revision history, and recoverable state.”

Use first person only for work you actually did or owned. The repository establishes what the project contains; it does not establish which collaborator authored every part or how many hours you personally spent.

## 8.2 A two-minute architecture explanation

“The browser connects through CloudFront and Caddy to Streamlit. Streamlit calls a private FastAPI API inside the application container. Cognito identifies the user, and the backend loads the owned notebook from DSQL. On a chat turn, it reloads canonical stage, history, and source scope rather than trusting those fields from the client.

“Retrieval is selective. Personal uploads use BM25-style lexical chunks, while course questions use the official course catalog through Bedrock Knowledge Base Retrieve. The application validates source locations and maps evidence to citation labels. It then sends a bounded context to the generation runtime.

“Normal generation is one outer Fast Chat invocation with a structured result, rather than a multi-agent chain. A bounded fallback can retrieve if the first pass needs evidence. The application validates the result and persists the user/assistant pair, assessment, citations, and progression metadata transactionally.

“Retries use a stable idempotency key, request fingerprint, and SQL lease. Message edits create append-only revisions. The main current scaling limitation is the single-origin process model: rate limits and review execution include local state. Before adding replicas I would introduce distributed notebook coordination and durable job workers.”

## 8.3 What is the hardest engineering problem?

A strong answer identifies an invariant and a concrete failure, rather than saying “integrating AWS.” For example:

“A model call can finish after the browser times out or after the student edits the conversation. I needed to separate the slow external generation from the database commit. A durable request reservation lets an exact retry replay; a lease token rejects a stale worker; a conversation revision rejects an answer generated against old history. That preserves coherent learning state even when network delivery is unreliable.”

Explain the limitation too: a crash after generation but before database persistence can still cause another paid call. The guarantee is controlled durable effects, not magical exactly-once execution across every external service.

## 8.4 What did I spend the most time on?

The Git log and implementation-status entries show repeated work in these areas:

| Evidence theme | Examples visible in the repository history | Interview framing |
|---|---|---|
| Streamlit interaction reliability | Rerun/remount flicker, stacked workspaces, composer focus, mobile scroll, dialogs, pagination | “Making asynchronous chat feel stable in a rerun-based UI required careful state and lifecycle work.” |
| Learning-state integrity | Ready/move behavior, HMW guards, Guide/Free policy, Reflection completion, revisited checkpoints | “I translated educational requirements into explicit state rules and tested edge cases.” |
| Persistence and retries | DSQL SQL compatibility, idempotency, revisions, recovery, research atomicity | “I worked on correctness under retries and concurrent changes, not just happy-path saves.” |
| Runtime output reliability | Structured schemas, bounded recovery, timeout alignment, runtime publication | “I debugged the boundary between SDK behavior, model output, and application contracts.” |
| Retrieval scope | Course catalog versus personal selection, attachment isolation, metadata filters, citation mapping | “I made evidence access explicit so visible material did not automatically become model context.” |
| Lecturer experience | Lazy roster/workbench reads, DSQL queries, review projections, responsive layouts | “I extended the student notebook into an attributable research and teaching interface.” |

This supports saying these were recurring engineering themes. Commit frequency is not a timesheet, and a large commit can contain more work than many small fixes. To claim the single largest time investment, use your own records. The latest inspected history includes consolidated commits, so precise time attribution from Git alone would be unreliable.

## 8.5 Interview questions with defensible answers

### Q1. Why separate Streamlit from FastAPI?

Streamlit handles rendering and interaction, while FastAPI supplies a reusable, authenticated application boundary. This lets tests exercise business behavior without browser reruns and allows a future frontend to reuse the backend. It costs an extra client/server boundary and requires careful owner/cookie forwarding.

Follow-up: separate code layers do not necessarily mean separate deployments. Today both processes share one app container.

### Q2. Why SQL instead of putting chat history in AgentCore memory?

The notebook needs exact active/historical messages, revisions, atomic learning-state updates, research provenance, and replayable request results. SQL gives an explicit system of record. Runtime memory can disappear or retain outdated assets; it is useful for compute optimization but should not determine which transcript is true.

### Q3. Why SQLite locally and DSQL in production?

SQLite makes isolated local development and deterministic tests straightforward. DSQL is the chosen production SQL service accessed through IAM and the project's compatibility adapter. The application preserves a common logical model. This creates portability work because DSQL has different DDL, index, and foreign-key assumptions in this implementation.

Do not claim DSQL was objectively the cheapest or fastest option without measurements. PostgreSQL would be a reasonable alternative to evaluate when reducing AWS dependence.

### Q4. Is your RAG hybrid?

“At application level it is composite: managed course KB retrieval plus lexical student-source retrieval. The local ranker is BM25-style with title/phrase boosts and diversity limits. It does not implement dense-plus-sparse rank fusion. Any managed KB hybrid behavior belongs to that service; I would verify live configuration before naming embedding or index details.”

### Q5. Why not retrieve on every turn?

Many turns are personal reflection or navigation, not document questions. Unnecessary retrieval adds latency and can inject unrelated evidence. A deterministic gate handles clear source needs, with a bounded model-requested retrieval fallback for misses. The tradeoff is gate recall, especially with ambiguous or multilingual phrasing.

### Q6. How do you stop hallucinations?

You cannot guarantee zero hallucinations. You reduce unsupported answers through authorized retrieval, bounded evidence, citation validation, clear evidence-gap behavior, output contracts, and groundedness evaluation. Citation validation proves the source was allowed and supplied, not that every claim is entailed. Distinguish these guarantees.

### Q7. How do you prevent duplicate messages?

Use one stable key per logical send, fingerprint the request, reserve a deterministic SQL marker, and let only the lease owner commit. Same-key completed retries replay. Store the exact result with the turn transaction. Missing keys and distinct keys need separate handling; don't claim all POST endpoints are automatically idempotent.

### Q8. Why do you need both idempotency and a revision number?

Idempotency answers whether this logical operation already completed. Revision checks answer whether the state used to generate its answer is still current. A unique request can still be stale after the student edits an earlier message. Both protections are needed.

### Q9. What happens if the process crashes?

Committed SQL records remain, and keyed requests can replay/recover them. Uncommitted work can retry after a lease expires. In-memory graph state is lost. Stage-review queues can be resubmitted through their recovery path; explicit Deep Review can become a stale failed job and require retry. A running Streamlit interaction is not durably preserved as a browser session.

### Q10. Is it multi-agent?

The active normal chat path is a constrained Fast Chat invocation; it internally selects the response mode within its output contract. Legacy specialist modules exist, and Deep Review is a separate task, but this is not an autonomous agent committee negotiating every student turn. The application owns progression and source access.

### Q11. Why not CRAG or a critic agent?

Add it if measured retrieval or answer-quality failures justify the extra cost and latency. The existing fallback corrects some skipped-retrieval cases, but is not full CRAG. A bounded evaluator over the authorized corpus is a plausible experiment. An unrestricted web-search critic would change the source policy and research reproducibility.

### Q12. What does LangGraph add here?

It makes the assessment/recommendation execution structure explicit and inspectable. Today its graph is small and uses in-memory checkpoints. A larger durable graph could expose retrieval branches and resume long tasks, but it must preserve existing SQL idempotency and ownership rather than replacing them by assumption.

### Q13. How would you remove AWS?

Keep the API/domain contracts. Replace identity with another OIDC implementation, DSQL with an explicitly supported SQL adapter, S3 with a file/object adapter, KB retrieval with a course retriever, and AgentCore with a generation adapter. Extend the production validator for the new stack. LangGraph alone does not replace those services.

### Q14. How would you scale to 1,000 students?

First specify send rate, burst pattern, latency target, and review workload. Measure current bottlenecks. Add distributed admission and notebook fencing, durable review/extraction workers, and a session strategy before replicas. Scale API, UI, retrieval, and model capacity independently where useful. Verify provider quotas and costs rather than deriving capacity from a setting named 120.

### Q15. Why not just add Redis?

Redis could implement shared counters or a coordination adapter, but it is not a complete concurrency design. Define key scope, lease expiry/renewal, fencing, crash recovery, and how SQL commit validates ownership. Keep the database's durable operation result authoritative even if the coordination cache restarts.

### Q16. What if S3 deletion fails after database deletion?

The application must treat object cleanup as retryable work. SQL and S3 do not share a transaction. A durable outbox is a useful future improvement to guarantee cleanup attempts survive process failure. Don't roll back unrelated successful SQL work by pretending external deletion was transactional.

### Q17. How do you test without paying for models?

Use deterministic mock providers, temporary SQLite databases, fake storage and OIDC adapters, HTTP contract tests, persistence tests, and Streamlit AppTest/browser fixtures. Test invalid outputs, wrong owners, revisions, retries, missing evidence, and restart boundaries. Separate live quality evaluation from deterministic correctness tests and give it an explicit budget.

### Q18. How do you know a deployment includes your fix?

Check the app image's immutable Git revision and the actual AgentCore DEFAULT version separately. A prompt change requires a runtime publication; UI/backend changes require an image release. Verify effective affinity generation so warm runtime sessions do not retain old assets. A successful Git push proves neither service is updated.

### Q19. Is the UI streaming model tokens?

The inspected coach route streams NDJSON progress and a final validated/persisted turn. It is not raw token streaming. A later stream error can appear inside an HTTP 200 response, so the client must process event types and terminal state.

### Q20. How do you protect students from each other?

Cognito establishes identity; owner-scoped services validate notebook access; retrieval uses authorized source scope; object keys are generated under owner/notebook namespaces; staff routes check persisted roles; research reads audit access. Prompt instructions alone are not an access-control boundary.

### Q21. What would you improve in your data model?

Dedicated operation/job tables would clarify request uniqueness, expiry lookup, and job recovery. Frequently queried JSON fields could become explicit columns or projections. I would preserve revisions, provenance, and additive migration compatibility. The right change depends on measured queries and operational pain, not a preference for more tables.

### Q22. How would you measure educational quality?

Use phase-specific examples and human-reviewed criteria: does the coach elicit reasoning, distinguish evidence from assumptions, avoid writing the assignment, keep the student's agency, and respect progression policy? Compare model/prompt versions on a fixed evaluation set. Research coding disagreement and student outcome measures are separate from API success rates.

### Q23. What is your most important tradeoff?

A defensible choice is centralizing authority in the application while constraining generation. It limits autonomous model flexibility but makes ownership, citations, transitions, and retries easier to test and explain. Another is Streamlit speed of development versus increasingly complex UI lifecycle handling. Pick the one you can support with a specific example.

### Q24. What evidence would change your architecture decision?

Repeated measured semantic misses could justify hybrid student retrieval. Sustained DOM/rerun maintenance could justify a SPA. Review jobs lost during deployments could justify a durable queue. Model-context latency could justify better compression. Independent reasoning tasks with demonstrated quality gains could justify parallel agents. State a trigger and a measurement for each change.

## 8.6 Three STAR-style stories to personalize

**Retry correctness.** Situation: a network timeout made it unclear whether Send had completed. Task: recover the result without duplicate learning records. Action: explain the stable key, fingerprint, SQL reservation, lease and atomic turn result. Result: cite the actual relevant deterministic tests or an observed incident; do not invent a percentage reduction in duplicates.

**Frontend reliability.** Situation: a background panel refresh could remount the workspace during a chat turn. Task: maintain a stable composer/transcript across streaming and mobile use. Action: separate fragment reruns from app reruns, preserve widget keys, and test viewport/scroll behavior. Result: cite dated browser evidence from the status log, identifying fixture versus authenticated production checks.

**Grounding integrity.** Situation: course-library visibility and personal selection were being conflated. Task: ensure source questions use the right evidence without contaminating personal attachment scope. Action: separate view-only course catalog, selected personal sources, and turn-scoped attachments; validate KB bucket/key and citations. Result: cite the course-context regression tests and explain what still requires a live ingestion check.

## 8.7 Read the code in this order

1. Read [streamlit_app.py](../../streamlit_app.py) and sketch its auth/staff/student branches.
2. Read the normal coach and stream handlers in [http/app.py](../../backend/http/app.py). Identify which errors happen before and after streaming starts.
3. Trace `submit` into `_submit_body` and `_submit_once` in [execution.py](../../backend/coaching/execution.py).
4. Follow `_prepare_authoritative_turn` and the [TurnSnapshot](../../backend/coaching/turn_snapshot.py). Identify what is trusted and where it came from.
5. Read [LocalChunkRetriever](../../backend/retrieval.py) and the KB request/validation path in [bedrock_retrieve.py](../../backend/bedrock_retrieve.py).
6. Follow [workflow.py](../../backend/workflow.py) into [agentcore_provider.py](../../backend/agentcore_provider.py), then [runtime main](../../agentcore_runtime/main.py).
7. Read `claim_coach_request`, `persist_coach_turn`, and revision helpers in [student_store.py](../../backend/student_store.py).
8. Compare [stage review jobs](../../backend/coaching/stage_review_jobs.py) with [Deep Review jobs](../../backend/coaching/deep_review_jobs.py).
9. Read [compose.prod.yaml](../../compose.prod.yaml) and [Caddyfile](../../Caddyfile), then explain why private coach routes remain usable from Streamlit.

## 8.8 Exercises that test real understanding

**Draw a lost-response timeline.** Place model completion, SQL commit, marker completion, and browser receipt on a line. Simulate a crash between every adjacent pair. Explain what the next request should do. Answer: completed SQL effects can replay; a model result lost before persistence may require another call.

**Explain a source mismatch.** The KB returns `export/week1.pdf`, while the catalog authorizes `course/readings/week1.pdf`. Should the application accept it because the filename matches? Answer: no; source identity requires the approved bucket/key, not filename similarity.

**Find the meaning of 120.** Does it mean model tokens, users, API requests per second, or workflows? Answer: the global local active workflow ceiling. Then find the smaller KB executor limit and explain the bottleneck.

**Follow a revision.** Write three user/assistant pairs, edit the first user message, and mark which rows stay active. Answer: historical content is retained, but future rows from the superseded path no longer belong to the active projection; derived state must align with the new revision.

**Compare two recoveries.** Restart during a queued stage review and during a queued explicit Deep Review. Answer: their current recovery policies differ; persistent metadata alone does not guarantee resubmission.

**Check a deployment assumption.** Change only the host generation variable while Compose explicitly defines the same variable. Which wins? Answer: the explicit Compose environment entry. Inspect effective configuration before claiming the runtime uses the new value.

**Design a retrieval experiment.** Use ten synonym-heavy questions and ten exact lecture-name questions. Compare lexical baseline with a proposed semantic/hybrid candidate, holding source scope and generation constant. Answer: measure retrieval quality independently so model prose does not hide a retrieval regression.

## 8.9 Glossary

| Term | Meaning here |
|---|---|
| Adapter | Implementation translating a stable application interface into a service-specific call |
| Application service | Coordinates a use case such as submitting a coach turn |
| ASGI | Server/application interface used by Uvicorn and FastAPI |
| Atomic | Related database changes commit together or not at all |
| Authentication | Establish who the caller is |
| Authorization | Decide what that caller may access or do |
| Backpressure | Refuse or delay work when downstream capacity is full |
| Checkpoint | Saved execution state; durability depends on its storage |
| Citation provenance | Trace from displayed source label to supplied evidence and source identity |
| Compare-and-swap | Apply an update only if the expected previous version still matches |
| DDL | Schema operations such as CREATE TABLE and ALTER TABLE |
| DML | Record operations such as INSERT, UPDATE, and DELETE |
| Derived state | Rebuildable summary/projection of authoritative data |
| Embedding | Numeric representation used for meaning-oriented similarity |
| Fencing | Reject writes from a worker whose ownership/version is stale |
| Fingerprint | Stable digest used to compare request identity/content |
| Idempotency key | Identity of one logical operation across retries |
| Inference | Running a model to obtain output |
| Lease | Time-limited right to execute/commit an operation |
| Middleware | Code around request/model processing that adds shared behavior |
| NDJSON | One JSON value per line, useful for incremental event responses |
| OCC | Optimistic concurrency control; conflicts can require a transaction retry |
| OIDC | Identity protocol layered on OAuth 2.0 |
| Outbox | Durable record of external work saved in the same transaction as application changes |
| Port / Protocol | Narrow interface expressing what the application needs |
| Projection | Read-oriented transformation of stored data for a surface or report |
| RAG | Retrieve relevant evidence, then generate using it |
| Revision | Identifier of an active/historical conversation branch |
| SLO | Measurable service reliability/performance objective |
| Source of truth | Authoritative record used to resolve conflicting representations |
| Stateless invocation | Receives the needed context rather than relying on hidden previous conversation memory |
| TTL | Time to live; an expiry policy, not proof of physical deletion at that instant |
| WebSocket | Long-lived bidirectional browser/server connection used by interactive UI infrastructure |

## 8.10 Claims to avoid

Avoid “all requests execute exactly once,” “we have fully durable LangGraph resume,” “the UI streams every model token,” “the system is a multi-agent architecture because there are specialist files,” “the database has only five tables,” “all uploads use vector search,” and “120 means we proved support for 120 concurrent students.”

Replace each with the specific, bounded behavior you can explain from the code. That precision is one of the strongest ways to demonstrate you understand the project beyond its list of technologies.
