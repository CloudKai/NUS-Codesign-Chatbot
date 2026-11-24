# Documentation

Start with the [local setup](../README.md) to run the app offline.

## Understand the system

- [Architecture and package ownership](LOCAL_DEMO_IMPLEMENTATION.md)
- [Database and migrations](DATABASE.md)
- [Identity, guest access, and course material security](SECURITY_BOUNDARIES.md)
- [Retrieval and citations](RAG_ARCHITECTURE.md) and [prompt architecture](PROMPT_ARCHITECTURE.md)
- [Product brief](../PRODUCT.md), [glossary](../GLOSSARY.md), [React design](../frontend/DESIGN.md), and [Streamlit design](../DESIGN.md)

## Develop and test

- Approved specs for [stage feedback in Summary](specs/STAGE_REVIEW_SUMMARY.md) and [starred messages](specs/STARRED_MESSAGES.md); [bookmark implementation evidence](specs/STARRED_MESSAGES_HANDOFF.md)
- [Contribution and issue workflow](CONTRIBUTING.md) and [implementation status](IMPLEMENTATION_STATUS.md)
- [Whole-chat project brief and clean Summary](specs/PROJECT_BRIEF_HANDOFF.md)
- [Normal/edited LLM reply streaming and AgentCore rollout](specs/REPLY_STREAMING_HANDOFF.md)
- [Testing and mock load probes](TESTING.md); [Review refinement evidence](specs/REVIEW_REFINEMENTS_HANDOFF.md)
- [Architecture audit, improvement milestones and baseline measurements](operations/ARCHITECTURE_IMPROVEMENTS.md)
- [Retrieval evaluation](RETRIEVAL_EVAL.md)

## Deploy

- [AWS deployment runbook](deploy/AWS_STATELESS_EC2.md)
- [AWS architecture proposal](deploy/AWS_ARCHITECTURE_PROPOSAL.md) (single self-healing app tier, templates in `infra/aws/`)
- [Production release checklist](PRODUCTION_RELEASE_CHECKLIST.md)
- [Model providers](providers/MODEL_PROVIDERS.md)
- [Required course Knowledge Base filters](KB_REQUIRED_MODE_RUNBOOK.md)

## Run the classroom

- [Capacity and recovery rehearsal](operations/CLASSROOM_CAPACITY_GATE.md)
- [Gemma latency research and benchmark plan](operations/GEMMA_LATENCY_RESEARCH.md)
- [AgentCore V2 cost and value for two classes](operations/AGENTCORE_V2_TWO_CLASS_VALUE.md)
- [AgentCore V2 live comparison and rollback](operations/AGENTCORE_V2_LIVE_COMPARISON.md)
- [Chat progress feedback and cold-start messaging research](operations/CHAT_PROGRESS_FEEDBACK_RESEARCH.md)
- [Frontend stack choices for chat feedback and data loading](operations/FRONTEND_STACK_RESEARCH.md)
- [Bedrock workshop, multimodal retrieval, and chatbot latency research](operations/BEDROCK_WORKSHOP_AND_CHATBOT_RESEARCH.md)
- [Readiness decisions, post-credit hosting, and a second module](operations/CLASSROOM_READINESS_DECISIONS.md)
- [Cost accounting](COST_ACCOUNTING.md) and [generation admission](GENERATION_ADMISSION.md)
- [Research data reset](operations/RESEARCH_DATA_RESET.md)

## Study

- [Learning handbook](learning/README.md) and [code-derived reference generator](learning/README.md#generate-the-code-derived-reference)
- [Learning measures and research coding](LEARNING_BASELINE.md)
- [Stakeholder system overview (PowerPoint)](CDE2300_Design_Thinking_Companion_System_Documentation.pptx)
