# Hosting plan for two course modules

## Two course modules on one deployment

Use one Singapore-hosted application, one database, one login and one custom hostname. Give each module a stable entry path such as `/m/cde2300` and `/m/<second-module-code>`. These are proposed routes. Students enrolled in both can switch modules. Each module opens its own chats, notebooks, course readings and Review. One hostname lets both course teams publish permanent links even if the host changes.

**First implementation change:** introduce a module record and module membership with student and lecturer roles. Bind each workspace to its module on the server. Verify membership and existing owner permissions on reads, writes, downloads, exports and lecturer reports. Scope guest invitations and sessions to the intended module. Before migrating existing records, take a backup and verify which cohort owns them. Leave ambiguous records inaccessible to the new module pending reconciliation.

**Course materials and coaching.** Production currently selects one course prefix and one Knowledge Base ID for the deployment. Resolve the allowed corpus from the authenticated workspace before searching, and include module scope in citation lookups and cache keys. Each lecturer maintains their own readings, assignments and rubric. Share the coaching workflow and model routing where the learning objectives fit. Validate the five-stage Thinking Path with the second lecturer before enabling Project coaching there. [Current settings](../../backend/settings.py) · [Production configuration](../../compose.prod.yaml)

**Combined budget and capacity.** Assuming S$30 covers both modules and 30 generation calls per enrollment per month, the 90% Luna / 10% Sol example below is US$3.83 for 80 enrollments total and US$7.66 for 80 per module. The same student taking both modules counts twice if they use both allowances. Track calls and spending per module against a shared ceiling. Budget storage and ingestion for both sets of readings. Rehearse overlapping classes at the combined peak if their schedules coincide.

**Release check.** Put different readings with identical filenames in both modules. Verify retrieval and citations with a student in each and one enrolled in both. Try switching modules, following a saved link and opening a lecturer export. Verify that private notebooks retain owner restrictions within each module and that authorized history survives a restart before sharing the second link.

## Recommended stack for 80 students

Updated 2026-11-19. **Keep the AWS stack for the next class while credits cover it.** For the semester after credits, first compare the gross AWS bill with the S$30 monthly ceiling. If the existing stack fits with headroom and passes the classroom gate, keep it. Otherwise benchmark the following single-VM design. The team can maintain a VM. Region approval, available capacity, workload and recurring costs still determine whether to adopt it.

