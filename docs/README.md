# Documentation

Start with the [local setup](../README.md) to run the app offline.

## Understand the system

- [Architecture and package ownership](LOCAL_DEMO_IMPLEMENTATION.md)
- [Database and migrations](DATABASE.md)
- [Identity, guest access, and course material security](SECURITY_BOUNDARIES.md)
- [Retrieval and citations](RAG_ARCHITECTURE.md) and [prompt architecture](PROMPT_ARCHITECTURE.md)
- [Product brief](../PRODUCT.md), [glossary](../GLOSSARY.md), [React design](../frontend/DESIGN.md), and [Streamlit design](../DESIGN.md)

## Develop and test

- [Contribution and issue workflow](CONTRIBUTING.md) and [implementation status](IMPLEMENTATION_STATUS.md)
- [Testing and mock load probes](TESTING.md)
- [Retrieval evaluation](RETRIEVAL_EVAL.md)

## Deploy

- [AWS deployment runbook](deploy/AWS_STATELESS_EC2.md)
- [AWS architecture proposal](deploy/AWS_ARCHITECTURE_PROPOSAL.md) (single self-healing app tier, templates in `infra/aws/`)
- [Production release checklist](PRODUCTION_RELEASE_CHECKLIST.md)
- [Model providers](providers/MODEL_PROVIDERS.md)
- [Required course Knowledge Base filters](KB_REQUIRED_MODE_RUNBOOK.md)

## Run the classroom

- [Capacity and recovery rehearsal](operations/CLASSROOM_CAPACITY_GATE.md)
- [Readiness decisions, post-credit hosting, and a second module](operations/CLASSROOM_READINESS_DECISIONS.md)
- [Cost accounting](COST_ACCOUNTING.md) and [generation admission](GENERATION_ADMISSION.md)
- [Research data reset](operations/RESEARCH_DATA_RESET.md)

## Study

- [Learning handbook](learning/README.md) and [code-derived reference generator](learning/README.md#generate-the-code-derived-reference)
- [Learning measures and research coding](LEARNING_BASELINE.md)
- [Stakeholder system overview (PowerPoint)](CDE2300_Design_Thinking_Companion_System_Documentation.pptx)
