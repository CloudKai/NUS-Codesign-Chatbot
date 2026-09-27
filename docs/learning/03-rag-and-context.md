# 3. Retrieval and model context

[Handbook index](README.md) · [Next: database and idempotency](04-database-and-idempotency.md)

## 3.1 RAG in everyday language

Retrieval-augmented generation means looking up relevant evidence and putting it into the model's input before asking for an answer. The model has general knowledge from training, but a student's interview notes and the exact lecture material need to be supplied. Retrieval chooses a manageable subset rather than sending every document on every turn.

Imagine a tutor with a bookshelf. Retrieval is finding the right paragraphs. Generation is explaining those paragraphs in response to the student's question. Citation handling is recording which book and passage were actually used. Authorization decides which bookshelf the tutor may open. These are separate responsibilities.

RAG does not guarantee a correct answer. The wrong passage can be retrieved; extraction can miss a table; a right passage can be misinterpreted; a citation can point to a real document without supporting the particular claim. Each stage needs its own evaluation.

## 3.2 The actual retrieval architecture

The key source files are [retrieval.py](../../backend/retrieval.py), [bedrock_retrieve.py](../../backend/bedrock_retrieve.py), [retrieval_gate.py](../../backend/retrieval_gate.py), [mode policy](../../backend/coaching/mode_policy.py), and [turn preparation](../../backend/coaching/execution.py).

| Material | Storage | How it becomes eligible | Retrieval implementation |
|---|---|---|---|
| Personal My Sources | Local files in development, S3 in production; metadata in SQL | Selected for the owned notebook | `LocalChunkRetriever`: deterministic lexical ranking of extracted chunks |
| Current-turn attachment | Stored source plus turn attachment association | Included/scoped by the current request and server policy | Text chunks or image input; attachment-only scope can exclude unrelated material |
| Official course material | Shared `course/` objects and a virtual catalog | Course intent causes server-owned catalog inclusion | `BedrockKnowledgeBaseRetriever` via Retrieve |
| Ordinary project discussion | Durable transcript plus derived memory | Current notebook conversation | Retrieval may be skipped; bounded history supplies continuity |

`CompositeContextRetriever` splits course sources from student sources, calls the appropriate adapters, and formats compatible chunks. It currently processes the KB branch and local branch sequentially in its implementation. It does not perform application-owned reciprocal-rank fusion of dense and sparse candidates.

Older RAG docs repeatedly say “selected course sources.” At the adapter boundary that still describes the request's authorized source scope. At the current UI boundary, locked course entries are not user-selected checkboxes. `TurnSnapshot` excludes locked course rows from personal selection; `_hydrate_retrieval_sources(..., include_course_catalog=True)` supplies the course catalog when policy requires it. This distinction is essential when explaining the current product.

## 3.3 Lexical, semantic, hybrid, and composite are different

**Lexical retrieval** matches words or phrases. A query containing “pedestrian crossing” strongly matches a chunk containing those words. It is useful for exact terminology, identifiers, and reproducible local tests. It can miss synonyms: “older adults” and “elderly pedestrians” may be semantically related while sharing few terms.

**Semantic retrieval** uses meaning-oriented representations or a managed semantic retrieval system. A common implementation embeds text into vectors and searches for similar vectors. Embeddings represent text as lists of numbers, not stored prose. Vector similarity is a relevance signal, not truth.

**Hybrid search**, in its usual retrieval sense, combines lexical and semantic signals for the same search corpus. The application here does not implement a local vector index plus BM25 fusion. It delegates course retrieval to a managed KB and uses lexical retrieval for personal uploads.

**Composite retrieval** means combining retrieval backends or source groups. That is the directly evidenced application design here. **Hybrid model selection** can also mean using a smaller model for chat and a stronger model for review; that has nothing to do with hybrid search.

AWS describes its managed KB Retrieve connector as hybrid search. That is useful service-level context, but this repository's adapter does not reveal the live embedding model, internal ranking, ingestion chunk configuration, or backing index. It also does not install an AgentCore Gateway connector: it calls Retrieve from FastAPI. Say “managed KB retrieval for courses plus lexical retrieval for student uploads,” and qualify any more specific claim about deployed KB internals. [AWS managed KB connector documentation](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/gateway-add-target-api-target-config.html)

## 3.4 How personal text becomes chunks

The source importer saves raw bytes, extracts text, and can write `derived/chunks.v1.json`. A valid chunk artifact avoids reconstructing chunks every query; an invalid/missing artifact falls back to chunking extracted text. The chunk cache is an optimization, not the authoritative source of document bytes.

`LocalChunkRetriever` defaults to chunks around 1,800 characters with 220 characters of overlap, and the chunking function tries to respect text boundaries. Character limits are not token limits. Tokens are the model's encoding units; the same number of characters can produce different token counts across languages and content.

