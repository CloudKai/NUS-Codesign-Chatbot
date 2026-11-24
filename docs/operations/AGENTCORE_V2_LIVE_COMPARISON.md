# AgentCore V2 live comparison

24 November 2026 SGT. Production moved from AgentCore platform V1, deployment 38, to platform V2, deployment 39, using the same Oregon direct-code artifact, Gemma 4 31B Fast Chat, and Sonnet 4.6 Deep Review configuration. V2 uses consumption pricing and a 30-minute session idle timeout. Production readiness passed after updating the session generation. Deployment 38 is READY on the existing `GemmaStable37` rollback alias, which was advanced to version 38 because the account had reached its endpoint quota. `HaikuRollback36` remains available. [Deployment runbook](../deploy/AWS_STATELESS_EC2.md#publish-an-agentcore-runtime-version) · [Release rollback](../PRODUCTION_RELEASE_CHECKLIST.md#11-rollback)

After the comparison, the user chose to restore V1. Production now routes
through `GemmaStable37` to deployment 38 with a fresh session generation.
The host readiness check, production health endpoint, and public workspace
load passed. [Current deployment status](../IMPLEMENTATION_STATUS.md#agentcore-platform-v1-restored-in-production-2026-11-24-sgt)

## Browser measurements

Each platform served eight new synthetic Guest notebooks with simultaneous Design Coaching submissions, then eight matched warm follow-ups. Both used the same four first-turn/follow-up prompt pairs. Chromium measured from form submission to the first visible reply text in the DOM and to the reconciled saved reply. The preview appeared on all 32 turns. With eight observations in each cell, nearest-rank p95 equals the maximum. Measurements are paired by prompt and test shape across two separate waves.

| Browser measurement | V1 median | V2 median | V1 p95 | V2 p95 |
| --- | ---: | ---: | ---: | ---: |
| Cold first visible reply | 11.36 s | 9.63 s | 12.85 s | 33.99 s |
| Warm first visible reply | 4.41 s | 4.24 s | 4.99 s | 5.83 s |
| Cold saved reply | 17.30 s | 14.91 s | 19.33 s | 39.63 s |
| Warm saved reply | 10.09 s | 10.98 s | 12.05 s | 11.60 s |

All 16 V2 model-backed turns saved, with one generation cycle per turn. The slowest V2 invocation took about 27.67 s from inside the runtime to first reply text. AWS reported a maximum 1.76 s of platform overhead across the 16 invocations. These timings place most of the outlier after platform startup without dividing that internal time among model queueing, guardrails, and inference. The proposed two-second cold p95 improvement did not pass in this small comparison. The classroom gate still needs 80 actual concurrent generations. [AWS platform metric](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/observability-runtime-metrics.html) · [Prior direct Gemma results](GEMMA_LATENCY_RESEARCH.md#measured-on-2026-11-24)

## Validation and cost scope

The signed control-plane request confirmed platform V2 before cutover. The guarded synthetic citation smoke passed before production switched. A PDF uploaded through the public reader attachment endpoint returned both expected facts, a citation scoped to that file, and a matching saved receipt. The test PDF and its notebook were removed through the public reader routes. The browser comparison used disposable Guest identities and generated synthetic notebooks. The first PDF setup attempt made no generation call because it used a route unavailable at the public edge.

Validation passed 112 focused tests and the applicable backend, HTTP, persistence, architecture, and deployment suite with 2,482 passed and one skipped. The live evaluation used 54 chat turns against a 60-turn, US$1 test allowance, including the preliminary Lecture Help measurements. The preliminary set included application responses without model generation and was excluded from the matched Design Coaching comparison. V2's 16 matched turns recorded 116,984 input and 2,875 output tokens, estimated at **US$0.0175 in Gemma tokens** using Oregon Standard list rates. Runtime, guardrails, and the rest of the AWS bill are additional. [Bedrock pricing](https://aws.amazon.com/bedrock/pricing/) · [Two-class cost assumptions](AGENTCORE_V2_TWO_CLASS_VALUE.md#runtime-cost-at-80-students-per-class)

## Metered memory and two-class estimate

The 11 complete, one-minute `DEFAULT` CloudWatch buckets from 12:56 to 13:07 SGT contained 2.86708 GB-hours and 0.07003 vCPU-hours. An earlier V1 test session was still idle on that endpoint. Subtracting its estimated steady usage from the median of four pre-pilot minutes gives **2.62280 GB-hours over about 97 V2 session-minutes**, or **1.62 GB per session**. The eight browser sessions were metered throughout that window, and the PDF session joined in the third minute. The last five idle minutes averaged **1.45 GB** after the same adjustment. Each included bucket had the full set of expected usage samples. Session counts and the legacy-session subtraction make this an endpoint telemetry estimate. The sample covers the early active and idle period of the pilot; memory was still falling and the full 30-minute idle tail falls outside the calculation. [AWS metric dimensions and reporting delay](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/observability-runtime-metrics.html)

At **1.62 GB**, AgentCore V2 projects to about **S$6.15 for two 80-student classes** with one hour of session life per student, or **S$9.00** with 90-minute sessions. The projection uses the earlier one minute of active vCPU per session and US$1 = S$1.30 budgeting assumptions. The one-hour V1 reference using the prior 1.22 GB observation was S$2.71. At five Design Coaching turns per student per class, the tested Gemma token mix would add about S$1.14 per month. These estimates precede hosting, database, retrieval, guardrails, storage, observability, tax, and reconciliation to the AWS bill. [AgentCore pricing](https://aws.amazon.com/bedrock/agentcore/pricing/) · [Full cost accounting](../COST_ACCOUNTING.md#supply-a-complete-sgd-inventory)

The test supports a faster typical cold reply and higher projected runtime spend. It did not demonstrate a better slow tail or an 80-student capacity pass. The next latency investigation should separate guardrail time and the model call from the remaining in-runtime wait. [Classroom capacity gate](CLASSROOM_CAPACITY_GATE.md)
