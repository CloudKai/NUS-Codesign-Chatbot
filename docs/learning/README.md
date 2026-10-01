# Co-design Chatbot: a learning handbook

This handbook explains the project from the student's screen to the model and database, then explores how to redesign it. It is written for learning, code walkthroughs, and interview preparation.

**Evidence baseline:** repository `Bedrock-v3`, commit `85f79cc`, inspected 7 September 2026. This is a source-code explanation, not verification of what AWS is currently serving. Infrastructure settings supplied outside the repository, current AWS quotas, actual model charges, and the live image/runtime version have not been inspected.

This is a teaching companion to the existing architecture and operations documents, not a replacement specification. Sections explicitly distinguish implemented behavior, historical behavior, and proposed changes. Where an older document disagrees with executable code, the discrepancy is called out rather than silently copied.

## Reading order

| Chapter | What you will learn |
|---|---|
| [1. System and services](01-system-and-services.md) | What the product does; each AWS service, framework, and application service; deployment boundaries; why this design fits a pilot |
| [2. Frontend, API, and a complete turn](02-frontend-api-and-turns.md) | Streamlit rendering, authentication, request validation, streaming, source upload, revisions, lecturer access |
| [3. Retrieval and model context](03-rag-and-context.md) | Actual RAG paths, lexical versus semantic versus hybrid, chunks, catalog scope, citations, budgets, CRAG and Self-RAG |
| [4. Database and idempotency](04-database-and-idempotency.md) | All ten tables, SQL, indexes, DDL, OCC, transactions, retries, leases, failure windows and restart recovery |
| [5. AgentCore and educational workflow](05-agentcore-and-workflow.md) | Bedrock versus Runtime versus harness versus Strands; Fast Chat, Deep Review, prompts, schemas, stages and research feedback |
| [6. Running without AWS and extending LangGraph](06-without-aws-and-langgraph.md) | What already works locally; replacement services; graph design; persistence and migration steps |
| [7. Scaling, operations, and design decisions](07-scaling-and-tradeoffs.md) | Current limits, bottlenecks, capacity math, distributed coordination, queues, observability, cost and security |
| [8. Interview preparation and learning exercises](08-interview-and-study.md) | Short and detailed explanations, likely questions, honest contribution narratives, debugging exercises and glossary |
| [Code-derived reference](REFERENCE.md) | Route inventory, full table definitions and indexes, module index, and dependency pins |

Start with chapters 1–2 to understand the whole product. Read 3–5 while following the linked Python modules. Read 6–8 after you can explain a single request without using the phrase “the AI handles it.” The reference is for lookup, not sequential reading.

## Five corrections that prevent misleading explanations

1. **The database has ten tables.** The older five-table description covers only the original application core. Research and workflow metadata add five more tables.
2. **The application already contains LangGraph.** Its current graph uses an in-memory checkpointer; durable application recovery comes from SQL. Those are different kinds of persistence.
3. **Normal chat does not run a committee of autonomous agents.** The active AgentCore path uses `fast_chat`; several older role modules remain for compatibility.
4. **RAG has multiple meanings here.** Student uploads use local BM25-style lexical ranking. Official course material uses Bedrock Knowledge Base Retrieve. Combining these is composite retrieval; the application does not implement dense-plus-sparse rank fusion itself. Managed KB internals must be distinguished from application code.
5. **Course Library visibility is not personal source selection.** Locked Lecture Notes and Readings are view-only. Course Q&A can bring in the official catalog through a server-owned intent gate; personal uploads use selection, and attachments can be scoped to the current turn.

## How to read an evidence claim

- **Implemented:** a code path or committed configuration supports the statement.
- **Recorded:** an implementation-status entry describes past testing or deployment; it is dated evidence, not a fresh result.
- **Reasoned tradeoff:** an explanation of why the design makes engineering sense. It is not proof of the original author's personal motivation.
- **Proposal:** an alternative that would require implementation and verification.

No production changes, live model calls, student-data queries, or database migrations were made to prepare this handbook. Existing application test results are identified as historical. Documentation validation checks links, syntax/inventory extraction, and agreement with inspected code; it does not certify the running service.

The appendix can be regenerated without importing application settings or accessing a database:

```sh
.venv/bin/python docs/learning/build_reference.py
```

This command writes only `docs/learning/REFERENCE.md`. It parses source text and SQL string literals; it does not execute the application. Review the generated diff after code changes.