| Layer | Recommendation | Benefit and trade-off |
| --- | --- | --- |
| Web and hosting | Run the existing Caddy, React build, FastAPI and protected Streamlit on one Oracle Cloud Ampere A1 VM. Check ARM64 image and dependency compatibility first. | Preserves URLs, streaming and lecturer tools. Oracle documents a free allowance equivalent to 2 OCPUs and 12 GB RAM. Capacity depends on the home region and idle instances can be reclaimed. One VM creates a shared failure point. [Oracle free resources](https://docs.oracle.com/en-us/iaas/Content/FreeTier/freetier_topic-Always_Free_Resources.htm) |
| Database | Use PostgreSQL on a persistent volume for notebooks, chat history, learning evidence, consent/audit records and request coordination. Keep DSQL authoritative until migration is verified. | One database to back up and operate. Generic PostgreSQL needs a production adapter and concurrency tests. The DSQL adapter and the local SQLite setup are separate implementations. |
| Files and identity | Keep existing S3 objects and Cognito accounts initially. Preserve object keys, owner IDs, guest expiry and lecturer authorization. Keep an encrypted off-host database backup and rehearse restoring it alongside the matching files. | Avoids re-uploading student work or remapping logins during the host move. Include cross-cloud traffic, backup storage and auth in the bill. Confirm permitted locations for files, backups and model processing. |
| RAG | Start with PostgreSQL full-text search for official course PDFs. Extract text once per document revision and retain course, version and page metadata. Keep the existing selected-source retrieval for private notebook files. Add pgvector and embeddings only if paraphrased questions miss relevant pages in evaluation. | No separate vector service to operate. Page-level results support inspectable citations. Lexical search can miss conceptual matches. A managed third-party retriever becomes worthwhile if it measurably improves recall or reduces maintenance within budget. |
| AI and workflow | Benchmark Luna for routine coaching and Sol for requested reviews against the current Haiku and Sonnet setup. Keep the single workflow, structured responses and explicit stage confirmation. | Put more model budget into reasoning feedback and measure quality with the lecturer. Opening saved Review makes no additional generation call. |

The quoted free 2 OCPU / 12 GB allowance belongs to Oracle. Cloudflare Containers requires Workers Paid and meters usage. Moving the static frontend alone would leave the Python API, lecturer sessions and durable state to host elsewhere. [Cloudflare Containers pricing](https://developers.cloudflare.com/containers/platform/pricing/)

### Singapore deployment, coaching models and student URL

For Singapore hosting, benchmark Oracle A1 in a Singapore home region if the free shape is available to the tenancy. Put the app, PostgreSQL, course index and off-host backups in approved Singapore locations. The existing configuration targets Oregon. If local residency is required, inventory and migrate student files, identity data and logs as well. Keeping existing US services is an option only if the institution permits it. Oracle lists both Singapore and Singapore West. [Oracle regions](https://docs.oracle.com/en-us/iaas/Content/General/Concepts/regions.htm) · [Always Free constraints](https://docs.oracle.com/en-us/iaas/Content/FreeTier/freetier_topic-Always_Free_Resources.htm)

For the upcoming AWS class, keep Haiku 4.5 for routine Project coaching and Sonnet 4.6 for requested Deep Review if global inference is approved. These are already configured in [production Compose](../../compose.prod.yaml). AWS lists only global routing from Singapore for both models on the Bedrock runtime endpoint. A Singapore web host therefore does not establish Singapore-only AI processing. Require documented in-country inference for the exact endpoint and model if prompts must stay in Singapore. [Haiku availability](https://docs.aws.amazon.com/bedrock/latest/userguide/model-card-anthropic-claude-haiku-4-5.html) · [Sonnet availability](https://docs.aws.amazon.com/bedrock/latest/userguide/model-card-anthropic-claude-sonnet-4-6.html)

For the cash-funded pilot, prioritize GPT-6 Luna for ordinary coaching and GPT-6.2 Sol for requested reviews over the earlier nano/mini shortlist. Compare blinded responses against Haiku and Sonnet for a vague problem statement, conflicting stakeholder evidence and an unsupported request to advance. Have the lecturer score source use, whether the coach asks a productive next question, and whether it leaves the decision to the student. The [app registry](../../backend/models.py) currently labels its default GPT-5.6 Luna. Resolve and log the actual provider/model per operation before evaluating or billing.

| Model | Suggested role | Illustrative USD for 2,400 calls using only this model |
| --- | --- | ---: |
| GPT-6 Luna | Routine Project coaching challenger | $1.32 |
| GPT-6.2 Sol | Complex reasoning or requested review challenger | $26.40 |
| Claude Haiku 4.5 | Current AWS coaching baseline | $13.20 |
| Claude Sonnet 4.6 | Current AWS Deep Review baseline | $39.60 |

At 3,000 input and 500 total billable output tokens per call, a 90% Luna / 10% Sol mix costs about US$3.83 monthly for generation. Claude estimates use Anthropic's direct base rates. Validate AWS charges from the actual billing profile. All estimates exclude hosting, tools, retries and tax. [OpenAI model prices](https://developers.openai.com/api/docs/models) · [Anthropic prices](https://platform.claude.com/docs/en/about-claude/pricing)

Use one student-facing hostname across hosts. Request a university-managed course subdomain such as `codesign.nus.edu.sg` (illustrative, subject to NUS approval). An owned domain can use `coach.<your-domain>`; budget its annual renewal divided by twelve. For the current deployment, attach the hostname and a matching ACM viewer certificate in `us-east-1` to CloudFront, point the DNS alias/CNAME to the distribution, set `PUBLIC_ORIGIN` and register the matching Cognito callback and sign-out URLs. Test HTTPS, guest access, registered login/logout, streamed replies and protected lecturer access before sharing the link. Guest cookies belong to the old hostname, so arrange a transition for students with existing guest work. For a later direct VM origin, configure HTTPS on Caddy before switching DNS. Today's production Caddy listens on HTTP behind CloudFront. [CloudFront certificate requirements](https://docs.aws.amazon.com/AmazonCloudFront/latest/DeveloperGuide/cnames-and-https-requirements.html) · [Existing deployment guide](AWS_STATELESS_EC2.md)

### What the budget buys

Include hosting, S3 storage and transfer, authentication, backups, logs,
embeddings, taxes and reserve under the combined S$30 ceiling. During a
pilot, include any AWS services still running. Populate the
[cost report](../../scripts/cost_report.py) from a billing export and the usage
ledger. A student turn can trigger several billable calls.

### Improvements in delivery order

1. **Measure the current stack first.** Record gross monthly costs before credits, peak simultaneous arrivals, billable tokens per saved answer and the proportion of Lecture help versus Project coaching. This shows whether a migration would save enough to justify maintaining a database.
2. **Bound model spend at the provider call.** Extend the [OpenAI adapter](../../backend/providers.py) and model registry with tested request/output limits. Reserve a worst-case allowance before dispatch, count retries and background calls, and release unused allowance on completion. Keep saved work readable if generation reaches its cap. Use anonymous fixture prompts to compare grounding, coaching quality and stage recommendations.
3. **Prove course retrieval before replacing the managed KB.** Virtual course entries need ingestion from the canonical PDFs. Compare top results and page citations for exact terms, paraphrases and unanswerable questions. Test that another student's files and unselected sources never appear. Keep the existing KB available for rollback. [Current RAG architecture](../RAG_ARCHITECTURE.md)
4. **Prove data recovery before moving students.** Add a PostgreSQL implementation behind the [existing persistence factory](../../backend/persistence/factory.py). On an isolated copy, verify IDs, ownership, transcript order, revisions, stage confirmations, file references and idempotent retries. Restore an off-host backup into a fresh instance. For cutover, pause writes, reconcile the final copy and validate it before reopening. If reverting after new writes, reconcile those writes before redirecting students to AWS.
5. **Rehearse the classroom peak.** Run the 80-submission burst on the candidate ARM host with representative files, slow model responses and a restart. Measure queue wait, time to first visible text, completion, duplicates and memory during ingestion. Agree an acceptable wait with the lecturer. The existing 80/80 rehearsal used four running slots and a 250 ms mock provider. A capped, explicitly approved provider test is still needed to establish real throughput. [Classroom capacity gate](../operations/CLASSROOM_CAPACITY_GATE.md)

Obtain one gross AWS billing export and confirm permitted processing and
backup regions. Retain AWS if the current stack meets the budget and classroom
gate. See [readiness decisions](../operations/CLASSROOM_READINESS_DECISIONS.md)
for backup, capacity, and pilot evidence.