Overlap preserves context around a boundary. Without overlap, a paragraph ending “the following assumption was rejected” might be separated from the next sentence explaining the assumption. Too much overlap repeats evidence and wastes context space. Too-small chunks lose meaning; too-large chunks dilute relevance and consume model budget.

The extractor has practical coverage limits. Word paragraph extraction does not imply every table/header is represented. Spreadsheet cached formula values are not a recalculation engine. Text extraction from a PDF is not full visual interpretation of its charts. A useful improvement would evaluate tables, scanned PDFs, and slide diagrams explicitly rather than assume a document's text is complete.

## 3.5 The student ranking algorithm, explained

The implementation is **BM25-style**, not a claim of exact standard BM25. Its score combines:

1. Weighted query-term overlap.
2. Higher value for terms appearing in fewer candidate chunks.
3. A frequency saturation/length normalization term.
4. Title boosts.
5. Adjacent-word pair boosts in text and titles.

For a matched term, the inspected code uses:

```text
inverse_frequency = log(1 + (N - df + 0.5) / (df + 0.5))
length_factor = max(0.7, number_of_distinct_terms_in_chunk / 180)
normalized_tf = term_frequency / (term_frequency + 1.2 * length_factor)
term_contribution = query_weight * inverse_frequency * normalized_tf
```

`N` is the candidate count; `df` is the number of candidates containing the term. A rare topic word gets more weight than a word present everywhere. Repeating a word helps only up to a point because frequency is normalized. The implementation uses distinct-term count in its length factor, so calling this textbook BM25 would hide a real difference.

The code adds a 0.8 weighted title-term boost, 1.25 for matching text bigrams, and 2.0 for title bigrams. Stemming, stop-word removal, and session aliases such as lecture/week numbering improve matching. Ties are resolved deterministically by source/chunk order.

Selection favors source diversity: first pick a strong chunk from different relevant sources, then fill remaining capacity with more evidence, subject to per-source limits. The class default is up to eight chunks and two per source; normal Fast Chat applies tighter four-chunk / 8,000-character budgets. Distinguish constructor defaults from the configured caller's effective limits.

If no chunk has positive lexical score, the local adapter has a representative-beginnings fallback. This helps “summarize these sources,” but it can also deliver weak evidence. Therefore “retriever returned something” must not be equated with “retriever found strong support.” Evaluation should include unrelated questions and generic summaries.

## 3.6 Course Knowledge Base retrieval

Official course objects live under the shared course namespace. The application does not duplicate a PDF for every notebook. Catalog rows can be virtual and intentionally contain no extracted text. A missing KB must yield an evidence gap for those objects, not a fabricated chunk based on display placeholder text.

