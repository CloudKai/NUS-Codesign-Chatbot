# Contributing

## Domain terms

Use the [glossary](../GLOSSARY.md) in code, issues, and tests. Read relevant
records in `docs/adr/` when they exist. Check the
[architecture](LOCAL_DEMO_IMPLEMENTATION.md) before proposing a new boundary.
Identify any conflicting decision and what would supersede it.

## GitHub issues

Use [CloudKai/NUS-Codesign-Chatbot](https://github.com/CloudKai/NUS-Codesign-Chatbot/issues)
for issue scope, state, and dependencies. Pass `--repo CloudKai/NUS-Codesign-Chatbot`
to `gh`. Use an approved draft with `gh issue create --body-file PATH` when
publication is authorized. Record the issue URL, apply the triage label, and
add blockers with `gh issue edit NUMBER --add-blocked-by BLOCKER`. Verify
publication and dependency links before closing out a drafting task.

## Triage labels

| Canonical role | GitHub label | Meaning |
| --- | --- | --- |
| needs-triage | `needs-triage` | Maintainer evaluation needed |
| needs-info | `needs-info` | Required information missing |
| ready-for-agent | `ready-for-agent` | Specified work suitable for an agent |
| ready-for-human | `ready-for-human` | Human implementation needed |
| wontfix | `wontfix` | Will not be actioned |

Use the exact label names above. Start a ready ticket once its blockers are
complete. Update an issue or close it after checking current state and
documenting acceptance evidence.

## Ticket execution

Use one writer and a fresh `gpt-6.1-sol` session per approved ticket.
`gpt-6-luna` is the read-only discovery role and `gpt-6-astra` handles concrete
blockers. The client selects the model. Follow the [root guide](../AGENTS.md)
for delegation, cost limits and Git permissions.

1. Read the issue, current status, glossary and relevant package guide.
2. Inspect Git status. Use deterministic providers and disposable data.
3. Implement the ticket and verify focused tests and the applicable handoff
   checks. Use the [testing guide](TESTING.md) for the validation sequence.
4. Capture behavior, commands and evidence, compatibility, rollback, and
   outstanding work in [implementation status](IMPLEMENTATION_STATUS.md).
   Attach detailed acceptance evidence to the issue when authorized.
5. End the session. Start the next approved, unblocked ticket with a fresh
   client session.

## Published tickets

The user-approved architecture-completion programme is tracked locally in the
[53-ticket execution pack](../.scratch/architecture-completion/README.md), with
one file per ticket and explicit blocking edges. Its numbers are local to that
pack and are not GitHub issue numbers or the earlier rollout's ticket numbers.
The approved testing seams and TDD execution contract are recorded with the
pack. Use the existing implementation status as the evidence ledger; start
ticket 01 first, then only tickets whose blockers have acceptance evidence.
No new GitHub issue or parent-issue change is implied by local publication.

The initial rollout mapped local tickets 01–16 to GitHub issues #14–#29.
Use current GitHub state when planning work.

| Local ticket | GitHub issue | Blocked by GitHub issues |
| --- | --- | --- |
| 01 | [#14: Reliable turn completion and bounded graph memory](https://github.com/CloudKai/NUS-Codesign-Chatbot/issues/14) | None |
| 02 | [#15: Direct lecture help with optional project application](https://github.com/CloudKai/NUS-Codesign-Chatbot/issues/15) | None |
| 03 | [#16: Confirmed advancement and free stage revisits](https://github.com/CloudKai/NUS-Codesign-Chatbot/issues/16) | None |
| 04 | [#17: Resume project work with a useful next action](https://github.com/CloudKai/NUS-Codesign-Chatbot/issues/17) | [#16](https://github.com/CloudKai/NUS-Codesign-Chatbot/issues/16) |
| 05 | [#18: Safe Guest entry for classroom arrivals](https://github.com/CloudKai/NUS-Codesign-Chatbot/issues/18) | None |
| 06 | [#19: Bounded uploads with independent cleanup](https://github.com/CloudKai/NUS-Codesign-Chatbot/issues/19) | None |
| 07 | [#20: Complete cost visibility before and after credits](https://github.com/CloudKai/NUS-Codesign-Chatbot/issues/20) | None |
| 08 | [#21: Budget-safe classroom generation admission](https://github.com/CloudKai/NUS-Codesign-Chatbot/issues/21) | [#14](https://github.com/CloudKai/NUS-Codesign-Chatbot/issues/14), [#20](https://github.com/CloudKai/NUS-Codesign-Chatbot/issues/20) |
| 09 | [#22: Learning funnel and formative usability baseline](https://github.com/CloudKai/NUS-Codesign-Chatbot/issues/22) | [#15](https://github.com/CloudKai/NUS-Codesign-Chatbot/issues/15), [#17](https://github.com/CloudKai/NUS-Codesign-Chatbot/issues/17) |
| 10 | [#23: Authenticated React notebook reader](https://github.com/CloudKai/NUS-Codesign-Chatbot/issues/23) | [#22](https://github.com/CloudKai/NUS-Codesign-Chatbot/issues/22) |
| 11 | [#24: React lecture conversation and interrupted-turn recovery](https://github.com/CloudKai/NUS-Codesign-Chatbot/issues/24) | [#14](https://github.com/CloudKai/NUS-Codesign-Chatbot/issues/14), [#15](https://github.com/CloudKai/NUS-Codesign-Chatbot/issues/15), [#23](https://github.com/CloudKai/NUS-Codesign-Chatbot/issues/23) |
| 12 | [#25: React progression, revisits, and project resumption](https://github.com/CloudKai/NUS-Codesign-Chatbot/issues/25) | [#16](https://github.com/CloudKai/NUS-Codesign-Chatbot/issues/16), [#17](https://github.com/CloudKai/NUS-Codesign-Chatbot/issues/17), [#24](https://github.com/CloudKai/NUS-Codesign-Chatbot/issues/24) |
| 13 | [#26: React source management without draft loss](https://github.com/CloudKai/NUS-Codesign-Chatbot/issues/26) | [#19](https://github.com/CloudKai/NUS-Codesign-Chatbot/issues/19), [#24](https://github.com/CloudKai/NUS-Codesign-Chatbot/issues/24) |
| 14 | [#27: React workspace and preference parity](https://github.com/CloudKai/NUS-Codesign-Chatbot/issues/27) | [#23](https://github.com/CloudKai/NUS-Codesign-Chatbot/issues/23) |
| 15 | [#28: Classroom capacity and sustainable-cost gate](https://github.com/CloudKai/NUS-Codesign-Chatbot/issues/28) | [#18](https://github.com/CloudKai/NUS-Codesign-Chatbot/issues/18), [#19](https://github.com/CloudKai/NUS-Codesign-Chatbot/issues/19), [#21](https://github.com/CloudKai/NUS-Codesign-Chatbot/issues/21) |
| 16 | [#29: React comparison and reversible release candidate](https://github.com/CloudKai/NUS-Codesign-Chatbot/issues/29) | [#22](https://github.com/CloudKai/NUS-Codesign-Chatbot/issues/22), [#25](https://github.com/CloudKai/NUS-Codesign-Chatbot/issues/25), [#26](https://github.com/CloudKai/NUS-Codesign-Chatbot/issues/26), [#27](https://github.com/CloudKai/NUS-Codesign-Chatbot/issues/27), [#28](https://github.com/CloudKai/NUS-Codesign-Chatbot/issues/28) |

## Branch protection

Require pull requests and the Mock CI `mock-suite` status check before merging
to the production branch. Restrict force pushes and deletion, and require
administrators to satisfy the same checks during cutover. Use the
[release checklist](PRODUCTION_RELEASE_CHECKLIST.md) for live AWS validation.
