# Documentation

Start with the [local setup](../README.md). Use the map below to find the guide
for the change or operational decision you are making.

| Area | Guides |
| --- | --- |
| Architecture | [Application and workflow](LOCAL_DEMO_IMPLEMENTATION.md), [code map](CODEBASE_STRUCTURE.md), [database](DATABASE.md), [RAG](RAG_ARCHITECTURE.md), [prompts](PROMPT_ARCHITECTURE.md) |
| Security | [Identity, guest access, and course material publication](SECURITY_BOUNDARIES.md) |
| Deploy | [AWS runbook](deploy/AWS_STATELESS_EC2.md), [release checklist](PRODUCTION_RELEASE_CHECKLIST.md), [manual QA](MANUAL_PRODUCTION_QA.md), [required course KB filters](KB_REQUIRED_MODE_RUNBOOK.md) |
| Providers | [AgentCore Runtime](providers/AGENTCORE_ADAPTER.md), [direct Bedrock](providers/BEDROCK_ADAPTER.md) |
| Classroom | [Capacity and recovery](operations/CLASSROOM_CAPACITY_GATE.md), [readiness and pilot gates](operations/CLASSROOM_READINESS_DECISIONS.md), [hosting and two modules](deploy/HOSTING_PLAN.md) |
| Operations | [Cost accounting](COST_ACCOUNTING.md), [generation admission](GENERATION_ADMISSION.md), [load probe](operations/LOAD_PROBE.md), [research reset](operations/RESEARCH_DATA_RESET.md), [retrieval evaluation](RETRIEVAL_EVAL.md) |
| Contribute | [Current status](IMPLEMENTATION_STATUS.md), [issues and contribution workflow](CONTRIBUTING.md), [testing](TESTING.md) |
| Product and design | [Product brief](../PRODUCT.md), [glossary](../GLOSSARY.md), [React design](../frontend/DESIGN.md), [Streamlit design](../DESIGN.md) |
| Study | [Learning handbook](learning/README.md), [learning measures and research coding](LEARNING_BASELINE.md) |

`examples/` contains synthetic cost inputs and mock capacity results. The
system presentation is an overview for course stakeholders. The learning
handbook and generated reference are teaching aids with a dated baseline.