The adapter calls **Retrieve**, which returns evidence. It does not call **RetrieveAndGenerate**, which would also ask the service to generate an answer. Keeping generation separate allows FastAPI to retain citation mapping, context limits, and the educational output contract. AWS documents Retrieve as a standalone retrieval operation. [AWS Retrieve documentation](https://docs.aws.amazon.com/bedrock/latest/userguide/kb-test-retrieve.html)

The checked production config declares `KNOWLEDGE_BASE_TYPE=MANAGED`. The adapter selects `managedSearchConfiguration` for that type, and `vectorSearchConfiguration` for a VECTOR KB. Do not infer that a VECTOR payload is appropriate merely because RAG often uses vectors.

The metadata identifier `course_material_id` is derived from object keys, including nested path components to avoid filename collisions. Sibling `.metadata.json` files accompany course objects for ingestion. The request can filter by one ID using `equals` or several IDs using `in`.

Three explicit filter modes exist:

| Mode | Behavior | Tradeoff |
|---|---|---|
| `required` | Send the metadata filter; retrieval failure becomes an evidence gap | Strong intended retrieval scope; needs properly ingested metadata |
| `degraded_unfiltered` | Retrieve without that filter, then validate bucket and object key | Temporary recall/efficiency compromise; unauthorized hits are still rejected |
| `disabled` | Do not retrieve | Course grounding unavailable |

There is no hidden automatic unfiltered retry after a required-filter error. That would silently change scope and mask operational problems.

Every surviving KB hit is checked against the expected course bucket and authorized object key. A metadata filter improves precision; it is not the authorization boundary. An old export path and the new `course/` path are different objects even if their filenames match. The application must not “repair” mismatches by guessing.

## 3.7 Why there is a retrieval gate

“I think my target user feels rushed” can be coached without searching every course file. “According to Week 2, what is a job story?” needs course evidence. Retrieving for every selected-source notebook adds latency and can turn an ordinary coaching prompt into an unnecessary evidence-gap answer.

The gate is deterministic Python matching, not an extra LLM router. It recognizes course/source names, citations, definitions, and narrow summary requests, while treating personal reasoning and generic help conservatively. It also accounts for titles, attachments, and workflow navigation through the broader mode policy.

A deterministic gate is cheap, inspectable, and testable. Its weakness is language coverage: unusual phrasing, multilingual queries, and ambiguous references can be missed. Those cases should become evaluation examples rather than an ever-growing unmeasured list of regexes.

If the first Fast Chat response says `needs_source_retrieval=true` after retrieval was skipped, the application can retrieve and invoke again within its outer-call budget. The provisional first result is not persisted as the final turn. Runtime agents still do not search the KB themselves.

This is a bounded corrective fallback. It is not the complete CRAG algorithm. Recovery from a transient structured-output harness error shares the two-outer-invocation budget, so not every recovery path can independently add another call.

## 3.8 Citations and evidence integrity

The internal chunk record includes source ID, request label, title, chunk ID, text, score, origin, and optional location fields. `[S1]` is a convenient label for a source in the request; it is not a globally permanent database identifier. Internal IDs such as `S1-C2` distinguish chunks for auditing.

The application records two related things: `retrieval_refs` describe evidence supplied to the model, while `source_refs` describe validated citations actually used. A supplied source may not be cited. A model-invented source label must not become a working citation merely because it looks syntactically correct.

Citation resolution uses the request's source snapshot and retrieved evidence. It should not fetch a changing catalog again after generation and accidentally map a label onto different content. A snapshot also reduces repeated source reads.

Structural validation answers “is this an allowed, supplied source?” It does not fully answer “does this excerpt logically support every associated claim?” A future groundedness evaluator should measure support at the claim level without weakening the existing authorization checks.

## 3.9 Memory is not RAG, and storage is not context

The entire active transcript can be stored while only part is sent to the model. Fast Chat configuration uses up to six recent verbatim messages, around 3,000 estimated history tokens, and up to 1,500 per historical message, plus derived conversation memory. Total Fast Chat input has a 12,000-token soft target and 16,000-token maximum in Compose.

Conversation memory is a summary/projection, not a replacement transcript. It should be invalidated after a revision because the old summary may contain superseded reasoning. Deep Review uses its own larger planning strategy, including full-history or checkpoint-plus-delta context depending on eligibility and size.

Retrieval finds document evidence; recent history preserves dialogue; derived memory preserves compressed continuity. A prior assistant assertion is not valid course evidence just because it is in memory. An evidence gap should remain visible when course-grounded answering is required.

## 3.10 What CRAG, Self-RAG, and feedback would change

CRAG adds retrieval-quality evaluation and corrective behavior, including alternate retrieval strategies when evidence is poor. Its paper includes a retrieval evaluator and corrective actions; this project does not implement that full method. For this educational app, a bounded evaluator could label evidence sufficient/insufficient and retry within the course corpus. Open-web fallback would require a deliberate new source policy. [CRAG paper](https://arxiv.org/abs/2401.15884)

Self-RAG is a specific method that learns retrieval and reflection behavior using special reflection tokens. A prompt saying “check your answer” is not equivalent to implementing that training/inference method. A simpler proposal here is a small, separately evaluated groundedness check for selected tasks. [Self-RAG paper](https://arxiv.org/abs/2310.11511)

Student learning feedback, lecturer research coding, retrieval evaluation, model self-critique, and model fine-tuning are different feedback loops. Existing research review does not automatically update model weights. To use lecturer judgments for improvement, define an offline labeled evaluation set, record prompt/model versions, compare candidates, and approve a release. Do not allow one noisy judgment to alter the production coach immediately.

## 3.11 How to evaluate and improve this RAG

Create questions with known relevant chunks, including synonyms, exact lecture identifiers, mixed course/personal evidence, attachment references, and questions with no supporting source. Measure retrieval recall@k, precision@k, wrong-source rate, citation support, evidence-gap honesty, latency, and cost per answer. Evaluate the gate separately: how often did it retrieve needlessly, or skip when evidence was required?

A plausible improvement experiment is adding an embedding retriever for personal uploads, preserving notebook filters, then fusing lexical and semantic ranks. Reciprocal rank fusion could combine ranks without assuming the two score scales are comparable. That is a proposal, not current code. Compare it against the existing lexical baseline before accepting extra embedding storage, ingestion latency, and deletion complexity.

Other focused improvements include table-aware extraction, OCR for scanned PDFs, a small reranker, multilingual gate tests, explicit evidence-coverage warnings, and caching shared catalog metadata. Each should have a measured failure case. “Use a vector database” by itself does not explain which current problem it solves.
