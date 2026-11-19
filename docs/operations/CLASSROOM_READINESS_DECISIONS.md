# Classroom readiness decisions and post-promotion options

Updated 2026-11-17, local #28 only. **Decision support prepared; release not
approved. #28 OPEN, #29 blocked.** No purchase, migration, provider switch, paid
call, recruitment message, publication or new commit is authorized by this sheet.

## Confirmed inputs and current evidence

The user reports the existing AWS promotion/trial ends during 2026; the exact
expiry date, balance and service restrictions remain unverified. Plan on ordinary
cash-funded operation after credits. The working budget remains **S$30/month for
hosting, generation and retrieval together**. The user is open to OpenAI and
other hosts, and confirms the project team can maintain a VPS. Singapore-only
residency is **not yet confirmed**. No host/model has been selected.

Local commit `9992bc46082fb3c0d7970aa4210779503fdbedb4` fixes the reproduced
SQLite queue failure; all310 normal submissions saved in the final rehearsal,
including three80-request waves. See the [continuation handoff](https://github.com/CloudKai/NUS-Codesign-Chatbot/blob/948162e1eba9d0de3fbda7cbfce1d00731001158/new_docs/ticket_handoffs/15-continuation.md).
That is mock HTTP engineering evidence, not live provider or rendered-client
capacity. The [capacity gate](CLASSROOM_CAPACITY_GATE.md),
[cost accounting](../COST_ACCOUNTING.md) and
[learning baseline](../LEARNING_BASELINE.md) remain the acceptance authorities.
The benchmark shortlist below records the 2026-11-17 options. The later
[Singapore hosting plan](../deploy/HOSTING_PLAN.md) covers
two modules, the custom domain, and the Luna/Sol and Haiku/Sonnet comparison.

## November 17 benchmark shortlist

**One small VPS, the existing Python application, durable state/files, an
explicitly validated course retriever, and direct OpenAI API calls.** Compare
GPT-5.4 nano with GPT-5.4 mini on the same educational cases; choose only after
quality, citations, structured assessments and budget behavior pass. GPT-5 nano
is a cheaper comparison candidate, with coaching quality unproven here.

This is a recommendation for a separately scoped benchmark, not a migration
approval or proof that80 students fit a particular server. Keeping the current
AWS system running temporarily requires counting its concurrent charges.

### Hosting shortlist: published prices checked 2026-11-17

Amounts below are USD/month unless marked EUR. These are building-block prices,
not complete SGD bills. No promotional grant offsets are assumed.

| Candidate | Verified building blocks | Assessment for this project |
| --- | --- | --- |
| DigitalOcean Basic VPS |2 GiB/1 vCPU/50 GiB: US$12. Weekly percentage-based VM backup adds20%: US$14.40 subtotal. [Compute](https://www.digitalocean.com/pricing/droplets), [backups](https://www.digitalocean.com/pricing/backups) | Leading fixed-price benchmark because the team can operate a VPS.2 GiB is an untested candidate, not a capacity floor. Application-consistent independent backups, auth, tax, transfer and other costs remain. Verify region/stock at selection. |
| Railway containers | Hobby US$5 minimum including first US$5 usage; RAM US$10/GB-month, CPU US$20/vCPU-month, volume US$0.15/GB-month, egress US$0.05/GB. [Plans](https://docs.railway.com/pricing/plans) | Alternative if managed deployment convenience outweighs variable billing. US$5 is not an always-on stack price. For an invented1 GiB average RAM +0.1 average vCPU +5 GiB disk +10 GiB egress, resource subtotal is US$13.25, including the minimum once; no capacity claim. Confirm plan suitability for institution use. |
| Render paid Python/container service |512 MB/<1 CPU US$7;2 GB/1 CPU US$25; disk US$0.25/GB-month. Workspace fees can be additional. [Pricing](https://render.com/pricing) | US$7 tier leaves little demonstrated memory margin for the combined app;2 GB compute alone uses most of this budget before AI. Default files are ephemeral, requiring a persistent disk or external state. [Disk constraints](https://render.com/docs/disks) |
| Hetzner | Current regional page has region-dependent EUR pricing. [Regional catalogue](https://www.hetzner.com/cloud/regular-performance/) | Secondary quote candidate only. Do not apply an EU headline to Singapore: the extracted location columns are insufficient for a firm selected-region quote. Confirm country, size, IPv4, tax, stock, traffic and backups before ranking. |

The measured390176KiB API process maximum excludes driver, Streamlit clients,
OS, ingestion spikes and a replacement index/database. It does not validate a
512 MB host or show the whole application fits within2 GiB under class load.

### OpenAI API comparison: USD per million tokens

Standard text rates from official model pages, checked 2026-11-17. No cache
savings, Batch discount or promotional credits are assumed in the arithmetic.

| Model | Input | Cached input | Output | Role in comparison |
| --- | ---: | ---: | ---: | --- |
| [GPT-5 nano](https://developers.openai.com/api/docs/models/gpt-5-nano) |0.05|0.005|0.40| Cheapest baseline; no established coaching quality. |
| [GPT-5.4 nano](https://developers.openai.com/api/docs/models/gpt-5.4-nano) |0.20|0.02|1.25| Budget-first evaluation candidate. |
| [GPT-5.4 mini](https://developers.openai.com/api/docs/models/gpt-5.4-mini) |0.75|0.075|4.50| Higher-cost comparison candidate; no automatic fallback selection. |

Regional processing endpoints for5.4 nano/mini have a documented10% price uplift;
confirm approved processing location before choosing rates. Model features and
prices do not establish educational suitability. Reasoning tokens are charged
as output; visible response length alone cannot bound spending.
[Reasoning and output limits](https://developers.openai.com/api/docs/guides/reasoning).

Illustrative workload: one call/turn,3,000 input and500 **total billable output**
tokens,80 students. These are hypothetical inputs, not measured monthly usage.

| Turns per student/month | Total calls | GPT-5 nano USD | GPT-5.4 nano USD | GPT-5.4 mini USD |
| --- | ---: | ---: | ---: | ---: |
|10|800|0.28|0.98|3.60|
|30|2,400|0.84|2.94|10.80|
|100|8,000|2.80|9.80|36.00|

Formula: calls × (input_tokens × input_rate + billable_output_tokens × output_rate)
/1,000,000. At16,000 input/2,000 total output per call,2,400 calls instead cost
US$3.84/13.68/50.40 respectively. Structured JSON, growing history, reasoning,
images, failures, retries, RAG recovery, Deep Review and checkpoints can change
both tokens and call counts. These scenarios are not conservative ceilings.

Example subtotal only: US$14.40 VPS/weekly VM backup +US$2.94 nano scenario =
**US$17.34/month before remaining costs**. At a purely hypothetical SGD/USD
conversion of1.35, that would be S$23.41. This is **not a current FX quote** and
leaves only S$6.59 for all missing costs and positive approved headroom. Use the
actual billed FX/tax basis; the example establishes no S$30 pass. Mini at the
same workload makes the subtotal US$25.20 before extras, requiring a different
funding/usage plan at that illustrative FX rate.

## Repository work required before any switch or paid evaluation

Read-only code/configuration findings, not implementation changes:

- `compose.prod.yaml` configures AgentCore/Bedrock, DSQL/S3 and a MANAGED course
  KB in us-west-2. Its normal/deep roles target Haiku4.5/Sonnet4.6. These are
  repository settings, not a verified live runtime version, account quota or bill.
- `backend/providers.py` already has an OpenAI Responses structured-output
  adapter. Its current request does **not set max_output_tokens**. Before a
  bounded paid evaluation, implement and test a hard total-output limit, prompt
  bound, explicit model mapping, unknown-usage reserve and finite retry behavior.
  `backend/models.py` currently lists only its existing application default;
  the shortlist models have not been added. AgentCore and direct OpenAI prompt
  paths differ; preservation of educational behavior needs evaluation.
- `backend/settings.py` production validation currently requires DSQL/S3.
  A VPS with local SQLite/files is not a safe production environment toggle.
  A generic PostgreSQL or alternative production storage profile needs its own
  tested adapter, explicit migration, backup and rollback decision.
- Existing local retrieval handles student source chunks. Virtual managed course
  sources lack local extracted text; disabling the KB does not provide working
  local course RAG. Import authorized course originals/page offsets/stable IDs and
  validate retrieval/citations before replacing it. No embedding model is selected.
- The local SQLite generation ledger is not a multi-host/DSQL admission adapter.
  Compose does not pin GENERATION_ADMISSION_POLICY; host configuration/durable
  ledger topology must be verified. Do not present mock limits as active production
  protection. Retained Cognito/S3/DSQL/KB/runtime services remain cost lines until
  deliberately retired after migration acceptance.

No infrastructure, storage, provider, prompt, schema or UI code is changed here.
Keep saved notebooks/sources/history/learning data, auth and Streamlit rollback.

## Evidence and decision register

Owner roles below are responsibilities to assign, not claims that a person has
accepted them. Every approval needs name/date/evidence reference in private records.

| Gate | Prepared now | Required input / owner | Pass evidence still needed |
| --- | --- | --- | --- |
| Classroom wait | Measurement boundaries below; final mock results linked | Lecturer: maximum queue and total wait, percentile vs hard limit, help/retry expectation | Approved numbers and intended-topology measurements against them. |
| Real capacity | Official quota sources and configured topology identified | Operator: chosen AWS profile or replacement provider project, region/model/runtime version/KB, effective quotas and other workload | Dated effective quotas and complete call/token/retry envelope; capped live test only after explicit approval. |
| Sustainable costs | Current public list prices, scenarios and existing nine-category unknown inventory | Operator: current full bill, complete month usage, exact credit balance/expiry, billed FX/taxes, monthly workload; lecturer/funder: positive headroom and funding/usage choice | Evidenced post-credit recurring C + separately approved H>0 with C+H<=S$30, or explicit alternative funding/usage/postponement decision. |
| Off-host recovery | Correct topology-specific rehearsal sequence below | Operator: backup/recovery-point location, keys/roles, isolated target, retention, RPO/RTO and funded restore cap | Actual loss-of-active-store restore, byte/state/ledger verification and measured RPO/RTO. |
| Formative study | Existing task/observation protocol plus scheduling sheet below | Lecturer/research lead: authorized recruitment/consent/storage,5–8 participants, facilitator, dates | Actual completed observations and defect synthesis. Zero sessions so far. |
| Two-week pilot | Day-relative plan below | Research lead/operator: roster, approved interface, start/end dates, consent, funding and support owner | Two weeks of actual observations; counts retain denominator and identity limitations. Zero pilot sessions. |

AWS CLI is installed with two profiles; no default is explicitly selected. No
account identity, quotas, billing or resource access was attempted. A profile
selection and account-specific evidence remain pending. Existing billing exports
can be analyzed offline. Cost Explorer API queries have a per-request charge, so
they are not used without a separate cap.
[Cost Explorer pricing](https://aws.amazon.com/aws-cost-management/aws-cost-explorer/pricing/).

Queue measurement: dispatch → first queued → admission/thinking. Total answer
measurement: dispatch → durable done/recovered saved answer. Separately record
provider failure, wait expiry, capacity rejection, interrupted transport and
recovery.30-second limiter settings and the two-minute study stop convention
are not approved classroom targets. Approval fields: queue_seconds=unknown;
total_seconds=unknown; percentile/hard-bound=unknown; approver/date=unknown.

Public quota references are guidance, not account entitlement: runtime quotas
are region/account scoped; model token/request quotas also require the exact
model and inference route; retrieval has its own quotas. For example, the current
managed-KB defaults list600 Retrieve RPM with a25 RPS burst, which is **not proof**
that the user's KB/account has this capacity or that an80-arrival burst succeeds.
[AgentCore quotas](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/bedrock-agentcore-limits.html),
[Bedrock runtime quotas](https://docs.aws.amazon.com/bedrock/latest/userguide/quotas-runtime.html),
[managed KB quotas](https://docs.aws.amazon.com/bedrock/latest/userguide/kb-managed-quotas.html).
AgentCore runtime and model inference costs must be reconciled separately.
[Runtime pricing](https://aws.amazon.com/bedrock/agentcore/pricing/).

## Off-host rehearsal prepared, not executed

1. Confirm the actual durable topology and approve retention, RPO/RTO, target and
   charge cap. Inventory transcripts/auth/project/source metadata, original/derived
   file bytes, policy/ledger, deployment configuration and key/role access. Do not
   put secret values, source content or private resource identifiers in this repo.
2. For current DSQL/S3, use a coordinated recovery point for DB and file versions.
   AWS documents full DSQL backups through AWS Backup and restoration into a **new
   cluster**. A SQLite backup or generic Aurora MySQL PITR recipe is not equivalent.
   [DSQL backup](https://docs.aws.amazon.com/aurora-dsql/latest/userguide/backup-aurora-dsql.html),
   [restore requirements](https://docs.aws.amazon.com/aws-backup/latest/devguide/restore-auroradsql.html).
   Plan S3 recovery and application-consistent file/DB mapping separately.
3. For a future SQLite/local-files host, stop every writer, use SQLite backup APIs,
   copy matching files/policy/ledger into an independent off-host destination, and
   restore to an isolated host with the active originals unavailable. Reuse the
   canonical snapshot checks from the classroom probe; do not touch the live store.
4. With generation disabled, verify owner isolation, transcript/export hashes,
   exact source/citation bytes, project/progression and auth records. Reconcile
   post-backup paid usage before enabling generation; a stale ledger cannot safely
   restore spent funding. Test recovery after a second restart.
5. Record actual elapsed restore time and backup age, failures and repair steps.
   Keep originals and rollback intact. No cloud restore/backup, object download,
   resource creation/deletion or data migration was executed by this planning work.

## Study and pilot materials ready for a facilitator

Use the existing [task script and observation sheet](../LEARNING_BASELINE.md#reproducible-comparison-session)
with synthetic analogy notes, older-pedestrian framing, exact build SHA, same
fixture/device/network conditions, desktop1440×960/mobile390×844. The research
lead confirms consent/approved storage before collecting actual observations.
Roster identities and private observations stay outside this repository.

| Planned slot | Participant identity / consent | First interface and device | Dates / facilitator | Result |
| --- | --- | --- | --- | --- |
|P01/P03/P05/P07|Unassigned|Counterbalance plan A: Streamlit then React; desktop then mobile|Unscheduled|Unobserved|
|P02/P04/P06/P08|Unassigned|Counterbalance plan B: React then Streamlit; mobile then desktop|Unscheduled|Unobserved|

Recruit5–8 across lecture-only, project starters, returning and mobile/accessibility
needs; the rows are scheduling slots, not a consented roster. Log order effects,
hints, stalls, citation return, draft loss and optional usefulness judgments.
If a mock recommendation is not elicited, record that and use the established
pre-seeded control fixture; do not fabricate pedagogical success. Preserve #27
capability gaps; an interface comparison does not authorize a default switch.

Two-week pilot schedule, all **proposed/unscheduled**:

| Period | Operator / facilitator actions | Evidence |
| --- | --- | --- |
|Before day1|Approve roster/consent/interface, funding, max waits and support; capture code/fixture/version and baseline aggregates|Dated signed-off plan; no invented start date|
|Days1–3|Observe entry, first lecture help, citation access and recovery; record every support intervention|Task observations and incidents, including non-completion|
|Days4–10|Observe voluntary return/project contributions; review failures and actual costs; freeze unrecorded experimental changes|Separately defined denominators, optional usefulness, incident and spend records|
|Days11–14|Repeat representative tasks/interviews, inspect actual returns and authorized reasoning samples|De-identified findings, unresolved defects and missing observations|
|After day14|Reconcile full recurring costs; lecturer assesses observed waits/usefulness and remaining gates|Explicit continue/change/postpone decision, with limitations|

Saved-answer/owner/stage counts are proxies, not people, useful learning or a
consented two-week cohort. Recruitment, consent, attendance, interviews and
participant feedback cannot be supplied by mock tests. No invitations sent;
zero formative or pilot sessions completed. The existing learning baseline is
reused, not replaced by a new study or analytics implementation.

## Next exact action

Confirm data-location requirements and the current bill/credit expiry; then scope
one disposable VPS/model compatibility benchmark with explicit token/output and
cost limits. No purchase or paid evaluation approval is inferred from willingness
to use OpenAI. Obtain the lecturer's wait limits and schedule actual participants
in parallel through the responsible humans. Keep #28 open/#29 blocked, publication
LOCAL, and the current system/data intact until a separately approved migration.

## Pilot and release acceptance

- Desktop and 390 px mobile: no lost drafts, focus loss, composer obstruction,
  accidental scroll jumps, or broken citation return. Check keyboard navigation,
  status announcements, zoom, light/dark themes, and the browser console.
- Proposed interaction targets from the prior report: pending feedback p95 within
  100 ms; warm local navigation p95 within 300 ms; event-to-preview render p95
  within 100 ms. These are engineering targets, not observed production results.
- Compare the React pilot and current Streamlit baseline with the same device,
  fixture, mock delays, and cold/warm conditions. Use at least 30 repetitions per
  measured scenario. Adoption requires feature parity and either at least a 30%
  improvement in an interaction missing its target or removal of a reproducible
  critical interaction defect. Do not infer model latency improvements from UI tests.
- Run stepped load tests ending with 80 sessions and an 80-submission burst.
  Require no lost or duplicated accepted turns, no ownership leaks, bounded
  resource growth, and truthful overload outcomes. Publish observed p50/p95 waits
  and completions. Final classroom readiness requires an agreed maximum wait and
  provider capacity evidence; mocks alone do not establish live capacity.
- Run focused regressions during implementation and the full applicable mock
  suite at phase boundaries. Verify real local startup and browser journeys.
  Live model evaluations require separate explicit approval with a request/token
  or cost cap; historical approvals are not reused.
- Before a default-interface switch, demonstrate rollback to Streamlit against
  the same saved data. Before a cash-funded deployment, verify the complete budget
  and off-host recovery plan. Any later storage migration is separately scoped.
