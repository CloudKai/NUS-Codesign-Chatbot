# AgentCore Runtime V2 for two classes per month

Reviewed 24 November 2026 SGT for up to 80 students per class and at most two classes per month.

V2 is worth a bounded pilot if fresh-session startup is a noticeable part of the student wait. At the same 1.22 GB effective memory as the current observation, two full classes would cost about **S$4.73/month on V2 consumption**, versus **S$2.71/month at V1 rates**. V2 would match that V1 estimate at about **0.64 GB** effective memory and cost **S$2.20/month** at 0.50 GB. These figures cover AgentCore Runtime CPU and memory for the modeled classes. [AWS pricing](https://aws.amazon.com/bedrock/agentcore/pricing/).

## Current Runtime evidence

The seven-day CloudWatch lookback ending 24 November SGT left out at least the latest hour for publication lag. Oregon's `DEFAULT` endpoint recorded **6.994245975 GB-hours** across six hourly buckets, **0.07301446 vCPU-hours** and **12 new sessions**. Account memory matched the endpoint total. The five hourly buckets with both memory and the account active-session gauge held **6.988989486 GB-hours** over **345 session-minutes**, giving **1.21548 GB** effective memory. The 24 November 01:00 SGT memory bucket lacked a gauge denominator and was excluded from the ratio. This is a matched-window telemetry estimate. The new-session counter counts starts and cannot supply session duration. [AWS Runtime metrics](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/observability-runtime-metrics.html).

The control-plane read reported a **1,800-second idle timeout** and deployment version **38**. The `platformVersion` query returned `null`, so the deployed microVM platform is unconfirmed. AWS lists V2 as the default for new Oregon runtimes and documents the platform and deployment versions as separate fields. The cost model uses V1 rates as its comparison baseline. [AWS Oregon default announcement](https://aws.amazon.com/about-aws/whats-new/2026/11/new-agentcore-runtime-default/) · [Runtime platform versions](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/runtime-how-it-works.html) · [GetAgentRuntime](https://docs.aws.amazon.com/bedrock-agentcore-control/latest/APIReference/API_GetAgentRuntime.html).

## Runtime cost at 80 students per class

The model assumes one Runtime session per student per class, 60 vCPU-seconds per session, one hour of total session life including idle, and a budgeting conversion of US$1 = S$1.30. The stress case holds CPU work constant and extends session life to 90 minutes, as if every session began at the start of a one-hour class, received its last request at the end and then used the full 30-minute idle timeout. Repeat sessions and activity outside the modeled classes would add usage.

AWS's public microVM table lists V1 at **US$0.0895/vCPU-hour and US$0.00945/GB-hour** and V2 consumption at **US$0.1276/vCPU-hour and US$0.0169/GB-hour**. The estimate assumes pure consumption with no committed resource configuration. AWS describes automatic V2 reclamation of unused memory after 120 seconds, and the 0.50 GB row is a sensitivity for that behavior. Actual V2 memory for this workload remains unmeasured. [AWS pricing](https://aws.amazon.com/bedrock/agentcore/pricing/) · [Resource configurations](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/runtime-how-it-works.html).

| Pricing and effective memory | 60 min, one class | 60 min, two classes | 90 min, one class | 90 min, two classes |
| --- | ---: | ---: | ---: | ---: |
| V1 reference, 1.22 GB | S$1.35 | S$2.71 | S$1.95 | S$3.91 |
| V2 consumption, 1.22 GB | S$2.37 | S$4.73 | S$3.44 | S$6.88 |
| V2 consumption, 0.50 GB | S$1.10 | S$2.20 | S$1.54 | S$3.08 |

The formula is `sessions × 1.30 × (60/3600 × CPU rate + session hours × effective GB × memory rate)`. At one hour, the higher V2 CPU charge brings its break-even memory to **0.645 GB**, about **47% lower** than the 1.22 GB reference. At 90 minutes it is about **0.657 GB** if CPU time stays fixed.

At 1.22 GB, V2 uses about **16%** of the S$30 monthly ceiling in the one-hour scenario and **23%** at 90 minutes, leaving **S$25.27** and **S$23.12** respectively for other costs and positive budget headroom. Bedrock model and guardrail calls, retrieval and ingestion, hosting, storage, backups, observability, network, taxes and any costs of preparing a test deployment sit outside these figures. The classroom budget decision needs the full recurring inventory. [Full cost accounting](../COST_ACCOUNTING.md#supply-a-complete-sgd-inventory) · [Cash-funded release gate](CLASSROOM_CAPACITY_GATE.md#complete-recurring-cost-and-decision-record).

## What students could gain

V2 restores an initialized environment from a snapshot. AWS reported p75 platform cold starts of **1.9–2.0 seconds** on 200 MB to 2 GB images, compared with **5.4–30 seconds** on V1. The classroom benefit would be a faster first visible reply for students opening a fresh session together. The direct 80-call Gemma run already had a **32.319-second p95 completion** without AgentCore in the path, so model latency remains a separate contributor. [AWS V2 benchmark](https://aws.amazon.com/about-aws/whats-new/2026/09/new-agentcore-runtime-generally-available/) · [Gemma measurements](GEMMA_LATENCY_RESEARCH.md#measured-on-2026-11-24).

For a separately authorized comparison, confirm both platforms and use the same container, prompts, model, Region, guardrails, retrieval and streaming path. Start with 20 synthetic students using a mix of prompts, each with a cold first turn and a natural warm follow-up. Then compare full 80-student waves if the initial run is healthy and the capped allowance covers both. Measure p95 from browser submission to the first visible answer words for cold turns. Track warm timing, application queue and model timing, saved completions, errors, and CPU/memory meters alongside it. A proposed pilot target is **at least 2 seconds faster at cold p95**, with no degradation in successful saved replies or warm p95. The operator should agree on that target before the run. Let sessions end naturally or clean up test sessions at the end, without no-op keepalive calls that extend billable time. [Runtime latency and usage metrics](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/observability-runtime-metrics.html) · [Classroom test scope](CLASSROOM_CAPACITY_GATE.md#gates-still-requiring-evidence).
