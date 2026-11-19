# Implementation status

## Current status

### Local workspace

React serves the student workspace at `/`, with `/pilot/` as an alias.
Lecturers and accounts with Enabled Access use `/streamlit/`. Students can
resume notebook conversations, move or pin chats, search their workspace,
and open Review without a generation call. Stage changes require explicit
confirmation. Notebook Sources control reusable evidence, and chat
attachments apply to the submitted turn unless added as a notebook source.
Past local work checked persistence, source and citation handling, and desktop
and mobile browser behavior. [Application architecture](LOCAL_DEMO_IMPLEMENTATION.md) ·
[React workspace](../frontend/README.md)

Private Library uploads use one stored original and derived text with
owner-scoped links. Existing uploads retain their storage anchors. If legacy
files need to survive deletion of their original conversation, plan and
verify a separate storage migration. [Library and citation behavior](RAG_ARCHITECTURE.md#library-files-and-notebook-sources)

### Classroom and release

| Gate | Evidence and next action |
| --- | --- |
| [#28 Classroom capacity and cost](https://github.com/CloudKai/NUS-Codesign-Chatbot/issues/28) | Open. The mock rehearsal completed three 80-submission waves after the SQLite waiter fix. Obtain the actual gross AWS bill and credit dates, permitted processing locations, and a lecturer-approved wait target. Then assess live throughput, restore evidence, and full operating cost. |
| [#29 React release](https://github.com/CloudKai/NUS-Codesign-Chatbot/issues/29) | Open and depends on the classroom gate. Record the participant comparison, accessibility and capability gaps, and demonstrate rollback against the same saved data. |
| Two course modules | Proposed. Start with module membership, owner scope, and corpus isolation before exposing the second route. The hosting plan covers the shared S$30 budget and overlapping 80- or 160-enrolment peaks. |

[Capacity evidence](operations/CLASSROOM_CAPACITY_GATE.md) ·
[Decision register and release checks](operations/CLASSROOM_READINESS_DECISIONS.md) ·
[Hosting plan](deploy/HOSTING_PLAN.md)

### Documentation consolidation

The root README now opens with the local mock workflow. The docs index points
to current architecture, AWS operations, classroom readiness, and contributing
guides. The security guide includes guest access and course-publication
decisions. The learning handbook includes all eight chapters on one page.
Documentation and the handbook PDF generator are the scope of this pass.

The React build, Python compilation and full mock suite passed via
`sh scripts/build.sh`. A disposable local stack served the React shell,
returned API readiness and created a guest session. The consolidated handbook
rendered as 41 pages with the codebase appendix. Local Markdown links and
heading anchors resolved.

The previous working-tree documents are backed up at
`/private/tmp/codesign-docs-before-tightening-2m_inlg6`. Application runtime
and deployment configuration were outside this phase. For the next technical
phase, use the classroom [decision register](operations/CLASSROOM_READINESS_DECISIONS.md#evidence-and-decision-register).

## Earlier evidence

The previous repository snapshot contains the original validation commands,
rollback notes, and full phase history.
[Implementation log at 948162e](https://github.com/CloudKai/NUS-Codesign-Chatbot/blob/948162e1eba9d0de3fbda7cbfce1d00731001158/docs/IMPLEMENTATION_STATUS.md) ·
[Original ticket handoffs](https://github.com/CloudKai/NUS-Codesign-Chatbot/tree/948162e1eba9d0de3fbda7cbfce1d00731001158/new_docs/ticket_handoffs) ·
[Streamlit design QA](https://github.com/CloudKai/NUS-Codesign-Chatbot/blob/948162e1eba9d0de3fbda7cbfce1d00731001158/design-qa.md)

For future phases, record the behavior change, validation evidence, compatibility,
rollback, and the next owner action here. Link to the relevant issue or guide
for detailed evidence.
