# Improve my design replaces Lecture help

**Status:** Product direction agreed on 27 November 2026 SGT. Test boundaries
and ticket breakdown proposed for approval. **Implemented and validated on
`improvement/architecture-responsiveness` (2026-11-27): backend suite 3443
passed, frontend suite 213 passed, generated client regenerated, prompt
baseline and route-inventory contracts updated, stack rebuilt and serving
`/improve/stream` with the `/lecture/stream` compatibility path.**

## Problem statement

Students who already have a design need feedback on a sketch, draft, or
prototype. The Lecture help entry point invites course questions, while Design
coaching guides a project through the five Thinking Path stages. Students need
a direct way to refine existing work and continue from what they already shared.

## Solution

Replace the student-facing Lecture help mode with **Improve my design**.
On Home, offer **Improve my design** with “Get feedback on a design you
already have” alongside **Start my design project**. Both modes use the
same saved conversation. Improve gives concrete feedback on the student's
current goal and design. Design coaching uses the Thinking Path and resumes
its saved stage when the student switches back. Resuming still re-checks the
saved stage's requirements (for example a workable How Might We in Problem
identification), but the coach has read the Improve conversation, so
requirements already met in substance can advance quickly through the normal
recommend-and-confirm flow. Improve turns never retroactively appear as stage
contributions — stage work is tagged at save time by mode — so students
re-share relevant work in a Design coaching turn to count it.

## User stories

1. As a student with a draft, I want to start in Improve from Home, so I can
   get feedback on the work I brought.
2. As a student starting a project, I want a clear Design coaching entry point,
   so I can work through the Thinking Path.
3. As a student who has already named a design and goal, I want the coach to
   respond directly, so I can act on the first reply.
4. As a student whose goal is still open, I want one focused question, so I can
   choose what to improve.
5. As a student with a document, sketch, or canvas selection, I want the coach
   to use it as context, so the feedback addresses the part I shared.
6. As a student switching modes, I want both modes to see the same conversation,
   so I can continue the discussion without explaining my design again.
7. As a student with saved project decisions, I want an Improve reply to leave
   them intact, so I can pick up the Thinking Path later.
8. As a student applying a course method, I want relevant readings cited, so I
   can check the coach's explanation.
9. As a student asking for practical feedback, I want the coach to help with
   what I shared, so an optional course lookup does not delay the reply.
10. As a returning student, I want the chat to reopen in the mode I used, so I
    can continue the same kind of work.
11. As a student in an older tab, I want to keep my draft and recover a pending
    send after the update, so I can finish the conversation.
12. As a student revising a message, I want it to use its original mode, so
    editing does not silently switch the kind of feedback I receive.
13. As a student reviewing Improve work, I want to see my stars and citations,
    so I can revisit feedback I chose to keep.
14. As a lecturer, I want historical Lecture help and new Improve turns reported
    separately, so usage trends retain their meaning.

## Implementation decisions

- Use the existing model and shared turn lifecycle. Introduce a short Improve
  instruction family with current-turn feedback, one useful question when
  needed, and the existing grounding and output rules. Keep Fast Chat's
  existing context budgets and history policy.
- Share active transcript messages, selected design material, and authorized
  sources. Student-authored stage references remain conversation content.
  Exclude app-owned stage prompts, stage-derived summaries, rubric, and stage
  identifiers from the Improve model payload, including AgentCore's runtime
  assembly. Retrieval relevance must also be independent of the saved stage.
- Keep stage state at the server for concurrency and Design coaching. An
  ordinary Improve send cannot create or resolve a stage recommendation, award
  completion, record stage assessment, or change Journey progress. Switching
  modes while a turn is being saved follows the existing send and recovery
  locks. A saved but undecided recommendation is available again in Design
  coaching.
- Reuse the first-pass evidence gate and source ownership checks. Define an
  explicit Improve policy. Ordinary design critique can proceed without course
  retrieval. Explicit course questions and eligible student-selected evidence
  use the scoped retrieval and citation path. Keep attachments, draft and
  canvas selections, streaming, reply detail, and existing language behavior.
- Store new turns using `improve_design` and use `improve` in the reader UI and
  preferences. Continue to read saved `lecture_help` classifications for
  historical analytics. Open a saved chat using a pending receipt first,
  followed by an explicit tab mode choice, then the latest saved student
  turn's intent. Normalize legacy Lecture help to Improve for reopening, with
  the existing inference as a fallback for unclassified history.
- Use the original saved mode for revision, mapping legacy Lecture help to
  Improve for the new response. Editing an earlier turn still supersedes later
  messages and can roll back their Thinking Path progress. Give the student
  that information before submission.
- Add `/improve/stream` and ship it with its updated callers and API contract.
  Keep a temporary old-route compatibility path for stale clients and existing
  request receipts. Preserve idempotency when recovering pre-cutover sends.
  Read old preference values and migrate tab draft keys and embedded intents
  without rewriting historical message rows.
- Show **My work** with stars and citations in Improve Review. Hide Thinking
  Path controls, incentives, scores, and stage-specific export in this mode.
  Keep the existing Design coaching Review available on switching back. The
  existing Project Brief continues to summarize the active shared conversation.
  Retain useful-answer receipts for Improve and count them under its own label.
- Update active student entry points, including the supported Streamlit student
  surface. Preserve the lecturer's ability to interpret old Lecture help
  analytics.

## Testing decisions

Proposed public boundaries for TDD, using disposable data and deterministic
providers:

1. **Authenticated reader HTTP API.** Exercise Improve streams, saved receipts,
   transcript reads and revisions, stage state, preferences, and analytics
   through the existing API fixtures. This covers durable behavior and owner
   scoping.
2. **Provider request and runtime prompt.** Capture the provider-bound request
   for the same student input at two different saved stages, including the
   final AgentCore system prompt. This verifies that stages cannot change the
   Improve context and that Design coaching still gets its stage prompt.
3. **Student browser flow.** Use the existing mock browser harness to start
   Improve on Home, send and recover a reply, switch modes, reopen the chat, and
   exercise Review at desktop and 390 px. This checks what students can
   actually see and do. Use the existing Streamlit smoke seam for its mode picker.

Follow the existing stream, retrieval, replay, prompt, and browser tests as
prior art. Check course citations, history across restart, and explicit stage
confirmation in the full handoff. Update the OpenAPI export and generated
client with the route change.

## Out of scope

- Context-window expansion, older-message recall, changes to memory packing,
  and model-wide prompt optimisation. Schedule these on a separate branch after
  this branch is complete. The Improve prompt itself is part of this feature.
- A generated “What we worked on” recap, its export, and decisions about
  recap scope for mixed conversations.
- Model replacement, live paid inference, deployment, and database migration.

## Further notes

See the [context research and follow-up evaluation cases](../operations/COACH_CONTEXT_RESEARCH.md).
Document the new mode in the prompt, retrieval, product and glossary guides
during implementation. Record validation, cutover compatibility, and rollback
in [implementation status](../IMPLEMENTATION_STATUS.md).
